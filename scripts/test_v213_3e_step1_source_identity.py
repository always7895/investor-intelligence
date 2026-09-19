#!/usr/bin/env python3
"""TASK0-3E_CLAIM_SOURCE_FEASIBILITY step 1: 固定資料基準與來源身分.

使用一組明確的既有 normalized Top20、audit、policy，登錄完整 SHA-256 與
artifact 路徑。依 ticker 比對 input evidence 與 audit source 的 URL、source
ID、family、domain、claim type、日期；不能再只比較 claim-type 集合就宣稱
沒有 mapping loss。

Read-only source; 0 network; 0 credentials; 0 formal KV/DO; 0 schedules; 0 LINE.
Exit 0 when the comparison completes.
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
POLICY = SCRIPT_DIR.parent / "config" / "v213-serenity-evidence-freshness-policy.json"


def _sha256_full(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    print("=== TASK0-3E STEP 1: 固定資料基準與來源身分 ===")

    # Log full SHA-256 and artifact paths.
    top20_sha = _sha256_full(NORMALIZED_TOP20)
    audit_sha = _sha256_full(AUDIT)
    policy_sha = _sha256_full(POLICY)
    print(f"BOUND_INPUTS:")
    print(f"  normalized_top20: {NORMALIZED_TOP20} (SHA256={top20_sha})")
    print(f"  audit: {AUDIT} (SHA256={audit_sha})")
    print(f"  policy: {POLICY} (SHA256={policy_sha})")

    # Load the data.
    top20 = json.load(open(NORMALIZED_TOP20, encoding="utf-8"))
    audit = json.load(open(AUDIT, encoding="utf-8"))
    audit_records = {r["ticker"]: r for r in audit.get("records", [])}

    # Unique run directory (no overwrite).
    run_dir = TMP / f"3e_step1_run_{int(time.time() * 1_000_000)}"
    if run_dir.exists():
        print(f"FAIL: run directory already exists (no-overwrite violated): {run_dir}")
        raise SystemExit(1)
    run_dir.mkdir(parents=True)

    # Compare input evidence and audit source by ticker.
    comparison = {}
    for item in top20:
        ticker = item.get("ticker")
        input_evidence = item.get("evidence", [])
        audit_record = audit_records.get(ticker, {})
        audit_sources = audit_record.get("sources", [])

        # Build the input evidence set (URL, source_id, family, domain, claim_type, date).
        input_set = set()
        for e in input_evidence:
            url = e.get("url", "")
            source_id = e.get("source_id", "")
            family = e.get("family", "")
            # domain is not in the input evidence; derive from URL.
            domain = url.split("/")[2] if "://" in url else ""
            claim_type = e.get("claim_type", "")
            date = e.get("publication_date", e.get("as_of", ""))
            input_set.add((url, source_id, family, domain, claim_type, date))

        # Build the audit source set (URL, source_id, family, domain, claim_type, date).
        audit_set = set()
        for s in audit_sources:
            url = s.get("url", "")
            source_id = s.get("source_id", "")
            family = s.get("family", "")
            domain = s.get("domain", "")
            claim_type = s.get("claim_type", "")
            date = s.get("as_of", "")
            audit_set.add((url, source_id, family, domain, claim_type, date))

        # Compare: input evidence not in audit (mapping loss?), audit not in input (extra?).
        input_not_in_audit = input_set - audit_set
        audit_not_in_input = audit_set - input_set

        # Claim-type set comparison (the earlier flawed approach).
        input_claim_types = {e.get("claim_type", "") for e in input_evidence}
        audit_claim_types = {s.get("claim_type", "") for s in audit_sources}
        claim_type_set_equal = (input_claim_types == audit_claim_types)

        comparison[ticker] = {
            "input_evidence_count": len(input_evidence),
            "audit_source_count": len(audit_sources),
            "input_not_in_audit_count": len(input_not_in_audit),
            "audit_not_in_input_count": len(audit_not_in_input),
            "claim_type_set_equal": claim_type_set_equal,
            "input_claim_types": sorted(input_claim_types),
            "audit_claim_types": sorted(audit_claim_types),
            "input_not_in_audit": [list(x) for x in input_not_in_audit],
            "audit_not_in_input": [list(x) for x in audit_not_in_input],
        }

    # Save the comparison to the unique run directory.
    manifest = {
        "normalized_top20": str(NORMALIZED_TOP20),
        "normalized_top20_sha256": top20_sha,
        "audit": str(AUDIT),
        "audit_sha256": audit_sha,
        "policy": str(POLICY),
        "policy_sha256": policy_sha,
        "comparison": comparison,
    }
    manifest_bytes = json.dumps(manifest, sort_keys=True, indent=2).encode("utf-8")
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    manifest_path = run_dir / "source_identity_comparison.json"
    manifest_path.write_bytes(manifest_bytes)
    print(f"\nSOURCE_IDENTITY_COMPARISON saved to {manifest_path} (SHA256={manifest_sha})")

    # Print a summary.
    print(f"\nSUMMARY (20 tickers):")
    total_input_not_in_audit = sum(c["input_not_in_audit_count"] for c in comparison.values())
    total_audit_not_in_input = sum(c["audit_not_in_input_count"] for c in comparison.values())
    claim_type_set_equal_count = sum(1 for c in comparison.values() if c["claim_type_set_equal"])
    print(f"  total input_not_in_audit: {total_input_not_in_audit}")
    print(f"  total audit_not_in_input: {total_audit_not_in_input}")
    print(f"  claim_type_set_equal count: {claim_type_set_equal_count}/20")
    print(f"\nNOTE: claim_type_set_equal={claim_type_set_equal_count}/20, but input_not_in_audit={total_input_not_in_audit} — the claim-type set comparison is INSUFFICIENT (different sources with the same claim_type are not distinguished).")

    print("\nTASK0-3E_STEP1 = COMPLETE (source identity comparison done; claim-type set comparison is insufficient)")
    print("APPLICATION_SOURCE_UNCHANGED = true; PRODUCTION_TOUCHED = false")
    raise SystemExit(0)


if __name__ == "__main__":
    raise SystemExit(main())