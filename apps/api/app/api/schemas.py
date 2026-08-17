"""Request and response contracts.

Field names are serialised in camelCase to match the browser client, while the
Python attributes stay snake_case. FastAPI and Pydantic own the OpenAPI
document; the frontend still parses critical responses at runtime rather than
trusting generated types.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from app.config import ProviderDefaults
from app.domain.aoi import fahrenheit_to_celsius


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )


# --- errors ------------------------------------------------------------------


class ErrorResponse(ApiModel):
    code: str
    message: str
    detail: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str


# --- heat jobs ---------------------------------------------------------------


class HeatJobCreateRequest(ApiModel):
    aoi: dict[str, Any] = Field(description="GeoJSON Polygon or MultiPolygon inside the allowed corridor")
    start_date: dt.date
    filter_type: Literal[1, 2, 3, 4] = Field(
        default=3, description="1=single hour, 2=range of hours, 3=single day, 4=range of days"
    )
    end_date: dt.date | None = None
    start_time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    end_time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    analytic_type: Literal["tcm", "time_of_measure", "exceedance", "persistence"] = (
        ProviderDefaults.DEFAULT_ANALYTIC_TYPE
    )
    #: FortyGuard expresses the threshold in Celsius. Fahrenheit is accepted as a
    #: convenience for a US-facing interface and converted before hashing, so the
    #: two spellings of the same request share one cached result.
    threshold_celsius: float | None = None
    threshold_fahrenheit: float | None = None
    direction: Literal["above", "below"] | None = ProviderDefaults.DEFAULT_DIRECTION
    granularity: Literal[60, 80, 100] = ProviderDefaults.DEFAULT_GRANULARITY

    @model_validator(mode="after")
    def _resolve_threshold(self) -> HeatJobCreateRequest:
        if self.threshold_celsius is not None and self.threshold_fahrenheit is not None:
            converted = fahrenheit_to_celsius(self.threshold_fahrenheit)
            if abs(converted - self.threshold_celsius) > 0.01:
                raise ValueError(
                    "thresholdCelsius and thresholdFahrenheit describe different temperatures"
                )
        elif self.threshold_celsius is None and self.threshold_fahrenheit is not None:
            self.threshold_celsius = round(fahrenheit_to_celsius(self.threshold_fahrenheit), 4)
        elif self.threshold_celsius is None:
            self.threshold_celsius = ProviderDefaults.DEFAULT_THRESHOLD_CELSIUS
        return self


class HeatJobResponse(ApiModel):
    job_id: uuid.UUID
    state: str
    runtime_mode: str
    provider_activity_id: str | None
    request_hash: str
    analytic_type: str | None
    threshold_celsius: float | None
    threshold_fahrenheit: float | None
    aoi: dict[str, Any]
    aoi_area_km2: float | None
    heat_cell_count: int
    reused: bool
    reuse_count: int
    created_at: dt.datetime
    completed_at: dt.datetime | None
    last_checked_at: dt.datetime | None
    next_provider_poll_at: dt.datetime | None
    error_code: str | None
    error_message: str | None
    #: Present so the UI can say "Stopped checking" without implying that the
    #: provider activity was cancelled.
    poll_recommended: bool


# --- scenarios ---------------------------------------------------------------


class ScenarioCreateRequest(ApiModel):
    heat_job_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)
    shelter_slots: int = Field(default=10, ge=1, le=200)
    equity_weight: float = Field(default=0.45, ge=0.0, le=1.0)
    minimum_equity_share: float = Field(default=0.4, ge=0.0, le=1.0)


class ScenarioResponse(ApiModel):
    scenario_id: uuid.UUID
    name: str
    heat_job_id: uuid.UUID
    shelter_slots: int
    equity_weight: float
    minimum_equity_share: float
    formula_version: str
    created_at: dt.datetime
    heat_job: HeatJobResponse
    latest_run_id: uuid.UUID | None


# --- portfolio runs ----------------------------------------------------------


class PortfolioStop(ApiModel):
    stop_id: str
    name: str
    longitude: float
    latitude: float
    shelter_count: int
    ridership_value: float
    exceedance_hours: float
    svi_percentile: float
    heat_component: float
    ridership_component: float
    equity_component: float
    final_score: float
    selected: bool
    baseline_selected: bool
    eligible: bool
    rank: int | None
    heat_join_method: str
    reason_codes: list[str]


class SourceVersion(ApiModel):
    name: str
    url: str | None = None
    version: str
    retrieved_at: str | None = None
    checksum: str | None = None
    evidence_mode: str | None = None
    license_note: str | None = None


class PortfolioRunResponse(ApiModel):
    run_id: uuid.UUID
    scenario_id: uuid.UUID
    scenario_name: str
    state: str
    runtime_mode: str
    solver_status: str | None
    solver_version: str | None
    solver_wall_time_seconds: float | None
    formula_version: str
    integer_scale_factor: int
    objective_value: float | None
    baseline_value: float | None
    shelter_slots: int
    equity_weight: float
    minimum_equity_share: float
    threshold_celsius: float | None
    threshold_fahrenheit: float | None
    metric_name: str
    infeasible_reason: str | None
    constraints: dict[str, Any]
    source_versions: list[SourceVersion]
    reason_code_labels: dict[str, str]
    created_at: dt.datetime
    completed_at: dt.datetime | None
    stops: list[PortfolioStop]


# --- source snapshots --------------------------------------------------------


class SourceSnapshotResponse(ApiModel):
    id: uuid.UUID
    source_name: str
    source_url: str
    source_version: str
    retrieved_at: dt.datetime
    checksum: str
    evidence_mode: str
    license_note: str | None


class SourceSnapshotListResponse(ApiModel):
    snapshots: list[SourceSnapshotResponse]
    live_provider_enabled: bool
    allowed_aoi: dict[str, Any]
    allowed_aoi_name: str
    allowed_date_min: dt.date
    allowed_date_max: dt.date
    max_aoi_area_km2: float
    map_style_url: str


# --- health ------------------------------------------------------------------


class HealthResponse(ApiModel):
    status: Literal["ok", "degraded"]
    app_env: str
    database: Literal["ok", "unavailable"]
    provider_configured: bool
    live_provider_enabled: bool
    version: str
