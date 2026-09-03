"""
The trimmed "summary" table: one row per quarter, showing the handful of
headline figures most people actually look up (revenue, operating income,
net income, EPS) with the same quarter a year earlier and the YoY change
next to each — instead of the wide everything-at-once table the dashboard
used to open with.

WHICH NUMBERS: THE "BASIS" CHOICE
-----------------------------------
This project started as a GAAP-vs-non-GAAP comparison, but most of the
time you just want one set of numbers. So the caller picks a basis:

  "GAAP"      — official SEC-filed figures (the default; this is what you
                want ~90% of the time)
  "Non-GAAP"  — the company's own adjusted figures from its press release
                (only as complete as data/non_gaap/<TICKER>.json)
  "Both"      — GAAP and non-GAAP EPS side by side plus the gap metrics,
                i.e. the original purpose of the project

Each basis is just a list of `Metric` definitions below, so adding a
column is one line, and the dashboard doesn't hard-code any of them.

Stdlib-only, same as compare.py/ratios.py — it operates on
QuarterComparison objects and returns plain dicts; dataframes.py turns
those into a DataFrame for the dashboard.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from earnings_screener.models import QuarterComparison, QuarterKey

BASES = ("GAAP", "Non-GAAP", "Both")
DEFAULT_BASIS = "GAAP"

Getter = Callable[[QuarterComparison], Optional[float]]


@dataclass(frozen=True)
class Metric:
    label: str
    kind: str  # "dollars" (scaled to M/B for display) | "eps" | "pct" | "text"
    getter: Getter
    show_yoy: bool = True  # add a "<label> YoY %" column next to it


def _g(attr: str) -> Getter:
    """Getter for a field on the GAAP side."""
    return lambda c: getattr(c.gaap, attr) if c.gaap else None


def _ng(attr: str) -> Getter:
    """Getter for a field on the non-GAAP side."""
    return lambda c: getattr(c.non_gaap, attr) if c.non_gaap else None


def _c(attr: str) -> Getter:
    """Getter for a computed field on the comparison itself."""
    return lambda c: getattr(c, attr)


GAAP_METRICS: list[Metric] = [
    Metric("Revenue", "dollars", _g("revenue")),
    Metric("Gross Profit", "dollars", _g("gross_profit")),
    Metric("Operating Income", "dollars", _g("operating_income")),
    Metric("Net Income", "dollars", _g("net_income")),
    Metric("Diluted EPS", "eps", _g("eps_diluted")),
]

NON_GAAP_METRICS: list[Metric] = [
    # Total revenue is a GAAP figure either way (there's no "adjusted
    # revenue"), so it stays as the anchor column in the non-GAAP view.
    Metric("Revenue", "dollars", _g("revenue")),
    Metric("Product Revenue", "dollars", _ng("product_revenue")),
    Metric("Non-GAAP EPS", "eps", _ng("non_gaap_eps")),
    Metric("Non-GAAP Op Margin %", "pct", _ng("non_gaap_operating_margin_pct"), show_yoy=False),
    Metric("RPO", "dollars", _ng("rpo")),
    Metric("NRR %", "pct", _ng("nrr_pct"), show_yoy=False),
]

BOTH_METRICS: list[Metric] = [
    Metric("Revenue", "dollars", _g("revenue")),
    Metric("Net Income (GAAP)", "dollars", _g("net_income")),
    Metric("GAAP EPS", "eps", _g("eps_diluted"), show_yoy=False),
    Metric("Non-GAAP EPS", "eps", _ng("non_gaap_eps"), show_yoy=False),
    Metric("EPS Gap", "eps", _c("eps_gap"), show_yoy=False),
    Metric("Gap % of Revenue", "pct", _c("gap_pct_of_revenue"), show_yoy=False),
    Metric("SBC % of Revenue", "pct", _c("sbc_pct_of_revenue"), show_yoy=False),
]

METRICS_BY_BASIS: dict[str, list[Metric]] = {
    "GAAP": GAAP_METRICS,
    "Non-GAAP": NON_GAAP_METRICS,
    "Both": BOTH_METRICS,
}


@dataclass(frozen=True)
class SummaryColumn:
    """What the dashboard needs to know to format one column of the table."""

    label: str
    kind: str  # "text" | "dollars" | "eps" | "pct"


def summary_columns(basis: str = DEFAULT_BASIS) -> list[SummaryColumn]:
    """The columns `build_summary_rows` will produce for this basis, in order."""
    columns = [SummaryColumn("Quarter", "text"), SummaryColumn("Period End", "text")]
    for metric in METRICS_BY_BASIS[basis]:
        columns.append(SummaryColumn(metric.label, metric.kind))
        if metric.show_yoy:
            columns.append(SummaryColumn(f"{metric.label} YoY %", "pct"))
    return columns


def _pct_change(new: Optional[float], old: Optional[float]) -> Optional[float]:
    # Same convention as compare.py: change relative to the ABSOLUTE prior
    # value, so a net loss that shrinks reads as a positive % (improvement).
    if new is None or old is None or old == 0:
        return None
    return (new - old) / abs(old) * 100


def build_summary_rows(comparisons: list[QuarterComparison], basis: str = DEFAULT_BASIS) -> list[dict]:
    """
    One dict per quarter, in the same order as `comparisons` (newest-first
    as compare.py returns them). Each metric gets its value plus, where
    `show_yoy` is set, the % change versus the same fiscal quarter one
    year earlier (looked up by QuarterKey, so a missing year-ago quarter
    just yields None rather than comparing against the wrong quarter).
    Dollar values are FULL dollars here — scaling to millions/billions is
    a display decision (see units.py / dataframes.py).
    """
    if basis not in METRICS_BY_BASIS:
        raise ValueError(f"unknown basis {basis!r}; expected one of {BASES}")

    by_key = {c.key: c for c in comparisons}
    rows = []
    for comp in comparisons:
        year_ago = by_key.get(QuarterKey(comp.key.fiscal_year - 1, comp.key.fiscal_period))
        row = {
            "Quarter": str(comp.key),
            "Period End": comp.gaap.period_end if comp.gaap else None,
        }
        for metric in METRICS_BY_BASIS[basis]:
            value = metric.getter(comp)
            row[metric.label] = value
            if metric.show_yoy:
                row[f"{metric.label} YoY %"] = _pct_change(value, metric.getter(year_ago) if year_ago else None)
        rows.append(row)
    return rows
