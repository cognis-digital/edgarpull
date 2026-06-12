"""Tests for the full-text search subcommand and HTML report renderers.

Standard library only, fully offline. Exercises:
  * parse_fulltext_hits over cached/sample efts.sec.gov JSON shapes
  * CIK fallback parsing from display_names when no ``ciks`` list is present
  * Edgar.fulltext via the demo cache and via a fake live opener (no network)
  * --format html for both filings results and full-text results
  * HTML escaping of hostile dynamic text
  * the fulltext CLI in table / json / html modes
"""

import html.parser
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edgarpull import Edgar  # noqa: E402
from edgarpull.cli import main, render_fulltext_html, render_html  # noqa: E402
from edgarpull.core import (  # noqa: E402
    Company,
    EdgarError,
    Fetcher,
    Filing,
    FullTextResult,
    Result,
    _fulltext_total,
    load_sample_cache,
    parse_fulltext_hits,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _WellFormed(html.parser.HTMLParser):
    def error(self, message):  # pragma: no cover - only on malformed input
        raise AssertionError(message)


def _assert_html(doc):
    assert doc.startswith("<!DOCTYPE html>"), "missing doctype"
    assert doc.rstrip().endswith("</html>"), "missing closing html"
    _WellFormed().feed(doc)


# Real-world efts.sec.gov hit shape (mirrors the live endpoint).
LIVE_SHAPE = {
    "took": 7,
    "timed_out": False,
    "hits": {
        "total": {"value": 10000, "relation": "gte"},
        "hits": [
            {
                "_index": "edgar_file",
                "_id": "0001683168-20-000837:radnet_8k-ex9901.htm",
                "_source": {
                    "ciks": ["0000790526"],
                    "display_names": ["RadNet, Inc.  (RDNT)  (CIK 0000790526)"],
                    "root_forms": ["8-K"],
                    "form": "8-K",
                    "file_date": "2020-03-16",
                    "adsh": "0001683168-20-000837",
                },
            },
            {
                "_index": "edgar_file",
                "_id": "0000320193-26-000045:aapl.htm",
                "_source": {
                    "display_names": ["Apple Inc. (AAPL) (CIK 0000320193)"],
                    "form": "10-Q",
                    "file_date": "2026-05-02",
                },
            },
        ],
    },
}


class TestParseFulltextHits(unittest.TestCase):
    def test_basic_parse(self):
        hits = parse_fulltext_hits(LIVE_SHAPE, limit=20)
        self.assertEqual(len(hits), 2)
        self.assertEqual(hits[0].accession, "0001683168-20-000837")
        self.assertEqual(hits[0].form, "8-K")
        self.assertEqual(hits[0].file_date, "2020-03-16")
        self.assertEqual(hits[0].cik, "0000790526")
        self.assertEqual(hits[0].document, "radnet_8k-ex9901.htm")

    def test_cik_fallback_from_display_name(self):
        # Second hit has no ``ciks`` list and no ``adsh``; both must be derived.
        hits = parse_fulltext_hits(LIVE_SHAPE, limit=20)
        self.assertEqual(hits[1].cik, "0000320193")
        self.assertEqual(hits[1].accession, "0000320193-26-000045")

    def test_url_strips_leading_zeros(self):
        hits = parse_fulltext_hits(LIVE_SHAPE, limit=1)
        url = hits[0].url
        self.assertIn("/Archives/edgar/data/790526/", url)  # int, not zero-padded
        self.assertIn("000168316820000837", url)            # dashes stripped
        self.assertTrue(url.endswith("radnet_8k-ex9901.htm"))

    def test_limit_respected(self):
        self.assertEqual(len(parse_fulltext_hits(LIVE_SHAPE, limit=1)), 1)

    def test_defensive_on_garbage(self):
        self.assertEqual(parse_fulltext_hits(None, 5), [])
        self.assertEqual(parse_fulltext_hits({}, 5), [])
        self.assertEqual(parse_fulltext_hits({"hits": {"hits": ["x", 3]}}, 5), [])

    def test_total_estimate_flag(self):
        total, est = _fulltext_total(LIVE_SHAPE)
        self.assertEqual(total, 10000)
        self.assertTrue(est)
        self.assertEqual(_fulltext_total({"hits": {"total": {"value": 4,
                         "relation": "eq"}}}), (4, False))


class TestFulltextEngineDemo(unittest.TestCase):
    def test_demo_fulltext(self):
        r = Edgar.demo().fulltext("anything")
        self.assertEqual(r.source, "demo")
        self.assertEqual(r.kind if hasattr(r, "kind") else "fulltext", "fulltext")
        self.assertGreater(len(r.hits), 0)
        self.assertEqual(r.to_dict()["kind"], "fulltext")

    def test_empty_query_raises(self):
        with self.assertRaises(EdgarError):
            Edgar.demo().fulltext("   ")


class TestFulltextLiveFakeOpener(unittest.TestCase):
    def test_live_builds_efts_url_with_forms(self):
        captured = {}

        class _Resp:
            headers = {}

            def __init__(self, payload):
                self._d = json.dumps(payload).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return self._d

        def fake_opener(req, timeout=30):
            captured["url"] = req.full_url
            captured["ua"] = req.get_header("User-agent")
            return _Resp(LIVE_SHAPE)

        fetcher = Fetcher(mode="live", user_agent="UnitTest t@example.com",
                          sleep_seconds=0.0, opener=fake_opener)
        r = Edgar(fetcher).fulltext("battery storage", forms="8-K,10-K")
        self.assertEqual(r.source, "live")
        self.assertTrue(captured["url"].startswith("https://efts.sec.gov/LATEST/"))
        self.assertIn("q=battery+storage", captured["url"])
        self.assertIn("forms=8-K%2C10-K", captured["url"])
        self.assertEqual(captured["ua"], "UnitTest t@example.com")
        self.assertEqual(len(r.hits), 2)


class TestHtmlRender(unittest.TestCase):
    def test_filings_html_well_formed(self):
        r = Edgar.demo().filings("AAPL")
        doc = render_html(r)
        _assert_html(doc)
        self.assertIn("Apple Inc.", doc)
        self.assertIn("/Archives/edgar/data/320193/", doc)

    def test_fulltext_html_well_formed(self):
        r = Edgar.demo().fulltext("ai")
        doc = render_fulltext_html(r)
        _assert_html(doc)
        self.assertIn("full-text", doc)

    def test_empty_filings_html(self):
        empty = Result(company=Company(cik="0000000001", ticker="ZZ", name="Z"),
                       kind="insiders", filings=[], source="demo")
        doc = render_html(empty)
        _assert_html(doc)
        self.assertIn("No matching filings", doc)

    def test_empty_fulltext_html(self):
        empty = FullTextResult(query="nope", hits=[], total=0, source="demo")
        doc = render_fulltext_html(empty)
        _assert_html(doc)
        self.assertIn("No matching filings", doc)

    def test_html_escapes_hostile_text(self):
        nasty = '<script>alert(1)</script>"&'
        r = Result(
            company=Company(cik="0000000001", ticker=nasty, name=nasty),
            kind="filings",
            filings=[Filing(cik="0000000001", form=nasty, filing_date="2026-01-01",
                            accession="000", primary_document="d.htm", items=nasty)],
            source="demo",
        )
        doc = render_html(r)
        self.assertNotIn("<script>", doc)
        self.assertIn("&lt;script&gt;", doc)


class TestFulltextCli(unittest.TestCase):
    def test_table(self):
        self.assertEqual(main(["fulltext", "ai", "--demo"]), 0)

    def test_empty_query_exits_2(self):
        self.assertEqual(main(["fulltext", "   ", "--demo"]), 2)

    def test_json_subprocess(self):
        proc = subprocess.run(
            [sys.executable, "-m", "edgarpull", "fulltext", "ai",
             "--demo", "--format", "json"],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["kind"], "fulltext")
        self.assertEqual(data["source"], "demo")
        self.assertGreater(data["count"], 0)

    def test_html_to_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "r.html")
            rc = main(["filings", "AAPL", "--demo", "--format", "html", "--out", out])
            self.assertEqual(rc, 0)
            with open(out, encoding="utf-8") as fh:
                doc = fh.read()
            _assert_html(doc)

    def test_fulltext_html_to_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "r.html")
            rc = main(["fulltext", "ai", "--demo", "--format", "html", "--out", out])
            self.assertEqual(rc, 0)
            with open(out, encoding="utf-8") as fh:
                _assert_html(fh.read())


if __name__ == "__main__":
    unittest.main()
