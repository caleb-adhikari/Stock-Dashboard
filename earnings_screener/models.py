"""
Data structures shared across the whole project.

Keeping these in one place (instead of passing raw dicts around) is what
makes this codebase easy to build on later — a future dashboard, a database
writer, or a new data source can all import `QuarterKey`, `GaapQuarter`, and
`NonGaapQuarter` from here and know exactly what shape of data to expect.

We use `dataclasses` (built into Python, no dependency needed) because they
give us:
  - a clear, typed schema (you can see every field at a glance)
  - free __init__, __repr__, and equality methods
  - a natural place to hang small computed properties (see GapReport below)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True, order=True)
class QuarterKey:
    """
    Uniquely identifies one fiscal quarter for one company.

    We key on the company's OWN fiscal year/quarter labels (as reported in
    their filings), not calendar quarters, because companies like Snowflake
    have a fiscal year that doesn't line up with the calendar (SNOW's fiscal
    year ends January 31, so "Q2 FY2027" is the quarter ended July 31, 2026).

    `order=True` lets us sort a list of these chronologically for free.
    """

    fiscal_year: int
    fiscal_period: str  # "Q1", "Q2", "Q3", "Q4", or "FY" for a full-year figure

    def __str__(self) -> str:
        return f"Q{self.fiscal_period[-1]} FY{self.fiscal_year}" if self.fiscal_period.startswith("Q") else f"FY{self.fiscal_year}"


@dataclass
class GaapQuarter:
    """
    One quarter's official GAAP figures, sourced from SEC EDGAR XBRL data.

    Fields are Optional because not every company reports every tag every
    quarter (e.g. a company might not break out stock-based comp as its own
    XBRL fact), and we'd rather show "data missing" than silently show 0.
    """

    ticker: str
    key: QuarterKey
    period_start: str  # ISO date string, e.g. "2026-05-01"
    period_end: str  # ISO date string, e.g. "2026-07-31"
    revenue: Optional[float] = None
    gross_profit: Optional[float] = None
    operating_income: Optional[float] = None
    net_income: Optional[float] = None  # negative = net loss
    eps_diluted: Optional[float] = None
    diluted_shares: Optional[float] = None
    stock_based_comp: Optional[float] = None

    # Balance sheet figures below are "instant" facts — a snapshot AS OF
    # period_end, not a total accumulated DURING the quarter the way
    # revenue/net_income are. We attach them to the quarter they line up
    # with so ratio math (ROE, current ratio, P/B, ...) has everything it
    # needs on one object. See sec_edgar.py's docstring for why instant
    # facts need different parsing than duration facts.
    total_assets: Optional[float] = None
    total_liabilities: Optional[float] = None
    stockholders_equity: Optional[float] = None
    current_assets: Optional[float] = None
    current_liabilities: Optional[float] = None
    cash: Optional[float] = None

    source_accession: Optional[str] = None  # SEC accession number, for traceability
    filed_date: Optional[str] = None


@dataclass
class NonGaapQuarter:
    """
    One quarter's non-GAAP / "adjusted" figures.

    These come from the company's own earnings press release (8-K Exhibit
    99.1), which has no standardized machine-readable API — so for now this
    is manually entered data (see data/non_gaap/<TICKER>.json). The shape is
    still a first-class typed object so that swapping in an automated
    scraper later doesn't require touching any other file.
    """

    ticker: str
    key: QuarterKey
    non_gaap_eps: Optional[float] = None
    non_gaap_operating_margin_pct: Optional[float] = None  # e.g. 15.3 means 15.3%
    rpo: Optional[float] = None  # remaining performance obligations, in dollars
    nrr_pct: Optional[float] = None  # net revenue retention, e.g. 126 means 126%
    product_revenue: Optional[float] = None
    notes: str = ""
    source: str = ""  # e.g. "press release 2026-09-02" — where this was entered from


@dataclass
class QuarterComparison:
    """
    A GAAP quarter and its matching non-GAAP quarter, merged, plus the
    computed comparison metrics. Either side can be missing (e.g. a quarter
    that's been reported in a press release but whose 10-Q hasn't been filed
    yet with the SEC), which the report layer displays rather than hides.
    """

    ticker: str
    key: QuarterKey
    gaap: Optional[GaapQuarter] = None
    non_gaap: Optional[NonGaapQuarter] = None

    # Filled in by compare.py once both sides are merged.
    eps_gap: Optional[float] = None  # non_gaap_eps - gaap_eps_diluted
    implied_gap_dollars: Optional[float] = None  # eps_gap * diluted_shares
    gap_pct_of_revenue: Optional[float] = None
    sbc_pct_of_revenue: Optional[float] = None
    revenue_qoq_pct: Optional[float] = None
    revenue_yoy_pct: Optional[float] = None
    rpo_qoq_pct: Optional[float] = None
    rpo_yoy_pct: Optional[float] = None


@dataclass
class CompanySnapshot:
    """
    One row of a cross-company comparison table: a single company's most
    recent reported quarter, flattened out of a QuarterComparison so
    several companies' snapshots can sit side by side regardless of each
    company's own fiscal calendar (see cross_company.py for why we align
    on "most recent quarter" rather than matching fiscal quarter numbers
    across companies).
    """

    ticker: str
    key: QuarterKey
    period_end: Optional[str] = None
    revenue: Optional[float] = None
    revenue_qoq_pct: Optional[float] = None
    revenue_yoy_pct: Optional[float] = None
    gaap_eps_diluted: Optional[float] = None
    non_gaap_eps: Optional[float] = None
    eps_gap: Optional[float] = None
    gap_pct_of_revenue: Optional[float] = None
    non_gaap_operating_margin_pct: Optional[float] = None
    rpo: Optional[float] = None
    rpo_yoy_pct: Optional[float] = None
    nrr_pct: Optional[float] = None
    gaap_fetch_error: Optional[str] = None  # set if we couldn't pull GAAP data for this ticker at all
