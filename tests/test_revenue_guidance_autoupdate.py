"""ORDERS-V3-AUTOUPDATE-01 Part A: public-filing replay chains and fail-closed behaviour (docs/REVENUE_GUIDANCE_AUTOUPDATE.md).

The chains start from the test baseline (bootstrap-registry.json: each issuer as of the release before the chain) and
run the real release checker over complete replayed SEC, wire and IR feeds, the updater with a hermetic replay
transport, and admission by re-derivation, release after release. The curated production records
(config/revenue-guidance-v1.json) are used only as an oracle for the last link, and every expected value below is
typed from the filings, never computed by the code under test."""
from __future__ import annotations

import contextlib
import copy
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.parse
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import revenue_guidance  # noqa: E402
import revenue_guidance_auto_verify as verify  # noqa: E402
import revenue_guidance_autoupdate as updater  # noqa: E402
import revenue_guidance_overlay as overlay  # noqa: E402
import revenue_guidance_release_check as checker  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "revenue-guidance-autoupdate"
PROFILES = ROOT / "config" / "revenue-guidance-extraction-profiles-v1.json"
INVENTORY = json.loads((FIXTURES / "inventory.json").read_text(encoding="utf-8"))
BY_URL = {row["url"]: row for row in INVENTORY}
EXHIBIT = re.compile(r"q[1-4]fy[0-9]{2}pr\.htm|a20[0-9]{2}q[1-4]ex991-pressrelease\.htm")


def fixture_bytes(row: dict) -> bytes:
    data = gzip.decompress((FIXTURES / "raw" / f"{row['sha256']}.gz").read_bytes())
    if hashlib.sha256(data).hexdigest() != row["sha256"] or len(data) != row["bytes"]:
        raise AssertionError(f"fixture bytes changed: {row['url']}")
    return data


def row_of(issuer: str, role: str, **match) -> dict:
    rows = [r for r in INVENTORY if r["issuer"] == issuer and r["role"] == role and all(r.get(k) == v for k, v in match.items())]
    assert len(rows) == 1, (issuer, role, match, len(rows))
    return rows[0]


def exhibit_row(issuer: str, filed: str) -> dict:
    rows = [r for r in INVENTORY if r["issuer"] == issuer and r["role"] == "FILING_DOCUMENT" and r["filed"] == filed
            and EXHIBIT.fullmatch(r.get("name", ""))]
    assert len(rows) == 1
    return rows[0]


def at(instant: str):
    moment = datetime.strptime(instant, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return lambda: moment


# ------------------------------------------------------------------------------------------------ replay feeds

def sec_fetch_as_of(day: str):
    """The captured submissions feed as it stood on `day` (later filings removed from every parallel array)."""
    def fetch(url: str):
        data = json.loads(fixture_bytes(BY_URL[url]).decode("utf-8"))
        recent = data["filings"]["recent"]
        count = len(recent["filingDate"])
        keep = [i for i, filed in enumerate(recent["filingDate"]) if filed <= day]
        for key, values in list(recent.items()):
            if isinstance(values, list) and len(values) == count:
                recent[key] = [values[i] for i in keep]
        return data
    return fetch


def ir_fetch_as_of(day: str):
    def fetch(url: str) -> bytes:
        data = json.loads(fixture_bytes(BY_URL[url]).decode("utf-8"))
        rows = data["GetPressReleaseListResult"]
        data["GetPressReleaseListResult"] = [r for r in rows if datetime.strptime(r["PressReleaseDate"][:10], "%m/%d/%Y").date().isoformat() <= day]
        return json.dumps(data).encode("utf-8")
    return fetch


def wire_fetch_as_of(day: str):
    """The captured Nasdaq press-release feed as it stood on `day`, paged as the checker requests it."""
    def fetch(url: str):
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        symbol = query["q"][0].split("|")[0].split(":")[1].upper()
        rows = [r for p in INVENTORY if p["issuer"] == symbol and p["role"] == "WIRE_FEED_PAGE"
                for r in json.loads(fixture_bytes(p).decode("utf-8"))["data"]["rows"]]
        seen, current = set(), []
        for r in rows:
            if r["id"] not in seen and datetime.strptime(r["created"], "%b %d, %Y").date().isoformat() <= day:
                seen.add(r["id"])
                current.append(r)
        offset, limit = int(query["offset"][0]), int(query["limit"][0])
        return {"data": {"rows": current[offset:offset + limit], "totalrecords": len(current)}}
    return fetch


class ReplayAsOf(updater.ReplayTransport):
    """The fixture replay, refusing any document not yet filed on the replay day (as the real feed would not list it)."""

    def __init__(self, day: str):
        super().__init__(FIXTURES)
        self.day = day

    def get(self, url, profile, symbol):
        row = self.by_url.get(url)
        if row is not None and row.get("filed") and row["filed"] > self.day:
            raise updater.NetworkBlocked("REPLAY_NOT_YET_FILED")
        data, ctype = super().get(url, profile, symbol)
        if row is not None and row.get("role") == "SEC_SUBMISSIONS":
            data = json.dumps(sec_fetch_as_of(self.day)(url)).encode("utf-8")
        return data, ctype


# ------------------------------------------------------------------------------------------------ the loop under test

class Chain:
    """One temporary runtime: baseline files, receipts cache and auto-update state root."""

    def __init__(self, base: Path):
        self.base = base
        self.state = base / "state"
        self.registry = base / "revenue-guidance-v1.json"
        self.approval = base / "revenue-guidance-approval-v1.json"
        self.receipts = base / "revenue_guidance_release_checks.json"
        shutil.copyfile(FIXTURES / "bootstrap-registry.json", self.registry)
        self.approval.write_text('{"schema": "test-baseline-approval"}\n', encoding="utf-8")

    def curated(self) -> dict:
        return {r["symbol"]: r for r in json.loads(self.registry.read_text(encoding="utf-8"))["issuers"]}

    def resolve(self, cutoff: str, receipts: bool = False) -> dict:
        return overlay.resolve_issuers(self.state, cutoff, PROFILES.read_bytes(), self.registry.read_bytes(), self.approval.read_bytes(),
                                       self.curated(), json.loads(self.receipts.read_text(encoding="utf-8")) if receipts else None,
                                       allow_replay=True)

    def snapshot(self, instant: str, **kwargs) -> "overlay.EffectiveInputs":
        """The shared effective-input snapshot (B1) of this runtime at the instant."""
        return overlay.load_effective_inputs(cutoff=instant, state_root=self.state, registry_path=self.registry, approval_path=self.approval,
                                             profiles_path=PROFILES, receipts_path=self.receipts, allow_replay=True, **kwargs)

    def check(self, instant: str) -> dict:
        """The real release checker over the shared discovery records (B1: the production entry point, no merge)."""
        day = instant[:10]
        return checker.run(self.registry, self.receipts, datetime.strptime(instant, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc),
                           sec_fetch_as_of(day), wire_fetch_as_of(day), ir_fetch_as_of(day), effective_inputs=self.snapshot(instant))

    def update(self, instant: str) -> dict:
        return updater.run(self.state, ReplayAsOf(instant[:10]), at(instant), PROFILES, self.registry, self.approval, self.receipts)

    def cycle(self, instant: str) -> dict:
        self.check(instant)
        return self.update(instant)


NVDA_EXPECTED = [
    # (instant, claim point, low, high, label, period, trailing quarters (label, start, end, revenue))
    ("2026-02-26T12:00:00Z", 78.0e9, 76.44e9, 79.56e9, "Q1 FY27", ("2026-01-26", "2026-04-26"),
     [("Q1 FY26", "2025-01-27", "2025-04-27", 44062e6), ("Q2 FY26", "2025-04-28", "2025-07-27", 46743e6),
      ("Q3 FY26", "2025-07-28", "2025-10-26", 57006e6), ("Q4 FY26", "2025-10-27", "2026-01-25", 68127e6)]),
    ("2026-05-21T12:00:00Z", 91.0e9, 89.18e9, 92.82e9, "Q2 FY27", ("2026-04-27", "2026-07-26"),
     [("Q2 FY26", "2025-04-28", "2025-07-27", 46743e6), ("Q3 FY26", "2025-07-28", "2025-10-26", 57006e6),
      ("Q4 FY26", "2025-10-27", "2026-01-25", 68127e6), ("Q1 FY27", "2026-01-26", "2026-04-26", 81615e6)]),
    ("2026-08-27T12:00:00Z", 108.0e9, 105.84e9, 110.16e9, "Q3 FY27", ("2026-07-27", "2026-10-25"),
     [("Q3 FY26", "2025-07-28", "2025-10-26", 57006e6), ("Q4 FY26", "2025-10-27", "2026-01-25", 68127e6),
      ("Q1 FY27", "2026-01-26", "2026-04-26", 81615e6), ("Q2 FY27", "2026-04-27", "2026-07-26", 96221e6)]),
]
NVDA_FORWARD_FINAL = [("2026-07-27", "2026-10-25"), ("2026-10-26", "2027-01-31"), ("2027-02-01", "2027-05-02"), ("2027-05-03", "2027-08-01")]
MU_EXPECTED = [
    ("2025-12-19T12:00:00Z", 18.7e9, 18.3e9, 19.1e9, "FQ2-26", ("2025-11-28", "2026-02-26"),
     [("FQ2-25", "2024-11-29", "2025-02-27", 8053e6), ("FQ3-25", "2025-02-28", "2025-05-29", 9301e6),
      ("FQ4-25", "2025-05-30", "2025-08-28", 11315e6), ("FQ1-26", "2025-08-29", "2025-11-27", 13643e6)]),
    ("2026-03-20T12:00:00Z", 33.5e9, 32.75e9, 34.25e9, "FQ3-26", ("2026-02-27", "2026-05-28"),
     [("FQ3-25", "2025-02-28", "2025-05-29", 9301e6), ("FQ4-25", "2025-05-30", "2025-08-28", 11315e6),
      ("FQ1-26", "2025-08-29", "2025-11-27", 13643e6), ("FQ2-26", "2025-11-28", "2026-02-26", 23860e6)]),
    ("2026-06-26T12:00:00Z", 50.0e9, 49.0e9, 51.0e9, "FQ4-26", ("2026-05-29", "2026-09-03"),
     [("FQ4-25", "2025-05-30", "2025-08-28", 11315e6), ("FQ1-26", "2025-08-29", "2025-11-27", 13643e6),
      ("FQ2-26", "2025-11-28", "2026-02-26", 23860e6), ("FQ3-26", "2026-02-27", "2026-05-28", 41456e6)]),
]
MU_FORWARD_FINAL = [("2026-05-29", "2026-09-03"), ("2026-09-04", "2026-12-03"), ("2026-12-04", "2027-03-04"), ("2027-03-05", "2027-06-03")]


class ReplayChainTests(unittest.TestCase):
    """Three consecutive real releases per issuer through checker -> updater -> admission -> gate."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.chain = Chain(Path(cls.tmp.name))
        cls.results = {"NVDA": [], "MU": []}
        # Before any automatic state: the gate already applies to the curated baseline (Astra A1-r2 N1).
        cls.chain.check("2025-12-17T23:00:00Z")
        cls.bootstrap_gated = cls.chain.resolve("2025-12-17T23:00:00Z", receipts=True)
        # MU day of the FQ1-26 release: its 10-Q is filed the next day -> the ordinary run waits, the next one succeeds.
        cls.waiting = cls.chain.update("2025-12-17T23:00:00Z")
        cls.waiting_state = cls.chain.resolve("2025-12-17T23:00:00Z")
        instants = sorted({e[0] for e in NVDA_EXPECTED} | {e[0] for e in MU_EXPECTED})
        for instant in instants:
            cls.chain.cycle(instant)
            state = cls.chain.resolve(instant)
            for sym, expected in (("NVDA", NVDA_EXPECTED), ("MU", MU_EXPECTED)):
                if any(e[0] == instant for e in expected):
                    cls.results[sym].append((instant, copy.deepcopy(state[sym])))
        cls.snapshot = Path(cls.tmp.name) / "state-2026-08-27"
        shutil.copytree(cls.chain.state, cls.snapshot)
        # The successors' own checks, as the next ordinary runs make them.
        cls.chain.check("2026-06-27T12:00:00Z")
        cls.mu_gated = cls.chain.resolve("2026-06-27T12:00:00Z", receipts=True)
        # The day after NVDA's release: its own check lists a same-day unrelated IR release (the AWS agreement of
        # 2026-08-26) which nothing accounts for -> detected and waiting; the run after that writes nothing.
        cls.day_after = cls.chain.cycle("2026-08-28T12:00:00Z")
        cls.day_after_state = cls.chain.resolve("2026-08-28T12:00:00Z")
        cls.day_after_gated = cls.chain.resolve("2026-08-28T12:00:00Z", receipts=True)
        cls.idle_before = sorted(p.name for p in (cls.chain.state / "generations").iterdir())
        cls.idle = cls.chain.cycle("2026-08-28T13:00:00Z")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def assert_link(self, sym, expected, got):
        instant, point, low, high, label, (start, end), quarters = expected
        self.assertEqual(got[0], instant)
        state = got[1]
        self.assertEqual(state["mode"], "AUTO_VERIFIED", state.get("detail"))
        record = state["record"]
        revenue_guidance.validate_issuer_record(record, sym)
        claim = record["claims"][0]
        self.assertEqual((claim["stated_point"], claim["low"], claim["high"], claim["fiscal_label"], claim["period_start"], claim["period_end"]),
                         (point, low, high, label, start, end))
        self.assertEqual([(q["fiscal_label"], q["start"], q["end"], q["revenue"]) for q in record["reported_quarters"]], quarters)
        self.assertEqual((record["forward_intervals"][0]["start"], record["forward_intervals"][0]["end"]), (start, end))
        # the sealed passage is the exact span of the canonical release text its locator names
        raw = overlay.load_capture(self.chain.state, state["attempt"]["captures"]["exhibit"])["raw"]
        text = verify.parse_document(raw).text
        a, b = (int(x) for x in re.fullmatch(r"canonical\[(\d+):(\d+)\] rg-canon-1", claim["locator"]).groups())
        self.assertEqual(text[a:b], claim["passage"])

    def test_nvda_three_releases(self):
        self.assertEqual(len(self.results["NVDA"]), 3)
        for expected, got in zip(NVDA_EXPECTED, self.results["NVDA"]):
            self.assert_link("NVDA", expected, got)
        final = self.results["NVDA"][-1][1]["record"]
        self.assertEqual([(i["start"], i["end"]) for i in final["forward_intervals"]], NVDA_FORWARD_FINAL)
        q4 = next(q for q in final["reported_quarters"] if q["fiscal_label"] == "Q4 FY26")
        self.assertEqual((q4["derivation"]["longer_value"], q4["derivation"]["shorter_value"]), (215938e6, 147811e6))

    def test_mu_three_releases_after_a_wait(self):
        self.assertEqual(self.waiting["issuers"]["MU"]["outcome"], "WAITING")
        self.assertEqual(self.waiting["issuers"]["MU"]["reason"], "WAITING_PERIODIC_FILING")
        self.assertEqual(self.waiting_state["MU"]["mode"], "WAITING")
        self.assertIsNone(self.waiting_state["MU"]["record"])  # the old numbers never come back while waiting
        self.assertEqual(len(self.results["MU"]), 3)
        for expected, got in zip(MU_EXPECTED, self.results["MU"]):
            self.assert_link("MU", expected, got)
        final = self.results["MU"][-1][1]["record"]
        self.assertEqual([(i["start"], i["end"]) for i in final["forward_intervals"]], MU_FORWARD_FINAL)
        fq4 = next(q for q in final["reported_quarters"] if q["fiscal_label"] == "FQ4-25")
        self.assertEqual((fq4["derivation"]["longer_value"], fq4["derivation"]["shorter_value"]), (37378e6, 26063e6))

    def test_last_links_equal_the_curated_production_records(self):
        """The curated records of config/revenue-guidance-v1.json are the oracle for the last link of each chain."""
        registry = {r["symbol"]: r for r in json.loads((ROOT / "config" / "revenue-guidance-v1.json").read_text(encoding="utf-8"))["issuers"]}
        for sym in ("NVDA", "MU"):
            auto, curated = self.results[sym][-1][1]["record"], registry[sym]
            keys = ("stated_point", "low", "high", "fiscal_label", "period_start", "period_end", "currency", "accounting_basis", "scope")
            self.assertEqual([auto["claims"][0][k] for k in keys], [curated["claims"][0][k] for k in keys])
            qk = ("fiscal_label", "start", "end", "revenue", "currency", "scope", "accounting_basis")
            self.assertEqual([[q[k] for k in qk] for q in auto["reported_quarters"]], [[q[k] for k in qk] for q in curated["reported_quarters"]])
            for a, c in zip(auto["reported_quarters"], curated["reported_quarters"]):
                da, dc = a.get("derivation"), c.get("derivation")
                self.assertEqual(da is None, dc is None)
                if da:
                    self.assertEqual([da[k] for k in ("kind", "longer_value", "longer_start", "shorter_value", "shorter_end")],
                                     [dc[k] for k in ("kind", "longer_value", "longer_start", "shorter_value", "shorter_end")])
            ik = ("fiscal_label", "start", "end")
            self.assertEqual([[i[k] for k in ik] for i in auto["forward_intervals"]], [[i[k] for k in ik] for i in curated["forward_intervals"]])

    def test_every_decision_names_its_own_capture_and_consumed_copies_are_proven(self):
        for sym in ("NVDA", "MU"):
            state = self.results[sym][-1][1]
            captures = state["attempt"]["captures"]
            self.assertEqual(sorted({d["kind"] for d in state["attempt"]["decisions"]}), ["ACTUAL", "CALENDAR", "CLAIM", "ROUTING"])
            for d in state["attempt"]["decisions"]:
                self.assertIn(d["capture"], captures)
            actual_captures = {d["capture"] for d in state["attempt"]["decisions"] if d["kind"] == "ACTUAL" and not d["ref"].startswith("release:")}
            self.assertGreaterEqual(len(actual_captures), 4)  # each quarter from its own periodic filing
            docs = {d["id"]: d for d in state["record"]["documents"]}
            for q in state["record"]["reported_quarters"]:
                self.assertEqual(docs[q["document_id"]]["source_kind"], "SEC_PERIODIC")
            routing = next(d for d in state["attempt"]["decisions"] if d["kind"] == "ROUTING")["operands"]
            channels = sorted({c["channel"] for c in routing["consumed"]})
            self.assertEqual(channels, ["ISSUER_IR", "SEC_SUBMISSIONS", "WIRE_PRESS_RELEASES"])
            self.assertIsNotNone(routing["wire_item"])

    def test_successor_does_not_inherit_predecessor_numbers(self):
        """The baseline's numbers are not operative: a changed baseline number changes nothing but the chain binding."""
        base = json.loads((FIXTURES / "bootstrap-registry.json").read_text(encoding="utf-8"))
        altered = copy.deepcopy(next(r for r in base["issuers"] if r["symbol"] == "NVDA"))
        for q in altered["reported_quarters"]:
            q["revenue"] += 1e9
        altered["claims"][0]["stated_point"] = 1.0
        attempt = self.results["NVDA"][0][1]["attempt"]
        again = overlay.rederive(self.chain.state, PROFILES_BY_SYMBOL["NVDA"], altered, attempt, allow_replay=True,
                                 baseline=self.chain.curated()["NVDA"])
        self.assertEqual(verify.canonical_json(again["record"]), verify.canonical_json(attempt["record"]))

    # ------------------------------------------------------------------ the release-check gate (Astra A1-r2 N1/N2)

    def test_gate_applies_to_the_curated_baseline_without_any_state(self):
        # 2025-12-17: MU's results filing is listed for its baseline reference -> suspended although no generation exists
        self.assertEqual((self.bootstrap_gated["MU"]["mode"], self.bootstrap_gated["MU"]["reason"]), ("SUSPENDED", "RECEIPT_RESULTS_PUBLISHED"))
        self.assertIsNone(self.bootstrap_gated["MU"]["record"])

    def test_complete_successor_receipt_makes_the_automatic_record_usable(self):
        """MU FQ4-26 successor: its own check the next day reads SEC, wire and IR completely; the same-day 8-K and the
        wire copy are the consumed event, the IR copy is its reference title -> usable."""
        state = self.mu_gated["MU"]
        self.assertEqual((state["mode"], state["reason"]), ("AUTO_VERIFIED", None))
        self.assertEqual(state["record"]["claims"][0]["stated_point"], 50.0e9)
        rows = json.loads(self.chain.receipts.read_text(encoding="utf-8"))["issuers"]["MU"]
        own = [r for r in rows if r["guidance_document_id"] == state["record"]["claims"][0]["document_id"]]
        self.assertTrue(own and own[-1]["status"] == "REVIEW_REQUIRED")  # the checker alone would suspend it
        self.assertTrue(all(c["status"] == "OK" and c["complete"] for c in own[-1]["channels"]))

    def test_unaccounted_same_day_item_keeps_the_issuer_suspended(self):
        self.assertEqual(self.day_after["issuers"]["NVDA"], {"action": "WAITING", "reason": "EVENT_UNRESOLVED"})
        self.assertEqual((self.day_after_state["NVDA"]["mode"], self.day_after_state["NVDA"]["record"]), ("WAITING", None))
        self.assertEqual(self.day_after_state["NVDA"]["effective"]["claims"][0]["stated_point"], 108.0e9)  # kept for checking only
        later = self.day_after_state["NVDA"]["attempt"]["event"]["later_documents"]
        self.assertTrue(any(d["label"].startswith("AWS and NVIDIA to Deliver 2 Million") for d in later), later)
        self.assertEqual(self.day_after_gated["NVDA"]["mode"], "WAITING")

    def test_gate_uses_the_strict_receipt_validation(self):
        record = self.mu_gated["MU"]["record"]
        rows = json.loads(self.chain.receipts.read_text(encoding="utf-8"))["issuers"]["MU"]
        newest = copy.deepcopy(next(r for r in rows if r["checked_at"] == "2026-06-27T12:00:00Z"))
        producer = self.mu_gated["MU"]["attempt"]
        self.assertIsNone(overlay.receipt_gate({"issuers": {"MU": [newest]}}, "MU", record, "2026-06-27T13:00:00Z", producer))
        partial = dict(newest, channels=newest["channels"][:1])
        self.assertIsNotNone(overlay.receipt_gate({"issuers": {"MU": [partial]}}, "MU", record, "2026-06-27T13:00:00Z", producer))
        tampered = dict(newest, later_documents=[])  # digest no longer matches
        self.assertEqual(overlay.receipt_gate({"issuers": {"MU": [tampered]}}, "MU", record, "2026-06-27T13:00:00Z", producer), "RECEIPT_DIGEST_MISMATCH")
        self.assertEqual(overlay.receipt_gate({"issuers": {"MU": [newest]}}, "MU", record, "2026-06-29T13:00:00Z", producer), "RECEIPT_RECEIPT_AGE_EXCEEDED")

    def test_detected_items_are_never_cleared_by_a_later_omission(self):
        record = self.mu_gated["MU"]["record"]
        producer = self.mu_gated["MU"]["attempt"]
        rows = json.loads(self.chain.receipts.read_text(encoding="utf-8"))["issuers"]["MU"]
        newest = next(r for r in rows if r["checked_at"] == "2026-06-27T12:00:00Z")
        earlier = dict(copy.deepcopy(newest), checked_at="2026-06-27T11:00:00Z")
        earlier["later_documents"].append({"channel": "SEC_SUBMISSIONS", "date": "2026-06-26", "id": "0000723125-26-999999",
                                           "label": "8-K items 2.02,9.01", "disposition": "RESULTS_RELEASE"})
        self.assertEqual(overlay.receipt_gate({"issuers": {"MU": [earlier, newest]}}, "MU", record, "2026-06-27T13:00:00Z", producer),
                         "RECEIPT_RESULTS_PUBLISHED")

    def test_idempotent_second_run_writes_nothing(self):
        self.assertEqual(self.idle["issuers"]["NVDA"], {"action": "WAITING", "reason": "EVENT_UNRESOLVED"})
        self.assertNotIn("generation_id", self.idle)
        self.assertEqual(sorted(p.name for p in (self.chain.state / "generations").iterdir()), self.idle_before)

    def test_historical_cutoff_selects_the_generation_of_that_time(self):
        state = self.chain.resolve("2026-05-21T12:00:00Z")
        self.assertEqual(state["NVDA"]["record"]["claims"][0]["stated_point"], 91.0e9)
        state = self.chain.resolve("2025-12-01T00:00:00Z")
        self.assertEqual(state["NVDA"]["mode"], "CURATED")
        self.assertEqual(state["NVDA"]["record"]["claims"][0]["stated_point"], 65.0e9)

    # ------------------------------------------------------------------ admission against tampering (R1/R8/R9, N3/N7/N8)

    def _copy_state(self) -> Path:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        shutil.copytree(self.snapshot, tmp / "state")
        return tmp / "state"

    def _resolve(self, state: Path, cutoff: str = "2026-08-27T12:00:00Z", profiles: bytes | None = None) -> dict:
        return overlay.resolve_issuers(state, cutoff, profiles or PROFILES.read_bytes(), self.chain.registry.read_bytes(),
                                       self.chain.approval.read_bytes(), self.chain.curated(), allow_replay=True)

    def _rewrite_current(self, state: Path, mutate) -> None:
        pointer = json.loads((state / "current.json").read_text(encoding="utf-8"))
        path = state / "generations" / f"{pointer['generation_id']}.json"
        gen = json.loads(path.read_text(encoding="utf-8"))
        mutate(gen)
        data = json.dumps(gen, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8")
        path.write_bytes(data)
        pointer["sha256"] = hashlib.sha256(data).hexdigest()
        (state / "current.json").write_text(json.dumps(pointer), encoding="utf-8")

    @staticmethod
    def _last_verified(gen, sym):
        """The newest verified attempt among the issuer's open attempts (the chains are shorter than a segment)."""
        return next(a for a in reversed(gen["issuers"][sym]["open"]) if a["outcome"] == "VERIFIED")

    def test_rehashed_false_record_is_not_admitted(self):
        state = self._copy_state()

        def forge(gen):
            attempt = self._last_verified(gen, "NVDA")
            attempt["record"]["claims"][0].update(stated_point=115e9, low=112.7e9, high=117.3e9)
            attempt["record_sha256"] = overlay.record_sha256(attempt["record"])
        self._rewrite_current(state, forge)
        got = self._resolve(state)
        self.assertEqual((got["NVDA"]["mode"], got["NVDA"]["reason"], got["NVDA"]["record"]), ("BLOCKED", "APPROVAL_BINDING", None))
        self.assertEqual(got["MU"]["mode"], "AUTO_VERIFIED")  # an unrelated issuer is unaffected

    def test_forged_event_identities_are_not_admitted(self):
        """A consumed IR id or a moved filing date, rehashed into the state, does not survive re-derivation."""
        for mutate in (lambda a: a["event"]["ir_item"].update(id="https://investor.nvidia.com/news/press-release-details/2026/Withdrawal/default.aspx"),
                       lambda a: (a["event"].update(filed="2099-01-01"), a["event"]["ir_item"].update(date="2099-01-01")),
                       lambda a: a["event"].update(accession="0001045810-26-000069")):
            state = self._copy_state()

            def forge(gen, mutate=mutate):
                mutate(self._last_verified(gen, "NVDA"))
            self._rewrite_current(state, forge)
            got = self._resolve(state)
            self.assertEqual((got["NVDA"]["mode"], got["NVDA"]["record"]), ("BLOCKED", None))

    def test_rehashed_capture_with_an_unsupported_transformation_is_not_admitted(self):
        """R5-1 through stored admission: a periodic capture whose transformation namespace is unsupported, stored
        and re-bound into the attempt with recomputed digests, does not re-derive."""
        def swap(gen):
            attempt = self._last_verified(gen, "MU")
            key = next(k for k in attempt["captures"] if k == "0000723125-26-000015")
            old = overlay.load_capture(state, attempt["captures"][key])
            raw = mutate(old["raw"])
            self.assertNotEqual(raw, old["raw"])
            attempt["captures"][key] = overlay.store_capture(state, raw, {k: old[k] for k in ("url", "retrieved_at", "role")})
        transform = b'xmlns:ixt="http://www.xbrl.org/inlineXBRL/transformation/2020-02-12"'
        forged = (b'xmlns:XMLNS="urn:synthetic:attributes" XMLNS:ixt="urn:synthetic:unsupported" '
                  b"data-note=' xmlns:ixt=\"http://www.xbrl.org/inlineXBRL/transformation/2020-02-12\"'")
        for mutate in (lambda raw: raw.replace(transform, b'xmlns:ixt="urn:synthetic:unsupported-transform"'),
                       lambda raw: raw.replace(b'format="ixt:', b'format="IXT:'),
                       lambda raw: raw.replace(transform, forged, 1),
                       lambda raw: raw.replace(b'<xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>',
                                               b'<xbrli:measure>iso4217:USD</xbrli:measure><xbrli:unit id="usd"></xbrli:unit>', 1),
                       lambda raw: re.sub(rb"(<xbrli:startDate>[0-9-]+</xbrli:startDate>)", rb"\1<xbrli:startDate>1900-01-01</xbrli:startDate>", raw)):
            state = self._copy_state()
            self._rewrite_current(state, swap)
            got = self._resolve(state)
            self.assertEqual((got["MU"]["mode"], got["MU"]["reason"], got["MU"]["record"]), ("BLOCKED", "APPROVAL_BINDING", None))

    def test_malformed_nested_state_blocks_only_that_issuer(self):
        state = self._copy_state()
        self._rewrite_current(state, lambda gen: self._last_verified(gen, "NVDA").update(event=None))
        got = self._resolve(state)
        self.assertEqual((got["NVDA"]["mode"], got["NVDA"]["reason"]), ("BLOCKED", "STATE_CORRUPT"))
        self.assertEqual(got["MU"]["mode"], "AUTO_VERIFIED")

    def test_changed_capture_bytes_block(self):
        state = self._copy_state()
        attempt = self._resolve(state)["NVDA"]["attempt"]
        path = overlay.capture_path(state, attempt["captures"]["exhibit"])
        path.write_bytes(path.read_bytes().replace(b"108.0 billion", b"115.0 billion"))
        got = self._resolve(state)
        self.assertEqual((got["NVDA"]["mode"], got["NVDA"]["reason"]), ("BLOCKED", "APPROVAL_BINDING"))

    def test_missing_capture_blocks(self):
        state = self._copy_state()
        attempt = self._resolve(state)["MU"]["attempt"]
        overlay.capture_path(state, attempt["captures"]["exhibit"]).unlink()
        self.assertEqual(self._resolve(state)["MU"]["mode"], "BLOCKED")

    def test_changed_policy_code_or_baseline_identity_blocks_until_reverified(self):
        profiles = json.loads(PROFILES.read_text(encoding="utf-8"))
        profiles["policy_id"] = "ORDERS-V3-AUTOUPDATE-01-changed"
        got = self._resolve(self.snapshot, profiles=json.dumps(profiles).encode("utf-8"))
        self.assertEqual((got["NVDA"]["mode"], got["NVDA"]["reason"]), ("BLOCKED", "APPROVAL_BINDING"))
        original = overlay.implementation_sha256
        overlay.implementation_sha256 = lambda: "0" * 64  # a changed installed verifier/overlay byte
        try:
            self.assertEqual(self._resolve(self.snapshot)["MU"]["mode"], "BLOCKED")
        finally:
            overlay.implementation_sha256 = original

    def test_updater_reverifies_after_an_identity_change(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        chain = Chain(tmp)
        shutil.copytree(self.snapshot, chain.state)
        shutil.copyfile(self.chain.receipts, chain.receipts)
        approval = json.loads(chain.approval.read_text(encoding="utf-8"))
        chain.approval.write_text(json.dumps(dict(approval, revision=2)), encoding="utf-8")  # a new baseline approval
        self.assertEqual(chain.resolve("2026-08-27T12:00:00Z")["NVDA"]["mode"], "BLOCKED")
        summary = chain.update("2026-08-27T12:30:00Z")
        self.assertTrue(summary["reverified"])
        self.assertEqual(chain.resolve("2026-08-27T12:30:00Z")["NVDA"]["mode"], "AUTO_VERIFIED")

    def test_capture_less_verified_attempt_is_blocked_by_reverification(self):
        profiles = verify.validate_profiles(json.loads(PROFILES.read_text(encoding="utf-8")))
        state = self._copy_state()
        gen = overlay.generation_at(state, "2026-08-27T12:00:00Z")
        entries = copy.deepcopy(gen["issuers"])
        self._last_verified({"issuers": entries}, "NVDA")["captures"] = {}
        verified_before = len(entries["NVDA"]["index"]["verified"])
        updater.reverify(state, profiles, self.chain.curated(), entries, {"NVDA", "MU"}, True, "2026-08-27T12:30:00Z")
        self.assertEqual(len(entries["NVDA"]["index"]["verified"]), verified_before - 1)  # no longer the producer
        self.assertIn(("BLOCKED", "APPROVAL_BINDING"), [(a["outcome"], a["reason"]) for a in entries["NVDA"]["open"]])

    def test_unadmitted_state_steers_no_capture(self):
        state = self._copy_state()

        def forge(gen):
            attempt = self._last_verified(gen, "NVDA")
            attempt["record"]["claims"][0]["stated_point"] = 1.0
            attempt["record_sha256"] = overlay.record_sha256(attempt["record"])
        self._rewrite_current(state, forge)

        class Refuse:
            replay = True

            def get(self, url, profile, symbol):
                raise AssertionError(f"fetched {url}")
        summary = updater.run(state, Refuse(), at("2026-08-28T12:00:00Z"), PROFILES, self.chain.registry, self.chain.approval, self.chain.receipts)
        self.assertEqual(summary["issuers"]["NVDA"], {"action": "BLOCKED", "reason": "APPROVAL_BINDING"})

    def test_disabled_profile_is_never_admitted(self):
        profiles = json.loads(PROFILES.read_text(encoding="utf-8"))
        profiles["enabled_symbols"] = ["MU"]
        self.assertNotIn("NVDA", self._resolve(self.snapshot, profiles=json.dumps(profiles).encode("utf-8")))

    def test_broken_predecessor_chain_blocks(self):
        state = self._copy_state()

        def cut(gen):
            self._last_verified(gen, "NVDA")["predecessor_sha256"] = "0" * 64  # the producer's link
        self._rewrite_current(state, cut)
        self.assertEqual(self._resolve(state)["NVDA"]["mode"], "BLOCKED")

    def test_replay_captures_need_explicit_permission(self):
        got = overlay.resolve_issuers(self.snapshot, "2026-08-27T12:00:00Z", PROFILES.read_bytes(), self.chain.registry.read_bytes(),
                                      self.chain.approval.read_bytes(), self.chain.curated())
        self.assertEqual(got["NVDA"]["mode"], "BLOCKED")

    def test_corrupt_or_missing_pointer_fails_closed(self):
        state = self._copy_state()
        (state / "current.json").write_text("{", encoding="utf-8")
        self.assertEqual({(s["mode"], s["reason"]) for s in self._resolve(state).values()}, {("BLOCKED", "STATE_CORRUPT")})
        (state / "current.json").unlink()
        self.assertEqual({s["mode"] for s in self._resolve(state).values()}, {"BLOCKED"})  # generations but no pointer

    def test_unknown_generation_key_fails_closed(self):
        state = self._copy_state()
        self._rewrite_current(state, lambda gen: gen.update(extra=1))
        self.assertEqual(self._resolve(state)["MU"]["reason"], "STATE_CORRUPT")

    def test_interrupted_publication_keeps_the_committed_generation(self):
        state = self._copy_state()
        before = self._resolve(state)["NVDA"]["record"]
        pointer = json.loads((state / "current.json").read_text(encoding="utf-8"))
        (state / "generations" / "20990101T000000Z-000000000000.json").write_text("{}", encoding="utf-8")  # pointer never moved
        self.assertEqual(self._resolve(state)["NVDA"]["record"], before)
        gen = overlay.read_generation(state, pointer["generation_id"], pointer["sha256"])
        with self.assertRaises(overlay.StateError):
            overlay.publish_generation(state, dict(gen, generation_id=pointer["generation_id"]), pointer)  # never overwritten
        with self.assertRaises(overlay.StateError):
            overlay.publish_generation(state, dict(gen, generation_id="20990101T000000Z-111111111111"), None)  # pointer moved


# ------------------------------------------------------------------------------------------------ verifier cases

PROFILES_BY_SYMBOL = verify.validate_profiles(json.loads(PROFILES.read_text(encoding="utf-8")))
DECIDED = "2026-09-29T12:00:00Z"
TITLES = {("NVDA", "2026-08-26"): "NVIDIA Announces Financial Results for Second Quarter Fiscal 2027",
          ("MU", "2026-06-24"): "Micron Technology, Inc. Reports Record Results for the Third Quarter of Fiscal 2026"}


def capture(row: dict, raw: bytes | None = None, **override) -> dict:
    raw = fixture_bytes(row) if raw is None else raw
    cap = {"url": row["url"], "retrieved_at": row["retrieved_at"], "bytes": len(raw), "raw_sha256": verify.sha256(raw),
           "sha256": verify.sha256(verify.canonical_bytes(raw)), "raw": raw, "role": row["role"]}
    cap.update(override)
    return cap


def event_for(sym: str, filed: str, release_raw: bytes | None = None, drop: tuple = ()):
    """The verifier input of a real release from the fixtures, as the updater's capture step assembles it."""
    rel = exhibit_row(sym, filed)
    acc = rel["accession"]
    captures = {"submissions": capture(row_of(sym, "SEC_SUBMISSIONS")), "index": capture(row_of(sym, "SEC_INDEX", accession=acc)),
                "exhibit": capture(rel, release_raw)}
    names = verify.package_names(verify.parse_index(captures["index"]["raw"]))
    for r in INVENTORY:
        if r["issuer"] == sym and r["role"] == "FILING_DOCUMENT" and r.get("accession") == acc and r["name"] in names and r["url"] != rel["url"]:
            captures[f"package:{r['name']}"] = capture(r)
    periodic = {}
    for r in INVENTORY:
        if r["issuer"] == sym and r["role"] == "PERIODIC_FILING" and r["report_date"] not in drop:
            captures[r["accession"]] = capture(r)
            periodic[r["report_date"]] = r["accession"]
    tenk = max((r for r in INVENTORY if r["issuer"] == sym and r["role"] == "PERIODIC_FILING" and r["form"] == "10-K"), key=lambda r: r["filed"])
    ir, wire = row_of(sym, "IR_RELEASE_PAGE", filed=filed), row_of(sym, "WIRE_RELEASE_PAGE", filed=filed)
    captures["ir_copy"], captures["wire_copy"] = capture(ir), capture(wire)
    title = TITLES[(sym, filed)]
    event = {"accession": acc, "filed": filed, "periodic": periodic, "calendar": tenk["accession"], "allocation_sources": [],
             "ir_item": {"id": ir["url"], "title": title, "date": filed}, "wire_item": {"id": wire["url"], "title": title, "date": filed},
             "later_documents": []}
    return event, captures


BASE_CHANNELS = {r["symbol"]: r["release_channels"] for r in json.loads((FIXTURES / "bootstrap-registry.json").read_text(encoding="utf-8"))["issuers"]}
PRED = {"NVDA": {"reported_quarters": [{"end": "2026-04-26"}], "release_channels": BASE_CHANNELS["NVDA"]},
        "MU": {"reported_quarters": [{"end": "2026-02-26"}], "release_channels": BASE_CHANNELS["MU"]}}
FILED = {"NVDA": "2026-08-26", "MU": "2026-06-24"}


def release(sym: str) -> bytes:
    return fixture_bytes(exhibit_row(sym, FILED[sym]))


class VerifierTests(unittest.TestCase):
    def build(self, sym="NVDA", event=None, pred=None, decided=DECIDED):
        if event is None:
            event = event_for(sym, FILED[sym])
        return verify.build_successor(PROFILES_BY_SYMBOL[sym], pred or PRED[sym], event[0], event[1], decided)

    def outcome(self, result):
        return (result["outcome"], result["reason"])

    def with_release(self, sym, old: bytes, new: bytes):
        raw = release(sym)
        self.assertIn(old, raw)
        return event_for(sym, FILED[sym], raw.replace(old, new, 1))

    def with_capture(self, sym, key, mutate):
        event, caps = event_for(sym, FILED[sym])
        old = caps[key]["raw"]
        raw = mutate(old)
        self.assertNotEqual(raw, old)
        caps[key] = dict(caps[key], raw=raw, bytes=len(raw), raw_sha256=verify.sha256(raw), sha256=verify.sha256(verify.canonical_bytes(raw)))
        return event, caps

    def test_nominal(self):
        for sym in ("NVDA", "MU"):
            self.assertEqual(self.outcome(self.build(sym)), ("VERIFIED", None))

    # transitions (R6, N5)
    def test_real_withdrawal_releases_are_detected(self):
        for sym in ("OLED", "CMG"):
            found = verify.detect_transitions(verify.parse_document(fixture_bytes(row_of(sym, "WITHDRAWAL_CASE"))))
            self.assertIn("WITHDRAWAL", [r for r, _ in found], sym)

    def test_real_packages_and_copies_have_no_transition(self):
        for row in INVENTORY:
            if row["issuer"] in ("NVDA", "MU") and row["role"] in ("FILING_DOCUMENT", "IR_RELEASE_PAGE", "WIRE_RELEASE_PAGE"):
                self.assertEqual(verify.detect_transitions(verify.parse_document(fixture_bytes(row))), [], row["url"])

    def test_withdrawal_restatement_and_revision_wordings_block(self):
        for text, reason in (
                (b"We are withdrawing our previous fiscal 2027 guidance. We have no obligation to update forward-looking statements.", "WITHDRAWAL"),
                (b"We withdrew our previous fiscal 2027 revenue guidance.", "WITHDRAWAL"),
                (b"Our fiscal 2027 revenue guidance has been withdrawn.", "WITHDRAWAL"),
                (b"Our previously issued financial statements should no longer be relied upon.", "RESTATEMENT"),
                (b"We are restating our revenue for the second quarter of fiscal 2027.", "RESTATEMENT"),
                (b"We are lowering our previously issued fiscal 2027 outlook.", "REVISION")):
            event = self.with_release("NVDA", b"</body>", b"<p>" + text + b"</p></body>")
            self.assertEqual(self.outcome(self.build("NVDA", event)), ("BLOCKED", reason), text)

    def test_transition_in_another_package_document_blocks(self):
        event = self.with_capture("NVDA", "package:q2fy27cfocommentary.htm",
                                  lambda raw: raw.replace(b"</body>", b"<p>Our fiscal 2027 outlook has been suspended.</p></body>", 1))
        self.assertEqual(self.outcome(self.build("NVDA", event)), ("BLOCKED", "WITHDRAWAL"))

    def test_missing_package_document_blocks(self):
        event, caps = event_for("NVDA", FILED["NVDA"])
        del caps["package:q2fy27cfocommentary.htm"]
        self.assertEqual(self.outcome(self.build("NVDA", (event, caps))), ("BLOCKED", "INPUT_MISSING"))

    # guidance selection (R6)
    def test_second_revenue_outlook_blocks(self):
        event = self.with_release("NVDA", b"</body>", b"<p>Revenue is expected to be $125.0 billion, plus or minus 2%.</p></body>")
        self.assertEqual(self.outcome(self.build("NVDA", event)), ("BLOCKED", "AMBIGUOUS"))

    def test_outlook_not_under_its_heading_blocks(self):
        event = self.with_release("NVDA", b">Outlook<", b">See separate document<")
        self.assertEqual(self.outcome(self.build("NVDA", event)), ("BLOCKED", "NO_MATCH"))

    def test_guided_period_must_follow_the_reported_quarter(self):
        event = self.with_release("NVDA", b"outlook for the third quarter of fiscal 2027", b"outlook for the second quarter of fiscal 2027")
        self.assertEqual(self.outcome(self.build("NVDA", event, pred={"reported_quarters": [{"end": "2026-01-25"}], "release_channels": BASE_CHANNELS["NVDA"]})),
                         ("BLOCKED", "PERIOD_MISMATCH"))
        event = self.with_release("NVDA", b"outlook for the third quarter of fiscal 2027", b"outlook for the fourth quarter of fiscal 2027")
        self.assertEqual(self.outcome(self.build("NVDA", event))[0], "BLOCKED")

    def test_unit_error_blocks(self):
        event = self.with_release("NVDA", b"$108.0 billion, plus or minus 2%", b"$108.0 million, plus or minus 2%")
        self.assertEqual(self.outcome(self.build("NVDA", event)), ("BLOCKED", "UNIT_MISMATCH"))

    def test_mu_conflicting_bands_or_columns_block(self):
        band = b"$50.0 billion &#177; $1.0 billion"
        positions = [m.start() for m in re.finditer(re.escape(band), release("MU"))]
        self.assertEqual(len(positions), 4)  # GAAP and non-GAAP columns of the summary and the reconciliation tables
        for index in (1, 3):
            at_ = positions[index]
            raw = release("MU")
            conflicting = raw[:at_] + b"$50.0 billion &#177; $4.0 billion" + raw[at_ + len(band):]
            self.assertEqual(self.outcome(self.build("MU", event_for("MU", FILED["MU"], conflicting))), ("BLOCKED", "SOURCE_DISAGREEMENT"))

    # actuals (R4, N4)
    def test_release_row_must_equal_the_filing(self):
        event = event_for("NVDA", FILED["NVDA"], release("NVDA").replace(b"$96,221", b"$96,222"))
        self.assertEqual(self.outcome(self.build("NVDA", event)), ("BLOCKED", "SOURCE_DISAGREEMENT"))

    def latest_10q(self, sym):
        return {"NVDA": "0001045810-26-000075", "MU": "0000723125-26-000015"}[sym]

    def test_shifted_fact_duration_is_not_selected(self):
        event = self.with_capture("NVDA", self.latest_10q("NVDA"), lambda raw: raw.replace(
            b"<xbrli:startDate>2026-04-27</xbrli:startDate>", b"<xbrli:startDate>2026-05-01</xbrli:startDate>"))
        self.assertEqual(self.outcome(self.build("NVDA", event)), ("BLOCKED", "ACTUAL_NOT_FOUND"))

    def test_wrong_currency_unit_blocks(self):
        event = self.with_capture("NVDA", self.latest_10q("NVDA"), lambda raw: raw.replace(b"iso4217:USD<", b"iso4217:EUR<"))
        self.assertEqual(self.outcome(self.build("NVDA", event))[0], "BLOCKED")

    def test_dimensional_scenario_context_is_not_company_wide(self):
        def add_scenario(raw):
            return re.sub(rb'(<xbrli:context id="c-3">.*?</xbrli:entity>)',
                          rb'\1<xbrli:scenario><xbrldi:explicitMember dimension="us-gaap:StatementBusinessSegmentsAxis">nvda:ComputeAndNetworkingMember</xbrldi:explicitMember></xbrli:scenario>',
                          raw, count=1, flags=re.S)
        event = self.with_capture("NVDA", self.latest_10q("NVDA"), add_scenario)
        self.assertEqual(self.outcome(self.build("NVDA", event)), ("BLOCKED", "ACTUAL_NOT_FOUND"))

    def test_conflicting_equivalent_concept_blocks(self):
        def add_fact(raw):
            fact = re.search(rb'<ix:nonFraction[^>]*name="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"[^>]*>41,456</ix:nonFraction>', raw).group(0)
            other = fact.replace(b"RevenueFromContractWithCustomerExcludingAssessedTax", b"Revenues").replace(b"41,456", b"99,999").replace(b'id="', b'id="x-')
            return raw.replace(fact, fact + other, 1)
        event = self.with_capture("MU", self.latest_10q("MU"), add_fact)
        self.assertEqual(self.outcome(self.build("MU", event)), ("BLOCKED", "SOURCE_DISAGREEMENT"))

    def test_conflicting_duplicate_fact_blocks(self):
        def dup(raw):
            fact = re.search(rb'<ix:nonFraction[^>]*contextRef="c-3"[^>]*name="us-gaap:Revenues"[^>]*>96,221</ix:nonFraction>', raw).group(0)
            return raw.replace(fact, fact + fact.replace(b"96,221", b"96,222").replace(b'id="', b'id="dup-'), 1)
        self.assertEqual(self.outcome(self.build("NVDA", self.with_capture("NVDA", self.latest_10q("NVDA"), dup))), ("BLOCKED", "SOURCE_DISAGREEMENT"))

    def test_filing_of_another_quarter_is_refused(self):
        event, caps = event_for("NVDA", FILED["NVDA"])
        event["periodic"]["2026-07-26"] = event["periodic"]["2026-04-26"]
        self.assertEqual(self.outcome(self.build("NVDA", (event, caps))), ("BLOCKED", "SOURCE_DISAGREEMENT"))

    def test_filing_of_another_issuer_is_refused(self):
        event, caps = event_for("NVDA", FILED["NVDA"])
        acc = event["periodic"]["2026-07-26"]
        caps[acc] = dict(caps[acc], url=caps[acc]["url"].replace("/1045810/", "/723125/"))
        self.assertEqual(self.outcome(self.build("NVDA", (event, caps))), ("BLOCKED", "APPROVAL_BINDING"))

    def test_missing_quarter_filing_waits(self):
        self.assertEqual(self.outcome(self.build("NVDA", event_for("NVDA", FILED["NVDA"], drop=("2026-07-26",)))),
                         ("WAITING", "WAITING_PERIODIC_FILING"))

    def test_capture_after_decision_is_refused(self):
        event, caps = event_for("NVDA", FILED["NVDA"])
        caps["exhibit"] = dict(caps["exhibit"], retrieved_at="2026-09-30T00:00:00Z")
        self.assertEqual(self.outcome(self.build("NVDA", (event, caps))), ("BLOCKED", "APPROVAL_BINDING"))
        self.assertEqual(self.outcome(self.build("NVDA", decided="2026-08-26T23:00:00Z"))[0], "BLOCKED")

    # event identity (N3)
    def test_event_date_must_be_the_edgar_filing_date(self):
        event, caps = event_for("NVDA", FILED["NVDA"])
        event["filed"] = "2099-01-01"
        event["ir_item"]["date"] = "2099-01-01"
        self.assertEqual(self.outcome(self.build("NVDA", (event, caps))), ("BLOCKED", "APPROVAL_BINDING"))

    def test_non_results_filing_is_not_an_event(self):
        event, caps = event_for("NVDA", FILED["NVDA"])
        event["accession"] = "0001045810-26-000069"  # 2026-08-17 8-K items 1.01, 2.03, 7.01
        self.assertEqual(self.outcome(self.build("NVDA", (event, caps))), ("BLOCKED", "EVENT_UNRESOLVED"))

    def test_ir_copy_must_be_the_same_release(self):
        event, caps = event_for("NVDA", FILED["NVDA"])
        event["ir_item"]["id"] = "https://investor.nvidia.com/news/press-release-details/2026/Other/default.aspx"
        self.assertEqual(self.outcome(self.build("NVDA", (event, caps))), ("BLOCKED", "INCOMPLETE_EVENT_COVERAGE"))
        event, caps = event_for("NVDA", FILED["NVDA"])
        event["ir_item"]["title"] = "NVIDIA Announces Financial Results for First Quarter Fiscal 2027"
        self.assertEqual(self.outcome(self.build("NVDA", (event, caps))), ("BLOCKED", "INCOMPLETE_EVENT_COVERAGE"))
        event, caps = self.with_capture("NVDA", "ir_copy", lambda raw: raw.replace(b"108.0 billion", b"109.0 billion"))
        self.assertEqual(self.outcome(self.build("NVDA", (event, caps))), ("BLOCKED", "INCOMPLETE_EVENT_COVERAGE"))
        event, caps = event_for("NVDA", FILED["NVDA"])
        event["ir_item"] = None
        self.assertEqual(self.outcome(self.build("NVDA", (event, caps))), ("WAITING", "INCOMPLETE_EVENT_COVERAGE"))

    def test_unproven_wire_copy_is_not_consumed(self):
        event, caps = self.with_capture("MU", "wire_copy", lambda raw: raw.replace(b"50.0 billion", b"51.0 billion"))
        result = self.build("MU", (event, caps))
        self.assertEqual(self.outcome(result), ("VERIFIED", None))
        routing = next(d for d in result["decisions"] if d["kind"] == "ROUTING")["operands"]
        self.assertIsNone(routing["wire_item"])
        self.assertNotIn("WIRE_PRESS_RELEASES", {c["channel"] for c in routing["consumed"]})

    # copies are whole publications (R3-2)
    def test_copy_with_a_transition_or_competing_outlook_blocks(self):
        for key in ("ir_copy", "wire_copy"):
            event = self.with_capture("MU", key, lambda raw: raw.replace(b"</body>", b"<p>Our fiscal 2026 revenue guidance has been withdrawn.</p></body>", 1))
            self.assertEqual(self.outcome(self.build("MU", event)), ("BLOCKED", "WITHDRAWAL"), key)
        event = self.with_capture("NVDA", "ir_copy", lambda raw: raw.replace(
            b"</body>", b"<p>Revenue is expected to be $120.0 billion, plus or minus 2%.</p></body>", 1))
        self.assertEqual(self.outcome(self.build("NVDA", event)), ("BLOCKED", "SOURCE_DISAGREEMENT"))
        # a recognised outlook table with an unsupported or conflicting value, beside the original one (R4-2)
        for value in (b"$45.0 to $47.0 billion", b"$45.0 billion &#177; $1.0 billion", b"approximately $46 billion"):
            table = (b"<table><tr><td>FQ4-26</td><td>GAAP Outlook</td><td>Non-GAAP Outlook</td></tr><tr><td>Revenue</td><td>" + value
                     + b"</td><td>" + value + b"</td></tr></table>")
            for key in ("ir_copy", "wire_copy"):
                event = self.with_capture("MU", key, lambda raw, table=table: raw.replace(b"</body>", table + b"</body>", 1))
                self.assertEqual(self.outcome(self.build("MU", event)), ("BLOCKED", "SOURCE_DISAGREEMENT"), (key, value))

    # namespaces and the Q4 operands (R3-3, R3-4)
    def test_conflicting_equivalent_concept_in_the_nine_month_operand_blocks(self):
        def add_fact(raw):
            ctx = re.search(rb'<xbrli:context id="([^"]+)"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000723125</xbrli:identifier>'
                            rb'</xbrli:entity><xbrli:period><xbrli:startDate>2024-08-30</xbrli:startDate><xbrli:endDate>2025-05-29</xbrli:endDate>', raw).group(1)
            fact = re.search(rb'<ix:nonFraction[^>]*contextRef="' + re.escape(ctx) + rb'"[^>]*name="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"[^>]*>26,063</ix:nonFraction>', raw).group(0)
            other = fact.replace(b"RevenueFromContractWithCustomerExcludingAssessedTax", b"Revenues").replace(b"26,063", b"99,999").replace(b'id="', b'id="x-')
            return raw.replace(fact, fact + other, 1)
        q3 = row_of("MU", "PERIODIC_FILING", report_date="2025-05-29")["accession"]
        self.assertEqual(self.outcome(self.build("MU", self.with_capture("MU", q3, add_fact))), ("BLOCKED", "SOURCE_DISAGREEMENT"))

    def test_namespaces_are_resolved_not_spelled(self):
        acc = self.latest_10q("NVDA")
        taxonomy = self.with_capture("NVDA", acc, lambda raw: re.sub(rb'xmlns:us-gaap="[^"]+"', b'xmlns:us-gaap="urn:synthetic:unreviewed-taxonomy"', raw))
        self.assertEqual(self.build("NVDA", taxonomy)["outcome"], "BLOCKED")
        currency = self.with_capture("NVDA", acc, lambda raw: re.sub(rb'xmlns:iso4217="[^"]+"', b'xmlns:iso4217="urn:synthetic:unreviewed-taxonomy"', raw))
        self.assertEqual(self.outcome(self.build("NVDA", currency)), ("BLOCKED", "UNIT_MISMATCH"))
        rebound = self.with_capture("NVDA", acc, lambda raw: raw.replace(b"<body", b'<body xmlns:us-gaap="urn:synthetic:other"', 1))
        self.assertEqual(self.outcome(self.build("NVDA", rebound)), ("BLOCKED", "UNSUPPORTED_TEMPLATE"))
        alias = self.with_capture("NVDA", acc, lambda raw: raw.replace(b"xmlns:us-gaap=", b"xmlns:usgaap=").replace(b"us-gaap:", b"usgaap:"))
        self.assertEqual(self.outcome(self.build("NVDA", alias)), ("VERIFIED", None))  # a legitimate alias prefix
        # a declaration on an unrelated sibling element does not bind the facts' or measures' prefix (R4-3)
        for prefix in (b"us-gaap", b"iso4217", b"dei"):
            def move(raw, prefix=prefix):
                decl = re.search(rb'\sxmlns:' + prefix + rb'="[^"]+"', raw).group(0)
                return raw.replace(decl, b"", 1).replace(b"</body>", b"<div" + decl + b"></div></body>", 1)
            self.assertEqual(self.build("NVDA", self.with_capture("NVDA", acc, move))["outcome"], "BLOCKED", prefix)
        # the numeric transformation is a namespaced name too (R5-1)
        transform = rb'xmlns:ixt="http://www.xbrl.org/inlineXBRL/transformation/2020-02-12"'
        for label, mutate in (
                ("wrong registry", lambda raw: raw.replace(transform, b'xmlns:ixt="urn:synthetic:unsupported-transform"')),
                ("no declaration", lambda raw: raw.replace(b" " + transform, b"")),
                ("sibling only", lambda raw: raw.replace(b" " + transform, b"").replace(b"</body>", b"<div " + transform + b"></div></body>", 1)),
                ("rebound locally", lambda raw: raw.replace(b"<ix:nonFraction ", b'<ix:nonFraction xmlns:ixt="urn:synthetic:other" ', 1)),
                ("unsupported local name", lambda raw: re.sub(rb'(<ix:nonFraction[^>]*contextRef="c-3"[^>]*name="us-gaap:Revenues"[^>]*format=")ixt:num-dot-decimal"',
                                                                rb'\1ixt:num-comma-decimal"', raw, count=1))):
            result = self.build("NVDA", self.with_capture("NVDA", acc, mutate))
            self.assertEqual(result["outcome"], "BLOCKED", label)
        # prefixes are case-sensitive (R6-1): an upper- or mixed-case reference or declaration binds nothing else
        for label, mutate in (
                ("reference IXT, declaration ixt", lambda raw: re.sub(rb'(<ix:nonFraction[^>]*contextRef="c-3"[^>]*name="us-gaap:Revenues"[^>]*format=")ixt:',
                                                                        rb'\1IXT:', raw, count=1)),
                ("reference ixt, declaration IXT", lambda raw: raw.replace(b"xmlns:ixt=", b"xmlns:IXT=")),
                ("mixed-case reference", lambda raw: raw.replace(b'format="ixt:', b'format="Ixt:')),
                ("case-only prefixes bound apart", lambda raw: raw.replace(transform, transform + b' xmlns:IXT="urn:synthetic:other"', 1)
                 .replace(b'format="ixt:', b'format="IXT:')),
                ("uppercase structure prefix", lambda raw: raw.replace(b"<ix:nonFraction ", b"<IX:nonFraction ").replace(b"</ix:nonFraction>", b"</IX:nonFraction>"))):
            self.assertEqual(self.build("NVDA", self.with_capture("NVDA", acc, mutate))["outcome"], "BLOCKED", label)
        self.assertEqual(self.build("MU", self.with_capture("MU", tenk_mu := row_of("MU", "PERIODIC_FILING", form="10-K")["accession"],
                                                           lambda raw: raw.replace(b'format="ixt:', b'format="IXT:')))["outcome"], "BLOCKED")
        self.assertTrue(tenk_mu)
        # namespace-looking text in another attribute and XMLNS-prefixed attributes declare nothing (R7-1)
        forged = (b'xmlns:XMLNS="urn:synthetic:attributes" XMLNS:ixt="urn:synthetic:unsupported" '
                  b"data-note=' xmlns:ixt=\"http://www.xbrl.org/inlineXBRL/transformation/2020-02-12\"'")
        self.assertEqual(self.build("NVDA", self.with_capture("NVDA", acc, lambda raw: raw.replace(transform, forged, 1)))["outcome"], "BLOCKED")
        self.assertEqual(self.build("MU", self.with_capture("MU", self.latest_10q("MU"), lambda raw: raw.replace(transform, forged, 1)))["outcome"], "BLOCKED")
        self.assertEqual(self.build("MU", self.with_capture("MU", row_of("MU", "PERIODIC_FILING", form="10-K")["accession"],
                                                           lambda raw: raw.replace(transform, forged, 1)))["outcome"], "BLOCKED")
        # EDGAR's injected fragment is removed exactly once and nothing else: a second copy or any other non-XML markup
        # makes the filing unreadable as inline XBRL
        injected = re.search(rb'<script >bazadebezolkohpepadr="[0-9]+"</script><script [^>]*defer></script>', fixture_bytes(row_of("NVDA", "PERIODIC_FILING", report_date="2026-07-26"))).group(0)
        for label, mutate in (("second injection", lambda raw: raw.replace(b"</body>", injected + b"</body>", 1)),
                              ("other script", lambda raw: raw.replace(b"</body>", b"<script defer></script></body>", 1))):
            self.assertEqual(self.outcome(self.build("NVDA", self.with_capture("NVDA", acc, mutate))), ("BLOCKED", "UNSUPPORTED_TEMPLATE"), label)
        alias_tr = self.with_capture("NVDA", acc, lambda raw: raw.replace(b"xmlns:ixt=", b"xmlns:tr4=").replace(b'format="ixt:', b'format="tr4:'))
        self.assertEqual(self.outcome(self.build("NVDA", alias_tr)), ("VERIFIED", None))  # a legitimate alias of the registry
        tenk = row_of("MU", "PERIODIC_FILING", form="10-K")["accession"]  # the Q4 longer operand
        self.assertEqual(self.build("MU", self.with_capture("MU", tenk, lambda raw: raw.replace(
            transform, b'xmlns:ixt="urn:synthetic:unsupported-transform"')))["outcome"], "BLOCKED")
        # a structure prefix bound elsewhere for one element is not read as XBRL
        scoped = self.with_capture("NVDA", acc, lambda raw: raw.replace(b"<xbrli:context ", b'<xbrli:context xmlns:xbrli="urn:synthetic:other" ', 1))
        self.assertEqual(self.outcome(self.build("NVDA", scoped)), ("BLOCKED", "UNSUPPORTED_TEMPLATE"))

    # XBRL structure shapes (R8-1, R8-2)
    UNIT = b'<xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>'
    SHAPES = (
        ("measure outside its unit", lambda raw: raw.replace(VerifierTests.UNIT, b'<xbrli:measure>iso4217:USD</xbrli:measure><xbrli:unit id="usd"></xbrli:unit>', 1)),
        ("two measures", lambda raw: raw.replace(VerifierTests.UNIT, b'<xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure>'
                                                                        b'<xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>', 1)),
        ("nested measure", lambda raw: raw.replace(VerifierTests.UNIT, b'<xbrli:unit id="usd"><xbrli:divide><xbrli:unitNumerator>'
                                                                         b'<xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unitNumerator></xbrli:divide></xbrli:unit>', 1)),
        ("second start date", lambda raw: re.sub(rb"(<xbrli:startDate>[0-9-]+</xbrli:startDate>)", rb"\1<xbrli:startDate>1900-01-01</xbrli:startDate>", raw)),
        ("second end date", lambda raw: re.sub(rb"(<xbrli:endDate>[0-9-]+</xbrli:endDate>)", rb"\1<xbrli:endDate>2099-01-01</xbrli:endDate>", raw)),
        ("instant beside the duration", lambda raw: re.sub(rb"(<xbrli:endDate>[0-9-]+</xbrli:endDate>)", rb"\1<xbrli:instant>2026-01-01</xbrli:instant>", raw)),
        ("second period", lambda raw: re.sub(rb"(</xbrli:period>)", rb"\1<xbrli:period><xbrli:instant>2026-01-01</xbrli:instant></xbrli:period>", raw)),
        ("second identifier", lambda raw: re.sub(rb"(</xbrli:identifier>)", rb'\1<xbrli:identifier scheme="http://www.sec.gov/CIK">0000000001</xbrli:identifier>', raw)),
    )

    def test_unit_and_context_shapes_are_strict(self):
        for sym, key in (("NVDA", self.latest_10q("NVDA")), ("MU", self.latest_10q("MU")),
                         ("MU", row_of("MU", "PERIODIC_FILING", form="10-K")["accession"])):
            for label, mutate in self.SHAPES:
                self.assertEqual(self.build(sym, self.with_capture(sym, key, mutate))["outcome"], "BLOCKED", (sym, key, label))
        # positive controls: an aliased instance prefix and an aliased currency prefix read exactly as before
        alias = self.with_capture("NVDA", self.latest_10q("NVDA"), lambda raw: raw.replace(b"xmlns:xbrli=", b"xmlns:inst=")
                                  .replace(b"<xbrli:", b"<inst:").replace(b"</xbrli:", b"</inst:").replace(b"xbrli:shares", b"inst:shares")
                                  .replace(b"xbrli:pure", b"inst:pure"))
        self.assertEqual(self.outcome(self.build("NVDA", alias)), ("VERIFIED", None))
        currency = self.with_capture("MU", self.latest_10q("MU"), lambda raw: raw.replace(b"xmlns:iso4217=", b"xmlns:ccy=").replace(b">iso4217:", b">ccy:"))
        self.assertEqual(self.outcome(self.build("MU", currency)), ("VERIFIED", None))

    def test_malformed_event_is_a_typed_block(self):
        event, caps = event_for("NVDA", FILED["NVDA"])
        event["periodic"] = None
        self.assertEqual(self.build("NVDA", (event, caps))["outcome"], "BLOCKED")

    # calendar (R5)
    def test_calendar_filing_is_required_and_newest(self):
        event, caps = event_for("NVDA", FILED["NVDA"])
        event["calendar"] = None
        self.assertEqual(self.outcome(self.build("NVDA", (event, caps))), ("BLOCKED", "INPUT_MISSING"))

    def test_changed_calendar_rule_blocks(self):
        tenk = row_of("NVDA", "PERIODIC_FILING", form="10-K")["accession"]
        event = self.with_capture("NVDA", tenk, lambda raw: raw.replace(b"ending on the last Sunday in January", b"ending on the last Sunday in February"))
        self.assertEqual(self.outcome(self.build("NVDA", event)), ("BLOCKED", "CALENDAR_RULE_UNPROVEN"))

    def test_unproven_extra_week_waits(self):
        event, caps = event_for("NVDA", FILED["NVDA"])
        statement = b"with the fourth quarter consisting of 14 weeks"
        for key, cap in list(caps.items()):
            if statement in cap["raw"]:
                raw = cap["raw"].replace(statement, b"with the fourth quarter consisting of many weeks")
                caps[key] = dict(cap, raw=raw, bytes=len(raw), raw_sha256=verify.sha256(raw), sha256=verify.sha256(verify.canonical_bytes(raw)))
        self.assertEqual(self.outcome(self.build("NVDA", (event, caps))), ("WAITING", "CALENDAR_ALLOCATION_UNPROVEN"))

    def test_fiscal_calendar_rules(self):
        rule_n, rule_m = "LAST_SUNDAY_OF_JANUARY", "THURSDAY_CLOSEST_TO_AUGUST_31"
        self.assertEqual([verify.year_weeks(rule_n, y) for y in (2026, 2027, 2028)], [52, 53, 52])
        self.assertEqual([verify.year_weeks(rule_m, y) for y in (2025, 2026, 2027)], [52, 53, 52])
        self.assertEqual(verify.fiscal_quarter(rule_n, 2027, 4), (datetime(2026, 10, 26).date(), datetime(2027, 1, 31).date()))
        self.assertEqual(verify.fiscal_quarter(rule_m, 2026, 4), (datetime(2026, 5, 29).date(), datetime(2026, 9, 3).date()))
        for rule in (rule_n, rule_m):
            for fy in (2025, 2026, 2027, 2028):
                spans = [verify.fiscal_quarter(rule, fy, q) for q in (1, 2, 3, 4)]
                for (_, e1), (s2, _) in zip(spans, spans[1:]):
                    self.assertEqual((s2 - e1).days, 1)

    def test_older_release_after_a_newer_predecessor_is_refused(self):
        self.assertEqual(self.outcome(self.build("NVDA", pred={"reported_quarters": [{"end": "2026-07-26"}], "release_channels": BASE_CHANNELS["NVDA"]})),
                         ("BLOCKED", "OUT_OF_ORDER"))

    def test_profiles_are_strict(self):
        for mutate in (lambda d: d["profiles"][0].update(extra=1), lambda d: d["enabled_symbols"].append("AMD"),
                       lambda d: d["profiles"][1]["calendar"].update(label_format="{q}{yy}; import os"),
                       lambda d: d["profiles"][0].update(ir_host="www.sec.gov"),
                       lambda d: d["profiles"][0].update(wire_page_pattern="^https://evil\\.example/.*$"),
                       lambda d: d["profiles"][0]["actuals"].update(measure="iso4217:EUR")):
            data = json.loads(PROFILES.read_text(encoding="utf-8"))
            mutate(data)
            with self.assertRaises(ValueError):
                verify.validate_profiles(data)


# ------------------------------------------------------------------------------------------------ transport (R7, N6)

class FakeResponse:
    def __init__(self, body: bytes = b"x", status=200, ctype="text/html", encoding=None, headers=None):
        self.body, self.status, self.taken = body, status, 0
        self.headers = {"content-type": ctype, **({"content-encoding": encoding} if encoding else {}), **(headers or {})}

    def read(self, n):
        chunk = self.body[self.taken:self.taken + n]
        self.taken += len(chunk)
        return chunk

    def close(self):
        pass


DOC = "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000073/q2fy27pr.htm"
NV = PROFILES_BY_SYMBOL["NVDA"]


class TransportTests(unittest.TestCase):
    def transport(self, script, resolver=lambda host: ["162.159.140.1"]):
        clock = [0.0]
        calls = []

        def connector(host, address, path, headers, timeout):
            calls.append((host, address, path, dict(headers)))
            item = script.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        t = updater.Transport({"User-Agent": "sec-contact-sentinel"}, connector=connector, resolver=resolver,
                              sleep=lambda s: clock.__setitem__(0, clock[0] + s), monotonic=lambda: clock[0])
        t.calls = calls
        return t

    def test_url_rules(self):
        self.assertEqual(updater.url_rule(DOC, NV), "document")
        self.assertEqual(updater.url_rule("https://data.sec.gov/submissions/CIK0001045810.json", NV), "submissions")
        self.assertEqual(updater.url_rule("https://www.nasdaq.com/press-release/nvidia-announces-2026-08-26", NV), "wire_page")
        self.assertEqual(updater.url_rule("https://investor.nvidia.com/news/press-release-details/2026/X-Y/default.aspx", NV), "ir_page")
        for bad in (DOC.replace("https", "http"), DOC.replace("www.sec.gov", "unreviewed.www.sec.gov"),
                    DOC.replace("/1045810/", "/723125/"), DOC + "?x=1", DOC.replace("www.sec.gov", "user@www.sec.gov"),
                    DOC.replace("q2fy27pr.htm", "..%2fx"), "https://162.159.140.1/Archives/edgar/data/1045810/000104581026000073/a.htm",
                    "https://www.sec.gov:8443/Archives/edgar/data/1045810/000104581026000073/a.htm",
                    "https://investors.micron.com/news/press-release/2026/X/default.aspx",
                    "https://www.nasdaq.com/market-activity/x"):
            with self.assertRaises(updater.NetworkBlocked, msg=bad):
                updater.url_rule(bad, NV)

    def test_redirects_are_never_followed(self):
        t = self.transport([FakeResponse(status=302, headers={"location": DOC.replace("000104581026000073", "000104581026999999")})])
        with self.assertRaises(updater.NetworkBlocked):
            t.get(DOC, NV, "NVDA")
        self.assertEqual(len(t.calls), 1)

    def test_connection_goes_to_the_checked_address_and_sec_headers_stay_at_sec(self):
        t = self.transport([FakeResponse(), FakeResponse()])
        t.get(DOC, NV, "NVDA")
        t.get("https://www.nasdaq.com/press-release/nvidia-announces-2026-08-26", NV, "NVDA")
        self.assertEqual(t.calls[0][1], "162.159.140.1")
        self.assertEqual(t.calls[0][3]["User-Agent"], "sec-contact-sentinel")
        self.assertNotIn("sec-contact-sentinel", json.dumps(t.calls[1][3]))

    def test_private_address_refused(self):
        with self.assertRaises(updater.NetworkBlocked):
            self.transport([FakeResponse()], resolver=lambda host: ["10.0.0.5"]).get(DOC, NV, "NVDA")
        with self.assertRaises(updater.NetworkBlocked):
            self.transport([FakeResponse()], resolver=lambda host: ["162.159.140.1", "127.0.0.1"]).get(DOC, NV, "NVDA")

    def test_body_caps_mime_and_encoding(self):
        with self.assertRaises(updater.NetworkBlocked):
            self.transport([FakeResponse(b"x" * (updater.CAPS["document"] + 1))]).get(DOC, NV, "NVDA")
        with self.assertRaises(updater.NetworkBlocked):
            self.transport([FakeResponse(ctype="application/octet-stream")]).get(DOC, NV, "NVDA")
        with self.assertRaises(updater.NetworkBlocked):
            self.transport([FakeResponse(encoding="gzip")]).get(DOC, NV, "NVDA")
        body, _ = self.transport([FakeResponse(b"x" * updater.CAPS["document"])]).get(DOC, NV, "NVDA")
        self.assertEqual(len(body), updater.CAPS["document"])

    def test_error_body_is_read_bounded(self):
        response = FakeResponse(b"e" * 1_000_000, status=404)
        with self.assertRaises(updater.NetworkBlocked):
            self.transport([response]).get(DOC, NV, "NVDA")
        self.assertLessEqual(response.taken, updater.ERROR_BODY_CAP)

    def test_transient_retry_is_bounded(self):
        t = self.transport([FakeResponse(status=503, headers={"retry-after": "1"}), FakeResponse(status=503, headers={"retry-after": "1"}), FakeResponse()])
        with self.assertRaises(updater.NetworkBlocked):
            t.get(DOC, NV, "NVDA")
        self.assertEqual(len(t.calls), 2)
        t = self.transport([FakeResponse(status=429, headers={"retry-after": "600"})])
        with self.assertRaises(updater.NetworkBlocked):
            t.get(DOC, NV, "NVDA")
        self.assertEqual(len(t.calls), 1)
        t = self.transport([OSError("reset"), OSError("reset")])
        with self.assertRaises(updater.NetworkBlocked):
            t.get(DOC, NV, "NVDA")

    def test_request_budgets(self):
        t = self.transport([FakeResponse() for _ in range(updater.PER_ISSUER_REQUESTS + 1)])
        for _ in range(updater.PER_ISSUER_REQUESTS):
            t.get(DOC, NV, "NVDA")
        with self.assertRaises(updater.NetworkBlocked):
            t.get(DOC, NV, "NVDA")


# ------------------------------------------------------------------------------------------------ lock, CLI and updater state

class LockAndCliTests(unittest.TestCase):
    def test_second_lock_holder_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = updater.StateLock(Path(tmp))
            try:
                with self.assertRaises(updater.SystemicFailure):
                    updater.StateLock(Path(tmp))
            finally:
                first.release()
            updater.StateLock(Path(tmp)).release()

    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "scripts" / "revenue_guidance_autoupdate.py"), *args],
                              capture_output=True, text=True, encoding="utf-8", timeout=300)

    def test_cli_requires_an_isolated_state_root(self):
        self.assertNotEqual(self.run_cli("--replay", str(FIXTURES)).returncode, 0)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "unrelated.txt").write_text("x", encoding="utf-8")
            result = self.run_cli("--state-root", tmp, "--replay", str(FIXTURES), "--as-of", "2026-08-27T12:00:00Z")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--state-root", result.stderr)
            self.assertNotEqual(self.run_cli("--state-root", str(Path(tmp) / "s"), "--as-of", "2026-08-27T12:00:00Z").returncode, 0)

    def test_cli_replay_runs_hermetically_and_failures_are_systemic(self):
        with tempfile.TemporaryDirectory() as tmp:
            chain = Chain(Path(tmp))
            chain.check("2026-02-26T12:00:00Z")
            args = ("--replay", str(FIXTURES), "--as-of", "2026-02-26T12:00:00Z", "--registry", str(chain.registry),
                    "--approval", str(chain.approval), "--receipts", str(chain.receipts))
            result = self.run_cli("--state-root", str(chain.state), *args)
            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads(result.stdout)
            self.assertEqual((summary["status"], summary["issuers"]["NVDA"]["action"]), ("OK", "ATTEMPTED"))
            (chain.state / "current.json").write_text("{", encoding="utf-8")
            result = self.run_cli("--state-root", str(chain.state), *args)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(result.stdout)["status"], "SYSTEMIC_FAILURE")
            chain.receipts.write_text("[", encoding="utf-8")
            self.assertEqual(self.run_cli("--state-root", str(chain.state), *args).returncode, 2)


class ReferenceChangeTests(unittest.TestCase):
    """R3-1: what was detected against the old reference survives the verified successor unless consumed or dated
    strictly before the successor's own filing day."""

    def run_with_extra(self, extra: dict) -> dict:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        chain = Chain(Path(tmp.name))
        for instant in ("2025-12-19T12:00:00Z", "2026-03-20T12:00:00Z"):
            chain.cycle(instant)
        chain.check("2026-06-26T12:00:00Z")
        rows = json.loads(chain.receipts.read_text(encoding="utf-8"))
        receipt = rows["issuers"]["MU"][-1]
        receipt["later_documents"] = sorted(receipt["later_documents"] + [extra], key=lambda d: (d["date"], d["channel"], d["id"]))
        body = {k: v for k, v in receipt.items() if k != "digest"}
        receipt["digest"] = checker.canonical_digest(body)
        chain.receipts.write_text(json.dumps(rows), encoding="utf-8")
        summary = chain.update("2026-06-26T12:00:00Z")
        self.assertEqual(summary["issuers"]["MU"]["outcome"], "VERIFIED")
        chain.check("2026-06-27T12:00:00Z")  # the successor's own complete check does not list the extra item
        return chain.resolve("2026-06-27T12:00:00Z", receipts=True)["MU"]

    def item(self, day):
        return {"channel": "SEC_SUBMISSIONS", "date": day, "id": "0000723125-26-999999", "label": "8-K items 8.01", "disposition": "POSSIBLY_RELEVANT"}

    def test_later_detection_survives_the_successor(self):
        state = self.run_with_extra(self.item("2026-06-25"))
        self.assertEqual((state["mode"], state["reason"], state["record"]), ("SUSPENDED", "RECEIPT_REVIEW_REQUIRED", None))

    def test_same_day_detection_survives_the_successor(self):
        self.assertEqual(self.run_with_extra(self.item("2026-06-24"))["mode"], "SUSPENDED")

    def test_earlier_detection_is_superseded_by_the_later_release(self):
        state = self.run_with_extra(self.item("2026-06-20"))
        self.assertEqual((state["mode"], state["reason"]), ("AUTO_VERIFIED", None))

    def chain_until_june(self) -> Chain:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        chain = Chain(Path(tmp.name))
        for instant in ("2025-12-19T12:00:00Z", "2026-03-20T12:00:00Z"):
            chain.cycle(instant)
        return chain

    def inject(self, chain: Chain, instant: str, extra: dict) -> None:
        chain.check(instant)
        rows = json.loads(chain.receipts.read_text(encoding="utf-8"))
        receipt = rows["issuers"]["MU"][-1]
        receipt["later_documents"] = sorted(receipt["later_documents"] + [extra], key=lambda d: (d["date"], d["channel"], d["id"]))
        receipt["digest"] = checker.canonical_digest({k: v for k, v in receipt.items() if k != "digest"})
        chain.receipts.write_text(json.dumps(rows), encoding="utf-8")

    def test_detection_seen_during_a_repeated_wait_survives_receipt_retention(self):
        """Astra A1-r4 R4-1: outage, new material item during the repeated wait, the checker's eight-receipt retention
        drops it, the retry succeeds, the successor's own check does not list it -> still suspended."""
        chain = self.chain_until_june()
        chain.check("2026-06-26T12:00:00Z")
        down = lambda instant: updater.run(chain.state, DownTransport(), at(instant), PROFILES, chain.registry, chain.approval, chain.receipts)  # noqa: E731
        self.assertEqual(down("2026-06-26T12:00:00Z")["issuers"]["MU"]["reason"], "NETWORK_UNAVAILABLE")
        self.inject(chain, "2026-06-26T13:00:00Z", self.item("2026-06-25"))
        self.assertIn("generation_id", down("2026-06-26T13:00:00Z"))  # the new observation is committed
        for hour in range(14, 22):
            chain.check(f"2026-06-26T{hour:02d}:00:00Z")
        rows = json.loads(chain.receipts.read_text(encoding="utf-8"))["issuers"]["MU"]
        self.assertFalse(any(d["id"] == "0000723125-26-999999" for r in rows for d in r["later_documents"]))
        self.assertEqual(chain.update("2026-06-26T22:00:00Z")["issuers"]["MU"]["outcome"], "VERIFIED")
        chain.check("2026-06-27T12:00:00Z")
        state = chain.resolve("2026-06-27T12:00:00Z", receipts=True)["MU"]
        self.assertEqual((state["mode"], state["reason"], state["record"]), ("SUSPENDED", "RECEIPT_REVIEW_REQUIRED", None))

    def test_detection_seen_on_a_retry_survives_a_crash(self):
        chain = self.chain_until_june()
        chain.check("2026-06-26T12:00:00Z")
        updater.run(chain.state, DownTransport(), at("2026-06-26T12:00:00Z"), PROFILES, chain.registry, chain.approval, chain.receipts)
        self.inject(chain, "2026-06-26T13:00:00Z", self.item("2026-06-25"))

        class Crash:
            replay = True

            def get(self, url, profile, symbol):
                raise KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            updater.run(chain.state, Crash(), at("2026-06-26T13:00:00Z"), PROFILES, chain.registry, chain.approval, chain.receipts)
        gen = overlay.generation_at(chain.state, "2026-06-26T13:00:00Z")
        self.assertIn("0000723125-26-999999", [d["id"] for d in gen["detections"]["MU"]["documents"]])

    def test_detection_overflow_is_a_barrier(self):
        chain = self.chain_until_june()
        chain.check("2026-06-26T12:00:00Z")
        rows = json.loads(chain.receipts.read_text(encoding="utf-8"))
        receipt = rows["issuers"]["MU"][-1]
        receipt["later_documents"] = sorted(receipt["later_documents"] + [dict(self.item("2026-06-25"), id=f"0000723125-26-9{i:05d}") for i in range(300)],
                                           key=lambda d: (d["date"], d["channel"], d["id"]))
        receipt["digest"] = checker.canonical_digest({k: v for k, v in receipt.items() if k != "digest"})
        chain.receipts.write_text(json.dumps(rows), encoding="utf-8")
        self.assertEqual(chain.update("2026-06-26T12:00:00Z")["issuers"]["MU"], {"action": "WAITING", "reason": "DETECTIONS_OVERFLOW"})
        state = chain.resolve("2026-06-26T12:00:00Z")["MU"]
        self.assertEqual((state["mode"], state["reason"], state["record"]), ("SUSPENDED", "DETECTIONS_OVERFLOW", None))
        gated = overlay.resolve_issuers(chain.state, "2026-06-26T12:00:00Z", PROFILES.read_bytes(), chain.registry.read_bytes(),
                                        chain.approval.read_bytes(), chain.curated(), {"issuers": {}}, allow_replay=True)["MU"]
        self.assertEqual((gated["mode"], gated["reason"]), ("SUSPENDED", "DETECTIONS_OVERFLOW"))


class DownTransport:
    replay = True

    def get(self, url, profile, symbol):
        raise updater.NetworkBlocked("UNREACHABLE URLError")


class UpdaterStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.chain = Chain(Path(self.tmp.name))

    def test_detection_is_committed_before_fetching_and_an_outage_waits_then_succeeds(self):
        self.chain.check("2026-02-26T12:00:00Z")
        summary = updater.run(self.chain.state, DownTransport(), at("2026-02-26T12:00:00Z"), PROFILES, self.chain.registry,
                              self.chain.approval, self.chain.receipts)
        self.assertEqual(summary["issuers"]["NVDA"]["reason"], "NETWORK_UNAVAILABLE")
        generations = sorted((self.chain.state / "generations").iterdir())
        self.assertGreaterEqual(len(generations), 2)  # the detection, then the outcome
        state = self.chain.resolve("2026-02-26T12:00:00Z")
        self.assertEqual((state["NVDA"]["mode"], state["NVDA"]["record"]), ("WAITING", None))
        again = updater.run(self.chain.state, DownTransport(), at("2026-02-26T13:00:00Z"), PROFILES, self.chain.registry,
                            self.chain.approval, self.chain.receipts)
        self.assertNotIn("generation_id", again)  # the same wait is not rewritten every hour
        self.chain.cycle("2026-02-26T14:00:00Z")
        self.assertEqual(self.chain.resolve("2026-02-26T14:00:00Z")["NVDA"]["mode"], "AUTO_VERIFIED")

    def test_crash_after_detection_keeps_the_issuer_suspended(self):
        self.chain.check("2026-02-26T12:00:00Z")

        class Crash:
            replay = True

            def get(self, url, profile, symbol):
                raise KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            updater.run(self.chain.state, Crash(), at("2026-02-26T12:00:00Z"), PROFILES, self.chain.registry, self.chain.approval, self.chain.receipts)
        state = self.chain.resolve("2026-02-26T12:00:00Z")
        self.assertEqual((state["NVDA"]["mode"], state["NVDA"]["reason"]), ("WAITING", "EVENT_DETECTED"))

    def test_no_check_or_nothing_new_writes_nothing(self):
        summary = self.chain.update("2026-02-26T12:00:00Z")  # no receipts file yet
        self.assertEqual({v["action"] for v in summary["issuers"].values()}, {"NO_EVENT"})
        self.assertFalse((self.chain.state / "current.json").exists())

    def test_unresolved_wait_is_not_cleared_by_omission(self):
        self.chain.check("2025-11-25T12:00:00Z")
        rows = json.loads(self.chain.receipts.read_text(encoding="utf-8"))
        receipt = rows["issuers"]["NVDA"][-1]
        clean = copy.deepcopy(dict(receipt, checked_at="2025-11-26T12:00:00Z"))
        receipt["later_documents"] = receipt["later_documents"] + [
            {"channel": "SEC_SUBMISSIONS", "date": "2025-11-24", "id": "0001045810-25-999999", "label": "8-K items 8.01", "disposition": "POSSIBLY_RELEVANT"}]
        self.chain.receipts.write_text(json.dumps(rows), encoding="utf-8")
        self.assertEqual(self.chain.update("2025-11-25T12:00:00Z")["issuers"]["NVDA"]["action"], "WAITING")
        rows["issuers"]["NVDA"] = [clean]  # the older receipt left the cache; a later read no longer lists the item
        self.chain.receipts.write_text(json.dumps(rows), encoding="utf-8")
        self.chain.update("2025-11-26T12:00:00Z")
        self.assertEqual(self.chain.resolve("2025-11-26T12:00:00Z")["NVDA"]["mode"], "WAITING")

    def test_corrupt_state_is_a_systemic_failure(self):
        self.chain.state.mkdir(parents=True)
        (self.chain.state / "current.json").write_text("{", encoding="utf-8")
        self.chain.check("2026-02-26T12:00:00Z")
        with self.assertRaises(updater.SystemicFailure):
            self.chain.update("2026-02-26T12:00:00Z")


class CountingReplay(ReplayAsOf):
    """The fixture replay that counts requests and can refuse or crash for one issuer."""

    def __init__(self, day: str, crash: str | None = None, refuse: str | None = None):
        super().__init__(day)
        self.calls: list[str] = []
        self.crash, self.refuse = crash, refuse

    def get(self, url, profile, symbol):
        if symbol == self.crash:
            raise KeyboardInterrupt
        if symbol == self.refuse:
            raise updater.NetworkBlocked("REQUEST_BUDGET")
        self.calls.append(url)
        return super().get(url, profile, symbol)


class SharedBudget(ReplayAsOf):
    """The fixture replay under a shared per-run request budget: after `limit` requests every issuer is refused as
    the real transport refuses a spent run budget."""

    def __init__(self, day: str, limit: int):
        super().__init__(day)
        self.limit, self.calls = limit, []

    def get(self, url, profile, symbol):
        if len(self.calls) >= self.limit:
            raise updater.NetworkBlocked("RUN_BUDGET")
        self.calls.append((symbol, url))
        return super().get(url, profile, symbol)


class B0Tests(unittest.TestCase):
    """ORDERS-V3-AUTOUPDATE-01 B0: shared reference, adapters, decision contract, fair queue, reuse, history segments."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.chain = Chain(Path(self.tmp.name))

    def run_with(self, transport, instant):
        return updater.run(self.chain.state, transport, at(instant), PROFILES, self.chain.registry, self.chain.approval, self.chain.receipts)

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


class FixtureInventoryTests(unittest.TestCase):
    def test_every_fixture_matches_its_inventory(self):
        names = {p.name for p in (FIXTURES / "raw").iterdir()}
        self.assertEqual(names, {f"{r['sha256']}.gz" for r in INVENTORY})
        for row in INVENTORY:
            fixture_bytes(row)
            self.assertRegex(row["retrieved_at"], r"^20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9:]{8}Z$")

    def test_baseline_values_are_the_filed_values(self):
        """Each baseline actual re-read from the fixture filings with an independent inline-XBRL reader."""
        def fact(sym, report_date, concept, start, end):
            raw = fixture_bytes(row_of(sym, "PERIODIC_FILING", report_date=report_date)).decode("utf-8")
            contexts = {m.group(1) for m in re.finditer(
                r'<xbrli:context id="([^"]+)"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">[0-9]+</xbrli:identifier></xbrli:entity>'
                rf'<xbrli:period><xbrli:startDate>{start}</xbrli:startDate><xbrli:endDate>{end}</xbrli:endDate>', raw)}
            values = {Decimal(m.group(2).replace(",", "")) * 10 ** 6 for m in re.finditer(
                rf'<ix:nonFraction[^>]*contextRef="([^"]+)"[^>]*name="{concept}"[^>]*scale="6"[^>]*>([0-9,]+)</ix:nonFraction>', raw)
                if m.group(1) in contexts}
            self.assertEqual(len(values), 1, (sym, report_date, start, end))
            return float(values.pop())
        base = {r["symbol"]: r for r in json.loads((FIXTURES / "bootstrap-registry.json").read_text(encoding="utf-8"))["issuers"]}
        nv = base["NVDA"]["reported_quarters"]
        self.assertEqual(nv[1]["revenue"], fact("NVDA", "2025-04-27", "us-gaap:Revenues", "2025-01-27", "2025-04-27"))
        self.assertEqual(nv[2]["revenue"], fact("NVDA", "2025-07-27", "us-gaap:Revenues", "2025-04-28", "2025-07-27"))
        self.assertEqual(nv[3]["revenue"], fact("NVDA", "2025-10-26", "us-gaap:Revenues", "2025-07-28", "2025-10-26"))
        self.assertEqual(nv[0]["revenue"], fact("NVDA", "2026-01-25", "us-gaap:Revenues", "2024-01-29", "2025-01-26")
                         - fact("NVDA", "2025-10-26", "us-gaap:Revenues", "2024-01-29", "2024-10-27"))
        c = "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
        mu = base["MU"]["reported_quarters"]
        self.assertEqual(mu[0]["revenue"], fact("MU", "2025-11-27", c, "2024-08-30", "2024-11-28"))
        self.assertEqual(mu[1]["revenue"], fact("MU", "2025-02-27", c, "2024-11-29", "2025-02-27"))
        self.assertEqual(mu[2]["revenue"], fact("MU", "2025-05-29", c, "2025-02-28", "2025-05-29"))
        self.assertEqual(mu[3]["revenue"], fact("MU", "2025-08-28", c, "2024-08-30", "2025-08-28") - fact("MU", "2025-05-29", c, "2024-08-30", "2025-05-29"))
        for sym, filed in (("NVDA", "2025-11-19"), ("MU", "2025-09-23")):
            text = verify.parse_document(fixture_bytes(exhibit_row(sym, filed))).text
            self.assertIn(base[sym]["claims"][0]["passage"], text)


if __name__ == "__main__":
    unittest.main()
