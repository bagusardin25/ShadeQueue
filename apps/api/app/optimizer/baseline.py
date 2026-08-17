"""Proxy baseline: the highest source-provided ridership values.

This is explicitly a comparison proxy. It is not the City of Phoenix's current
capital-planning procedure and must never be labelled as such (plan section 9).
"""

from __future__ import annotations

from app.domain.scoring import ScoredStop

BASELINE_NAME = "highest-source-ridership"
BASELINE_LABEL = "Proxy baseline: highest source-provided ridership"


def select_baseline(stops: list[ScoredStop], shelter_slots: int) -> list[str]:
    """Return the baseline stop ids, ordered by descending ridership.

    Ties break on `stop_id` so the baseline is reproducible.
    """
    eligible = [stop for stop in stops if stop.eligible]
    ranked = sorted(eligible, key=lambda stop: (-stop.ridership_value, stop.stop_id))
    return [stop.stop_id for stop in ranked[: max(0, shelter_slots)]]
