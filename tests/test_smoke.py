"""Smoke tests for edgarpull. Standard library only, fully offline (--demo)."""

import json
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edgarpull import TOOL_NAME, TOOL_VERSION, Edgar  # noqa: E402
from edgarpull.cli import main  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestMetadata(unittest.TestCase):
    def test_metadata(self):
        self.assertEqual(TOOL_NAME, "edgarpull")
        self.assertTrue(TOOL_VERSION)


class TestEngineDemo(unittest.TestCase):
    def setUp(self):
        self.edgar = Edgar.demo()

    def test_filings_by_ticker(self):
        r = self.edgar.filings("AAPL")
        self.assertEqual(r.company.cik, "0000320193")
        self.assertEqual(r.company.ticker, "AAPL")
        self.assertEqual(r.source, "demo")
        self.assertGreater(len(r.filings), 0)

    def test_filings_by_cik(self):
        r = self.edgar.filings("320193")
        self.assertEqual(r.company.cik, "0000320193")
        self.assertEqual(r.company.name, "Apple Inc.")

    def test_insiders_only_form4(self):
        r = self.edgar.insiders("AAPL")
        self.assertGreater(len(r.filings), 0)
        for f in r.filings:
            self.assertIn(f.form.upper(), ("4", "4/A"))

    def test_institutions_only_13f(self):
        r = self.edgar.institutions("AAPL")
        self.assertGreater(len(r.filings), 0)
        for f in r.filings:
            self.assertTrue(f.form.upper().startswith("13F"))

    def test_events_only_8k(self):
        r = self.edgar.events("AAPL")
        self.assertGreater(len(r.filings), 0)
        for f in r.filings:
            self.assertTrue(f.form.upper().startswith("8-K"))
        # 8-K items are surfaced.
        self.assertTrue(any(f.items for f in r.filings))

    def test_limit(self):
        r = self.edgar.filings("AAPL", limit=2)
        self.assertEqual(len(r.filings), 2)

    def test_unknown_ticker_raises(self):
        from edgarpull.core import EdgarError
        with self.assertRaises(EdgarError):
            self.edgar.filings("NOSUCHTICKERZZZ")


class TestCli(unittest.TestCase):
    def test_version_subprocess(self):
        proc = subprocess.run(
            [sys.executable, "-m", "edgarpull", "--version"],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn(TOOL_VERSION, proc.stdout)

    def test_help_subprocess(self):
        proc = subprocess.run(
            [sys.executable, "-m", "edgarpull", "--help"],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_demo_json(self):
        proc = subprocess.run(
            [sys.executable, "-m", "edgarpull", "institutions", "AAPL",
             "--demo", "--format", "json"],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["kind"], "institutions")
        self.assertEqual(data["source"], "demo")
        self.assertGreater(data["count"], 0)

    def test_main_table(self):
        self.assertEqual(main(["events", "AAPL", "--demo"]), 0)

    def test_main_unknown_ticker_exits_2(self):
        self.assertEqual(main(["filings", "NOPEZZZ", "--demo"]), 2)

    def test_no_command_exits_2(self):
        self.assertEqual(main([]), 2)


if __name__ == "__main__":
    unittest.main()
