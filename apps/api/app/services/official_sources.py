"""Live City of Phoenix bus-stop and CDC SVI ingestion.

These snapshots are tagged LIVE. They replace DEMO_FIXTURE rows when a
production bootstrap succeeds. Fixtures remain the local/test default.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from shapely.geometry import MultiPolygon, Polygon, mapping, shape
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.aoi import ALLOWED_AOI_GEOJSON
from app.domain.runtime_mode import RuntimeMode
from app.services import snapshots

PHOENIX_LAYER_URL = (
    "https://maps.phoenix.gov/pub/rest/services/Public/BusStops/MapServer/0/query"
)
PHOENIX_LICENSE_NOTE = (
    "City of Phoenix Public/BusStops GIS (as-is). NBR_SHELTERS is missing for "
    "almost every stop and is stored as 0 (no recorded shelter), not as a "
    "field-verified amenity survey. RIDERSHIP is a source-provided value; its "
    "period and unit are unverified. Not a City endorsement."
)

SVI_QUERY_URLS = (
    "https://services3.arcgis.com/ZvidGQkLaDJxRSJ2/arcgis/rest/services/"
    "CDC_ATSDR_Social_Vulnerability_Index_2022_USA/FeatureServer/2/query",
    "https://onemap.cdc.gov/onemapservices/rest/services/SVI/"
    "CDC_ATSDR_Social_Vulnerability_Index_2022_USA/FeatureServer/2/query",
)
SVI_EDITION = "SVI 2022 US tract"
SVI_LICENSE_NOTE = (
    "CDC/ATSDR Social Vulnerability Index 2022, U.S. census tract layer. "
    "RPL_THEMES is a national percentile rank (0-1), not an Arizona-only rank. "
    "Public domain in the United States; cite CDC/ATSDR/GRASP. Suppressed "
    "values (-999) are dropped."
)
SVI_SUPPRESSED = -999

PAGE_SIZE = 1000
_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=10.0)
_USER_AGENT = "ShadeQueue/0.1 (hackathon demo; official-source ingest)"

_UPSERT_STOP = text(
    """
    INSERT INTO bus_stops (stop_id, location_name, shelter_count, ridership_value, geom, source_snapshot_id)
    VALUES (
        :stop_id, :location_name, :shelter_count, :ridership_value,
        ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326), :snapshot_id
    )
    ON CONFLICT (stop_id) DO UPDATE SET
        location_name = EXCLUDED.location_name,
        shelter_count = EXCLUDED.shelter_count,
        ridership_value = EXCLUDED.ridership_value,
        geom = EXCLUDED.geom,
        source_snapshot_id = EXCLUDED.source_snapshot_id
    """
)

_UPSERT_TRACT = text(
    """
    INSERT INTO svi_tracts (geoid, overall_percentile, geom, source_snapshot_id)
    VALUES (
        :geoid, :overall_percentile,
        ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(CAST(:geometry AS text)), 4326)),
        :snapshot_id
    )
    ON CONFLICT (geoid) DO UPDATE SET
        overall_percentile = EXCLUDED.overall_percentile,
        geom = EXCLUDED.geom,
        source_snapshot_id = EXCLUDED.source_snapshot_id
    """
)

_LIVE_COUNTS = text(
    """
    SELECT
        (SELECT COUNT(*) FROM bus_stops bs
           JOIN source_snapshots s ON s.id = bs.source_snapshot_id
          WHERE s.evidence_mode = 'LIVE') AS live_stops,
        (SELECT COUNT(*) FROM svi_tracts t
           JOIN source_snapshots s ON s.id = t.source_snapshot_id
          WHERE s.evidence_mode = 'LIVE') AS live_tracts
    """
)


def aoi_envelope() -> tuple[float, float, float, float]:
    ring = ALLOWED_AOI_GEOJSON["coordinates"][0]
    xs = [pt[0] for pt in ring]
    ys = [pt[1] for pt in ring]
    return min(xs), min(ys), max(xs), max(ys)


def _geometry_params() -> dict[str, str]:
    minx, miny, maxx, maxy = aoi_envelope()
    return {
        "geometry": f"{minx},{miny},{maxx},{maxy}",
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
    }


async def _get_geojson(client: httpx.AsyncClient, url: str, params: dict[str, str]) -> dict[str, Any]:
    response = await client.get(url, params=params)
    response.raise_for_status()
    document = response.json()
    if "error" in document:
        raise RuntimeError(f"ArcGIS error from {url}: {document['error']}")
    return document


def validate_phoenix_features(features: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    report = {
        "received": len(features),
        "missingStopId": 0,
        "missingGeometry": 0,
        "nullShelters": 0,
        "nullRidership": 0,
        "negativeRidership": 0,
        "duplicateStopId": 0,
    }
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []

    for feature in features:
        props = feature.get("properties") or feature.get("attributes") or {}
        geometry = feature.get("geometry") or {}
        coords = geometry.get("coordinates")
        if geometry.get("type") == "Point" and coords:
            lon, lat = float(coords[0]), float(coords[1])
        else:
            report["missingGeometry"] += 1
            continue

        stop_id = props.get("STOP_ID")
        if stop_id in (None, ""):
            report["missingStopId"] += 1
            continue
        stop_id = str(stop_id)
        if stop_id in seen:
            report["duplicateStopId"] += 1
            continue

        shelters = props.get("NBR_SHELTERS")
        if shelters is None:
            report["nullShelters"] += 1
            shelters = 0

        ridership = props.get("RIDERSHIP")
        if ridership is None:
            report["nullRidership"] += 1
            ridership = 0.0
        elif float(ridership) < 0:
            report["negativeRidership"] += 1
            ridership = 0.0

        name = (
            props.get("LOCATION")
            or props.get("LOCATION_NAME")
            or props.get("STOP_NAME")
            or f"Stop {stop_id}"
        )
        seen.add(stop_id)
        rows.append(
            {
                "stop_id": stop_id,
                "location_name": str(name),
                "shelter_count": max(0, int(shelters)),
                "ridership_value": max(0.0, float(ridership)),
                "longitude": lon,
                "latitude": lat,
            }
        )

    report["accepted"] = len(rows)
    return rows, report


def svi_rows_from_geojson(features: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    report = {
        "received": len(features),
        "suppressed": 0,
        "nullPercentile": 0,
        "outOfRange": 0,
        "missingGeometry": 0,
        "invalidGeometryRepaired": 0,
        "duplicateGeoid": 0,
        "nonArizona": 0,
    }
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []

    for feature in features:
        props = feature.get("properties") or feature.get("attributes") or {}
        geoid = props.get("FIPS") or props.get("GEOID") or props.get("GEOID20")
        if geoid in (None, ""):
            report["missingGeometry"] += 1
            continue
        geoid = str(geoid).strip()
        if not geoid.startswith("04"):
            report["nonArizona"] += 1
            continue
        if geoid in seen:
            report["duplicateGeoid"] += 1
            continue

        raw_geom = feature.get("geometry")
        if not raw_geom:
            report["missingGeometry"] += 1
            continue
        try:
            geometry = shape(raw_geom)
        except (TypeError, ValueError):
            report["missingGeometry"] += 1
            continue
        if geometry.is_empty:
            report["missingGeometry"] += 1
            continue
        if not geometry.is_valid:
            geometry = geometry.buffer(0)
            if geometry.is_empty or not geometry.is_valid:
                report["missingGeometry"] += 1
                continue
            report["invalidGeometryRepaired"] += 1
        if isinstance(geometry, Polygon):
            geometry = MultiPolygon([geometry])
        elif not isinstance(geometry, MultiPolygon):
            report["missingGeometry"] += 1
            continue
        geojson = mapping(geometry)

        value = props.get("RPL_THEMES")
        if value is None:
            report["nullPercentile"] += 1
            continue
        value = float(value)
        if value <= SVI_SUPPRESSED + 1:
            report["suppressed"] += 1
            continue
        if not 0.0 <= value <= 1.0:
            report["outOfRange"] += 1
            continue

        seen.add(geoid)
        rows.append(
            {
                "geoid": geoid,
                "overall_percentile": value,
                "geometry": json.dumps(geojson),
            }
        )

    report["accepted"] = len(rows)
    return rows, report


async def fetch_phoenix_features(*, clip_to_aoi: bool = True) -> tuple[list[dict[str, Any]], str]:
    params: dict[str, str] = {
        "where": "1=1",
        "outFields": "STOP_ID,LOCATION,NBR_SHELTERS,RIDERSHIP,NEXTRIDEID",
        "f": "geojson",
        "outSR": "4326",
        "resultRecordCount": str(PAGE_SIZE),
        "returnGeometry": "true",
    }
    if clip_to_aoi:
        params.update(_geometry_params())

    features: list[dict[str, Any]] = []
    offset = 0
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers={"user-agent": _USER_AGENT}) as client:
        while True:
            page = await _get_geojson(client, PHOENIX_LAYER_URL, {**params, "resultOffset": str(offset)})
            batch = page.get("features") or []
            features.extend(batch)
            if len(batch) < PAGE_SIZE:
                break
            offset += PAGE_SIZE
            if offset > 50_000:
                raise RuntimeError("Phoenix pagination guard tripped")
    return features, PHOENIX_LAYER_URL


async def fetch_svi_features() -> tuple[list[dict[str, Any]], str]:
    params = {
        "where": "1=1",
        "outFields": "ST,ST_ABBR,FIPS,LOCATION,RPL_THEMES",
        "f": "geojson",
        "outSR": "4326",
        "returnGeometry": "true",
        "resultRecordCount": str(PAGE_SIZE),
        **_geometry_params(),
    }
    errors: list[str] = []
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers={"user-agent": _USER_AGENT}) as client:
        for url in SVI_QUERY_URLS:
            try:
                features: list[dict[str, Any]] = []
                offset = 0
                while True:
                    page = await _get_geojson(client, url, {**params, "resultOffset": str(offset)})
                    batch = page.get("features") or []
                    features.extend(batch)
                    if len(batch) < PAGE_SIZE:
                        break
                    offset += PAGE_SIZE
                    if offset > 20_000:
                        raise RuntimeError("SVI pagination guard tripped")
                if features:
                    return features, url
                errors.append(f"{url}: empty feature set")
            except Exception as exc:  # noqa: BLE001 - try the next official host
                errors.append(f"{url}: {exc}")
    raise RuntimeError("CDC SVI FeatureServer query failed: " + " | ".join(errors))


async def live_source_counts(session: AsyncSession) -> tuple[int, int]:
    row = (await session.execute(_LIVE_COUNTS)).one()
    return int(row.live_stops), int(row.live_tracts)


async def delete_demo_fixture_rows(session: AsyncSession) -> None:
    """Remove synthetic stops/tracts after a successful live ingest.

    Live snapshots and denormalized historical portfolio rows are left intact.
    """
    await session.execute(
        text(
            """
            DELETE FROM bus_stops WHERE source_snapshot_id IN (
                SELECT id FROM source_snapshots WHERE evidence_mode = 'DEMO_FIXTURE'
            )
            """
        )
    )
    await session.execute(
        text(
            """
            DELETE FROM svi_tracts WHERE source_snapshot_id IN (
                SELECT id FROM source_snapshots WHERE evidence_mode = 'DEMO_FIXTURE'
            )
            """
        )
    )
    await session.execute(text("DELETE FROM source_snapshots WHERE evidence_mode = 'DEMO_FIXTURE'"))


async def ingest_phoenix(session: AsyncSession, *, clip_to_aoi: bool = True) -> dict[str, Any]:
    features, url = await fetch_phoenix_features(clip_to_aoi=clip_to_aoi)
    rows, report = validate_phoenix_features(features)
    if not rows:
        raise RuntimeError(f"Phoenix ingest produced no usable stops: {report}")

    canonical = json.dumps(sorted(rows, key=lambda row: row["stop_id"]), sort_keys=True, separators=(",", ":")).encode()
    snapshot = await snapshots.record_snapshot(
        session,
        source_name=snapshots.PHOENIX_SOURCE_NAME,
        source_url=url,
        source_version=(
            f"Public/BusStops layer 0, {len(rows)} stops, clipped={clip_to_aoi}; "
            f"NBR_SHELTERS null for {report['nullShelters']} of {report['received']}"
        ),
        checksum=snapshots.checksum_of(canonical),
        evidence_mode=RuntimeMode.LIVE.value,
        license_note=PHOENIX_LICENSE_NOTE,
    )
    payload = [{**row, "snapshot_id": str(snapshot.id)} for row in rows]
    await session.execute(_UPSERT_STOP, payload)
    report["snapshotId"] = str(snapshot.id)
    report["sourceUrl"] = url
    return report


async def ingest_svi(session: AsyncSession) -> dict[str, Any]:
    features, url = await fetch_svi_features()
    rows, report = svi_rows_from_geojson(features)
    if not rows:
        raise RuntimeError(f"SVI ingest produced no usable tracts: {report}")

    canonical = json.dumps(
        sorted(({"geoid": row["geoid"], "overall_percentile": row["overall_percentile"]} for row in rows),
               key=lambda row: row["geoid"]),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    snapshot = await snapshots.record_snapshot(
        session,
        source_name=snapshots.SVI_SOURCE_NAME,
        source_url=url,
        source_version=f"{SVI_EDITION}, {len(rows)} Arizona tracts intersecting the corridor envelope",
        checksum=snapshots.checksum_of(canonical),
        evidence_mode=RuntimeMode.LIVE.value,
        license_note=SVI_LICENSE_NOTE,
    )
    payload = [{**row, "snapshot_id": str(snapshot.id)} for row in rows]
    await session.execute(_UPSERT_TRACT, payload)
    report["snapshotId"] = str(snapshot.id)
    report["sourceUrl"] = url
    return report
