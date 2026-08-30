"""Official Phoenix / SVI parsers do not require a live GIS call."""

from __future__ import annotations

from app.services.official_sources import svi_rows_from_geojson, validate_phoenix_features


def test_phoenix_null_shelter_is_stored_as_zero_and_counted():
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-112.073, 33.465]},
            "properties": {
                "STOP_ID": 275,
                "LOCATION": "EB CAMELBACK RD FS CENTRAL AVE",
                "NBR_SHELTERS": None,
                "RIDERSHIP": 179,
            },
        },
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-112.082, 33.451]},
            "properties": {
                "STOP_ID": 8783,
                "LOCATION": "EB MCDOWELL RD FS 5TH AVE",
                "NBR_SHELTERS": 1,
                "RIDERSHIP": None,
            },
        },
    ]
    rows, report = validate_phoenix_features(features)
    by_id = {row["stop_id"]: row for row in rows}
    assert report["accepted"] == 2
    assert report["nullShelters"] == 1
    assert report["nullRidership"] == 1
    assert by_id["275"]["shelter_count"] == 0
    assert by_id["275"]["ridership_value"] == 179.0
    assert by_id["8783"]["ridership_value"] == 0.0
    assert by_id["8783"]["location_name"] == "EB MCDOWELL RD FS 5TH AVE"


def test_svi_keeps_arizona_tracts_and_drops_suppressed_values():
    polygon = {
        "type": "Polygon",
        "coordinates": [[
            [-112.09, 33.44],
            [-112.08, 33.44],
            [-112.08, 33.45],
            [-112.09, 33.45],
            [-112.09, 33.44],
        ]],
    }
    features = [
        {
            "type": "Feature",
            "geometry": polygon,
            "properties": {"FIPS": "04013107403", "RPL_THEMES": 0.9244},
        },
        {
            "type": "Feature",
            "geometry": polygon,
            "properties": {"FIPS": "06037123401", "RPL_THEMES": 0.5},
        },
        {
            "type": "Feature",
            "geometry": polygon,
            "properties": {"FIPS": "04013107500", "RPL_THEMES": -999},
        },
    ]
    rows, report = svi_rows_from_geojson(features)
    assert report["accepted"] == 1
    assert report["nonArizona"] == 1
    assert report["suppressed"] == 1
    assert rows[0]["geoid"] == "04013107403"
    assert rows[0]["overall_percentile"] == 0.9244
    assert '"type": "MultiPolygon"' in rows[0]["geometry"] or '"type":"MultiPolygon"' in rows[0]["geometry"]
