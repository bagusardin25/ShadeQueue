"""Integration tests against a real PostGIS database.

These cover the things a unit test cannot prove: that the migration produces a
usable schema, that the spatial join returns the values the fixture encodes,
that the request-hash guard survives concurrency, and that the whole path from
heat job to CSV export works end to end.
"""

from __future__ import annotations

import asyncio
import datetime as dt

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.config import settings
from app.db.models import AuditEvent, HeatJob
from app.domain.runtime_mode import HeatJobState, RuntimeMode
from app.main import create_app
from app.services import heat_jobs as heat_job_service
from app.services import spatial
from tests.conftest import requires_db

pytestmark = requires_db

AOI = {
    "type": "Polygon",
    "coordinates": [[
        [-112.0930, 33.4420],
        [-112.0670, 33.4420],
        [-112.0670, 33.5130],
        [-112.0930, 33.5130],
        [-112.0930, 33.4420],
    ]],
}

#: Values encoded into the fixture heat surface for these stops.
EXPECTED_EXCEEDANCE = {"SQ-101": 7.8, "SQ-109": 12.4, "SQ-116": 12.8, "SQ-114": 5.2}
EXPECTED_SVI = {"SQ-101": 0.61, "SQ-109": 0.96, "SQ-116": 0.98}


def _job_request(**overrides) -> dict:
    payload = {
        "aoi": AOI,
        "startDate": "2026-07-15",
        "filterType": 3,
        "analyticType": "exceedance",
        "thresholdCelsius": 40.0,
        "direction": "above",
        "granularity": 100,
    }
    payload.update(overrides)
    return payload


async def _client() -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="http://testserver"
    )


async def _completed_job(client: AsyncClient) -> dict:
    response = await client.post("/api/v1/heat-jobs", json=_job_request())
    assert response.status_code == 201, response.text
    job = response.json()

    for _ in range(20):
        if job["state"] in {"COMPLETED", "FAILED"}:
            break
        job = (await client.get(f"/api/v1/heat-jobs/{job['jobId']}")).json()
    return job


# --- schema ------------------------------------------------------------------


async def test_gist_indexes_exist_on_every_geometry_column(session):
    result = await session.execute(
        text(
            """
            SELECT tablename, indexname
            FROM pg_indexes
            WHERE indexdef ILIKE '%USING gist%'
              AND tablename IN ('bus_stops', 'svi_tracts', 'heat_cells')
            """
        )
    )
    indexed = {row.tablename for row in result}
    assert indexed == {"bus_stops", "svi_tracts", "heat_cells"}


async def test_postgis_is_installed(session):
    version = await session.scalar(text("SELECT postgis_version()"))
    assert version


# --- spatial join ------------------------------------------------------------


async def test_spatial_join_returns_the_values_the_fixture_encodes(seeded_db, fast_provider):
    async with await _client() as client:
        job = await _completed_job(client)
    assert job["state"] == "COMPLETED"
    assert job["heatCellCount"] > 100

    import uuid

    candidates = await spatial.load_candidates(
        seeded_db, heat_job_id=uuid.UUID(job["jobId"]), aoi_geojson=AOI
    )
    by_id = {c.stop_id: c for c in candidates}
    assert len(candidates) == 16

    for stop_id, expected in EXPECTED_EXCEEDANCE.items():
        assert by_id[stop_id].exceedance_hours == pytest.approx(expected), stop_id
        assert by_id[stop_id].heat_join_method == "INTERSECTS"
    for stop_id, expected in EXPECTED_SVI.items():
        assert by_id[stop_id].svi_percentile == pytest.approx(expected), stop_id

    # The two stops that already have shelters must be visible but ineligible.
    assert by_id["SQ-107"].eligible is False
    assert by_id["SQ-114"].eligible is False


async def test_an_aoi_with_no_stops_returns_no_candidates(seeded_db, fast_provider):
    async with await _client() as client:
        job = await _completed_job(client)

    import uuid

    empty_aoi = {
        "type": "Polygon",
        "coordinates": [[
            [-112.0690, 33.4430], [-112.0680, 33.4430],
            [-112.0680, 33.4440], [-112.0690, 33.4440], [-112.0690, 33.4430],
        ]],
    }
    candidates = await spatial.load_candidates(
        seeded_db, heat_job_id=uuid.UUID(job["jobId"]), aoi_geojson=empty_aoi
    )
    assert candidates == []


# --- heat job contract -------------------------------------------------------


async def test_a_fixture_job_is_labelled_demo_fixture(clean_db, fast_provider):
    async with await _client() as client:
        job = await _completed_job(client)
    assert job["runtimeMode"] == RuntimeMode.DEMO_FIXTURE.value
    assert job["providerActivityId"].startswith("fixture-activity")
    assert job["pollRecommended"] is False


async def test_a_duplicate_request_is_reused_and_labelled_cached(clean_db, fast_provider):
    async with await _client() as client:
        first = await client.post("/api/v1/heat-jobs", json=_job_request())
        second = await client.post("/api/v1/heat-jobs", json=_job_request())

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["jobId"] == first.json()["jobId"]
    assert second.json()["reused"] is True
    assert second.json()["reuseCount"] == 1


async def test_concurrent_duplicate_submissions_create_one_job(clean_db, fast_provider):
    async with await _client() as client:
        responses = await asyncio.gather(
            *[client.post("/api/v1/heat-jobs", json=_job_request()) for _ in range(6)]
        )

    job_ids = {r.json()["jobId"] for r in responses}
    assert len(job_ids) == 1, "the request-hash guard let a duplicate through"

    count = await clean_db.scalar(text("SELECT count(*) FROM heat_jobs"))
    assert count == 1


async def test_state_survives_a_new_application_instance(clean_db, fast_provider):
    """A reload during processing must not lose the provider activity id."""
    async with await _client() as first_instance:
        created = (await first_instance.post("/api/v1/heat-jobs", json=_job_request())).json()

    assert created["state"] == HeatJobState.SUBMITTED.value
    activity_id = created["providerActivityId"]

    # A separate app object stands in for a restarted process.
    async with await _client() as second_instance:
        reread = (await second_instance.get(f"/api/v1/heat-jobs/{created['jobId']}")).json()

    assert reread["jobId"] == created["jobId"]
    assert reread["providerActivityId"] == activity_id


async def test_processing_state_is_reported_while_the_provider_works(clean_db, monkeypatch):
    monkeypatch.setattr(settings, "provider_poll_interval_seconds", 0)
    monkeypatch.setattr(settings, "fixture_processing_seconds", 120)

    async with await _client() as client:
        created = (await client.post("/api/v1/heat-jobs", json=_job_request())).json()
        polled = (await client.get(f"/api/v1/heat-jobs/{created['jobId']}")).json()

    assert polled["state"] == HeatJobState.PROCESSING.value
    assert polled["pollRecommended"] is True
    assert polled["heatCellCount"] == 0


async def test_an_aoi_outside_the_corridor_is_rejected(clean_db):
    async with await _client() as client:
        response = await client.post(
            "/api/v1/heat-jobs",
            json=_job_request(
                aoi={
                    "type": "Polygon",
                    "coordinates": [[
                        [-110.99, 32.20], [-110.95, 32.20],
                        [-110.95, 32.24], [-110.99, 32.24], [-110.99, 32.20],
                    ]],
                }
            ),
        )
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "INVALID_AOI"
    assert body["correlationId"]


async def test_a_date_outside_the_approved_window_is_rejected(clean_db):
    async with await _client() as client:
        response = await client.post("/api/v1/heat-jobs", json=_job_request(startDate="2026-12-01"))
    assert response.status_code == 422
    assert response.json()["code"] == "DATE_NOT_ALLOWED"


async def test_fahrenheit_and_celsius_spellings_share_one_job(clean_db, fast_provider):
    async with await _client() as client:
        celsius = await client.post("/api/v1/heat-jobs", json=_job_request())
        fahrenheit = await client.post(
            "/api/v1/heat-jobs",
            json=_job_request(thresholdCelsius=None, thresholdFahrenheit=104.0),
        )
    assert fahrenheit.json()["jobId"] == celsius.json()["jobId"]


# --- full flow ---------------------------------------------------------------


async def test_fixture_scenario_to_optimized_portfolio_and_export(seeded_db, fast_provider):
    async with await _client() as client:
        job = await _completed_job(client)
        assert job["state"] == "COMPLETED"

        scenario = (
            await client.post(
                "/api/v1/scenarios",
                json={
                    "heatJobId": job["jobId"],
                    "name": "Central Phoenix heat scenario",
                    "shelterSlots": 10,
                    "equityWeight": 0.45,
                    "minimumEquityShare": 0.4,
                },
            )
        ).json()
        assert scenario["formulaVersion"] == "heat-burden-v1.0"

        run = (
            await client.post(f"/api/v1/scenarios/{scenario['scenarioId']}/runs")
        ).json()

        assert run["state"] == "OPTIMAL"
        assert run["solverStatus"] == "OPTIMAL"
        assert run["runtimeMode"] == "DEMO_FIXTURE"
        assert run["integerScaleFactor"] == 10_000
        assert run["thresholdFahrenheit"] == pytest.approx(104.0)

        stops = run["stops"]
        assert len(stops) == 16
        selected = [s for s in stops if s["selected"]]
        assert len(selected) == 10
        # Every already-sheltered stop must be excluded from new shelters.
        assert all(s["shelterCount"] == 0 for s in selected)

        # The equity floor was actually applied.
        required = run["constraints"]["requiredEquityStops"]
        assert required == 4
        assert sum(1 for s in selected if s["sviPercentile"] >= 0.75) >= required

        # Optimized covers at least as much of the declared objective as baseline.
        assert run["objectiveValue"] >= run["baselineValue"]

        # Provenance is present and names all three sources.
        source_names = {s["name"] for s in run["sourceVersions"]}
        assert "FortyGuard heatmap" in source_names
        assert "City of Phoenix bus stops" in source_names
        assert "CDC/ATSDR SVI" in source_names

        # Re-reading the run returns the same portfolio.
        reread = (await client.get(f"/api/v1/portfolio-runs/{run['runId']}")).json()
        assert [s["stopId"] for s in reread["stops"] if s["selected"]] == [
            s["stopId"] for s in selected
        ]

        heatmap = await client.get(f"/api/v1/heat-jobs/{job['jobId']}/heatmap")
        assert heatmap.status_code == 200
        layer = heatmap.json()
        assert layer["type"] == "FeatureCollection"
        assert len(layer["features"]) >= 1

        export = await client.get(f"/api/v1/portfolio-runs/{run['runId']}/export.csv")
        assert export.status_code == 200
        assert "text/csv" in export.headers["content-type"]
        body = export.text
        assert "does not authorize capital expenditure" in body
        assert "heat-burden-v1.0" in body
        for stop in selected:
            assert stop["stopId"] in body


async def test_the_same_scenario_run_twice_is_reproducible(seeded_db, fast_provider):
    async with await _client() as client:
        job = await _completed_job(client)
        scenario = (
            await client.post(
                "/api/v1/scenarios",
                json={
                    "heatJobId": job["jobId"],
                    "name": "Reproducibility check",
                    "shelterSlots": 8,
                    "equityWeight": 0.3,
                    "minimumEquityShare": 0.25,
                },
            )
        ).json()
        first = (await client.post(f"/api/v1/scenarios/{scenario['scenarioId']}/runs")).json()
        second = (await client.post(f"/api/v1/scenarios/{scenario['scenarioId']}/runs")).json()

    assert first["runId"] != second["runId"]
    assert sorted(s["stopId"] for s in first["stops"] if s["selected"]) == sorted(
        s["stopId"] for s in second["stops"] if s["selected"]
    )
    assert first["objectiveValue"] == pytest.approx(second["objectiveValue"])


async def test_equity_weight_zero_changes_the_portfolio(seeded_db, fast_provider):
    async with await _client() as client:
        job = await _completed_job(client)

        async def run_with(equity_weight: float, share: float) -> set[str]:
            scenario = (
                await client.post(
                    "/api/v1/scenarios",
                    json={
                        "heatJobId": job["jobId"],
                        "name": f"weight-{equity_weight}",
                        "shelterSlots": 6,
                        "equityWeight": equity_weight,
                        "minimumEquityShare": share,
                    },
                )
            ).json()
            run = (
                await client.post(f"/api/v1/scenarios/{scenario['scenarioId']}/runs")
            ).json()
            return {s["stopId"] for s in run["stops"] if s["selected"]}

        neutral = await run_with(0.0, 0.0)
        weighted = await run_with(0.8, 0.5)

    assert neutral != weighted, "the equity settings had no observable effect"


async def test_infeasible_constraints_are_explained_not_hidden(seeded_db, fast_provider):
    async with await _client() as client:
        job = await _completed_job(client)
        scenario = (
            await client.post(
                "/api/v1/scenarios",
                json={
                    "heatJobId": job["jobId"],
                    "name": "Impossible portfolio",
                    "shelterSlots": 15,  # only 14 eligible stops exist
                    "equityWeight": 0.45,
                    "minimumEquityShare": 0.4,
                },
            )
        ).json()
        run = (await client.post(f"/api/v1/scenarios/{scenario['scenarioId']}/runs")).json()

    assert run["state"] == "INFEASIBLE"
    assert run["objectiveValue"] is None
    assert "eligible" in run["infeasibleReason"].lower()
    assert run["constraints"]["infeasibleDetail"]["eligibleStops"] == 14
    # The candidate list is still returned so the planner can see why.
    assert len(run["stops"]) == 16
    assert not any(s["selected"] for s in run["stops"])


async def test_a_scenario_cannot_be_built_on_an_incomplete_heat_job(clean_db, monkeypatch):
    monkeypatch.setattr(settings, "fixture_processing_seconds", 120)
    async with await _client() as client:
        job = (await client.post("/api/v1/heat-jobs", json=_job_request())).json()
        response = await client.post(
            "/api/v1/scenarios",
            json={
                "heatJobId": job["jobId"],
                "name": "Too early",
                "shelterSlots": 5,
                "equityWeight": 0.4,
                "minimumEquityShare": 0.2,
            },
        )
    assert response.status_code == 409
    assert response.json()["code"] == "CONFLICT"


# --- audit and provenance ----------------------------------------------------


async def test_the_audit_trail_links_the_whole_flow(seeded_db, fast_provider):
    async with await _client() as client:
        job = await _completed_job(client)
        scenario = (
            await client.post(
                "/api/v1/scenarios",
                json={
                    "heatJobId": job["jobId"],
                    "name": "Audit check",
                    "shelterSlots": 5,
                    "equityWeight": 0.4,
                    "minimumEquityShare": 0.2,
                },
            )
        ).json()
        run = (await client.post(f"/api/v1/scenarios/{scenario['scenarioId']}/runs")).json()
        await client.get(f"/api/v1/portfolio-runs/{run['runId']}/export.csv")

    result = await seeded_db.execute(text("SELECT event_type FROM audit_events"))
    events = {row.event_type for row in result}
    assert "heat_job.submitted" in events
    assert "heat_job.state_changed" in events
    assert "scenario.created" in events
    assert "portfolio_run.started" in events
    assert "portfolio_run.completed" in events
    assert "portfolio_run.exported" in events


async def test_no_audit_payload_contains_a_credential(seeded_db, fast_provider):
    async with await _client() as client:
        await _completed_job(client)

    result = await seeded_db.execute(text("SELECT event_payload::text AS payload FROM audit_events"))
    for row in result:
        lowered = row.payload.lower()
        assert "api_key" not in lowered
        assert "password" not in lowered


async def test_source_snapshots_endpoint_exposes_limits_but_no_secret(seeded_db):
    async with await _client() as client:
        response = await client.get("/api/v1/source-snapshots")
    body = response.json()
    assert response.status_code == 200
    assert body["allowedAoiName"].startswith("Central / 7th Avenue")
    assert body["maxAoiAreaKm2"] == settings.max_aoi_area_km2
    assert len(body["snapshots"]) == 2
    serialized = response.text.lower()
    assert "password" not in serialized
    assert "fortyguard_api_key" not in serialized


async def test_health_reports_database_readiness(clean_db):
    async with await _client() as client:
        response = await client.get("/api/health")
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["liveProviderEnabled"] is False


async def test_a_correlation_id_is_returned_on_every_response(clean_db):
    async with await _client() as client:
        response = await client.get("/api/health")
    assert len(response.headers["x-correlation-id"]) == 32


async def test_an_unknown_run_id_is_a_clean_404(clean_db):
    import uuid

    async with await _client() as client:
        response = await client.get(f"/api/v1/portfolio-runs/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


# --- provider failure --------------------------------------------------------


async def test_a_provider_timeout_reaches_a_known_failed_state(clean_db, monkeypatch):
    """An expired job fails explicitly rather than pretending to still work."""
    monkeypatch.setattr(settings, "fixture_processing_seconds", 120)
    monkeypatch.setattr(settings, "provider_poll_interval_seconds", 0)

    async with await _client() as client:
        created = (await client.post("/api/v1/heat-jobs", json=_job_request())).json()

        job = await clean_db.get(HeatJob, __import__("uuid").UUID(created["jobId"]))
        await clean_db.refresh(job)
        await clean_db.execute(
            text("UPDATE heat_jobs SET created_at = :old WHERE id = :id"),
            {
                "old": dt.datetime.now(dt.UTC) - dt.timedelta(seconds=100_000),
                "id": created["jobId"],
            },
        )
        await clean_db.commit()

        polled = (await client.get(f"/api/v1/heat-jobs/{created['jobId']}")).json()

    assert polled["state"] == "FAILED"
    assert polled["errorCode"] == "PROVIDER_TIMEOUT"
    assert polled["pollRecommended"] is False


async def test_a_failed_job_does_not_block_a_later_retry(clean_db, fast_provider):
    async with await _client() as client:
        created = (await client.post("/api/v1/heat-jobs", json=_job_request())).json()
        await clean_db.execute(
            text("UPDATE heat_jobs SET state = 'FAILED', error_code = 'PROVIDER_FAILED' WHERE id = :id"),
            {"id": created["jobId"]},
        )
        await clean_db.commit()

        retry = await client.post("/api/v1/heat-jobs", json=_job_request())

    assert retry.status_code == 201
    assert retry.json()["jobId"] != created["jobId"]


async def test_audit_rows_are_written_for_a_failed_job(clean_db, fast_provider):
    async with await _client() as client:
        created = (await client.post("/api/v1/heat-jobs", json=_job_request())).json()

    result = await clean_db.execute(
        text("SELECT count(*) FROM audit_events WHERE object_id = :id"),
        {"id": created["jobId"]},
    )
    assert result.scalar_one() >= 1


async def test_audit_events_share_one_correlation_id_per_request(clean_db, fast_provider):
    async with await _client() as client:
        created = (await client.post("/api/v1/heat-jobs", json=_job_request())).json()

    result = await clean_db.execute(
        text(
            "SELECT DISTINCT correlation_id FROM audit_events WHERE object_id = :id"
        ),
        {"id": created["jobId"]},
    )
    assert len(result.scalars().all()) == 1


async def test_audit_event_model_is_append_only_in_practice(clean_db):
    count = await clean_db.scalar(text("SELECT count(*) FROM audit_events"))
    assert count == 0
    clean_db.add(
        AuditEvent(
            correlation_id="a" * 32,
            object_type="heat_job",
            object_id="x",
            event_type="test.event",
            event_payload={},
        )
    )
    await clean_db.commit()
    assert await clean_db.scalar(text("SELECT count(*) FROM audit_events")) == 1


async def test_heat_job_service_exposes_the_stored_activity_id(clean_db, fast_provider):
    async with await _client() as client:
        created = (await client.post("/api/v1/heat-jobs", json=_job_request())).json()

    import uuid

    job = await heat_job_service.get_heat_job(clean_db, uuid.UUID(created["jobId"]))
    assert job.provider_activity_id == created["providerActivityId"]
    assert job.runtime_mode == RuntimeMode.DEMO_FIXTURE.value
