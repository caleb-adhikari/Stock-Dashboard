"""Offline tests for watchlist.py — uses a throwaway temp file, never the
real data/watchlist.json, so running tests never touches your actual list."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from earnings_screener.watchlist import load_watchlist, save_watchlist


def test_load_missing_file_returns_empty_list():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "does_not_exist.json"
        assert load_watchlist(path) == []


def test_save_then_load_round_trip():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "watchlist.json"
        save_watchlist(["snow", "DDOG", "crwd"], path)
        assert load_watchlist(path) == ["SNOW", "DDOG", "CRWD"]


def test_load_dedupes_and_uppercases():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "watchlist.json"
        path.write_text('["SNOW", "snow", "  ddog  ", ""]')
        assert load_watchlist(path) == ["SNOW", "DDOG"]


if __name__ == "__main__":
    test_load_missing_file_returns_empty_list()
    test_save_then_load_round_trip()
    test_load_dedupes_and_uppercases()
    print("All watchlist tests passed.")
