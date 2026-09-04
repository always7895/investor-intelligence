#!/usr/bin/env python3
"""Build the v2.1.1 signed public snapshot envelope.

Schema v2 keeps the accepted v2.1 Top 20/source-plan/report payloads and adds an
owner-independent scored research universe plus public-only option observations.
No portfolio, brokerage, LINE identity, tenant identity or secret is eligible.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import build_v21_public_snapshot as base

UNIVERSE_PATH = ROOT / "data" / "cache" / "research_universe_public_latest.json"
OPTIONS_PATH = ROOT / "data" / "cache" / "options_public_latest.json"
OUTPUT_PATH = ROOT / "data" / "cache" / "v211_public_snapshot_upload.json"

OPTION_RECORD_KEYS = {
    "schema_version", "ticker", "provider_symbol", "currency", "current_price",
    "retrieved_at", "status", "quote_source", "quote_delay_status",
    "provider_scope", "line_public_eligible", "ibkr_connected",
    "brokerage_data_included", "account_data_included", "position_data_included",
    "owner_watchlist_inherited", "periods",
}


class SnapshotV211Error(RuntimeError):
    pass


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def validate_universe(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not 20 <= len(raw) <= 120:
        raise SnapshotV211Error("Research universe must contain 20..120 scored records")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict) or set(item) != base.RECORD_KEYS:
            raise SnapshotV211Error(f"Research-universe record {index} has an invalid closed schema")
        ticker = str(item.get("ticker") or "").upper()
        if not ticker or ticker in seen or item.get("rank") != index:
            raise SnapshotV211Error("Research-universe ticker/rank integrity failed")
        seen.add(ticker)
        if (
            not _finite(item.get("serenity_score"))
            or not _finite(item.get("serenity_raw_score"))
            or not _finite(item.get("risk_penalty"))
            or not _finite(item.get("data_quality"))
            or not 0 <= float(item["serenity_score"]) <= 100
            or not 0 <= float(item["data_quality"]) <= 1
            or item.get("scoring_version") != "serenity-first-v2.1.0"
            or item.get("line_public_eligible") is not True
            or item.get("provider_scope") != "public_only"
            or item.get("owner_watchlist_inherited") is not False
            or not isinstance(item.get("evidence"), list)
            or not item["evidence"]
            or item.get("evidence_count") != len(item["evidence"])
        ):
            raise SnapshotV211Error(f"Research-universe record {ticker} failed validation")
        overlay = item.get("aschenbrenner_overlay")
        if not isinstance(overlay, dict) or overlay.get("included_in_serenity_score") is not False:
            raise SnapshotV211Error(f"Research-universe record {ticker} leaked overlay into Serenity")
        base.iso_timestamp(item.get("generated_at"), f"universe.{ticker}.generated_at")
        base.iso_timestamp(item.get("as_of"), f"universe.{ticker}.as_of")
        result.append({**item, "ticker": ticker})
    expected = sorted(
        result,
        key=lambda item: (
            -float(item["serenity_score"]),
            -float(item["data_quality"]),
            str(item["ticker"]),
        ),
    )
    if result != expected:
        raise SnapshotV211Error("Research-universe ordering is not deterministic")
    base.reject_private_keys(result)
    return result


def validate_options(raw: Any, universe: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or len(raw) != len(universe):
        raise SnapshotV211Error("Public option records must cover the complete scored universe")
    expected_tickers = [str(item["ticker"]) for item in universe]
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict) or set(item) != OPTION_RECORD_KEYS:
            raise SnapshotV211Error(f"Public option record {index} has an invalid closed schema")
        ticker = str(item.get("ticker") or "").upper()
        if ticker in seen or ticker != expected_tickers[index]:
            raise SnapshotV211Error("Public option record ordering does not match the research universe")
        seen.add(ticker)
        if (
            item.get("schema_version") != 1
            or item.get("quote_source") != "yfinance"
            or item.get("provider_scope") != "public_only"
            or item.get("line_public_eligible") is not True
            or item.get("ibkr_connected") is not False
            or item.get("brokerage_data_included") is not False
            or item.get("account_data_included") is not False
            or item.get("position_data_included") is not False
            or item.get("owner_watchlist_inherited") is not False
            or not isinstance(item.get("periods"), dict)
        ):
            raise SnapshotV211Error(f"Public option record {ticker} violated the public-only boundary")
        base.iso_timestamp(item.get("retrieved_at"), f"options.{ticker}.retrieved_at")
        result.append({**item, "ticker": ticker})
    base.reject_private_keys(result)
    return result


def build_envelope(
    *,
    top20_path: Path = base.TOP20_PATH,
    universe_path: Path = UNIVERSE_PATH,
    options_path: Path = OPTIONS_PATH,
    plan_path: Path = base.PLAN_PATH,
    metadata_path: Path = base.METADATA_PATH,
    report_path: Path = base.REPORT_PATH,
) -> dict[str, Any]:
    top20 = base.validate_top20(base.load_json(top20_path))
    universe = validate_universe(base.load_json(universe_path))
    options = validate_options(base.load_json(options_path), universe)
    if [item["ticker"] for item in top20] != [item["ticker"] for item in universe[:20]]:
        raise SnapshotV211Error("Top 20 is not the leading slice of the scored research universe")

    plan = base.validate_plan(base.load_json(plan_path))
    discovery = plan.get("v211_discovery")
    if (
        not isinstance(discovery, dict)
        or discovery.get("product_version") != "2.1.1"
        or discovery.get("scoring_formula_changed") is not False
        or discovery.get("owner_watchlist_inherited") is not False
        or discovery.get("scored_universe_count") != len(universe)
    ):
        raise SnapshotV211Error("Source plan lacks the v2.1.1 discovery attestation")

    metadata = base.load_json(metadata_path)
    if (
        not isinstance(metadata, dict)
        or metadata.get("line_public_eligible") is not True
        or metadata.get("provider_scope") != "public_only"
        or metadata.get("owner_watchlist_inherited") is not False
        or metadata.get("product_version") != "2.1.1"
        or metadata.get("research_universe_count") != len(universe)
    ):
        raise SnapshotV211Error("Public metadata lacks the v2.1.1 boundary attestation")
    public_as_of = base.iso_timestamp(
        metadata.get("last_successful_pipeline_timestamp"),
        "last_successful_pipeline_timestamp",
    )

    try:
        report_body = report_path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise SnapshotV211Error(f"Unable to read public report: {report_path}") from exc
    report = base.REPORT_PREFIX + report_body.lstrip("\ufeff")

    payloads = {
        "top20_json": base.canonical_json(top20),
        "research_universe_json": base.canonical_json(universe),
        "options_json": base.canonical_json(options),
        "source_plan_json": base.canonical_json(plan),
        "report_text": report,
    }
    material = "\n".join((*payloads.values(), public_as_of))
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + hashlib.sha256(
        material.encode("utf-8")
    ).hexdigest()[:12]
    generated = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return {
        "schema_version": 2,
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


def _synthetic_option(ticker: str, generated: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "ticker": ticker,
        "provider_symbol": ticker,
        "currency": "USD",
        "current_price": 100.0,
        "retrieved_at": generated,
        "status": "NO_ELIGIBLE_LIQUID_QUOTE",
        "quote_source": "yfinance",
        "quote_delay_status": "THIRD_PARTY_DELAY_UNKNOWN",
        "provider_scope": "public_only",
        "line_public_eligible": True,
        "ibkr_connected": False,
        "brokerage_data_included": False,
        "account_data_included": False,
        "position_data_included": False,
        "owner_watchlist_inherited": False,
        "periods": {},
    }


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="ii-v211-public-snapshot-") as temporary:
        root = Path(temporary)
        generated = "2026-08-31T00:00:00Z"
        universe = [base.synthetic_record(index, generated) for index in range(30)]
        top20 = universe[:20]
        plan = {
            "schema_version": 1,
            "catalog_count": 101,
            "automatic_activation": False,
            "owner_watchlist_inherited": False,
            "provider_scope": "public_only",
            "line_public_eligible": True,
            "inventory": {"source_count": 101, "runtime_enabled_count": 0, "topic_counts": {}},
            "v211_discovery": {
                "product_version": "2.1.1",
                "scoring_formula_changed": False,
                "owner_watchlist_inherited": False,
                "scored_universe_count": 30,
            },
        }
        metadata = {
            "schema_version": 1,
            "last_successful_pipeline_timestamp": generated,
            "line_public_eligible": True,
            "provider_scope": "public_only",
            "owner_watchlist_inherited": False,
            "product_version": "2.1.1",
            "research_universe_count": 30,
        }
        options = [_synthetic_option(item["ticker"], generated) for item in universe]
        files = {
            "top.json": top20,
            "universe.json": universe,
            "options.json": options,
            "plan.json": plan,
            "metadata.json": metadata,
        }
        for name, value in files.items():
            (root / name).write_text(json.dumps(value), encoding="utf-8")
        (root / "report.md").write_text("# Synthetic v2.1.1 briefing\n" + "evidence\n" * 40, encoding="utf-8")
        envelope = build_envelope(
            top20_path=root / "top.json",
            universe_path=root / "universe.json",
            options_path=root / "options.json",
            plan_path=root / "plan.json",
            metadata_path=root / "metadata.json",
            report_path=root / "report.md",
        )
        if envelope["schema_version"] != 2 or len(envelope["payloads"]) != 5:
            raise SnapshotV211Error("v2.1.1 synthetic envelope is invalid")
        for name, content in envelope["payloads"].items():
            if hashlib.sha256(content.encode("utf-8")).hexdigest() != envelope["sha256"][name]:
                raise SnapshotV211Error("v2.1.1 synthetic digest mismatch")
    print("V211_PUBLIC_SNAPSHOT_BUILDER_SELF_TEST = PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
            return 0
        envelope = build_envelope()
        atomic_write(args.output, envelope)
        print(json.dumps({
            "status": "PASS",
            "schema_version": 2,
            "run_id": envelope["run_id"],
            "output": str(args.output),
            "top20_count": 20,
            "payload_count": 5,
            "provider_scope": "public_only",
        }, ensure_ascii=False, indent=2))
        return 0
    except (SnapshotV211Error, base.SnapshotError, OSError, ValueError) as exc:
        print(f"V2.1.1 public snapshot build failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
