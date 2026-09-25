#!/usr/bin/env python3
"""Top20 last-known-good (LKG) bundle for the hourly sealed publisher (single-writer design, T5).

The hourly publisher is the only Production writer. It re-seals the newest validated Top20 bundle byte for byte
(``load_top20_bundle``) and never re-stamps report or row times; the report may be carried until
``report_max_age_hours`` (config/v213-top20-report-freshness-v1.json) minus one hourly interval. A data-only
refresh writes a candidate bundle; ``promote`` copies it into the LKG directory only after the same checks pass.
``due`` tells the hourly script whether a refresh is needed (LKG older than ``refresh_after_hours``, or missing)
and not suppressed by the persisted backoff after a failed refresh.

Commands (JSON on stdout):
  top20_carry_forward.py check   --bundle PATH
  top20_carry_forward.py due     [--lkg-dir DIR]
  top20_carry_forward.py promote --candidate PATH [--lkg-dir DIR]
  top20_carry_forward.py record  --result ok|fail [--note TEXT] [--lkg-dir DIR]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import v213_evidence_policy as policy  # noqa: E402

LKG_DIR = ROOT / "data" / "cache" / "top20-lkg"
PUBLICATION_MODE_PATH = ROOT / "config" / "v213-r75-publication-mode-v1.json"
STATE_NAME = "refresh-state.json"
RUN_ID = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{12}$")
# The Top20 objects the publisher may carry; every other object keeps its sealed placeholder (reports:*,
# source-independence and federation have no report-age gate in their readers).
CARRIED_OBJECTS = {
    "top20_json": "v21:top20:latest",
    "v212_top20_report_json": "v212:top20-report:latest",
    "v213_top20_report_json": "v213:top20-report:latest",
}
SHARED_FIELDS = ("long_term_return_pct", "short_term_return_pct", "industry", "profit_summary")
SEAL_INTERVAL_SECONDS = 3600  # a carried report must stay readable until the next hourly seal
BACKOFF_SECONDS = 3 * 3600
KEEP_LKG = 5


class BundleRejected(ValueError):
    """A bundle the publisher must not carry; the message is a stable reason code."""


def _age_ok(value: Any, now: datetime, limit_seconds: float) -> bool:
    moment = policy.parse_time(value)
    if moment is None:
        return False
    age = (now - moment).total_seconds()
    return -policy.CLOCK_SKEW_SECONDS <= age <= limit_seconds


def load_top20_bundle(path: Path, now: datetime) -> dict[str, Any]:
    """Validated carry set: {"payloads": {name: exact text}, "run_id", "bundle_sha256", "report_generated_at",
    "tickers", "test_only_admission"}. Raises BundleRejected with a reason code."""
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise BundleRejected("TOP20_BUNDLE_MISSING") from error
    try:
        bundle = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as error:
        raise BundleRejected("TOP20_BUNDLE_JSON_INVALID") from error
    mode = json.loads(PUBLICATION_MODE_PATH.read_text(encoding="utf-8"))
    if not isinstance(bundle, dict) or bundle.get("schema_version") != mode["bundle_schema_version"]:
        raise BundleRejected("TOP20_BUNDLE_SCHEMA")
    if not RUN_ID.fullmatch(str(bundle.get("run_id", ""))):
        raise BundleRejected("TOP20_BUNDLE_RUN_ID")
    payloads, digests = bundle.get("payloads"), bundle.get("sha256")
    names = set(mode["payload_names"])
    if not isinstance(payloads, dict) or not isinstance(digests, dict) or set(payloads) != names or set(digests) != names:
        raise BundleRejected("TOP20_BUNDLE_PAYLOAD_NAMES")
    for name in sorted(names):
        text = payloads[name]
        if not isinstance(text, str) or hashlib.sha256(text.encode("utf-8")).hexdigest() != digests[name]:
            raise BundleRejected("TOP20_BUNDLE_DIGEST")
    try:
        top20 = json.loads(payloads["top20_json"])
        v212 = json.loads(payloads["v212_top20_report_json"])
        v213 = json.loads(payloads["v213_top20_report_json"])
    except ValueError as error:
        raise BundleRejected("TOP20_PAYLOAD_JSON_INVALID") from error
    # The Worker contract must hold now and at the next hourly seal (readers check at read time).
    for moment in (now, now + timedelta(seconds=SEAL_INTERVAL_SECONDS)):
        reasons = policy.validate_seven_field_report(v213, now=moment)
        if reasons:
            raise BundleRejected("TOP20_REPORT_INVALID:" + reasons[0])
    limit = policy.report_freshness()["report_max_age_hours"] * 3600 - SEAL_INTERVAL_SECONDS
    if not _age_ok(v213.get("generated_at"), now, limit):
        raise BundleRejected("TOP20_REPORT_TOO_OLD")
    if not isinstance(top20, list) or len(top20) != 20 or not isinstance(v212, dict) \
            or not isinstance(v212.get("records"), list) or len(v212["records"]) != 20:
        raise BundleRejected("TOP20_RECORD_COUNT")
    order = [str(row.get("ticker")) for row in v213["records"]]
    if [str(row.get("ticker")) if isinstance(row, dict) else None for row in top20] != order \
            or [str(row.get("ticker")) if isinstance(row, dict) else None for row in v212["records"]] != order:
        raise BundleRejected("TOP20_ORDER_MISMATCH")
    if any(row.get(key) != five.get(key) for row, five in zip(v213["records"], v212["records"]) for key in SHARED_FIELDS):
        raise BundleRejected("TOP20_ACQUISITION_MISMATCH")
    carried_times = [v212.get("generated_at"), *(row.get("generated_at") for row in top20),
                     *(row.get("retrieved_at") for row in v212["records"])]
    if not all(_age_ok(value, now, limit) for value in carried_times):
        raise BundleRejected("TOP20_ROW_TOO_OLD")
    return {
        "payloads": {name: payloads[name] for name in CARRIED_OBJECTS},
        "run_id": bundle["run_id"],
        "bundle_sha256": hashlib.sha256(raw).hexdigest(),
        "report_generated_at": v213["generated_at"],
        "tickers": order,
        "test_only_admission": v213["records"][0]["test_only_admission"],
    }


def newest_lkg(lkg_dir: Path = LKG_DIR) -> Path | None:
    """Newest LKG file; names are run ids, so name order is time order."""
    files = sorted(p for p in lkg_dir.glob("*.json") if RUN_ID.fullmatch(p.stem))
    return files[-1] if files else None


def _read_state(lkg_dir: Path) -> dict[str, Any]:
    try:
        state = json.loads((lkg_dir / STATE_NAME).read_text(encoding="utf-8"))
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_bytes(data)
    os.replace(temp, path)


def refresh_due(now: datetime, lkg_dir: Path = LKG_DIR) -> dict[str, Any]:
    """{"due": bool, "reason": code}: refresh when the LKG is missing, invalid or refresh_after_hours old,
    unless a failed refresh less than BACKOFF_SECONDS ago suppresses the retry."""
    state = _read_state(lkg_dir)
    failed_at = policy.parse_time(state.get("last_failure_at"))
    if state.get("last_result") == "fail" and failed_at and (now - failed_at).total_seconds() < BACKOFF_SECONDS:
        return {"due": False, "reason": "BACKOFF_ACTIVE", "retry_after": policy.iso_z(failed_at + timedelta(seconds=BACKOFF_SECONDS))}
    newest = newest_lkg(lkg_dir)
    if newest is None:
        return {"due": True, "reason": "LKG_MISSING"}
    try:
        carried = load_top20_bundle(newest, now)
    except BundleRejected as error:
        return {"due": True, "reason": "LKG_REJECTED", "detail": str(error)}
    generated = policy.parse_time(carried["report_generated_at"])
    age_hours = (now - generated).total_seconds() / 3600
    if age_hours >= policy.report_freshness()["refresh_after_hours"]:
        return {"due": True, "reason": "LKG_AGED", "age_hours": round(age_hours, 2)}
    return {"due": False, "reason": "LKG_FRESH", "age_hours": round(age_hours, 2)}


def promote(candidate: Path, now: datetime, lkg_dir: Path = LKG_DIR) -> dict[str, Any]:
    """Copy a candidate bundle into the LKG directory (exact bytes) after it passes load_top20_bundle; keep the
    newest KEEP_LKG files. A candidate that is not newer than the newest LKG is not promoted."""
    carried = load_top20_bundle(candidate, now)
    newest = newest_lkg(lkg_dir)
    if newest is not None and newest.stem >= carried["run_id"]:
        raise BundleRejected("TOP20_CANDIDATE_NOT_NEWER")
    target = lkg_dir / f"{carried['run_id']}.json"
    _write_atomic(target, candidate.read_bytes())
    for old in sorted(p for p in lkg_dir.glob("*.json") if RUN_ID.fullmatch(p.stem))[:-KEEP_LKG]:
        old.unlink()
    return {"promoted": carried["run_id"], "bundle_sha256": carried["bundle_sha256"],
            "report_generated_at": carried["report_generated_at"]}


def record(result: str, now: datetime, note: str = "", lkg_dir: Path = LKG_DIR) -> dict[str, Any]:
    state = _read_state(lkg_dir)
    state.update({"schema_version": 1, "last_result": result, "last_attempt_at": policy.iso_z(now), "note": note[:200]})
    if result == "fail":
        state["last_failure_at"] = policy.iso_z(now)
        state["consecutive_failures"] = int(state.get("consecutive_failures", 0)) + 1
    else:
        state["consecutive_failures"] = 0
    _write_atomic(lkg_dir / STATE_NAME, json.dumps(state, indent=1).encode("utf-8"))
    return state


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["check", "due", "promote", "record"])
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--lkg-dir", type=Path, default=LKG_DIR)
    parser.add_argument("--result", choices=["ok", "fail"])
    parser.add_argument("--note", default="")
    args = parser.parse_args(argv)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    try:
        if args.command == "check":
            carried = load_top20_bundle(args.bundle, now)
            out: dict[str, Any] = {"status": "VALID", **{k: v for k, v in carried.items() if k != "payloads"}}
        elif args.command == "due":
            out = refresh_due(now, args.lkg_dir)
        elif args.command == "promote":
            out = {"status": "PROMOTED", **promote(args.candidate, now, args.lkg_dir)}
        else:
            if not args.result:
                parser.error("record needs --result")
            out = record(args.result, now, args.note, args.lkg_dir)
    except BundleRejected as error:
        print(json.dumps({"status": "REJECTED", "reason": str(error)}))
        return 2
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
