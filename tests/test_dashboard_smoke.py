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
    at.sidebar.text_input(key=None)  # no-op touch to ensure sidebar widgets are indexed
    email_box = at.sidebar.text_input[0]
    email_box.set_value("test@example.com").run()

    ticker_box = at.sidebar.text_input[1]
    ticker_box.set_value("SNOW").run()

    assert not at.exception, f"dashboard raised after entering ticker/email: {at.exception}"

    # Pick a couple of ratios in the multiselect (this exercises
    # compute_ratio_rows + ratio_rows_to_dataframe + the chart/table code).
    if at.multiselect:
        ratio_picker = at.multiselect[0]
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


if __name__ == "__main__":
    test_dashboard_loads_without_exceptions()
    test_ratios_tab_renders_after_picking_a_ticker_and_ratios()
    test_charts_tab_renders_with_seeded_ticker()
    test_charts_tab_builds_altair_charts_from_synthetic_data()
    print("Dashboard smoke tests passed.")
