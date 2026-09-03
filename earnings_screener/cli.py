"""
Command-line entry point.

Usage:
    python -m earnings_screener SNOW
    python -m earnings_screener SNOW --email you@example.com
    python -m earnings_screener SNOW --quarters 4

This file is intentionally "thin" — it just wires together the pieces from
sources/sec_edgar.py, sources/manual_nongaap.py, and compare.py, then
prints the result. All the actual logic lives in those modules so it can be
reused from something other than a CLI later (a notebook, a future
dashboard backend, a test suite, etc.) without dragging argparse along.
"""

from __future__ import annotations

import argparse
import os
import sys

from earnings_screener.compare import find_divergences
from earnings_screener.models import QuarterComparison
from earnings_screener.pipeline import get_comparisons_for_ticker

EMAIL_ENV_VAR = "EARNINGS_SCREENER_EMAIL"


# ---- formatting helpers ---------------------------------------------------


def fmt_dollars(value: float | None) -> str:
    if value is None:
        return "—"
    sign = "-" if value < 0 else ""
    value = abs(value)
    if value >= 1_000_000_000:
        return f"{sign}${value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"{sign}${value / 1_000_000:.1f}M"
    return f"{sign}${value:,.0f}"


def fmt_eps(value: float | None) -> str:
    if value is None:
        return "—"
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):.2f}"


def fmt_pct(value: float | None, decimals: int = 1) -> str:
    if value is None:
        return "—"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.{decimals}f}%"


# ---- report printing -------------------------------------------------


def print_report(comparisons: list[QuarterComparison]) -> None:
    for comp in comparisons:
        gaap = comp.gaap
        non_gaap = comp.non_gaap
        print(f"\n{'=' * 60}")
        print(f"{comp.ticker}  {comp.key}", end="")
        if gaap:
            print(f"  (quarter ended {gaap.period_end})")
        else:
            print("  (no GAAP filing found yet for this quarter)")
        print("-" * 60)

        print(f"  {'Revenue (GAAP)':32s} {fmt_dollars(gaap.revenue if gaap else None)}")
        if comp.revenue_qoq_pct is not None or comp.revenue_yoy_pct is not None:
            print(f"  {'  QoQ / YoY change':32s} {fmt_pct(comp.revenue_qoq_pct)} / {fmt_pct(comp.revenue_yoy_pct)}")

        print(f"  {'Net income (GAAP)':32s} {fmt_dollars(gaap.net_income if gaap else None)}")
        print(f"  {'EPS diluted (GAAP)':32s} {fmt_eps(gaap.eps_diluted if gaap else None)}")
        print(f"  {'EPS (non-GAAP / adjusted)':32s} {fmt_eps(non_gaap.non_gaap_eps if non_gaap else None)}")

        if comp.eps_gap is not None:
            print(f"  {'  EPS gap (non-GAAP - GAAP)':32s} {fmt_eps(comp.eps_gap)}")
        if comp.gap_pct_of_revenue is not None:
            print(f"  {'  Implied gap, % of revenue':32s} {fmt_pct(comp.gap_pct_of_revenue)}")
        if comp.sbc_pct_of_revenue is not None:
            print(f"  {'  Stock-based comp, % of revenue':32s} {fmt_pct(comp.sbc_pct_of_revenue)}")

        if non_gaap and non_gaap.non_gaap_operating_margin_pct is not None:
            print(f"  {'Non-GAAP operating margin':32s} {non_gaap.non_gaap_operating_margin_pct:.1f}%")
        if non_gaap and non_gaap.rpo is not None:
            print(f"  {'RPO':32s} {fmt_dollars(non_gaap.rpo)}", end="")
            if comp.rpo_qoq_pct is not None or comp.rpo_yoy_pct is not None:
                print(f"   (QoQ {fmt_pct(comp.rpo_qoq_pct)} / YoY {fmt_pct(comp.rpo_yoy_pct)})", end="")
            print()
        if non_gaap and non_gaap.nrr_pct is not None:
            print(f"  {'NRR':32s} {non_gaap.nrr_pct:.0f}%")
        if non_gaap and non_gaap.notes:
            print(f"  Notes: {non_gaap.notes}")

    # Flag the kind of QoQ-vs-YoY divergence that prompted this project:
    # RPO (or revenue) still growing YoY but decelerating, or even shrinking
    # sequentially. This is a plain print for now — it becomes the seed of
    # the "abnormal" flagging logic once a threshold is defined. The actual
    # detection logic lives in compare.find_divergences() so the CLI and
    # the dashboard never disagree about what counts as worth flagging.
    print(f"\n{'=' * 60}")
    print("Sequential vs. year-over-year divergence check:")
    divergences = find_divergences(comparisons)
    if divergences:
        for message in divergences:
            print(f"  {message}")
    else:
        print("  (none found in the quarters shown)")


# ---- entry point -------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GAAP vs non-GAAP earnings screener")
    parser.add_argument("ticker", help="Stock ticker, e.g. SNOW")
    parser.add_argument("--quarters", type=int, default=8, help="How many recent quarters of GAAP data to pull")
    parser.add_argument(
        "--email",
        default=os.environ.get(EMAIL_ENV_VAR),
        help=(
            "Contact email for the SEC EDGAR User-Agent header (required by SEC). "
            f"Can also be set via the {EMAIL_ENV_VAR} environment variable."
        ),
    )
    args = parser.parse_args(argv)

    if not args.email:
        parser.error(
            f"An email is required (SEC EDGAR policy). Pass --email you@example.com "
            f"or `export {EMAIL_ENV_VAR}=you@example.com`."
        )

    result = get_comparisons_for_ticker(args.ticker, email=args.email, quarters=args.quarters)
    if result.gaap_fetch_error:
        # Network hiccup, SEC EDGAR unreachable, or an unrecognized ticker —
        # degrade gracefully and still show whatever non-GAAP data we have
        # locally, rather than a raw traceback. Re-run to retry the fetch.
        print(f"Warning: couldn't fetch GAAP data ({result.gaap_fetch_error}). Showing non-GAAP data only.\n", file=sys.stderr)

    if not result.comparisons:
        print(f"No data found at all for {args.ticker.upper()}.", file=sys.stderr)
        return 1

    print_report(result.comparisons)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
