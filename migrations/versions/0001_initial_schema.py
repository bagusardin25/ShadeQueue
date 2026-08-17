"""Initial ShadeQueue schema with PostGIS geometry and spatial indexes.

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-13
"""

from __future__ import annotations

from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HEAT_JOB_STATES = "'SUBMITTED', 'PROCESSING', 'COMPLETED', 'FAILED'"
RUNTIME_MODES = "'LIVE', 'CACHED_LIVE', 'DEMO_FIXTURE'"
RUN_STATES = "'RUNNING', 'OPTIMAL', 'FEASIBLE', 'INFEASIBLE', 'FAILED'"


def _geometry(kind: str) -> geoalchemy2.Geometry:
    """Geometry column without an implicit index.

    Every spatial index in this schema is created explicitly below so the
    migration is the single source of truth for what exists in the database.
    """
    return geoalchemy2.Geometry(geometry_type=kind, srid=4326, spatial_index=False)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.create_table(
        "source_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_name", sa.String(length=120), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_version", sa.String(length=200), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("evidence_mode", sa.String(length=32), nullable=False),
        sa.Column("license_note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(f"evidence_mode IN ({RUNTIME_MODES})", name="ck_source_snapshots_mode"),
    )
    op.create_index(
        "ix_source_snapshots_name_retrieved", "source_snapshots", ["source_name", "retrieved_at"]
    )

    op.create_table(
        "bus_stops",
        sa.Column("stop_id", sa.String(length=64), nullable=False),
        sa.Column("location_name", sa.Text(), nullable=False),
        sa.Column("shelter_count", sa.Integer(), nullable=False),
        sa.Column("ridership_value", sa.Float(), nullable=False),
        sa.Column("geom", _geometry("POINT"), nullable=False),
        sa.Column("source_snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("stop_id"),
        sa.ForeignKeyConstraint(
            ["source_snapshot_id"], ["source_snapshots.id"], ondelete="RESTRICT"
        ),
        sa.CheckConstraint("shelter_count >= 0", name="ck_bus_stops_shelter_count"),
        sa.CheckConstraint("ridership_value >= 0", name="ck_bus_stops_ridership"),
    )
    op.create_index("idx_bus_stops_geom", "bus_stops", ["geom"], postgresql_using="gist")

    op.create_table(
        "svi_tracts",
        sa.Column("geoid", sa.String(length=20), nullable=False),
        sa.Column("overall_percentile", sa.Float(), nullable=False),
        sa.Column("geom", _geometry("MULTIPOLYGON"), nullable=False),
        sa.Column("source_snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("geoid"),
        sa.ForeignKeyConstraint(
            ["source_snapshot_id"], ["source_snapshots.id"], ondelete="RESTRICT"
        ),
        sa.CheckConstraint(
            "overall_percentile >= 0 AND overall_percentile <= 1",
            name="ck_svi_tracts_percentile_range",
        ),
    )
    op.create_index("idx_svi_tracts_geom", "svi_tracts", ["geom"], postgresql_using="gist")

    op.create_table(
        "heat_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_activity_id", sa.String(length=200), nullable=True),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("runtime_mode", sa.String(length=20), nullable=False),
        sa.Column("request_payload", postgresql.JSONB(), nullable=False),
        sa.Column("provider_response", postgresql.JSONB(), nullable=True),
        sa.Column("next_provider_poll_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("reuse_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("client_fingerprint", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(f"state IN ({HEAT_JOB_STATES})", name="ck_heat_jobs_state"),
        sa.CheckConstraint(f"runtime_mode IN ({RUNTIME_MODES})", name="ck_heat_jobs_runtime_mode"),
        sa.CheckConstraint("reuse_count >= 0", name="ck_heat_jobs_reuse_count"),
    )
    # Partial uniqueness: a duplicate concurrent submission is rejected by the
    # database, while a FAILED job can still be retried.
    op.create_index(
        "uq_heat_jobs_active_request_hash",
        "heat_jobs",
        ["request_hash"],
        unique=True,
        postgresql_where=sa.text("state <> 'FAILED'"),
    )
    op.create_index("ix_heat_jobs_state_poll", "heat_jobs", ["state", "next_provider_poll_at"])
    op.create_index("ix_heat_jobs_created_at", "heat_jobs", ["created_at"])

    op.create_table(
        "heat_cells",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("heat_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("metric_name", sa.String(length=64), nullable=False),
        sa.Column("metric_value", sa.Float(), nullable=False),
        sa.Column("geom", _geometry("POLYGON"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["heat_job_id"], ["heat_jobs.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_heat_cells_job", "heat_cells", ["heat_job_id"])
    op.create_index("idx_heat_cells_geom", "heat_cells", ["geom"], postgresql_using="gist")

    op.create_table(
        "scenarios",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("heat_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("shelter_slots", sa.Integer(), nullable=False),
        sa.Column("equity_weight", sa.Float(), nullable=False),
        sa.Column("minimum_equity_share", sa.Float(), nullable=False),
        sa.Column("formula_version", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["heat_job_id"], ["heat_jobs.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("shelter_slots > 0", name="ck_scenarios_slots_positive"),
        sa.CheckConstraint(
            "equity_weight >= 0 AND equity_weight <= 1", name="ck_scenarios_equity_weight"
        ),
        sa.CheckConstraint(
            "minimum_equity_share >= 0 AND minimum_equity_share <= 1",
            name="ck_scenarios_min_equity_share",
        ),
    )
    op.create_index("ix_scenarios_heat_job", "scenarios", ["heat_job_id"])

    op.create_table(
        "portfolio_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scenario_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("solver_status", sa.String(length=40), nullable=True),
        sa.Column("solver_version", sa.String(length=40), nullable=True),
        sa.Column("objective_value", sa.Float(), nullable=True),
        sa.Column("baseline_value", sa.Float(), nullable=True),
        sa.Column("integer_scale_factor", sa.Integer(), nullable=False),
        sa.Column(
            "source_versions", postgresql.JSONB(), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column("runtime_mode", sa.String(length=20), nullable=False),
        sa.Column(
            "constraints_payload", postgresql.JSONB(), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column("infeasible_reason", sa.Text(), nullable=True),
        sa.Column("solver_wall_time_seconds", sa.Float(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["scenario_id"], ["scenarios.id"], ondelete="CASCADE"),
        sa.CheckConstraint(f"state IN ({RUN_STATES})", name="ck_portfolio_runs_state"),
        sa.CheckConstraint(f"runtime_mode IN ({RUNTIME_MODES})", name="ck_portfolio_runs_mode"),
    )
    op.create_index("ix_portfolio_runs_scenario", "portfolio_runs", ["scenario_id", "created_at"])

    op.create_table(
        "portfolio_items",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stop_id", sa.String(length=64), nullable=False),
        sa.Column("selected", sa.Boolean(), nullable=False),
        sa.Column("baseline_selected", sa.Boolean(), nullable=False),
        sa.Column("eligible", sa.Boolean(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("location_name", sa.Text(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("shelter_count", sa.Integer(), nullable=False),
        sa.Column("ridership_value", sa.Float(), nullable=False),
        sa.Column("exceedance_hours", sa.Float(), nullable=False),
        sa.Column("svi_percentile", sa.Float(), nullable=False),
        sa.Column("heat_component", sa.Float(), nullable=False),
        sa.Column("ridership_component", sa.Float(), nullable=False),
        sa.Column("equity_component", sa.Float(), nullable=False),
        sa.Column("final_score", sa.Float(), nullable=False),
        sa.Column("heat_join_method", sa.String(length=20), nullable=False),
        sa.Column("reason_codes", postgresql.JSONB(), server_default=sa.text("'[]'"), nullable=False),
        sa.PrimaryKeyConstraint("run_id", "stop_id"),
        sa.ForeignKeyConstraint(["run_id"], ["portfolio_runs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("run_id", "rank", name="uq_portfolio_items_run_rank"),
    )
    op.create_index("ix_portfolio_items_run_selected", "portfolio_items", ["run_id", "selected"])

    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("object_type", sa.String(length=40), nullable=False),
        sa.Column("object_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=60), nullable=False),
        sa.Column(
            "event_payload", postgresql.JSONB(), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_audit_events_object", "audit_events", ["object_type", "object_id", "created_at"]
    )
    op.create_index("ix_audit_events_correlation", "audit_events", ["correlation_id"])


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("portfolio_items")
    op.drop_table("portfolio_runs")
    op.drop_table("scenarios")
    op.drop_table("heat_cells")
    op.drop_table("heat_jobs")
    op.drop_table("svi_tracts")
    op.drop_table("bus_stops")
    op.drop_table("source_snapshots")
    # The postgis extension is intentionally left installed: other schemas in
    # the same database may depend on it.
