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
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
NS = "96142af40b5d4213862d5483fe3a66da"
RUN_ID = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{12}$")
Getter = Callable[[str], bytes]


def remote_getter() -> Getter:
    npx = shutil.which("npx") or shutil.which("npx.cmd") or "npx"

    def get(key: str) -> bytes:
        done = subprocess.run([npx, "--yes", "wrangler", "kv", "key", "get", key, "--namespace-id", NS, "--remote"],
                              cwd=str(ROOT / "cloud"), capture_output=True, timeout=300)
        if done.returncode != 0 or not done.stdout:
            raise LookupError(f"LIVE_KEY_MISSING {key}")
        return done.stdout
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
        body = get(f"snapshot:{run}:{name}")
        files[f"snapshot:{run}:{name}"] = body
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
