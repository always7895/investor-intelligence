"""Disaster-recovery rollback for the sealed snapshot pointer.

Rolls `snapshot:current` back to a specified prior RUN whose sealed objects were
previously published to the production PUBLIC_CACHE.

Contract (strict fail-closed; the ONLY mutation ever performed is the pointer key):
  1. The target run dir must exist locally AND be tracked in git
     (`git ls-files` must list its pointer.raw.json) — we only roll back to
     committed integrity-proven runs.
  2. The target's committed pointer seal is recomputed-checkable: the 14 object
     keys of the run's objects.json are read back live from KV and verified
     byte-identical (sha256) against the committed body bytes.
  3. If the live pointer already equals the target pointer text -> NO-OP.
  4. Only then is `snapshot:current` written with the target's committed pointer
     bytes (canonical, stripped), followed by a readback verification.

Any failure exits non-zero WITHOUT touching the pointer. Default mode is
`--apply` (trailed flag); a plain invocation is a dry-run that verifies and
reports only. The kv layer is injectable for tests (get/put callables);
the default uses `wrangler kv key ... --namespace-id <PUBLIC_CACHE>` via the
cached session. No credentials are read or printed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAP_DIR = ROOT / "state" / "v213-snapshots"
NS = "96142af40b5d4213862d5483fe3a66da"
POINTER_KEY = "snapshot:current"
NPX = shutil.which("npx") or shutil.which("npx.cmd") or "npx"


class RollbackError(RuntimeError):
    pass


def sha(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def clean(raw: str) -> str:
    body = raw
    while body and body[-1] in "\r\n":
        body = body[:-1]
    return body


# ---------------------------------------------------------------- kv layer
def wrangler_kv_get(key: str) -> str | None:
    p = subprocess.run(
        [NPX, "--yes", "wrangler", "kv", "key", "get", key, "--namespace-id", NS],
        cwd=str(ROOT / "cloud"), capture_output=True, text=True, errors="replace", timeout=300,
    )
    if p.returncode != 0:
        return None
    return clean(p.stdout)


def wrangler_kv_put(key: str, body: str) -> bool:
    # write to a gitignored staging path; wrangler --path needs a file
    stage = ROOT / "data" / "cache" / "rollback-stage.txt"
    stage.parent.mkdir(parents=True, exist_ok=True)
    stage.write_bytes(body.encode("utf-8"))
    p = subprocess.run(
        [NPX, "--yes", "wrangler", "kv", "key", "put", key,
         "--path", str(stage), "--namespace-id", NS],
        cwd=str(ROOT / "cloud"), capture_output=True, text=True, errors="replace", timeout=300,
    )
    return p.returncode == 0


# --------------------------------------------------------------- contract
def load_target(run_id: str) -> dict:
    run_dir = SNAP_DIR / run_id
    obj_file = run_dir / "objects.json"
    ptr_file = run_dir / "pointer.raw.json"
    if not obj_file.is_file() or not ptr_file.is_file():
        raise RollbackError(f"target run dir incomplete: {run_dir}")
    tracked = subprocess.run(
        ["git", "ls-files", "state/v213-snapshots/" + run_id + "/pointer.raw.json"],
        cwd=str(ROOT), capture_output=True, text=True,
    ).stdout.strip()
    if tracked != "state/v213-snapshots/" + run_id + "/pointer.raw.json":
        raise RollbackError(f"target run {run_id} is not git-tracked (refusing uncommitted runs)")
    objects = json.loads(obj_file.read_text(encoding="utf-8"))
    pointer_text = clean(ptr_file.read_text(encoding="utf-8"))
    pointer = json.loads(pointer_text)
    if pointer.get("run_id") != run_id:
        raise RollbackError("pointer run_id mismatch inside target dir")
    if set(pointer) != {"schema_version", "run_id", "transaction_id", "seal_sha256",
                        "public_data_as_of", "promoted_at", "provider_scope",
                        "owner_watchlist_inherited"}:
        raise RollbackError("pointer schema mismatch")
    return {"run_id": run_id, "objects": objects, "pointer_text": pointer_text, "pointer": pointer}


def verify_objects(target: dict, kv_get) -> list[dict]:
    rows = []
    for key, body in target["objects"].items():
        live = kv_get(key)
        ok = live is not None and sha(live) == sha(body)
        rows.append({"key": key, "verified": ok})
        if not ok:
            raise RollbackError(f"object readback mismatch: {key}")
    return rows


def rollback(run_id: str, apply: bool, kv_get=None, kv_put=None) -> dict:
    kv_get = kv_get or wrangler_kv_get
    kv_put = kv_put or wrangler_kv_put
    target = load_target(run_id)
    rows = verify_objects(target, kv_get)
    live_ptr = kv_get(POINTER_KEY)
    if live_ptr == target["pointer_text"]:
        return {"status": "NOOP", "run_id": run_id, "verified_objects": len(rows), "applied": False}
    result = {"status": "PLANNED", "run_id": run_id, "verified_objects": len(rows),
              "seal": target["pointer"]["seal_sha256"], "from_run": None, "to_run": run_id,
              "applied": False}
    if live_ptr:
        try:
            result["from_run"] = json.loads(live_ptr).get("run_id")
        except Exception:
            result["from_run"] = "<unparseable>"
    if not apply:
        result["status"] = "DRY_RUN"
        return result
    if not kv_put(POINTER_KEY, target["pointer_text"]):
        raise RollbackError("pointer put failed — previous pointer untouched")
    if kv_get(POINTER_KEY) != target["pointer_text"]:
        raise RollbackError("pointer readback mismatch — state UNKNOWN, investigate before re-running")
    result["status"] = "ROLLED_BACK"
    result["applied"] = True
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target-run", required=True)
    ap.add_argument("--apply", action="store_true",
                    help="Actually rewrite snapshot:current (default: dry-run verify only)")
    args = ap.parse_args(argv)
    try:
        out = rollback(args.target_run, apply=args.apply)
    except RollbackError as e:
        print(f"ROLLBACK ABORT: {e}", file=sys.stderr)
        return 1
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())