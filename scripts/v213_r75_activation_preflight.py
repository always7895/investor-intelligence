#!/usr/bin/env python3
"""Fail-closed v2.1.3 R75 activation preflight.

The sealed seven-payload activation bundle is the only activation authority.  A
candidate is accepted in exactly one of two publication modes:

* EVIDENCE_QUALIFIED: independently corroborated company evidence.
* LIMITED_RESEARCH_CANDIDATE: latest primary company evidence plus independent
  listing/legal-entity provenance, with every sensitive positive factor
  withheld, no validated thesis, and no HIGH-confidence eligibility.

This program is read-only.  It never writes Production, Cloudflare KV, Worker
configuration, LINE state, scheduled tasks, or model configuration.  It writes
only an optional local JSON receipt after every validation gate has passed.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "config" / "v213-r75-publication-mode-v1.json"
try:
    CONTRACT = json.loads(CONTRACT_PATH.read_text(encoding="utf-8-sig"))
except (OSError, json.JSONDecodeError) as exc:
    raise RuntimeError(f"unable to load R75 publication contract: {CONTRACT_PATH}") from exc

PRODUCT_VERSION = str(CONTRACT["product_version"])
SCHEMA_VERSION = int(CONTRACT["bundle_schema_version"])
PAYLOAD_NAMES = set(CONTRACT["payload_names"])
RUN_ID_RE = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{12}$")
TRANSACTION_ID_RE = re.compile(r"^[0-9a-f]{32}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
EVIDENCE_QUALIFIED = str(CONTRACT["modes"]["evidence_qualified"])
LIMITED = str(CONTRACT["modes"]["limited"])
LIMITED_MISSING_CODES = set(CONTRACT["limited_missing_codes"])
SENSITIVE_FACTORS = tuple(CONTRACT["sensitive_factors"])
REQUIRED_FEDERATION_FAMILIES = set(CONTRACT["required_federation_families"])
THRESHOLDS = CONTRACT["thresholds"]
MARKET_DEGRADATION = "INSUFFICIENT_NON_YAHOO_MARKET_COVERAGE"
MAX_BUNDLE_AGE_SECONDS = int(THRESHOLDS["max_bundle_age_seconds"])
CLOCK_SKEW_SECONDS = int(THRESHOLDS["clock_skew_seconds"])


class PreflightError(RuntimeError):
    """The sealed bundle is not safe to activate."""


def object_(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PreflightError(f"{label} must be an object")
    return value


def array(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise PreflightError(f"{label} must be an array")
    return value


def integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def number(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def boolean(value: Any) -> bool:
    return value is True


def timestamp(value: Any, label: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise PreflightError(f"{label} is missing")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PreflightError(f"{label} is invalid") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def contract_sha256() -> str:
    return sha256_text(canonical_json(CONTRACT))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_json_text(value: Any, label: str) -> Any:
    if not isinstance(value, str):
        raise PreflightError(f"{label} payload must be UTF-8 JSON text")
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise PreflightError(f"{label} payload is invalid JSON") from exc


def ticker_order(rows: Any, label: str) -> list[str]:
    values = array(rows, label)
    if len(values) != int(THRESHOLDS["ticker_count"]):
        raise PreflightError(f"{label} must contain exactly {int(THRESHOLDS["ticker_count"])} rows")
    result: list[str] = []
    for index, raw in enumerate(values, 1):
        row = object_(raw, f"{label}[{index}]")
        ticker = str(row.get("ticker") or "").strip().upper()
        if not ticker:
            raise PreflightError(f"{label}[{index}] has no ticker")
        if integer(row.get("rank"), index) != index:
            raise PreflightError(f"{label}[{index}] rank is not {index}")
        if ticker in result:
            raise PreflightError(f"{label} contains duplicate ticker {ticker}")
        result.append(ticker)
    return result


def require_same_order(expected: Sequence[str], rows: Any, label: str) -> None:
    actual = ticker_order(rows, label)
    if list(expected) != actual:
        raise PreflightError(f"{label} order does not match final Top20")


def validate_freshness(root: Mapping[str, Any], now: datetime) -> dict[str, float]:
    values = {
        "bundle.generated_at": root.get("generated_at"),
        "bundle.public_data_as_of": root.get("public_data_as_of"),
    }
    ages: dict[str, float] = {}
    parsed: dict[str, datetime] = {}
    for label, value in values.items():
        observed = timestamp(value, label)
        parsed[label] = observed
        age = (now - observed).total_seconds()
        if age < -CLOCK_SKEW_SECONDS:
            raise PreflightError(f"{label} is future-dated")
        if age > MAX_BUNDLE_AGE_SECONDS:
            raise PreflightError(
                f"{label} is stale; age_seconds={round(age)}; "
                f"max={MAX_BUNDLE_AGE_SECONDS}"
            )
        ages[label] = round(max(0.0, age), 3)
    if (
        parsed["bundle.public_data_as_of"]
        - parsed["bundle.generated_at"]
    ).total_seconds() > CLOCK_SKEW_SECONDS:
        raise PreflightError("public_data_as_of is later than generated_at")
    return ages


def validate_source_plan(raw: Any) -> None:
    plan = object_(raw, "source plan")
    inventory = object_(plan.get("inventory"), "source plan inventory")
    federation = object_(plan.get("live_source_federation"), "source plan federation")
    scoring = object_(plan.get("scoring_methodology"), "source plan scoring")
    successful = {str(item) for item in array(federation.get("successful_families"), "source plan successful families")}
    official = {str(item) for item in array(federation.get("official_successful_families"), "source plan official families")}
    if (
        integer(plan.get("schema_version")) != 1
        or integer(plan.get("catalog_count")) != 101
        or plan.get("automatic_activation") is not False
        or str(plan.get("provider_scope") or "") != "public_only"
        or plan.get("owner_watchlist_inherited") is not False
        or plan.get("line_public_eligible") is not True
        or integer(inventory.get("source_count")) != 101
        or integer(inventory.get("runtime_enabled_count"), -1) != 0
        or len(successful) < int(THRESHOLDS["min_successful_families"])
        or len(official) < int(THRESHOLDS["min_official_successful_families"])
        or not REQUIRED_FEDERATION_FAMILIES.issubset(successful)
        or not REQUIRED_FEDERATION_FAMILIES.issubset(official)
        or number(federation.get("ticker_coverage_ratio")) < number(THRESHOLDS["min_ticker_coverage_ratio"])
        or integer(federation.get("unresolved_material_conflict_count")) != 0
        or federation.get("yahoo_authoritative") is not False
        or federation.get("catalog_source_count_is_not_live_use") is not True
        or str(scoring.get("scoring_version") or "") != str(CONTRACT["scoring_version"])
        or scoring.get("official_serenity_formula_claimed") is not False
        or scoring.get("private_process_reproduction_claimed") is not False
    ):
        raise PreflightError("source plan violates the publication contract")


def validate_federation(raw: Any, order: Sequence[str]) -> dict[str, Any]:
    document = object_(raw, "source federation")
    gates = object_(document.get("gates"), "source federation gates")
    if integer(document.get("schema_version")) != 1:
        raise PreflightError("source federation schema_version is invalid")
    if str(document.get("product_version") or "") != PRODUCT_VERSION:
        raise PreflightError("source federation product_version is invalid")
    timestamp(document.get("generated_at"), "source federation generated_at")
    if gates.get("pass") is not True:
        raise PreflightError("source federation gate is not PASS")
    successful = {
        str(item) for item in array(gates.get("successful_families"), "successful families")
    }
    official = {
        str(item)
        for item in array(
            gates.get("official_successful_families"),
            "official successful families",
        )
    }
    missing = REQUIRED_FEDERATION_FAMILIES - successful
    missing_official = REQUIRED_FEDERATION_FAMILIES - official
    if missing or missing_official:
        raise PreflightError(
            "source federation lacks required core families: "
            + ",".join(sorted(missing | missing_official))
        )
    if len(successful) < int(THRESHOLDS["min_successful_families"]):
        raise PreflightError("source federation has fewer than the required successful families")
    if len(official) < int(THRESHOLDS["min_official_successful_families"]):
        raise PreflightError("source federation has fewer than four official families")
    reported_missing = array(
        gates.get("missing_required_families"),
        "missing required families",
    )
    if reported_missing:
        raise PreflightError("source federation reports missing required families")
    if number(gates.get("ticker_coverage_ratio")) < number(THRESHOLDS["min_ticker_coverage_ratio"]):
        raise PreflightError("source federation Top20 coverage is below 80%")
    if integer(gates.get("unresolved_material_conflict_count")) != 0:
        raise PreflightError("source federation has unresolved material conflicts")
    if gates.get("concentration_pass") is not True:
        raise PreflightError("source federation concentration gate failed")
    if gates.get("yahoo_authoritative") is not False:
        raise PreflightError("Yahoo is incorrectly authoritative")
    if gates.get("catalog_source_count_is_not_live_use") is not True:
        raise PreflightError("catalog count is incorrectly treated as live use")
    require_same_order(order, document.get("ticker_sources"), "source federation")
    return {
        "successful_family_count": len(successful),
        "official_family_count": len(official),
        "bls_present": "us_bls" in successful,
        "ticker_coverage_ratio": number(gates.get("ticker_coverage_ratio")),
    }


def record_mode(record: Mapping[str, Any]) -> str:
    direct = str(record.get("publication_evidence_mode") or "")
    if direct:
        return direct
    state = record.get("freshness_state")
    if isinstance(state, Mapping):
        nested = str(state.get("publication_evidence_mode") or "")
        if nested:
            return nested
    logic = record.get("public_logic_state")
    if isinstance(logic, Mapping):
        return str(logic.get("publication_evidence_mode") or "")
    return ""


def sensitive_positive_factors(top20_row: Mapping[str, Any]) -> list[str]:
    factors = object_(top20_row.get("serenity_factors"), "Top20 serenity_factors")
    return [name for name in SENSITIVE_FACTORS if number(factors.get(name)) > 0]


def validate_source_audit(
    raw: Any,
    order: Sequence[str],
    top20: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    document = object_(raw, "source-independence audit")
    portfolio = object_(document.get("portfolio"), "source-independence portfolio")
    notice = object_(document.get("methodology_notice"), "methodology notice")
    records = array(document.get("records"), "source-independence records")
    violations = array(document.get("violations"), "source violations")
    blockers = array(document.get("blocking_violations"), "source blockers")
    degradations = {
        str(item)
        for item in array(document.get("degradations"), "source degradations")
    }
    if integer(document.get("schema_version")) < 3:
        raise PreflightError("source-independence schema_version is below 3")
    if str(document.get("product_version") or "") != PRODUCT_VERSION:
        raise PreflightError("source-independence product_version is invalid")
    if str(document.get("status") or "") != "PASS":
        raise PreflightError("source-independence status is not PASS")
    timestamp(document.get("generated_at"), "source-independence generated_at")
    if violations or blockers:
        raise PreflightError("source-independence audit contains blocking violations")
    if len(records) != int(THRESHOLDS["ticker_count"]):
        raise PreflightError("source-independence audit does not contain 20 records")
    require_same_order(order, records, "source-independence audit")
    if integer(portfolio.get("independent_source_families")) < int(THRESHOLDS["min_independent_source_families"]):
        raise PreflightError("portfolio has fewer than three independent source families")
    if integer(portfolio.get("independent_domains")) < int(THRESHOLDS["min_independent_domains"]):
        raise PreflightError("portfolio has fewer than three independent domains")
    if number(portfolio.get("claim_primary_coverage_ratio")) < number(THRESHOLDS["min_claim_primary_coverage_ratio"]):
        raise PreflightError("claim-primary coverage is below 75%")
    if integer(portfolio.get("claim_source_families")) < int(THRESHOLDS["min_portfolio_claim_source_families"]):
        raise PreflightError("portfolio has no company-claim family")
    if integer(portfolio.get("claim_source_domains")) < int(THRESHOLDS["min_portfolio_claim_source_domains"]):
        raise PreflightError("portfolio has no company-claim domain")
    if number(portfolio.get("maximum_single_family_share"), 1.0) > number(THRESHOLDS["max_single_family_share"]):
        raise PreflightError("one source family exceeds the 70% concentration cap")
    if integer(portfolio.get("market_conflict_ticker_count")) != 0:
        raise PreflightError("market-source conflicts remain unresolved")

    coverage = number(portfolio.get("non_yahoo_market_coverage_ratio"))
    target = number(portfolio.get("non_yahoo_market_coverage_target_ratio"), 0.75)
    degraded = coverage < target
    if degraded:
        if str(document.get("quality_status") or "") != "PASS_WITH_DEGRADATION":
            raise PreflightError("degraded market quality is not explicitly labelled")
        if str(portfolio.get("market_corroboration_status") or "") != "DEGRADED":
            raise PreflightError("portfolio market status is not DEGRADED")
        if portfolio.get("market_corroboration_global_blocker") is not False:
            raise PreflightError("market endpoint unavailability is a global blocker")
        if MARKET_DEGRADATION not in degradations:
            raise PreflightError("market degradation code is missing")
    else:
        if str(portfolio.get("market_corroboration_status") or "") != "CORROBORATED":
            raise PreflightError("adequate market coverage is not CORROBORATED")
        if MARKET_DEGRADATION in degradations:
            raise PreflightError("market degradation code remains on corroborated data")

    required_false = (
        "official_serenity_formula",
        "official_serenity_score",
        "private_method_reproduced",
        "single_source_inference_allowed",
        "market_corroboration_unavailable_is_global_blocker",
    )
    for name in required_false:
        if notice.get(name) is not False:
            raise PreflightError(f"methodology notice weakened: {name}")
    required_true = (
        "source_diversity_is_not_truth_by_itself",
        "official_macro_is_not_company_claim_evidence",
        "market_corroboration_required_for_high_confidence_model_inference",
        "market_corroboration_required_for_uncapped_valuation_factor",
        "provider_failure_must_be_disclosed",
        "market_data_is_not_averaged_into_published_returns",
    )
    for name in required_true:
        if notice.get(name) is not True:
            raise PreflightError(f"methodology notice weakened: {name}")

    strict_declared = integer(portfolio.get("evidence_qualified_candidate_count"), -1)
    limited_declared = integer(portfolio.get("limited_research_candidate_count"), -1)
    if strict_declared < 0 or limited_declared < 0:
        raise PreflightError("publication-mode counts are missing")
    if strict_declared + limited_declared != int(THRESHOLDS["ticker_count"]):
        raise PreflightError("publication-mode counts do not total 20")
    if portfolio.get("all_rows_publication_provenance_multi_source") is not True:
        raise PreflightError("not every row has independent publication provenance")
    if integer(portfolio.get("limited_rows_high_confidence_eligible_count")) != 0:
        raise PreflightError("a LIMITED row is HIGH eligible")

    freshness = object_(document.get("freshness_audit"), "freshness audit")
    if str(freshness.get("status") or "") != "PASS":
        raise PreflightError("freshness audit is not PASS")
    if integer(freshness.get("ticker_count")) != int(THRESHOLDS["ticker_count"]):
        raise PreflightError("freshness audit ticker count is not 20")
    if integer(freshness.get("evidence_qualified_candidate_count"), -1) != strict_declared:
        raise PreflightError("strict publication count disagrees with freshness audit")
    if integer(freshness.get("limited_research_candidate_count"), -1) != limited_declared:
        raise PreflightError("LIMITED publication count disagrees with freshness audit")
    if freshness.get("all_tickers_publication_provenance_multi_source") is not True:
        raise PreflightError("freshness audit lacks multi-source publication provenance")
    if freshness.get("all_positive_advantages_fresh_multi_source") is not True:
        raise PreflightError("positive advantages lack fresh multi-source support")

    strict_count = 0
    limited_count = 0
    high_count = 0
    for index, raw_record in enumerate(records):
        record = object_(raw_record, f"source record {index + 1}")
        metrics = object_(record.get("source_metrics"), "source metrics")
        logic = object_(record.get("public_logic_state"), "public logic state")
        state = object_(record.get("freshness_state"), "freshness state")
        mode = record_mode(record)
        ticker = order[index]
        if str(record.get("ticker") or "").strip().upper() != ticker:
            raise PreflightError(f"source record order mismatch at {ticker}")
        if str(state.get("status") or "") != "PASS":
            raise PreflightError(f"{ticker}: freshness state is not PASS")
        if record.get("eligible_for_high_confidence_model_inference") is True:
            high_count += 1
        positives = sensitive_positive_factors(top20[index])

        if mode == EVIDENCE_QUALIFIED:
            strict_count += 1
            if integer(metrics.get("claim_relevant_independent_families")) < int(THRESHOLDS["min_evidence_claim_families"]):
                raise PreflightError(f"{ticker}: EVIDENCE_QUALIFIED has fewer than two claim families")
            if integer(metrics.get("claim_relevant_independent_domains")) < int(THRESHOLDS["min_evidence_claim_domains"]):
                raise PreflightError(f"{ticker}: EVIDENCE_QUALIFIED has fewer than two claim domains")
            if integer(metrics.get("claim_relevant_primary_sources")) < int(THRESHOLDS["min_evidence_primary_sources"]):
                raise PreflightError(f"{ticker}: EVIDENCE_QUALIFIED has no primary claim source")
            if number(metrics.get("claim_dated_evidence_ratio")) < number(THRESHOLDS["min_claim_dated_evidence_ratio"]):
                raise PreflightError(f"{ticker}: EVIDENCE_QUALIFIED dated-evidence ratio is below 80%")
        elif mode == LIMITED:
            limited_count += 1
            if integer(state.get("claim_primary_units")) < int(THRESHOLDS["min_limited_claim_primary_units"]):
                raise PreflightError(f"{ticker}: LIMITED candidate lacks primary company evidence")
            if integer(state.get("publication_provenance_origin_count")) < int(THRESHOLDS["min_publication_provenance_origins"]):
                raise PreflightError(f"{ticker}: LIMITED candidate has one publication origin")
            if integer(state.get("publication_provenance_domain_count")) < int(THRESHOLDS["min_publication_provenance_domains"]):
                raise PreflightError(f"{ticker}: LIMITED candidate has one publication domain")
            if record.get("eligible_for_high_confidence_model_inference") is not False:
                raise PreflightError(f"{ticker}: LIMITED candidate is HIGH eligible")
            if str(logic.get("model_inference_confidence") or "") != "LIMITED":
                raise PreflightError(f"{ticker}: LIMITED candidate confidence is not capped")
            if logic.get("validated_company_thesis") is not False:
                raise PreflightError(f"{ticker}: LIMITED candidate is a validated thesis")
            missing = {
                str(item)
                for item in array(record.get("missing_or_review"), "missing_or_review")
            }
            if not LIMITED_MISSING_CODES.issubset(missing):
                raise PreflightError(f"{ticker}: LIMITED disclosure codes are missing")
            if positives:
                raise PreflightError(
                    f"{ticker}: LIMITED candidate retains positive sensitive factors: "
                    + ",".join(positives)
                )
        else:
            raise PreflightError(f"{ticker}: unknown publication mode {mode!r}")

    if strict_count != strict_declared or limited_count != limited_declared:
        raise PreflightError("record publication modes disagree with portfolio counts")
    declared_high = integer(portfolio.get("high_confidence_model_inference_eligible_count"))
    if high_count != declared_high:
        raise PreflightError("HIGH-eligibility count disagrees with record truth")
    if limited_count and high_count:
        # Mixed bundles may contain strict HIGH rows, but every HIGH row must be
        # EVIDENCE_QUALIFIED.  Verify that directly instead of globally blocking.
        for record in records:
            row = object_(record, "source record")
            if row.get("eligible_for_high_confidence_model_inference") is True and record_mode(row) != EVIDENCE_QUALIFIED:
                raise PreflightError("a non-strict publication row is HIGH eligible")

    return {
        "evidence_qualified_candidate_count": strict_count,
        "limited_research_candidate_count": limited_count,
        "high_confidence_eligible_count": high_count,
        "non_yahoo_market_coverage_ratio": coverage,
        "market_quality_degraded": degraded,
    }


def validate_bundle(bundle_path: Path, now: datetime | None = None) -> dict[str, Any]:
    try:
        root = json.loads(bundle_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PreflightError(f"unable to read activation bundle: {bundle_path}") from exc
    root = object_(root, "activation bundle")
    if set(root) != {
        "schema_version",
        "product_version",
        "transaction_id",
        "run_id",
        "generated_at",
        "public_data_as_of",
        "payloads",
        "sha256",
    }:
        raise PreflightError("activation bundle keys are not exact")
    if integer(root.get("schema_version")) != SCHEMA_VERSION:
        raise PreflightError("activation bundle schema_version is not 4")
    if str(root.get("product_version") or "") != PRODUCT_VERSION:
        raise PreflightError("activation bundle product_version is invalid")
    transaction_id = str(root.get("transaction_id") or "")
    run_id = str(root.get("run_id") or "")
    if not TRANSACTION_ID_RE.fullmatch(transaction_id):
        raise PreflightError("activation transaction_id is invalid")
    if not RUN_ID_RE.fullmatch(run_id):
        raise PreflightError("activation run_id is invalid")
    evaluated_at = now or datetime.now(timezone.utc)
    ages = validate_freshness(root, evaluated_at)

    payloads = object_(root.get("payloads"), "activation payloads")
    digests = object_(root.get("sha256"), "activation digests")
    if set(payloads) != PAYLOAD_NAMES or set(digests) != PAYLOAD_NAMES:
        raise PreflightError("activation payload names are not exact")
    for name in sorted(PAYLOAD_NAMES):
        body = payloads.get(name)
        expected = str(digests.get(name) or "").lower()
        if not isinstance(body, str):
            raise PreflightError(f"{name} is not text")
        if not HEX64_RE.fullmatch(expected):
            raise PreflightError(f"{name} digest is invalid")
        if sha256_text(body) != expected:
            raise PreflightError(f"{name} digest mismatch")

    top20_raw = parse_json_text(payloads["top20_json"], "Top20")
    top20_list = array(top20_raw, "Top20")
    order = ticker_order(top20_list, "Top20")
    top20 = [object_(row, "Top20 row") for row in top20_list]
    for row in top20:
        if str(row.get("scoring_version") or "") != str(CONTRACT["scoring_version"]):
            raise PreflightError("Top20 contains a provisional or legacy scoring row")

    validate_source_plan(parse_json_text(payloads["source_plan_json"], "source plan"))
    report = payloads["report_text"]
    if len(report) < 200 or len(report) > 200_000:
        raise PreflightError("report_text length is outside the publication contract")
    for marker in CONTRACT["report_markers"]:
        if marker not in report:
            raise PreflightError(f"report_text lacks attestation marker: {marker}")

    v212 = object_(parse_json_text(payloads["v212_top20_report_json"], "v2.1.2 report"), "v2.1.2 report")
    v213 = object_(parse_json_text(payloads["v213_top20_report_json"], "v2.1.3 report"), "v2.1.3 report")
    if str(v212.get("product_version") or "") != "2.1.2":
        raise PreflightError("v2.1.2 report product_version is invalid")
    if str(v213.get("product_version") or "") != PRODUCT_VERSION:
        raise PreflightError("v2.1.3 report product_version is invalid")
    require_same_order(order, v212.get("records"), "v2.1.2 report")
    require_same_order(order, v213.get("records"), "v2.1.3 report")

    federation_result = validate_federation(
        parse_json_text(payloads["source_federation_json"], "source federation"),
        order,
    )
    source_result = validate_source_audit(
        parse_json_text(payloads["source_independence_json"], "source independence"),
        order,
        top20,
    )
    return {
        "schema_version": 1,
        "status": "PASS",
        "product_version": PRODUCT_VERSION,
        "policy": "r75-sealed-publication-mode-preflight-v1",
        "publication_mode_contract_id": str(CONTRACT["contract_id"]),
        "publication_mode_contract_sha256": contract_sha256(),
        "bundle_path": str(bundle_path.resolve()),
        "bundle_sha256": sha256_file(bundle_path),
        "transaction_id": transaction_id,
        "run_id": run_id,
        "evaluated_at": evaluated_at.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "input_age_seconds": ages,
        "ticker_count": int(THRESHOLDS["ticker_count"]),
        **federation_result,
        **source_result,
        "production_mutation": False,
    }


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="\n",
        delete=False,
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        pending = Path(handle.name)
    pending.replace(path)


def synthetic_bundle(now: datetime | None = None) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    stamp = current.isoformat().replace("+00:00", "Z")
    order = [f"T{index:02d}" for index in range(20)]
    top20 = []
    records = []
    for rank, ticker in enumerate(order, 1):
        top20.append(
            {
                "rank": rank,
                "ticker": ticker,
                "scoring_version": str(CONTRACT["scoring_version"]),
                "serenity_factors": {
                    "demand_wave": 0,
                    "chokepoint": 0,
                    "pricing_power": 0,
                    "replacement_friction": 0,
                    "tam_capture": 0,
                    "valuation_expectations": 3.75,
                },
            }
        )
        records.append(
            {
                "rank": rank,
                "ticker": ticker,
                "publication_evidence_mode": LIMITED,
                "source_metrics": {
                    "claim_relevant_independent_families": 1,
                    "claim_relevant_independent_domains": 1,
                    "claim_relevant_primary_sources": 1,
                    "claim_dated_evidence_ratio": 1.0,
                },
                "market_corroboration": {
                    "status": "UNAVAILABLE",
                    "independent_provider_count": 0,
                },
                "public_logic_state": {
                    "publication_evidence_mode": LIMITED,
                    "model_inference_confidence": "LIMITED",
                    "validated_company_thesis": False,
                },
                "freshness_state": {
                    "status": "PASS",
                    "publication_evidence_mode": LIMITED,
                    "claim_primary_units": 1,
                    "publication_provenance_origin_count": 2,
                    "publication_provenance_domain_count": 2,
                },
                "missing_or_review": sorted(LIMITED_MISSING_CODES | {"NON_YAHOO_MARKET_CORROBORATION"}),
                "eligible_for_high_confidence_model_inference": False,
            }
        )
    report_records = [
        {"rank": rank, "ticker": ticker}
        for rank, ticker in enumerate(order, 1)
    ]
    plan = {
        "schema_version": 1,
        "catalog_count": 101,
        "automatic_activation": False,
        "provider_scope": "public_only",
        "owner_watchlist_inherited": False,
        "line_public_eligible": True,
        "inventory": {"source_count": 101, "runtime_enabled_count": 0},
        "live_source_federation": {
            "successful_families": ["us_sec", "nasdaq", "world_bank", "ecb"],
            "official_successful_families": ["us_sec", "nasdaq", "world_bank", "ecb"],
            "ticker_coverage_ratio": 1.0,
            "unresolved_material_conflict_count": 0,
            "yahoo_authoritative": False,
            "catalog_source_count_is_not_live_use": True,
        },
        "scoring_methodology": {
            "scoring_version": CONTRACT["scoring_version"],
            "official_serenity_formula_claimed": False,
            "private_process_reproduction_claimed": False,
        },
    }
    federation = {
        "schema_version": 1,
        "product_version": PRODUCT_VERSION,
        "generated_at": stamp,
        "ticker_sources": report_records,
        "gates": {
            "pass": True,
            "successful_families": ["us_sec", "nasdaq", "world_bank", "ecb", "gleif"],
            "official_successful_families": ["us_sec", "nasdaq", "world_bank", "ecb"],
            "missing_required_families": [],
            "ticker_coverage_ratio": 1.0,
            "unresolved_material_conflict_count": 0,
            "concentration_pass": True,
            "yahoo_authoritative": False,
            "catalog_source_count_is_not_live_use": True,
        },
    }
    source = {
        "schema_version": 3,
        "product_version": PRODUCT_VERSION,
        "generated_at": stamp,
        "status": "PASS",
        "quality_status": "PASS_WITH_DEGRADATION",
        "violations": [],
        "blocking_violations": [],
        "degradations": [MARKET_DEGRADATION],
        "portfolio": {
            "independent_source_families": 3,
            "independent_domains": 4,
            "claim_primary_coverage_ratio": 1.0,
            "claim_source_families": 1,
            "claim_source_domains": 1,
            "maximum_single_family_share": 0.5,
            "market_conflict_ticker_count": 0,
            "non_yahoo_market_coverage_ratio": 0.0,
            "non_yahoo_market_coverage_target_ratio": 0.75,
            "market_corroboration_status": "DEGRADED",
            "market_corroboration_global_blocker": False,
            "evidence_qualified_candidate_count": 0,
            "limited_research_candidate_count": 20,
            "all_rows_publication_provenance_multi_source": True,
            "limited_rows_high_confidence_eligible_count": 0,
            "high_confidence_model_inference_eligible_count": 0,
        },
        "methodology_notice": {
            "official_serenity_formula": False,
            "official_serenity_score": False,
            "private_method_reproduced": False,
            "single_source_inference_allowed": False,
            "source_diversity_is_not_truth_by_itself": True,
            "official_macro_is_not_company_claim_evidence": True,
            "market_corroboration_unavailable_is_global_blocker": False,
            "market_corroboration_required_for_high_confidence_model_inference": True,
            "market_corroboration_required_for_uncapped_valuation_factor": True,
            "provider_failure_must_be_disclosed": True,
            "market_data_is_not_averaged_into_published_returns": True,
        },
        "freshness_audit": {
            "status": "PASS",
            "ticker_count": int(THRESHOLDS["ticker_count"]),
            "evidence_qualified_candidate_count": 0,
            "limited_research_candidate_count": 20,
            "all_tickers_publication_provenance_multi_source": True,
            "all_positive_advantages_fresh_multi_source": True,
        },
        "records": records,
    }
    payloads = {
        "top20_json": json.dumps(top20, ensure_ascii=False, separators=(",", ":")),
        "source_plan_json": json.dumps(plan, ensure_ascii=False, separators=(",", ":")),
        "report_text": "\n".join(
            [
                "<!-- line-public-eligible: true -->",
                "<!-- provider-scope: public_only -->",
                "<!-- owner-watchlist-inherited: false -->",
                f"<!-- scoring-version: {CONTRACT['scoring_version']} -->",
                "<!-- official-serenity-formula-claimed: false -->",
                "# Synthetic R75 report",
                "Evidence-bound LIMITED research candidate report. " * 10,
            ]
        ),
        "v212_top20_report_json": json.dumps(
            {"product_version": "2.1.2", "records": report_records},
            separators=(",", ":"),
        ),
        "v213_top20_report_json": json.dumps(
            {"product_version": PRODUCT_VERSION, "records": report_records},
            separators=(",", ":"),
        ),
        "source_federation_json": json.dumps(federation, separators=(",", ":")),
        "source_independence_json": json.dumps(source, separators=(",", ":")),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "product_version": PRODUCT_VERSION,
        "transaction_id": "1" * 32,
        "run_id": current.strftime("%Y%m%dT%H%M%SZ-") + "123456789abc",
        "generated_at": stamp,
        "public_data_as_of": stamp,
        "payloads": payloads,
        "sha256": {name: sha256_text(body) for name, body in payloads.items()},
    }


def validate_fixture(path: Path) -> dict[str, Any]:
    fixture = object_(json.loads(path.read_text(encoding="utf-8-sig")), "fixture")
    if fixture.get("schema_version") != 1 or fixture.get("contract_id") != CONTRACT["contract_id"]:
        raise PreflightError("fixture contract identity is invalid")
    if fixture.get("contract_sha256") != contract_sha256():
        raise PreflightError("fixture contract hash is invalid")
    evaluated_at = timestamp(fixture.get("evaluated_at"), "fixture evaluated_at")
    bundle = object_(fixture.get("bundle"), "fixture bundle")
    expected = object_(fixture.get("expected"), "fixture expected")
    with tempfile.TemporaryDirectory(prefix="v213-r75-fixture-") as directory:
        bundle_path = Path(directory) / "bundle.json"
        bundle_path.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
        receipt = validate_bundle(bundle_path, evaluated_at)
    observed = {
        "status": receipt["status"],
        "evidence_qualified": receipt["evidence_qualified_candidate_count"],
        "limited": receipt["limited_research_candidate_count"],
        "high_eligible": receipt["high_confidence_eligible_count"],
        "bls_present": receipt["bls_present"],
    }
    if observed != dict(expected):
        raise PreflightError(f"fixture result mismatch: {path.name}")
    return {**observed, "fixture": str(path), "contract_sha256": contract_sha256()}


def self_test() -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    with tempfile.TemporaryDirectory(prefix="v213-r75-preflight-") as directory:
        path = Path(directory) / "bundle.json"
        value = synthetic_bundle(now)
        path.write_text(json.dumps(value), encoding="utf-8")
        receipt = validate_bundle(path, now)
        assert receipt["status"] == "PASS"
        assert receipt["limited_research_candidate_count"] == 20
        assert receipt["evidence_qualified_candidate_count"] == 0
        assert receipt["bls_present"] is False

        positive = copy.deepcopy(value)
        rows = json.loads(positive["payloads"]["top20_json"])
        rows[0]["serenity_factors"]["demand_wave"] = 1
        body = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
        positive["payloads"]["top20_json"] = body
        positive["sha256"]["top20_json"] = sha256_text(body)
        path.write_text(json.dumps(positive), encoding="utf-8")
        try:
            validate_bundle(path, now)
        except PreflightError as exc:
            assert "positive sensitive factors" in str(exc)
        else:
            raise AssertionError("LIMITED positive factor was not rejected")

        high = copy.deepcopy(value)
        source = json.loads(high["payloads"]["source_independence_json"])
        source["records"][0]["eligible_for_high_confidence_model_inference"] = True
        source["portfolio"]["limited_rows_high_confidence_eligible_count"] = 1
        source["portfolio"]["high_confidence_model_inference_eligible_count"] = 1
        body = json.dumps(source, separators=(",", ":"))
        high["payloads"]["source_independence_json"] = body
        high["sha256"]["source_independence_json"] = sha256_text(body)
        path.write_text(json.dumps(high), encoding="utf-8")
        try:
            validate_bundle(path, now)
        except PreflightError as exc:
            assert "LIMITED" in str(exc)
        else:
            raise AssertionError("LIMITED HIGH eligibility was not rejected")

        single = copy.deepcopy(value)
        source = json.loads(single["payloads"]["source_independence_json"])
        source["records"][0]["freshness_state"]["publication_provenance_origin_count"] = 1
        body = json.dumps(source, separators=(",", ":"))
        single["payloads"]["source_independence_json"] = body
        single["sha256"]["source_independence_json"] = sha256_text(body)
        path.write_text(json.dumps(single), encoding="utf-8")
        try:
            validate_bundle(path, now)
        except PreflightError as exc:
            assert "publication origin" in str(exc)
        else:
            raise AssertionError("single-origin LIMITED candidate was not rejected")

        def rewrite_payload(candidate: dict[str, Any], name: str, document: Any) -> None:
            body = json.dumps(document, ensure_ascii=False, separators=(",", ":"))
            candidate["payloads"][name] = body
            candidate["sha256"][name] = sha256_text(body)

        def rejected(candidate: dict[str, Any], expected: str) -> None:
            path.write_text(json.dumps(candidate), encoding="utf-8")
            try:
                validate_bundle(path, now)
            except PreflightError as exc:
                if expected not in str(exc):
                    raise AssertionError(f"expected {expected!r}, observed {exc!r}") from exc
            else:
                raise AssertionError(f"unsafe invariant was accepted: {expected}")

        negative_factor = copy.deepcopy(value)
        rows = json.loads(negative_factor["payloads"]["top20_json"])
        rows[0]["serenity_factors"]["demand_wave"] = -1
        rewrite_payload(negative_factor, "top20_json", rows)
        path.write_text(json.dumps(negative_factor), encoding="utf-8")
        assert validate_bundle(path, now)["status"] == "PASS"

        thesis = copy.deepcopy(value)
        source = json.loads(thesis["payloads"]["source_independence_json"])
        source["records"][0]["public_logic_state"]["validated_company_thesis"] = True
        rewrite_payload(thesis, "source_independence_json", source)
        rejected(thesis, "validated thesis")

        provenance_domain = copy.deepcopy(value)
        source = json.loads(provenance_domain["payloads"]["source_independence_json"])
        source["records"][0]["freshness_state"]["publication_provenance_domain_count"] = 1
        rewrite_payload(provenance_domain, "source_independence_json", source)
        rejected(provenance_domain, "publication domain")

        count = copy.deepcopy(value)
        source = json.loads(count["payloads"]["source_independence_json"])
        source["portfolio"]["limited_research_candidate_count"] = 19
        rewrite_payload(count, "source_independence_json", source)
        rejected(count, "do not total")

        ordering = copy.deepcopy(value)
        source = json.loads(ordering["payloads"]["source_independence_json"])
        source["records"][0], source["records"][1] = source["records"][1], source["records"][0]
        rewrite_payload(ordering, "source_independence_json", source)
        rejected(ordering, "rank")

        freshness = copy.deepcopy(value)
        source = json.loads(freshness["payloads"]["source_independence_json"])
        source["records"][0]["freshness_state"]["status"] = "STALE"
        rewrite_payload(freshness, "source_independence_json", source)
        rejected(freshness, "freshness state")

        bad_digest = copy.deepcopy(value)
        bad_digest["sha256"]["top20_json"] = "0" * 64
        rejected(bad_digest, "digest mismatch")

        stale = copy.deepcopy(value)
        stale["generated_at"] = "2020-01-01T00:00:00Z"
        rejected(stale, "stale")

        mixed_fixture = json.loads((ROOT / CONTRACT["fixture_files"][1]).read_text(encoding="utf-8"))
        mixed_bundle = mixed_fixture["bundle"]
        mixed_now = timestamp(mixed_fixture["evaluated_at"], "mixed evaluated_at")
        for field, invalid in (
            ("claim_relevant_independent_families", 1),
            ("claim_relevant_independent_domains", 1),
            ("claim_relevant_primary_sources", 0),
            ("claim_dated_evidence_ratio", 0.79),
        ):
            strict = copy.deepcopy(mixed_bundle)
            source = json.loads(strict["payloads"]["source_independence_json"])
            source["records"][1]["source_metrics"][field] = invalid
            rewrite_payload(strict, "source_independence_json", source)
            path.write_text(json.dumps(strict), encoding="utf-8")
            try:
                validate_bundle(path, mixed_now)
            except PreflightError as exc:
                assert "EVIDENCE_QUALIFIED" in str(exc)
            else:
                raise AssertionError(f"strict metric was accepted: {field}")

    for relative in CONTRACT["fixture_files"]:
        validate_fixture(ROOT / relative)

    print(
        "V213_R75_ACTIVATION_PREFLIGHT_SELF_TEST = PASS; "
        "all_limited=true; optional_bls=true; positive_limited_rejected=true; "
        "limited_high_rejected=true; single_origin_rejected=true; "
        "validated_thesis_rejected=true; strict_metrics_rejected=true; "
        "count_order_freshness_digest_rejected=true; negative_factor_pass=true; "
        "production_mutation=false"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bundle",
        type=Path,
        default=Path("data/cache/v213_activation_bundle_upload.json"),
    )
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--print-contract-hash", action="store_true")
    args = parser.parse_args()
    if args.print_contract_hash:
        print(contract_sha256())
        return 0
    if args.fixture:
        result = validate_fixture(args.fixture)
        print("V213_R75_PUBLICATION_FIXTURE = PASS; " + json.dumps(result, sort_keys=True))
        return 0
    if args.self_test:
        self_test()
        return 0
    receipt = validate_bundle(args.bundle)
    if args.receipt:
        atomic_json(args.receipt, receipt)
    print(
        "V213_R75_ACTIVATION_PREFLIGHT = PASS; "
        f"run_id={receipt['run_id']}; transaction_id={receipt['transaction_id']}; "
        f"evidence_qualified={receipt['evidence_qualified_candidate_count']}; "
        f"limited={receipt['limited_research_candidate_count']}; "
        f"families={receipt['successful_family_count']}; "
        f"official={receipt['official_family_count']}; "
        f"bls_present={str(receipt['bls_present']).lower()}; "
        "production_mutation=false",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (PreflightError, OSError, ValueError) as exc:
        print(f"V213_R75_ACTIVATION_PREFLIGHT = FAIL; {exc}", flush=True)
        raise SystemExit(1)
