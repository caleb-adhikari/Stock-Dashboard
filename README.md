# Earnings Screener

> **This project was vibecoded** — built by talking through requirements
> with Claude and having it write, test, and explain the code, rather than
> hand-written line by line. The design decisions, data source choices,
> and edge cases (see "Known limitations" below) were worked through in
> that conversation; nothing here has been independently audited by a
> professional developer. Treat it as a personal tool and a learning
> project, not production or investment-grade software.

Pulls a company's official GAAP figures from SEC EDGAR, lines them up next
to its non-GAAP ("adjusted") figures, and shows a quarter-by-quarter
comparison — the GAAP/non-GAAP gap, QoQ vs. YoY divergence checks (e.g. RPO
growing YoY but shrinking sequentially), a stock price chart, and
side-by-side comparison across multiple companies. Also includes a
watchlist for tracking a personal list of tickers' price charts. Available
both as a CLI (`python3 -m earnings_screener TICKER`) and as an
interactive Streamlit dashboard (`streamlit run dashboard.py`).

The "flag it as abnormal" threshold logic is still intentionally not
built — see "Next steps" below. The point so far has been to get real
numbers in front of you to build intuition for what "normal" looks like
before deciding on a rule.

## Requirements

- Python 3.9+.
- The core data pipeline (everything except the dashboard) uses only the
  standard library — no installs needed to use `cli.py` on its own.
- The dashboard needs three extra packages (`streamlit`, `yfinance`,
  `pandas`) — see Setup below.
- No API keys anywhere. SEC EDGAR's XBRL API is free and open, but it does
  require every request to identify who's calling via a `User-Agent`
  header containing a real contact email (SEC's fair-use policy, not a
  login).

## Setup

```bash
# from inside this folder
pip3 install -r requirements.txt                    # needed for the dashboard
export EARNINGS_SCREENER_EMAIL="you@example.com"     # required by SEC EDGAR

python3 -m earnings_screener SNOW                    # CLI
streamlit run dashboard.py                           # dashboard (opens in your browser)
```

The dashboard also has a text box for the email in its sidebar if you'd
rather not export the environment variable.

## Project layout

```
earnings_screener/
    models.py              # QuarterKey, GaapQuarter, NonGaapQuarter, QuarterComparison, CompanySnapshot
    sources/
        sec_edgar.py         # pulls GAAP figures from SEC EDGAR's XBRL API
        manual_nongaap.py    # loads hand-entered non-GAAP figures
        stock_prices.py      # pulls stock price history via yfinance
    compare.py              # merges GAAP+non-GAAP for ONE company, computes gap/QoQ/YoY metrics
    cross_company.py        # lines up several companies' latest quarters side by side
    pipeline.py             # "given a ticker, fetch+merge its data" — shared by cli.py and dashboard.py
    dataframes.py            # converts the typed objects above into pandas DataFrames (dashboard only)
    watchlist.py             # load/save a persisted list of tickers (JSON file), used by the Watchlist tab
    cli.py                  # `python -m earnings_screener TICKER`
dashboard.py                # `streamlit run dashboard.py` — the interactive UI
data/
    non_gaap/SNOW.json      # hand-entered non-GAAP data, one file per ticker
    watchlist.json           # your saved watchlist tickers (created the first time you add one)
tests/
    test_sec_edgar_parsing.py   # EDGAR quarter-filtering/dedup logic (see below)
    test_cross_company.py        # snapshot-building + DataFrame conversion
    test_stock_prices.py         # price-history combine/normalize helpers
    test_watchlist.py            # watchlist load/save round-trip
```

**Why it's split up this way — the dependency direction matters:**
`models.py`, `sources/sec_edgar.py`, `sources/manual_nongaap.py`,
`compare.py`, `cross_company.py`, and `pipeline.py` use nothing but the
standard library. `dataframes.py`, `sources/stock_prices.py`, and
`dashboard.py` are the only files that know about `pandas`/`yfinance`/
`streamlit`. That means the core pipeline stays usable from a bare Python
install (a script, a notebook, a cron job, a different UI entirely) even
if you never touch the dashboard — the dashboard is a consumer of the
pipeline, not the thing the pipeline is built around.

`pipeline.py` exists because the CLI and the dashboard both need to do the
exact same "fetch this ticker's GAAP data, load its non-GAAP data, merge
them" sequence — pulling that into one function means they can't quietly
drift apart into two slightly-different implementations.

## How the GAAP side works

SEC EDGAR publishes every public company's XBRL-tagged financial data as
plain JSON, no key required:

```
https://data.sec.gov/api/xbrl/companyconcept/CIK{10-digit-cik}/us-gaap/{TAG}.json
```

`sec_edgar.py` fetches a handful of tags (revenue, net income, diluted
EPS, diluted share count, stock-based comp) for any ticker (it resolves
ticker → CIK itself, with SNOW/AAPL cached and everything else looked up
live) and assembles them into one `GaapQuarter` per fiscal quarter.

**The gotcha:** each tag's JSON mixes together quarterly, six/nine-month
year-to-date, and full-year figures — and can contain restated values from
later filings for the same period. `sec_edgar.py` filters to entries whose
date range is 80-100 days (a single quarter) and, when a period appears
more than once, keeps the one with the latest `filed` date. This logic is
covered by `tests/test_sec_edgar_parsing.py` using a fixture built from
real SNOW data confirmed live against the API while building this.

## How the non-GAAP side works

Non-GAAP figures (adjusted EPS, non-GAAP operating margin, RPO, NRR) are
defined by each company itself and only published in the prose/tables of
its earnings press release — there's no SEC-standardized API for them. For
now, `data/non_gaap/<TICKER>.json` holds them by hand, in the same shape
(`NonGaapQuarter`) an automated parser would eventually produce, so
swapping in real automation later is additive, not a rewrite.

**To compare a new company, you don't need to add non-GAAP data first** —
GAAP figures work automatically for any ticker via SEC EDGAR. Non-GAAP
data (and therefore the gap metrics) will just show as blank until you add
`data/non_gaap/<TICKER>.json` for that company.

## How cross-company comparison works

`cross_company.py` fetches each requested ticker independently and builds
one `CompanySnapshot` per company from its own most-recently-reported
quarter. It deliberately does NOT try to match fiscal quarter numbers
across companies (e.g. "SNOW's Q2" vs. "some retailer's Q2") because
different companies' fiscal years don't line up on the calendar — SNOW's
fiscal year ends January 31, so lining up by fiscal label instead of
calendar recency would silently compare quarters that don't overlap in
time. See the docstring at the top of `cross_company.py` for the full
reasoning.

## The dashboard

`streamlit run dashboard.py` opens a browser tab with two top-level tabs:

**Earnings Screener** — everything from before, now nested under one tab,
with four sections inside it:

- **Quarterly Detail** — the GAAP vs. non-GAAP table and charts for one
  ticker (same data as the CLI, browsable/sortable instead of printed).
- **QoQ vs YoY** — growth-rate charts plus the same divergence flags the
  CLI prints (e.g. "RPO fell X% QoQ while still up Y% YoY").
- **Stock Price** — a price chart for the primary ticker (and any
  comparison tickers, normalized to % change so different share prices
  are comparable), optionally with the reported quarter-end dates marked
  so you can eyeball how price moved around earnings.
- **Compare Companies** — add tickers in the sidebar to see their latest
  quarters side by side, plus bar charts of revenue YoY growth and
  GAAP-vs-non-GAAP EPS across companies.

**Watchlist** — a separate, simpler feature: add tickers to a personal
list (persisted to `data/watchlist.json`, so it survives closing and
reopening the dashboard), remove them, and see a price chart for each —
plus one combined chart normalizing all of them to % change so you can
compare performance across very differently priced stocks at a glance.
It shares the same price-fetching code (and cache) as the Earnings
Screener's Stock Price tab, so looking up a ticker in both places only
fetches it once.

If you haven't used Streamlit before: it re-runs this whole script top to
bottom every time you touch a widget (a slider, a text box, adding a
watchlist ticker) — there's no manual event-wiring like a typical web
framework. The `@st.cache_data` decorators near the top of `dashboard.py`
are what stop that from re-hitting SEC EDGAR/Yahoo Finance on every single
interaction; see the comments there for details. Each tab's content also
lives in its own function (`render_earnings_screener_tab` /
`render_watchlist_tab`) rather than flat top-level code — that's what lets
one tab bail out early (no email entered yet, no watchlist tickers yet)
via a normal `return` without blanking out the *other* tab too, which is
what would happen with Streamlit's `st.stop()`.

## Publishing this to GitHub

Nothing in this repo needs to be scrubbed before making it public/private —
the SEC EDGAR contact email is always supplied at runtime (an environment
variable, a CLI flag, or the dashboard's sidebar box), never hardcoded into
a file, and there are no other credentials or API keys anywhere in this
project. `.gitignore` also excludes `.env` files and Streamlit's
`secrets.toml` in case you add either later.

To publish as a private repo, from a real Terminal window in this folder
(not needed if you already know your way around `git`):

```bash
git init
git add .
git commit -m "Initial commit"
```

Then either, if you have the GitHub CLI installed and are logged in
(`gh auth status` to check):

```bash
gh repo create earnings-screener --private --source=. --remote=origin --push
```

...or, without `gh`: create a new **private** repository named
`earnings-screener` at github.com/new (leave "Add a README"/".gitignore"
unchecked, since this folder already has both), then:

```bash
git remote add origin https://github.com/<your-username>/earnings-screener.git
git branch -M main
git push -u origin main
```

## Known limitations

- **Q4 isn't derived.** SEC filings report Q1-Q3 as discrete quarters but
  the "fourth quarter" only shows up as part of the full-year 10-K figure.
  Getting a true Q4 means subtracting Q1+Q2+Q3 from the full year — not
  implemented yet.
- **The most recent quarter can lag the press release by days to weeks.**
  Companies typically issue the earnings press release (8-K) before the
  detailed 10-Q is filed with XBRL data. Right after an earnings report,
  don't be surprised if that quarter's GAAP figures show as missing for a
  bit — the non-GAAP figures (seeded manually from the press release) will
  still show.
- **The GAAP/non-GAAP gap math needs a diluted share count for the same
  quarter** to convert an EPS gap into a dollar/revenue-% gap. If SEC
  hasn't tagged `WeightedAverageNumberOfDilutedSharesOutstanding` for that
  quarter yet, the gap-in-dollars and gap-%-of-revenue figures just won't
  show (rather than showing something wrong).
- **yfinance is a scraper of an unofficial Yahoo endpoint**, not an
  official API — it's normally reliable for plain closing prices (unlike
  for non-GAAP earnings figures, which is a separate and worse problem —
  see `sources/stock_prices.py`'s docstring), but if it ever starts
  failing for everyone, `pip install --upgrade yfinance` is the first
  thing to try.
- **Only one ticker's non-GAAP data is seeded** (SNOW). Add another
  ticker by creating `data/non_gaap/<TICKER>.json` in the same format.

## Next steps (not built yet, on purpose)

1. **Define the "abnormal" threshold.** Once you've eyeballed enough
   quarters/companies to have a feel for it, decide the rule — e.g. "gap >
   X% of revenue" or "gap more than N standard deviations above this
   company's own trailing 4-8 quarter average" — and add a `flag.py` that
   consumes `QuarterComparison` objects and adds a boolean/severity field.
   Nothing above needs to change for this.
2. **Break down *why* the gap is large**, not just that it is — GAAP
   already exposes stock-based comp (`stock_based_comp` /
   `sbc_pct_of_revenue` are already on the objects; the dashboard doesn't
   chart it yet), and other common add-backs (amortization of acquired
   intangibles, restructuring charges) are individually tagged in XBRL too
   and can be added to `sec_edgar.py` the same way SBC was.
3. **Automate non-GAAP extraction** from the 8-K's EX-99.1 press-release
   exhibit (SEC EDGAR's `submissions` API can find the filing, then it's
   an HTML parsing problem) instead of hand-entering `data/non_gaap/*`.
4. **True Q4 and full-year figures**, derived by subtracting Q1-Q3 from
   the annual 10-K figure.
5. **A "watchlist" of tickers with data pre-loaded**, instead of typing
   tickers into the sidebar each time — a small config file the dashboard
   reads on startup.
