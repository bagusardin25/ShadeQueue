"""Scenario creation and portfolio execution.

For the expected 100-200 stops the optimization runs synchronously. CP-SAT is
CPU-bound and blocking, so it is dispatched to a worker thread rather than
stalling the event loop.
"""

from __future__ import annotations

import datetime as dt
import importlib.metadata
import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import anyio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import HeatJob, PortfolioItem, PortfolioRun, Scenario
from app.domain import reason_codes as rc
from app.domain.errors import ConflictError, EmptyCorridorError, ResourceNotFoundError
from app.domain.runtime_mode import (
    HeatJobState,
    PortfolioRunState,
    RuntimeMode,
    effective_runtime_mode,
)
from app.domain.scoring import (
    FORMULA_VERSION,
    INTEGER_SCALE_FACTOR,
    ScoredStop,
    score_candidates,
)
from app.optimizer.baseline import BASELINE_LABEL, BASELINE_NAME, select_baseline
from app.optimizer.cpsat import OptimizerConstraints, objective_value_for, solve_portfolio
from app.services import audit, snapshots, spatial
from app.services.audit import EventType, ObjectType


@lru_cache(maxsize=1)
def _solver_version() -> str:
    """The installed OR-Tools version, recorded on every run for reproducibility."""
    try:
        return f"ortools-cpsat-{importlib.metadata.version('ortools')}"
    except importlib.metadata.PackageNotFoundError:
        return "ortools-cpsat-unknown"


@dataclass(frozen=True)
class ScenarioRequest:
    heat_job_id: uuid.UUID
    name: str
    shelter_slots: int
    equity_weight: float
    minimum_equity_share: float


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


async def create_scenario(session: AsyncSession, request: ScenarioRequest) -> Scenario:
    job = await session.get(HeatJob, request.heat_job_id)
    if job is None:
        raise ResourceNotFoundError("No heat job exists with that identifier.")
    if job.state != HeatJobState.COMPLETED:
        raise ConflictError(
            "A scenario can only be created from a completed heat job.",
            detail={"heatJobState": job.state},
        )

    scenario = Scenario(
        id=uuid.uuid4(),
        name=request.name,
        heat_job_id=job.id,
        shelter_slots=request.shelter_slots,
        equity_weight=request.equity_weight,
        minimum_equity_share=request.minimum_equity_share,
        formula_version=FORMULA_VERSION,
    )
    session.add(scenario)
    await session.flush()

    await audit.record_event(
        session,
        object_type=ObjectType.SCENARIO,
        object_id=str(scenario.id),
        event_type=EventType.SCENARIO_CREATED,
        payload={
            "heatJobId": str(job.id),
            "shelterSlots": request.shelter_slots,
            "equityWeight": request.equity_weight,
            "minimumEquityShare": request.minimum_equity_share,
            "formulaVersion": FORMULA_VERSION,
        },
    )
    await session.commit()
    return scenario


async def get_scenario(session: AsyncSession, scenario_id: uuid.UUID) -> Scenario:
    scenario = await session.get(Scenario, scenario_id)
    if scenario is None:
        raise ResourceNotFoundError("No scenario exists with that identifier.")
    return scenario


async def get_run(session: AsyncSession, run_id: uuid.UUID) -> PortfolioRun:
    run = await session.get(PortfolioRun, run_id)
    if run is None:
        raise ResourceNotFoundError("No portfolio run exists with that identifier.")
    return run


async def list_run_items(session: AsyncSession, run_id: uuid.UUID) -> list[PortfolioItem]:
    result = await session.execute(
        select(PortfolioItem)
        .where(PortfolioItem.run_id == run_id)
        .order_by(PortfolioItem.final_score.desc(), PortfolioItem.stop_id)
    )
    return list(result.scalars().all())


async def execute_run(session: AsyncSession, scenario: Scenario) -> PortfolioRun:
    """Run the baseline and the constrained optimizer for one scenario."""
    job = await session.get(HeatJob, scenario.heat_job_id)
    if job is None:
        raise ResourceNotFoundError("The scenario references a heat job that no longer exists.")
    if job.state != HeatJobState.COMPLETED:
        raise ConflictError(
            "The heat job for this scenario has not completed.",
            detail={"heatJobState": job.state},
        )

    aoi_geojson = job.request_payload["aoi"]
    mode = effective_runtime_mode(stored_mode=job.runtime_mode, reuse_count=job.reuse_count or 0)

    run = PortfolioRun(
        id=uuid.uuid4(),
        scenario_id=scenario.id,
        state=PortfolioRunState.RUNNING,
        integer_scale_factor=INTEGER_SCALE_FACTOR,
        runtime_mode=mode.value,
        source_versions={},
        constraints_payload={},
    )
    session.add(run)
    await session.flush()
    await audit.record_event(
        session,
        object_type=ObjectType.PORTFOLIO_RUN,
        object_id=str(run.id),
        event_type=EventType.PORTFOLIO_RUN_STARTED,
        payload={"scenarioId": str(scenario.id), "runtimeMode": mode.value},
    )
    await session.commit()

    candidates = await spatial.load_candidates(
        session, heat_job_id=job.id, aoi_geojson=aoi_geojson
    )
    if not candidates:
        run.state = PortfolioRunState.FAILED
        run.infeasible_reason = "No bus stops were found inside the requested corridor."
        run.completed_at = _now()
        await session.commit()
        raise EmptyCorridorError(
            "No bus stops were found inside the requested corridor.",
            detail={"runId": str(run.id)},
        )

    scored = score_candidates(candidates, equity_weight=scenario.equity_weight)
    baseline_ids = select_baseline(scored, scenario.shelter_slots)

    constraints = OptimizerConstraints(
        shelter_slots=scenario.shelter_slots,
        minimum_equity_share=scenario.minimum_equity_share,
    )
    result = await anyio.to_thread.run_sync(
        lambda: solve_portfolio(
            scored, constraints, time_limit_seconds=settings.solver_time_limit_seconds
        )
    )

    source_versions = {
        "sources": [
            snapshots.heat_job_source_entry(job),
            *await snapshots.snapshots_used_for(session, aoi_geojson),
        ],
        "formulaVersion": FORMULA_VERSION,
        "metricName": "Hours above the comparison threshold",
        "analyticType": job.request_payload.get("analyticType"),
        "thresholdCelsius": job.request_payload.get("thresholdCelsius"),
    }

    run.source_versions = source_versions
    run.solver_status = result.solver_status_name
    run.solver_version = _solver_version()
    run.solver_wall_time_seconds = result.wall_time_seconds
    run.state = result.state
    run.constraints_payload = {
        "shelterSlots": scenario.shelter_slots,
        "equityWeight": scenario.equity_weight,
        "minimumEquityShare": scenario.minimum_equity_share,
        "equityPercentileThreshold": constraints.equity_percentile_threshold,
        "requiredEquityStops": result.equity_stops_required,
        "selectedEquityStops": result.equity_stops_selected,
        "eligibleStops": result.eligible_stop_count,
        "candidateStops": len(scored),
        "integerScaleFactor": INTEGER_SCALE_FACTOR,
        "baselineName": BASELINE_NAME,
        "baselineLabel": BASELINE_LABEL,
        "solverTimeLimitSeconds": settings.solver_time_limit_seconds,
        "infeasibleDetail": result.infeasible_detail,
    }
    run.infeasible_reason = result.infeasible_reason
    run.completed_at = _now()

    selected_ids = set(result.selected_stop_ids)
    baseline_id_set = set(baseline_ids)
    if result.succeeded:
        run.objective_value = result.objective_value
        run.baseline_value = objective_value_for(scored, baseline_ids)
    else:
        run.objective_value = None
        run.baseline_value = objective_value_for(scored, baseline_ids)

    _persist_items(
        session,
        run=run,
        scored=scored,
        selected_ids=selected_ids,
        baseline_ids=baseline_id_set,
        equity_threshold=constraints.equity_percentile_threshold,
    )

    await audit.record_event(
        session,
        object_type=ObjectType.PORTFOLIO_RUN,
        object_id=str(run.id),
        event_type=(
            EventType.PORTFOLIO_RUN_COMPLETED
            if result.succeeded
            else EventType.PORTFOLIO_RUN_INFEASIBLE
        ),
        payload={
            "state": run.state,
            "solverStatus": run.solver_status,
            "objectiveValue": run.objective_value,
            "baselineValue": run.baseline_value,
            "selectedStops": sorted(selected_ids),
            "infeasibleReason": run.infeasible_reason,
        },
    )
    await session.commit()
    return run


def _persist_items(
    session: AsyncSession,
    *,
    run: PortfolioRun,
    scored: list[ScoredStop],
    selected_ids: set[str],
    baseline_ids: set[str],
    equity_threshold: float,
) -> None:
    """Store one row per candidate stop, including the ones that lost.

    Rank is assigned across every eligible stop, so the audit shows the full
    ordering rather than only the winners.
    """
    rank_counter = 0
    for stop in scored:
        rank: int | None = None
        if stop.eligible:
            rank_counter += 1
            rank = rank_counter

        reasons = list(stop.reason_codes)
        if stop.stop_id in selected_ids and not reasons:
            reasons.append(rc.BALANCED_PORTFOLIO_VALUE)

        session.add(
            PortfolioItem(
                run_id=run.id,
                stop_id=stop.stop_id,
                selected=stop.stop_id in selected_ids,
                baseline_selected=stop.stop_id in baseline_ids,
                eligible=stop.eligible,
                rank=rank,
                location_name=stop.location_name,
                longitude=stop.longitude,
                latitude=stop.latitude,
                shelter_count=stop.shelter_count,
                ridership_value=stop.ridership_value,
                exceedance_hours=stop.exceedance_hours,
                svi_percentile=stop.svi_percentile,
                heat_component=stop.heat_component,
                ridership_component=stop.ridership_component,
                equity_component=stop.equity_component,
                final_score=stop.final_score,
                heat_join_method=stop.heat_join_method,
                reason_codes=reasons,
            )
        )


def runtime_mode_of(run: PortfolioRun) -> RuntimeMode:
    return RuntimeMode(run.runtime_mode)


def summarize_run(run: PortfolioRun) -> dict[str, Any]:
    return {
        "runId": str(run.id),
        "state": run.state,
        "solverStatus": run.solver_status,
        "objectiveValue": run.objective_value,
        "baselineValue": run.baseline_value,
    }
