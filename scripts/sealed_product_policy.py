"""Independent product publication over one immutable, atomically promoted seal.

A market-only root references the already confirmed eager/core run. It cannot
renew that run's claim, report, approval, data time, or ranking cadence clock.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import ranking_write_policy as writes

SEAL_KEY = "v213:snapshot-seal:v1"
PIPELINE_KEY = "last_successful_pipeline_timestamp"
CORE_PERIOD_SECONDS = 12 * 3600
RANKING_KEYS = frozenset({"v213:bottleneck-top20:v3", "v213:revenue-guidance-binding:v1"})
PERIOD_SECONDS = {"market": 2 * 3600, "prices": 3 * 3600, "identity": 24 * 3600}
MAX_AGE_SECONDS = {"market": 6 * 3600, "prices": 4 * 86400, "identity": 8 * 86400}


def encoded(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def digest(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def instant(raw: str) -> datetime:
    if not isinstance(raw, str):
        raise ValueError("PRODUCT_CLOCK_INVALID")
    value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if value.tzinfo is None or value.utcoffset().total_seconds() != 0:
        raise ValueError("PRODUCT_CLOCK_INVALID")
    return value.astimezone(timezone.utc)


def stamp(now: datetime) -> str:
    return now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def product(logical: str) -> str | None:
    if logical.startswith("v213:identity:v2:"):
        return "identity"
    if logical.startswith("v213:prices:v1:"):
        return "prices"
    if logical in {"v213:quotes:v1", "v213:options:v1", "v213:options:v2", "v213:options-coverage:v1"}:
        return "market"
    return None


def core_keys() -> tuple[str, ...]:
    from publish_sealed_snapshot import OBJECT_KEYS, MACRO_KEY
    return (*OBJECT_KEYS, MACRO_KEY)


def parts(objects: dict[str, str], pointer: dict) -> dict:
    """Resolve every declared immutable member, including a reused core run."""
    import top20_carry_forward as carry
    run = pointer.get("run_id")
    if not isinstance(run, str) or not carry.RUN_ID.fullmatch(run):
        raise ValueError("PRODUCT_RUN_INVALID")
    raw = objects[f"snapshot:{run}:{SEAL_KEY}"]
    if digest(raw) != pointer.get("seal_sha256"):
        raise ValueError("PRODUCT_SEAL_DIGEST")
    manifest = json.loads(raw)
    if manifest.get("run_id") != run or not isinstance(manifest.get("objects"), dict):
        raise ValueError("PRODUCT_SEAL_INVALID")
    reused_core = "core_run_id" in manifest
    if reused_core != ("ranking_persisted_at" in manifest):
        raise ValueError("PRODUCT_CORE_METADATA")
    core_run = manifest.get("core_run_id", run)
    if not isinstance(core_run, str) or not carry.RUN_ID.fullmatch(core_run):
        raise ValueError("PRODUCT_CORE_METADATA")
    generated = instant(manifest["generated_at"])
    eager_keys = core_keys()
    ranking_time = instant(manifest.get("ranking_persisted_at", manifest["generated_at"]))
    if ranking_time > generated:
        raise ValueError("PRODUCT_CLOCK_INVALID")
    clocks = manifest.get("product_persisted_at", {})
    if (not isinstance(clocks, dict) or not set(clocks) <= set(PERIOD_SECONDS)
            or any(instant(value) > generated for value in clocks.values())):
        raise ValueError("PRODUCT_CLOCK_INVALID")
    eager, lazy, physical = {}, {}, {}
    for logical, entry in manifest["objects"].items():
        if not isinstance(entry, dict):
            raise ValueError("PRODUCT_OBJECT_INVALID")
        storage_run = run if reused_core and logical == PIPELINE_KEY else core_run
        key = f"snapshot:{storage_run}:{logical}" if logical in eager_keys else "blob:v1:" + entry["sha256"]
        body = objects[key]
        if digest(body) != entry.get("sha256") or len(body.encode("utf-8")) != entry.get("utf8_bytes"):
            raise ValueError("PRODUCT_OBJECT_DIGEST")
        (eager if logical in eager_keys else lazy)[logical] = body
        physical[key] = logical
    if reused_core:
        expected = set(physical) | {f"snapshot:{run}:{SEAL_KEY}"}
        if set(objects) != expected or set(eager) != set(eager_keys):
            raise ValueError("PRODUCT_OBJECT_NAMESPACE")
        if instant(eager[PIPELINE_KEY]) != generated:
            raise ValueError("PRODUCT_PIPELINE_CLOCK")
    return {"core": eager, "lazy": lazy, "manifest": manifest,
            "pointer": pointer, "core_run_id": core_run, "physical": physical}


def write_plan(objects: dict[str, str], pointer: dict, ledger: dict[str, float],
               now: datetime, attempts: int = 3, reuse_seconds: int = 20 * 86400) -> dict:
    """Actual controlled PUT plan; reused objects still require live readback."""
    eager_keys = core_keys()
    run = pointer["run_id"]
    seal_key = f"snapshot:{run}:{SEAL_KEY}"
    detail = parts(objects, pointer) if seal_key in objects else None
    ranking_root = detail and instant(detail["manifest"].get(
        "ranking_persisted_at", detail["manifest"]["generated_at"])) == instant(detail["manifest"]["generated_at"])
    control_product = "ranking" if not detail or ranking_root else "market"
    reused, assignment = set(), {}
    for key in objects:
        logical = detail["physical"].get(key) if detail else None
        bucket = "market" if logical and product(logical) else "ranking"
        if key == seal_key:
            bucket = control_product
        if logical == PIPELINE_KEY:
            bucket = control_product
        assignment[key] = bucket
        if logical in eager_keys and logical != PIPELINE_KEY and detail and detail["core_run_id"] != run:
            reused.add(key)
        elif key.startswith("blob:v1:") and 0 <= now.timestamp() - ledger.get(key[8:], 0.0) < reuse_seconds:
            reused.add(key)
    assignment["snapshot:current"] = control_product
    counts = {"ranking": 0, "market": 0}
    for key, bucket in assignment.items():
        if key not in reused:
            counts[bucket] += attempts
    return {"counts": counts, "reused": reused, "assignment": assignment}


def _healthy(groups: dict[str, str], now: datetime) -> dict[str, str]:
    result = {}
    identity = {key: body for key, body in groups.items() if product(key) == "identity"}
    identity_times = []
    identity_ok = True
    for body in identity.values():
        try:
            doc = json.loads(body)
            if not isinstance(doc, dict) or "generated_at" not in doc:
                raise ValueError("IDENTITY_CLOCK_UNAVAILABLE")
            identity_times.append(instant(doc["generated_at"]))
        except (ValueError, TypeError, KeyError):
            identity_ok = False
            break
    identity_ok = identity_ok and bool(identity_times) and all(
        -300 <= (now - value).total_seconds() <= MAX_AGE_SECONDS["identity"] for value in identity_times)
    for key, body in groups.items():
        kind = product(key)
        if kind == "identity":
            if identity_ok:
                result[key] = body
        elif kind is not None:
            try:
                value = instant(json.loads(body)["generated_at"])
                if -300 <= (now - value).total_seconds() <= MAX_AGE_SECONDS[kind]:
                    result[key] = body
            except (ValueError, KeyError, TypeError):
                pass
    return result


def choose_products(old: dict[str, str], fresh: dict[str, str], clocks: dict,
                    now: datetime, fallback_clock: str) -> tuple[dict[str, str], dict]:
    """Own publication clocks; expired bytes are removed, never restamped."""
    healthy_old, healthy_fresh = _healthy(old, now), _healthy(fresh, now)
    selected, selected_clocks = {}, dict(clocks)
    for kind, period in PERIOD_SECONDS.items():
        prior = {key: value for key, value in healthy_old.items() if product(key) == kind}
        newer = {key: value for key, value in healthy_fresh.items() if product(key) == kind}
        last = clocks.get(kind, fallback_clock if prior else None)
        due = last is None or (now - instant(last)).total_seconds() >= period
        if last is not None and now < instant(last):
            raise ValueError("PRODUCT_CLOCK_IN_FUTURE")
        candidate = {**prior, **newer} if due else prior
        # Identity batches are one directory generation, never mixed old/new shards.
        if kind == "identity" and due and newer:
            candidate = newer
        if kind == "market" and due and candidate != prior:
            from publish_sealed_snapshot import lazy_options_coverage_body
            candidate.pop("v213:options-coverage:v1", None)
            candidate.update(lazy_options_coverage_body(candidate.get("v213:options:v2"), now))
        if candidate != prior:
            selected_clocks[kind] = stamp(now)
        selected.update(candidate)
    return selected, selected_clocks


def _assemble(base: dict, ranking_lazy: dict[str, str], products: dict[str, str],
              clocks: dict, now: datetime, *, new_core: bool, ranking_clock: str) -> tuple[dict[str, str], str]:
    old = base["manifest"]
    lazy = {**ranking_lazy, **products}
    core_run, transaction, eager = base["core_run_id"], old["transaction_id"], dict(base["core"])
    if new_core:
        run = old["run_id"]
    else:
        seed = encoded({"core": core_run, "at": stamp(now), "ranking_at": ranking_clock,
                        "lazy": {key: digest(body) for key, body in sorted(lazy.items())}})
        run = now.strftime("%Y%m%dT%H%M%SZ-") + digest(seed)[:12]
    # Actual public-seal liveness, NOT an activation payload or evidence date.
    eager[PIPELINE_KEY] = stamp(now)
    entries = {key: {"sha256": digest(body), "utf8_bytes": len(body.encode("utf-8"))}
               for key, body in [*eager.items(), *lazy.items()]}
    manifest = {**old, "run_id": run, "transaction_id": transaction, "generated_at": stamp(now),
                "core_run_id": core_run, "ranking_persisted_at": ranking_clock,
                "product_persisted_at": clocks, "objects": entries}
    seal_text = encoded(manifest)
    objects = {f"snapshot:{run if key == PIPELINE_KEY else core_run}:{key}": body for key, body in eager.items()}
    objects.update({"blob:v1:" + digest(body): body for body in lazy.values()})
    objects[f"snapshot:{run}:{SEAL_KEY}"] = seal_text
    pointer = {**base["pointer"], "run_id": run, "transaction_id": transaction,
               "promoted_at": stamp(now), "seal_sha256": digest(seal_text)}
    return objects, encoded(pointer)


def prepare_publication(snapshot_root: Path, objects: dict[str, str], pointer_text: str,
                        now: datetime, *, previous: dict | None = None,
                        fresh_products: dict[str, str] | None = None,
                        confirmed_only: bool = False, reconcile: bool = False,
                        allow_confirmed_heartbeat: bool = True) -> dict:
    """Select rank/products; remote discovery is explicit, never an implicit credential read."""
    import top20_carry_forward as carry
    import sync_sealed_snapshot_kv as sync
    root = carry.plain_path(snapshot_root)
    if previous is None:
        try:
            previous = carry.confirmed_snapshot(root)
        except (OSError, ValueError, KeyError, TypeError):
            previous = None
        if previous is None and reconcile:
            previous = sync.reconcile_confirmed_snapshot(root)
    pointer = json.loads(pointer_text)
    candidate = parts(objects, pointer)
    candidate_ranking = carry.ranking_from_objects(objects, pointer)
    if previous is None:
        if confirmed_only or (candidate_ranking is None and reconcile):
            raise ValueError("BOOTSTRAP_REQUIRED")
        if candidate_ranking is None:
            return {"objects": objects, "pointer": pointer_text}
    old = parts(previous["objects"], previous["pointer"]) if previous else None
    old_ranking = previous["ranking"] if previous else None
    due = ("CANDIDATE_UNAVAILABLE" if candidate_ranking is None else
           writes.publication_due(old_ranking, candidate_ranking, now))
    ranking_due = due not in {"NO_CHANGE", "CANDIDATE_UNAVAILABLE"}
    if confirmed_only:
        ranking_due = (allow_confirmed_heartbeat and
                       (now - instant(old["manifest"].get("ranking_persisted_at", old["manifest"]["generated_at"]))).total_seconds() >= writes.HEARTBEAT_SECONDS)
    old_lazy = old["lazy"] if old else {}
    products, clocks = choose_products(old_lazy,
        fresh_products if fresh_products is not None else candidate["lazy"],
        old["manifest"].get("product_persisted_at", {}) if old else {}, now,
        old["manifest"]["generated_at"] if old else stamp(now))
    ledger = sync.load_ledger()
    budget = writes.PublicationWriteBudget(sync.LEDGER.with_name("ranking-kv-write-budget.json"))
    reason = "CANDIDATE_UNAVAILABLE" if candidate_ranking is None else "NO_CHANGE"
    choices = ((ranking_due, True), (False, True), (ranking_due, False)) if ranking_due else ((False, True),)
    for allow_ranking, allow_products in choices:
        if old is None and not allow_ranking:
            continue
        base = candidate if allow_ranking and not confirmed_only else old
        # Twelve hours is a refresh target when NEW evidence exists, not an
        # authority renewal or a veto on independently fresh market products.
        refresh_core = allow_ranking and not confirmed_only and (old is None or (
            candidate["core_run_id"] != old["core_run_id"] and (now - datetime.strptime(
                old["core_run_id"][:16], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)).total_seconds() >= CORE_PERIOD_SECONDS))
        ranking_base = base
        base = base if refresh_core else old
        if base is None:
            continue
        chosen_products = products if allow_products else _healthy(old_lazy, now)
        chosen_products = {key: value for key, value in chosen_products.items() if product(key)}
        chosen_clocks = (clocks if allow_products else
                         dict(old["manifest"].get("product_persisted_at", {})) if old else {})
        ranking_lazy = {key: value for key, value in ranking_base["lazy"].items() if key in RANKING_KEYS}
        old_products = {key: value for key, value in old_lazy.items() if product(key)}
        if not allow_ranking and chosen_products == old_products:
            continue
        ranking_clock = (stamp(now) if allow_ranking else
                         old["manifest"].get("ranking_persisted_at", old["manifest"]["generated_at"]))
        selected, selected_pointer = _assemble(base, ranking_lazy, chosen_products, chosen_clocks, now,
            new_core=refresh_core, ranking_clock=ranking_clock)
        plan = write_plan(selected, json.loads(selected_pointer), ledger, now, sync.ATTEMPTS, sync.BLOB_REUSE_SECONDS)
        if old is None or budget.can_reserve(plan["counts"], now):
            return {"objects": selected, "pointer": selected_pointer,
                    "ranking_status": "PERSISTED" if allow_ranking else "REUSED",
                    "ranking_reason": due if allow_ranking or not ranking_due else "WRITE_BUDGET",
                    "writes_by_product": plan["counts"]}
        reason = "WRITE_BUDGET"
    if previous is None:
        raise ValueError("BOOTSTRAP_REQUIRED")
    return {"retained": carry.retained_snapshot(root, reason)}
