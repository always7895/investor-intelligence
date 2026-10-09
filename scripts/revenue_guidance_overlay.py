#!/usr/bin/env python3
"""Runtime state of ORDERS-V3-AUTOUPDATE-01 (docs/REVENUE_GUIDANCE_AUTOUPDATE.md): content-addressed captures,
immutable generations, admission by re-derivation and the release-check gate.

Layout under one state root (the runtime's data/cache/revenue_guidance_autoupdate, a temporary root in tests):
  captures/<aa>/<raw sha256>        exact HTTP entity bytes
  captures/<aa>/<raw sha256>.json   capture metadata (url, retrieved_at, bytes, digests, role ...)
  segments/<sha256>.json            immutable, content-addressed segments of an issuer's attempt history
  generations/<id>.json             one immutable generation (per issuer: sealed segments + open attempts,
                                    detections)
  queue.json                        the updater's fair-queue position (a scheduling hint only, never an admission input)
  current.json                      pointer {schema, generation_id, sha256}, replaced atomically

The updater is the only writer. Nothing stored is trusted as an outcome: an issuer's automatic record is admitted
only when the installed verifier, run again on the stored capture bytes, reproduces the stored record and decisions
exactly, along an unbroken chain of predecessors starting at the curated record, under the generation's recorded
implementation, profile and baseline identities. Any mismatch fails closed for that issuer (never back to old
numbers); unreadable global state fails closed for every enabled issuer; issuers without attempts keep their curated
record. Readers and the updater use the same admission (`admit`)."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import revenue_guidance
import revenue_guidance_auto_verify as verify

STATE_SCHEMA = "revenue-guidance-auto-state-v3"
POINTER_SCHEMA = "revenue-guidance-auto-pointer-v1"
CAPTURE_META_KEYS = {"url", "accession", "form", "filed", "retrieved_at", "bytes", "raw_sha256", "sha256", "content_type", "role"}
ATTEMPT_KEYS = {"event_key", "attempted_at", "predecessor_sha256", "event", "captures", "outcome", "reason", "detail",
                "record_sha256", "record", "decisions"}
EVENT_KEYS = {"accession", "filed", "periodic", "calendar", "allocation_sources", "ir_item", "wire_item", "later_documents"}
DECISION_KEYS = {"kind", "ref", "decision", "capture", "operands", "reviewed_at"}
LATER_KEYS = {"channel", "date", "id", "label", "disposition"}
ITEM_KEYS = {"id", "title", "date"}
GENERATION_KEYS = {"schema", "generation_id", "parent", "created_at", "verifier_version", "normalizer_version",
                   "implementation_sha256", "profiles_sha256", "baseline_registry_sha256", "baseline_approval_sha256", "issuers",
                   "detections"}
# History: attempts are sealed into immutable segments of at most SEGMENT_SIZE; a generation references them by digest
# and keeps the newest attempts open (a trailing wait can still be superseded). No lifetime attempt limit, nothing
# deleted; a missing or altered segment blocks that issuer.
SEGMENT_SIZE = 32
MAX_OPEN = 64
MAX_SEGMENTS = 4096
# The machine decision contract: exact operand keys per decision kind (and per ACTUAL shape).
OPERAND_KEYS = {
    "CLAIM": ({"offsets", "point", "low", "high", "quarter", "fiscal_year"},),
    "ACTUAL": ({"concept", "start", "end", "value"}, {"concept", "longer", "shorter_concept", "shorter", "shorter_capture"}, {"label", "value"}),
    "CALENDAR": ({"rule", "offsets", "allocation"},),
    "ROUTING": ({"adapter", "accession", "form", "items", "filed", "exhibit", "package", "ir_item", "wire_item", "consumed",
                 "report_period", "reference"},),
}
CONSUMED_KEYS = {"channel", "id", "date"}
DETECTION_KEYS = {"documents", "overflow"}
INDEX_KEYS = {"verified", "truncated", "settled"}
ENTRY_KEYS = {"head", "sealed", "open", "index"}
INDEX_TAIL = 8
LOCATOR_KEYS = {"segment", "position"}
MAX_VERIFIED = 4096
MAX_SETTLED = 256
MAX_DETECTIONS = 256
IDENTITY_KEYS = ("verifier_version", "normalizer_version", "implementation_sha256", "profiles_sha256",
                 "baseline_registry_sha256", "baseline_approval_sha256")
# The reviewed code whose behaviour decides admission; a changed byte invalidates every stored machine approval.
IMPLEMENTATION_FILES = ("revenue_guidance.py", "revenue_guidance_auto_verify.py", "revenue_guidance_overlay.py")
ID_RE = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
INSTANT_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
DAY_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
ACCESSION_RE = re.compile(r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")
KEY_RE = re.compile(r"^(?:submissions|index|exhibit|ir_copy|wire_copy|package:[A-Za-z0-9._-]{1,120}|[0-9]{10}-[0-9]{2}-[0-9]{6})$")
CHANNELS = ("SEC_SUBMISSIONS", "WIRE_PRESS_RELEASES", "ISSUER_IR")
MATERIAL = ("RESULTS_RELEASE", "POSSIBLY_RELEVANT")
DECISION_KINDS = ("CLAIM", "ACTUAL", "CALENDAR", "ROUTING")
MAX_GENERATION_BYTES = 8 * 1024 * 1024


class StateError(Exception):
    """The state root is present but unusable (corrupt, foreign or incomplete)."""


def record_sha256(record: Mapping[str, Any]) -> str:
    return verify.sha256(verify.canonical_json(record).encode("utf-8"))


def implementation_sha256(root=None) -> str:
    here = Path(__file__).resolve().parent
    parts = [f"{name}:{hashlib.sha256(root.implementation(name) if type(root) is B1Store else (here / name).read_bytes()).hexdigest()}" for name in IMPLEMENTATION_FILES]
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def identity(profiles_bytes: bytes, registry_bytes: bytes, approval_bytes: bytes, root=None) -> dict[str, str]:
    return {"verifier_version": verify.VERIFIER_VERSION, "normalizer_version": verify.NORMALIZER_VERSION,
            "implementation_sha256": implementation_sha256(root), "profiles_sha256": verify.sha256(profiles_bytes),
            "baseline_registry_sha256": verify.sha256(registry_bytes), "baseline_approval_sha256": verify.sha256(approval_bytes)}


# ------------------------------------------------------------------------------------------------ captures

def capture_path(root: Path, raw_sha: str) -> Path:
    if not SHA_RE.match(str(raw_sha)):
        raise StateError("CAPTURE_ID")
    return root / "captures" / raw_sha[:2] / raw_sha


def load_capture(root: Path, raw_sha: str) -> dict[str, Any]:
    """Bytes and metadata of one capture, re-hashed; the verifier re-checks them against its own rules again."""
    path = capture_path(root, raw_sha)
    try:
        raw = path.read_bytes()
        meta = json.loads(path.with_name(raw_sha + ".json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise StateError(f"CAPTURE_MISSING {raw_sha[:12]}") from error
    if not isinstance(meta, dict) or set(meta) != CAPTURE_META_KEYS:
        raise StateError(f"CAPTURE_META {raw_sha[:12]}")
    if verify.sha256(raw) != raw_sha or meta["raw_sha256"] != raw_sha or meta["bytes"] != len(raw):
        raise StateError(f"CAPTURE_BYTES {raw_sha[:12]}")
    if meta["sha256"] != verify.sha256(verify.canonical_bytes(raw)) or not INSTANT_RE.match(str(meta["retrieved_at"])):
        raise StateError(f"CAPTURE_IDENTITY {raw_sha[:12]}")
    if not isinstance(meta["url"], str) or not meta["url"].startswith("https://") or len(meta["url"]) > 400:
        raise StateError(f"CAPTURE_URL {raw_sha[:12]}")
    return dict(meta, raw=raw)


def _durable_write(path: Path, data: bytes) -> None:
    """Write to a temporary sibling, flush and fsync, then atomically replace (never a half-written file)."""
    if type(path) is B1Object:
        path.store.write(path.components, data)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp-{os.getpid()}")
    with open(tmp, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def store_capture(root: Path, raw: bytes, meta: Mapping[str, Any]) -> str:
    """Content-addressed; an existing capture must hold exactly these bytes (it is never overwritten)."""
    raw_sha = verify.sha256(raw)
    path = capture_path(root, raw_sha)
    full = {"url": meta["url"], "accession": meta.get("accession"), "form": meta.get("form"), "filed": meta.get("filed"),
            "retrieved_at": meta["retrieved_at"], "bytes": len(raw), "raw_sha256": raw_sha,
            "sha256": verify.sha256(verify.canonical_bytes(raw)), "content_type": meta.get("content_type", ""),
            "role": meta.get("role", "")}
    if path.exists():
        if type(root) is B1Store:
            load_capture(root, raw_sha)  # reuse only admitted original metadata/time
            return raw_sha
        if verify.sha256(path.read_bytes()) != raw_sha:
            raise StateError(f"CAPTURE_BYTES {raw_sha[:12]}")
        # Same bytes captured again (another URL or time): keep the first metadata; the attempt names the URL it used.
        # (The bytes were counted when the object was reserved.)
        if not path.with_name(raw_sha + ".json").exists():
            _durable_write(path.with_name(raw_sha + ".json"), json.dumps(full, sort_keys=True).encode("utf-8"))
        return raw_sha
    # Reservation first: the counter already includes these bytes (and names them pending) before any file is written,
    # so an interruption at any later point can only over-count; `reconcile_usage` settles pending reservations.
    usage = _read_usage_file(root)
    if usage is None:
        if (root / "captures").exists():
            raise StateError("STORE_ACCOUNTING_UNKNOWN")
        usage = {"bytes": 0, "files": 0, "pending": {}}
    if len(usage["pending"]) >= MAX_PENDING:
        raise StateError("STORE_ACCOUNTING_PENDING")
    usage["bytes"] += len(raw)
    usage["files"] += 1
    usage["pending"][raw_sha] = {"bytes": len(raw), "pid": os.getpid()}
    _write_usage(root, usage)
    if type(root) is B1Store:
        root.ensure_capture_bucket(raw_sha)
    _durable_write(path, raw)
    _durable_write(path.with_name(raw_sha + ".json"), json.dumps(full, sort_keys=True).encode("utf-8"))
    del usage["pending"][raw_sha]
    _write_usage(root, usage)
    return raw_sha


USAGE_FILE = "store_usage.json"
MAX_PENDING = 16


def _read_usage_file(root: Path) -> dict[str, Any] | None:
    """The store's accounting journal: raw bytes and objects held (reservations included) and the pending reservations
    (object digest -> reserved bytes and the writing process id). None when missing or malformed."""
    try:
        data = json.loads((root / USAGE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (not isinstance(data, dict) or set(data) != {"bytes", "files", "pending"} or type(data["bytes"]) is not int or data["bytes"] < 0
            or type(data["files"]) is not int or data["files"] < 0 or not isinstance(data["pending"], dict) or len(data["pending"]) > MAX_PENDING
            or not all(SHA_RE.match(str(k)) and isinstance(v, dict) and set(v) == {"bytes", "pid"} and type(v["bytes"]) is int
                       and v["bytes"] >= 0 and type(v["pid"]) is int for k, v in data["pending"].items())):
        return None
    return data


def _write_usage(root: Path, usage: Mapping[str, Any]) -> None:
    _durable_write(root / USAGE_FILE, json.dumps({"bytes": usage["bytes"], "files": usage["files"], "pending": usage["pending"]},
                                                 sort_keys=True).encode("utf-8"))


def _capability_pending_usage(root, usage):
    """Shared admission of real reservations, not absence/partial-byte settlement.

    None means missing/incoherent accounting identity; never reconstruct it from
    enumeration. Native capacity/pending/cleanup exceptions propagate unchanged.
    """
    if (usage is None or usage["bytes"] < sum(v["bytes"] for v in usage["pending"].values())
            or usage["files"] < len(usage["pending"])):
        return None
    pending = {digest: dict(reserved) for digest, reserved in usage["pending"].items()}
    for digest, reserved in usage["pending"].items():
        if not SHA_RE.fullmatch(digest):
            return None
        try:
            captured = load_capture(root, digest)  # original metadata/time, shared validator
        except (StateError, ValueError):
            continue  # EXACT original identity/amount/pid remains unresolved
        if len(captured["raw"]) == reserved["bytes"]:
            del pending[digest]
    return pending


def reconcile_usage(root: Path) -> int | None:
    """Raw bytes held by the capture store, from the accounting journal (under the updater's lock, at the start of a
    run). Pending reservations are settled: an object that was written stays counted; one that was not is released
    and its temporary file (an incomplete write, never referenced) removed. Work is bounded by MAX_PENDING; nothing is
    enumerated. None when the journal is missing or malformed for a non-empty store: new captures then wait until
    `recount_usage` (the `--recount-store` maintenance command) rebuilds it."""
    usage = _read_usage_file(root)
    if type(root) is B1Store:
        if usage is None:
            return None
        # No delete-by-name/refund. Incoherent identity or ANY unresolved original
        # reservation stays UNKNOWN; successful admission never lowers counters.
        pending = _capability_pending_usage(root, usage)
        if pending is None or pending:
            return None
        usage["pending"] = pending
        _write_usage(root, usage)
        return usage["bytes"]
    if usage is None:
        return 0 if not (root / "captures").exists() else None
    if usage["pending"]:
        for raw_sha, reserved in list(usage["pending"].items()):
            path = capture_path(root, raw_sha)
            if not path.exists():
                usage["bytes"] = max(0, usage["bytes"] - reserved["bytes"])
                usage["files"] = max(0, usage["files"] - 1)
                path.with_name(f"{raw_sha}.tmp-{reserved['pid']}").unlink(missing_ok=True)
            path.with_name(f"{raw_sha}.json.tmp-{reserved['pid']}").unlink(missing_ok=True)
            del usage["pending"][raw_sha]
        _write_usage(root, usage)
    return usage["bytes"]


def recount_usage(root: Path) -> dict[str, Any]:
    """Non-destructive maintenance. Legacy rebuild is explicit; capability recount
    requires the original ledger and cannot refund unresolved reservations."""
    if type(root) is B1Store:
        # Actual captured mutable state also binds the eventual conditional write.
        root.capture_mutable((USAGE_FILE,))
        usage = _read_usage_file(root)
        pending = _capability_pending_usage(root, usage)
        if pending is None:
            return {"status": "UNKNOWN", "bytes": None, "files": None, "pending": None}
        total = files = 0
        observed_raw = {}
        unknown = bool(pending)
        for bucket in sorted((root / "captures").iterdir(), key=lambda x: x.name):
            for item in bucket.iterdir():
                if not item.is_file():
                    raise StateError("STORE_ACCOUNTING_UNKNOWN")
                is_meta = item.name.endswith(".json")
                digest = item.name[:-5] if is_meta else item.name
                named_raw = bool(SHA_RE.fullmatch(digest)) and bucket.name == digest[:2]
                if not is_meta:
                    size = len(item.read_bytes())
                    total += size  # actual raw/temp bytes, never guessed/published evidence
                    files += 1
                    if named_raw:
                        observed_raw[digest] = size
                if named_raw:
                    try:
                        load_capture(root, digest)  # complete bytes + ORIGINAL admitted metadata
                    except (StateError, ValueError):
                        unknown = True
                else:
                    unknown = True  # leftover/foreign identity is counted, not repaired/admitted
        for digest, reserved in pending.items():
            # Raw already counted (even if partial/unadmitted) covers that part
            # only. Retain full original obligation without counting it twice.
            total += max(0, reserved["bytes"] - observed_raw.get(digest, 0))
            if digest not in observed_raw:
                files += 1
        # An unexplained old high-water count is not proven settled by absence;
        # retain it and UNKNOWN rather than inventing the missing accounting.
        unknown = unknown or total < usage["bytes"] or files < usage["files"]
        usage = {"bytes": max(usage["bytes"], total), "files": max(usage["files"], files), "pending": pending}
        _write_usage(root, usage)  # same-epoch captured expected identity/bytes + native readback
        return {"status": "UNKNOWN" if unknown else "RECOUNTED", "bytes": usage["bytes"],
                "files": usage["files"], "pending": len(pending)}
    total = files = 0
    captures = root / "captures"
    for bucket in sorted(captures.iterdir(), key=lambda x: x.name) if captures.exists() else []:
        for item in bucket.iterdir():
            if item.is_file() and not item.name.endswith(".json"):
                total += len(item.read_bytes()) if type(item) is B1Object else item.stat().st_size
                files += 1
    usage = {"bytes": total, "files": files, "pending": {}}
    _write_usage(root, usage)
    return {"bytes": total, "files": files}


# ------------------------------------------------------------------------------------------------ generations

def _generation_path(root: Path, generation_id: str) -> Path:
    if not ID_RE.match(str(generation_id)):
        raise StateError("GENERATION_ID")
    return root / "generations" / f"{generation_id}.json"


def read_generation(root: Path, generation_id: str, expected_sha: str) -> dict[str, Any]:
    path = _generation_path(root, generation_id)
    try:
        data = path.read_bytes()
    except OSError as error:
        raise StateError(f"GENERATION_MISSING {generation_id}") from error
    if len(data) > MAX_GENERATION_BYTES or verify.sha256(data) != expected_sha:
        raise StateError(f"GENERATION_BYTES {generation_id}")
    try:
        gen = json.loads(data.decode("utf-8"))
    except ValueError as error:
        raise StateError(f"GENERATION_JSON {generation_id}") from error
    validate_generation(gen)
    if gen["generation_id"] != generation_id:
        raise StateError("GENERATION_ID_MISMATCH")
    return gen


def _text(value: Any, limit: int, pattern: re.Pattern[str] | None = None) -> bool:
    return isinstance(value, str) and len(value) <= limit and (pattern is None or bool(pattern.match(value)))


def validate_attempt(a: Any) -> None:
    """Exact keys, types and bounds of one stored attempt (issuer-local: a violation blocks only that issuer)."""
    if not isinstance(a, dict) or set(a) != ATTEMPT_KEYS or a["outcome"] not in verify.OUTCOMES:
        raise StateError("ATTEMPT_SHAPE")
    if not _text(a["event_key"], 60, re.compile(r"^(?:[0-9]{10}-[0-9]{2}-[0-9]{6}|unresolved:[0-9a-f]{16})$")):
        raise StateError("ATTEMPT_KEY")
    if not _text(a["attempted_at"], 20, INSTANT_RE) or not _text(a["predecessor_sha256"], 64, SHA_RE):
        raise StateError("ATTEMPT_BINDING")
    if not _text(a["detail"], 400):
        raise StateError("ATTEMPT_DETAIL")
    caps = a["captures"]
    e = a["event"]
    nbis = isinstance(e, dict) and e.get("adapter") == verify.NBIS_6K_TABLE_REAFFIRMATION_V1
    capture_domain = re.compile(r"^(?:submissions|ir_copy|wire_copy|nbis:[0-9]{10}-[0-9]{2}-[0-9]{6}:(?:index|form|statement|letter|ir_copy|wire_copy|member:[A-Za-z0-9._-]{1,100}))$") if nbis else KEY_RE
    if not isinstance(caps, dict) or len(caps) > 32 or not all(_text(k, 140, capture_domain) and _text(v, 64, SHA_RE) for k, v in caps.items()):
        raise StateError("ATTEMPT_CAPTURES")
    if nbis:
        try:
            if revenue_guidance.parse_instant(a["attempted_at"]) is None:
                raise StateError("ATTEMPT_TIME")
            verify.validate_nbis_event(e, complete=a["outcome"] == "VERIFIED")
            if e["filed"] is not None and e["filed"] > a["attempted_at"][:10]:
                raise StateError("EVENT_AFTER_CUTOFF")
            if a["outcome"] == "VERIFIED":
                if (a["reason"] is not None or not isinstance(a["record"], dict) or a["record"].get("symbol") != "NBIS"
                        or a["record_sha256"] != record_sha256(a["record"]) or a["event_key"] != e["accession"]):
                    raise StateError("ATTEMPT_RECORD")
                revenue_guidance.validate_issuer_record(a["record"], "NBIS")
                verify.validate_nbis_decisions(a["decisions"], caps, e, a["record"], a["attempted_at"])
                if "submissions" not in caps or "ir_copy" not in caps or any(
                        p[k] not in caps for p in e["packages"] for k in ("index", "form", "statement", "letter")):
                    raise StateError("ATTEMPT_INPUTS")
            elif (a["record"] is not None or a["record_sha256"] is not None or a["decisions"] != [] or a["reason"] not in verify.REASONS
                  or (e["accession"] is not None and a["event_key"] != e["accession"])):
                raise StateError("ATTEMPT_OUTCOME")
        except (verify.Blocked, revenue_guidance.GuidanceError, KeyError, TypeError, ValueError, AttributeError, IndexError) as error:
            raise StateError("ATTEMPT_NBIS_SCHEMA") from error
        return  # exact distinct dialect; never the union of A1/NBIS fields

    if not isinstance(e, dict) or set(e) != EVENT_KEYS:
        raise StateError("ATTEMPT_EVENT")
    if e["accession"] is not None and not _text(e["accession"], 20, ACCESSION_RE):
        raise StateError("EVENT_ACCESSION")
    if e["filed"] is not None and not _text(e["filed"], 10, DAY_RE):
        raise StateError("EVENT_FILED")
    periodic = e["periodic"]
    if not isinstance(periodic, dict) or len(periodic) > 8 or not all(_text(k, 10, DAY_RE) and _text(v, 20, ACCESSION_RE) for k, v in periodic.items()):
        raise StateError("EVENT_PERIODIC")
    if e["calendar"] is not None and not _text(e["calendar"], 20, ACCESSION_RE):
        raise StateError("EVENT_CALENDAR")
    if not isinstance(e["allocation_sources"], list) or len(e["allocation_sources"]) > 4 or not all(_text(x, 20, ACCESSION_RE) for x in e["allocation_sources"]):
        raise StateError("EVENT_ALLOCATION")
    for item in (e["ir_item"], e["wire_item"]):
        if item is not None and (not isinstance(item, dict) or set(item) != ITEM_KEYS or not _text(item["id"], 400)
                                 or not _text(item["title"], 200) or not _text(item["date"], 10, DAY_RE)):
            raise StateError("EVENT_ITEM")
    later = e["later_documents"]
    if not isinstance(later, list) or len(later) > MAX_DETECTIONS or not all(
            isinstance(d, dict) and set(d) == LATER_KEYS and d["channel"] in CHANNELS and _text(d["id"], 400)
            and _text(d["date"], 10, DAY_RE) and _text(d["label"], 200) and d["disposition"] in MATERIAL for d in later):
        raise StateError("EVENT_LATER")
    decisions = a["decisions"]
    if not isinstance(decisions, list) or len(decisions) > 32 or not all(
            isinstance(d, dict) and set(d) == DECISION_KEYS and d["kind"] in DECISION_KINDS and _text(d["ref"], 80)
            and _text(d["decision"], 40) and d["capture"] in caps and isinstance(d["operands"], dict)
            and d["reviewed_at"] == a["attempted_at"] and set(d["operands"]) in OPERAND_KEYS[d["kind"]] for d in decisions):
        raise StateError("ATTEMPT_DECISIONS")
    if a["outcome"] == "VERIFIED":
        if a["reason"] is not None or not isinstance(a["record"], dict) or a["record_sha256"] != record_sha256(a["record"]) or not decisions:
            raise StateError("ATTEMPT_RECORD")
        kinds = [d["kind"] for d in decisions]
        if kinds.count("ROUTING") != 1 or kinds.count("CLAIM") != 1 or kinds.count("CALENDAR") != 1 or kinds.count("ACTUAL") < 5:
            raise StateError("ATTEMPT_DECISION_SET")
        routing = next(d["operands"] for d in decisions if d["kind"] == "ROUTING")
        consumed = routing["consumed"]
        if not isinstance(consumed, list) or not 1 <= len(consumed) <= 32 or not all(
                isinstance(c, dict) and set(c) == CONSUMED_KEYS and c["channel"] in CHANNELS and _text(c["id"], 400)
                and _text(c["date"], 10, DAY_RE) for c in consumed):
            raise StateError("ATTEMPT_CONSUMED")
        if (not _text(routing["filed"], 10, DAY_RE) or not _text(routing["accession"], 20, ACCESSION_RE)
                or not isinstance(routing["reference"], dict) or not isinstance(routing["report_period"], dict)):
            raise StateError("ATTEMPT_ROUTING")
        for key in ("submissions", "index", "exhibit", "ir_copy"):
            if key not in caps:
                raise StateError("ATTEMPT_INPUTS")
    elif a["record"] is not None or a["record_sha256"] is not None or decisions or a["reason"] not in verify.REASONS:
        raise StateError("ATTEMPT_OUTCOME")


def _later_ok(docs: Any) -> bool:
    return isinstance(docs, list) and len(docs) <= MAX_DETECTIONS and all(
        isinstance(d, dict) and set(d) == LATER_KEYS and d["channel"] in CHANNELS and _text(d["id"], 400)
        and _text(d["date"], 10, DAY_RE) and _text(d["label"], 200) and d["disposition"] in MATERIAL for d in docs)


def validate_detections(entry: Any) -> None:
    """An issuer's monotonic set of observed material documents (issuer-local). Only the admitted, re-derived producer
    accounts for items (its consumed identities, and items dated strictly before its filing day)."""
    if not isinstance(entry, dict) or set(entry) != DETECTION_KEYS or not _later_ok(entry["documents"]) or not isinstance(entry["overflow"], bool):
        raise StateError("ATTEMPT_DETECTIONS")


def segment_path(root: Path, digest: str) -> Path:
    if not SHA_RE.match(str(digest)):
        raise StateError("SEGMENT_ID")
    return root / "segments" / f"{digest}.json"


def write_segment(root: Path, attempts: list[Mapping[str, Any]], previous: str | None) -> str:
    """Seal attempts into an immutable content-addressed segment linked to the previous segment (a hash chain)."""
    if not 1 <= len(attempts) <= SEGMENT_SIZE:
        raise StateError("SEGMENT_SIZE")
    for a in attempts:
        validate_attempt(a)
    data = json.dumps({"previous": previous, "attempts": list(attempts)}, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8")
    digest = verify.sha256(data)
    path = segment_path(root, digest)
    if path.exists():
        if verify.sha256(path.read_bytes()) != digest:
            raise StateError("SEGMENT_BYTES")
    else:
        _durable_write(path, data)
    return digest


def load_segment(root: Path, digest: str) -> tuple[str | None, list[dict[str, Any]]]:
    path = segment_path(root, digest)
    try:
        data = path.read_bytes()
    except OSError as error:
        raise StateError(f"SEGMENT_MISSING {digest[:12]}") from error
    if len(data) > MAX_GENERATION_BYTES or verify.sha256(data) != digest:
        raise StateError(f"SEGMENT_BYTES {digest[:12]}")
    try:
        body = json.loads(data.decode("utf-8"))
    except ValueError as error:
        raise StateError(f"SEGMENT_JSON {digest[:12]}") from error
    if (not isinstance(body, dict) or set(body) != {"previous", "attempts"} or not (body["previous"] is None or _text(body["previous"], 64, SHA_RE))
            or not isinstance(body["attempts"], list) or not 1 <= len(body["attempts"]) <= SEGMENT_SIZE):
        raise StateError("SEGMENT_SHAPE")
    return body["previous"], body["attempts"]


def _locator_ok(loc: Any, entry: Mapping[str, Any]) -> bool:
    if not isinstance(loc, dict) or set(loc) != LOCATOR_KEYS or type(loc["position"]) is not int or loc["position"] < 0:
        return False
    if loc["segment"] is None:
        return loc["position"] < len(entry["open"])
    return _text(loc["segment"], 64, SHA_RE) and loc["position"] < SEGMENT_SIZE


def validate_entry(entry: Any) -> None:
    """One issuer's history, constant size: the head of its hash-linked chain of sealed segments (audit history), the
    number of sealed attempts, open attempts, and the index admission reads - the locations of the newest verified
    attempts (at most 8; `truncated` when older ones exist) and the events settled since the producer's filing day."""
    if (not isinstance(entry, dict) or set(entry) != ENTRY_KEYS or not (entry["head"] is None or _text(entry["head"], 64, SHA_RE))
            or type(entry["sealed"]) is not int or entry["sealed"] < 0 or (entry["sealed"] == 0) != (entry["head"] is None)
            or not isinstance(entry["open"], list) or len(entry["open"]) > MAX_OPEN or not (entry["head"] or entry["open"])):
        raise StateError("ATTEMPT_ENTRY")
    index = entry["index"]
    if (not isinstance(index, dict) or set(index) != INDEX_KEYS or not isinstance(index["verified"], list)
            or len(index["verified"]) > INDEX_TAIL or not all(_locator_ok(loc, entry) for loc in index["verified"])
            or not isinstance(index["truncated"], bool)
            or not isinstance(index["settled"], list) or len(index["settled"]) > MAX_SETTLED
            or not all(isinstance(x, dict) and set(x) == {"key", "date"} and _text(x["key"], 60) and _text(x["date"], 10, DAY_RE)
                       for x in index["settled"])):
        raise StateError("ATTEMPT_INDEX")


def new_entry() -> dict[str, Any]:
    return {"head": None, "sealed": 0, "open": [], "index": {"verified": [], "truncated": False, "settled": []}}


def attempt_at(root: Path, entry: Mapping[str, Any], loc: Mapping[str, Any]) -> dict[str, Any]:
    if loc["segment"] is None:
        return entry["open"][loc["position"]]
    _, sealed = load_segment(root, loc["segment"])
    if loc["position"] >= len(sealed):
        raise StateError("SEGMENT_POSITION")
    return sealed[loc["position"]]


def last_attempt(root: Path, entry: Mapping[str, Any]) -> dict[str, Any] | None:
    if entry["open"]:
        return entry["open"][-1]
    return load_segment(root, entry["head"])[1][-1] if entry["head"] else None


def append_attempt(entry: dict[str, Any], attempt: dict[str, Any]) -> None:
    """Append to the open attempts and keep the index: a verified attempt becomes the producer (settled events dated
    before its filing day are dropped), a verified or blocked event is settled."""
    entry["open"].append(attempt)
    index = entry["index"]
    if attempt["outcome"] == "VERIFIED":
        index["verified"].append({"segment": None, "position": len(entry["open"]) - 1})
        if len(index["verified"]) > INDEX_TAIL:
            index["verified"] = index["verified"][-INDEX_TAIL:]
            index["truncated"] = True
        filed = routing_filed(attempt)
        index["settled"] = [x for x in index["settled"] if x["date"] >= filed]
    if attempt["outcome"] in ("VERIFIED", "BLOCKED") and not attempt["event_key"].startswith("unresolved:"):
        date = attempt["event"]["filed"] or attempt["attempted_at"][:10]
        if not any(x["key"] == attempt["event_key"] for x in index["settled"]):
            index["settled"].append({"key": attempt["event_key"], "date": date})
        if len(index["settled"]) > MAX_SETTLED:
            raise StateError("SETTLED_OVERFLOW")


def seal(root: Path, entry: dict[str, Any]) -> list[str]:
    """Move the oldest open attempts into new chained segments while more than SEGMENT_SIZE are open (locators follow);
    returns the digests written."""
    written = []
    while len(entry["open"]) > SEGMENT_SIZE:
        chunk = entry["open"][:SEGMENT_SIZE]
        digest = write_segment(root, chunk, entry["head"])
        written.append(digest)
        entry["head"] = digest
        entry["sealed"] += len(chunk)
        entry["open"] = entry["open"][SEGMENT_SIZE:]
        for loc in entry["index"]["verified"]:
            if loc["segment"] is None:
                if loc["position"] < SEGMENT_SIZE:
                    loc["segment"] = digest
                else:
                    loc["position"] -= SEGMENT_SIZE
    return written


def verify_history(root: Path, entry: Any) -> int:
    """Structural audit of a whole history, off the admission path: walks the segment chain from its head (every
    segment present, hash-verified, correctly linked), validates every attempt's shape and time order, checks the sealed
    count and that the index tail locates the newest verified attempts. It does not re-derive sources (admission
    re-derives the producer). Returns the number of attempts."""
    validate_entry(entry)
    segments = []
    digest = entry["head"]
    while digest is not None:
        previous, attempts = load_segment(root, digest)
        segments.append((digest, attempts))
        digest = previous
        if len(segments) > MAX_SEGMENTS:
            raise StateError("SEGMENT_CHAIN")
    ordered = [(d, pos, a) for d, attempts in reversed(segments) for pos, a in enumerate(attempts)]
    ordered += [(None, pos, a) for pos, a in enumerate(entry["open"])]
    if len(ordered) - len(entry["open"]) != entry["sealed"]:
        raise StateError("SEGMENT_COUNT")
    previous_at = ""
    verified = []
    for d, pos, a in ordered:
        validate_attempt(a)
        if a["attempted_at"] < previous_at:
            raise StateError("ATTEMPT_ORDER")
        previous_at = a["attempted_at"]
        if a["outcome"] == "VERIFIED":
            verified.append({"segment": d, "position": pos})
    # The index tail locates verified attempts in history order (a producer that a re-verification did not reproduce
    # is superseded by the newer decision and leaves the index, so the tail may skip it).
    tail = entry["index"]["verified"]
    positions = [verified.index(loc) if loc in verified else -1 for loc in tail]
    if any(p < 0 for p in positions) or positions != sorted(set(positions)):
        raise StateError("ATTEMPT_INDEX_MISMATCH")
    return len(ordered)


def validate_generation(gen: Any) -> None:
    """Global envelope (a violation blocks every enabled issuer); attempts are validated per issuer by `admit`."""
    if not isinstance(gen, dict) or set(gen) != GENERATION_KEYS or gen["schema"] != STATE_SCHEMA:
        raise StateError("GENERATION_SHAPE")
    parent = gen["parent"]
    if parent is not None and (not isinstance(parent, dict) or set(parent) != {"generation_id", "sha256"}
                               or not ID_RE.match(str(parent["generation_id"])) or not SHA_RE.match(str(parent["sha256"]))):
        raise StateError("GENERATION_PARENT")
    if not _text(gen["created_at"], 20, INSTANT_RE) or not _text(gen["generation_id"], 40, ID_RE):
        raise StateError("GENERATION_TIME")
    for key in ("implementation_sha256", "profiles_sha256", "baseline_registry_sha256", "baseline_approval_sha256"):
        if not _text(gen[key], 64, SHA_RE):
            raise StateError(f"GENERATION_{key.upper()}")
    if not _text(gen["verifier_version"], 40) or not _text(gen["normalizer_version"], 40):
        raise StateError("GENERATION_VERSIONS")
    issuers = gen["issuers"]
    if not isinstance(issuers, dict) or len(issuers) > 32:
        raise StateError("GENERATION_ISSUERS")
    if not isinstance(gen["detections"], dict) or len(gen["detections"]) > 32:
        raise StateError("GENERATION_DETECTIONS")
    for sym in issuers:
        if not _text(sym, 16, re.compile(r"^[A-Z][A-Z0-9.\-]{0,15}$")):
            raise StateError("GENERATION_ATTEMPTS")


def read_pointer(root: Path) -> dict[str, Any] | None:
    """None when the state root has never been written; StateError when it exists but is unusable."""
    pointer = root / "current.json"
    generations = root / "generations"
    if type(root) is B1Store:
        root.pointer_capture = root.capture_mutable(("current.json",))
    if not pointer.exists():
        if generations.exists() and any(generations.glob("*.json")):
            raise StateError("POINTER_MISSING")
        return None
    try:
        data = json.loads(pointer.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise StateError("POINTER_UNREADABLE") from error
    if not isinstance(data, dict) or set(data) != {"schema", "generation_id", "sha256"} or data["schema"] != POINTER_SCHEMA:
        raise StateError("POINTER_SHAPE")
    return data


def generation_at(root: Path, cutoff: str) -> dict[str, Any] | None:
    """The newest committed generation created at or before the cutoff (walking the verified parent chain)."""
    return generation_from(root, read_pointer(root), cutoff)


def generation_from(root: Path, pointer: Mapping[str, Any] | None, cutoff: str) -> dict[str, Any] | None:
    """As `generation_at`, from a pointer already read once."""
    return pinned_generation(root, pointer, cutoff)[0]


def pinned_generation(root: Path, pointer: Mapping[str, Any] | None, cutoff: str) -> tuple[dict[str, Any] | None, str | None]:
    """(generation, its verified file digest) at the cutoff, walking the verified parent chain from the pointer."""
    if pointer is None:
        return None, None
    sha = str(pointer["sha256"])
    gen = read_generation(root, str(pointer["generation_id"]), sha)
    while gen["created_at"] > cutoff:
        if gen["parent"] is None:
            return None, None
        sha = gen["parent"]["sha256"]
        gen = read_generation(root, gen["parent"]["generation_id"], sha)
    return gen, sha


def publish_generation(root: Path, gen: Mapping[str, Any], expected_parent: Mapping[str, Any] | None,
                       carried: set[str] | frozenset[str] = frozenset(), written: set[str] | frozenset[str] = frozenset()) -> str:
    """Write the immutable generation file, then move the pointer; a pre-existing id or a moved pointer refuses.
    `carried` issuers are unreadable histories carried forward unchanged as their fail-closed barrier. Only the
    segments `written` by this publication are checked here (older segments are immutable references carried on;
    admission reads the ones it needs and `verify_history` audits the rest), so missing audit history never stops
    another issuer."""
    validate_generation(gen)
    for sym, entry in gen["issuers"].items():
        if sym in carried:
            continue
        validate_entry(entry)
        for a in entry["open"]:
            validate_attempt(a)
    for digest in written:
        load_segment(root, digest)  # actual digest-bound readback, also in the capability lane
    for entry in gen["detections"].values():
        validate_detections(entry)
    current = read_pointer(root)
    if (current is None) != (expected_parent is None) or (current is not None and (
            current["generation_id"] != expected_parent["generation_id"] or current["sha256"] != expected_parent["sha256"])):
        raise StateError("POINTER_MOVED")
    data = json.dumps(gen, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8")
    path = _generation_path(root, gen["generation_id"])
    if path.exists():
        raise StateError("GENERATION_EXISTS")
    _durable_write(path, data)
    digest = verify.sha256(data)
    pointer = {"schema": POINTER_SCHEMA, "generation_id": gen["generation_id"], "sha256": digest}
    if type(root) is B1Store:
        # Compare the exact captured current pointer, not a newly adopted later value.
        root.write(("current.json",), json.dumps(pointer, sort_keys=True).encode("utf-8"),
                   expected=root.pointer_capture)
    else:
        _durable_write(root / "current.json", json.dumps(pointer, sort_keys=True).encode("utf-8"))
    return digest


# ------------------------------------------------------------------------------------------------ admission

def predecessor_view(effective: Mapping[str, Any], baseline: Mapping[str, Any] | None) -> dict[str, Any]:
    """What a successor may take from its predecessor: its anchor (ordering) only. Release channels come from the
    curated baseline record, never from a stored machine record; no number is inherited."""
    return dict(effective, release_channels=dict((baseline or {}).get("release_channels") or {}))


def rederive(root: Path, profile: Mapping[str, Any], effective: Mapping[str, Any], attempt: Mapping[str, Any],
             allow_replay: bool = False, baseline: Mapping[str, Any] | None = None) -> dict[str, Any]:
    captures = {key: load_capture(root, raw_sha) for key, raw_sha in attempt["captures"].items()}
    if not allow_replay and any(str(c["role"]).startswith("REPLAY_") for c in captures.values()):
        raise StateError("REPLAY_CAPTURE")
    return verify.build_successor(profile, predecessor_view(effective, baseline), attempt["event"], captures, attempt["attempted_at"])


def admit(root: Path, gen: Mapping[str, Any] | None, cutoff: str, profiles: Mapping[str, Mapping[str, Any]],
          curated: Mapping[str, Mapping[str, Any]], ident: Mapping[str, str], allow_replay: bool = False,
          entries: Mapping[str, Mapping[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    """Per enabled issuer: {"mode", "reason", "detail", "effective", "producer", "attempt", "detections", "overflow"}.

    Bounded work per issuer: the index's producer (newest verified attempt) is re-derived from its stored bytes with its
    predecessor (the verified attempt before it, or the curated record) as the only input; the newest attempt gives the
    mode; open attempts (at most 64) are validated; the issuer's monotonic detection set, plus the open attempts'
    observations, minus what the re-derived producer accounts for (its consumed identities, items dated strictly before
    its filing day), is what remains unresolved. No older decision is operative. `effective` is the record the release
    checker and the updater continue from; never a display input by itself. `entries` replaces the generation's
    issuer entries (the updater's in-memory state)."""
    out: dict[str, dict[str, Any]] = {}
    for sym in profiles:
        out[sym] = {"mode": "CURATED", "reason": None, "detail": None, "effective": curated.get(sym), "producer": None,
                    "attempt": None, "detections": [], "overflow": False, "generation_id": None if gen is None else gen["generation_id"]}
    if gen is None:
        return out
    identity_ok = all(gen[k] == ident[k] for k in IDENTITY_KEYS)
    issuers = entries if entries is not None else gen["issuers"]
    # Every attempt admission reads must precede both the requested cutoff and the generation that holds it.
    horizon = min(cutoff, gen.get("created_at") or cutoff)
    for sym in sorted(set(issuers) | set(gen.get("detections") or {})):
        state = out.get(sym)
        if state is None:
            continue  # history of a profile no longer enabled: never admitted
        if not identity_ok:
            state.update(mode="BLOCKED", reason="APPROVAL_BINDING", effective=None, detail="implementation, policy or baseline changed; awaiting re-verification")
            continue
        effective, producer = curated.get(sym), None
        mode, reason, detail, last = "CURATED", None, None, None
        detections: list[dict[str, Any]] = []
        overflow = False
        try:
            entry = issuers.get(sym)
            if entry is not None:
                validate_entry(entry)
                previous_at = ""
                for attempt in entry["open"]:
                    validate_attempt(attempt)
                    if attempt["attempted_at"] < previous_at:
                        raise StateError("ATTEMPT_ORDER")
                    previous_at = attempt["attempted_at"]
                    if attempt["attempted_at"] > horizon:
                        raise StateError("ATTEMPT_AFTER_CUTOFF")
                    detections.extend(attempt["event"]["later_documents"])
                verified = entry["index"]["verified"]
                if not verified and entry["index"]["truncated"]:
                    raise StateError("ATTEMPT_INDEX_EXHAUSTED")
                if verified:
                    producer = attempt_at(root, entry, verified[-1])
                    validate_attempt(producer)
                    if producer["attempted_at"] > horizon:
                        raise StateError("ATTEMPT_AFTER_CUTOFF")
                    if len(verified) > 1:
                        before = attempt_at(root, entry, verified[-2])
                        validate_attempt(before)
                        if before["outcome"] != "VERIFIED" or before["attempted_at"] > producer["attempted_at"]:
                            raise StateError("ATTEMPT_INDEX_MISMATCH")
                        predecessor = before["record"]
                    elif entry["index"]["truncated"]:
                        raise StateError("ATTEMPT_INDEX_EXHAUSTED")
                    else:
                        predecessor = curated.get(sym)
                    if producer["outcome"] != "VERIFIED" or predecessor is None or producer["predecessor_sha256"] != record_sha256(predecessor):
                        raise StateError("PREDECESSOR_CHAIN")
                    # Admission: the installed verifier must reproduce the producing release exactly from its stored bytes.
                    again = rederive(root, profiles[sym], predecessor, producer, allow_replay, curated.get(sym))
                    if again["outcome"] != "VERIFIED" or (verify.canonical_json(again["record"]) != verify.canonical_json(producer["record"])
                                                          or verify.canonical_json(again["decisions"]) != verify.canonical_json(producer["decisions"])):
                        raise StateError("REDERIVATION_RECORD")
                    effective = producer["record"]
                last = last_attempt(root, entry)
                if last is not None:
                    validate_attempt(last)
                    if last["attempted_at"] > horizon:
                        raise StateError("ATTEMPT_AFTER_CUTOFF")
                    if last["outcome"] == "VERIFIED":
                        if producer is None or verify.canonical_json(last) != verify.canonical_json(producer):
                            raise StateError("ATTEMPT_INDEX_MISMATCH")
                        mode = "AUTO_VERIFIED"
                    else:
                        mode, reason, detail = last["outcome"], last["reason"], last["detail"]
                        if producer is None and effective is None:
                            raise StateError("PREDECESSOR_CHAIN")
            store = (gen.get("detections") or {}).get(sym)
            if store is not None:
                validate_detections(store)
                detections.extend(store["documents"])
                overflow = store["overflow"]
            detections = _material_documents([{"later_documents": detections}])
            if producer is not None:
                consumed, filed = consumed_identities(producer), routing_filed(producer)
                detections = [d for d in detections if (str(d["channel"]), str(d["id"]), str(d["date"])) not in consumed and not str(d["date"]) < filed]
        except (StateError, KeyError, TypeError, ValueError, AttributeError, IndexError) as error:
            # Malformed stored state is corrupt; well-formed state that the sources do not reproduce is unbound.
            malformed = not isinstance(error, StateError) or str(error).startswith(("ATTEMPT_", "EVENT_", "SEGMENT_"))
            state.update(mode="BLOCKED", reason="STATE_CORRUPT" if malformed else "APPROVAL_BINDING", effective=None, producer=None,
                         detail=f"{type(error).__name__}: {error}"[:300])
            continue
        state.update(mode=mode, reason=reason, detail=detail, effective=effective, producer=producer, attempt=last,
                     detections=detections, overflow=overflow)
    return out


# ------------------------------------------------------------------------------------------------ release-check gate

def reference(record: Mapping[str, Any]) -> tuple[str | None, str | None]:
    """(guidance reference document id, its published date) of the whole active claim set (the registry's helper)."""
    ref = revenue_guidance.guidance_reference(record)
    return ref["document_id"], ref["published_date"]


def routing_filed(attempt: Mapping[str, Any]) -> str:
    for decision in attempt.get("decisions") or []:
        if decision.get("kind") == "ROUTING":
            filed = (decision.get("operands") or {}).get("filed")
            if isinstance(filed, str) and DAY_RE.match(filed):
                return filed
    raise StateError("ROUTING_FILED")


def consumed_identities(producer: Mapping[str, Any] | None) -> set[tuple[str, str, str]]:
    """(channel, id, date) of the publications the admitted producing attempt proved to be this very results event
    (its EDGAR filings and the IR/wire copies whose captured pages state the same outlook passage)."""
    out = set()
    for decision in (producer or {}).get("decisions") or []:
        if decision.get("kind") == "ROUTING":
            for c in (decision.get("operands") or {}).get("consumed") or []:
                out.add((str(c.get("channel")), str(c.get("id")), str(c.get("date"))))
    return out


def _material_documents(rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    seen, out = set(), []
    for row in rows:
        for d in row.get("later_documents") or []:
            if isinstance(d, Mapping) and d.get("disposition") in MATERIAL:
                key = (d.get("channel"), d.get("id"), d.get("date"))
                if key not in seen:
                    seen.add(key)
                    out.append(dict(d))
    return out


def receipt_rows(receipts: Mapping[str, Any] | None, symbol: str, ref: str | None, cutoff: str) -> list[dict[str, Any]]:
    rows = ((receipts or {}).get("issuers") or {}).get(symbol) or []
    if not isinstance(rows, list):
        return []
    return [r for r in rows if isinstance(r, dict) and r.get("guidance_document_id") == ref
            and INSTANT_RE.match(str(r.get("checked_at", ""))) and r["checked_at"] <= cutoff]


def unaccounted(record: Mapping[str, Any], rows: list[Mapping[str, Any]], producer: Mapping[str, Any] | None,
                detections: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Material documents ever listed for this record's reference (any receipt up to the cutoff, plus detections the
    updater recorded) that the record did not itself consume and that are not in its human-reviewed list. Absence
    from a later feed read never removes an item."""
    consumed = consumed_identities(producer)
    # A human review list accounts for items of a curated record only; a machine record inherits no human disposition.
    reviewed = set() if producer is not None else {
        str(d.get("id")) for d in record.get("reviewed_later_documents") or [] if d.get("disposition") == "REVIEWED_IRRELEVANT"}
    out = []
    for d in _material_documents(list(rows) + [{"later_documents": list(detections)}]):
        if (str(d.get("channel")), str(d.get("id")), str(d.get("date"))) in consumed or str(d.get("id")) in reviewed:
            continue
        out.append(d)
    return out


def receipt_admission(receipts: Mapping[str, Any] | None, symbol: str, record: Mapping[str, Any], cutoff: str,
                      producer: Mapping[str, Any] | None = None, detections: list[Mapping[str, Any]] = ()) -> dict[str, Any]:
    """The structured receipt decision for one record at the cutoff (the record's own reference only).

    The newest receipt of the record's reference must pass the registry's strict receipt validation (issuer, digest,
    coverage, channel set and hosts, anchor, reference, age, recomputed status); only its terminal raw status
    (RESULTS_PUBLISHED / REVIEW_REQUIRED) is then eligible for source-proven accounting, and no material document ever
    listed or detected for the reference may be left unaccounted. The raw receipt is returned unchanged; `decision` is
    None when the record is usable, else the reason."""
    ref, published = reference(record)
    rows = receipt_rows(receipts, symbol, ref, cutoff)
    quarters = record.get("reported_quarters") or []
    anchor = quarters[-1]["end"] if quarters else None
    out: dict[str, Any] = {"reference": ref, "published": published, "anchor": anchor, "receipt": None, "receipt_digest": None,
                           "receipt_status": None, "checked_at": None, "valid": False, "status": None, "error": None,
                           "rows": [{"checked_at": r.get("checked_at"), "digest": r.get("digest"), "status": r.get("status")} for r in rows],
                           "consumed": sorted([list(c) for c in consumed_identities(producer)]), "unaccounted": [], "decision": None}
    if not rows:
        out["decision"] = "RECEIPT_MISSING"
        return out
    newest = max(rows, key=lambda r: r["checked_at"])
    channels = record.get("release_channels") or {}
    moment = datetime.strptime(cutoff, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    valid, status, error = revenue_guidance.validate_receipt(
        newest, symbol, anchor, ref, moment,
        reviewed_later_documents=[] if producer is not None else (record.get("reviewed_later_documents") or []),
        guidance_published_date=published,
        expected_cik=channels.get("sec_cik"), expected_wire_symbol=channels.get("wire_symbol"), expected_ir=channels.get("ir"))
    out.update(receipt=json.loads(json.dumps(newest)), receipt_digest=newest.get("digest"), receipt_status=newest.get("status"),
               checked_at=newest.get("checked_at"), valid=valid, status=status, error=error)
    if not valid and error not in ("RESULTS_PUBLISHED", "REVIEW_REQUIRED"):
        out["decision"] = f"RECEIPT_{error}"
        return out
    left = unaccounted(record, rows, producer, detections)
    out["unaccounted"] = [{k: d.get(k) for k in ("channel", "id", "date", "disposition")} for d in left]
    if any(d.get("disposition") == "RESULTS_RELEASE" for d in left):
        out["decision"] = "RECEIPT_RESULTS_PUBLISHED"
    elif left:
        out["decision"] = "RECEIPT_REVIEW_REQUIRED"
    return out


def receipt_gate(receipts: Mapping[str, Any] | None, symbol: str, record: Mapping[str, Any], cutoff: str,
                 producer: Mapping[str, Any] | None = None, detections: list[Mapping[str, Any]] = ()) -> str | None:
    """None when the record is usable at the cutoff, otherwise the reason (see `receipt_admission`)."""
    return receipt_admission(receipts, symbol, record, cutoff, producer, detections)["decision"]


def resolve_issuers(root: Path, cutoff: str, profiles_bytes: bytes, registry_bytes: bytes, approval_bytes: bytes,
                    curated: Mapping[str, Mapping[str, Any]], receipts: Mapping[str, Any] | None = None,
                    allow_replay: bool = False) -> dict[str, dict[str, Any]]:
    """Per enabled issuer at the cutoff: {"mode": CURATED|AUTO_VERIFIED|WAITING|BLOCKED|SUSPENDED, "record",
    "effective", "reason", "detail", "attempt", "generation_id"}. `record` (usable for revenue) is set only in
    CURATED and AUTO_VERIFIED mode; with `receipts` (the release-check cache) every such record, curated or automatic,
    with or without any auto-update state, must also pass `receipt_gate`, else the issuer is SUSPENDED."""
    profiles = verify.validate_profiles(json.loads(profiles_bytes.decode("utf-8")))
    ident = identity(profiles_bytes, registry_bytes, approval_bytes)
    try:
        gen = generation_at(root, cutoff)
    except StateError as error:
        return {sym: {"mode": "BLOCKED", "reason": "STATE_CORRUPT", "detail": str(error), "record": None, "effective": None,
                      "attempt": None, "generation_id": None} for sym in profiles}
    admitted = admit(root, gen, cutoff, profiles, curated, ident, allow_replay)
    result = {}
    for sym, s in admitted.items():
        usable = s["mode"] in ("CURATED", "AUTO_VERIFIED") and s["effective"] is not None
        state = {"mode": s["mode"], "reason": s["reason"], "detail": s["detail"], "record": s["effective"] if usable else None,
                 "effective": s["effective"], "attempt": s["attempt"], "generation_id": s["generation_id"]}
        if usable and s["overflow"]:
            state.update(mode="SUSPENDED", reason="DETECTIONS_OVERFLOW", record=None)
        elif usable and receipts is not None:
            gate = receipt_gate(receipts, sym, s["effective"], cutoff, s["producer"], s["detections"])
            if gate is not None:
                state.update(mode="SUSPENDED", reason=gate, record=None)
        result[sym] = state
    return result


# ------------------------------------------------------------------------------------------------ effective inputs (B1)

# The one effective-input boundary shared by the release checker, the updater, the order model and the lazy sealer
# (ORDERS-V3-AUTOUPDATE-01 B1). Automatic mode is limited to these issuers in this integration; every other issuer
# keeps its curated path unchanged.
SUPPORTED_AUTO = ("MU", "NVDA", "NBIS")  # recognized capability, NOT default profile activation
DEFAULT_STATE_ROOT = revenue_guidance.ROOT / "data" / "cache" / "revenue_guidance_autoupdate"
PROFILES_DEFAULT = revenue_guidance.ROOT / "config" / "revenue-guidance-extraction-profiles-v1.json"
MANIFEST_SCHEMA = "revenue-guidance-effective-inputs-v1"
AUTO_EVIDENCE_VERSION = "auto-admission-evidence-v1"
DISPOSITIONS = ("CURATED", "AUTO_VERIFIED", "WAITING", "BLOCKED", "SUSPENDED")
class B1Store:
    """Typed held-capability operands, never a filesystem path or callback adapter.

    Must be constructed inside the lease's ONE namespace epoch. Every byte comes
    from held descent or native readback; caches are confined to that live epoch.
    Control baseline/code bytes are protected and independently release-bound.
    """
    def __init__(self, lease):
        import revenue_guidance_storage as storage
        if type(lease) not in (storage.NativeStorageLease, storage.NativeIssuerContext):
            raise EffectiveInputsError("CAPABILITY_TYPE")
        if lease.limits.profile != "b1" or lease.anchor.schema_version != "guidance-provider-storage-v2":
            raise EffectiveInputsError("CAPABILITY_LAYOUT")
        lease._namespace_guard()
        self.lease, self.epoch = lease, lease._live_operation
        self._bytes = {}
        self._mutables = {}
        self.pointer_capture = None

    def require_live(self):
        self.lease._namespace_guard()
        if self.epoch is not self.lease._live_operation:
            raise EffectiveInputsError("CAPABILITY_EPOCH")

    def __truediv__(self, name):
        return B1Object(self, (name,))

    def exists(self):
        self.require_live()
        return True

    def is_dir(self):
        return self.exists()

    def iterdir(self):
        return self.children(())

    def _directory(self, components):
        self.require_live()
        if not components:
            return self.lease.b1_handle, False
        return self.lease.open_directory(("b1",) + tuple(components)), True

    def children(self, components):
        h, close = self._directory(components)
        try:
            return tuple(B1Object(self, tuple(components) + (n,)) for n in self.lease.enumerate_directory(h))
        finally:
            if close:
                self.lease.close_owned(h)

    def read(self, components):
        import revenue_guidance_windows as windows
        self.require_live()
        names = tuple(components)
        if names in self._bytes:
            return self._bytes[names]
        raw = len(names) == 3 and (names[0] == "captures" or names[:2] == ("outputs", "cache")) and bool(SHA_RE.fullmatch(names[-1]))
        try:
            data, _ = self.lease.capture_bytes(("b1",) + names, 16 * 1024 * 1024 if raw else MAX_GENERATION_BYTES,
                                               raw_document=raw, historical=raw)
        except windows.StorageObjectMissingError:
            raise FileNotFoundError("CAPABILITY_OBJECT_MISSING") from None
        self._bytes[names] = data
        return data

    def input(self, name):
        self.require_live()
        if name == "receipts":
            return self.read(("receipts.json",))
        if name not in ("registry", "approval", "profiles", "config"):
            raise EffectiveInputsError("CAPABILITY_INPUT_NAME")
        return self._control(name + ".json")

    def implementation(self, name):
        if name not in IMPLEMENTATION_FILES:
            raise EffectiveInputsError("CAPABILITY_IMPLEMENTATION_NAME")
        return self._control(name)

    def _control(self, name):
        self.require_live()
        expected = dict(self.lease.anchor.input_digests).get(name)
        if expected is None:
            raise EffectiveInputsError("CAPABILITY_CONTROL_BINDING")
        key = ("control", name)
        if key not in self._bytes:
            self._bytes[key] = self.lease.capture_bytes(key, MAX_GENERATION_BYTES, bytes.fromhex(expected))[0]
        return self._bytes[key]

    def capture_mutable(self, components):
        names = tuple(components)
        h, close = self._directory(names[:-1])
        try:
            expected = self.lease.capture_mutable(h, names[-1])
            self._mutables[names] = expected
            if expected.data is not None:
                self._bytes[names] = expected.data
            else:
                self._bytes.pop(names, None)
            return expected
        finally:
            if close:
                self.lease.close_owned(h)

    def write(self, components, data, *, expected=None):
        self.require_live()
        names = tuple(components)
        if type(data) is not bytes:
            raise EffectiveInputsError("CAPABILITY_WRITE_BYTES")
        mutable = (len(names) == 1 and names[0] in ("current.json", "queue.json", "store_usage.json", "receipts.json")) or (
            len(names) == 2 and names[0] == "outputs" and names[1] in ("ledger.json", "cision.json", "capture-index.json"))
        h, close = self._directory(names[:-1])
        try:
            stage = "stage-" + secrets.token_hex(12)
            if mutable:
                if expected is None:
                    expected = self._mutables.get(names)
                if expected is None:
                    expected = self.lease.capture_mutable(h, names[-1])
                actual = self.lease.replace_mutable(h, names[-1], stage, data, expected)
            else:
                raw = len(names) == 3 and (names[0] == "captures" or names[:2] == ("outputs", "cache")) and bool(SHA_RE.fullmatch(names[-1]))
                if raw:
                    self.lease.budget.admit_capture(len(data), raw_document=True)
                actual = self.lease.publish_named_immutable(h, names[-1], stage, data, hashlib.sha256(data).digest(), raw_document=raw)
            self._bytes[names] = data
            self._mutables.pop(names, None)
        finally:
            if close:
                self.lease.close_owned(h)
        return actual  # ORIGINAL native verified/readback result, only after confirmed owned close

    def ensure_capture_bucket(self, digest):
        import revenue_guidance_windows as windows
        parent, close = self._directory(("captures",))
        try:
            try:
                bucket = self.lease.create_directory(parent, digest[:2])
            except windows.StorageObjectExistsError:
                bucket = self.lease.open_directory(("b1", "captures", digest[:2]))
            self.lease.close_owned(bucket)
        finally:
            if close:
                self.lease.close_owned(parent)


class B1OutputControlFault(BaseException):
    """Original output custody/control failure, not optional market absence."""


class B1Outputs:
    """Explicit bounded output-only subtree; no authority/pointer/gir1 projection.

    Original native publication, independent digest, actual captured mutable
    compare/readback. Unknown reservations/layouts remain unavailable; no deletion.
    """
    MAX_BUNDLES = 64
    MAX_BYTES = 64 * 1024 * 1024
    _ARTIFACT = re.compile(r"^(rank|body|record)-[0-9a-f]{64}\.json$")

    def __new__(cls, store):
        # Data/readback cache ONLY, bound to the ORIGINAL actual lease/epoch.
        # Fresh B1Store input snapshots must not rescan all retained output bytes.
        if cls is not B1Outputs or type(store) is not B1Store:
            raise EffectiveInputsError("OUTPUT_OPERAND")
        store.require_live()
        old = getattr(store.lease, "_guidance_outputs_owner", None)
        if old is not None:
            if type(old) is not cls or old.store.lease is not store.lease:
                raise StateError("OUTPUT_ADMISSION_UNKNOWN")
            if old.store.epoch is store.epoch:
                if old._initialization != "READY":
                    raise StateError("OUTPUT_ADMISSION_UNKNOWN")  # no retry/repair after interrupted admission
                old.store.require_live()
                return old
        owner = super().__new__(cls)
        owner.store, owner._initialization = store, "INITIALIZING"
        store.lease._guidance_outputs_owner = owner  # actual readback graph rooted BEFORE admission
        return owner

    def __init__(self, store):
        import revenue_guidance_windows as windows
        if type(store) is not B1Store:
            raise EffectiveInputsError("OUTPUT_OPERAND")
        store.require_live()
        if self._initialization == "READY":
            self.store.require_live()
            self._ledger()  # same-epoch owner still refuses unknown reservations
            return
        self.store = store
        self._artifact_bytes, self._payload_sizes = {}, {}
        self._payload_bytes = 0
        self._ledger_value = self._index_value = self._inventory = None
        self._ledger_raw = self._index_raw = self._cache_inventory = None
        self._ledger_identity = self._index_identity = self._parent_identity = None
        self._cision_raw = self._cision_identity = None
        self._cision_admitted = False
        self._pack_bytes = {}  # one actual SHA read per pack per live epoch
        created = False
        try:
            directory = store.lease.open_directory(("b1", "outputs"))
        except windows.StorageObjectMissingError:
            directory = store.lease.create_directory(store.lease.b1_handle, "outputs")
            created = True  # only positively NEW may initialize honest machine accounting
        store.lease.close_owned(directory)
        if created:
            self._save_ledger({"schema": "guidance-output-accounting-v1", "bytes": 0,
                               "entries": [], "captures": [], "pending": None})
            parent, owned = store._directory(("outputs",))
            try:
                cache = store.lease.create_directory(parent, "cache")
                store.lease.close_owned(cache)
            finally:
                if owned:
                    store.lease.close_owned(parent)
            store.capture_mutable(("outputs", "capture-index.json"))
            store.write(("outputs", "capture-index.json"), b'{"schema":"guidance-public-capture-index-v2","entries":{},"progress":{}}')
            # Initialization writes are not a substitute for the first actual
            # namespace inventory. Re-admit the positively new completed layout.
            self._ledger_value = None
        self._ledger()
        self._capture_index()
        self.load_cision()  # bounded control overhead admitted BEFORE any payload publication
        self._initialization = "READY"

    @staticmethod
    def _output_json(raw):
        def pairs(items):
            out = {}
            for key, value in items:
                if key in out:
                    raise StateError("OUTPUT_JSON_UNKNOWN")
                out[key] = value
            return out
        if type(raw) is not bytes or len(raw) > MAX_GENERATION_BYTES:
            raise StateError("OUTPUT_JSON_UNKNOWN")
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(StateError("OUTPUT_JSON_UNKNOWN")))
        stack, nodes = [(value, 0)], 0
        while stack:
            item, depth = stack.pop()
            nodes += 1
            if depth > 32 or nodes > 1000000:
                raise StateError("OUTPUT_JSON_UNKNOWN")
            if type(item) is dict:
                stack.extend((child, depth + 1) for child in item.values())
            elif type(item) is list:
                stack.extend((child, depth + 1) for child in item)
        return value

    def _ledger(self):
        self.store.require_live()
        if self._ledger_value is not None:
            if (self._ledger_value["pending"] is not None or
                    not self._payload_bytes <= self._ledger_value["bytes"] <= self.MAX_BYTES):
                raise StateError("OUTPUT_ACCOUNTING_UNKNOWN")
            return self._ledger_value
        expected = self.store.capture_mutable(("outputs", "ledger.json"))
        if (expected.data is None or (self._ledger_raw is not None and
                (expected.data != self._ledger_raw or expected.identity != self._ledger_identity))):
            raise StateError("OUTPUT_ACCOUNTING_UNKNOWN")
        try:
            ledger = self._output_json(expected.data)
            if (type(ledger) is not dict or set(ledger) != {"schema", "bytes", "entries", "captures", "pending"}
                    or ledger["schema"] != "guidance-output-accounting-v1" or type(ledger["bytes"]) is not int
                    or not 0 <= ledger["bytes"] <= self.MAX_BYTES or type(ledger["entries"]) is not list
                    or len(ledger["entries"]) > self.MAX_BUNDLES or ledger["pending"] is not None
                    or any(type(x) is not str or not SHA_RE.fullmatch(x) for x in ledger["entries"])
                    or len(set(ledger["entries"])) != len(ledger["entries"]) or type(ledger["captures"]) is not list
                    or len(ledger["captures"]) > 256 or len(set(ledger["captures"])) != len(ledger["captures"])
                    or any(type(x) is not str or not SHA_RE.fullmatch(x) for x in ledger["captures"])):
                raise ValueError()
            names = {item.name for item in (self.store / "outputs").iterdir()}
            if len(names) > 3 * self.MAX_BUNDLES + 4 or any(
                    name not in ("ledger.json", "cision.json", "cache", "capture-index.json") and not self._ARTIFACT.fullmatch(name) for name in names):
                raise ValueError()
            accounted = {"ledger.json", "cache", "capture-index.json"}
            if "cision.json" in names:
                accounted.add("cision.json")
            for record_digest in ledger["entries"]:
                record_name = "record-" + record_digest + ".json"
                if record_name not in names:
                    raise ValueError()
                raw_record = self._admit_artifact("record", record_digest)
                if self._payload_bytes > ledger["bytes"]:
                    raise ValueError()
                record = self._output_json(raw_record)
                if (type(record) is not dict or record.get("schema") != "guidance-local-completion-v1" or
                        not SHA_RE.fullmatch(str(record.get("ranking_sha256"))) or
                        not SHA_RE.fullmatch(str(record.get("output_sha256")))):
                    raise ValueError()
                accounted.update((record_name, "rank-" + record["ranking_sha256"] + ".json",
                                  "body-" + record["output_sha256"] + ".json"))
            if names != accounted:
                raise ValueError()  # orphan/missing/foreign immutable output, never guessed repair
            # Every UNIQUE artifact name contributes its actual held/digest-bound
            # length once, even if many completion records reference the same rank/body.
            for name in names:
                if self._ARTIFACT.fullmatch(name):
                    kind, tail = name.split("-", 1)
                    self._admit_artifact(kind, tail[:-5])
                    if self._payload_bytes > ledger["bytes"]:
                        raise ValueError()  # understated writable accounting is NOT capacity proof
            if self._parent_identity is not None and expected.parent_identity != self._parent_identity:
                raise ValueError()
            self._ledger_value, self._ledger_raw = ledger, expected.data
            self._ledger_identity, self._parent_identity = expected.identity, expected.parent_identity
            self._inventory = names
            return ledger
        except (ValueError, UnicodeError):
            raise StateError("OUTPUT_ACCOUNTING_UNKNOWN") from None

    def _remember_payload(self, key, raw):
        # key is the actual immutable namespace name, not a logical observation
        # or repeated record reference. A higher old counter is NEVER refunded.
        if key in self._payload_sizes:
            if self._payload_sizes[key] != len(raw):
                raise StateError("OUTPUT_PAYLOAD_CHANGED")
            return
        self._payload_sizes[key] = len(raw)
        self._payload_bytes += len(raw)
        if self._payload_bytes > self.MAX_BYTES:
            raise StateError("OUTPUT_CAPACITY_UNAVAILABLE")

    def _admit_artifact(self, kind, sha):
        name = kind + "-" + sha + ".json"
        if name not in self._artifact_bytes:
            raw = self.read(kind, sha)  # ORIGINAL held read, independent digest, actual size
            self._remember_payload(("artifact", name), raw)
            self._artifact_bytes[name] = raw
        return self._artifact_bytes[name]

    def _save_ledger(self, ledger):
        expected = self.store.capture_mutable(("outputs", "ledger.json"))
        if (expected.data != self._ledger_raw or expected.identity != self._ledger_identity or
                (self._parent_identity is not None and expected.parent_identity != self._parent_identity)):
            raise StateError("OUTPUT_ACCOUNTING_CHANGED")
        raw = json.dumps(ledger, sort_keys=True, allow_nan=False).encode("utf-8")
        actual = self.store.write(("outputs", "ledger.json"), raw, expected=expected)
        self._ledger_identity, self._parent_identity = actual.identity, expected.parent_identity
        # Detached confirmed value: a caller clearing its local pending field
        # before a fallible final save must NOT clear the live unknown latch.
        self._ledger_value, self._ledger_raw = self._output_json(raw), raw

    def _capture_index(self):
        self.store.require_live()
        ledger = self._ledger()  # cached index may not bypass an unresolved reservation
        if self._index_value is not None:
            return self._index_value
        expected = self.store.capture_mutable(("outputs", "capture-index.json"))
        try:
            if expected.parent_identity != self._parent_identity:
                raise ValueError()
            index = self._output_json(expected.data)
            if (type(index) is not dict or set(index) != {"schema", "entries", "progress"} or index["schema"] != "guidance-public-capture-index-v2"
                    or type(index["entries"]) is not dict or len(index["entries"]) > 1024):
                raise ValueError()
            names = {item.name for item in self.store.children(("outputs", "cache"))}
            if names != set(ledger["captures"]) or len(names) > 256:
                raise ValueError()
            for key, row in index["entries"].items():
                if (type(key) is not str or not SHA_RE.fullmatch(key) or type(row) is not dict or
                        set(row) != {"url", "sha256", "pack", "offset", "retrieved_at", "bytes", "status", "http_status"} or
                        type(row["url"]) is not str or len(row["url"]) > 4096 or
                        type(row["bytes"]) is not int or not 0 <= row["bytes"] <= 16 * 1024 * 1024 or
                        type(row["offset"]) is not int or row["offset"] < 0 or
                        type(row["retrieved_at"]) is not str or not INSTANT_RE.fullmatch(row["retrieved_at"]) or
                        row["status"] not in ("CAPTURED", "HTTP_UNAVAILABLE", "TRANSPORT_UNAVAILABLE") or
                        (row["http_status"] is not None and (type(row["http_status"]) is not int or not 100 <= row["http_status"] <= 599))):
                    raise ValueError()
                if ((row["status"] == "CAPTURED" and row["http_status"] != 200) or
                        (row["status"] == "HTTP_UNAVAILABLE" and (row["http_status"] is None or row["http_status"] == 200)) or
                        (row["status"] == "TRANSPORT_UNAVAILABLE" and row["http_status"] is not None)):
                    raise ValueError()
                datetime.strptime(row["retrieved_at"], "%Y-%m-%dT%H:%M:%SZ")
                if row["status"] == "CAPTURED":
                    if (type(row["sha256"]) is not str or not SHA_RE.fullmatch(row["sha256"]) or
                            type(row["pack"]) is not str or row["pack"] not in names or
                            row["offset"] + row["bytes"] > 16 * 1024 * 1024):
                        raise ValueError()
                elif row["pack"] is not None or row["sha256"] is not None or row["bytes"] != 0 or row["offset"] != 0:
                    raise ValueError()
            # All retained packs count, including old packs no active URL slot
            # references. Native actual sizes/digests, NOT index row lengths or
            # ledger totals, establish the conservative retained-payload minimum.
            for sha in names:
                self.store.require_live()
                raw = self.store.lease.capture_bytes(("b1", "outputs", "cache", sha),
                    16 * 1024 * 1024, bytes.fromhex(sha), raw_document=True, historical=True)[0]
                self._remember_payload(("cache", sha), raw)
                self._pack_bytes[sha] = raw
                if self._payload_bytes > ledger["bytes"]:
                    raise ValueError()  # reject BEFORE any new reservation/capture/publication
            for row in index["entries"].values():
                if row["status"] == "CAPTURED":
                    self.store.require_live()
                    pack = self._pack_bytes[row["pack"]]
                    if row["offset"] + row["bytes"] > len(pack):
                        raise ValueError()
                    part = pack[row["offset"]:row["offset"] + row["bytes"]]
                    if hashlib.sha256(part).hexdigest() != row["sha256"]:
                        raise ValueError()
            progress = index["progress"]
            if type(progress) is not dict or len(progress) > 8:
                raise ValueError()
            for plan, cursor in progress.items():
                if type(plan) is not str or not SHA_RE.fullmatch(plan) or type(cursor) is not int or not 0 <= cursor < 1024:
                    raise ValueError()
            self._index_value, self._index_raw = index, expected.data
            self._index_identity = expected.identity
            self._cache_inventory = names
            return index
        except (ValueError, AttributeError, TypeError, KeyError, UnicodeError):
            raise StateError("OUTPUT_CAPTURE_UNKNOWN") from None

    def captured_public(self, key, url, moment, max_age_hours):
        row = self._capture_index()["entries"].get(key)
        if row is None or row["url"] != url:
            return None
        captured_at = datetime.strptime(row["retrieved_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if not 0 <= (moment - captured_at).total_seconds() <= max_age_hours * 3600:
            return None
        raw = None
        if row["status"] == "CAPTURED":
            sha = row["pack"]
            if sha not in self._pack_bytes:
                raise StateError("OUTPUT_CAPTURE_UNKNOWN")  # no lazy second admission/read sweep
            pack = self._pack_bytes[sha]
            if row["offset"] + row["bytes"] > len(pack):
                raise StateError("OUTPUT_CAPTURE_UNKNOWN")  # including zero-length out-of-pack slices
            raw = pack[row["offset"]:row["offset"] + row["bytes"]]
            if len(raw) != row["bytes"] or hashlib.sha256(raw).hexdigest() != row["sha256"]:
                raise StateError("OUTPUT_CAPTURE_UNKNOWN")
        return raw, dict(row)  # original claimed time/status, no authenticated freshness claim

    def progress(self, plan, count):
        if type(count) is not int or not 0 < count <= 1024:
            raise StateError("OUTPUT_PLAN_BOUND")
        if type(plan) is not str or not SHA_RE.fullmatch(plan):
            raise StateError("OUTPUT_PLAN_BOUND")
        return self._capture_index()["progress"].get(plan, 0) % count

    def capture_batch(self, observations, plan, cursor):
        """Finite logical slots -> packed immutable bytes, index/progress LAST.

        URL slots are NOT raw-directory entries. Up to1024 observations share
        <=256 packs with the SAME64MiB high-water limit and native caps. Only
        actual newly observed bodies/times/statuses enter a batch. No eviction.
        """
        ledger, index = self._ledger(), self._capture_index()
        if (plan is not None and (type(plan) is not str or not SHA_RE.fullmatch(plan) or
                type(cursor) is not int or not 0 <= cursor < 1024)) or (plan is None and cursor is not None):
            raise StateError("OUTPUT_PLAN_BOUND")
        if type(observations) is not list or len(observations) > 120:
            raise StateError("OUTPUT_CAPTURE_BOUND")
        if not observations and (plan is None or index["progress"].get(plan) == cursor):
            return  # full warm traversals need no duplicate mutation/reservation
        pending, packs, pack, size = {}, [], bytearray(), 0
        def seal():
            nonlocal pack
            if pack:
                packs.append(bytes(pack))
                pack = bytearray()
        for key, url, raw, moment, status, http_status in observations:
            if (type(key) is not str or not SHA_RE.fullmatch(key) or key in pending or
                    type(url) is not str or len(url) > 4096 or type(moment) is not datetime or moment.tzinfo != timezone.utc or
                    status not in ("CAPTURED", "HTTP_UNAVAILABLE", "TRANSPORT_UNAVAILABLE") or
                    (raw is not None and (type(raw) is not bytes or len(raw) > 16 * 1024 * 1024)) or
                    (status == "CAPTURED") != (raw is not None) or
                    (http_status is not None and (type(http_status) is not int or not 100 <= http_status <= 599)) or
                    (status == "CAPTURED" and http_status != 200) or
                    (status == "HTTP_UNAVAILABLE" and (http_status is None or http_status == 200)) or
                    (status == "TRANSPORT_UNAVAILABLE" and http_status is not None)):
                raise StateError("OUTPUT_CAPTURE_BOUND")
            # Empty successful bodies occupy a real sentinel byte in the pack,
            # while their indexed slice remains zero length with its actual SHA.
            stored = raw if raw else b"\x00"
            if raw is not None and len(pack) + len(stored) > 16 * 1024 * 1024:
                seal()
            pending[key] = {"url": url, "sha256": hashlib.sha256(raw).hexdigest() if raw is not None else None,
                "pack": len(packs) if raw is not None else None, "offset": len(pack) if raw is not None else 0,
                "bytes": len(raw) if raw is not None else 0, "retrieved_at": moment.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "status": status, "http_status": http_status}
            if raw is not None:
                pack.extend(stored)
                size += len(stored)
        seal()
        hashes = [hashlib.sha256(raw).hexdigest() for raw in packs]
        if (len(set(index["entries"]) | set(pending)) > 1024 or
                len(set(ledger["captures"]) | set(hashes)) > 256 or ledger["bytes"] + size > self.MAX_BYTES):
            raise StateError("OUTPUT_CAPACITY_UNAVAILABLE")
        ledger["bytes"] += size
        ledger["pending"] = {"kind": "capture_batch", "bytes": size, "packs": hashes}
        self._save_ledger(ledger)  # no refund even if any following step is UNKNOWN
        for sha, raw in zip(hashes, packs):
            self.store.write(("outputs", "cache", sha), raw)
            actual = self.store.lease.capture_bytes(("b1", "outputs", "cache", sha),
                16 * 1024 * 1024, bytes.fromhex(sha), raw_document=True, historical=True)[0]
            if actual != raw:
                raise StateError("OUTPUT_CAPTURE_READBACK")
            self._remember_payload(("cache", sha), actual)
            self._pack_bytes[sha] = actual
            self._cache_inventory.add(sha)  # ONLY confirmed owned immutable/readback
            if sha not in ledger["captures"]:
                ledger["captures"].append(sha)
        for row in pending.values():
            if row["pack"] is not None:
                row["pack"] = hashes[row["pack"]]
        index["entries"].update(pending)
        if plan is not None:
            if plan not in index["progress"] and len(index["progress"]) >= 8:
                raise StateError("OUTPUT_PLAN_BOUND")
            index["progress"][plan] = cursor
        # Fresh CAS token must still match the exact previously captured/readback
        # bytes. A foreign mutable change is refused, not silently overwritten.
        expected = self.store.capture_mutable(("outputs", "capture-index.json"))
        if (expected.data != self._index_raw or expected.identity != self._index_identity or
                expected.parent_identity != self._parent_identity):
            raise StateError("OUTPUT_CAPTURE_CHANGED")
        raw_index = json.dumps(index, sort_keys=True, allow_nan=False).encode()
        actual = self.store.write(("outputs", "capture-index.json"), raw_index, expected=expected)
        self._index_raw, self._index_identity = raw_index, actual.identity
        ledger["pending"] = None
        self._save_ledger(ledger)
        self._index_value = index  # only confirmed publication/readback advances fair cursor

    def load_cision(self):
        self._ledger()
        if self._cision_admitted:
            return self._cision_raw  # exact once-admitted control bytes in SAME actual epoch
        expected = self.store.capture_mutable(("outputs", "cision.json"))
        if expected.parent_identity != self._parent_identity:
            raise StateError("OUTPUT_CISION_CHANGED")
        if expected.data is not None and len(expected.data) > 1024 * 1024:
            raise StateError("OUTPUT_CISION_BOUND")
        self._cision_raw, self._cision_identity = expected.data, expected.identity
        self._cision_admitted = True
        return expected.data

    def save_cision(self, raw):
        try:
            if type(raw) is not bytes or len(raw) > 1024 * 1024:
                raise StateError("OUTPUT_CISION_BOUND")
            self._ledger()
            if not self._cision_admitted:
                self.load_cision()
            expected = self.store.capture_mutable(("outputs", "cision.json"))
            if (expected.data != self._cision_raw or expected.identity != self._cision_identity or
                    expected.parent_identity != self._parent_identity):
                raise StateError("OUTPUT_CISION_CHANGED")
            actual = self.store.write(("outputs", "cision.json"), raw, expected=expected)
            self._cision_raw, self._cision_identity = raw, actual.identity
            self._inventory.add("cision.json")  # only actual owned conditional/readback mutation
        except Exception:
            # Legacy Cision's optional fetch catch must not swallow/retry a
            # failed output compare/publication or original native UNKNOWN.
            raise B1OutputControlFault("OUTPUT_CISION_UNAVAILABLE") from None

    def read(self, kind, digest):
        if kind not in ("rank", "body", "record") or type(digest) is not str or not SHA_RE.fullmatch(digest):
            raise StateError("OUTPUT_NAME")
        self.store.require_live()
        # Fresh actual read, NOT the write-side epoch cache or public metadata.
        raw, actual = self.store.lease.capture_bytes(("b1", "outputs", kind + "-" + digest + ".json"),
                                                    MAX_GENERATION_BYTES, bytes.fromhex(digest))
        if hashlib.sha256(raw).hexdigest() != digest:
            raise StateError("OUTPUT_READBACK")
        return raw

    def publish(self, ranking, body, record):
        items = (("rank", ranking), ("body", body), ("record", record))
        if any(type(raw) is not bytes or not raw or len(raw) > MAX_GENERATION_BYTES for _, raw in items):
            raise StateError("OUTPUT_BYTES")
        ledger = self._ledger()
        size = sum(len(raw) for _, raw in items)
        if len(ledger["entries"]) >= self.MAX_BUNDLES or ledger["bytes"] + size > self.MAX_BYTES:
            raise StateError("OUTPUT_CAPACITY_UNAVAILABLE")
        digests = {kind: hashlib.sha256(raw).hexdigest() for kind, raw in items}
        # Reservation FIRST, never refunded on partial/UNKNOWN. Record is LAST.
        ledger["bytes"] += size
        ledger["pending"] = {"bytes": size, "digests": digests}
        self._save_ledger(ledger)
        for kind, raw in items:
            self.store.write(("outputs", kind + "-" + digests[kind] + ".json"), raw)
            actual = self.read(kind, digests[kind])  # fresh publication/witness readback stays mandatory
            if actual != raw:
                raise StateError("OUTPUT_READBACK")
            name = kind + "-" + digests[kind] + ".json"
            self._remember_payload(("artifact", name), actual)
            self._artifact_bytes[name] = actual
            self._inventory.add(name)
        if digests["record"] not in ledger["entries"]:
            ledger["entries"].append(digests["record"])
        ledger["pending"] = None  # only ALL actual immutable readbacks settle it
        self._save_ledger(ledger)
        self._ledger()
        return digests


class B1Object:
    """Closed typed operand; deliberately no __fspath__, arbitrary open or unlink."""
    def __init__(self, store, components):
        import revenue_guidance_windows as windows
        if type(store) is not B1Store or type(components) is not tuple or not components:
            raise EffectiveInputsError("CAPABILITY_OPERAND")
        for n in components:
            windows._namespace_name(n)
        self.store, self.components = store, components

    def __truediv__(self, name):
        return B1Object(self.store, self.components + (name,))

    @property
    def name(self):
        return self.components[-1]

    def with_name(self, name):
        return B1Object(self.store, self.components[:-1] + (name,))

    def read_bytes(self):
        return self.store.read(self.components)

    def read_text(self, encoding="utf-8"):
        return self.read_bytes().decode(encoding)

    def exists(self):
        if self.is_directory_operand():
            return self.is_dir()
        try:
            self.read_bytes()
            return True
        except FileNotFoundError:
            return False

    def is_directory_operand(self):
        return self.components in (("captures",), ("segments",), ("generations",), ("outputs",)) or (
            len(self.components) == 2 and self.components[0] == "captures" and bool(re.fullmatch("[0-9a-f]{2}", self.name)))

    def is_dir(self):
        import revenue_guidance_windows as windows
        try:
            h, close = self.store._directory(self.components)
        except windows.StorageObjectMissingError:
            return False
        if close:
            self.store.lease.close_owned(h)
        return True

    def is_file(self):
        return not self.is_directory_operand() and self.exists()

    def iterdir(self):
        return self.store.children(self.components)

    def glob(self, pattern):
        if pattern != "*.json":
            raise EffectiveInputsError("CAPABILITY_GLOB")
        return tuple(x for x in self.iterdir() if x.name.endswith(".json"))


STATE_ARTIFACTS = {"captures", "generations", "segments", "store_usage.json", "queue.json"}
STATE_ROOT_ENTRIES = STATE_ARTIFACTS | {"current.json", "lock"}
_TEMP_ENTRY = re.compile(r"^(current|queue|store_usage)\.json\.tmp-\d+$")
_SEAL_KEY = secrets.token_bytes(32)  # per process: a snapshot is an in-process object, never deserialized


class EffectiveInputsError(ValueError):
    """An argument error or a snapshot that was not produced (or was altered after being produced) by the loader."""


def _normalize_cutoff(cutoff: Any) -> tuple[datetime, str]:
    if isinstance(cutoff, datetime):
        if cutoff.tzinfo is None or cutoff.utcoffset() is None:
            raise EffectiveInputsError("CUTOFF_NAIVE")
        moment = cutoff.astimezone(timezone.utc).replace(microsecond=0)
    elif isinstance(cutoff, str) and INSTANT_RE.match(cutoff):
        moment = datetime.strptime(cutoff, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    else:
        raise EffectiveInputsError("CUTOFF_INVALID")
    return moment, moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_input(name: str, path: Path | None, data: bytes | None, default: Path) -> tuple[bytes | None, str | None, Path | None]:
    """(bytes, fault, path read) for one input: exactly one explicit source, or the project default, read once."""
    if path is not None and data is not None:
        raise EffectiveInputsError(f"{name.upper()}_SOURCE_CONFLICT")
    if data is not None:
        if not isinstance(data, (bytes, bytearray)):
            raise EffectiveInputsError(f"{name.upper()}_BYTES")
        return bytes(data), None, None
    target = Path(path) if path is not None else default
    try:
        return target.read_bytes(), None, target
    except FileNotFoundError:
        return None, "MISSING", target
    except OSError:
        return None, "UNREADABLE", target


def valid_receipt_history(data: Any) -> bool:
    """The retained release-check cache shape both the loader and the checker require: the schema, an issuer map of
    lists of receipt objects that each carry a UTC check instant (the receipts themselves are validated on use)."""
    return (isinstance(data, dict) and data.get("schema") == revenue_guidance.RELEASE_CHECKS_SCHEMA and isinstance(data.get("issuers"), dict)
            and all(isinstance(sym, str) and isinstance(rows, list) and all(
                isinstance(r, dict) and isinstance(r.get("checked_at"), str) and INSTANT_RE.match(r["checked_at"]) for r in rows)
                for sym, rows in data["issuers"].items()))


def _digest(data: bytes | None, fault: str | None) -> str:
    return verify.sha256(data) if data is not None else f"FAULT:{fault or 'MISSING'}"


@dataclass(frozen=True)
class IssuerInputs:
    """One issuer's inputs at the snapshot cutoff (a fresh copy on every access; never a model input by itself)."""
    symbol: str
    disposition: str
    reason: str | None
    detail: str | None
    discovery_record: dict[str, Any] | None
    discovery_origin: str | None
    discovery_reference: dict[str, Any] | None
    usable_record: dict[str, Any] | None
    record_sha256: str | None
    admission_kind: str | None
    producer: dict[str, Any] | None
    last_attempt: dict[str, Any] | None
    detections: list[dict[str, Any]]
    overflow: bool
    receipt_admission: dict[str, Any] | None
    evidence: dict[str, Any] | None


@dataclass(frozen=True)
class EffectiveInputs:
    """One pinned, immutable snapshot of every revenue-guidance input at one cutoff. Its parts are stored as JSON
    text and sealed with a per-process key: every access re-checks the seal and returns a copy, so a rebound field
    or a hand-built object never passes as loader output."""
    cutoff: str
    input_digest: str
    condition: str
    generation_id: str | None
    generation_sha256: str | None
    _parts: tuple[tuple[str, str], ...]
    _seal: str

    def _check(self) -> dict[str, str]:
        if not isinstance(self, EffectiveInputs):
            raise EffectiveInputsError("SNAPSHOT_TYPE")
        expected = _seal_of(self.cutoff, self.input_digest, self.condition, self.generation_id, self.generation_sha256, self._parts)
        if not hmac.compare_digest(expected, str(self._seal)):
            raise EffectiveInputsError("SNAPSHOT_SEAL")
        return dict(self._parts)

    def part(self, name: str) -> Any:
        return json.loads(self._check()[name])

    @property
    def registry(self) -> dict[str, Any]:
        """The curated registry exactly as `revenue_guidance.load_registry` returns it for the captured bytes."""
        return self.part("registry")

    @property
    def approval(self) -> dict[str, Any]:
        return self.part("approval")

    @property
    def release_checks(self) -> dict[str, Any]:
        """The release-check cache with the curated path's legacy semantics (missing or malformed: empty)."""
        return self.part("release_checks")

    @property
    def manifest(self) -> dict[str, Any]:
        return self.part("manifest")

    def symbols(self) -> list[str]:
        return sorted(self.part("issuers"))

    def issuer(self, symbol: str) -> IssuerInputs | None:
        data = self.part("issuers").get(symbol)
        return None if data is None else IssuerInputs(**data)

    def discovery_records(self) -> list[tuple[str, dict[str, Any] | None, str | None]]:
        """(symbol, discovery record or None when not checkable, origin) for every GUIDANCE discovery input, in the
        registry's order (the release checker's work list)."""
        issuers = self.part("issuers")
        order = self.part("order")
        out = []
        for sym in order + sorted(s for s in issuers if s not in order):  # an automatic issuer outside the registry too
            item = issuers.get(sym)
            if item is None:
                continue
            record = item["discovery_record"]
            if record is not None and record.get("status") != "GUIDANCE":
                continue
            if record is None and item["disposition"] == "CURATED":
                continue  # no record at all (an uncovered issuer): nothing to check
            out.append((sym, record, item["discovery_origin"]))
        return out


def _seal_of(cutoff: str, digest: str, condition: str, gen_id: str | None, gen_sha: str | None, parts: tuple[tuple[str, str], ...]) -> str:
    material = json.dumps([cutoff, digest, condition, gen_id, gen_sha, [[n, verify.sha256(t.encode("utf-8"))] for n, t in parts]])
    return hmac.new(_SEAL_KEY, material.encode("utf-8"), hashlib.sha256).hexdigest()


def require_snapshot(snapshot: Any, cutoff: datetime | str | None = None) -> EffectiveInputs:
    """The consumer check: a genuine, unaltered loader snapshot (and, when given, for exactly this cutoff)."""
    if not isinstance(snapshot, EffectiveInputs):
        raise EffectiveInputsError("SNAPSHOT_TYPE")
    snapshot._check()
    if cutoff is not None and _normalize_cutoff(cutoff)[1] != snapshot.cutoff:
        raise EffectiveInputsError("SNAPSHOT_CUTOFF")
    return snapshot


def _valid_baseline(record: Mapping[str, Any] | None, symbol: str) -> dict[str, Any] | None:
    if not isinstance(record, Mapping):
        return None
    try:
        revenue_guidance.validate_issuer_record(record, expected_symbol=symbol)
    except Exception:  # noqa: BLE001 - any invalid baseline is simply not a discovery input
        return None
    return dict(record)


def _capture_binding(root: Path, key: str, raw_sha: str) -> dict[str, Any]:
    meta_path = capture_path(root, raw_sha).with_name(raw_sha + ".json")
    data = meta_path.read_bytes()
    meta = json.loads(data.decode("utf-8"))
    return {"key": key, "raw_sha256": raw_sha, "sha256": meta.get("sha256"), "meta_sha256": verify.sha256(data),
            "url": meta.get("url"), "role": meta.get("role"), "accession": meta.get("accession"), "retrieved_at": meta.get("retrieved_at")}


def _producer_binding(root: Path, entry: Mapping[str, Any] | None, producer: Mapping[str, Any]) -> dict[str, Any]:
    routing = next((d["operands"] for d in producer["decisions"] if d["kind"] == "ROUTING"), {})
    index = (entry or {}).get("index") or {}
    verified = index.get("verified") or []
    return {"event_key": producer["event_key"], "event_sha256": verify.sha256(verify.canonical_json(producer["event"]).encode("utf-8")),
            "attempt_sha256": verify.sha256(verify.canonical_json(producer).encode("utf-8")),
            "decisions_sha256": verify.sha256(verify.canonical_json(producer["decisions"]).encode("utf-8")),
            "predecessor_sha256": producer["predecessor_sha256"], "record_sha256": producer["record_sha256"],
            "attempted_at": producer["attempted_at"], "filed": routing.get("filed"), "report_period": routing.get("report_period"),
            "reference": routing.get("reference"),
            "segments": {"head": (entry or {}).get("head"),
                         "producer": verified[-1]["segment"] if verified else None,
                         "predecessor": verified[-2]["segment"] if len(verified) > 1 else None},
            "captures": [_capture_binding(root, k, v) for k, v in sorted(producer["captures"].items())]}


def _auto_evidence(symbol: str, disposition: str, reason: str | None, kind: str | None, gen: Mapping[str, Any] | None,
                   producer: Mapping[str, Any] | None, binding: Mapping[str, Any] | None, detections: list[Mapping[str, Any]],
                   overflow: bool, admission: Mapping[str, Any] | None) -> dict[str, Any]:
    """The in-memory AutoAdmissionEvidence (B3 owns the sealed schema); snapshot cutoff/digest are added by the model."""
    return {
        "version": AUTO_EVIDENCE_VERSION, "issuer": symbol, "disposition": disposition, "reason": reason, "admission_kind": kind,
        "generation_id": (gen or {}).get("generation_id"),
        "identity": {k: (gen or {}).get(k) for k in IDENTITY_KEYS},
        "producer": None if producer is None else dict(binding or {}),
        "decisions": [] if producer is None else [
            {"kind": d["kind"], "ref": d["ref"], "decision": d["decision"], "capture": d["capture"], "operands": d["operands"]}
            for d in producer["decisions"]],
        "consumed": sorted([list(c) for c in consumed_identities(producer)]),
        "detections": [{k: d.get(k) for k in ("channel", "id", "date", "disposition")} for d in detections],
        "overflow": overflow,
        "receipt": None if admission is None else {k: admission[k] for k in (
            "reference", "anchor", "receipt_digest", "receipt_status", "checked_at", "rows", "unaccounted", "decision")},
    }


def load_effective_inputs(*, cutoff: datetime | str, state_root: Path,
                          registry_path: Path | None = None, registry_bytes: bytes | None = None,
                          approval_path: Path | None = None, approval_bytes: bytes | None = None,
                          profiles_path: Path | None = None, profiles_bytes: bytes | None = None,
                          receipts_path: Path | None = None, receipts_bytes: bytes | None = None,
                          symbols: Iterable[str] | None = None, state_required: bool = False,
                          expected_generation: Mapping[str, Any] | None = None, allow_replay: bool = False) -> EffectiveInputs:
    """The one pinned snapshot of every revenue-guidance input at `cutoff` (see docs/REVENUE_GUIDANCE_AUTOUPDATE.md, B1).

    Each input is read once (one explicit path or exact bytes, else the project default); the state root's pointer is
    read once and the generation at the cutoff pinned through its verified parent chain (or `expected_generation`,
    whose exact bytes are loaded). Per issuer: the discovery record (what the release checker and the updater check),
    the usable record (the only model input; None unless CURATED or AUTO_VERIFIED) and the typed disposition. Data
    faults are typed dispositions, never exceptions and never a fallback to curated numbers for the automatic lane;
    argument errors raise EffectiveInputsError."""
    moment, instant = _normalize_cutoff(cutoff)
    root = state_root if type(state_root) is B1Store else Path(state_root)
    if type(root) is B1Store:
        root.require_live()
        if any(x is not None for x in (registry_path, registry_bytes, approval_path, approval_bytes,
                                       profiles_path, profiles_bytes, receipts_path, receipts_bytes)) or allow_replay:
            raise EffectiveInputsError("CAPABILITY_INPUT_SOURCE_CONFLICT")
        state_required = True
        reg_raw, reg_fault, reg_path = root.input("registry"), None, None
        appr_raw, appr_fault = root.input("approval"), None
        prof_raw, prof_fault = root.input("profiles"), None
        rec_raw, rec_fault = root.input("receipts"), None
    else:
        reg_raw, reg_fault, reg_path = _read_input("registry", registry_path, registry_bytes, revenue_guidance.REGISTRY_PATH)
        appr_raw, appr_fault, _ = _read_input("approval", approval_path, approval_bytes, revenue_guidance.APPROVAL_PATH)
        prof_raw, prof_fault, _ = _read_input("profiles", profiles_path, profiles_bytes, PROFILES_DEFAULT)
        rec_raw, rec_fault, _ = _read_input("receipts", receipts_path, receipts_bytes, revenue_guidance.RELEASE_CHECKS_CACHE_PATH)

    registry = revenue_guidance.parse_registry(reg_raw, reg_path) if reg_raw is not None else revenue_guidance.parse_registry(None)
    approval = revenue_guidance.parse_approval(appr_raw)
    release_checks = revenue_guidance.parse_release_checks_cache(rec_raw)
    curated: dict[str, dict[str, Any]] = dict(registry.get("issuers") or {}) if registry.get("status") == "OK" else {}
    order = [r.get("symbol") for r in (json.loads(reg_raw.decode("utf-8")).get("issuers") or [])] if registry.get("status") == "OK" else []
    receipts_strict: dict[str, Any] | None = None
    if rec_raw is not None:
        try:
            data = json.loads(rec_raw.decode("utf-8"))
            if valid_receipt_history(data):
                receipts_strict = data
            else:
                rec_fault = "INVALID"
        except (UnicodeDecodeError, ValueError):
            rec_fault = "INVALID"
    profiles: dict[str, Any] | None = None
    if prof_raw is not None:
        try:
            profiles = verify.validate_profiles(json.loads(prof_raw.decode("utf-8")))
        except (UnicodeDecodeError, ValueError, KeyError, TypeError):
            prof_fault = "INVALID"

    # ---- state: the pointer read once, the generation at the cutoff pinned
    condition, state_error, gen, pointer, gen_file_sha = "BOOTSTRAP", None, None, None, None
    if expected_generation is not None and (
            not isinstance(expected_generation, Mapping) or set(expected_generation) != {"generation_id", "sha256"}
            or not ID_RE.match(str(expected_generation["generation_id"])) or not SHA_RE.match(str(expected_generation["sha256"]))):
        raise EffectiveInputsError("EXPECTED_GENERATION_SHAPE")
    try:
        # The root's integrity is checked in every mode (a replay pin never vouches for a damaged root).
        if root.exists() and not root.is_dir():
            raise StateError("STATE_ROOT_NOT_DIRECTORY")
        present = {c.name for c in root.iterdir()} if root.exists() else set()
        allowed = STATE_ROOT_ENTRIES | {"receipts.json", "outputs"} if type(root) is B1Store else STATE_ROOT_ENTRIES
        foreign = {n for n in present if n not in allowed and not _TEMP_ENTRY.match(n)}
        if foreign:
            raise StateError("STATE_ROOT_FOREIGN")
        if "current.json" not in present and present & STATE_ARTIFACTS:
            raise StateError("STATE_POINTER_MISSING")
        if expected_generation is not None:
            gen = read_generation(root, str(expected_generation["generation_id"]), str(expected_generation["sha256"]))
            gen_file_sha = str(expected_generation["sha256"])
            if gen["created_at"] > instant:
                raise StateError("EXPECTED_GENERATION_AFTER_CUTOFF")
            condition = "PINNED"
        else:
            pointer = read_pointer(root)
            if pointer is None:
                if present & STATE_ARTIFACTS:
                    raise StateError("STATE_POINTER_MISSING")
                if state_required:
                    raise StateError("STATE_REQUIRED_MISSING")
            else:
                gen, gen_file_sha = pinned_generation(root, pointer, instant)
                condition = "PINNED"
    except EffectiveInputsError:
        raise
    except (StateError, OSError, ValueError) as error:
        condition, state_error, gen = "STATE_FAILURE", f"{type(error).__name__}: {error}"[:200], None

    # ---- the automatic lane
    lane_fault = None
    if condition == "STATE_FAILURE":
        lane_fault = "STATE_CORRUPT"
    elif profiles is None:
        lane_fault = "PROFILES_INVALID"
    elif registry.get("status") != "OK" or appr_raw is None:
        lane_fault = "BASELINE_INVALID"
    supported = [sym for sym in SUPPORTED_AUTO if profiles is not None and sym in profiles]
    ident = identity(prof_raw, reg_raw, appr_raw, root) if lane_fault is None else None
    admitted: dict[str, dict[str, Any]] = {}
    discovery_admitted: dict[str, dict[str, Any]] = {}
    if lane_fault is None and supported:
        sub = {sym: profiles[sym] for sym in supported}
        admitted = admit(root, gen, instant, sub, curated, ident, allow_replay)
        if gen is not None and any(gen[k] != ident[k] for k in IDENTITY_KEYS):
            # Discovery only: the stored producer re-derived under the current code, profiles and baseline. It can
            # supply the reference to check; it never makes the record usable before the updater re-verifies.
            discovery_admitted = admit(root, gen, instant, sub, curated, {k: gen[k] for k in IDENTITY_KEYS}, allow_replay)

    wanted = sorted(set(curated) | set(SUPPORTED_AUTO) | {str(x) for x in (symbols or [])})
    issuers: dict[str, dict[str, Any]] = {}
    manifest_issuers: dict[str, Any] = {}
    for sym in wanted:
        base = curated.get(sym)
        item: dict[str, Any] = {"symbol": sym, "disposition": "CURATED", "reason": None if base is not None else "NO_RECORD", "detail": None,
                                "discovery_record": base, "discovery_origin": "CURATED" if base is not None else None,
                                "discovery_reference": None, "usable_record": base, "record_sha256": None,
                                "admission_kind": "HUMAN_PROFILE" if base is not None else None, "producer": None, "last_attempt": None,
                                "detections": [], "overflow": False, "receipt_admission": None, "evidence": None}
        binding = None
        if sym in SUPPORTED_AUTO:
            entry = ((gen or {}).get("issuers") or {}).get(sym)
            a = admitted.get(sym)
            if lane_fault is not None or a is None:
                reason = lane_fault or "PROFILE_DISABLED"
                if reason == "PROFILE_DISABLED":
                    pass  # not an automatic issuer in this configuration: its curated path stays as it is
                else:
                    rescan = _valid_baseline(base, sym)
                    item.update(disposition="BLOCKED", reason=reason, detail=state_error, usable_record=None, admission_kind=None,
                                discovery_record=rescan, discovery_origin="CURATED_RESCAN" if rescan else None)
            else:
                mode = a["mode"]
                item.update(reason=a["reason"], detail=a["detail"], producer=a["producer"], last_attempt=a["attempt"],
                            detections=list(a["detections"]), overflow=bool(a["overflow"]))
                # discovery
                if mode == "BLOCKED" and a["reason"] == "APPROVAL_BINDING" and sym in discovery_admitted:
                    d = discovery_admitted[sym]
                    if d["producer"] is not None and d["effective"] is not None:
                        item.update(discovery_record=d["effective"], discovery_origin="READMITTED_AUTO")
                    elif d["effective"] is not None and d["mode"] == "CURATED":
                        item.update(discovery_record=base, discovery_origin="CURATED")
                    else:
                        rescan = _valid_baseline(base, sym)
                        item.update(discovery_record=rescan, discovery_origin="CURATED_RESCAN" if rescan else None)
                elif a["effective"] is None:
                    rescan = _valid_baseline(base, sym)
                    item.update(discovery_record=rescan, discovery_origin="CURATED_RESCAN" if rescan else None)
                else:
                    item.update(discovery_record=a["effective"], discovery_origin="READMITTED_AUTO" if a["producer"] else "CURATED")
                # usable record
                if mode == "AUTO_VERIFIED":
                    admission = None
                    if a["overflow"]:
                        item.update(disposition="SUSPENDED", reason="DETECTIONS_OVERFLOW")
                    elif receipts_strict is None:
                        item.update(disposition="SUSPENDED", reason=f"RECEIPTS_{rec_fault or 'INVALID'}")
                    else:
                        admission = receipt_admission(receipts_strict, sym, a["effective"], instant, a["producer"], a["detections"])
                        item["receipt_admission"] = admission
                        if admission["decision"] is not None:
                            item.update(disposition="SUSPENDED", reason=admission["decision"])
                        else:
                            item.update(disposition="AUTO_VERIFIED", reason=None)
                    if item["disposition"] == "AUTO_VERIFIED":
                        item.update(usable_record=a["effective"], admission_kind="MACHINE_REPLAY")
                    else:
                        item.update(usable_record=None, admission_kind=None)
                elif mode == "CURATED":
                    if a["detections"] or a["overflow"]:
                        # A material event recorded against the curated record: stricter than the curated freshness gate
                        # (fail closed until a verified successor or the human registry accounts for it).
                        item.update(disposition="SUSPENDED", reason="DETECTIONS_OVERFLOW" if a["overflow"] else "DETECTIONS_UNRESOLVED",
                                    usable_record=None, admission_kind=None)
                else:
                    item.update(disposition=mode, usable_record=None, admission_kind=None)
                if a["producer"] is not None:
                    try:
                        binding = _producer_binding(root, entry, a["producer"])
                    except (OSError, ValueError, KeyError, TypeError, StateError) as error:
                        item.update(disposition="BLOCKED", reason="STATE_CORRUPT", detail=f"producer binding: {type(error).__name__}",
                                    usable_record=None, admission_kind=None)
            if item["disposition"] != "CURATED" or item["producer"] is not None:
                item["evidence"] = _auto_evidence(sym, item["disposition"], item["reason"], item["admission_kind"], gen,
                                                  item["producer"] if item["admission_kind"] == "MACHINE_REPLAY" else None,
                                                  binding if item["admission_kind"] == "MACHINE_REPLAY" else None,
                                                  item["detections"], item["overflow"], item["receipt_admission"])
        if item["discovery_record"] is not None:
            item["discovery_reference"] = revenue_guidance.guidance_reference(item["discovery_record"])
        if item["usable_record"] is not None:
            item["record_sha256"] = record_sha256(item["usable_record"])
        issuers[sym] = item
        manifest_issuers[sym] = {
            "disposition": item["disposition"], "reason": item["reason"], "admission_kind": item["admission_kind"],
            "discovery_origin": item["discovery_origin"],
            "discovery_record_sha256": record_sha256(item["discovery_record"]) if item["discovery_record"] is not None else None,
            "discovery_reference": item["discovery_reference"], "usable_record_sha256": item["record_sha256"],
            "producer": binding, "last_attempt": None if item["last_attempt"] is None else {
                "event_key": item["last_attempt"]["event_key"], "attempted_at": item["last_attempt"]["attempted_at"],
                "outcome": item["last_attempt"]["outcome"],
                "sha256": verify.sha256(verify.canonical_json(item["last_attempt"]).encode("utf-8"))},
            "detections": sorted([[str(d.get("channel")), str(d.get("id")), str(d.get("date"))] for d in item["detections"]]),
            "overflow": item["overflow"],
            "receipt": None if item["receipt_admission"] is None else {
                k: item["receipt_admission"][k] for k in ("reference", "receipt_digest", "checked_at", "rows", "decision")}}

    manifest = {
        "schema": MANIFEST_SCHEMA, "cutoff": instant, "allow_replay": bool(allow_replay), "state_required": bool(state_required),
        "supported": list(SUPPORTED_AUTO),
        "inputs": {"registry": _digest(reg_raw, reg_fault), "approval": _digest(appr_raw, appr_fault),
                   "profiles": _digest(prof_raw, prof_fault) if prof_fault != "INVALID" else f"FAULT:INVALID:{_digest(prof_raw, None)}",
                   "receipts": _digest(rec_raw, rec_fault) if rec_fault != "INVALID" else f"FAULT:INVALID:{_digest(rec_raw, None)}"},
        "implementation": {"implementation_sha256": implementation_sha256(root), "verifier_version": verify.VERIFIER_VERSION,
                           "normalizer_version": verify.NORMALIZER_VERSION},
        "state": {"condition": condition, "error": state_error,
                  "generation_id": (gen or {}).get("generation_id"),
                  "generation_sha256": gen_file_sha if gen is not None else None,
                  "pinned": dict(expected_generation) if expected_generation is not None else None},
        "issuers": manifest_issuers}
    input_digest = verify.sha256(verify.canonical_json(manifest).encode("utf-8"))
    gen_id, gen_sha = manifest["state"]["generation_id"], manifest["state"]["generation_sha256"]
    parts = tuple((name, json.dumps(value, ensure_ascii=False)) for name, value in (
        ("registry", registry), ("approval", approval), ("release_checks", release_checks), ("issuers", issuers),
        ("order", [sym for sym in order if isinstance(sym, str)]), ("manifest", manifest)))
    return EffectiveInputs(cutoff=instant, input_digest=input_digest, condition=condition, generation_id=gen_id, generation_sha256=gen_sha,
                           _parts=parts, _seal=_seal_of(instant, input_digest, condition, gen_id, gen_sha, parts))



def curated_snapshot(cutoff: datetime | str, registry: Mapping[str, Any], approval: Mapping[str, Any],
                     release_checks: Mapping[str, Any]) -> EffectiveInputs:
    """Compatibility adapter for explicit, already parsed curated inputs (fixtures and the legacy build interface): a
    sealed snapshot in which every issuer is CURATED under the given objects and the automatic lane is disabled (no
    state is read, no automatic disposition exists). Only `load_effective_inputs` produces automatic dispositions."""
    moment, instant = _normalize_cutoff(cutoff)
    registry, approval, release_checks = (json.loads(json.dumps(x)) for x in (registry, approval, release_checks))
    curated = dict(registry.get("issuers") or {}) if isinstance(registry.get("issuers"), dict) else {}
    issuers = {sym: {"symbol": sym, "disposition": "CURATED", "reason": None, "detail": None, "discovery_record": rec,
                     "discovery_origin": "CURATED", "discovery_reference": revenue_guidance.guidance_reference(rec) if isinstance(rec, Mapping) else None,
                     "usable_record": rec, "record_sha256": record_sha256(rec) if isinstance(rec, Mapping) else None,
                     "admission_kind": "HUMAN_PROFILE", "producer": None, "last_attempt": None, "detections": [], "overflow": False,
                     "receipt_admission": None, "evidence": None} for sym, rec in curated.items()}
    manifest = {"schema": MANIFEST_SCHEMA, "cutoff": instant, "adapter": "CURATED_ONLY",
                "inputs": {name: verify.sha256(verify.canonical_json(value).encode("utf-8"))
                           for name, value in (("registry", registry), ("approval", approval), ("release_checks", release_checks))}}
    digest = verify.sha256(verify.canonical_json(manifest).encode("utf-8"))
    parts = tuple((name, json.dumps(value, ensure_ascii=False)) for name, value in (
        ("registry", registry), ("approval", approval), ("release_checks", release_checks), ("issuers", issuers),
        ("order", sorted(curated)), ("manifest", manifest)))
    return EffectiveInputs(cutoff=instant, input_digest=digest, condition="CURATED_ONLY", generation_id=None, generation_sha256=None,
                           _parts=parts, _seal=_seal_of(instant, digest, "CURATED_ONLY", None, None, parts))
