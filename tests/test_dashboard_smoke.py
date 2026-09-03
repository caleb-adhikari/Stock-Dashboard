"""
A smoke test for dashboard.py using Streamlit's headless AppTest — no real
browser, no network required. This isn't testing the ratio *math* (that's
tests/test_ratios.py, offline against synthetic data); it's testing that
the dashboard script itself runs without crashing once you've entered a
ticker/email and picked some ratios from the new dropdown, including in
this sandbox where the live SEC EDGAR/Yahoo Finance calls will fail (no
outbound network here) — pipeline.py is designed to catch that and show a
warning instead of raising, and this test proves the Ratios tab code path
handles a GAAP-fetch failure (empty GAAP data) without blowing up either.

Run with:  python -m pytest tests/test_dashboard_smoke.py
(needs `pip install -r requirements.txt` first — streamlit/pandas/yfinance)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DASHBOARD_PATH = str(Path(__file__).resolve().parents[1] / "dashboard.py")


def _run_app():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(DASHBOARD_PATH, default_timeout=30)
    at.run()
    return at


def test_dashboard_loads_without_exceptions():
    at = _run_app()
    assert not at.exception, f"dashboard raised on initial load: {at.exception}"


def test_ratios_tab_renders_after_picking_a_ticker_and_ratios():
    at = _run_app()

    # Sidebar: email + primary ticker (SNOW has seeded non-GAAP data, so
    # even with the live GAAP fetch failing here for lack of network, the
    # comparisons list won't be empty and the Ratios tab has something to
    # iterate over).
    email_box = at.sidebar.text_input[0]
    email_box.set_value("test@example.com").run()

    ticker_box = at.sidebar.text_input[1]
    ticker_box.set_value("SNOW").run()

    assert not at.exception, f"dashboard raised after entering ticker/email: {at.exception}"

    # Flip through every basis (GAAP is the default) and both dollar units —
    # each combination re-renders the Summary table, the Charts tab and the
    # Compare table with different column sets, so this catches a typo'd
    # column name in any of them.
    basis_radio = at.sidebar.radio[0]
    units_box = at.sidebar.selectbox[0]
    for basis in ("GAAP", "Non-GAAP", "Both"):
        for units in ("Millions", "Billions"):
            basis_radio.set_value(basis)
            units_box.set_value(units).run()
            assert not at.exception, f"dashboard raised for basis={basis}, units={units}: {at.exception}"

    # Pick a couple of ratios in the multiselect (this exercises
    # compute_ratio_rows + ratio_rows_to_dataframe + the chart/table code).
    ratio_picker = next((m for m in at.multiselect if m.key == "ratio_keys"), None)
    if ratio_picker is not None:
        ratio_picker.set_value(["gross_margin", "revenue_yoy"]).run()
        assert not at.exception, f"dashboard raised after selecting ratios: {at.exception}"


def test_charts_tab_renders_with_seeded_ticker():
    """With the live GAAP fetch failing (no network), the Charts tab only has
    non-GAAP quarters to work with — every GAAP metric is None. This proves
    the "nothing to plot for these metrics" path and the RPO-only path both
    render without raising."""
    at = _run_app()
    at.sidebar.text_input[0].set_value("test@example.com").run()
    at.sidebar.text_input[1].set_value("SNOW").run()
    assert not at.exception, f"dashboard raised after entering ticker/email: {at.exception}"

    chart_picker = next((m for m in at.multiselect if m.key == "chart_metrics"), None)
    assert chart_picker is not None, "Charts tab multiselect not found"
    chart_picker.set_value(["revenue", "rpo"]).run()
    assert not at.exception, f"dashboard raised after selecting chart metrics: {at.exception}"

    chart_picker.set_value([]).run()
    assert not at.exception, f"dashboard raised with no chart metrics selected: {at.exception}"


# A tiny standalone Streamlit script that calls render_charts_tab() directly
# with synthetic quarters, so the Altair chart-building code runs against
# real numbers (bars AND lines, QoQ/YoY/Both) without any network. Importing
# dashboard.py executes its top-level page code too, which is harmless here.
_CHARTS_SCRIPT = f"""
import sys
sys.path.insert(0, {str(Path(__file__).resolve().parents[1])!r})
import streamlit as st
from dashboard import render_charts_tab
from earnings_screener.compare import build_comparisons
from earnings_screener.models import GaapQuarter, NonGaapQuarter, QuarterKey

def g(fy, p, rev, gp, oi, ni):
    return GaapQuarter("TEST", QuarterKey(fy, p), "", f"{{fy}}-01-31", revenue=rev, gross_profit=gp,
                       operating_income=oi, net_income=ni, stock_based_comp=rev * 0.3)

comps = build_comparisons(
    [g(2026, "Q1", 1.0e9, 0.7e9, -0.1e9, -0.05e9), g(2026, "Q2", 1.1e9, 0.77e9, -0.05e9, -0.02e9),
     g(2026, "Q3", 1.2e9, 0.84e9, 0.0, 0.01e9), g(2026, "Q4", 1.3e9, 0.91e9, 0.05e9, 0.04e9),
     g(2027, "Q1", 1.5e9, 1.05e9, 0.15e9, 0.12e9)],
    [NonGaapQuarter("TEST", QuarterKey(2026, "Q1"), rpo=5e9), NonGaapQuarter("TEST", QuarterKey(2027, "Q1"), rpo=6.5e9)],
)
render_charts_tab("TEST", comps)
"""


def test_charts_tab_builds_altair_charts_from_synthetic_data():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_string(_CHARTS_SCRIPT, default_timeout=30)
    at.run()
    assert not at.exception, f"charts tab raised on synthetic data: {at.exception}"
    # Two charts by default: quarterly values + YoY growth.
    assert len(at.get("vega_lite_chart")) == 2

    picker = next(m for m in at.multiselect if m.key == "chart_metrics")
    picker.set_value(["revenue", "cost_of_revenue", "operating_expenses", "rpo"]).run()
    assert not at.exception

    for style in ("Lines", "Bars"):
        next(r for r in at.radio if r.key == "chart_value_style").set_value(style).run()
        assert not at.exception, f"charts tab raised with value style {style}: {at.exception}"
    for basis in ("QoQ", "Both", "YoY"):
        next(r for r in at.radio if r.key == "chart_growth_basis").set_value(basis).run()
        assert not at.exception, f"charts tab raised with growth basis {basis}: {at.exception}"
        assert len(at.get("vega_lite_chart")) == 2


def _synthetic_fetch_result(ticker: str, email: str, quarters: int = 8):
    """Stand-in for pipeline.get_comparisons_for_ticker with a full set of
    GAAP + non-GAAP fields populated, so every column in every table and
    chart actually has numbers in it (the live fetch can't run here)."""
    from earnings_screener.compare import build_comparisons
    from earnings_screener.models import GaapQuarter, NonGaapQuarter, QuarterKey
    from earnings_screener.pipeline import FetchResult

    keys = [(2026, "Q1"), (2026, "Q2"), (2026, "Q3"), (2027, "Q1"), (2027, "Q2")]
    gaap, non_gaap = [], []
    for i, (fy, q) in enumerate(keys):
        rev = 1_000_000_000 + i * 120_000_000
        gaap.append(
            GaapQuarter(
                ticker=ticker, key=QuarterKey(fy, q), period_start="2026-01-01", period_end=f"2026-0{i + 1}-28",
                revenue=rev, gross_profit=rev * 0.7, operating_income=-50_000_000 + i * 10_000_000,
                net_income=-200_000_000 + i * 30_000_000, eps_diluted=-0.9 + i * 0.1, diluted_shares=340_000_000,
                stock_based_comp=400_000_000, total_assets=9_000_000_000, total_liabilities=3_000_000_000,
                stockholders_equity=6_000_000_000, current_assets=5_000_000_000, current_liabilities=2_000_000_000,
                cash=1_000_000_000,
            )
        )
        non_gaap.append(
            NonGaapQuarter(
                ticker=ticker, key=QuarterKey(fy, q), non_gaap_eps=0.3 + i * 0.08, non_gaap_operating_margin_pct=10 + i,
                rpo=6_000_000_000 + i * 700_000_000, nrr_pct=126, product_revenue=rev * 0.95,
            )
        )
    return FetchResult(ticker=ticker, comparisons=build_comparisons(gaap, non_gaap), gaap_fetch_error=None)


def test_every_basis_and_unit_renders_with_full_synthetic_data():
    import earnings_screener.pipeline as pipeline

    original = pipeline.get_comparisons_for_ticker
    pipeline.get_comparisons_for_ticker = _synthetic_fetch_result
    try:
        import streamlit as st

        # st.cache_data is process-wide, so the earlier test's (failed-fetch)
        # SNOW result would otherwise be served here instead of the synthetic
        # data — clear it, and use a different ticker for good measure.
        st.cache_data.clear()
        at = _run_app()
        at.sidebar.text_input[0].set_value("test@example.com").run()
        at.sidebar.text_input[1].set_value("SYNTH").run()
        assert not at.exception, f"raised on load with synthetic data: {at.exception}"

        basis_radio = at.sidebar.radio[0]
        units_box = at.sidebar.selectbox[0]
        for basis in ("GAAP", "Non-GAAP", "Both"):
            for units in ("Millions", "Billions"):
                basis_radio.set_value(basis)
                units_box.set_value(units).run()
                assert not at.exception, f"raised for basis={basis}, units={units}: {at.exception}"

        # The summary table must actually contain the scaled figure: latest
        # quarter revenue is $1.48B -> 1480.0 in Millions, 1.48 in Billions.
        basis_radio.set_value("GAAP")
        units_box.set_value("Millions").run()
        summary_df = at.dataframe[0].value
        assert abs(summary_df.iloc[0]["Revenue"] - 1480.0) < 1e-6, summary_df.iloc[0]
        units_box.set_value("Billions").run()
        summary_df = at.dataframe[0].value
        assert abs(summary_df.iloc[0]["Revenue"] - 1.48) < 1e-6, summary_df.iloc[0]

        ratio_picker = next((m for m in at.multiselect if m.key == "ratio_keys"), None)
        if ratio_picker is not None:
            ratio_picker.set_value(["gross_margin", "roe", "pe_gaap", "pb_ratio"]).run()
            assert not at.exception, f"raised computing ratios on synthetic data: {at.exception}"
    finally:
        pipeline.get_comparisons_for_ticker = original


if __name__ == "__main__":
    test_dashboard_loads_without_exceptions()
    test_ratios_tab_renders_after_picking_a_ticker_and_ratios()
    test_charts_tab_renders_with_seeded_ticker()
    test_charts_tab_builds_altair_charts_from_synthetic_data()
    test_every_basis_and_unit_renders_with_full_synthetic_data()
    print("Dashboard smoke tests passed.")
