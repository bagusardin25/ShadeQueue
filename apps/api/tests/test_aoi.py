"""AOI validation, area limits, and canonical request hashing."""

from __future__ import annotations

import datetime as dt

import pytest

from app.domain.aoi import (
    ALLOWED_AOI_GEOJSON,
    canonical_request_hash,
    celsius_to_fahrenheit,
    fahrenheit_to_celsius,
    geodesic_area_km2,
    validate_aoi,
    validate_date_window,
)
from app.domain.errors import DateNotAllowedError, InvalidAOIError

CORRIDOR = {
    "type": "Polygon",
    "coordinates": [[
        [-112.0900, 33.4500],
        [-112.0700, 33.4500],
        [-112.0700, 33.5100],
        [-112.0900, 33.5100],
        [-112.0900, 33.4500],
    ]],
}


def _hash(**overrides):
    payload = {
        "aoi_geojson": CORRIDOR,
        "start_date": dt.date(2026, 7, 15),
        "end_date": None,
        "start_time": None,
        "end_time": None,
        "filter_type": 3,
        "analytic_type": "exceedance",
        "threshold_celsius": 40.0,
        "direction": "above",
        "granularity": 100,
        "runtime_mode": "LIVE",
    }
    payload.update(overrides)
    return canonical_request_hash(**payload)


def test_accepts_a_polygon_inside_the_predeclared_corridor():
    result = validate_aoi(CORRIDOR, max_area_km2=25.0)
    assert result.area_km2 > 0
    assert result.geojson["type"] == "Polygon"


def test_rejects_a_polygon_outside_the_predeclared_corridor():
    tucson = {
        "type": "Polygon",
        "coordinates": [[
            [-110.99, 32.20], [-110.95, 32.20], [-110.95, 32.24], [-110.99, 32.24], [-110.99, 32.20],
        ]],
    }
    with pytest.raises(InvalidAOIError) as exc:
        validate_aoi(tucson, max_area_km2=25.0)
    assert "outside the predeclared" in exc.value.message


def test_rejects_an_aoi_larger_than_the_configured_limit():
    with pytest.raises(InvalidAOIError) as exc:
        validate_aoi(CORRIDOR, max_area_km2=0.5)
    assert exc.value.detail["maxAreaKm2"] == 0.5


def test_rejects_non_polygon_geometry():
    point = {"type": "Point", "coordinates": [-112.08, 33.46]}
    with pytest.raises(InvalidAOIError):
        validate_aoi(point, max_area_km2=25.0)


def test_repairs_a_self_intersecting_polygon():
    bowtie = {
        "type": "Polygon",
        "coordinates": [[
            [-112.0900, 33.4500],
            [-112.0700, 33.5100],
            [-112.0700, 33.4500],
            [-112.0900, 33.5100],
            [-112.0900, 33.4500],
        ]],
    }
    result = validate_aoi(bowtie, max_area_km2=25.0)
    assert result.geometry.is_valid


def test_the_allowed_envelope_validates_against_itself():
    """The predeclared AOI must itself be submittable, or nothing is."""
    area = geodesic_area_km2(
        validate_aoi(ALLOWED_AOI_GEOJSON, max_area_km2=100.0).geometry
    )
    assert 10.0 < area < 40.0


def test_hash_is_stable_across_equivalent_coordinate_precision():
    shifted = {
        "type": "Polygon",
        "coordinates": [[
            [-112.09000000001, 33.45],
            [-112.07, 33.45],
            [-112.07, 33.51],
            [-112.09, 33.51],
            [-112.09000000001, 33.45],
        ]],
    }
    assert _hash() == _hash(aoi_geojson=shifted)


@pytest.mark.parametrize(
    "override",
    [
        {"start_date": dt.date(2026, 7, 16)},
        {"analytic_type": "tcm"},
        {"threshold_celsius": 41.0},
        {"granularity": 80},
        {"direction": "below"},
        {"filter_type": 4},
        {"runtime_mode": "DEMO_FIXTURE"},
    ],
)
def test_hash_changes_when_any_provider_input_changes(override):
    assert _hash() != _hash(**override)


def test_fixture_and_live_requests_never_share_a_hash():
    assert _hash(runtime_mode="LIVE") != _hash(runtime_mode="DEMO_FIXTURE")


def test_date_window_rejects_dates_outside_the_approved_range():
    with pytest.raises(DateNotAllowedError):
        validate_date_window(
            dt.date(2026, 1, 1), None, minimum=dt.date(2026, 6, 1), maximum=dt.date(2026, 8, 31)
        )


def test_date_window_rejects_an_end_before_the_start():
    with pytest.raises(DateNotAllowedError):
        validate_date_window(
            dt.date(2026, 7, 10),
            dt.date(2026, 7, 1),
            minimum=dt.date(2026, 6, 1),
            maximum=dt.date(2026, 8, 31),
        )


def test_temperature_conversion_round_trips():
    assert celsius_to_fahrenheit(40.0) == pytest.approx(104.0)
    assert fahrenheit_to_celsius(104.0) == pytest.approx(40.0)
