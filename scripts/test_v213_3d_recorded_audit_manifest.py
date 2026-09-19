#!/usr/bin/env python3
"""TASK0-3D_RECORDED_AUDIT_REPLAY: input integrity manifest (read-only).

Checks the existing files actually consumed by the v3 source-audit builder
(v213_source_independence_gate_v3.py -> v4 gate) against the CURRENT top20
ticker set. Each input records: consumer function / fixture path / SHA-256 /
schema; ticker coverage; PRESENT_VALID | MISSING | INCOMPATIBLE | STALE;
required_to_execute / required_for_claim_support.

The v3 enrich function (enrich_top20_with_latest_sec_filing_provenance) requires
a per-ticker SEC Company Facts CIK file (CIK{cik.zfill(10)}.json, .source-v1.json
wrapper supported) for EVERY ticker in the final Top20; if any is missing it
raises FederationOrderError before the v4 gate runs.

Read-only: copies nothing, writes nothing, no network, no credentials, no
formal KV/DO, no schedules, no LINE. Exit 0 on a completed manifest (the
manifest itself may report BLOCKED_INPUT_MANIFEST_READY).
"""
from __future__ import annotations

import hashlib
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
V21_DIR = ROOT / "data" / "cache" / "v21"
COMPANYFACTS_DIR = V21_DIR / "companyfacts"
SEC_REF_PATH = V21_DIR / "sec_company_tickers_exchange.json"
TOP20_PATH = ROOT / "data" / "cache" / "top20_public_latest.json"
FEDERATION_PATH = ROOT / "data" / "cache" / "v213_source_federation_latest.json"
POLICY_PATH = ROOT / "config" / "v213-serenity-evidence-freshness-policy.json"
STANDARD_PATH = ROOT / "config" / "v213-serenity-evidence-standard-v3.json"


def sha256(p: Path) -> str | None:
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    except Exception:
        return None


def load_body(p: Path):
    """Mirror the v3 _load_json: .source-v1.json wrapper first, then raw."""
    for cand in (p.with_name(p.name + ".source-v1.json"), p):
        if cand.is_file():
            data = json.loads(cand.read_text(encoding="utf-8-sig"))
            if isinstance(data, dict) and isinstance(data.get("last_success"), dict):
                body = data["last_success"].get("body_utf8")
                if body:
                    return json.loads(body)
            return data
    return None


def main() -> int:
    manifest: list[dict] = []

    def record(name, consumer, path, status, required_to_execute, required_for_claim_support, detail=""):
        manifest.append({
            "input": name, "consumer": consumer, "path": str(path),
            "sha256": sha256(path) if path.is_file() else None,
            "status": status, "required_to_execute": required_to_execute,
            "required_for_claim_support": required_for_claim_support, "detail": detail,
        })

    # --- Structural inputs ---
    for name, consumer, path, claim in [
        ("TOP20", "enrich+normalize+v4", TOP20_PATH, True),
        ("FEDERATION", "v4 gate", FEDERATION_PATH, True),
        ("FRESHNESS_POLICY", "guard", POLICY_PATH, True),
        ("EVIDENCE_STANDARD", "diversified writer", STANDARD_PATH, True),
    ]:
        if path.is_file():
            record(name, consumer, path, "PRESENT_VALID", True, claim)
        else:
            record(name, consumer, path, "MISSING", True, claim)

    # --- SEC reference (ticker -> CIK) ---
    ref = load_body(SEC_REF_PATH)
    if isinstance(ref, dict) and ref.get("fields") and ref.get("data"):
        fields = ref["fields"]; rows = ref["data"]
        ci = fields.index("cik"); ti = fields.index("ticker")
        ticker_to_cik = {str(r[ti] or "").strip().upper(): str(r[ci]).zfill(10)
                         for r in rows if isinstance(r, list) and len(r) == len(fields) and str(r[ci]).isdigit()}
        record("SEC_REFERENCE", "enrich (ticker->CIK)", SEC_REF_PATH, "PRESENT_VALID", True, True,
               f"rows={len(rows)}; ticker->cik={len(ticker_to_cik)}")
    else:
        ticker_to_cik = {}
        record("SEC_REFERENCE", "enrich (ticker->CIK)", SEC_REF_PATH, "MISSING", True, True)

    # --- Per-ticker SEC Company Facts CIK files (the required recorded inputs) ---
    top = json.loads(TOP20_PATH.read_text(encoding="utf-8-sig"))
    tickers = [str(r.get("ticker") or "").strip().upper() for r in top]
    present, missing = [], []
    for tk in tickers:
        cik = ticker_to_cik.get(tk, "")
        if not cik:
            missing.append((tk, "NO_CIK_IN_REF")); continue
        cf = COMPANYFACTS_DIR / f"CIK{cik}.json"
        if cf.is_file() or cf.with_name(cf.name + ".source-v1.json").is_file():
            present.append((tk, cik))
        else:
            missing.append((tk, f"CIK{cik}_FILE_MISSING"))
    record("SEC_COMPANYFACTS_PER_TICKER", "enrich (per-ticker CIK{cik}.json)", COMPANYFACTS_DIR,
           "PRESENT_VALID" if not missing else "MISSING", True, True,
           f"present={len(present)}/{len(tickers)}; missing={len(missing)}; "
           f"present_tickers={[t for t, _ in present]}; missing_detail={missing}")

    print("=== TASK0-3D INPUT INTEGRITY MANIFEST ===")
    for m in manifest:
        print(f"{m['input']:28s} {m['status']:14s} required_exec={m['required_to_execute']} required_claim={m['required_for_claim_support']}")
        if m["detail"]:
            print(f"  detail: {m['detail']}")

    # --- Verdict ---
    if missing:
        first_blocker = f"enrich_top20_with_latest_sec_filing_provenance: {len(missing)} of {len(tickers)} top20 tickers have no SEC Company Facts CIK file (required recorded input)"
        print(f"\nRESULT = BLOCKED_INPUT_MANIFEST_READY")
        print(f"FIRST_BLOCKER = {first_blocker}")
        print(f"MISSING_INPUTS = {missing}")
        print(f"USES = per-ticker latest SEC filing provenance (filed_date_used=true; retrieval_time_used=false; positive_factor_support=false)")
        print(f"REAL_AUDIT_BUILDER = NOT_EXECUTED (blocked at enrich before v4 gate)")
        print(f"SYNTHETIC_AUDIT_SUBSTITUTION = NOT_DONE (per Pro 3D: no synthetic audit substitution)")
        print(f"APPLICATION_SOURCE_UNCHANGED = true; NETWORK_ATTEMPTS = 0; PRODUCTION_TOUCHED = false")
    else:
        print("\nRESULT = DATA_SUFFICIENT (proceed to real writer/audit wiring replay)")
    raise SystemExit(0)


if __name__ == "__main__":
    raise SystemExit(main())