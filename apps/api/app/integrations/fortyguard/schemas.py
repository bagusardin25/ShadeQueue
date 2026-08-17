"""FortyGuard request construction and defensive response parsing.

The request side is pinned to the published OpenAPI document
(https://api.fortyguard.com/openapi.json): `HeatmapSubmitRequest` declares
`polygon_aoi`, `date_time` (`DateTimeRange`), `granularity` in {60, 80, 100},
`analytic_type` in {tcm, time_of_measure, exceedance, persistence}, a `threshold`
in degrees Celsius, and `direction` in {above, below}.

The response side is *not* pinned: that document declares the 200 responses of
both `POST /v1/heatmap` and `GET /v1/status/{activity_id}` as empty schemas. So
rather than assume field names, this module accepts a small set of documented
aliases, records which alias actually matched, and raises
`MalformedProviderResponseError` when nothing matches. A live failure must never
be reshaped into a fixture-shaped success (plan section 13).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from app.config import ProviderDefaults
from app.domain.errors import MalformedProviderResponseError

# --- response key aliases ----------------------------------------------------

_ACTIVITY_ID_KEYS = ("activity_id", "activityId", "task_id", "taskId", "job_id", "jobId", "id")
_STATUS_KEYS = ("status", "state", "activity_status", "task_status", "job_status")
_MAP_DATA_KEYS = ("map_data", "mapData", "geojson", "result_data", "heatmap")
_ERROR_KEYS = ("error", "message", "detail", "error_message", "reason")
#: Containers a provider commonly wraps its payload in.
_ENVELOPE_KEYS = ("data", "result", "response", "payload", "activity", "task")

_COMPLETED_TOKENS = {"completed", "complete", "success", "successful", "succeeded", "done", "finished"}
_FAILED_TOKENS = {"failed", "failure", "error", "errored", "cancelled", "canceled", "aborted"}
_PENDING_TOKENS = {
    "pending",
    "queued",
    "submitted",
    "accepted",
    "processing",
    "running",
    "in_progress",
    "inprogress",
    "started",
}

#: Feature property names that plausibly carry the exceedance value, most
#: specific first. The name that matched is stored as `metric_name`, so an audit
#: reader can see exactly which provider field produced the score.
_METRIC_PROPERTY_KEYS = (
    "exceedance_hours",
    "exceedanceHours",
    "exceedance",
    "hours",
    "hours_above",
    "value",
    "metric_value",
    "metric",
    "count",
    "temperature",
    "tcm",
)


class ProviderStatusValue:
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class HeatCellRecord:
    """One polygon of the returned heat surface, ready for persistence."""

    geometry: BaseGeometry
    metric_name: str
    metric_value: float


@dataclass
class ParsedHeatmapResult:
    status: str
    activity_id: str | None = None
    cells: list[HeatCellRecord] = field(default_factory=list)
    metric_name: str | None = None
    error_message: str | None = None
    #: Which alias each value was read from, retained for the audit trail.
    parse_notes: dict[str, str] = field(default_factory=dict)


# --- request -----------------------------------------------------------------


def build_heatmap_request(
    *,
    aoi_geojson: dict[str, Any],
    start_date: dt.date,
    filter_type: int,
    end_date: dt.date | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    analytic_type: str = ProviderDefaults.DEFAULT_ANALYTIC_TYPE,
    threshold_celsius: float | None = ProviderDefaults.DEFAULT_THRESHOLD_CELSIUS,
    direction: str | None = ProviderDefaults.DEFAULT_DIRECTION,
    granularity: int = ProviderDefaults.DEFAULT_GRANULARITY,
) -> dict[str, Any]:
    """Build the POST /v1/heatmap body.

    Raises ValueError for values the provider's own enum would reject, so an
    invalid combination never reaches the network and never costs credit.
    """
    if analytic_type not in ProviderDefaults.ANALYTIC_TYPES:
        raise ValueError(f"analytic_type must be one of {ProviderDefaults.ANALYTIC_TYPES}")
    if granularity not in ProviderDefaults.GRANULARITIES:
        raise ValueError(f"granularity must be one of {ProviderDefaults.GRANULARITIES}")
    if filter_type not in ProviderDefaults.FILTER_TYPES:
        raise ValueError(f"filter_type must be one of {ProviderDefaults.FILTER_TYPES}")
    if direction is not None and direction not in ProviderDefaults.DIRECTIONS:
        raise ValueError(f"direction must be one of {ProviderDefaults.DIRECTIONS}")

    date_time: dict[str, Any] = {
        "start_date": start_date.isoformat(),
        "filter_type": filter_type,
    }
    if end_date is not None:
        date_time["end_date"] = end_date.isoformat()
    if start_time is not None:
        date_time["start_time"] = start_time
    if end_time is not None:
        date_time["end_time"] = end_time

    body: dict[str, Any] = {
        "polygon_aoi": aoi_geojson,
        "date_time": date_time,
        "granularity": granularity,
        "analytic_type": analytic_type,
    }
    if threshold_celsius is not None:
        body["threshold"] = threshold_celsius
    if direction is not None:
        body["direction"] = direction
    return body


# --- response ----------------------------------------------------------------


def _candidate_scopes(payload: Any) -> list[dict[str, Any]]:
    """The payload itself plus one level of common envelope objects."""
    if not isinstance(payload, dict):
        return []
    scopes = [payload]
    for key in _ENVELOPE_KEYS:
        nested = payload.get(key)
        if isinstance(nested, dict):
            scopes.append(nested)
    return scopes


def _first_key(payload: Any, keys: tuple[str, ...]) -> tuple[str | None, Any]:
    for scope in _candidate_scopes(payload):
        for key in keys:
            if key in scope and scope[key] is not None:
                return key, scope[key]
    return None, None


def normalize_status(raw: Any) -> str | None:
    """Map a provider status string onto the three states this app persists."""
    if isinstance(raw, bool):
        return ProviderStatusValue.COMPLETED if raw else ProviderStatusValue.PROCESSING
    if not isinstance(raw, str):
        return None
    token = raw.strip().lower().replace("-", "_").replace(" ", "_")
    if token in _COMPLETED_TOKENS:
        return ProviderStatusValue.COMPLETED
    if token in _FAILED_TOKENS:
        return ProviderStatusValue.FAILED
    if token in _PENDING_TOKENS:
        return ProviderStatusValue.PROCESSING
    return None


def parse_submit_response(payload: Any) -> str:
    """Extract the provider activity id from a heatmap submission response."""
    key, value = _first_key(payload, _ACTIVITY_ID_KEYS)
    if value is None:
        raise MalformedProviderResponseError(
            "The provider accepted the heatmap request but returned no recognisable activity id.",
            detail={"expectedOneOf": list(_ACTIVITY_ID_KEYS)},
        )
    activity_id = str(value).strip()
    if not activity_id:
        raise MalformedProviderResponseError(
            "The provider returned an empty activity id.", detail={"field": key}
        )
    return activity_id


def _extract_metric(properties: Any) -> tuple[str, float] | None:
    """Find the numeric property that carries the analytic value."""
    if not isinstance(properties, dict):
        return None
    for key in _METRIC_PROPERTY_KEYS:
        if key in properties:
            value = properties[key]
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                return key, float(value)
            if isinstance(value, str):
                try:
                    return key, float(value)
                except ValueError:
                    continue
    # Last resort: the first numeric property in insertion order.
    for key, value in properties.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return str(key), float(value)
    return None


def _iter_features(map_data: Any) -> list[dict[str, Any]]:
    if isinstance(map_data, dict):
        if map_data.get("type") == "FeatureCollection" and isinstance(
            map_data.get("features"), list
        ):
            return [f for f in map_data["features"] if isinstance(f, dict)]
        if map_data.get("type") == "Feature":
            return [map_data]
    if isinstance(map_data, list):
        return [f for f in map_data if isinstance(f, dict) and f.get("type") == "Feature"]
    return []


def parse_map_data(map_data: Any) -> tuple[list[HeatCellRecord], str]:
    """Convert the provider's GeoJSON into persistable heat cells.

    MultiPolygon members are exploded into individual polygons because the
    `heat_cells` table stores one polygon per row, which keeps the GiST index
    selective for stop-level joins.
    """
    features = _iter_features(map_data)
    if not features:
        raise MalformedProviderResponseError(
            "The completed provider response contained no GeoJSON features.",
        )

    cells: list[HeatCellRecord] = []
    metric_names: set[str] = set()
    skipped = 0

    for feature in features:
        geometry_raw = feature.get("geometry")
        metric = _extract_metric(feature.get("properties"))
        if geometry_raw is None or metric is None:
            skipped += 1
            continue
        try:
            geometry = shape(geometry_raw)
        except Exception:
            skipped += 1
            continue
        if geometry.is_empty:
            skipped += 1
            continue
        if not geometry.is_valid:
            geometry = geometry.buffer(0)
            if geometry.is_empty or not geometry.is_valid:
                skipped += 1
                continue

        metric_name, metric_value = metric
        metric_names.add(metric_name)

        parts = list(geometry.geoms) if geometry.geom_type == "MultiPolygon" else [geometry]
        for part in parts:
            if part.geom_type != "Polygon" or part.is_empty:
                skipped += 1
                continue
            cells.append(
                HeatCellRecord(geometry=part, metric_name=metric_name, metric_value=metric_value)
            )

    if not cells:
        raise MalformedProviderResponseError(
            "No usable heat polygons could be read from the provider response.",
            detail={"featuresReceived": len(features), "featuresSkipped": skipped},
        )

    # Mixed metric names would make the score uninterpretable.
    if len(metric_names) > 1:
        raise MalformedProviderResponseError(
            "The provider response mixed multiple metric properties in one heat surface.",
            detail={"metricNames": sorted(metric_names)},
        )

    return cells, next(iter(metric_names))


def parse_status_response(payload: Any) -> ParsedHeatmapResult:
    """Interpret GET /v1/status/{activity_id}.

    A response that carries usable map data is treated as completed even when
    the status token is unfamiliar, because the data is the stronger evidence.
    A response with neither a recognised status nor usable data is malformed.
    """
    notes: dict[str, str] = {}

    status_key, status_raw = _first_key(payload, _STATUS_KEYS)
    status = normalize_status(status_raw)
    if status_key:
        notes["statusField"] = status_key

    activity_key, activity_raw = _first_key(payload, _ACTIVITY_ID_KEYS)
    activity_id = str(activity_raw).strip() if activity_raw is not None else None
    if activity_key:
        notes["activityIdField"] = activity_key

    map_key, map_data = _first_key(payload, _MAP_DATA_KEYS)
    has_map_data = bool(_iter_features(map_data))
    if map_key and has_map_data:
        notes["mapDataField"] = map_key

    if status == ProviderStatusValue.FAILED:
        error_key, error_raw = _first_key(payload, _ERROR_KEYS)
        if error_key:
            notes["errorField"] = error_key
        message = (
            str(error_raw)
            if error_raw is not None
            else "The provider reported a failed activity."
        )
        return ParsedHeatmapResult(
            status=ProviderStatusValue.FAILED,
            activity_id=activity_id,
            error_message=message,
            parse_notes=notes,
        )

    if has_map_data:
        cells, metric_name = parse_map_data(map_data)
        return ParsedHeatmapResult(
            status=ProviderStatusValue.COMPLETED,
            activity_id=activity_id,
            cells=cells,
            metric_name=metric_name,
            parse_notes=notes,
        )

    if status == ProviderStatusValue.COMPLETED:
        raise MalformedProviderResponseError(
            "The provider reported a completed activity but returned no heat surface.",
            detail={"expectedOneOf": list(_MAP_DATA_KEYS)},
        )

    if status == ProviderStatusValue.PROCESSING:
        return ParsedHeatmapResult(
            status=ProviderStatusValue.PROCESSING, activity_id=activity_id, parse_notes=notes
        )

    raise MalformedProviderResponseError(
        "The provider status response was not recognisable as pending, completed, or failed.",
        detail={
            "expectedStatusField": list(_STATUS_KEYS),
            "receivedStatus": str(status_raw) if status_raw is not None else None,
        },
    )
