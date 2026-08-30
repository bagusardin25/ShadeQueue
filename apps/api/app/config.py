"""Application configuration.

Every value is read from the environment so that secrets never live in source
control. `FORTYGUARD_API_KEY` and `DATABASE_URL` must only ever exist in
protected service variables (plan section 16).
"""

from __future__ import annotations

import datetime as dt
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# apps/api/app/config.py -> apps/api/app -> apps/api -> apps -> repository root
REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES_DIR = REPO_ROOT / "fixtures"
WEB_DIST_DIR = REPO_ROOT / "apps" / "web" / "dist"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = "local"
    #: auto = live sources in production, fixtures otherwise. live/fixture force one path.
    source_mode: str = "auto"
    refresh_sources: bool = False

    database_url: str = "postgresql+psycopg://shadequeue:shadequeue@127.0.0.1:55432/shadequeue"

    # --- provider ---
    fortyguard_api_key: str = ""
    fortyguard_base_url: str = "https://api.fortyguard.com"
    fortyguard_api_key_header: str = "api-key"  # FortyGuard dashboard / products sample
    fortyguard_api_key_prefix: str = ""
    live_provider_enabled: bool = False

    # --- credit and abuse protection ---
    max_live_jobs_per_day: int = 25
    max_live_jobs_per_client_per_day: int = 5
    max_aoi_area_km2: float = 25.0
    allowed_date_min: dt.date = dt.date(2024, 6, 1)
    allowed_date_max: dt.date = dt.date(2026, 8, 31)
    max_request_body_bytes: int = 256_000

    # --- provider timing ---
    provider_connect_timeout_seconds: float = 5.0
    provider_read_timeout_seconds: float = 20.0
    provider_poll_interval_seconds: int = 3
    provider_job_timeout_seconds: int = 600
    fixture_processing_seconds: int = 3

    # --- frontend ---
    map_style_url: str = "https://demotiles.maplibre.org/style.json"
    cors_allow_origins: str = "http://127.0.0.1:5173,http://localhost:5173,https://shadequeue-web.vercel.app,https://shadequeue-app-production.up.railway.app"

    # --- optimizer ---
    solver_time_limit_seconds: float = 10.0

    @field_validator("database_url")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        """Accept the bare `postgresql://` URL that hosting platforms inject.

        Railway and most managed providers publish `postgresql://...`, which
        SQLAlchemy would route to the synchronous psycopg2 driver. The whole
        request path here is async, so the driver is pinned explicitly.
        """
        if value.startswith("postgresql+"):
            return value
        if value.startswith("postgresql://"):
            return "postgresql+psycopg://" + value[len("postgresql://") :]
        if value.startswith("postgres://"):
            return "postgresql+psycopg://" + value[len("postgres://") :]
        return value

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]

    @property
    def provider_configured(self) -> bool:
        return bool(self.fortyguard_api_key)

    @property
    def live_provider_available(self) -> bool:
        """Live mode requires both the switch and a credential.

        Returning fixture-shaped success from a misconfigured live deployment is
        forbidden (plan section 13), so this is checked before every submission
        and surfaced in the response mode.
        """
        return self.live_provider_enabled and self.provider_configured


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()


class ProviderDefaults:
    """Constants derived from the published FortyGuard OpenAPI document.

    Source: https://api.fortyguard.com/openapi.json (HeatmapSubmitRequest,
    DateTimeRange). The response schemas for POST /v1/heatmap and
    GET /v1/status/{activity_id} are declared as empty objects in that spec, so
    they are parsed defensively in app.integrations.fortyguard.schemas.
    """

    HEATMAP_PATH = "/v1/heatmap"
    STATUS_PATH = "/v1/status/{activity_id}"

    ANALYTIC_TYPES = ("tcm", "time_of_measure", "exceedance", "persistence")
    GRANULARITIES = (60, 80, 100)
    DIRECTIONS = ("above", "below")
    # 1=single hour, 2=range of hours, 3=single day, 4=range of days
    FILTER_TYPES = (1, 2, 3, 4)

    #: The MVP submits `exceedance`, producing hours over a labelled comparison
    #: threshold. This is an analysis parameter, not a medical or safety limit.
    DEFAULT_ANALYTIC_TYPE = "exceedance"
    DEFAULT_GRANULARITY = 100
    DEFAULT_DIRECTION = "above"
    #: FortyGuard expresses `threshold` in degrees Celsius.
    DEFAULT_THRESHOLD_CELSIUS = 40.0
