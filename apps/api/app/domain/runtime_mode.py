"""Runtime mode rules (plan section 13).

Every result carries exactly one mode, and a live failure may never be
downgraded into a fixture-shaped success. The mode is derived from stored facts
rather than from what the caller asked for.
"""

from __future__ import annotations

from enum import StrEnum


class RuntimeMode(StrEnum):
    LIVE = "LIVE"
    CACHED_LIVE = "CACHED_LIVE"
    DEMO_FIXTURE = "DEMO_FIXTURE"


class HeatJobState(StrEnum):
    SUBMITTED = "SUBMITTED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


TERMINAL_HEAT_JOB_STATES = frozenset({HeatJobState.COMPLETED, HeatJobState.FAILED})


class PortfolioRunState(StrEnum):
    RUNNING = "RUNNING"
    OPTIMAL = "OPTIMAL"
    FEASIBLE = "FEASIBLE"
    INFEASIBLE = "INFEASIBLE"
    FAILED = "FAILED"


def effective_runtime_mode(*, stored_mode: str, reuse_count: int) -> RuntimeMode:
    """Return the mode a caller should see for a stored heat job.

    A fixture stays a fixture forever. A live result that is being served again
    for a later request is labelled CACHED_LIVE, because the provider was not
    contacted for this particular answer.
    """
    if stored_mode == RuntimeMode.DEMO_FIXTURE:
        return RuntimeMode.DEMO_FIXTURE
    if reuse_count > 0:
        return RuntimeMode.CACHED_LIVE
    return RuntimeMode.LIVE
