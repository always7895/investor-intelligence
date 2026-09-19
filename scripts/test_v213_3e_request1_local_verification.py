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
import importlib.util
import json
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
TMP = SCRIPT_DIR.parent / ".tmp"
NORMALIZED_TOP20 = TMP / "3d_fullgate_normalized_top20.json"
AUDIT = TMP / "3d_fullgate_audit.json"
SOURCE_INDEPENDENCE_POLICY = SCRIPT_DIR.parent / "config" / "v213-serenity-public-logic-policy.json"
COLLECTOR_PATH = SCRIPT_DIR / "v213_source_independence_gate.py"


def _load_collector():
    """Load the audited collector's pure functions (normalize_url, domain_of, make_source)."""
    spec = importlib.util.spec_from_file_location("ii_v213_collector", COLLECTOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load collector {COLLECTOR_PATH}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


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

    # Load the audited collector's pure functions.
    collector = _load_collector()
    normalize_url = collector.normalize_url
    domain_of = collector.domain_of
    make_source = collector.make_source

    # Load the data.
    top20_bytes = NORMALIZED_TOP20.read_bytes()
    top20_sha = _sha256_bytes(top20_bytes)
    audit_bytes = AUDIT.read_bytes()
    audit_sha = _sha256_bytes(audit_bytes)
    top20 = json.loads(top20_bytes)
    audit = json.loads(audit_bytes)
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

    # Step 2: 三個來源對照 (source mapping) using the audited collector's rules.
    source_mapping = {}
    for ticker in claim_cards:
        item = next((x for x in top20 if x.get("ticker") == ticker), {})
        input_evidence = item.get("evidence", [])
        audit_record = audit_records.get(ticker, {})
        audit_sources = audit_record.get("sources", [])
        # Build the input evidence rows using the collector's make_source rules.
        input_rows = []
        for i, e in enumerate(input_evidence):
            url = e.get("url", "")
            source_id = e.get("source_id", "")
            claim_type = e.get("claim_type", "")
            title = e.get("title", "")
            as_of = e.get("publication_date", e.get("as_of", ""))
            # Use the collector's make_source to create the canonical source identity.
            canonical = make_source(source_id, claim_type, title, url, as_of)
            input_rows.append({
                "input_evidence_locator": f"evidence[{i}]",
                "raw_source_identity": f"domain={e.get('domain', url.split('/')[2] if '://' in url else '')}, family={e.get('family', '')}, claim_type={claim_type}",
                "canonical_source_identity": f"domain={canonical['domain']}, family={canonical['family']}, claim_type={canonical['claim_type']}",
                "canonical_url": canonical["url"],
                "canonical_domain": canonical["domain"],
                "canonical_family": canonical["family"],
                "canonical_claim_type": canonical["claim_type"],
                "url": url,
                "source_id": source_id,
                "claim_type": claim_type,
            })
        # Build the audit source rows using the collector's make_source rules.
        audit_rows = []
        for i, s in enumerate(audit_sources):
            url = s.get("url", "")
            source_id = s.get("source_id", "")
            claim_type = s.get("claim_type", "")
            title = s.get("title", "")
            as_of = s.get("as_of", "")
            canonical = make_source(source_id, claim_type, title, url, as_of)
            audit_rows.append({
                "audit_locator": f"sources[{i}]",
                "canonical_url": canonical["url"],
                "canonical_domain": canonical["domain"],
                "canonical_family": canonical["family"],
                "canonical_claim_type": canonical["claim_type"],
                "url": url,
                "source_id": source_id,
                "claim_type": claim_type,
            })
        # Compute the dedup unit (domain, family, claim_type) and find the first retained representative.
        dedup_representatives: dict[tuple[str, str, str], dict] = {}
        for ir in input_rows:
            unit = (ir["canonical_domain"], ir["canonical_family"], ir["canonical_claim_type"])
            dedup_representatives.setdefault(unit, ir)
        # Match input rows to audit rows (by canonical domain + family + claim_type).
        matched = []
        for ir in input_rows:
            unit = (ir["canonical_domain"], ir["canonical_family"], ir["canonical_claim_type"])
            representative = dedup_representatives.get(unit)
            matched_audit = None
            for ar in audit_rows:
                ar_unit = (ar["canonical_domain"], ar["canonical_family"], ar["canonical_claim_type"])
                if ar_unit == unit:
                    matched_audit = ar
                    break
            if matched_audit:
                matched.append({
                    "input_evidence_locator": ir["input_evidence_locator"],
                    "raw_source_identity": ir["raw_source_identity"],
                    "canonical_source_identity": ir["canonical_source_identity"],
                    "dedup_unit": f"({ir['canonical_domain']}, {ir['canonical_family']}, {ir['canonical_claim_type']})",
                    "dedup_representative": representative["input_evidence_locator"] if representative else None,
                    "matched_audit_locator": matched_audit["audit_locator"],
                    "classification": "MATCHED",
                    "reason": f"canonical (domain, family, claim_type) match: {ir['canonical_source_identity']}",
                })
            else:
                matched.append({
                    "input_evidence_locator": ir["input_evidence_locator"],
                    "raw_source_identity": ir["raw_source_identity"],
                    "canonical_source_identity": ir["canonical_source_identity"],
                    "dedup_unit": f"({ir['canonical_domain']}, {ir['canonical_family']}, {ir['canonical_claim_type']})",
                    "dedup_representative": representative["input_evidence_locator"] if representative else None,
                    "matched_audit_locator": None,
                    "classification": "UNEXPLAINED",
                    "reason": f"UNEXPLAINED: input evidence [{ir['input_evidence_locator']}] (canonical={ir['canonical_source_identity']}) has no matching audit source",
                })
        source_mapping[ticker] = matched
        print(f"\n{ticker} source mapping (canonical/dedup):")
        for m in matched:
            print(f"  {m['input_evidence_locator']}: {m['classification']} (dedup_unit={m['dedup_unit']}, representative={m['dedup_representative']}, matched_audit={m['matched_audit_locator']})")

    # Save the results to the unique run directory.
    manifest = {
        "source_independence_policy": str(SOURCE_INDEPENDENCE_POLICY),
        "source_independence_policy_sha256": policy_sha,
        "normalized_top20": str(NORMALIZED_TOP20),
        "normalized_top20_sha256": top20_sha,
        "audit": str(AUDIT),
        "audit_sha256": audit_sha,
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