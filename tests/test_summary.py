"""
Offline tests for summary.py (the trimmed YoY table) and units.py (the
Millions/Billions display scaling) — no network calls, synthetic data.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from earnings_screener.compare import build_comparisons
from earnings_screener.models import GaapQuarter, NonGaapQuarter, QuarterKey
from earnings_screener.summary import BASES, build_summary_rows, summary_columns
from earnings_screener.units import format_dollars, scale_dollars


def _comparisons():
    gaap = [
        GaapQuarter("T", QuarterKey(2026, "Q2"), "2025-05-01", "2025-07-31",
                    revenue=1_000_000_000, operating_income=-100_000_000, net_income=-300_000_000, eps_diluted=-0.90),
        GaapQuarter("T", QuarterKey(2027, "Q1"), "2026-02-01", "2026-04-30",
                    revenue=1_300_000_000, operating_income=-80_000_000, net_income=-280_000_000, eps_diluted=-0.86),
        GaapQuarter("T", QuarterKey(2027, "Q2"), "2026-05-01", "2026-07-31",
                    revenue=1_500_000_000, operating_income=-50_000_000, net_income=-180_000_000, eps_diluted=-0.55),
    ]
    non_gaap = [
        NonGaapQuarter("T", QuarterKey(2027, "Q2"), non_gaap_eps=0.62, rpo=9_000_000_000, nrr_pct=126),
        NonGaapQuarter("T", QuarterKey(2026, "Q2"), non_gaap_eps=0.40, rpo=6_900_000_000),
    ]
    return build_comparisons(gaap, non_gaap)


def test_gaap_rows_have_value_and_yoy_columns_and_are_newest_first():
    rows = build_summary_rows(_comparisons(), "GAAP")
    assert [r["Quarter"] for r in rows] == ["Q2 FY2027", "Q1 FY2027", "Q2 FY2026"]
    latest = rows[0]
    assert latest["Revenue"] == 1_500_000_000  # full dollars, not scaled
    assert round(latest["Revenue YoY %"], 1) == 50.0  # 1.5B vs 1.0B a year earlier
    # Net loss shrank from -300M to -180M: reads as +40% (improvement), same convention as compare.py
    assert round(latest["Net Income YoY %"], 1) == 40.0
    assert latest["Diluted EPS"] == -0.55


def test_yoy_is_none_when_no_year_ago_quarter():
    rows = build_summary_rows(_comparisons(), "GAAP")
    q1 = next(r for r in rows if r["Quarter"] == "Q1 FY2027")
    assert q1["Revenue YoY %"] is None  # no Q1 FY2026 in the data
    oldest = rows[-1]
    assert oldest["Revenue YoY %"] is None


def test_non_gaap_basis_uses_press_release_figures():
    rows = build_summary_rows(_comparisons(), "Non-GAAP")
    latest = rows[0]
    assert latest["Revenue"] == 1_500_000_000  # total revenue stays as the anchor column
    assert latest["Non-GAAP EPS"] == 0.62
    assert round(latest["Non-GAAP EPS YoY %"], 1) == 55.0  # 0.62 vs 0.40
    assert latest["RPO"] == 9_000_000_000
    assert latest["NRR %"] == 126
    assert "NRR % YoY %" not in latest  # show_yoy=False for percentage metrics


def test_both_basis_shows_gap_columns():
    rows = build_summary_rows(_comparisons(), "Both")
    latest = rows[0]
    assert latest["GAAP EPS"] == -0.55
    assert latest["Non-GAAP EPS"] == 0.62
    assert round(latest["EPS Gap"], 2) == 1.17


def test_columns_match_row_keys_for_every_basis():
    comparisons = _comparisons()
    for basis in BASES:
        labels = [c.label for c in summary_columns(basis)]
        for row in build_summary_rows(comparisons, basis):
            assert list(row.keys()) == labels, f"{basis}: {list(row.keys())} != {labels}"


def test_unknown_basis_raises():
    try:
        build_summary_rows(_comparisons(), "Adjusted-ish")
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "Adjusted-ish" in str(exc)


def test_scale_and_format_dollars():
    assert scale_dollars(1_550_000_000, "Millions") == 1550.0
    assert scale_dollars(1_550_000_000, "Billions") == 1.55
    assert scale_dollars(None, "Billions") is None
    assert format_dollars(1_550_000_000, "Millions") == "$1,550.0M"
    assert format_dollars(1_550_000_000, "Billions") == "$1.55B"
    assert format_dollars(-180_000_000, "Millions") == "-$180.0M"
    assert format_dollars(None) == "—"


if __name__ == "__main__":
    test_gaap_rows_have_value_and_yoy_columns_and_are_newest_first()
    test_yoy_is_none_when_no_year_ago_quarter()
    test_non_gaap_basis_uses_press_release_figures()
    test_both_basis_shows_gap_columns()
    test_columns_match_row_keys_for_every_basis()
    test_unknown_basis_raises()
    test_scale_and_format_dollars()
    print("All summary/units tests passed.")
