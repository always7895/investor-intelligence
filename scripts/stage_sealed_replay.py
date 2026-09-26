#!/usr/bin/env python3
"""Replay a locally sealed run through the real Worker readers before any KV write (single-writer design, T5).

Stages the run's pointer and sealed objects (exact bytes from objects.json / pointer.raw.json) in the layout
cloud/test/live-kv-replay.test.ts reads, runs that test with vitest, and checks the result against the run's
Top20 state (summary.json):
  CARRIED_FORWARD  fresh report with 20 records, LINE flex and text answers, broadcast pre-checks, 20 v21 and
                   v212 rows;
  INSUFFICIENT     the sealed INSUFFICIENT refusal, never another report;
  (golden)         a fresh report.
Every state needs integrity=sealed, this run id and a sealed macro overview. Exit 0 only when all hold; the
result JSON (one line) names every failed expectation. Nothing is written to any KV namespace.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
CLOUD = ROOT / "cloud"
READER_CONTRACT_VERSION = "v213-reader-replay-v2"
SEAL_MAX_AGE_SECONDS = "7200"

Runner = Callable[[Path, Path], int]


def stage(run_dir: Path, out: Path) -> str:
    """Write index.json (KV key -> file) for the run's pointer and objects; returns the run id."""
    objects = json.loads((run_dir / "objects.json").read_bytes().decode("utf-8"))
    pointer = (run_dir / "pointer.raw.json").read_bytes()
    run_id = str(json.loads(pointer)["run_id"])
    out.mkdir(parents=True, exist_ok=True)
    index = {"snapshot:current": "k0.txt"}
    (out / "k0.txt").write_bytes(pointer)
    for number, (key, body) in enumerate(objects.items(), start=1):
        (out / f"k{number}.txt").write_bytes(body.encode("utf-8"))
        index[key] = f"k{number}.txt"
    (out / "index.json").write_text(json.dumps(index), encoding="utf-8")
    return run_id


def vitest_runner(replay_dir: Path, result_path: Path) -> int:
    npx = shutil.which("npx") or shutil.which("npx.cmd") or "npx"
    env = {**os.environ, "V213_LIVE_REPLAY_DIR": str(replay_dir), "V213_LIVE_REPLAY_OUT": str(result_path),
           "V213_LIVE_REPLAY_MAX_AGE": SEAL_MAX_AGE_SECONDS}
    done = subprocess.run([npx, "--yes", "vitest", "run", "test/live-kv-replay.test.ts"], cwd=str(CLOUD), env=env,
                          capture_output=True, timeout=600)
    return done.returncode


def expectations(result: dict[str, Any], state: str | None, run_id: str, identity: bool = False, bottleneck: bool = False) -> list[str]:
    """Names of every failed expectation for this Top20 state (empty: pass)."""
    checks = {
        "READER_CONTRACT": result.get("reader_contract_version") == READER_CONTRACT_VERSION,
        "INTEGRITY_SEALED": result.get("integrity") == "sealed",
        "RUN_ID": result.get("run_id") == run_id,
        "MACRO_SEALED": result.get("macro_overview_sealed") is True,
    }
    if state == "CARRIED_FORWARD":
        checks.update({
            "FRESH": result.get("fresh") is True,
            "TOP20_RECORDS": result.get("top20_records") == 20,
            "LINE_FLEX": int(result.get("line_flex_messages") or 0) > 0,
            "LINE_TEXT": int(result.get("line_text_messages") or 0) > 0,
            "BROADCAST_READY": result.get("broadcast_ready") is True,
            "V21_RECORDS": result.get("v21_records") == 20,
            "V212_RECORDS": result.get("v212_records") == 20,
            "ADMISSION_BOOLEAN": isinstance(result.get("test_only_admission"), bool),
        })
    elif state == "INSUFFICIENT":
        checks.update({
            "NOT_FRESH": result.get("fresh") is False,
            "INSUFFICIENT_REFUSAL": result.get("refusal_is_insufficient") is True,
            "NO_CARRIED_ROWS": result.get("v21_records") == 0,
        })
    else:
        checks["FRESH"] = result.get("fresh") is True
    if identity:
        probe = result.get("identity_probe") or {}
        checks["IDENTITY_NVDA"] = probe.get("NVDA") == "RESOLVED:NASDAQ:NVDA"
        checks["IDENTITY_2330"] = probe.get("2330") == "RESOLVED:TWSE:2330"
        checks["IDENTITY_TW_NAME"] = probe.get("台積電") == "RESOLVED:TWSE:2330"  # exchange name beats sourced Chinese names
    if bottleneck:
        checks["BOTTLENECK_V3"] = int(result.get("bottleneck_v3_records") or 0) >= 10 and int(result.get("bottleneck_v3_flex") or 0) > 0
        checks["INDUSTRY_V3"] = int(result.get("industry_v3_flex") or 0) > 0
    return [name for name, ok in checks.items() if not ok]


def replay(run_dir: Path, runner: Runner = vitest_runner) -> dict[str, Any]:
    summary = json.loads((run_dir / "summary.json").read_bytes().decode("utf-8"))
    state = summary.get("top20_state")
    with tempfile.TemporaryDirectory(prefix="ii-staged-replay-") as tmp:
        replay_dir, result_path = Path(tmp) / "kv", Path(tmp) / "result.json"
        run_id = stage(run_dir, replay_dir)
        code = runner(replay_dir, result_path)
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            result = {}
    objects = json.loads((run_dir / "objects.json").read_bytes().decode("utf-8"))
    seal = json.loads(next(body for key, body in objects.items() if key.endswith(":v213:snapshot-seal:v1")))
    sealed_keys = set(seal.get("objects", {}))
    identity = any(key.startswith("v213:identity:v2:") for key in sealed_keys)
    failed = expectations(result, state, run_id, identity, "v213:bottleneck-top20:v3" in sealed_keys) if result else ["RESULT_MISSING"]
    if code != 0:
        failed.insert(0, "VITEST_EXIT_NONZERO")
    return {"status": "PASS" if not failed else "FAIL", "run_id": run_id, "top20_state": state, "failed": failed,
            **{key: result.get(key) for key in ("fresh", "top20_records", "test_only_admission", "report_generated_at",
                                                 "potential_ranking_records", "reader_contract_version", "identity_probe", "price_probe", "bottleneck_v3_zh_named",
                                                 "bottleneck_v3_records")}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        outcome = replay(args.run_dir)
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
        outcome = {"status": "FAIL", "failed": ["STAGE_ERROR"], "error": type(error).__name__}
    print(json.dumps(outcome, ensure_ascii=False))
    return 0 if outcome["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
