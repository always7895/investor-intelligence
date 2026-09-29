#!/usr/bin/env python3
"""Runtime state of ORDERS-V3-AUTOUPDATE-01 (docs/REVENUE_GUIDANCE_AUTOUPDATE.md): content-addressed captures,
immutable generations, admission by re-derivation and the release-check gate.

Layout under one state root (the runtime's data/cache/revenue_guidance_autoupdate, a temporary root in tests):
  captures/<aa>/<raw sha256>        exact HTTP entity bytes
  captures/<aa>/<raw sha256>.json   capture metadata (url, retrieved_at, bytes, digests, role ...)
  generations/<id>.json             one immutable generation (the complete per-issuer attempt history)
  current.json                      pointer {schema, generation_id, sha256}, replaced atomically

The updater is the only writer. Nothing stored is trusted as an outcome: an issuer's automatic record is admitted
only when the installed verifier, run again on the stored capture bytes, reproduces the stored record and decisions
exactly, along an unbroken chain of predecessors starting at the curated record, under the generation's recorded
implementation, profile and baseline identities. Any mismatch fails closed for that issuer (never back to old
numbers); unreadable global state fails closed for every enabled issuer; issuers without attempts keep their curated
record. Readers and the updater use the same admission (`admit`)."""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import revenue_guidance
import revenue_guidance_auto_verify as verify

STATE_SCHEMA = "revenue-guidance-auto-state-v2"
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
DETECTION_KEYS = {"predecessor_sha256", "documents", "overflow"}
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
MAX_ATTEMPTS_PER_ISSUER = 64


class StateError(Exception):
    """The state root is present but unusable (corrupt, foreign or incomplete)."""


def record_sha256(record: Mapping[str, Any]) -> str:
    return verify.sha256(verify.canonical_json(record).encode("utf-8"))


def implementation_sha256() -> str:
    here = Path(__file__).resolve().parent
    parts = [f"{name}:{hashlib.sha256((here / name).read_bytes()).hexdigest()}" for name in IMPLEMENTATION_FILES]
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def identity(profiles_bytes: bytes, registry_bytes: bytes, approval_bytes: bytes) -> dict[str, str]:
    return {"verifier_version": verify.VERIFIER_VERSION, "normalizer_version": verify.NORMALIZER_VERSION,
            "implementation_sha256": implementation_sha256(), "profiles_sha256": verify.sha256(profiles_bytes),
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
        if verify.sha256(path.read_bytes()) != raw_sha:
            raise StateError(f"CAPTURE_BYTES {raw_sha[:12]}")
        # Same bytes captured again (another URL or time): keep the first metadata; the attempt names the URL it used.
        if not path.with_name(raw_sha + ".json").exists():
            _durable_write(path.with_name(raw_sha + ".json"), json.dumps(full, sort_keys=True).encode("utf-8"))
        return raw_sha
    _durable_write(path, raw)
    _durable_write(path.with_name(raw_sha + ".json"), json.dumps(full, sort_keys=True).encode("utf-8"))
    return raw_sha


def capture_bytes_total(root: Path) -> int:
    total = 0
    for meta in (root / "captures").glob("*/*.json"):
        try:
            total += int(json.loads(meta.read_text(encoding="utf-8"))["bytes"])
        except (OSError, ValueError, KeyError, TypeError):
            raise StateError("CAPTURE_META_UNREADABLE") from None
    return total


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
    if not isinstance(caps, dict) or len(caps) > 32 or not all(_text(k, 140, KEY_RE) and _text(v, 64, SHA_RE) for k, v in caps.items()):
        raise StateError("ATTEMPT_CAPTURES")
    e = a["event"]
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
            and d["reviewed_at"] == a["attempted_at"] for d in decisions):
        raise StateError("ATTEMPT_DECISIONS")
    if a["outcome"] == "VERIFIED":
        if a["reason"] is not None or not isinstance(a["record"], dict) or a["record_sha256"] != record_sha256(a["record"]) or not decisions:
            raise StateError("ATTEMPT_RECORD")
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
    """The monotonic set of material documents observed against one effective record (issuer-local)."""
    if (not isinstance(entry, dict) or set(entry) != DETECTION_KEYS or not _text(entry["predecessor_sha256"], 64, SHA_RE)
            or not _later_ok(entry["documents"]) or not isinstance(entry["overflow"], bool)):
        raise StateError("ATTEMPT_DETECTIONS")


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
    for sym, attempts in issuers.items():
        if not _text(sym, 16, re.compile(r"^[A-Z][A-Z0-9.\-]{0,15}$")) or not isinstance(attempts, list) or not 1 <= len(attempts) <= MAX_ATTEMPTS_PER_ISSUER:
            raise StateError("GENERATION_ATTEMPTS")


def read_pointer(root: Path) -> dict[str, Any] | None:
    """None when the state root has never been written; StateError when it exists but is unusable."""
    pointer = root / "current.json"
    generations = root / "generations"
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
    pointer = read_pointer(root)
    if pointer is None:
        return None
    gen = read_generation(root, str(pointer["generation_id"]), str(pointer["sha256"]))
    while gen["created_at"] > cutoff:
        if gen["parent"] is None:
            return None
        gen = read_generation(root, gen["parent"]["generation_id"], gen["parent"]["sha256"])
    return gen


def publish_generation(root: Path, gen: Mapping[str, Any], expected_parent: Mapping[str, Any] | None) -> str:
    """Write the immutable generation file, then move the pointer; a pre-existing id or a moved pointer refuses."""
    validate_generation(gen)
    for attempts in gen["issuers"].values():
        for a in attempts:
            validate_attempt(a)
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
    _durable_write(root / "current.json", json.dumps(pointer, sort_keys=True).encode("utf-8"))
    return digest


# ------------------------------------------------------------------------------------------------ admission

def rederive(root: Path, profile: Mapping[str, Any], effective: Mapping[str, Any], attempt: Mapping[str, Any],
             allow_replay: bool = False) -> dict[str, Any]:
    captures = {key: load_capture(root, raw_sha) for key, raw_sha in attempt["captures"].items()}
    if not allow_replay and any(str(c["role"]).startswith("REPLAY_") for c in captures.values()):
        raise StateError("REPLAY_CAPTURE")
    return verify.build_successor(profile, effective, attempt["event"], captures, attempt["attempted_at"])


def admit(root: Path, gen: Mapping[str, Any] | None, cutoff: str, profiles: Mapping[str, Mapping[str, Any]],
          curated: Mapping[str, Mapping[str, Any]], ident: Mapping[str, str], allow_replay: bool = False) -> dict[str, dict[str, Any]]:
    """Per enabled issuer: {"mode", "reason", "detail", "effective", "producer", "attempts", "detections"} at the cutoff.

    `effective` is the newest admitted record of the chain (curated or automatic, also while waiting/blocked: the
    release checker and the updater continue from it; never a display input by itself); `producer` the admitted
    attempt that made it; `detections` the material documents recorded as unresolved against it."""
    out: dict[str, dict[str, Any]] = {}
    for sym in profiles:
        out[sym] = {"mode": "CURATED", "reason": None, "detail": None, "effective": curated.get(sym), "producer": None,
                    "attempt": None, "attempts": [], "detections": [], "overflow": False,
                    "generation_id": None if gen is None else gen["generation_id"]}
    if gen is None:
        return out
    identity_ok = all(gen[k] == ident[k] for k in IDENTITY_KEYS)
    for sym in sorted(set(gen["issuers"]) | set(gen.get("detections") or {})):
        attempts = gen["issuers"].get(sym, [])
        state = out.get(sym)
        if state is None:
            continue  # history of a profile no longer enabled: never admitted
        if not identity_ok:
            state.update(mode="BLOCKED", reason="APPROVAL_BINDING", effective=None, detail="implementation, policy or baseline changed; awaiting re-verification")
            continue
        effective, producer = curated.get(sym), None
        mode, reason, detail, detections, kept = "CURATED", None, None, [], []
        try:
            previous = ""
            for attempt in attempts:
                validate_attempt(attempt)
                if attempt["attempted_at"] < previous:
                    raise StateError("ATTEMPT_ORDER")
                previous = attempt["attempted_at"]
                if attempt["attempted_at"] > cutoff:
                    break
                if effective is None or attempt["predecessor_sha256"] != record_sha256(effective):
                    raise StateError("PREDECESSOR_CHAIN")
                if attempt["outcome"] == "VERIFIED":
                    # Admission: the installed verifier must reproduce this exact outcome from the stored bytes.
                    again = rederive(root, profiles[sym], effective, attempt, allow_replay)
                    if again["outcome"] != "VERIFIED" or (verify.canonical_json(again["record"]) != verify.canonical_json(attempt["record"])
                                                          or verify.canonical_json(again["decisions"]) != verify.canonical_json(attempt["decisions"])):
                        raise StateError("REDERIVATION_RECORD")
                    # Detections carry across the reference change: a verified release accounts only for what it
                    # consumed and for documents dated strictly before its own filing day (it supersedes them); a
                    # same-day or later document stays unresolved.
                    carried = detections + list(attempt["event"]["later_documents"])
                    consumed = consumed_identities(attempt)
                    filed = routing_filed(attempt)
                    detections = [d for d in _material_documents([{"later_documents": carried}])
                                  if (str(d["channel"]), str(d["id"]), str(d["date"])) not in consumed and not str(d["date"]) < filed]
                    effective, producer, mode, reason, detail = attempt["record"], attempt, "AUTO_VERIFIED", None, None
                else:
                    # A waiting or blocked attempt only ever suspends the issuer; its detections persist until a
                    # verified successor supersedes the record they were detected against.
                    mode, reason, detail = attempt["outcome"], attempt["reason"], attempt["detail"]
                    detections = detections + list(attempt["event"]["later_documents"])
                kept.append(attempt)
                state["attempt"] = attempt
            entry = (gen.get("detections") or {}).get(sym)
            overflow = False
            if entry is not None:
                validate_detections(entry)
                if effective is not None and entry["predecessor_sha256"] == record_sha256(effective):
                    detections = _material_documents([{"later_documents": detections + list(entry["documents"])}])
                    overflow = entry["overflow"]
        except (StateError, KeyError, TypeError, ValueError, AttributeError) as error:
            # Malformed stored state is corrupt; well-formed state that the sources do not reproduce is unbound.
            malformed = not isinstance(error, StateError) or str(error).startswith(("ATTEMPT_", "EVENT_"))
            state.update(mode="BLOCKED", reason="STATE_CORRUPT" if malformed else "APPROVAL_BINDING", effective=None, producer=None,
                         detail=f"{type(error).__name__}: {error}"[:300])
            continue
        state.update(mode=mode, reason=reason, detail=detail, effective=effective, producer=producer, attempts=kept, detections=detections,
                     overflow=overflow)
    return out


# ------------------------------------------------------------------------------------------------ release-check gate

def reference(record: Mapping[str, Any]) -> tuple[str | None, str | None]:
    """(guidance reference document id, its published date) by the registry's own active-claim selection."""
    docs = {d.get("id"): d for d in record.get("documents") or [] if isinstance(d, Mapping)}
    active = revenue_guidance.select_active_guidance_claims(record)
    ref = revenue_guidance.guidance_reference_document_id(active[0], docs) if active else None
    return ref, (docs.get(ref) or {}).get("published_date") if ref else None


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
    reviewed = {str(d.get("id")) for d in record.get("reviewed_later_documents") or [] if d.get("disposition") == "REVIEWED_IRRELEVANT"}
    out = []
    for d in _material_documents(list(rows) + [{"later_documents": list(detections)}]):
        if (str(d.get("channel")), str(d.get("id")), str(d.get("date"))) in consumed or str(d.get("id")) in reviewed:
            continue
        out.append(d)
    return out


def receipt_gate(receipts: Mapping[str, Any] | None, symbol: str, record: Mapping[str, Any], cutoff: str,
                 producer: Mapping[str, Any] | None = None, detections: list[Mapping[str, Any]] = ()) -> str | None:
    """None when the record is usable at the cutoff: its newest release check passes the registry's strict receipt
    validation (issuer, digest, coverage, channel set and hosts, anchor, reference, age <= 24 h, recomputed status)
    and no material document ever listed for its reference is left unaccounted; otherwise the reason."""
    ref, published = reference(record)
    rows = receipt_rows(receipts, symbol, ref, cutoff)
    if not rows:
        return "RECEIPT_MISSING"
    newest = max(rows, key=lambda r: r["checked_at"])
    channels = record.get("release_channels") or {}
    quarters = record.get("reported_quarters") or []
    moment = datetime.strptime(cutoff, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    valid, status, error = revenue_guidance.validate_receipt(
        newest, symbol, quarters[-1]["end"] if quarters else None, ref, moment,
        reviewed_later_documents=record.get("reviewed_later_documents") or [], guidance_published_date=published,
        expected_cik=channels.get("sec_cik"), expected_wire_symbol=channels.get("wire_symbol"), expected_ir=channels.get("ir"))
    if not valid and error not in ("RESULTS_PUBLISHED", "REVIEW_REQUIRED"):
        return f"RECEIPT_{error}"
    left = unaccounted(record, rows, producer, detections)
    if any(d.get("disposition") == "RESULTS_RELEASE" for d in left):
        return "RECEIPT_RESULTS_PUBLISHED"
    return "RECEIPT_REVIEW_REQUIRED" if left else None


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
