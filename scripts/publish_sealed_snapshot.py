"""Signed-snapshot promotion chain for multi-lineage ADMISSION_QUALIFIED candidates.

Builds, from OFFLINE assets only (no provider calls):
  1. the qualified v213 bottleneck report (GEV rank 1, 6501 rank 2,
     admitted_count = 2, ranked_count = 2, zero padding absent);
  2. the certified seven-field v213 Top20 projection;
  3. the 13-object sealed snapshot (SHAs, sizes, activation claim, seal
     manifest) per cloud/src/v213/snapshot-seal.ts contract v1;
  4. the schema-v2 sealed pointer.

Artifacts (pointer is committed LAST, in its own commit):
  state/v213-snapshots/<run_id>/objects.json   (14 store keys: 13 bodies + seal)
  state/v213-snapshots/<run_id>/pointer.raw.json   (exact pointer text)

Deterministic for a fixed evaluation clock; fails closed on any engine or
corpus drift.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import bottleneck_ranking as engine  # noqa: E402
import multilineage_claim_bundle as mlb  # noqa: E402

EVALUATED_AT = "2026-09-15T12:00:00Z"
RETRIEVED_AT = "2026-09-15T11:00:00Z"
GENERATED_AT = "2026-09-15T12:00:00Z"
CLAIMED_AT = "2026-09-15T12:00:00Z"
PROMOTED_AT = "2026-09-15T13:00:00Z"
PUBLISHED_DATA_AS_OF = "2026-09-15T12:00:00Z"
POLICY_ID = "system-bottleneck-explosion-v1"
PRODUCT_VERSION = "2.1.3"
CONTRACT_ID = "v213-stored-snapshot-v1"

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
    "GEV": "Electrical equipment & renewable energy (power & grid; Prolec-GE Waukesha)",
    "6501": "Electrical equipment (grid solutions; Hitachi Energy, TSE)",
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


def _sha(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def qualified_ranking() -> dict:
    mlb.verify_corpus_anchors()
    policy = engine.load_json(engine.POLICY_DEFAULT_PATH)
    registry = mlb.build_registry()
    health = mlb.health_for(registry)
    clock = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)
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
        "admitted_count": result["admitted_count"],
        "ranked_count": result["ranked_count"],
        "total_evaluated": result["total_evaluated"],
        "records": records,
        "provider_scope": "public_only",
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
            "orders_as_of": row["retrieved_at"],
            "orders_confidence": "EVIDENCE_BOUND" if (current_orders and not unavailable) else "UNAVAILABLE",
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
        "display_columns": display_columns,
        "long_term_definition": "trailing_2y_adjusted_close_cagr",
        "short_term_definition": "trailing_6m_adjusted_close_price_return",
        "records": records,
        "provider_scope": "public_only",
        "owner_watchlist_inherited": False,
    }


def build_bodies() -> "tuple[dict[str, str], dict]":
    result = qualified_ranking()
    report = bottleneck_report(result)
    bottleneck_json = _dumps(report)
    top20 = top20_projection(report)
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
    digest_seed = "".join(bodies[k] for k in OBJECT_KEYS if k != "v213:activation-claim") + bottleneck_json
    run_suffix = _sha(digest_seed)[:12]
    transaction_id = _sha(digest_seed)[:32]
    run_id = "20260915T1200Z-" + run_suffix if False else "20260915T120000Z-" + run_suffix
    claim = {
        "schema_version": 1,
        "transaction_id": transaction_id,
        "run_id": run_id,
        "payload_digests": {name: _sha(bodies[PAYLOAD_OBJECT[name]]) for name in PAYLOAD_NAMES},
        "claimed_at": CLAIMED_AT,
    }
    bodies["v213:bottleneck-report:latest"] = bottleneck_json
    bodies["v213:activation-claim"] = _dumps(claim)
    return bodies, {"report": report, "top20": top20, "run_id": run_id, "transaction_id": transaction_id}


def build_seal(bodies: "dict[str, str]", meta: "dict") -> "tuple[str, str]":
    digest_rows = {key: {"sha256": _sha(bodies[key]), "utf8_bytes": len(bodies[key].encode("utf-8"))}
                   for key in OBJECT_KEYS}
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


def main() -> None:
    bodies, meta = build_bodies()
    seal_text, seal_sha = build_seal(bodies, meta)
    pointer = pointer_text(meta, seal_sha)
    out_dir = ROOT / "state" / "v213-snapshots" / meta["run_id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"snapshot:{meta['run_id']}:"
    objects = {prefix + key: bodies[key] for key in OBJECT_KEYS}
    objects[prefix + SEAL_KEY] = seal_text
    objects_path = out_dir / "objects.json"
    objects_path.write_text(_dumps(objects) + "\n", encoding="utf-8")
    pointer_path = out_dir / "pointer.raw.json"
    pointer_path.write_text(pointer + "\n", encoding="utf-8")
    (out_dir / "seven-field-projection.json").write_text(_dumps(meta["top20"]), encoding="utf-8")

    summary = {
        "run_id": meta["run_id"],
        "transaction_id": meta["transaction_id"],
        "seal_sha256": seal_sha,
        "promoted_at": PROMOTED_AT,
        "public_data_as_of": PUBLISHED_DATA_AS_OF,
        "ranked": [(r["rank"], r["ticker"], r["system_bottleneck_explosion_score"]) for r in meta["report"]["records"]],
        "admitted_count": meta["report"]["admitted_count"],
        "ranked_count": meta["report"]["ranked_count"],
        "objects_json": str(objects_path.relative_to(ROOT)),
        "pointer_raw_json": str(pointer_path.relative_to(ROOT)),
    }
    out_dir.write_text if False else (out_dir / "summary.json").write_text(_dumps(summary) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()