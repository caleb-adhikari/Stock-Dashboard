"""Offline tests for stock_prices.py's pure-data helpers (combine/normalize)
— no network calls; fetch_price_history itself just wraps yfinance and is
exercised via dashboard.py's graceful-failure path instead (see README)."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from earnings_screener.sources.stock_prices import combine_price_histories, normalize_to_pct_change


def test_combine_price_histories_skips_missing_tickers():
    dates = pd.date_range("2026-01-01", periods=3)
    snow_df = pd.DataFrame({"SNOW": [100.0, 110.0, 121.0]}, index=dates)
    combined = combine_price_histories({"SNOW": snow_df, "MISSING": None})
    assert list(combined.columns) == ["SNOW"]
    assert len(combined) == 3


def test_normalize_to_pct_change_starts_at_zero():
    dates = pd.date_range("2026-01-01", periods=3)
    df = pd.DataFrame({"SNOW": [100.0, 110.0, 90.0], "DDOG": [50.0, 55.0, 60.0]}, index=dates)
    normalized = normalize_to_pct_change(df)
    assert normalized["SNOW"].iloc[0] == 0.0
    assert normalized["DDOG"].iloc[0] == 0.0
    assert round(normalized["SNOW"].iloc[1], 4) == 10.0  # +10%
    assert round(normalized["SNOW"].iloc[2], 4) == -10.0  # -10%
    assert round(normalized["DDOG"].iloc[2], 4) == 20.0  # +20%


if __name__ == "__main__":
    test_combine_price_histories_skips_missing_tickers()
    test_normalize_to_pct_change_starts_at_zero()
    print("All stock price helper tests passed.")
