"""Heat job endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import client_fingerprint
from app.api.presenters import heat_job_response
from app.api.schemas import HeatJobCreateRequest, HeatJobResponse
from app.db.session import get_session
from app.services import heat_jobs as service

router = APIRouter(prefix="/heat-jobs", tags=["heat-jobs"])


@router.post("", response_model=HeatJobResponse, status_code=status.HTTP_201_CREATED)
async def create_heat_job(
    payload: HeatJobCreateRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
    fingerprint: str | None = Depends(client_fingerprint),
) -> HeatJobResponse:
    """Validate and deduplicate a request, then submit it to the provider.

    A duplicate of an in-flight or completed request returns 200 with the
    existing job instead of spending provider credit again.
    """
    outcome = await service.submit_heat_job(
        session,
        service.HeatJobRequest(
            aoi=payload.aoi,
            start_date=payload.start_date,
            filter_type=payload.filter_type,
            end_date=payload.end_date,
            start_time=payload.start_time,
            end_time=payload.end_time,
            analytic_type=payload.analytic_type,
            threshold_celsius=payload.threshold_celsius,
            direction=payload.direction,
            granularity=payload.granularity,
        ),
        client_fingerprint=fingerprint,
    )
    if outcome.reused:
        response.status_code = status.HTTP_200_OK

    cells = await service.count_heat_cells(session, outcome.job.id)
    return heat_job_response(outcome.job, heat_cell_count=cells, reused=outcome.reused)


@router.get("/{job_id}", response_model=HeatJobResponse)
async def read_heat_job(
    job_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> HeatJobResponse:
    """Return authoritative local status, refreshing the provider when due."""
    job = await service.get_heat_job(session, job_id)
    job = await service.refresh_if_due(session, job)
    cells = await service.count_heat_cells(session, job.id)
    return heat_job_response(job, heat_cell_count=cells)
