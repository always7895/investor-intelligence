"""Append-only, signed, score-neutral Top20 rotation and screener shadow evidence.

No account, broker, credential, user identity, SEC header, or private holdings enter records.
An HMAC signing key must be explicitly provisioned; no key means no attestation.
An input-family change is a possible cause, NOT proof of why ranking changed.

Retention authenticates a bounded tail from an HMAC-signed checkpoint, NOT a
full-lifetime genesis proof. A checkpoint anchors the final discarded observation;
earlier history is deliberately unavailable. Legacy v2 journals are never migrated.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import logging
import math
import re
import stat
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import validated_rule_engine as rule_engine
import ranking_write_policy as write_policy

SCHEMA = "top20-rotation-shadow-v3"
MAX_SEGMENT_BYTES = 4 * 1024 * 1024
MAX_RETAINED_SEGMENTS = 8
MAX_RECORD_BYTES = 1024 * 1024
LOCK_STALE_SECONDS = 300
UNVERIFIED_NOTICE_ZH = "本輪輪動來源鏈未驗證；排行仍依既有資料更新，請人工覆核。"
LOGGER = logging.getLogger(__name__)
INPUT_FAMILIES = ("prices", "filings", "serenity", "leopold", "events")
SYMBOL = re.compile(r"[A-Z0-9][A-Z0-9.^=-]{0,15}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def _safe_log_path(path: Path) -> None:
    # Inspect ancestors before descendants; never traverse a junction to inspect a leaf.
    absolute = path.absolute()
    for item in reversed((absolute, *absolute.parents)):
        try:
            metadata = item.lstat()
        except FileNotFoundError:
            continue
        if (stat.S_ISLNK(metadata.st_mode)
                or getattr(metadata, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
            raise ValueError("SHADOW_UNSAFE_PATH")
    if not path.parent.is_dir():
        raise ValueError("SHADOW_UNSAFE_PARENT")
    if path.exists() and not path.is_file():
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
        # Commit all validated evidence without copying source URLs, prose or the
        # full per-rule document into every hourly journal observation.
        result.append({"symbol": symbol, "verification": "UNVERIFIED", "ruleset": screen["ruleset"],
                       "input_sha256": screen["input_sha256"], "rules_sha256": digest(retained),
                       "status_counts": {status: sum(row["status"] == status for row in retained)
                                         for status in ("PASS", "FAIL", "UNKNOWN")}})
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
    previous_screen = {row["symbol"]: row["rules_sha256"] for row in previous.get("screener_shadow", [])} if previous else {}
    current_screen = {row["symbol"]: row["rules_sha256"] for row in screen}
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


def _verify_stream(stream: Any, key: bytes, previous: dict[str, Any] | None,
                   segment_index: int) -> dict[str, Any] | None:
    last = previous
    while line := stream.readline(MAX_RECORD_BYTES + 1):
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
        if (row.get("previous_entry_sha256") != (last["entry_sha256"] if last else None)
                or type(row.get("sequence")) is not int or row["sequence"] != (last["sequence"] + 1 if last else 1)
                or type(row.get("segment_index")) is not int or row["segment_index"] != segment_index):
            raise ValueError("SHADOW_CHAIN_INVALID")
        claimed = row.pop("entry_sha256", None)
        if not _sha(claimed) or claimed != digest(row):
            raise ValueError("SHADOW_ENTRY_HASH_INVALID")
        row["entry_sha256"], row["signature"] = claimed, signature
        if last and _clock(row.get("asof_utc")) <= _clock(last.get("asof_utc")):
            raise ValueError("SHADOW_NON_MONOTONIC")
        _clock(row.get("asof_utc"))
        last = row
    if last is previous and (segment_index or previous is not None):
        raise ValueError("SHADOW_EMPTY_SEGMENT")
    return last


def _checkpoint(path: Path, key: bytes) -> dict[str, Any] | None:
    checkpoint = path.with_name(path.name + ".checkpoint")
    _safe_log_path(checkpoint)
    if not checkpoint.exists():
        return None
    with checkpoint.open("rb") as stream:
        raw = stream.read(MAX_RECORD_BYTES + 4097)
    if len(raw) > MAX_RECORD_BYTES + 4096:
        raise ValueError("SHADOW_RECORD_LIMIT")
    wrapper = json.loads(raw, object_pairs_hook=_unique_object)
    if not isinstance(wrapper, dict):
        raise ValueError("SHADOW_CHAIN_INVALID")
    signature = wrapper.pop("signature", None)
    if (set(wrapper) != {"schema", "anchor"} or wrapper["schema"] != "top20-rotation-checkpoint-v1"
            or not _sha(signature) or not hmac.compare_digest(
                signature, hmac.new(key, canonical(wrapper), hashlib.sha256).hexdigest())):
        raise ValueError("SHADOW_SIGNATURE_INVALID")
    anchor = wrapper["anchor"]
    if (not isinstance(anchor, dict) or type(anchor.get("sequence")) is not int or anchor["sequence"] < 1
            or type(anchor.get("segment_index")) is not int or anchor["segment_index"] < 0):
        raise ValueError("SHADOW_CHAIN_INVALID")
    # Validate the anchor's original entry hash/signature as well as its wrapper.
    unsigned = {name: value for name, value in anchor.items() if name != "signature"}
    if (anchor.get("schema") != SCHEMA or not _sha(anchor.get("signature"))
            or not hmac.compare_digest(anchor["signature"], hmac.new(key, canonical(unsigned), hashlib.sha256).hexdigest())
            or unsigned.get("entry_sha256") != digest({name: value for name, value in unsigned.items()
                                                        if name != "entry_sha256"})):
        raise ValueError("SHADOW_ENTRY_HASH_INVALID")
    _clock(anchor.get("asof_utc"))
    return anchor


def _segment_index(path: Path, segment: Path) -> int:
    return 0 if segment == path else int(segment.name[len(path.name + ".segment-"):])


def _segments(path: Path, *, after: int | None = None) -> list[Path]:
    _safe_log_path(path)
    indexed = {0: path} if path.exists() else {}
    prefix = path.name + ".segment-"
    for child in path.parent.iterdir():
        if not child.name.startswith(prefix):
            continue
        suffix = child.name[len(prefix):]
        if not re.fullmatch(r"[0-9]{8}", suffix) or int(suffix) == 0:
            raise ValueError("SHADOW_SEGMENTS_INVALID")
        _safe_log_path(child)
        indexed[int(suffix)] = child
    retained = sorted(index for index in indexed if after is None or index > after)
    if after is not None and any(index != after + 1 + offset for offset, index in enumerate(retained)):
        raise ValueError("SHADOW_SEGMENTS_INVALID")
    return [indexed[index] for index in retained]


def _verify_chain(path: Path, key: bytes) -> tuple[dict[str, Any] | None, list[Path]]:
    if not isinstance(key, bytes) or len(key) < 32:
        raise ValueError("SHADOW_SIGNING_KEY_UNAVAILABLE")
    last = _checkpoint(path, key)
    segments = _segments(path, after=last["segment_index"] if last else -1)
    if last and not segments:
        raise ValueError("SHADOW_EMPTY_SEGMENT")
    for segment in segments:
        if segment.stat().st_size > MAX_SEGMENT_BYTES:
            raise ValueError("SHADOW_SEGMENT_LIMIT")
        with segment.open("rb") as stream:
            last = _verify_stream(stream, key, last, _segment_index(path, segment))
    return last, segments


def verify_log(path: Path, key: bytes) -> dict[str, Any] | None:
    """Authenticate the retained tail from genesis or its signed retention checkpoint."""
    return _verify_chain(path, key)[0]


def _retain_tail(path: Path, key: bytes, segments: list[Path]) -> None:
    anchor = _checkpoint(path, key)
    while len(segments) > MAX_RETAINED_SEGMENTS:
        discarded = segments.pop(0)
        with discarded.open("rb") as stream:
            anchor = _verify_stream(stream, key, anchor, _segment_index(path, discarded))
        wrapper = {"schema": "top20-rotation-checkpoint-v1", "anchor": anchor}
        wrapper["signature"] = hmac.new(key, canonical(wrapper), hashlib.sha256).hexdigest()
        checkpoint = path.with_name(path.name + ".checkpoint")
        temp = path.with_name(path.name + ".checkpoint.tmp")
        _safe_log_path(temp)
        with temp.open("wb") as stream:
            stream.write(canonical(wrapper))
            stream.flush()
            os.fsync(stream.fileno())
        temp.replace(checkpoint)  # Publish authenticated anchor BEFORE deleting history.
    if anchor:
        # Also finish deletion after a crash between checkpoint publication and unlink.
        for old in _segments(path):
            if _segment_index(path, old) <= anchor["segment_index"]:
                old.unlink()


def _windows_process_alive(pid: int) -> bool | None:
    # Query-only rights: os.kill(pid, 0) is NOT a liveness probe on Windows.
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel.GetExitCodeProcess.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION only
    if not handle:
        return False if ctypes.get_last_error() == 87 else None  # invalid PID; denied/unknown stays busy
    try:
        code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
            return None
        return code.value == 259  # STILL_ACTIVE
    finally:
        kernel.CloseHandle(handle)


def _process_alive(pid: int) -> bool | None:
    if os.name == "nt":
        return _windows_process_alive(pid)
    try:
        os.kill(pid, 0)  # POSIX signal zero never sends a signal.
    except ProcessLookupError:
        return False
    except OSError:
        return None
    return True


def _file_lock(fd: int, *, release: bool = False) -> None:
    # A stable lock inode plus an OS lock prevents simultaneous stale-owner
    # recovery from unlinking a replacement writer's lock.
    os.lseek(fd, 0, os.SEEK_SET)
    if os.name == "nt":
        import msvcrt
        msvcrt.locking(fd, msvcrt.LK_UNLCK if release else msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_UN if release else fcntl.LOCK_EX | fcntl.LOCK_NB)


def _write_lock(fd: int, value: dict[str, Any]) -> None:
    os.lseek(fd, 0, os.SEEK_SET)
    body = canonical(value)
    if os.write(fd, body) != len(body):
        raise OSError("SHADOW_LOCK_WRITE_FAILED")
    os.ftruncate(fd, len(body))
    os.fsync(fd)


def _acquire_lock(path: Path) -> int:
    _safe_log_path(path)
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_RDWR | getattr(os, "O_BINARY", 0), 0o600)
        created = True
    except FileExistsError:
        fd = os.open(str(path), os.O_RDWR | getattr(os, "O_BINARY", 0))
        created = False
    locked = False
    try:
        try:
            _file_lock(fd)
        except OSError:
            raise ValueError("SHADOW_WRITER_BUSY") from None
        locked = True
        if not created:
            try:
                owner = json.loads(os.read(fd, 513), object_pairs_hook=_unique_object)
            except (ValueError, UnicodeDecodeError):
                raise ValueError("SHADOW_WRITER_BUSY") from None
            if owner != {"released": True}:
                if (not isinstance(owner, dict) or set(owner) != {"pid", "created_at"}
                        or type(owner["pid"]) is not int or not 0 < owner["pid"] <= 0xFFFFFFFF
                        or type(owner["created_at"]) not in (int, float) or not math.isfinite(owner["created_at"])
                        or time.time() - owner["created_at"] < LOCK_STALE_SECONDS
                        or _process_alive(owner["pid"]) is not False):
                    raise ValueError("SHADOW_WRITER_BUSY")
        _write_lock(fd, {"pid": os.getpid(), "created_at": time.time()})
        return fd
    except BaseException:
        if locked:
            _file_lock(fd, release=True)
        os.close(fd)
        raise


def append_signed(path: Path, doc: dict[str, Any], *, key: bytes, asof: str) -> dict[str, Any]:
    if not isinstance(key, bytes) or len(key) < 32:
        raise ValueError("SHADOW_SIGNING_KEY_UNAVAILABLE")
    _safe_log_path(path)
    # Read-only suppression does not even rewrite the writer lock or observation clock.
    observed = verify_log(path, key)
    if observed and _clock(observed["asof_utc"]) > _clock(asof):
        raise ValueError("SHADOW_NON_MONOTONIC")
    if (observed and not doc.get("source_failures") and doc.get("refresh_state") != "REFRESH_FAILED"
            and write_policy.publication_due(observed, {**doc, "generated_at": asof}, _clock(asof)) == "NO_CHANGE"):
        return {"state": "SKIPPED_NO_CHANGE", "asof_utc": observed["asof_utc"],
                "changes": 0, "input_families_changed": 0, "ranking_changed": False}
    lock_fd = _acquire_lock(path.with_name(path.name + ".lock"))
    try:
        prev, segments = _verify_chain(path, key)
        if doc.get("refresh_state") == "REFRESH_FAILED" or doc.get("source_failures"):
            return {"state": "REFRESH_FAILED", "asof_utc": prev["asof_utc"] if prev else None,
                    "changes": 0, "input_families_changed": 0, "ranking_changed": False}
        if prev and _clock(prev["asof_utc"]) > _clock(asof):
            raise ValueError("SHADOW_NON_MONOTONIC")
        due = write_policy.publication_due(prev, {**doc, "generated_at": asof}, _clock(asof))
        if due == "NO_CHANGE":
            return {"state": "SKIPPED_NO_CHANGE", "asof_utc": prev["asof_utc"],
                    "changes": 0, "input_families_changed": 0, "ranking_changed": False}
        if prev and _clock(prev["asof_utc"]) == _clock(asof):
            raise ValueError("SHADOW_NON_MONOTONIC")  # Changed signed rows need a later clock.
        # Finish any interrupted retention before allowing further growth.
        # A failed checkpoint can leave one bounded overflow record, never
        # repeated new segments on subsequent attempts.
        _retain_tail(path, key, segments)
        row = build_record(doc, prev, asof=asof)
        index = _segment_index(path, segments[-1]) if segments else 0
        row.update(sequence=prev["sequence"] + 1 if prev else 1, segment_index=index)
        row["publication_due"] = due
        row["entry_sha256"] = digest(row)
        row["signature"] = hmac.new(key, canonical(row), hashlib.sha256).hexdigest()
        body = canonical(row) + b"\n"
        if len(body) > min(MAX_RECORD_BYTES, MAX_SEGMENT_BYTES):
            raise ValueError("SHADOW_RECORD_LIMIT")
        target = segments[-1] if segments else path
        rollover = target.exists() and target.stat().st_size + len(body) > MAX_SEGMENT_BYTES
        if rollover:
            index += 1
            if index > 99999999:
                raise ValueError("SHADOW_SEGMENT_LIMIT")
            target = path.with_name(f"{path.name}.segment-{index:08d}")
            _safe_log_path(target)
            row.pop("signature")
            row.pop("entry_sha256")
            row["segment_index"] = index
            row["entry_sha256"] = digest(row)
            row["signature"] = hmac.new(key, canonical(row), hashlib.sha256).hexdigest()
            body = canonical(row) + b"\n"
            if len(body) > min(MAX_RECORD_BYTES, MAX_SEGMENT_BYTES):
                raise ValueError("SHADOW_RECORD_LIMIT")
        flags = os.O_WRONLY | os.O_CREAT | getattr(os, "O_BINARY", 0)
        flags |= os.O_EXCL if rollover else os.O_APPEND
        fd = os.open(str(target), flags, 0o600)
        with os.fdopen(fd, "ab", closefd=True) as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        _retain_tail(path, key, [*segments, target] if target not in segments else segments)
    finally:
        try:
            _write_lock(lock_fd, {"released": True})
        finally:
            try:
                _file_lock(lock_fd, release=True)
            finally:
                os.close(lock_fd)
    return {"state": "SIGNED", "changes": len(row["diff"]["entered"]),
            "ranking_changed": row["diff"]["ranking_changed"],
            "reason_code": row["diff"]["reason_code"],
            "input_families_changed": len(row["diff"]["changed_input_families"])}


def append_if_configured(doc: dict[str, Any], *, path: Path, asof: str) -> str:
    secret = os.environ.get("II_R2B_SHADOW_SIGNING_KEY")
    if secret is None:
        return "UNCONFIGURED"
    try:
        # Never print, persist, or include this secret in exception text.
        return append_signed(path, doc, key=secret.encode("utf-8"), asof=asof)["state"]
    except Exception as error:
        causes = {
            "SHADOW_WRITER_BUSY", "SHADOW_SIGNING_KEY_UNAVAILABLE", "SHADOW_RECORD_LIMIT", "SHADOW_SEGMENT_LIMIT",
            "SHADOW_UNSAFE_PATH", "SHADOW_UNSAFE_PARENT", "SHADOW_UNSAFE_FILE", "SHADOW_SEGMENTS_INVALID",
            "SHADOW_RECORD_TRUNCATED", "SHADOW_RECORD_INVALID", "SHADOW_SCHEMA_INVALID",
            "SHADOW_SIGNATURE_INVALID", "SHADOW_CHAIN_INVALID", "SHADOW_ENTRY_HASH_INVALID",
            "SHADOW_NON_MONOTONIC", "SHADOW_EMPTY_SEGMENT", "SHADOW_CLOCK_INVALID",
            "SHADOW_TOP_INVALID", "SHADOW_TICKER_INVALID", "SHADOW_DUPLICATE_TICKER",
            "SHADOW_FINGERPRINTS_INVALID", "SHADOW_FINGERPRINTS_INCOMPLETE",
            "SHADOW_INPUT_CONTEXT_INVALID", "SHADOW_SCREENER_INVALID", "SHADOW_DUPLICATE_FIELD",
        }
        cause = (str(error) if type(error) is ValueError and str(error) in causes else
                 "SHADOW_IO_ERROR" if isinstance(error, OSError) else "SHADOW_INTERNAL_ERROR")
        doc["rotation_provenance"] = {"status": "UNVERIFIED", "notice_zh": UNVERIFIED_NOTICE_ZH}
        try:
            LOGGER.warning("Rotation provenance UNVERIFIED: %s", cause)
        except Exception:
            pass  # A logging sink is shadow-only too; never turn it into a ranking outage.
        return "UNVERIFIED"
