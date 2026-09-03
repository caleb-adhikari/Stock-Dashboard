"""
The financial ratio catalog: the "dropdown of different financial
statistics" feature. Each ratio is a small, self-contained definition
(label, category, how to compute it) so the dashboard can offer them as a
checklist and just ask this module to compute whichever ones you pick.

Stdlib-only on purpose, same as compare.py/cross_company.py/pipeline.py —
this operates on plain QuarterComparison objects (see models.py), so it's
usable from a script or notebook with no pandas/streamlit install. The
dashboard is the thing that turns its output into a table/chart, not the
other way around.

WHAT "TTM" MEANS AND WHY SEVERAL RATIOS USE IT
--------------------------------------------------
Comparing a single quarter's net income to a full-year-scale balance sheet
figure (like stockholders' equity) doesn't make sense — one is a 3-month
number, the other is a snapshot. So ratios like ROE, ROA, P/E, and P/S use
"trailing twelve months" (TTM): the sum of the most recent 4 quarters'
worth of that duration figure, which is directly comparable to an annual
or point-in-time figure. _ttm() below returns None (not a partial sum) if
fewer than 4 quarters are available, or if any of those 4 is missing the
figure — a partial sum would understate TTM without saying so, which is
worse than clearly showing nothing.

WHY NEGATIVE-EARNINGS RATIOS SHOW AS MISSING, NOT AS A NEGATIVE NUMBER
---------------------------------------------------------------------------
P/E and P/B are conventionally shown as "N/A" rather than a negative
number when TTM earnings or book value are negative — a "P/E of -12x"
isn't a meaningful multiple the way a positive one is, it's just the sign
of the inputs. This is standard practice on most finance sites, and it's
also directly useful here: it's exactly why this ratio catalog includes
BOTH a GAAP P/E and a non-GAAP P/E — a company like Snowflake with a GAAP
net loss but positive non-GAAP earnings will show "N/A" for GAAP P/E and
a real number for non-GAAP P/E, which is itself a look at the GAAP/non-GAAP
gap from a different angle.

WHY THERE'S NO DEBT/EQUITY OR EV/EBITDA HERE
------------------------------------------------
"Total debt" isn't one clean XBRL tag — it's split across several
inconsistent tags (current vs. noncurrent, secured vs. unsecured, finance
leases, ...) with no reliable fallback list the way revenue has. Rather
than guess and show a debt figure that might be wrong, those ratios are
left out — see README "Known limitations."
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from earnings_screener.models import QuarterComparison

Getter = Callable[[QuarterComparison], Optional[float]]


def _ttm(comparisons: list[QuarterComparison], start_index: int, getter: Getter) -> Optional[float]:
    """Sum `getter(comp)` over the 4 quarters starting at `start_index` in
    `comparisons` (must be sorted newest-first) — the trailing twelve
    months as of that quarter."""
    window = comparisons[start_index : start_index + 4]
    if len(window) < 4:
        return None
    values = [getter(c) for c in window]
    if any(v is None for v in values):
        return None
    return sum(values)


def _safe_div(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _pct(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    ratio = _safe_div(numerator, denominator)
    return ratio * 100 if ratio is not None else None


# ---------------------------------------------------------------------------
# Individual ratio calculations. Signature is always
# (comparisons, index, latest_price) -> value for comparisons[index]'s
# quarter. `latest_price` is only used by the valuation ratios (P/E, P/S,
# P/B) — everything else ignores it, since a ratio needs the price *as of
# that quarter* to be exactly right, and yfinance's free data doesn't give
# us that; using the current price against historical quarters' valuation
# ratios is a simplification worth knowing about (see README).
# ---------------------------------------------------------------------------


def _gross_margin(comparisons, i, price):
    g = comparisons[i].gaap
    return _pct(g.gross_profit, g.revenue) if g else None


def _operating_margin(comparisons, i, price):
    g = comparisons[i].gaap
    return _pct(g.operating_income, g.revenue) if g else None


def _net_margin(comparisons, i, price):
    g = comparisons[i].gaap
    return _pct(g.net_income, g.revenue) if g else None


def _roe(comparisons, i, price):
    g = comparisons[i].gaap
    if not g or not g.stockholders_equity:
        return None
    ttm_net_income = _ttm(comparisons, i, lambda c: c.gaap.net_income if c.gaap else None)
    return _pct(ttm_net_income, g.stockholders_equity)


def _roa(comparisons, i, price):
    g = comparisons[i].gaap
    if not g or not g.total_assets:
        return None
    ttm_net_income = _ttm(comparisons, i, lambda c: c.gaap.net_income if c.gaap else None)
    return _pct(ttm_net_income, g.total_assets)


def _current_ratio(comparisons, i, price):
    g = comparisons[i].gaap
    if not g or not g.current_liabilities or g.current_assets is None:
        return None
    return g.current_assets / g.current_liabilities


def _pe_gaap(comparisons, i, price):
    if price is None:
        return None
    ttm_eps = _ttm(comparisons, i, lambda c: c.gaap.eps_diluted if c.gaap else None)
    if not ttm_eps or ttm_eps <= 0:
        return None  # negative/zero TTM earnings: P/E isn't a meaningful multiple
    return price / ttm_eps


def _pe_non_gaap(comparisons, i, price):
    if price is None:
        return None
    ttm_eps = _ttm(comparisons, i, lambda c: c.non_gaap.non_gaap_eps if c.non_gaap else None)
    if not ttm_eps or ttm_eps <= 0:
        return None
    return price / ttm_eps


def _ps_ratio(comparisons, i, price):
    g = comparisons[i].gaap
    if not g or price is None or not g.diluted_shares:
        return None
    ttm_revenue = _ttm(comparisons, i, lambda c: c.gaap.revenue if c.gaap else None)
    if not ttm_revenue:
        return None
    market_cap = price * g.diluted_shares
    return market_cap / ttm_revenue


def _pb_ratio(comparisons, i, price):
    g = comparisons[i].gaap
    if not g or price is None or not g.diluted_shares or not g.stockholders_equity:
        return None
    book_value_per_share = g.stockholders_equity / g.diluted_shares
    if book_value_per_share <= 0:
        return None  # negative book value: P/B isn't a meaningful multiple
    return price / book_value_per_share


def _revenue_yoy(comparisons, i, price):
    return comparisons[i].revenue_yoy_pct


def _revenue_qoq(comparisons, i, price):
    return comparisons[i].revenue_qoq_pct


@dataclass(frozen=True)
class Ratio:
    key: str
    label: str
    category: str
    format: str  # "pct" | "multiple" | "ratio"
    needs_price: bool
    description: str
    compute: Callable[[list[QuarterComparison], int, Optional[float]], Optional[float]]


RATIO_CATALOG: list[Ratio] = [
    Ratio("gross_margin", "Gross Margin %", "Profitability", "pct", False,
          "Gross profit ÷ revenue.", _gross_margin),
    Ratio("operating_margin", "Operating Margin %", "Profitability", "pct", False,
          "Operating income ÷ revenue.", _operating_margin),
    Ratio("net_margin", "Net Margin %", "Profitability", "pct", False,
          "Net income ÷ revenue.", _net_margin),
    Ratio("roe", "Return on Equity (ROE) %", "Returns", "pct", False,
          "Trailing-12-month net income ÷ stockholders' equity.", _roe),
    Ratio("roa", "Return on Assets (ROA) %", "Returns", "pct", False,
          "Trailing-12-month net income ÷ total assets.", _roa),
    Ratio("current_ratio", "Current Ratio", "Liquidity", "ratio", False,
          "Current assets ÷ current liabilities.", _current_ratio),
    Ratio("pe_gaap", "P/E (GAAP, TTM)", "Valuation", "multiple", True,
          "Latest price ÷ trailing-12-month GAAP diluted EPS.", _pe_gaap),
    Ratio("pe_non_gaap", "P/E (Non-GAAP, TTM)", "Valuation", "multiple", True,
          "Latest price ÷ trailing-12-month non-GAAP EPS (needs non-GAAP data seeded for this ticker).",
          _pe_non_gaap),
    Ratio("ps_ratio", "P/S (TTM)", "Valuation", "multiple", True,
          "Market cap (latest price × diluted shares) ÷ trailing-12-month revenue.", _ps_ratio),
    Ratio("pb_ratio", "P/B", "Valuation", "multiple", True,
          "Latest price ÷ book value per share (stockholders' equity ÷ diluted shares).", _pb_ratio),
    Ratio("revenue_yoy", "Revenue Growth YoY %", "Growth", "pct", False,
          "Same quarter, one year ago.", _revenue_yoy),
    Ratio("revenue_qoq", "Revenue Growth QoQ %", "Growth", "pct", False,
          "Prior quarter, sequential.", _revenue_qoq),
]

RATIO_BY_KEY: dict[str, Ratio] = {r.key: r for r in RATIO_CATALOG}


def compute_ratio_rows(
    comparisons: list[QuarterComparison], ratio_keys: list[str], latest_price: Optional[float] = None
) -> list[dict]:
    """
    One dict per quarter (same order as `comparisons`, i.e. newest-first),
    with "Quarter" plus one entry per selected ratio's label. Plain dicts
    (not a DataFrame) — see dataframes.py for the pandas conversion, kept
    separate so this module stays dependency-free.
    """
    rows = []
    for i, comp in enumerate(comparisons):
        row = {"Quarter": str(comp.key)}
        for key in ratio_keys:
            ratio = RATIO_BY_KEY[key]
            row[ratio.label] = ratio.compute(comparisons, i, latest_price)
        rows.append(row)
    return rows
