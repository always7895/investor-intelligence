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
import math
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
import build_zh_names  # noqa: E402
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
# Lazy sealed objects (cloud/src/v213/snapshot-seal.ts SNAPSHOT_LAZY_KEY_RE): listed in the seal with their digest,
# stored once under blob:v1:<sha256> and verified by the Worker only when a lookup needs them.
LAZY_BLOB_PREFIX = "blob:v1:"
IDENTITY_SHARDS_PATH = ROOT / "data" / "cache" / "identity_shards_latest.json"
IDENTITY_MAX_AGE = timedelta(days=8)
BOTTLENECK_V3_PATH = ROOT / "data" / "cache" / "bottleneck_top20_v3.json"
BOTTLENECK_V3_KEY = "v213:bottleneck-top20:v3"
BOTTLENECK_V3_MAX_AGE = timedelta(hours=13)  # the Worker refuses it after report_max_age_hours (14 h)
MARKET_OBSERVATIONS_PATH = ROOT / "data" / "cache" / "market_quotes_options.json"
MARKET_OBSERVATIONS_MAX_AGE = timedelta(hours=5)  # the Worker ignores observations older than 6 h
PRICE_SHARDS_PATH = ROOT / "data" / "cache" / "price_shards_latest.json"
PRICE_SHARD_MAX_AGE = timedelta(days=3)  # the Worker ignores a market shard older than 4 days (weekends, holidays)
PRICE_MARKETS = ("US", "TAIWAN", "SWEDEN", "EUROPE", "JAPAN", "KOREA", "UK", "HK")
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


def lazy_identity_bodies(path: Path, now: datetime) -> "dict[str, str]":
    """Identity shards (scripts/build_identity_shards.py) as lazy bodies; none when missing, stale or malformed."""
    try:
        document = json.loads(path.read_bytes().decode("utf-8"))
        generated = datetime.strptime(document["generated_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if document.get("schema") != "v213-identity-shard-v2" or now - generated > IDENTITY_MAX_AGE:
            return {}
        bodies = {f"v213:identity:v2:sym:{bucket}": _dumps(shard) for bucket, shard in sorted(document["symbol_shards"].items())}
        bodies.update({f"v213:identity:v2:name:{bucket}": _dumps(shard) for bucket, shard in sorted(document["name_shards"].items())})
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}
    if "v213:identity:v2:sym:A" not in bodies or any(len(body.encode("utf-8")) > 2_000_000 for body in bodies.values()):
        return {}
    return bodies


BOTTLENECK_LAYERS_PATH = ROOT / "config" / "bottleneck-layers-v3.json"


def _layer_translations(path: Path = BOTTLENECK_LAYERS_PATH) -> "tuple[dict[str, str], dict[str, str]]":
    """Traditional Chinese roles by symbol and Leopold constraints by layer from the installed configuration, so a
    corrected translation reaches the next seal without waiting for the three-hourly v3 rebuild."""
    try:
        layers = json.loads(path.read_text(encoding="utf-8"))["layers"]
    except (OSError, ValueError, KeyError, TypeError):
        return {}, {}
    roles = {cap["symbol"]: cap["role_zh"] for layer in layers for cap in layer.get("capturers", []) if isinstance(cap.get("role_zh"), str)}
    constraints = {layer["id"]: layer["leopold_constraint_zh"] for layer in layers if isinstance(layer.get("leopold_constraint_zh"), str)}
    return roles, constraints


def _exchange_cross_checks(symbols: "list[str]", market_prices: "dict[str, dict]", path: Path = PRICE_SHARDS_PATH) -> "dict[str, dict]":
    """Operator 2026-09-26 (cards cited Yahoo only): the exchange's own close for each Top20 listing from the price
    shards, beside the Yahoo close the card's returns use. Only exchange feeds count (a Yahoo daily-close shard is not an
    independent source); the difference is given only in the same currency unit and never replaces the card's figures."""
    try:
        shards = json.loads(path.read_bytes().decode("utf-8"))["shards"]
    except (OSError, ValueError, KeyError, TypeError):
        return {}
    unit = lambda value: {"GBP": "GBX", "GBp": "GBX", "GBX": "GBX"}.get(str(value or ""), str(value or "").upper())  # noqa: E731
    out: dict = {}
    for symbol in symbols:
        market, _, native = build_zh_names.listing_key(symbol).partition(":")
        shard = shards.get(market) if isinstance(shards, dict) else None
        rows = (shard or {}).get("rows") or {}
        row = rows.get(native)
        if row is None and market == "EUROPE":  # Euronext rows are keyed "VENUE|SYMBOL"; only an unambiguous match counts
            matches = [key for key in rows if key.endswith("|" + native)]
            row = rows[matches[0]] if len(matches) == 1 else None
        if not isinstance(row, list) or len(row) < 5:
            continue
        try:
            source = shard["sources"][int(row[4])]
            price, asof, currency = float(row[0]), row[2], row[3]
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        if str(source.get("id", "")).startswith("yahoo") or not math.isfinite(price) or price <= 0 \
                or not str(source.get("url", "")).startswith("https://"):
            continue
        mine = market_prices.get(symbol) or {}
        own = mine.get("price")
        same = isinstance(own, (int, float)) and math.isfinite(own) and own > 0 and unit(mine.get("currency")) == unit(currency)
        out[symbol] = {"source_id": str(source["id"])[:40], "source_url": str(source["url"])[:400], "price": price,
                       "asof": asof if isinstance(asof, str) else shard.get("generated_at"), "currency": str(currency)[:8],
                       "diff": round(own / price - 1, 5) if same else None}
    return out


def _sealed_revenue_check(raw: "object") -> "dict | None":
    """An official revenue figure beside a listing's Yahoo quarter (scripts/bottleneck_top20_v3.py): the exchange's monthly
    revenue for Taiwan (period YYYY-MM, TWD), the issuer's own Cision interim report for Stockholm (YYYY-Qn, SEK) or a
    Korean company's curated IR release (YYYY-Qn, KRW),
    reduced to known keys with finite numbers and an https source; anything malformed is dropped."""
    sources = {"TWSE": ("TWD", False), "TPEX": ("TWD", False), "CISION": ("SEK", True), "COMPANY_IR_KR": ("KRW", True)}
    if not isinstance(raw, dict) or raw.get("source_id") not in sources or not str(raw.get("source_url", "")).startswith("https://"):
        return None
    currency, quarterly = sources[raw["source_id"]]
    period = str(raw.get("period", ""))
    if len(period) != 7 or period[4] != "-" or not period[:4].isdigit():
        return None
    if not (period[5] == "Q" and period[6] in "1234" if quarterly else period[5:].isdigit() and 1 <= int(period[5:]) <= 12):
        return None
    def number(value: object) -> "float | None":
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None
    yoy, cumulative = number(raw.get("revenue_yoy")), number(raw.get("cumulative_yoy"))
    if yoy is None and cumulative is None:
        return None
    return {"source_id": raw["source_id"], "source_url": raw["source_url"][:400], "period": period, "revenue_yoy": yoy,
            "cumulative_yoy": cumulative, "currency": currency}


def _sealed_outlook(raw: "object") -> "dict | None":
    """Orders, consensus and scenario figures from the v3 builder, reduced to known keys with finite numbers and https
    sources; anything malformed is dropped rather than sealed."""
    if not isinstance(raw, dict):
        return None

    def number(value: object) -> "float | None":
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None

    def text(value: object, limit: int) -> "str | None":
        return value[:limit] if isinstance(value, str) and value else None

    orders = raw.get("orders") if isinstance(raw.get("orders"), dict) else None
    sealed_orders = None
    if orders and orders.get("kind") in ("RPO", "BACKLOG") and number(orders.get("amount")) and \
            str(orders.get("source_url", "")).startswith("https://"):
        sealed_orders = {"kind": orders["kind"], "amount": number(orders["amount"]), "currency": text(orders.get("currency"), 8),
                         "as_of": text(orders.get("as_of"), 12), "yoy": number(orders.get("yoy")), "scope": text(orders.get("scope"), 40),
                         "source": text(orders.get("source"), 120), "source_url": orders["source_url"][:400]}
        for key in ("intake_quarter", "guidance"):
            part = orders.get(key)
            if isinstance(part, dict) and number(part.get("amount")):
                sealed_orders[key] = {name: (number(value) if name != "kind" else text(value, 30)) for name, value in part.items()
                                      if name in ("amount", "yoy", "year", "previous", "kind")}
    elif orders and orders.get("kind") == "NOT_DISCLOSED":
        sealed_orders = {"kind": "NOT_DISCLOSED", "reason": text(orders.get("reason"), 200)}
    consensus = raw.get("consensus") if isinstance(raw.get("consensus"), dict) else None
    sealed_consensus = None
    if consensus and number(consensus.get("revenue_growth")) is not None and str(consensus.get("source_url", "")).startswith("https://"):
        sealed_consensus = {key: number(consensus.get(key)) for key in ("revenue_fy0", "revenue_fy1", "revenue_growth", "revenue_analysts",
                                                                     "eps_fy0", "eps_fy1", "eps_growth", "eps_analysts",
                                                                     "target_mean", "target_analysts", "price", "target_upside")}
        sealed_consensus.update(source=text(consensus.get("source"), 80), source_url=consensus["source_url"][:400],
                                asof=text(consensus.get("asof"), 12))
    scenarios = [{"kind": row["kind"], "change": number(row.get("change"))} for row in raw.get("scenarios") or []
                 if isinstance(row, dict) and row.get("kind") in ("REVENUE_CONSTANT_PS", "EPS_CONSTANT_PE", "ANALYST_TARGET")
                 and number(row.get("change")) is not None][:3]
    second = raw.get("consensus_second") if isinstance(raw.get("consensus_second"), dict) else None
    sealed_second = None
    if second and str(second.get("source_url", "")).startswith("https://") and \
            (number(second.get("target_mean")) or number(second.get("eps_fy1")) is not None):
        sealed_second = {key: number(second.get(key)) for key in ("target_mean", "target_upside", "target_analysts", "eps_fy0",
                                                                  "eps_fy1", "eps_growth", "eps_analysts")}
        sealed_second.update(source=text(second.get("source"), 80), source_url=second["source_url"][:400],
                             asof=text(second.get("asof"), 12), eps_fiscal_end=text(second.get("eps_fiscal_end"), 20))
    return {"orders": sealed_orders, "consensus": sealed_consensus, "scenarios": scenarios if sealed_consensus else [],
            "consensus_second": sealed_second}


def lazy_bottleneck_v3_body(path: Path, now: datetime) -> "dict[str, str]":
    """The compact sealed form of scripts/bottleneck_top20_v3.py output; none when missing, stale or malformed."""
    try:
        doc = json.loads(path.read_bytes().decode("utf-8"))
        roles_zh, constraints_zh = _layer_translations()
        generated = datetime.strptime(doc["generated_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if doc.get("schema") != "v213-bottleneck-top20-v3" or not timedelta(0) <= now - generated <= BOTTLENECK_V3_MAX_AGE:
            return {}
        pick = lambda row, keys: {key: row.get(key) for key in keys}  # noqa: E731
        top = []
        zh = build_zh_names.names_for([entry["symbol"] for entry in doc["top"]])
        checks = _exchange_cross_checks([entry["symbol"] for entry in doc["top"]],
                                        {entry["symbol"]: entry.get("market") or {} for entry in doc["top"]})
        for entry in doc["top"]:
            parts = entry["score_parts"]
            sig, pos = entry.get("serenity"), entry.get("leopold")
            fund = entry.get("fundamentals")
            role_zh = roles_zh.get(entry["symbol"]) or entry.get("role_zh")
            top.append({
                "rank": entry["rank"], "symbol": entry["symbol"], "name": str(entry.get("name") or entry["symbol"])[:160],
                "name_zh": zh[entry["symbol"]][0] if entry["symbol"] in zh else None,
                "name_zh_source": zh[entry["symbol"]][1] if entry["symbol"] in zh else None,
                "layer": entry["layer"], "archetype": entry["archetype"], "score": entry["score"],
                "role": entry["role"][:200], "role_zh": str(role_zh)[:200] if role_zh else None,
                "role_source": entry["role_source"], "outlook": _sealed_outlook(entry.get("outlook")),
                "parts": {key: round(float(parts[key]), 2) for key in ("layer_heat", "capture", "lead", "confirmation", "size", "penalty")},
                "fundamentals": None if not fund else {
                    **pick(fund, ("source", "source_url", "quarter_end", "revenue_yoy", "revenue_yoy_prev", "gross_margin",
                                  "gross_margin_change", "rpo_yoy", "shares_yoy")),
                    **({"cross_check": check} if (check := _sealed_revenue_check(fund.get("cross_check"))) else {})},
                "market": {**pick(entry["market"], ("source", "source_url", "asof", "ret_6m", "ret_1y", "cagr_2y", "cagr_listed",
                                                    "history_start", "currency")),
                           **({"cross_check": checks[entry["symbol"]]} if entry["symbol"] in checks else {})},
                "market_cap_usd": entry.get("market_cap_usd"),
                "serenity": None if not sig else pick(sig, ("mentions", "bullish", "bearish", "stance", "latest_at", "latest_url")),
                "leopold": None if not pos else {"long_weight": pos["long_weight"], "status": pos["status"]},
            })
        industries = [{**pick(row, ("rank", "id", "name_zh", "chain", "leopold_constraint", "explosiveness", "median_revenue_yoy",
                                    "median_acceleration", "median_return_6m", "fund_13f_weight", "serenity_heat")),
                       "leopold_constraint_zh": constraints_zh.get(row["id"]) or row.get("leopold_constraint_zh") or None,
                       "news": None if not row.get("news") else pick(row["news"], ("source", "source_url", "recent_30d", "prior_60d", "ratio"))}
                      for row in doc["industries"]]
        serenity = (doc.get("leads") or {}).get("serenity") or {}
        filing = ((doc.get("leads") or {}).get("leopold") or {}).get("filing") or {}
        deep = company_deep_report.load_reports(tickers=[row["symbol"] for row in top if "." not in row["symbol"]])
        sealed = {"schema": "v213-bottleneck-top20-v3-sealed", "generated_at": doc["generated_at"], "deep_reports": deep,
                  "serenity_source": {"url": serenity.get("url"), "latest_post_at": serenity.get("latest_post_at")} if serenity.get("url") else None,
                  "leopold_filing": pick(filing, ("period", "filed", "url")) if filing.get("url") else None,
                  "top": top, "industries": industries}
        body = json.dumps(sealed, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}
    return {BOTTLENECK_V3_KEY: body} if len(body.encode("utf-8")) <= 1_900_000 and 10 <= len(top) <= 20 else {}


def lazy_price_bodies(path: Path, now: datetime) -> "dict[str, str]":
    """Per-market delayed price shards (scripts/build_price_shards.py) as lazy bodies; a stale or malformed market is
    left out on its own."""
    try:
        document = json.loads(path.read_bytes().decode("utf-8"))
        shards = document["shards"] if document.get("schema") == "v213-price-shard-v1" else {}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}
    bodies: dict[str, str] = {}
    for market, shard in sorted(shards.items()):
        try:
            generated = datetime.strptime(shard["generated_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if market not in PRICE_MARKETS or shard.get("market") != market or not timedelta(0) <= now - generated <= PRICE_SHARD_MAX_AGE \
                    or not isinstance(shard.get("rows"), dict) or not shard.get("sources"):
                continue
            body = _dumps(shard)
        except (KeyError, TypeError, ValueError):
            continue
        if len(body.encode("utf-8")) <= 1_900_000:
            bodies[f"v213:prices:v1:{market}"] = body
    return bodies


def lazy_market_bodies(path: Path, now: datetime) -> "dict[str, str]":
    """Delayed quotes and covered-call suggestions (scripts/build_market_quotes_options.py) as two lazy bodies; each cycle
    must pass the shared validator or is replaced by an explicit unavailability reason."""
    from validate_v213_market_products import MarketProductValidationError, validate_covered_call_cycle
    try:
        doc = json.loads(path.read_bytes().decode("utf-8"))
        generated = datetime.strptime(doc["generated_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if doc.get("schema") != "v213-market-observations-v2" or not timedelta(0) <= now - generated <= MARKET_OBSERVATIONS_MAX_AGE:
            return {}
        options: dict = {}
        for ticker, cycles in doc["options"].items():
            options[ticker] = {}
            for cycle, value in cycles.items():
                if "unavailable" in value:
                    options[ticker][cycle] = {"unavailable": str(value["unavailable"])[:200]}
                    continue
                try:
                    validate_covered_call_cycle(value, evaluated_at=doc["generated_at"])
                    options[ticker][cycle] = value
                except MarketProductValidationError as error:
                    options[ticker][cycle] = {"unavailable": f"報價未通過驗證（{str(error)[:60]}）"}
        quotes = {"schema": "v213-quotes-v1", "generated_at": doc["generated_at"], "quotes": doc["quotes"]}
        option_doc = {"schema": "v213-options-v2", "generated_at": doc["generated_at"], "options": options}
        bodies = {"v213:quotes:v1": json.dumps(quotes, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
                  "v213:options:v2": json.dumps(option_doc, ensure_ascii=False, separators=(",", ":"), allow_nan=False)}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}
    return bodies if all(len(body.encode("utf-8")) <= 1_900_000 for body in bodies.values()) else {}


def build_seal(bodies: "dict[str, str]", meta: "dict", lazy: "dict[str, str] | None" = None) -> "tuple[str, str]":
    digest_rows = {key: {"sha256": _sha(bodies[key]), "utf8_bytes": len(bodies[key].encode("utf-8"))}
                   for key in [*OBJECT_KEYS, MACRO_KEY]}
    for key, body in sorted((lazy or {}).items()):
        digest_rows[key] = {"sha256": _sha(body), "utf8_bytes": len(body.encode("utf-8"))}
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
    ap.add_argument("--identity-shards", nargs="?", const=str(IDENTITY_SHARDS_PATH), default=None, metavar="PATH",
                    help="Seal the global identity shards as lazy objects (no PATH: data/cache/identity_shards_latest.json).")
    ap.add_argument("--market-observations", nargs="?", const=str(MARKET_OBSERVATIONS_PATH), default=None, metavar="PATH",
                    help="Seal delayed quotes and option observations as lazy objects.")
    ap.add_argument("--price-shards", nargs="?", const=str(PRICE_SHARDS_PATH), default=None, metavar="PATH",
                    help="Seal per-market delayed price shards as lazy objects (no PATH: data/cache/price_shards_latest.json).")
    ap.add_argument("--bottleneck-v3", nargs="?", const=str(BOTTLENECK_V3_PATH), default=None, metavar="PATH",
                    help="Seal the bottleneck-explosion Top20 v3 as a lazy object (no PATH: data/cache/bottleneck_top20_v3.json).")
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
    lazy: "dict[str, str]" = {}
    if args.identity_shards is not None:
        lazy.update(lazy_identity_bodies(Path(args.identity_shards), LIVE_NOW or datetime.now(timezone.utc)))
    if args.market_observations is not None:
        lazy.update(lazy_market_bodies(Path(args.market_observations), LIVE_NOW or datetime.now(timezone.utc)))
    if args.price_shards is not None:
        lazy.update(lazy_price_bodies(Path(args.price_shards), LIVE_NOW or datetime.now(timezone.utc)))
    if args.bottleneck_v3 is not None:
        lazy.update(lazy_bottleneck_v3_body(Path(args.bottleneck_v3), LIVE_NOW or datetime.now(timezone.utc)))
    seal_text, seal_sha = build_seal(bodies, meta, lazy)
    pointer = pointer_text(meta, seal_sha)
    out_dir = args.snapshot_root / meta["run_id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"snapshot:{meta['run_id']}:"
    objects = {prefix + key: bodies[key] for key in [*OBJECT_KEYS, MACRO_KEY]}
    objects[prefix + SEAL_KEY] = seal_text
    for body in lazy.values():
        objects[LAZY_BLOB_PREFIX + _sha(body)] = body
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
    if lazy:
        summary["lazy_objects"] = len(lazy)
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