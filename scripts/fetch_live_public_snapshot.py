#!/usr/bin/env python3
"""Read-only copy of the Production public sealed snapshot for the deploy gate's reader replay.

Copies `snapshot:current`, its global seal and every sealed object from the PUBLIC_CACHE namespace as exact
bytes (PowerShell 5.1 decodes native output with the console code page and corrupts UTF-8), verifies each
object against the seal's sha256 AND UTF-8 byte length and writes `index.json` (KV key -> file). Reused eager
payloads stay under core_run_id; only the fixed pipeline-liveness control stays global. Lazy objects stay
digest-addressed. Both identities are bound to the pointer-hashed root.
Wrangler 4 KV commands default to the local Miniflare store, so every read passes `--remote`. Nothing is written to any KV namespace.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

from stage_sealed_replay import LIVENESS_KEY, _seal_context, _verified_root  # shared read-only root validation

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import sync_sealed_snapshot_kv as sync  # noqa: E402  the sync's locked Wrangler CLI (no registry download)
NS = "96142af40b5d4213862d5483fe3a66da"
RUN_ID = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{12}$")
LAZY_KEY = re.compile(r"^v213:(?:identity:v2:(?:sym:[A-Z0-9_]|name:(?:1[0-5]|[0-9])|tok:[0-7])|quotes:v1|options:v[12]|options-coverage:v1|bottleneck-top20:v3|revenue-guidance-binding:v1"
                      r"|prices:v1:(?:US|TAIWAN|SWEDEN|EUROPE|JAPAN|KOREA|UK|HK))$")  # mirror of snapshot-seal.ts SNAPSHOT_LAZY_KEY_RE
ATTEMPTS = 3
RETRY_SECONDS = 5
Getter = Callable[[str], bytes]
EAGER_KEYS = frozenset((
    "v21:top20:latest", "scores:latest", "source_views:latest", "source_plan:latest",
    "reports:latest", "reports:morning:latest", "reports:evening:latest",
    "last_successful_pipeline_timestamp", "v212:top20-report:latest", "v213:top20-report:latest",
    "v213:source-federation:latest", "v213:source-independence:latest", "v213:activation-claim",
    "v213:macro-industry:latest",
))


def remote_getter() -> Getter:
    # The locked local Wrangler of cloud/ (declared == locked == installed); sync.CliUnavailable before any read.
    # Never a registry download run with the cached Production session.
    cli = sync._cli_command()

    def get(key: str) -> bytes:
        # A transient Cloudflare/network failure is retried; only a key absent on every attempt is reported missing.
        for attempt in range(ATTEMPTS):
            done = subprocess.run([*cli, "kv", "key", "get", key, "--namespace-id", NS, "--remote"],
                                  cwd=str(ROOT / "cloud"), capture_output=True, timeout=300)
            if done.returncode == 0 and done.stdout:
                return done.stdout
            if attempt + 1 < ATTEMPTS:
                time.sleep(RETRY_SECONDS)
        raise LookupError(f"LIVE_KEY_MISSING {key}")
    return get


def copy_snapshot(get: Getter, out: Path) -> dict:
    """Copy exact public bytes; return separately verified global and core identities plus any body mismatch."""
    if out.is_dir() and any(out.iterdir()):
        raise FileExistsError("snapshot copy directory is not empty")
    pointer = get("snapshot:current")
    pointer_meta = json.loads(pointer)
    if not isinstance(pointer_meta, dict):
        raise ValueError("LIVE_POINTER_INVALID")
    run = pointer_meta.get("run_id")
    if not isinstance(run, str) or not RUN_ID.fullmatch(run):
        raise ValueError("LIVE_POINTER_RUN_ID_INVALID")
    seal_key = f"snapshot:{run}:v213:snapshot-seal:v1"
    seal = get(seal_key)
    if not 0 < len(seal) <= 32_768:
        raise ValueError("LIVE_SEAL_SIZE_INVALID")
    manifest = json.loads(seal)
    if not isinstance(manifest, dict):
        raise ValueError("LIVE_SEAL_INVALID")
    _, core = _verified_root(pointer_meta, manifest, seal.decode("utf-8"))
    definitions = manifest["objects"]
    if not isinstance(definitions, dict):
        raise ValueError("LIVE_OBJECT_DEFINITIONS_INVALID")
    files = {"snapshot:current": pointer, seal_key: seal}
    mismatches = []
    for name, meta in definitions.items():
        if (name not in EAGER_KEYS and not LAZY_KEY.fullmatch(name)):
            raise ValueError("LIVE_OBJECT_KEY_INVALID")
        if (not isinstance(meta, dict) or set(meta) != {"sha256", "utf8_bytes"}
                or not isinstance(meta["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", meta["sha256"])
                or type(meta["utf8_bytes"]) is not int or not 0 < meta["utf8_bytes"] <= 2_097_152):
            raise ValueError("LIVE_OBJECT_DIGEST_INVALID")
        eager_run = run if "core_run_id" in manifest and name == LIVENESS_KEY else core
        key = f"blob:v1:{meta['sha256']}" if LAZY_KEY.fullmatch(name) else f"snapshot:{eager_run}:{name}"
        body = get(key)
        files[key] = body
        if len(body) != meta["utf8_bytes"] or hashlib.sha256(body).hexdigest() != meta["sha256"]:
            mismatches.append(name)
    if get("snapshot:current") != pointer:
        raise ValueError("LIVE_POINTER_MOVED_DURING_COPY")
    if not mismatches:
        _seal_context({key: body.decode("utf-8") for key, body in files.items() if key != "snapshot:current"}, pointer_meta)
        liveness_run = run if "core_run_id" in manifest else core
        expected_liveness = manifest["generated_at"] if "core_run_id" in manifest else manifest["public_data_as_of"]
        if files.get(f"snapshot:{liveness_run}:{LIVENESS_KEY}") != expected_liveness.encode("utf-8"):
            raise ValueError("LIVE_PIPELINE_LIVENESS_INVALID")
    out.mkdir(parents=True, exist_ok=True)
    index = {}
    for number, (key, body) in enumerate(files.items()):
        (out / f"k{number}.txt").write_bytes(body)
        index[key] = f"k{number}.txt"
    (out / "index.json").write_text(json.dumps(index), encoding="utf-8")
    return {"run_id": run, "core_run_id": core, "seal_sha256": pointer_meta["seal_sha256"],
            "pipeline_liveness_at": (manifest["generated_at"] if "core_run_id" in manifest else manifest["public_data_as_of"]) if not mismatches else None,
            "objects": len(files) - 2, "seal_mismatches": mismatches}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = copy_snapshot(remote_getter(), args.out)
    except sync.CliUnavailable:
        print(json.dumps({"status": "FAIL", "error": "LOCKED_CLI_UNAVAILABLE wrangler"}))
        return 1
    except (OSError, LookupError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "FAIL", "error": str(error)[:120]}))
        return 1
    print(json.dumps({"status": "OK", **result}))
    return 0 if not result["seal_mismatches"] else 1


if __name__ == "__main__":
    sys.exit(main())
