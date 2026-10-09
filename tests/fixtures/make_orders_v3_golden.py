"""Regenerates tests/fixtures/v213-orders-v3-golden-sealed.json: the sealed outlook (order_forecast v2 + order_forecast_v3)
of every reviewed record in revenue-guidance-issuers-r2.json, produced by the real sealer function
scripts/publish_sealed_snapshot.py _with_order_forecast at the fixed cutoff the Worker golden test uses
(2026-09-28T15:00:00Z, after the writer's 14:45Z CRWV IR review), with the real consensus capture fixture and one
synthetic OK latest-release receipt per GUIDANCE issuer (checked an hour before the cutoff, anchored at the guidance
reference document; a complete OK ISSUER_IR channel and SEC_WIRE_IR coverage for issuers with a reviewed official IR
channel, Astra W1 ruling astra-ir-coverage).

A1 (Astra acceptance r7): also regenerates tests/fixtures/revenue-guidance-approval-v1.json, the synthetic enforced
reviewed profile for the fixture registry: the registry bytes' sha256, each record's canonical-JSON sha256 and a
timestamped decision for every operative input (claims, actuals, calendar, FY reconciliation, reaffirmations,
routing). The fixture registry carries no consensus gate, so build_v3's fail-closed default defers the Korean
consensus route (CONSENSUS_DEFERRED on the NOT_DISCLOSED records) for the first rollout.
Run from the repository root:
    python tests/fixtures/make_orders_v3_golden.py [--check]
--check exits 1 when a committed fixture differs from a fresh build."""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import publish_sealed_snapshot  # noqa: E402
import revenue_guidance  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
OUTPUT = FIXTURES / "v213-orders-v3-golden-sealed.json"
APPROVAL_OUTPUT = FIXTURES / "revenue-guidance-approval-v1.json"
# The build clock sits after the writer's 14:45Z CRWV IR review (verify/ir-live-2026-09-28.txt), so the reviewed
# item is admissible; the strict reviewed_at <= cutoff rule is unchanged, only the build time moves past the review.
# The Worker golden test parses with the same generated_at (cloud/test/v213-order-forecast-v3.test.ts GOLDEN_GENERATED).
CUTOFF = datetime(2026, 9, 28, 15, 0, tzinfo=timezone.utc)
CHECKED_AT = "2026-09-28T14:00:00Z"
# The synthetic review instant: after every fixture document retrieval and before the fixed build cutoff.
REVIEWED_AT = "2026-09-28T14:45:00Z"
EMPTY_CLAIMS = {"status": "EMPTY", "sha256": "0" * 64, "issuers": {}}  # no reviewed order claims (the tests' convention)


def make_approval(registry_path: Path) -> tuple[dict, dict]:
    """The synthetic reviewed profile for the fixture registry: exact byte/record digests plus a decision for every
    operative input, all reviewed at one fixed instant before the cutoff (A1: synthetic data, writer-owned real
    file). Returns (the file shape sealed to tests/fixtures/revenue-guidance-approval-v1.json, the loader shape
    build_v3 consumes - the same content with status OK and the file bytes' sha256)."""
    raw = registry_path.read_bytes()
    registry_sha = hashlib.sha256(raw).hexdigest()
    data = json.loads(raw.decode("utf-8"))
    records: dict[str, dict] = {}
    for rec in data["issuers"]:
        record_sha = hashlib.sha256(revenue_guidance.canonical_json(rec).encode("utf-8")).hexdigest()
        decisions: list[dict] = []
        for claim in rec.get("claims", []):
            decisions.append({"kind": "CLAIM", "ref": claim["id"], "decision": "VERBATIM_IN_SOURCE", "reviewed_at": REVIEWED_AT})
            if claim.get("reaffirmed_by"):
                decisions.append({"kind": "REAFFIRMATION", "ref": claim["id"], "decision": "VERBATIM_IN_SOURCE", "reviewed_at": REVIEWED_AT})
        for actual in rec.get("reported_quarters", []):
            decisions.append({"kind": "ACTUAL", "ref": actual["end"], "decision": "VALUE_IN_SOURCE", "reviewed_at": REVIEWED_AT})
        decisions.append({"kind": "CALENDAR", "ref": "calendar", "decision": "RULE_QUOTED", "reviewed_at": REVIEWED_AT})
        if rec.get("fy_reconciliation") is not None:
            decisions.append({"kind": "FY_RECONCILIATION", "ref": "fy_reconciliation", "decision": "DERIVATION_OPERANDS_IN_SOURCE",
                              "reviewed_at": REVIEWED_AT})
        routing_decision = "NONDISCLOSURE_CONFIRMED" if rec["status"] == "NOT_DISCLOSED" else "RULE_QUOTED"
        decisions.append({"kind": "ROUTING", "ref": "routing", "decision": routing_decision, "reviewed_at": REVIEWED_AT})
        records[rec["symbol"]] = {"record_sha256": record_sha, "decisions": decisions}
    file_data = {"schema": "revenue-guidance-approval-v1", "registry_sha256": registry_sha, "approved_at": REVIEWED_AT,
                 "reviewer": "writer", "records": records}
    file_bytes = (json.dumps(file_data, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    loader_shape = {"status": "OK", "sha256": hashlib.sha256(file_bytes).hexdigest(), **file_data}
    return file_data, loader_shape


def receipt(record: dict) -> dict:
    docs = {d["id"]: d for d in record["documents"]}
    claims = [c for c in record["claims"] if c["period_kind"] == "QUARTER"] or [c for c in record["claims"] if c["period_kind"] == "FISCAL_YEAR"]
    reference = revenue_guidance.guidance_reference_document_id(claims[0], docs)
    rc = record.get("release_channels") or {}
    cik = rc.get("sec_cik")
    sec_url = f"https://data.sec.gov/submissions/CIK{cik:010d}.json" if cik else "https://data.sec.gov/submissions/CIK0000000000.json"
    wire_sym = (rc.get("wire_symbol") or record["symbol"]).lower()
    wire_url = f"https://api.nasdaq.com/api/news/topic/press_release?q=symbol:{wire_sym}|assetclass:stocks"
    channels = [{"kind": "SEC_SUBMISSIONS", "url": sec_url, "status": "OK",
                 "checked_through": "2026-09-28", "complete": True},
                {"kind": "WIRE_PRESS_RELEASES", "url": wire_url,
                 "status": "OK", "checked_through": "2026-09-28", "complete": True}]
    coverage = "SEC_AND_WIRE"
    ir = rc.get("ir")
    if isinstance(ir, dict) and isinstance(ir.get("url"), str) and ir["url"].startswith("https://"):
        # The official IR channel (Astra W1 ruling, astra-ir-coverage): the registry's own feed URL, a synthetic OK
        # read; records without a reviewed IR channel keep the classic SEC_AND_WIRE coverage (their company-guidance
        # revenue path stays suspended by the IR_COVERAGE_MISSING rule).
        channels.append({"kind": "ISSUER_IR", "url": ir["url"], "status": "OK",
                         "checked_through": "2026-09-28", "complete": True})
        coverage = "SEC_WIRE_IR"
    body = {"issuer": record["symbol"], "checked_at": CHECKED_AT, "status": "OK", "guidance_document_id": reference,
            "guidance_published_date": docs[reference]["published_date"], "anchor_end": record["reported_quarters"][-1]["end"],
            "coverage": coverage,
            "channels": channels,
            "later_documents": []}
    body["digest"] = revenue_guidance.compute_receipt_digest(body)
    return body


def build() -> dict:
    registry = revenue_guidance.load_registry(FIXTURES / "revenue-guidance-issuers-r2.json")
    consensus = json.loads((FIXTURES / "consensus-capture-writer.json").read_text(encoding="utf-8"))
    checks = {"schema": "revenue-guidance-release-checks-v1", "generated_at": CHECKED_AT,
              "issuers": {s: [receipt(r)] for s, r in registry["issuers"].items() if r["status"] == "GUIDANCE"}}
    _, approval = make_approval(FIXTURES / "revenue-guidance-issuers-r2.json")
    return {symbol: publish_sealed_snapshot._with_order_forecast(symbol, None, None, None, CUTOFF, EMPTY_CLAIMS, revenue_registry=registry,
                                                                 consensus_cache=consensus, release_checks_cache=checks,
                                                                 revenue_approval=approval)
            for symbol in registry["issuers"]}


if __name__ == "__main__":
    fresh = json.dumps(build(), ensure_ascii=False, indent=1) + "\n"
    approval_file, _ = make_approval(FIXTURES / "revenue-guidance-issuers-r2.json")
    fresh_approval = json.dumps(approval_file, ensure_ascii=False, indent=1) + "\n"
    if "--check" in sys.argv:
        sys.exit(0 if OUTPUT.read_text(encoding="utf-8") == fresh and APPROVAL_OUTPUT.read_text(encoding="utf-8") == fresh_approval else 1)
    OUTPUT.write_bytes(fresh.encode("utf-8"))
    APPROVAL_OUTPUT.write_bytes(fresh_approval.encode("utf-8"))
