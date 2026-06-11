"""edgarpull MCP server.

Exposes the EDGAR query engine as MCP tools over stdio using newline-delimited
JSON-RPC 2.0. Standard library only — no SDK — so it runs anywhere Python does
and can be wired into Cognis.Studio, Claude Desktop, or Cursor:

    {"command": "python", "args": ["-m", "edgarpull", "mcp"]}

Tools: filings, insiders, institutions, events. Each accepts an ``identifier``
(ticker or CIK), an optional ``limit``, and an optional ``demo`` flag that runs
offline against the bundled sample bundle.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, Optional

from edgarpull import TOOL_NAME, TOOL_VERSION
from edgarpull.core import Edgar, EdgarError

PROTOCOL_VERSION = "2024-11-05"

_QUERY_KINDS = ("filings", "insiders", "institutions", "events")

_DESCRIPTIONS = {
    "filings": "List recent SEC EDGAR filings of any type for a ticker or CIK.",
    "insiders": "List Form 4 insider buy/sell filings for a ticker or CIK.",
    "institutions": "List 13F institutional-holder filings for a ticker or CIK.",
    "events": "List 8-K material-event filings for a ticker or CIK.",
}


def _tool_schema(name: str) -> Dict[str, Any]:
    return {
        "name": name,
        "description": _DESCRIPTIONS[name],
        "inputSchema": {
            "type": "object",
            "properties": {
                "identifier": {
                    "type": "string",
                    "description": "Ticker symbol (e.g. AAPL) or CIK (e.g. 320193).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max filings to return (default 20; 0 = all).",
                },
                "demo": {
                    "type": "boolean",
                    "description": "Run offline against the bundled sample bundle.",
                },
            },
            "required": ["identifier"],
            "additionalProperties": False,
        },
    }


_TOOLS = [_tool_schema(k) for k in _QUERY_KINDS]


def _result(req_id: Any, result: Dict[str, Any]) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error(req_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _call_tool(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    if name not in _QUERY_KINDS:
        raise ValueError(f"unknown tool: {name}")
    identifier = arguments.get("identifier")
    if not isinstance(identifier, str) or not identifier:
        raise ValueError("`identifier` (ticker or CIK string) is required")
    limit = arguments.get("limit", 20)
    if not isinstance(limit, int):
        raise ValueError("`limit` must be an integer")
    demo = bool(arguments.get("demo", False))

    engine = Edgar.demo() if demo else Edgar.live()
    result = getattr(engine, name)(identifier, limit=limit)
    payload = result.to_dict()
    return {
        "content": [{"type": "text", "text": json.dumps(payload, indent=2)}],
        "isError": False,
    }


def handle_request(req: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Dispatch a single JSON-RPC request. Returns None for notifications."""
    method = req.get("method")
    req_id = req.get("id")
    params = req.get("params") or {}
    is_notification = "id" not in req

    if method == "initialize":
        res = _result(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": TOOL_NAME, "version": TOOL_VERSION},
        })
        return None if is_notification else res

    if method in ("notifications/initialized", "initialized"):
        return None

    if method == "ping":
        return None if is_notification else _result(req_id, {})

    if method == "tools/list":
        return _result(req_id, {"tools": _TOOLS})

    if method == "tools/call":
        name = params.get("name", "")
        arguments = params.get("arguments") or {}
        try:
            return _result(req_id, _call_tool(name, arguments))
        except (ValueError, EdgarError) as exc:
            return _error(req_id, -32602, str(exc))
        except Exception as exc:  # pragma: no cover - defensive
            return _error(req_id, -32603, f"internal error: {exc}")

    if is_notification:
        return None
    return _error(req_id, -32601, f"method not found: {method}")


def run_mcp_server(stdin=None, stdout=None) -> None:
    """Read newline-delimited JSON-RPC from stdin, write responses to stdout."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            stdout.write(json.dumps(_error(None, -32700, "parse error")) + "\n")
            stdout.flush()
            continue
        response = handle_request(req)
        if response is not None:
            stdout.write(json.dumps(response) + "\n")
            stdout.flush()


if __name__ == "__main__":
    run_mcp_server()
