#!/usr/bin/env python3
"""Build a signed-upload-ready, public-only v2.1 LINE snapshot envelope."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
TOP20_PATH = ROOT / "data" / "cache" / "top20_public_latest.json"
PLAN_PATH = ROOT / "data" / "cache" / "source_plan_public_latest.json"
METADATA_PATH = ROOT / "data" / "cache" / "public_snapshot_metadata.json"
REPORT_PATH = ROOT / "reports" / "public_briefing_latest.md"
OUTPUT_PATH = ROOT / "data" / "cache" / "v21_public_snapshot_upload.json"

PRIVATE_KEYS = {
    "account",
    "account_id",
    "portfolio",
    "position",
    "positions",
    "holding",
    "holdings",
    "cost_basis",
    "pnl",
    "line_user_id",
    "raw_user_id",
    "tenant_id",
    "conversation",
    "private_message",
    "brokerage",
    "ibkr",
    "secret",
    "token",
}

RECORD_KEYS = {
    "ticker", "name", "serenity_score", "serenity_raw_score", "risk_penalty",
    "data_quality", "rating", "category", "serenity_factors", "risk_flags",
    "aschenbrenner_overlay", "evidence", "evidence_count", "source_count",
    "scoring_version", "line_public_eligible", "provider_scope",
    "owner_watchlist_inherited", "rank", "generated_at", "as_of",
}

REPORT_PREFIX = "\n".join((
    "<!-- line-public-eligible: true -->",
    "<!-- provider-scope: public_only -->",
    "<!-- owner-watchlist-inherited: false -->",
    "<!-- scoring-version: serenity-first-v2.1.0 -->",
    "",
))

class SnapshotError(RuntimeError):
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
        raise SnapshotError(f"Invalid JSON input: {path}") from exc


def iso_timestamp(value: Any, label: str) -> str:
    text = str(value or "").strip()
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SnapshotError(f"Invalid timestamp: {label}") from exc
    return text


def reject_private_keys(value: Any, path: str = "$") -> None:
    if isinstance(value, list):
        for index, item in enumerate(value):
            reject_private_keys(item, f"{path}[{index}]")
        return
    if not isinstance(value, dict):
        return
    for key, child in value.items():
        normalized = str(key).casefold()
        public_catalog_topic = path == "$.inventory.topic_counts" and normalized == "positions"
        if normalized in PRIVATE_KEYS and not public_catalog_topic:
            raise SnapshotError(f"Forbidden public key at {path}: {key}")
        reject_private_keys(child, f"{path}.{key}")


def validate_top20(records: Any) -> list[dict[str, Any]]:
    if not isinstance(records, list) or len(records) != 20:
        raise SnapshotError("Top 20 must contain exactly 20 records")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(records, start=1):
        if not isinstance(raw, dict) or set(raw) != RECORD_KEYS:
            raise SnapshotError(f"Top 20 record {index} has an invalid closed schema")
        ticker = str(raw.get("ticker") or "").upper()
        if not ticker or ticker in seen:
            raise SnapshotError("Top 20 tickers must be unique")
        seen.add(ticker)
        if raw.get("rank") != index:
            raise SnapshotError("Top 20 ranks must be exactly 1..20")
        for key in ("serenity_score", "serenity_raw_score", "risk_penalty", "data_quality"):
            value = raw.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise SnapshotError(f"Top 20 {ticker} has invalid numeric field {key}")
        if not 0 <= float(raw["serenity_score"]) <= 100:
            raise SnapshotError(f"Top 20 {ticker} score is outside 0..100")
        if not 0 <= float(raw["data_quality"]) <= 1:
            raise SnapshotError(f"Top 20 {ticker} data quality is outside 0..1")
        if (
            raw.get("scoring_version") != "serenity-first-v2.1.0"
            or raw.get("line_public_eligible") is not True
            or raw.get("provider_scope") != "public_only"
            or raw.get("owner_watchlist_inherited") is not False
        ):
            raise SnapshotError(f"Top 20 {ticker} public boundary is invalid")
        overlay = raw.get("aschenbrenner_overlay")
        if not isinstance(overlay, dict) or overlay.get("included_in_serenity_score") is not False:
            raise SnapshotError(f"Top 20 {ticker} overlay boundary is invalid")
        evidence = raw.get("evidence")
        if not isinstance(evidence, list) or not evidence or raw.get("evidence_count") != len(evidence):
            raise SnapshotError(f"Top 20 {ticker} evidence is invalid")
        iso_timestamp(raw.get("generated_at"), f"{ticker}.generated_at")
        iso_timestamp(raw.get("as_of"), f"{ticker}.as_of")
        result.append({**raw, "ticker": ticker})
    expected = sorted(
        result,
        key=lambda item: (
            -float(item["serenity_score"]),
            -float(item["data_quality"]),
            str(item["ticker"]),
        ),
    )
    if result != expected:
        raise SnapshotError("Top 20 ordering is not deterministic")
    reject_private_keys(result)
    return result


def validate_plan(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SnapshotError("Source plan must be an object")
    inventory = value.get("inventory")
    if (
        value.get("schema_version") != 1
        or value.get("catalog_count") != 101
        or value.get("automatic_activation") is not False
        or value.get("owner_watchlist_inherited") is not False
        or value.get("provider_scope") != "public_only"
        or value.get("line_public_eligible") is not True
        or not isinstance(inventory, dict)
        or inventory.get("source_count") != 101
        or inventory.get("runtime_enabled_count") != 0
    ):
        raise SnapshotError("Source plan does not preserve the reviewed 101-source fail-closed boundary")
    reject_private_keys(value)
    return value


def build_envelope(
    *,
    top20_path: Path = TOP20_PATH,
    plan_path: Path = PLAN_PATH,
    metadata_path: Path = METADATA_PATH,
    report_path: Path = REPORT_PATH,
) -> dict[str, Any]:
    top20 = validate_top20(load_json(top20_path))
    plan = validate_plan(load_json(plan_path))
    metadata = load_json(metadata_path)
    if not isinstance(metadata, dict):
        raise SnapshotError("Public snapshot metadata must be an object")
    if (
        metadata.get("line_public_eligible") is not True
        or metadata.get("provider_scope") != "public_only"
        or metadata.get("owner_watchlist_inherited") is not False
    ):
        raise SnapshotError("Public snapshot metadata boundary is invalid")
    public_as_of = iso_timestamp(
        metadata.get("last_successful_pipeline_timestamp"),
        "last_successful_pipeline_timestamp",
    )
    try:
        report_body = report_path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise SnapshotError(f"Unable to read public report: {report_path}") from exc
    report = REPORT_PREFIX + report_body.lstrip("\ufeff")
    top20_json = canonical_json(top20)
    plan_json = canonical_json(plan)
    material = "\n".join((top20_json, plan_json, report, public_as_of))
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + hashlib.sha256(
        material.encode("utf-8")
    ).hexdigest()[:12]
    generated = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    payloads = {
        "top20_json": top20_json,
        "source_plan_json": plan_json,
        "report_text": report,
    }
    return {
        "schema_version": 1,
        "run_id": run_id,
        "generated_at": generated,
        "public_data_as_of": public_as_of,
        "payloads": payloads,
        "sha256": {
            name: hashlib.sha256(content.encode("utf-8")).hexdigest()
            for name, content in payloads.items()
        },
    }


def atomic_write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def synthetic_record(index: int, generated: str) -> dict[str, Any]:
    ticker = f"T{index:02d}"
    score = 98 - index
    evidence = [{
        "source_id": "sec_edgar",
        "tier": "T0",
        "claim_type": "xbrl_fact",
        "title": f"Synthetic SEC fact {ticker}",
        "url": f"https://www.sec.gov/Archives/edgar/data/{1000000 + index}/synthetic.htm",
        "as_of": "2026-06-30T00:00:00+00:00",
    }]
    return {
        "ticker": ticker,
        "name": f"Synthetic Company {index}",
        "serenity_score": score,
        "serenity_raw_score": score,
        "risk_penalty": 0,
        "data_quality": 1.0,
        "rating": "S",
        "category": "Synthetic",
        "serenity_factors": {
            "demand_wave": 15,
            "chokepoint": 13,
            "pricing_power": 15,
            "replacement_friction": 10,
            "tam_capture": 15,
            "valuation_expectations": 15,
            "evidence_quality": 15,
        },
        "risk_flags": [],
        "aschenbrenner_overlay": {
            "domain": "C",
            "fit_score": 20,
            "included_in_serenity_score": False,
            "attribution": "system_operationalization_not_aschenbrenner_stock_score",
        },
        "evidence": evidence,
        "evidence_count": len(evidence),
        "source_count": 2,
        "scoring_version": "serenity-first-v2.1.0",
        "line_public_eligible": True,
        "provider_scope": "public_only",
        "owner_watchlist_inherited": False,
        "rank": index + 1,
        "generated_at": generated,
        "as_of": "2026-06-30T00:00:00+00:00",
    }


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="ii-v21-public-snapshot-") as temporary:
        root = Path(temporary)
        generated = "2026-08-30T00:00:00Z"
        top = [synthetic_record(index, generated) for index in range(20)]
        plan = {
            "schema_version": 1,
            "catalog_count": 101,
            "automatic_activation": False,
            "owner_watchlist_inherited": False,
            "provider_scope": "public_only",
            "line_public_eligible": True,
            "inventory": {
                "source_count": 101,
                "runtime_enabled_count": 0,
                "topic_counts": {"positions": 1},
            },
        }
        metadata = {
            "schema_version": 1,
            "last_successful_pipeline_timestamp": generated,
            "line_public_eligible": True,
            "provider_scope": "public_only",
            "owner_watchlist_inherited": False,
        }
        top_path = root / "top.json"
        plan_path = root / "plan.json"
        metadata_path = root / "metadata.json"
        report_path = root / "report.md"
        top_path.write_text(json.dumps(top), encoding="utf-8")
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        report_path.write_text("# Synthetic public briefing\n" + "evidence\n" * 40, encoding="utf-8")
        envelope = build_envelope(
            top20_path=top_path,
            plan_path=plan_path,
            metadata_path=metadata_path,
            report_path=report_path,
        )
        if not str(envelope["run_id"]).startswith("20"):
            raise SnapshotError("Self-test run ID is invalid")
        for name, content in envelope["payloads"].items():
            if hashlib.sha256(content.encode("utf-8")).hexdigest() != envelope["sha256"][name]:
                raise SnapshotError("Self-test digest mismatch")
        compromised = json.loads(json.dumps(top))
        compromised[0]["portfolio"] = {"shares": 1}
        try:
            validate_top20(compromised)
        except SnapshotError:
            pass
        else:
            raise SnapshotError("Self-test did not reject a private field")
    print("V21_PUBLIC_SNAPSHOT_BUILDER_SELF_TEST = PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    envelope = build_envelope()
    atomic_write(args.output, envelope)
    print(json.dumps({
        "status": "PASS",
        "run_id": envelope["run_id"],
        "output": str(args.output),
        "top20_count": 20,
        "catalog_count": 101,
        "provider_scope": "public_only",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
