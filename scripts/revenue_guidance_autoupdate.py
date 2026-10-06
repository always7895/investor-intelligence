#!/usr/bin/env python3
"""Updater of ORDERS-V3-AUTOUPDATE-01 (docs/REVENUE_GUIDANCE_AUTOUPDATE.md), Part A: discovery, capture and machine
verification of new results releases into the runtime state root; no publication, no registry or config write.

For each enabled issuer: admit its chain (the same admission readers use), list the material documents ever reported
for the effective record's reference by the release checker (plus detections recorded earlier) that the record did not
consume, and when one is an EDGAR results filing (8-K item 2.02) that no attempt has settled: record the detection
(a generation is committed before anything is fetched), capture from EDGAR the submissions feed, the accession
index, every HTML document of the filing, the periodic filings of the quarters the successor needs, the newest 10-K
and newest periodic report, plus the issuer's official IR page and the wire copy listed for that day, run the pure
verifier and append the attempt (VERIFIED / WAITING / BLOCKED) to a new immutable generation.

Network: public HTTPS GET only, hosts and paths bound to the issuer's reviewed profile, no redirects, each
connection made to the address that was checked to be public, SEC contact headers sent only to SEC hosts, bodies
read under per-kind caps, bounded retries, per-issuer and per-run request budgets, a wall-clock budget and pacing. A
later ordinary run retries WAITING outcomes; BLOCKED outcomes are deterministic and are not re-fetched."""
from __future__ import annotations

import argparse
import gzip
import http.client
import ipaddress
import json
import os
import re
import secrets
import socket
import ssl
import sys
import time
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import revenue_guidance_auto_verify as verify  # noqa: E402
import revenue_guidance_overlay as overlay  # noqa: E402

PROFILES_PATH = ROOT / "config" / "revenue-guidance-extraction-profiles-v1.json"
REGISTRY_PATH = ROOT / "config" / "revenue-guidance-v1.json"
APPROVAL_PATH = ROOT / "config" / "revenue-guidance-approval-v1.json"
RECEIPTS_PATH = ROOT / "data" / "cache" / "revenue_guidance_release_checks.json"

SEC_HOSTS = {"www.sec.gov", "data.sec.gov"}
WIRE_HOST = "www.nasdaq.com"
PUBLIC_USER_AGENT = "Mozilla/5.0 (InvestorIntelligence public observation)"
CAPS = {"submissions": 8 * 1024 * 1024, "index": 1024 * 1024, "document": 16 * 1024 * 1024,
        "ir_page": 4 * 1024 * 1024, "wire_page": 4 * 1024 * 1024}
CONTENT_TYPES = {"submissions": ("application/json",), "index": ("application/json",),
                 "document": ("text/html", "application/xhtml+xml"), "ir_page": ("text/html",), "wire_page": ("text/html",)}
ERROR_BODY_CAP = 64 * 1024
REQUEST_TIMEOUT = 30
MAX_ATTEMPTS = 2
PER_ISSUER_REQUESTS = 24
PER_RUN_REQUESTS = 120
RUN_BUDGET_SECONDS = 600
PACING_SECONDS = 0.5
MAX_RETRY_AFTER = 30
CYCLE_CAPTURE_BYTES = 128 * 1024 * 1024
STORE_QUOTA_BYTES = 2 * 1024 * 1024 * 1024
# Network failures that a later ordinary run can overcome (as opposed to a refused resource).
RETRYABLE = ("RUN_BUDGET", "RUN_REQUEST_BUDGET", "ISSUER_REQUEST_BUDGET", "TRANSIENT", "UNREACHABLE", "DNS")
STATE_ENTRIES = {"captures", "generations", "segments", "current.json", "queue.json", "lock", "store_usage.json"}
TEMP_ENTRY_RE = re.compile(r"^(current|queue|store_usage)\.json\.tmp-\d+$")  # an interrupted atomic write


class SystemicFailure(Exception):
    """Integrity, lock or persistence failure: the run stops and exits nonzero."""


class NetworkBlocked(Exception):
    """A request that cannot complete within the rules (typed per issuer, never a crash of the whole run)."""


class _Transient(Exception):
    def __init__(self, retry_after: int):
        super().__init__(retry_after)
        self.retry_after = retry_after


def now_instant(clock: Callable[[], datetime]) -> str:
    return clock().astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------------------------------------------------ transport

def url_rule(url: str, profile: Mapping[str, Any]) -> str:
    """The kind of an allowed URL for this issuer's profile; anything else refuses."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or parts.username or parts.password or parts.port not in (None, 443) or parts.fragment or parts.query:
        raise NetworkBlocked(f"URL_SHAPE {url[:120]}")
    host, path, cik = parts.hostname or "", parts.path, profile["cik"]
    if "%" in path or "\\" in path or "/./" in path or "/../" in path or path.endswith(("/..", "/.")):
        raise NetworkBlocked("PATH_ENCODING")
    if host == "data.sec.gov" and path == f"/submissions/CIK{cik:010d}.json":
        return "submissions"
    m = re.fullmatch(rf"/Archives/edgar/data/{cik}/([0-9]{{18}})/([A-Za-z0-9][A-Za-z0-9._-]{{0,119}})", path)
    if host == "www.sec.gov" and m:
        return "index" if m.group(2) == "index.json" else "document"
    if host == profile["ir_host"] and re.fullmatch(profile["ir_page_pattern"], url):
        return "ir_page"
    if host == WIRE_HOST and re.fullmatch(profile["wire_page_pattern"], url):
        return "wire_page"
    raise NetworkBlocked(f"URL {host} {path[:100]}")


def _public_resolver(host: str) -> list[str]:
    return [info[4][0] for info in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)]


class _PinnedHTTPS(http.client.HTTPSConnection):
    """TLS to the host name (certificate and SNI checked) over a socket to the one address already validated."""

    def __init__(self, host: str, address: str, timeout: float):
        super().__init__(host, 443, timeout=timeout, context=ssl.create_default_context())
        self.address = address

    def connect(self) -> None:
        sock = socket.create_connection((self.address, 443), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _Response:
    def __init__(self, connection: http.client.HTTPSConnection, response: http.client.HTTPResponse):
        self.connection, self.response = connection, response
        self.status = response.status
        self.headers = {k.lower(): v for k, v in response.getheaders()}

    def read(self, n: int) -> bytes:
        return self.response.read(n)

    def close(self) -> None:
        self.connection.close()


def _connect(host: str, address: str, path: str, headers: Mapping[str, str], timeout: float) -> Any:
    connection = _PinnedHTTPS(host, address, timeout)
    connection.request("GET", path, headers=dict(headers))
    return _Response(connection, connection.getresponse())


class Transport:
    """Bounded public GET; no proxies, no redirects, every request counted and paced."""

    def __init__(self, sec_headers: Mapping[str, str], connector: Callable[..., Any] = _connect,
                 resolver: Callable[[str], list[str]] = _public_resolver, sleep: Callable[[float], None] = time.sleep,
                 monotonic: Callable[[], float] = time.monotonic):
        self.sec_headers = dict(sec_headers)
        self.connector, self.resolver, self.sleep, self.monotonic = connector, resolver, sleep, monotonic
        self.started = monotonic()
        self.requests = 0
        self.issuer_requests: dict[str, int] = {}
        self.last = -PACING_SECONDS
        self.lease = None

    def bind_capability(self, store):
        if (type(self) is not Transport or self.connector is not _connect or self.resolver is not _public_resolver
                or self.sleep is not time.sleep or self.monotonic is not time.monotonic):
            raise SystemicFailure("CAPABILITY_TRANSPORT_REQUIRED")
        store.require_live()
        self.lease = store.lease
        self.started = max(self.started, self.lease.budget.start_time)
        if not hasattr(self.lease, "_network_work"):
            self.lease._network_work = {"requests": 0, "bytes": 0, "last": -PACING_SECONDS, "issuers": {}}

    def account_bytes(self, count):
        if self.lease is not None:
            work = self.lease._network_work
            work["bytes"] += count
            if work["bytes"] > CYCLE_CAPTURE_BYTES:
                raise NetworkBlocked("RUN_CAPTURE_BUDGET")

    def remaining(self):
        deadline = self.started + RUN_BUDGET_SECONDS
        if self.lease is not None:
            self.lease.budget._check_time()
            deadline = min(deadline, self.lease.budget.deadline)
        left = deadline - self.monotonic()
        if left <= 0:
            raise NetworkBlocked("RUN_BUDGET")
        return left

    def _address(self, host: str) -> str:
        try:
            addresses = self.resolver(host)
        except OSError as error:
            raise NetworkBlocked(f"DNS {host}") from error
        if not addresses or not all(ipaddress.ip_address(a).is_global for a in addresses):
            raise NetworkBlocked(f"ADDRESS {host}")
        return addresses[0]

    def _budget(self, symbol: str) -> None:
        self.remaining()
        work = self.lease._network_work if self.lease is not None else None
        requests = work["requests"] if work is not None else self.requests
        issuers = work["issuers"] if work is not None else self.issuer_requests
        if requests >= PER_RUN_REQUESTS:
            raise NetworkBlocked("RUN_REQUEST_BUDGET")
        if issuers.get(symbol, 0) >= PER_ISSUER_REQUESTS:
            raise NetworkBlocked("ISSUER_REQUEST_BUDGET")
        last = work["last"] if work is not None else self.last
        wait = PACING_SECONDS - (self.monotonic() - last)
        if wait > 0:
            if wait >= self.remaining():
                raise NetworkBlocked("RUN_BUDGET")
            self.sleep(wait)
        self.remaining()
        self.last = self.monotonic()
        if work is not None:
            work["requests"] += 1
            work["issuers"][symbol] = work["issuers"].get(symbol, 0) + 1
            work["last"] = self.last
        self.requests += 1
        self.issuer_requests[symbol] = self.issuer_requests.get(symbol, 0) + 1

    def get(self, url: str, profile: Mapping[str, Any], symbol: str) -> tuple[bytes, str]:
        kind = url_rule(url, profile)
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname or ""
        headers = dict(self.sec_headers) if host in SEC_HOSTS else {"User-Agent": PUBLIC_USER_AGENT}
        headers.update({"Accept-Encoding": "identity", "Host": host})
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                address = self._address(host)
                self._budget(symbol)
                response = self.connector(host, address, parts.path, headers, min(REQUEST_TIMEOUT, self.remaining()))
                try:
                    status = response.status
                    if 300 <= status < 400:
                        raise NetworkBlocked(f"REDIRECT {status}")  # sources are addressed exactly; nothing is followed
                    if status == 429 or status >= 500:
                        response.read(ERROR_BODY_CAP)
                        retry_after = str(response.headers.get("retry-after", ""))
                        raise _Transient(int(retry_after) if retry_after.isdigit() else 2)
                    if status != 200:
                        response.read(ERROR_BODY_CAP)
                        raise NetworkBlocked(f"HTTP {status}")
                    encoding = str(response.headers.get("content-encoding") or "identity").lower()
                    ctype = str(response.headers.get("content-type") or "").split(";")[0].strip().lower()
                    if encoding != "identity":
                        raise NetworkBlocked(f"ENCODING {encoding}")
                    if ctype not in CONTENT_TYPES[kind]:
                        raise NetworkBlocked(f"CONTENT_TYPE {ctype}")
                    chunks, total = [], 0
                    while True:
                        chunk = response.read(65536)
                        if not chunk:
                            break
                        total += len(chunk)
                        self.account_bytes(len(chunk))
                        if total > CAPS[kind]:
                            raise NetworkBlocked(f"CAP {kind}")
                        self.remaining()
                        chunks.append(chunk)
                    return b"".join(chunks), ctype
                finally:
                    response.close()
            except _Transient as transient:
                if attempt == MAX_ATTEMPTS or transient.retry_after > MAX_RETRY_AFTER:
                    raise NetworkBlocked("TRANSIENT") from None
                if transient.retry_after >= self.remaining():
                    raise NetworkBlocked("RUN_BUDGET")
                self.sleep(transient.retry_after)
            except (OSError, http.client.HTTPException) as error:
                if attempt == MAX_ATTEMPTS:
                    raise NetworkBlocked(f"UNREACHABLE {type(error).__name__}") from None
                if 2 >= self.remaining():
                    raise NetworkBlocked("RUN_BUDGET")
                self.sleep(2)
        raise NetworkBlocked("UNREACHABLE")


class ReplayTransport:
    """Hermetic replay from a capture directory ({inventory.json, raw/<sha256>[.gz]}): the same URL rules, no network."""

    replay = True

    def __init__(self, replay_dir: Path):
        self.dir = replay_dir
        rows = json.loads((replay_dir / "inventory.json").read_text(encoding="utf-8"))
        self.by_url = {r["url"]: r for r in rows}

    def get(self, url: str, profile: Mapping[str, Any], symbol: str) -> tuple[bytes, str]:
        kind = url_rule(url, profile)
        row = self.by_url.get(url)
        if row is None:
            raise NetworkBlocked("REPLAY_MISSING")
        plain = self.dir / "raw" / row["sha256"]
        if plain.exists():
            data = plain.read_bytes()
        else:
            with gzip.open(plain.with_name(row["sha256"] + ".gz"), "rb") as handle:
                data = handle.read(CAPS[kind] + 1)
        if len(data) > CAPS[kind]:
            raise NetworkBlocked(f"CAP {kind}")
        if verify.sha256(data) != row["sha256"]:
            raise SystemicFailure("REPLAY_BYTES")
        return data, CONTENT_TYPES[kind][0]


# ------------------------------------------------------------------------------------------------ lock

class StateLock:
    """An operating-system lock on <root>/lock (released by the OS if the process dies)."""

    def __init__(self, root: Path):
        root.mkdir(parents=True, exist_ok=True)
        self.handle = open(root / "lock", "a+b")
        try:
            if os.name == "nt":
                import msvcrt
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self.handle.close()
            raise SystemicFailure("LOCKED") from error

    def release(self) -> None:
        try:
            if os.name == "nt":
                import msvcrt
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            self.handle.close()


# ------------------------------------------------------------------------------------------------ discovery

def reference_accession(record: Mapping[str, Any]) -> str | None:
    ref, _ = overlay.reference(record)
    doc = next((d for d in record.get("documents") or [] if d.get("id") == ref), None)
    m = re.search(r"/Archives/edgar/data/\d+/(\d{18})/", str((doc or {}).get("url", "")))
    return verify.dashed(m.group(1)) if m else None


def candidate_events(documents: list[Mapping[str, Any]], ref_accession: str | None, profile: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Results filings (8-K item 2.02) listed after the reference, oldest first; the same-day official IR and wire
    items whose titles name a results release are leads for the verifier's content check."""
    events = []
    for item in documents:
        if item.get("channel") != "SEC_SUBMISSIONS" or item.get("id") == ref_accession or item.get("disposition") not in overlay.MATERIAL:
            continue
        nbis = profile["adapter"] == verify.NBIS_6K_TABLE_REAFFIRMATION_V1
        if nbis:
            # REVIEW_REQUIRED / POSSIBLY_RELEVANT is an inspection lead, not
            # fabricated 8-K item metadata or a results classification.
            if not re.fullmatch(r"6-K(?: items [0-9.,]+)?", str(item.get("label", ""))):
                continue
        else:
            m = re.fullmatch(r"8-K items ([0-9.,]+)", str(item.get("label", "")))
            if not m or "2.02" not in m.group(1).split(","):
                continue

        def lead(channel: str, pattern: str) -> dict[str, str] | None:
            same = [x for x in documents if x.get("channel") == channel and x.get("date") == item.get("date")
                    and re.fullmatch(pattern, str(x.get("label", "")))]
            return {"id": same[0]["id"], "title": same[0]["label"], "date": same[0]["date"]} if len(same) == 1 else None
        event = {"accession": item["id"], "filed": item["date"],
                 "ir_item": lead("ISSUER_IR", profile["ir_title_pattern"]),
                 "wire_item": lead("WIRE_PRESS_RELEASES", profile["wire_title_pattern"]), "later_documents": []}
        event.update({"adapter": profile["adapter"], "packages": [], "channel_history": []} if nbis else
                     {"periodic": {}, "calendar": None, "allocation_sources": []})
        events.append(event)
    return sorted(events, key=lambda e: (e["filed"], e["accession"]))


def read_queue(root: Path) -> dict[str, Any]:
    """The fair-queue position; unreadable or foreign content only resets the order (it is not an admission input)."""
    try:
        data = json.loads((root / "queue.json").read_text(encoding="utf-8"))
        if isinstance(data, dict) and set(data) == {"last_served"} and (data["last_served"] is None or isinstance(data["last_served"], str)):
            return data
    except (OSError, ValueError):
        pass
    return {"last_served": None}


def write_queue(root: Path, queue: Mapping[str, Any]) -> None:
    try:
        overlay._durable_write(root / "queue.json", json.dumps({"last_served": queue.get("last_served")}).encode("utf-8"))
    except OSError as error:
        raise SystemicFailure(f"QUEUE {type(error).__name__}") from error


def archive_captures(root: Path, attempts: list[Mapping[str, Any]]) -> dict[str, str]:
    """URL -> raw digest of stored EDGAR archive captures referenced by the given attempts (the open attempts and the
    admitted producers: bounded). Accession-bound documents never change; reuse re-hashes them and the verifier
    re-verifies them. Feeds, IR and wire pages are always fetched again."""
    out: dict[str, str] = {}
    for a in attempts:
        for raw_sha in (a.get("captures") or {}).values():
            try:
                meta = overlay.load_capture(root, raw_sha)
            except (OSError, ValueError, overlay.StateError):
                continue
            url = str(meta.get("url", ""))
            if url.startswith("https://www.sec.gov/Archives/edgar/data/"):
                out[url] = raw_sha
    return out


def plan_event(transport: Any, root: Path, profile: Mapping[str, Any], lead: Mapping[str, Any], today: str,
               clock: Callable[[], datetime], budget: dict[str, int], reuse: Mapping[str, str] | None = None,
               captures: dict[str, str] | None = None) -> tuple[dict[str, Any], dict[str, str]]:
    """SEC_8K_202_INLINE_XBRL_V1: capture what the verifier needs for this event; returns (event for the verifier,
    {capture key: raw sha}). The caller's `captures` map is filled as each document is stored, so an interrupted plan
    still records what it captured (a later retry reuses it). Stored EDGAR archive documents are reused (re-hashed),
    not fetched again; feeds and IR/wire pages are always fetched again."""
    cik, sym = profile["cik"], profile["symbol"]
    captures = {} if captures is None else captures

    def fetch(key: str, url: str, role: str) -> bytes:
        if reuse and url in reuse:
            try:
                captures[key] = reuse[url]
                return overlay.load_capture(root, reuse[url])["raw"]
            except overlay.StateError:
                del captures[key]
        data, ctype = transport.get(url, profile, sym)
        budget["bytes"] += len(data)
        if budget["bytes"] > CYCLE_CAPTURE_BYTES:
            raise verify.Blocked("WAITING", "CAPTURE_LIMIT", "RUN_CAPTURE_BUDGET")
        if budget["store"] is None:
            raise verify.Blocked("WAITING", "CAPTURE_LIMIT", "store accounting unknown (--recount-store)")
        if budget["store"] + budget["bytes"] > STORE_QUOTA_BYTES:
            raise verify.Blocked("WAITING", "CAPTURE_LIMIT", "store quota")
        if getattr(transport, "replay", False):
            role = "REPLAY_" + role
        captures[key] = overlay.store_capture(root, data, {"url": url, "retrieved_at": now_instant(clock), "content_type": ctype, "role": role})
        return data

    filings = verify.parse_submissions(fetch("submissions", f"https://data.sec.gov/submissions/CIK{cik:010d}.json", "SEC_SUBMISSIONS"), cik)
    acc = lead["accession"]
    filing = filings.get(acc)
    if filing is None or filing.form != "8-K" or "2.02" not in filing.items or filing.filed != lead["filed"]:
        raise verify.Blocked("BLOCKED", "EVENT_UNRESOLVED", "accession is not this issuer's item 2.02 filing on that day")
    base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}"
    names = verify.parse_index(fetch("index", base + "/index.json", "SEC_INDEX"))
    exhibits = [n for n in names if re.search(profile["release"]["exhibit_name_pattern"], n)]
    if len(exhibits) != 1:
        raise verify.Blocked("BLOCKED", "UNSUPPORTED_TEMPLATE" if not exhibits else "AMBIGUOUS", f"{len(exhibits)} release exhibits")
    exhibit_raw = fetch("exhibit", f"{base}/{exhibits[0]}", "RELEASE_EXHIBIT")
    package = verify.package_names(names)
    if len(package) > verify.MAX_PACKAGE_DOCUMENTS:
        raise verify.Blocked("BLOCKED", "CAPTURE_LIMIT", f"{len(package)} documents in the results filing")
    for name in package:
        if name != exhibits[0]:
            fetch(f"package:{name}", f"{base}/{name}", "RESULTS_PACKAGE")
    # Which quarters are needed follows from the release's own guided period (the verifier re-derives it).
    rule = profile["calendar"]["rule"]
    needed: set[str] = set()
    try:
        report = verify.a1_report_period(verify.extract_guidance(verify.parse_document(exhibit_raw), profile), profile)
        aq, afy = report["quarter"], report["fiscal_year"]
        for q, fy in [verify.next_quarter(aq, afy, -k) for k in (3, 2, 1, 0)]:
            needed.add(verify.fiscal_quarter(rule, fy, q)[1].isoformat())
            if q == 4:
                needed.add(verify.fiscal_quarter(rule, fy, 3)[1].isoformat())
    except verify.Blocked:
        pass  # the verifier returns the extraction outcome from the exhibit alone
    periodic: dict[str, str] = {}
    usable = [f for f in filings.values() if f.form in ("10-Q", "10-K") and f.filed <= today]

    def fetch_periodic(f: verify.Filing) -> None:
        if f.accession not in captures:
            fetch(f.accession, f"https://www.sec.gov/Archives/edgar/data/{cik}/{f.accession.replace('-', '')}/{f.primary}", "PERIODIC_FILING")

    for end in sorted(needed):
        match = [f for f in usable if f.report == end]
        if len(match) > 1:
            raise verify.Blocked("BLOCKED", "AMBIGUOUS", f"{len(match)} periodic filings for {end}")
        if match:
            fetch_periodic(match[0])
            periodic[end] = match[0].accession
    tenks = sorted((f for f in usable if f.form == "10-K"), key=lambda f: (f.filed, f.accession))
    calendar = None
    if tenks:
        fetch_periodic(tenks[-1])
        calendar = tenks[-1].accession
    allocation = []
    if usable:
        newest = max(usable, key=lambda f: (f.filed, f.accession))
        fetch_periodic(newest)
        allocation.append(newest.accession)
    # The official IR page is required (the verifier waits without it); the wire copy is optional.
    if lead["ir_item"]:
        fetch("ir_copy", lead["ir_item"]["id"], "IR_RELEASE_PAGE")
    if lead["wire_item"]:
        try:
            fetch("wire_copy", lead["wire_item"]["id"], "WIRE_RELEASE_PAGE")
        except NetworkBlocked as error:
            if str(error).startswith(RETRYABLE):
                raise  # a budget or transient failure waits for the next run instead of giving up the copy
            # a refused page (for example HTTP 404) is simply not consumed; it keeps the issuer suspended if it is listed
    event = dict(lead, periodic=periodic, calendar=calendar, allocation_sources=allocation)
    return event, captures


# ------------------------------------------------------------------------------------------------ run

def plan_nbis_event(transport, root, profile, lead, today, clock, budget, reuse=None, captures=None):
    """Report-body-driven 6-K planning on the SAME held B1Store/transport.

    Captures are charged/stored immediately and survive any interruption. Archive
    reuse rechecks original metadata/bytes; feeds/channel pages are never reused.
    No predecessor financial values, inferred report month or generated filenames.
    """
    captures = {} if captures is None else captures
    event = dict(lead, adapter=verify.NBIS_6K_TABLE_REAFFIRMATION_V1, packages=[], channel_history=[])
    cik, sym = profile["cik"], profile["symbol"]

    def fetch(key, url, role):
        # An alias occupies this attempt's slot even if the raw bytes are cached.
        # Admission BEFORE either branch: no request/persist/assignment on a full
        # domain, no clipping of already accumulated original witnesses.
        if key not in captures and len(captures) >= 32:
            raise verify.Blocked("WAITING", "CAPTURE_LIMIT", "NBIS capture domain")
        if reuse and url in reuse:
            try:
                cap = overlay.load_capture(root, reuse[url])
                if (cap["url"] == url and cap["role"] in (role, "REPLAY_" + role)
                        and verify.revenue_guidance.parse_instant(cap["retrieved_at"]) is not None
                        and cap["retrieved_at"] <= now_instant(clock)):
                    captures[key] = reuse[url]
                    return cap["raw"]
            except overlay.StateError:
                pass
        data, content_type = transport.get(url, profile, sym)
        budget["bytes"] += len(data)
        if budget["bytes"] > CYCLE_CAPTURE_BYTES:
            raise verify.Blocked("WAITING", "CAPTURE_LIMIT", "RUN_CAPTURE_BUDGET")
        if budget["store"] is None or budget["store"] + budget["bytes"] > STORE_QUOTA_BYTES:
            raise verify.Blocked("WAITING", "CAPTURE_LIMIT", "store accounting unknown or quota")
        role = "REPLAY_" + role if getattr(transport, "replay", False) else role
        captures[key] = overlay.store_capture(root, data, {"url": url, "retrieved_at": now_instant(clock),
                                              "content_type": content_type, "role": role})
        return data

    filings = verify.parse_submissions(fetch("submissions", f"https://data.sec.gov/submissions/CIK{cik:010d}.json",
                                             "SEC_SUBMISSIONS"), cik, foreign_items_absence=True)
    current = filings.get(lead["accession"])
    if current is None or current.form != "6-K" or current.filed != lead["filed"] or current.filed > today:
        raise verify.Blocked("BLOCKED", "EVENT_UNRESOLVED", "NBIS actual issuer/submissions 6-K lead")

    def package(filing, selected=False):
        base = f"{verify.SEC_ARCHIVES}{cik}/{filing.accession.replace('-', '')}/"
        prefix = "nbis:" + filing.accession + ":"
        names = verify.parse_index(fetch(prefix + "index", base + "index.json", "SEC_INDEX"))
        members = verify.nbis_members(names, filing.accession)
        statements = [n for n in members if re.fullmatch(profile["release"]["statement_name_pattern"], n)]
        letters = [n for n in members if re.fullmatch(profile["release"]["letter_name_pattern"], n)]
        if len(statements) != 1 or len(letters) != 1 or filing.primary not in members:
            if selected:
                raise verify.Blocked("BLOCKED", "EVENT_UNRESOLVED", "NBIS nonresults or unsupported whole package")
            return None  # not consumed, remains in the material detection set
        mapping = {}
        for name in members:
            suffix = "form" if name == filing.primary else "statement" if name == statements[0] else "letter" if name == letters[0] else "member:" + name
            key = prefix + suffix
            data = fetch(key, base + name, verify.NBIS_ROLES[suffix if suffix in verify.NBIS_ROLES else "member"])
            verify._nbis_package_links(data, base + name)  # unknown operative formats fail closed
            mapping[name] = key
        statement_raw = overlay.load_capture(root, captures[mapping[statements[0]]])["raw"]
        _, values, end = verify.nbis_statement(statement_raw, filing.filed)
        form_raw = overlay.load_capture(root, captures[mapping[filing.primary]])["raw"]
        verify._nbis_form_report(verify.parse_document(form_raw), profile["company_name"], end)
        return ({"accession": filing.accession, "filed": filing.filed, "index": prefix + "index",
                 "form": mapping[filing.primary], "statement": mapping[statements[0]],
                 "letter": mapping[letters[0]], "members": mapping}, values, end)

    first = package(current, True)
    event["packages"].append(first[0])
    anchor = date.fromisoformat(first[2])
    needed = set()
    for step in (3, 2, 1, 0):
        q, year = verify.next_quarter(anchor.month // 3, anchor.year, -step)
        start, end = verify.nbis_quarter(year, q)
        needed.add((start.isoformat(), end.isoformat()))
        if q == 4:
            needed.update({(f"{year}-01-01", f"{year}-12-31"), (f"{year}-01-01", f"{year}-09-30")})
        if q == 1 and anchor >= date(year, 6, 30):
            needed.update({(f"{year}-01-01", f"{year}-06-30"), (f"{year}-04-01", f"{year}-06-30")})
    # Full-year calendar proof and the original guidance letter must be captured,
    # not inherited from a predecessor/oracle. Bounded historical candidates are
    # positively inspected using their form + statement periods.
    collected = list(first[1])
    candidates = sorted((f for f in filings.values() if f.form == "6-K" and f.filed <= current.filed
                          and f.accession != current.accession), key=lambda f: (f.filed, f.accession), reverse=True)
    for filing in candidates:
        intervals = {(o["start"], o["end"]) for o in collected}
        has_year = any(o["start"] == o["end"][:4] + "-01-01" and o["end"].endswith("-12-31") for o in collected)
        fy = (anchor + timedelta(days=1)).year
        has_original = any(f"{fy} Guidance update" in verify.parse_document(
            overlay.load_capture(root, captures[p["letter"]])["raw"]).text for p in event["packages"])
        if needed <= intervals and has_year and has_original:
            break
        if len(event["packages"]) >= 8:
            raise verify.Blocked("WAITING", "CAPTURE_LIMIT", "NBIS bounded historical package domain")
        candidate = package(filing)
        if candidate is not None:
            if candidate[2] > first[2]:
                raise verify.Blocked("BLOCKED", "OUT_OF_ORDER", "NBIS newer actual period in earlier filing")
            event["packages"].append(candidate[0])
            collected.extend(candidate[1])
    for p in event["packages"]:
        if p["accession"] == current.accession:
            continue
        for channel, suffix, role, pattern in (("ISSUER_IR", "ir_copy", "IR_RELEASE_PAGE", profile["ir_title_pattern"]),
                                                ("WIRE_PRESS_RELEASES", "wire_copy", "WIRE_RELEASE_PAGE", profile["wire_title_pattern"])):
            rows = [d for d in lead["later_documents"] if d["channel"] == channel and d["date"] == p["filed"]
                    and re.search(pattern, str(d.get("label", "")))]
            if len(rows) > 1:
                raise verify.Blocked("BLOCKED", "AMBIGUOUS", "NBIS historical channel item")
            if rows:
                d = rows[0]
                item = {"id": d["id"], "date": d["date"], "title": d["label"]}
                key = "nbis:" + p["accession"] + ":" + suffix
                fetch(key, item["id"], role)
                event["channel_history"].append({"accession": p["accession"], "channel": channel, "item": item, "capture": key})
    if lead["ir_item"] is not None:
        fetch("ir_copy", lead["ir_item"]["id"], "IR_RELEASE_PAGE")
    if lead["wire_item"] is not None:
        fetch("wire_copy", lead["wire_item"]["id"], "WIRE_RELEASE_PAGE")
    return event, captures


PLANNERS = {verify.SEC_8K_202_INLINE_XBRL_V1: plan_event,
            verify.NBIS_6K_TABLE_REAFFIRMATION_V1: plan_nbis_event}


def _new_generation_id(clock: Callable[[], datetime]) -> str:
    return f"{clock().astimezone(timezone.utc):%Y%m%dT%H%M%SZ}-{secrets.token_hex(6)}"


def _attempt(key: str, decided: str, effective: Mapping[str, Any], event: Mapping[str, Any], captures: Mapping[str, str],
             result: Mapping[str, Any]) -> dict[str, Any]:
    record = result["record"]
    nbis = event.get("adapter") == verify.NBIS_6K_TABLE_REAFFIRMATION_V1
    full_event = ({"adapter": verify.NBIS_6K_TABLE_REAFFIRMATION_V1, "accession": None, "filed": None,
                   "packages": [], "channel_history": [], "ir_item": None, "wire_item": None, "later_documents": []} if nbis else
                  {"accession": None, "filed": None, "periodic": {}, "calendar": None, "allocation_sources": [],
                   "ir_item": None, "wire_item": None, "later_documents": []})
    domain = verify.NBIS_EVENT_KEYS if nbis else overlay.EVENT_KEYS
    full_event.update({k: v for k, v in event.items() if k in domain})
    return {"event_key": key, "attempted_at": decided, "predecessor_sha256": overlay.record_sha256(effective),
            "event": full_event, "captures": dict(captures), "outcome": result["outcome"], "reason": result["reason"],
            "detail": str(result["detail"])[:300], "record_sha256": overlay.record_sha256(record) if record else None,
            "record": record, "decisions": result["decisions"]}


def _record(entry: dict[str, Any], new: dict[str, Any]) -> bool:
    """Append an attempt to an issuer's entry, superseding a trailing wait of the same event (a superseding wait keeps
    the captures already referenced, so interrupted plans accumulate progress); an identical wait changes nothing."""
    last = entry["open"][-1] if entry["open"] else None
    if last is not None and last["event_key"] == new["event_key"] and last["outcome"] == "WAITING":
        nbis = new["event"].get("adapter") == verify.NBIS_6K_TABLE_REAFFIRMATION_V1
        if new["outcome"] == "WAITING":
            merged = {**last["captures"], **new["captures"]}
            if nbis and len(merged) > 32:
                overlay.append_attempt(entry, new)  # retain BOTH bounded incomplete evidence sets, no silent clipping
                return True
            new = dict(new, captures=merged)
            if all(last[k] == new[k] for k in ("reason", "detail", "event", "captures")):
                return False
        if not nbis or new["outcome"] == "WAITING":
            entry["open"].pop()  # A1 unchanged; terminal NBIS preserves its interrupted raw-evidence predecessor
    overlay.append_attempt(entry, new)
    return True


def reverify(root: Path, profiles: Mapping[str, Mapping[str, Any]], curated: Mapping[str, Mapping[str, Any]],
             entries: dict[str, dict[str, Any]], readable: set[str], allow_replay: bool, now: str) -> None:
    """After a change of reviewed policy, code or baseline: re-derive each readable issuer's producer under the
    installed identity from its stored bytes (one per issuer). If it reproduces the stored decision nothing changes;
    otherwise a new decision is taken now from the same captures and appended (VERIFIED becomes the producer, anything
    else leaves the index so the verified attempt before it becomes the producer). Stored attempts and segments are
    never rewritten."""
    for sym in sorted(readable):
        entry = entries[sym]
        verified = entry["index"]["verified"]
        if sym not in profiles or curated.get(sym) is None or not verified:
            continue
        try:
            a = overlay.attempt_at(root, entry, verified[-1])
            if len(verified) > 1:
                previous = overlay.attempt_at(root, entry, verified[-2])["record"]
            elif entry["index"]["truncated"]:
                raise overlay.StateError("ATTEMPT_INDEX_EXHAUSTED")
            else:
                previous = curated[sym]
            again = overlay.rederive(root, profiles[sym], previous, a, allow_replay, curated[sym]) if a.get("captures") else None
        except (overlay.StateError, KeyError, TypeError, IndexError):
            readable.discard(sym)  # unreadable history: carried unchanged, admission blocks it
            continue
        if (again is not None and again["outcome"] == "VERIFIED" and verify.canonical_json(again["record"]) == verify.canonical_json(a["record"])
                and verify.canonical_json(again["decisions"]) == verify.canonical_json(a["decisions"])):
            continue
        if a.get("captures"):
            try:
                captures = {k: overlay.load_capture(root, v) for k, v in a["captures"].items()}
                result = verify.build_successor(profiles[sym], overlay.predecessor_view(previous, curated[sym]), a["event"], captures, now)
            except overlay.StateError as error:
                result = {"outcome": "BLOCKED", "reason": "APPROVAL_BINDING", "detail": str(error), "record": None, "decisions": []}
        else:
            result = {"outcome": "BLOCKED", "reason": "APPROVAL_BINDING", "detail": "verified attempt without captures", "record": None, "decisions": []}
        verified.pop()
        overlay.append_attempt(entry, _attempt(a["event_key"], now, previous, a["event"], a.get("captures") or {}, result))


def run(state_root: Path, transport: Any, clock: Callable[[], datetime], profiles_path: Path = PROFILES_PATH,
        registry_path: Path = REGISTRY_PATH, approval_path: Path = APPROVAL_PATH, receipts_path: Path = RECEIPTS_PATH) -> dict[str, Any]:
    """One cycle; the capability branch uses only its held control/B1 operands."""
    capability = type(state_root) is overlay.B1Store
    if capability:
        state_root.require_live()
        if (profiles_path, registry_path, approval_path, receipts_path) != (PROFILES_PATH, REGISTRY_PATH, APPROVAL_PATH, RECEIPTS_PATH):
            raise SystemicFailure("CAPABILITY_INPUT_SOURCE_CONFLICT")
        if type(transport) is not Transport or getattr(transport, "replay", False):
            raise SystemicFailure("CAPABILITY_TRANSPORT_REQUIRED")
        transport.bind_capability(state_root)
        profiles_bytes, registry_bytes, approval_bytes = (state_root.input(n) for n in ("profiles", "registry", "approval"))
        receipts_path = state_root / "receipts.json"
    else:
        profiles_bytes, registry_bytes, approval_bytes = profiles_path.read_bytes(), registry_path.read_bytes(), approval_path.read_bytes()
    profiles = {sym: prof for sym, prof in verify.validate_profiles(json.loads(profiles_bytes.decode("utf-8"))).items()
                if sym in overlay.SUPPORTED_AUTO}  # automatic mode is limited to the supported issuers (B1)
    curated = {r["symbol"]: r for r in json.loads(registry_bytes.decode("utf-8"))["issuers"]}
    try:
        receipts_raw = receipts_path.read_bytes() if receipts_path.exists() else None
        receipts = json.loads(receipts_raw.decode("utf-8")) if receipts_raw is not None else {"issuers": {}}
    except (OSError, ValueError) as error:
        raise SystemicFailure("RECEIPTS_UNREADABLE") from error
    replay = bool(getattr(transport, "replay", False))
    lock = None if capability else StateLock(state_root)
    try:
        now = now_instant(clock)
        try:
            pointer = overlay.read_pointer(state_root)
            base = overlay.read_generation(state_root, pointer["generation_id"], pointer["sha256"]) if pointer else None
        except overlay.StateError as error:
            raise SystemicFailure(f"STATE {error}") from error
        ident = overlay.identity(profiles_bytes, registry_bytes, approval_bytes, state_root)
        entries: dict[str, dict[str, Any]] = json.loads(json.dumps((base or {}).get("issuers", {})))  # a private copy
        readable: set[str] = set()
        for sym, entry in entries.items():
            try:
                overlay.validate_entry(entry)
                for a in entry["open"]:
                    overlay.validate_attempt(a)
                readable.add(sym)
            except overlay.StateError:
                pass  # carried unchanged as its own fail-closed barrier; admission blocks it and nothing is fetched for it
        detections: dict[str, dict[str, Any]] = json.loads(json.dumps((base or {}).get("detections", {})))
        # Phase 0 (B1): the shared discovery view at entry (the same snapshot the release checker used), from the inputs
        # read above and the pinned current generation. Material items listed for its discovery reference join the
        # monotonic detection set before any re-verification switches the reference or anything is fetched, so an item
        # collected during an identity change or while an issuer is unadmitted is never lost; only a currently
        # re-derived producer accounts for it later (phase 1).
        source_args = {} if capability else dict(registry_bytes=registry_bytes, approval_bytes=approval_bytes,
                    profiles_bytes=profiles_bytes, receipts_bytes=receipts_raw, receipts_path=receipts_path if receipts_raw is None else None)
        entry_view = overlay.load_effective_inputs(
            cutoff=now, state_root=state_root, **source_args,
            # the generation just read (unless the clock is behind it: then the loader walks to the one at `now`)
            expected_generation={"generation_id": pointer["generation_id"], "sha256": pointer["sha256"]}
            if pointer and base is not None and base["created_at"] <= now else None,
            allow_replay=replay)
        if entry_view.condition == "STATE_FAILURE":
            # Damaged state (a lost pointer or generations beside recognizable state, a foreign root, ...) is never
            # overwritten or re-initialized: stop before any detection, re-verification, capture or publication.
            raise SystemicFailure(f"STATE {entry_view.manifest['state']['error']}")
        entry_changed = False
        for sym in profiles:
            item = entry_view.issuer(sym)
            if item is None or item.discovery_record is None:
                continue
            ref = item.discovery_reference["document_id"] if item.discovery_reference else None
            seen = overlay.unaccounted(item.discovery_record, overlay.receipt_rows(receipts, sym, ref, now),
                                       item.producer if item.discovery_origin == "READMITTED_AUTO" else None, [])
            if not seen:
                continue
            store = detections.get(sym) or {"documents": [], "overflow": False}
            union = overlay._material_documents([{"later_documents": list(store["documents"]) + seen}])
            updated = {"documents": [{k: d[k] for k in overlay.LATER_KEYS} for d in union[:overlay.MAX_DETECTIONS]],
                       "overflow": store["overflow"] or len(union) > overlay.MAX_DETECTIONS}
            if updated != store:
                detections[sym] = updated
                entry_changed = True
        queue = read_queue(state_root)
        summary: dict[str, Any] = {"status": "OK", "at": now, "issuers": {}, "reverified": False}
        state = {"pointer": pointer, "changed": entry_changed}

        def publish() -> None:
            try:
                stored, written = {}, set()
                for s, entry in entries.items():
                    if s in readable and not (entry["head"] or entry["open"]):
                        continue  # nothing recorded for this issuer yet
                    if s in readable:
                        written.update(overlay.seal(state_root, entry))
                    stored[s] = entry
                gen = dict(ident, schema=overlay.STATE_SCHEMA, generation_id=_new_generation_id(clock),
                           parent=None if state["pointer"] is None else {"generation_id": state["pointer"]["generation_id"], "sha256": state["pointer"]["sha256"]},
                           created_at=now_instant(clock), issuers=stored, detections=dict(detections))
                digest = overlay.publish_generation(state_root, gen, state["pointer"], carried=frozenset(set(stored) - readable),
                                                    written=frozenset(written))
            except overlay.StateError as error:
                raise SystemicFailure(f"PUBLISH {error}") from error
            state["pointer"] = {"schema": overlay.POINTER_SCHEMA, "generation_id": gen["generation_id"], "sha256": digest}
            summary["generation_id"] = gen["generation_id"]
            state["changed"] = False

        if base is not None and any(base[k] != ident[k] for k in overlay.IDENTITY_KEYS):
            reverify(state_root, profiles, curated, entries, readable, replay, now)  # new reviewed policy, code or baseline
            summary["reverified"] = True
            state["changed"] = True
        virtual = dict(ident, generation_id=None, issuers=entries, detections=detections)
        admitted = overlay.admit(state_root, virtual, now, profiles, curated, ident, allow_replay=replay, entries=entries)
        for sym, adm in admitted.items():
            if adm["mode"] == "BLOCKED" and adm["reason"] in ("APPROVAL_BINDING", "STATE_CORRUPT"):
                readable.discard(sym)  # carried unchanged: its references stay the fail-closed barrier
        # Store usage comes from the reservation journal (bounded reconciliation, nothing enumerated). When it is unknown
        # new captures wait and the summary says so; detections and everything else proceed.
        try:
            usage = overlay.reconcile_usage(state_root)
        except (OSError, overlay.StateError) as error:
            raise SystemicFailure(f"STORE {type(error).__name__}") from error
        if usage is None:
            summary["store_accounting"] = "UNKNOWN"
        budget = {"bytes": 0, "store": usage}
        reuse = archive_captures(state_root, [a for s in readable for a in entries[s]["open"]]
                                 + [admitted[s]["producer"] for s in admitted if admitted[s]["producer"]])
        # Phase 1, for every issuer before anything is fetched: every material document observed against the
        # effective record joins the issuer's monotonic detection set, committed in one generation (items the admitted
        # producer accounts for are pruned). Later feed reads, receipt retention, a crash while another issuer is
        # fetched or a retry can no longer make one disappear; overflow is kept as a fail-closed barrier.
        work: dict[str, tuple[Mapping[str, Any], list[dict[str, Any]], list[dict[str, Any]]]] = {}
        for sym in profiles:
            adm = admitted[sym]
            if adm["mode"] == "BLOCKED" and adm["reason"] in ("APPROVAL_BINDING", "STATE_CORRUPT"):
                summary["issuers"][sym] = {"action": "BLOCKED", "reason": adm["reason"]}  # nothing is fetched on unadmitted state
                continue
            effective = adm["effective"]
            if effective is None:
                summary["issuers"][sym] = {"action": "SKIPPED", "reason": "NO_CURATED_RECORD"}
                continue
            ref, _ = overlay.reference(effective)
            rows = overlay.receipt_rows(receipts, sym, ref, now)
            material = overlay.unaccounted(effective, rows, adm["producer"], adm["detections"])
            store = detections.get(sym) or {"documents": [], "overflow": False}
            union = overlay._material_documents([{"later_documents": list(store["documents"]) + material}])
            if adm["producer"] is not None:
                consumed, filed = overlay.consumed_identities(adm["producer"]), overlay.routing_filed(adm["producer"])
                union = [d for d in union if (str(d["channel"]), str(d["id"]), str(d["date"])) not in consumed and not str(d["date"]) < filed]
            overflow = len(union) > overlay.MAX_DETECTIONS or store["overflow"]
            updated = {"documents": [{k: d[k] for k in overlay.LATER_KEYS} for d in union[:overlay.MAX_DETECTIONS]], "overflow": overflow}
            if updated != store and (material or sym in detections):
                detections[sym] = updated
                state["changed"] = True
            if overflow:
                summary["issuers"][sym] = {"action": "WAITING", "reason": "DETECTIONS_OVERFLOW"}
                continue
            if not material:
                summary["issuers"][sym] = {"action": "NO_EVENT", "receipts": len(rows)}
                continue
            work[sym] = (effective, rows, material)
        if state["changed"]:
            publish()
        # Phase 2: events, one issuer at a time, in a persisted fair order (starting after the issuer served last).
        order = list(profiles)
        if queue.get("last_served") in order:
            start = order.index(queue["last_served"]) + 1
            order = order[start:] + order[:start]
        exhausted = False
        for sym in order:
            profile = profiles[sym]
            if sym not in work:
                continue
            if exhausted:
                # The run's shared budget is spent: this issuer is not served and keeps its place at the queue head.
                summary["issuers"][sym] = {"action": "WAITING", "reason": "RUN_BUDGET"}
                continue
            adm = admitted[sym]
            entry = entries.setdefault(sym, overlay.new_entry())
            readable.add(sym)
            effective, rows, material = work[sym]
            listed = overlay._material_documents(rows + [{"later_documents": adm["detections"]}]) + [
                dict(d) for r in rows for d in r.get("later_documents") or [] if d.get("disposition") not in overlay.MATERIAL]
            all_events = candidate_events(listed, reference_accession(effective), profile)
            settled = {x["key"] for x in entry["index"]["settled"]}
            events = [e for e in all_events if e["accession"] not in settled]
            documents = list((detections.get(sym) or {"documents": []})["documents"])
            if not all_events:
                # Material documents but no supported results filing (a 10-Q alone, a 6-K, an unrelated same-day
                # release, an unclassified 8-K): the issuer waits until a verified successor supersedes the record.
                key = "unresolved:" + verify.sha256(verify.canonical_json(sorted(
                    [str(d.get("channel")), str(d.get("id")), str(d.get("date"))] for d in material)).encode("utf-8"))[:16]
                last = entry["open"][-1] if entry["open"] else None
                if last is None or last["event_key"] != key:
                    if last is not None and last["outcome"] == "WAITING" and last["event_key"].startswith("unresolved:"):
                        entry["open"].pop()
                    overlay.append_attempt(entry, _attempt(key, now, effective,
                        {"later_documents": documents, **({"adapter": profile["adapter"]} if
                         profile["adapter"] == verify.NBIS_6K_TABLE_REAFFIRMATION_V1 else {})}, {}, {
                        "outcome": "WAITING", "reason": "EVENT_UNRESOLVED", "record": None, "decisions": [],
                        "detail": f"{len(material)} material later documents, no supported results filing"}))
                    state["changed"] = True
                summary["issuers"][sym] = {"action": "WAITING", "reason": "EVENT_UNRESOLVED"}
                continue
            if not events:
                last = entry["open"][-1] if entry["open"] else None
                summary["issuers"][sym] = {"action": "SETTLED", "outcome": last["outcome"] if last else None}
                continue
            # The complete unresolved material set is persisted with the event before anything is fetched.
            lead = dict(events[0], later_documents=documents)
            if not any(a["event_key"] == lead["accession"] for a in entry["open"]):
                # Detection is committed before anything is fetched: a failure after this point cannot forget it.
                state["changed"] |= _record(entry, _attempt(lead["accession"], now, effective, lead, {}, {
                    "outcome": "WAITING", "reason": "EVENT_DETECTED", "record": None, "decisions": [], "detail": "results filing detected"}))
            if state["changed"]:
                publish()  # the detection (and anything else pending) before any fetch
            # The queue position is written before fetching, so a crash or a stuck source for this issuer never makes
            # the next run start with it again.
            before = queue.get("last_served")
            if before != sym:
                queue["last_served"] = sym
                write_queue(state_root, queue)
            captures: dict[str, str] = {}
            try:
                if profile["adapter"] not in PLANNERS:
                    raise verify.Blocked("BLOCKED", "UNSUPPORTED_TEMPLATE", f"adapter {profile['adapter']}")
                event, captures = PLANNERS[profile["adapter"]](transport, state_root, profile, lead, now[:10], clock, budget, reuse, captures)
                decided = now_instant(clock)
                result = verify.build_successor(profile, overlay.predecessor_view(effective, curated.get(sym)), event,
                                                {k: overlay.load_capture(state_root, v) for k, v in captures.items()}, decided)
            except verify.Blocked as b:
                decided, event = now_instant(clock), lead  # the captures made so far stay referenced (resume)
                result = {"outcome": b.outcome, "reason": b.reason, "detail": b.detail, "record": None, "decisions": []}
            except NetworkBlocked as nb:
                decided, event = now_instant(clock), lead
                result = {"outcome": "WAITING", "reason": "NETWORK_UNAVAILABLE", "detail": str(nb)[:120], "record": None, "decisions": []}
            except overlay.StateError as error:
                raise SystemicFailure(f"STATE {error}") from error
            if result["outcome"] == "WAITING" and str(result["detail"]).startswith(("RUN_BUDGET", "RUN_REQUEST_BUDGET", "RUN_CAPTURE_BUDGET")):
                exhausted = True
                if not captures and before != sym:
                    queue["last_served"] = before  # not served: keep this issuer at the head of the next run
                    write_queue(state_root, queue)
            try:
                state["changed"] |= _record(entry, _attempt(lead["accession"], decided, effective, event, captures, result))
            except overlay.StateError as error:
                raise SystemicFailure(f"STATE {error}") from error
            summary["issuers"][sym] = {"action": "ATTEMPTED", "event": lead["accession"], "outcome": result["outcome"], "reason": result["reason"]}
        if state["changed"]:
            publish()
        return summary
    finally:
        if lock is not None:
            lock.release()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--state-root", type=Path, required=True, help="explicit state root (no default)")
    parser.add_argument("--profiles", type=Path, default=PROFILES_PATH)
    parser.add_argument("--registry", type=Path, default=REGISTRY_PATH)
    parser.add_argument("--approval", type=Path, default=APPROVAL_PATH)
    parser.add_argument("--receipts", type=Path, default=RECEIPTS_PATH)
    parser.add_argument("--replay", type=Path, help="hermetic replay directory (inventory.json + raw/); no network")
    parser.add_argument("--as-of", help="replay clock (UTC instant, only with --replay)")
    parser.add_argument("--recount-store", action="store_true",
                        help="maintenance: rebuild the capture-store accounting from the objects on disk, then exit")
    args = parser.parse_args(argv)
    if args.as_of and not args.replay:
        parser.error("--as-of is only valid with --replay")
    root = args.state_root
    if root.exists() and (not root.is_dir() or any(c.name not in STATE_ENTRIES and not TEMP_ENTRY_RE.match(c.name) for c in root.iterdir())):
        parser.error("--state-root must be empty or an existing auto-update state root")
    if args.recount_store:
        try:
            lock = StateLock(root)
        except SystemicFailure as error:
            print(json.dumps({"status": "SYSTEMIC_FAILURE", "error": str(error)[:200]}))
            return 2
        try:
            print(json.dumps(dict(overlay.recount_usage(root), status="RECOUNTED")))
        finally:
            lock.release()
        return 0
    try:
        if args.as_of:
            fixed = datetime.strptime(args.as_of, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            clock: Callable[[], datetime] = lambda: fixed  # noqa: E731
        else:
            clock = lambda: datetime.now(timezone.utc)  # noqa: E731
        if args.replay:
            transport: Any = ReplayTransport(args.replay)
        else:
            from sec_contact_headers import sec_identity_headers
            transport = Transport(sec_identity_headers())
        summary = run(root, transport, clock, args.profiles, args.registry, args.approval, args.receipts)
    except SystemicFailure as error:
        print(json.dumps({"status": "SYSTEMIC_FAILURE", "error": str(error)[:200]}))
        return 2
    except Exception as error:  # noqa: BLE001 - any unexpected failure is systemic, reported without source text
        print(json.dumps({"status": "SYSTEMIC_FAILURE", "error": type(error).__name__}))
        return 2
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
