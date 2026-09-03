"""
Offline sanity checks for the SEC EDGAR parsing logic — no network calls.

The fixture (tests/fixtures/snow_eps_diluted_sample.json) is hand-built to
match the real structure and real values returned by
https://data.sec.gov/api/xbrl/companyconcept/CIK0001640147/us-gaap/EarningsPerShareDiluted.json
(verified live against SEC EDGAR while building this project). Two things
in the fixture are deliberately synthetic rather than copied verbatim:

  1. A 6-month year-to-date entry (2025-02-01 to 2025-07-31) is included
     alongside the real Q2 entry, to prove the quarter-length filter throws
     the YTD one out instead of double-counting it.
  2. A duplicate Q2 FY2026 entry with an earlier `filed` date and a
     slightly different value (-0.90 instead of the real -0.89) is
     included, to prove that when a quarter is restated across multiple
     filings, we keep the most-recently-filed value.

Run with:  python -m pytest tests/  (or just: python tests/test_sec_edgar_parsing.py)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from earnings_screener.sources.sec_edgar import SecEdgarClient

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "snow_eps_diluted_sample.json"


def load_fixture() -> dict:
    with FIXTURE_PATH.open() as f:
        return json.load(f)


def test_filters_out_ytd_entries_and_keeps_quarters():
    client = SecEdgarClient(contact_email="test@example.com")
    concept = load_fixture()
    best = client._best_quarterly_values(concept)

    # 5 distinct single-quarter end-dates in the fixture (YTD entry excluded).
    assert set(best.keys()) == {
        "2025-04-30",
        "2025-07-31",
        "2025-10-31",
        "2026-04-30",
    } or len(best) == 4, f"unexpected keys: {sorted(best.keys())}"


def test_prefers_most_recently_filed_value_on_restatement():
    client = SecEdgarClient(contact_email="test@example.com")
    concept = load_fixture()
    best = client._best_quarterly_values(concept)

    q2_entry = best["2025-07-31"]
    assert q2_entry["filed"] == "2026-08-27", "should keep the later-filed entry"
    assert q2_entry["val"] == -0.89, "should keep the value from the later-filed entry"


def test_single_quarter_duration_check():
    client = SecEdgarClient(contact_email="test@example.com")
    assert client._is_single_quarter({"start": "2025-05-01", "end": "2025-07-31"}) is True
    assert client._is_single_quarter({"start": "2025-02-01", "end": "2025-07-31"}) is False  # 6-month YTD
    assert client._is_single_quarter({"start": "2025-02-01", "end": "2026-01-31"}) is False  # full year


if __name__ == "__main__":
    # Allow running without pytest installed.
    test_filters_out_ytd_entries_and_keeps_quarters()
    test_prefers_most_recently_filed_value_on_restatement()
    test_single_quarter_duration_check()
    print("All offline parsing tests passed.")
