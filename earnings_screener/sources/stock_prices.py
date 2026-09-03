"""
Stock price history, via yfinance.

This is intentionally a SEPARATE data source from sec_edgar.py: EDGAR gives
us official, standardized fundamentals (revenue, EPS, RPO); this module
gives us daily closing price so the dashboard can draw a plain price chart
and (optionally) mark where earnings reports landed on it. The two are
fetched and cached independently — a price-chart hiccup should never take
down the fundamentals view, and vice versa.

Why yfinance is fine here even though it's NOT reliable for non-GAAP
earnings figures (see sources/sec_edgar.py's docstring and the project
README for that whole story): plain historical closing prices are exactly
the kind of data yfinance is good at — it's just reading Yahoo Finance's
public chart data, not trying to parse a company's own non-GAAP
reconciliation table out of a press release.

Known rough edge: yfinance scrapes/uses an unofficial Yahoo endpoint, so it
occasionally breaks when Yahoo changes something, independent of anything
in this codebase. If `fetch_price_history` starts failing for everyone,
`pip install --upgrade yfinance` is the first thing to try.
"""

from __future__ import annotations

import pandas as pd


def fetch_price_history(ticker: str, period: str = "1y") -> pd.DataFrame | None:
    """
    Return a DataFrame indexed by date with at least a "Close" column, for
    the last `period` of trading days (yfinance period strings: "1mo",
    "3mo", "6mo", "1y", "2y", "5y", "max", ...).

    Returns None (rather than raising) on any failure — a flaky price feed
    shouldn't crash the whole dashboard, just that one chart.
    """
    try:
        import yfinance as yf
    except ImportError:
        return None

    try:
        history = yf.Ticker(ticker.upper()).history(period=period)
    except Exception:
        # yfinance can raise several different exception types depending on
        # *how* Yahoo's endpoint misbehaves (bad JSON, HTTP error, empty
        # response...) — we treat all of them the same way: no data.
        return None

    if history is None or history.empty:
        return None

    return history[["Close"]].rename(columns={"Close": ticker.upper()})


def combine_price_histories(prices_by_ticker: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    Combine several single-ticker price DataFrames (as returned by
    fetch_price_history) into one DataFrame, one column per ticker, aligned
    on date. Missing tickers/None entries are skipped rather than raising.
    """
    frames = [df for df in prices_by_ticker.values() if df is not None and not df.empty]
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, axis=1)
    return combined


def normalize_to_pct_change(prices: pd.DataFrame) -> pd.DataFrame:
    """
    Rescale each column so it starts at 0% on the first available date for
    that column. This is what makes an overlay of, say, SNOW and a $150
    stock and a $1,500 stock actually comparable on one chart — plotting
    raw prices side by side would just show whichever stock has the
    biggest dollar price, not who actually performed better.
    """
    if prices.empty:
        return prices
    first_valid = prices.apply(lambda col: col.dropna().iloc[0] if col.dropna().size else None)
    return (prices / first_valid - 1.0) * 100
