"""
Manual non-GAAP data store.

WHY THIS EXISTS
-----------------
Non-GAAP ("adjusted") figures — adjusted EPS, non-GAAP operating margin,
RPO, NRR — are metrics companies define themselves and report only in the
prose/tables of their earnings press release (usually filed as Exhibit 99.1
to an 8-K). There is no SEC-standardized taxonomy for them, so there's no
clean free API the way there is for GAAP figures via XBRL.

For now we store these by hand in a JSON file per ticker under
`data/non_gaap/<TICKER>.json`. This keeps the "shape" of the data (see
NonGaapQuarter in models.py) identical to what an automated press-release
parser would eventually produce — so when that's built, it can just write
to the same JSON files (or a real database) and nothing downstream has to
change.

FILE FORMAT
-------------
data/non_gaap/SNOW.json looks like:

    [
      {
        "fiscal_year": 2027,
        "fiscal_period": "Q2",
        "non_gaap_eps": 0.62,
        "non_gaap_operating_margin_pct": 15.3,
        "rpo": 9000000000,
        "nrr_pct": 126,
        "product_revenue": null,
        "notes": "...",
        "source": "..."
      },
      ...
    ]

Add a new quarter by appending another object to the list.
"""

from __future__ import annotations

import json
from pathlib import Path

from earnings_screener.models import NonGaapQuarter, QuarterKey

# project_root/data/non_gaap/
DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "non_gaap"


def load_non_gaap_quarters(ticker: str) -> list[NonGaapQuarter]:
    path = DATA_DIR / f"{ticker.upper()}.json"
    if not path.exists():
        return []

    with path.open() as f:
        raw = json.load(f)

    quarters = []
    for entry in raw:
        key = QuarterKey(fiscal_year=entry["fiscal_year"], fiscal_period=entry["fiscal_period"])
        quarters.append(
            NonGaapQuarter(
                ticker=ticker.upper(),
                key=key,
                non_gaap_eps=entry.get("non_gaap_eps"),
                non_gaap_operating_margin_pct=entry.get("non_gaap_operating_margin_pct"),
                rpo=entry.get("rpo"),
                nrr_pct=entry.get("nrr_pct"),
                product_revenue=entry.get("product_revenue"),
                notes=entry.get("notes", ""),
                source=entry.get("source", ""),
            )
        )
    quarters.sort(key=lambda q: q.key, reverse=True)
    return quarters
