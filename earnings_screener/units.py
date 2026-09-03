"""
Dollar-unit scaling for display: show $1,550,000,000 as $1,550.0M or
$1.55B depending on what's easier to read.

Tiny on purpose, and stdlib-only, so both the dashboard and the CLI (or
anything else) format dollar figures the same way. The raw data objects
(models.py) always hold full-dollar values — scaling is a display-time
decision, never baked into the data, so a ratio computed from two
scaled numbers can't accidentally be off by a factor of a thousand.
"""

from __future__ import annotations

from typing import Optional

# Display unit name -> (divisor, suffix). Order here is the order the
# dashboard offers them in.
DOLLAR_UNITS: dict[str, tuple[float, str]] = {
    "Millions": (1_000_000, "M"),
    "Billions": (1_000_000_000, "B"),
}

DEFAULT_UNITS = "Millions"


def scale_dollars(value: Optional[float], units: str = DEFAULT_UNITS) -> Optional[float]:
    """Divide a full-dollar value down to the chosen unit (None stays None)."""
    if value is None:
        return None
    divisor, _ = DOLLAR_UNITS[units]
    return value / divisor


def unit_suffix(units: str = DEFAULT_UNITS) -> str:
    return DOLLAR_UNITS[units][1]


def format_dollars(value: Optional[float], units: str = DEFAULT_UNITS, decimals: Optional[int] = None) -> str:
    """'$1,550.0M' / '$1.55B' style, for text output (the CLI). The dashboard
    formats via Streamlit column configs instead, but uses the same
    scaling so the two agree."""
    if value is None:
        return "—"
    scaled = scale_dollars(value, units)
    if decimals is None:
        decimals = 1 if units == "Millions" else 2
    sign = "-" if scaled < 0 else ""
    return f"{sign}${abs(scaled):,.{decimals}f}{unit_suffix(units)}"
