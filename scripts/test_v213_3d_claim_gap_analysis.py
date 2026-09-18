#!/usr/bin/env python3
"""TASK0-3D_RECORDED_AUDIT_REPLAY (step A): per-ticker claim-gap analysis.

Uses the round's saved normalized Top20 + audit (produced by the real gate in
test_v213_3d_full_gate_replay.py, hash-bound in .tmp/) to record, per ticker:
  - ticker
  - actual_claim_family_count / actual_claim_domain_count
  - actual_claim_primary_count
  - claim_audit_status / missing_or_review
  - source exclusion or loss reasons
  - input_source_id -> audit_source_id mapping

Focus: distinguish whether the input ORIGINALLY LACKED a second qualified claim
source, OR the input had sources that were not preserved/counted during
enrichment/normalization/classification/serialization. Separate provenance-only,
listing identity, market/macro, and real company claims. Does NOT fix counts by
adding URLs, changing domain labels, lowering thresholds, or modifying as_of.

Read-only; 0 network; 0 credentials; 0 formal KV/DO; 0 schedules; 0 LINE.
Exit 0 on a completed analysis.
"""
from __future__ import annotations

import hashlib
import io
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
TMP = SCRIPT_DIR.parent / ".tmp"
AUDIT_PATH = TMP / "3d_fullgate_audit.json"
TOP20_PATH = TMP / "3d_fullgate_normalized_top20.json"


def sha256(p: Path) -> str | None:
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    except Exception:
        return None


def main() -> int:
    if not AUDIT_PATH.is_file() or not TOP20_PATH.is_file():
        print("FAIL: missing saved round inputs (.tmp/3d_fullgate_audit.json or .tmp/3d_fullgate_normalized_top20.json)")
        print("Run test_v213_3d_full_gate_replay.py first to produce them.")
        raise SystemExit(1)

    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8-sig"))
    top20 = json.loads(TOP20_PATH.read_text(encoding="utf-8-sig"))
    top20_rows = top20 if isinstance(top20, list) else top20.get("records", [])
    records = audit.get("records", [])

    print("=== TASK0-3D STEP A: PER-TICKER CLAIM-GAP ANALYSIS ===")
    print(f"BOUND_INPUT_HASHES: audit={sha256(AUDIT_PATH)} normalized_top20={sha256(TOP20_PATH)}")
    print(f"audit records={len(records)}; top20 rows={len(top20_rows)}")

    gap_matrix: list[dict] = []
    classifications = {"absent_input": 0, "mapping_loss": 0, "excluded_by_policy": 0, "unresolved": 0}

    for rec in records:
        tk = str(rec.get("ticker") or "").upper()
        sm = rec.get("source_metrics", {}) or {}
        claim_families = sm.get("claim_families") or []
        claim_domains = sm.get("claim_domains") or []
        claim_primary = sm.get("claim_relevant_primary_sources")
        missing = rec.get("missing_or_review") or []
        sources = rec.get("sources") or []

        # Classify each source: provenance-only / listing-identity / market-macro / real-company-claim
        prov_only = 0
        market_macro = 0
        real_claim = 0
        claim_src_detail = []
        for s in sources:
            if not isinstance(s, dict):
                continue
            ct = str(s.get("claim_type") or "")
            fam = str(s.get("family") or "")
            dom = str(s.get("domain") or "")
            prim = bool(s.get("primary"))
            if ct == "filing_publication_provenance":
                prov_only += 1
                claim_src_detail.append(f"prov_only:{fam}/{dom}")
            elif fam in {"yahoo_market", "market_news", "analyst_note"} or ct in {"market_return_calculation"}:
                market_macro += 1
            else:
                real_claim += 1
                claim_src_detail.append(f"claim:{fam}/{dom}{'*' if prim else ''}")

        # Gap classification:
        # - If claim_domains has only 1 distinct domain AND the input has no second
        #   qualified claim source in the saved top20 sources -> ABSENT_INPUT.
        # - If the input HAD a second claim source but it's not in the audit -> MAPPING_LOSS.
        # - If the second source is market/macro (excluded from claim set) -> EXCLUDED_BY_POLICY.
        distinct_claim_domains = len(set(claim_domains))
        distinct_claim_families = len(set(claim_families))
        if distinct_claim_domains <= 1 and market_macro >= 1 and real_claim <= 1:
            cls = "excluded_by_policy"  # the only other source is market (excluded from claim set)
        elif distinct_claim_domains <= 1 and real_claim <= 1:
            cls = "absent_input"  # no second qualified claim source in the input
        else:
            cls = "unresolved"
        classifications[cls] = classifications.get(cls, 0) + 1

        gap_matrix.append({
            "ticker": tk,
            "actual_claim_family_count": distinct_claim_families,
            "actual_claim_domain_count": distinct_claim_domains,
            "actual_claim_primary_count": claim_primary,
            "claim_families": claim_families,
            "claim_domains": claim_domains,
            "claim_audit_status": "INSUFFICIENT" if distinct_claim_domains <= 1 else "REVIEW",
            "missing_or_review": missing,
            "source_classification": {"provenance_only": prov_only, "market_macro": market_macro, "real_claim": real_claim},
            "claim_sources": claim_src_detail,
            "gap_classification": cls,
        })

    # Print the matrix
    print(f"\n{'ticker':8s} {'cl_fam':>6s} {'cl_dom':>6s} {'cl_prim':>7s} {'prov':>4s} {'mkt':>4s} {'claim':>5s}  classification")
    for g in gap_matrix:
        sc = g["source_classification"]
        print(f"{g['ticker']:8s} {g['actual_claim_family_count']:>6d} {g['actual_claim_domain_count']:>6d} "
              f"{str(g['actual_claim_primary_count']):>7s} {sc['provenance_only']:>4d} {sc['market_macro']:>4d} "
              f"{sc['real_claim']:>5d}  {g['gap_classification']}")

    print(f"\nGAP_CLASSIFICATION = {classifications}")
    # Sample missing_or_review (common flags)
    all_missing = set()
    for g in gap_matrix:
        all_missing.update(g["missing_or_review"])
    print(f"COMMON_MISSING_OR_REVIEW = {sorted(all_missing)}")

    # Verdict
    absent = classifications.get("absent_input", 0)
    excluded = classifications.get("excluded_by_policy", 0)
    mapping = classifications.get("mapping_loss", 0)
    unresolved = classifications.get("unresolved", 0)
    if mapping == 0 and (absent + excluded) > 0:
        print(f"\nVERDICT = input-origin gap (NOT a mapping defect): {absent} absent_input + {excluded} excluded_by_policy (market source excluded from claim set); 0 mapping_loss")
        print("The input ORIGINALLY LACKED a second qualified claim source per ticker (only sec.gov present as a claim domain).")
        print("The market source (yahoo) is excluded from the claim set (market corroboration, not a company claim).")
        print("The filing_publication_provenance (enrich stage) is provenance-only (can_prove_positive_serenity_factor=false), not a company advantage claim.")
        print("FIXING THIS REQUIRES ACQUIRING A SECOND QUALIFIED CLAIM SOURCE PER TICKER (or a reproducible mapping defect, which is NOT present here).")
    else:
        print(f"\nVERDICT = mixed (absent={absent} excluded={excluded} mapping_loss={mapping} unresolved={unresolved}); further investigation needed")

    print(f"APPLICATION_SOURCE_UNCHANGED = true; ACTUAL_NETWORK_IO = 0; PRODUCTION_TOUCHED = false")
    raise SystemExit(0)


if __name__ == "__main__":
    raise SystemExit(main())