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

from earnings_screener.charting import (
    CHART_METRIC_BY_KEY,
    CHART_METRIC_CATALOG,
    DEFAULT_CHART_METRIC_KEYS,
    compute_chart_rows,
    pick_dollar_unit,
)
from earnings_screener.compare import find_divergences
from earnings_screener.cross_company import build_snapshot_table
from earnings_screener.dataframes import (
    comparisons_to_dataframe,
    ratio_rows_to_dataframe,
    scale_dollar_columns,
    snapshots_to_dataframe,
    summary_rows_to_dataframe,
)
from earnings_screener.pipeline import FetchResult, get_comparisons_for_ticker
from earnings_screener.ratios import RATIO_BY_KEY, RATIO_CATALOG, compute_ratio_rows
from earnings_screener.sources.stock_prices import (
    combine_price_histories,
    fetch_latest_price,
    fetch_price_history,
    normalize_to_pct_change,
)
from earnings_screener.summary import BASES, DEFAULT_BASIS, SummaryColumn, build_summary_rows, summary_columns
from earnings_screener.units import DEFAULT_UNITS, DOLLAR_UNITS, unit_suffix
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


@st.cache_data(ttl=900, show_spinner="Fetching latest price...")
def cached_latest_price(ticker: str):
    # Shorter TTL than the other caches (15 min, not 1 hr) since this feeds
    # valuation ratios (P/E, P/S, P/B) where "latest price" is the whole
    # point — no reason to hold a stale price longer than necessary.
    return fetch_latest_price(ticker)


# ---------------------------------------------------------------------------
# Charts sub-tab (inside the Earnings Screener tab)
# ---------------------------------------------------------------------------


def render_charts_tab(ticker: str, comparisons, units: str | None = None) -> None:
    """
    Pick any of the quarterly metrics in charting.CHART_METRIC_CATALOG
    (revenue, the expense lines, net income, RPO, ...) and see them plotted
    quarter by quarter, alongside their QoQ / YoY growth rates.

    Dollar values and growth percentages are deliberately TWO charts, not
    one chart with two y-axes: a dual-axis chart lets you make any two
    lines look correlated (or not) just by fiddling with the scales, so
    it's the one chart type that's easy to mislead yourself with.
    """
    import altair as alt

    st.subheader(f"{ticker} — quarterly trends")
    st.caption(
        "Plot the income statement over time. Expense lines are derived from the reported subtotals "
        "(cost of revenue = revenue − gross profit; operating expenses = gross profit − operating income) — "
        "see charting.py for why."
    )

    control_cols = st.columns([3, 1, 1])
    with control_cols[0]:
        selected_keys = st.multiselect(
            "Metrics to chart",
            options=[m.key for m in CHART_METRIC_CATALOG],
            default=DEFAULT_CHART_METRIC_KEYS,
            format_func=lambda key: CHART_METRIC_BY_KEY[key].label,
            help="\n".join(f"**{m.label}** — {m.description}" for m in CHART_METRIC_CATALOG),
            key="chart_metrics",
        )
    with control_cols[1]:
        value_style = st.radio("Values as", ["Bars", "Lines"], horizontal=True, key="chart_value_style")
    with control_cols[2]:
        growth_basis = st.radio("Growth", ["YoY", "QoQ", "Both"], horizontal=True, key="chart_growth_basis")

    if not selected_keys:
        st.info("Pick one or more metrics above.")
        return

    rows = compute_chart_rows(comparisons, selected_keys)
    df = pd.DataFrame(rows)
    if df.empty:
        st.info("No quarterly data to chart yet.")
        return

    # Both axes need an explicit order, otherwise Altair sorts "Q1 FY2027"
    # alphabetically (which puts FY2027 before FY2026's Q2...). Rows already
    # come back chronological from compute_chart_rows, so just dedupe.
    quarter_order = list(dict.fromkeys(df["Quarter"]))
    metric_order = [CHART_METRIC_BY_KEY[k].label for k in selected_keys]

    # -- Dollar values ---------------------------------------------------------
    if units:
        # Sidebar's Millions/Billions choice, so charts and tables agree.
        divisor, unit_label = DOLLAR_UNITS[units][0], f"$ {units.lower()}"
    else:
        divisor, unit_label = pick_dollar_unit(df["Value"].tolist())
    suffix = {1e9: "B", 1e6: "M", 1e3: "K"}.get(divisor, "")
    decimals = 2 if suffix == "B" else 1

    def fmt_scaled(value) -> str:
        # "$1,550.0M" / "-$0.18B" — a pre-formatted string for the hover
        # tooltip, since Altair's number formats can't append a unit suffix.
        if value is None or pd.isna(value):
            return "—"
        scaled = value / divisor
        return f"{'-' if scaled < 0 else ''}${abs(scaled):,.{decimals}f}{suffix}"

    values_df = df.dropna(subset=["Value"]).copy()
    values_df["Scaled"] = values_df["Value"] / divisor
    values_df["Display"] = values_df["Value"].map(fmt_scaled)

    if values_df.empty:
        st.warning(
            "None of the selected metrics have data for these quarters. "
            "GAAP lines need a successful SEC EDGAR fetch; non-GAAP lines need entries in data/non_gaap/."
        )
    else:
        st.markdown(f"**Quarterly values** ({unit_label})")
        x = alt.X("Quarter:N", sort=quarter_order, title=None, axis=alt.Axis(labelAngle=0))
        y = alt.Y("Scaled:Q", title=unit_label, axis=alt.Axis(format="~s"))
        color = alt.Color("Metric:N", sort=metric_order, legend=alt.Legend(title=None, orient="top"))
        tooltip = [
            alt.Tooltip("Quarter:N"),
            alt.Tooltip("Metric:N"),
            alt.Tooltip("Display:N", title=f"Value ({unit_label})"),
            alt.Tooltip("QoQ %:Q", format=".1f"),
            alt.Tooltip("YoY %:Q", format=".1f"),
        ]
        if value_style == "Bars":
            marks = (
                alt.Chart(values_df)
                .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
                .encode(x=x, y=y, color=color, xOffset=alt.XOffset("Metric:N", sort=metric_order), tooltip=tooltip)
            )
        else:
            marks = (
                alt.Chart(values_df)
                .mark_line(point=alt.OverlayMarkDef(size=60), strokeWidth=2)
                .encode(x=x, y=y, color=color, tooltip=tooltip)
            )
        zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color="gray", strokeWidth=1).encode(y="y:Q")
        st.altair_chart((marks + zero).properties(height=340), width="stretch")

    # -- Growth rates -----------------------------------------------------------
    growth_cols = {"YoY": ["YoY %"], "QoQ": ["QoQ %"], "Both": ["QoQ %", "YoY %"]}[growth_basis]
    growth_df = df.melt(
        id_vars=["Quarter", "Metric"],
        value_vars=growth_cols,
        var_name="Basis",
        value_name="Growth %",
    ).dropna(subset=["Growth %"])
    growth_df["Basis"] = growth_df["Basis"].str.replace(" %", "", regex=False)

    if growth_df.empty:
        st.caption(
            f"No {growth_basis} growth to show yet — YoY needs the same quarter a year earlier in the data "
            "(try raising 'Quarters of GAAP history' in the sidebar); QoQ needs the previous quarter."
        )
    else:
        st.markdown(f"**Growth ({growth_basis})** — % change per quarter")
        growth_encoding = dict(
            # Pin the x-axis to every quarter in the data (not just the ones
            # with a growth figure) so a single YoY point still sits in context.
            x=alt.X(
                "Quarter:N",
                sort=quarter_order,
                scale=alt.Scale(domain=quarter_order),
                title=None,
                axis=alt.Axis(labelAngle=0),
            ),
            y=alt.Y("Growth %:Q", title="% change", axis=alt.Axis(format=".0f")),
            color=alt.Color("Metric:N", sort=metric_order, legend=alt.Legend(title=None, orient="top")),
            tooltip=[
                alt.Tooltip("Quarter:N"),
                alt.Tooltip("Metric:N"),
                alt.Tooltip("Basis:N"),
                alt.Tooltip("Growth %:Q", format=".1f"),
            ],
        )
        if growth_basis == "Both":
            # Solid = YoY, dashed = QoQ, so the two bases for the same metric
            # share a color but are still tellable apart.
            growth_encoding["strokeDash"] = alt.StrokeDash(
                "Basis:N",
                sort=["YoY", "QoQ"],
                legend=alt.Legend(title=None, orient="top"),
            )
        growth_lines = (
            alt.Chart(growth_df)
            .mark_line(point=alt.OverlayMarkDef(size=60), strokeWidth=2)
            .encode(**growth_encoding)
        )
        zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color="gray", strokeWidth=1).encode(y="y:Q")
        st.altair_chart((growth_lines + zero).properties(height=300), width="stretch")
        st.caption(
            "Growth is computed as (new − old) / |old|, so a shrinking loss shows as positive growth "
            "(e.g. net loss going from −\\$50M to −\\$25M reads as +50%)."
        )

    # -- The numbers behind the charts ---------------------------------------
    with st.expander("Show data table"):
        table = (
            df.pivot(index="Quarter", columns="Metric", values=["Value", "QoQ %", "YoY %"])
            .reindex(quarter_order[::-1])  # newest first, like the Summary table
        )
        # Flatten the (measure, metric) column pairs to "Revenue", "Revenue QoQ %", ...
        table.columns = [
            metric if measure == "Value" else f"{metric} {measure}" for measure, metric in table.columns
        ]
        ordered_cols = [
            col
            for metric in metric_order
            for col in (metric, f"{metric} QoQ %", f"{metric} YoY %")
            if col in table.columns
        ]
        # If a metric is None for EVERY quarter, pivot() leaves that column as
        # object dtype, which NumberColumn can't format — coerce to float.
        table = table[ordered_cols].apply(pd.to_numeric).reset_index()
        table_config = {}
        for col in ordered_cols:
            if col.endswith("%"):
                table_config[col] = st.column_config.NumberColumn(col, format="%.1f%%")
            else:
                # Same millions/billions scaling as the chart axis and tooltips.
                table[col] = table[col] / divisor
                table_config[col] = st.column_config.NumberColumn(col, format=f"$%.{decimals}f{suffix}")
        st.dataframe(table, width="stretch", column_config=table_config, hide_index=True)


# ---------------------------------------------------------------------------
# Earnings Screener tab
# ---------------------------------------------------------------------------


def _dollar_format(units: str) -> str:
    """printf-style format for a Streamlit NumberColumn holding a dollar
    figure already scaled to `units` — '$%.1fM' or '$%.2fB'."""
    decimals = 1 if units == "Millions" else 2
    return f"$%.{decimals}f{unit_suffix(units)}"


def _column_config_for(columns: list[SummaryColumn], units: str) -> dict:
    """Streamlit column formatting driven by summary.py's column kinds, so
    the dashboard never has to hard-code which columns are dollars/EPS/%."""
    config = {}
    for col in columns:
        if col.kind == "dollars":
            config[col.label] = st.column_config.NumberColumn(col.label, format=_dollar_format(units))
        elif col.kind == "eps":
            config[col.label] = st.column_config.NumberColumn(col.label, format="$%.2f")
        elif col.kind == "pct":
            config[col.label] = st.column_config.NumberColumn(col.label, format="%.1f%%")
    return config


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

    # Which set of numbers to show. GAAP is the default because that's what
    # you want the vast majority of the time; "Both" is the original
    # GAAP-vs-non-GAAP comparison this project started as.
    basis = st.sidebar.radio(
        "Numbers to show",
        BASES,
        index=BASES.index(DEFAULT_BASIS),
        horizontal=True,
        help="GAAP = official SEC-filed figures. Non-GAAP = the company's own adjusted figures "
        "(only for tickers with data in data/non_gaap/). Both = side by side, with the gap.",
    )
    units = st.sidebar.selectbox("Dollar figures in", list(DOLLAR_UNITS), index=list(DOLLAR_UNITS).index(DEFAULT_UNITS))

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

    has_non_gaap = any(c.non_gaap is not None for c in result.comparisons)
    if basis != "GAAP" and not has_non_gaap:
        st.info(
            f"No non-GAAP data has been entered for {primary_ticker} yet (data/non_gaap/{primary_ticker}.json), "
            "so non-GAAP columns will be blank. GAAP figures still work for any ticker."
        )

    # Chronological DataFrame with every column — the charts pick from it.
    # Dollar columns are scaled once here so every chart uses the same units.
    dollar_columns = ["Revenue", "Gross Profit", "Operating Income", "Net Income (GAAP)", "RPO"]
    df_asc = scale_dollar_columns(comparisons_to_dataframe(result.comparisons, ascending=True), dollar_columns, units)
    by_quarter = df_asc.set_index("Quarter")
    suffix = unit_suffix(units)

    tab_summary, tab_charts, tab_price, tab_compare, tab_ratios = st.tabs(
        ["Summary", "Charts", "Stock Price", "Compare Companies", "Ratios"]
    )

    # -- Summary ------------------------------------------------------------
    with tab_summary:
        st.subheader(f"{primary_ticker} — {basis} figures by quarter, with year-over-year change")
        st.caption(
            f"Dollar figures in {units.lower()}. Each “YoY %” column compares that quarter to the same "
            "fiscal quarter one year earlier. Charts are on the next tab."
        )
        columns = summary_columns(basis)
        rows = build_summary_rows(result.comparisons, basis)  # newest-first
        summary_df = scale_dollar_columns(
            summary_rows_to_dataframe(rows), [c.label for c in columns if c.kind == "dollars"], units
        )
        st.dataframe(
            summary_df,
            width="stretch",
            column_config=_column_config_for(columns, units),
            hide_index=True,
        )

    # -- Charts -------------------------------------------------------------
    with tab_charts:
        # The metric picker / bar-vs-line / growth charts live in
        # render_charts_tab (above); the sidebar's dollar units are passed
        # through so the axis matches the Summary table.
        render_charts_tab(primary_ticker, result.comparisons, units)

        st.divider()
        col_eps, col_growth = st.columns(2)
        with col_eps:
            if basis == "GAAP":
                st.caption("Diluted EPS (GAAP)")
                st.line_chart(by_quarter[["GAAP EPS (diluted)"]])
            elif basis == "Non-GAAP":
                eps = by_quarter[["Non-GAAP EPS"]].dropna()
                st.caption("Non-GAAP EPS")
                if eps.empty:
                    st.caption("(no non-GAAP EPS entered yet)")
                else:
                    st.line_chart(eps)
            else:  # Both
                st.caption("GAAP vs non-GAAP EPS")
                st.line_chart(by_quarter[["GAAP EPS (diluted)", "Non-GAAP EPS"]])
        with col_growth:
            if basis == "Both":
                st.caption("GAAP/non-GAAP gap as % of revenue")
                st.bar_chart(by_quarter[["Gap % of Revenue"]])
            else:
                rpo_growth = by_quarter[["RPO QoQ %", "RPO YoY %"]].dropna(how="all")
                st.caption("RPO growth — QoQ vs YoY %")
                if rpo_growth.empty:
                    st.caption("(needs RPO entered for enough consecutive quarters)")
                else:
                    st.line_chart(rpo_growth)

        st.caption(
            "Why QoQ and YoY are shown together: a metric can still be growing year-over-year while "
            "shrinking sequentially (deceleration or seasonality) — easy to miss looking at either alone."
        )
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
                f"Dollar figures in {units.lower()}. Companies are lined up by each one's own most recent quarter, "
                "not matching fiscal quarter numbers — see cross_company.py for why that's the right comparison "
                "across different fiscal calendars."
            )

            snapshots, _fetch_results = cached_snapshot_table(tuple(all_tickers), email, quarters)
            snap_df = scale_dollar_columns(snapshots_to_dataframe(snapshots), ["Revenue", "RPO"], units)

            # Trim the side-by-side table to the chosen basis too.
            gaap_only_cols = ["Non-GAAP EPS", "EPS Gap", "Gap % of Revenue", "Non-GAAP Op Margin %", "RPO", "RPO YoY %", "NRR %"]
            non_gaap_only_cols = ["GAAP EPS", "EPS Gap", "Gap % of Revenue"]
            if basis == "GAAP":
                snap_df = snap_df.drop(columns=[c for c in gaap_only_cols if c in snap_df.columns])
            elif basis == "Non-GAAP":
                snap_df = snap_df.drop(columns=[c for c in non_gaap_only_cols if c in snap_df.columns])

            snap_column_config = {
                "Revenue": st.column_config.NumberColumn("Revenue", format=_dollar_format(units)),
                "RPO": st.column_config.NumberColumn("RPO", format=_dollar_format(units)),
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
                eps_cols = [c for c in ["GAAP EPS", "Non-GAAP EPS"] if c in snap_df.columns]
                eps_df = snap_df.set_index("Ticker")[eps_cols].dropna(how="all")
                if not eps_df.empty:
                    st.caption("EPS, latest quarter")
                    st.bar_chart(eps_df)

            note_rows = snap_df[snap_df["Note"] != ""]
            for _, row in note_rows.iterrows():
                st.caption(f"{row['Ticker']}: {row['Note']}")

    # -- Ratios --------------------------------------------------------------
    with tab_ratios:
        st.subheader(f"{primary_ticker} — financial ratios")
        st.caption(
            "Pick the ratios you want and this computes the math from the GAAP/non-GAAP data above — "
            "no separate lookup needed."
        )

        options = [r.key for r in RATIO_CATALOG]
        default_keys = ["gross_margin", "net_margin", "revenue_yoy"]

        selected_keys = st.multiselect(
            "Ratios to compute",
            options=options,
            default=[k for k in default_keys if k in options],
            format_func=lambda key: f"{RATIO_BY_KEY[key].category} — {RATIO_BY_KEY[key].label}",
            help="Grouped by category in the label (Profitability, Returns, Liquidity, Valuation, Growth).",
            key="ratio_keys",
        )

        if not selected_keys:
            st.info("Pick one or more ratios above to see them computed for every quarter shown.")
        else:
            selected_ratios = [RATIO_BY_KEY[k] for k in selected_keys]
            needs_price = any(r.needs_price for r in selected_ratios)

            latest_price = None
            if needs_price:
                latest_price = cached_latest_price(primary_ticker)
                if latest_price is None:
                    st.caption(
                        f"Couldn't fetch a current price for {primary_ticker} — valuation ratios "
                        "(P/E, P/S, P/B) will show as blank."
                    )

            # result.comparisons is already newest-first (see compare.py), which
            # is exactly the order the TTM-based ratios (ROE, ROA, P/E, P/S)
            # need — each one sums the 4 quarters starting at its own index.
            rows = compute_ratio_rows(result.comparisons, selected_keys, latest_price=latest_price)
            ratio_df_newest_first = ratio_rows_to_dataframe(rows)

            format_by_key = {"pct": "%.1f%%", "multiple": "%.1fx", "ratio": "%.2f"}
            ratio_column_config = {
                r.label: st.column_config.NumberColumn(r.label, format=format_by_key[r.format], help=r.description)
                for r in selected_ratios
            }
            st.dataframe(
                ratio_df_newest_first,
                width="stretch",
                column_config=ratio_column_config,
                hide_index=True,
            )

            pct_or_ratio_ratios = [r for r in selected_ratios if r.format in ("pct", "ratio")]
            multiple_ratios = [r for r in selected_ratios if r.format == "multiple"]
            ratio_df_chart = ratio_df_newest_first.iloc[::-1].set_index("Quarter")  # chronological, for charts

            if pct_or_ratio_ratios:
                st.caption("Percentages and ratios")
                st.line_chart(ratio_df_chart[[r.label for r in pct_or_ratio_ratios]])
            if multiple_ratios:
                st.caption("Valuation multiples (uses today's price against each historical quarter's TTM figures — "
                            "see README for why that's a simplification)")
                st.line_chart(ratio_df_chart[[r.label for r in multiple_ratios]])


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
