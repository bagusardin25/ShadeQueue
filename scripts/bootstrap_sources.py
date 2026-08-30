"""Choose fixture or official sources at process start.

    uv run --project apps/api python scripts/bootstrap_sources.py

Production (`APP_ENV=production` or `SOURCE_MODE=live`) ingests City of Phoenix
bus stops and CDC SVI 2022 tracts, then deletes DEMO_FIXTURE rows so the two
never mix. Local/test defaults stay on labeled fixtures.

If live rows already exist, ingest is skipped unless `REFRESH_SOURCES=1`.
A failed first-time live ingest falls back to fixtures so the app can still boot.
"""

from __future__ import annotations

import asyncio

import _bootstrap  # noqa: F401

from app.config import settings
from app.db.session import dispose_engine, session_scope
from app.services import official_sources
from load_fixtures import load


def _mode() -> str:
    configured = (settings.source_mode or "auto").strip().lower()
    if configured in {"live", "fixture"}:
        return configured
    return "live" if settings.app_env.lower() == "production" else "fixture"


async def bootstrap() -> None:
    mode = _mode()
    print(f"source bootstrap mode={mode} app_env={settings.app_env}")
    if mode == "fixture":
        await load(reset=False)
        return

    fallback_to_fixture = False
    async with session_scope() as session:
        live_stops, live_tracts = await official_sources.live_source_counts(session)
        has_live = live_stops >= 50 and live_tracts >= 5
        print(f"existing live stops={live_stops} tracts={live_tracts}")
        if has_live and not settings.refresh_sources:
            print("keeping existing LIVE Phoenix + SVI snapshots")
            return
        try:
            phoenix = await official_sources.ingest_phoenix(session, clip_to_aoi=True)
            print("phoenix ingest", phoenix)
            svi = await official_sources.ingest_svi(session)
            print("svi ingest", svi)
            await official_sources.delete_demo_fixture_rows(session)
            print("removed DEMO_FIXTURE stops and tracts")
        except Exception as exc:
            print(f"live ingest failed: {exc!r}")
            if has_live:
                print("keeping previously ingested LIVE sources")
                return
            fallback_to_fixture = True
    if fallback_to_fixture:
        print("falling back to DEMO_FIXTURE sources")
        await load(reset=False)


async def _run() -> None:
    try:
        await bootstrap()
    finally:
        await dispose_engine()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
