"""Shared test fixtures.

Unit tests run with no external dependency. Integration tests need a reachable
PostGIS and are skipped, not failed, when one is absent, so the unit suite stays
useful on a machine without Docker.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.domain.scoring import CandidateStop
from app.runtime import configure_event_loop

configure_event_loop()


def _database_reachable() -> bool:
    async def probe() -> bool:
        engine = create_async_engine(settings.database_url)
        try:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
            return True
        except Exception:
            return False
        finally:
            await engine.dispose()

    try:
        return asyncio.run(probe())
    except Exception:
        return False


DATABASE_AVAILABLE = _database_reachable()

requires_db = pytest.mark.skipif(
    not DATABASE_AVAILABLE,
    reason=f"No reachable PostGIS at the configured DATABASE_URL ({settings.app_env})",
)


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine(settings.database_url)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as db_session:
        yield db_session
    await engine.dispose()


@pytest.fixture
async def clean_db(session: AsyncSession) -> AsyncSession:
    """Truncate application tables so each integration test starts empty."""
    await session.execute(
        text(
            """
            TRUNCATE portfolio_items, portfolio_runs, scenarios, heat_cells,
                     heat_jobs, audit_events, bus_stops, svi_tracts, source_snapshots
            RESTART IDENTITY CASCADE
            """
        )
    )
    await session.commit()
    return session


def make_candidate(
    stop_id: str,
    *,
    ridership: float = 1000.0,
    exceedance: float = 8.0,
    svi: float = 0.5,
    shelters: int = 0,
    longitude: float = -112.074,
    latitude: float = 33.45,
) -> CandidateStop:
    return CandidateStop(
        stop_id=stop_id,
        location_name=f"Stop {stop_id}",
        longitude=longitude,
        latitude=latitude,
        shelter_count=shelters,
        ridership_value=ridership,
        exceedance_hours=exceedance,
        svi_percentile=svi,
    )


@pytest.fixture
def sample_candidates() -> list[CandidateStop]:
    """Twelve stops: two already sheltered, four above the equity floor."""
    return [
        make_candidate("S01", ridership=2000, exceedance=12.0, svi=0.95),
        make_candidate("S02", ridership=1800, exceedance=11.0, svi=0.90),
        make_candidate("S03", ridership=1600, exceedance=10.5, svi=0.80),
        make_candidate("S04", ridership=1500, exceedance=9.0, svi=0.76),
        make_candidate("S05", ridership=1400, exceedance=8.0, svi=0.60),
        make_candidate("S06", ridership=1300, exceedance=7.5, svi=0.55),
        make_candidate("S07", ridership=1200, exceedance=7.0, svi=0.40),
        make_candidate("S08", ridership=1100, exceedance=6.5, svi=0.35),
        make_candidate("S09", ridership=1000, exceedance=6.0, svi=0.30),
        make_candidate("S10", ridership=900, exceedance=5.0, svi=0.20),
        make_candidate("S11", ridership=2500, exceedance=13.0, svi=0.99, shelters=1),
        make_candidate("S12", ridership=2400, exceedance=12.5, svi=0.98, shelters=2),
    ]


_INSERT_STOP = text(
    """
    INSERT INTO bus_stops (stop_id, location_name, shelter_count, ridership_value, geom, source_snapshot_id)
    VALUES (:stop_id, :location_name, :shelter_count, :ridership_value,
            ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326), :snapshot_id)
    """
)

_INSERT_TRACT = text(
    """
    INSERT INTO svi_tracts (geoid, overall_percentile, geom, source_snapshot_id)
    VALUES (:geoid, :overall_percentile,
            ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(CAST(:geometry AS text)), 4326)), :snapshot_id)
    """
)


@pytest.fixture
async def seeded_db(clean_db: AsyncSession) -> AsyncSession:
    """An empty database loaded with the deterministic demo fixtures."""
    import json

    from app.config import FIXTURES_DIR
    from app.domain.runtime_mode import RuntimeMode
    from app.services import snapshots

    session = clean_db
    stops_doc = json.loads((FIXTURES_DIR / "bus_stops_demo.geojson").read_text(encoding="utf-8"))
    tracts_doc = json.loads((FIXTURES_DIR / "svi_tracts_demo.geojson").read_text(encoding="utf-8"))

    stops_snapshot = await snapshots.record_snapshot(
        session,
        source_name=snapshots.PHOENIX_SOURCE_NAME,
        source_url="fixtures/bus_stops_demo.geojson",
        source_version="test-fixture",
        checksum="0" * 64,
        evidence_mode=RuntimeMode.DEMO_FIXTURE.value,
    )
    svi_snapshot = await snapshots.record_snapshot(
        session,
        source_name=snapshots.SVI_SOURCE_NAME,
        source_url="fixtures/svi_tracts_demo.geojson",
        source_version="test-fixture",
        checksum="1" * 64,
        evidence_mode=RuntimeMode.DEMO_FIXTURE.value,
    )

    await session.execute(
        _INSERT_STOP,
        [
            {
                "stop_id": f["properties"]["STOP_ID"],
                "location_name": f["properties"]["LOCATION_NAME"],
                "shelter_count": int(f["properties"]["NBR_SHELTERS"]),
                "ridership_value": float(f["properties"]["RIDERSHIP"]),
                "longitude": f["geometry"]["coordinates"][0],
                "latitude": f["geometry"]["coordinates"][1],
                "snapshot_id": str(stops_snapshot.id),
            }
            for f in stops_doc["features"]
        ],
    )
    await session.execute(
        _INSERT_TRACT,
        [
            {
                "geoid": f["properties"]["GEOID"],
                "overall_percentile": float(f["properties"]["RPL_THEMES"]),
                "geometry": json.dumps(f["geometry"]),
                "snapshot_id": str(svi_snapshot.id),
            }
            for f in tracts_doc["features"]
        ],
    )
    await session.commit()
    return session


@pytest.fixture
def fast_provider(monkeypatch):
    """Remove the simulated provider latency so flow tests stay quick."""
    monkeypatch.setattr(settings, "fixture_processing_seconds", 0)
    monkeypatch.setattr(settings, "provider_poll_interval_seconds", 0)
    return settings


@pytest.fixture
def fixed_now() -> dt.datetime:
    return dt.datetime(2026, 8, 13, 12, 0, 0, tzinfo=dt.UTC)


@pytest.fixture
def run_id() -> uuid.UUID:
    return uuid.uuid4()
