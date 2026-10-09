#!/usr/bin/env python3
"""M1: operator-enrolled local model registry, user-triggered METADATA-ONLY refresh, verified MANUAL choice and an opt-in READ-ONLY
priority SUGGESTION. One shared helper for the EXE (launcher/InvestorIntelligenceLauncher.cs) and any other caller: no GUI-only
validation.

What this is: a bounded registry of explicitly enrolled (loopback root, exact model id, original seven-field profile, unique priority)
descriptors in <user config>/v213-model-registry-v1.json. Enrollment, removal and the opt-in flag are OFFLINE operations. A refresh
asks ONLY the enrolled roots, only /health and /v1/models through the shared credential-free transport
(v213_model_profile.selected_metadata); a candidate is SERVED_METADATA_ONLY only when that shared check passes for its exact model.
Only the manual `select` operation writes REQUEST INTENT, through the original v213_model_profile.save_binding, after the user chose
that exact candidate; it never starts, stops, loads or replaces anything. The opt-in `suggest` operation is READ-ONLY: it proposes the
served candidate with the lowest user priority (AUTO_SELECTION_PROPOSAL) and a user must confirm it with `select`; it never calls
save_binding and never writes a file, profile, binding or environment value, because a registry lock cannot serialize every other
binding writer. Actual automatic selection saving and resident-weight replacement stay OPEN
(BLOCKED_EXCLUSIVITY_AND_NATIVE_ADMISSION). There is no FULLY_QUALIFIED state and no capacity claim.

Path authority (every FS access): the user config folder must be a drive-letter absolute spelling on a PROVEN direct local volume with
a no-follow plain-directory ancestor walk, and the registry, lock and temp paths must each fit 240 UTF-16 units, BEFORE any
metadata read, mkdir, open or lock (shared local_model_endpoint._require_local_chain, which refuses reparse, offline and recall
flags); the chain is re-proven after a directory is created. The registry is read as bounded raw bytes with the shared terminal guards
and decoded with the shared duplicate-key/depth/node-safe strict_object, so a duplicated key or malformed presence is refused, never
empty. Writes are a fixed temp name under an OS-owned non-blocking lock (msvcrt byte lock on a persistent validated regular file,
imported lazily): ownership is the OS lock, never file age or existence, and nothing is ever stolen or unlinked by time. Native and
handle-race behavior is NOT_RUN and unproven.

Bounds: at most 16 candidates; the registry file is at most 64 KiB; one refresh accepts results for at most 20 seconds in total
(a result-acceptance deadline, NOT a proven hard OS wall: outstanding I/O is bounded separately and a late reply is refused) and
makes at most 16 evaluations of at most 2 GETs, each body bounded by 131071 bytes plus one over-limit detection byte, so at most
16 * 2 * 131072 = 4 MiB of received BODY bytes (HTTP headers and wire bytes are not covered by that limit). Failed and oversized
replies count; nothing is retried or re-fetched within the budget. Ports 5000 (IBKR Client Portal) and 8000 (retired System One)
are never enrolled or probed. Missing registry means empty. No cache becomes availability: refresh results are returned to the
caller, never stored.

CLI: python scripts/local_model_catalog.py --op list|register|remove|set-opt-in|refresh|select|suggest  (JSON request on stdin,
one JSON line out; exit 0 on success, 1 with a finite sanitized reason otherwise)."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any, Callable

SCHEMA_VERSION = 1
REGISTRY_NAME = "v213-model-registry-v1.json"
LOCK_NAME = "v213-model-registry-v1.lck"
TEMP_NAME = "v213-model-registry-v1.tmp"
REGISTRY_LIMIT = 65536
MAX_CANDIDATES = 16
MIN_PRIORITY, MAX_PRIORITY = 1, 64
PROTECTED_PORTS = frozenset({5000, 8000})
REFRESH_DEADLINE_SECONDS = 20
EVALUATION_BUDGET_SECONDS = 15
MAX_BODY_BYTES = 131071
REPLACEMENT_STATE = "BLOCKED_EXCLUSIVITY_AND_NATIVE_ADMISSION"
_REASON = re.compile(r"[A-Z][A-Z0-9_]{0,63}")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_ENTRY_KEYS = {"base_url", "model", "profile", "priority"}
_REGISTRY_KEYS = {"schema_version", "auto_select_opt_in", "candidates"}


class CatalogUnavailable(ValueError):
    """Finite sanitized reason code only; never a raw payload, path, header or credential."""


def _shared() -> Any:
    try:
        import v213_model_profile as shared  # the ONE profile/binding schema, hash and credential-free transport
    except Exception:
        raise CatalogUnavailable("CATALOG_HELPER_UNAVAILABLE") from None
    return shared


def _endpoint() -> Any:
    try:
        import local_model_endpoint as endpoint  # the shared bounded, no-link, UTF-16-ceiling state reader and path authority
    except Exception:
        raise CatalogUnavailable("CATALOG_HELPER_UNAVAILABLE") from None
    return endpoint


def _reason(error: BaseException) -> str:
    text = str(error)
    if isinstance(error, ValueError) and not isinstance(error, UnicodeError) and _REASON.fullmatch(text):
        return text
    return "CATALOG_OPERATION_UNAVAILABLE"


def _proven_folder() -> Path:
    """The user config folder, proven BEFORE any registry/lock/temp metadata, read, mkdir, open or lock: lexical drive-letter spelling,
    every derived path within the UTF-16 ceiling, a proven direct local volume and a no-follow plain-directory ancestor walk (the
    first genuinely missing component is legitimate absence). No GetFullPath/Resolve and no UNC or remote access to establish it."""
    shared = _shared()
    endpoint = _endpoint()
    try:
        configured = shared._user_paths()[0]
    except Exception:
        raise CatalogUnavailable("CATALOG_USERDATA_UNAVAILABLE") from None
    try:
        folder = endpoint._local_absolute_folder(str(configured))
        endpoint._require_local_chain(folder, (REGISTRY_NAME, LOCK_NAME, TEMP_NAME))
    except endpoint.IntentUnavailable as error:
        raise CatalogUnavailable(_reason(error)) from None
    return folder


def registry_path() -> Path:
    return _proven_folder() / REGISTRY_NAME


def _validate_entry(entry: Any) -> dict[str, Any]:
    shared = _shared()
    if not isinstance(entry, dict) or set(entry) != _ENTRY_KEYS:
        raise CatalogUnavailable("CATALOG_ENTRY_INVALID")
    try:
        root = shared.canonical_strata_root(entry["base_url"])
        profile = shared.validate_profile(entry["profile"])
    except (ValueError, KeyError, TypeError):
        raise CatalogUnavailable("CATALOG_ENTRY_INVALID") from None
    if int(root.rsplit(":", 1)[1]) in PROTECTED_PORTS:
        raise CatalogUnavailable("CATALOG_PORT_PROTECTED")
    if entry["model"] != profile["model"]:
        raise CatalogUnavailable("CATALOG_ENTRY_INVALID")
    priority = entry["priority"]
    if type(priority) is not int or not MIN_PRIORITY <= priority <= MAX_PRIORITY:
        raise CatalogUnavailable("CATALOG_PRIORITY_INVALID")
    return {"base_url": root, "model": profile["model"], "profile": profile, "priority": priority}


def _identity(entry: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], str]:
    """(binding, profile, binding_sha256) with the ORIGINAL schema and hash; no new binding schema exists."""
    shared = _shared()
    profile = shared.validate_profile(entry["profile"])
    binding = {"schema_version": 1, "engine": "strata", "base_url": entry["base_url"], "model": entry["model"],
               "model_profile_sha256": shared.profile_sha256(profile), "qualification": "UNQUALIFIED"}
    return binding, profile, shared.binding_sha256(binding, profile)


def validate_registry(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _REGISTRY_KEYS:
        raise CatalogUnavailable("CATALOG_SCHEMA_INVALID")
    if (type(value["schema_version"]) is not int or value["schema_version"] != SCHEMA_VERSION
            or type(value["auto_select_opt_in"]) is not bool or not isinstance(value["candidates"], list)
            or len(value["candidates"]) > MAX_CANDIDATES):
        raise CatalogUnavailable("CATALOG_SCHEMA_INVALID")
    priorities: set[int] = set()
    digests: set[str] = set()
    pairs: set[tuple[str, str]] = set()
    candidates = []
    for item in value["candidates"]:
        entry = _validate_entry(item)
        digest = _identity(entry)[2]
        pair = (entry["base_url"], entry["model"])
        if entry["priority"] in priorities or digest in digests or pair in pairs:
            raise CatalogUnavailable("CATALOG_DUPLICATE")
        priorities.add(entry["priority"])
        digests.add(digest)
        pairs.add(pair)
        candidates.append(entry)
    return {"schema_version": SCHEMA_VERSION, "auto_select_opt_in": value["auto_select_opt_in"], "candidates": candidates}


def _registry_sha256(registry: dict[str, Any]) -> str:
    """Semantic identity of the VALIDATED registry (opt-in flag, priorities and every descriptor): the sha256 of its canonical sorted
    compact JSON. It is a change detector for this helper only, not a binding hash and not a policy hash."""
    text = json.dumps(registry, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def load_registry() -> tuple[dict[str, Any], str]:
    """(validated registry, semantic sha256). A MISSING file is the honestly empty registry. A present link, reparse point, offline or
    recall-flagged file, directory, over-long path, unreadable, oversized, malformed or duplicate-key file is refused, never empty."""
    shared = _shared()
    endpoint = _endpoint()
    path = registry_path()
    try:
        raw = endpoint._read_state_bytes(path, REGISTRY_LIMIT)
    except endpoint.IntentUnavailable as error:
        raise CatalogUnavailable(_reason(error)) from None
    if raw is None:
        empty = {"schema_version": SCHEMA_VERSION, "auto_select_opt_in": False, "candidates": []}
        return empty, _registry_sha256(empty)
    try:
        value = shared.strict_object(raw.decode("utf-8-sig"), REGISTRY_LIMIT)
    except (shared.BindingUnavailable, UnicodeError):
        raise CatalogUnavailable("CATALOG_STATE_INVALID") from None
    registry = validate_registry(value)
    return registry, _registry_sha256(registry)


class _Serialized:
    """OS-owned, non-blocking write serialization: a one-byte msvcrt lock on a persistent, validated, regular lock file. The lock is owned
    by this handle and released by the OS when the process exits; the file is never unlinked and nothing is reclaimed by age or
    existence. Busy or unknown state is CATALOG_BUSY; a non-Windows host refuses runtime I/O. msvcrt is imported lazily so pure
    validation stays importable everywhere."""

    def __enter__(self) -> "_Serialized":
        try:
            import msvcrt
        except ImportError:
            raise CatalogUnavailable("CATALOG_LOCK_UNSUPPORTED") from None
        endpoint = _endpoint()
        folder = _proven_folder()  # proof BEFORE any create/open
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            raise CatalogUnavailable("CATALOG_STATE_UNAVAILABLE") from None
        folder = _proven_folder()  # the created chain is proven again before the lock file is touched
        path = folder / LOCK_NAME
        try:
            attributes = endpoint._file_attributes(str(path))
            if attributes is not None and attributes & (endpoint._REFUSED_ATTRIBUTES | endpoint._DIRECTORY_ATTRIBUTE):
                raise CatalogUnavailable("CATALOG_LOCK_UNSAFE")
            fd = os.open(str(path), os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0))
        except endpoint.IntentUnavailable as error:
            raise CatalogUnavailable(_reason(error)) from None
        except OSError:
            raise CatalogUnavailable("CATALOG_STATE_UNAVAILABLE") from None
        try:
            opened = os.fstat(fd)
            named = os.lstat(path)
            if (not stat.S_ISREG(opened.st_mode) or opened.st_size > 1 or endpoint._is_link_or_reparse(named)
                    or (opened.st_ino and (opened.st_ino, opened.st_dev) != (named.st_ino, named.st_dev))):
                raise CatalogUnavailable("CATALOG_LOCK_UNSAFE")
            os.lseek(fd, 0, 0)
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            except OSError:
                raise CatalogUnavailable("CATALOG_BUSY") from None
        except BaseException:
            os.close(fd)
            raise
        self.fd = fd
        self.msvcrt = msvcrt
        return self

    def __exit__(self, *exc: Any) -> None:
        try:
            os.lseek(self.fd, 0, 0)
            self.msvcrt.locking(self.fd, self.msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        finally:
            os.close(self.fd)


def _discard_owned_temp(endpoint: Any, temp: Path, owned: tuple[int, int]) -> None:
    """FAILURE cleanup only, with NO following query: the entry at the temp name is removed only when the shared no-follow attribute query
    and lstat show a plain regular file whose (inode, device) is the identity this operation recorded when it created the temp. Anything
    else (changed, link, reparse, offline/recall, directory, unknown or inaccessible) is left in place untouched."""
    try:
        attributes = endpoint._file_attributes(str(temp))
        if attributes is None or attributes & (endpoint._REFUSED_ATTRIBUTES | endpoint._DIRECTORY_ATTRIBUTE):
            return
        named = os.lstat(temp)
        if endpoint._is_link_or_reparse(named) or not stat.S_ISREG(named.st_mode) or (named.st_ino, named.st_dev) != owned:
            return
        os.unlink(temp)
    except (OSError, endpoint.IntentUnavailable):
        return


def _write_registry(registry: dict[str, Any]) -> None:
    """Atomic write under the held lock: re-proven folder, fixed bounded temp name created EXCLUSIVELY (a leftover entry at that name is
    REFUSED as CATALOG_TEMP_LEFTOVER and never deleted by name), the identity of the temp this operation created is recorded, fsync,
    then os.replace consumes it. After a successful replace the name is no longer this operation's: nothing is probed or deleted there.
    After a failure only an entry that still has the recorded identity is removed (no following existence check anywhere). Handle-level
    races remain unproven."""
    endpoint = _endpoint()
    folder = _proven_folder()
    path, temp = folder / REGISTRY_NAME, folder / TEMP_NAME
    text = json.dumps(registry, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    if len(text) > REGISTRY_LIMIT:
        raise CatalogUnavailable("CATALOG_TOO_LARGE")
    try:
        if endpoint._file_attributes(str(temp)) is not None:
            raise CatalogUnavailable("CATALOG_TEMP_LEFTOVER")  # nothing is deleted by name; the operator must remove a crashed writer's leftover
        fd = os.open(str(temp), os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0))
        owned: tuple[int, int] | None = None
        consumed = False
        try:
            with os.fdopen(fd, "wb") as handle:
                info = os.fstat(handle.fileno())
                owned = (info.st_ino, info.st_dev) if info.st_ino else None
                handle.write(text.encode("ascii"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path)
            consumed = True
        finally:
            if not consumed and owned is not None:
                _discard_owned_temp(endpoint, temp, owned)
    except endpoint.IntentUnavailable as error:
        raise CatalogUnavailable(_reason(error)) from None
    except OSError:
        raise CatalogUnavailable("CATALOG_STATE_UNAVAILABLE") from None


def _describe(registry: dict[str, Any], sha: str) -> dict[str, Any]:
    rows = []
    for entry in sorted(registry["candidates"], key=lambda item: item["priority"]):
        rows.append({"binding_sha256": _identity(entry)[2], "base_url": entry["base_url"], "model": entry["model"],
                     "priority": entry["priority"], "profile": entry["profile"], "state": "REGISTERED"})
    return {"scope": "REGISTRY", "schema_version": SCHEMA_VERSION, "auto_select_opt_in": registry["auto_select_opt_in"],
            "registry_sha256": sha, "candidates": rows, "replacement": REPLACEMENT_STATE, "weights_replaced": False,
            "qualification": "UNQUALIFIED"}


def list_registry() -> dict[str, Any]:
    registry, sha = load_registry()
    return _describe(registry, sha)


def register(entry: Any) -> dict[str, Any]:
    with _Serialized():
        registry, _ = load_registry()
        normalized = _validate_entry(entry)
        updated = validate_registry({**registry, "candidates": [*registry["candidates"], normalized]})
        _write_registry(updated)
    return _describe(updated, _registry_sha256(updated))


def remove(binding_sha256: Any) -> dict[str, Any]:
    if not isinstance(binding_sha256, str) or _DIGEST.fullmatch(binding_sha256) is None:
        raise CatalogUnavailable("CATALOG_REQUEST_INVALID")
    with _Serialized():
        registry, _ = load_registry()
        kept = [entry for entry in registry["candidates"] if _identity(entry)[2] != binding_sha256]
        if len(kept) == len(registry["candidates"]):
            raise CatalogUnavailable("CATALOG_CANDIDATE_UNKNOWN")
        updated = validate_registry({**registry, "candidates": kept})
        _write_registry(updated)
    return _describe(updated, _registry_sha256(updated))


def set_opt_in(value: Any) -> dict[str, Any]:
    if type(value) is not bool:
        raise CatalogUnavailable("CATALOG_REQUEST_INVALID")
    with _Serialized():
        registry, _ = load_registry()
        updated = validate_registry({**registry, "auto_select_opt_in": value})
        _write_registry(updated)
    return _describe(updated, _registry_sha256(updated))


def _context_minimum(root: Any) -> int:
    shared = _shared()
    try:
        return shared.context_minimum(root)
    except Exception:
        raise CatalogUnavailable("CATALOG_CONTEXT_POLICY_UNAVAILABLE") from None


def refresh(root: Any, *, metadata_reader: Callable[..., Any] | None = None,
            clock: Callable[[], float] | None = None) -> dict[str, Any]:
    """User-triggered METADATA-ONLY refresh of the ENROLLED roots. Whole 20 s result-acceptance deadline, at most 16 evaluations, each
    at most 2 GETs of at most 131071 (+1) body bytes: <= 4 MiB of received bodies. No retry, no other URL, no unenrolled root."""
    import time
    clock = clock or time.monotonic
    shared = _shared()
    registry, sha = load_registry()
    reader = metadata_reader or shared.selected_metadata
    minimum = _context_minimum(root)
    deadline = clock() + REFRESH_DEADLINE_SECONDS
    rows: list[dict[str, Any]] = []
    evaluations = 0
    exhausted = False
    for entry in sorted(registry["candidates"], key=lambda item: item["priority"]):
        binding, profile, digest = _identity(entry)
        row = {"binding_sha256": digest, "base_url": entry["base_url"], "model": entry["model"], "priority": entry["priority"],
               "state": "REGISTERED", "reason": "", "declared_context": None, "qualification": "UNQUALIFIED"}
        remaining = deadline - clock()
        if exhausted or remaining <= 0 or evaluations >= MAX_CANDIDATES:
            exhausted = True
            row.update(state="BUDGET_EXHAUSTED", reason="CATALOG_REFRESH_BUDGET_EXHAUSTED")
            rows.append(row)
            continue
        evaluations += 1
        try:
            metadata = reader(binding, profile, minimum, budget=min(EVALUATION_BUDGET_SECONDS, remaining),
                              max_response_bytes=MAX_BODY_BYTES)
        except shared.BindingUnavailable as error:
            row.update(state="UNAVAILABLE", reason=_reason(error))
        except Exception:
            row.update(state="UNAVAILABLE", reason="CATALOG_OPERATION_UNAVAILABLE")
        else:
            if clock() > deadline:
                exhausted = True
                row.update(state="UNAVAILABLE", reason="CATALOG_REFRESH_LATE_REPLY_REFUSED")
            elif (not isinstance(metadata, dict) or metadata.get("binding_sha256") != digest
                    or metadata.get("model") != entry["model"] or type(metadata.get("declared_context")) is not int):
                row.update(state="UNAVAILABLE", reason="CATALOG_METADATA_IDENTITY_MISMATCH")
            else:
                row.update(state="SERVED_METADATA_ONLY", declared_context=metadata["declared_context"])
        rows.append(row)
    return {"scope": "METADATA_ONLY", "deadline_seconds": REFRESH_DEADLINE_SECONDS, "evaluations": evaluations,
            "max_received_body_bytes": MAX_CANDIDATES * 2 * (MAX_BODY_BYTES + 1), "registry_sha256": sha,
            "auto_select_opt_in": registry["auto_select_opt_in"], "rows": rows, "replacement": REPLACEMENT_STATE,
            "weights_replaced": False, "qualification": "UNQUALIFIED"}


def _entry_for(registry: dict[str, Any], digest: str) -> dict[str, Any]:
    for entry in registry["candidates"]:
        if _identity(entry)[2] == digest:
            return entry
    raise CatalogUnavailable("CATALOG_CANDIDATE_UNKNOWN")


def _save(root: str, entry: dict[str, Any]) -> None:
    """The ONLY write of request intent in this module (manual `select` only): the original offline save_binding."""
    shared = _shared()
    shared.save_binding(root, {"root": root, "base_url": entry["base_url"], "model": entry["model"], "profile": entry["profile"]})


def select(root: Any, binding_sha256: Any, *, metadata_reader: Callable[..., Any] | None = None) -> dict[str, Any]:
    """Manual verified selection of the candidate the user chose: re-read the registry, verify that exact candidate with its OWN bounded
    metadata check (2 GETs of at most 131071 (+1) bytes, <= 15 s), re-read the registry again, require the identical candidate, then
    save request intent only. Race limits: a registry lock cannot serialize other binding writers; the launcher serializes its own."""
    if not isinstance(root, str) or not isinstance(binding_sha256, str) or _DIGEST.fullmatch(binding_sha256) is None:
        raise CatalogUnavailable("CATALOG_REQUEST_INVALID")
    shared = _shared()
    registry, _ = load_registry()
    entry = _entry_for(registry, binding_sha256)
    binding, profile, digest = _identity(entry)
    reader = metadata_reader or shared.selected_metadata
    metadata = reader(binding, profile, _context_minimum(root), budget=EVALUATION_BUDGET_SECONDS, max_response_bytes=MAX_BODY_BYTES)
    if not isinstance(metadata, dict) or metadata.get("binding_sha256") != digest or metadata.get("model") != entry["model"]:
        raise CatalogUnavailable("CATALOG_METADATA_IDENTITY_MISMATCH")
    again, _ = load_registry()
    if _entry_for(again, binding_sha256) != entry:
        raise CatalogUnavailable("CATALOG_REGISTRY_CHANGED")
    _save(root, entry)
    return {"scope": "VERIFIED_REQUEST_INTENT", "state": "SELECTED_INTENT", "binding_sha256": digest,
            "base_url": entry["base_url"], "model": entry["model"], "metadata_scope": "METADATA_ONLY",
            "replacement": REPLACEMENT_STATE, "weights_replaced": False, "qualification": "UNQUALIFIED"}


def _current_intent(root: str) -> tuple[str, str]:
    shared = _shared()
    try:
        saved = shared.resolve_binding(root)
    except (ValueError, OSError, KeyError, TypeError):
        raise CatalogUnavailable("CATALOG_SAVED_INTENT_UNAVAILABLE") from None
    return str(saved.get("mode")), str(saved.get("binding_sha256", ""))


def suggest(root: Any, *, startup: bool = False, metadata_reader: Callable[..., Any] | None = None,
            clock: Callable[[], float] | None = None) -> dict[str, Any]:
    """READ-ONLY opt-in priority SUGGESTION (AUTO_SELECTION_PROPOSAL): among the REGISTERED candidates that a fresh metadata refresh shows
    as SERVED_METADATA_ONLY, propose the one with the lowest unique user priority (never a family, performance or quantization guess).
    It never calls save_binding or any writer and never changes a file, profile, binding or environment value; the user must confirm
    with `select`. After the metadata the opt-in flag, the WHOLE registry identity (priorities included) and the current saved intent
    are read again; any change, revocation or unreadable intent returns a finite refusal and no proposal. A saved or external intent
    that differs from the pick is reported in the result, not overwritten. This does not claim to close races with other writers."""
    if not isinstance(root, str):
        raise CatalogUnavailable("CATALOG_REQUEST_INVALID")
    registry, sha = load_registry()
    if not registry["auto_select_opt_in"] or not registry["candidates"]:
        if startup:
            return {"scope": "AUTO_SELECTION_PROPOSAL", "state": "NOT_ENABLED_OR_EMPTY", "saved": False, "weights_replaced": False}
        raise CatalogUnavailable("CATALOG_AUTO_NOT_OPTED_IN" if not registry["auto_select_opt_in"] else "CATALOG_REGISTRY_EMPTY")
    before = _current_intent(root)
    refreshed = refresh(root, metadata_reader=metadata_reader, clock=clock)
    again, again_sha = load_registry()
    if refreshed["registry_sha256"] != sha or again_sha != sha or not again["auto_select_opt_in"] or _current_intent(root) != before:
        raise CatalogUnavailable("CATALOG_PROPOSAL_STALE")  # registry, opt-in, priorities or current intent changed: no proposal
    served = [row for row in refreshed["rows"] if row["state"] == "SERVED_METADATA_ONLY"]
    base = {"scope": "AUTO_SELECTION_PROPOSAL", "saved": False, "requires_manual_confirmation": True, "registry_sha256": sha,
            "rows": refreshed["rows"], "current_intent_mode": before[0], "replacement": REPLACEMENT_STATE,
            "weights_replaced": False, "qualification": "UNQUALIFIED"}
    if not served:
        if startup:
            return {**base, "state": "NO_SERVED_CANDIDATE"}
        raise CatalogUnavailable("CATALOG_AUTO_NO_SERVED_CANDIDATE")
    pick = min(served, key=lambda row: row["priority"])
    same = before[0] == "EXPLICIT_STRATA" and before[1] == pick["binding_sha256"]
    external = any(key in os.environ for key in ("V213_RUNTIME_BINDING_JSON", "V213_MODEL_PROFILE_JSON", "II_LOCAL_LLM_MODEL", "II_LLAMA_BASE_URL"))
    return {**base, "state": "ALREADY_SELECTED" if same else "PROPOSED", "binding_sha256": pick["binding_sha256"],
            "base_url": pick["base_url"], "model": pick["model"], "priority": pick["priority"],
            "differs_from_current_intent": before[0] == "EXPLICIT_STRATA" and not same, "external_intent_present": external}


def _request_root(request: dict[str, Any]) -> str:
    root = request.get("root")
    if not isinstance(root, str) or not 0 < len(root) <= 1024:
        raise CatalogUnavailable("CATALOG_REQUEST_INVALID")
    return root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--op", required=True, choices=("list", "register", "remove", "set-opt-in", "refresh", "select", "suggest"))
    args = parser.parse_args(argv)
    try:
        if sys.version_info < (3, 10):
            raise CatalogUnavailable("CATALOG_PYTHON_PREREQUISITE_UNAVAILABLE")
        shared = _shared()
        request = shared.strict_object(sys.stdin.read(16385), 16384)
        if not isinstance(request, dict):
            raise CatalogUnavailable("CATALOG_REQUEST_INVALID")
        allowed = {"list": set(), "register": {"entry"}, "remove": {"binding_sha256"}, "set-opt-in": {"value"},
                   "refresh": {"root"}, "select": {"root", "binding_sha256"}, "suggest": {"root", "startup"}}[args.op]
        if set(request) - allowed or (args.op in ("register", "remove", "set-opt-in", "select") and not allowed <= set(request)):
            raise CatalogUnavailable("CATALOG_REQUEST_INVALID")
        if args.op == "list":
            result = list_registry()
        elif args.op == "register":
            result = register(request["entry"])
        elif args.op == "remove":
            result = remove(request["binding_sha256"])
        elif args.op == "set-opt-in":
            result = set_opt_in(request["value"])
        elif args.op == "refresh":
            result = refresh(_request_root(request))
        elif args.op == "select":
            result = select(_request_root(request), request["binding_sha256"])
        else:
            startup = request.get("startup", False)
            if type(startup) is not bool:
                raise CatalogUnavailable("CATALOG_REQUEST_INVALID")
            result = suggest(_request_root(request), startup=startup)
        print(json.dumps(result, separators=(",", ":"), ensure_ascii=True))
        return 0
    except Exception as error:
        print(json.dumps({"error": "MODEL_CATALOG_UNAVAILABLE", "reason": _reason(error), "qualification": "UNQUALIFIED"},
                         separators=(",", ":")))
        return 1


if __name__ == "__main__":
    sys.exit(main())
