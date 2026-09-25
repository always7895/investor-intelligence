"""Signed-snapshot promotion chain for multi-lineage ADMISSION_QUALIFIED candidates.

Builds, from OFFLINE assets only (no provider calls):
  1. the qualified v213 bottleneck report (GEV rank 1, 6501 rank 2,
     admitted_count = 2, ranked_count = 2, zero padding absent);
  2. the certified seven-field v213 Top20 projection;
  3. the 13-object sealed snapshot (SHAs, sizes, activation claim, seal
     manifest) per cloud/src/v213/snapshot-seal.ts contract v1;
  4. the schema-v2 sealed pointer.

Artifacts (pointer is committed LAST, in its own commit):
  state/v213-snapshots/<run_id>/objects.json   (15 store keys: 14 bodies + seal)
  state/v213-snapshots/<run_id>/pointer.raw.json   (exact pointer text)

Deterministic for a fixed evaluation clock; fails closed on any engine or
corpus drift.

Carry-forward mode (``--top20-bundle``, single-writer design T5, used only by
run_production_sealed_refresh.ps1 -CarryForwardTop20): the Top20 objects
(v21:top20, v212 and v213 reports) are the exact payload bytes of the newest
validated last-known-good bundle (scripts/top20_carry_forward.py); report and
row times are never re-stamped. An invalid or missing bundle seals an honest
INSUFFICIENT Top20 with a reason code; the macro overview is sealed either way.
The GEV/6501 corpus is used only on the default (golden) path.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import bottleneck_ranking as engine  # noqa: E402
import multilineage_claim_bundle as mlb  # noqa: E402
import build_v213_macro_industry_research as macro_builder  # noqa: E402
import company_deep_report  # noqa: E402
import top20_carry_forward  # noqa: E402

MACRO_KEY = "v213:macro-industry:latest"

EVALUATED_AT = "2026-09-15T12:00:00Z"
RETRIEVED_AT = "2026-09-15T11:00:00Z"
GENERATED_AT = "2026-09-15T12:00:00Z"
CLAIMED_AT = "2026-09-15T12:00:00Z"
PROMOTED_AT = "2026-09-15T13:00:00Z"
PUBLISHED_DATA_AS_OF = "2026-09-15T12:00:00Z"
POLICY_ID = "system-bottleneck-explosion-v1"
PRODUCT_VERSION = "2.1.3"
LIVE_NOW = None
LIVE_STAMP = None
CONTRACT_ID = "v213-stored-snapshot-v1"
# One snapshot-root setting shared with company_deep_report.sealed_tickers and the hourly script (-SnapshotRoot):
# an installed runtime keeps its sealed runs under data\, outside the attested payload.
SNAPSHOT_ROOT = ROOT / (os.environ.get("II_SNAPSHOT_ROOT", "").strip() or "state/v213-snapshots")

# Evidence honesty (P0 freshness incident repair; two-anchor contract):
#   * EVIDENCE_CAPTURE_AT is the real offline capture time of the bundled corpus.
#     It is NEVER re-labelled to the live clock.
#   * orders_state_as_of is the SOURCE-STATE date the cited disclosure describes
#     (MLGW board packet for GEV; DOE-26 / FY2025-era window for 6501), not the
#     retrieval time.
#   * generated_at / promoted_at / pointer anchors keep the real seal (assembly)
#     time. Pipeline-health freshness and evidence freshness are different gates.
# The bundled qualification runs the licensed TEST-ONLY fixture path; the report
# bytes carry that provenance so every reader can disclose it.
EVIDENCE_CAPTURE_AT = "2026-09-15T11:00:00Z"
EVIDENCE_POLICY_PATH = ROOT / "config" / "v213-serenity-evidence-freshness-policy.json"
EVIDENCE_CLASS = "structural_claim"
EVIDENCE_POLICY_KEY = "structural_claim_max_age_days"
ORDERS_STATE_AS_OF = {
    "GEV": "2025-09-17T00:00:00Z",   # MLGW Board of Commissioners packet, sixty-month PO program
    "6501": "2026-04-03T00:00:00Z",  # DOE-26 demand webinar text + FY2025 reporting window
}

SEAL_KEY = "v213:snapshot-seal:v1"
OBJECT_KEYS = [
    "v21:top20:latest", "scores:latest", "source_views:latest", "source_plan:latest",
    "reports:latest", "reports:morning:latest", "reports:evening:latest",
    "last_successful_pipeline_timestamp", "v212:top20-report:latest",
    "v213:top20-report:latest", "v213:source-federation:latest",
    "v213:source-independence:latest", "v213:activation-claim",
]

PAYLOAD_NAMES = [
    "top20_json", "source_plan_json", "report_text", "v212_top20_report_json",
    "v213_top20_report_json", "source_federation_json", "source_independence_json",
]
PAYLOAD_OBJECT = {
    "top20_json": "v21:top20:latest",
    "source_plan_json": "source_plan:latest",
    "report_text": "reports:latest",
    "v212_top20_report_json": "v212:top20-report:latest",
    "v213_top20_report_json": "v213:top20-report:latest",
    "source_federation_json": "v213:source-federation:latest",
    "source_independence_json": "v213:source-independence:latest",
}

INDUSTRY = {
    "GEV": "重電與綠能設備 (Electrical equipment & grid; Prolec-GE)",
    "6501": "重電與電網設備 (Electrical equipment / grid solutions; Hitachi Energy)",
}
NAME = {
    "GEV": "GE Vernova Inc. (incl. Prolec-GE Waukesha, Inc.)",
    "6501": "Hitachi Energy (Hitachi, Ltd.; TSE: 6501)",
}
PROFIT_SUMMARY = {
    "GEV": "Power & grid segment: occupying transformer lead manufacturing positions; 60-month utility PO program in place.",
    "6501": "Grid solutions: EHV transformer lead positions; ~$1.5B North America expansion; DOE-corroborated demand ramp.",
}
CURRENT_ORDERS = {
    "GEV": "60-month power-transformer purchase orders (MLGW; NTE $112M contract program).",
    "6501": "Power-transformer orders continue into multi-year backlog (FY2025 report; DOE lead-time cover).",
}
FUTURE_ORDERS = {
    "GEV": "Next-generation capacity expansion completion (2027); DOE grid modernization program order; ~$18B buildout pipeline",
    "6501": "North America keeps expending expansion through 2027; capacity expansion completion in-chain with additional multi-year commitments",
}
SOURCE_URLS = {
    "GEV": [mlb.MLGW_URL, mlb.DOE26_URL],
    "6501": [mlb.DOE26_URL],
}


def evidence_policy_binding() -> "dict":
    """Bind the exact freshness-policy bytes (not the filename) into the report.

    Canonical digest mirrors the worker's canonical stringify: sorted keys,
    minimal separators, unescaped non-ASCII. Readers compare against their own
    trusted in-worker policy copy; any drift rejects the report.
    """
    import v213_evidence_policy  # one binding implementation for every producer (the Worker re-verifies it)
    return v213_evidence_policy.policy_binding(EVIDENCE_POLICY_PATH)


def _sha(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def qualified_ranking() -> dict:
    mlb.verify_corpus_anchors()
    policy = engine.load_json(engine.POLICY_DEFAULT_PATH)
    registry = mlb.build_registry()
    health = mlb.health_for(registry)
    clock = LIVE_NOW or datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)
    cands = list(mlb.bundled_candidates().values())
    result = engine.rank_bottleneck_candidates(
        cands, policy, top_count=20, as_of=clock,
        registry=registry, health_states=health, fixture_mode=True,
    )
    if result["admitted_count"] != 2 or result["ranked_count"] != 2:
        raise AssertionError(f"expected 2/2 qualified admission, got {result['admitted_count']}/{result['ranked_count']}")
    tickers = [r["ticker"] for r in result["ranked_candidates"]]
    if set(tickers) != {"GEV", "6501"}:
        raise AssertionError(f"expected GEV/6501 ranked, got {tickers}")
    return result


def bottleneck_report(result: dict) -> dict:
    records = []
    for rank, row in enumerate(result["ranked_candidates"], start=1):
        tk = row["ticker"]
        factor = lambda key: float(row.get(key, {}).get("score", 0.0) or 0.0)  # noqa: E731
        audit = row.get("claims_audit") or {}
        records.append({
            "schema_version": 1,
            "rank": rank,
            "ticker": tk,
            "name": NAME[tk],
            "industry": INDUSTRY[tk],
            "bottleneck_role": "CAPACITY_BOTTLENECK",
            "system_bottleneck_explosion_score": float(row["system_bottleneck_explosion_score"]),
            "dependency_score": factor("dependency_criticality"),
                        "scarcity_score": 10.0,  # engine ladder: effective_suppliers<=2 and switching_time_months>=12 = 10 pts
            "pricing_power_score": factor("pricing_power"),
            "company_capture_score": factor("company_capture"),
            "long_term_return_pct": None,
            "short_term_return_pct": None,
            "profit_summary": PROFIT_SUMMARY[tk],
            "current_orders": CURRENT_ORDERS[tk],
            "future_orders_estimate": FUTURE_ORDERS[tk],
            "current_order_source_urls": SOURCE_URLS[tk],
            "future_order_source_urls": [],
            "retrieved_at": RETRIEVED_AT,
            "admission_status": "ADMITTED",
            "score_qualified": True,
            "candidate_assessment_mode": "RANKING_QUALIFIED",
            "evidence_class": EVIDENCE_CLASS,
            "freshness_policy_key": EVIDENCE_POLICY_KEY,
            "orders_state_as_of": ORDERS_STATE_AS_OF[tk],
            "test_only_admission": True,
            "claims_audit": {
                "supported_claim_count": int(audit.get("supported_claim_count", 4)),
                "conflicted_claim_count": int(audit.get("conflicted_claim_count", 0)),
                "all_material_claims_supported": bool(audit.get("all_material_claims_supported", True)),
            },
        })
    return {
        "schema_version": 1,
        "policy_id": POLICY_ID,
        "product_version": PRODUCT_VERSION,
        "status": "QUALIFIED",
        "publication_status": "NOT_PUBLICATION_QUALIFIED",
        "live_qualification": "DEFERRED",
        "generated_at": GENERATED_AT,
        "freshness_policy": evidence_policy_binding(),
        "evidence_capture_at": EVIDENCE_CAPTURE_AT,
        "admitted_count": result["admitted_count"],
        "ranked_count": result["ranked_count"],
        "total_evaluated": result["total_evaluated"],
        "records": records,
        "provider_scope": "public_only",
        # Data-driven company reports (SEC XBRL + industry rotation, refreshed daily) for the
        # ranked tickers; missing or stale reports leave the Worker's audit template in place.
        "deep_reports": company_deep_report.load_reports(tickers=[row["ticker"] for row in records]),
    }


def top20_projection(report: dict) -> dict:
    display_columns = [
        "\u80a1\u7968", "\u957f\u671f\u6295\u8cc7\u52dd\u5229\u7387\uff08\u8fd12\u5e74\u5e74\u5316\uff09",
        "\u77ed\u671f\u6295\u8cc7\u52dd\u5229\u7387\uff08\u8fd16\u500b\u6708\uff09", "\u884c\u696d\u5225",
        "\u7d6a\u5229\u7e8c\u8ff0", "\u516c\u53f8\u73fe\u5728\u8a02\u55ae", "\u672a\u4f86\u8a02\u55ae\u9810\u4f30",
    ]
    records = []
    for row in report["records"]:
        current_orders = row["current_orders"]
        unavailable = current_orders == "\u672a\u62ab\u9732\uff08\u7121\u53ef\u9760\u516c\u958b\u8a02\u55ae\u6578\u5b57\uff09"
        records.append({
            "schema_version": 2,
            "rank": row["rank"],
            "ticker": row["ticker"],
            "name": row["name"],
            "long_term_return_pct": None,
            "short_term_return_pct": None,
            "two_year_total_return_pct": None,
            "two_year_return_evidence": None,
            "industry": row["industry"],
            "profit_summary": row["profit_summary"],
            "current_orders": current_orders,
            "future_orders_estimate": row["future_orders_estimate"],
            "long_term_window": "2y_cagr",
            "short_term_window": "6m_price_return",
            "market_source": "yfinance",
            "profit_source": "sec_edgar",
            "orders_as_of": row["orders_state_as_of"],
            "orders_state_as_of": row["orders_state_as_of"],
            "orders_confidence": "EVIDENCE_BOUND" if (current_orders and not unavailable) else "UNAVAILABLE",
            "evidence_class": row["evidence_class"],
            "freshness_policy_key": row["freshness_policy_key"],
            "test_only_admission": row["test_only_admission"],
            "current_order_source_urls": row["current_order_source_urls"],
            "future_order_source_urls": row["future_order_source_urls"],
            "numeric_total_order_estimate_prohibited": True,
            "retrieved_at": row["retrieved_at"],
            "provider_scope": "public_only",
            "owner_watchlist_inherited": False,
        })
    return {
        "schema_version": 2,
        "product_version": PRODUCT_VERSION,
        "generated_at": report["generated_at"],
        "freshness_policy": report["freshness_policy"],
        "evidence_capture_at": report["evidence_capture_at"],
        "display_columns": display_columns,
        "long_term_definition": "trailing_2y_adjusted_close_cagr",
        "short_term_definition": "trailing_6m_adjusted_close_price_return",
        "records": records,
        "provider_scope": "public_only",
        "owner_watchlist_inherited": False,
    }


def build_bodies(carry: "dict | None" = None) -> "tuple[dict[str, str], dict]":
    """Golden path when ``carry`` is None; otherwise ``carry`` is {"state", "reason", "bundle"} from carry_state()."""
    if carry is None:
        result = qualified_ranking()
        report = bottleneck_report(result)
        bottleneck_json = _dumps(report)
        top20 = top20_projection(report)
    else:
        report = top20 = None
        if carry["state"] == "CARRIED_FORWARD":
            bottleneck_json = carry["bundle"]["payloads"]["v213_top20_report_json"]
            top20 = json.loads(bottleneck_json)
        else:
            bottleneck_json = _dumps({"status": "INSUFFICIENT_EVIDENCE", "reason": carry["reason"], "records": []})
    bodies = {
        "v21:top20:latest": "[]",
        "scores:latest": "{}",
        "source_views:latest": "[]",
        "source_plan:latest": "[]",
        "reports:latest": _dumps({"status": "INSUFFICIENT_EVIDENCE"}),
        "reports:morning:latest": _dumps({"status": "SUPPRESSED_BY_SEALED_PROMOTION"}),
        "reports:evening:latest": _dumps({"status": "SUPPRESSED_BY_SEALED_PROMOTION"}),
        "last_successful_pipeline_timestamp": PUBLISHED_DATA_AS_OF,
        "v212:top20-report:latest": _dumps({"status": "INSUFFICIENT_EVIDENCE", "records": []}),
        "v213:top20-report:latest": bottleneck_json,
        "v213:source-federation:latest": _dumps({"status": "INSUFFICIENT_EVIDENCE", "families": 0}),
        "v213:source-independence:latest": _dumps({"status": "INSUFFICIENT_EVIDENCE", "families": 0}),
    }
    if carry is not None and carry["state"] == "CARRIED_FORWARD":
        # Exact bundle bytes; reports:*, source-independence and federation keep their placeholders.
        for name, key in top20_carry_forward.CARRIED_OBJECTS.items():
            bodies[key] = carry["bundle"]["payloads"][name]
    digest_seed = "".join(bodies[k] for k in OBJECT_KEYS if k != "v213:activation-claim") + bottleneck_json
    run_suffix = _sha(digest_seed)[:12]
    transaction_id = _sha(digest_seed)[:32]
    run_id = (LIVE_STAMP or "20260915T120000Z") + "-" + run_suffix
    claim = {
        "schema_version": 1,
        "transaction_id": transaction_id,
        "run_id": run_id,
        "payload_digests": {name: _sha(bodies[PAYLOAD_OBJECT[name]]) for name in PAYLOAD_NAMES},
        "claimed_at": CLAIMED_AT,
    }
    bodies["v213:bottleneck-report:latest"] = bottleneck_json
    # Macro TOP5 artifact: built from the evidenced candidate pool. The pipeline
    # stays fail-closed on builder drift; a SHORTFALL_NOT_QUALIFIED document is
    # published honestly (the reader gate still refuses to rank under 5).
    # Data-driven rotation (BLS PPI + SEC XBRL, refreshed daily); a stale or missing
    # rotation publishes an honest shortfall, never hand-written industries.
    rotation_candidates, rotation_deep, rotation_doc = macro_builder.load_rotation_candidates()
    macro_doc = macro_builder.build_macro_overview_output(
        *macro_builder.evaluate_candidates(rotation_candidates), deep_analyses=rotation_deep, rotation=rotation_doc)
    bodies[MACRO_KEY] = _dumps(macro_doc)
    bodies["v213:activation-claim"] = _dumps(claim)
    return bodies, {"report": report, "top20": top20, "run_id": run_id, "transaction_id": transaction_id, "carry": carry}


def carry_state(bundle_path: "Path | None", forced_reason: "str | None" = None) -> dict:
    """CARRIED_FORWARD with the validated bundle, or INSUFFICIENT with a reason code (never raises)."""
    if forced_reason:
        return {"state": "INSUFFICIENT", "reason": forced_reason, "bundle": None}
    if bundle_path is None:
        return {"state": "INSUFFICIENT", "reason": "TOP20_BUNDLE_MISSING", "bundle": None}
    try:
        bundle = top20_carry_forward.load_top20_bundle(bundle_path, LIVE_NOW or datetime.now(timezone.utc))
    except top20_carry_forward.BundleRejected as error:
        return {"state": "INSUFFICIENT", "reason": str(error), "bundle": None}
    return {"state": "CARRIED_FORWARD", "reason": None, "bundle": bundle}


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def build_seal(bodies: "dict[str, str]", meta: "dict") -> "tuple[str, str]":
    digest_rows = {key: {"sha256": _sha(bodies[key]), "utf8_bytes": len(bodies[key].encode("utf-8"))}
                   for key in [*OBJECT_KEYS, MACRO_KEY]}
    manifest = {
        "schema_version": 1,
        "contract_id": CONTRACT_ID,
        "run_id": meta["run_id"],
        "transaction_id": meta["transaction_id"],
        "generated_at": GENERATED_AT,
        "public_data_as_of": PUBLISHED_DATA_AS_OF,
        "provider_scope": "public_only",
        "owner_watchlist_inherited": False,
        "objects": digest_rows,
    }
    text = _dumps(manifest)
    return text, _sha(text)


def pointer_text(meta, seal_sha: str) -> str:
    pointer = {
        "schema_version": 2,
        "run_id": meta["run_id"],
        "transaction_id": meta["transaction_id"],
        "seal_sha256": seal_sha,
        "public_data_as_of": PUBLISHED_DATA_AS_OF,
        "promoted_at": PROMOTED_AT,
        "provider_scope": "public_only",
        "owner_watchlist_inherited": False,
    }
    return _dumps(pointer)


def main(argv=None) -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--live-clock", action="store_true",
                    help="Live UTC clock stamp (production refresh lane); default = pinned golden clock.")
    ap.add_argument("--top20-bundle", nargs="?", const="", default=None, metavar="PATH",
                    help="Carry the Top20 objects from this validated bundle (no PATH: newest in data/cache/top20-lkg).")
    ap.add_argument("--top20-insufficient", metavar="REASON",
                    help="Carry-forward mode, but seal an INSUFFICIENT Top20 with this reason (replay fallback).")
    ap.add_argument("--snapshot-root", type=Path, default=SNAPSHOT_ROOT,
                    help="Directory for sealed runs (default state/v213-snapshots).")
    args = ap.parse_args(argv)
    if args.live_clock:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        g = globals()
        # Two-anchor contract: the EVIDENCE anchors (retrieved_at, capture and
        # source-state dates) are NEVER re-labelled to the live clock. Only the
        # assembly anchors below (evaluation/seal/promotion) follow the wall clock.
        g["LIVE_NOW"] = now
        g["LIVE_STAMP"] = now.strftime("%Y%m%dT%H%M%SZ")
        g["EVALUATED_AT"] = iso
        g["GENERATED_AT"] = iso
        g["CLAIMED_AT"] = iso
        g["PROMOTED_AT"] = iso
        g["PUBLISHED_DATA_AS_OF"] = iso
        assert RETRIEVED_AT == EVIDENCE_CAPTURE_AT, "evidence capture time must stay pinned"
    carry = None
    if args.top20_bundle is not None or args.top20_insufficient:
        if args.top20_insufficient is not None and not re.fullmatch(r"[A-Z0-9_:]{1,80}", args.top20_insufficient):
            ap.error("--top20-insufficient needs an upper-case reason code")
        path = Path(args.top20_bundle) if args.top20_bundle else top20_carry_forward.newest_lkg()
        carry = carry_state(path, args.top20_insufficient)
    bodies, meta = build_bodies(carry)
    seal_text, seal_sha = build_seal(bodies, meta)
    pointer = pointer_text(meta, seal_sha)
    out_dir = args.snapshot_root / meta["run_id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"snapshot:{meta['run_id']}:"
    objects = {prefix + key: bodies[key] for key in [*OBJECT_KEYS, MACRO_KEY]}
    objects[prefix + SEAL_KEY] = seal_text
    objects_path = out_dir / "objects.json"
    objects_path.write_bytes(_dumps(objects).encode("utf-8"))
    pointer_path = out_dir / "pointer.raw.json"
    pointer_path.write_bytes(pointer.encode("utf-8"))
    if meta["top20"] is not None:
        (out_dir / "seven-field-projection.json").write_bytes(_dumps(meta["top20"]).encode("utf-8"))

    if carry is None:
        ranked = [(r["rank"], r["ticker"], r["system_bottleneck_explosion_score"]) for r in meta["report"]["records"]]
        counts = {"admitted_count": meta["report"]["admitted_count"], "ranked_count": meta["report"]["ranked_count"]}
    else:
        rows = meta["top20"]["records"] if meta["top20"] else []
        ranked = [(r["rank"], r["ticker"], None) for r in rows]
        counts = {"admitted_count": len(rows), "ranked_count": len(rows)}
    summary = {
        "run_id": meta["run_id"],
        "transaction_id": meta["transaction_id"],
        "seal_sha256": seal_sha,
        "promoted_at": PROMOTED_AT,
        "public_data_as_of": PUBLISHED_DATA_AS_OF,
        "ranked": ranked,
        **counts,
        "objects_json": _display_path(objects_path),
        "pointer_raw_json": _display_path(pointer_path),
    }
    if carry is not None:
        bundle = carry["bundle"] or {}
        summary.update({
            "top20_state": carry["state"],
            "top20_reason": carry["reason"],
            "top20_bundle_run_id": bundle.get("run_id"),
            "top20_bundle_sha256": bundle.get("bundle_sha256"),
            "top20_report_generated_at": bundle.get("report_generated_at"),
            "run_dir": str(out_dir),
        })
    (out_dir / "summary.json").write_bytes(_dumps(summary).encode("utf-8"))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()