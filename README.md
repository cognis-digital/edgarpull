# edgarpull — SEC EDGAR intelligence (13F, Form 4, 8-K) by ticker/CIK

> Part of the **[Cognis Neural Suite](https://github.com/cognis-digital)** by [Cognis Digital](https://cognis.digital)
> Cognis Open Collaboration License (COCL) v1.0 · domain: `fintech`

[![PyPI](https://img.shields.io/pypi/v/cognis-edgarpull.svg)](https://pypi.org/project/cognis-edgarpull/)
[![CI](https://github.com/cognis-digital/edgarpull/actions/workflows/ci.yml/badge.svg)](https://github.com/cognis-digital/edgarpull/actions)
[![License: COCL 1.0](https://img.shields.io/badge/License-COCL%201.0-2b6cb0.svg)](LICENSE)
[![Suite](https://img.shields.io/badge/Cognis-Neural%20Suite-6b46c1.svg)](https://github.com/cognis-digital)

**Pull SEC EDGAR data — 13F institutional holdings, Form 4 insider trades, and 8-K material events — by ticker or CIK.**

*Fintech & markets — turning public regulatory filings into structured signal.*

Uses the **official, public, free, no-key** SEC endpoints:
`company_tickers.json` for ticker→CIK resolution and the `data.sec.gov`
submissions API for filing history. Standard library only (urllib/json) — no
pip dependencies. The SEC requires a descriptive `User-Agent` and asks clients
to stay under ~10 req/s; edgarpull sends a proper UA and sleeps between live
requests.

## Why

Analysts and quants need fast, scriptable access to who is buying, who is
selling, and what just materially changed — without standing up a data vendor.
`edgarpull` is single-purpose and CI-friendly: point it at a ticker, get
structured filings in table or JSON, and wire it into agents over MCP when you
want it autonomous. It ships a cached sample bundle so it runs and tests fully
offline.

<!-- cognis:domains:start -->
## Domains

**Primary domain:** Intelligence & OSINT  ·  **JTF MERIDIAN division:** NULLBYTE · BLACK CELL

**Topics:** `cognis` `osint` `intelligence` `recon`

Part of the **Cognis Neural Suite** — 300+ source-available tools organized across 12 domains under the JTF MERIDIAN command structure. See the [suite on GitHub](https://github.com/cognis-digital) and [jtf-meridian](https://github.com/cognis-digital/jtf-meridian) for how the pieces fit together.
<!-- cognis:domains:end -->

## Install

```bash
pip install cognis-edgarpull
# or, from this repo:
pip install -e ".[dev]"
```

## Quick start

```bash
edgarpull --version
edgarpull institutions AAPL --demo          # offline against the sample bundle
edgarpull insiders AAPL --demo --format json
edgarpull events AAPL --demo
edgarpull filings 320193 --demo --limit 5   # by CIK instead of ticker
edgarpull filings AAPL --demo --format html --out aapl.html   # styled HTML report

# full-text search across ALL filers (EDGAR efts.sec.gov, 2001→present):
edgarpull fulltext '"battery storage"' --forms 8-K --limit 10
edgarpull fulltext "artificial intelligence" --format html --out ai.html

# live (real SEC APIs, no key needed) — supply a contact UA per SEC policy:
edgarpull institutions AAPL --user-agent "Your Name you@example.com"

edgarpull mcp                               # expose as an MCP server
```

## Subcommands

| Command                       | What it returns                                   | Forms             |
|-------------------------------|---------------------------------------------------|-------------------|
| `filings <ticker\|cik>`       | Recent filings of any type                        | all               |
| `insiders <ticker\|cik>`      | Insider buys/sells                                | `4`, `4/A`        |
| `institutions <ticker\|cik>`  | 13F institutional-holder filings                  | `13F-HR`, `13F-NT`|
| `events <ticker\|cik>`        | Material events (with 8-K item codes)             | `8-K`, `8-K/A`    |
| `fulltext <query>`            | Full-text search across **all** filers            | any (`--forms`)   |

Flags: `--format table|json|html`, `--limit N` (`0` = all), `--out FILE`,
`--demo`, `--user-agent STR`, `--sleep SECONDS`. `fulltext` adds `--forms` to
restrict to comma-separated form types (e.g. `--forms 8-K,10-K`).

## Built-in demo scenario

See [`demos/01-basic/SCENARIO.md`](demos/01-basic/SCENARIO.md). It runs entirely
offline against [`edgarpull/sample_cache.json`](edgarpull/sample_cache.json),
whose shapes mirror the real SEC `company_tickers.json` and submissions API.

## Output formats

- **Table** (default) — human-readable terminal summary
- **JSON** — machine-readable filings (with direct EDGAR archive URLs) for pipelines
- **HTML** (`--format html`) — a self-contained, styled report with clickable
  accession links to the EDGAR archive; all dynamic text is HTML-escaped

## Full-text search

`edgarpull fulltext <query>` queries the EDGAR full-text search API
(`efts.sec.gov`), which indexes filing **content** across every filer from 2001
to the present — complementing the per-issuer submissions feed. Quote a phrase
for an exact match and use `--forms` to narrow by form type. It sends the same
descriptive `User-Agent` and fails gracefully when offline (use `--demo` for the
bundled fixture).

## MCP server

```jsonc
{ "command": "python", "args": ["-m", "edgarpull", "mcp"] }
```

Exposes `filings`, `insiders`, `institutions`, and `events` as MCP tools over
stdio JSON-RPC (each accepts `identifier`, optional `limit`, optional `demo`).
Standard-library implementation — no SDK required.

## Credits / Built on

Cognis composes and credits the best of open source. This tool builds on:

- [U.S. SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) — the public data source
- [`data.sec.gov` submissions & company_tickers](https://www.sec.gov/files/company_tickers.json) — endpoints

Missing a credit? Open a PR.

## How it fits the Cognis Neural Suite

`edgarpull` is one tool in the [Cognis Neural Suite](https://github.com/cognis-digital).
Every tool ships an MCP server, so [Cognis.Studio](https://cognis.studio) agents
can call them as scoped capabilities.

## License

Source-available under the **Cognis Open Collaboration License (COCL) v1.0** —
free for personal, internal-evaluation, research, and educational use;
**commercial / production use requires a license** (licensing@cognis.digital).
See [LICENSE](LICENSE).

## Responsible use

EDGAR data is public. Respect the SEC's fair-access policy: send a descriptive
`User-Agent` and keep request rates polite (edgarpull does both by default).
Filings are regulatory disclosures, not investment advice.

## About

**[Cognis Digital](https://cognis.digital)** — Wyoming, USA · *Making Tomorrow Better Today: Advanced Cybersecurity, AI Innovation, and Blockchain Expertise.*
