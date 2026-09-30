"""ORDERS-V3-AUTOUPDATE-01 B1: one effective-input boundary (Astra contract astra-contract-b1.result.md, tests B1-01..17).

The fixture chain is the accepted A1/B0 one (tests/fixtures/revenue-guidance-autoupdate): real historical NVDA/MU
releases replayed through the actual release checker and updater; every model call here goes through the production
entry points (revenue_guidance_overlay.load_effective_inputs, order_forecast.build_v3, publish_sealed_snapshot)."""
from __future__ import annotations

import copy
import contextlib
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import order_forecast as ofc  # noqa: E402
import publish_sealed_snapshot as publisher  # noqa: E402
import revenue_guidance as rg  # noqa: E402
import revenue_guidance_autoupdate as updater  # noqa: E402
import revenue_guidance_overlay as overlay  # noqa: E402
import revenue_guidance_release_check as checker  # noqa: E402
from tests import test_revenue_guidance_autoupdate as a1  # noqa: E402
from tests.test_order_forecast import recognition  # noqa: E402

STAGES: dict[str, Path] = {}
_TMP = None


def moment(instant: str) -> datetime:
    return datetime.strptime(instant, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def setUpModule():
    """One real chain, saved after each stage (copied per test)."""
    global _TMP
    _TMP = tempfile.TemporaryDirectory()
    base = Path(_TMP.name) / "chain"
    base.mkdir()
    chain = a1.Chain(base)

    def save(name):
        shutil.copytree(base, Path(_TMP.name) / name)
        STAGES[name] = Path(_TMP.name) / name

    chain.cycle("2025-12-17T23:00:00Z")
    chain.check("2025-12-18T12:00:00Z")
    save("DEC_WAIT")                          # MU waits for its 10-Q
    for run, check in (("2025-12-19T12:00:00Z", "2025-12-20T12:00:00Z"), ("2026-02-26T12:00:00Z", "2026-02-27T12:00:00Z")):
        chain.cycle(run)
        chain.check(check)
    save("FEB")                               # NVDA Q1 FY27 outlook usable
    for run, check in (("2026-03-20T12:00:00Z", "2026-03-21T12:00:00Z"), ("2026-05-21T12:00:00Z", "2026-05-22T12:00:00Z")):
        chain.cycle(run)
        chain.check(check)
    save("MAY")                               # NVDA Q2 FY27 usable, MU waiting on an unresolved item
    chain.cycle("2026-06-26T12:00:00Z")
    save("JUN_PRECHECK")                      # MU successor committed, only the predecessor's receipt
    chain.check("2026-06-27T12:00:00Z")
    save("JUN")                               # MU FQ4-26 successor with its own REVIEW_REQUIRED receipt
    chain.cycle("2026-08-27T12:00:00Z")
    chain.check("2026-08-28T12:00:00Z")
    save("AUG")                               # NVDA: unrelated same-day AWS item unresolved


def tearDownModule():
    _TMP.cleanup()


class Base(unittest.TestCase):
    def open(self, stage: str) -> a1.Chain:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        shutil.copytree(STAGES[stage], tmp / "chain")
        return a1.Chain(tmp / "chain")

    @staticmethod
    def v3(snapshot, symbol: str, cutoff: str, **kwargs) -> dict:
        m = moment(cutoff)
        return ofc.build_v3(symbol, None, kwargs.pop("recognition", None), m.date(), m, {}, effective_inputs=snapshot, **kwargs)

    @staticmethod
    def rewrite_current(state: Path, mutate) -> None:
        pointer = json.loads((state / "current.json").read_text(encoding="utf-8"))
        path = state / "generations" / f"{pointer['generation_id']}.json"
        gen = json.loads(path.read_text(encoding="utf-8"))
        mutate(gen)
        data = json.dumps(gen, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8")
        path.write_bytes(data)
        pointer["sha256"] = hashlib.sha256(data).hexdigest()
        (state / "current.json").write_text(json.dumps(pointer), encoding="utf-8")

    @staticmethod
    def producer_of(gen: dict, symbol: str) -> dict:
        loc = gen["issuers"][symbol]["index"]["verified"][-1]
        assert loc["segment"] is None
        return gen["issuers"][symbol]["open"][loc["position"]]

    def write_receipts(self, chain: a1.Chain, mutate) -> None:
        doc = json.loads(chain.receipts.read_text(encoding="utf-8"))
        mutate(doc)
        chain.receipts.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    def assert_unusable(self, snapshot, symbol: str, cutoff: str) -> dict:
        item = snapshot.issuer(symbol)
        self.assertNotEqual(item.disposition, "AUTO_VERIFIED")
        self.assertIsNone(item.usable_record)
        out = self.v3(snapshot, symbol, cutoff)
        self.assertEqual(out["revenue_status"], "UNAVAILABLE")
        self.assertIsNone(out["m6"].get("amount"))
        return out


# ------------------------------------------------------------------------------------------------ B1-01 .. B1-03

class RealChainTests(Base):
    def lazy_body(self, snapshot, cutoff: str, symbols=("MU",)) -> dict:
        """The actual lazy sealer on a 20-entry document at the snapshot cutoff (other entries synthetic)."""
        entry = {"rank": 1, "symbol": "S1", "name": "S One", "layer": "optics", "archetype": "EXPLOSION", "score": 60.9,
                 "role": "CW laser", "role_source": {"url": "https://x.com/a/status/1", "date": "2026-06-01"},
                 "score_parts": {"layer_heat": 5, "capture": 4, "lead": 14, "confirmation": 15, "size": 10, "penalty": 0},
                 "fundamentals": None, "market": {"source": "Yahoo", "source_url": "https://finance.yahoo.com/quote/S1",
                                                  "asof": cutoff[:10], "ret_6m": 0.9, "ret_1y": 0.5, "cagr_2y": 0.6,
                                                  "currency": "USD", "price": 1.0},
                 "market_cap_usd": 1.05e9, "serenity": None, "leopold": None}
        names = list(symbols) + [f"S{i}" for i in range(1, 21 - len(symbols))]
        doc = {"schema": "v213-bottleneck-top20-v3", "generated_at": cutoff,
               "leads": {"serenity": {"url": None, "latest_post_at": None}, "leopold": {"filing": None}},
               "top": [{**entry, "rank": i + 1, "symbol": s} for i, s in enumerate(names)], "industries": []}
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(publisher.revenue_consensus_quarterly, "select_for_cutoff", lambda *a, **k: {}), \
                mock.patch.object(publisher.company_deep_report, "load_order_scenarios", lambda *a, **k: {}), \
                mock.patch.object(publisher.company_deep_report, "load_reports", lambda *a, **k: {}):
            path = Path(tmp) / "v3.json"
            path.write_text(json.dumps(doc), encoding="utf-8")
            body = publisher.lazy_bottleneck_v3_body(path, moment(cutoff), effective_inputs=snapshot)
        self.assertTrue(body)
        return {row["symbol"]: row for row in json.loads(body[publisher.BOTTLENECK_V3_KEY])["top"]}

    def test_b1_01_mu_successor_own_review_required_receipt_builds(self):
        chain = self.open("JUN")
        receipts_before = chain.receipts.read_bytes()
        cutoff = "2026-06-27T13:00:00Z"
        snap = chain.snapshot(cutoff)
        item = snap.issuer("MU")
        self.assertEqual((item.disposition, item.admission_kind, item.discovery_origin), ("AUTO_VERIFIED", "MACHINE_REPLAY", "READMITTED_AUTO"))
        raw = next(r for r in json.loads(receipts_before)["issuers"]["MU"] if r["checked_at"] == "2026-06-27T12:00:00Z")
        self.assertEqual(item.receipt_admission["receipt"], raw)  # the genuine raw object, unchanged
        self.assertEqual(raw["status"], "REVIEW_REQUIRED")
        self.assertEqual(rg.compute_receipt_digest(raw), raw["digest"])
        self.assertTrue(item.receipt_admission["consumed"])
        point, low, high, label, period, trailing = a1.MU_EXPECTED[2][1:]
        fw = rg.build_forward_quarters("MU", rg.validate_issuer_record(item.usable_record, expected_symbol="MU"), moment(cutoff),
                                       effective_inputs=snap)
        self.assertEqual(fw["status"], "AVAILABLE")
        self.assertEqual([(q["start"], q["end"]) for q in fw["forward_quarters"]], a1.MU_FORWARD_FINAL)
        out = self.v3(snap, "MU", cutoff)
        self.assertEqual((out["revenue_status"], out["revenue_basis"]), ("AVAILABLE", "COMPANY_GUIDANCE"))
        self.assertEqual((out["m6"]["amount"], out["m12"]["amount"]), (2 * point, 4 * point))  # m6 $100B, m12 $200B
        self.assertEqual((out["m6"]["start"], out["m6"]["end"], out["m12"]["end"]),
                         (a1.MU_FORWARD_FINAL[0][0], a1.MU_FORWARD_FINAL[1][1], a1.MU_FORWARD_FINAL[3][1]))
        ttm = sum(rev for *_x, rev in trailing)
        self.assertEqual(out["m6"]["ttm_revenue"], sum(rev for *_x, rev in trailing[2:]) + 2 * point)
        self.assertAlmostEqual(out["m12"]["scenario"]["change"], 4 * point / ttm - 1)
        ev = out["evidence"]
        self.assertEqual([(q["fiscal_label"], q["start"], q["end"], q["revenue"]) for q in ev["reported_quarters"]], trailing)
        self.assertEqual((ev["approval_sha256"], ev["approval_approved_at"], ev["approval_decisions"]), (None, None, None))
        self.assertEqual(ev["latest_release_check"], raw)
        self.assertEqual(ev["auto_update"]["disposition"], "AUTO_VERIFIED")
        self.assertEqual(ev["auto_update"]["input_digest"], snap.input_digest)
        self.assertEqual(ev["auto_update"]["receipt"]["receipt_digest"], raw["digest"])
        self.assertTrue(ev["auto_update"]["producer"]["captures"])
        self.assertEqual(ev["reviewed_later_documents"], [])
        # the actual sealer path carries the same result
        wrapped = publisher._with_order_forecast("MU", None, None, None, moment(cutoff), {}, effective_inputs=snap)
        self.assertEqual(wrapped["order_forecast_v3"], out)
        sealed = self.lazy_body(snap, cutoff)["MU"]["outlook"]["order_forecast_v3"]
        self.assertEqual((sealed["m6"]["amount"], sealed["m12"]["amount"]), (2 * point, 4 * point))
        self.assertEqual(sealed["evidence"]["auto_update"]["disposition"], "AUTO_VERIFIED")
        self.assertEqual(chain.receipts.read_bytes(), receipts_before)
        self.assertFalse((chain.base / "effective-registry.json").exists())

    def test_b1_02_nvda_chain_and_unrelated_same_day_item(self):
        for stage, cutoff, index in (("FEB", "2026-02-27T13:00:00Z", 0), ("MAY", "2026-05-22T13:00:00Z", 1)):
            snap = self.open(stage).snapshot(cutoff)
            point = a1.NVDA_EXPECTED[index][1]
            out = self.v3(snap, "NVDA", cutoff)
            self.assertEqual((snap.issuer("NVDA").disposition, out["revenue_status"]), ("AUTO_VERIFIED", "AVAILABLE"), stage)
            self.assertEqual((out["m6"]["amount"], out["m12"]["amount"]), (2 * point, 4 * point), stage)
            self.assertEqual([(q["fiscal_label"], q["start"], q["end"], q["revenue"]) for q in out["evidence"]["reported_quarters"]],
                             a1.NVDA_EXPECTED[index][6], stage)
        chain = self.open("AUG")
        cutoff = "2026-08-28T13:00:00Z"
        snap = chain.snapshot(cutoff)
        item = snap.issuer("NVDA")
        self.assertEqual((item.disposition, item.reason), ("SUSPENDED", "RECEIPT_REVIEW_REQUIRED"))
        self.assertIn(("ISSUER_IR", "2026-08-26"), [(d["channel"], d["date"]) for d in item.receipt_admission["unaccounted"]])
        self.assertEqual(item.discovery_record["claims"][0]["stated_point"], a1.NVDA_EXPECTED[2][1])  # still checked from here
        out = self.assert_unusable(snap, "NVDA", cutoff)
        self.assertEqual(out["revenue_reason"], "STALE")
        self.assertEqual(out["evidence"]["auto_update"]["disposition"], "SUSPENDED")

    def test_b1_03_mu_wait_then_ordinary_verification(self):
        chain = self.open("DEC_WAIT")
        snap = chain.snapshot("2025-12-18T13:00:00Z")
        item = snap.issuer("MU")
        self.assertEqual((item.disposition, item.reason), ("WAITING", "WAITING_PERIODIC_FILING"))
        self.assertEqual(self.assert_unusable(snap, "MU", "2025-12-18T13:00:00Z")["revenue_reason"], "STALE")
        rows = json.loads(chain.receipts.read_text(encoding="utf-8"))["issuers"]["MU"]
        self.assertIn("2025-12-18T12:00:00Z", [r["checked_at"] for r in rows])  # still checked while waiting
        chain.cycle("2025-12-19T12:00:00Z")
        chain.check("2025-12-20T12:00:00Z")
        snap = chain.snapshot("2025-12-20T13:00:00Z")
        record = snap.issuer("MU").usable_record
        self.assertEqual(snap.issuer("MU").disposition, "AUTO_VERIFIED")
        q4 = next(q for q in record["reported_quarters"] if q["fiscal_label"] == "FQ4-25")
        self.assertEqual(q4["revenue"], 11315e6)  # 37,378M - 26,063M
        self.assertEqual(self.v3(snap, "MU", "2025-12-20T13:00:00Z")["m6"]["amount"], 2 * a1.MU_EXPECTED[0][1])


# ------------------------------------------------------------------------------------------------ B1-04 .. B1-07

class ReceiptAndProofTests(Base):
    CUTOFF = "2026-06-27T13:00:00Z"

    def own(self, chain) -> dict:
        return next(r for r in json.loads(chain.receipts.read_text(encoding="utf-8"))["issuers"]["MU"]
                    if r["checked_at"] == "2026-06-27T12:00:00Z")

    def test_b1_04_successor_requires_its_own_receipt(self):
        snap = self.open("JUN_PRECHECK").snapshot("2026-06-26T13:00:00Z")
        self.assertEqual((snap.issuer("MU").disposition, snap.issuer("MU").reason), ("SUSPENDED", "RECEIPT_MISSING"))
        self.assert_unusable(snap, "MU", "2026-06-26T13:00:00Z")
        chain = self.open("JUN")
        own = self.own(chain)
        other = dict(own, checked_at="2026-06-27T12:30:00Z", guidance_document_id="MU-0000723125-26-999999")
        other["digest"] = rg.compute_receipt_digest(other)
        self.write_receipts(chain, lambda d: d["issuers"]["MU"].append(other))
        snap = chain.snapshot(self.CUTOFF)
        self.assertEqual(snap.issuer("MU").receipt_admission["receipt"], own)  # never the newer other-reference receipt
        self.assertEqual(self.v3(snap, "MU", self.CUTOFF)["revenue_status"], "AVAILABLE")
        self.write_receipts(chain, lambda d: d["issuers"].__setitem__("MU", [r for r in d["issuers"]["MU"] if r["checked_at"] != own["checked_at"]]))
        snap = chain.snapshot(self.CUTOFF)
        self.assertEqual(snap.issuer("MU").reason, "RECEIPT_MISSING")  # a wrong-reference receipt only is no proof
        self.assert_unusable(snap, "MU", self.CUTOFF)

    def test_b1_05_strict_auto_receipt_negatives(self):
        def sec(r):
            r["channels"][0]["url"] = r["channels"][0]["url"].replace("0000723125", "0000723126")

        def wire(r):
            r["channels"][1]["url"] = r["channels"][1]["url"].replace("symbol:mu", "symbol:nvda")

        def ir(r):
            r["channels"][2]["url"] = r["channels"][2]["url"].replace("investors.micron.com", "investors.example.com")

        mutations = {
            "issuer": lambda r: r.update(issuer="NVDA"), "anchor": lambda r: r.update(anchor_end="2026-02-26"),
            "published": lambda r: r.update(guidance_published_date="2026-06-25"), "sec_cik": sec, "wire_symbol": wire, "ir_host": ir,
            "coverage": lambda r: r.update(coverage="SEC_AND_WIRE"), "channel_set": lambda r: r["channels"].pop(),
            "incomplete": lambda r: r["channels"][0].update(complete=False),
            "checked_through": lambda r: r["channels"][1].update(checked_through="2026-06-20"),
            "status_ok": lambda r: r.update(status="OK")}
        for name, mutate in mutations.items():
            for recompute in (True, False):
                with self.subTest(mutation=name, recomputed_digest=recompute):
                    chain = self.open("JUN")

                    def change(doc, mutate=mutate, recompute=recompute):
                        r = next(x for x in doc["issuers"]["MU"] if x["checked_at"] == "2026-06-27T12:00:00Z")
                        mutate(r)
                        if recompute:
                            r["digest"] = rg.compute_receipt_digest(r)
                    self.write_receipts(chain, change)
                    snap = chain.snapshot(self.CUTOFF)
                    self.assert_unusable(snap, "MU", self.CUTOFF)
        chain = self.open("JUN")
        self.assert_unusable(chain.snapshot("2026-06-28T12:30:00Z"), "MU", "2026-06-28T12:30:00Z")  # older than 24 h
        self.write_receipts(chain, lambda d: self.own_future(d))
        self.assertEqual(chain.snapshot(self.CUTOFF).issuer("MU").reason, "RECEIPT_MISSING")  # a future check is not seen
        chain.receipts.write_text("{broken", encoding="utf-8")
        snap = chain.snapshot(self.CUTOFF)
        self.assertEqual(snap.issuer("MU").reason, "RECEIPTS_INVALID")
        self.assert_unusable(snap, "MU", self.CUTOFF)
        chain.receipts.unlink()
        self.assertEqual(chain.snapshot(self.CUTOFF).issuer("MU").reason, "RECEIPTS_MISSING")

    @staticmethod
    def own_future(doc):
        for r in doc["issuers"]["MU"]:
            if r["checked_at"] == "2026-06-27T12:00:00Z":
                r["checked_at"] = "2026-06-27T14:00:00Z"
                r["digest"] = rg.compute_receipt_digest(r)

    def test_b1_06_typed_consumption_and_persistent_detections(self):
        chain = self.open("JUN")
        gen = overlay.generation_at(chain.state, self.CUTOFF)
        consumed = next(d for d in self.producer_of(gen, "MU")["decisions"] if d["kind"] == "ROUTING")["operands"]["consumed"]
        target = consumed[0]
        for label, channel, date, usable in (("exact", target["channel"], target["date"], True),
                                             ("wrong channel", "ISSUER_IR" if target["channel"] != "ISSUER_IR" else "SEC_SUBMISSIONS", target["date"], False),
                                             ("wrong date", target["channel"], "2026-06-25", False)):
            with self.subTest(label):
                copy_chain = self.open("JUN")
                doc = {"channel": channel, "id": target["id"], "date": date, "label": "same id", "disposition": "POSSIBLY_RELEVANT"}
                self.rewrite_current(copy_chain.state, lambda g: g["detections"].__setitem__("MU", {"documents": [doc], "overflow": False}))
                snap = copy_chain.snapshot(self.CUTOFF)
                self.assertEqual(snap.issuer("MU").disposition == "AUTO_VERIFIED", usable)
        # an item only in the durable detection set (its receipt row evicted) keeps the issuer suspended; overflow too
        late = {"channel": "ISSUER_IR", "id": "https://investors.micron.com/news/x", "date": "2026-06-27", "label": "later",
                "disposition": "POSSIBLY_RELEVANT"}
        self.rewrite_current(chain.state, lambda g: g["detections"].__setitem__("MU", {"documents": [late], "overflow": False}))
        self.assertEqual(chain.snapshot(self.CUTOFF).issuer("MU").reason, "RECEIPT_REVIEW_REQUIRED")
        self.rewrite_current(chain.state, lambda g: g["detections"].__setitem__("MU", {"documents": [], "overflow": True}))
        self.assertEqual(chain.snapshot(self.CUTOFF).issuer("MU").reason, "DETECTIONS_OVERFLOW")
        self.assert_unusable(chain.snapshot(self.CUTOFF), "MU", self.CUTOFF)

    def test_b1_07_rehashed_proof_never_becomes_model_input(self):
        def claim(p):
            p["record"]["claims"][0]["stated_point"] = 60.0

        def operands(p):
            next(d for d in p["decisions"] if d["kind"] == "CLAIM")["operands"]["point"] = 60.0

        def period(p):
            next(d for d in p["decisions"] if d["kind"] == "ROUTING")["operands"]["report_period"]["quarter"] = 2

        def reference(p):
            next(d for d in p["decisions"] if d["kind"] == "ROUTING")["operands"]["reference"]["document_id"] = "MU-X"

        def event(p):
            p["event"]["accession"] = "0000723125-26-999999"

        def consumed(p):
            next(d for d in p["decisions"] if d["kind"] == "ROUTING")["operands"]["consumed"].append(
                {"channel": "ISSUER_IR", "id": "https://investors.micron.com/news/x", "date": "2026-06-27"})

        def predecessor(p):
            p["predecessor_sha256"] = "0" * 64

        def no_decision(p):
            p["decisions"] = [d for d in p["decisions"] if d["kind"] != "CALENDAR"]

        def no_capture(p):
            p["captures"].pop(sorted(p["captures"])[0])

        for name, mutate in (("claim", claim), ("operands", operands), ("period", period), ("reference", reference), ("event", event),
                             ("consumed", consumed), ("predecessor", predecessor), ("no_decision", no_decision), ("no_capture", no_capture)):
            with self.subTest(name):
                chain = self.open("JUN")

                def change(gen, mutate=mutate):
                    p = self.producer_of(gen, "MU")
                    mutate(p)
                    p["record_sha256"] = overlay.record_sha256(p["record"])
                self.rewrite_current(chain.state, change)
                snap = chain.snapshot(self.CUTOFF)
                self.assert_unusable(snap, "MU", self.CUTOFF)
        chain = self.open("JUN")
        gen = overlay.generation_at(chain.state, self.CUTOFF)
        raw = sorted(self.producer_of(gen, "MU")["captures"].values())[0]
        overlay.capture_path(chain.state, raw).unlink()  # a required capture missing
        self.assert_unusable(chain.snapshot(self.CUTOFF), "MU", self.CUTOFF)
        # a hand-built dictionary or an altered snapshot never passes as loader output
        snap = self.open("JUN").snapshot(self.CUTOFF)
        with self.assertRaises(overlay.EffectiveInputsError):
            self.v3({"issuers": {"MU": {"disposition": "AUTO_VERIFIED"}}}, "MU", self.CUTOFF)
        forged = copy.copy(snap)
        parts = dict(forged._parts)
        issuers = json.loads(parts["issuers"])
        issuers["MU"]["usable_record"]["claims"][0]["stated_point"] = 60.0
        parts["issuers"] = json.dumps(issuers)
        object.__setattr__(forged, "_parts", tuple(parts.items()))
        with self.assertRaises(overlay.EffectiveInputsError):
            self.v3(forged, "MU", self.CUTOFF)
        other = copy.copy(snap)
        object.__setattr__(other, "cutoff", "2026-06-27T14:00:00Z")
        with self.assertRaises(overlay.EffectiveInputsError):
            overlay.require_snapshot(other)
        curated_record = json.loads(a1.FIXTURES.joinpath("bootstrap-registry.json").read_text(encoding="utf-8"))["issuers"][1]
        self.assertEqual(rg.build_forward_quarters("MU", curated_record, moment(self.CUTOFF), effective_inputs=snap)["reason"], "INVALID")


# ------------------------------------------------------------------------------------------------ B1-08 .. B1-11

class StateTests(Base):
    def test_b1_08_future_state_and_capture_cutoffs(self):
        chain = self.open("AUG")
        early = chain.snapshot("2026-06-27T13:00:00Z")
        self.assertLessEqual(overlay.generation_at(chain.state, "2026-06-27T13:00:00Z")["created_at"], "2026-06-27T13:00:00Z")
        self.assertEqual(early.generation_id, overlay.generation_at(chain.state, "2026-06-27T13:00:00Z")["generation_id"])
        self.assertEqual(self.v3(early, "MU", "2026-06-27T13:00:00Z")["m6"]["amount"], 2 * a1.MU_EXPECTED[2][1])
        # replay captures are admitted only with explicit test permission
        strict = overlay.load_effective_inputs(cutoff="2026-06-27T13:00:00Z", state_root=chain.state, registry_path=chain.registry,
                                               approval_path=chain.approval, profiles_path=a1.PROFILES, receipts_path=chain.receipts)
        self.assert_unusable(strict, "MU", "2026-06-27T13:00:00Z")
        # a backdated, rehashed generation carrying later attempts is not admitted
        chain = self.open("JUN")
        self.rewrite_current(chain.state, lambda g: g.update(created_at="2026-06-20T00:00:00Z", parent=None))
        snap = chain.snapshot("2026-06-21T00:00:00Z")
        self.assertEqual((snap.issuer("MU").disposition, snap.issuer("MU").reason), ("BLOCKED", "STATE_CORRUPT"))  # the horizon itself
        self.assert_unusable(snap, "MU", "2026-06-21T00:00:00Z")
        # a broken parent chain blocks when the walk needs it
        chain = self.open("JUN")
        self.rewrite_current(chain.state, lambda g: g.update(parent={"generation_id": g["parent"]["generation_id"], "sha256": "0" * 64}))
        snap = chain.snapshot("2026-06-26T11:00:00Z")
        self.assertEqual((snap.condition, snap.issuer("MU").disposition), ("STATE_FAILURE", "BLOCKED"))

    def test_b1_09_pointer_and_receipt_change_cannot_mix_build_inputs(self):
        chain = self.open("JUN")
        cutoff = "2026-06-27T13:00:00Z"
        snap = chain.snapshot(cutoff)
        first = self.v3(snap, "MU", cutoff)
        # the pointer moves and the receipts change after the snapshot was taken
        chain.cycle("2026-06-27T12:45:00Z")
        self.write_receipts(chain, lambda d: d["issuers"]["MU"].clear())
        again = self.v3(snap, "MU", cutoff)
        self.assertEqual(again, first)
        self.assertEqual(again["evidence"]["auto_update"]["input_digest"], snap.input_digest)
        fresh = chain.snapshot(cutoff)
        self.assertNotEqual(fresh.input_digest, snap.input_digest)
        self.assert_unusable(fresh, "MU", cutoff)
        with self.assertRaises(overlay.EffectiveInputsError):
            self.v3(snap, "MU", "2026-06-27T14:00:00Z")  # the same snapshot for another cutoff
        # a dependency lost before loading completes: the pinned generation's file
        chain = self.open("JUN")
        pointer = json.loads((chain.state / "current.json").read_text(encoding="utf-8"))
        (chain.state / "generations" / f"{pointer['generation_id']}.json").unlink()
        snap = chain.snapshot(cutoff)
        self.assertEqual((snap.condition, snap.issuer("MU").disposition, snap.issuer("MU").reason), ("STATE_FAILURE", "BLOCKED", "STATE_CORRUPT"))

    def test_b1_10_bootstrap_and_missing_initialized_state(self):
        chain = self.open("JUN")
        cutoff = "2026-06-27T13:00:00Z"
        for empty in (chain.base / "absent", chain.base / "empty"):
            if empty.name == "empty":
                empty.mkdir()
            snap = overlay.load_effective_inputs(cutoff=cutoff, state_root=empty, registry_path=chain.registry, approval_path=chain.approval,
                                                 profiles_path=a1.PROFILES, receipts_path=chain.receipts)
            self.assertEqual(snap.condition, "BOOTSTRAP")
            legacy = overlay.curated_snapshot(cutoff, snap.registry, snap.approval, snap.release_checks)
            for sym in ("NVDA", "MU"):
                self.assertEqual((snap.issuer(sym).disposition, snap.issuer(sym).admission_kind), ("CURATED", "HUMAN_PROFILE"))
                self.assertEqual(self.v3(snap, sym, cutoff), self.v3(legacy, sym, cutoff))  # the existing gated curated path

        def blocked(snapshot):
            self.assertEqual(snapshot.condition, "STATE_FAILURE")
            for sym in ("NVDA", "MU"):
                self.assertEqual(snapshot.issuer(sym).disposition, "BLOCKED")
                self.assert_unusable(snapshot, sym, cutoff)

        cases = {
            "pointer deleted": lambda s: (s / "current.json").unlink(),
            "pointer corrupt": lambda s: (s / "current.json").write_text("{", encoding="utf-8"),
            "generation missing": lambda s: [p.unlink() for p in (s / "generations").glob("*.json")],
            "orphan state": lambda s: ((s / "current.json").unlink(), shutil.rmtree(s / "generations")),
            "foreign entry": lambda s: (s / "notes.txt").write_text("x", encoding="utf-8"),
        }
        for name, damage in cases.items():
            with self.subTest(name):
                chain = self.open("JUN")
                damage(chain.state)
                blocked(chain.snapshot(cutoff))
        chain = self.open("JUN")
        shutil.rmtree(chain.state)
        chain.state.write_text("not a directory", encoding="utf-8")
        blocked(chain.snapshot(cutoff))
        chain = self.open("JUN")
        shutil.rmtree(chain.state)
        blocked(chain.snapshot(cutoff, state_required=True))
        chain = self.open("JUN")
        blocked(chain.snapshot(cutoff, expected_generation={"generation_id": "20260101T000000Z-000000000000", "sha256": "0" * 64}))

    def test_b1_11_identity_change_keeps_discovery_without_admission(self):
        chain = self.open("JUN")
        cutoff = "2026-06-27T13:00:00Z"
        successor_ref = chain.snapshot(cutoff).issuer("MU").discovery_reference["document_id"]
        chain.approval.write_text('{"schema": "test-baseline-approval", "revision": 2}\n', encoding="utf-8")  # identity change
        snap = chain.snapshot(cutoff)
        item = snap.issuer("MU")
        self.assertEqual((item.disposition, item.reason, item.discovery_origin), ("BLOCKED", "APPROVAL_BINDING", "READMITTED_AUTO"))
        self.assertEqual(item.discovery_reference["document_id"], successor_ref)
        self.assert_unusable(snap, "MU", cutoff)
        # the checker keeps checking the issuer against the re-derived reference before the updater re-verifies
        chain.check("2026-06-27T12:40:00Z")
        rows = json.loads(chain.receipts.read_text(encoding="utf-8"))["issuers"]["MU"]
        self.assertEqual(rows[-1]["checked_at"], "2026-06-27T12:40:00Z")
        self.assertEqual(rows[-1]["guidance_document_id"], successor_ref)
        # without replay permission the stored producer cannot be re-derived: a conservative baseline rescan
        strict = overlay.load_effective_inputs(cutoff=cutoff, state_root=chain.state, registry_path=chain.registry,
                                               approval_path=chain.approval, profiles_path=a1.PROFILES, receipts_path=chain.receipts)
        baseline_ref = rg.guidance_reference(chain.curated()["MU"])["document_id"]
        self.assertEqual((strict.issuer("MU").discovery_origin, strict.issuer("MU").discovery_reference["document_id"]),
                         ("CURATED_RESCAN", baseline_ref))
        # a material item seen during the change is carried into the durable detections before re-verification
        late = {"channel": "ISSUER_IR", "id": "https://investors.micron.com/news/late", "date": "2026-06-27", "label": "later release",
                "disposition": "POSSIBLY_RELEVANT"}

        def add(doc):
            doc["issuers"]["MU"][-1]["later_documents"].append(late)
            doc["issuers"]["MU"][-1]["digest"] = rg.compute_receipt_digest(doc["issuers"]["MU"][-1])
        self.write_receipts(chain, add)
        summary = chain.update("2026-06-27T12:50:00Z")
        self.assertTrue(summary["reverified"])
        gen = overlay.generation_at(chain.state, "2026-06-27T12:50:00Z")
        self.assertIn(late["id"], [d["id"] for d in gen["detections"]["MU"]["documents"]])
        snap = chain.snapshot(cutoff)
        self.assertNotEqual(snap.issuer("MU").disposition, "AUTO_VERIFIED")
        self.assertIn(late["id"], [d["id"] for d in snap.issuer("MU").detections])

    def test_b1_11b_items_seen_under_a_rescan_reference_survive_reverification(self):
        """A new policy that no longer reproduces the stored producer: the checker rescans from the baseline reference,
        the updater's re-verification then falls back to an earlier producer - an item listed only under the rescan
        reference is kept by the updater's entry phase (it is not visible from either producer's reference)."""
        chain = self.open("JUN")
        cutoff = "2026-06-27T13:00:00Z"
        profiles = json.loads(a1.PROFILES.read_text(encoding="utf-8"))
        mu = next(p for p in profiles["profiles"] if p["symbol"] == "MU")
        mu["release"]["exhibit_name_pattern"] = "^no-such-exhibit\.htm$"
        changed = chain.base / "profiles.json"
        changed.write_text(json.dumps(profiles, indent=2), encoding="utf-8")
        snap = overlay.load_effective_inputs(cutoff=cutoff, state_root=chain.state, registry_path=chain.registry, approval_path=chain.approval,
                                             profiles_path=changed, receipts_path=chain.receipts, allow_replay=True)
        item = snap.issuer("MU")
        baseline_ref = rg.guidance_reference(chain.curated()["MU"])["document_id"]
        self.assertEqual((item.discovery_origin, item.discovery_reference["document_id"]), ("CURATED_RESCAN", baseline_ref))
        late = {"channel": "ISSUER_IR", "id": "https://investors.micron.com/news/rescan", "date": "2026-06-27", "label": "later release",
                "disposition": "POSSIBLY_RELEVANT"}

        def add(doc):
            row = dict(doc["issuers"]["MU"][-1], checked_at="2026-06-27T12:40:00Z", guidance_document_id=baseline_ref,
                       later_documents=[late])
            doc["issuers"]["MU"].append(row)
        self.write_receipts(chain, add)
        summary = updater.run(chain.state, a1.ReplayAsOf("2026-06-27"), a1.at("2026-06-27T12:50:00Z"), changed, chain.registry,
                              chain.approval, chain.receipts)
        self.assertTrue(summary["reverified"])
        gen = overlay.generation_at(chain.state, "2026-06-27T12:50:00Z")
        self.assertIn(late["id"], [d["id"] for d in gen["detections"]["MU"]["documents"]])


# ------------------------------------------------------------------------------------------------ B1-12 .. B1-14, 16

class BridgeTests(Base):
    def test_b1_12_unusable_auto_cannot_rescue_from_curated_or_v2(self):
        def rec_for(at: str) -> dict:
            day = moment(at).date()
            end = str(day - timedelta(days=30))
            return recognition(horizons={"m6": None, "m12": {"share_pct": 39, "derived": False}}, as_of=end, quarter_end=end,
                               filed=str(day - timedelta(days=2)))
        v2_revenue = {"version": 2, "m6": {"status": "AVAILABLE", "basis": "REVENUE", "amount": 1.0e12, "currency": "USD"},
                      "m12": {"status": "AVAILABLE", "basis": "REVENUE", "amount": 2.0e12, "currency": "USD"}, "evidence": None}
        # control: the same MU record is usable without a barrier
        chain = self.open("JUN")
        cutoff = "2026-06-27T13:00:00Z"
        self.assertEqual(self.v3(chain.snapshot(cutoff), "MU", cutoff)["revenue_status"], "AVAILABLE")
        cases = []
        barrier = self.open("JUN")
        late = {"channel": "ISSUER_IR", "id": "https://investors.micron.com/news/y", "date": "2026-06-27", "label": "x", "disposition": "POSSIBLY_RELEVANT"}
        self.rewrite_current(barrier.state, lambda g: g["detections"].__setitem__("MU", {"documents": [late], "overflow": False}))
        cases.append(("SUSPENDED", barrier.snapshot(cutoff), cutoff))
        cases.append(("WAITING", self.open("DEC_WAIT").snapshot("2025-12-18T13:00:00Z"), "2025-12-18T13:00:00Z"))
        corrupt = self.open("JUN")
        self.rewrite_current(corrupt.state, lambda g: g["issuers"]["MU"]["open"][-1].update(outcome="BROKEN"))
        cases.append(("BLOCKED", corrupt.snapshot(cutoff), cutoff))
        for disposition, snap, at in cases:
            with self.subTest(disposition):
                self.assertEqual(snap.issuer("MU").disposition, disposition)
                self.assertIsNotNone(snap.issuer("MU").discovery_record)  # discovery keeps its record ...
                m = moment(at)
                out = ofc.build_v3("MU", None, None, m.date(), m, {}, effective_inputs=snap, v2_forecast=v2_revenue)
                self.assertEqual(out["revenue_status"], "UNAVAILABLE")  # ... but no revenue, not v2 revenue either
                self.assertTrue(all(out[k]["status"] == "UNAVAILABLE" for k in ("m6", "m12")))
                rec = rec_for(at)
                v2 = ofc.build_v2("MU", None, rec, m.date(), m, {})
                self.assertEqual((v2["m12"]["status"], v2["m12"]["basis"]), ("AVAILABLE", "RECOGNITION"))
                out = ofc.build_v3("MU", None, rec, m.date(), m, {}, effective_inputs=snap, v2_forecast=v2)
                self.assertEqual(out["revenue_status"], "UNAVAILABLE")
                self.assertEqual((out["m12"]["basis"], out["m12"]["scenario"]["reason"]), ("RECOGNITION", "NO_REVENUE_BASIS"))
                self.assertEqual(out["m12"]["amount"], v2["m12"]["amount"])
                self.assertEqual(ofc.build_v2("MU", None, rec, m.date(), m, {}), v2)

    def test_b1_13_checker_updater_use_shared_discovery(self):
        chain = self.open("DEC_WAIT")
        corrupt_nvda = lambda g: g["issuers"]["NVDA"]["open"][-1].update(outcome="BROKEN")  # noqa: E731
        if "NVDA" in overlay.generation_at(chain.state, "2025-12-18T13:00:00Z")["issuers"]:
            self.rewrite_current(chain.state, corrupt_nvda)
        snap = chain.snapshot("2025-12-18T14:00:00Z")
        listed = {sym: origin for sym, _record, origin in snap.discovery_records()}
        self.assertEqual(set(listed), {"NVDA", "MU"})  # waiting and (if present) corrupt issuers are still checked
        chain.check("2025-12-18T14:00:00Z")
        rows = json.loads(chain.receipts.read_text(encoding="utf-8"))["issuers"]
        for sym in ("NVDA", "MU"):
            self.assertEqual(rows[sym][-1]["checked_at"], "2025-12-18T14:00:00Z")
            self.assertEqual(rows[sym][-1]["guidance_document_id"], snap.issuer(sym).discovery_reference["document_id"])
        self.assertFalse((chain.base / "effective-registry.json").exists())
        # the model agrees with the same reference
        chain = self.open("JUN")
        snap = chain.snapshot("2026-06-27T13:00:00Z")
        item = snap.issuer("MU")
        self.assertEqual(item.receipt_admission["reference"], item.discovery_reference["document_id"])
        self.assertEqual(item.receipt_admission["reference"], rg.guidance_reference(item.usable_record)["document_id"])

    def test_b1_14_manifest_is_replayable_and_bounded(self):
        chain = self.open("JUN")
        cutoff = "2026-06-27T13:00:00Z"
        enumerated, derived = [], []
        original_derive = overlay.verify.build_successor

        def counting(name, fn):
            def wrapper(*a, **k):
                if "captures" in str(a[0] if a else ""):
                    enumerated.append(name)
                return fn(*a, **k)
            return wrapper
        with mock.patch.object(os, "scandir", counting("scandir", os.scandir)), \
                mock.patch.object(os, "listdir", counting("listdir", os.listdir)), \
                mock.patch.object(Path, "iterdir", counting("iterdir", Path.iterdir)), \
                mock.patch.object(overlay.verify, "build_successor", lambda *a, **k: derived.append(a[0]["symbol"]) or original_derive(*a, **k)):
            first = chain.snapshot(cutoff)
        self.assertEqual(enumerated, [])
        self.assertLessEqual(len(derived), 2)  # one producer re-derivation per automatic issuer
        self.assertEqual(chain.snapshot(cutoff).input_digest, first.input_digest)
        pin = {"generation_id": first.generation_id, "sha256": first.generation_sha256}
        self.assertEqual(chain.snapshot(cutoff, expected_generation=pin).input_digest, chain.snapshot(cutoff, expected_generation=pin).input_digest)
        self.assertEqual(chain.snapshot(cutoff, expected_generation=pin).issuer("MU").usable_record, first.issuer("MU").usable_record)
        moved = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, moved, True)
        shutil.copytree(chain.state, moved / "elsewhere")
        (moved / "elsewhere" / "queue.json").write_text('{"last_served": "NVDA"}', encoding="utf-8")
        relocated = overlay.load_effective_inputs(cutoff=cutoff, state_root=moved / "elsewhere", registry_path=chain.registry,
                                                  approval_path=chain.approval, profiles_path=a1.PROFILES, receipts_path=chain.receipts,
                                                  allow_replay=True)
        self.assertEqual(relocated.input_digest, first.input_digest)  # paths and the queue cursor are not inputs
        for label, change in (("receipts", lambda: self.write_receipts(chain, lambda d: d["issuers"]["NVDA"].pop())),
                              ("approval", lambda: chain.approval.write_text('{"schema": "other"}', encoding="utf-8")),
                              ("cutoff", lambda: None)):
            with self.subTest(label):
                before = chain.snapshot(cutoff).input_digest
                change()
                after = chain.snapshot("2026-06-27T13:00:01Z" if label == "cutoff" else cutoff).input_digest
                self.assertNotEqual(after, before)

    def test_b1_16_auto_state_changes_only_nvda_mu(self):
        """Same inputs with and without automatic state: only the NVDA and MU entries differ."""
        chain = self.open("JUN")
        real = json.loads((ROOT / "config" / "revenue-guidance-v1.json").read_text(encoding="utf-8"))
        boot = {r["symbol"]: r for r in json.loads(chain.registry.read_text(encoding="utf-8"))["issuers"]}
        real["issuers"] = [boot.get(r["symbol"], r) for r in real["issuers"]]
        chain.registry.write_text(json.dumps(real, ensure_ascii=False, indent=2), encoding="utf-8")
        self.assertTrue(chain.update("2026-06-27T12:30:00Z")["reverified"])  # the changed baseline re-verifies the state
        cutoff = "2026-06-27T13:00:00Z"
        symbols = [r["symbol"] for r in real["issuers"]][:20]
        with_state = chain.snapshot(cutoff)
        empty = chain.base / "no-state"
        without = overlay.load_effective_inputs(cutoff=cutoff, state_root=empty, registry_path=chain.registry, approval_path=chain.approval,
                                                profiles_path=a1.PROFILES, receipts_path=chain.receipts)
        self.assertEqual(with_state.issuer("MU").disposition, "AUTO_VERIFIED")
        a = RealChainTests.lazy_body(self, with_state, cutoff, symbols)
        b = RealChainTests.lazy_body(self, without, cutoff, symbols)
        changed = sorted(sym for sym in a if json.dumps(a[sym], sort_keys=True) != json.dumps(b[sym], sort_keys=True))
        self.assertEqual(changed, ["MU", "NVDA"])
        self.assertEqual(a["MU"]["outlook"]["order_forecast_v3"]["m6"]["amount"], 2 * a1.MU_EXPECTED[2][1])
        # an extra enabled profile cannot make another issuer automatic
        profiles = json.loads(a1.PROFILES.read_text(encoding="utf-8"))
        extra = copy.deepcopy(profiles["profiles"][0])
        extra.update(symbol="LITE", profile_id="lite-test")
        profiles["profiles"].append(extra)
        try:
            other = overlay.load_effective_inputs(cutoff=cutoff, state_root=chain.state, registry_path=chain.registry,
                                                  approval_path=chain.approval, profiles_bytes=json.dumps(profiles).encode("utf-8"),
                                                  receipts_path=chain.receipts, allow_replay=True)
        except overlay.EffectiveInputsError:
            other = None
        if other is not None:
            self.assertEqual(other.issuer("LITE").disposition, "CURATED")
            self.assertEqual(other.issuer("LITE").admission_kind, "HUMAN_PROFILE")


class PreReviewFollowUpTests(Base):
    """Gemini pre-review (gemini-b1-prereview.result.md) findings 1, 3 and 4."""

    def test_checker_refuses_a_snapshot_for_another_instant(self):
        chain = self.open("JUN")
        snap = chain.snapshot("2026-06-27T13:00:00Z")
        with self.assertRaises(overlay.EffectiveInputsError):
            checker.run(chain.registry, chain.receipts, moment("2026-06-27T14:00:00Z"), a1.sec_fetch_as_of("2026-06-27"),
                        a1.wire_fetch_as_of("2026-06-27"), a1.ir_fetch_as_of("2026-06-27"), effective_inputs=snap)

    def test_an_automatic_issuer_missing_from_the_registry_is_an_explicit_outcome(self):
        chain = self.open("JUN")
        registry = json.loads(chain.registry.read_text(encoding="utf-8"))
        registry["issuers"] = [r for r in registry["issuers"] if r["symbol"] != "MU"]
        snap = overlay.load_effective_inputs(cutoff="2026-06-27T13:00:00Z", state_root=chain.state,
                                             registry_bytes=json.dumps(registry).encode("utf-8"), approval_path=chain.approval,
                                             profiles_path=a1.PROFILES, receipts_path=chain.receipts, allow_replay=True)
        listed = {sym: record for sym, record, _origin in snap.discovery_records()}
        self.assertIn("MU", listed)
        self.assertIsNone(listed["MU"])  # not checkable, not silently dropped
        self.assertNotEqual(snap.issuer("MU").disposition, "AUTO_VERIFIED")
        result = checker.run(chain.registry, chain.receipts, moment("2026-06-27T13:00:00Z"), a1.sec_fetch_as_of("2026-06-27"),
                             a1.wire_fetch_as_of("2026-06-27"), a1.ir_fetch_as_of("2026-06-27"), effective_inputs=snap)
        self.assertIn("MU", result["failed"])

    def test_a_machine_record_inherits_no_human_review_list(self):
        chain = self.open("AUG")
        snap = chain.snapshot("2026-08-28T13:00:00Z")
        item = snap.issuer("NVDA")
        aws = next(d for d in item.receipt_admission["unaccounted"] if d["channel"] == "ISSUER_IR")
        record = dict(item.discovery_record, reviewed_later_documents=[
            {"id": aws["id"], "disposition": "REVIEWED_IRRELEVANT", "reviewed_at": "2026-08-28T00:00:00Z"}])
        rows = overlay.receipt_rows(json.loads(chain.receipts.read_text(encoding="utf-8")), "NVDA",
                                    item.discovery_reference["document_id"], snap.cutoff)
        self.assertIn(aws["id"], [d["id"] for d in overlay.unaccounted(record, rows, item.producer, [])])
        self.assertNotIn(aws["id"], [d["id"] for d in overlay.unaccounted(record, rows, None, [])])  # curated semantics unchanged


class CallerBoundaryTests(Base):
    """Astra B1 review r1 (astra-accept-b1.result.md): R1 corrupt retained history, R2 damaged state, R3 checker CLI."""
    CUTOFF = "2026-06-27T13:00:00Z"

    def test_r1_checker_never_replaces_a_corrupt_history(self):
        damages = {"not json": b"{broken", "wrong schema": json.dumps({"schema": "other", "issuers": {}}).encode(),
                   "rows not a list": json.dumps({"schema": checker.SCHEMA, "issuers": {"MU": {"x": 1}}}).encode(),
                   "row without time": json.dumps({"schema": checker.SCHEMA, "issuers": {"MU": [{"status": "OK"}]}}).encode()}
        for name, data in damages.items():
            with self.subTest(name):
                chain = self.open("JUN")
                chain.receipts.write_bytes(data)
                with self.assertRaises(ValueError):
                    chain.check("2026-06-27T12:40:00Z")
                self.assertEqual(chain.receipts.read_bytes(), data)  # left exactly as it was
                snap = chain.snapshot(self.CUTOFF)
                self.assertTrue(snap.issuer("MU").reason.startswith("RECEIPTS_"))
                self.assert_unusable(snap, "MU", self.CUTOFF)
        # a history that changed after the snapshot read it is not overwritten either
        chain = self.open("JUN")
        snap = chain.snapshot("2026-06-27T12:40:00Z")
        before = chain.receipts.read_bytes() + b" "
        chain.receipts.write_bytes(before)
        with self.assertRaises(ValueError):
            checker.run(chain.registry, chain.receipts, moment("2026-06-27T12:40:00Z"), a1.sec_fetch_as_of("2026-06-27"),
                        a1.wire_fetch_as_of("2026-06-27"), a1.ir_fetch_as_of("2026-06-27"), effective_inputs=snap)
        self.assertEqual(chain.receipts.read_bytes(), before)
        # CLI: a corrupt history is a failed run with the file unchanged
        chain.receipts.write_bytes(b"{broken")
        with mock.patch("sec_contact_headers.sec_identity_headers", lambda: {"User-Agent": "test"}),                 contextlib.redirect_stdout(io.StringIO()) as out:
            code = checker.main(["--registry", str(chain.registry), "--output", str(chain.receipts), "--state-root", str(chain.state)])
        self.assertEqual((code, json.loads(out.getvalue())["status"]), (1, "FAILED"))
        self.assertEqual(chain.receipts.read_bytes(), b"{broken")

    def tree(self, root: Path) -> dict:
        return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*"))
                if p.is_file() and p.name != "lock"}

    def test_r2_updater_never_reinitializes_damaged_state(self):
        def orphan(state):
            (state / "current.json").unlink()
            shutil.rmtree(state / "generations")

        def foreign(state):
            (state / "notes.txt").write_text("x", encoding="utf-8")
        for name, damage in (("orphaned artifacts", orphan), ("foreign entry", foreign)):
            with self.subTest(name):
                chain = self.open("JUN")
                damage(chain.state)
                before = self.tree(chain.state)
                self.assertEqual(chain.snapshot(self.CUTOFF).condition, "STATE_FAILURE")
                with self.assertRaises(updater.SystemicFailure):
                    chain.update(self.CUTOFF)
                self.assertEqual(self.tree(chain.state), before)  # no capture, queue, generation or pointer change
                self.assertEqual(chain.snapshot(self.CUTOFF).condition, "STATE_FAILURE")
                argv = ["--state-root", str(chain.state), "--replay", str(a1.FIXTURES), "--as-of", self.CUTOFF, "--profiles", str(a1.PROFILES),
                        "--registry", str(chain.registry), "--approval", str(chain.approval), "--receipts", str(chain.receipts)]
                with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()):
                    if name == "foreign entry":
                        with self.assertRaises(SystemExit):  # the CLI refuses an unrelated root before any work
                            updater.main(argv)
                    else:
                        self.assertEqual(updater.main(argv), 2)
                        self.assertIn("SYSTEMIC_FAILURE", out.getvalue())
                self.assertEqual(self.tree(chain.state), before)

    def test_r3_checker_cli_forwards_the_state_root(self):
        chain = self.open("JUN")
        seen = {}

        def fake_run(*args, **kwargs):
            seen.update(kwargs)
            return {"status": "OK", "issuers": 0, "receipts": {}, "failed": []}
        with mock.patch.object(checker, "run", fake_run), mock.patch("sec_contact_headers.sec_identity_headers", lambda: {"User-Agent": "t"}),                 contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(checker.main(["--registry", str(chain.registry), "--output", str(chain.receipts),
                                           "--state-root", str(chain.state)]), 0)
        self.assertEqual(seen.get("state_root"), chain.state)
        # the explicit root selects its own discovery reference and never touches the default root
        loads = []
        real = overlay.load_effective_inputs

        def recording(**kwargs):
            loads.append(kwargs["state_root"])
            return real(**{**kwargs, "approval_path": chain.approval, "profiles_path": a1.PROFILES, "allow_replay": True})
        with mock.patch.object(overlay, "load_effective_inputs", recording):
            checker.run(chain.registry, chain.receipts, moment("2026-06-27T12:40:00Z"), a1.sec_fetch_as_of("2026-06-27"),
                        a1.wire_fetch_as_of("2026-06-27"), a1.ir_fetch_as_of("2026-06-27"), state_root=chain.state)
        self.assertEqual(loads, [chain.state])
        row = json.loads(chain.receipts.read_text(encoding="utf-8"))["issuers"]["MU"][-1]
        self.assertEqual((row["checked_at"], row["guidance_document_id"]),
                         ("2026-06-27T12:40:00Z", chain.snapshot(self.CUTOFF).issuer("MU").discovery_reference["document_id"]))
        self.assertFalse(overlay.DEFAULT_STATE_ROOT.exists())


class CuratedContractTests(unittest.TestCase):
    def test_b1_15_bootstrap_equals_the_legacy_curated_build(self):
        """Tracked counterpart of the frozen-production golden (archive b1-golden): with an empty state root the loader's
        build equals the legacy curated interface over the same bytes, for every registry issuer."""
        cutoff = "2026-09-29T22:15:03Z"
        with tempfile.TemporaryDirectory() as tmp:
            snap = overlay.load_effective_inputs(cutoff=cutoff, state_root=Path(tmp) / "none", receipts_bytes=b'{"schema": "revenue-guidance-release-checks-v1", "issuers": {}}')
            legacy = overlay.curated_snapshot(cutoff, snap.registry, snap.approval, snap.release_checks)
            for sym in snap.symbols():
                m = moment(cutoff)
                self.assertEqual(ofc.build_v3(sym, None, None, m.date(), m, {}, effective_inputs=snap),
                                 ofc.build_v3(sym, None, None, m.date(), m, {}, revenue_registry=snap.registry,
                                              revenue_approval=snap.approval, release_checks_cache=snap.release_checks), sym)
                self.assertEqual(ofc.build_v3(sym, None, None, m.date(), m, {}, effective_inputs=legacy),
                                 ofc.build_v3(sym, None, None, m.date(), m, {}, effective_inputs=snap), sym)

    def test_b1_17_golden_and_probe_fixtures_are_current(self):
        for script in ("make_orders_v3_golden.py", "make_orders_v3_probes.py"):
            with self.subTest(script):
                result = __import__("subprocess").run([sys.executable, str(ROOT / "tests" / "fixtures" / script), "--check"],
                                                      capture_output=True, text=True, cwd=ROOT, env={**os.environ, "PYTHONUTF8": "1"})
                self.assertEqual(result.returncode, 0, result.stdout[-500:] + result.stderr[-500:])


if __name__ == "__main__":
    unittest.main()
