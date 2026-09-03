"""
Offline tests for cross_company.py + dataframes.py — no network calls.
Builds synthetic FetchResult/QuarterComparison objects directly (same
technique as tests/manual_dry_run.py used during development) so these can
run anywhere, including this sandbox where outbound network is blocked.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from earnings_screener.compare import build_comparisons
from earnings_screener.cross_company import snapshot_from_fetch_result
from earnings_screener.dataframes import comparisons_to_dataframe, snapshots_to_dataframe
from earnings_screener.models import GaapQuarter, NonGaapQuarter, QuarterKey
from earnings_screener.pipeline import FetchResult


def _snow_fetch_result():
    gaap = [
        GaapQuarter(
            ticker="SNOW",
            key=QuarterKey(2026, "Q2"),
            period_start="2025-05-01",
            period_end="2025-07-31",
            revenue=1_144_969_000,
            eps_diluted=-0.89,
        ),
        GaapQuarter(
            ticker="SNOW",
            key=QuarterKey(2027, "Q1"),
            period_start="2026-02-01",
            period_end="2026-04-30",
            revenue=1_390_951_000,
            eps_diluted=-0.86,
        ),
        GaapQuarter(
            ticker="SNOW",
            key=QuarterKey(2027, "Q2"),
            period_start="2026-05-01",
            period_end="2026-07-31",
            revenue=1_550_000_000,
            eps_diluted=-0.55,
        ),
    ]
    non_gaap = [
        NonGaapQuarter(ticker="SNOW", key=QuarterKey(2027, "Q2"), non_gaap_eps=0.62, rpo=9_000_000_000, nrr_pct=126),
        NonGaapQuarter(ticker="SNOW", key=QuarterKey(2027, "Q1"), rpo=9_210_000_000),
        NonGaapQuarter(ticker="SNOW", key=QuarterKey(2026, "Q2"), rpo=6_900_000_000),
    ]
    comparisons = build_comparisons(gaap, non_gaap)
    return FetchResult(ticker="SNOW", comparisons=comparisons, gaap_fetch_error=None)


def test_snapshot_picks_latest_quarter_with_gaap():
    result = _snow_fetch_result()
    snap = snapshot_from_fetch_result(result)
    assert snap.ticker == "SNOW"
    assert str(snap.key) == "Q2 FY2027"
    assert snap.revenue == 1_550_000_000
    assert snap.non_gaap_eps == 0.62
    assert snap.gaap_fetch_error is None


def test_snapshot_handles_missing_gaap_gracefully():
    result = FetchResult(ticker="MISSING", comparisons=[], gaap_fetch_error="couldn't resolve CIK")
    snap = snapshot_from_fetch_result(result)
    assert snap.ticker == "MISSING"
    assert snap.gaap_fetch_error == "couldn't resolve CIK"
    assert snap.revenue is None


def test_dataframes_round_trip_without_error():
    result = _snow_fetch_result()
    df = comparisons_to_dataframe(result.comparisons)
    assert len(df) == 3
    assert list(df["Quarter"]) == ["Q2 FY2026", "Q1 FY2027", "Q2 FY2027"]  # chronological order

    snap = snapshot_from_fetch_result(result)
    snap_df = snapshots_to_dataframe([snap])
    assert snap_df.loc[0, "Ticker"] == "SNOW"
    assert snap_df.loc[0, "Revenue"] == 1_550_000_000


if __name__ == "__main__":
    test_snapshot_picks_latest_quarter_with_gaap()
    test_snapshot_handles_missing_gaap_gracefully()
    test_dataframes_round_trip_without_error()
    print("All cross-company/dataframe tests passed.")
