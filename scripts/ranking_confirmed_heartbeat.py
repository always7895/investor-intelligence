"""Reseal confirmed bytes after genuine host NO_CHANGE; never produce ranking/ACK.

Only the activation envelope identity is rebound (its original claimed_at and
payload digests remain evidence). All reports, approvals and lazy blobs stay exact.
The normal replay and sync own admission, all-object readback and pointer-last.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import publish_sealed_snapshot as publisher
import top20_carry_forward as carry


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def stage(snapshot_root: Path, now: datetime) -> dict:
    root = carry.plain_path(snapshot_root)
    try:
        previous = carry.confirmed_snapshot(root)
    except (OSError, ValueError, TypeError, KeyError):
        previous = None
    if previous is None:
        import sync_sealed_snapshot_kv as sync
        previous = sync.reconcile_confirmed_snapshot(root)
    if previous is None:
        raise ValueError("BOOTSTRAP_REQUIRED")
    source = dict(previous["objects"])
    old_pointer = previous["pointer"]
    old_prefix = f"snapshot:{previous['run_id']}:"
    seal = json.loads(source[old_prefix + carry.SEALED_MANIFEST_KEY])
    assembled = datetime.fromisoformat(seal["generated_at"].replace("Z", "+00:00"))
    if now < assembled:
        raise ValueError("CONFIRMED_CLOCK_IN_FUTURE")
    if (now - assembled).total_seconds() < 6 * 3600:
        return carry.retained_snapshot(root)
    # Validate EVERY immutable operand, not only the ranking selected by receipt.
    for name, entry in seal["objects"].items():
        key = old_prefix + name
        if key not in source:
            key = "blob:v1:" + entry["sha256"]
        body = source[key].encode("utf-8")
        if hashlib.sha256(body).hexdigest() != entry["sha256"] or len(body) != entry["utf8_bytes"]:
            raise ValueError("CONFIRMED_OBJECT_MISMATCH")
    instant = now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    run = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid4().hex[:12]
    prefix = f"snapshot:{run}:"
    transaction = uuid4().hex
    objects = {}
    for key, body in source.items():
        if key == old_prefix + carry.SEALED_MANIFEST_KEY:
            continue
        if key.startswith(old_prefix):
            objects[prefix + key[len(old_prefix):]] = body
        elif key.startswith("blob:v1:"):
            objects[key] = body
        else:
            raise ValueError("CONFIRMED_OBJECT_NAMESPACE")
    claim_key = prefix + "v213:activation-claim"
    claim = json.loads(objects[claim_key])
    if claim["run_id"] != previous["run_id"] or claim["transaction_id"] != seal["transaction_id"]:
        raise ValueError("CONFIRMED_CLAIM_BINDING")
    claim.update(run_id=run, transaction_id=transaction)
    objects[claim_key] = encoded(claim)
    seal["objects"]["v213:activation-claim"] = {
        "sha256": hashlib.sha256(objects[claim_key].encode("utf-8")).hexdigest(),
        "utf8_bytes": len(objects[claim_key].encode("utf-8")),
    }
    seal.update(run_id=run, transaction_id=transaction, generated_at=instant)
    seal_text = encoded(seal)
    objects[prefix + carry.SEALED_MANIFEST_KEY] = seal_text
    pointer = {**old_pointer, "run_id": run, "transaction_id": transaction,
               "seal_sha256": hashlib.sha256(seal_text.encode("utf-8")).hexdigest(), "promoted_at": instant}
    pointer_text = encoded(pointer)
    retained = publisher.retained_publication(root, objects, pointer_text, now)
    if retained is not None:
        return retained
    destination = carry.plain_path(root / run)
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "objects.json").write_bytes(encoded(objects).encode("utf-8"))
    (destination / "pointer.raw.json").write_bytes(pointer_text.encode("utf-8"))
    return {"status": "STAGED_CONFIRMED_HEARTBEAT", "run_id": run,
            "source_run_id": previous["run_id"], "public_data_as_of": pointer["public_data_as_of"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = stage(args.snapshot_root, datetime.now(timezone.utc).replace(microsecond=0))
    except (OSError, ValueError, TypeError, KeyError):
        print("CONFIRMED_HEARTBEAT_UNAVAILABLE")
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
