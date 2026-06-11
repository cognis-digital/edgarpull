"""Command-line interface for edgarpull.

Subcommands:
  filings <ticker|cik>     recent filings of any type
  insiders <ticker|cik>    Form 4 insider buys/sells
  institutions <ticker|cik> 13F institutional-holder filings
  events <ticker|cik>      8-K material events

By default queries hit the live SEC EDGAR APIs (free, no key) with the required
User-Agent and a polite rate-limit sleep. ``--demo`` runs entirely offline
against the bundled sample bundle so the tool is testable without a network.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from edgarpull import TOOL_NAME, TOOL_VERSION
from edgarpull.core import (
    DEFAULT_USER_AGENT,
    SEC_RATE_LIMIT_SLEEP,
    Edgar,
    EdgarError,
    Result,
)

_KIND_TITLE = {
    "filings": "Recent filings",
    "insiders": "Form 4 insider transactions",
    "institutions": "13F institutional holdings filings",
    "events": "8-K material events",
}


def _truncate(text: str, width: int) -> str:
    text = text or ""
    return text if len(text) <= width else text[: width - 1] + "~"


def _render_table(result: Result) -> str:
    c = result.company
    lines: List[str] = []
    title = _KIND_TITLE.get(result.kind, result.kind)
    name = c.name or "(unknown)"
    header = f"{TOOL_NAME}: {title} - {name} [{c.ticker or '?'}] CIK {c.cik}"
    lines.append(header)
    lines.append("=" * max(len(header), 60))
    if not result.filings:
        lines.append("No matching filings found.")
        lines.append("-" * 60)
        lines.append(f"source={result.source}  count=0")
        return "\n".join(lines)

    show_items = result.kind in ("events", "filings")
    if show_items:
        lines.append(f"{'FILED':<11} {'FORM':<8} {'REPORT':<11} {'ITEMS':<14} ACCESSION")
    else:
        lines.append(f"{'FILED':<11} {'FORM':<8} {'REPORT':<11} ACCESSION")
    lines.append("-" * 60)
    for f in result.filings:
        if show_items:
            lines.append(
                f"{f.filing_date:<11} {f.form:<8} {f.report_date:<11} "
                f"{_truncate(f.items, 14):<14} {f.accession}"
            )
        else:
            lines.append(
                f"{f.filing_date:<11} {f.form:<8} {f.report_date:<11} {f.accession}"
            )
    lines.append("-" * 60)
    lines.append(f"source={result.source}  count={len(result.filings)}")
    return "\n".join(lines)


def _emit(text: str, out: Optional[str]) -> None:
    if out:
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(text if text.endswith("\n") else text + "\n")
        print(f"wrote {out}", file=sys.stderr)
    else:
        print(text)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=TOOL_NAME,
        description="SEC EDGAR intelligence — 13F institutional holdings, "
                    "Form 4 insider trades, and 8-K material events by "
                    "ticker/CIK. Public, free, no API key.",
    )
    p.add_argument("--version", action="version",
                   version=f"{TOOL_NAME} {TOOL_VERSION}")
    sub = p.add_subparsers(dest="command")

    def _common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("identifier", metavar="TICKER|CIK",
                        help="Ticker symbol (e.g. AAPL) or CIK (e.g. 320193).")
        sp.add_argument("--format", choices=("table", "json"), default="table",
                        help="Output format (default: table).")
        sp.add_argument("--limit", type=int, default=20,
                        help="Max filings to return (default: 20; 0 = all).")
        sp.add_argument("--out", help="Write output to this file instead of stdout.")
        sp.add_argument("--demo", action="store_true",
                        help="Run offline against the bundled sample bundle.")
        sp.add_argument("--user-agent", default=DEFAULT_USER_AGENT,
                        help="User-Agent header for live SEC requests "
                             "(SEC requires a descriptive contact string).")
        sp.add_argument("--sleep", type=float, default=SEC_RATE_LIMIT_SLEEP,
                        help="Seconds to sleep between live SEC requests "
                             "(rate-limit politeness).")

    for name, help_text in (
        ("filings", "Recent filings of any type for a ticker/CIK."),
        ("insiders", "Form 4 insider buys/sells for a ticker/CIK."),
        ("institutions", "13F institutional-holder filings for a ticker/CIK."),
        ("events", "8-K material events for a ticker/CIK."),
    ):
        sp = sub.add_parser(name, help=help_text)
        _common(sp)

    # mcp: expose as an MCP server over stdio.
    sub.add_parser("mcp", help="Run as an MCP server (stdio JSON-RPC).")
    return p


def _engine(args: argparse.Namespace) -> Edgar:
    if args.demo:
        return Edgar.demo()
    return Edgar.live(user_agent=args.user_agent, sleep_seconds=args.sleep)


def _run_query(args: argparse.Namespace) -> int:
    try:
        engine = _engine(args)
        method = getattr(engine, args.command)
        result = method(args.identifier, limit=args.limit)
    except EdgarError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.format == "json":
        _emit(json.dumps(result.to_dict(), indent=2), args.out)
    else:
        _emit(_render_table(result), args.out)
    # Exit 0 even when empty: "no filings" is a valid, successful answer.
    return 0


def _run_mcp() -> int:
    from edgarpull.mcp_server import run_mcp_server
    run_mcp_server()
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command in ("filings", "insiders", "institutions", "events"):
        return _run_query(args)
    if args.command == "mcp":
        return _run_mcp()
    parser.print_help(sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
