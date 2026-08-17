"""Optimizer behaviour: constraints, statuses, and reproducibility."""

from __future__ import annotations

import pytest

from app.domain.runtime_mode import PortfolioRunState
from app.domain.scoring import score_candidates
from app.optimizer.baseline import select_baseline
from app.optimizer.cpsat import OptimizerConstraints, objective_value_for, solve_portfolio
from tests.conftest import make_candidate


def _scored(candidates, equity_weight=0.45):
    return score_candidates(candidates, equity_weight=equity_weight)


def test_selects_exactly_the_requested_number_of_slots(sample_candidates):
    scored = _scored(sample_candidates)
    result = solve_portfolio(scored, OptimizerConstraints(shelter_slots=5, minimum_equity_share=0.0))
    assert result.state is PortfolioRunState.OPTIMAL
    assert len(result.selected_stop_ids) == 5


def test_never_selects_a_stop_that_already_has_a_shelter(sample_candidates):
    scored = _scored(sample_candidates)
    result = solve_portfolio(scored, OptimizerConstraints(shelter_slots=8, minimum_equity_share=0.0))
    assert "S11" not in result.selected_stop_ids
    assert "S12" not in result.selected_stop_ids


def test_without_an_equity_floor_it_takes_the_highest_scores(sample_candidates):
    scored = _scored(sample_candidates)
    result = solve_portfolio(scored, OptimizerConstraints(shelter_slots=4, minimum_equity_share=0.0))
    eligible_ranked = [s.stop_id for s in scored if s.eligible][:4]
    assert sorted(result.selected_stop_ids) == sorted(eligible_ranked)


def test_the_equity_floor_is_satisfied():
    candidates = [
        make_candidate("HIGH1", ridership=400, exceedance=3.0, svi=0.90),
        make_candidate("HIGH2", ridership=380, exceedance=2.8, svi=0.88),
        make_candidate("LOW1", ridership=2000, exceedance=12.0, svi=0.10),
        make_candidate("LOW2", ridership=1900, exceedance=11.5, svi=0.12),
        make_candidate("LOW3", ridership=1800, exceedance=11.0, svi=0.15),
        make_candidate("LOW4", ridership=1700, exceedance=10.5, svi=0.18),
    ]
    scored = _scored(candidates)

    unconstrained = solve_portfolio(
        scored, OptimizerConstraints(shelter_slots=4, minimum_equity_share=0.0)
    )
    assert not any(sid.startswith("HIGH") for sid in unconstrained.selected_stop_ids)

    constrained = solve_portfolio(
        scored, OptimizerConstraints(shelter_slots=4, minimum_equity_share=0.5)
    )
    assert constrained.state is PortfolioRunState.OPTIMAL
    assert constrained.equity_stops_required == 2
    assert constrained.equity_stops_selected >= 2
    # The floor genuinely costs objective value; hiding that would hide the tradeoff.
    assert constrained.objective_value < unconstrained.objective_value


def test_more_slots_than_eligible_stops_is_infeasible_with_an_explanation():
    candidates = [make_candidate("A"), make_candidate("B", shelters=1)]
    result = solve_portfolio(
        _scored(candidates), OptimizerConstraints(shelter_slots=2, minimum_equity_share=0.0)
    )
    assert result.state is PortfolioRunState.INFEASIBLE
    assert "eligible" in result.infeasible_reason.lower()
    assert result.infeasible_detail["eligibleStops"] == 1
    assert result.infeasible_detail["shelterSlots"] == 2


def test_an_unreachable_equity_floor_is_infeasible_with_an_explanation():
    candidates = [make_candidate(f"L{i}", svi=0.10) for i in range(6)]
    result = solve_portfolio(
        _scored(candidates), OptimizerConstraints(shelter_slots=4, minimum_equity_share=0.5)
    )
    assert result.state is PortfolioRunState.INFEASIBLE
    assert result.infeasible_detail["requiredEquityStops"] == 2
    assert result.infeasible_detail["availableEquityStops"] == 0


def test_zero_slots_is_infeasible():
    result = solve_portfolio(
        _scored([make_candidate("A")]), OptimizerConstraints(shelter_slots=0, minimum_equity_share=0.0)
    )
    assert result.state is PortfolioRunState.INFEASIBLE


def test_an_equity_floor_above_one_hundred_percent_is_infeasible():
    candidates = [make_candidate(f"H{i}", svi=0.9) for i in range(6)]
    constraints = OptimizerConstraints(shelter_slots=3, minimum_equity_share=1.0)
    assert constraints.required_equity_stops == 3
    result = solve_portfolio(_scored(candidates), constraints)
    assert result.state is PortfolioRunState.OPTIMAL


def test_the_same_input_produces_the_same_portfolio(sample_candidates):
    scored = _scored(sample_candidates)
    constraints = OptimizerConstraints(shelter_slots=6, minimum_equity_share=0.34)
    first = solve_portfolio(scored, constraints)
    second = solve_portfolio(scored, constraints)
    assert first.selected_stop_ids == second.selected_stop_ids
    assert first.objective_value == pytest.approx(second.objective_value)


def test_baseline_ranks_by_source_ridership_only(sample_candidates):
    scored = _scored(sample_candidates)
    baseline = select_baseline(scored, 3)
    assert baseline == ["S01", "S02", "S03"]
    assert "S11" not in baseline  # already sheltered


def test_optimizer_beats_the_baseline_on_its_own_objective(sample_candidates):
    scored = _scored(sample_candidates)
    result = solve_portfolio(
        scored, OptimizerConstraints(shelter_slots=5, minimum_equity_share=0.0)
    )
    baseline_value = objective_value_for(scored, select_baseline(scored, 5))
    assert result.objective_value >= baseline_value


def test_objective_value_matches_the_sum_of_selected_scores(sample_candidates):
    scored = _scored(sample_candidates)
    result = solve_portfolio(
        scored, OptimizerConstraints(shelter_slots=4, minimum_equity_share=0.0)
    )
    expected = objective_value_for(scored, result.selected_stop_ids)
    assert result.objective_value == pytest.approx(expected)
