"""One same-hour, create-once sealed KV sync retry; no new seal or credential action.

Invoked only by the opt-in :42 watchdog path under the publisher's operation mutex.
Fail-closed offline eligibility and reservations precede any child process.
The unchanged sync adapter still owns object readback and pointer-last publication.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

RUN_PATTERN = re.compile(r"\d{8}T\d{6}Z-[0-9a-f]{12}")
PRIMARY_OUTCOME = re.compile(r"sealed-sync-[0-9a-f]{32}\.json")
MARKER_NAME = re.compile(r"(\d{8}T\d{6}Z-[0-9a-f]{12})\.json")
CATEGORIES = {"TRANSIENT_HTTP", "AUTHENTICATION_ERROR"}
PHASES = {"OBJECT_PUT", "POINTER_PUT"}
DAILY_WRITE_LIMIT = 1000
NON_SEALED_WRITE_RESERVE = 300
MAX_SYNC_SECONDS = 900
MAX_OBJECTS = 512


class Refused(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _plain(path: Path) -> Path:
    """Refuse reparse-point traversal, including Windows junctions."""
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        if part.exists() and (part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction())):
            raise Refused("PATH_UNSAFE")
    return path


def _load_json(path: Path, max_bytes: int = 8192) -> dict:
    if not path.is_file() or path.stat().st_size > max_bytes:
        raise Refused("EVIDENCE_UNAVAILABLE")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, UnicodeError):
        raise Refused("EVIDENCE_INVALID") from None
    if not isinstance(value, dict):
        raise Refused("EVIDENCE_INVALID")
    return value


def _stamp(run_id: str) -> datetime:
    if not RUN_PATTERN.fullmatch(run_id):
        raise Refused("RUN_INVALID")
    try:
        return datetime.strptime(run_id[:16], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        raise Refused("RUN_INVALID") from None


def _objects(run_dir: Path) -> int:
    _plain(run_dir)
    _plain(run_dir / "objects.json")
    if not (run_dir / "pointer.raw.json").is_file():
        raise Refused("RUN_INPUT_MISSING")
    size = (run_dir / "objects.json").stat().st_size
    if size > 8 * 1024 * 1024:
        raise Refused("RUN_INPUT_INVALID")
    try:
        value = json.loads((run_dir / "objects.json").read_text(encoding="utf-8"))
        pointer = json.loads((run_dir / "pointer.raw.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        raise Refused("RUN_INPUT_INVALID") from None
    if not isinstance(value, dict) or not 1 <= len(value) <= MAX_OBJECTS:
        raise Refused("RUN_INPUT_INVALID")
    if not isinstance(pointer, dict) or pointer.get("run_id") != run_dir.name:
        raise Refused("RUN_INPUT_INVALID")
    return len(value)


def _last_primary_summary(cache: Path) -> dict:
    log = _plain(cache / "sealed-refresh.log")
    if not log.is_file():
        raise Refused("PRIMARY_LOG_MISSING")
    # The final cycle's bounded summary is at the end; never copy raw log lines.
    with log.open("rb") as stream:
        stream.seek(max(0, log.stat().st_size - 131072))
        tail = stream.read().decode("utf-8", "replace")
    for line in reversed(tail.splitlines()):
        if line.startswith("SEALED_REFRESH_OUTCOME "):
            try:
                value = json.loads(line[len("SEALED_REFRESH_OUTCOME "):])
            except ValueError:
                raise Refused("PRIMARY_SUMMARY_INVALID") from None
            if not isinstance(value, dict):
                raise Refused("PRIMARY_SUMMARY_INVALID")
            return value
    raise Refused("PRIMARY_SUMMARY_MISSING")


def _primary_outcomes(cache: Path) -> dict[str, dict]:
    result = {}
    for path in cache.glob("sealed-sync-*.json"):
        if not PRIMARY_OUTCOME.fullmatch(path.name):
            continue
        _plain(path)
        record = _load_json(path)
        if record.get("schema_version") != 1 or record.get("operation") != "SYNC":
            raise Refused("OUTCOME_INVALID")
        run_id = record.get("run_id")
        if not isinstance(run_id, str) or not RUN_PATTERN.fullmatch(run_id):
            # An input refusal with zero calls cannot have issued any KV writes.
            if (run_id == "" and record.get("phase") == "INPUT" and
                    record.get("cli_attempts_total") == 0 and record.get("pointer_state") == "NOT_ATTEMPTED"):
                continue
            raise Refused("OUTCOME_INVALID")
        if run_id in result:
            raise Refused("DUPLICATE_PRIMARY_OUTCOME")
        if (record.get("status") not in ("SUCCEEDED", "FAILED") or
                type(record.get("objects_uploaded")) is not int or record["objects_uploaded"] < 0 or
                type(record.get("cli_attempts_total")) is not int or record["cli_attempts_total"] < 0):
            raise Refused("OUTCOME_INVALID")
        result[run_id] = record
    return result


def _runs(snapshots: Path) -> dict[str, Path]:
    if not snapshots.is_dir():
        raise Refused("SNAPSHOTS_MISSING")
    found = {}
    for path in snapshots.iterdir():
        if RUN_PATTERN.fullmatch(path.name):
            _plain(path)
            if not path.is_dir():
                raise Refused("RUN_INVALID")
            _stamp(path.name)
            found[path.name] = path
    if not found:
        raise Refused("RUN_MISSING")
    return found


def _budget(runs: dict[str, Path], outcomes: dict[str, dict], markers: Path,
            now: datetime, target_run: str) -> tuple[int, int]:
    """Reserve historical retry-inclusive PUTs, external margin, and one new full retry.

    Failed/missing primary outcomes reserve all objects at 3 PUTs each plus
    three pointer PUTs, even if the original stopped early. Successful cycles
    retain the existing 3*(uploaded+1) conservative estimator. Every previous
    retry marker reserves its full 3*(objects+1), including crashed attempts.
    """
    today = now.date()
    consumed = NON_SEALED_WRITE_RESERVE
    for run_id, record in outcomes.items():
        if _stamp(run_id).date() == today and run_id not in runs:
            raise Refused("BUDGET_HISTORY_GAP")
    for run_id, path in runs.items():
        if _stamp(run_id).date() != today:
            continue
        n = _objects(path)
        row = outcomes.get(run_id)
        if row is not None and row["status"] == "SUCCEEDED":
            if (row.get("phase") != "COMPLETE" or row.get("pointer_state") != "READBACK_CONFIRMED" or
                    row["objects_uploaded"] > n):
                raise Refused("BUDGET_OUTCOME_INVALID")
            consumed += 3 * (row["objects_uploaded"] + 1)
        else:
            consumed += 3 * (n + 1)
    if markers.exists():
        _plain(markers)
        for path in markers.iterdir():
            match = MARKER_NAME.fullmatch(path.name)
            if not match or not path.is_file():
                raise Refused("BUDGET_MARKER_INVALID")
            _plain(path)
            run_id = match.group(1)
            if _stamp(run_id).date() == today:
                if run_id not in runs:
                    raise Refused("BUDGET_HISTORY_GAP")
                consumed += 3 * (_objects(runs[run_id]) + 1)
    reserved = 3 * (_objects(runs[target_run]) + 1)
    if consumed + reserved > DAILY_WRITE_LIMIT:
        raise Refused("DAILY_BUDGET_REFUSED")
    return consumed, reserved


def _execute(sync_script: Path, run_dir: Path, outcome: Path) -> int:
    """Hard-stop the child process tree, not just its top-level Python process."""
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
    child = subprocess.Popen(
        [sys.executable, "-B", str(sync_script), "--run-dir", str(run_dir),
         "--outcome-path", str(outcome)],
        cwd=str(sync_script.parent.parent), stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=flags,
    )
    try:
        return child.wait(timeout=MAX_SYNC_SECONDS)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            # The unchanged adapter may have a live Wrangler grandchild.
            killed = subprocess.run(
                ["taskkill.exe", "/PID", str(child.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=30, check=False,
            )
            if killed.returncode != 0 and child.poll() is None:
                raise Refused("PROCESS_TREE_KILL_UNCONFIRMED")
        else:
            child.kill()
        try:
            child.wait(timeout=30)
        except subprocess.TimeoutExpired:
            raise Refused("PROCESS_TREE_KILL_UNCONFIRMED") from None
        return 124


def _retry_result(path: Path, run_id: str, exit_code: int) -> tuple[str, str]:
    try:
        _plain(path)
        result = _load_json(path)
        if (result.get("schema_version") != 1 or result.get("operation") != "SYNC" or
                result.get("run_id") != run_id):
            return "FAILED", "OUTCOME_INVALID"
        if (exit_code == 0 and result.get("status") == "SUCCEEDED" and
                result.get("phase") == "COMPLETE" and result.get("error_category") == "NONE" and
                result.get("pointer_state") == "READBACK_CONFIRMED"):
            return "SUCCEEDED", "READBACK_CONFIRMED"
        if result.get("pointer_state") == "ATTEMPTED_UNCONFIRMED":
            return "FAILED", "POINTER_UNCONFIRMED"
        return "FAILED", "SYNC_FAILED"
    except (Refused, OSError):
        return "FAILED", "OUTCOME_UNAVAILABLE"


def _write_marker(path: Path, row: dict, *, create: bool = False) -> None:
    payload = (json.dumps(row, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    if create:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    else:
        tmp = path.with_suffix(".tmp")
        with tmp.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        tmp.replace(path)


def attempt_once(repo: Path, snapshots: Path, now: datetime | None = None,
                 runner=None) -> dict:
    """No external calls on refusals. Runner is replaceable only for offline tests."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    try:
        repo, snapshots = _plain(repo), _plain(snapshots)
        cache = _plain(repo / "data" / "cache")
        if not cache.is_dir() or not (39 <= now.minute <= 49):
            raise Refused("NOT_RETRY_WINDOW")
        runs = _runs(snapshots)
        run_id = max(runs)
        age = (now - _stamp(run_id)).total_seconds()
        if not (20 * 60 <= age <= 45 * 60):
            raise Refused("RUN_AGE_INELIGIBLE")
        summary = _last_primary_summary(cache)
        if (summary.get("run_id") != run_id or type(summary.get("primary_exit")) is not int or
                summary["primary_exit"] == 0 or summary.get("publication_confirmed") is not False or
                summary.get("publication_operation_succeeded") is not False):
            raise Refused("NOT_LATEST_FAILED_PRIMARY")
        outcomes = _primary_outcomes(cache)
        record = outcomes.get(run_id)
        if not record or (record.get("status") != "FAILED" or
                          record.get("phase") not in PHASES or
                          record.get("error_category") not in CATEGORIES or
                          record.get("pointer_state") != "NOT_ATTEMPTED"):
            raise Refused("INELIGIBLE_SYNC_OUTCOME")
        if (summary.get("primary_phase") != record["phase"] or
                summary.get("error_category") != record["error_category"] or
                summary.get("pointer_state") != record["pointer_state"]):
            raise Refused("PRIMARY_OUTCOME_MISMATCH")
        markers = _plain(cache / "sealed-sync-retry-markers")
        marker = markers / (run_id + ".json")
        _plain(marker)
        if marker.exists():
            raise Refused("ALREADY_ATTEMPTED")
        previous, reserved = _budget(runs, outcomes, markers, now, run_id)
        # A crash between marker creation and the child launch consumes the attempt.
        markers.mkdir(exist_ok=True)
        try:
            _write_marker(marker, {"schema_version": 1, "status": "ATTEMPTED",
                                   "result": "PENDING", "reserved_put_attempts": reserved}, create=True)
        except FileExistsError:
            raise Refused("ALREADY_ATTEMPTED") from None
        except OSError:
            raise Refused("MARKER_WRITE_REFUSED") from None
        outcome = cache / ("sealed-sync-retry-" + run_id + ".json")
        _plain(outcome)
        try:
            if outcome.exists():
                raise Refused("RETRY_OUTCOME_ALREADY_EXISTS")
            sync_script = _plain(repo / "scripts" / "sync_sealed_snapshot_kv.py")
            if not sync_script.is_file():
                raise Refused("SYNC_SCRIPT_UNAVAILABLE")
            exit_code = (runner or _execute)(sync_script, runs[run_id], outcome)
            status, reason = _retry_result(outcome, run_id, exit_code)
        except Refused as error:
            status, reason = "FAILED", error.code
        except (OSError, subprocess.SubprocessError):
            status, reason = "FAILED", "EXECUTION_FAILED"
        row = {"schema_version": 1, "status": "COMPLETE", "result": status,
               "reason": reason, "attempts": 1, "reserved_put_attempts": reserved}
        try:
            _write_marker(marker, row)
        except (OSError, FileExistsError):
            return {"status": "FAILED", "reason": "MARKER_FINALIZE_FAILED", "attempted": True}
        return {"status": status, "reason": reason, "attempted": True,
                "reserved_put_attempts": reserved}
    except Refused as error:
        return {"status": "SKIPPED", "reason": error.code, "attempted": False}
    except (OSError, ValueError):
        return {"status": "SKIPPED", "reason": "LOCAL_EVIDENCE_UNAVAILABLE", "attempted": False}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", type=Path, required=True)
    ap.add_argument("--snapshot-root", type=Path, required=True)
    args = ap.parse_args()
    result = attempt_once(args.repo_root, args.snapshot_root)
    print("RETRY_OUTCOME " + json.dumps(result, separators=(",", ":"), allow_nan=False))
    return 1 if result["status"] == "FAILED" else 0


if __name__ == "__main__":
    sys.exit(main())
