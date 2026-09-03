"""
Interactive dashboard, built with Streamlit.

RUN IT WITH:
    streamlit run dashboard.py

WHAT STREAMLIT IS, IF YOU HAVEN'T USED IT
--------------------------------------------
Streamlit turns a plain Python script into a browser-based app. There's no
HTML/CSS/JS to write: you call functions like `st.title(...)` or
`st.line_chart(...)` and Streamlit renders the corresponding widget in the
browser. `streamlit run` starts a small local web server (default
http://localhost:8501) and opens it in your browser.

THE ONE THING ABOUT STREAMLIT THAT SURPRISES EVERYONE AT FIRST
------------------------------------------------------------------
Streamlit re-runs this ENTIRE script, top to bottom, every time you
interact with a widget (move a slider, type in a box, switch tabs). That's
its whole programming model — there's no manual event-wiring. The
consequence: without caching, moving the "quarters of history" slider
would re-fetch from SEC EDGAR and Yahoo Finance on every single tick,
which is slow and rude to those free services. That's what the
`@st.cache_data(ttl=...)` decorators below are for — they remember a
function's result for a given set of arguments for `ttl` seconds, so
re-running the script re-uses cached data instead of re-fetching.

WHY THE TWO TABS ARE FUNCTIONS, NOT JUST TOP-LEVEL CODE
------------------------------------------------------------
`st.stop()` halts the ENTIRE script rerun, not just "the current tab" —
there's no way to bail out of one tab's content without also skipping
every tab after it. Wrapping each tab's content in its own function and
using an ordinary `return` instead of `st.stop()` fixes that: an early
return only exits that one function, so the Watchlist tab still renders
even if, say, the Earnings Screener tab has nothing to show yet because
no contact email has been entered.

LAYOUT
--------
This file is intentionally "thin," same philosophy as cli.py: all the
actual data logic (fetching, merging, computing gaps/growth rates) lives
in the earnings_screener package. This file just calls into it and hands
the results to Streamlit widgets.
"""

from __future__ import annotations

import os

import pandas as pd
import streamlit as st

from earnings_screener.compare import find_divergences
from earnings_screener.cross_company import build_snapshot_table
from earnings_screener.dataframes import comparisons_to_dataframe, snapshots_to_dataframe
from earnings_screener.pipeline import FetchResult, get_comparisons_for_ticker
from earnings_screener.sources.stock_prices import (
    combine_price_histories,
    fetch_price_history,
    normalize_to_pct_change,
)
from earnings_screener.watchlist import load_watchlist, save_watchlist

EMAIL_ENV_VAR = "EARNINGS_SCREENER_EMAIL"

st.set_page_config(page_title="Stock Dashboard", layout="wide")


# ---------------------------------------------------------------------------
# Cached data-fetching wrappers.
#
# These are the ONLY place caching happens — everything downstream of them
# (compare.py, dataframes.py) is cheap, pure Python that's fine to re-run
# on every Streamlit rerun. Only network calls need caching. Both tabs
# share `cached_price_history`, so looking up the same ticker in the
# Earnings Screener tab and the Watchlist tab only fetches it once.
# ---------------------------------------------------------------------------


@st.cache_data(ttl=3600, show_spinner="Fetching GAAP + non-GAAP data...")
def cached_ticker_data(ticker: str, email: str, quarters: int) -> FetchResult:
    return get_comparisons_for_ticker(ticker, email=email, quarters=quarters)


@st.cache_data(ttl=3600, show_spinner="Fetching comparison companies...")
def cached_snapshot_table(tickers: tuple[str, ...], email: str, quarters: int):
    # tickers is a tuple (not a list) specifically because st.cache_data
    # needs hashable arguments to know when it can reuse a cached result.
    return build_snapshot_table(list(tickers), email=email, quarters=quarters)


@st.cache_data(ttl=3600, show_spinner="Fetching price history...")
def cached_price_history(ticker: str, period: str):
    return fetch_price_history(ticker, period=period)


# ---------------------------------------------------------------------------
# Earnings Screener tab
# ---------------------------------------------------------------------------


def render_earnings_screener_tab(email: str) -> None:
    st.sidebar.header("Earnings Screener settings")
    primary_ticker = st.sidebar.text_input("Primary ticker", value="SNOW").strip().upper()
    compare_input = st.sidebar.text_input(
        "Compare against (comma-separated tickers)",
        value="",
        help='e.g. "DDOG, CRWD, MDB" — leave blank to skip cross-company comparison.',
    )
    compare_tickers = [t.strip().upper() for t in compare_input.split(",") if t.strip()]
    quarters = st.sidebar.slider("Quarters of GAAP history", min_value=4, max_value=12, value=8)
    price_period = st.sidebar.selectbox("Price chart range", ["6mo", "1y", "2y", "5y"], index=1)
    show_earnings_markers = st.sidebar.checkbox("Mark earnings dates on price chart", value=True)

    if not email:
        st.warning(
            f"Enter a contact email in the sidebar to fetch data from SEC EDGAR "
            f"(or set the {EMAIL_ENV_VAR} environment variable before launching)."
        )
        return
    if not primary_ticker:
        st.info("Enter a ticker in the sidebar to get started.")
        return

    result = cached_ticker_data(primary_ticker, email, quarters)

    if result.gaap_fetch_error:
        st.warning(
            f"Couldn't fetch GAAP data for {primary_ticker}: {result.gaap_fetch_error}. "
            "Showing non-GAAP data only where available."
        )

    if not result.comparisons:
        st.error(f"No data found at all for {primary_ticker}.")
        return

    df_asc = comparisons_to_dataframe(result.comparisons, ascending=True)  # chronological, for charts
    df_table = df_asc.iloc[::-1]  # most-recent-first, for the table

    tab_detail, tab_growth, tab_price, tab_compare = st.tabs(
        ["Quarterly Detail", "QoQ vs YoY", "Stock Price", "Compare Companies"]
    )

    # -- Quarterly Detail --------------------------------------------------
    with tab_detail:
        st.subheader(f"{primary_ticker} — GAAP vs non-GAAP by quarter")

        dollar_cols = ["Revenue", "Net Income (GAAP)", "RPO"]
        pct_cols = [
            "Revenue QoQ %",
            "Revenue YoY %",
            "Gap % of Revenue",
            "SBC % of Revenue",
            "Non-GAAP Op Margin %",
            "RPO QoQ %",
            "RPO YoY %",
            "NRR %",
        ]
        eps_cols = ["GAAP EPS (diluted)", "Non-GAAP EPS", "EPS Gap"]

        column_config = {}
        for col in dollar_cols:
            column_config[col] = st.column_config.NumberColumn(col, format="$%.0f")
        for col in pct_cols:
            column_config[col] = st.column_config.NumberColumn(col, format="%.1f%%")
        for col in eps_cols:
            column_config[col] = st.column_config.NumberColumn(col, format="$%.2f")

        st.dataframe(
            df_table.drop(columns=["Fiscal Year", "Fiscal Period"]),
            width="stretch",
            column_config=column_config,
            hide_index=True,
        )

        col1, col2 = st.columns(2)
        with col1:
            st.caption("GAAP vs non-GAAP EPS")
            st.line_chart(df_asc.set_index("Quarter")[["GAAP EPS (diluted)", "Non-GAAP EPS"]])
        with col2:
            st.caption("Gap as % of revenue")
            st.bar_chart(df_asc.set_index("Quarter")[["Gap % of Revenue"]])

    # -- QoQ vs YoY ----------------------------------------------------------
    with tab_growth:
        st.subheader(f"{primary_ticker} — sequential vs. year-over-year growth")
        st.caption(
            "The point of showing both: a metric can be growing YoY while shrinking QoQ "
            "(deceleration or seasonality) — that pattern is easy to miss looking at either number alone."
        )

        col1, col2 = st.columns(2)
        with col1:
            st.caption("Revenue growth")
            st.line_chart(df_asc.set_index("Quarter")[["Revenue QoQ %", "Revenue YoY %"]])
        with col2:
            rpo_growth = df_asc.set_index("Quarter")[["RPO QoQ %", "RPO YoY %"]].dropna(how="all")
            if not rpo_growth.empty:
                st.caption("RPO growth")
                st.line_chart(rpo_growth)
            else:
                st.caption("RPO growth (no RPO data entered for enough consecutive quarters yet)")

        divergences = find_divergences(result.comparisons)
        if divergences:
            for message in divergences:
                st.info(f"⚠️ {message}")
        else:
            st.caption("No QoQ-down-but-YoY-up divergence found in the quarters shown.")

    # -- Stock Price ------------------------------------------------------
    with tab_price:
        st.subheader(f"Price performance ({price_period})")

        price_tickers = [primary_ticker] + [t for t in compare_tickers if t != primary_ticker]
        price_by_ticker = {t: cached_price_history(t, price_period) for t in price_tickers}
        missing = [t for t, df in price_by_ticker.items() if df is None]
        if missing:
            st.caption(f"Couldn't fetch price data for: {', '.join(missing)}")

        combined = combine_price_histories(price_by_ticker)
        if combined.empty:
            st.warning("No price data available.")
        else:
            if len(price_by_ticker) > 1:
                st.caption(
                    "Indexed to 0% at the start of the period, so tickers at very different "
                    "share prices are comparable."
                )
                st.line_chart(normalize_to_pct_change(combined))
            else:
                st.line_chart(combined)

            primary_prices = price_by_ticker.get(primary_ticker)
            if show_earnings_markers and primary_prices is not None:
                try:
                    import altair as alt

                    price_df = primary_prices.reset_index()
                    date_col = price_df.columns[0]  # yfinance names the index "Date"
                    base = (
                        alt.Chart(price_df)
                        .mark_line()
                        .encode(x=f"{date_col}:T", y=alt.Y(f"{primary_ticker}:Q", title="Price ($)"))
                    )
                    earnings_dates = pd.DataFrame(
                        {"Date": [pd.to_datetime(c.gaap.period_end) for c in result.comparisons if c.gaap]}
                    )
                    if not earnings_dates.empty:
                        rules = alt.Chart(earnings_dates).mark_rule(color="orange", strokeDash=[4, 4]).encode(
                            x="Date:T"
                        )
                        st.caption(f"{primary_ticker} price with reported quarter-end dates marked (dashed orange lines)")
                        st.altair_chart((base + rules).interactive(), width="stretch")
                except ImportError:
                    pass  # altair ships with streamlit, but don't hard-fail if it's ever missing

    # -- Compare Companies --------------------------------------------------
    with tab_compare:
        all_tickers = [primary_ticker] + [t for t in compare_tickers if t != primary_ticker]

        if len(all_tickers) < 2:
            st.info('Add one or more comparison tickers in the sidebar (e.g. "DDOG, CRWD") to compare companies.')
        else:
            st.subheader("Latest reported quarter, side by side")
            st.caption(
                "Companies are lined up by each one's own most recent quarter, not matching fiscal quarter "
                "numbers — see cross_company.py for why that's the right comparison across different fiscal calendars."
            )

            snapshots, _fetch_results = cached_snapshot_table(tuple(all_tickers), email, quarters)
            snap_df = snapshots_to_dataframe(snapshots)

            snap_column_config = {
                "Revenue": st.column_config.NumberColumn("Revenue", format="$%.0f"),
                "RPO": st.column_config.NumberColumn("RPO", format="$%.0f"),
                "GAAP EPS": st.column_config.NumberColumn("GAAP EPS", format="$%.2f"),
                "Non-GAAP EPS": st.column_config.NumberColumn("Non-GAAP EPS", format="$%.2f"),
                "EPS Gap": st.column_config.NumberColumn("EPS Gap", format="$%.2f"),
                "Revenue QoQ %": st.column_config.NumberColumn("Revenue QoQ %", format="%.1f%%"),
                "Revenue YoY %": st.column_config.NumberColumn("Revenue YoY %", format="%.1f%%"),
                "Gap % of Revenue": st.column_config.NumberColumn("Gap % of Revenue", format="%.1f%%"),
                "Non-GAAP Op Margin %": st.column_config.NumberColumn("Non-GAAP Op Margin %", format="%.1f%%"),
                "RPO YoY %": st.column_config.NumberColumn("RPO YoY %", format="%.1f%%"),
                "NRR %": st.column_config.NumberColumn("NRR %", format="%.0f%%"),
            }
            st.dataframe(snap_df, width="stretch", column_config=snap_column_config, hide_index=True)

            col1, col2 = st.columns(2)
            with col1:
                growth_df = snap_df.set_index("Ticker")[["Revenue YoY %"]].dropna()
                if not growth_df.empty:
                    st.caption("Revenue YoY growth, latest quarter")
                    st.bar_chart(growth_df)
            with col2:
                eps_df = snap_df.set_index("Ticker")[["GAAP EPS", "Non-GAAP EPS"]].dropna(how="all")
                if not eps_df.empty:
                    st.caption("GAAP vs non-GAAP EPS, latest quarter")
                    st.bar_chart(eps_df)

            note_rows = snap_df[snap_df["Note"] != ""]
            for _, row in note_rows.iterrows():
                st.caption(f"{row['Ticker']}: {row['Note']}")


# ---------------------------------------------------------------------------
# Watchlist tab
# ---------------------------------------------------------------------------


def render_watchlist_tab() -> None:
    st.subheader("Watchlist")
    st.caption("Track a personal list of tickers and see their price charts. Saved locally to data/watchlist.json.")

    # st.session_state persists across reruns WITHIN one browser session, but
    # resets when you restart `streamlit run` — that's why we also load from
    # (and save to) a JSON file via watchlist.py, so the list survives a
    # restart too. Loading into session_state only happens once (the `if
    # "watchlist" not in st.session_state` guard) so edits during the
    # session aren't clobbered by re-reading the file on every rerun.
    if "watchlist" not in st.session_state:
        st.session_state.watchlist = load_watchlist()

    with st.form("add_ticker_form", clear_on_submit=True):
        col_input, col_button = st.columns([3, 1])
        with col_input:
            new_ticker = st.text_input("Add a ticker", label_visibility="collapsed", placeholder="e.g. AAPL")
        with col_button:
            submitted = st.form_submit_button("Add")

    if submitted and new_ticker.strip():
        ticker = new_ticker.strip().upper()
        if ticker not in st.session_state.watchlist:
            st.session_state.watchlist.append(ticker)
            save_watchlist(st.session_state.watchlist)

    if not st.session_state.watchlist:
        st.info("Your watchlist is empty — add a ticker above.")
        return

    for ticker in list(st.session_state.watchlist):
        col_name, col_remove = st.columns([5, 1])
        col_name.write(f"**{ticker}**")
        if col_remove.button("Remove", key=f"remove_{ticker}"):
            st.session_state.watchlist.remove(ticker)
            save_watchlist(st.session_state.watchlist)
            st.rerun()

    period = st.selectbox("Chart range", ["1mo", "3mo", "6mo", "1y", "2y", "5y"], index=3, key="watchlist_period")

    prices = {ticker: cached_price_history(ticker, period) for ticker in st.session_state.watchlist}
    missing = [ticker for ticker, df in prices.items() if df is None]
    if missing:
        st.caption(f"Couldn't fetch price data for: {', '.join(missing)}")

    valid_tickers = [t for t in st.session_state.watchlist if prices.get(t) is not None]
    if not valid_tickers:
        return

    combined = combine_price_histories(prices)
    if len(valid_tickers) > 1 and not combined.empty:
        st.caption("All tickers, indexed to 0% at the start of the period")
        st.line_chart(normalize_to_pct_change(combined))

    st.caption("Individual charts")
    cols_per_row = 3
    for i in range(0, len(valid_tickers), cols_per_row):
        row_tickers = valid_tickers[i : i + cols_per_row]
        row_cols = st.columns(cols_per_row)
        for col, ticker in zip(row_cols, row_tickers):
            with col:
                st.caption(ticker)
                st.line_chart(prices[ticker])


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

st.title("Stock Dashboard")

email = st.sidebar.text_input(
    "SEC EDGAR contact email",
    value=os.environ.get(EMAIL_ENV_VAR, ""),
    help="SEC EDGAR requires a contact email on every request (its fair-use policy). "
    "Not sent anywhere except SEC EDGAR itself. Only needed for the Earnings Screener tab.",
)

tab_screener, tab_watchlist = st.tabs(["Earnings Screener", "Watchlist"])

with tab_screener:
    render_earnings_screener_tab(email)

with tab_watchlist:
    render_watchlist_tab()
