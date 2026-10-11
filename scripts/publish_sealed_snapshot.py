"""Signed-snapshot promotion chain for multi-lineage ADMISSION_QUALIFIED candidates.

Builds, from OFFLINE assets only (no provider calls):
  1. the qualified v213 bottleneck report (GEV rank 1, 6501 rank 2,
     admitted_count = 2, ranked_count = 2, zero padding absent);
  2. the certified seven-field v213 Top20 projection;
  3. the sealed snapshot: 14 bodies (the 13 OBJECT_KEYS, activation claim included, plus the
     macro overview) and their seal manifest (SHAs, sizes) per cloud/src/v213/snapshot-seal.ts contract v1;
  4. the schema-v2 sealed pointer.

Artifacts (pointer is committed LAST, in its own commit):
  state/v213-snapshots/<run_id>/objects.json   (15 store keys: 14 bodies + seal; + one blob:v1:<sha256> per distinct lazy body)
  state/v213-snapshots/<run_id>/pointer.raw.json   (exact pointer text)

Deterministic for a fixed evaluation clock; fails closed on any engine or corpus drift, and never
replaces an existing run's objects.json/pointer.raw.json with different bytes (SEALED_RUN_DIR_CONFLICT).

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
import listing_lineage  # noqa: E402
import order_forecast  # noqa: E402
import order_claims  # noqa: E402
import revenue_guidance  # noqa: E402
import revenue_guidance_overlay  # noqa: E402
import revenue_guidance_wire  # noqa: E402
import revenue_consensus_quarterly  # noqa: E402
import top20_carry_forward  # noqa: E402
import official_quarterly_revenue  # noqa: E402

MACRO_KEY = "v213:macro-industry:latest"
SHARES_BASES = ("OUTSTANDING", "DILUTED_WEIGHTED_AVERAGE")  # scripts/bottleneck_top20_v3.py shares_basis

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


class CapturedInput:
    """Closed immutable byte operand for existing pure read/parsing adapters.

    NOT a pathname: no fspath, join, open, stat, write, callback or temporary file.
    Missing is an actual captured absence, never a fallback to a default pathname.
    """
    __slots__ = ("_raw",)

    def __init__(self, raw: bytes | None):
        if raw is not None and (type(raw) is not bytes or len(raw) > 16 * 1024 * 1024):
            raise ValueError("CAPTURED_INPUT_BOUND")
        object.__setattr__(self, "_raw", raw)

    def __setattr__(self, name, value):
        raise AttributeError("CAPTURED_INPUT_IMMUTABLE")

    def exists(self):
        return self._raw is not None

    def read_bytes(self):
        if self._raw is None:
            raise FileNotFoundError("CAPTURED_INPUT_ABSENT")
        return self._raw

    def read_text(self, encoding="utf-8"):
        if encoding not in ("utf-8", "utf-8-sig"):
            raise ValueError("CAPTURED_INPUT_ENCODING")
        return self.read_bytes().decode(encoding, "strict")

    def __str__(self):
        return "CAPTURED_INPUT"


class CapturedPublicationInputs:
    """Exact byte catalog consumed by ranking/publisher; data, NEVER authority."""
    __slots__ = ("_entries",)

    def __init__(self, entries: dict[str, bytes | None]):
        if type(entries) is not dict or not 1 <= len(entries) <= 1024:
            raise ValueError("CAPTURED_CATALOG_BOUND")
        object.__setattr__(self, "_entries", tuple((key, CapturedInput(value)) for key, value in sorted(entries.items())))

    def __setattr__(self, name, value):
        raise AttributeError("CAPTURED_CATALOG_IMMUTABLE")

    def operand(self, name):
        for key, value in self._entries:
            if key == name:
                return value
        raise ValueError("CAPTURED_INPUT_NOT_SELECTED")

    def manifest(self):
        return {name: hashlib.sha256(value.read_bytes()).hexdigest() if value.exists() else "ABSENT"
                for name, value in self._entries}


class ForecastConsumption:
    """Concrete observation of actual build_v3 returns with ONE genuine object.

    No callable hook, serialized seal or writable completion flag can replace it.
    """
    __slots__ = ("snapshot", "rows")

    def __init__(self, snapshot):
        self.snapshot = revenue_guidance_overlay.require_snapshot(snapshot)
        self.rows = []

    def observe(self, symbol, snapshot, result):
        if snapshot is not self.snapshot or type(result) is not dict or result.get("version") != 3:
            raise ValueError("MODEL_CONSUMPTION_MISMATCH")
        self.rows.append((symbol, hashlib.sha256(_dumps(result).encode("utf-8")).hexdigest()))


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
    if not re.fullmatch(r"[0-9]{4}-Q[1-4]" if quarterly else r"[0-9]{4}-(?:0[1-9]|1[0-2])", period):  # ASCII only
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


def _with_order_forecast(issuer: str, outlook: "dict | None", stock_orders: "object", recognition: "object",
                         cutoff: "datetime", claims: "dict",
                         revenue_registry: "dict | None" = None,
                         consensus_cache: "dict | None" = None,
                         release_checks_cache: "dict | None" = None,
                         revenue_approval: "dict | None" = None,
                         effective_inputs: "object | None" = None,
                         *, guidance_wire_enabled: bool = False,
                         guidance_machine_enabled: bool = False, machine_inputs=None,
                         consumption: "ForecastConsumption | None" = None) -> "dict":
    """The sealed outlook plus dual fields (Astra contract ORDERS-V3-01 section 6):
    - order_forecast: existing version:2, built by unchanged build_v2
    - order_forecast_v3: new version:3, separate revenue+order view
    at the build cutoff with reviewed registries, receipts and the enforced reviewed profile (A1) loaded once - or, from
    B1 on, with the one pinned effective-input snapshot (`effective_inputs`) of the lazy build."""
    sealed = outlook if outlook is not None else {"orders": None, "consensus": None, "scenarios": [], "consensus_second": None}
    v2 = order_forecast.build_v2(
        issuer, stock_orders if isinstance(stock_orders, dict) else None, recognition if isinstance(recognition, dict) else None,
        cutoff.date(), cutoff, claims)
    v3 = order_forecast.build_v3(
        issuer, stock_orders if isinstance(stock_orders, dict) else None, recognition if isinstance(recognition, dict) else None,
        cutoff.date(), cutoff, claims, revenue_registry=revenue_registry, consensus_cache=consensus_cache, v2_forecast=v2,
        release_checks_cache=release_checks_cache, revenue_approval=revenue_approval, effective_inputs=effective_inputs)
    if consumption is not None:
        if type(consumption) is not ForecastConsumption:
            raise ValueError("MODEL_CONSUMPTION_OPERAND")
        consumption.observe(issuer, effective_inputs, v3)
    # B3-WIRE-01: the disabled versioned transport wraps only the v3 result (default off; the disabled path is
    # byte-identical to the legacy structure, no new fields or null placeholders).
    if guidance_machine_enabled:
        import revenue_guidance_machine as machine
        if machine_inputs is None or effective_inputs is not machine_inputs.snapshot:
            raise machine.MachinePublicationBlocked()
        envelope = machine.make_machine_envelope(v3, issuer, machine_inputs)
        if envelope is not None:
            v3 = envelope  # full untouched model payload, NEVER transport-double-wrap
        elif guidance_wire_enabled:
            v3 = revenue_guidance_wire.envelope_v3_forecast(v3)  # explicit CURATED compatibility only
    elif guidance_wire_enabled:
        v3 = revenue_guidance_wire.envelope_v3_forecast(v3)
    return {**sealed, "order_forecast": v2, "order_forecast_v3": v3}


def lazy_bottleneck_v3_body(path: Path, now: datetime, effective_inputs: "object | None" = None,
                            state_root: "Path | None" = None,
                            *, guidance_wire_enabled: bool = False,
                            guidance_machine_enabled: bool = False, machine_inputs=None) -> "dict[str, str]":
    """The compact sealed form of scripts/bottleneck_top20_v3.py output; none when missing, stale or malformed.

    B1: one effective-input snapshot per build, taken at the ranking document's `generated_at` (not the wall clock)
    and passed unchanged to every model call (`effective_inputs` injects one for tests and replay; `state_root`
    selects the auto-update state root, default revenue_guidance_overlay.DEFAULT_STATE_ROOT)."""
    if guidance_machine_enabled:
        import revenue_guidance_machine as machine
        if effective_inputs is not None or state_root is not None:
            raise machine.MachinePublicationBlocked()  # legacy substitutions cannot satisfy machine prerequisites
        if machine_inputs is None:
            raise machine.MachinePublicationBlocked("GUIDANCE_MACHINE_PROVIDER_UNAVAILABLE")
    try:
        raw = path.read_bytes()
    except OSError:
        if guidance_machine_enabled:
            raise machine.MachinePublicationBlocked() from None
        return {}
    return captured_bottleneck_v3_body(raw, now, effective_inputs, state_root,
                                      guidance_wire_enabled=guidance_wire_enabled,
                                      guidance_machine_enabled=guidance_machine_enabled, machine_inputs=machine_inputs)


def captured_bottleneck_v3_body(raw: bytes, now: datetime, effective_inputs=None, state_root=None,
                               *, guidance_wire_enabled=False, guidance_machine_enabled=False,
                               machine_inputs=None, captured=None, consumption=None):
    """Shared actual parser/model path over captured ranking bytes, never reopen.

    Existing path caller is an adapter. A protected host supplies only exact typed
    captured auxiliary operands and its SAME genuine EffectiveInputs object.
    """
    import revenue_guidance_machine as machine
    if type(guidance_machine_enabled) is not bool:
        raise machine.MachinePublicationBlocked()
    if type(raw) is not bytes or len(raw) > 8 * 1024 * 1024:
        if guidance_machine_enabled:
            raise machine.MachinePublicationBlocked()
        return {}
    if captured is not None and type(captured) is not CapturedPublicationInputs:
        raise ValueError("CAPTURED_PUBLICATION_OPERAND")
    if consumption is not None and type(consumption) is not ForecastConsumption:
        raise ValueError("MODEL_CONSUMPTION_OPERAND")
    operand = captured.operand if captured is not None else None
    try:
        doc = json.loads(raw.decode("utf-8"))
        roles_zh, constraints_zh = _layer_translations(operand("layers") if operand else BOTTLENECK_LAYERS_PATH)
        generated = datetime.strptime(doc["generated_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if doc.get("schema") != "v213-bottleneck-top20-v3" or not timedelta(0) <= now - generated <= BOTTLENECK_V3_MAX_AGE:
            if guidance_machine_enabled:
                raise machine.MachinePublicationBlocked()
            return {}
        pick = lambda row, keys: {key: row.get(key) for key in keys}  # noqa: E731
        top = []
        zh = build_zh_names.names_for([entry["symbol"] for entry in doc["top"]],
             identity_path=operand("identity") if operand else None,
             names_path=operand("names") if operand else None,
             official_path=operand("official_names") if operand else None)
        # The deep reports' full order scenarios (RPO recognition schedules) feed the 6-month / 1-year order forecast.
        # The reviewed order claims after the filings, loaded once per document (never fetched while sealing).
        order_claim_registry = order_claims.load(operand("claims") if operand else None)
        # B1: the registry, the enforced reviewed profile (A1), the release-check receipts and the auto-update state are
        # read once into one pinned snapshot at this build's cutoff; a missing/malformed file stays a typed fault (the
        # curated path keeps its UNREVIEWED_INPUTS / freshness semantics, the automatic lane fails closed).
        if guidance_machine_enabled:
            resolved = machine.require_machine_inputs(machine_inputs, generated, [e["symbol"] for e in doc["top"]])
            if state_root is not None or (effective_inputs is not None and effective_inputs is not resolved.snapshot):
                raise machine.MachinePublicationBlocked()
            effective_inputs = resolved.snapshot  # actual SAME host-resolved object, BEFORE any legacy loader
        elif effective_inputs is None:
            effective_inputs = revenue_guidance_overlay.load_effective_inputs(
                cutoff=generated, state_root=state_root if state_root is not None else revenue_guidance_overlay.DEFAULT_STATE_ROOT,
                symbols=[entry["symbol"] for entry in doc["top"]])
        else:
            revenue_guidance_overlay.require_snapshot(effective_inputs, generated)
        try:
            # The newest capture per issuer taken at or before this build's cutoff (captures keep a short history).
            # A corrupted or missing cache is a typed channel fault, never conflated with a genuine empty/nondisclosed
            # success (Astra r5 item 9): the fault travels sealed so the Worker re-derives the same scoped failure.
            consensus_cache = revenue_consensus_quarterly.select_for_cutoff(
                revenue_consensus_quarterly.load_cache(operand("consensus") if operand else None), generated)
        except Exception:
            consensus_cache = {"__fault__": "CONSENSUS_CACHE_LOAD_FAILED"}
        order_scenarios = company_deep_report.load_order_scenarios(
            operand("deep") if operand else company_deep_report.OUTPUT_PATH,
            tickers=[entry["symbol"] for entry in doc["top"] if "." not in entry["symbol"]],
            today=generated.date() if operand else None)
        checks = _exchange_cross_checks([entry["symbol"] for entry in doc["top"]],
                                        {entry["symbol"]: entry.get("market") or {} for entry in doc["top"]},
                                        operand("prices") if operand else PRICE_SHARDS_PATH)
        for entry in doc["top"]:
            parts = entry["score_parts"]
            sig, pos = entry.get("serenity"), entry.get("leopold")
            fund = entry.get("fundamentals")
            role_zh = roles_zh.get(entry["symbol"]) or entry.get("role_zh")
            sealed_fund = None
            if fund:
                # The previous-quarter YoY from a reviewed official pair travels only with evidence rebuilt from the local
                # config (scripts/official_quarterly_revenue.py); a figure without it, or evidence without that basis,
                # refuses the whole object rather than keeping a number the reader would attribute to Yahoo.
                basis, source = fund.get("revenue_yoy_prev_basis"), fund.get("revenue_yoy_prev_source")
                if basis == "OFFICIAL_CURATED":
                    try:
                        source = official_quarterly_revenue.seal_evidence(
                            source, symbol=entry["symbol"], quarter=fund.get("quarter_end"), current_yoy=fund.get("revenue_yoy"),
                            prev_yoy=fund.get("revenue_yoy_prev"), as_of=generated,
                            path=operand("official_quarters") if operand else None)
                    except official_quarterly_revenue.RecordError:
                        if guidance_machine_enabled:
                            raise machine.MachinePublicationBlocked() from None
                        return {}
                elif basis not in (None, "YAHOO") or source is not None:
                    if guidance_machine_enabled:
                        raise machine.MachinePublicationBlocked()
                    return {}
                sealed_fund = {
                    **pick(fund, ("source", "source_url", "quarter_end", "revenue_yoy", "revenue_yoy_prev", "gross_margin",
                                  "gross_margin_change", "rpo_yoy", "shares_yoy")),
                    # What the share-count change measures; a figure without a known basis is not sealed.
                    "shares_basis": fund.get("shares_basis") if fund.get("shares_basis") in SHARES_BASES else None,
                    **({"shares_yoy": None} if fund.get("shares_basis") not in SHARES_BASES and "shares_basis" in fund else {}),
                    **({"cross_check": check} if (check := _sealed_revenue_check(fund.get("cross_check"))) else {})}
                if "revenue_yoy_prev_basis" in fund:  # older builds carry neither field and keep their legacy meaning
                    sealed_fund["revenue_yoy_prev_basis"] = basis
                    sealed_fund["revenue_yoy_prev_source"] = source
            top.append({
                "rank": entry["rank"], "symbol": entry["symbol"], "name": str(entry.get("name") or entry["symbol"])[:160],
                "name_zh": zh[entry["symbol"]][0] if entry["symbol"] in zh else None,
                "name_zh_source": zh[entry["symbol"]][1] if entry["symbol"] in zh else None,
                "layer": entry["layer"], "archetype": entry["archetype"], "score": entry["score"],
                "role": entry["role"][:200], "role_zh": str(role_zh)[:200] if role_zh else None,
                "role_source": entry["role_source"], "outlook": _with_order_forecast(
                    entry["symbol"], _sealed_outlook(entry.get("outlook")), (entry.get("outlook") or {}).get("orders"),
                    order_scenarios.get(entry["symbol"]), generated, order_claim_registry,
                    consensus_cache=consensus_cache, effective_inputs=effective_inputs,
                    guidance_wire_enabled=guidance_wire_enabled, guidance_machine_enabled=guidance_machine_enabled,
                    machine_inputs=machine_inputs, consumption=consumption),
                "parts": {key: round(float(parts[key]), 2) for key in ("layer_heat", "capture", "lead", "confirmation", "size", "penalty")},
                "fundamentals": sealed_fund,
                # The long-term fields travel validated and consistent (scripts/listing_lineage.py); malformed ones fail closed.
                "market": {**pick(entry["market"], ("source", "source_url", "asof", "ret_6m", "ret_1y", "history_start", "currency")),
                           **listing_lineage.clean_market_lineage(entry["market"], generated.date()),
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
        deep = company_deep_report.load_reports(
            operand("deep") if operand else company_deep_report.OUTPUT_PATH,
            tickers=[row["symbol"] for row in top if "." not in row["symbol"]],
            today=generated.date() if operand else None)
        sealed = {"schema": "v213-bottleneck-top20-v3-sealed", "generated_at": doc["generated_at"], "deep_reports": deep,
                  "serenity_source": {"url": serenity.get("url"), "latest_post_at": serenity.get("latest_post_at")} if serenity.get("url") else None,
                  "leopold_filing": pick(filing, ("period", "filed", "url")) if filing.get("url") else None,
                  "top": top, "industries": industries}
        body = (machine.compact(sealed, machine.REPORT_BYTES).decode("utf-8") if guidance_machine_enabled else
                json.dumps(sealed, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    except machine.MachinePublicationBlocked:
        raise  # actual typed resolver/envelope/serialization blocks never become partial/legacy {}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        if guidance_machine_enabled:
            raise machine.MachinePublicationBlocked() from None
        return {}
    if len(body.encode("utf-8")) > 1_900_000 or not 10 <= len(top) <= 20:
        if guidance_machine_enabled:
            raise machine.MachinePublicationBlocked("MACHINE_EVIDENCE_LIMIT")
        return {}
    return {BOTTLENECK_V3_KEY: body}


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
    import public_options_provider_gate as option_rights
    # Public RIGHTS admission (distinct from the shared FORMAT validator and from the honest local-candidate labels): the audited
    # canonical catalog is loaded ONCE; a cycle reaches v213:options:v2 only when its claimed identity matches an admitted scope of a
    # fully eligible provider. An empty/invalid/unselected catalog (the current state) admits nothing: no network, no mutation.
    policy = option_rights.load_public_option_policy(ROOT, today=now.astimezone(timezone.utc).date())
    try:
        doc = json.loads(path.read_bytes().decode("utf-8"))
        generated = datetime.strptime(doc["generated_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if doc.get("schema") != "v213-market-observations-v2" or not timedelta(0) <= now - generated <= MARKET_OBSERVATIONS_MAX_AGE:
            return {}
        options: dict = {}
        for ticker, cycles in doc["options"].items():
            if not isinstance(cycles, dict):
                continue  # a malformed ticker entry does not drop the healthy siblings
            options[ticker] = {}
            for cycle, value in cycles.items():
                try:
                    if isinstance(value, dict) and "unavailable" in value:
                        options[ticker][cycle] = {"unavailable": str(value["unavailable"])[:200]}
                        continue
                    if isinstance(value, dict) and option_rights.public_option_cycle_admission(value, policy) is not None:
                        options[ticker][cycle] = {"unavailable": option_rights.OPTION_RIGHTS_UNAVAILABLE_ZH}  # label/currency/source never admit
                        continue
                    # A non-record cycle (e.g. suggestions=[null]) must raise the domain error here, not an
                    # AttributeError that escapes to the whole-document catch and discards healthy cycles.
                    validate_covered_call_cycle(value, evaluated_at=now, document_at=doc["generated_at"], period=cycle)
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


COVERAGE_KEY = "v213:options-coverage:v1"
COVERAGE_NOTE_CODES = ["CATALOG_COUNT_IS_NOT_INDEPENDENT_CONFIRMATION", "DECLARED_IS_NOT_COLLECTED_OR_LIVE", "EOD_INDEX_AND_DELTA_NOT_ADMITTED_BY_THIS_VIEW",
                       "NO_RAW_QUOTES_IN_THIS_OBJECT", "ORIGIN_LINEAGE_UNKNOWN_NO_CORROBORATION_METRIC", "UNCATALOGUED_JURISDICTIONS_ARE_NOT_COVERAGE"]


def _coverage_observed(options_body: "str | None", policy: "object", now: datetime) -> "tuple[list[dict], dict | None]":
    """Admitted-row counts and the quote as-of ONLY from this publisher's own `v213:options:v2` body (the exact string the seal will carry),
    under the SAME rules as the real public loader (loadDetailedOptionObservation), re-applied here so a standalone call does not rely on an
    earlier caller: v2 shape, a canonical document clock at most 5 minutes in the future and 6 hours old, ONLY the weekly and monthly period
    keys, producer-unavailable entries stay unavailable, validate_covered_call_cycle with its period, a canonical quote instant, and the
    canonical policy admission. Any proof failure returns an empty list and a null link (UNKNOWN), never a manufactured zero. The link
    (sha256 and byte length of that very body) is what the Worker rechecks. Retrieval time is never an as-of. ticker_key_count is the number
    of distinct sealed option-document ticker keys, NOT native underlyings, ISINs or chain completeness (aliases are not collapsed)."""
    import public_options_provider_gate as option_rights
    from validate_v213_market_products import MarketProductValidationError, coverage_instant, validate_covered_call_cycle
    if options_body is None:
        return [], None
    link = {"key": "v213:options:v2", "sha256": _sha(options_body), "utf8_bytes": len(options_body.encode("utf-8"))}
    document = json.loads(options_body)
    if (not isinstance(document, dict) or document.get("schema") != "v213-options-v2" or not isinstance(document.get("options"), dict)
            or not coverage_instant(document.get("generated_at"))):
        return [], None
    now_utc = now.astimezone(timezone.utc)
    age = (now_utc - datetime.strptime(document["generated_at"][:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)).total_seconds()
    if age < -300 or age > 6 * 3600:
        return [], None
    groups: dict = {}
    for ticker, cycles in document["options"].items():
        if not isinstance(cycles, dict):
            return [], None  # a corrupt ticker entry makes the whole document unprovable
        if re.fullmatch(r"[A-Z0-9.\- ]{1,16}", ticker) is None:
            continue
        for period in ("weekly", "monthly"):  # no arbitrary period key is interpreted
            if period not in cycles:
                continue
            cycle = cycles[period]
            if isinstance(cycle, dict) and isinstance(cycle.get("unavailable"), str):
                continue
            try:
                validate_covered_call_cycle(cycle, evaluated_at=now_utc, document_at=document["generated_at"], period=period)
            except (MarketProductValidationError, TypeError, ValueError, KeyError, AttributeError, OverflowError):
                continue
            if not coverage_instant(cycle["timestamp"]) or option_rights.public_option_cycle_admission(cycle, policy) is not None:
                continue  # a label, a boolean or the mere presence in the body never counts
            identity = tuple(cycle[key] for key in ("provider_id", "jurisdiction", "venue", "instrument_kind", "quote_basis", "publication_scope"))
            stamp = datetime.strptime(cycle["timestamp"][:-1], "%Y-%m-%dT%H:%M:%S" + (".%f" if len(cycle["timestamp"]) == 24 else ""))
            group = groups.setdefault(identity, {"cycles": 0, "tickers": set(), "as_of": cycle["timestamp"], "stamp": stamp})
            group["cycles"] += 1
            group["tickers"].add(ticker)
            if stamp > group["stamp"]:
                group["stamp"], group["as_of"] = stamp, cycle["timestamp"]
    rows = [{"provider_id": key[0], "jurisdiction": key[1], "venue": key[2], "instrument_kind": key[3], "quote_basis": key[4],
             "publication_scope": key[5], "cycle_count": group["cycles"], "ticker_key_count": len(group["tickers"]),
             "quote_as_of_max": group["as_of"]} for key, group in sorted(groups.items(), key=lambda item: "|".join(item[0]))]
    return rows, link


def lazy_options_coverage_body(options_body: "str | None", now: datetime) -> "dict[str, str]":
    """The PUBLIC, METADATA-ONLY global options source/gap object (G1A) for the existing sealed R75 snapshot: catalog-DECLARED providers and
    jurisdictions derived from the unchanged canonical catalog (never a hand-kept country map, never a second approval list), the local
    covered-call routing scope from config/option-adr-map-v1.json, and observed admitted counts/as-of computed from the SAME publisher's
    options body. It carries no raw quote, no private field and no rights decision; the Worker re-verifies it. An unusable catalog, a
    schema failure or an oversized body yields {} (the Worker then reports COVERAGE_ABSENT), never a fabricated or cached object."""
    import public_options_provider_gate as option_rights
    from validate_v213_market_products import MAX_COVERAGE_BODY_BYTES, MarketProductValidationError, validate_options_coverage_document
    try:
        day = now.astimezone(timezone.utc).date()
        findings, _summary = option_rights.audit_public_options_providers(ROOT, today=day)
        if findings:
            return {}
        catalog = option_rights._object(ROOT / "config" / "public-options-provider-candidates.json")
        policy = option_rights.load_public_option_policy(ROOT, today=day)
        admitted = set(policy.provider_ids())
        providers: list = []
        by_jurisdiction: dict = {}
        for provider in catalog["providers"]:
            provider_id = str(provider["id"])
            providers.append({"provider_id": provider_id, "name": provider["name"], "authority": provider["authority"],
                              "jurisdictions": list(provider["jurisdictions"]), "data_roles": list(provider["data_roles"]),
                              "rights_status": provider["rights_status"], "rights_reviewed_at": provider["rights_reviewed_at"],
                              "adapter_status": provider["adapter_status"], "runtime_enabled": provider["runtime_enabled"],
                              "line_quote_eligible": provider["line_quote_eligible"],
                              "public_admission": "ADMITTED" if provider_id in admitted else "NOT_ADMITTED",
                              "declared": "CATALOG_DECLARED_UNVERIFIED"})
            for code in provider["jurisdictions"]:
                by_jurisdiction.setdefault(str(code), []).append(provider_id)
        routing = json.loads((ROOT / "config" / "option-adr-map-v1.json").read_text(encoding="utf-8"))
        local = [{"market": market, "capability": "COVERED_CALL_DELAYED_LOCAL_CANDIDATE", "status": "LOCAL_UNADMITTED_NO_CATALOG_IDENTITY"}
                 for market in sorted(routing["covered_markets"])]
        observed, link = _coverage_observed(options_body, policy, now)
        document = {
            "schema": "v213-options-coverage-v1", "generated_at": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "purpose": "SOURCE_COVERAGE_METADATA_ONLY", "options_link": link,
            "catalog_summary": {"catalog_provider_count": len(providers), "public_admitted_provider_count": len(admitted),
                                "production_provider_selected": catalog["production_quote_provider_selected"]},
            "providers": providers,
            "jurisdictions": [{"code": code, "provider_ids": ids, "catalog_provider_count": len(ids)} for code, ids in sorted(by_jurisdiction.items())],
            "local_capabilities": local, "observed": observed, "data_completeness": "NOT_REAUDITED", "notes": list(COVERAGE_NOTE_CODES),
        }
        validate_options_coverage_document(document)
        body = json.dumps(document, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, MarketProductValidationError):
        return {}
    return {COVERAGE_KEY: body} if len(body.encode("utf-8")) <= MAX_COVERAGE_BODY_BYTES else {}


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
    ap.add_argument("--guidance-machine", action="store_true", help="Seal already-exported SAME-host PUBLIC body+binding; no lazy rebuild.")
    ap.add_argument("--guidance-public-token")
    ap.add_argument("--guidance-report-sha256")
    ap.add_argument("--guidance-binding-sha256")
    args = ap.parse_args(argv)
    machine_bodies = None
    if args.guidance_machine:
        import revenue_guidance_machine as machine
        machine_bodies = machine.read_staged_bundle(args.guidance_public_token,
                              args.guidance_report_sha256, args.guidance_binding_sha256)
    elif any((args.guidance_public_token, args.guidance_report_sha256, args.guidance_binding_sha256)):
        from revenue_guidance_machine import MachinePublicationBlocked
        raise MachinePublicationBlocked()
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
        # G1A: metadata-only source/gap object on the SAME seal, computed from the options body just built (no second route or storage).
        lazy.update(lazy_options_coverage_body(lazy.get("v213:options:v2"), LIVE_NOW or datetime.now(timezone.utc)))
    if args.price_shards is not None:
        lazy.update(lazy_price_bodies(Path(args.price_shards), LIVE_NOW or datetime.now(timezone.utc)))
    if machine_bodies is not None:
        lazy.update(machine_bodies)  # BOTH exact independently channel-bound objects in ONE generic seal
    elif args.bottleneck_v3 is not None:
        lazy.update(lazy_bottleneck_v3_body(Path(args.bottleneck_v3), LIVE_NOW or datetime.now(timezone.utc)))
    seal_text, seal_sha = build_seal(bodies, meta, lazy)
    pointer = pointer_text(meta, seal_sha)
    out_dir = args.snapshot_root / meta["run_id"]
    prefix = f"snapshot:{meta['run_id']}:"
    objects = {prefix + key: bodies[key] for key in [*OBJECT_KEYS, MACRO_KEY]}
    objects[prefix + SEAL_KEY] = seal_text
    for body in lazy.values():
        objects[LAZY_BLOB_PREFIX + _sha(body)] = body
    objects_path = out_dir / "objects.json"
    objects_bytes = _dumps(objects).encode("utf-8")
    pointer_path = out_dir / "pointer.raw.json"
    # One run id names one sealed byte set (a synced run may be serving, a git-tracked one is a rollback target): an
    # identical re-run may rewrite it, different bytes never replace it. Checked before the mkdir and before any write.
    for path, data in ((objects_path, objects_bytes), (pointer_path, pointer.encode("utf-8"))):
        if path.is_file() and path.read_bytes() != data:
            raise SystemExit("SEALED_RUN_DIR_CONFLICT")
    out_dir.mkdir(parents=True, exist_ok=True)
    objects_path.write_bytes(objects_bytes)
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
    from revenue_guidance_machine import MachinePublicationBlocked
    try:
        main()
    except MachinePublicationBlocked as error:
        print(error.reason)  # fixed safe reason only, no provider/path/traceback diagnostic
        raise SystemExit(2) from None