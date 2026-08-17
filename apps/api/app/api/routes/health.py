"""Readiness reporting that never exposes a secret."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.api.schemas import HealthResponse
from app.config import settings
from app.db.session import get_session

router = APIRouter(tags=["health"])


@router.get("/api/health", response_model=HealthResponse)
async def health(response: Response, session: AsyncSession = Depends(get_session)) -> HealthResponse:
    database = "ok"
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        # The reason is deliberately not returned: a connection error can
        # contain the database host and user.
        database = "unavailable"

    status = "ok" if database == "ok" else "degraded"
    if status != "ok":
        response.status_code = 503

    return HealthResponse(
        status=status,
        app_env=settings.app_env,
        database=database,
        provider_configured=settings.provider_configured,
        live_provider_enabled=settings.live_provider_available,
        version=__version__,
    )
