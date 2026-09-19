"""Sync one sealed snapshot run to the production PUBLIC_CACHE namespace.

Strict fail-closed contract (Task #23 PRODUCTION_FRESHNESS_REPAIR):
  1. upload ALL object keys of the run dir's objects.json (plus the 14th
     audited bottleneck key when present);
  2. read every uploaded key back and verify byte-identical sha256;
  3. ONLY after all verifications pass, write `snapshot:current` LAST;
  4. on ANY failure: exit non-zero WITHOUT touching the pointer — the
     previous sealed run keeps serving.

No credentials are read or printed; the wrangler CLI's cached session is
used. The namespace id is the operator-provided PUBLIC_CACHE id.
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
CLOUD_DIR = ROOT / "cloud"
NS = "96142af40b5d4213862d5483fe3a66da"

NPX = shutil.which("npx") or shutil.which("npx.cmd") or "npx"


def _run_cli(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [NPX, "--yes", "wrangler", *args],
        cwd=str(CLOUD_DIR), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
    )


def client_put(key: str, local_path: Path) -> bool:
    rel = os.path.relpath(local_path, str(ROOT)).replace("\\", "/")
    p = _run_cli(["kv", "key", "put", key, "--path", "../" + rel, "--namespace-id", NS])
    return p.returncode == 0


def client_get(key: str) -> str | None:
    p = _run_cli(["kv", "key", "get", key, "--namespace-id", NS])
    if p.returncode != 0:
        return None
    body = p.stdout
    while body and body[-1] in "\r\n":
        body = body[:-1]
    return body


def sha(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True, help="state/v213-snapshots/<run>/")
    args = ap.parse_args()
    run_dir = Path(args.run_dir).resolve()
    objects_file = run_dir / "objects.json"
    pointer_file = run_dir / "pointer.raw.json"
    objects = json.loads(objects_file.read_text(encoding="utf-8"))
    entries = [(k, v) for k, v in sorted(objects.items())]
    staged = run_dir / ".kv-stage"
    staged.mkdir(exist_ok=True)

    # Stage exact bytes (no trailing-newline drift).
    staged_files: dict[str, Path] = {}
    for key, body in entries:
        safe = key.rstrip(":").replace("snapshot:", "").replace(":", "_")[:80]
        fp = staged / (safe + ".bin")
        fp.write_bytes(body.encode("utf-8"))
        staged_files[key] = fp
    ptr_raw = pointer_file.read_text(encoding="utf-8").strip()
    ptr_fp = staged / "__pointer.bin"
    ptr_fp.write_bytes(ptr_raw.encode("utf-8"))

    # 1) objects FIRST (pointer must never lead).
    for key, fp in staged_files.items():
        if not client_put(key, fp):
            print(f"SYNC ABORT (object put failed): {key}", file=sys.stderr)
            return 1
    print(f"OBJECTS_UPLOADED {len(staged_files)}")

    # 2) verify every object by live readback.
    for key, body in entries:
        live = client_get(key)
        if live is None or sha(live) != sha(body):
            print(f"SYNC ABORT (readback mismatch, pointer untouched): {key}", file=sys.stderr)
            return 1

    print(f"READBACK_VERIFIED {len(entries)}")

    # 3) pointer LAST, only after full verification.
    if not client_put("snapshot:current", ptr_fp):
        print("SYNC ABORT (pointer put failed)", file=sys.stderr)
        return 1
    live_ptr = client_get("snapshot:current")
    if live_ptr is None or sha(live_ptr) != sha(ptr_raw):
        print("SYNC ABORT (pointer readback mismatch)", file=sys.stderr)
        return 1
    print(f"POINTER_LAST {json.loads(ptr_raw)['run_id']} seal {json.loads(ptr_raw)['seal_sha256'][:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())