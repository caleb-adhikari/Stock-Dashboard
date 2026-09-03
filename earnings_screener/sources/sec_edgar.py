"""
SEC EDGAR XBRL "Company Facts" client.

WHAT THIS FILE DOES
--------------------
SEC EDGAR publishes every public company's financial statement data in a
structured, standardized format called XBRL. You don't need a scraper or an
API key to get it — it's a plain JSON file per company, per accounting
concept, served from data.sec.gov.

The endpoint we use is "companyconcept":

    https://data.sec.gov/api/xbrl/companyconcept/CIK##########/us-gaap/<TAG>.json

  - CIK##########  = the company's 10-digit "Central Index Key" (SEC's
                      permanent company ID), zero-padded.
  - <TAG>           = a standardized XBRL tag name, e.g. "Revenues" or
                      "EarningsPerShareDiluted". Companies pick from a shared
                      taxonomy (US-GAAP), which is what makes this
                      queryable across any company without custom parsing
                      per company.

THE ONE GOTCHA THAT WILL BITE YOU IF YOU SKIP IT
--------------------------------------------------
Each concept's JSON contains EVERY historical value the company has ever
reported for that tag — including quarterly figures, six-month/nine-month
year-to-date figures, and full-year figures, all mixed together in one
list, sometimes with the same period restated across multiple filings.
If you naively take "the last N entries", you'll mix a Q2 number in with a
six-month year-to-date number and get nonsense.

We handle this by:
  1. Filtering to entries whose (end - start) duration looks like a single
     fiscal quarter (roughly 80-100 days) — this throws out YTD/half-year/
     annual cumulative entries.
  2. When the same period end-date appears more than once (a company can
     restate a prior quarter in a later filing), keeping the one with the
     latest `filed` date, since that's the most up-to-date figure.

SEC's ACCESS REQUIREMENT
--------------------------
SEC EDGAR requires every request to send a `User-Agent` header identifying
who's asking (e.g. "AppName your-email@example.com") — this is not
optional, requests without one get blocked. This is a courtesy/fair-use
policy from the SEC, not a secret API key, and it does not require you to
sign up for anything.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import date
from typing import Optional

from earnings_screener.models import GaapQuarter, QuarterKey

BASE_URL = "https://data.sec.gov/api/xbrl/companyconcept"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

# Small fallback cache so the script works even if the ticker->CIK lookup
# endpoint is unreachable. Extend this as you add more tickers.
KNOWN_CIKS = {
    "SNOW": 1640147,  # Snowflake Inc.
    "AAPL": 320193,  # Apple Inc. (used for testing/sanity-checks)
}

# The XBRL tags we pull for the GAAP side of the comparison. Revenue tag
# varies a bit by company/era; we try each in order and use the first one
# that returns data. Stock-based comp is included because it's usually the
# single biggest driver of the GAAP/non-GAAP gap for software companies —
# even though we don't use it in a formula yet, having it on the object
# already means the "why is the gap big" feature later is just a report
# change, not a new data-fetching project.
REVENUE_TAGS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",  # common for modern SaaS filers (ASC 606)
    "Revenues",  # older/simpler tag, still used by many companies
]
NET_INCOME_TAG = "NetIncomeLoss"
EPS_DILUTED_TAG = "EarningsPerShareDiluted"
DILUTED_SHARES_TAG = "WeightedAverageNumberOfDilutedSharesOutstanding"
STOCK_COMP_TAG = "ShareBasedCompensation"


class SecEdgarClient:
    def __init__(self, contact_email: str, user_agent_app_name: str = "EarningsScreener"):
        if not contact_email or "@" not in contact_email:
            raise ValueError(
                "SEC EDGAR requires a real contact email in the User-Agent header. "
                "Pass your email, e.g. SecEdgarClient(contact_email='you@example.com')."
            )
        self.user_agent = f"{user_agent_app_name} {contact_email}"

    # -- low-level HTTP -----------------------------------------------

    def _get_json(self, url: str) -> dict:
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))

    # -- ticker -> CIK --------------------------------------------------

    def resolve_cik(self, ticker: str) -> int:
        ticker = ticker.upper()
        if ticker in KNOWN_CIKS:
            return KNOWN_CIKS[ticker]

        # Fall back to SEC's own ticker->CIK mapping file if we don't have
        # it cached above.
        data = self._get_json(TICKERS_URL)
        for entry in data.values():
            if entry.get("ticker", "").upper() == ticker:
                return int(entry["cik_str"])
        raise ValueError(f"Could not resolve CIK for ticker {ticker!r}")

    # -- one XBRL concept -------------------------------------------------

    def get_company_concept(self, cik: int, tag: str) -> Optional[dict]:
        """
        Fetch one concept's raw JSON for a company. Returns None (rather than
        raising) if the company simply doesn't report this tag, since that's
        an expected, normal condition — not every company uses every tag.
        """
        cik_padded = f"CIK{cik:010d}"
        url = f"{BASE_URL}/{cik_padded}/us-gaap/{tag}.json"
        try:
            return self._get_json(url)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise

    # -- quarter filtering / dedup ----------------------------------------

    @staticmethod
    def _is_single_quarter(entry: dict) -> bool:
        """True if this entry's date range looks like one fiscal quarter
        (roughly 80-100 days) rather than a half-year/YTD/annual figure."""
        try:
            start = date.fromisoformat(entry["start"])
            end = date.fromisoformat(entry["end"])
        except (KeyError, ValueError):
            return False
        return 80 <= (end - start).days <= 100

    def _best_quarterly_values(self, concept_json: dict) -> dict:
        """
        Given a raw companyconcept JSON blob, return {end_date: entry} for
        the best (most recently filed) single-quarter entry per end date.
        Only looks at USD / USD-per-shares units, whichever is present.
        """
        units = concept_json.get("units", {})
        entries = units.get("USD") or units.get("USD-per-shares") or units.get("shares") or []

        best_by_end: dict[str, dict] = {}
        for entry in entries:
            if entry.get("form") != "10-Q":
                # Skip 10-K entries here; annual EPS/revenue isn't a quarter.
                # (A company's Q4 has to be derived as FY minus Q1-Q3, which
                # we don't attempt yet — see README "Known limitations".)
                continue
            if not self._is_single_quarter(entry):
                continue
            end = entry["end"]
            current_best = best_by_end.get(end)
            if current_best is None or entry.get("filed", "") > current_best.get("filed", ""):
                best_by_end[end] = entry
        return best_by_end

    # -- public: build GaapQuarter objects ---------------------------------

    def fetch_quarterly_gaap(self, ticker: str, max_quarters: int = 8) -> list[GaapQuarter]:
        """
        Fetch and assemble the last `max_quarters` quarters of GAAP figures
        for `ticker`, one GaapQuarter per fiscal quarter, newest first.
        """
        cik = self.resolve_cik(ticker)

        revenue_by_end = {}
        for tag in REVENUE_TAGS:
            concept = self.get_company_concept(cik, tag)
            if concept:
                revenue_by_end = self._best_quarterly_values(concept)
                if revenue_by_end:
                    break

        net_income_concept = self.get_company_concept(cik, NET_INCOME_TAG)
        net_income_by_end = self._best_quarterly_values(net_income_concept) if net_income_concept else {}

        eps_concept = self.get_company_concept(cik, EPS_DILUTED_TAG)
        eps_by_end = self._best_quarterly_values(eps_concept) if eps_concept else {}

        shares_concept = self.get_company_concept(cik, DILUTED_SHARES_TAG)
        shares_by_end = self._best_quarterly_values(shares_concept) if shares_concept else {}

        sbc_concept = self.get_company_concept(cik, STOCK_COMP_TAG)
        sbc_by_end = self._best_quarterly_values(sbc_concept) if sbc_concept else {}

        # Revenue is the anchor: build one GaapQuarter per period-end we
        # have a revenue figure for, and pull in the other tags if present.
        quarters: list[GaapQuarter] = []
        for end, rev_entry in revenue_by_end.items():
            key = QuarterKey(fiscal_year=rev_entry["fy"], fiscal_period=rev_entry["fp"])
            ni_entry = net_income_by_end.get(end)
            eps_entry = eps_by_end.get(end)
            shares_entry = shares_by_end.get(end)
            sbc_entry = sbc_by_end.get(end)

            quarters.append(
                GaapQuarter(
                    ticker=ticker.upper(),
                    key=key,
                    period_start=rev_entry["start"],
                    period_end=end,
                    revenue=rev_entry.get("val"),
                    net_income=ni_entry.get("val") if ni_entry else None,
                    eps_diluted=eps_entry.get("val") if eps_entry else None,
                    diluted_shares=shares_entry.get("val") if shares_entry else None,
                    stock_based_comp=sbc_entry.get("val") if sbc_entry else None,
                    source_accession=rev_entry.get("accn"),
                    filed_date=rev_entry.get("filed"),
                )
            )

        quarters.sort(key=lambda q: q.period_end, reverse=True)
        return quarters[:max_quarters]


def be_polite_between_requests():
    """SEC asks for no more than ~10 requests/second; we're nowhere near
    that here (a handful of requests per run), but this is the hook to add
    a delay if you extend this to loop over many tickers."""
    time.sleep(0.1)
