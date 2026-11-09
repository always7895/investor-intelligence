"""Append-only, signed, score-neutral Top20 rotation and screener shadow evidence.

No account, broker, credential, user identity, SEC header, or private holdings enter records.
An HMAC signing key must be explicitly provisioned by the operator; absence fails closed.
An input-family change is a possible cause, NOT proof of why ranking changed.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import validated_rule_engine as rule_engine

SCHEMA = "top20-rotation-shadow-v2"
MAX_LOG_BYTES = 80 * 1024 * 1024
MAX_RECORD_BYTES = 2 * 1024 * 1024
INPUT_FAMILIES = ("prices", "filings", "serenity", "leopold", "events")
SYMBOL = re.compile(r"[A-Z0-9][A-Z0-9.^=-]{0,15}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def _safe_log_path(path: Path) -> None:
    for item in (path, *path.parents):
        if item.is_symlink():
            raise ValueError("SHADOW_UNSAFE_PATH")
        if item.exists():
            metadata = item.lstat()
            if getattr(metadata, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
                raise ValueError("SHADOW_UNSAFE_PATH")
    if not path.parent.is_dir():
        raise ValueError("SHADOW_UNSAFE_PARENT")
    if path.exists() and (not path.is_file() or path.stat().st_size > MAX_LOG_BYTES):
        raise ValueError("SHADOW_UNSAFE_FILE")


def _clock(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("SHADOW_CLOCK_INVALID")
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("SHADOW_CLOCK_INVALID") from None
    if moment.tzinfo is None or moment.utcoffset() != timezone.utc.utcoffset(moment):
        raise ValueError("SHADOW_CLOCK_INVALID")
    return moment


def _sha(value: Any) -> bool:
    return isinstance(value, str) and SHA256.fullmatch(value) is not None


def _fingerprints(doc: dict[str, Any]) -> list[dict[str, str]]:
    supplied = doc.get("candidate_fingerprints")
    if (not isinstance(supplied, list) or not supplied or len(supplied) > 1000
            or not all(isinstance(row, dict) and isinstance(row.get("symbol"), str)
                       and SYMBOL.fullmatch(row["symbol"])
                       and all(_sha(row.get(name)) for name in INPUT_FAMILIES) for row in supplied)
            or len({row["symbol"] for row in supplied}) != len(supplied)):
        raise ValueError("SHADOW_FINGERPRINTS_INVALID")
    if not {row["symbol"] for row in doc["top"]} <= {row["symbol"] for row in supplied}:
        raise ValueError("SHADOW_FINGERPRINTS_INCOMPLETE")
    return sorted(({"symbol": row["symbol"], **{name: row[name] for name in INPUT_FAMILIES}}
                   for row in supplied), key=lambda row: row["symbol"])


def _screen(doc: dict[str, Any], symbols: list[str], cutoff: datetime) -> list[dict[str, Any]]:
    supplied = doc.get("screener_shadow", [])
    if not isinstance(supplied, list):
        raise ValueError("SHADOW_SCREENER_INVALID")
    conditions = {}
    for entry in supplied:
        if not isinstance(entry, dict) or entry.get("symbol") not in symbols or entry["symbol"] in conditions:
            raise ValueError("SHADOW_SCREENER_INVALID")
        conditions[entry["symbol"]] = entry.get("conditions")
    result = []
    for symbol in symbols:
        screen = conditions.get(symbol)
        if screen is None:
            screen = rule_engine.evaluate(None, None, cutoff=cutoff.date(), symbol=symbol)
        rows = screen.get("rules") if isinstance(screen, dict) else None
        expected = {rule[0] for rule in rule_engine.RULES}
        if (not isinstance(rows, list) or len(rows) != len(expected)
                or not all(isinstance(row, dict) for row in rows)
                or {row.get("rule_id") for row in rows} != expected
                or screen.get("state") != "UNVERIFIED" or screen.get("ruleset") != rule_engine.RULESET_VERSION
                or not _sha(screen.get("input_sha256"))):
            raise ValueError("SHADOW_SCREENER_INVALID")
        retained = []
        for row in rows:
            if (row.get("status") not in {"PASS", "FAIL", "UNKNOWN"}
                    or not _sha(row.get("provenance_hash"))
                    or row.get("freshness") not in {"FRESH", "STALE", "UNKNOWN"}):
                raise ValueError("SHADOW_SCREENER_INVALID")
            # Only bounded evaluator-produced public research metadata, never author text.
            keep = {name: row.get(name) for name in (
                "rule_id", "status", "filed_at", "period_end", "quote_asof",
                "source_url", "freshness", "complete", "provenance_hash", "reason_zh")}
            if (not isinstance(keep["reason_zh"], str) or len(keep["reason_zh"]) > 120
                    or any(keep[name] is not None and rule_engine._day(keep[name]) is None
                           for name in ("filed_at", "period_end", "quote_asof"))):
                raise ValueError("SHADOW_SCREENER_INVALID")
            retained.append(keep)
        retained.sort(key=lambda row: row["rule_id"])
        result.append({"symbol": symbol, "verification": "UNVERIFIED", "ruleset": screen["ruleset"],
                       "input_sha256": screen["input_sha256"], "rules": retained,
                       "status": {row["rule_id"]: row["status"] for row in retained}})
    return result


def build_record(doc: dict[str, Any], previous: dict[str, Any] | None, *, asof: str) -> dict[str, Any]:
    if (not isinstance(doc, dict) or not isinstance(doc.get("top"), list)
            or not 1 <= len(doc["top"]) <= 20 or not all(isinstance(row, dict) for row in doc["top"])):
        raise ValueError("SHADOW_TOP_INVALID")
    now = _clock(asof)
    top = [row.get("symbol") for row in doc["top"]]
    if not all(isinstance(symbol, str) and SYMBOL.fullmatch(symbol) for symbol in top):
        raise ValueError("SHADOW_TICKER_INVALID")
    if len(set(top)) != len(top):
        raise ValueError("SHADOW_DUPLICATE_TICKER")
    fingerprints = _fingerprints(doc)
    # Whole-source context covers global config/FX/news and publication clocks.
    # Only hashes enter the journal; never runtime paths or raw source contents.
    context = doc.get("input_context", {})
    if (not isinstance(context, dict)
            or any(name not in (*INPUT_FAMILIES, "context") for name in context)):
        raise ValueError("SHADOW_INPUT_CONTEXT_INVALID")
    source_hashes = {name: digest(value) for name, value in context.items()}
    hashes = {name: digest({"candidates": [(row["symbol"], row[name]) for row in fingerprints],
                           "source": source_hashes.get(name)}) for name in INPUT_FAMILIES}
    hashes["context"] = source_hashes.get("context", digest(doc.get("layers_source")))
    previous_hashes = previous.get("input_hashes", {}) if previous else {}
    changed = sorted(name for name in hashes.keys() | previous_hashes.keys()
                     if previous_hashes.get(name) != hashes.get(name))
    previous_candidates = {row["symbol"]: row for row in previous.get("candidate_fingerprints", [])} if previous else {}
    current_candidates = {row["symbol"]: row for row in fingerprints}
    changed_candidates = []
    for symbol in sorted(previous_candidates.keys() | current_candidates.keys()):
        before, after = previous_candidates.get(symbol, {}), current_candidates.get(symbol, {})
        families = [name for name in INPUT_FAMILIES if before.get(name) != after.get(name)]
        if families:
            changed_candidates.append({"symbol": symbol, "families": families,
                                       "change": "ADDED" if not before else "REMOVED" if not after else "UPDATED"})
    before = previous.get("ranked", []) if previous else []
    enter = [symbol for symbol in top if symbol not in before]
    exit_ = [symbol for symbol in before if symbol not in top]
    moved = [{"symbol": symbol, "from_rank": before.index(symbol) + 1, "to_rank": rank}
             for rank, symbol in enumerate(top, 1) if symbol in before and before.index(symbol) + 1 != rank]
    symbols = [row["symbol"] for row in fingerprints]
    screen = _screen(doc, symbols, now)
    previous_screen = {row["symbol"]: digest(row["rules"]) for row in previous.get("screener_shadow", [])} if previous else {}
    current_screen = {row["symbol"]: digest(row["rules"]) for row in screen}
    screen_changed = sorted(symbol for symbol in previous_screen.keys() | current_screen.keys()
                            if previous_screen.get(symbol) != current_screen.get(symbol))
    ranking_changed = bool(previous and top != before)
    reason_code = ("INITIAL_OBSERVATION" if previous is None else
                   "RANKING_CHANGED_INPUT_CANDIDATES" if ranking_changed and changed else
                   "RANKING_CHANGED_WITHOUT_INPUT_CHANGE" if ranking_changed else
                   "INPUT_CHANGED_RANKING_UNCHANGED" if changed else
                   "SCREENER_CHANGED_RANKING_UNCHANGED" if screen_changed else "NO_CHANGE")
    reasons = {
        "INITIAL_OBSERVATION": "首次觀測，尚無前期可比較；不視為輪動",
        "RANKING_CHANGED_INPUT_CANDIDATES": "名單或排序改變；輸入資料變動僅為可能原因，尚未證明因果",
        "RANKING_CHANGED_WITHOUT_INPUT_CHANGE": "名單或排序改變但已記錄輸入未變；時間衰減或未覆蓋輸入原因尚待核對",
        "INPUT_CHANGED_RANKING_UNCHANGED": "輸入資料改變，但名單與排序未變",
        "SCREENER_CHANGED_RANKING_UNCHANGED": "研究條件狀態改變，但名單與排序未變；不影響分數",
        "NO_CHANGE": "名單、排序與已記錄輸入均未改變",
    }
    local_changes = {row["symbol"]: row["families"] for row in changed_candidates}
    rotations = []
    for symbol in sorted(set(enter + exit_ + [row["symbol"] for row in moved])):
        families = local_changes.get(symbol, [])
        rotations.append({
            "symbol": symbol, "change": "BASELINE" if previous is None else
            "ENTERED" if symbol in enter else "EXITED" if symbol in exit_ else "MOVED",
            "from_rank": before.index(symbol) + 1 if symbol in before else None,
            "to_rank": top.index(symbol) + 1 if symbol in top else None,
            "candidate_input_families": families, "possible_global_input_families": changed,
            "reason_zh": reasons["INITIAL_OBSERVATION"] if previous is None else
            "該候選輸入改變，與名次變動的因果尚未證明" if families else
            "該候選輸入未變；其他候選或整體輸入改變，因果尚未證明" if changed else
            reasons["RANKING_CHANGED_WITHOUT_INPUT_CHANGE"],
        })
    return {"schema": SCHEMA, "asof_utc": now.isoformat().replace("+00:00", "Z"),
            "ruleset_version": rule_engine.RULESET_VERSION, "rules_kept": 0,
            "ranked": top, "universe_sha256": digest(symbols), "input_hashes": hashes,
            "input_sha256": digest({"universe": symbols, "families": hashes}),
            "candidate_fingerprints": fingerprints,
            "diff": {"entered": enter, "exited": exit_, "moved": moved,
                     "ranking_changed": ranking_changed, "changed_input_families": changed,
                     "changed_candidates": changed_candidates, "changed_screener_symbols": screen_changed,
                     "reason_code": reason_code, "reason_zh": reasons[reason_code], "rotation_reasons": rotations,
                     "causality": "UNPROVEN_INPUT_CANDIDATES"},
            "screener_shadow": screen, "screener_verified": False,
            "previous_entry_sha256": previous.get("entry_sha256") if previous else None}


def _unique_object(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for name, value in items:
        if name in result:
            raise ValueError("SHADOW_DUPLICATE_FIELD")
        result[name] = value
    return result


def _verify_stream(stream: Any, key: bytes) -> dict[str, Any] | None:
    last = None
    stream.seek(0)
    for line in stream:
        if not line.endswith(b"\n") or len(line) > MAX_RECORD_BYTES:
            raise ValueError("SHADOW_RECORD_TRUNCATED")
        try:
            row = json.loads(line, object_pairs_hook=_unique_object)
        except (ValueError, UnicodeDecodeError):
            raise ValueError("SHADOW_RECORD_INVALID") from None
        if not isinstance(row, dict) or row.get("schema") != SCHEMA:
            raise ValueError("SHADOW_SCHEMA_INVALID")
        signature = row.pop("signature", None)
        if not _sha(signature) or not hmac.compare_digest(
                signature, hmac.new(key, canonical(row), hashlib.sha256).hexdigest()):
            raise ValueError("SHADOW_SIGNATURE_INVALID")
        if row.get("previous_entry_sha256") != (last["entry_sha256"] if last else None):
            raise ValueError("SHADOW_CHAIN_INVALID")
        claimed = row.pop("entry_sha256", None)
        if not _sha(claimed) or claimed != digest(row):
            raise ValueError("SHADOW_ENTRY_HASH_INVALID")
        row["entry_sha256"], row["signature"] = claimed, signature
        if last and _clock(row.get("asof_utc")) <= _clock(last.get("asof_utc")):
            raise ValueError("SHADOW_NON_MONOTONIC")
        _clock(row.get("asof_utc"))
        last = row
    return last


def verify_log(path: Path, key: bytes) -> dict[str, Any] | None:
    """Verify every HMAC, entry digest, UTC clock and hash link, including the genesis."""
    if not isinstance(key, bytes) or len(key) < 32:
        raise ValueError("SHADOW_SIGNING_KEY_UNAVAILABLE")
    _safe_log_path(path)
    if not path.exists():
        return None
    with path.open("rb") as stream:
        return _verify_stream(stream, key)


def append_signed(path: Path, doc: dict[str, Any], *, key: bytes, asof: str) -> dict[str, Any]:
    if not isinstance(key, bytes) or len(key) < 32:
        raise ValueError("SHADOW_SIGNING_KEY_UNAVAILABLE")
    _safe_log_path(path)
    # Serialize verify+append; a concurrent writer must fail, never fork the hash chain.
    lock = path.with_name(path.name + ".lock")
    _safe_log_path(lock)
    try:
        lock_fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise ValueError("SHADOW_WRITER_BUSY") from None
    try:
        os.close(lock_fd)
        prev = verify_log(path, key)
        if doc.get("refresh_state") == "REFRESH_FAILED" or doc.get("source_failures"):
            return {"state": "REFRESH_FAILED", "asof_utc": prev["asof_utc"] if prev else None,
                    "changes": 0, "input_families_changed": 0, "ranking_changed": False}
        if prev and _clock(prev["asof_utc"]) >= _clock(asof):
            raise ValueError("SHADOW_NON_MONOTONIC")
        row = build_record(doc, prev, asof=asof)
        row["entry_sha256"] = digest(row)
        row["signature"] = hmac.new(key, canonical(row), hashlib.sha256).hexdigest()
        body = canonical(row) + b"\n"
        if len(body) > MAX_RECORD_BYTES or (path.stat().st_size if path.exists() else 0) + len(body) > MAX_LOG_BYTES:
            raise ValueError("SHADOW_LOG_LIMIT")
        fd = os.open(str(path), os.O_APPEND | os.O_WRONLY | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o600)
        with os.fdopen(fd, "ab", closefd=True) as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        lock.unlink()
    return {"state": "SIGNED", "changes": len(row["diff"]["entered"]),
            "ranking_changed": row["diff"]["ranking_changed"],
            "reason_code": row["diff"]["reason_code"],
            "input_families_changed": len(row["diff"]["changed_input_families"])}


def append_if_configured(doc: dict[str, Any], *, path: Path, asof: str) -> str:
    secret = os.environ.get("II_R2B_SHADOW_SIGNING_KEY")
    if secret is None:
        return "UNCONFIGURED"
    # Do not print, persist, include in exception text, or log this secret.
    return append_signed(path, doc, key=secret.encode("utf-8"), asof=asof)["state"]
