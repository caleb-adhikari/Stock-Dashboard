"""
Cross-company comparison: put several tickers' most recent quarters side
by side.

WHY "MOST RECENT QUARTER" RATHER THAN MATCHING FISCAL QUARTER NUMBERS
------------------------------------------------------------------------
compare.py's QuarterKey (fiscal_year, fiscal_period) is exactly right for
comparing one company against ITSELF over time, because "Q2 FY2027" always
means the same thing for Snowflake. But it does NOT mean the same thing
across companies: Snowflake's fiscal year ends January 31, so its "Q2"
covers May-July, while a company on a calendar fiscal year (e.g. most
retailers, many older tech companies) has its "Q2" cover April-June. If we
naively matched "Q2 FY2027" across two companies, we could be comparing
quarters that don't even overlap in time.

So for cross-company comparison, this module ignores each company's own
fiscal labels and instead lines companies up by ACTUAL CALENDAR RECENCY —
each company's single most-recently-reported quarter, whatever that
company happens to call it. That's the right comparison for "how does
company A's latest quarter stack up against company B's latest quarter,"
which is what a screener across companies is actually for. Comparing
company-to-itself over time (QoQ/YoY) stays in compare.py, keyed by each
company's own fiscal calendar, because that comparison SHOULD use the
company's own quarter boundaries.
"""

from __future__ import annotations

from earnings_screener.models import CompanySnapshot, QuarterComparison
from earnings_screener.pipeline import FetchResult, get_comparisons_for_ticker


def _latest_comparison_with_gaap(comparisons: list[QuarterComparison]) -> QuarterComparison | None:
    """The most recent quarter that actually has a GAAP filing behind it —
    skips a quarter that's only been announced in a press release so far
    (see sec_edgar.py's docstring: the 10-Q typically lags the earnings
    release by days to weeks)."""
    for comp in comparisons:  # comparisons is already sorted newest-first
        if comp.gaap is not None:
            return comp
    return None


def snapshot_from_fetch_result(result: FetchResult) -> CompanySnapshot:
    """Build one CompanySnapshot row from a ticker's fetched comparisons."""
    comp = _latest_comparison_with_gaap(result.comparisons)

    if comp is None:
        # Either the GAAP fetch failed outright, or this ticker only has
        # non-GAAP data seeded with no matching GAAP filing yet. Still
        # return a (mostly empty) snapshot so the ticker shows up in the
        # comparison table with a visible "no data" row instead of quietly
        # vanishing.
        fallback_key = result.comparisons[0].key if result.comparisons else None
        return CompanySnapshot(
            ticker=result.ticker,
            key=fallback_key,
            gaap_fetch_error=result.gaap_fetch_error or "No GAAP filing found for any recent quarter",
        )

    gaap = comp.gaap
    non_gaap = comp.non_gaap
    return CompanySnapshot(
        ticker=result.ticker,
        key=comp.key,
        period_end=gaap.period_end,
        revenue=gaap.revenue,
        revenue_qoq_pct=comp.revenue_qoq_pct,
        revenue_yoy_pct=comp.revenue_yoy_pct,
        gaap_eps_diluted=gaap.eps_diluted,
        non_gaap_eps=non_gaap.non_gaap_eps if non_gaap else None,
        eps_gap=comp.eps_gap,
        gap_pct_of_revenue=comp.gap_pct_of_revenue,
        non_gaap_operating_margin_pct=non_gaap.non_gaap_operating_margin_pct if non_gaap else None,
        rpo=non_gaap.rpo if non_gaap else None,
        rpo_yoy_pct=comp.rpo_yoy_pct,
        nrr_pct=non_gaap.nrr_pct if non_gaap else None,
        gaap_fetch_error=result.gaap_fetch_error,
    )


def build_snapshot_table(
    tickers: list[str], email: str, quarters: int = 8
) -> tuple[list[CompanySnapshot], dict[str, FetchResult]]:
    """
    Fetch each ticker's data and return:
      - a list of CompanySnapshot rows, one per ticker, ready for a
        comparison table/chart
      - a dict of the full FetchResult per ticker (ticker -> FetchResult),
        in case a caller (like the dashboard) also wants each company's
        full quarterly history, not just the latest-quarter snapshot
    """
    results: dict[str, FetchResult] = {}
    snapshots: list[CompanySnapshot] = []

    for ticker in tickers:
        result = get_comparisons_for_ticker(ticker, email=email, quarters=quarters)
        results[result.ticker] = result
        snapshots.append(snapshot_from_fetch_result(result))

    return snapshots, results
