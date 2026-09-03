"""
Offline tests for charting.py — no network, no streamlit.

Builds synthetic GaapQuarter/NonGaapQuarter objects (same technique as
test_ratios.py), runs them through compare.build_comparisons (so the
QuarterComparison objects look exactly like the real pipeline's), and
checks: the derived expense lines, QoQ/YoY growth per metric, chronological
ordering regardless of input order, None-handling, and the axis unit picker.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from earnings_screener.charting import (
    CHART_METRIC_BY_KEY,
    CHART_METRIC_CATALOG,
    DEFAULT_CHART_METRIC_KEYS,
    compute_chart_rows,
    pick_dollar_unit,
)
from earnings_screener.compare import build_comparisons
from earnings_screener.models import GaapQuarter, NonGaapQuarter, QuarterKey


def _gaap(fy, period, **fields) -> GaapQuarter:
    return GaapQuarter(ticker="TEST", key=QuarterKey(fy, period), period_start="", period_end=f"{fy}-01-31", **fields)


def _five_quarters():
    """Q1 FY2026 .. Q1 FY2027 — enough for both a QoQ and a YoY comparison."""
    gaap = [
        _gaap(2026, "Q1", revenue=1000, gross_profit=700, operating_income=-100, net_income=-50, stock_based_comp=300),
        _gaap(2026, "Q2", revenue=1100, gross_profit=770, operating_income=-50, net_income=-25, stock_based_comp=310),
        _gaap(2026, "Q3", revenue=1200, gross_profit=840, operating_income=0, net_income=10, stock_based_comp=320),
        _gaap(2026, "Q4", revenue=1300, gross_profit=910, operating_income=50, net_income=40, stock_based_comp=330),
        _gaap(2027, "Q1", revenue=1500, gross_profit=1050, operating_income=150, net_income=120, stock_based_comp=340),
    ]
    non_gaap = [
        NonGaapQuarter(ticker="TEST", key=QuarterKey(2026, "Q1"), rpo=5000),
        NonGaapQuarter(ticker="TEST", key=QuarterKey(2027, "Q1"), rpo=6500),
    ]
    return build_comparisons(gaap, non_gaap)


def _rows_by(rows, metric_label):
    return {r["Quarter"]: r for r in rows if r["Metric"] == metric_label}


def test_catalog_keys_are_unique_and_defaults_exist():
    keys = [m.key for m in CHART_METRIC_CATALOG]
    assert len(keys) == len(set(keys))
    for key in DEFAULT_CHART_METRIC_KEYS:
        assert key in CHART_METRIC_BY_KEY


def test_rows_are_chronological_even_when_input_is_newest_first():
    comps = _five_quarters()  # build_comparisons returns newest-first
    assert str(comps[0].key) == "Q1 FY2027"
    rows = compute_chart_rows(comps, ["revenue"])
    assert [r["Quarter"] for r in rows] == ["Q1 FY2026", "Q2 FY2026", "Q3 FY2026", "Q4 FY2026", "Q1 FY2027"]


def test_metrics_within_a_quarter_follow_requested_order():
    rows = compute_chart_rows(_five_quarters(), ["net_income", "revenue"])
    first_quarter = [r["Metric"] for r in rows if r["Quarter"] == "Q1 FY2026"]
    assert first_quarter == ["Net Income", "Revenue"]


def test_expense_lines_are_derived_by_subtraction():
    rows = compute_chart_rows(_five_quarters(), ["cost_of_revenue", "operating_expenses", "total_costs"])
    q1 = {r["Metric"]: r["Value"] for r in rows if r["Quarter"] == "Q1 FY2026"}
    assert q1["Cost of Revenue"] == 1000 - 700
    assert q1["Operating Expenses"] == 700 - (-100)
    assert q1["Total Costs & Expenses"] == 1000 - (-100)


def test_qoq_and_yoy_growth_per_metric():
    rows = compute_chart_rows(_five_quarters(), ["revenue", "rpo"])
    revenue = _rows_by(rows, "Revenue")
    # Oldest quarter has nothing to compare against.
    assert revenue["Q1 FY2026"]["QoQ %"] is None
    assert revenue["Q1 FY2026"]["YoY %"] is None
    # Q2 FY2026: 1100 vs 1000 -> +10% QoQ, no year-ago yet.
    assert revenue["Q2 FY2026"]["QoQ %"] == pytest.approx(10.0)
    assert revenue["Q2 FY2026"]["YoY %"] is None
    # Q1 FY2027 crosses the fiscal-year boundary for QoQ (vs Q4 FY2026) and
    # has a year-ago quarter (Q1 FY2026).
    assert revenue["Q1 FY2027"]["QoQ %"] == pytest.approx((1500 - 1300) / 1300 * 100)
    assert revenue["Q1 FY2027"]["YoY %"] == pytest.approx(50.0)

    rpo = _rows_by(rows, "RPO")
    assert rpo["Q1 FY2027"]["YoY %"] == pytest.approx(30.0)
    assert rpo["Q1 FY2027"]["QoQ %"] is None  # no RPO entered for Q4 FY2026
    assert rpo["Q3 FY2026"]["Value"] is None  # still emitted, just empty


def test_growth_uses_abs_denominator_so_shrinking_loss_is_positive():
    rows = compute_chart_rows(_five_quarters(), ["net_income"])
    net = _rows_by(rows, "Net Income")
    # -50 -> -25: loss halved, reported as +50%.
    assert net["Q2 FY2026"]["QoQ %"] == pytest.approx(50.0)
    # 0 -> 50: base of zero can't be divided, so None rather than inf.
    assert _rows_by(compute_chart_rows(_five_quarters(), ["operating_income"]), "Operating Income")["Q4 FY2026"]["QoQ %"] is None


def test_missing_gross_profit_blanks_only_the_lines_that_need_it():
    comps = build_comparisons([_gaap(2026, "Q1", revenue=1000, operating_income=100)], [])
    rows = {r["Metric"]: r["Value"] for r in compute_chart_rows(comps, ["cost_of_revenue", "operating_expenses", "total_costs"])}
    assert rows["Cost of Revenue"] is None
    assert rows["Operating Expenses"] is None
    assert rows["Total Costs & Expenses"] == 900


def test_non_gaap_only_quarter_has_no_gaap_values():
    comps = build_comparisons([], [NonGaapQuarter(ticker="TEST", key=QuarterKey(2027, "Q2"), rpo=9e9)])
    rows = compute_chart_rows(comps, ["revenue", "rpo"])
    by_metric = {r["Metric"]: r for r in rows}
    assert by_metric["Revenue"]["Value"] is None
    assert by_metric["Revenue"]["Period End"] is None
    assert by_metric["RPO"]["Value"] == 9e9


def test_unknown_metric_key_raises():
    with pytest.raises(KeyError):
        compute_chart_rows(_five_quarters(), ["revenue", "ebitda_margin_of_dreams"])


def test_pick_dollar_unit():
    assert pick_dollar_unit([1.55e9, 2e8, None]) == (1e9, "$ billions")
    assert pick_dollar_unit([-450e6, 12e6]) == (1e6, "$ millions")
    assert pick_dollar_unit([2500.0]) == (1e3, "$ thousands")
    assert pick_dollar_unit([12.0]) == (1.0, "$")
    assert pick_dollar_unit([None, None]) == (1.0, "$")
    assert pick_dollar_unit([]) == (1.0, "$")
