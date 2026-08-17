"""Ingest City of Phoenix bus stops from the official ArcGIS MapServer.

    uv run --project apps/api python scripts/ingest_phoenix.py --dry-run
    uv run --project apps/api python scripts/ingest_phoenix.py

The MVP covers one corridor, so the query is clipped to the predeclared AOI
envelope by default rather than pulling the whole city.

`RIDERSHIP` is stored as a source-provided value. Its period and unit have not
been verified against source metadata, so nothing in this pipeline may relabel
it as boardings per day until that verification is documented.

Source: https://maps.phoenix.gov/pub/rest/services/public/BusStops/MapServer
Check the publisher's terms and attribution requirements before redistributing
any snapshot produced by this script.
"""

from __future__ import annotations

import argparse
import asyncio
import json

import _bootstrap  # noqa: F401  (sys.path side effect)

import httpx
from app.db.session import dispose_engine, session_scope
from app.domain.aoi import ALLOWED_AOI_GEOJSON
from app.domain.runtime_mode import RuntimeMode
from app.services import snapshots
from shapely.geometry import shape
from sqlalchemy import text

BASE_URL = "https://maps.phoenix.gov/pub/rest/services/Public/BusStops/MapServer"
DEFAULT_LAYER = 0
PAGE_SIZE = 1000
REQUIRED_FIELDS = ("STOP_ID", "NBR_SHELTERS", "RIDERSHIP")
LICENSE_NOTE = (
    "City of Phoenix open GIS service. Verify the publisher's terms and attribution "
    "requirements before redistributing a snapshot."
)

_UPSERT = text(
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


def aoi_envelope() -> tuple[float, float, float, float]:
    return shape(ALLOWED_AOI_GEOJSON).bounds


async def fetch_features(layer: int, clip_to_aoi: bool) -> tuple[list[dict], str]:
    """Page through the service and return (features, query url)."""
    url = f"{BASE_URL}/{layer}/query"
    params: dict[str, str] = {
        "where": "1=1",
        "outFields": ",".join(REQUIRED_FIELDS) + ",*",
        "f": "geojson",
        "outSR": "4326",
        "resultRecordCount": str(PAGE_SIZE),
    }
    if clip_to_aoi:
        minx, miny, maxx, maxy = aoi_envelope()
        params.update(
            {
                "geometry": f"{minx},{miny},{maxx},{maxy}",
                "geometryType": "esriGeometryEnvelope",
                "inSR": "4326",
                "spatialRel": "esriSpatialRelIntersects",
            }
        )

    features: list[dict] = []
    offset = 0
    timeout = httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        while True:
            page_params = dict(params, resultOffset=str(offset))
            response = await client.get(url, params=page_params)
            response.raise_for_status()
            document = response.json()
            if "error" in document:
                raise SystemExit(f"ArcGIS error: {document['error']}")
            page = document.get("features", [])
            features.extend(page)
            if len(page) < PAGE_SIZE:
                break
            offset += PAGE_SIZE
            if offset > 50_000:
                raise SystemExit("Pagination guard tripped; the service returned an unexpected volume.")

    return features, url


def validate(features: list[dict]) -> tuple[list[dict], dict[str, int]]:
    """Validate required fields and geometry, and report what was dropped."""
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
    rows: list[dict] = []

    for feature in features:
        props = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}

        stop_id = props.get("STOP_ID")
        if stop_id in (None, ""):
            report["missingStopId"] += 1
            continue
        stop_id = str(stop_id)
        if stop_id in seen:
            report["duplicateStopId"] += 1
            continue

        if geometry.get("type") != "Point" or not geometry.get("coordinates"):
            report["missingGeometry"] += 1
            continue
        lon, lat = geometry["coordinates"][0], geometry["coordinates"][1]

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
            props.get("LOCATION_NAME")
            or props.get("STOP_NAME")
            or props.get("LOCATION")
            or f"Stop {stop_id}"
        )

        seen.add(stop_id)
        rows.append(
            {
                "stop_id": stop_id,
                "location_name": str(name),
                "shelter_count": max(0, int(shelters)),
                "ridership_value": max(0.0, float(ridership)),
                "longitude": float(lon),
                "latitude": float(lat),
            }
        )

    report["accepted"] = len(rows)
    return rows, report


async def run(layer: int, clip_to_aoi: bool, dry_run: bool) -> None:
    features, url = await fetch_features(layer, clip_to_aoi)
    rows, report = validate(features)

    canonical = json.dumps(
        sorted(
            (
                {k: v for k, v in row.items()}
                for row in rows
            ),
            key=lambda row: row["stop_id"],
        ),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    checksum = snapshots.checksum_of(canonical)

    print("--- ingestion report ---")
    for key, value in report.items():
        print(f"{key:>18}: {value}")
    print(f"{'checksum':>18}: {checksum}")
    print(f"{'sourceUrl':>18}: {url}")

    if not rows:
        raise SystemExit("No usable stops were returned; nothing was written.")

    if dry_run:
        print("\nDry run: no rows were written.")
        return

    async with session_scope() as session:
        snapshot = await snapshots.record_snapshot(
            session,
            source_name=snapshots.PHOENIX_SOURCE_NAME,
            source_url=url,
            source_version=f"layer {layer}, {len(rows)} stops, clipped={clip_to_aoi}",
            checksum=checksum,
            evidence_mode=RuntimeMode.LIVE.value,
            license_note=LICENSE_NOTE,
        )
        for row in rows:
            row["snapshot_id"] = str(snapshot.id)
        await session.execute(_UPSERT, rows)
        print(f"\nupserted {len(rows)} stops under snapshot {snapshot.id}")

    await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layer", type=int, default=DEFAULT_LAYER)
    parser.add_argument(
        "--all-city",
        action="store_true",
        help="Ingest the whole service instead of clipping to the predeclared AOI envelope.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Fetch and validate without writing.")
    args = parser.parse_args()
    asyncio.run(run(args.layer, not args.all_city, args.dry_run))


if __name__ == "__main__":
    main()
