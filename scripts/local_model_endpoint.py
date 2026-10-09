#!/usr/bin/env python3
"""Finds the local OpenAI-compatible model server and the model to use (operator 2026-09-26: the local model's port
and ID change, for example TabbyAPI :5000 with Qwen3.8-27B-EXL3-5.5bpw-v2 replaced by ninfer :8080 with Qwen3.8-27B;
every local caller must still connect without a manual edit).

Servers, in order: an explicit base (II_LLAMA_BASE_URL or --base), the launcher's saved selection
(<user_config_root>/v213-model-selection.json llama_base_url), the configured base (config/local-runtime-independence-
v1.json primary_reasoner.base_url), the well-known ports (llama.cpp/Strata 8080, Ollama 11434, LM Studio
1234, 5001, 8081), then every other loopback TCP listener. Ports 5000 (IBKR Client Portal) and 8000 (the retired System One decider) are never probed, from ANY source (known, listener, saved, explicit). Each probe
is one read-only GET of /v1/models, then /models, with a short timeout, no proxy and no redirect; only a reply in the
OpenAI list shape counts.

Model, per server: the wanted model (II_LOCAL_LLM_MODEL, --want, else the saved selection, else the configured model)
when served (id or alias, case-insensitive); else a served model of the same family (the id up to its parameter-count
token, e.g. Qwen3.8-27B for Qwen3.8-27B-EXL3-5.5bpw-v2); else the only model the server lists. Several unrelated models
and no family match give no automatic choice. The best match wins across servers (exact, then family, then only);
the earlier server wins a tie. The result names the served id, so callers verify replies against the model that is
actually loaded and label it; nothing is substituted silently.

Explicit Strata intent (F04): before ANY listener scan, catalog request, configured fallback or ranking, the shared request
binding (scripts/v213_model_profile.py resolve_binding: CLI/env/saved intent) is resolved. When present it is the only
authority: exactly the bound root/model/profile, checked with the shared selected-only /health + /v1/models metadata, and
nothing else (no family/only/alias/case-fold/port scan, no generation, no credentials). The caller's want/base are legacy
configured defaults there and cannot select or conflict; --binding-json/--explicit-model/--explicit-base are explicit
arguments whose PRESENCE is preserved (empty or conflicting is refused, never omission). Invalid, torn, conflicting,
unloaded or unknown state is a finite sanitized error with no configured fallback, and --all refuses. Only a genuine
LEGACY_ABSENT keeps the legacy behavior below. The reply is METADATA_ONLY/UNQUALIFIED, never a marker or capacity proof.

CLI: python scripts/local_model_endpoint.py [--want MODEL] [--base URL] [--all] -> one JSON line; exit 0 when found,
3 when not. --all also scans every loopback listener and lists all servers (scripts/select_local_model.ps1 uses it to
let the operator pick one of several models; the pick is saved as the launcher selection, which every caller wants first).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
LOCAL_RUNTIME_CONFIG = ROOT / "config" / "local-runtime-independence-v1.json"
KNOWN_PORTS = (8080, 11434, 1234, 5001, 8081)
NEVER_PROBED = {5000, 8000}  # 5000 IBKR Client Portal (broker, no model catalog), 8000 retired System One decider
MAX_LISTENERS = 48
PROBE_TIMEOUT = 2.0
_SIZE_TOKEN = re.compile(r"^\d+(?:\.\d+)?[BbMm]$")
_LOOPBACK = ("127.0.0.1", "localhost", "::1")
RANK = {"exact": 0, "family": 1, "only": 2}


def model_family(model_id: str) -> str:
    """Qwen3.8-27B-EXL3-5.5bpw-v2 -> qwen3.8-27b; an id without a parameter-count token is its own family."""
    parts = str(model_id or "").strip().split("-")
    for index, token in enumerate(parts):
        if _SIZE_TOKEN.match(token):
            return "-".join(parts[: index + 1]).lower()
    return str(model_id or "").strip().lower()


def loopback_base(url: str) -> str | None:
    """http://127.0.0.1:PORT, http://localhost:PORT or http://[::1]:PORT (optionally ending in /v1) without credentials, query or fragment.
    The result is canonical: localhost becomes 127.0.0.1, the IPv6 host keeps its brackets, an absent port is HTTP's 80 and an explicit
    port 0 is refused (never silently retargeted). This only repairs the output format of the already allowed host: no IPv6 scan or support."""
    try:
        parts = urlsplit(str(url or "").strip())
        port = parts.port
    except ValueError:
        return None
    if parts.scheme != "http" or parts.hostname not in _LOOPBACK or parts.username or parts.password or parts.query or parts.fragment:
        return None
    if parts.path.rstrip("/") not in ("", "/v1") or port in NEVER_PROBED or port == 0:
        return None
    host = "127.0.0.1" if parts.hostname == "localhost" else f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
    return f"http://{host}:{80 if port is None else port}"


def listening_ports() -> list[int]:
    """Loopback-reachable TCP listeners (Windows netstat); an empty list when unavailable."""
    try:
        text = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, timeout=10,
                              errors="replace").stdout
    except (OSError, subprocess.SubprocessError):
        return []
    ports: set[int] = set()
    for line in text.splitlines():
        fields = line.split()
        if len(fields) >= 4 and fields[0].upper() == "TCP" and "LISTEN" in fields[3].upper():
            host, _, port = fields[1].rpartition(":")
            if host in ("127.0.0.1", "0.0.0.0", "[::]", "[::1]") and port.isdigit():
                ports.add(int(port))
    return sorted(port for port in ports if 1024 <= port <= 65535 and port not in NEVER_PROBED)


def _user_config_root() -> Path | None:
    """Legacy-preference view only: the validated alternate folder, or None. Present-but-unusable install state is refused by
    selected_intent BEFORE any preference is read, so here it merely yields no preference."""
    try:
        return _alternate_config_folder()
    except IntentUnavailable:
        return None


def saved_selection() -> dict[str, str]:
    root = _user_config_root()
    try:
        value = json.loads((root / "v213-model-selection.json").read_text(encoding="utf-8-sig")) if root else {}
    except Exception:
        value = {}
    if not isinstance(value, dict):  # selected_intent refuses a present non-object selection first; never a late .get
        value = {}
    return {"model": str(value.get("model") or ""), "base": str(value.get("llama_base_url") or "")}


def configured_reasoner(path: Path = LOCAL_RUNTIME_CONFIG) -> dict[str, str]:
    try:
        reasoner = json.loads(path.read_text(encoding="utf-8"))["primary_reasoner"]
        return {"model": str(reasoner.get("model") or ""), "base": str(reasoner.get("base_url") or "")}
    except Exception:
        return {"model": "", "base": ""}


def read_catalog(base: str) -> list[dict[str, Any]] | None:
    """Model rows ({"id", "aliases"}) from GET /v1/models or /models; None when the server gives no list."""
    opener = build_opener(ProxyHandler({}))
    for suffix in ("/v1/models", "/models"):
        try:
            request = Request(base + suffix, headers={"Accept": "application/json", "Cache-Control": "no-cache"})
            with opener.open(request, timeout=PROBE_TIMEOUT) as response:  # noqa: S310 - loopback only
                if response.geturl().rstrip("/") != (base + suffix).rstrip("/"):
                    continue  # a redirect is not a model catalog
                payload = json.loads(response.read(2_000_000).decode("utf-8"))
        except Exception:
            continue
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            continue
        models = []
        for row in rows[:256]:
            ident = row if isinstance(row, str) else (row.get("id") if isinstance(row, dict) else None)
            if isinstance(ident, str) and ident.strip():
                aliases = row.get("aliases") if isinstance(row, dict) and isinstance(row.get("aliases"), list) else []
                models.append({"id": ident.strip(), "aliases": [str(alias) for alias in aliases if isinstance(alias, str)]})
        if models:
            return models
    return None


def choose_model(catalog: list[dict[str, Any]], wanted: Iterable[str]) -> tuple[str, str] | None:
    """(served id, exact|family|only) for one server's catalog."""
    wanted = [str(model).strip() for model in wanted if str(model or "").strip()]
    for model in wanted:
        for row in catalog:
            if model.lower() in [row["id"].lower(), *(alias.lower() for alias in row["aliases"])]:
                return row["id"], "exact"
    for model in wanted:
        family = model_family(model)
        matches = [row["id"] for row in catalog if model_family(row["id"]) == family]
        if len(matches) == 1:
            return matches[0], "family"
    if len(catalog) == 1:
        return catalog[0]["id"], "only"
    return None


def candidate_bases(explicit: str = "") -> list[str]:
    """The addresses probed first; other loopback listeners follow only when none of these serves the wanted model."""
    saved, configured = saved_selection(), configured_reasoner()
    ordered = [explicit, os.getenv("II_LLAMA_BASE_URL", ""), saved["base"], configured["base"],
               *(f"http://127.0.0.1:{port}" for port in KNOWN_PORTS)]
    bases: list[str] = []
    for value in ordered:
        base = loopback_base(value)
        if base and base not in bases:
            bases.append(base)
    return bases


class IntentUnavailable(ValueError):
    """Finite sanitized reason code only; never a raw payload, header, path or credential."""


_REASON = re.compile(r"[A-Z][A-Z0-9_]{0,63}")
EXPLICIT_KEYS = frozenset({"binding_json", "base_url", "model", "profile_json"})


def _reason(error: BaseException) -> str:
    """Only a finite code raised by the shared helpers is echoed; operational exception text (OS, HTTP, decoding) never is."""
    text = str(error)
    if isinstance(error, ValueError) and not isinstance(error, UnicodeError) and _REASON.fullmatch(text):
        return text
    return "BINDING_OPERATION_UNAVAILABLE"


def _shared() -> Any:
    try:
        import v213_model_profile as shared  # the ONE binding/profile schema, hash and transport
    except Exception:
        raise IntentUnavailable("BINDING_HELPER_UNAVAILABLE") from None
    return shared


_REPARSE_POINT = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT (reported by the attribute query; os.lstat alone sees only name-surrogate kinds)
_OFFLINE = 0x1000  # FILE_ATTRIBUTE_OFFLINE
_RECALL_ON_OPEN = 0x40000  # FILE_ATTRIBUTE_RECALL_ON_OPEN
_RECALL_ON_DATA_ACCESS = 0x400000  # FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
_REFUSED_ATTRIBUTES = _REPARSE_POINT | _OFFLINE | _RECALL_ON_OPEN | _RECALL_ON_DATA_ACCESS  # exactly these flags, no wider claim
_PATH_CEILING_UTF16 = 240  # conservative Windows path ceiling in UTF-16 code units
_SELECTION_FILE = "v213-model-selection.json"
_DIRECTORY_ATTRIBUTE = 0x10  # FILE_ATTRIBUTE_DIRECTORY
_INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF  # GetFileAttributesW failure value (a DWORD -1)
_MISSING_WIN32_ERRORS = (2, 3)  # ERROR_FILE_NOT_FOUND, ERROR_PATH_NOT_FOUND: the ONLY errors that mean genuinely missing
_DIRECT_LOCAL_VOLUME = re.compile(r"\\Device\\HarddiskVolume[0-9]{1,6}")
_RESERVED_NAME = re.compile(r"(?:CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|(?:COM|LPT)[0-9\u00b9\u00b2\u00b3])(?:\..*)?", re.IGNORECASE)


def _is_link_or_reparse(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & _REPARSE_POINT)


def _file_attributes(path: str) -> int | None:
    """None when the entry is genuinely MISSING; else its attribute flags WITHOUT following a final link. On Windows this is Win32
    GetFileAttributesW through the standard-library ctypes (explicit argument and result types): it reports the attributes of a
    final symbolic link, junction or other reparse point itself rather than its target; callers refuse exactly the flags in
    _REFUSED_ATTRIBUTES (reparse point, offline, recall-on-open, recall-on-data-access) and claim nothing wider about placeholders
    or remote backing; intermediate components are resolved by the system, which is why callers walk every ancestor
    separately. INVALID_FILE_ATTRIBUTES is missing ONLY for Win32 error 2 or 3; every other failure (access, not ready, bad path,
    unavailable API) is IntentUnavailable, never absence. A non-Windows host has no reparse attributes: it uses lstat (symlink and
    directory only; the alternate-drive proof refuses such hosts anyway). Native behavior is NOT_RUN and not race-free."""
    if os.name != "nt":
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            return None
        except OSError:
            raise IntentUnavailable("BINDING_STATE_UNAVAILABLE") from None
        return (_REPARSE_POINT if stat.S_ISLNK(info.st_mode) else 0) | (_DIRECTORY_ATTRIBUTE if stat.S_ISDIR(info.st_mode) else 0)
    try:
        import ctypes
        query = ctypes.WinDLL("kernel32", use_last_error=True).GetFileAttributesW
        query.argtypes = [ctypes.c_wchar_p]
        query.restype = ctypes.c_uint32
        ctypes.set_last_error(0)
        value = query(path)
        error = ctypes.get_last_error()
    except Exception:
        raise IntentUnavailable("BINDING_STATE_UNAVAILABLE") from None
    if value != _INVALID_FILE_ATTRIBUTES:
        return int(value)
    if error in _MISSING_WIN32_ERRORS:
        return None
    raise IntentUnavailable("BINDING_STATE_UNAVAILABLE")


def _checked_utf16_length(text: str) -> None:
    """The FULL resulting path (suffix and non-BMP characters included) against a conservative ceiling in UTF-16 code units, BEFORE any
    native metadata or authority call. A lone surrogate or any unencodable text is refused; no filesystem-resolving normalization."""
    try:
        units = len(text.encode("utf-16-le", "strict")) // 2
    except UnicodeError:
        raise IntentUnavailable("BINDING_INSTALL_STATE_INVALID") from None
    if units > _PATH_CEILING_UTF16:
        raise IntentUnavailable("BINDING_INSTALL_STATE_INVALID")


def _read_state_bytes(path: Path, limit: int) -> bytes | None:
    """The ORIGINAL bytes of a bounded regular terminal file, or None when it is genuinely MISSING (Win32 error 2/3). This is NOT a JSON
    reader: it decodes and validates nothing (no top-level-object or duplicate-key check; decoding, plain or strict, belongs to the
    caller), and it is NOT an ancestor or local-volume proof (the caller must already have proven the folder chain, for example with
    _require_local_chain). TERMINAL checks only: the full path length against the UTF-16 ceiling first; then the terminal entry is
    inspected WITHOUT following it before it is opened: the no-final-link attribute query (the _REFUSED_ATTRIBUTES flags or a
    directory are refused), then lstat, and the opened handle must be the same regular file; an unreadable or over-limit file is
    IntentUnavailable. A swap between the checks and the open is a narrowed, not eliminated, race (native handle-level proof is NOT_RUN)."""
    try:
        _checked_utf16_length(str(path))
        attributes = _file_attributes(str(path))
        if attributes is None:
            return None
        if attributes & (_REFUSED_ATTRIBUTES | _DIRECTORY_ATTRIBUTE):
            raise IntentUnavailable("BINDING_STATE_INVALID")
        before = os.lstat(path)  # an OSError here (including a swap to missing) is the fixed unavailable code below
        if _is_link_or_reparse(before) or not stat.S_ISREG(before.st_mode):
            raise IntentUnavailable("BINDING_STATE_INVALID")
        with path.open("rb") as handle:
            after = os.fstat(handle.fileno())
            if not stat.S_ISREG(after.st_mode) or (before.st_ino and (before.st_ino, before.st_dev) != (after.st_ino, after.st_dev)):
                raise IntentUnavailable("BINDING_STATE_INVALID")
            raw = handle.read(limit + 1)
    except IntentUnavailable:
        raise
    except OSError:
        raise IntentUnavailable("BINDING_STATE_UNAVAILABLE") from None
    if len(raw) > limit:
        raise IntentUnavailable("BINDING_STATE_INVALID")
    return raw  # the ORIGINAL bytes: strict callers (the model registry) decode them with the shared duplicate-key-safe parser


def _read_state_object(path: Path, limit: int) -> dict[str, Any] | None:
    """The legacy decoded view of _read_state_bytes (all its path, attribute, handle and size guards apply): a top-level JSON object,
    or None when the optional file is genuinely MISSING. Behavior for existing callers is unchanged."""
    raw = _read_state_bytes(path, limit)
    if raw is None:
        return None
    try:
        value = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeError, RecursionError):
        raise IntentUnavailable("BINDING_STATE_INVALID") from None
    if not isinstance(value, dict):
        raise IntentUnavailable("BINDING_STATE_INVALID")
    return value


def _folder_parts(value: str) -> list[str]:
    """Components of an already drive-letter-validated folder spelling. Doubled separators (empty components), names ending in a dot
    or space (Windows strips them; this also covers dot and dot-dot), reserved device names and over-long paths are ambiguous
    spellings and are refused. A stream suffix or device prefix cannot pass the character class of the caller."""
    if len(value) > 240:
        raise IntentUnavailable("BINDING_INSTALL_STATE_INVALID")
    parts = re.split(r"[\\/]", value[3:]) if value[3:] else []
    if parts and parts[-1] == "":
        parts.pop()  # a single trailing separator names the same folder
    for part in parts:
        if not part or len(part) > 255 or part.endswith((".", " ")) or _RESERVED_NAME.fullmatch(part):
            raise IntentUnavailable("BINDING_INSTALL_STATE_INVALID")
    return parts


def _local_absolute_folder(value: Any) -> Path:
    """Only an unambiguous drive-letter absolute spelling: never UNC/device/relative/parent-segment/stream paths, so no remote probe.
    Spelling alone never proves the folder is local; _require_local_chain does that BEFORE any state inside it is touched."""
    if (not isinstance(value, str) or not 3 <= len(value) <= 512
            or re.fullmatch(r'[A-Za-z]:[\\/][^<>:"|?*\x00-\x1f]*', value) is None):
        raise IntentUnavailable("BINDING_INSTALL_STATE_INVALID")
    _folder_parts(value)
    return Path(value)


def _direct_local_volume(drive: str) -> bool:
    """True only when QueryDosDeviceW maps the drive letter (for example C:) to exactly ONE direct local-volume device target
    (the pattern is the HarddiskVolumeN device). A mapped network drive, a subst alias (a path or a UNC target), a drive missing
    in this session, an overlay with several targets and any non-Windows or API failure are all unproven. Isolated source text:
    the native call is NOT_RUN here and is never exercised by this module's callers except through a configured alternate folder."""
    try:
        import ctypes
        query = ctypes.WinDLL("kernel32", use_last_error=True).QueryDosDeviceW
        query.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_uint32]
        query.restype = ctypes.c_uint32
        buffer = ctypes.create_unicode_buffer(1024)
        length = query(drive, ctypes.cast(buffer, ctypes.c_void_p), 1024)
        if not 0 < length < 1024:
            return False
        targets = ctypes.wstring_at(buffer, length).rstrip("\x00").split("\x00")
        return len(targets) == 1 and _DIRECT_LOCAL_VOLUME.fullmatch(targets[0]) is not None
    except Exception:
        return False


def _same_folder(left: Path, right: Path) -> bool:
    return os.path.normcase(os.path.normpath(str(left))) == os.path.normcase(os.path.normpath(str(right)))


def _require_local_chain(folder: Path, leaf_names: tuple[str, ...] = (_SELECTION_FILE,)) -> None:
    """Local-volume authority and a no-follow ancestor walk BEFORE any state below an alternate folder is read. The drive must be a
    proven direct local volume; then every existing component from the root down is inspected without following it (the
    no-final-link attribute query first, refusing the _REFUSED_ATTRIBUTES flags only (reparse point, offline, recall), then lstat; no resolver, no realpath, no existence call that
    follows links, no recursive inventory) and must be a plain directory. The first genuinely missing component (Win32 error 2/3
    only) ends the walk: nothing below it exists, which is legitimate absence in a proven chain. Any other error, a
    non-directory or a reparse point is IntentUnavailable, never absence."""
    text = str(folder)
    parts = _folder_parts(text)
    for leaf in leaf_names:
        _checked_utf16_length(str(folder / leaf))  # every derived full path (selection, or registry/lock/temp), BEFORE any native authority call
    drive = text[:2].upper()
    if not _direct_local_volume(drive):
        raise IntentUnavailable("BINDING_LOCAL_VOLUME_UNPROVEN")
    current = drive
    for part in parts:
        current = current + "\\" + part
        attributes = _file_attributes(current)
        if attributes is None:
            return
        if attributes & _REFUSED_ATTRIBUTES or not attributes & _DIRECTORY_ATTRIBUTE:
            raise IntentUnavailable("BINDING_STATE_INVALID")
        try:
            info = os.lstat(current)
        except OSError:
            raise IntentUnavailable("BINDING_STATE_UNAVAILABLE") from None
        if _is_link_or_reparse(info) or not stat.S_ISDIR(info.st_mode):
            raise IntentUnavailable("BINDING_STATE_INVALID")


def _canonical_config_folder() -> Path | None:
    local = os.environ.get("LOCALAPPDATA")
    return Path(local, "InvestorIntelligence", "UserData", "config") if local else None


def _alternate_config_folder() -> Path | None:
    """The install-state user_config_root when install state is present with that field; None when install state or the field is
    missing (optional legacy state). Present-but-unusable state or an unsafe path is IntentUnavailable. Metadata reads only."""
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return None
    state = _read_state_object(Path(local, "InvestorIntelligence", "install-state.json"), 65536)
    if state is None or "user_config_root" not in state:
        return None
    folder = _local_absolute_folder(state["user_config_root"])
    canonical = _canonical_config_folder()
    if canonical is None or not _same_folder(folder, canonical):
        _require_local_chain(folder)  # the canonical folder is validated by the shared resolve_binding; any other one is proven here
    return folder


def _check_alternate_state() -> None:
    """Runs for EVERY mode, also when a canonical binding exists. The canonical folder is validated by the shared
    resolve_binding (a valid canonical selection with engine/digest is fine). A different alternate folder must be missing or hold
    a readable object selection WITHOUT explicit markers; an explicit-looking alternate layout is unsupported and refused (never
    stripped, relocated or silently ignored)."""
    root = _alternate_config_folder()
    canonical = _canonical_config_folder()
    if root is None or canonical is None:
        return
    if _same_folder(root, canonical):
        return
    selection = _read_state_object(root / "v213-model-selection.json", 16384)
    if selection is not None and ("engine" in selection or "runtime_binding_sha256" in selection):
        raise IntentUnavailable("BINDING_ALTERNATE_SELECTION_UNSUPPORTED")


def selected_intent(explicit: dict[str, Any] | None = None) -> dict[str, Any]:
    """Shared resolution BEFORE any probe: {'mode': 'LEGACY_ABSENT'} or the validated EXPLICIT_STRATA binding. Presence of
    CLI/env/saved intent is preserved; invalid/torn/conflicting state raises IntentUnavailable, never becomes legacy.

    This is the ONE complete public boundary: argument construction/type validation, the shared import and resolution, the
    mode checks and the alternate-install selection inspection all run inside _selected_intent. Known IntentUnavailable codes
    stay finite; any other operational Exception (RecursionError, decoding, HTTP, malformed shape, a code surprise) becomes a
    fixed code with chaining suppressed and no text, never legacy. KeyboardInterrupt/SystemExit/BaseException propagate."""
    try:
        return _selected_intent(explicit)
    except IntentUnavailable:
        raise
    except Exception:
        raise IntentUnavailable("BINDING_OPERATION_UNAVAILABLE") from None


def _selected_intent(explicit: dict[str, Any] | None) -> dict[str, Any]:
    request = dict(explicit or {})
    if set(request) - EXPLICIT_KEYS:
        raise IntentUnavailable("BINDING_REQUEST_INVALID")
    shared = _shared()
    try:
        resolved = shared.resolve_binding(str(ROOT), **request)
    except (ValueError, OSError, KeyError, TypeError, UnicodeError) as error:
        raise IntentUnavailable(_reason(error)) from None
    except Exception:  # untrusted state/IO surprise: fixed code, no text, chaining suppressed, never legacy (not BaseException)
        raise IntentUnavailable("BINDING_OPERATION_UNAVAILABLE") from None
    mode = resolved.get("mode") if isinstance(resolved, dict) else None
    if mode == "LEGACY_ABSENT":
        if request:  # an explicit argument without any binding is never silently dropped
            raise IntentUnavailable("BINDING_REQUIRED_FOR_EXPLICIT_ARGUMENT")
    elif mode != "EXPLICIT_STRATA":
        raise IntentUnavailable("BINDING_MODE_UNKNOWN")
    _check_alternate_state()
    return resolved


def _unavailable(reason: str) -> dict[str, Any]:
    return {"error": "LOCAL_MODEL_BINDING_UNAVAILABLE", "reason": reason, "mode": "SELECTED_INTENT_UNAVAILABLE",
            "wanted": [], "servers": [], "probed": 0, "qualification": "UNQUALIFIED"}


def _resolve_selected(intent: dict[str, Any], explicit: dict[str, Any] | None, metadata_reader: Callable[..., Any] | None,
                      scan_all: bool, hinted: bool) -> dict[str, Any]:
    if scan_all:
        raise IntentUnavailable("BINDING_SCAN_ALL_REFUSED")  # never enumerate unrelated servers
    shared = _shared()
    binding, profile, digest = intent["binding"], intent["profile"], intent["binding_sha256"]
    try:
        metadata = (metadata_reader or shared.selected_metadata)(binding, profile, shared.context_minimum(str(ROOT)))
        again = selected_intent(explicit)  # identity is checked again AFTER the metadata round trip
    except IntentUnavailable:
        raise
    except (ValueError, OSError, KeyError, TypeError, UnicodeError) as error:
        raise IntentUnavailable(_reason(error)) from None
    except Exception:  # e.g. http.client.HTTPException from the untrusted metadata transport: no status line/body/text
        raise IntentUnavailable("BINDING_METADATA_OPERATION_FAILED") from None
    if (again.get("mode") != "EXPLICIT_STRATA" or again.get("binding_sha256") != digest
            or again.get("profile_sha256") != intent["profile_sha256"] or not isinstance(metadata, dict)
            or metadata.get("binding_sha256") != digest or metadata.get("model") != binding["model"]):
        raise IntentUnavailable("BINDING_CHANGED_DURING_METADATA")
    return {"base_url": binding["base_url"], "model": binding["model"], "match": "exact", "wanted": [binding["model"]],
            "servers": [{"base_url": binding["base_url"], "models": [binding["model"]]}], "probed": 1, "changed": False,
            "mode": "EXPLICIT_STRATA", "binding_sha256": digest, "model_profile_sha256": intent["profile_sha256"],
            "declared_context": metadata.get("declared_context"), "legacy_hints_ignored": hinted,
            "scope": "METADATA_ONLY", "qualification": "UNQUALIFIED", "release_qualified": False}


def resolve(want: str = "", base: str = "", *, catalog_reader: Callable[[str], list[dict[str, Any]] | None] = read_catalog,
            listeners: Callable[[], list[int]] = listening_ports, scan_all: bool = False,
            explicit: dict[str, Any] | None = None, metadata_reader: Callable[..., Any] | None = None) -> dict[str, Any]:
    try:
        intent = selected_intent(explicit)
        if intent["mode"] == "EXPLICIT_STRATA":
            return _resolve_selected(intent, explicit, metadata_reader, scan_all, bool(want or base))
    except IntentUnavailable as error:
        return _unavailable(str(error))
    except Exception:  # selected-resolution shape surprise only; the legacy scanner below is never wrapped
        return _unavailable("BINDING_OPERATION_UNAVAILABLE")
    wanted = [want, os.getenv("II_LOCAL_LLM_MODEL", ""), saved_selection()["model"], configured_reasoner()["model"]]
    wanted = [model for index, model in enumerate(wanted) if model and model not in wanted[:index]]
    bases = candidate_bases(base)
    best: dict[str, Any] | None = None
    seen: list[dict[str, Any]] = []

    def scan(batch: list[str]) -> None:
        nonlocal best
        with ThreadPoolExecutor(max_workers=8) as pool:
            catalogs = list(pool.map(catalog_reader, batch))
        for server, catalog in zip(batch, catalogs):
            if not catalog:
                continue
            seen.append({"base_url": server, "models": [row["id"] for row in catalog][:16]})
            choice = choose_model(catalog, wanted)
            if choice and (best is None or RANK[choice[1]] < RANK[best["match"]]):
                best = {"base_url": server, "model": choice[0], "match": choice[1]}

    scan(bases)
    if scan_all or best is None or best["match"] != "exact":
        extra = [f"http://127.0.0.1:{port}" for port in listeners() if port not in NEVER_PROBED]
        extra = [server for server in extra if server not in bases][:MAX_LISTENERS]
        scan(extra)
        bases += extra
    if best is None:
        return {"error": "LOCAL_MODEL_NOT_FOUND" if not seen else "LOCAL_MODEL_AMBIGUOUS", "wanted": wanted,
                "servers": seen, "probed": len(bases)}
    best.update({"wanted": wanted, "servers": seen, "probed": len(bases),
                 "changed": bool(wanted) and best["model"].lower() != wanted[0].lower()})
    return best


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--want", default="")
    parser.add_argument("--base", default="")
    parser.add_argument("--all", action="store_true")
    # Explicit-argument PRESENCE matters: None is absent, an empty string is present-invalid.
    parser.add_argument("--binding-json", default=None)
    parser.add_argument("--explicit-model", default=None)
    parser.add_argument("--explicit-base", default=None)
    args = parser.parse_args(list(argv) if argv is not None else None)
    explicit = {key: value for key, value in (("binding_json", args.binding_json), ("model", args.explicit_model),
                                              ("base_url", args.explicit_base)) if value is not None}
    result = resolve(args.want, args.base, scan_all=args.all, explicit=explicit or None)
    print(json.dumps(result, ensure_ascii=True, separators=(",", ":")))
    return 0 if "error" not in result else 3


if __name__ == "__main__":
    sys.exit(main())
