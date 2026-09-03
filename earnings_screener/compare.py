"""
Merges GAAP + non-GAAP data and computes the comparison metrics.

This is deliberately kept separate from both the SEC EDGAR fetcher and the
manual non-GAAP loader — this module doesn't know or care where the data
came from, it just takes two lists of typed objects (see models.py) and
produces QuarterComparison objects. That separation is what lets you swap
in an automated non-GAAP scraper later, or add a second data source (say,
another ticker or a different filer), without touching this file.
"""

from __future__ import annotations

from earnings_screener.models import GaapQuarter, NonGaapQuarter, QuarterComparison, QuarterKey


def _pct_change(new: float | None, old: float | None) -> float | None:
    """Percent change from `old` to `new`. Returns None if either value is
    missing or `old` is zero (can't divide by zero)."""
    if new is None or old is None or old == 0:
        return None
    return (new - old) / abs(old) * 100


def build_comparisons(
    gaap_quarters: list[GaapQuarter],
    non_gaap_quarters: list[NonGaapQuarter],
) -> list[QuarterComparison]:
    """
    Merge by QuarterKey (fiscal year + fiscal period) and compute:
      - eps_gap: how far non-GAAP EPS is from GAAP diluted EPS
      - implied_gap_dollars: that gap translated into a dollar amount, using
        the diluted share count, so it can be compared to revenue
      - gap_pct_of_revenue: the gap sized against revenue, which is more
        useful for comparing gap size across quarters of different revenue
        scale than a raw dollar or per-share number would be
      - sbc_pct_of_revenue: stock-based comp as a % of revenue — usually the
        single largest component of the GAAP/non-GAAP gap for software
        companies, shown separately so you can see how much of the gap it
        explains
      - revenue/RPO QoQ and YoY % changes, so divergences between the two
        (e.g. YoY still positive while QoQ is negative) are visible at a
        glance rather than requiring you to do the arithmetic yourself
    """
    gaap_by_key = {q.key: q for q in gaap_quarters}
    non_gaap_by_key = {q.key: q for q in non_gaap_quarters}
    all_keys = sorted(set(gaap_by_key) | set(non_gaap_by_key), reverse=True)

    # Index GAAP quarters by key for QoQ/YoY lookups (previous quarter, same
    # quarter last year). This assumes standard fiscal quarter numbering
    # (Q1-Q4); it will not correctly find "previous quarter" across a fiscal
    # year boundary if a quarter is missing from the data.
    def prior_quarter_key(key: QuarterKey) -> QuarterKey | None:
        if key.fiscal_period == "Q1":
            return QuarterKey(key.fiscal_year - 1, "Q4")
        q_num = int(key.fiscal_period[-1])
        return QuarterKey(key.fiscal_year, f"Q{q_num - 1}")

    def year_ago_key(key: QuarterKey) -> QuarterKey:
        return QuarterKey(key.fiscal_year - 1, key.fiscal_period)

    comparisons = []
    for key in all_keys:
        gaap = gaap_by_key.get(key)
        non_gaap = non_gaap_by_key.get(key)
        comp = QuarterComparison(
            ticker=(gaap.ticker if gaap else non_gaap.ticker),
            key=key,
            gaap=gaap,
            non_gaap=non_gaap,
        )

        if gaap and non_gaap and gaap.eps_diluted is not None and non_gaap.non_gaap_eps is not None:
            comp.eps_gap = non_gaap.non_gaap_eps - gaap.eps_diluted
            if gaap.diluted_shares:
                comp.implied_gap_dollars = comp.eps_gap * gaap.diluted_shares
                if gaap.revenue:
                    comp.gap_pct_of_revenue = comp.implied_gap_dollars / gaap.revenue * 100

        if gaap and gaap.stock_based_comp is not None and gaap.revenue:
            comp.sbc_pct_of_revenue = gaap.stock_based_comp / gaap.revenue * 100

        prior_gaap = gaap_by_key.get(prior_quarter_key(key)) if gaap else None
        year_ago_gaap = gaap_by_key.get(year_ago_key(key)) if gaap else None
        if gaap:
            comp.revenue_qoq_pct = _pct_change(gaap.revenue, prior_gaap.revenue if prior_gaap else None)
            comp.revenue_yoy_pct = _pct_change(gaap.revenue, year_ago_gaap.revenue if year_ago_gaap else None)

        prior_non_gaap = non_gaap_by_key.get(prior_quarter_key(key)) if non_gaap else None
        year_ago_non_gaap = non_gaap_by_key.get(year_ago_key(key)) if non_gaap else None
        if non_gaap:
            comp.rpo_qoq_pct = _pct_change(non_gaap.rpo, prior_non_gaap.rpo if prior_non_gaap else None)
            comp.rpo_yoy_pct = _pct_change(non_gaap.rpo, year_ago_non_gaap.rpo if year_ago_non_gaap else None)

        comparisons.append(comp)

    return comparisons


def find_divergences(comparisons: list[QuarterComparison]) -> list[str]:
    """
    Plain-English call-outs for the exact pattern that kicked off this
    project: a metric still growing year-over-year while shrinking
    quarter-over-quarter (deceleration, seasonality, or a real slowdown
    worth a closer look) — checked for both RPO and revenue. This is
    shared by cli.py and dashboard.py so the two never disagree about
    what counts as "worth flagging."
    """
    messages = []
    for comp in comparisons:
        if comp.rpo_qoq_pct is not None and comp.rpo_qoq_pct < 0 and (comp.rpo_yoy_pct or 0) > 0:
            messages.append(
                f"{comp.key}: RPO fell {comp.rpo_qoq_pct:.1f}% QoQ while still up {comp.rpo_yoy_pct:.1f}% YoY."
            )
        if comp.revenue_qoq_pct is not None and comp.revenue_qoq_pct < 0 and (comp.revenue_yoy_pct or 0) > 0:
            messages.append(
                f"{comp.key}: Revenue fell {comp.revenue_qoq_pct:.1f}% QoQ while still up {comp.revenue_yoy_pct:.1f}% YoY."
            )
    return messages
