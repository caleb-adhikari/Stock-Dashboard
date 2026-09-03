"""
Orchestration layer: "given a ticker, get me its merged GAAP/non-GAAP
comparisons." This used to be inline in cli.py's main() function; it's
pulled out here so that both the CLI and the dashboard (and anything else
you build later — a notebook, a scheduled report, tests) call the exact
same fetch-and-merge logic instead of two copies drifting apart.

This module deliberately stays free of third-party dependencies (no
pandas, no streamlit) — it's pure orchestration over the stdlib-only
sources/compare modules. Anything that needs pandas/streamlit lives in
dataframes.py or dashboard.py instead, so you can still use this file (and
everything it depends on) in a plain script with zero pip installs.
"""

from __future__ import annotations

import urllib.error
from dataclasses import dataclass, field

from earnings_screener.compare import build_comparisons
from earnings_screener.models import QuarterComparison
from earnings_screener.sources.manual_nongaap import load_non_gaap_quarters
from earnings_screener.sources.sec_edgar import SecEdgarClient


@dataclass
class FetchResult:
    """Wraps the comparisons for one ticker along with whether the live
    GAAP fetch succeeded, so callers (CLI, dashboard) can show a warning
    instead of silently pretending nothing went wrong."""

    ticker: str
    comparisons: list[QuarterComparison]
    gaap_fetch_error: str | None = None


def get_comparisons_for_ticker(ticker: str, email: str, quarters: int = 8) -> FetchResult:
    """
    Fetch GAAP quarters from SEC EDGAR, load manually-entered non-GAAP
    quarters, merge them, and return both the merged data and whether the
    GAAP fetch succeeded.

    Never raises for a network problem talking to SEC EDGAR — that's a
    normal, expected failure mode (rate limiting, no internet, SEC
    downtime) and callers should be able to still show whatever non-GAAP
    data exists locally rather than crashing.
    """
    client = SecEdgarClient(contact_email=email)
    non_gaap_quarters = load_non_gaap_quarters(ticker)

    gaap_quarters = []
    gaap_fetch_error = None
    try:
        gaap_quarters = client.fetch_quarterly_gaap(ticker, max_quarters=quarters)
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        # ValueError covers "could not resolve CIK for ticker" (typo'd or
        # unlisted ticker) and "no revenue tag matched" (e.g. banks/insurers/
        # REITs — see sec_edgar.py), alongside network errors from urllib.
        gaap_fetch_error = str(exc)

    comparisons = build_comparisons(gaap_quarters, non_gaap_quarters)
    return FetchResult(ticker=ticker.upper(), comparisons=comparisons, gaap_fetch_error=gaap_fetch_error)
