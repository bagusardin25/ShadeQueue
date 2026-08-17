"""PostGIS candidate assembly.

One indexed query turns "a completed heat job plus an AOI" into the candidate
stop list the scorer consumes. `ST_Intersects` is the primary join; a documented
nearest-cell fallback covers stops that fall in a gap of the heat surface
(plan section 8).
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.scoring import CandidateStop, HeatJoinMethod

#: A stop further than this from every heat cell is treated as uncovered rather
#: than borrowing a distant value. 0.01 degrees is roughly 1.1 km here.
NEAREST_CELL_MAX_DEGREES = 0.01

_CANDIDATE_SQL = text(
    """
WITH aoi AS (
    SELECT ST_SetSRID(ST_GeomFromGeoJSON(CAST(:aoi_geojson AS text)), 4326) AS geom
),
candidates AS (
    SELECT bs.stop_id,
           bs.location_name,
           bs.shelter_count,
           bs.ridership_value,
           bs.geom
    FROM bus_stops bs, aoi
    WHERE ST_Intersects(bs.geom, aoi.geom)
)
SELECT c.stop_id,
       c.location_name,
       c.shelter_count,
       c.ridership_value,
       ST_X(c.geom) AS longitude,
       ST_Y(c.geom) AS latitude,
       intersecting.metric_value AS intersect_value,
       nearest.metric_value      AS nearest_value,
       nearest.distance_degrees  AS nearest_distance,
       tract.overall_percentile  AS svi_percentile,
       tract.geoid               AS svi_geoid
FROM candidates c
-- Overlapping cells are possible, so the strongest exposure wins and the
-- choice is recorded rather than left to row order.
LEFT JOIN LATERAL (
    SELECT MAX(hc.metric_value) AS metric_value
    FROM heat_cells hc
    WHERE hc.heat_job_id = :heat_job_id
      AND ST_Intersects(hc.geom, c.geom)
) AS intersecting ON TRUE
LEFT JOIN LATERAL (
    SELECT hc.metric_value,
           hc.geom <-> c.geom AS distance_degrees
    FROM heat_cells hc
    WHERE hc.heat_job_id = :heat_job_id
    ORDER BY hc.geom <-> c.geom
    LIMIT 1
) AS nearest ON intersecting.metric_value IS NULL
LEFT JOIN LATERAL (
    SELECT t.overall_percentile, t.geoid
    FROM svi_tracts t
    WHERE ST_Intersects(t.geom, c.geom)
    ORDER BY t.geoid
    LIMIT 1
) AS tract ON TRUE
ORDER BY c.stop_id
"""
)


async def load_candidates(
    session: AsyncSession,
    *,
    heat_job_id: Any,
    aoi_geojson: dict[str, Any],
) -> list[CandidateStop]:
    result = await session.execute(
        _CANDIDATE_SQL,
        {"aoi_geojson": json.dumps(aoi_geojson), "heat_job_id": str(heat_job_id)},
    )
    rows = result.mappings().all()

    candidates: list[CandidateStop] = []
    for row in rows:
        if row["intersect_value"] is not None:
            exceedance = float(row["intersect_value"])
            join_method = HeatJoinMethod.INTERSECTS
        elif (
            row["nearest_value"] is not None
            and row["nearest_distance"] is not None
            and float(row["nearest_distance"]) <= NEAREST_CELL_MAX_DEGREES
        ):
            exceedance = float(row["nearest_value"])
            join_method = HeatJoinMethod.NEAREST_CELL
        else:
            # No fabricated exposure: an uncovered stop scores zero and is
            # labelled, rather than silently inheriting a neighbour's value.
            exceedance = 0.0
            join_method = HeatJoinMethod.NONE

        svi_raw = row["svi_percentile"]
        candidates.append(
            CandidateStop(
                stop_id=row["stop_id"],
                location_name=row["location_name"],
                longitude=float(row["longitude"]),
                latitude=float(row["latitude"]),
                shelter_count=int(row["shelter_count"]),
                ridership_value=float(row["ridership_value"]),
                exceedance_hours=exceedance,
                svi_percentile=float(svi_raw) if svi_raw is not None else 0.0,
                heat_join_method=join_method,
                svi_covered=svi_raw is not None,
            )
        )
    return candidates


async def count_stops_in_aoi(session: AsyncSession, aoi_geojson: dict[str, Any]) -> int:
    result = await session.execute(
        text(
            """
            SELECT count(*)
            FROM bus_stops bs
            WHERE ST_Intersects(
                bs.geom,
                ST_SetSRID(ST_GeomFromGeoJSON(CAST(:aoi_geojson AS text)), 4326)
            )
            """
        ),
        {"aoi_geojson": json.dumps(aoi_geojson)},
    )
    return int(result.scalar_one())
