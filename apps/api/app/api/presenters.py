"""Database records to API responses."""

from __future__ import annotations

from app.api.schemas import (
    HeatJobResponse,
    PortfolioRunResponse,
    PortfolioStop,
    SourceVersion,
)
from app.db.models import HeatJob, PortfolioItem, PortfolioRun, Scenario
from app.domain.aoi import celsius_to_fahrenheit
from app.domain.reason_codes import REASON_CODE_LABELS
from app.domain.runtime_mode import HeatJobState, effective_runtime_mode


def heat_job_response(job: HeatJob, *, heat_cell_count: int, reused: bool = False) -> HeatJobResponse:
    payload = job.request_payload or {}
    threshold_c = payload.get("thresholdCelsius")
    mode = effective_runtime_mode(stored_mode=job.runtime_mode, reuse_count=job.reuse_count or 0)
    return HeatJobResponse(
        job_id=job.id,
        state=job.state,
        runtime_mode=mode.value,
        provider_activity_id=job.provider_activity_id,
        request_hash=job.request_hash,
        analytic_type=payload.get("analyticType"),
        threshold_celsius=threshold_c,
        threshold_fahrenheit=(
            round(celsius_to_fahrenheit(threshold_c), 2) if threshold_c is not None else None
        ),
        aoi=payload.get("aoi", {}),
        aoi_area_km2=payload.get("aoiAreaKm2"),
        heat_cell_count=heat_cell_count,
        reused=reused,
        reuse_count=job.reuse_count or 0,
        created_at=job.created_at,
        completed_at=job.completed_at,
        last_checked_at=job.last_checked_at,
        next_provider_poll_at=job.next_provider_poll_at,
        error_code=job.error_code,
        error_message=job.error_message,
        poll_recommended=job.state in {HeatJobState.SUBMITTED, HeatJobState.PROCESSING},
    )


def portfolio_stop(item: PortfolioItem) -> PortfolioStop:
    return PortfolioStop(
        stop_id=item.stop_id,
        name=item.location_name,
        longitude=item.longitude,
        latitude=item.latitude,
        shelter_count=item.shelter_count,
        ridership_value=item.ridership_value,
        exceedance_hours=item.exceedance_hours,
        svi_percentile=item.svi_percentile,
        heat_component=item.heat_component,
        ridership_component=item.ridership_component,
        equity_component=item.equity_component,
        final_score=item.final_score,
        selected=item.selected,
        baseline_selected=item.baseline_selected,
        eligible=item.eligible,
        rank=item.rank,
        heat_join_method=item.heat_join_method,
        reason_codes=list(item.reason_codes or []),
    )


def portfolio_run_response(
    *,
    run: PortfolioRun,
    scenario: Scenario,
    items: list[PortfolioItem],
) -> PortfolioRunResponse:
    versions = run.source_versions or {}
    threshold_c = versions.get("thresholdCelsius")
    sources = [SourceVersion(**source) for source in versions.get("sources", [])]

    # Only the labels for codes that actually appear, so the UI legend stays
    # honest about what this run produced.
    present_codes = {code for item in items for code in (item.reason_codes or [])}
    labels = {code: REASON_CODE_LABELS.get(code, code) for code in sorted(present_codes)}

    return PortfolioRunResponse(
        run_id=run.id,
        scenario_id=scenario.id,
        scenario_name=scenario.name,
        state=run.state,
        runtime_mode=run.runtime_mode,
        solver_status=run.solver_status,
        solver_version=run.solver_version,
        solver_wall_time_seconds=run.solver_wall_time_seconds,
        formula_version=scenario.formula_version,
        integer_scale_factor=run.integer_scale_factor,
        objective_value=run.objective_value,
        baseline_value=run.baseline_value,
        shelter_slots=scenario.shelter_slots,
        equity_weight=scenario.equity_weight,
        minimum_equity_share=scenario.minimum_equity_share,
        threshold_celsius=threshold_c,
        threshold_fahrenheit=(
            round(celsius_to_fahrenheit(threshold_c), 2) if threshold_c is not None else None
        ),
        metric_name=versions.get("metricName", "Hours above the comparison threshold"),
        infeasible_reason=run.infeasible_reason,
        constraints=run.constraints_payload or {},
        source_versions=sources,
        reason_code_labels=labels,
        created_at=run.created_at,
        completed_at=run.completed_at,
        stops=[portfolio_stop(item) for item in items],
    )
