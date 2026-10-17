"""Synthetic BATCH08B real-caller fixtures; all I/O providers are replaced."""
import copy
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from tests import test_bottleneck_top20_v3 as existing
import build_v213_activation_bundle_v2 as builder
import bottleneck_top20_v3 as engine
import build_v213_scheduled_top20_report as scheduled
from contextlib import contextmanager

NOW = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)


class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW if tz else NOW.replace(tzinfo=None)


@contextmanager
def frozen():
    with mock.patch.object(builder, "datetime", Clock), mock.patch.object(scheduled, "datetime", Clock):
        yield


def documents(case="independent", positive=False):
    with frozen():
        docs = builder._synthetic_documents()
    stamp = NOW.isoformat()
    expiry = (NOW + timedelta(hours=1)).isoformat()
    for row in docs[-1]["records"]:
        cid = row["ticker"] + ":revenue"
        evidence = []
        for i, src in enumerate(row["sources"]):
            evidence.append(dict(observation_id=f"obs-{i}", source_id=src["source_id"],
                claim_ids=[cid], admitted=True, freshness="CURRENT", value=100,
                independence_group=f"publisher-{i}", origin_group=f"origin-{i}",
                content_sha256=str(i + 1) * 64, valid_until=expiry,
                published_at=stamp, as_of=stamp, primary=i == 0,
                claim_type="issuer_financial_statement", subject=row["ticker"],
                metric="revenue", period="2026Q2", unit="USD", currency="USD",
                basis="GAAP", scope="consolidated"))
        claim = dict(claim_id=cid, status="SUPPORTED", high_confidence_eligible=True,
                     independent_evidence_families=99, value=100, conflict_set=[],
                     evidence_ids=[r["observation_id"] for r in evidence])
        row["claim_evidence_audit"] = dict(schema_version=2, all_material_claims_supported=True,
            claims=[claim], evidence=evidence, validated_at=stamp, valid_until=expiry,
            full_research_eligible=False)
    row = docs[-1]["records"][0]
    audit = row["claim_evidence_audit"]
    evidence, claim = audit["evidence"], audit["claims"][0]
    if case in {"origin", "hash", "publisher"}:
        field = {"origin": "origin_group", "hash": "content_sha256", "publisher": "independence_group"}[case]
        evidence[1][field] = evidence[0][field]
    elif case == "chain":
        evidence.extend([copy.deepcopy(evidence[1]), copy.deepcopy(evidence[1])])
        for i, e in enumerate(evidence):
            e.update(observation_id=f"obs-{i}", independence_group=f"publisher-{i}",
                     origin_group=f"origin-{i}", content_sha256=str(i + 1) * 64)
        evidence[1]["independence_group"] = evidence[0]["independence_group"]
        evidence[2]["origin_group"] = evidence[1]["origin_group"]
        evidence[3]["content_sha256"] = evidence[2]["content_sha256"]
        claim["evidence_ids"] = [e["observation_id"] for e in evidence]
    elif case == "absent":
        row.pop("claim_evidence_audit")
    elif case == "audit_type":
        row["claim_evidence_audit"] = []
    elif case == "claims_type":
        audit["claims"] = {}
    elif case == "evidence_type":
        audit["evidence"] = {}
    elif case == "claim_type":
        audit["claims"] = [None]
    elif case == "id_type":
        claim["claim_id"] = None
    elif case == "empty_id":
        claim["claim_id"] = " "
    elif case == "ids_type":
        claim["evidence_ids"] = "obs-0 obs-1"
    elif case == "row_type":
        evidence[1] = None
    elif case == "row_claims_type":
        evidence[1]["claim_ids"] = claim["claim_id"]
    elif case == "missing_value":
        evidence[1].pop("value")
    elif case == "schema":
        audit["schema_version"] = 1
    elif case == "unsupported":
        audit["all_material_claims_supported"] = False
    elif case == "empty":
        audit["claims"] = []
    elif case == "claim_status":
        claim["status"] = "UNAVAILABLE"
    elif case == "claim_flag":
        claim["high_confidence_eligible"] = False
    elif case == "declared_conflict":
        claim["conflict_set"] = [{"value": 99}]
    elif case == "conflict":
        evidence[1]["value"] = 101
    elif case == "claim_value":
        claim["value"] = 99
    elif case == "unadmitted":
        evidence[1]["admitted"] = False
    elif case == "stale":
        evidence[1]["freshness"] = "STALE"
    elif case == "unbound_id":
        evidence[1]["observation_id"] = "unbound"
    elif case == "unbound_claim":
        evidence[1]["claim_ids"] = ["different-claim"]
    elif case == "expired_row":
        evidence[1]["valid_until"] = stamp
    elif case == "expired_audit":
        audit["valid_until"] = stamp
    elif case == "future_audit":
        audit["validated_at"] = (NOW + timedelta(days=1)).isoformat()
    elif case == "long_expiry":
        audit["valid_until"] = (NOW + timedelta(days=1)).isoformat()
    elif case == "malformed":
        evidence[1]["valid_until"] = "invalid"
    elif case == "missing_lineage":
        evidence[1].update(independence_group="", origin_group="", content_sha256="")
    elif case == "duplicate_claim":
        audit["claims"].append(copy.deepcopy(claim))
    elif case == "second_claim":
        other = copy.deepcopy(claim)
        other.update(claim_id="other", evidence_ids=["obs-0"])
        evidence[0]["claim_ids"].append("other")
        audit["claims"].append(other)
    if not positive:
        rows = json.loads(docs[0]["payloads"]["top20_json"])
        for factor in rows[0]["serenity_factors"]:
            rows[0]["serenity_factors"][factor] = 0.0
        builder._replace_top20_payload(docs[0], rows)
    return docs


def bundle_result(docs):
    with frozen():
        try:
            bundle = builder.build_bundle(*docs)
        except Exception as exc:
            return {"error_type": type(exc).__name__, "error": str(exc)}
    audit = json.loads(bundle["payloads"]["source_independence_json"])
    first = audit["records"][0]
    top = json.loads(bundle["payloads"]["top20_json"])[0]
    return {"raw_bundle": bundle, "mode": first["publication_evidence_mode"],
            "validated": first["public_logic_state"]["validated_company_thesis"],
            "missing": first["missing_or_review"], "logic": first["public_logic_state"],
            "factors": top["serenity_factors"],
            "qualified_count": audit["freshness_audit"]["evidence_qualified_candidate_count"]}


def share_facts(case="anchor"):
    facts = existing.SharesDilutionTests()._facts()
    latest = date(2026, 6, 27)
    end = latest + timedelta(days=35)
    rows = facts["facts"]["dei"]["EntityCommonStockSharesOutstanding"]["units"]["shares"]
    def pair(day):
        return [{"end": (day - timedelta(days=365)).isoformat(), "val": 100},
                {"end": day.isoformat(), "val": 120}]
    if case == "stale":
        rows[:] = pair(date(2012, 8, 1))
    elif case == "late":
        rows[:] = pair(latest + timedelta(days=106))
    elif case == "before":
        rows[:] = pair(latest - timedelta(days=1))
    elif case in {"lower", "upper"}:
        rows[:] = pair(latest + timedelta(days=0 if case == "lower" else 105))
    elif case == "earliest":
        rows.append({"end": (latest + timedelta(days=80)).isoformat(), "val": 150})
    elif case == "late_ignored":
        rows.append({"end": (latest + timedelta(days=150)).isoformat(), "val": 150})
    elif case == "nearest":
        rows.append({"end": (end - timedelta(days=300)).isoformat(), "val": 110})
    elif case in {"prior_lower", "prior_upper", "prior_outside_lower", "prior_outside_upper"}:
        days = {"prior_lower": 300, "prior_upper": 430, "prior_outside_lower": 299, "prior_outside_upper": 431}[case]
        rows[:] = [{"end": (end - timedelta(days=days)).isoformat(), "val": 100}, {"end": end.isoformat(), "val": 120}]
    elif case == "invalid":
        rows[-1]["val"] = 0
    return facts


def rank(facts, module=engine):
    layer = dict(id="synthetic", name_zh="Synthetic", chain="chips", chain_rank=4,
                 leopold_constraint="synthetic", filing_terms=[], capturers=[
                     dict(symbol="SYN", role="synthetic", source_url="https://issuer.example/f", source_date="2026-10")])
    market = dict(cagr_2y=0.2, ret_1y=0.3, ret_6m=0.2, price=10, currency="USD", market_cap=1e9)
    with mock.patch.multiple(module, load_json=lambda p: {"layers": [layer]},
            SERENITY=Path("missing-batch08b-serenity.json"), LEOPOLD=Path("missing-batch08b-leopold.json"),
            cik_index=lambda captured=None: {"SYN": 1}, companyfacts=lambda *a, **kw: copy.deepcopy(facts),
            yahoo_data=lambda *a, **kw: {"market": market, "name": "Synthetic"},
            taiwan_monthly_revenue=lambda *a: {}, cision_interim_revenue=lambda *a: {},
            korea_ir_revenue=lambda *a: None, usd_rate=lambda *a: 1,
            nasdaq_consensus=lambda *a: None, outlook=lambda *a, **kw: {}), \
            mock.patch.object(module.listing_lineage, "load", return_value={}):
        return module.build(None, NOW, with_news=False)
