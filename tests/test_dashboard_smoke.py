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


if __name__ == "__main__":
    test_dashboard_loads_without_exceptions()
    test_ratios_tab_renders_after_picking_a_ticker_and_ratios()
    print("Dashboard smoke tests passed.")
