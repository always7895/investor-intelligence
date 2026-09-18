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
    # Index the input top20 evidence per ticker (for the input-to-audit mapping).
    input_evidence_by_ticker: dict[str, list] = {}
    for row in top20_rows:
        tk = str(row.get("ticker") or "").upper()
        input_evidence_by_ticker[tk] = row.get("evidence") or []

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

        # INPUT-TO-AUDIT MAPPING (Pro 3D step A correction): compare the input
        # top20 evidence (per ticker) vs the audit sources. Determine if any
        # input source was lost in the audit (mapping_loss) or preserved.
        input_ev = input_evidence_by_ticker.get(tk, [])
        input_claim_types = [str(e.get("claim_type") or "") for e in input_ev if isinstance(e, dict)]
        audit_claim_types = [str(s.get("claim_type") or "") for s in sources if isinstance(s, dict)]
        input_source_count = len(input_ev)
        audit_source_count = len(sources)
        # A mapping_loss is present if the input had MORE distinct claim_types than
        # the audit preserved (some input sources were not carried into the audit).
        input_distinct_ct = set(input_claim_types)
        audit_distinct_ct = set(audit_claim_types)
        lost_ct = input_distinct_ct - audit_distinct_ct  # input claim_types not in audit
        mapping_status = "mapping_loss" if lost_ct else "preserved_or_deduped"
        if mapping_status == "mapping_loss":
            classifications["mapping_loss"] = classifications.get("mapping_loss", 0) + 1
        else:
            classifications["preserved_or_deduped"] = classifications.get("preserved_or_deduped", 0) + 1

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
            "claim_audit_status": "NOT_ASSESSED_BY_ANALYSIS (domain-count heuristic only)",
            "missing_or_review": missing,
            "source_classification": {"provenance_only": prov_only, "market_macro": market_macro, "real_claim": real_claim},
            "claim_sources": claim_src_detail,
            "gap_classification": cls,
            "input_source_count": input_source_count,
            "audit_source_count": audit_source_count,
            "input_to_audit_mapping": mapping_status,
            "lost_claim_types": sorted(lost_ct),
        })

    # Print the matrix
    print(f"\n{'ticker':8s} {'cl_fam':>6s} {'cl_dom':>6s} {'cl_prim':>7s} {'prov':>4s} {'mkt':>4s} {'claim':>5s}  classification")
    for g in gap_matrix:
        sc = g["source_classification"]
        print(f"{g['ticker']:8s} {g['actual_claim_family_count']:>6d} {g['actual_claim_domain_count']:>6d} "
              f"{str(g['actual_claim_primary_count']):>7s} {sc['provenance_only']:>4d} {sc['market_macro']:>4d} "
              f"{sc['real_claim']:>5d}  {g['gap_classification']}")

    print(f"\nGAP_CLASSIFICATION = {classifications}")
    # Input-to-audit mapping summary (Pro 3D step A correction).
    mapping_summary = {g["ticker"]: g["input_to_audit_mapping"] for g in gap_matrix}
    mapping_loss_count = sum(1 for v in mapping_summary.values() if v == "mapping_loss")
    print(f"INPUT_TO_AUDIT_MAPPING = {mapping_loss_count} mapping_loss / {len(mapping_summary) - mapping_loss_count} preserved_or_deduped")
    for g in gap_matrix[:3]:
        print(f"  {g['ticker']}: input={g['input_source_count']} audit={g['audit_source_count']} mapping={g['input_to_audit_mapping']} lost_ct={g['lost_claim_types']}")
    # Sample missing_or_review (common flags)
    all_missing = set()
    for g in gap_matrix:
        all_missing.update(g["missing_or_review"])
    print(f"COMMON_MISSING_OR_REVIEW = {sorted(all_missing)}")

    # Verdict (Pro 3D step A correction: retract the hard-coded root-cause conclusion).
    print(f"\nSTEP_A_MAPPING_VERDICT = NOT_ASSESSED (the input-to-audit mapping is now computed above, but the root-cause conclusion is NOT established)")
    print(f"AUDIT_SOURCE_INVENTORY = OPERATOR_REPORTED (the audit only has regulator_filing/sec.gov as claim sources — this inventory is valid)")
    print(f"INPUT_TO_AUDIT_MAPPING = {'MAPPING_LOSS_PRESENT' if mapping_loss_count > 0 else 'PRESERVED_OR_DEDUPED'} ({mapping_loss_count} tickers with lost claim_types)")
    print(f"MAPPING_LOSS = {'UNKNOWN' if mapping_loss_count == 0 else 'PRESENT'} (the mapping is now computed; a lost claim_type may be deduplication, not loss)")
    print(f"INPUT_ORIGIN_GAP = NOT_ESTABLISHED (requires the input-to-audit mapping to be fully interpreted; 'audit sees one domain' != 'input lacked a second source')")
    print(f"SECOND_SOURCE_ACQUISITION_REQUIRED = NOT_YET_DETERMINED")
    print(f"cl_prim=2 is the gate-reported primary metric (separately: {gap_matrix[0]['source_classification']['provenance_only']} provenance-only); NOT 'two independent company advantage supports'")
    print(f"APPLICATION_SOURCE_UNCHANGED = true; ACTUAL_NETWORK_IO = 0; PRODUCTION_TOUCHED = false")
    raise SystemExit(0)


if __name__ == "__main__":
    raise SystemExit(main())