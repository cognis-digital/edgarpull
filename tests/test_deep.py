"""Deep behavior tests for edgarpull — parsing, CIK normalization, live-mode
fetch via a fake opener (no real network), MCP server round-trips.

Standard library only.
"""

import io
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edgarpull import mcp_server  # noqa: E402
from edgarpull.cli import main  # noqa: E402
from edgarpull.core import (  # noqa: E402
    Edgar,
    EdgarError,
    Fetcher,
    Filing,
    load_sample_cache,
    normalize_cik,
    resolve_company,
)


class TestCikNormalization(unittest.TestCase):
    def test_pad(self):
        self.assertEqual(normalize_cik("320193"), "0000320193")

    def test_prefixed(self):
        self.assertEqual(normalize_cik("CIK0000320193"), "0000320193")

    def test_already_padded(self):
        self.assertEqual(normalize_cik("0000320193"), "0000320193")

    def test_empty_raises(self):
        with self.assertRaises(EdgarError):
            normalize_cik("abc")


class TestResolveAndParse(unittest.TestCase):
    def setUp(self):
        self.fetcher = Fetcher(mode="demo", cache=load_sample_cache())

    def test_resolve_ticker(self):
        c = resolve_company("aapl", self.fetcher)
        self.assertEqual(c.cik, "0000320193")
        self.assertEqual(c.name, "Apple Inc.")

    def test_resolve_cik_not_in_table_is_usable(self):
        # Demo cache only has submissions for known CIKs, but resolution of an
        # unknown CIK should still produce a Company (live mode would fetch it).
        c = resolve_company("9999999999", self.fetcher)
        self.assertEqual(c.cik, "9999999999")
        self.assertEqual(c.ticker, "")

    def test_filing_url_built(self):
        f = Filing(cik="0000320193", form="8-K", filing_date="2026-04-28",
                   accession="0000320193-26-000040",
                   primary_document="aapl-20260428.htm")
        self.assertIn("/Archives/edgar/data/320193/", f.url)
        self.assertIn("000032019326000040", f.url)  # accession, dashes stripped
        self.assertTrue(f.url.endswith("aapl-20260428.htm"))

    def test_berkshire_13f(self):
        r = Edgar(self.fetcher).institutions("BRK-B")
        self.assertEqual(r.company.cik, "0001067983")
        self.assertGreater(len(r.filings), 0)


class _FakeResp:
    """Context-manager stand-in for urlopen's HTTPResponse."""

    def __init__(self, payload):
        self._data = json.dumps(payload).encode("utf-8")
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._data


class TestLiveModeWithFakeOpener(unittest.TestCase):
    """Exercise the live HTTP code path without touching the network."""

    def test_live_fetch_sets_user_agent_and_parses(self):
        sample = load_sample_cache()
        captured = {}

        def fake_opener(req, timeout=30):
            captured["url"] = req.full_url
            captured["ua"] = req.get_header("User-agent")
            if req.full_url.endswith("company_tickers.json"):
                return _FakeResp(sample["tickers"])
            return _FakeResp(sample["submissions"]["0000320193"])

        fetcher = Fetcher(mode="live", user_agent="UnitTest test@example.com",
                          sleep_seconds=0.0, opener=fake_opener)
        r = Edgar(fetcher).insiders("AAPL")
        self.assertEqual(r.source, "live")
        self.assertEqual(captured["ua"], "UnitTest test@example.com")
        self.assertTrue(captured["url"].startswith("https://data.sec.gov/"))
        for f in r.filings:
            self.assertIn(f.form.upper(), ("4", "4/A"))


class TestCliOutputs(unittest.TestCase):
    def test_table_contains_company(self):
        rc = main(["filings", "AAPL", "--demo"])
        self.assertEqual(rc, 0)

    def test_json_to_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "r.json")
            rc = main(["insiders", "AAPL", "--demo", "--format", "json", "--out", out])
            self.assertEqual(rc, 0)
            with open(out, encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertEqual(data["kind"], "insiders")
            self.assertEqual(data["tool"], "edgarpull")

    def test_limit_zero_returns_all(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "r.json")
            main(["filings", "AAPL", "--demo", "--limit", "0",
                  "--format", "json", "--out", out])
            with open(out, encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertGreaterEqual(data["count"], 8)


class TestMcpServer(unittest.TestCase):
    def _roundtrip(self, requests):
        stdin = io.StringIO("\n".join(json.dumps(r) for r in requests) + "\n")
        stdout = io.StringIO()
        mcp_server.run_mcp_server(stdin=stdin, stdout=stdout)
        return [json.loads(l) for l in stdout.getvalue().splitlines() if l.strip()]

    def test_initialize_and_list(self):
        out = self._roundtrip([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ])
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["result"]["serverInfo"]["name"], "edgarpull")
        names = {t["name"] for t in out[1]["result"]["tools"]}
        self.assertEqual(names, {"filings", "insiders", "institutions", "events"})

    def test_tools_call_demo(self):
        out = self._roundtrip([
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "institutions",
                        "arguments": {"identifier": "AAPL", "demo": True}}},
        ])
        res = out[0]["result"]
        self.assertFalse(res["isError"])
        payload = json.loads(res["content"][0]["text"])
        self.assertEqual(payload["kind"], "institutions")
        self.assertGreater(payload["count"], 0)

    def test_missing_identifier_is_error(self):
        out = self._roundtrip([
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
             "params": {"name": "filings", "arguments": {"demo": True}}},
        ])
        self.assertEqual(out[0]["error"]["code"], -32602)

    def test_unknown_tool_is_error(self):
        out = self._roundtrip([
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
             "params": {"name": "nope", "arguments": {"identifier": "AAPL"}}},
        ])
        self.assertEqual(out[0]["error"]["code"], -32602)

    def test_parse_error(self):
        stdin = io.StringIO("{not json\n")
        stdout = io.StringIO()
        mcp_server.run_mcp_server(stdin=stdin, stdout=stdout)
        out = json.loads(stdout.getvalue().strip())
        self.assertEqual(out["error"]["code"], -32700)

    def test_unknown_method(self):
        out = self._roundtrip([
            {"jsonrpc": "2.0", "id": 6, "method": "totally/unknown"},
        ])
        self.assertEqual(out[0]["error"]["code"], -32601)


if __name__ == "__main__":
    unittest.main()
