"""Lets `python -m earnings_screener ...` work (see cli.py for the actual logic)."""

from earnings_screener.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
