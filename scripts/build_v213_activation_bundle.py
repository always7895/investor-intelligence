#!/usr/bin/env python3
"""Build one signed-upload-ready v2.1.3 activation bundle.

The bundle keeps the diversified Top20, source plan, public report, v2.1.2
five-field report, v2.1.3 seven-field report, live-source federation and
claim-level source audit under one immutable run.  The Worker validates every
payload and writes ``snapshot:current`` last, so readers never observe a new
Top20 without its matching reports and evidence sidecars.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
V21_ENVELOPE_PATH = ROOT / "data" / "cache" / "v21_public_snapshot_upload.json"
V212_REPORT_PATH = ROOT / "data" / "cache" / "v212_top20_report_public_latest.json"
V213_REPORT_PATH = ROOT / "data" / "cache" / "v213_top20_report_public_latest.json"
FEDERATION_PATH = ROOT / "data" / "cache" / "v213_source_federation_latest.json"
SOURCE_AUDIT_PATH = ROOT / "data" / "cache" / "v213_source_independence_latest.json"
OUTPUT_PATH = ROOT / "data" / "cache" / "v213_activation_bundle_upload.json"

RUN_ID_RE = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{12}$")
SCORING_VERSION = "system-operationalization-v2.1.3-diversified"
PAYLOAD_NAMES = (
    "top20_json",
    "source_plan_json",
    "report_text",
    "v212_top20_report_json",
    "v213_top20_report_json",
    "source_federation_json",
    "source_independence_json",
)


class ActivationBundleError(RuntimeError):
    pass


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ActivationBundleError(f"Invalid JSON input: {path}") from exc


def timestamp(value: Any, label: str) -> str:
    text = str(value or "").strip()
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ActivationBundleError(f"Invalid timestamp: {label}") from exc
    return text


def ordered_tickers(rows: Any, label: str) -> list[str]:
    if not isinstance(rows, list) or len(rows) != 20:
        raise ActivationBundleError(f"{label} must contain exactly 20 rows")
    result: list[str] = []
    for index, raw in enumerate(rows, 1):
        if not isinstance(raw, dict):
            raise ActivationBundleError(f"{label} row must be an object")
        ticker = str(raw.get("ticker") or "").strip().upper()
        if not ticker or int(raw.get("rank") or 0) != index or ticker in result:
            raise ActivationBundleError(f"{label} ticker/rank contract failed")
        result.append(ticker)
    return result


def validate_inputs(
    envelope: Mapping[str, Any],
    v212: Mapping[str, Any],
    v213: Mapping[str, Any],
    federation: Mapping[str, Any],
    source_audit: Mapping[str, Any],
) -> tuple[str, list[str]]:
    if envelope.get("schema_version") != 1:
        raise ActivationBundleError("Diversified v2.1 snapshot envelope schema must be 1")
    run_id = str(envelope.get("run_id") or "")
    if not RUN_ID_RE.fullmatch(run_id):
        raise ActivationBundleError("Diversified v2.1 run_id is invalid")
    timestamp(envelope.get("generated_at"), "envelope.generated_at")
    timestamp(envelope.get("public_data_as_of"), "envelope.public_data_as_of")
    payloads = envelope.get("payloads")
    digests = envelope.get("sha256")
    if not isinstance(payloads, dict) or not isinstance(digests, dict):
        raise ActivationBundleError("Diversified v2.1 payload/digest objects are missing")
    if set(payloads) != {"top20_json", "source_plan_json", "report_text"}:
        raise ActivationBundleError("Diversified v2.1 payload keys are invalid")
    if set(digests) != set(payloads):
        raise ActivationBundleError("Diversified v2.1 digest keys are invalid")
    for name, body in payloads.items():
        if not isinstance(body, str):
            raise ActivationBundleError(f"Diversified payload {name} is not text")
        actual = hashlib.sha256(body.encode("utf-8")).hexdigest()
        if actual != str(digests.get(name) or ""):
            raise ActivationBundleError(f"Diversified payload digest mismatch: {name}")

    try:
        top20 = json.loads(str(payloads["top20_json"]))
        plan = json.loads(str(payloads["source_plan_json"]))
    except json.JSONDecodeError as exc:
        raise ActivationBundleError("Diversified Top20/source plan is invalid JSON") from exc
    order = ordered_tickers(top20, "Diversified Top20")
    if any(
        not isinstance(row, dict)
        or row.get("scoring_version") != SCORING_VERSION
        for row in top20
    ):
        raise ActivationBundleError("Top20 contains a provisional or legacy scoring row")
    if (
        not isinstance(plan, dict)
        or plan.get("catalog_count") != 101
        or plan.get("provider_scope") != "public_only"
        or plan.get("owner_watchlist_inherited") is not False
    ):
        raise ActivationBundleError("Diversified source plan boundary is invalid")

    if v212.get("product_version") != "2.1.2":
        raise ActivationBundleError("v2.1.2 report product version is invalid")
    if v213.get("product_version") != "2.1.3":
        raise ActivationBundleError("v2.1.3 report product version is invalid")
    if ordered_tickers(v212.get("records"), "v2.1.2 report") != order:
        raise ActivationBundleError("v2.1.2 report order does not match final Top20")
    if ordered_tickers(v213.get("records"), "v2.1.3 report") != order:
        raise ActivationBundleError("v2.1.3 report order does not match final Top20")

    gates = federation.get("gates")
    if (
        federation.get("schema_version") != 1
        or federation.get("product_version") != "2.1.3"
        or not isinstance(gates, dict)
        or gates.get("pass") is not True
        or int(gates.get("unresolved_material_conflict_count") or 0) != 0
    ):
        raise ActivationBundleError("Live source federation is not publishable")
    timestamp(federation.get("generated_at"), "source_federation.generated_at")
    if ordered_tickers(federation.get("ticker_sources"), "source federation") != order:
        raise ActivationBundleError("Source federation order does not match final Top20")

    portfolio = source_audit.get("portfolio")
    violations = source_audit.get("violations")
    blockers = source_audit.get("blocking_violations")
    if (
        int(source_audit.get("schema_version") or 0) < 3
        or source_audit.get("product_version") != "2.1.3"
        or source_audit.get("status") != "PASS"
        or not isinstance(violations, list)
        or violations
        or not isinstance(blockers, list)
        or blockers
        or not isinstance(portfolio, dict)
        or float(portfolio.get("claim_primary_coverage_ratio") or 0) < 0.75
        or int(portfolio.get("claim_source_families") or 0) < 2
        or int(portfolio.get("claim_source_domains") or 0) < 2
        or float(portfolio.get("maximum_single_family_share") or 1) > 0.70
        or int(portfolio.get("market_conflict_ticker_count") or 0) != 0
    ):
        raise ActivationBundleError("Claim-level source audit contains a blocking defect")
    timestamp(source_audit.get("generated_at"), "source_independence.generated_at")
    if ordered_tickers(source_audit.get("records"), "source independence") != order:
        raise ActivationBundleError("Source-independence order does not match final Top20")
    return run_id, order


def build_bundle(
    envelope: Mapping[str, Any],
    v212: Mapping[str, Any],
    v213: Mapping[str, Any],
    federation: Mapping[str, Any],
    source_audit: Mapping[str, Any],
) -> dict[str, Any]:
    run_id, _order = validate_inputs(envelope, v212, v213, federation, source_audit)
    original_payloads = envelope["payloads"]
    assert isinstance(original_payloads, dict)
    payloads = {
        "top20_json": str(original_payloads["top20_json"]),
        "source_plan_json": str(original_payloads["source_plan_json"]),
        "report_text": str(original_payloads["report_text"]),
        "v212_top20_report_json": canonical_json(v212),
        "v213_top20_report_json": canonical_json(v213),
        "source_federation_json": canonical_json(federation),
        "source_independence_json": canonical_json(source_audit),
    }
    digests = {
        name: hashlib.sha256(body.encode("utf-8")).hexdigest()
        for name, body in payloads.items()
    }
    material = "\n".join([run_id, *[digests[name] for name in PAYLOAD_NAMES]])
    transaction_id = hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]
    return {
        "schema_version": 4,
        "product_version": "2.1.3",
        "transaction_id": transaction_id,
        "run_id": run_id,
        "generated_at": str(envelope["generated_at"]),
        "public_data_as_of": str(envelope["public_data_as_of"]),
        "payloads": payloads,
        "sha256": digests,
    }


def atomic_write(path: Path, value: Mapping[str, Any]) -> None:
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
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def self_test() -> None:
    generated = "2026-09-02T00:00:00Z"
    run_id = "20260902T000000Z-123456789abc"
    rows = [
        {
            "rank": index + 1,
            "ticker": f"T{index:02d}",
            "scoring_version": SCORING_VERSION,
        }
        for index in range(20)
    ]
    plan = {
        "catalog_count": 101,
        "provider_scope": "public_only",
        "owner_watchlist_inherited": False,
    }
    base_payloads = {
        "top20_json": canonical_json(rows),
        "source_plan_json": canonical_json(plan),
        "report_text": "x",
    }
    envelope = {
        "schema_version": 1,
        "run_id": run_id,
        "generated_at": generated,
        "public_data_as_of": generated,
        "payloads": base_payloads,
        "sha256": {
            name: hashlib.sha256(body.encode("utf-8")).hexdigest()
            for name, body in base_payloads.items()
        },
    }
    v212 = {"product_version": "2.1.2", "records": rows}
    v213 = {"product_version": "2.1.3", "records": rows}
    federation = {
        "schema_version": 1,
        "product_version": "2.1.3",
        "generated_at": generated,
        "ticker_sources": rows,
        "gates": {"pass": True, "unresolved_material_conflict_count": 0},
    }
    source = {
        "schema_version": 3,
        "product_version": "2.1.3",
        "generated_at": generated,
        "status": "PASS",
        "violations": [],
        "blocking_violations": [],
        "portfolio": {
            "claim_primary_coverage_ratio": 1.0,
            "claim_source_families": 2,
            "claim_source_domains": 2,
            "maximum_single_family_share": 0.5,
            "market_conflict_ticker_count": 0,
        },
        "records": rows,
    }
    bundle = build_bundle(envelope, v212, v213, federation, source)
    assert bundle["schema_version"] == 4
    assert bundle["run_id"] == run_id
    assert re.fullmatch(r"[0-9a-f]{32}", str(bundle["transaction_id"]))
    assert set(bundle["payloads"]) == set(PAYLOAD_NAMES)
    for name, body in bundle["payloads"].items():
        assert hashlib.sha256(body.encode("utf-8")).hexdigest() == bundle["sha256"][name]
    print("V213_ACTIVATION_BUNDLE_BUILDER_SELF_TEST = PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v21-envelope", type=Path, default=V21_ENVELOPE_PATH)
    parser.add_argument("--v212-report", type=Path, default=V212_REPORT_PATH)
    parser.add_argument("--v213-report", type=Path, default=V213_REPORT_PATH)
    parser.add_argument("--source-federation", type=Path, default=FEDERATION_PATH)
    parser.add_argument("--source-independence", type=Path, default=SOURCE_AUDIT_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    bundle = build_bundle(
        load_json(args.v21_envelope),
        load_json(args.v212_report),
        load_json(args.v213_report),
        load_json(args.source_federation),
        load_json(args.source_independence),
    )
    atomic_write(args.output, bundle)
    print(
        "V213_ACTIVATION_BUNDLE = PASS; "
        f"run_id={bundle['run_id']}; transaction_id={bundle['transaction_id']}; "
        f"payloads={len(bundle['payloads'])}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ActivationBundleError, OSError, ValueError) as exc:
        print(f"V213_ACTIVATION_BUNDLE = FAIL; {exc}", flush=True)
        raise SystemExit(1)
