"""
Offline tests for ratios.py — no network calls.

Builds synthetic GaapQuarter/NonGaapQuarter/QuarterComparison objects
directly (same technique as test_cross_company.py) covering: the TTM
window logic (needs exactly 4 full quarters), the plain per-quarter
ratios (margins, current ratio), and the valuation ratios' "show N/A
instead of a negative number" behavior when TTM earnings or book value
are negative.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from earnings_screener.models import GaapQuarter, NonGaapQuarter, QuarterComparison, QuarterKey
from earnings_screener.ratios import (
    RATIO_BY_KEY,
    RATIO_CATALOG,
    _pb_ratio,
    _pe_gaap,
    _pe_non_gaap,
    _roe,
    _ttm,
    compute_ratio_rows,
)


def _comp(fy, period, revenue=None, gross_profit=None, operating_income=None, net_income=None,
          eps_diluted=None, diluted_shares=None, stockholders_equity=None, total_assets=None,
          current_assets=None, current_liabilities=None, non_gaap_eps=None,
          revenue_qoq_pct=None, revenue_yoy_pct=None):
    """Build one QuarterComparison with just the fields a given test needs;
    everything else stays None, matching how a real quarter with partial
    XBRL data would look."""
    key = QuarterKey(fy, period)
    gaap = GaapQuarter(
        ticker="TEST",
        key=key,
        period_start="2026-01-01",
        period_end="2026-03-31",
        revenue=revenue,
        gross_profit=gross_profit,
        operating_income=operating_income,
        net_income=net_income,
        eps_diluted=eps_diluted,
        diluted_shares=diluted_shares,
        stockholders_equity=stockholders_equity,
        total_assets=total_assets,
        current_assets=current_assets,
        current_liabilities=current_liabilities,
    )
    non_gaap = NonGaapQuarter(ticker="TEST", key=key, non_gaap_eps=non_gaap_eps) if non_gaap_eps is not None else None
    return QuarterComparison(
        ticker="TEST",
        key=key,
        gaap=gaap,
        non_gaap=non_gaap,
        revenue_qoq_pct=revenue_qoq_pct,
        revenue_yoy_pct=revenue_yoy_pct,
    )


def _four_quarters(net_incomes):
    """Newest-first list of 4 comparisons, each with the given net_income,
    everything else minimal — for exercising _ttm()."""
    assert len(net_incomes) == 4
    periods = [("2027", "Q1"), ("2026", "Q4"), ("2026", "Q3"), ("2026", "Q2")]
    return [
        _comp(int(fy), p, net_income=ni)
        for (fy, p), ni in zip(periods, net_incomes)
    ]


def test_ttm_sums_four_quarters():
    comparisons = _four_quarters([100, 90, 80, 70])
    assert _ttm(comparisons, 0, lambda c: c.gaap.net_income if c.gaap else None) == 340


def test_ttm_returns_none_with_fewer_than_four_quarters():
    comparisons = _four_quarters([100, 90, 80, 70])[:3]
    assert _ttm(comparisons, 0, lambda c: c.gaap.net_income if c.gaap else None) is None


def test_ttm_returns_none_if_any_quarter_missing_the_figure():
    comparisons = _four_quarters([100, 90, 80, 70])
    comparisons[2].gaap.net_income = None
    assert _ttm(comparisons, 0, lambda c: c.gaap.net_income if c.gaap else None) is None


def test_gross_and_operating_and_net_margin():
    comp = _comp(2027, "Q1", revenue=1000, gross_profit=750, operating_income=200, net_income=100)
    row = compute_ratio_rows([comp], ["gross_margin", "operating_margin", "net_margin"])[0]
    assert row["Gross Margin %"] == 75.0
    assert row["Operating Margin %"] == 20.0
    assert row["Net Margin %"] == 10.0


def test_current_ratio():
    comp = _comp(2027, "Q1", current_assets=500, current_liabilities=250)
    row = compute_ratio_rows([comp], ["current_ratio"])[0]
    assert row["Current Ratio"] == 2.0


def test_current_ratio_none_without_liabilities():
    comp = _comp(2027, "Q1", current_assets=500)
    row = compute_ratio_rows([comp], ["current_ratio"])[0]
    assert row["Current Ratio"] is None


def test_roe_uses_ttm_net_income_over_latest_equity():
    comparisons = _four_quarters([100, 90, 80, 70])
    comparisons[0].gaap.stockholders_equity = 1700  # TTM net income = 340 -> ROE 20%
    assert _roe(comparisons, 0, None) == 20.0


def test_roe_none_without_full_ttm_window():
    comparisons = _four_quarters([100, 90, 80, 70])[:3]
    comparisons[0].gaap.stockholders_equity = 1700
    assert _roe(comparisons, 0, None) is None


def test_pe_gaap_positive_ttm_earnings():
    comparisons = _four_quarters([25, 25, 25, 25])  # TTM EPS-equivalent net income = 100
    for c in comparisons:
        c.gaap.eps_diluted = 1.0  # each quarter contributes 1.0 -> TTM EPS 4.0
    assert _pe_gaap(comparisons, 0, 40.0) == 10.0  # price 40 / TTM EPS 4 = 10x


def test_pe_gaap_none_when_ttm_earnings_negative():
    comparisons = _four_quarters([0, 0, 0, 0])
    for c in comparisons:
        c.gaap.eps_diluted = -0.5
    assert _pe_gaap(comparisons, 0, 40.0) is None


def test_pe_gaap_none_without_price():
    comparisons = _four_quarters([0, 0, 0, 0])
    for c in comparisons:
        c.gaap.eps_diluted = 1.0
    assert _pe_gaap(comparisons, 0, None) is None


def test_pe_non_gaap_uses_non_gaap_eps_series():
    comparisons = _four_quarters([0, 0, 0, 0])
    for c in comparisons:
        c.non_gaap = NonGaapQuarter(ticker="TEST", key=c.key, non_gaap_eps=0.5)
    assert _pe_non_gaap(comparisons, 0, 20.0) == 10.0  # price 20 / TTM non-GAAP EPS 2.0 = 10x


def test_pb_ratio_none_when_book_value_negative():
    comp = _comp(2027, "Q1", diluted_shares=100, stockholders_equity=-500)
    assert _pb_ratio([comp], 0, 25.0) is None


def test_pb_ratio_normal_case():
    comp = _comp(2027, "Q1", diluted_shares=100, stockholders_equity=1000)  # book value/share = 10
    assert _pb_ratio([comp], 0, 25.0) == 2.5


def test_revenue_growth_columns_pass_through_comparison_fields():
    comp = _comp(2027, "Q1", revenue_qoq_pct=5.5, revenue_yoy_pct=-2.0)
    row = compute_ratio_rows([comp], ["revenue_qoq", "revenue_yoy"])[0]
    assert row["Revenue Growth QoQ %"] == 5.5
    assert row["Revenue Growth YoY %"] == -2.0


def test_compute_ratio_rows_shape_and_order():
    comparisons = [_comp(2027, "Q2", revenue=100), _comp(2027, "Q1", revenue=90)]
    rows = compute_ratio_rows(comparisons, ["gross_margin"], latest_price=None)
    assert [r["Quarter"] for r in rows] == ["Q2 FY2027", "Q1 FY2027"]  # same order as input, not re-sorted


def test_every_catalog_entry_is_reachable_by_key_and_runs_without_crashing():
    comp = _comp(2027, "Q1", revenue=100, gross_profit=50, operating_income=10, net_income=5,
                 eps_diluted=0.1, diluted_shares=10, stockholders_equity=200, total_assets=500,
                 current_assets=80, current_liabilities=40, non_gaap_eps=0.2)
    all_keys = [r.key for r in RATIO_CATALOG]
    rows = compute_ratio_rows([comp], all_keys, latest_price=15.0)
    assert len(rows) == 1
    for ratio in RATIO_CATALOG:
        assert ratio.label in rows[0]
        assert RATIO_BY_KEY[ratio.key] is ratio


if __name__ == "__main__":
    test_ttm_sums_four_quarters()
    test_ttm_returns_none_with_fewer_than_four_quarters()
    test_ttm_returns_none_if_any_quarter_missing_the_figure()
    test_gross_and_operating_and_net_margin()
    test_current_ratio()
    test_current_ratio_none_without_liabilities()
    test_roe_uses_ttm_net_income_over_latest_equity()
    test_roe_none_without_full_ttm_window()
    test_pe_gaap_positive_ttm_earnings()
    test_pe_gaap_none_when_ttm_earnings_negative()
    test_pe_gaap_none_without_price()
    test_pe_non_gaap_uses_non_gaap_eps_series()
    test_pb_ratio_none_when_book_value_negative()
    test_pb_ratio_normal_case()
    test_revenue_growth_columns_pass_through_comparison_fields()
    test_compute_ratio_rows_shape_and_order()
    test_every_catalog_entry_is_reachable_by_key_and_runs_without_crashing()
    print("All ratio tests passed.")
