"""Append-only audit trail.

Audit rows are written in the same transaction as the change they describe, so
a rolled-back request leaves no misleading trace.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditEvent
from app.services.correlation import get_correlation_id


class ObjectType:
    HEAT_JOB = "heat_job"
    SCENARIO = "scenario"
    PORTFOLIO_RUN = "portfolio_run"
    SOURCE_SNAPSHOT = "source_snapshot"


class EventType:
    HEAT_JOB_SUBMITTED = "heat_job.submitted"
    HEAT_JOB_REUSED = "heat_job.reused"
    HEAT_JOB_STATE_CHANGED = "heat_job.state_changed"
    HEAT_JOB_PROVIDER_CHECKED = "heat_job.provider_checked"
    HEAT_JOB_PROVIDER_ERROR = "heat_job.provider_error"
    SCENARIO_CREATED = "scenario.created"
    PORTFOLIO_RUN_STARTED = "portfolio_run.started"
    PORTFOLIO_RUN_COMPLETED = "portfolio_run.completed"
    PORTFOLIO_RUN_INFEASIBLE = "portfolio_run.infeasible"
    PORTFOLIO_RUN_EXPORTED = "portfolio_run.exported"
    SOURCE_SNAPSHOT_RECORDED = "source_snapshot.recorded"


async def record_event(
    session: AsyncSession,
    *,
    object_type: str,
    object_id: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        correlation_id=get_correlation_id(),
        object_type=object_type,
        object_id=str(object_id),
        event_type=event_type,
        event_payload=payload or {},
    )
    session.add(event)
    return event
