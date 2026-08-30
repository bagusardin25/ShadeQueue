"""Ingest City of Phoenix bus stops from the official ArcGIS MapServer.

    uv run --project apps/api python scripts/ingest_phoenix.py --dry-run
    uv run --project apps/api python scripts/ingest_phoenix.py

The MVP covers one corridor, so the query is clipped to the predeclared AOI
envelope by default rather than pulling the whole city.

`RIDERSHIP` is stored as a source-provided value. Its period and unit have not
been verified against source metadata, so nothing in this pipeline may relabel
it as boardings per day until that verification is documented.

`NBR_SHELTERS` is missing for almost every stop in the live service and is
stored as 0 (no recorded shelter).

Source: https://maps.phoenix.gov/pub/rest/services/Public/BusStops/MapServer
"""

from __future__ import annotations

import argparse
import asyncio
import json

import _bootstrap  # noqa: F401

from app.db.session import dispose_engine, session_scope
from app.services import official_sources


async def run(clip_to_aoi: bool, dry_run: bool) -> None:
    features, url = await official_sources.fetch_phoenix_features(clip_to_aoi=clip_to_aoi)
    rows, report = official_sources.validate_phoenix_features(features)
    print("--- ingestion report ---")
    for key, value in report.items():
        print(f"{key:>18}: {value}")
    print(f"{'sourceUrl':>18}: {url}")
    if dry_run:
        print("\nDry run: no rows were written.")
        print(json.dumps(rows[:3], indent=2))
        return
    async with session_scope() as session:
        written = await official_sources.ingest_phoenix(session, clip_to_aoi=clip_to_aoi)
        print(f"\nupserted {written['accepted']} stops under snapshot {written['snapshotId']}")
    await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--all-city",
        action="store_true",
        help="Ingest the whole service instead of clipping to the predeclared AOI envelope.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Fetch and validate without writing.")
    args = parser.parse_args()
    asyncio.run(run(not args.all_city, args.dry_run))


if __name__ == "__main__":
    main()
