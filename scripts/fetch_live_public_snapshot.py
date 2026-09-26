#!/usr/bin/env python3
"""Read-only copy of the Production public sealed snapshot for the deploy gate's reader replay.

Copies `snapshot:current`, the run's seal and every sealed object from the PUBLIC_CACHE namespace as exact
bytes (PowerShell 5.1 decodes native output with the console code page and corrupts UTF-8), verifies each
object against the seal's sha256 and writes `index.json` (KV key -> file). Wrangler 4 KV commands default to
the local Miniflare store, so every read passes `--remote`. Nothing is written to any KV namespace.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
NS = "96142af40b5d4213862d5483fe3a66da"
RUN_ID = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{12}$")
LAZY_KEY = re.compile(r"^v213:(?:identity:v2:(?:sym:[A-Z0-9_]|name:(?:1[0-5]|[0-9]))|quotes:v1|options:v[12]|bottleneck-top20:v3"
                      r"|prices:v1:(?:US|TAIWAN|SWEDEN|EUROPE|JAPAN|KOREA|UK|HK))$")  # mirror of snapshot-seal.ts SNAPSHOT_LAZY_KEY_RE
ATTEMPTS = 3
RETRY_SECONDS = 5
Getter = Callable[[str], bytes]


def remote_getter() -> Getter:
    npx = shutil.which("npx") or shutil.which("npx.cmd") or "npx"

    def get(key: str) -> bytes:
        # A transient Cloudflare/network failure is retried; only a key absent on every attempt is reported missing.
        for attempt in range(ATTEMPTS):
            done = subprocess.run([npx, "--yes", "wrangler", "kv", "key", "get", key, "--namespace-id", NS, "--remote"],
                                  cwd=str(ROOT / "cloud"), capture_output=True, timeout=300)
            if done.returncode == 0 and done.stdout:
                return done.stdout
            if attempt + 1 < ATTEMPTS:
                time.sleep(RETRY_SECONDS)
        raise LookupError(f"LIVE_KEY_MISSING {key}")
    return get


def copy_snapshot(get: Getter, out: Path) -> dict:
    """Copy pointer, seal and sealed objects; returns run id, object count and seal mismatches."""
    out.mkdir(parents=True, exist_ok=True)
    pointer = get("snapshot:current")
    run = str(json.loads(pointer).get("run_id", ""))
    if not RUN_ID.fullmatch(run):
        raise ValueError("LIVE_POINTER_RUN_ID_INVALID")
    seal_key = f"snapshot:{run}:v213:snapshot-seal:v1"
    seal = get(seal_key)
    files = {"snapshot:current": pointer, seal_key: seal}
    mismatches = []
    for name, meta in json.loads(seal)["objects"].items():
        # Lazy sealed objects live once under their content address (cloud/src/v213/snapshot-seal.ts).
        key = f"blob:v1:{meta.get('sha256')}" if LAZY_KEY.fullmatch(name) else f"snapshot:{run}:{name}"
        body = get(key)
        files[key] = body
        if hashlib.sha256(body).hexdigest() != meta.get("sha256"):
            mismatches.append(name)
    index = {}
    for number, (key, body) in enumerate(files.items()):
        (out / f"k{number}.txt").write_bytes(body)
        index[key] = f"k{number}.txt"
    (out / "index.json").write_text(json.dumps(index), encoding="utf-8")
    return {"run_id": run, "objects": len(files) - 2, "seal_mismatches": mismatches}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = copy_snapshot(remote_getter(), args.out)
    except (LookupError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "FAIL", "error": str(error)[:120]}))
        return 1
    print(json.dumps({"status": "OK", **result}))
    return 0 if not result["seal_mismatches"] else 1


if __name__ == "__main__":
    sys.exit(main())
