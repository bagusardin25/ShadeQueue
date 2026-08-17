"""Area-of-interest validation and canonical request hashing.

The public deployment must not expose an unlimited credit-consuming endpoint
(plan section 14), so an AOI is accepted only when it is a valid polygon, small
enough for the Basic tier, and fully inside one predeclared Phoenix envelope.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from pyproj import Geod
from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry

from app.domain.errors import DateNotAllowedError, InvalidAOIError

_GEOD = Geod(ellps="WGS84")

#: The single predeclared corridor envelope for the MVP: Central Avenue and
#: 7th Avenue between roughly Jefferson St and Camelback Rd. Any submitted AOI
#: must fall inside it. Widening this constant widens the credit exposure, so
#: it lives in source control rather than in the environment.
ALLOWED_AOI_GEOJSON: dict[str, Any] = {
    "type": "Polygon",
    "coordinates": [
        [
            [-112.0950, 33.4400],
            [-112.0650, 33.4400],
            [-112.0650, 33.5150],
            [-112.0950, 33.5150],
            [-112.0950, 33.4400],
        ]
    ],
}

ALLOWED_AOI_NAME = "Central / 7th Avenue corridor, Phoenix AZ"

#: Tolerance in degrees for the containment test. Floating point round-tripping
#: through GeoJSON can push a boundary vertex a few nanodegrees outside the
#: envelope; this is far below the resolution of any source dataset.
_CONTAINMENT_BUFFER_DEGREES = 1e-9


@dataclass(frozen=True)
class ValidatedAOI:
    geometry: BaseGeometry
    geojson: dict[str, Any]
    area_km2: float


def allowed_aoi_geometry() -> BaseGeometry:
    return shape(ALLOWED_AOI_GEOJSON)


def geodesic_area_km2(geometry: BaseGeometry) -> float:
    """Return the geodesic area on the WGS84 ellipsoid in square kilometres.

    Planar area on lon/lat degrees is meaningless, and reprojecting to a metre
    CRS would need an AOI-specific projection, so the ellipsoidal integral is
    used directly.
    """
    area_m2, _perimeter = _GEOD.geometry_area_perimeter(geometry)
    return abs(area_m2) / 1_000_000.0


def validate_aoi(raw: Any, *, max_area_km2: float) -> ValidatedAOI:
    """Validate an untrusted GeoJSON polygon and return a repaired geometry."""
    if not isinstance(raw, dict):
        raise InvalidAOIError("The AOI must be a GeoJSON geometry object.")

    geom_type = raw.get("type")
    if geom_type not in {"Polygon", "MultiPolygon"}:
        raise InvalidAOIError(
            "The AOI must be a GeoJSON Polygon or MultiPolygon.",
            detail={"receivedType": str(geom_type)},
        )

    try:
        geometry = shape(raw)
    except Exception as exc:  # shapely raises a range of types for bad input
        raise InvalidAOIError("The AOI geometry could not be parsed.") from exc

    if geometry.is_empty:
        raise InvalidAOIError("The AOI geometry is empty.")

    if not geometry.is_valid:
        # buffer(0) repairs self-intersections; anything it cannot fix is rejected.
        geometry = geometry.buffer(0)
        if geometry.is_empty or not geometry.is_valid:
            raise InvalidAOIError("The AOI geometry is invalid and could not be repaired.")

    minx, miny, maxx, maxy = geometry.bounds
    if not (-180.0 <= minx <= 180.0 and -180.0 <= maxx <= 180.0):
        raise InvalidAOIError("AOI longitude values must lie between -180 and 180.")
    if not (-90.0 <= miny <= 90.0 and -90.0 <= maxy <= 90.0):
        raise InvalidAOIError("AOI latitude values must lie between -90 and 90.")

    area_km2 = geodesic_area_km2(geometry)
    if area_km2 <= 0.0:
        raise InvalidAOIError("The AOI has no measurable area.")
    if area_km2 > max_area_km2:
        raise InvalidAOIError(
            "The AOI exceeds the permitted area for this deployment.",
            detail={"areaKm2": round(area_km2, 4), "maxAreaKm2": max_area_km2},
        )

    allowed = allowed_aoi_geometry().buffer(_CONTAINMENT_BUFFER_DEGREES)
    if not allowed.contains(geometry):
        raise InvalidAOIError(
            "The AOI falls outside the predeclared Phoenix corridor for this deployment.",
            detail={"allowedAoiName": ALLOWED_AOI_NAME, "allowedAoi": ALLOWED_AOI_GEOJSON},
        )

    return ValidatedAOI(geometry=geometry, geojson=mapping(geometry), area_km2=area_km2)


def validate_date_window(
    start_date: dt.date,
    end_date: dt.date | None,
    *,
    minimum: dt.date,
    maximum: dt.date,
) -> None:
    """Reject dates outside the approved analysis window."""
    if start_date < minimum or start_date > maximum:
        raise DateNotAllowedError(
            "The requested start date is outside the approved analysis window.",
            detail={"allowedFrom": minimum.isoformat(), "allowedTo": maximum.isoformat()},
        )
    if end_date is not None:
        if end_date < start_date:
            raise DateNotAllowedError("The end date precedes the start date.")
        if end_date > maximum:
            raise DateNotAllowedError(
                "The requested end date is outside the approved analysis window.",
                detail={"allowedFrom": minimum.isoformat(), "allowedTo": maximum.isoformat()},
            )


def _round_coordinates(value: Any, precision: int = 6) -> Any:
    """Round nested coordinate lists so equivalent AOIs hash identically.

    Six decimal places is roughly 0.11 m at this latitude, well below the
    positional accuracy of any input dataset.
    """
    if isinstance(value, (list, tuple)):
        return [_round_coordinates(item, precision) for item in value]
    if isinstance(value, (int, float)):
        return round(float(value), precision)
    return value


def canonical_request_hash(
    *,
    aoi_geojson: dict[str, Any],
    start_date: dt.date,
    end_date: dt.date | None,
    start_time: str | None,
    end_time: str | None,
    filter_type: int,
    analytic_type: str,
    threshold_celsius: float | None,
    direction: str | None,
    granularity: int,
    runtime_mode: str,
) -> str:
    """Compute a stable hash of everything that changes the provider result.

    Two requests with the same hash must never consume provider credit twice;
    the second one reuses the stored result instead (plan section 14).

    `runtime_mode` participates so a fixture job can never be reused to answer a
    live request, or the reverse.
    """
    canonical = {
        "aoi": {
            "type": aoi_geojson.get("type"),
            "coordinates": _round_coordinates(aoi_geojson.get("coordinates")),
        },
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat() if end_date else None,
        "startTime": start_time,
        "endTime": end_time,
        "filterType": filter_type,
        "analyticType": analytic_type,
        "thresholdCelsius": round(threshold_celsius, 4) if threshold_celsius is not None else None,
        "direction": direction,
        "granularity": granularity,
        "runtimeMode": runtime_mode,
    }
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def celsius_to_fahrenheit(celsius: float) -> float:
    return celsius * 9.0 / 5.0 + 32.0


def fahrenheit_to_celsius(fahrenheit: float) -> float:
    return (fahrenheit - 32.0) * 5.0 / 9.0
