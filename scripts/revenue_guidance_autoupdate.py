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
from datetime import datetime, timezone
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
STATE_ENTRIES = {"captures", "generations", "current.json", "lock"}


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

    def _address(self, host: str) -> str:
        try:
            addresses = self.resolver(host)
        except OSError as error:
            raise NetworkBlocked(f"DNS {host}") from error
        if not addresses or not all(ipaddress.ip_address(a).is_global for a in addresses):
            raise NetworkBlocked(f"ADDRESS {host}")
        return addresses[0]

    def _budget(self, symbol: str) -> None:
        if self.monotonic() - self.started > RUN_BUDGET_SECONDS:
            raise NetworkBlocked("RUN_BUDGET")
        if self.requests >= PER_RUN_REQUESTS or self.issuer_requests.get(symbol, 0) >= PER_ISSUER_REQUESTS:
            raise NetworkBlocked("REQUEST_BUDGET")
        wait = PACING_SECONDS - (self.monotonic() - self.last)
        if wait > 0:
            self.sleep(wait)
        self.last = self.monotonic()
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
                response = self.connector(host, address, parts.path, headers, REQUEST_TIMEOUT)
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
                        if total > CAPS[kind]:
                            raise NetworkBlocked(f"CAP {kind}")
                        if self.monotonic() - self.started > RUN_BUDGET_SECONDS:
                            raise NetworkBlocked("RUN_BUDGET")
                        chunks.append(chunk)
                    return b"".join(chunks), ctype
                finally:
                    response.close()
            except _Transient as transient:
                if attempt == MAX_ATTEMPTS or transient.retry_after > MAX_RETRY_AFTER:
                    raise NetworkBlocked("TRANSIENT") from None
                self.sleep(transient.retry_after)
            except (OSError, http.client.HTTPException) as error:
                if attempt == MAX_ATTEMPTS:
                    raise NetworkBlocked(f"UNREACHABLE {type(error).__name__}") from None
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
        m = re.fullmatch(r"8-K items ([0-9.,]+)", str(item.get("label", "")))
        if not m or "2.02" not in m.group(1).split(","):
            continue

        def lead(channel: str, pattern: str) -> dict[str, str] | None:
            same = [x for x in documents if x.get("channel") == channel and x.get("date") == item.get("date")
                    and re.fullmatch(pattern, str(x.get("label", "")))]
            return {"id": same[0]["id"], "title": same[0]["label"], "date": same[0]["date"]} if len(same) == 1 else None
        events.append({"accession": item["id"], "filed": item["date"], "periodic": {}, "calendar": None, "allocation_sources": [],
                       "ir_item": lead("ISSUER_IR", profile["ir_title_pattern"]),
                       "wire_item": lead("WIRE_PRESS_RELEASES", profile["wire_title_pattern"]), "later_documents": []})
    return sorted(events, key=lambda e: (e["filed"], e["accession"]))


def plan_event(transport: Any, root: Path, profile: Mapping[str, Any], lead: Mapping[str, Any], today: str,
               clock: Callable[[], datetime], budget: dict[str, int]) -> tuple[dict[str, Any], dict[str, str]]:
    """Capture what the verifier needs for this event; returns (event for the verifier, {capture key: raw sha})."""
    cik, sym = profile["cik"], profile["symbol"]
    captures: dict[str, str] = {}

    def fetch(key: str, url: str, role: str) -> bytes:
        data, ctype = transport.get(url, profile, sym)
        budget["bytes"] += len(data)
        if budget["bytes"] > CYCLE_CAPTURE_BYTES or budget["store"] + budget["bytes"] > STORE_QUOTA_BYTES:
            raise verify.Blocked("WAITING", "CAPTURE_LIMIT", "cycle or store byte budget")
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
        g = verify.extract_guidance(verify.parse_document(exhibit_raw), profile)
        aq, afy = verify.next_quarter(g["quarter"], g["fiscal_year"], -1)
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
        except NetworkBlocked:
            pass  # an unproven wire copy is simply not consumed (it keeps the issuer suspended if it is listed)
    event = dict(lead, periodic=periodic, calendar=calendar, allocation_sources=allocation)
    return event, captures


# ------------------------------------------------------------------------------------------------ run

def _new_generation_id(clock: Callable[[], datetime]) -> str:
    return f"{clock().astimezone(timezone.utc):%Y%m%dT%H%M%SZ}-{secrets.token_hex(6)}"


def _attempt(key: str, decided: str, effective: Mapping[str, Any], event: Mapping[str, Any], captures: Mapping[str, str],
             result: Mapping[str, Any]) -> dict[str, Any]:
    record = result["record"]
    full_event = {"accession": None, "filed": None, "periodic": {}, "calendar": None, "allocation_sources": [], "ir_item": None,
                  "wire_item": None, "later_documents": []}
    full_event.update({k: v for k, v in event.items() if k in overlay.EVENT_KEYS})
    return {"event_key": key, "attempted_at": decided, "predecessor_sha256": overlay.record_sha256(effective),
            "event": full_event, "captures": dict(captures), "outcome": result["outcome"], "reason": result["reason"],
            "detail": str(result["detail"])[:300], "record_sha256": overlay.record_sha256(record) if record else None,
            "record": record, "decisions": result["decisions"]}


def _record(attempts: list[dict[str, Any]], new: dict[str, Any]) -> bool:
    """Append an attempt, superseding a trailing wait of the same event; an unchanged wait changes nothing."""
    last = attempts[-1] if attempts else None
    if (last is not None and last["event_key"] == new["event_key"] and last["outcome"] == "WAITING" == new["outcome"]
            and last["reason"] == new["reason"] and last["detail"] == new["detail"] and last["event"] == new["event"]):
        return False
    if last is not None and last["event_key"] == new["event_key"] and last["outcome"] == "WAITING":
        attempts.pop()
    attempts.append(new)
    return True


def reverify(root: Path, profiles: Mapping[str, Mapping[str, Any]], curated: Mapping[str, Mapping[str, Any]],
             history: Mapping[str, list[Mapping[str, Any]]], allow_replay: bool) -> dict[str, list[dict[str, Any]]]:
    """Re-run every stored attempt with captures under the installed policy and code, in order, from the stored bytes
    (earlier generations keep the original history). A VERIFIED attempt without captures cannot be proven: blocked."""
    out: dict[str, list[dict[str, Any]]] = {}
    for sym, attempts in history.items():
        if sym not in profiles or curated.get(sym) is None:
            continue
        effective, rebuilt = curated[sym], []
        for a in attempts:
            if a.get("captures"):
                try:
                    result = overlay.rederive(root, profiles[sym], effective, a, allow_replay)
                except overlay.StateError as error:
                    result = {"outcome": "BLOCKED", "reason": "APPROVAL_BINDING", "detail": str(error), "record": None, "decisions": []}
            elif a.get("outcome") == "VERIFIED":
                result = {"outcome": "BLOCKED", "reason": "APPROVAL_BINDING", "detail": "verified attempt without captures", "record": None, "decisions": []}
            else:
                result = {k: a[k] for k in ("outcome", "reason", "detail", "record", "decisions")}
            rebuilt.append(_attempt(a["event_key"], a["attempted_at"], effective, a["event"], a.get("captures") or {}, result))
            if result["outcome"] == "VERIFIED":
                effective = result["record"]
        out[sym] = rebuilt
    return out


def run(state_root: Path, transport: Any, clock: Callable[[], datetime], profiles_path: Path = PROFILES_PATH,
        registry_path: Path = REGISTRY_PATH, approval_path: Path = APPROVAL_PATH, receipts_path: Path = RECEIPTS_PATH) -> dict[str, Any]:
    """One updater cycle. Returns a summary; raises SystemicFailure for integrity/lock/persistence failures."""
    profiles_bytes, registry_bytes, approval_bytes = profiles_path.read_bytes(), registry_path.read_bytes(), approval_path.read_bytes()
    profiles = verify.validate_profiles(json.loads(profiles_bytes.decode("utf-8")))
    curated = {r["symbol"]: r for r in json.loads(registry_bytes.decode("utf-8"))["issuers"]}
    try:
        receipts = json.loads(receipts_path.read_text(encoding="utf-8")) if receipts_path.exists() else {"issuers": {}}
    except (OSError, ValueError) as error:
        raise SystemicFailure("RECEIPTS_UNREADABLE") from error
    replay = bool(getattr(transport, "replay", False))
    lock = StateLock(state_root)
    try:
        now = now_instant(clock)
        try:
            pointer = overlay.read_pointer(state_root)
            base = overlay.read_generation(state_root, pointer["generation_id"], pointer["sha256"]) if pointer else None
        except overlay.StateError as error:
            raise SystemicFailure(f"STATE {error}") from error
        ident = overlay.identity(profiles_bytes, registry_bytes, approval_bytes)
        history: dict[str, list[dict[str, Any]]] = {s: list(a) for s, a in (base or {}).get("issuers", {}).items()}
        detections: dict[str, dict[str, Any]] = {s: dict(d) for s, d in (base or {}).get("detections", {}).items()}
        summary: dict[str, Any] = {"status": "OK", "at": now, "issuers": {}, "reverified": False}
        state = {"pointer": pointer, "changed": False}

        def publish() -> None:
            gen = dict(ident, schema=overlay.STATE_SCHEMA, generation_id=_new_generation_id(clock),
                       parent=None if state["pointer"] is None else {"generation_id": state["pointer"]["generation_id"], "sha256": state["pointer"]["sha256"]},
                       created_at=now_instant(clock), issuers={s: a for s, a in history.items() if a}, detections=dict(detections))
            try:
                digest = overlay.publish_generation(state_root, gen, state["pointer"])
            except overlay.StateError as error:
                raise SystemicFailure(f"PUBLISH {error}") from error
            state["pointer"] = {"schema": overlay.POINTER_SCHEMA, "generation_id": gen["generation_id"], "sha256": digest}
            summary["generation_id"] = gen["generation_id"]
            state["changed"] = False

        if base is not None and any(base[k] != ident[k] for k in overlay.IDENTITY_KEYS):
            history = reverify(state_root, profiles, curated, history, replay)  # new reviewed policy, code or baseline
            summary["reverified"] = True
            state["changed"] = True
        virtual = dict(ident, generation_id=None, issuers=history, detections=detections)
        admitted = overlay.admit(state_root, virtual, now, profiles, curated, ident, allow_replay=replay)
        budget = {"bytes": 0, "store": overlay.capture_bytes_total(state_root)}
        # Phase 1, for every issuer before anything is fetched: every material document observed against the
        # effective record joins its monotonic detection set, committed in one generation. Later feed reads, receipt
        # retention, a crash while another issuer is fetched or a retry can no longer make it disappear; overflow is
        # kept as a fail-closed barrier.
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
            pred = overlay.record_sha256(effective)
            entry = detections.get(sym)
            prior = list(entry["documents"]) if entry and entry["predecessor_sha256"] == pred else []
            union = overlay._material_documents([{"later_documents": prior + material}])
            overflow = len(union) > overlay.MAX_DETECTIONS or bool(entry and entry["predecessor_sha256"] == pred and entry["overflow"])
            updated = {"predecessor_sha256": pred, "documents": [{k: d[k] for k in overlay.LATER_KEYS} for d in union[:overlay.MAX_DETECTIONS]],
                       "overflow": overflow}
            if material and updated != entry:
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
        # Phase 2: events, one issuer at a time.
        for sym, profile in profiles.items():
            if sym not in work:
                continue
            adm = admitted[sym]
            attempts = history.setdefault(sym, [])
            effective, rows, material = work[sym]
            listed = overlay._material_documents(rows + [{"later_documents": adm["detections"]}]) + [
                dict(d) for r in rows for d in r.get("later_documents") or [] if d.get("disposition") not in overlay.MATERIAL]
            all_events = candidate_events(listed, reference_accession(effective), profile)
            settled = {a["event_key"] for a in attempts if a["outcome"] in ("VERIFIED", "BLOCKED")}
            events = [e for e in all_events if e["accession"] not in settled]
            if not all_events:
                # Material documents but no supported results filing (a 10-Q alone, a 6-K, an unrelated same-day
                # release, an unclassified 8-K): the issuer waits until a verified successor supersedes the record.
                key = "unresolved:" + verify.sha256(verify.canonical_json(sorted(
                    [str(d.get("channel")), str(d.get("id")), str(d.get("date"))] for d in material)).encode("utf-8"))[:16]
                if not attempts or attempts[-1]["event_key"] != key:
                    state["changed"] |= _record(attempts, _attempt(key, now, effective, {"later_documents": list(detections[sym]["documents"])}, {}, {
                        "outcome": "WAITING", "reason": "EVENT_UNRESOLVED", "record": None, "decisions": [],
                        "detail": f"{len(material)} material later documents, no supported results filing"}))
                summary["issuers"][sym] = {"action": "WAITING", "reason": "EVENT_UNRESOLVED"}
                continue
            if not events:
                summary["issuers"][sym] = {"action": "SETTLED", "outcome": attempts[-1]["outcome"] if attempts else None}
                continue
            # The complete unresolved material set is persisted with the event before anything is fetched, so it
            # survives the reference change a verified successor makes.
            lead = dict(events[0], later_documents=list(detections[sym]["documents"]))
            if not any(a["event_key"] == lead["accession"] for a in attempts):
                # Detection is committed before anything is fetched: a failure after this point cannot forget it.
                _record(attempts, _attempt(lead["accession"], now, effective, lead, {}, {
                    "outcome": "WAITING", "reason": "EVENT_DETECTED", "record": None, "decisions": [], "detail": "results filing detected"}))
                publish()
            try:
                event, captures = plan_event(transport, state_root, profile, lead, now[:10], clock, budget)
                decided = now_instant(clock)
                result = verify.build_successor(profile, effective, event,
                                                {k: overlay.load_capture(state_root, v) for k, v in captures.items()}, decided)
            except verify.Blocked as b:
                decided, event, captures = now_instant(clock), lead, {}
                result = {"outcome": b.outcome, "reason": b.reason, "detail": b.detail, "record": None, "decisions": []}
            except NetworkBlocked as nb:
                decided, event, captures = now_instant(clock), lead, {}
                result = {"outcome": "WAITING", "reason": "NETWORK_UNAVAILABLE", "detail": str(nb)[:120], "record": None, "decisions": []}
            except overlay.StateError as error:
                raise SystemicFailure(f"STATE {error}") from error
            state["changed"] |= _record(attempts, _attempt(lead["accession"], decided, effective, event, captures, result))
            summary["issuers"][sym] = {"action": "ATTEMPTED", "event": lead["accession"], "outcome": result["outcome"], "reason": result["reason"]}
        for sym in [s for s, a in history.items() if not a]:
            del history[sym]
        if state["changed"]:
            publish()
        return summary
    finally:
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
    args = parser.parse_args(argv)
    if args.as_of and not args.replay:
        parser.error("--as-of is only valid with --replay")
    root = args.state_root
    if root.exists() and (not root.is_dir() or any(c.name not in STATE_ENTRIES for c in root.iterdir())):
        parser.error("--state-root must be empty or an existing auto-update state root")
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
