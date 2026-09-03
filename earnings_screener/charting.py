"""
The catalog of quarterly metrics you can plot on the dashboard's Charts
tab, plus the math that turns a list of QuarterComparison objects into
plain rows of (quarter, metric, value, QoQ %, YoY %).

Same design as ratios.py: this file is the "what can be charted and how
is it computed" layer, standard library only, so it's testable offline
(tests/test_charting.py) and usable without pandas/streamlit. The
dashboard just asks this module for rows and hands them to Altair.

WHY "EXPENSES" ARE DERIVED RATHER THAN FETCHED
--------------------------------------------------
SEC EDGAR has no single reliable XBRL tag for "total expenses" — companies
break costs out very differently (CostOfRevenue vs. CostOfGoodsAndServicesSold,
OperatingExpenses present for some filers and absent for others, ...). But
the three subtotals we DO already fetch (revenue, gross profit, operating
income) pin the expense lines down by simple subtraction:

    cost of revenue     = revenue      - gross profit
    operating expenses  = gross profit - operating income   (R&D + S&M + G&A)
    total costs         = revenue      - operating income

That's exactly how they appear on the income statement, just read
backwards, so the derived numbers match what the company reported — with
the caveat that if a filer skips the GrossProfit tag, cost of revenue and
operating expenses come back as None (total costs still works).

GROWTH RATES
---------------
QoQ and YoY % are computed for EVERY metric here, using the same
prior-quarter / year-ago lookups and the same _pct_change rule as
compare.py (None if either side is missing or the base is zero). Note
that _pct_change divides by abs(old), so a metric going from a -$50M loss
to a -$25M loss reads as +50% ("improved by half"), not -50% — worth
remembering when charting net income or operating income for a company
that's still losing money.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from earnings_screener.compare import _pct_change, prior_quarter_key, year_ago_key
from earnings_screener.models import QuarterComparison


def _gaap_field(name: str) -> Callable[[QuarterComparison], Optional[float]]:
    return lambda comp: getattr(comp.gaap, name) if comp.gaap else None


def _non_gaap_field(name: str) -> Callable[[QuarterComparison], Optional[float]]:
    return lambda comp: getattr(comp.non_gaap, name) if comp.non_gaap else None


def _difference(a: str, b: str) -> Callable[[QuarterComparison], Optional[float]]:
    """GAAP field `a` minus GAAP field `b`, or None if either is missing."""

    def compute(comp: QuarterComparison) -> Optional[float]:
        if not comp.gaap:
            return None
        left = getattr(comp.gaap, a)
        right = getattr(comp.gaap, b)
        if left is None or right is None:
            return None
        return left - right

    return compute


@dataclass(frozen=True)
class ChartMetric:
    key: str
    label: str
    category: str  # groups the dropdown: "Income statement", "Expenses", "Non-GAAP / KPIs"
    description: str
    compute: Callable[[QuarterComparison], Optional[float]]


CHART_METRIC_CATALOG: list[ChartMetric] = [
    # -- Income statement (straight from the GAAP filing) --------------------
    ChartMetric(
        "revenue", "Revenue", "Income statement",
        "Total GAAP revenue for the quarter.", _gaap_field("revenue"),
    ),
    ChartMetric(
        "gross_profit", "Gross Profit", "Income statement",
        "Revenue minus cost of revenue, as reported.", _gaap_field("gross_profit"),
    ),
    ChartMetric(
        "operating_income", "Operating Income", "Income statement",
        "GAAP operating income (loss) — profit after all operating expenses, before interest and tax.",
        _gaap_field("operating_income"),
    ),
    ChartMetric(
        "net_income", "Net Income", "Income statement",
        "GAAP net income (loss) — the bottom line.", _gaap_field("net_income"),
    ),
    # -- Expenses (derived by subtraction; see module docstring) --------------
    ChartMetric(
        "cost_of_revenue", "Cost of Revenue", "Expenses",
        "Revenue minus gross profit — the direct cost of delivering the product/service.",
        _difference("revenue", "gross_profit"),
    ),
    ChartMetric(
        "operating_expenses", "Operating Expenses", "Expenses",
        "Gross profit minus operating income — R&D, sales & marketing, and G&A combined.",
        _difference("gross_profit", "operating_income"),
    ),
    ChartMetric(
        "total_costs", "Total Costs & Expenses", "Expenses",
        "Revenue minus operating income — everything the company spent to operate this quarter.",
        _difference("revenue", "operating_income"),
    ),
    ChartMetric(
        "stock_based_comp", "Stock-Based Compensation", "Expenses",
        "Share-based compensation expense — usually the biggest piece of the GAAP/non-GAAP gap.",
        _gaap_field("stock_based_comp"),
    ),
    # -- Non-GAAP / KPIs (hand-entered from press releases) ------------------
    ChartMetric(
        "product_revenue", "Product Revenue (non-GAAP)", "Non-GAAP / KPIs",
        "Product revenue as the company reports it in its press release, if entered.",
        _non_gaap_field("product_revenue"),
    ),
    ChartMetric(
        "rpo", "RPO", "Non-GAAP / KPIs",
        "Remaining performance obligations — contracted revenue not yet recognized.",
        _non_gaap_field("rpo"),
    ),
]

CHART_METRIC_BY_KEY: dict[str, ChartMetric] = {m.key: m for m in CHART_METRIC_CATALOG}

# The dropdown's starting selection: the four lines that tell the basic
# "is this business scaling efficiently" story at a glance.
DEFAULT_CHART_METRIC_KEYS = ["revenue", "gross_profit", "operating_expenses", "net_income"]


def compute_chart_rows(comparisons: list[QuarterComparison], metric_keys: list[str]) -> list[dict]:
    """
    One row per (quarter, metric) — "long" format, which is what Altair
    wants for a grouped bar chart or a multi-line chart (one column says
    which series a point belongs to, rather than one column per series).

    Rows come back in CHRONOLOGICAL order (oldest quarter first), with the
    metrics for each quarter in the order `metric_keys` was given, no
    matter what order `comparisons` arrived in — charts read left to right.
    Quarters where a metric is None are still emitted (with Value None) so
    the caller can decide whether to show a gap or drop the point.

    Each row: {"Quarter", "Fiscal Year", "Fiscal Period", "Period End",
               "Metric" (label), "Metric Key", "Value", "QoQ %", "YoY %"}
    """
    unknown = [k for k in metric_keys if k not in CHART_METRIC_BY_KEY]
    if unknown:
        raise KeyError(f"Unknown chart metric key(s): {unknown}")

    by_key = {comp.key: comp for comp in comparisons}
    ordered = sorted(comparisons, key=lambda c: c.key)

    rows: list[dict] = []
    for comp in ordered:
        prior = by_key.get(prior_quarter_key(comp.key))
        year_ago = by_key.get(year_ago_key(comp.key))
        for metric_key in metric_keys:
            metric = CHART_METRIC_BY_KEY[metric_key]
            value = metric.compute(comp)
            rows.append(
                {
                    "Quarter": str(comp.key),
                    "Fiscal Year": comp.key.fiscal_year,
                    "Fiscal Period": comp.key.fiscal_period,
                    "Period End": comp.gaap.period_end if comp.gaap else None,
                    "Metric": metric.label,
                    "Metric Key": metric.key,
                    "Value": value,
                    "QoQ %": _pct_change(value, metric.compute(prior) if prior else None),
                    "YoY %": _pct_change(value, metric.compute(year_ago) if year_ago else None),
                }
            )
    return rows


def pick_dollar_unit(values: list[Optional[float]]) -> tuple[float, str]:
    """
    Choose a display unit for a set of dollar figures so the chart axis
    reads "1.5" with a "$ billions" label instead of "1500000000". Returns
    (divisor, label). Based on the largest absolute value present.
    """
    biggest = max((abs(v) for v in values if v is not None), default=0.0)
    if biggest >= 1e9:
        return 1e9, "$ billions"
    if biggest >= 1e6:
        return 1e6, "$ millions"
    if biggest >= 1e3:
        return 1e3, "$ thousands"
    return 1.0, "$"
