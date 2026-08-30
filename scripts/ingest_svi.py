"""Ingest CDC/ATSDR Social Vulnerability Index tracts.

    uv run --project apps/api python scripts/ingest_svi.py --dry-run
    uv run --project apps/api python scripts/ingest_svi.py
    uv run --project apps/api --extra etl python scripts/ingest_svi.py --input <path>

Default path queries the official 2022 US tract FeatureServer for Arizona
tracts that intersect the ShadeQueue corridor envelope. `--input` still accepts
a downloaded shapefile/geodatabase/GeoPackage.
"""

from __future__ import annotations

import argparse
import asyncio
import pathlib

import _bootstrap  # noqa: F401

from app.db.session import dispose_engine, session_scope
from app.domain.runtime_mode import RuntimeMode
from app.services import official_sources, snapshots
from sqlalchemy import text

GEOID_FIELDS = ("FIPS", "GEOID", "GEOID10", "GEOID20", "TRACTCE")
PERCENTILE_FIELD = "RPL_THEMES"
SUPPRESSED_VALUE = -999

_FILE_UPSERT = text(
    """
    INSERT INTO svi_tracts (geoid, overall_percentile, geom, source_snapshot_id)
    VALUES (
        :geoid, :overall_percentile,
        ST_Multi(ST_SetSRID(ST_GeomFromText(:wkt), 4326)),
        :snapshot_id
    )
    ON CONFLICT (geoid) DO UPDATE SET
        overall_percentile = EXCLUDED.overall_percentile,
        geom = EXCLUDED.geom,
        source_snapshot_id = EXCLUDED.source_snapshot_id
    """
)


def load_frame(path: pathlib.Path, layer: str | None):
    try:
        import geopandas as gpd
    except ImportError as exc:  # pragma: no cover - depends on the etl extra
        raise SystemExit(
            "geopandas is required for --input. Install the etl extra:\n"
            "  uv sync --project apps/api --extra etl"
        ) from exc
    if not path.exists():
        raise SystemExit(f"Input not found: {path}")
    frame = gpd.read_file(path, layer=layer) if layer else gpd.read_file(path)
    if frame.crs is None:
        raise SystemExit("The input has no CRS; refusing to guess. Reproject it first.")
    if frame.crs.to_epsg() != 4326:
        frame = frame.to_crs(epsg=4326)
    return frame


def pick_geoid_field(frame) -> str:
    for candidate in GEOID_FIELDS:
        if candidate in frame.columns:
            return candidate
    raise SystemExit(f"No tract identifier column found. Looked for: {', '.join(GEOID_FIELDS)}")


def build_rows(frame) -> tuple[list[dict], dict[str, int]]:
    if PERCENTILE_FIELD not in frame.columns:
        raise SystemExit(f"Required column {PERCENTILE_FIELD} is missing from the input.")
    geoid_field = pick_geoid_field(frame)
    report = {
        "received": len(frame),
        "suppressed": 0,
        "nullPercentile": 0,
        "outOfRange": 0,
        "missingGeometry": 0,
        "invalidGeometryRepaired": 0,
        "duplicateGeoid": 0,
    }
    seen: set[str] = set()
    rows: list[dict] = []
    for _, record in frame.iterrows():
        geoid = record.get(geoid_field)
        geometry = record.get("geometry")
        value = record.get(PERCENTILE_FIELD)
        if geoid is None or geometry is None or geometry.is_empty:
            report["missingGeometry"] += 1
            continue
        geoid = str(geoid).strip()
        if geoid in seen:
            report["duplicateGeoid"] += 1
            continue
        if value is None:
            report["nullPercentile"] += 1
            continue
        value = float(value)
        if value <= SUPPRESSED_VALUE + 1:
            report["suppressed"] += 1
            continue
        if not 0.0 <= value <= 1.0:
            report["outOfRange"] += 1
            continue
        if not geometry.is_valid:
            geometry = geometry.buffer(0)
            if geometry.is_empty or not geometry.is_valid:
                report["missingGeometry"] += 1
                continue
            report["invalidGeometryRepaired"] += 1
        seen.add(geoid)
        rows.append({"geoid": geoid, "overall_percentile": value, "wkt": geometry.wkt})
    report["accepted"] = len(rows)
    return rows, report


async def run_service(dry_run: bool) -> None:
    features, url = await official_sources.fetch_svi_features()
    rows, report = official_sources.svi_rows_from_geojson(features)
    print("--- ingestion report ---")
    for key, value in report.items():
        print(f"{key:>24}: {value}")
    print(f"{'sourceUrl':>24}: {url}")
    if dry_run:
        print("\nDry run: no rows were written.")
        return
    async with session_scope() as session:
        written = await official_sources.ingest_svi(session)
        print(f"\nupserted {written['accepted']} tracts under snapshot {written['snapshotId']}")
    await dispose_engine()


async def run_file(
    path: pathlib.Path, layer: str | None, edition: str, source_url: str, dry_run: bool
) -> None:
    frame = load_frame(path, layer)
    rows, report = build_rows(frame)
    print("--- ingestion report ---")
    for key, value in report.items():
        print(f"{key:>24}: {value}")
    if not rows:
        raise SystemExit("No usable tracts were produced; nothing was written.")
    if dry_run:
        print("\nDry run: no rows were written.")
        return
    async with session_scope() as session:
        snapshot = await snapshots.record_snapshot(
            session,
            source_name=snapshots.SVI_SOURCE_NAME,
            source_url=source_url,
            source_version=f"{edition} Arizona tracts, {len(rows)} accepted, file {path.name}",
            checksum=snapshots.checksum_of(path.read_bytes()),
            evidence_mode=RuntimeMode.LIVE.value,
            license_note=official_sources.SVI_LICENSE_NOTE,
        )
        payload = [{**row, "snapshot_id": str(snapshot.id)} for row in rows]
        await session.execute(_FILE_UPSERT, payload)
        print(f"\nupserted {len(rows)} tracts under snapshot {snapshot.id}")
    await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=pathlib.Path, default=None)
    parser.add_argument("--layer", default=None, help="Layer name for multi-layer sources")
    parser.add_argument("--edition", default="SVI 2022")
    parser.add_argument(
        "--source-url",
        default="https://www.atsdr.cdc.gov/place-health/php/svi/svi-data-documentation-download.html",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.input is None:
        asyncio.run(run_service(args.dry_run))
        return
    asyncio.run(run_file(args.input, args.layer, args.edition, args.source_url, args.dry_run))


if __name__ == "__main__":
    main()
