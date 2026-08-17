"""Deterministic fixture provider.

Fixtures go through exactly the same validated adapter contract as live
responses (plan section 13): the JSON on disk is parsed by
`parse_submit_response` and `parse_status_response`, not shortcut into an
in-memory object. If the parser regresses, the fixture path breaks too.

The simulated latency is real: a fixture activity reports PROCESSING until
`FIXTURE_PROCESSING_SECONDS` have passed, so the processing UI state and the
reload-during-processing test exercise genuine transitions.
"""

from __future__ import annotations

import datetime as dt
import json
from functools import lru_cache
from typing import Any

from app.config import FIXTURES_DIR, Settings
from app.config import settings as default_settings
from app.integrations.fortyguard.schemas import (
    ParsedHeatmapResult,
    parse_status_response,
    parse_submit_response,
)

SUBMIT_FIXTURE = "fortyguard_submit_accepted.json"
STATUS_COMPLETED_FIXTURE = "fortyguard_status_completed.json"
STATUS_PROCESSING_FIXTURE = "fortyguard_status_processing.json"
STATUS_FAILED_FIXTURE = "fortyguard_status_failed.json"

FIXTURE_ACTIVITY_PREFIX = "fixture-activity"


@lru_cache(maxsize=8)
def load_fixture(name: str) -> dict[str, Any]:
    path = FIXTURES_DIR / name
    if not path.is_file():
        raise FileNotFoundError(f"Fixture {name} is missing from {FIXTURES_DIR}")
    return json.loads(path.read_text(encoding="utf-8"))


class FixtureProvider:
    """Satisfies the same protocol as `FortyGuardClient`."""

    def __init__(self, config: Settings | None = None, *, force_failure: bool = False):
        self._settings = config or default_settings
        self._force_failure = force_failure

    async def submit_heatmap(self, body: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        payload = dict(load_fixture(SUBMIT_FIXTURE))
        activity_id = parse_submit_response(payload)
        return activity_id, payload

    async def check_status(self, activity_id: str) -> tuple[ParsedHeatmapResult, dict[str, Any]]:
        """Fixture status without timing context: always the completed surface."""
        name = STATUS_FAILED_FIXTURE if self._force_failure else STATUS_COMPLETED_FIXTURE
        payload = load_fixture(name)
        return parse_status_response(payload), _strip_map_data(payload)

    async def check_status_at(
        self, activity_id: str, *, submitted_at: dt.datetime, now: dt.datetime
    ) -> tuple[ParsedHeatmapResult, dict[str, Any]]:
        """Status that respects the simulated provider latency."""
        if self._force_failure:
            payload = load_fixture(STATUS_FAILED_FIXTURE)
            return parse_status_response(payload), _strip_map_data(payload)

        elapsed = (now - submitted_at).total_seconds()
        if elapsed < self._settings.fixture_processing_seconds:
            payload = load_fixture(STATUS_PROCESSING_FIXTURE)
            return parse_status_response(payload), _strip_map_data(payload)

        payload = load_fixture(STATUS_COMPLETED_FIXTURE)
        return parse_status_response(payload), _strip_map_data(payload)


def _strip_map_data(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep the audit copy small; the polygons live in `heat_cells`."""
    return {
        key: ({"omitted": "stored as heat_cells rows"} if key == "map_data" else value)
        for key, value in payload.items()
    }


def fixture_source_version() -> str:
    return "deterministic-fixture-v1"
