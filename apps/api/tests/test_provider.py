"""FortyGuard request construction and defensive response parsing."""

from __future__ import annotations

import datetime as dt

import httpx
import pytest

from app.config import Settings
from app.domain.errors import (
    MalformedProviderResponseError,
    ProviderFailedError,
    ProviderNotConfiguredError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    is_transient,
)
from app.integrations.fortyguard.client import FortyGuardClient
from app.integrations.fortyguard.fixture_provider import FixtureProvider, load_fixture
from app.integrations.fortyguard.schemas import (
    ProviderStatusValue,
    build_heatmap_request,
    normalize_status,
    parse_status_response,
    parse_submit_response,
)

AOI = {
    "type": "Polygon",
    "coordinates": [[
        [-112.09, 33.45],
        [-112.07, 33.45],
        [-112.07, 33.51],
        [-112.09, 33.51],
        [-112.09, 33.45],
    ]],
}


# --- request -----------------------------------------------------------------


def test_request_matches_the_published_schema():
    body = build_heatmap_request(
        aoi_geojson=AOI, start_date=dt.date(2026, 7, 15), filter_type=3, threshold_celsius=40.0
    )
    assert body["polygon_aoi"] == AOI
    assert body["date_time"] == {"start_date": "2026-07-15", "filter_type": 3}
    assert body["analytic_type"] == "exceedance"
    assert body["granularity"] == 100
    assert body["threshold"] == 40.0
    assert body["direction"] == "above"


def test_optional_date_fields_are_only_sent_when_present():
    body = build_heatmap_request(
        aoi_geojson=AOI,
        start_date=dt.date(2026, 7, 15),
        filter_type=2,
        start_time="06:00",
        end_time="18:00",
    )
    assert body["date_time"]["start_time"] == "06:00"
    assert "end_date" not in body["date_time"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"analytic_type": "not-a-mode"},
        {"granularity": 42},
        {"filter_type": 9},
        {"direction": "sideways"},
    ],
)
def test_invalid_enum_values_never_reach_the_network(kwargs):
    call = {"aoi_geojson": AOI, "start_date": dt.date(2026, 7, 15), "filter_type": 3, **kwargs}
    with pytest.raises(ValueError):
        build_heatmap_request(**call)


# --- submit response ---------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {"activity_id": "abc-123"},
        {"activityId": "abc-123"},
        {"task_id": "abc-123"},
        {"data": {"activity_id": "abc-123"}},
        {"result": {"id": "abc-123"}},
    ],
)
def test_activity_id_is_read_from_documented_aliases(payload):
    assert parse_submit_response(payload) == "abc-123"


def test_a_submit_response_without_an_activity_id_is_malformed():
    with pytest.raises(MalformedProviderResponseError):
        parse_submit_response({"ok": True})


def test_an_empty_activity_id_is_malformed():
    with pytest.raises(MalformedProviderResponseError):
        parse_submit_response({"activity_id": "   "})


# --- status response ---------------------------------------------------------


@pytest.mark.parametrize(
    "token,expected",
    [
        ("completed", ProviderStatusValue.COMPLETED),
        ("SUCCESS", ProviderStatusValue.COMPLETED),
        ("in-progress", ProviderStatusValue.PROCESSING),
        ("queued", ProviderStatusValue.PROCESSING),
        ("FAILED", ProviderStatusValue.FAILED),
        ("banana", None),
    ],
)
def test_status_tokens_normalize(token, expected):
    assert normalize_status(token) is expected


def test_processing_status_carries_no_cells():
    result = parse_status_response({"activity_id": "a1", "status": "processing"})
    assert result.status == ProviderStatusValue.PROCESSING
    assert result.cells == []


def test_failed_status_captures_the_provider_message():
    result = parse_status_response(
        {"activity_id": "a1", "status": "failed", "error": "area unavailable"}
    )
    assert result.status == ProviderStatusValue.FAILED
    assert result.error_message == "area unavailable"


def test_completed_status_parses_polygons_and_metric_name():
    payload = {
        "activity_id": "a1",
        "status": "completed",
        "map_data": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[
                            [-112.08, 33.45], [-112.07, 33.45], [-112.07, 33.46],
                            [-112.08, 33.46], [-112.08, 33.45],
                        ]],
                    },
                    "properties": {"exceedance_hours": 9.5},
                }
            ],
        },
    }
    result = parse_status_response(payload)
    assert result.status == ProviderStatusValue.COMPLETED
    assert len(result.cells) == 1
    assert result.metric_name == "exceedance_hours"
    assert result.cells[0].metric_value == 9.5
    assert result.parse_notes["mapDataField"] == "map_data"


def test_a_multipolygon_is_exploded_into_separate_cells():
    payload = {
        "status": "completed",
        "map_data": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "MultiPolygon",
                        "coordinates": [
                            [[
                                [-112.08, 33.45], [-112.075, 33.45], [-112.075, 33.455],
                                [-112.08, 33.455], [-112.08, 33.45],
                            ]],
                            [[
                                [-112.07, 33.46], [-112.065, 33.46], [-112.065, 33.465],
                                [-112.07, 33.465], [-112.07, 33.46],
                            ]],
                        ],
                    },
                    "properties": {"exceedance_hours": 7.0},
                }
            ],
        },
    }
    result = parse_status_response(payload)
    assert len(result.cells) == 2
    assert all(cell.geometry.geom_type == "Polygon" for cell in result.cells)


def test_completed_without_a_surface_is_malformed():
    with pytest.raises(MalformedProviderResponseError):
        parse_status_response({"status": "completed"})


def test_an_unrecognised_status_with_no_data_is_malformed():
    with pytest.raises(MalformedProviderResponseError):
        parse_status_response({"state": "banana"})


def test_mixed_metric_names_are_rejected():
    def feature(prop, value, offset):
        return {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [-112.08 + offset, 33.45], [-112.075 + offset, 33.45],
                    [-112.075 + offset, 33.455], [-112.08 + offset, 33.455],
                    [-112.08 + offset, 33.45],
                ]],
            },
            "properties": {prop: value},
        }

    with pytest.raises(MalformedProviderResponseError):
        parse_status_response(
            {
                "status": "completed",
                "map_data": {
                    "type": "FeatureCollection",
                    "features": [feature("exceedance_hours", 5.0, 0.0), feature("tcm", 31.0, 0.01)],
                },
            }
        )


# --- the fixture provider uses the same contract -----------------------------


async def test_fixture_submit_and_completed_status_parse_through_the_real_adapter():
    provider = FixtureProvider()
    activity_id, raw = await provider.submit_heatmap({})
    assert activity_id.startswith("fixture-activity")
    assert raw["status"] == "queued"

    parsed, stored = await provider.check_status(activity_id)
    assert parsed.status == ProviderStatusValue.COMPLETED
    assert len(parsed.cells) > 100
    assert parsed.metric_name == "exceedance_hours"
    # The bulky surface is not duplicated into the audit copy.
    assert stored["map_data"] == {"omitted": "stored as heat_cells rows"}


async def test_fixture_reports_processing_before_the_simulated_latency_elapses():
    provider = FixtureProvider(Settings(fixture_processing_seconds=30))
    submitted = dt.datetime(2026, 8, 13, 12, 0, 0, tzinfo=dt.UTC)
    parsed, _ = await provider.check_status_at(
        "fixture-activity-x", submitted_at=submitted, now=submitted + dt.timedelta(seconds=5)
    )
    assert parsed.status == ProviderStatusValue.PROCESSING

    parsed, _ = await provider.check_status_at(
        "fixture-activity-x", submitted_at=submitted, now=submitted + dt.timedelta(seconds=31)
    )
    assert parsed.status == ProviderStatusValue.COMPLETED


async def test_a_forced_fixture_failure_is_a_failure_not_a_fixture_success():
    provider = FixtureProvider(force_failure=True)
    parsed, _ = await provider.check_status("fixture-activity-x")
    assert parsed.status == ProviderStatusValue.FAILED


def test_the_malformed_fixture_is_actually_rejected():
    """The stored malformed sample must fail the parser, or it proves nothing."""
    with pytest.raises(MalformedProviderResponseError):
        parse_status_response(load_fixture("fortyguard_status_malformed.json"))


# --- HTTP failure classification ---------------------------------------------


def _client(handler, **overrides) -> FortyGuardClient:
    config = Settings(fortyguard_api_key="test-key", **overrides)
    transport = httpx.MockTransport(handler)
    return FortyGuardClient(config, client=httpx.AsyncClient(transport=transport))


async def test_a_missing_api_key_is_reported_before_any_request():
    client = FortyGuardClient(Settings(fortyguard_api_key=""))
    with pytest.raises(ProviderNotConfiguredError):
        await client.check_status("a1")


async def test_the_api_key_is_sent_in_the_configured_header():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        return httpx.Response(200, json={"activity_id": "a1"})

    client = _client(handler, fortyguard_api_key_header="x-api-key")
    await client.submit_heatmap({})
    assert seen["x-api-key"] == "test-key"


async def test_a_bearer_prefix_is_honoured():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        return httpx.Response(200, json={"activity_id": "a1"})

    client = _client(
        handler, fortyguard_api_key_header="authorization", fortyguard_api_key_prefix="Bearer "
    )
    await client.submit_heatmap({})
    assert seen["authorization"] == "Bearer test-key"


@pytest.mark.parametrize(
    "status_code,expected",
    [
        (429, ProviderRateLimitError),
        (500, ProviderUnavailableError),
        (503, ProviderUnavailableError),
        (401, ProviderFailedError),
        (422, ProviderFailedError),
    ],
)
async def test_http_status_codes_map_to_classified_errors(status_code, expected):
    client = _client(lambda request: httpx.Response(status_code, json={"detail": "nope"}))
    with pytest.raises(expected):
        await client.check_status("a1")


async def test_a_timeout_is_classified_as_transient():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    client = _client(handler)
    with pytest.raises(ProviderTimeoutError) as exc:
        await client.check_status("a1")
    assert is_transient(exc.value)


async def test_rate_limit_and_unavailable_are_transient_but_rejection_is_not():
    assert is_transient(ProviderRateLimitError("x"))
    assert is_transient(ProviderUnavailableError("x"))
    assert not is_transient(ProviderFailedError("x"))
    assert not is_transient(MalformedProviderResponseError("x"))


async def test_a_non_json_body_is_malformed():
    client = _client(lambda request: httpx.Response(200, text="<html>nope</html>"))
    with pytest.raises(MalformedProviderResponseError):
        await client.check_status("a1")


async def test_credentials_never_appear_in_an_error_message():
    client = _client(lambda request: httpx.Response(403, json={"detail": "bad key"}))
    with pytest.raises(ProviderFailedError) as exc:
        await client.check_status("a1")
    assert "test-key" not in exc.value.message
    assert "test-key" not in str(exc.value.detail)
