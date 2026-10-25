"""Regenerates tests/fixtures/v213-orders-v3-probes.json: producer-to-reader regressions for Astra's r7 acceptance
(A1, A2, A4), each built by the real collector (revenue_guidance_release_check.receipt_for), the real loaders
(revenue_guidance.load_registry / load_approval) and the real sealer function
(publish_sealed_snapshot._with_order_forecast), from frozen real NVDA inputs (tests/fixtures/orders-v3-probe-inputs.json:
the reviewed registry record and its approval decisions, the RPO recognition schedule and order figure of the genuine
2026-09-28 rebuild, and the captured official IR feed). The Worker test parses the exact produced outlooks.

Cases (one outlook each):
- control: the approved record, quiet SEC/wire/IR channels -> revenue AVAILABLE beside the 12-month recognition;
- unreviewed_extra_field: an unknown 2,000,000-character field on the first actual, approval not renewed ->
  revenue INVALID / UNREVIEWED_INPUTS, the recognition kept (A1); the same without any order inputs keeps the
  diagnostic on the fully unavailable branch;
- evidence_limit_fiscal_label: the first actual's fiscal_label replaced by 2,000,000 characters -> revenue
  EVIDENCE_LIMIT, the recognition kept (A4);
- title_<n>: one unreviewed official-IR item dated 2026-09-28 with a compound material title -> review required,
  revenue unavailable (A2); scheduling-only titles stay current (positive controls).
Run from the repository root:
    python tests/fixtures/make_orders_v3_probes.py [--check]
--check exits 1 when the committed fixture differs from a fresh build."""
import copy
import hashlib
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import publish_sealed_snapshot  # noqa: E402
import revenue_guidance  # noqa: E402
import revenue_guidance_release_check as release_check  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
INPUTS = FIXTURES / "orders-v3-probe-inputs.json"
OUTPUT = FIXTURES / "v213-orders-v3-probes.json"
EMPTY_CLAIMS = {"status": "EMPTY", "sha256": "0" * 64, "issuers": {}}
MATERIAL_TITLES = [
    "NVIDIA Withdraws Its Financial Targets",
    "NVIDIA Reports Record Revenue and Announces Conference Call",
    "NVIDIA Reports Quarterly Earnings and Declares Dividend",
    "NVIDIA Announces Revenue of $110 Billion and Webcast",
    # Astra r8 A2: a meeting outcome or a release date in another clause never erases a clause reporting figures
    "NVIDIA Reports Record Revenue and Announces Date of Conference Call",
    "NVIDIA Reports Quarterly Earnings and Announces Results of Its Annual General Meeting",
    "NVIDIA Announces Revenue of $110 Billion and Date of Webcast",
    # Astra r9 A2: "to report" followed by figures or an expectation is not a scheduling notice
    "NVIDIA Expects to Report Revenue of $100 Billion",
    "NVIDIA Expects to Report a 20% Decline in Revenue",
    # Astra r10 A2: only a whole known notice is exempt; a trailing figure after punctuation keeps the review
    "NVIDIA to Report Third Quarter Revenue, Up 50% Year over Year",
    "NVIDIA to Report Third Quarter Revenue: $100 Billion",
]
SCHEDULING_TITLES = [
    "NVIDIA to Report Third Quarter Fiscal 2027 Results on November 18, 2026",
    "NVIDIA Declares Quarterly Dividend Payment",
    "NVIDIA Announces Results of Its Annual General Meeting",
    "NVIDIA Announces Date of Third Quarter Fiscal 2027 Results and Conference Call",
]


def _instant(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _loaded(inputs: dict, tmp: Path) -> tuple[dict, dict, dict]:
    """The one-issuer registry and its approval written as files and read back through the real loaders."""
    registry_bytes = (json.dumps(inputs["registry"], ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    (tmp / "registry.json").write_bytes(registry_bytes)
    record = inputs["registry"]["issuers"][0]
    approval = {"schema": "revenue-guidance-approval-v1", "registry_sha256": hashlib.sha256(registry_bytes).hexdigest(),
                "approved_at": inputs["approved_at"], "reviewer": inputs["reviewer"],
                "records": {record["symbol"]: {"record_sha256": hashlib.sha256(revenue_guidance.canonical_json(record).encode("utf-8")).hexdigest(),
                                               "decisions": inputs["approval_decisions"]}}}
    (tmp / "approval.json").write_bytes((json.dumps(approval, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    return revenue_guidance.load_registry(tmp / "registry.json"), revenue_guidance.load_approval(tmp / "approval.json"), record


def _receipt(inputs: dict, record: dict, extra_ir_title: str | None) -> dict:
    now = _instant(inputs["checked_at"])
    sec = inputs["sec_rows"]
    forms, dates, items, accs, reports = (list(col) for col in zip(*sec))

    def sec_fetch(url):
        return {"filings": {"recent": {"form": forms, "filingDate": dates, "items": items, "accessionNumber": accs, "reportDate": reports}}}

    def wire_fetch(url):
        offset = int(url.rsplit("offset=", 1)[1])
        rows = inputs["wire_rows"][offset:offset + release_check.WIRE_PAGE]
        return {"data": {"rows": [{"created": d, "title": t, "url": u} for d, t, u in rows], "totalrecords": len(inputs["wire_rows"])}}

    rows = list(inputs["ir_rows"])
    if extra_ir_title is not None:
        rows.insert(0, {"PressReleaseDate": "09/28/2026 07:00:00", "Headline": extra_ir_title,
                        "LinkToDetailPage": "/news/press-release-details/2026/probe/default.aspx"})

    def ir_fetch(url):
        return json.dumps({"GetPressReleaseListResult": rows if "year=2026" in url else []}).encode("utf-8")

    return release_check.receipt_for(record, now, sec_fetch, wire_fetch, ir_fetch)


def _outlook(inputs: dict, registry: dict, approval: dict, receipt: dict) -> dict:
    checks = {"schema": "revenue-guidance-release-checks-v1", "generated_at": receipt["checked_at"], "issuers": {"NVDA": [receipt]}}
    return publish_sealed_snapshot._with_order_forecast(
        "NVDA", None, copy.deepcopy(inputs["stock_orders"]), copy.deepcopy(inputs["recognition"]), _instant(inputs["cutoff"]),
        EMPTY_CLAIMS, revenue_registry=registry, consensus_cache=None, release_checks_cache=checks, revenue_approval=approval)


def build() -> dict:
    inputs = json.loads(INPUTS.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        registry, approval, record = _loaded(inputs, Path(tmp))
    quiet = _receipt(inputs, record, None)
    cases = {"control": {"title": None, "receipt_status": quiet["status"], "outlook": _outlook(inputs, registry, approval, quiet)}}

    unreviewed = copy.deepcopy(registry)
    unreviewed["issuers"]["NVDA"]["reported_quarters"][0]["extra_unknown"] = "x" * 2_000_000
    cases["unreviewed_extra_field"] = {"title": None, "receipt_status": quiet["status"],
                                       "outlook": _outlook(inputs, unreviewed, approval, quiet)}

    no_orders = dict(inputs, stock_orders=None, recognition=None)
    cases["unreviewed_without_orders"] = {"title": None, "receipt_status": quiet["status"],
                                          "outlook": _outlook(no_orders, unreviewed, approval, quiet)}

    limited = copy.deepcopy(registry)
    limited["issuers"]["NVDA"]["reported_quarters"][0]["fiscal_label"] = "x" * 2_000_000
    cases["evidence_limit_fiscal_label"] = {"title": None, "receipt_status": quiet["status"],
                                            "outlook": _outlook(inputs, limited, approval, quiet)}

    for n, title in enumerate(MATERIAL_TITLES + SCHEDULING_TITLES):
        receipt = _receipt(inputs, record, title)
        cases[f"title_{n}"] = {"title": title, "material": title in MATERIAL_TITLES, "receipt_status": receipt["status"],
                               "outlook": _outlook(inputs, registry, approval, receipt)}
    return {"origin": "tests/fixtures/make_orders_v3_probes.py (Astra r7 acceptance A1/A2/A4 producer-to-reader regressions)",
            "generated_at": inputs["cutoff"], "cases": cases}


if __name__ == "__main__":
    fresh = json.dumps(build(), ensure_ascii=False, indent=1) + "\n"
    if "--check" in sys.argv:
        sys.exit(0 if OUTPUT.exists() and OUTPUT.read_text(encoding="utf-8") == fresh else 1)
    OUTPUT.write_bytes(fresh.encode("utf-8"))
