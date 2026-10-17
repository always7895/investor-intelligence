"""Reviewed order claims (scripts/order_claims.py) and the version-2 order forecast (scripts/order_forecast.py build_v2):
registry validation, selection at the build cutoff, supersession of the filing and the shared Python/Worker fixture
tests/fixtures/v213-order-forecast-v2.json (Astra contract ORDERS-V2-01 and its revision-1 review). Network-free."""
from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import order_claims as oc  # noqa: E402
import order_forecast as of  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "v213-order-forecast-v2.json"
CUTOFF = datetime(2026, 9, 27, 1, 0, 0, tzinfo=timezone.utc)  # the fixture document's generated_at
REPORT_DAY = CUTOFF.date()
PREFIX = "https://investors.synthetic.example/ir/"
SHA = "a" * 64
FILING = "0000000000-26-000001"


def document(doc_id: str, issuer: str, kind: str, published: str, *, lineage: str | None = None, url: str | None = None,
             retrieved: str = "2026-09-20T00:00:00Z") -> dict:
    sec = kind in oc.SEC_FORMS
    out = {"id": doc_id, "issuer": issuer, "publisher": "Synthetic Corp", "title": f"{kind} {published}", "source_kind": kind,
           "url": url or (f"https://www.sec.gov/Archives/edgar/data/1/{doc_id}.htm" if sec else f"{PREFIX}{doc_id}.pdf"),
           "published_date": published, "retrieved_at": retrieved, "sha256": SHA, "byte_size": 1000, "lineage_id": lineage or doc_id}
    if kind == "SEC_8K_EXHIBIT":
        out["sec"] = {"accession": "0000000001-26-000009", "form": "8-K", "exhibit": "99.1"}
    elif sec:
        out["sec"] = {"accession": "0000000001-26-000009", "form": "10-Q"}
    return out


def claim(claim_id: str, symbol: str, doc_id: str, metric: str, amount: float | None, as_of: str, *, series: str | None = None,
          scope: str = "COMPANY", revision: dict | None = None, checked: str = "2026-09-21T00:00:00Z", **extra) -> dict:
    out = {"id": claim_id, "symbol": symbol, "document_id": doc_id, "locator": "p.1", "passage": f"{metric} statement {claim_id}",
           "metric": metric, "assertion_kind": "COMPANY_GUIDANCE" if metric == "ORDER_GUIDANCE" else "DISCLOSED_FACT",
           "currency": "USD", "unit_multiplier": 1_000_000_000, "amount": amount, "as_of": as_of, "scope": scope,
           "series_id": series or f"{symbol}:{metric}:{scope}", "basis": "ASC 606", "revision": revision or {"kind": "ORIGINAL"},
           "review": {"checked_at": checked, "receipt": "fixture-receipt"}}
    if scope != "COMPANY":
        out["scope_label"] = "新簽長約"
    if metric in oc.PERIOD_METRICS:
        out.update(period_start="2026-01-01", period_end="2026-12-31", period_kind="YEAR")
    out.update(extra)
    return out


def registry(documents: list[dict], claims: list[dict], issuers: tuple[str, ...] = ("S1", "S2", "S3", "S4", "S5", "S6", "S7")) -> dict:
    return {"schema": oc.SCHEMA, "issuers": {s: {"name": f"Synthetic {s}", "url_prefixes": [PREFIX]} for s in issuers},
            "documents": documents, "claims": claims}


def loaded(raw: dict) -> dict:
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "order-claims-v2.json"
        path.write_text(json.dumps(raw), encoding="utf-8")
        return oc.load(path)


def periodic(**change) -> dict:
    """A deep-report order scenario (company_deep_report.order_scenario) for the periodic base."""
    out = {"status": "DISCLOSED", "form": "10-Q", "filed": "2026-08-10", "url": "https://www.sec.gov/Archives/synthetic-base.htm",
           "rpo": 40e9, "rpo_as_of": "2026-06-30", "quarter_revenue": 8e9, "quarter_start": "2026-04-01", "quarter_end": "2026-06-30",
           "quarter_basis": "FRAME", "accession": FILING, "passage": "30% within six months and 55% within twelve months",
           "report_date": "2026-06-30", "horizons": {"m6": {"share_pct": 30.0, "derived": False},
                                                     "m12": {"share_pct": 55.0, "derived": False}, "m24": None}}
    out.update(change)
    return out


def build(symbol: str, raw: dict, rec: dict | None = None, stock: dict | None = None) -> dict:
    return of.build_v2(symbol, stock, rec, REPORT_DAY, CUTOFF, loaded(raw))


def cases() -> dict:
    """The shared cases: inputs and the Python output the Worker must reproduce exactly."""
    base_docs = [document("S1-8K", "S1", "SEC_8K_EXHIBIT", "2026-09-10", lineage="S1-Q3"),
                 document("S1-PR", "S1", "ISSUER_EARNINGS_RELEASE", "2026-09-10", lineage="S1-Q3"),
                 document("S1-REMARKS", "S1", "ISSUER_PREPARED_REMARKS", "2026-09-11")]
    base_claims = [claim("S1-RPO", "S1", "S1-8K", "RPO_STOCK", 48, "2026-08-31"),
                   claim("S1-SCHED", "S1", "S1-8K", "RECOGNITION_SCHEDULE", None, "2026-08-31", stock_claim_id="S1-RPO",
                         shares={"m6": 32.0, "m12": 58.0, "m24": 80.0}),
                   claim("S1-RPO-MIRROR", "S1", "S1-PR", "RPO_STOCK", 48, "2026-08-31"),
                   claim("S1-CONTRACT", "S1", "S1-REMARKS", "SIGNED_CONTRACT_VALUE", 5, "2026-09-11", scope="CONTRACT",
                         revision={"kind": "SUPPLEMENTS", "overlap": "UNKNOWN"}, summary="新簽5年供貨合約約 US$5.0B")]
    conflict_docs = [document("S2-A", "S2", "ISSUER_EARNINGS_RELEASE", "2026-09-05"), document("S2-B", "S2", "ISSUER_PREPARED_REMARKS", "2026-09-06")]
    conflict_claims = [claim("S2-RPO-A", "S2", "S2-A", "RPO_STOCK", 12, "2026-08-31"), claim("S2-RPO-B", "S2", "S2-B", "RPO_STOCK", 13, "2026-08-31")]
    revision_docs = [document("S3-A", "S3", "ISSUER_EARNINGS_RELEASE", "2026-09-01"), document("S3-B", "S3", "ISSUER_CONTRACT_ANNOUNCEMENT", "2026-09-02"),
                     document("S3-C", "S3", "ISSUER_EARNINGS_RELEASE", "2026-09-08")]
    revision_claims = [claim("S3-RPO", "S3", "S3-A", "RPO_STOCK", 10, "2026-08-31"),
                       claim("S3-DEAL", "S3", "S3-B", "SIGNED_CONTRACT_VALUE", 2, "2026-09-02", scope="CONTRACT",
                             revision={"kind": "SUPPLEMENTS", "overlap": "INCLUDED"}, summary="合約 US$2.0B"),
                       claim("S3-RPO-FIX", "S3", "S3-C", "RPO_STOCK", 10.5, "2026-08-31",
                             revision={"kind": "REPLACES", "targets": ["S3-RPO"], "reason": "issuer correction of the RPO"}),
                       claim("S3-DEAL-OFF", "S3", "S3-C", "SIGNED_CONTRACT_VALUE", 0, "2026-09-08", scope="CONTRACT",
                             revision={"kind": "CANCELS", "targets": ["S3-DEAL"], "reason": "customer terminated the agreement"},
                             summary="合約取消")]
    late_docs = [document("S4-LATE", "S4", "ISSUER_EARNINGS_RELEASE", "2026-09-27", retrieved="2026-09-27T00:20:00Z")]
    late_claims = [claim("S4-RPO", "S4", "S4-LATE", "RPO_STOCK", 60, "2026-08-31", checked="2026-09-27T00:30:00Z")]
    fix_docs = [document("S6-FIX", "S6", "ISSUER_EARNINGS_RELEASE", "2026-08-20")]
    fix_claims = [claim("S6-RPO-FIX", "S6", "S6-FIX", "RPO_STOCK", 40.4, "2026-06-30",
                        revision={"kind": "REPLACES", "targets": [f"FILING:{FILING}"], "reason": "issuer restated the filing's RPO"})]
    zero_docs = [document("S7-Z", "S7", "ISSUER_EARNINGS_RELEASE", "2026-09-05")]
    zero_claims = [claim("S7-RPO-ZERO", "S7", "S7-Z", "RPO_STOCK", 0, "2026-08-31")]
    # S8: the most evidence an issuer may seal (4 documents, 8 claims, 60-character summaries, 1000-character passages).
    max_docs = [document(f"S8-D{i}", "S8", "ISSUER_EARNINGS_RELEASE", f"2026-09-0{i}") for i in range(1, 5)]
    max_claims = [claim("S8-RPO", "S8", "S8-D1", "RPO_STOCK", 30, "2026-08-31", passage="R" * 1000),
                  claim("S8-SCHED", "S8", "S8-D1", "RECOGNITION_SCHEDULE", None, "2026-08-31", stock_claim_id="S8-RPO",
                        shares={"m6": 40.0, "m12": 70.0, "m24": 90.0}, passage="S" * 1000)]
    max_claims += [claim(f"S8-C{i}", "S8", f"S8-D{1 + i % 4}", "SIGNED_CONTRACT_VALUE", i, "2026-08-31", scope="CONTRACT",
                         series=f"S8:CONTRACT:{i}", revision={"kind": "SUPPLEMENTS", "overlap": "UNKNOWN"},
                         summary=f"合約{i}" + "約" * 57, passage=f"contract {i} " + "P" * 980) for i in range(1, 7)]
    # S9: the largest presentation within the shared budget (URLs of 167 characters, CJK locators, passages and summaries):
    # 6 claims x (167 + 30 + 160) + 4 summaries x 60 + 4 scope labels x 4 = 2,398 of 2,400 code points.
    sec_url = "https://www.sec.gov/Archives/edgar/data/9/"
    big_urls = [sec_url + "d0" + "z" * (167 - len(sec_url) - 6) + ".htm"] + \
               [PREFIX + f"d{i}" + "z" * (167 - len(PREFIX) - 6) + ".pdf" for i in range(1, 4)]
    big_docs = [document("S9-D0", "S9", "SEC_8K_EXHIBIT", "2026-09-02", url=big_urls[0])] + \
               [document(f"S9-D{i}", "S9", "ISSUER_PREPARED_REMARKS", f"2026-09-0{2 + i}", url=big_urls[i]) for i in range(1, 4)]
    big_claims = [claim("S9-RPO", "S9", "S9-D0", "RPO_STOCK", 30, "2026-08-31", locator="頁" * 30, passage="證" * 1000),
                  claim("S9-SCHED", "S9", "S9-D0", "RECOGNITION_SCHEDULE", None, "2026-08-31", stock_claim_id="S9-RPO",
                        shares={"m6": 40.0, "m12": 70.0}, locator="頁" * 30, passage="證" * 1000)]
    big_claims += [claim(f"S9-C{i}", "S9", f"S9-D{1 + (i - 1) % 3}", "SIGNED_CONTRACT_VALUE", i, "2026-08-31", scope="CONTRACT",
                         series=f"S9:CONTRACT:{i}", revision={"kind": "SUPPLEMENTS", "overlap": "UNKNOWN"}, locator="頁" * 30,
                         summary=f"合{i}" + "約" * 58, passage="證" * 1000) for i in range(1, 5)]
    # S10: a later RPO stated only as a range (a unit of billions); S11: a 6-month-only schedule that has ended.
    range_docs = [document("S10-R", "S10", "ISSUER_EARNINGS_RELEASE", "2026-09-05")]
    range_claims = [claim("S10-RPO", "S10", "S10-R", "RPO_STOCK", None, "2026-08-31", null_reason="stated as a lower bound", bounds={"lower": 40})]
    ended_docs = [document("S11-E", "S11", "ISSUER_EARNINGS_RELEASE", "2026-03-20")]
    ended_claims = [claim("S11-RPO", "S11", "S11-E", "RPO_STOCK", 20, "2026-03-15"),
                    claim("S11-SCHED", "S11", "S11-E", "RECOGNITION_SCHEDULE", None, "2026-03-15", stock_claim_id="S11-RPO", shares={"m6": 45.0})]
    # S12: two equal stocks with contradictory schedules; S13: an older, different registry stock; S14: the filing's own figure.
    pair_docs = [document("S12-D", "S12", "ISSUER_EARNINGS_RELEASE", "2026-09-12"), document("S12-E", "S12", "ISSUER_EARNINGS_RELEASE", "2026-09-13")]
    pair_claims = [claim("S12-A", "S12", "S12-D", "RPO_STOCK", 40, "2026-06-30"),
                   claim("S12-S", "S12", "S12-D", "RECOGNITION_SCHEDULE", None, "2026-06-30", stock_claim_id="S12-A", shares={"m6": 30.0, "m12": 55.0}),
                   claim("S12-B", "S12", "S12-E", "RPO_STOCK", 40, "2026-06-30"),
                   claim("S12-T", "S12", "S12-E", "RECOGNITION_SCHEDULE", None, "2026-06-30", stock_claim_id="S12-B", shares={"m6": 40.0, "m12": 90.0})]
    older_docs = [document("S13-D", "S13", "ISSUER_EARNINGS_RELEASE", "2026-09-12")]
    older_claims = [claim("S13-RPO", "S13", "S13-D", "RPO_STOCK", 30, "2026-05-31")]
    same_docs = [document("S14-D", "S14", "ISSUER_EARNINGS_RELEASE", "2026-08-12")]
    same_claims = [claim("S14-RPO", "S14", "S14-D", "RPO_STOCK", 40, "2026-06-30")]
    # S16: supplementary-plane characters up to the UTF-16 budget (4 documents, 6 claims).
    astral_docs = [document(f"S16-D{i}", "S16", "ISSUER_EARNINGS_RELEASE", f"2026-09-0{i + 1}", url=f"{PREFIX}astral-d{i}.pdf")
                   for i in range(4)]  # URLs without the issuer, so a renamed copy keeps the same size
    astral_claims = [claim("S16-RPO", "S16", "S16-D0", "RPO_STOCK", 30, "2026-08-31", passage="𠮷" * 1000),
                     claim("S16-SCHED", "S16", "S16-D0", "RECOGNITION_SCHEDULE", None, "2026-08-31", stock_claim_id="S16-RPO",
                           shares={"m6": 40.0, "m12": 70.0}, passage="𠮷" * 1000)]
    astral_claims += [claim(f"S16-C{i}", "S16", f"S16-D{i % 4}", "SIGNED_CONTRACT_VALUE", i, "2026-08-31", scope="CONTRACT",
                            series=f"S16:C{i}", revision={"kind": "SUPPLEMENTS", "overlap": "UNKNOWN"}, summary=f"合約{i}" + "𠮷" * 10,
                            passage="𠮷" * 1000) for i in range(1, 5)]
    for row in astral_claims:  # locators grow until the issuer sits at the budget
        row["locator"] = "𠮷"
    urls = {d["id"]: d["url"] for d in astral_docs}
    while True:
        grown = False
        for row in astral_claims:
            projected = [dict(c, checked_at="x") for c in astral_claims]
            if len(row["locator"]) < 80 and oc.presentation_size(astral_docs, projected) + 2 <= oc.PRESENTATION_BUDGET:
                row["locator"] += "𠮷"
                grown = True
        if not grown:
            break
    # S17: equal schedules spelled as integers and decimals; S18: equal ranges spelled 40 and 40.0 (one value each).
    spell_docs = [document("S17-D", "S17", "ISSUER_EARNINGS_RELEASE", "2026-09-12"), document("S17-E", "S17", "ISSUER_EARNINGS_RELEASE", "2026-09-13")]
    spell_claims = [claim("S17-A", "S17", "S17-D", "RPO_STOCK", 40, "2026-06-30"),
                    claim("S17-S", "S17", "S17-D", "RECOGNITION_SCHEDULE", None, "2026-06-30", stock_claim_id="S17-A", shares={"m6": 30.0, "m12": 55.0}),
                    claim("S17-B", "S17", "S17-E", "RPO_STOCK", 40, "2026-06-30"),
                    claim("S17-T", "S17", "S17-E", "RECOGNITION_SCHEDULE", None, "2026-06-30", stock_claim_id="S17-B", shares={"m6": 30, "m12": 55})]
    bound_docs = [document("S18-D", "S18", "ISSUER_EARNINGS_RELEASE", "2026-09-12"), document("S18-E", "S18", "ISSUER_EARNINGS_RELEASE", "2026-09-13")]
    bound_claims = [claim("S18-A", "S18", "S18-D", "RPO_STOCK", None, "2026-08-31", null_reason="lower bound", bounds={"lower": 40}),
                    claim("S18-B", "S18", "S18-E", "RPO_STOCK", None, "2026-08-31", null_reason="lower bound", bounds={"lower": 40.0})]
    # S19: equal ranges whose lower bound is written 0 and -0.0; S15: zero stocks written 0, -0.0 and 0e0 (one value each).
    signed_docs = [document("S19-D", "S19", "ISSUER_EARNINGS_RELEASE", "2026-09-12"), document("S19-E", "S19", "ISSUER_EARNINGS_RELEASE", "2026-09-13")]
    signed_claims = [claim("S19-A", "S19", "S19-D", "RPO_STOCK", None, "2026-08-31", null_reason="range", bounds={"lower": 0, "upper": 50}),
                     claim("S19-B", "S19", "S19-E", "RPO_STOCK", None, "2026-08-31", null_reason="range", bounds={"lower": -0.0, "upper": 50.0})]
    zeros_docs = [document(f"S15-{k}", "S15", "ISSUER_EARNINGS_RELEASE", f"2026-09-1{k}") for k in range(3)]
    zeros_claims = [claim(f"S15-Z{k}", "S15", f"S15-{k}", "RPO_STOCK", amount, "2026-08-31") for k, amount in enumerate((0, -0.0, 0e0))]
    full = registry(base_docs + conflict_docs + revision_docs + late_docs + fix_docs + zero_docs + max_docs + big_docs + range_docs + ended_docs
                    + pair_docs + older_docs + same_docs + astral_docs + spell_docs + bound_docs + signed_docs + zeros_docs,
                    base_claims + conflict_claims + revision_claims + late_claims + fix_claims + zero_claims + max_claims + big_claims
                    + range_claims + ended_claims + pair_claims + older_claims + same_claims + astral_claims + spell_claims + bound_claims
                    + signed_claims + zeros_claims,
                    issuers=("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11", "S12", "S13", "S14", "S16", "S17", "S18",
                             "S19", "S15"))
    ok = loaded(full)
    unavailable = {"status": "UNAVAILABLE", "sha256": None, "registry": None, "reason": "CLAIM_REGISTRY_UNAVAILABLE"}
    book = {"kind": "RPO", "amount": 2.0e9, "currency": "USD", "as_of": "2026-06-30", "yoy": 0.25, "yoy_prior_amount": 1.6e9,
            "yoy_prior_as_of": "2025-06-30", "source_url": "https://data.sec.gov/x.json", "scope_kind": "COMPANY"}
    inputs = {"S1": (periodic(), ok, None), "S2": (None, ok, None), "S3": (None, ok, book), "S4": (periodic(), ok, None),
              "S5": (periodic(), unavailable, None), "S6": (periodic(), ok, None), "S7": (periodic(), ok, None),
              "S8": (periodic(), ok, book), "S9": (periodic(), ok, None), "S10": (periodic(), ok, None), "S11": (None, ok, None),
              "S12": (periodic(), ok, None), "S13": (periodic(), ok, None), "S14": (periodic(), ok, None), "S16": (periodic(), ok, None),
              "S17": (periodic(), ok, None), "S18": (periodic(), ok, None), "S19": (periodic(), ok, None), "S15": (periodic(), ok, None)}
    return {"registry": full, "cutoff": CUTOFF.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "cases": {symbol: {"forecast": of.build_v2(symbol, stock, rec, REPORT_DAY, CUTOFF, load)}
                      for symbol, (rec, load, stock) in inputs.items()}}


class RegistryValidationTests(unittest.TestCase):
    def base(self) -> dict:
        return copy.deepcopy(cases()["registry"])

    def rejected(self, raw: dict) -> str:
        result = loaded(raw)
        self.assertEqual(result["status"], "INVALID", result)
        return result["reason"]

    def test_valid_registry_and_empty_registry(self):
        self.assertEqual(loaded(self.base())["status"], "OK")
        empty = loaded(registry([], []))
        self.assertEqual((empty["status"], empty["reason"]), ("EMPTY", None))
        self.assertEqual(oc.load(Path(tempfile.gettempdir()) / "missing-order-claims.json")["status"], "UNAVAILABLE")
        self.assertEqual(oc.load()["status"], "OK")  # the packaged registry

    def test_duplicate_json_keys_never_last_wins(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "r.json"
            path.write_text('{"schema": "order-claims-v2", "schema": "order-claims-v2", "issuers": {}, "documents": [], "claims": []}', encoding="utf-8")
            self.assertIn("DUPLICATE_KEY", oc.load(path)["reason"])

    def test_structural_rejections_never_raise(self):
        mutations = {
            "wrong schema": lambda r: r.update(schema="order-claims-v1"),
            "extra field": lambda r: r["claims"][0].update(note="x"),
            "dangling document": lambda r: r["claims"][0].update(document_id="NOPE"),
            "list document id": lambda r: r["claims"][0].update(document_id=["S1-8K"]),
            "cross issuer": lambda r: r["claims"][0].update(symbol="S2"),
            "unreviewed prefix": lambda r: r["documents"][2].update(url="https://investors.synthetic.example/other/x.pdf"),
            "SEC kind off SEC": lambda r: r["documents"][0].update(url=f"{PREFIX}x.htm"),
            "8-K without exhibit": lambda r: r["documents"][0]["sec"].pop("exhibit"),
            "exhibit object": lambda r: r["documents"][0]["sec"].update(exhibit={"n": 1}),
            "form of another kind": lambda r: r["documents"][0]["sec"].update(form="10-Q"),
            "invented SEC fields": lambda r: r["documents"][1].update(sec={"accession": "0000000001-26-000009", "form": "8-K"}),
            "userinfo URL": lambda r: r["documents"][2].update(url="https://user@investors.synthetic.example/ir/x.pdf"),
            "fragment URL": lambda r: r["documents"][2].update(url=f"{PREFIX}x.pdf#p7"),
            "http URL": lambda r: r["documents"][2].update(url="http://investors.synthetic.example/ir/x.pdf"),
            "boolean amount": lambda r: r["claims"][0].update(amount=True),
            "NaN amount": lambda r: r["claims"][0].update(amount=float("nan")),
            "overflowing amount": lambda r: r["claims"][0].update(amount=10 ** 400),
            "negative amount": lambda r: r["claims"][0].update(amount=-1),
            "boolean multiplier": lambda r: r["claims"][0].update(unit_multiplier=True),
            "impossible date": lambda r: r["claims"][0].update(as_of="2026-02-30"),
            "rollover instant": lambda r: r["claims"][0]["review"].update(checked_at="2026-09-21T24:00:00Z"),
            "control character": lambda r: r["claims"][0].update(passage="line\u2028break"),
            "long summary": lambda r: r["claims"][3].update(summary="長" * 61),
            "checked before retrieval": lambda r: r["claims"][0]["review"].update(checked_at="2026-09-19T00:00:00Z"),
            "retrieved before publication": lambda r: r["documents"][0].update(retrieved_at="2026-09-01T00:00:00Z"),
            "guidance typed as fact": lambda r: r["claims"][3].update(metric="ORDER_GUIDANCE"),
            "shrinking schedule": lambda r: r["claims"][1].update(shares={"m6": 60.0, "m12": 58.0}),
            "schedule of another date": lambda r: r["claims"][1].update(as_of="2026-07-31"),
            "schedule with amount": lambda r: r["claims"][1].update(amount=3),
            "schedule with its own window": lambda r: r["claims"][1].update(period_start="2027-01-01", period_end="2028-01-01", period_kind="YEAR"),
            "schedule of the filing": lambda r: r["claims"][1].update(stock_claim_id=f"FILING:{FILING}"),
            "intake without period": lambda r: r["claims"].append(claim("S1-INTAKE", "S1", "S1-8K", "ORDER_INTAKE", 1, "2026-08-31",
                                                                         period_start=None)),
            "null reason beside an amount": lambda r: r["claims"][0].update(null_reason="x"),
            "bounds beside an amount": lambda r: r["claims"][3].update(bounds={"lower": 1}),
            "nonsense bounds": lambda r: r["claims"][3].update(amount=None, null_reason="range", bounds={"lower": 3, "upper": 2}),
            "supplement without overlap": lambda r: r["claims"][3]["revision"].pop("overlap"),
            "replacement without reason": lambda r: r["claims"][8]["revision"].pop("reason"),
            "cancellation without reason": lambda r: r["claims"][9]["revision"].pop("reason"),
            "replacement of another series": lambda r: r["claims"][8].update(series_id="S3:OTHER"),
            "cancellation of another series": lambda r: r["claims"][9].update(series_id="S3:OTHER"),
            "filing target from a contract": lambda r: r["claims"][3]["revision"].update(kind="REPLACES", targets=[f"FILING:{FILING}"],
                                                                                         reason="x", overlap=None),
            "target published later": lambda r: r["documents"][6].update(published_date="2026-09-09", retrieved_at="2026-09-20T00:00:00Z"),
            "series units differ": lambda r: r["claims"][2].update(unit_multiplier=1_000_000),
            "duplicate claim id": lambda r: r["claims"].append(copy.deepcopy(r["claims"][0])),
        }
        for label, mutate in mutations.items():
            with self.subTest(label):
                raw = self.base()
                mutate(raw)
                if label == "intake without period":
                    raw["claims"][-1].pop("period_start")
                    raw["claims"][-1].pop("period_end")
                    raw["claims"][-1].pop("period_kind")
                if label == "filing target from a contract":
                    raw["claims"][3]["revision"].pop("overlap")
                self.rejected(raw)

    def test_cycles_and_limits(self):
        raw = self.base()
        raw["claims"][0]["revision"] = {"kind": "REPLACES", "targets": ["S1-RPO-MIRROR"], "reason": "x"}
        raw["claims"][2]["revision"] = {"kind": "REPLACES", "targets": ["S1-RPO"], "reason": "y"}
        self.assertIn("REVISION_CYCLE", self.rejected(raw))
        big = registry([document("D", "S1", "ISSUER_EARNINGS_RELEASE", "2026-09-01")],
                       [claim(f"C{i}", "S1", "D", "ORDER_INTAKE", 1, "2026-08-31", series=f"S{i}") for i in range(oc.MAX_CLAIMS + 1)])
        self.assertIn("REGISTRY_TOO_LARGE", self.rejected(big))
        many = registry([document("D", "S1", "ISSUER_EARNINGS_RELEASE", "2026-09-01")],
                        [claim(f"C{i}", "S1", "D", "ORDER_INTAKE", 1, "2026-08-31", series=f"S{i}") for i in range(oc.MAX_ISSUER_CLAIMS + 1)])
        forecast = build("S1", many, periodic())
        self.assertEqual((forecast["m12"]["reason"], forecast["evidence"]["selection"]["status"], forecast["references"]),
                         ("EVIDENCE_LIMIT", "EVIDENCE_LIMIT", []))


class SelectionTests(unittest.TestCase):
    def test_shared_fixture_matches_the_python_output(self):
        current = json.loads(json.dumps(cases()))
        if os.environ.get("II_WRITE_ORDER_V2_FIXTURE") == "1":
            FIXTURE.write_text(json.dumps(current, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
        self.assertEqual(json.loads(FIXTURE.read_text(encoding="utf-8")), current)

    def test_later_comparable_stock_with_its_own_schedule_replaces_the_filing(self):
        f = cases()["cases"]["S1"]["forecast"]
        self.assertEqual(f["m6"]["source"], "REGISTRY")
        self.assertAlmostEqual(f["m6"]["amount"], 48e9 * 0.32, delta=1)
        self.assertAlmostEqual(f["m12"]["amount"], 48e9 * 0.58, delta=1)
        self.assertEqual((f["m12"]["start"], f["m12"]["end"]), ("2026-08-31", "2027-08-31"))
        # The filing's quarter ends 2026-06-30, 62 days before the new stock: shown, never priced.
        self.assertEqual(f["m12"]["scenario"], {"status": "NO_BASIS", "reason": "NO_MATCHING_REVENUE"})
        self.assertIn(["S1-RPO-MIRROR", "MIRROR"], f["evidence"]["selection"]["excluded"])
        self.assertEqual([r["kind"] for r in f["references"]], ["REGISTRY_RECOGNITION_24M", "SUPERSEDED_SCHEDULE", "CLAIM"])
        self.assertEqual(f["references"][2]["claim_id"], "S1-CONTRACT")

    def test_a_failed_filing_never_prices_a_registry_schedule(self):
        raw = cases()["registry"]
        for claim_row in raw["claims"]:  # the new stock measured at the filing's quarter end would match its quarter
            if claim_row["id"] in ("S1-RPO", "S1-SCHED", "S1-RPO-MIRROR"):
                claim_row["as_of"] = "2026-07-15"
        for status in ("INVALID", "PERIOD_MISMATCH"):
            f = build("S1", raw, periodic(status=status, url=None, accession=None, passage=None, quarter_revenue=1e9))
            self.assertEqual(f["m12"]["scenario"], {"status": "NO_BASIS", "reason": "NO_MATCHING_REVENUE"}, status)
        # A valid filing whose quarter ends within 45 days prices it from that validated quarter.
        f = build("S1", raw, periodic())
        self.assertEqual((f["m12"]["scenario"]["status"], f["m12"]["quarter_revenue"]), ("INSUFFICIENT_COVERAGE", 8e9))

    def test_filing_corrections_conflicts_and_comparability(self):
        c = cases()["cases"]
        s6 = c["S6"]["forecast"]  # an explicit correction of the filing's RPO replaces it (no schedule of its own)
        self.assertEqual((s6["evidence"]["selection"]["filing"], s6["m12"]["reason"]), ("SUPERSEDED", "NO_REALIZATION_SCHEDULE"))
        self.assertEqual(s6["references"][0]["kind"], "SUPERSEDED_SCHEDULE")
        # The same date with any other figure and no correction: a conflict (no tolerance).
        raw = registry([document("D", "S1", "ISSUER_EARNINGS_RELEASE", "2026-08-12")], [claim("C", "S1", "D", "RPO_STOCK", 40.2, "2026-06-30")])
        self.assertEqual(build("S1", raw, periodic())["m12"]["reason"], "CONFLICTING_DISCLOSURES")
        raw["claims"][0]["amount"] = 40  # the same fact: the filing's schedule stands
        f = build("S1", raw, periodic())
        self.assertEqual((f["m12"]["source"], f["m12"]["amount"]), ("PERIODIC", 40e9 * 0.55))
        # Another currency, metric or scope is not comparable with the filing: a reference, the filing stands.
        for metric, change in (("RPO_STOCK", {"currency": "EUR"}), ("BACKLOG_STOCK", {}), ("RPO_STOCK", {"scope": "SEGMENT"})):
            raw = registry([document("D", "S1", "ISSUER_EARNINGS_RELEASE", "2026-09-12")],
                           [claim("C", "S1", "D", metric, 99, "2026-08-31", **change)])
            f = build("S1", raw, periodic())
            self.assertEqual((f["m12"]["source"], f["references"][-1]), ("PERIODIC", {"kind": "CLAIM", "claim_id": "C"}), change)
        # Two comparable series at once are ambiguous; cancelling the filing leaves no schedule.
        raw = registry([document("D", "S1", "ISSUER_EARNINGS_RELEASE", "2026-09-12")],
                       [claim("A", "S1", "D", "RPO_STOCK", 50, "2026-08-31", series="S1:RPO:A"),
                        claim("B", "S1", "D", "RPO_STOCK", 50000, "2026-08-31", series="S1:RPO:B", unit_multiplier=1_000_000)])
        self.assertEqual(build("S1", raw, periodic())["m12"]["reason"], "CONFLICTING_DISCLOSURES")
        raw = registry([document("D", "S1", "ISSUER_EARNINGS_RELEASE", "2026-08-12")],
                       [claim("X", "S1", "D", "RPO_STOCK", 0, "2026-06-30",
                              revision={"kind": "CANCELS", "targets": [f"FILING:{FILING}"], "reason": "withdrawn"})])
        f = build("S1", raw, periodic())
        self.assertEqual((f["evidence"]["selection"]["filing"], f["m12"]["reason"]), ("CANCELLED", "UNQUANTIFIED_STOCK"))

    def test_zero_unquantified_or_range_observations_never_revive_the_filing(self):
        self.assertEqual(cases()["cases"]["S7"]["forecast"]["m12"]["reason"], "UNQUANTIFIED_STOCK")
        for change in ({"amount": None, "null_reason": "not quantified"}, {"amount": None, "null_reason": "range", "bounds": {"lower": 40}}):
            raw = registry([document("D", "S1", "ISSUER_EARNINGS_RELEASE", "2026-09-12")], [claim("C", "S1", "D", "RPO_STOCK", 1, "2026-08-31")])
            raw["claims"][0].update(change)
            f = build("S1", raw, periodic())
            self.assertEqual(f["m12"]["reason"], "UNQUANTIFIED_STOCK", change)
            self.assertFalse(any(h["status"] == "AVAILABLE" for h in (f["m6"], f["m12"])))

    def test_new_stock_never_inherits_an_old_schedule(self):
        raw = cases()["registry"]
        raw["claims"] = [c for c in raw["claims"] if c["id"] != "S1-SCHED"]
        f = build("S1", raw, periodic())
        self.assertEqual((f["m6"]["reason"], f["m12"]["reason"]), ("NO_REALIZATION_SCHEDULE", "NO_REALIZATION_SCHEDULE"))
        self.assertEqual(f["references"][0]["kind"], "SUPERSEDED_SCHEDULE")
        raw = cases()["registry"]
        raw["claims"].append(claim("S1-OLD", "S1", "S1-8K", "RPO_STOCK", 40, "2026-06-30"))
        raw["claims"].append(claim("S1-OLD-SCHED", "S1", "S1-8K", "RECOGNITION_SCHEDULE", None, "2026-06-30", stock_claim_id="S1-OLD",
                                   shares={"m12": 90.0}))
        f = build("S1", raw, periodic())
        self.assertIn(["S1-OLD-SCHED", "STOCK_NOT_CURRENT"], f["evidence"]["selection"]["excluded"])
        self.assertEqual(f["m12"]["share_pct"], 58.0)

    def test_conflicts_cancellations_cutoff_and_unavailable_registry(self):
        c = cases()["cases"]
        self.assertEqual(c["S2"]["forecast"]["m12"]["reason"], "CONFLICTING_DISCLOSURES")
        s3 = c["S3"]["forecast"]
        self.assertEqual(s3["evidence"]["selection"]["current_stock"], "S3-RPO-FIX")
        self.assertIn(["S3-RPO", "SUPERSEDED"], s3["evidence"]["selection"]["excluded"])
        self.assertIn(["S3-DEAL", "CANCELLED"], s3["evidence"]["selection"]["excluded"])
        self.assertEqual(s3["m12"]["reason"], "NO_REALIZATION_SCHEDULE")
        self.assertNotIn("scenario", s3["stock_sensitivity"]["m12"])  # a book extrapolation is never priced
        s4 = c["S4"]["forecast"]
        self.assertIn(["S4-RPO", "AFTER_CUTOFF"], s4["evidence"]["selection"]["excluded"])  # a date-only release on the cutoff day
        self.assertEqual((s4["m12"]["source"], s4["references"]), ("PERIODIC", []))
        s5 = c["S5"]["forecast"]
        self.assertEqual((s5["evidence"]["registry_status"], s5["evidence"]["registry_sha256"], s5["m12"]["source"]),
                         ("UNAVAILABLE", None, "PERIODIC"))
        invalid = of.build_v2("S1", None, periodic(), REPORT_DAY, CUTOFF,
                              {"status": "INVALID", "sha256": SHA, "registry": None, "reason": "INVALID_REGISTRY X"})
        self.assertEqual((invalid["evidence"]["registry_status"], invalid["evidence"]["documents"]), ("INVALID", []))
        empty = loaded(registry([], []))
        self.assertEqual(of.build_v2("S9", None, None, REPORT_DAY, CUTOFF, empty)["m12"]["reason"], "NO_ORDERS")
        self.assertEqual(of.build_v2("S9", {"kind": "NOT_DISCLOSED"}, None, REPORT_DAY, CUTOFF, empty)["m12"]["reason"], "NOT_DISCLOSED")

    def test_a_later_build_does_not_refresh_facts(self):
        raw = cases()["registry"]
        early = build("S1", raw, periodic())
        later = of.build_v2("S1", None, periodic(), REPORT_DAY, CUTOFF.replace(hour=5), loaded(raw))
        self.assertEqual(early["evidence"]["claims"], later["evidence"]["claims"])  # retrieval and review times kept
        self.assertEqual({k: v for k, v in early.items() if k != "evidence"}, {k: v for k, v in later.items() if k != "evidence"})
        self.assertEqual(later["evidence"]["cutoff"], "2026-09-27T05:00:00Z")


class ComparabilityAndTotalityTests(unittest.TestCase):
    """Astra review of revision 2: fixes 4, 6, 7 and 8."""

    def test_basis_and_schedule_comparability(self):
        # A stock on another basis is a reference; the filing stands.
        raw = registry([document("D", "S1", "ISSUER_EARNINGS_RELEASE", "2026-09-12")],
                       [claim("A", "S1", "D", "RPO_STOCK", 48, "2026-07-31", basis="NON_GAAP different cohort"),
                        claim("S", "S1", "D", "RECOGNITION_SCHEDULE", None, "2026-07-31", stock_claim_id="A", basis="NON_GAAP different cohort",
                              shares={"m6": 50.0, "m12": 90.0})])
        f = build("S1", raw, periodic())
        self.assertEqual((f["m12"]["source"], f["m12"]["amount"]), ("PERIODIC", 40e9 * 0.55))
        # A schedule on another basis than its stock is refused when the registry is loaded.
        raw["claims"][1]["basis"] = "another basis"
        self.assertIn("SCHEDULE_STOCK", loaded(raw)["reason"])
        # The same date and figure as the filing with another schedule: a contradiction; with the same schedule: one fact.
        raw = registry([document("D", "S1", "ISSUER_EARNINGS_RELEASE", "2026-08-12")],
                       [claim("A", "S1", "D", "RPO_STOCK", 40, "2026-06-30"),
                        claim("S", "S1", "D", "RECOGNITION_SCHEDULE", None, "2026-06-30", stock_claim_id="A", shares={"m6": 40.0, "m12": 90.0})])
        self.assertEqual(build("S1", raw, periodic())["m12"]["reason"], "CONFLICTING_DISCLOSURES")
        raw["claims"][1]["shares"] = {"m6": 30.0, "m12": 55.0}
        self.assertEqual(build("S1", raw, periodic())["m12"]["source"], "PERIODIC")

    def test_equal_stocks_never_hide_their_schedules_and_ids_never_decide(self):
        def equal_pair(first: str) -> dict:
            return registry([document("D", "S1", "ISSUER_EARNINGS_RELEASE", "2026-09-12"), document("E", "S1", "ISSUER_EARNINGS_RELEASE", "2026-09-13")],
                            [claim(first, "S1", "D", "RPO_STOCK", 40, "2026-06-30"),
                             claim("S", "S1", "D", "RECOGNITION_SCHEDULE", None, "2026-06-30", stock_claim_id=first, shares={"m6": 30.0, "m12": 55.0}),
                             claim("B", "S1", "E", "RPO_STOCK", 40, "2026-06-30"),
                             claim("T", "S1", "E", "RECOGNITION_SCHEDULE", None, "2026-06-30", stock_claim_id="B", shares={"m6": 40.0, "m12": 90.0})])
        for first in ("A", "Z"):  # renaming a claim never changes the result
            f = build("S1", equal_pair(first), periodic())
            self.assertEqual((f["evidence"]["selection"]["status"], f["m12"]["reason"]), ("CONFLICTING_DISCLOSURES", "CONFLICTING_DISCLOSURES"), first)
        # A valid correction resolves it: the later schedule replaces the earlier one and the stock restates the filing.
        raw = equal_pair("A")
        raw["claims"][3]["revision"] = {"kind": "REPLACES", "targets": ["S"], "reason": "schedule restated"}
        raw["claims"][2]["revision"] = {"kind": "REPLACES", "targets": [f"FILING:{FILING}"], "reason": "restated with the new schedule"}
        f = build("S1", raw, periodic())
        self.assertEqual((f["m12"]["source"], f["m12"]["share_pct"], f["evidence"]["selection"]["filing"]), ("REGISTRY", 90.0, "SUPERSEDED"))

    def test_filing_corrections_must_be_comparable_and_optional_fields_validated(self):
        raw = registry([document("D", "S1", "ISSUER_EARNINGS_RELEASE", "2026-08-20")],
                       [claim("X", "S1", "D", "RPO_STOCK", 41, "2026-06-30", basis="NON_GAAP other cohort",
                              revision={"kind": "REPLACES", "targets": [f"FILING:{FILING}"], "reason": "restated"})])
        self.assertIn("BAD_FILING_TARGET", loaded(raw)["reason"])
        for bad in ({"bad": 1}, ["x"], "", "x" * 161):
            raw = copy.deepcopy(cases()["registry"])
            raw["claims"][1]["null_reason"] = bad  # an optional field on a schedule is validated like anywhere else
            self.assertEqual(loaded(raw)["status"], "INVALID", bad)

    def test_the_budget_counts_utf16_units(self):
        docs = [document("D", "S1", "ISSUER_EARNINGS_RELEASE", "2026-09-01")]
        claims = [dict(claim("C", "S1", "D", "SIGNED_CONTRACT_VALUE", 1, "2026-08-31", scope="CONTRACT", revision={"kind": "SUPPLEMENTS",
                  "overlap": "UNKNOWN"}, locator="𠮷" * 10, passage="𠮷" * 1000), checked_at="x")]
        url_units = len(docs[0]["url"])
        self.assertEqual(oc.presentation_size(docs, claims), url_units + 20 + 320 + len("新簽長約"))

    def test_numbers_are_compared_by_value_not_by_spelling(self):
        c = cases()["cases"]
        self.assertEqual((c["S17"]["forecast"]["m12"]["source"], c["S17"]["forecast"]["evidence"]["selection"]["status"]), ("PERIODIC", "OK"))
        self.assertEqual((c["S18"]["forecast"]["m12"]["reason"], c["S18"]["forecast"]["evidence"]["selection"]["status"]), ("UNQUANTIFIED_STOCK", "OK"))
        raw = copy.deepcopy(cases()["registry"])
        for row in raw["claims"]:
            if row["id"] == "S17-T":
                row["shares"] = {"m6": 3e1, "m12": 55.5}  # genuinely different: still a conflict
        self.assertEqual(build("S17", raw, periodic())["m12"]["reason"], "CONFLICTING_DISCLOSURES")
        # Signed zero is one value; a genuinely different bound still conflicts.
        for symbol in ("S19", "S15"):
            f = c[symbol]["forecast"]
            self.assertEqual((f["evidence"]["selection"]["status"], f["m12"]["reason"]), ("OK", "UNQUANTIFIED_STOCK"), symbol)
        raw = copy.deepcopy(cases()["registry"])
        for row in raw["claims"]:
            if row["id"] == "S19-B":
                row["bounds"] = {"lower": 5e-324, "upper": 50}
        self.assertEqual(build("S19", raw, periodic())["m12"]["reason"], "CONFLICTING_DISCLOSURES")

    def test_one_text_policy(self):
        for field, value in (("locator", "x\ud800"), ("locator", "x\udfff"), ("passage", "a\ud800b"), ("summary", "\ud800"),
                             ("locator", "a\u200bb"), ("passage", "a\u202eb"), ("locator", "\u3000"), ("locator", "\ufeff")):
            raw = copy.deepcopy(cases()["registry"])
            raw["claims"][3][field] = value
            result = loaded(raw)
            self.assertEqual(result["status"], "INVALID", (field, value))
            of.build_v2("S1", None, periodic(), REPORT_DAY, CUTOFF, result)  # never raises
        raw = copy.deepcopy(cases()["registry"])
        raw["claims"][1]["null_reason"] = "\ufeff"
        self.assertEqual(loaded(raw)["status"], "INVALID")
        raw = copy.deepcopy(cases()["registry"])
        raw["claims"][3]["locator"] = "第𠮷頁"  # supplementary-plane characters stay supported
        self.assertEqual(loaded(raw)["status"], "OK")

    def test_filing_targets_resolve_only_against_the_actual_filing_after_it(self):
        for label, published, accession in (("before the filing", "2026-07-01", FILING), ("another filing", "2026-08-20", "0000000000-26-000099")):
            raw = registry([document("D", "S1", "ISSUER_EARNINGS_RELEASE", published)],
                           [claim("X", "S1", "D", "RPO_STOCK", 41, "2026-06-30",
                                  revision={"kind": "REPLACES", "targets": [f"FILING:{accession}"], "reason": "restated"})])
            f = build("S1", raw, periodic())
            self.assertEqual((f["evidence"]["selection"]["status"], f["m12"]["reason"]), ("UNRESOLVED_REVISION", "UNRESOLVED_REVISION"), label)
            self.assertIn(["X", "UNRESOLVED_FILING_TARGET"], f["evidence"]["selection"]["excluded"])
        # Without any filing the target cannot be resolved either.
        self.assertEqual(build("S1", raw, None)["m12"]["reason"], "UNRESOLVED_REVISION")

    def test_total_validation_boundaries(self):
        base = cases()["registry"]
        mutations = {
            "far future dates": lambda r: r["documents"][0].update(published_date="9999-12-31", retrieved_at="9999-12-31T12:00:00Z"),
            "ancient date": lambda r: r["claims"][0].update(as_of="1900-01-01"),
            "null summary": lambda r: r["claims"][3].update(summary=None),
            "null bounds": lambda r: r["claims"][0].update(bounds=None),
            "null published_at": lambda r: r["documents"][0].update(published_at=None),
            "dot segment": lambda r: r["documents"][2].update(url=f"{PREFIX}../unreviewed/file.pdf"),
            "encoded dot segment": lambda r: r["documents"][2].update(url=f"{PREFIX}%2e%2e/unreviewed/file.pdf"),
            "encoded slash": lambda r: r["documents"][2].update(url=f"{PREFIX}a%2Fb.pdf"),
            "empty segment": lambda r: r["documents"][2].update(url=f"{PREFIX}a//b.pdf"),
            "bounds overflow with the unit": lambda r: r["claims"][3].update(amount=None, null_reason="range", bounds={"lower": 1e8}),
        }
        for label, mutate in mutations.items():
            with self.subTest(label):
                raw = copy.deepcopy(base)
                mutate(raw)
                self.assertEqual(loaded(raw)["status"], "INVALID", label)

    def test_the_supplementary_plane_case_sits_at_the_budget(self):
        f = cases()["cases"]["S16"]["forecast"]
        size = oc.presentation_size(f["evidence"]["documents"], f["evidence"]["claims"])
        self.assertTrue(oc.PRESENTATION_BUDGET - 2 < size <= oc.PRESENTATION_BUDGET, size)
        self.assertEqual((f["m12"]["status"], len(f["evidence"]["claims"])), ("AVAILABLE", 6))

    def test_the_largest_case_sits_just_within_the_budget(self):
        f = cases()["cases"]["S9"]["forecast"]
        self.assertEqual(oc.presentation_size(f["evidence"]["documents"], f["evidence"]["claims"]), 2398)
        self.assertEqual((f["m12"]["status"], len(f["evidence"]["claims"])), ("AVAILABLE", 6))

    def test_presentation_budget_withholds_instead_of_cutting(self):
        long_url = PREFIX + "z" * (400 - len(PREFIX) - 4) + ".pdf"
        docs = [document(f"D{i}", "S1", "ISSUER_EARNINGS_RELEASE", "2026-09-01", url=long_url.replace("z", str(i), 1)) for i in range(4)]
        claims = [claim(f"C{i}", "S1", f"D{i % 4}", "SIGNED_CONTRACT_VALUE", 1, "2026-08-31", scope="CONTRACT", series=f"S1:C{i}",
                        revision={"kind": "SUPPLEMENTS", "overlap": "UNKNOWN"}, locator="頁" * 160, passage="證" * 1000) for i in range(8)]
        raw = registry(docs, claims)
        self.assertGreater(oc.presentation_size(raw["documents"], [dict(c, checked_at="x") for c in raw["claims"]]), oc.PRESENTATION_BUDGET)
        f = build("S1", raw, periodic())
        self.assertEqual((f["m12"]["reason"], f["evidence"]["claims"]), ("EVIDENCE_LIMIT", []))


class PackagingTests(unittest.TestCase):
    def test_the_packaged_registry_and_helper_are_tracked_valid_and_archive_free(self):
        """The runtime package is the commit's git archive: both files must be tracked; the registry must load as OK or
        EMPTY; neither may point at workspace archives or source captures."""
        import subprocess
        listed = subprocess.run(["git", "-C", str(ROOT), "ls-files", "--error-unmatch", "scripts/order_claims.py",
                                 "config/order-claims-v2.json"], capture_output=True, text=True)
        if listed.returncode != 0 and "not a git repository" in listed.stderr:
            self.skipTest("distribution package without git metadata")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertIn(oc.load()["status"], ("OK", "EMPTY"))
        for path in (oc.REGISTRY_PATH, ROOT / "scripts" / "order_claims.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"(?i)_archive|%TEMP%|ii-live|[A-Z]:\\\\")


if __name__ == "__main__":
    unittest.main()
