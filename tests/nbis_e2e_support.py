"""SYNTHETIC_G4_NOT_GENUINE: offline checker/updater/snapshot fixtures only."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import itertools
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from unittest import mock

from tests import nbis_synthetic_sources as f
import revenue_guidance_release_check as checker

T0 = "2032-02-19T23:00:00Z"
T1 = "2032-02-20T12:00:00Z"
CUTOFF_TEXT = "2032-02-20T13:00:00Z"
CUTOFF = datetime(2032, 2, 20, 13, tzinfo=timezone.utc)


def moment(instant):
    return datetime.strptime(instant, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


class Chain:
    """All writable objects are beneath the caller's owned disposable temp root."""
    def __init__(self, base: Path, *, tracked=False):
        self.base = base
        self.state = base / "state"
        self.registry = base / "registry.json"
        self.approval = base / "approval.json"
        self.receipts = base / "receipts.json"
        self.scenario = f.Scenario("Z")
        self.transport = self.scenario.transport
        self.registry.write_bytes(f.encoded({"schema": "revenue-guidance-v1", "version": 1,
                                           "issuers": [self.scenario.baseline]}))
        self.approval.write_bytes(f.encoded({"schema": "test-baseline-approval"}))
        self.profiles = f.PROFILE_PATH if tracked else base / "profiles.json"
        if not tracked:
            profiles = f.tracked()
            profiles["enabled_symbols"] = ["NBIS"]
            self.profiles.write_bytes(f.encoded(profiles))
        self.extra_ir = False
        self.checks = {}
        self.update_result = None
        self.snapshot = None

    def sec_fetch(self, url):
        return json.loads(self.scenario.bodies[url])

    def wire_fetch(self, url):
        query = parse_qs(urlsplit(url).query)
        offset, limit = int(query["offset"][0]), int(query["limit"][0])
        rows = [{"id": p.accession, "title": p.title,
                 "created": moment(p.filed + "T00:00:00Z").strftime("%b %d, %Y"),
                 "url": urlsplit(p.wire).path} for p in self.scenario.packages]
        return {"data": {"rows": rows[offset:offset + limit], "totalrecords": len(rows)}}

    def ir_fetch(self, url):
        rows = [(urlsplit(p.ir).path, p.title, p.filed) for p in self.scenario.packages]
        if self.extra_ir:
            rows.append(("/newsroom/synthetic-g4-new-guidance",
                         "Nebius revises synthetic revenue guidance", "2032-02-20"))
        body = "".join('<a href="' + path + '">' + title + " "
                       + moment(day + "T00:00:00Z").strftime("%B %d, %Y") + "</a>"
                       for path, title, day in rows)
        return f.html("e2e-newsroom", body)

    def load(self, instant, *, profiles=None):
        return f.overlay.load_effective_inputs(
            cutoff=instant, state_root=self.state, registry_path=self.registry,
            approval_path=self.approval, profiles_path=profiles or self.profiles,
            receipts_path=self.receipts, symbols=("NBIS",), allow_replay=False)

    def check(self, instant):
        self.checks[instant] = checker.run(
            self.registry, self.receipts, moment(instant), self.sec_fetch,
            self.wire_fetch, self.ir_fetch, effective_inputs=self.load(instant))
        return self.checks[instant]

    def update(self):
        sequence = itertools.count(1)
        with mock.patch.object(f.updater.secrets, "token_hex",
                               side_effect=lambda n: f"{next(sequence):0{2 * n}x}"):
            self.update_result = f.updater.run(
                self.state, self.transport, lambda: moment(T0),
                self.profiles, self.registry, self.approval, self.receipts)
        return self.update_result

    def produce(self):
        self.check(T0)
        self.update()
        self.check(T1)
        self.snapshot = self.load(CUTOFF_TEXT)
        return self.snapshot

    def receipt(self):
        return json.loads(self.receipts.read_bytes())["issuers"]["NBIS"][-1]

    def human_control(self):
        """Fresh registry/receipt/state, tracked profiles, no effective_inputs."""
        record = copy.deepcopy(self.snapshot.issuer("NBIS").usable_record)
        record["reviewed_later_documents"] = [
            {"id": row["id"], "disposition": "REVIEWED_IRRELEVANT", "reviewed_at": T1}
            for row in self.receipt()["later_documents"]
            if row["disposition"] == "POSSIBLY_RELEVANT"]
        human = self.base / "human"
        human.mkdir()
        registry, receipts, state = human / "registry.json", human / "receipts.json", human / "state"
        state.mkdir()
        registry.write_bytes(f.encoded({"schema": "revenue-guidance-v1", "version": 1,
                                       "issuers": [record]}))
        checker.run(registry, receipts, moment(T1), self.sec_fetch, self.wire_fetch,
                    self.ir_fetch, state_root=state)
        cache = json.loads(receipts.read_bytes())
        snapshot = f.overlay.load_effective_inputs(
            cutoff=CUTOFF_TEXT, state_root=state, registry_path=registry,
            approval_path=self.approval, profiles_path=f.PROFILE_PATH,
            receipts_path=receipts, symbols=("NBIS",), allow_replay=False)
        return record, cache, snapshot

    def forward(self):
        item = self.snapshot.issuer("NBIS")
        record = item.usable_record
        result = f.guidance.build_forward_quarters(
            "NBIS", record, CUTOFF, effective_inputs=self.snapshot)
        return (result["status"], result["reason"],
                (type(result["f1"]).__name__, result["f1"]),
                (type(result["f2"]).__name__, result["f2"]),
                (type(result["f3"]).__name__, result["f3"]),
                (type(result["f4"]).__name__, result["f4"]), len(result["forward_quarters"]),
                (type(record["fy_reconciliation"]["ytd_revenue"]).__name__,
                 record["fy_reconciliation"]["ytd_revenue"]))
