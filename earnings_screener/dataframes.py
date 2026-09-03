"""
Converts our typed objects (models.py) into pandas DataFrames for display
and charting in the dashboard.

This conversion layer is kept separate from compare.py/cross_company.py on
purpose: those modules work with plain dataclasses and the standard
library only, so they're usable (and testable) with zero pip installs.
Only this file — plus stock_prices.py and dashboard.py — need pandas and
friends. If you ever want to use the core pipeline from a bare-bones
script, skip this file and work with the dataclasses directly (see
cli.py for an example that does exactly that).
"""

from __future__ import annotations

import pandas as pd

from earnings_screener.models import CompanySnapshot, QuarterComparison


def comparisons_to_dataframe(comparisons: list[QuarterComparison], ascending: bool = True) -> pd.DataFrame:
    """One row per fiscal quarter for a single company — the shape used
    for both the detail table and the per-company trend charts."""
    rows = []
    for comp in comparisons:
        gaap = comp.gaap
        non_gaap = comp.non_gaap
        rows.append(
            {
                "Quarter": str(comp.key),
                "Fiscal Year": comp.key.fiscal_year,
                "Fiscal Period": comp.key.fiscal_period,
                "Period End": gaap.period_end if gaap else None,
                "Revenue": gaap.revenue if gaap else None,
                "Revenue QoQ %": comp.revenue_qoq_pct,
                "Revenue YoY %": comp.revenue_yoy_pct,
                "Net Income (GAAP)": gaap.net_income if gaap else None,
                "GAAP EPS (diluted)": gaap.eps_diluted if gaap else None,
                "Non-GAAP EPS": non_gaap.non_gaap_eps if non_gaap else None,
                "EPS Gap": comp.eps_gap,
                "Gap % of Revenue": comp.gap_pct_of_revenue,
                "SBC % of Revenue": comp.sbc_pct_of_revenue,
                "Non-GAAP Op Margin %": non_gaap.non_gaap_operating_margin_pct if non_gaap else None,
                "RPO": non_gaap.rpo if non_gaap else None,
                "RPO QoQ %": comp.rpo_qoq_pct,
                "RPO YoY %": comp.rpo_yoy_pct,
                "NRR %": non_gaap.nrr_pct if non_gaap else None,
                "Notes": non_gaap.notes if non_gaap else "",
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    # Sort chronologically using the (fiscal_year, fiscal_period) pair —
    # matches how QuarterKey itself sorts (see models.py).
    df = df.sort_values(["Fiscal Year", "Fiscal Period"], ascending=ascending).reset_index(drop=True)
    return df


def ratio_rows_to_dataframe(rows: list[dict]) -> pd.DataFrame:
    """
    Convert `ratios.compute_ratio_rows()`'s plain-dict output into a
    DataFrame. No re-sorting happens here — `compute_ratio_rows` returns
    one row per input `QuarterComparison` in the exact order it was given
    (see its docstring), so the caller controls chronological-vs-newest-
    first ordering the same way it already does for
    `comparisons_to_dataframe` (by choosing which order to pass
    `comparisons` in), rather than this function re-deriving a sort key
    from the "Quarter" label string.
    """
    return pd.DataFrame(rows)


def snapshots_to_dataframe(snapshots: list[CompanySnapshot]) -> pd.DataFrame:
    """One row per company — the shape used for the cross-company
    comparison table and bar chart."""
    rows = []
    for snap in snapshots:
        rows.append(
            {
                "Ticker": snap.ticker,
                "Latest Quarter": str(snap.key) if snap.key else "—",
                "Period End": snap.period_end,
                "Revenue": snap.revenue,
                "Revenue QoQ %": snap.revenue_qoq_pct,
                "Revenue YoY %": snap.revenue_yoy_pct,
                "GAAP EPS": snap.gaap_eps_diluted,
                "Non-GAAP EPS": snap.non_gaap_eps,
                "EPS Gap": snap.eps_gap,
                "Gap % of Revenue": snap.gap_pct_of_revenue,
                "Non-GAAP Op Margin %": snap.non_gaap_operating_margin_pct,
                "RPO": snap.rpo,
                "RPO YoY %": snap.rpo_yoy_pct,
                "NRR %": snap.nrr_pct,
                "Note": snap.gaap_fetch_error or "",
            }
        )
    return pd.DataFrame(rows)
