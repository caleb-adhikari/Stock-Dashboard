"""
A tiny persisted list of tickers for the dashboard's Watchlist tab.

This is deliberately dead simple — a JSON array of ticker strings on disk
at data/watchlist.json — because the only job here is "remember what
tickers I'm tracking between one `streamlit run` and the next." Streamlit's
own `st.session_state` would NOT do that: it resets every time the
process restarts, which is exactly when you'd want your watchlist to still
be there.

Both functions take an optional `path` so tests (and any future caller)
can point at a throwaway file instead of touching your real watchlist.
"""

from __future__ import annotations

import json
from pathlib import Path

# project_root/data/watchlist.json
DEFAULT_PATH = Path(__file__).resolve().parents[1] / "data" / "watchlist.json"


def load_watchlist(path: Path = DEFAULT_PATH) -> list[str]:
    if not path.exists():
        return []
    with path.open() as f:
        tickers = json.load(f)
    # Preserve order but drop duplicates, in case a file was hand-edited.
    seen = set()
    deduped = []
    for ticker in tickers:
        ticker = ticker.strip().upper()
        if ticker and ticker not in seen:
            seen.add(ticker)
            deduped.append(ticker)
    return deduped


def save_watchlist(tickers: list[str], path: Path = DEFAULT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(tickers, f, indent=2)
        f.write("\n")
