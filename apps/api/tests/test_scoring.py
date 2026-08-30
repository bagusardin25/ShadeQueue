"""Score normalisation, components, and integer scaling."""

from __future__ import annotations

import pytest

from app.domain import reason_codes as rc
from app.domain.scoring import (
    INTEGER_SCALE_FACTOR,
    HeatJoinMethod,
    score_candidates,
)
from tests.conftest import make_candidate


def test_scores_are_ordered_and_bounded(sample_candidates):
    scored = score_candidates(sample_candidates, equity_weight=0.45)
    assert len(scored) == len(sample_candidates)
    assert scored == sorted(scored, key=lambda s: (-s.final_score, s.stop_id))
    for stop in scored:
        assert 0.0 <= stop.final_score <= 100.0
        assert 0.0 <= stop.heat_component <= 100.0
        assert 0.0 <= stop.ridership_component <= 100.0
        assert 0.0 <= stop.equity_component <= 100.0


def test_the_top_scoring_stop_reaches_exactly_one_hundred(sample_candidates):
    scored = score_candidates(sample_candidates, equity_weight=0.45)
    assert scored[0].final_score == pytest.approx(100.0)


def test_equity_weight_zero_removes_the_vulnerability_term():
    low_svi = make_candidate("A", ridership=1000, exceedance=10.0, svi=0.10)
    high_svi = make_candidate("B", ridership=1000, exceedance=10.0, svi=0.99)
    scored = {s.stop_id: s for s in score_candidates([low_svi, high_svi], equity_weight=0.0)}
    assert scored["A"].raw_burden == pytest.approx(scored["B"].raw_burden)


def test_equity_weight_raises_the_vulnerable_stop():
    low_svi = make_candidate("A", ridership=1000, exceedance=10.0, svi=0.10)
    high_svi = make_candidate("B", ridership=1000, exceedance=10.0, svi=0.99)
    scored = {s.stop_id: s for s in score_candidates([low_svi, high_svi], equity_weight=0.8)}
    assert scored["B"].raw_burden > scored["A"].raw_burden


def test_a_stop_with_no_heat_exposure_scores_zero():
    stops = [
        make_candidate("A", exceedance=0.0),
        make_candidate("B", exceedance=10.0),
    ]
    scored = {s.stop_id: s for s in score_candidates(stops, equity_weight=0.45)}
    assert scored["A"].final_score == 0.0
    assert scored["A"].objective_coefficient == 0


def test_all_zero_inputs_do_not_divide_by_zero():
    stops = [make_candidate("A", ridership=0.0, exceedance=0.0, svi=0.0)]
    scored = score_candidates(stops, equity_weight=0.45)
    assert scored[0].final_score == 0.0
    assert scored[0].normalized_ridership == 0.0


def test_integer_coefficient_uses_the_documented_scale():
    stops = [make_candidate("A", exceedance=10.0), make_candidate("B", exceedance=5.0)]
    scored = score_candidates(stops, equity_weight=0.0)
    top = scored[0]
    assert top.objective_coefficient == round(top.final_score * INTEGER_SCALE_FACTOR)
    assert top.objective_coefficient == 100 * INTEGER_SCALE_FACTOR


def test_existing_shelters_make_a_stop_ineligible_but_still_scored():
    stops = [make_candidate("A"), make_candidate("B", shelters=1)]
    scored = {s.stop_id: s for s in score_candidates(stops, equity_weight=0.45)}
    assert scored["A"].eligible is True
    assert scored["B"].eligible is False
    assert rc.EXISTING_SHELTER in scored["B"].reason_codes


def test_reason_codes_reflect_the_documented_thresholds():
    stop = make_candidate("A", ridership=1600, exceedance=11.0, svi=0.90)
    scored = score_candidates([stop], equity_weight=0.45)[0]
    assert rc.HIGH_HEAT_EXPOSURE in scored.reason_codes
    assert rc.HIGH_SOCIAL_VULNERABILITY in scored.reason_codes
    assert rc.HIGH_SOURCE_RIDERSHIP in scored.reason_codes
    assert rc.EQUITY_FLOOR_ELIGIBLE in scored.reason_codes


def test_high_ridership_uses_the_scenario_maximum_not_a_fixed_count():
    high = make_candidate("HIGH", ridership=500, exceedance=1.0, svi=0.10)
    low = make_candidate("LOW", ridership=100, exceedance=1.0, svi=0.10)
    scored = {item.stop_id: item for item in score_candidates([high, low], equity_weight=0.0)}
    assert rc.HIGH_SOURCE_RIDERSHIP in scored["HIGH"].reason_codes
    assert rc.HIGH_SOURCE_RIDERSHIP not in scored["LOW"].reason_codes


def test_nearest_cell_and_missing_coverage_are_labelled():
    from dataclasses import replace

    base = make_candidate("A")
    nearest = replace(base, stop_id="B", heat_join_method=HeatJoinMethod.NEAREST_CELL)
    none = replace(base, stop_id="C", heat_join_method=HeatJoinMethod.NONE, svi_covered=False)
    scored = {s.stop_id: s for s in score_candidates([base, nearest, none], equity_weight=0.45)}
    assert rc.HEAT_VALUE_FROM_NEAREST_CELL in scored["B"].reason_codes
    assert rc.NO_HEAT_COVERAGE in scored["C"].reason_codes
    assert rc.NO_SVI_COVERAGE in scored["C"].reason_codes


def test_rejects_an_out_of_range_equity_weight():
    with pytest.raises(ValueError):
        score_candidates([make_candidate("A")], equity_weight=1.5)


def test_empty_input_returns_empty_output():
    assert score_candidates([], equity_weight=0.45) == []
