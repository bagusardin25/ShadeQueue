"""Heat-exposure demand scoring.

The metric is a proxy demand index, not passenger wait-minutes and not a health
outcome:

    heat_burden_i = normalized_ridership_i
                    * exceedance_hours_i
                    * (1 + equity_weight * svi_percentile_i)

Normalisation is relative to the candidate set for the scenario, so scores are
comparable within one portfolio run and not across corridors.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from app.domain import reason_codes as rc

#: Bumped whenever the formula, normalisation, or component definitions change.
#: Persisted on every portfolio run so an old result stays interpretable.
FORMULA_VERSION: Final = "heat-burden-v1.0"

#: CP-SAT works on integers. Final scores lie in [0, 100], so this factor gives
#: four decimal places of resolution with a maximum coefficient of 1_000_000.
INTEGER_SCALE_FACTOR: Final = 10_000


class HeatJoinMethod:
    INTERSECTS = "INTERSECTS"
    NEAREST_CELL = "NEAREST_CELL"
    NONE = "NONE"


@dataclass(frozen=True)
class CandidateStop:
    """A bus stop with the raw source values that feed the score."""

    stop_id: str
    location_name: str
    longitude: float
    latitude: float
    shelter_count: int
    ridership_value: float
    exceedance_hours: float
    svi_percentile: float
    heat_join_method: str = HeatJoinMethod.INTERSECTS
    svi_covered: bool = True

    @property
    def eligible(self) -> bool:
        """Stops that already have a shelter are excluded from new shelters."""
        return self.shelter_count == 0


@dataclass(frozen=True)
class ScoredStop:
    stop_id: str
    location_name: str
    longitude: float
    latitude: float
    shelter_count: int
    ridership_value: float
    exceedance_hours: float
    svi_percentile: float
    heat_join_method: str
    eligible: bool
    normalized_ridership: float
    heat_component: float
    ridership_component: float
    equity_component: float
    raw_burden: float
    final_score: float
    reason_codes: list[str] = field(default_factory=list)

    @property
    def objective_coefficient(self) -> int:
        """The integer coefficient handed to CP-SAT.

        `final_score` is `raw_burden` rescaled by one positive constant across
        the whole candidate set, so maximising it selects the same portfolio as
        maximising `raw_burden` while staying in the 0-100 unit the interface
        already displays.
        """
        return round(self.final_score * INTEGER_SCALE_FACTOR)


def _safe_ratio(value: float, maximum: float) -> float:
    """Normalise to [0, 1], treating a degenerate maximum as "no signal"."""
    if maximum <= 0.0:
        return 0.0
    return max(0.0, min(1.0, value / maximum))


def score_candidates(
    candidates: list[CandidateStop],
    *,
    equity_weight: float,
) -> list[ScoredStop]:
    """Score every candidate stop, including ineligible ones.

    Ineligible stops are scored so the audit can show why they were skipped, but
    they never enter the optimizer.
    """
    if not candidates:
        return []
    if not 0.0 <= equity_weight <= 1.0:
        raise ValueError("equity_weight must lie between 0 and 1")

    max_ridership = max(c.ridership_value for c in candidates)
    max_exceedance = max(c.exceedance_hours for c in candidates)

    intermediate: list[tuple[CandidateStop, float, float]] = []
    for candidate in candidates:
        normalized_ridership = _safe_ratio(candidate.ridership_value, max_ridership)
        raw_burden = (
            normalized_ridership
            * candidate.exceedance_hours
            * (1.0 + equity_weight * candidate.svi_percentile)
        )
        intermediate.append((candidate, normalized_ridership, raw_burden))

    max_raw_burden = max(item[2] for item in intermediate)

    scored: list[ScoredStop] = []
    for candidate, normalized_ridership, raw_burden in intermediate:
        reasons: list[str] = []
        if candidate.exceedance_hours >= rc.HIGH_HEAT_HOURS_THRESHOLD:
            reasons.append(rc.HIGH_HEAT_EXPOSURE)
        if candidate.svi_percentile >= rc.HIGH_SVI_PERCENTILE_THRESHOLD:
            reasons.append(rc.HIGH_SOCIAL_VULNERABILITY)
        if candidate.ridership_value >= rc.HIGH_RIDERSHIP_THRESHOLD:
            reasons.append(rc.HIGH_SOURCE_RIDERSHIP)
        if candidate.svi_percentile >= rc.EQUITY_FLOOR_PERCENTILE:
            reasons.append(rc.EQUITY_FLOOR_ELIGIBLE)
        if candidate.shelter_count > 0:
            reasons.append(rc.EXISTING_SHELTER)
        if candidate.heat_join_method == HeatJoinMethod.NEAREST_CELL:
            reasons.append(rc.HEAT_VALUE_FROM_NEAREST_CELL)
        if candidate.heat_join_method == HeatJoinMethod.NONE:
            reasons.append(rc.NO_HEAT_COVERAGE)
        if not candidate.svi_covered:
            reasons.append(rc.NO_SVI_COVERAGE)

        scored.append(
            ScoredStop(
                stop_id=candidate.stop_id,
                location_name=candidate.location_name,
                longitude=candidate.longitude,
                latitude=candidate.latitude,
                shelter_count=candidate.shelter_count,
                ridership_value=candidate.ridership_value,
                exceedance_hours=candidate.exceedance_hours,
                svi_percentile=candidate.svi_percentile,
                heat_join_method=candidate.heat_join_method,
                eligible=candidate.eligible,
                normalized_ridership=normalized_ridership,
                heat_component=_safe_ratio(candidate.exceedance_hours, max_exceedance) * 100.0,
                ridership_component=normalized_ridership * 100.0,
                equity_component=max(0.0, min(1.0, candidate.svi_percentile)) * 100.0,
                raw_burden=raw_burden,
                final_score=_safe_ratio(raw_burden, max_raw_burden) * 100.0,
                reason_codes=reasons,
            )
        )

    # Deterministic order regardless of how the database returned the rows.
    scored.sort(key=lambda stop: (-stop.final_score, stop.stop_id))
    return scored
