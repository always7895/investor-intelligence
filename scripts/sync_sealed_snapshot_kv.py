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
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLOUD_DIR = ROOT / "cloud"
NS = "96142af40b5d4213862d5483fe3a66da"
# Wrangler 4 KV commands default to the local Miniflare store; Production is always addressed explicitly
# (every hourly sync from 2026-09-16 to 2026-09-25 wrote only the local store).
REMOTE = "--remote"

NPX = shutil.which("npx") or shutil.which("npx.cmd") or "npx"
# A transient Cloudflare API or network error failed the 2026-09-25 16:56Z hourly put; an immediate manual retry
# of the same run passed. Each KV call gets bounded retries; the pointer still moves only after full readback.
ATTEMPTS = 3
RETRY_SECONDS = 5.0
LAST_ERROR: list[str] = []
BLOB_PREFIX = "blob:v1:"
# KV growth is bounded: per-run keys expire after 14 days (only the pointer's run is ever read), content-addressed
# blobs after 30 days. A local ledger remembers blobs this machine stored; one stored in the last 20 days is reused
# without a KV read, an older or unknown one is (re)put, which also renews its expiry while it is still referenced.
RUN_KEY_TTL_SECONDS = 14 * 86400
BLOB_TTL_SECONDS = 30 * 86400
BLOB_REUSE_SECONDS = 20 * 86400
LEDGER = ROOT / "data" / "cache" / "kv-blob-ledger.json"


def _run_cli(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [NPX, "--yes", "wrangler", *args],
        cwd=str(CLOUD_DIR), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
    )


def _error_summary(p: subprocess.CompletedProcess) -> str:
    """Last non-empty stderr line, truncated; ids and emails masked (logs never carry account details)."""
    lines = [line.strip() for line in (p.stderr or "").splitlines() if line.strip()]
    text = lines[-1] if lines else f"exit {p.returncode}"
    text = re.sub(r"[0-9a-f]{32}", "<id>", text)
    return re.sub(r"[^\s@]+@[^\s@]+", "<email>", text)[:200]


def _run_with_retry(args: list[str]) -> subprocess.CompletedProcess:
    for attempt in range(1, ATTEMPTS + 1):
        p = _run_cli(args)
        if p.returncode == 0:
            return p
        LAST_ERROR[:] = [_error_summary(p)]
        if attempt < ATTEMPTS:
            time.sleep(RETRY_SECONDS * attempt)
    return p


def client_put(key: str, local_path: Path, ttl: int | None = None) -> bool:
    rel = os.path.relpath(local_path, str(ROOT)).replace("\\", "/")
    extra = ["--ttl", str(ttl)] if ttl else []
    p = _run_with_retry(["kv", "key", "put", key, "--path", "../" + rel, "--namespace-id", NS, REMOTE, *extra])
    return p.returncode == 0


def load_ledger(path: Path | None = None) -> dict[str, float]:
    path = path or LEDGER
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return {str(k): float(v) for k, v in value.items()} if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def save_ledger(ledger: dict[str, float], path: Path | None = None) -> None:
    path = path or LEDGER
    horizon = time.time() - BLOB_TTL_SECONDS
    kept = {k: v for k, v in ledger.items() if v >= horizon}
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(kept), encoding="utf-8")
    temp.replace(path)


def client_get(key: str) -> str | None:
    p = _run_with_retry(["kv", "key", "get", key, "--namespace-id", NS, REMOTE])
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

    # 1) objects FIRST (pointer must never lead). Content-addressed lazy blobs (blob:v1:<sha256>) are immutable:
    # one this machine stored recently (ledger) is reused without a KV call; others are put with an expiry.
    ledger = load_ledger()
    now = time.time()
    reused: set[str] = set()
    for key, fp in staged_files.items():
        blob = key.startswith(BLOB_PREFIX)
        if blob and now - ledger.get(key[len(BLOB_PREFIX):], 0.0) < BLOB_REUSE_SECONDS:
            reused.add(key)
            continue
        if not client_put(key, fp, BLOB_TTL_SECONDS if blob else RUN_KEY_TTL_SECONDS):
            print(f"SYNC ABORT (object put failed after {ATTEMPTS} attempts): {key} {LAST_ERROR[:1]}", file=sys.stderr)
            return 1
    print(f"OBJECTS_UPLOADED {len(staged_files) - len(reused)}" + (f" BLOBS_REUSED {len(reused)}" if reused else ""))

    # 2) verify every object by live readback (reused blobs were verified just above).
    for key, body in entries:
        if key in reused:
            continue
        live = client_get(key)
        if live is None or sha(live) != sha(body):
            print(f"SYNC ABORT (readback mismatch, pointer untouched): {key}", file=sys.stderr)
            return 1

    print(f"READBACK_VERIFIED {len(entries)}")

    # 3) pointer LAST, only after full verification.
    if not client_put("snapshot:current", ptr_fp):
        print(f"SYNC ABORT (pointer put failed after {ATTEMPTS} attempts) {LAST_ERROR[:1]}", file=sys.stderr)
        return 1
    live_ptr = client_get("snapshot:current")
    if live_ptr is None or sha(live_ptr) != sha(ptr_raw):
        print("SYNC ABORT (pointer readback mismatch)", file=sys.stderr)
        return 1
    print(f"POINTER_LAST {json.loads(ptr_raw)['run_id']} seal {json.loads(ptr_raw)['seal_sha256'][:12]}")
    for key in staged_files:
        if key.startswith(BLOB_PREFIX) and key not in reused:
            ledger[key[len(BLOB_PREFIX):]] = now
    save_ledger(ledger)
    shutil.rmtree(staged, ignore_errors=True)  # the staged copies are only needed until the pointer moved
    return 0


if __name__ == "__main__":
    sys.exit(main())