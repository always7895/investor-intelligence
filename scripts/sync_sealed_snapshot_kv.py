"""Locked-CLI sealed sync and read-only freshness observations.

Objects -> all-object readback -> pointer LAST -> pointer readback. Failures
never manufacture success; a failed pointer call/readback leaves its state
unconfirmed, not "untouched". CLI streams stay in memory and only fixed safe
categories/counters are emitted. No login, credential inspection or install.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLOUD_DIR = ROOT / "cloud"
NS = "96142af40b5d4213862d5483fe3a66da"
REMOTE = "--remote"
ATTEMPTS = 3
RETRY_SECONDS = 5.0
LAST_ERROR: list[str] = []
LAST_CALL: dict = {"attempts": 0, "exit_code": None, "error_category": "NONE"}
TOTAL_ATTEMPTS = 0
BLOB_PREFIX = "blob:v1:"
RUN_KEY_TTL_SECONDS = 14 * 86400
BLOB_TTL_SECONDS = 30 * 86400
BLOB_REUSE_SECONDS = 20 * 86400
LEDGER = ROOT / "data" / "cache" / "kv-blob-ledger.json"
RUN_ID = re.compile(r"\d{8}T\d{6}Z-[0-9a-f]{12}")
KV_DAILY_LIMIT = "DAILY_KV_LIMIT"
TRANSIENT_CATEGORIES = {"NETWORK_FAILURE", "TRANSIENT_HTTP", "TIMEOUT"}


class CliUnavailable(RuntimeError):
    """A local locked CLI could not be selected; no CLI launch occurred."""


def _cli_command() -> list[str]:
    """Use the already-installed Wrangler matching BOTH manifest and lock.

    Reuse managed Node selection; never use npx --yes or install a dependency.
    Missing or mismatched components are an explicit unavailable outcome.
    """
    try:
        declared = json.loads((CLOUD_DIR / "package.json").read_text(encoding="utf-8"))["devDependencies"]["wrangler"]
        locked = json.loads((CLOUD_DIR / "package-lock.json").read_text(encoding="utf-8"))["packages"]["node_modules/wrangler"]["version"]
        package = CLOUD_DIR / "node_modules" / "wrangler"
        installed = json.loads((package / "package.json").read_text(encoding="utf-8"))["version"]
        cli = package / "bin" / "wrangler.js"
        node = os.getenv("PROJECT_NODE") or os.getenv("NODE_FOR_RUNNER") or shutil.which("node")
        if not node or not Path(node).is_file() or not cli.is_file() or declared != locked or installed != locked:
            raise CliUnavailable()
        return [str(Path(node).resolve()), str(cli)]
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise CliUnavailable() from error


def _run_cli(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [*_cli_command(), *args], cwd=str(CLOUD_DIR), capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=300,
    )


def _known_error_markers(stdout: str, stderr: str) -> tuple[set[int], bool]:
    """Cloudflare failure envelopes / Wrangler markers, NOT bare numbers.

    Full JSON or a JSON log line must be a success:false/errors envelope to
    contribute numeric codes. A named exception envelope/class marker is also
    recognized. Bare counters and unstructured numeric fragments prove nothing.
    """
    codes: set[int] = set()
    auth_class = False
    for stream in (stdout or "", stderr or ""):
        text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", stream)
        codes.update(int(code) for code in re.findall(r"\[\s*code\s*:\s*(10000|10048)\s*\]", text, re.IGNORECASE))
        if re.search(r"(?m)^\s*AuthenticationError(?:\s*:|\s*$)|\[ERROR\][^\r\n]*\bAuthenticationError\b", text, re.IGNORECASE):
            auth_class = True
        for candidate in [text, *text.splitlines()]:
            try:
                envelope = json.loads(candidate)
            except (ValueError, TypeError):
                continue
            if not isinstance(envelope, dict):
                continue
            if envelope.get("success") is False and isinstance(envelope.get("errors"), list):
                for error in envelope["errors"]:
                    if isinstance(error, dict) and type(error.get("code")) is int:
                        codes.add(error["code"])
            if envelope.get("name") == "AuthenticationError" and (
                    isinstance(envelope.get("message"), str) or isinstance(envelope.get("stack"), str)):
                auth_class = True
    return codes, auth_class


def classify_cli_error(stdout: str, stderr: str) -> str:
    """Classification only: never return any fragment of either CLI stream."""
    text = f"{stdout or ''}\n{stderr or ''}"
    codes, auth_class = _known_error_markers(stdout, stderr)
    if 10000 in codes or auth_class:
        return "AUTHENTICATION_ERROR"
    if 10048 in codes or re.search(r"\[ERROR\][^\r\n]*\bfree usage limit\b", text, re.IGNORECASE):
        return KV_DAILY_LIMIT
    if re.search(r"\b(?:ETIMEDOUT|ECONNRESET|ECONNREFUSED|EAI_AGAIN|ENETUNREACH|FetchError)\b|fetch failed|network error", text, re.IGNORECASE):
        return "NETWORK_FAILURE"
    if re.search(r"(?:HTTP(?:\s+status)?|status(?:\s+code)?)[\s:=]+(?:429|5\d\d)\b", text, re.IGNORECASE):
        return "TRANSIENT_HTTP"
    return "UNKNOWN"


def _daily_limit(p: subprocess.CompletedProcess) -> bool:
    return classify_cli_error(p.stdout, p.stderr) == KV_DAILY_LIMIT


def _error_summary(p: subprocess.CompletedProcess) -> str:
    return classify_cli_error(p.stdout, p.stderr)


def _run_with_retry(args: list[str]) -> subprocess.CompletedProcess:
    global TOTAL_ATTEMPTS
    launched = 0
    LAST_ERROR.clear()
    for attempt in range(1, ATTEMPTS + 1):
        try:
            p = _run_cli(args)
            launched += 1
            category = "NONE" if p.returncode == 0 else _error_summary(p)
        except CliUnavailable:
            p = subprocess.CompletedProcess(args, None, "", "")
            category = "CLI_UNAVAILABLE"
        except subprocess.TimeoutExpired as error:
            launched += 1
            out = error.stdout.decode("utf-8", "replace") if isinstance(error.stdout, bytes) else (error.stdout or "")
            err = error.stderr.decode("utf-8", "replace") if isinstance(error.stderr, bytes) else (error.stderr or "")
            p = subprocess.CompletedProcess(args, None, out, err)
            category = classify_cli_error(out, err)
            if category == "UNKNOWN":
                category = "TIMEOUT"
        except OSError:
            launched += 1  # an attempted launch, not a fabricated native exit
            p = subprocess.CompletedProcess(args, None, "", "")
            category = "CLI_LAUNCH_FAILED"
        LAST_CALL.update(attempts=launched, exit_code=p.returncode, error_category=category)
        if p.returncode == 0:
            break
        LAST_ERROR[:] = [category]
        # Auth/quota/UNKNOWN/local launch failures are terminal. Only a named
        # transient gets bounded retries; there is no credential/account fallback.
        if category not in TRANSIENT_CATEGORIES or attempt == ATTEMPTS:
            break
        time.sleep(RETRY_SECONDS * attempt)
    TOTAL_ATTEMPTS += launched
    return p


def client_put(key: str, local_path: Path, ttl: int | None = None) -> bool:
    # Absolute staged paths also work for an explicit SnapshotRoot outside ROOT.
    extra = ["--ttl", str(ttl)] if ttl else []
    p = _run_with_retry(["kv", "key", "put", key, "--path", str(local_path), "--namespace-id", NS, REMOTE, *extra])
    return p.returncode == 0


def client_get(key: str) -> str | None:
    p = _run_with_retry(["kv", "key", "get", key, "--namespace-id", NS, REMOTE])
    return p.stdout.rstrip("\r\n") if p.returncode == 0 else None


def load_ledger(path: Path | None = None) -> dict[str, float]:
    try:
        value = json.loads((path or LEDGER).read_text(encoding="utf-8"))
        return {str(k): float(v) for k, v in value.items()} if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def save_ledger(ledger: dict[str, float], path: Path | None = None) -> None:
    path = path or LEDGER
    horizon = time.time() - BLOB_TTL_SECONDS
    kept = {k: v for k, v in ledger.items() if v >= horizon}
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(kept), encoding="utf-8")
    temp.replace(path)


def sha(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _outcome(operation: str) -> dict:
    return {"schema_version": 1, "operation": operation, "status": "FAILED",
            "phase": "INPUT", "error_category": "UNKNOWN", "pointer_state": "NOT_ATTEMPTED",
            "run_id": "", "cli_attempts_total": 0, "last_cli_attempts": 0,
            "last_cli_exit_code": None, "objects_uploaded": 0, "objects_reused": 0,
            "objects_verified": 0}


def _finish_call(record: dict, category: str | None = None) -> None:
    record.update(cli_attempts_total=TOTAL_ATTEMPTS, last_cli_attempts=LAST_CALL["attempts"],
                  last_cli_exit_code=LAST_CALL["exit_code"],
                  error_category=category or LAST_CALL["error_category"])


def sync_run(run_dir: Path, record: dict) -> int:
    objects = json.loads((run_dir / "objects.json").read_text(encoding="utf-8"))
    ptr_raw = (run_dir / "pointer.raw.json").read_text(encoding="utf-8").strip()
    pointer = json.loads(ptr_raw)
    if not isinstance(objects, dict) or not objects or not all(isinstance(k, str) and isinstance(v, str) for k, v in objects.items()):
        raise ValueError()
    if not isinstance(pointer, dict) or not RUN_ID.fullmatch(str(pointer.get("run_id", ""))):
        raise ValueError()
    record["run_id"] = pointer["run_id"]
    prefix = f"snapshot:{record['run_id']}:"
    # Even malformed input must never smuggle the serving pointer into the
    # object-upload phase or cross a run boundary. Lazy blob bytes bind to key.
    for key, body in objects.items():
        if body.endswith(("\r", "\n")):
            raise ValueError()  # client_get strips trailing CR/LF from every readback: such a body could never verify
        if key.startswith(BLOB_PREFIX):
            digest = key[len(BLOB_PREFIX):]
            if not re.fullmatch(r"[0-9a-f]{64}", digest) or sha(body) != digest:
                raise ValueError()
        elif not key.startswith(prefix) or key == prefix:
            raise ValueError()
    entries = sorted(objects.items())
    staged = run_dir / ".kv-stage"
    staged.mkdir(exist_ok=True)
    staged_files = {}
    for index, (key, body) in enumerate(entries):
        fp = staged / f"object-{index}.bin"
        fp.write_bytes(body.encode("utf-8"))
        staged_files[key] = fp
    ptr_fp = staged / "__pointer.bin"
    ptr_fp.write_bytes(ptr_raw.encode("utf-8"))
    ledger = load_ledger()
    now = time.time()
    reused = set()
    record["phase"] = "OBJECT_PUT"
    for key, fp in staged_files.items():
        blob = key.startswith(BLOB_PREFIX)
        if blob and 0 <= now - ledger.get(key[len(BLOB_PREFIX):], 0.0) < BLOB_REUSE_SECONDS:
            reused.add(key)
            record["objects_reused"] += 1
            continue
        if not client_put(key, fp, BLOB_TTL_SECONDS if blob else RUN_KEY_TTL_SECONDS):
            _finish_call(record)
            return 1
        record["objects_uploaded"] += 1
    print(f"OBJECTS_UPLOADED {record['objects_uploaded']} BLOBS_REUSED {len(reused)}")
    record["phase"] = "OBJECT_READBACK"
    # A ledger is not live custody proof. Reused blobs MUST also pass readback.
    for key, body in entries:
        live = client_get(key)
        if live is None or sha(live) != sha(body):
            _finish_call(record, "READBACK_MISMATCH" if live is not None else None)
            return 1
        record["objects_verified"] += 1
    print(f"READBACK_VERIFIED {record['objects_verified']}")
    record["phase"] = "POINTER_PUT"
    record["pointer_state"] = "ATTEMPTED_UNCONFIRMED"
    if not client_put("snapshot:current", ptr_fp):
        _finish_call(record)
        return 1
    record["phase"] = "POINTER_READBACK"
    live_ptr = client_get("snapshot:current")
    if live_ptr is None or sha(live_ptr) != sha(ptr_raw):
        _finish_call(record, "READBACK_MISMATCH" if live_ptr is not None else None)
        return 1
    record["pointer_state"] = "READBACK_CONFIRMED"
    print(f"POINTER_LAST {record['run_id']}")
    record["phase"] = "LOCAL_LEDGER"
    for key in staged_files:
        if key.startswith(BLOB_PREFIX) and key not in reused:
            ledger[key[len(BLOB_PREFIX):]] = now
    save_ledger(ledger)
    shutil.rmtree(staged, ignore_errors=True)
    _finish_call(record, "NONE")
    record.update(status="SUCCEEDED", phase="COMPLETE")
    return 0


def _safe_instant(value) -> str | None:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)", value):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    except ValueError:
        return None


def read_freshness(record: dict) -> int:
    """Read-only shared CLI adapter; export safe metadata, never raw KV bodies."""
    record["phase"] = "POINTER_READ"
    raw = client_get("snapshot:current")
    if raw is None:
        _finish_call(record)
        return 1
    record["phase"] = "POINTER_PARSE"
    pointer = json.loads(raw)
    if not isinstance(pointer, dict) or not RUN_ID.fullmatch(str(pointer.get("run_id", ""))):
        raise ValueError()
    anchor = _safe_instant(pointer.get("public_data_as_of")) or _safe_instant(pointer.get("promoted_at"))
    if anchor is None:
        raise ValueError()
    record.update(run_id=pointer["run_id"], anchor=anchor, top20_state="UNKNOWN", report_generated_at=None)
    record["phase"] = "REPORT_READ"
    raw = client_get(f"snapshot:{record['run_id']}:v213:top20-report:latest")
    if raw is None:
        _finish_call(record)
        record["top20_state"] = "REPORT_READ_FAILED"
        return 1
    record["phase"] = "REPORT_PARSE"
    report = json.loads(raw)
    if not isinstance(report, dict):
        raise ValueError()
    if report.get("status") == "INSUFFICIENT_EVIDENCE":
        record["top20_state"] = "INSUFFICIENT"
    else:
        rows = report.get("records")
        generated = _safe_instant(report.get("generated_at"))
        if not isinstance(rows, list) or generated is None:
            raise ValueError()
        record.update(top20_state=f"RECORDS_{len(rows)}", report_generated_at=generated)
    _finish_call(record, "NONE")
    record.update(status="SUCCEEDED", phase="COMPLETE")
    return 0


def main() -> int:
    global TOTAL_ATTEMPTS
    TOTAL_ATTEMPTS = 0
    LAST_CALL.update(attempts=0, exit_code=None, error_category="NONE")
    ap = argparse.ArgumentParser()
    modes = ap.add_mutually_exclusive_group(required=True)
    modes.add_argument("--run-dir")
    modes.add_argument("--read-freshness", action="store_true")
    ap.add_argument("--outcome-path", type=Path, help="New safe outcome file; never overwrite an older result")
    args = ap.parse_args()
    record = _outcome("WATCHDOG" if args.read_freshness else "SYNC")
    stream = None
    if args.outcome_path is not None:
        try:
            # Caller owns a unique path. CreateNew BEFORE any KV call prevents stale-result replacement and stops an
            # existing or unwritable path while the pointer is still NOT_ATTEMPTED, never after a publish.
            stream = args.outcome_path.open("x", encoding="utf-8")
        except (OSError, ValueError):
            _finish_call(record, "OUTCOME_WRITE_FAILED")
    code = 1  # an outcome path that could not be reserved runs nothing
    try:
        if args.outcome_path is None or stream is not None:
            code = read_freshness(record) if args.read_freshness else sync_run(Path(args.run_dir).resolve(), record)
    except (ValueError, KeyError, TypeError):
        _finish_call(record, "PARSE_FAILED" if args.read_freshness else "INPUT_INVALID")
        code = 1
    except OSError:
        _finish_call(record, "LOCAL_IO_FAILURE")
        code = 1
    except Exception:
        # Fail closed without serializing exception messages, CLI arguments or streams.
        _finish_call(record, "UNKNOWN")
        code = 1
    if stream is not None:
        try:
            with stream:
                json.dump(record, stream, separators=(",", ":"), allow_nan=False)
        except (OSError, ValueError):
            # A late write failure fails the run; phase and pointer_state keep what was observed.
            record.update(status="FAILED", error_category="OUTCOME_WRITE_FAILED")
            code = 1
    marker = "WATCHDOG_OUTCOME" if args.read_freshness else "SYNC_OUTCOME"
    print(marker + " " + json.dumps(record, separators=(",", ":"), allow_nan=False))
    if code:
        print(f"{marker}_FAILED phase={record['phase']} category={record['error_category']} "
              f"attempts={record['last_cli_attempts']} pointer_state={record['pointer_state']}", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
