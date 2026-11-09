"""Continue independently due products after genuine protected-host NO_CHANGE.

Reuse confirmed core/ranking custody without renewing report, approval or ACK.
A ranking heartbeat advances only its persistence clock; original core identity
and evidence bytes stay exact. Independently fresh products keep their own clocks.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import publish_sealed_snapshot as publisher
import top20_carry_forward as carry


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def stage(snapshot_root: Path, now: datetime, *, product_paths: dict[str, Path] | None = None) -> dict:
    import sealed_product_policy as products
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
    source = products.parts(previous["objects"], previous["pointer"])
    if now < products.instant(source["manifest"]["generated_at"]):
        raise ValueError("CONFIRMED_CLOCK_IN_FUTURE")
    paths = {"identity": publisher.IDENTITY_SHARDS_PATH, "prices": publisher.PRICE_SHARDS_PATH,
             "market": publisher.MARKET_OBSERVATIONS_PATH}
    if product_paths is not None:
        if not set(product_paths) <= set(paths):
            raise ValueError("PRODUCT_PATH_INVALID")
        paths.update(product_paths)
    fresh = publisher.lazy_identity_bodies(Path(paths["identity"]), now)
    fresh.update(publisher.lazy_price_bodies(Path(paths["prices"]), now))
    fresh.update(publisher.lazy_market_bodies(Path(paths["market"]), now))
    fresh.update(publisher.lazy_options_coverage_body(fresh.get("v213:options:v2"), now))
    selected = products.prepare_publication(root, previous["objects"], encoded(previous["pointer"]), now,
        previous=previous, fresh_products=fresh, confirmed_only=True)
    if "retained" in selected:
        return selected["retained"]
    pointer_text = selected["pointer"]
    pointer = json.loads(pointer_text)
    run = pointer["run_id"]
    detail = products.parts(selected["objects"], pointer)
    report = json.loads(detail["core"]["v213:top20-report:latest"])
    summary = {"run_id": run, "transaction_id": pointer["transaction_id"],
               "core_run_id": detail["core_run_id"], "seal_sha256": pointer["seal_sha256"],
               "public_data_as_of": pointer["public_data_as_of"], "source_run_id": previous["run_id"],
               "top20_state": "INSUFFICIENT" if report.get("status") == "INSUFFICIENT_EVIDENCE" else "CARRIED_FORWARD",
               "ranking_status": selected["ranking_status"],
               "ranking_persisted_at": detail["manifest"]["ranking_persisted_at"]}
    destination = carry.plain_path(root / run)
    summary_path = carry.plain_path(destination / "summary.json")
    summary_bytes = publisher._dumps(summary).encode("utf-8")
    if summary_path.is_file():
        existing_bytes = summary_path.read_bytes()
        existing = json.loads(existing_bytes)
        if not isinstance(existing, dict) or any(existing.get(key) != summary[key] for key in
                ("run_id", "transaction_id", "seal_sha256", "top20_state")):
            raise ValueError("SEALED_RUN_DIR_CONFLICT")
        summary_bytes = existing_bytes
    payloads = {"objects.json": publisher._dumps(selected["objects"]).encode("utf-8"),
                "pointer.raw.json": pointer_text.encode("utf-8"), "summary.json": summary_bytes}
    for name, data in payloads.items():
        path = carry.plain_path(destination / name)
        if path.is_file() and path.read_bytes() != data:
            raise ValueError("SEALED_RUN_DIR_CONFLICT")
    destination.mkdir(parents=True, exist_ok=True)
    for name, data in payloads.items():
        carry.plain_path(destination / name).write_bytes(data)
    return {"status": ("STAGED_CONFIRMED_HEARTBEAT" if selected["ranking_status"] == "PERSISTED"
                       else "STAGED_INDEPENDENT_PRODUCTS"),
            "run_id": run, "source_run_id": previous["run_id"],
            "public_data_as_of": pointer["public_data_as_of"],
            "ranking_status": selected["ranking_status"], "writes_by_product": selected["writes_by_product"]}


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
