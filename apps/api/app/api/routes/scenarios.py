"""Scenario endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.presenters import heat_job_response, portfolio_run_response
from app.api.schemas import (
    PortfolioRunResponse,
    ScenarioCreateRequest,
    ScenarioResponse,
)
from app.db.models import PortfolioRun
from app.db.session import get_session
from app.services import heat_jobs as heat_job_service
from app.services import portfolio as service

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


async def _latest_run_id(session: AsyncSession, scenario_id: uuid.UUID) -> uuid.UUID | None:
    result = await session.execute(
        select(PortfolioRun.id)
        .where(PortfolioRun.scenario_id == scenario_id)
        .order_by(PortfolioRun.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _scenario_response(session: AsyncSession, scenario) -> ScenarioResponse:
    job = await heat_job_service.get_heat_job(session, scenario.heat_job_id)
    cells = await heat_job_service.count_heat_cells(session, job.id)
    return ScenarioResponse(
        scenario_id=scenario.id,
        name=scenario.name,
        heat_job_id=scenario.heat_job_id,
        shelter_slots=scenario.shelter_slots,
        equity_weight=scenario.equity_weight,
        minimum_equity_share=scenario.minimum_equity_share,
        formula_version=scenario.formula_version,
        created_at=scenario.created_at,
        heat_job=heat_job_response(job, heat_cell_count=cells),
        latest_run_id=await _latest_run_id(session, scenario.id),
    )


@router.post("", response_model=ScenarioResponse, status_code=status.HTTP_201_CREATED)
async def create_scenario(
    payload: ScenarioCreateRequest,
    session: AsyncSession = Depends(get_session),
) -> ScenarioResponse:
    scenario = await service.create_scenario(
        session,
        service.ScenarioRequest(
            heat_job_id=payload.heat_job_id,
            name=payload.name,
            shelter_slots=payload.shelter_slots,
            equity_weight=payload.equity_weight,
            minimum_equity_share=payload.minimum_equity_share,
        ),
    )
    return await _scenario_response(session, scenario)


@router.get("/{scenario_id}", response_model=ScenarioResponse)
async def read_scenario(
    scenario_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> ScenarioResponse:
    """Restore the configuration and the current source status."""
    scenario = await service.get_scenario(session, scenario_id)
    return await _scenario_response(session, scenario)


@router.post(
    "/{scenario_id}/runs",
    response_model=PortfolioRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_run(
    scenario_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> PortfolioRunResponse:
    """Execute the baseline and the constrained portfolio optimizer.

    An infeasible constraint set is a 201 with state INFEASIBLE and an
    explanation, not an error: the run happened and its outcome is recorded.
    """
    scenario = await service.get_scenario(session, scenario_id)
    run = await service.execute_run(session, scenario)
    items = await service.list_run_items(session, run.id)
    return portfolio_run_response(run=run, scenario=scenario, items=items)
