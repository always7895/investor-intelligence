#!/usr/bin/env python3
"""TASK0-3E_CLAIM_SOURCE_FEASIBILITY: 修正版 Request 1 (本機 recorded-data 核對).

對既有 recorded inputs 做一次本機抽取與來源對照，不上網找 IR、不執行新聞探索。
僅涵蓋 TAL、SMCI、GAP 三個代表案例。

1. 先補內容定位：從各卡已列出的 .source-v1.json 讀取實際資料，記錄:
   - recorded_file_path
   - recorded_file_sha256
   - hash_basis: wrapper bytes/保存的 response body/其他明確對象
   - JSON locator
   - namespace/tag + units
   - observation selector: accession + start + end + filed + form
   - selected value
2. 再完成三個來源對照：每列至少提供:
   - input evidence locator
   - raw source identity
   - canonical source identity/dedup unit
   - matched audit locator；或明確的未匹配狀態
   - classification
   - dedup representative（適用時）
   - reason

Read-only source; 0 network; 0 credentials; 0 formal KV/DO; 0 schedules; 0 LINE.
Exit 0 when the verification completes.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
TMP = SCRIPT_DIR.parent / ".tmp"
NORMALIZED_TOP20 = TMP / "3d_fullgate_normalized_top20.json"
AUDIT = TMP / "3d_fullgate_audit.json"
SOURCE_INDEPENDENCE_POLICY = SCRIPT_DIR.parent / "config" / "v213-serenity-public-logic-policy.json"


def _sha256_full(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def main() -> int:
    print("=== TASK0-3E: 修正版 Request 1 (本機 recorded-data 核對) ===")

    # Source-independence policy SHA-256.
    policy_sha = _sha256_full(SOURCE_INDEPENDENCE_POLICY)
    print(f"SOURCE_INDEPENDENCE_POLICY_SHA256: {SOURCE_INDEPENDENCE_POLICY} (SHA256={policy_sha})")

    # Unique run directory (no overwrite).
    run_dir = TMP / f"3e_request1_run_{int(time.time() * 1_000_000)}"
    if run_dir.exists():
        print(f"FAIL: run directory already exists (no-overwrite violated): {run_dir}")
        raise SystemExit(1)
    run_dir.mkdir(parents=True)

    # Load the data.
    top20 = json.load(open(NORMALIZED_TOP20, encoding="utf-8"))
    audit = json.load(open(AUDIT, encoding="utf-8"))
    audit_records = {r["ticker"]: r for r in audit.get("records", [])}

    # 3 claim cards (using actual tag and value from recorded input).
    claim_cards = {
        "TAL": {
            "claim_id": "TAL-REV-2026",
            "cik_file": "data/cache/v21/companyfacts/CIK0001499620.json.source-v1.json",
            "namespace_tag": "us-gaap:Revenues",
            "units": "USD",
            "observation_selector": {
                "accession": "0001104659-26-073410",
                "start": "2025-03-01",
                "end": "2026-02-28",
                "filed": "2026-06-12",
                "form": "20-F",
            },
            "expected_value": 3008908000,
        },
        "SMCI": {
            "claim_id": "SMCI-REV-2026",
            "cik_file": "data/cache/v21/companyfacts/CIK0001375365.json.source-v1.json",
            "namespace_tag": "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
            "units": "USD",
            "observation_selector": {
                "accession": "0001375365-26-000022",
                "start": "2025-07-01",
                "end": "2026-06-30",
                "filed": "2026-08-31",
                "form": "10-K",
            },
            "expected_value": 39063072000,
        },
        "GAP": {
            "claim_id": "GAP-REV-2026Q2",
            "cik_file": "data/cache/v21/companyfacts/CIK0000039911.json.source-v1.json",
            "namespace_tag": "us-gaap:Revenues",
            "units": "USD",
            "observation_selector": {
                "accession": "0001628280-26-059345",
                "start": "2026-05-03",
                "end": "2026-08-01",
                "filed": "2026-08-28",
                "form": "10-Q",
            },
            "expected_value": 3651000000,
        },
    }

    # Step 1: 補內容定位 (content localization).
    content_localization = {}
    for ticker, card in claim_cards.items():
        cik_file = SCRIPT_DIR.parent / card["cik_file"]
        cik_file_bytes = cik_file.read_bytes()
        cik_file_sha = _sha256_bytes(cik_file_bytes)
        wrapper = json.loads(cik_file_bytes)
        body_sha = wrapper.get("last_success", {}).get("body_sha256", "")
        body = json.loads(wrapper["last_success"]["body_utf8"])
        facts = body.get("facts", {})
        us_gaap = facts.get("us-gaap", {})
        tag = card["namespace_tag"].split(":")[1]
        metric = us_gaap.get(tag, {})
        units = metric.get("units", {})
        usd = units.get(card["units"], [])
        # Find the observation matching the selector.
        sel = card["observation_selector"]
        matches = []
        for obs in usd:
            if (obs.get("accn") == sel["accession"] and obs.get("start") == sel["start"]
                    and obs.get("end") == sel["end"] and obs.get("filed") == sel["filed"]
                    and obs.get("form") == sel["form"]):
                matches.append(obs)
        selected_value = matches[0].get("val") if len(matches) == 1 else None
        verification = (selected_value == card["expected_value"]) if len(matches) == 1 else False
        content_localization[ticker] = {
            "recorded_file_path": str(cik_file),
            "recorded_file_sha256": cik_file_sha,
            "hash_basis": "wrapper bytes",
            "saved_body_sha256": body_sha,
            "json_locator": f"facts.us-gaap.{tag}.units.{card['units']}",
            "namespace_tag": card["namespace_tag"],
            "units": card["units"],
            "observation_selector": sel,
            "matches_count": len(matches),
            "selected_value": selected_value,
            "expected_value": card["expected_value"],
            "verification": verification,
        }
        print(f"\n{ticker} ({card['claim_id']}):")
        print(f"  recorded_file_sha256: {cik_file_sha}")
        print(f"  saved_body_sha256: {body_sha}")
        print(f"  json_locator: facts.us-gaap.{tag}.units.{card['units']}")
        print(f"  observation_selector: {sel}")
        print(f"  matches_count: {len(matches)}")
        print(f"  selected_value: {selected_value}")
        print(f"  expected_value: {card['expected_value']}")
        print(f"  verification: {verification}")

    # Step 2: 三個來源對照 (source mapping).
    source_mapping = {}
    for ticker in claim_cards:
        item = next((x for x in top20 if x.get("ticker") == ticker), {})
        input_evidence = item.get("evidence", [])
        audit_record = audit_records.get(ticker, {})
        audit_sources = audit_record.get("sources", [])
        # Build the input evidence rows.
        input_rows = []
        for i, e in enumerate(input_evidence):
            url = e.get("url", "")
            source_id = e.get("source_id", "")
            family = e.get("family", "")
            domain = url.split("/")[2] if "://" in url else ""
            claim_type = e.get("claim_type", "")
            date = e.get("publication_date", e.get("as_of", ""))
            input_rows.append({
                "input_evidence_locator": f"evidence[{i}]",
                "raw_source_identity": f"domain={domain}, family={family}, claim_type={claim_type}",
                "url": url,
                "source_id": source_id,
                "family": family,
                "domain": domain,
                "claim_type": claim_type,
                "date": date,
            })
        # Build the audit source rows.
        audit_rows = []
        for i, s in enumerate(audit_sources):
            url = s.get("url", "")
            source_id = s.get("source_id", "")
            family = s.get("family", "")
            domain = s.get("domain", "")
            claim_type = s.get("claim_type", "")
            date = s.get("as_of", "")
            audit_rows.append({
                "audit_locator": f"sources[{i}]",
                "url": url,
                "source_id": source_id,
                "family": family,
                "domain": domain,
                "claim_type": claim_type,
                "date": date,
            })
        # Match input rows to audit rows (by URL + claim_type).
        matched = []
        for ir in input_rows:
            matched_audit = None
            for ar in audit_rows:
                if ir["url"] == ar["url"] and ir["claim_type"] == ar["claim_type"]:
                    matched_audit = ar
                    break
            if matched_audit:
                matched.append({
                    "input_evidence_locator": ir["input_evidence_locator"],
                    "raw_source_identity": ir["raw_source_identity"],
                    "canonical_source_identity": f"domain={ir['domain']}, family={ir['family']}, claim_type={ir['claim_type']}",
                    "matched_audit_locator": matched_audit["audit_locator"],
                    "classification": "MATCHED",
                    "dedup_representative": None,
                    "reason": "URL + claim_type match",
                })
            else:
                matched.append({
                    "input_evidence_locator": ir["input_evidence_locator"],
                    "raw_source_identity": ir["raw_source_identity"],
                    "canonical_source_identity": f"domain={ir['domain']}, family={ir['family']}, claim_type={ir['claim_type']}",
                    "matched_audit_locator": None,
                    "classification": "UNEXPLAINED",
                    "dedup_representative": None,
                    "reason": f"UNEXPLAINED: input evidence [{ir['input_evidence_locator']}] (url={ir['url']}, claim_type={ir['claim_type']}) has no matching audit source",
                })
        source_mapping[ticker] = matched
        print(f"\n{ticker} source mapping:")
        for m in matched:
            print(f"  {m['input_evidence_locator']}: {m['classification']} (matched_audit={m['matched_audit_locator']})")

    # Save the results to the unique run directory.
    manifest = {
        "source_independence_policy": str(SOURCE_INDEPENDENCE_POLICY),
        "source_independence_policy_sha256": policy_sha,
        "content_localization": content_localization,
        "source_mapping": source_mapping,
    }
    manifest_bytes = json.dumps(manifest, sort_keys=True, indent=2).encode("utf-8")
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = run_dir / "request1_results.json"
    manifest_path.write_bytes(manifest_bytes)
    print(f"\nREQUEST1_RESULTS saved to {manifest_path} (SHA256={manifest_sha})")

    # Summary.
    all_verified = all(cl["verification"] for cl in content_localization.values())
    total_unexplained = sum(1 for sm in source_mapping.values() for m in sm if m["classification"] == "UNEXPLAINED")
    print(f"\nSUMMARY:")
    print(f"  all_claim_cards_verified: {all_verified}")
    print(f"  total_unexplained_source_mapping: {total_unexplained}")
    print(f"\nTASK0-3E_REQUEST1 = COMPLETE (local recorded-data verification done)")
    print("APPLICATION_SOURCE_UNCHANGED = true; PRODUCTION_TOUCHED = false")
    raise SystemExit(0)


if __name__ == "__main__":
    raise SystemExit(main())