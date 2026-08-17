"""CP-SAT portfolio optimizer.

    maximize   sum(selected_i * heat_burden_i)
    subject to sum(selected_i) = shelter_slots
               selected_i = 0 where shelter_count_i > 0
               sum(selected_i over high-equity stops) >= ceil(slots * minimum_equity_share)

Infeasibility is detected before the solver runs wherever possible, so the API
can explain *which* constraint cannot be satisfied instead of returning a bare
solver status.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ortools.sat.python import cp_model

from app.domain import reason_codes as rc
from app.domain.runtime_mode import PortfolioRunState
from app.domain.scoring import INTEGER_SCALE_FACTOR, ScoredStop

#: Single worker plus a fixed seed keeps the search deterministic, which the
#: reproducibility requirement in the definition of done depends on.
_SOLVER_WORKERS = 1
_SOLVER_SEED = 0

_STATUS_MAP = {
    cp_model.OPTIMAL: PortfolioRunState.OPTIMAL,
    cp_model.FEASIBLE: PortfolioRunState.FEASIBLE,
    cp_model.INFEASIBLE: PortfolioRunState.INFEASIBLE,
    cp_model.MODEL_INVALID: PortfolioRunState.FAILED,
    cp_model.UNKNOWN: PortfolioRunState.FAILED,
}


@dataclass(frozen=True)
class OptimizerConstraints:
    shelter_slots: int
    minimum_equity_share: float
    equity_percentile_threshold: float = rc.EQUITY_FLOOR_PERCENTILE

    @property
    def required_equity_stops(self) -> int:
        if self.minimum_equity_share <= 0.0:
            return 0
        return math.ceil(self.shelter_slots * self.minimum_equity_share)


@dataclass
class OptimizerResult:
    state: PortfolioRunState
    selected_stop_ids: list[str] = field(default_factory=list)
    objective_value: float = 0.0
    solver_status_name: str = "NOT_SOLVED"
    wall_time_seconds: float = 0.0
    infeasible_reason: str | None = None
    infeasible_detail: dict = field(default_factory=dict)
    equity_stops_selected: int = 0
    equity_stops_required: int = 0
    eligible_stop_count: int = 0

    @property
    def succeeded(self) -> bool:
        return self.state in {PortfolioRunState.OPTIMAL, PortfolioRunState.FEASIBLE}


def solve_portfolio(
    stops: list[ScoredStop],
    constraints: OptimizerConstraints,
    *,
    time_limit_seconds: float = 10.0,
) -> OptimizerResult:
    eligible = [stop for stop in stops if stop.eligible]
    required_equity = constraints.required_equity_stops
    high_equity = [
        stop
        for stop in eligible
        if stop.svi_percentile >= constraints.equity_percentile_threshold
    ]

    base = OptimizerResult(
        state=PortfolioRunState.INFEASIBLE,
        equity_stops_required=required_equity,
        eligible_stop_count=len(eligible),
    )

    if constraints.shelter_slots <= 0:
        base.infeasible_reason = "The scenario allocates no shelter slots."
        base.infeasible_detail = {"shelterSlots": constraints.shelter_slots}
        return base

    if len(eligible) < constraints.shelter_slots:
        base.infeasible_reason = (
            "Fewer eligible stops than shelter slots. Stops that already have a shelter "
            "are excluded from new-shelter selection."
        )
        base.infeasible_detail = {
            "eligibleStops": len(eligible),
            "shelterSlots": constraints.shelter_slots,
            "totalStops": len(stops),
        }
        return base

    if required_equity > constraints.shelter_slots:
        base.infeasible_reason = (
            "The minimum equity share requires more stops than the portfolio has slots."
        )
        base.infeasible_detail = {
            "requiredEquityStops": required_equity,
            "shelterSlots": constraints.shelter_slots,
            "minimumEquityShare": constraints.minimum_equity_share,
        }
        return base

    if len(high_equity) < required_equity:
        base.infeasible_reason = (
            "Not enough eligible stops meet the equity percentile floor to satisfy the "
            "minimum equity share."
        )
        base.infeasible_detail = {
            "requiredEquityStops": required_equity,
            "availableEquityStops": len(high_equity),
            "equityPercentileThreshold": constraints.equity_percentile_threshold,
            "minimumEquityShare": constraints.minimum_equity_share,
        }
        return base

    model = cp_model.CpModel()
    variables = {stop.stop_id: model.new_bool_var(f"select_{stop.stop_id}") for stop in eligible}

    model.add(sum(variables.values()) == constraints.shelter_slots)
    if required_equity > 0:
        model.add(sum(variables[stop.stop_id] for stop in high_equity) >= required_equity)

    model.maximize(
        sum(stop.objective_coefficient * variables[stop.stop_id] for stop in eligible)
    )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_seconds
    solver.parameters.num_workers = _SOLVER_WORKERS
    solver.parameters.random_seed = _SOLVER_SEED
    status = solver.solve(model)

    state = _STATUS_MAP.get(status, PortfolioRunState.FAILED)
    result = OptimizerResult(
        state=state,
        solver_status_name=solver.status_name(status),
        wall_time_seconds=solver.wall_time,
        equity_stops_required=required_equity,
        eligible_stop_count=len(eligible),
    )

    if not result.succeeded:
        if state is PortfolioRunState.INFEASIBLE:
            result.infeasible_reason = (
                "The solver proved that no portfolio satisfies the requested constraints."
            )
            result.infeasible_detail = {
                "shelterSlots": constraints.shelter_slots,
                "requiredEquityStops": required_equity,
                "eligibleStops": len(eligible),
            }
        return result

    selected = [
        stop.stop_id for stop in eligible if solver.boolean_value(variables[stop.stop_id])
    ]
    # `eligible` is already ordered by descending final score, so `selected`
    # inherits that ranking order.
    result.selected_stop_ids = selected
    result.objective_value = solver.objective_value / INTEGER_SCALE_FACTOR
    result.equity_stops_selected = sum(
        1
        for stop in high_equity
        if solver.boolean_value(variables[stop.stop_id])
    )
    return result


def objective_value_for(stops: list[ScoredStop], stop_ids: list[str]) -> float:
    """Sum the objective contribution of an arbitrary selection.

    Used to state the baseline in the same unit as the optimized portfolio so
    the two are directly comparable.
    """
    wanted = set(stop_ids)
    total_scaled = sum(stop.objective_coefficient for stop in stops if stop.stop_id in wanted)
    return total_scaled / INTEGER_SCALE_FACTOR
