"""Auditable CSV review packet.

The export is a review artefact, not a procurement document. It carries the raw
source values, the normalised components, the formula version, the solver
status, the runtime mode, and the source provenance, so a reviewer can check the
recommendation without opening the application.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
from typing import Any

from app.db.models import PortfolioItem, PortfolioRun, Scenario

_COLUMNS = [
    "run_id",
    "scenario_name",
    "runtime_mode",
    "run_state",
    "solver_status",
    "solver_version",
    "formula_version",
    "integer_scale_factor",
    "shelter_slots",
    "equity_weight",
    "minimum_equity_share",
    "objective_value",
    "baseline_value",
    "generated_at",
    "stop_id",
    "location_name",
    "longitude",
    "latitude",
    "selected",
    "baseline_selected",
    "eligible",
    "rank",
    "shelter_count",
    "source_ridership_value",
    "exceedance_hours",
    "svi_percentile",
    "heat_component",
    "ridership_component",
    "equity_component",
    "final_score",
    "heat_join_method",
    "reason_codes",
    "source_versions",
]

DISCLAIMER = (
    "ShadeQueue produces a candidate planning portfolio. It does not authorize capital "
    "expenditure and does not claim any reduction in temperature, illness, or mortality. "
    "A qualified human planner owns the final decision."
)


def _flatten_sources(source_versions: dict[str, Any]) -> str:
    sources = source_versions.get("sources") or []
    parts = []
    for source in sources:
        name = source.get("name", "unknown")
        version = source.get("version", "unknown")
        retrieved = source.get("retrievedAt") or "unknown"
        mode = source.get("evidenceMode") or "unknown"
        parts.append(f"{name} | {version} | retrieved {retrieved} | {mode}")
    return " ;; ".join(parts)


def build_csv(
    *,
    run: PortfolioRun,
    scenario: Scenario,
    items: list[PortfolioItem],
    generated_at: dt.datetime | None = None,
) -> str:
    generated = (generated_at or dt.datetime.now(dt.UTC)).isoformat()
    sources = _flatten_sources(run.source_versions or {})

    buffer = io.StringIO()
    # QUOTE_ALL keeps the free-text reason and source columns unambiguous in
    # spreadsheet software.
    writer = csv.writer(buffer, lineterminator="\n", quoting=csv.QUOTE_ALL)
    writer.writerow([f"# {DISCLAIMER}"])
    if run.infeasible_reason:
        writer.writerow([f"# Constraint note: {run.infeasible_reason}"])
    writer.writerow(_COLUMNS)

    for item in items:
        writer.writerow(
            [
                str(run.id),
                scenario.name,
                run.runtime_mode,
                run.state,
                run.solver_status or "",
                run.solver_version or "",
                scenario.formula_version,
                run.integer_scale_factor,
                scenario.shelter_slots,
                scenario.equity_weight,
                scenario.minimum_equity_share,
                "" if run.objective_value is None else round(run.objective_value, 6),
                "" if run.baseline_value is None else round(run.baseline_value, 6),
                generated,
                item.stop_id,
                item.location_name,
                item.longitude,
                item.latitude,
                item.selected,
                item.baseline_selected,
                item.eligible,
                "" if item.rank is None else item.rank,
                item.shelter_count,
                item.ridership_value,
                item.exceedance_hours,
                item.svi_percentile,
                round(item.heat_component, 6),
                round(item.ridership_component, 6),
                round(item.equity_component, 6),
                round(item.final_score, 6),
                item.heat_join_method,
                "|".join(item.reason_codes or []),
                sources,
            ]
        )

    return buffer.getvalue()


def filename_for(run: PortfolioRun) -> str:
    return f"shadequeue-portfolio-{run.id}.csv"
