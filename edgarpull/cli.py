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
import html
import json
import sys
from typing import List, Optional

from edgarpull import TOOL_NAME, TOOL_VERSION
from edgarpull.core import (
    DEFAULT_USER_AGENT,
    SEC_RATE_LIMIT_SLEEP,
    Edgar,
    EdgarError,
    FullTextResult,
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


_HTML_STYLE = (
    "body{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;"
    "margin:24px;color:#1a1a1a;background:#fafafa}"
    "h1{font-size:1.25rem;margin:0 0 4px}"
    ".sub{color:#555;font-size:.9rem;margin:0 0 16px}"
    "table{width:100%;border-collapse:collapse;background:#fff;"
    "box-shadow:0 1px 3px rgba(0,0,0,.08)}"
    "th,td{border-bottom:1px solid #e3e3e3;padding:8px 10px;text-align:left;"
    "font-size:.9rem;vertical-align:top}"
    "th{background:#f0f3f7;font-weight:600}"
    "tr:hover td{background:#f7faff}"
    "a{color:#0b5fff;text-decoration:none}a:hover{text-decoration:underline}"
    "code{font-family:Consolas,Menlo,monospace;font-size:.85rem}"
    "footer{margin-top:14px;color:#777;font-size:.8rem}"
    ".empty{padding:16px;color:#777}"
)


def _html_doc(title: str, body: str) -> str:
    return (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>{html.escape(title)}</title>\n"
        f"<style>{_HTML_STYLE}</style>\n</head>\n<body>\n"
        f"{body}\n</body>\n</html>\n"
    )


def render_html(result: Result) -> str:
    """Render a filings/insiders/institutions/events Result as standalone HTML."""
    c = result.company
    name = c.name or "(unknown)"
    title = _KIND_TITLE.get(result.kind, result.kind)
    doc_title = f"{TOOL_NAME}: {title} - {name}"
    parts: List[str] = []
    parts.append(f"<h1>{html.escape(doc_title)}</h1>")
    parts.append(
        "<p class=\"sub\">"
        f"Ticker {html.escape(c.ticker or '?')} &middot; "
        f"CIK {html.escape(c.cik)}</p>"
    )
    if not result.filings:
        parts.append("<div class=\"empty\">No matching filings found.</div>")
    else:
        parts.append("<table>")
        parts.append(
            "<tr><th>Filed</th><th>Form</th><th>Report</th>"
            "<th>Items</th><th>Accession</th></tr>"
        )
        for f in result.filings:
            parts.append(
                "<tr>"
                f"<td>{html.escape(f.filing_date)}</td>"
                f"<td>{html.escape(f.form)}</td>"
                f"<td>{html.escape(f.report_date)}</td>"
                f"<td>{html.escape(f.items)}</td>"
                f"<td><a href=\"{html.escape(f.url)}\" target=\"_blank\" "
                f"rel=\"noopener\"><code>{html.escape(f.accession)}</code></a></td>"
                "</tr>"
            )
        parts.append("</table>")
    parts.append(
        f"<footer>source={html.escape(result.source)} &middot; "
        f"count={len(result.filings)}</footer>"
    )
    return _html_doc(doc_title, "\n".join(parts))


def _render_fulltext_table(result: FullTextResult) -> str:
    lines: List[str] = []
    approx = "~" if result.total_is_estimate else ""
    header = (
        f"{TOOL_NAME}: full-text search \"{result.query}\""
        + (f" forms={result.forms}" if result.forms else "")
    )
    lines.append(header)
    lines.append("=" * max(len(header), 60))
    if not result.hits:
        lines.append("No matching filings found.")
        lines.append("-" * 60)
        lines.append(f"source={result.source}  total={approx}{result.total}  count=0")
        return "\n".join(lines)
    lines.append(f"{'FILED':<11} {'FORM':<10} {'CIK':<11} ENTITY")
    lines.append("-" * 60)
    for h in result.hits:
        lines.append(
            f"{h.file_date:<11} {_truncate(h.form, 10):<10} "
            f"{(h.cik or '?'):<11} {_truncate(h.display_name, 40)}"
        )
    lines.append("-" * 60)
    lines.append(
        f"source={result.source}  total={approx}{result.total}  "
        f"count={len(result.hits)}"
    )
    return "\n".join(lines)


def render_fulltext_html(result: FullTextResult) -> str:
    approx = "~" if result.total_is_estimate else ""
    doc_title = f"{TOOL_NAME}: full-text search “{result.query}”"
    parts: List[str] = []
    parts.append(f"<h1>{html.escape(doc_title)}</h1>")
    sub = f"{approx}{result.total} total filings match"
    if result.forms:
        sub += f" &middot; forms {html.escape(result.forms)}"
    parts.append(f"<p class=\"sub\">{sub}</p>")
    if not result.hits:
        parts.append("<div class=\"empty\">No matching filings found.</div>")
    else:
        parts.append("<table>")
        parts.append(
            "<tr><th>Filed</th><th>Form</th><th>CIK</th>"
            "<th>Entity</th><th>Accession</th></tr>"
        )
        for h in result.hits:
            parts.append(
                "<tr>"
                f"<td>{html.escape(h.file_date)}</td>"
                f"<td>{html.escape(h.form)}</td>"
                f"<td>{html.escape(h.cik or '?')}</td>"
                f"<td>{html.escape(h.display_name)}</td>"
                f"<td><a href=\"{html.escape(h.url)}\" target=\"_blank\" "
                f"rel=\"noopener\"><code>{html.escape(h.accession)}</code></a></td>"
                "</tr>"
            )
        parts.append("</table>")
    parts.append(
        f"<footer>source={html.escape(result.source)} &middot; "
        f"count={len(result.hits)}</footer>"
    )
    return _html_doc(doc_title, "\n".join(parts))


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
        sp.add_argument("--format", choices=("table", "json", "html"),
                        default="table",
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

    # fulltext: EDGAR full-text search across all filers (efts.sec.gov).
    ft = sub.add_parser(
        "fulltext",
        help="Full-text search across all EDGAR filings (efts.sec.gov).",
    )
    ft.add_argument("query", metavar="QUERY",
                    help="Search phrase. Quote multi-word phrases for exact match.")
    ft.add_argument("--forms", default="",
                    help="Restrict to comma-separated form types (e.g. 8-K,10-K).")
    ft.add_argument("--format", choices=("table", "json", "html"), default="table",
                    help="Output format (default: table).")
    ft.add_argument("--limit", type=int, default=20,
                    help="Max hits to return (default: 20; 0 = all on page).")
    ft.add_argument("--out", help="Write output to this file instead of stdout.")
    ft.add_argument("--demo", action="store_true",
                    help="Run offline against the bundled sample bundle.")
    ft.add_argument("--user-agent", default=DEFAULT_USER_AGENT,
                    help="User-Agent header for live SEC requests.")
    ft.add_argument("--sleep", type=float, default=SEC_RATE_LIMIT_SLEEP,
                    help="Seconds to sleep between live SEC requests.")

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
    elif args.format == "html":
        _emit(render_html(result), args.out)
    else:
        _emit(_render_table(result), args.out)
    # Exit 0 even when empty: "no filings" is a valid, successful answer.
    return 0


def _run_fulltext(args: argparse.Namespace) -> int:
    try:
        engine = _engine(args)
        result = engine.fulltext(args.query, limit=args.limit, forms=args.forms)
    except EdgarError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.format == "json":
        _emit(json.dumps(result.to_dict(), indent=2), args.out)
    elif args.format == "html":
        _emit(render_fulltext_html(result), args.out)
    else:
        _emit(_render_fulltext_table(result), args.out)
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
    if args.command == "fulltext":
        return _run_fulltext(args)
    if args.command == "mcp":
        return _run_mcp()
    parser.print_help(sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
