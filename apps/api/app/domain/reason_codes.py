"""Reason codes attached to each candidate stop.

These are demo-scale explanation labels, not clinical or safety classifications.
The thresholds are analysis parameters and are reported alongside the codes so a
reviewer can see what produced them.
"""

from __future__ import annotations

from typing import Final

HIGH_HEAT_EXPOSURE: Final = "HIGH_HEAT_EXPOSURE"
HIGH_SOCIAL_VULNERABILITY: Final = "HIGH_SOCIAL_VULNERABILITY"
HIGH_SOURCE_RIDERSHIP: Final = "HIGH_SOURCE_RIDERSHIP"
EXISTING_SHELTER: Final = "EXISTING_SHELTER"
EQUITY_FLOOR_ELIGIBLE: Final = "EQUITY_FLOOR_ELIGIBLE"
HEAT_VALUE_FROM_NEAREST_CELL: Final = "HEAT_VALUE_FROM_NEAREST_CELL"
NO_HEAT_COVERAGE: Final = "NO_HEAT_COVERAGE"
NO_SVI_COVERAGE: Final = "NO_SVI_COVERAGE"
BALANCED_PORTFOLIO_VALUE: Final = "BALANCED_PORTFOLIO_VALUE"

#: Hours above the comparison threshold at or beyond which a stop is labelled
#: high exposure. Matches the label used by the existing frontend fixture.
HIGH_HEAT_HOURS_THRESHOLD: Final = 10.0
#: SVI overall percentile rank at or beyond which a stop is labelled high
#: social vulnerability.
HIGH_SVI_PERCENTILE_THRESHOLD: Final = 0.85
#: Fraction of the scenario's highest source ridership at or beyond which a
#: stop is labelled high ridership. Absolute boardings cannot be used: the
#: City of Phoenix GIS field is an unverified unit whose corridor max is far
#: below the synthetic fixture scale.
HIGH_RIDERSHIP_RELATIVE_THRESHOLD: Final = 0.75
#: SVI percentile that makes a stop count toward the minimum equity share.
EQUITY_FLOOR_PERCENTILE: Final = 0.75

REASON_CODE_LABELS: Final[dict[str, str]] = {
    HIGH_HEAT_EXPOSURE: f"At least {HIGH_HEAT_HOURS_THRESHOLD:.0f} hours above the comparison threshold",
    HIGH_SOCIAL_VULNERABILITY: (
        f"SVI overall percentile at or above {HIGH_SVI_PERCENTILE_THRESHOLD:.2f}"
    ),
    HIGH_SOURCE_RIDERSHIP: (
        f"Source-provided ridership at or above {HIGH_RIDERSHIP_RELATIVE_THRESHOLD:.0%} "
        "of the highest value in this scenario"
    ),
    EXISTING_SHELTER: "Already has at least one shelter, so it is excluded from new-shelter selection",
    EQUITY_FLOOR_ELIGIBLE: (
        f"SVI percentile at or above {EQUITY_FLOOR_PERCENTILE:.2f}, counts toward the minimum equity share"
    ),
    HEAT_VALUE_FROM_NEAREST_CELL: (
        "The stop did not intersect a heat cell; the nearest cell value was used"
    ),
    NO_HEAT_COVERAGE: "No heat cell was available for this stop; exposure treated as zero",
    NO_SVI_COVERAGE: "No SVI tract covered this stop; vulnerability treated as zero",
    BALANCED_PORTFOLIO_VALUE: "Selected on combined score without triggering a single-factor label",
}
