"""Authoritative data model (plan section 8).

Geometry columns are SRID 4326 and carry GiST indexes because every candidate
query is a spatial join. State columns are plain strings guarded by check
constraints rather than native enums, which keeps migrations reversible.
"""

from __future__ import annotations

import datetime as dt
import uuid

from geoalchemy2 import Geometry
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.domain.runtime_mode import HeatJobState, PortfolioRunState, RuntimeMode

_HEAT_JOB_STATES = tuple(state.value for state in HeatJobState)
_RUNTIME_MODES = tuple(mode.value for mode in RuntimeMode)
_RUN_STATES = tuple(state.value for state in PortfolioRunState)


def _in_list(column: str, values: tuple[str, ...]) -> str:
    rendered = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({rendered})"


class SourceSnapshot(Base):
    """One retrieval of one external dataset, with its provenance."""

    __tablename__ = "source_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_name: Mapped[str] = mapped_column(String(120), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_version: Mapped[str] = mapped_column(String(200), nullable=False)
    retrieved_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    license_note: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(_in_list("evidence_mode", _RUNTIME_MODES), name="ck_source_snapshots_mode"),
        Index("ix_source_snapshots_name_retrieved", "source_name", "retrieved_at"),
    )


class BusStop(Base):
    __tablename__ = "bus_stops"

    stop_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    location_name: Mapped[str] = mapped_column(Text, nullable=False)
    shelter_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ridership_value: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    geom: Mapped[object] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=True), nullable=False
    )
    source_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_snapshots.id", ondelete="RESTRICT"), nullable=False
    )

    __table_args__ = (
        CheckConstraint("shelter_count >= 0", name="ck_bus_stops_shelter_count"),
        CheckConstraint("ridership_value >= 0", name="ck_bus_stops_ridership"),
    )


class SviTract(Base):
    __tablename__ = "svi_tracts"

    geoid: Mapped[str] = mapped_column(String(20), primary_key=True)
    overall_percentile: Mapped[float] = mapped_column(Float, nullable=False)
    geom: Mapped[object] = mapped_column(
        Geometry(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=True), nullable=False
    )
    source_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_snapshots.id", ondelete="RESTRICT"), nullable=False
    )

    __table_args__ = (
        # CDC publishes -999 for suppressed tracts; ingestion must drop or
        # translate those before they reach this table.
        CheckConstraint(
            "overall_percentile >= 0 AND overall_percentile <= 1",
            name="ck_svi_tracts_percentile_range",
        ),
    )


class HeatJob(Base):
    """One FortyGuard heatmap request and its durable local state."""

    __tablename__ = "heat_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider_activity_id: Mapped[str | None] = mapped_column(String(200))
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default=HeatJobState.SUBMITTED)
    runtime_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    request_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    provider_response: Mapped[dict | None] = mapped_column(JSONB)
    next_provider_poll_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    last_checked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    #: How many later requests reused this result. Extends plan section 8 so the
    #: LIVE / CACHED_LIVE distinction is derived from a stored fact rather than
    #: guessed from timestamps.
    reuse_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    client_fingerprint: Mapped[str | None] = mapped_column(String(64))

    heat_cells: Mapped[list[HeatCell]] = relationship(
        back_populates="heat_job", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(_in_list("state", _HEAT_JOB_STATES), name="ck_heat_jobs_state"),
        CheckConstraint(_in_list("runtime_mode", _RUNTIME_MODES), name="ck_heat_jobs_runtime_mode"),
        CheckConstraint("reuse_count >= 0", name="ck_heat_jobs_reuse_count"),
        # A FAILED job must not block a genuine retry, so the uniqueness that
        # stops duplicate concurrent submissions is partial.
        Index(
            "uq_heat_jobs_active_request_hash",
            "request_hash",
            unique=True,
            postgresql_where=text("state <> 'FAILED'"),
        ),
        Index("ix_heat_jobs_state_poll", "state", "next_provider_poll_at"),
        Index("ix_heat_jobs_created_at", "created_at"),
    )


class HeatCell(Base):
    """One polygon of the provider's returned heat surface."""

    __tablename__ = "heat_cells"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    heat_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("heat_jobs.id", ondelete="CASCADE"), nullable=False
    )
    metric_name: Mapped[str] = mapped_column(String(64), nullable=False)
    metric_value: Mapped[float] = mapped_column(Float, nullable=False)
    geom: Mapped[object] = mapped_column(
        Geometry(geometry_type="POLYGON", srid=4326, spatial_index=True), nullable=False
    )

    heat_job: Mapped[HeatJob] = relationship(back_populates="heat_cells")

    __table_args__ = (Index("ix_heat_cells_job", "heat_job_id"),)


class Scenario(Base):
    __tablename__ = "scenarios"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    heat_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("heat_jobs.id", ondelete="RESTRICT"), nullable=False
    )
    shelter_slots: Mapped[int] = mapped_column(Integer, nullable=False)
    equity_weight: Mapped[float] = mapped_column(Float, nullable=False)
    minimum_equity_share: Mapped[float] = mapped_column(Float, nullable=False)
    formula_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    heat_job: Mapped[HeatJob] = relationship()

    __table_args__ = (
        CheckConstraint("shelter_slots > 0", name="ck_scenarios_slots_positive"),
        CheckConstraint(
            "equity_weight >= 0 AND equity_weight <= 1", name="ck_scenarios_equity_weight"
        ),
        CheckConstraint(
            "minimum_equity_share >= 0 AND minimum_equity_share <= 1",
            name="ck_scenarios_min_equity_share",
        ),
        Index("ix_scenarios_heat_job", "heat_job_id"),
    )


class PortfolioRun(Base):
    __tablename__ = "portfolio_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scenario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False
    )
    state: Mapped[str] = mapped_column(String(20), nullable=False, default=PortfolioRunState.RUNNING)
    solver_status: Mapped[str | None] = mapped_column(String(40))
    solver_version: Mapped[str | None] = mapped_column(String(40))
    objective_value: Mapped[float | None] = mapped_column(Float)
    baseline_value: Mapped[float | None] = mapped_column(Float)
    integer_scale_factor: Mapped[int] = mapped_column(Integer, nullable=False)
    source_versions: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'"))
    runtime_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    constraints_payload: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'")
    )
    infeasible_reason: Mapped[str | None] = mapped_column(Text)
    solver_wall_time_seconds: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    scenario: Mapped[Scenario] = relationship()
    items: Mapped[list[PortfolioItem]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(_in_list("state", _RUN_STATES), name="ck_portfolio_runs_state"),
        CheckConstraint(_in_list("runtime_mode", _RUNTIME_MODES), name="ck_portfolio_runs_mode"),
        Index("ix_portfolio_runs_scenario", "scenario_id", "created_at"),
    )


class PortfolioItem(Base):
    __tablename__ = "portfolio_items"

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("portfolio_runs.id", ondelete="CASCADE"), primary_key=True
    )
    stop_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    selected: Mapped[bool] = mapped_column(nullable=False, default=False)
    baseline_selected: Mapped[bool] = mapped_column(nullable=False, default=False)
    eligible: Mapped[bool] = mapped_column(nullable=False, default=True)
    rank: Mapped[int | None] = mapped_column(Integer)
    location_name: Mapped[str] = mapped_column(Text, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    shelter_count: Mapped[int] = mapped_column(Integer, nullable=False)
    ridership_value: Mapped[float] = mapped_column(Float, nullable=False)
    exceedance_hours: Mapped[float] = mapped_column(Float, nullable=False)
    svi_percentile: Mapped[float] = mapped_column(Float, nullable=False)
    heat_component: Mapped[float] = mapped_column(Float, nullable=False)
    ridership_component: Mapped[float] = mapped_column(Float, nullable=False)
    equity_component: Mapped[float] = mapped_column(Float, nullable=False)
    final_score: Mapped[float] = mapped_column(Float, nullable=False)
    heat_join_method: Mapped[str] = mapped_column(String(20), nullable=False)
    reason_codes: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'"))

    run: Mapped[PortfolioRun] = relationship(back_populates="items")

    __table_args__ = (
        UniqueConstraint("run_id", "rank", name="uq_portfolio_items_run_rank"),
        Index("ix_portfolio_items_run_selected", "run_id", "selected"),
    )


class AuditEvent(Base):
    """Append-only trail linking a provider activity to a rendered result."""

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    object_type: Mapped[str] = mapped_column(String(40), nullable=False)
    object_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    event_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'"))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        Index("ix_audit_events_object", "object_type", "object_id", "created_at"),
        Index("ix_audit_events_correlation", "correlation_id"),
    )
