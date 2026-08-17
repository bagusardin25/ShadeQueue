"""Portfolio run endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.presenters import portfolio_run_response
from app.api.schemas import PortfolioRunResponse
from app.db.session import get_session
from app.services import audit, export_csv
from app.services import portfolio as service
from app.services.audit import EventType, ObjectType

router = APIRouter(prefix="/portfolio-runs", tags=["portfolio-runs"])


@router.get("/{run_id}", response_model=PortfolioRunResponse)
async def read_run(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> PortfolioRunResponse:
    run = await service.get_run(session, run_id)
    scenario = await service.get_scenario(session, run.scenario_id)
    items = await service.list_run_items(session, run.id)
    return portfolio_run_response(run=run, scenario=scenario, items=items)


@router.get("/{run_id}/export.csv", response_class=PlainTextResponse)
async def export_run(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> PlainTextResponse:
    """Export an auditable review packet."""
    run = await service.get_run(session, run_id)
    scenario = await service.get_scenario(session, run.scenario_id)
    items = await service.list_run_items(session, run.id)

    body = export_csv.build_csv(run=run, scenario=scenario, items=items)
    await audit.record_event(
        session,
        object_type=ObjectType.PORTFOLIO_RUN,
        object_id=str(run.id),
        event_type=EventType.PORTFOLIO_RUN_EXPORTED,
        payload={"rows": len(items), "runtimeMode": run.runtime_mode},
    )
    await session.commit()

    return PlainTextResponse(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={
            "content-disposition": f'attachment; filename="{export_csv.filename_for(run)}"'
        },
    )
