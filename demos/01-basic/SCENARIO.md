# Demo 01 — EDGAR intelligence on a ticker, fully offline

This scenario runs `edgarpull` against the bundled **sample bundle** (a cached,
illustrative copy of the SEC `company_tickers.json` and `data.sec.gov`
submissions JSON for Apple Inc., CIK 0000320193). Because it uses `--demo`, it
makes **no network calls** and works on a fresh checkout with zero setup.

The same parsing/intelligence code runs in live mode; only the fetch source
differs.

## Run it

```bash
# 13F institutional-holder filings
python -m edgarpull institutions AAPL --demo

# Form 4 insider buys/sells, machine-readable
python -m edgarpull insiders AAPL --demo --format json

# 8-K material events (item codes surfaced)
python -m edgarpull events AAPL --demo

# Any filing type, by CIK instead of ticker
python -m edgarpull filings 320193 --demo --limit 5
```

## What you should see

| Subcommand     | Form filter        | In the sample bundle                       |
|----------------|--------------------|--------------------------------------------|
| `filings`      | none               | 10-Q, 4, 4/A, 8-K, 13F-HR (all recent)     |
| `insiders`     | `4`, `4/A`         | 3 Form 4 / 4-A filings                      |
| `institutions` | `13F-HR`, `13F-NT` | 2 13F-HR filings                            |
| `events`       | `8-K`, `8-K/A`     | 2 8-K filings, with item codes (2.02, 5.02) |

Each filing row includes the filing date, form type, report date, accession
number, and (in JSON) a direct EDGAR archive URL.

## Going live

Drop `--demo` to query the real SEC APIs (free, no key). The SEC requires a
descriptive `User-Agent`; edgarpull sends one by default and you can override it:

```bash
python -m edgarpull institutions AAPL \
  --user-agent "Your Name your-email@example.com"
```
