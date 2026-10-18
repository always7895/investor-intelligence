#!/usr/bin/env python3
"""Writes tests/fixtures/revenue-guidance-autoupdate/bootstrap-registry.json: the test baseline of the auto-update
replay chains (NVDA as of its 2025-11-19 release, MU as of its 2025-09-23 release), in the curated record schema.

Values are typed from the filings (NVDA q3fy26pr and its 10-Qs/10-K, MU a2025q4ex991 and its 10-Qs/10-K); the test
suite re-reads each one from the fixture bytes with its own inline-XBRL reader and proves that successors do not
depend on them. Document entries carry the fixtures' genuine capture metadata. Run after
make_revenue_guidance_autoupdate_fixtures.py."""
import gzip
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import revenue_guidance as g  # noqa: E402

D = ROOT / "tests" / "fixtures" / "revenue-guidance-autoupdate"
inv = json.loads((D / "inventory.json").read_text(encoding="utf-8"))
WM = re.compile(rb'bazadebezolkohpepadr="([0-9]+)"')


def docentry(sym, company, row, kind, title):
    raw = gzip.decompress((D / "raw" / (row["sha256"] + ".gz")).read_bytes())
    canon = WM.sub(lambda m: b'bazadebezolkohpepadr="' + b"0" * len(m.group(1)) + b'"', raw)
    did = f"{sym}-{row['accession']}"
    return {"id": did, "issuer": sym, "publisher": company, "title": title, "source_kind": kind, "url": row["url"],
            "published_date": row["filed"], "retrieved_at": row["retrieved_at"], "sha256": hashlib.sha256(canon).hexdigest(),
            "byte_size": len(raw), "lineage_id": did}


def row(sym, role, **kw):
    out = [r for r in inv if r["issuer"] == sym and r["role"] == role and all(r.get(k) == v for k, v in kw.items())]
    assert len(out) == 1, (sym, role, kw, len(out))
    return out[0]


def q(label, start, end, rev, doc, locator, derivation=None):
    d = {"fiscal_label": label, "start": start, "end": end, "revenue": rev, "currency": "USD", "scope": "COMPANY",
         "accounting_basis": "GAAP", "document_id": doc, "locator": locator}
    if derivation:
        d["derivation"] = derivation
    return d


def interval(label, start, end, cal_id, quote):
    return {"fiscal_label": label, "start": start, "end": end, "calendar_document_id": cal_id, "calendar_locator": quote}


# NVDA as of its Q3 FY26 release (2025-11-19)
co = "NVIDIA Corporation"
rel = row("NVDA", "FILING_DOCUMENT", filed="2025-11-19")
k26 = row("NVDA", "PERIODIC_FILING", report_date="2026-01-25")  # FY2026 10-K is later; the Q4 FY25 operands come from it
q1, q2, q3 = (row("NVDA", "PERIODIC_FILING", report_date=d) for d in ("2025-04-27", "2025-07-27", "2025-10-26"))
docs = [docentry("NVDA", co, rel, "SEC_8K_EXHIBIT", "NVIDIA Corporation earnings release with outlook")] + [
    docentry("NVDA", co, r, "SEC_PERIODIC", f"NVIDIA Corporation Form {r['form']} ({r['accession']})") for r in (q1, q2, q3, k26)]
quote_n = "We operate on a 52- or 53-week year, ending on the last Sunday in January."
nv = {
    "symbol": "NVDA", "company_name": co, "status": "GUIDANCE", "reason": None,
    "url_prefixes": ["https://www.sec.gov/Archives/edgar/data/"], "documents": docs,
    "claims": [{"id": "NVDA-Q-GUIDANCE", "document_id": docs[0]["id"], "locator": "Outlook",
                "passage": "NVIDIA’s outlook for the fourth quarter of fiscal 2026 is as follows: •Revenue is expected to be $65.0 billion, plus or minus 2%.",
                "metric": "REVENUE", "assertion_kind": "COMPANY_GUIDANCE", "currency": "USD", "unit_multiplier": 1, "amount": None,
                "low": 63700000000.0, "high": 66300000000.0, "stated_point": 65000000000.0,
                "original_representation": "$65.0 billion, plus or minus 2%", "scope": "COMPANY", "scope_label": "全公司",
                "accounting_basis": "GAAP", "fiscal_label": "Q4 FY26", "period_kind": "QUARTER",
                "period_start": "2025-10-27", "period_end": "2026-01-25"}],
    "reported_quarters": [
        q("Q4 FY25", "2024-10-28", "2025-01-26", 39331000000.0, docs[4]["id"], "XBRL us-gaap:Revenues 2024-01-29..2025-01-26 minus ..2024-10-27",
          {"kind": "YTD_DIFFERENCE", "longer_document_id": docs[4]["id"], "longer_value": 130497000000.0, "longer_start": "2024-01-29",
           "shorter_document_id": docs[3]["id"], "shorter_value": 91166000000.0, "shorter_end": "2024-10-27"}),
        q("Q1 FY26", "2025-01-27", "2025-04-27", 44062000000.0, docs[1]["id"], "XBRL us-gaap:Revenues 2025-01-27..2025-04-27"),
        q("Q2 FY26", "2025-04-28", "2025-07-27", 46743000000.0, docs[2]["id"], "XBRL us-gaap:Revenues 2025-04-28..2025-07-27"),
        q("Q3 FY26", "2025-07-28", "2025-10-26", 57006000000.0, docs[3]["id"], "XBRL us-gaap:Revenues 2025-07-28..2025-10-26")],
    "forward_intervals": [interval("Q4 FY26", "2025-10-27", "2026-01-25", docs[3]["id"], quote_n),
                          interval(None, "2026-01-26", "2026-04-26", docs[3]["id"], quote_n),
                          interval(None, "2026-04-27", "2026-07-26", docs[3]["id"], quote_n),
                          interval(None, "2026-07-27", "2026-10-25", docs[3]["id"], quote_n)],
    "fy_reconciliation": None,
    "release_channels": {"sec_cik": 1045810, "wire_symbol": "NVDA", "wire_names": ["NVIDIA"],
                         "ir": {"kind": "Q4_PRESS_RELEASES", "url": "https://investor.nvidia.com/feed/PressRelease.svc/GetPressReleaseList"},
                         "ir_guidance_release_title": "NVIDIA Announces Financial Results for Third Quarter Fiscal 2026"},
    "reviewed_later_documents": [],
}

# MU as of its FQ4-25 release (2025-09-23)
co = "Micron Technology, Inc."
rel = row("MU", "FILING_DOCUMENT", filed="2025-09-23")
f1, f2, f3 = (row("MU", "PERIODIC_FILING", report_date=d) for d in ("2025-11-27", "2025-02-27", "2025-05-29"))
k25 = row("MU", "PERIODIC_FILING", report_date="2025-08-28")
docs = [docentry("MU", co, rel, "SEC_8K_EXHIBIT", "Micron Technology, Inc. earnings release with outlook")] + [
    docentry("MU", co, r, "SEC_PERIODIC", f"Micron Technology, Inc. Form {r['form']} ({r['accession']})") for r in (f1, f2, f3, k25)]
quote_m = "Our fiscal year is the 52- or 53-week period ending on the Thursday closest to August 31."
c = "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
mu = {
    "symbol": "MU", "company_name": co, "status": "GUIDANCE", "reason": None,
    "url_prefixes": ["https://www.sec.gov/Archives/edgar/data/"], "documents": docs,
    "claims": [{"id": "MU-Q-GUIDANCE", "document_id": docs[0]["id"], "locator": "Outlook",
                "passage": "FQ1-26 GAAP(1) Outlook Non-GAAP(2) Outlook Revenue $12.50 billion ± $300 million $12.50 billion ± $300 million",
                "metric": "REVENUE", "assertion_kind": "COMPANY_GUIDANCE", "currency": "USD", "unit_multiplier": 1, "amount": None,
                "low": 12200000000.0, "high": 12800000000.0, "stated_point": 12500000000.0,
                "original_representation": "$12.50 billion ± $300 million", "scope": "COMPANY", "scope_label": "全公司",
                "accounting_basis": "GAAP", "fiscal_label": "FQ1-26", "period_kind": "QUARTER",
                "period_start": "2025-08-29", "period_end": "2025-11-27"}],
    "reported_quarters": [
        q("FQ1-25", "2024-08-30", "2024-11-28", 8709000000.0, docs[1]["id"], f"XBRL {c} 2024-08-30..2024-11-28"),
        q("FQ2-25", "2024-11-29", "2025-02-27", 8053000000.0, docs[2]["id"], f"XBRL {c} 2024-11-29..2025-02-27"),
        q("FQ3-25", "2025-02-28", "2025-05-29", 9301000000.0, docs[3]["id"], f"XBRL {c} 2025-02-28..2025-05-29"),
        q("FQ4-25", "2025-05-30", "2025-08-28", 11315000000.0, docs[4]["id"], f"XBRL {c} 2024-08-30..2025-08-28 minus ..2025-05-29",
          {"kind": "YTD_DIFFERENCE", "longer_document_id": docs[4]["id"], "longer_value": 37378000000.0, "longer_start": "2024-08-30",
           "shorter_document_id": docs[3]["id"], "shorter_value": 26063000000.0, "shorter_end": "2025-05-29"})],
    "forward_intervals": [interval("FQ1-26", "2025-08-29", "2025-11-27", docs[4]["id"], quote_m),
                          interval(None, "2025-11-28", "2026-02-26", docs[4]["id"], quote_m),
                          interval(None, "2026-02-27", "2026-05-28", docs[4]["id"], quote_m),
                          interval(None, "2026-05-29", "2026-09-03", docs[4]["id"], quote_m)],
    "fy_reconciliation": None,
    "release_channels": {"sec_cik": 723125, "wire_symbol": "MU", "wire_names": ["Micron"],
                         "ir": {"kind": "Q4_PRESS_RELEASES", "url": "https://investors.micron.com/feed/PressRelease.svc/GetPressReleaseList"},
                         "ir_guidance_release_title": "Micron Technology, Inc. Reports Results for the Fourth Quarter and Full Year of Fiscal 2025"},
    "reviewed_later_documents": [],
}
for rec in (nv, mu):
    g.validate_issuer_record(rec, rec["symbol"])
reg = {"schema": "revenue-guidance-v1", "version": 1, "issuers": [nv, mu]}
(D / "bootstrap-registry.json").write_text(json.dumps(reg, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
print("ok")
