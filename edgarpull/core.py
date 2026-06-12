"""Core EDGAR intelligence engine for edgarpull.

Standard library only (urllib/json/re/time/os). Pulls PUBLIC, free, no-key data
from the official SEC endpoints:

  * https://www.sec.gov/files/company_tickers.json   (ticker -> CIK map)
  * https://data.sec.gov/submissions/CIK##########.json  (filing history)

SEC requires a descriptive ``User-Agent`` (company + contact) on every request
and asks clients to stay under ~10 requests/second. We set a proper UA and
sleep between live calls.

To keep tests and the bundled demo fully offline, every fetch goes through a
small ``Fetcher`` indirection: in *live* mode it hits the network; in *demo*
mode it reads from a cached sample JSON bundle on disk. The parsing/intelligence
layer is identical in both modes, so the demo exercises real code paths.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

TOOL_NAME = "edgarpull"
TOOL_VERSION = "0.1.0"

# SEC asks for a descriptive UA: "Sample Company Name AdminContact@example.com".
DEFAULT_USER_AGENT = "Cognis Digital edgarpull/{ver} suite@cognis.digital".format(
    ver=TOOL_VERSION
)
SEC_RATE_LIMIT_SLEEP = 0.2  # seconds between live requests (<= ~5 req/s)

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"
# EDGAR full-text search (free, no key). Covers filings from 2001 onward.
# The efts endpoint returns up to 100 hits/page; we slice client-side by limit.
FULLTEXT_BASE = "https://efts.sec.gov/LATEST/search-index"

# Form-type groupings used by the subcommands.
INSIDER_FORMS = ("4", "4/A")
INSTITUTION_FORMS = ("13F-HR", "13F-HR/A", "13F-NT")
EVENT_FORMS = ("8-K", "8-K/A")


class EdgarError(Exception):
    """Raised for unrecoverable data/lookup problems (not a programming bug)."""


@dataclass
class Filing:
    """A single filing pulled from the submissions ``recent`` table."""

    cik: str
    form: str
    filing_date: str
    accession: str
    primary_document: str = ""
    primary_doc_description: str = ""
    report_date: str = ""
    items: str = ""  # 8-K item codes, comma-separated, when present

    @property
    def url(self) -> str:
        """Human-facing URL to the filing index on EDGAR."""
        acc_nodash = self.accession.replace("-", "")
        cik_int = str(int(self.cik))
        return (
            "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
            f"&CIK={cik_int}&type={self.form}"
            if not acc_nodash
            else f"https://www.sec.gov/Archives/edgar/data/{cik_int}/"
            f"{acc_nodash}/{self.primary_document or (self.accession + '-index.htm')}"
        )

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "cik": self.cik,
            "form": self.form,
            "filing_date": self.filing_date,
            "accession": self.accession,
            "primary_document": self.primary_document,
            "primary_doc_description": self.primary_doc_description,
            "report_date": self.report_date,
            "url": self.url,
        }
        if self.items:
            d["items"] = self.items
        return d


@dataclass
class Company:
    cik: str          # zero-padded 10-digit string
    ticker: str
    name: str

    def to_dict(self) -> Dict[str, Any]:
        return {"cik": self.cik, "ticker": self.ticker, "name": self.name}


@dataclass
class Result:
    """A query result: a company plus the filings that matched the subcommand."""

    company: Company
    kind: str                       # filings|insiders|institutions|events
    filings: List[Filing] = field(default_factory=list)
    source: str = "live"            # live|demo

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool": TOOL_NAME,
            "version": TOOL_VERSION,
            "kind": self.kind,
            "source": self.source,
            "company": self.company.to_dict(),
            "count": len(self.filings),
            "filings": [f.to_dict() for f in self.filings],
        }


# --------------------------------------------------------------------------- #
# Fetch layer — network in live mode, on-disk cache in demo mode.
# --------------------------------------------------------------------------- #
class Fetcher:
    """Retrieves JSON resources for the engine.

    In *live* mode it performs real HTTP requests against SEC endpoints with the
    required User-Agent and a polite inter-request sleep. In *demo* mode it
    resolves a logical key ("tickers" or a CIK) from a cached JSON bundle so the
    rest of the engine runs unchanged and fully offline.
    """

    def __init__(
        self,
        mode: str = "live",
        cache: Optional[Dict[str, Any]] = None,
        user_agent: str = DEFAULT_USER_AGENT,
        sleep_seconds: float = SEC_RATE_LIMIT_SLEEP,
        opener=None,
    ) -> None:
        if mode not in ("live", "demo"):
            raise ValueError("mode must be 'live' or 'demo'")
        self.mode = mode
        self.cache = cache or {}
        self.user_agent = user_agent
        self.sleep_seconds = sleep_seconds
        self._opener = opener or urllib.request.urlopen
        self._last_request = 0.0

    # -- live HTTP --------------------------------------------------------- #
    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request
        wait = self.sleep_seconds - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    def _http_json(self, url: str) -> Any:
        self._throttle()
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept-Encoding": "gzip, deflate",
                "Host": urllib.request.urlsplit(url).netloc,
            },
        )
        try:
            with self._opener(req, timeout=30) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    import gzip
                    raw = gzip.decompress(raw)
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:  # pragma: no cover - network
            raise EdgarError(f"SEC returned HTTP {exc.code} for {url}") from exc
        except urllib.error.URLError as exc:  # pragma: no cover - network
            raise EdgarError(f"network error fetching {url}: {exc.reason}") from exc

    # -- public API -------------------------------------------------------- #
    def tickers(self) -> Any:
        if self.mode == "demo":
            if "tickers" not in self.cache:
                raise EdgarError("demo cache has no 'tickers' entry")
            return self.cache["tickers"]
        return self._http_json(TICKERS_URL)

    def submissions(self, cik10: str) -> Any:
        if self.mode == "demo":
            bucket = self.cache.get("submissions", {})
            if cik10 not in bucket:
                raise EdgarError(f"demo cache has no submissions for CIK {cik10}")
            return bucket[cik10]
        return self._http_json(SUBMISSIONS_URL.format(cik10=cik10))

    def fulltext(self, query: str, forms: str = "") -> Any:
        if self.mode == "demo":
            bucket = self.cache.get("fulltext", {})
            # Look up by exact query first, then a "*" catch-all, then any entry.
            if query in bucket:
                return bucket[query]
            if "*" in bucket:
                return bucket["*"]
            if bucket:
                return next(iter(bucket.values()))
            raise EdgarError("demo cache has no 'fulltext' entry")
        params = {"q": query}
        if forms:
            params["forms"] = forms
        url = FULLTEXT_BASE + "?" + urllib.parse.urlencode(params)
        return self._http_json(url)


# --------------------------------------------------------------------------- #
# Lookups and parsing.
# --------------------------------------------------------------------------- #
def normalize_cik(value: str) -> str:
    """Return a zero-padded 10-digit CIK string from '320193' or 'CIK0000320193'."""
    digits = re.sub(r"\D", "", str(value))
    if not digits:
        raise EdgarError(f"not a valid CIK: {value!r}")
    return digits.zfill(10)


def looks_like_cik(value: str) -> bool:
    v = str(value).strip()
    return bool(re.fullmatch(r"(?:CIK)?\d{1,10}", v, flags=re.IGNORECASE))


def resolve_company(identifier: str, fetcher: Fetcher) -> Company:
    """Resolve a ticker symbol OR a CIK to a Company via company_tickers.json."""
    ident = str(identifier).strip()
    if not ident:
        raise EdgarError("empty ticker/CIK")

    table = _index_tickers(fetcher.tickers())

    if looks_like_cik(ident):
        cik10 = normalize_cik(ident)
        by_cik = table["by_cik"].get(cik10)
        if by_cik:
            return by_cik
        # CIK not in the (subset) table — still usable for live submissions.
        return Company(cik=cik10, ticker="", name="")

    by_ticker = table["by_ticker"].get(ident.upper())
    if by_ticker:
        return by_ticker
    raise EdgarError(
        f"ticker {ident!r} not found in company_tickers.json "
        "(symbol may be delisted, foreign, or mistyped)"
    )


def _index_tickers(raw: Any) -> Dict[str, Dict[str, Company]]:
    """Build ticker/CIK indexes from company_tickers.json.

    The SEC file is an object keyed by row number with values
    ``{"cik_str": int, "ticker": str, "title": str}``. We also accept a list of
    such rows for resilience.
    """
    rows: List[Dict[str, Any]]
    if isinstance(raw, dict):
        rows = [v for v in raw.values() if isinstance(v, dict)]
    elif isinstance(raw, list):
        rows = [v for v in raw if isinstance(v, dict)]
    else:
        raise EdgarError("unexpected company_tickers.json shape")

    by_ticker: Dict[str, Company] = {}
    by_cik: Dict[str, Company] = {}
    for row in rows:
        if "cik_str" not in row or "ticker" not in row:
            continue
        cik10 = normalize_cik(str(row["cik_str"]))
        comp = Company(
            cik=cik10,
            ticker=str(row["ticker"]).upper(),
            name=str(row.get("title", "")),
        )
        by_ticker[comp.ticker] = comp
        by_cik.setdefault(cik10, comp)
    return {"by_ticker": by_ticker, "by_cik": by_cik}


def _recent_filings(submissions: Any, cik10: str) -> List[Filing]:
    """Flatten the columnar ``filings.recent`` table into Filing objects."""
    if not isinstance(submissions, dict):
        raise EdgarError("unexpected submissions JSON shape")
    recent = (((submissions.get("filings") or {}).get("recent")) or {})
    forms = recent.get("form") or []
    dates = recent.get("filingDate") or []
    accns = recent.get("accessionNumber") or []
    docs = recent.get("primaryDocument") or []
    descs = recent.get("primaryDocDescription") or []
    reports = recent.get("reportDate") or []
    items = recent.get("items") or []

    out: List[Filing] = []
    for i, form in enumerate(forms):
        out.append(
            Filing(
                cik=cik10,
                form=str(form),
                filing_date=_at(dates, i),
                accession=_at(accns, i),
                primary_document=_at(docs, i),
                primary_doc_description=_at(descs, i),
                report_date=_at(reports, i),
                items=_at(items, i),
            )
        )
    return out


def _at(seq: List[Any], i: int) -> str:
    return str(seq[i]) if i < len(seq) and seq[i] is not None else ""


# --------------------------------------------------------------------------- #
# Full-text search (efts.sec.gov) parsing.
# --------------------------------------------------------------------------- #
_CIK_RE = re.compile(r"CIK\s*(\d{1,10})", re.IGNORECASE)


@dataclass
class FullTextHit:
    """A single hit from EDGAR full-text search."""

    accession: str
    form: str
    file_date: str
    display_name: str
    cik: str = ""
    document: str = ""

    @property
    def url(self) -> str:
        acc_nodash = self.accession.replace("-", "")
        if not acc_nodash:
            return "https://efts.sec.gov/LATEST/search-index"
        try:
            cik_int = str(int(self.cik)) if self.cik else ""
        except ValueError:
            cik_int = ""
        base = "https://www.sec.gov/Archives/edgar/data"
        if cik_int:
            tail = self.document or ""
            return f"{base}/{cik_int}/{acc_nodash}/{tail}"
        # No CIK: link to the filing-index search as a graceful fallback.
        return f"{base}/{acc_nodash}/"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "accession": self.accession,
            "form": self.form,
            "file_date": self.file_date,
            "display_name": self.display_name,
            "cik": self.cik,
            "url": self.url,
        }


@dataclass
class FullTextResult:
    query: str
    forms: str = ""
    hits: List[FullTextHit] = field(default_factory=list)
    total: int = 0
    total_is_estimate: bool = False
    source: str = "live"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool": TOOL_NAME,
            "version": TOOL_VERSION,
            "kind": "fulltext",
            "source": self.source,
            "query": self.query,
            "forms": self.forms,
            "total": self.total,
            "total_is_estimate": self.total_is_estimate,
            "count": len(self.hits),
            "hits": [h.to_dict() for h in self.hits],
        }


def parse_fulltext_hits(payload: Any, limit: int = 20) -> List[FullTextHit]:
    """Parse an efts.sec.gov full-text-search JSON payload into FullTextHit list.

    Defensive about missing keys and alternate field names (``ciks``/``adsh``
    are preferred over parsing the display name when present).
    """
    if not isinstance(payload, dict):
        return []
    hits_obj = payload.get("hits") or {}
    rows = hits_obj.get("hits") or []
    out: List[FullTextHit] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        src = row.get("_source") or {}
        _id = str(row.get("_id") or "")
        accession = src.get("adsh") or (_id.split(":", 1)[0] if ":" in _id else _id)
        document = _id.split(":", 1)[1] if ":" in _id else ""

        names = src.get("display_names") or []
        display_name = str(names[0]) if names else ""

        # Prefer the structured ``ciks`` list; fall back to the display name.
        ciks = src.get("ciks") or []
        cik = str(ciks[0]) if ciks else ""
        if not cik and display_name:
            m = _CIK_RE.search(display_name)
            if m:
                cik = m.group(1)

        root_forms = src.get("root_forms") or []
        form = str(src.get("form") or (root_forms[0] if root_forms else ""))
        file_date = str(src.get("file_date") or "")

        out.append(
            FullTextHit(
                accession=str(accession),
                form=form,
                file_date=file_date,
                display_name=display_name,
                cik=cik,
                document=document,
            )
        )
        if limit and limit > 0 and len(out) >= limit:
            break
    return out


def _fulltext_total(payload: Any) -> tuple:
    """Return (total:int, is_estimate:bool) from an efts payload."""
    if not isinstance(payload, dict):
        return (0, False)
    total = ((payload.get("hits") or {}).get("total")) or {}
    if isinstance(total, dict):
        val = total.get("value")
        rel = total.get("relation")
        try:
            return (int(val), rel == "gte")
        except (TypeError, ValueError):
            return (0, False)
    try:
        return (int(total), False)
    except (TypeError, ValueError):
        return (0, False)


# --------------------------------------------------------------------------- #
# Engine — the public query surface.
# --------------------------------------------------------------------------- #
class Edgar:
    """High-level EDGAR query engine. Mode is determined by its Fetcher."""

    def __init__(self, fetcher: Optional[Fetcher] = None) -> None:
        self.fetcher = fetcher or Fetcher(mode="live")

    @classmethod
    def live(
        cls,
        user_agent: str = DEFAULT_USER_AGENT,
        sleep_seconds: float = SEC_RATE_LIMIT_SLEEP,
    ) -> "Edgar":
        return cls(Fetcher(mode="live", user_agent=user_agent,
                           sleep_seconds=sleep_seconds))

    @classmethod
    def demo(cls, cache: Optional[Dict[str, Any]] = None) -> "Edgar":
        return cls(Fetcher(mode="demo", cache=cache if cache is not None
                           else load_sample_cache()))

    # -- core query -------------------------------------------------------- #
    def _query(
        self,
        identifier: str,
        kind: str,
        forms: Optional[tuple],
        limit: int,
    ) -> Result:
        company = resolve_company(identifier, self.fetcher)
        subs = self.fetcher.submissions(company.cik)
        # Enrich company name from submissions if the tickers table lacked it.
        if not company.name and isinstance(subs, dict) and subs.get("name"):
            company.name = str(subs["name"])
        if not company.ticker and isinstance(subs, dict):
            tickers = subs.get("tickers") or []
            if tickers:
                company.ticker = str(tickers[0]).upper()

        filings = _recent_filings(subs, company.cik)
        if forms is not None:
            allowed = {f.upper() for f in forms}
            filings = [f for f in filings if f.form.upper() in allowed]
        if limit and limit > 0:
            filings = filings[:limit]
        return Result(company=company, kind=kind, filings=filings,
                      source=self.fetcher.mode)

    def filings(self, identifier: str, limit: int = 20) -> Result:
        return self._query(identifier, "filings", None, limit)

    def insiders(self, identifier: str, limit: int = 20) -> Result:
        return self._query(identifier, "insiders", INSIDER_FORMS, limit)

    def institutions(self, identifier: str, limit: int = 20) -> Result:
        return self._query(identifier, "institutions", INSTITUTION_FORMS, limit)

    def events(self, identifier: str, limit: int = 20) -> Result:
        return self._query(identifier, "events", EVENT_FORMS, limit)

    def fulltext(self, query: str, limit: int = 20, forms: str = "") -> FullTextResult:
        query = (query or "").strip()
        if not query:
            raise EdgarError("empty full-text query")
        payload = self.fetcher.fulltext(query, forms=forms)
        hits = parse_fulltext_hits(payload, limit=limit)
        total, est = _fulltext_total(payload)
        return FullTextResult(
            query=query,
            forms=forms,
            hits=hits,
            total=total,
            total_is_estimate=est,
            source=self.fetcher.mode,
        )


# --------------------------------------------------------------------------- #
# Sample cache for offline demo / tests.
# --------------------------------------------------------------------------- #
def sample_cache_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample_cache.json")


def load_sample_cache(path: Optional[str] = None) -> Dict[str, Any]:
    path = path or sample_cache_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except OSError as exc:
        raise EdgarError(f"could not load sample cache: {exc}") from exc
