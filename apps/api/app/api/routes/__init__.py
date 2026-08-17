"""API routers."""

from fastapi import APIRouter

from app.api.routes import heat_jobs, portfolio_runs, scenarios, source_snapshots

v1_router = APIRouter(prefix="/api/v1")
v1_router.include_router(heat_jobs.router)
v1_router.include_router(scenarios.router)
v1_router.include_router(portfolio_runs.router)
v1_router.include_router(source_snapshots.router)

__all__ = ["v1_router"]
