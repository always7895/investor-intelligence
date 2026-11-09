#!/usr/bin/env python3
"""Replay a locally sealed run through the real Worker readers before any KV write (single-writer design, T5).

Stages the run's pointer and sealed objects (exact bytes from objects.json / pointer.raw.json) in the layout
cloud/test/live-kv-replay.test.ts reads, runs that test with vitest, and checks the result against the run's
Top20 state (summary.json):
  CARRIED_FORWARD  fresh report with 20 records, LINE flex and text answers, broadcast pre-checks, 20 v21 and
                   v212 rows;
  INSUFFICIENT     the sealed INSUFFICIENT refusal, never another report;
  (golden)         a fresh report.
A run whose seal carries the machine binding (v213:revenue-guidance-binding:v1) must also read it through the real
machine loader (guidance_machine_probe ADMITTED, expectation GUIDANCE_MACHINE_BINDING); other runs are unchanged.
Every state needs integrity=sealed, the immutable core/claim run id and a sealed macro overview. A market-only
global run may reference that core without renewing its clocks. Exit 0 only when all hold; the result JSON
(one line) names every failed expectation. Nothing is written to any KV namespace.
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
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
CLOUD = ROOT / "cloud"
READER_CONTRACT_VERSION = "v213-reader-replay-v5"
SEAL_MAX_AGE_SECONDS = "7200"
GUIDANCE_BINDING_KEY = "v213:revenue-guidance-binding:v1"
SEAL_KEY = "v213:snapshot-seal:v1"
LIVENESS_KEY = "last_successful_pipeline_timestamp"
RUN_RE = re.compile(r"\d{8}T\d{6}Z-[0-9a-f]{12}\Z")
LAZY_KEY_RE = re.compile(r"v213:(?:identity:v2:(?:sym:[A-Z0-9_]|name:(?:1[0-5]|[0-9])|tok:[0-7])|quotes:v1|options:v[12]|options-coverage:v1|bottleneck-top20:v3|revenue-guidance-binding:v1|prices:v1:(?:US|TAIWAN|SWEDEN|EUROPE|JAPAN|KOREA|UK|HK))\Z")

Runner = Callable[[Path, Path], int]


def _instant(value: Any) -> float:
    if not isinstance(value, str) or not re.fullmatch(r"(?!0000)\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{3})?Z", value):
        raise ValueError("invalid sealed timestamp")
    return datetime.fromisoformat(value[:-1] + "+00:00").timestamp()


def _verified_root(pointer: dict[str, Any], seal: dict[str, Any], raw: str) -> tuple[str, str]:
    """Bind global/core identities to the exact pointer-hashed root before any object lookup."""
    pointer_fields = {"schema_version", "run_id", "transaction_id", "seal_sha256", "public_data_as_of",
                      "promoted_at", "provider_scope", "owner_watchlist_inherited"}
    fields = {"schema_version", "contract_id", "run_id", "transaction_id", "generated_at", "public_data_as_of",
              "provider_scope", "owner_watchlist_inherited", "objects"}
    extended = "core_run_id" in seal
    if extended != ("ranking_persisted_at" in seal):
        raise ValueError("partial core metadata")
    if extended:
        fields.update(("core_run_id", "ranking_persisted_at"))
    if "product_persisted_at" in seal:
        fields.add("product_persisted_at")
    if (set(pointer) != pointer_fields or type(pointer["schema_version"]) is not int or pointer["schema_version"] != 2
            or not isinstance(pointer["run_id"], str) or not RUN_RE.fullmatch(pointer["run_id"])
            or not isinstance(pointer["transaction_id"], str) or not re.fullmatch(r"[0-9a-f]{32}", pointer["transaction_id"])
            or not isinstance(pointer["seal_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", pointer["seal_sha256"])
            or pointer["provider_scope"] != "public_only" or pointer["owner_watchlist_inherited"] is not False
            or set(seal) != fields or type(seal["schema_version"]) is not int or seal["schema_version"] != 1
            or seal["contract_id"] != "v213-stored-snapshot-v1" or seal["run_id"] != pointer["run_id"]
            or seal["transaction_id"] != pointer["transaction_id"] or seal["public_data_as_of"] != pointer["public_data_as_of"]
            or seal["provider_scope"] != "public_only" or seal["owner_watchlist_inherited"] is not False
            or hashlib.sha256(raw.encode("utf-8")).hexdigest() != pointer["seal_sha256"]):
        raise ValueError("invalid sealed root")
    _instant(pointer["promoted_at"])
    generated = _instant(seal["generated_at"])
    data_at = _instant(seal["public_data_as_of"])
    if data_at > generated + 300:
        raise ValueError("invalid data clock")
    core_id = seal["core_run_id"] if extended else pointer["run_id"]
    if not isinstance(core_id, str) or not RUN_RE.fullmatch(core_id):
        raise ValueError("invalid core run")
    if extended and (_instant(seal["ranking_persisted_at"]) > generated or data_at > _instant(seal["ranking_persisted_at"]) + 300):
        raise ValueError("invalid core clock")
    if "product_persisted_at" in seal:
        clocks = seal["product_persisted_at"]
        if (not isinstance(clocks, dict) or set(clocks) - {"market", "prices", "identity"}
                or any(_instant(stamp) > generated for stamp in clocks.values())):
            raise ValueError("invalid product clocks")
    return pointer["run_id"], core_id


def _seal_context(objects: dict[str, str], pointer: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    """Resolve only the pointer's root. Extended maps contain core payloads, global liveness and digest-bound blobs.

    Ordinary historical staging still delegates seal validity to the real Worker; no cross-run snapshot keys
    are accepted. This never fetches, clones or repairs a missing body.
    """
    run_id = str(pointer["run_id"])
    root_key = f"snapshot:{run_id}:{SEAL_KEY}"
    seal = json.loads(objects[root_key]) if root_key in objects else {}
    if not isinstance(seal, dict):
        raise ValueError("invalid seal root")
    extended = "core_run_id" in seal
    if extended != ("ranking_persisted_at" in seal):
        raise ValueError("partial core metadata")
    core_id = seal["core_run_id"] if extended else run_id
    if not isinstance(core_id, str) or (extended and not RUN_RE.fullmatch(core_id)):
        raise ValueError("invalid core run")
    liveness_key = f"snapshot:{run_id}:{LIVENESS_KEY}"
    if any(key.startswith("snapshot:") and key != root_key and not (extended and key == liveness_key)
           and not key.startswith(f"snapshot:{core_id}:") for key in objects):
        raise ValueError("objects.json crosses the sealed core run")
    if "product_persisted_at" in seal:
        clocks = seal["product_persisted_at"]
        if (not isinstance(clocks, dict) or set(clocks) - {"market", "prices", "identity"}
                or any(_instant(stamp) > _instant(seal.get("generated_at")) for stamp in clocks.values())):
            raise ValueError("invalid product clocks")
    if not extended:
        return run_id, core_id, seal
    run_id, core_id = _verified_root(pointer, seal, objects[root_key])
    ranking_at = _instant(seal["ranking_persisted_at"])
    definitions = seal["objects"]
    if not isinstance(definitions, dict):
        raise ValueError("invalid object definitions")
    expected = {root_key}
    for logical, entry in definitions.items():
        if (not isinstance(entry, dict) or set(entry) != {"sha256", "utf8_bytes"}
                or not isinstance(entry["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
                or type(entry["utf8_bytes"]) is not int or not 0 < entry["utf8_bytes"] <= 2_097_152):
            raise ValueError("invalid object digest")
        key = ("blob:v1:" + entry["sha256"] if LAZY_KEY_RE.fullmatch(logical)
               else liveness_key if logical == LIVENESS_KEY else f"snapshot:{core_id}:{logical}")
        body = objects.get(key)
        encoded = body.encode("utf-8") if isinstance(body, str) else b""
        if len(encoded) != entry["utf8_bytes"] or hashlib.sha256(encoded).hexdigest() != entry["sha256"]:
            raise ValueError("missing or corrupt sealed object")
        expected.add(key)
    if set(objects) != expected:
        raise ValueError("objects.json contains unsealed keys")
    claim = json.loads(objects.get(f"snapshot:{core_id}:v213:activation-claim", "null"))
    if (not isinstance(claim, dict) or claim.get("run_id") != core_id
            or claim.get("transaction_id") != seal["transaction_id"]
            or _instant(claim.get("claimed_at")) > ranking_at + 300
            or objects.get(liveness_key) != seal["generated_at"]):
        raise ValueError("core claim or global liveness changed")
    return run_id, core_id, seal


def _stage(objects_raw: bytes, pointer: bytes, out: Path) -> str:
    """Stage one captured source snapshot, never reopening its mutable run directory."""
    objects = json.loads(objects_raw.decode("utf-8"))
    if not isinstance(objects, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in objects.items()):
        raise ValueError("invalid objects map")
    run_id, _, _ = _seal_context(objects, json.loads(pointer))
    # Fail closed before any write: an object named like the pointer would take over k0.txt's index entry, and files
    # left in a reused directory would sit next to this run's index as if they belonged to it.
    if "snapshot:current" in objects:
        raise ValueError("objects.json names the serving pointer key")
    if out.is_dir() and any(out.iterdir()):
        raise FileExistsError("staging directory is not empty")
    out.mkdir(parents=True, exist_ok=True)
    index = {"snapshot:current": "k0.txt"}
    (out / "k0.txt").write_bytes(pointer)
    for number, (key, body) in enumerate(objects.items(), start=1):
        (out / f"k{number}.txt").write_bytes(body.encode("utf-8"))
        index[key] = f"k{number}.txt"
    (out / "index.json").write_text(json.dumps(index), encoding="utf-8")
    return run_id


def stage(run_dir: Path, out: Path) -> str:
    """Stage exact bytes; return the global run id (Worker run_id remains the core/claim identity)."""
    return _stage((run_dir / "objects.json").read_bytes(), (run_dir / "pointer.raw.json").read_bytes(), out)


class LockedCliUnavailable(RuntimeError):
    """The locked local Vitest of cloud/ could not be selected; no process was started."""


def _vitest_command() -> list[str]:
    """[node, vitest.mjs] of the installed Vitest matching BOTH cloud/package.json and the lock.

    The rule of sync_sealed_snapshot_kv._cli_command: never a registry download or an install; a missing or mismatched
    component is LockedCliUnavailable.
    """
    try:
        declared = json.loads((CLOUD / "package.json").read_text(encoding="utf-8"))["devDependencies"]["vitest"]
        locked = json.loads((CLOUD / "package-lock.json").read_text(encoding="utf-8"))["packages"]["node_modules/vitest"]["version"]
        package = CLOUD / "node_modules" / "vitest"
        installed = json.loads((package / "package.json").read_text(encoding="utf-8"))["version"]
        cli = package / "vitest.mjs"
        node = os.getenv("PROJECT_NODE") or os.getenv("NODE_FOR_RUNNER") or shutil.which("node")
        if not node or not Path(node).is_file() or not cli.is_file() or declared != locked or installed != locked:
            raise LockedCliUnavailable()
        return [str(Path(node).resolve()), str(cli)]
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise LockedCliUnavailable() from error


def vitest_runner(replay_dir: Path, result_path: Path) -> int:
    command = _vitest_command()
    env = {**os.environ, "V213_LIVE_REPLAY_DIR": str(replay_dir), "V213_LIVE_REPLAY_OUT": str(result_path),
           "V213_LIVE_REPLAY_MAX_AGE": SEAL_MAX_AGE_SECONDS}
    done = subprocess.run([*command, "run", "test/live-kv-replay.test.ts"], cwd=str(CLOUD), env=env,
                          capture_output=True, timeout=600)
    return done.returncode


def expectations(result: dict[str, Any], state: str | None, run_id: str, identity: bool = False, bottleneck: bool = False,
                 machine: bool = False, *, seal_run_id: str, seal_sha256: str) -> list[str]:
    """Names of every failed expectation for this Top20 state (empty: pass)."""
    checks = {
        "READER_CONTRACT": result.get("reader_contract_version") == READER_CONTRACT_VERSION,
        "INTEGRITY_SEALED": result.get("integrity") == "sealed",
        "SEAL_RUN_ID": result.get("seal_run_id") == seal_run_id,
        "RUN_ID": result.get("run_id") == run_id,
        "SEAL_SHA256": isinstance(seal_sha256, str) and re.fullmatch(r"[0-9a-f]{64}", seal_sha256) is not None
                       and result.get("seal_sha256") == seal_sha256,
        "MACRO_SEALED": result.get("macro_overview_sealed") is True,
    }
    reused_core = seal_run_id != run_id
    expired_core_refused = (reused_core and result.get("legacy_report_expired_refused") is True
                            and result.get("pipeline_liveness_fresh") is True and result.get("fresh") is False)
    if expired_core_refused:
        # The original legacy report must remain refused; its archived rows are not a new ranking publication.
        checks["LEGACY_EXPIRED_REFUSAL"] = (result.get("top20_records") == 0 and result.get("report_generated_at") is None
                                            and result.get("broadcast_ready") is False
                                            and isinstance(result.get("legacy_report_original_generated_at"), str)
                                            and bool(result["legacy_report_original_generated_at"]))
    elif state == "CARRIED_FORWARD":
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
    if machine:  # the staged run carries the sealed machine binding: the real machine loader must read it
        checks["GUIDANCE_MACHINE_BINDING"] = (result.get("guidance_machine_probe") == "ADMITTED"
            or (reused_core and result.get("guidance_machine_probe") == "REFUSED"
                and result.get("guidance_machine_dated_facts_only") is True))
    return [name for name, ok in checks.items() if not ok]


def replay(run_dir: Path, runner: Runner = vitest_runner) -> dict[str, Any]:
    captured = {name: (run_dir / name).read_bytes() for name in ("summary.json", "objects.json", "pointer.raw.json")}
    state = json.loads(captured["summary.json"]).get("top20_state")
    objects = json.loads(captured["objects.json"])
    pointer = json.loads(captured["pointer.raw.json"])
    run_id, core_id, seal = _seal_context(objects, pointer)
    seal_sha256 = pointer.get("seal_sha256")
    if (not isinstance(seal_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", seal_sha256)
            or hashlib.sha256(objects[f"snapshot:{run_id}:{SEAL_KEY}"].encode("utf-8")).hexdigest() != seal_sha256):
        raise ValueError("staged seal hash is not pointer-bound")
    sealed_keys = set(seal.get("objects", {}))
    identity = any(key.startswith("v213:identity:v2:") for key in sealed_keys)
    with tempfile.TemporaryDirectory(prefix="ii-staged-replay-") as tmp:
        replay_dir, result_path = Path(tmp) / "kv", Path(tmp) / "result.json"
        _stage(captured["objects.json"], captured["pointer.raw.json"], replay_dir)
        code = runner(replay_dir, result_path)
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            result = {}
        if not isinstance(result, dict):
            result = {}
    try:
        changed = any((run_dir / name).read_bytes() != raw for name, raw in captured.items())
    except OSError:
        changed = True
    failed = expectations(result, state, core_id, identity, "v213:bottleneck-top20:v3" in sealed_keys,
                           GUIDANCE_BINDING_KEY in sealed_keys, seal_run_id=run_id, seal_sha256=seal_sha256) if result else ["RESULT_MISSING"]
    if changed:
        failed.insert(0, "STAGED_SOURCE_CHANGED")
    if code != 0:
        failed.insert(0, "VITEST_EXIT_NONZERO")
    return {"status": "PASS" if not failed else "FAIL", "run_id": run_id, "core_run_id": core_id, "seal_sha256": seal_sha256,
            "top20_state": state, "failed": failed,
            **{key: result.get(key) for key in ("fresh", "top20_records", "test_only_admission", "report_generated_at",
                                                 "potential_ranking_records", "reader_contract_version", "identity_probe", "price_probe", "bottleneck_v3_zh_named",
                                                 "bottleneck_v3_records", "v3_cross_checks", "v3_detail_probe", "order_probe", "option_probe",
                                                 "alias_probe", "guidance_machine_probe", "guidance_machine_dated_facts_only",
                                                 "legacy_report_expired_refused", "legacy_report_original_generated_at",
                                                 "pipeline_liveness_fresh")}}  # probes bound to the captured seal, never re-associated with later source bytes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        outcome = replay(args.run_dir)
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired, LockedCliUnavailable) as error:
        outcome = {"status": "FAIL", "failed": ["STAGE_ERROR"], "error": type(error).__name__}
    print(json.dumps(outcome, ensure_ascii=False))
    return 0 if outcome["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
