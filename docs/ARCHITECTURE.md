# Architecture

`edgarpull` is a thin, dependency-free client over the public SEC EDGAR JSON
APIs, structured around a single fetch indirection so the same parsing code runs
both live and fully offline.

## Modules

```
edgarpull/
  core.py        # Fetcher (live HTTP / demo cache), Edgar engine, parsers, dataclasses
  cli.py         # argparse front-end; table + json renderers
  mcp_server.py  # stdio JSON-RPC 2.0 MCP server exposing the four query tools
  __main__.py    # `python -m edgarpull`
  sample_cache.json  # offline bundle mirroring real SEC JSON shapes
```

## Data flow

1. **Resolve** the identifier. `company_tickers.json` (object keyed by row, with
   `cik_str`/`ticker`/`title`) is indexed by both ticker and zero-padded 10-digit
   CIK. A value that already looks like a CIK skips the symbol lookup.
2. **Fetch submissions.** `data.sec.gov/submissions/CIK##########.json` returns a
   *columnar* `filings.recent` table (parallel arrays for `form`, `filingDate`,
   `accessionNumber`, `items`, …). `_recent_filings` zips those columns into
   `Filing` rows.
3. **Filter** by the subcommand's form set (`insiders` → `4`/`4/A`, etc.;
   `filings` applies no filter) and apply `--limit`.
4. **Render** as a table or JSON. JSON rows include a derived EDGAR archive URL.

## Live vs demo

`Fetcher(mode="live")` performs real HTTP with the SEC-required `User-Agent`,
gzip handling, and a monotonic-clock throttle between requests. `Fetcher(mode=
"demo")` resolves the same logical keys (`tickers`, a CIK) from an in-memory
cache loaded from `sample_cache.json`. Because the indirection sits *below* all
parsing, the demo and tests exercise the real engine without a network. Live
HTTP is itself unit-tested via an injectable `opener` (a fake urlopen).

## Rate limiting

The SEC asks clients to stay under ~10 requests/second and to identify
themselves. edgarpull defaults to a ~5 req/s sleep (`--sleep`) and a descriptive
`User-Agent` (`--user-agent`).
