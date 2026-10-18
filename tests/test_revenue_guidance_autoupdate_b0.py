"""ORDERS-V3-AUTOUPDATE-01 B0: shared reference, adapters, decision contract, fair queue, reuse, history segments.

Moved verbatim from tests/test_revenue_guidance_autoupdate.py so that each module stays well inside the per-module
gate limit (that module took 776 s of 895 s in the complete gate R/final-a43bef58-g2). The replay helpers stay there
(VerifierTests uses them too) and are imported by name below; none of them is a TestCase, so nothing runs twice.
This module launches no child process."""
from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import revenue_guidance  # noqa: E402
import revenue_guidance_auto_verify as verify  # noqa: E402
import revenue_guidance_autoupdate as updater  # noqa: E402
import revenue_guidance_overlay as overlay  # noqa: E402
import revenue_guidance_release_check as checker  # noqa: E402
from tests import nbis_synthetic_sources as f  # noqa: E402
from tests.test_revenue_guidance_autoupdate import (  # noqa: E402
    Chain,
    CountingReplay,
    DECIDED,
    FILED,
    FIXTURES,
    PRED,
    PROFILES,
    PROFILES_BY_SYMBOL,
    SharedBudget,
    at,
    event_for,
    exhibit_row,
    row_of,
)


class B0Tests(unittest.TestCase):
    """ORDERS-V3-AUTOUPDATE-01 B0: shared reference, adapters, decision contract, fair queue, reuse, history segments."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.chain = Chain(Path(self.tmp.name))

    def run_with(self, transport, instant):
        return updater.run(self.chain.state, transport, at(instant), PROFILES, self.chain.registry, self.chain.approval, self.chain.receipts)

    def boundary_row(self, label, fn, expected):
        actual = f.outcome_of(fn)
        f.observe_boundary(label, actual)
        with self.subTest(row=label):
            self.assertEqual(actual, expected)

    def marked_replay(self, slot, marker):
        target = (exhibit_row("NVDA", "2026-02-25") if slot == "exhibit" else
                  row_of("NVDA", "IR_RELEASE_PAGE", filed="2026-02-25"))["url"]
        class MarkedReplay(CountingReplay):
            def get(inner, url, profile, symbol):
                raw, kind = super().get(url, profile, symbol)
                return (raw + marker if symbol == "NVDA" and url == target else raw), kind
        return MarkedReplay("2026-02-26")

    def marked_settlement(self, slot, marker):
        from html.parser import HTMLParser
        self.assertEqual(sys.version_info[:3], (3, 12, 10))
        with self.assertRaises(AssertionError):
            HTMLParser().feed(marker.decode("ascii"))
        instant, later = "2026-02-26T12:00:00Z", "2026-02-26T13:00:00Z"
        acc = "0001045810-26-000019"
        self.chain.check(instant)
        transport = self.marked_replay(slot, marker)
        def invoke():
            summary = self.run_with(transport, instant)
            generation = overlay.generation_at(self.chain.state, instant)
            entry = generation["issuers"]["NVDA"]
            attempt = overlay.last_attempt(self.chain.state, entry)
            resolved = self.chain.resolve(instant)["NVDA"]
            clean = CountingReplay("2026-02-26")
            second = self.run_with(clean, later)
            return {"status": summary["status"], "generation_id_present": "generation_id" in summary,
                    "nvda": summary["issuers"].get("NVDA"), "mu_outcome": summary["issuers"].get("MU", {}).get("outcome"),
                    "detail": attempt["detail"], "exhibit_captured": "exhibit" in attempt["captures"],
                    "settled": acc in {r["key"] for r in entry["index"]["settled"]},
                    "resolved": (resolved["mode"], resolved["reason"]), "next_nvda": second["issuers"].get("NVDA"),
                    "next_nvda_archive_requests": [u for u in clean.calls if u.startswith("https://www.sec.gov/Archives/") and "/1045810/" in u]}
        self.boundary_row("b0.marked." + slot, invoke, ("RESULT", {
            "status": "OK", "generation_id_present": True,
            "nvda": {"action": "ATTEMPTED", "event": acc, "outcome": "BLOCKED", "reason": "UNSUPPORTED_TEMPLATE"},
            "mu_outcome": "VERIFIED", "detail": f.HTML_UNREADABLE, "exhibit_captured": True, "settled": True,
            "resolved": ("BLOCKED", "UNSUPPORTED_TEMPLATE"), "next_nvda": {"action": "SETTLED", "outcome": "BLOCKED"},
            "next_nvda_archive_requests": []}))

    def test_boundary_exhibit_settles_and_mu_continues(self):
        self.marked_settlement("exhibit", b"<![bogus[")

    def test_boundary_ir_settles_and_mu_continues(self):
        self.marked_settlement("ir", b"<![ endif]>")

    def test_boundary_main_returns_zero(self):
        from html.parser import HTMLParser
        marker = b"<![bogus["
        with self.assertRaises(AssertionError):
            HTMLParser().feed(marker.decode("ascii"))
        instant = "2026-02-26T12:00:00Z"
        self.chain.check(instant)
        transport = self.marked_replay("exhibit", marker)
        def invoke():
            out = io.StringIO()
            with mock.patch.object(updater, "ReplayTransport", lambda directory: transport), contextlib.redirect_stdout(out):
                code = updater.main(["--state-root", str(self.chain.state), "--replay", str(FIXTURES),
                                     "--as-of", instant, "--registry", str(self.chain.registry),
                                     "--approval", str(self.chain.approval), "--receipts", str(self.chain.receipts),
                                     "--profiles", str(PROFILES)])
            summary = json.loads(out.getvalue())
            return {"exit": code, "status": summary["status"], "error": summary.get("error"),
                    "nvda": summary.get("issuers", {}).get("NVDA")}
        self.boundary_row("b0.main", invoke, ("RESULT", {"exit": 0, "status": "OK", "error": None,
            "nvda": {"action": "ATTEMPTED", "event": "0001045810-26-000019", "outcome": "BLOCKED", "reason": "UNSUPPORTED_TEMPLATE"}}))

    def test_boundary_transport_assertion_propagates(self):
        instant = "2026-02-26T12:00:00Z"
        self.chain.check(instant)
        class DefectReplay(CountingReplay):
            def get(inner, url, profile, symbol):
                if symbol == "NVDA":
                    raise AssertionError("synthetic transport defect")
                return super().get(url, profile, symbol)
        self.boundary_row("b0.transport", lambda: self.run_with(DefectReplay("2026-02-26"), instant),
                          ("RAISED", "AssertionError", "synthetic transport defect"))

    def test_boundary_json_planner_and_run(self):
        nested = b"[" * 5000 + b"0" + b"]" * 5000
        cases = [("submissions", nested, "nested", "submissions feed shape"),
                 ("index", nested, "nested", "accession index shape"),
                 ("submissions", b'{"cik":1e400}', "overflow", "submissions feed shape")]
        instant = "2026-02-26T12:00:00Z"
        acc = "0001045810-26-000019"
        for key, raw, name, detail in cases:
            with self.subTest(key=key, row=name), tempfile.TemporaryDirectory() as tmp:
                chain = Chain(Path(tmp))
                target = ("https://data.sec.gov/submissions/CIK0001045810.json" if key == "submissions" else
                          "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000019/index.json")
                class ShapeReplay(CountingReplay):
                    def get(inner, url, profile, symbol):
                        body, kind = super().get(url, profile, symbol)
                        return (raw if symbol == "NVDA" and url == target else body), kind
                lead = {"accession": acc, "filed": "2026-02-25", "ir_item": None, "wire_item": None, "later_documents": []}
                self.boundary_row("b0.json.planner." + key + "." + name,
                    lambda: updater.plan_event(ShapeReplay("2026-02-26"), chain.state, PROFILES_BY_SYMBOL["NVDA"],
                                                lead, instant[:10], at(instant), {"bytes": 0, "store": 0}),
                    ("BLOCKED", "BLOCKED", "EVENT_UNRESOLVED", detail))
                # A separate owned chain keeps the direct planner's objects out of run accounting.
                with tempfile.TemporaryDirectory() as run_tmp:
                    run_chain = Chain(Path(run_tmp))
                    run_chain.check(instant)
                    def invoke():
                        summary = updater.run(run_chain.state, ShapeReplay("2026-02-26"), at(instant), PROFILES,
                                              run_chain.registry, run_chain.approval, run_chain.receipts)
                        entry = overlay.generation_at(run_chain.state, instant)["issuers"]["NVDA"]
                        attempt = overlay.last_attempt(run_chain.state, entry)
                        return {"status": summary["status"], "nvda": summary["issuers"].get("NVDA"),
                                "mu_outcome": summary["issuers"].get("MU", {}).get("outcome"), "detail": attempt["detail"]}
                    self.boundary_row("b0.json.run." + key + "." + name, invoke, ("RESULT", {
                        "status": "OK", "nvda": {"action": "ATTEMPTED", "event": acc, "outcome": "BLOCKED", "reason": "EVENT_UNRESOLVED"},
                        "mu_outcome": "VERIFIED", "detail": detail}))

    # shared reference
    def test_reference_is_shared_by_the_whole_active_claim_set(self):
        registry = json.loads((ROOT / "config" / "revenue-guidance-v1.json").read_text(encoding="utf-8"))
        for record in registry["issuers"]:
            active = revenue_guidance.select_active_guidance_claims(record)
            ref = revenue_guidance.guidance_reference(record)
            self.assertFalse(ref["conflict"], record["symbol"])
            if active:  # unchanged for every curated record: the one reference all its claims share
                docs = {d["id"]: d for d in record["documents"]}
                self.assertEqual(ref["document_id"], revenue_guidance.guidance_reference_document_id(active[0], docs), record["symbol"])
        crwv = next(r for r in registry["issuers"] if r["symbol"] == "CRWV")
        shuffled = dict(crwv, claims=list(reversed(crwv["claims"])))
        self.assertEqual(revenue_guidance.guidance_reference(shuffled), revenue_guidance.guidance_reference(crwv))  # order-independent
        split = copy.deepcopy(crwv)
        other = dict(split["documents"][0], id="CRWV-OTHER", lineage_id="CRWV-OTHER", published_date="2026-08-12")
        split["documents"].append(other)
        next(c for c in split["claims"] if c["period_kind"] == "QUARTER")["document_id"] = "CRWV-OTHER"
        ref = revenue_guidance.guidance_reference(split)
        self.assertEqual((ref["conflict"], ref["document_id"]), (True, None))  # never the first or the newest
        self.assertIsNone(checker.receipt_for(split, datetime(2026, 9, 1, tzinfo=timezone.utc), lambda u: {}, lambda u: {}, lambda u: b""))

    def test_routing_binds_adapter_report_period_and_reference(self):
        self.chain.cycle("2026-02-26T12:00:00Z")
        state = self.chain.resolve("2026-02-26T12:00:00Z")["NVDA"]
        routing = next(d for d in state["attempt"]["decisions"] if d["kind"] == "ROUTING")["operands"]
        self.assertEqual(routing["adapter"], "SEC_8K_202_INLINE_XBRL_V1")
        self.assertEqual(routing["report_period"], {"quarter": 4, "fiscal_year": 2026, "start": "2025-10-27", "end": "2026-01-25"})
        self.assertEqual(routing["reference"]["document_id"], state["record"]["claims"][0]["document_id"])
        self.assertEqual([c["id"] for c in routing["reference"]["claims"]], ["NVDA-Q-GUIDANCE"])

    def test_unknown_adapter_is_refused(self):
        data = json.loads(PROFILES.read_text(encoding="utf-8"))
        data["profiles"][0]["adapter"] = "SEC_6K_TABLE_V1"  # a later slice's mode is not implemented here
        with self.assertRaises(ValueError):
            verify.validate_profiles(data)
        profile = dict(PROFILES_BY_SYMBOL["NVDA"], adapter="SEC_6K_TABLE_V1")
        event, caps = event_for("NVDA", FILED["NVDA"])
        self.assertEqual(verify.build_successor(profile, PRED["NVDA"], event, caps, DECIDED)["reason"], "UNSUPPORTED_TEMPLATE")

    def test_decision_contract_is_strict(self):
        self.chain.cycle("2026-02-26T12:00:00Z")
        gen = overlay.generation_at(self.chain.state, "2026-02-26T12:00:00Z")
        attempt = next(a for a in gen["issuers"]["NVDA"]["open"] if a["outcome"] == "VERIFIED")
        overlay.validate_attempt(attempt)
        for mutate in (lambda a: a["decisions"][0]["operands"].update(extra=1),
                       lambda a: next(d for d in a["decisions"] if d["kind"] == "ROUTING")["operands"]["consumed"].append({"channel": "ISSUER_IR", "id": "x"}),
                       lambda a: a["decisions"].remove(next(d for d in a["decisions"] if d["kind"] == "CALENDAR"))):
            bad = copy.deepcopy(attempt)
            mutate(bad)
            with self.assertRaises(overlay.StateError):
                overlay.validate_attempt(bad)

    # fair queue and reuse
    def test_a_permanently_crashing_issuer_does_not_starve_another(self):
        self.chain.check("2026-02-26T12:00:00Z")
        with self.assertRaises(KeyboardInterrupt):
            self.run_with(CountingReplay("2026-02-26", crash="NVDA"), "2026-02-26T12:00:00Z")
        with self.assertRaises(KeyboardInterrupt):
            self.run_with(CountingReplay("2026-02-26", crash="NVDA"), "2026-02-26T13:00:00Z")
        state = self.chain.resolve("2026-02-26T13:00:00Z")
        self.assertEqual(state["MU"]["mode"], "AUTO_VERIFIED")  # served second time round
        self.assertEqual((state["NVDA"]["mode"], state["NVDA"]["reason"]), ("WAITING", "EVENT_DETECTED"))

    def test_an_exhausted_issuer_does_not_block_another_in_the_same_run(self):
        self.chain.check("2026-02-26T12:00:00Z")
        summary = self.run_with(CountingReplay("2026-02-26", refuse="NVDA"), "2026-02-26T12:00:00Z")
        self.assertEqual(summary["issuers"]["NVDA"]["reason"], "NETWORK_UNAVAILABLE")
        self.assertEqual(summary["issuers"]["MU"]["outcome"], "VERIFIED")

    def test_a_retry_reuses_stored_archive_documents(self):
        self.chain.check("2025-12-17T23:00:00Z")
        first = CountingReplay("2025-12-17")
        self.assertEqual(self.run_with(first, "2025-12-17T23:00:00Z")["issuers"]["MU"]["reason"], "WAITING_PERIODIC_FILING")
        self.chain.check("2025-12-19T12:00:00Z")
        second = CountingReplay("2025-12-19")
        self.assertEqual(self.run_with(second, "2025-12-19T12:00:00Z")["issuers"]["MU"]["outcome"], "VERIFIED")
        archive = [u for u in first.calls if u.startswith("https://www.sec.gov/Archives/") and "/723125/" in u]
        self.assertGreaterEqual(len(archive), 5)
        self.assertFalse(set(archive) & set(second.calls))  # immutable documents are re-hashed from the store
        self.assertIn("https://data.sec.gov/submissions/CIK0000723125.json", second.calls)  # feeds are always read again

    def test_shared_budget_exhaustion_keeps_fairness_and_progress(self):
        """B0-1/B0-3: with a run budget far smaller than one event, each run serves the queue head first, an issuer
        refused only because the shared budget was spent keeps its place, and interrupted plans resume from their
        stored captures until both issuers verify."""
        self.chain.check("2026-02-26T12:00:00Z")
        runs, seen = 0, []
        while runs < 16:
            transport = SharedBudget("2026-02-26", limit=6)
            summary = self.run_with(transport, f"2026-02-26T12:{runs:02d}:00Z")
            runs += 1
            if transport.calls:
                seen.append(transport.calls[0][0])
            state = self.chain.resolve(f"2026-02-26T12:{runs - 1:02d}:00Z")
            if state["NVDA"]["mode"] == state["MU"]["mode"] == "AUTO_VERIFIED":
                break
        self.assertEqual((state["NVDA"]["mode"], state["MU"]["mode"]), ("AUTO_VERIFIED", "AUTO_VERIFIED"), summary)
        self.assertIn("MU", seen[:2])  # MU is served first no later than the second run
        self.assertLess(runs, 16)

    def test_an_interrupted_plan_resumes_from_its_captures(self):
        self.chain.check("2026-02-26T12:00:00Z")
        first = SharedBudget("2026-02-26", limit=4)
        self.run_with(first, "2026-02-26T12:00:00Z")
        gen = overlay.generation_at(self.chain.state, "2026-02-26T12:00:00Z")
        waited = overlay.last_attempt(self.chain.state, gen["issuers"][first.calls[0][0]])
        self.assertEqual((waited["outcome"], waited["reason"]), ("WAITING", "NETWORK_UNAVAILABLE"))
        self.assertEqual(len(waited["captures"]), 4)  # the interrupted plan keeps what it stored
        second = SharedBudget("2026-02-26", limit=6)
        self.run_with(second, "2026-02-26T13:00:00Z")
        archive = {u for s, u in first.calls if u.startswith("https://www.sec.gov/Archives/")}
        self.assertTrue(archive)
        self.assertFalse(archive & {u for s, u in second.calls})

    def test_repeated_same_reason_interruptions_accumulate_progress(self):
        """B0-R2-1: four requests per run (less than any plan) and the same interruption every time: the capture
        checkpoint grows run after run and both issuers verify."""
        self.chain.check("2026-02-26T12:00:00Z")
        for run in range(30):
            self.run_with(SharedBudget("2026-02-26", limit=4), f"2026-02-26T13:{run:02d}:00Z")
            state = self.chain.resolve(f"2026-02-26T13:{run:02d}:00Z")
            if state["NVDA"]["mode"] == state["MU"]["mode"] == "AUTO_VERIFIED":
                break
        self.assertEqual((state["NVDA"]["mode"], state["MU"]["mode"]), ("AUTO_VERIFIED", "AUTO_VERIFIED"))
        self.assertLess(run, 29)
        for sym in ("NVDA", "MU"):  # the wire copy was waited for, not given up under the budget
            routing = next(d for d in state[sym]["attempt"]["decisions"] if d["kind"] == "ROUTING")["operands"]
            self.assertIsNotNone(routing["wire_item"], sym)

    def test_forged_older_consumption_clears_nothing(self):
        """B0-R2-2: only the re-derived producer accounts for detections; an older verified attempt's decisions (even
        forged) have no effect."""
        for instant in ("2026-02-26T12:00:00Z", "2026-05-21T12:00:00Z"):
            self.chain.cycle(instant)
        item = {"channel": "ISSUER_IR", "date": "2026-05-20", "id": "https://investor.nvidia.com/news/press-release-details/2026/X/default.aspx",
                "label": "synthetic same-day release", "disposition": "POSSIBLY_RELEVANT"}
        pointer = json.loads((self.chain.state / "current.json").read_text(encoding="utf-8"))
        path = self.chain.state / "generations" / f"{pointer['generation_id']}.json"
        gen = json.loads(path.read_text(encoding="utf-8"))
        gen["detections"]["NVDA"] = {"documents": [item], "overflow": False}
        older = next(a for a in gen["issuers"]["NVDA"]["open"] if a["outcome"] == "VERIFIED")
        next(d for d in older["decisions"] if d["kind"] == "ROUTING")["operands"]["consumed"].append(
            {"channel": item["channel"], "id": item["id"], "date": item["date"]})
        data = json.dumps(gen, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8")
        path.write_bytes(data)
        pointer["sha256"] = hashlib.sha256(data).hexdigest()
        (self.chain.state / "current.json").write_text(json.dumps(pointer), encoding="utf-8")
        admitted = overlay.admit(self.chain.state, overlay.generation_at(self.chain.state, "2026-05-21T12:00:00Z"), "2026-05-21T12:00:00Z",
                                 PROFILES_BY_SYMBOL, self.chain.curated(),
                                 overlay.identity(PROFILES.read_bytes(), self.chain.registry.read_bytes(), self.chain.approval.read_bytes()),
                                 allow_replay=True)["NVDA"]
        self.assertEqual(admitted["mode"], "AUTO_VERIFIED")
        self.assertIn(item["id"], [d["id"] for d in admitted["detections"]])  # still unresolved (same day as the producer)

    def test_admission_reads_a_bounded_part_of_a_long_history(self):
        """B0-R2-3: a producer sealed under 40 later blocked events: admission loads only the segments it needs; a
        corrupted required segment blocks the issuer."""
        self.chain.cycle("2026-02-26T12:00:00Z")
        self.chain.check("2026-03-02T12:00:00Z")
        rows = json.loads(self.chain.receipts.read_text(encoding="utf-8"))
        receipt = rows["issuers"]["NVDA"][-1]
        receipt["later_documents"] = receipt["later_documents"] + [
            {"channel": "SEC_SUBMISSIONS", "date": "2026-03-01", "id": f"0001045810-26-9{i:05d}", "label": "8-K items 2.02,9.01",
             "disposition": "RESULTS_RELEASE"} for i in range(40)]
        self.chain.receipts.write_text(json.dumps(rows), encoding="utf-8")
        for i in range(40):
            self.run_with(CountingReplay("2026-03-02"), f"2026-03-02T12:{i:02d}:00Z")
        entry = overlay.generation_at(self.chain.state, "2026-03-03T00:00:00Z")["issuers"]["NVDA"]
        self.assertEqual(entry["index"]["verified"][0]["segment"], entry["head"])  # the producer is sealed
        self.assertEqual(overlay.verify_history(self.chain.state, entry), 41)
        loads = []
        original = overlay.load_segment
        overlay.load_segment = lambda root, digest: loads.append(digest) or original(root, digest)
        try:
            state = self.chain.resolve("2026-03-03T00:00:00Z")
        finally:
            overlay.load_segment = original
        self.assertEqual((state["NVDA"]["mode"], state["NVDA"]["reason"]), ("BLOCKED", "EVENT_UNRESOLVED"))
        self.assertEqual(state["NVDA"]["effective"]["claims"][0]["stated_point"], 78.0e9)
        self.assertLessEqual(len(set(loads)), 1)  # the producer's segment only
        path = overlay.segment_path(self.chain.state, entry["head"])
        path.write_bytes(path.read_bytes().replace(b"results filing detected", b"results filing detectex", 1))
        self.assertEqual(self.chain.resolve("2026-03-03T00:00:00Z")["NVDA"]["mode"], "BLOCKED")

    def test_missing_audit_history_does_not_stop_another_issuer(self):
        """B0-R3-1: 33 blocked NVDA events seal one segment; that segment is removed. Admission does not need it
        (NVDA keeps its open state), the structural audit reports it, and MU's release still verifies and commits."""
        self.fake_results(33)
        for i in range(33):
            self.run_with(CountingReplay("2025-11-25"), f"2025-11-25T12:{i:02d}:00Z")
        entry = overlay.generation_at(self.chain.state, "2025-11-26T00:00:00Z")["issuers"]["NVDA"]
        self.assertEqual((entry["sealed"], len(entry["open"])), (32, 1))
        overlay.segment_path(self.chain.state, entry["head"]).unlink()
        with self.assertRaises(overlay.StateError):
            overlay.verify_history(self.chain.state, entry)
        self.assertEqual(self.chain.resolve("2025-11-26T00:00:00Z")["NVDA"]["reason"], "EVENT_UNRESOLVED")
        # also across an identity change
        approval = json.loads(self.chain.approval.read_text(encoding="utf-8"))
        self.chain.approval.write_text(json.dumps(dict(approval, revision=2)), encoding="utf-8")
        self.assertTrue(self.chain.update("2025-12-19T11:00:00Z")["reverified"])
        summary = self.chain.cycle("2025-12-19T12:00:00Z")
        self.assertEqual(summary["issuers"]["MU"].get("outcome"), "VERIFIED", summary)
        self.assertEqual(self.chain.resolve("2025-12-19T12:00:00Z")["MU"]["mode"], "AUTO_VERIFIED")
        entry_now = overlay.generation_at(self.chain.state, "2025-12-19T12:00:00Z")["issuers"]["NVDA"]
        self.assertEqual(entry_now["head"], entry["head"])  # the reference is carried, nothing dropped

    def test_a_missing_required_segment_blocks_only_its_issuer(self):
        """The producer's own segment is required: missing, the issuer is blocked (never curated numbers) and the other
        issuer still commits."""
        self.chain.cycle("2026-02-26T12:00:00Z")
        self.chain.check("2026-03-02T12:00:00Z")
        rows = json.loads(self.chain.receipts.read_text(encoding="utf-8"))
        receipt = rows["issuers"]["NVDA"][-1]
        receipt["later_documents"] = receipt["later_documents"] + [
            {"channel": "SEC_SUBMISSIONS", "date": "2026-03-01", "id": f"0001045810-26-9{i:05d}", "label": "8-K items 2.02,9.01",
             "disposition": "RESULTS_RELEASE"} for i in range(40)]
        self.chain.receipts.write_text(json.dumps(rows), encoding="utf-8")
        for i in range(40):
            self.run_with(CountingReplay("2026-03-02"), f"2026-03-02T12:{i:02d}:00Z")
        entry = overlay.generation_at(self.chain.state, "2026-03-03T00:00:00Z")["issuers"]["NVDA"]
        self.assertEqual(entry["index"]["verified"][-1]["segment"], entry["head"])
        overlay.segment_path(self.chain.state, entry["head"]).unlink()
        state = self.chain.resolve("2026-03-03T00:00:00Z")["NVDA"]
        self.assertEqual((state["mode"], state["reason"], state["record"]), ("BLOCKED", "STATE_CORRUPT", None))
        summary = self.chain.cycle("2026-05-21T12:00:00Z")
        self.assertEqual(summary["issuers"]["NVDA"], {"action": "BLOCKED", "reason": "STATE_CORRUPT"})
        self.assertIn("MU", summary["issuers"])
        self.assertIsNotNone(overlay.generation_at(self.chain.state, "2026-05-21T12:00:00Z"))  # publication not stopped
        self.assertEqual(self.chain.resolve("2026-05-21T12:00:00Z")["NVDA"]["mode"], "BLOCKED")

    def test_attempts_after_the_cutoff_are_never_admitted(self):
        """B0-R3-2: a generation whose attempts lie after its (rehashed, backdated) creation time is inconsistent."""
        self.chain.cycle("2026-02-26T12:00:00Z")
        self.assertEqual(self.chain.resolve("2026-02-25T00:00:00Z")["NVDA"]["mode"], "CURATED")  # honest history
        pointer = json.loads((self.chain.state / "current.json").read_text(encoding="utf-8"))
        path = self.chain.state / "generations" / f"{pointer['generation_id']}.json"
        gen = json.loads(path.read_text(encoding="utf-8"))
        gen["created_at"], gen["parent"] = "2026-02-24T00:00:00Z", None
        data = json.dumps(gen, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8")
        path.write_bytes(data)
        pointer["sha256"] = hashlib.sha256(data).hexdigest()
        (self.chain.state / "current.json").write_text(json.dumps(pointer), encoding="utf-8")
        state = self.chain.resolve("2026-02-25T00:00:00Z")["NVDA"]
        self.assertEqual((state["mode"], state["reason"], state["record"]), ("BLOCKED", "STATE_CORRUPT", None))

    @staticmethod
    def raw_on_disk(root: Path) -> int:
        folder = root / "captures"
        return sum(f.stat().st_size for b in folder.iterdir() for f in b.iterdir()
                   if not f.name.endswith(".json") and ".tmp-" not in f.name) if folder.exists() else 0

    @staticmethod
    def interrupted(window: str):
        """Interrupt store_capture's next new object in one window: reserve (during the reservation commit), raw (a
        partial temporary raw file, then stop), meta (after the raw commit) or clear (after the metadata commit)."""
        original = overlay._durable_write
        writes = []

        def durable(path, data):
            kind = "usage" if path.name == overlay.USAGE_FILE else "meta" if path.name.endswith(".json") else "raw"
            writes.append(kind)
            stop = {"reserve": writes == ["usage"], "raw": kind == "raw", "meta": kind == "meta",
                    "clear": writes == ["usage", "raw", "meta", "usage"]}[window]
            if stop:
                if kind == "raw":
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.with_name(path.name + f".tmp-{os.getpid()}").write_bytes(data[: len(data) // 2])
                raise KeyboardInterrupt
            return original(path, data)
        return mock.patch.object(overlay, "_durable_write", durable)

    def test_store_accounting_survives_every_interruption_window(self):
        """B0-R4-1: an interruption in any window of a capture leaves a journal that reconciles to exactly the raw
        bytes on disk (never less), removes only the incomplete temporary file, and a retry counts nothing twice."""
        meta = {"url": "https://www.sec.gov/Archives/edgar/data/1/x", "retrieved_at": "2026-01-01T00:00:00Z"}
        for window in ("reserve", "raw", "meta", "clear"):
            with self.subTest(window=window):
                root = Path(self.tmp.name) / f"store-{window}"
                overlay.store_capture(root, b"first object", meta)
                with self.interrupted(window), self.assertRaises(KeyboardInterrupt):
                    overlay.store_capture(root, b"second object " * 1000, meta)
                self.assertGreaterEqual(overlay._read_usage_file(root)["bytes"], self.raw_on_disk(root))  # never under
                self.assertEqual(overlay.reconcile_usage(root), self.raw_on_disk(root))
                self.assertFalse([f for b in (root / "captures").iterdir() for f in b.iterdir() if ".tmp-" in f.name])
                sha = overlay.store_capture(root, b"second object " * 1000, meta)  # retry (repairs missing metadata)
                overlay.store_capture(root, b"first object", meta)  # duplicate reuse
                self.assertEqual(overlay.load_capture(root, sha)["raw"], b"second object " * 1000)
                self.assertEqual(overlay.reconcile_usage(root), self.raw_on_disk(root))
                self.assertEqual(overlay.reconcile_usage(root), len(b"first object") + len(b"second object " * 1000))

    def initialize(self, when: str = "2025-01-01T00:00:00Z") -> None:
        """An initialized state root (one empty generation), as the updater leaves it before it ever captures: captures
        without a pointer are damaged state (B1 R2)."""
        ident = overlay.identity(PROFILES.read_bytes(), self.chain.registry.read_bytes(), self.chain.approval.read_bytes())
        gen = dict(ident, schema=overlay.STATE_SCHEMA, generation_id=updater._new_generation_id(at(when)), parent=None,
                   created_at=when, issuers={}, detections={})
        overlay.publish_generation(self.chain.state, gen, None)

    def test_the_updater_keeps_its_quota_after_an_interrupted_capture(self):
        """B0-R4-1 through the actual updater (quota lowered to 1 MiB for the test): a capture interrupted after its
        metadata leaves no under-count, so the release waits and nothing is stored beyond the quota."""
        self.initialize()
        with self.interrupted("clear"), self.assertRaises(KeyboardInterrupt):
            overlay.store_capture(self.chain.state, b"x" * (1 << 20), {"url": "https://www.sec.gov/Archives/edgar/data/1/y",
                                                                        "retrieved_at": "2026-01-01T00:00:00Z"})
        self.chain.check("2026-02-26T12:00:00Z")
        with mock.patch.object(updater, "STORE_QUOTA_BYTES", 1 << 20):
            summary = self.run_with(CountingReplay("2026-02-26"), "2026-02-26T12:00:00Z")
        self.assertEqual(summary["issuers"]["NVDA"]["reason"], "CAPTURE_LIMIT")
        self.assertEqual(self.raw_on_disk(self.chain.state), 1 << 20)
        self.assertEqual(self.run_with(CountingReplay("2026-02-26"), "2026-02-26T13:00:00Z")["issuers"]["NVDA"]["outcome"], "VERIFIED")

    def test_ordinary_runs_enumerate_nothing_and_unknown_accounting_waits(self):
        """B0-R4-2: no ordinary run enumerates the capture store, however large; an unknown journal makes captures wait
        (detections still commit) until the --recount-store maintenance command rebuilds it."""
        self.initialize()
        for i in range(128):
            overlay.store_capture(self.chain.state, f"synthetic {i}".encode(), {"url": f"https://www.sec.gov/Archives/edgar/data/1/{i}",
                                                                              "retrieved_at": "2025-01-01T00:00:00Z"})
        enumerated = []

        def counting(name, original):
            def wrapper(*a, **k):
                if "captures" in str(a[0] if a else k.get("path", "")):
                    enumerated.append(name)
                return original(*a, **k)
            return wrapper
        patches = [mock.patch.object(os, "scandir", counting("scandir", os.scandir)),
                   mock.patch.object(os, "listdir", counting("listdir", os.listdir)),
                   mock.patch.object(Path, "iterdir", counting("iterdir", Path.iterdir))]
        self.chain.check("2026-02-26T12:00:00Z")
        (self.chain.state / overlay.USAGE_FILE).unlink()
        for p in patches:
            p.start()
        try:
            summary = self.run_with(CountingReplay("2026-02-26"), "2026-02-26T12:00:00Z")
        finally:
            for p in patches:
                p.stop()
        self.assertEqual(summary["store_accounting"], "UNKNOWN")
        self.assertEqual(summary["issuers"]["NVDA"]["reason"], "CAPTURE_LIMIT")
        gen = overlay.generation_at(self.chain.state, "2026-02-26T12:00:00Z")
        self.assertEqual(gen["issuers"]["NVDA"]["open"][-1]["event_key"], "0001045810-26-000019")  # detection committed
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(updater.main(["--state-root", str(self.chain.state), "--recount-store"]), 0)
        self.assertEqual(json.loads(out.getvalue())["bytes"], self.raw_on_disk(self.chain.state))
        for p in patches:
            p.start()
        try:
            summary = self.run_with(CountingReplay("2026-02-26"), "2026-02-26T13:00:00Z")
        finally:
            for p in patches:
                p.stop()
        self.assertEqual(summary["issuers"]["NVDA"]["outcome"], "VERIFIED")
        self.assertEqual(enumerated, [])
        self.assertEqual(overlay.reconcile_usage(self.chain.state), self.raw_on_disk(self.chain.state))

    def test_admission_rederives_one_release_per_issuer(self):
        """B0-4: admission work is one re-derivation per issuer however long the verified history grows."""
        for instant in ("2026-02-26T12:00:00Z", "2026-05-21T12:00:00Z", "2026-08-27T12:00:00Z"):
            self.chain.cycle(instant)
        calls = []
        original = verify.build_successor
        verify.build_successor = lambda *a, **k: calls.append(a[0]["symbol"]) or original(*a, **k)
        try:
            state = self.chain.resolve("2026-08-27T12:00:00Z")
        finally:
            verify.build_successor = original
        self.assertEqual(state["NVDA"]["record"]["claims"][0]["stated_point"], 108.0e9)
        self.assertEqual(sorted(calls), ["MU", "NVDA"])  # NVDA has three verified releases, one is replayed

    def test_older_history_is_not_operative(self):
        """A rehashed forged older verified record (numbers and channels) changes nothing current: the producer is
        re-derived with channels from the baseline and no inherited number."""
        for instant in ("2026-02-26T12:00:00Z", "2026-05-21T12:00:00Z"):
            self.chain.cycle(instant)
        before = self.chain.resolve("2026-05-21T12:00:00Z")["NVDA"]["record"]
        pointer = json.loads((self.chain.state / "current.json").read_text(encoding="utf-8"))
        path = self.chain.state / "generations" / f"{pointer['generation_id']}.json"
        gen = json.loads(path.read_text(encoding="utf-8"))
        attempts = gen["issuers"]["NVDA"]["open"]
        verified = [a for a in attempts if a["outcome"] == "VERIFIED"]
        old = verified[0]
        old["record"]["claims"][0]["stated_point"] = 1.0
        old["record"]["release_channels"]["ir"]["url"] = "https://evil.example/feed"
        old["record_sha256"] = overlay.record_sha256(old["record"])
        for a in attempts[attempts.index(old) + 1:]:
            a["predecessor_sha256"] = overlay.record_sha256(old["record"]) if a["predecessor_sha256"] != overlay.record_sha256(before) else a["predecessor_sha256"]
        data = json.dumps(gen, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8")
        path.write_bytes(data)
        pointer["sha256"] = hashlib.sha256(data).hexdigest()
        (self.chain.state / "current.json").write_text(json.dumps(pointer), encoding="utf-8")
        after = self.chain.resolve("2026-05-21T12:00:00Z")["NVDA"]
        self.assertEqual(after["mode"], "AUTO_VERIFIED")
        self.assertEqual(after["record"], before)
        self.assertEqual(after["record"]["release_channels"]["ir"]["url"], self.chain.curated()["NVDA"]["release_channels"]["ir"]["url"])

    # history segments
    def fake_results(self, count: int) -> None:
        self.chain.check("2025-11-25T12:00:00Z")
        rows = json.loads(self.chain.receipts.read_text(encoding="utf-8"))
        receipt = rows["issuers"]["NVDA"][-1]
        receipt["later_documents"] = receipt["later_documents"] + [
            {"channel": "SEC_SUBMISSIONS", "date": "2025-11-24", "id": f"0001045810-25-9{i:05d}", "label": "8-K items 2.02,9.01",
             "disposition": "RESULTS_RELEASE"} for i in range(count)]
        self.chain.receipts.write_text(json.dumps(rows), encoding="utf-8")

    def test_history_beyond_64_transitions_is_segmented_and_complete(self):
        self.fake_results(70)
        for i in range(70):
            summary = self.run_with(CountingReplay("2025-11-25"), f"2025-11-25T12:{i // 60:02d}:{i % 60:02d}Z")
            self.assertEqual((summary["issuers"]["NVDA"]["outcome"], summary["issuers"]["NVDA"]["reason"]), ("BLOCKED", "EVENT_UNRESOLVED"), i)
        gen = overlay.generation_at(self.chain.state, "2025-11-26T00:00:00Z")
        entry = gen["issuers"]["NVDA"]
        self.assertEqual((entry["sealed"], len(entry["open"])), (64, 6))  # two chained segments, constant-size entry
        self.assertEqual(overlay.verify_history(self.chain.state, entry), 70)  # nothing dropped (full audit)
        state = self.chain.resolve("2025-11-26T00:00:00Z")["NVDA"]
        self.assertEqual((state["mode"], state["reason"]), ("BLOCKED", "EVENT_UNRESOLVED"))
        self.assertEqual(state["effective"]["claims"][0]["stated_point"], 65.0e9)  # the curated record stays the effective one
        # a restart continues on the same segments; an altered old segment blocks only this issuer
        self.assertEqual(self.run_with(CountingReplay("2025-11-25"), "2025-11-25T13:00:00Z")["issuers"]["NVDA"]["action"], "SETTLED")
        # an identity change re-derives producers only (there is none here); the whole history stays intact
        approval = json.loads(self.chain.approval.read_text(encoding="utf-8"))
        self.chain.approval.write_text(json.dumps(dict(approval, revision=2)), encoding="utf-8")
        self.assertTrue(self.run_with(CountingReplay("2025-11-25"), "2025-11-25T13:30:00Z")["reverified"])
        entry = overlay.generation_at(self.chain.state, "2025-11-26T00:00:00Z")["issuers"]["NVDA"]
        self.assertEqual(overlay.verify_history(self.chain.state, entry), 70)
        self.assertEqual(self.chain.resolve("2025-11-26T00:00:00Z")["NVDA"]["reason"], "EVENT_UNRESOLVED")
        # an altered old segment that admission does not need is found by the structural audit, not by admission
        path = overlay.segment_path(self.chain.state, entry["head"])
        path.write_bytes(path.read_bytes().replace(b"EVENT_UNRESOLVED", b"EVENT_UNRESOLVEX", 1))
        with self.assertRaises(overlay.StateError):
            overlay.verify_history(self.chain.state, entry)
        self.assertEqual(self.chain.resolve("2025-11-26T00:00:00Z")["NVDA"]["reason"], "EVENT_UNRESOLVED")
        # B0-2: an unreadable required history of NVDA (its open attempts altered) does not stop MU from committing and
        # verifying, also across an identity change; NVDA's entry is carried unchanged and it stays blocked
        pointer = json.loads((self.chain.state / "current.json").read_text(encoding="utf-8"))
        gpath = self.chain.state / "generations" / f"{pointer['generation_id']}.json"
        gen = json.loads(gpath.read_text(encoding="utf-8"))
        gen["issuers"]["NVDA"]["open"][-1]["outcome"] = "SOMETHING"
        data = json.dumps(gen, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8")
        gpath.write_bytes(data)
        pointer["sha256"] = hashlib.sha256(data).hexdigest()
        (self.chain.state / "current.json").write_text(json.dumps(pointer), encoding="utf-8")
        state = self.chain.resolve("2025-11-26T00:00:00Z")
        self.assertEqual((state["NVDA"]["mode"], state["NVDA"]["reason"]), ("BLOCKED", "STATE_CORRUPT"))
        summary = self.run_with(CountingReplay("2025-11-25"), "2025-11-25T14:00:00Z")
        self.assertEqual(summary["issuers"]["NVDA"], {"action": "BLOCKED", "reason": "STATE_CORRUPT"})  # nothing fetched
        self.chain.approval.write_text(json.dumps(dict(approval, revision=3)), encoding="utf-8")
        # (the run after an identity change re-verifies first; discovery against the re-verified records follows -
        # keeping discovery running while an issuer is unadmitted is B1's effective-input boundary)
        self.assertTrue(self.chain.update("2025-12-19T11:00:00Z")["reverified"])
        summary = self.chain.cycle("2025-12-19T12:00:00Z")
        self.assertEqual(summary["issuers"]["MU"].get("outcome"), "VERIFIED", summary)
        state = self.chain.resolve("2025-12-19T12:00:00Z")
        self.assertEqual((state["NVDA"]["mode"], state["NVDA"]["reason"]), ("BLOCKED", "STATE_CORRUPT"))
        self.assertEqual(state["MU"]["mode"], "AUTO_VERIFIED")
        entry_now = overlay.generation_at(self.chain.state, "2025-12-19T12:00:00Z")["issuers"]["NVDA"]
        self.assertEqual(entry_now, gen["issuers"]["NVDA"])  # carried unchanged


if __name__ == "__main__":
    unittest.main()
