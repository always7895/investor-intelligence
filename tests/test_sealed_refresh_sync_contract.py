"""P6, offline: real sync emission and BOTH original PowerShell outcome readers.

Only transport is fake. The harness parses FunctionDefinitionAst bodies and loads
the real readers and their original path/integer guards, never script entrypoints.
P6_3 drives the emitter's enforced closed wire schema through those consumers,
including invalid types and retention/category separation. No Python reader mirror.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import sync_sealed_snapshot_kv as SY  # noqa: E402
from sealed_kv_fakes import (  # noqa: E402
    NOWRITE, OLD_POINTER, POINTER_KEY, Q_OK, RUN, FakeKV, Fixture, KvTestCase, Row, cli_environment, make_cloud,
    run_sy)

GUID = "0123456789abcdef0123456789abcdef"
VIEW = ("status", "phase", "error_category", "pointer_state")
CALLER_REFUSES = "CALLER_REFUSES"
HOSTS = tuple(dict.fromkeys(path for name in ("powershell.exe", "pwsh.exe")
                           if (path := shutil.which(name))))
NATIVE_RUN, NATIVE_POPEN = subprocess.run, subprocess.Popen


def read_outcome_cases(cases, host):
    """Materialize exact JSON types; consumers read these bytes, not PS reserialization."""
    with tempfile.TemporaryDirectory(prefix="sealed-outcome-consumers-") as directory:
        root = Path(directory)
        inputs = []
        for index, case in enumerate(cases):
            path = root / f"outcome-{index}.json"
            if "raw" in case:
                path.write_bytes(case["raw"])
            else:
                path.write_text(json.dumps(case["record"], separators=(",", ":"), allow_nan=False), encoding="utf-8")
            inputs.append({"name": case["name"], "operation": case["operation"],
                           "path": str(path), "expected_run": case.get("expected_run", RUN)})
        cases_path = root / "cases.json"
        cases_path.write_text(json.dumps(inputs, separators=(",", ":")), encoding="utf-8")
        # Only this fixed, read-only AST-reader fixture may escape KvTestCase's
        # transport guard; the real sync remains unable to launch a native CLI.
        with mock.patch.object(subprocess, "run", NATIVE_RUN), mock.patch.object(subprocess, "Popen", NATIVE_POPEN):
            completed = subprocess.run(
                [host, "-NoProfile", "-NonInteractive", "-File",
                 str(ROOT / "tests/fixtures/sealed_outcome_readers.ps1"),
                 "-ProjectRoot", str(ROOT), "-CasesPath", str(cases_path)],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=120)
        if completed.returncode != 0:
            raise AssertionError("original outcome-reader harness failed: " + completed.stdout + completed.stderr)
        answers = json.loads(completed.stdout.lstrip("\ufeff"))
        if not isinstance(answers, list) or len(answers) != len(cases):
            raise AssertionError("original outcome-reader harness returned an incomplete case set")
        return {answer["name"]: answer for answer in answers}


def wire_record(operation, field=None, value=None):
    """Use actual emitter constructors, with valid companion fields for each wire value."""
    record = SY._outcome(operation)
    record["run_id"] = RUN
    if operation == "SYNC" and ((field == "retention_reason" and value is not None) or
                                (field == "status" and value == "RETAINED_LAST_GOOD")):
        reason = value if field == "retention_reason" else "NO_CHANGE"
        with mock.patch.object(SY, "TOTAL_ATTEMPTS", 0), mock.patch.object(SY, "PUT_ATTEMPTS", 0), \
                mock.patch.object(SY, "ACTIVE_WRITE_RESERVATION", None), \
                mock.patch.object(SY, "LAST_CALL", {"attempts": 0, "exit_code": None, "error_category": "NONE"}):
            if SY._retain(record, {"run_id": RUN}, reason) != 0:
                raise AssertionError("actual retained-outcome emitter refused confirmed custody")
    elif ((field == "status" and value == "SUCCEEDED") or (field == "phase" and value == "COMPLETE") or
          (field == "error_category" and value == "NONE")):
        record.update(status="SUCCEEDED", phase="COMPLETE", error_category="NONE")
        if operation == "SYNC":
            record["pointer_state"] = "READBACK_CONFIRMED"
    elif field == "pointer_state" and value == "READBACK_CONFIRMED":
        record.update(phase="LOCAL_LEDGER", error_category="LOCAL_IO_FAILURE")
    elif field == "pointer_state" and value == "ATTEMPTED_UNCONFIRMED":
        record["phase"] = "POINTER_READBACK"
    elif field == "error_category":
        record["phase"] = "OBJECT_PUT" if operation == "SYNC" else "POINTER_READ"
    if field is not None:
        record[field] = value
    return record


@unittest.skipUnless(HOSTS, "native PowerShell required for original consumer bodies")
class RefreshSyncContract(KvTestCase):
    def setUp(self):
        super().setUp()
        self.kv = FakeKV({POINTER_KEY: OLD_POINTER})
        self.ledger = self.tmp / "ledger" / "kv-blob-ledger.json"
        self.logs = self.tmp / "logs"
        self.logs.mkdir()
        self.outcome = self.logs / ("sealed-sync-" + GUID + ".json")

    def caller_row(self, fx, **kwargs) -> tuple:
        """Run the sync at its transport seam; feed its exact outcome bytes to the original reader."""
        run_dir = fx.write_to(self.tmp / "runs" / fx.run)
        r = run_sy(SY, self.kv, run_dir, self.ledger, fx.names, seam="B", outcome_path=self.outcome, **kwargs)
        try:
            case = {"name": "emitted", "operation": "SYNC", "expected_run": fx.run,
                    "raw": self.outcome.read_bytes()}
            answer = read_outcome_cases([case], HOSTS[0])["emitted"]
            view = tuple(answer["record"][name] for name in VIEW) if answer["accepted"] else CALLER_REFUSES
        except OSError:
            view = CALLER_REFUSES
        return r, Row(("exit", "outcome", "caller_view"), (r.exit, r.outcome, view))


    # P6-2a, SY 252-254 (seam B: 'kv put failed' classifies UNKNOWN, SY 115, terminal at 156): the caller reads the
    # same failure, with the pointer NOT_ATTEMPTED.
    def test_P6_2a_object_put_failure_reaches_the_caller(self):
        fx = Fixture(RUN, "sy")
        self.kv.fail_put(fx.key["B2"], 1, NOWRITE)
        _, row = self.caller_row(fx)
        failed = ("FAILED", "OBJECT_PUT", "UNKNOWN", "NOT_ATTEMPTED")
        self.assertRow(row, (1, failed, failed))

    # P6-2b, SY 266-270: a failed pointer put is ATTEMPTED_UNCONFIRMED for the caller too (never "untouched").
    def test_P6_2b_pointer_put_failure_reaches_the_caller(self):
        fx = Fixture(RUN, "sy")
        self.kv.fail_put(POINTER_KEY, 1, NOWRITE)
        _, row = self.caller_row(fx)
        failed = ("FAILED", "POINTER_PUT", "UNKNOWN", "ATTEMPTED_UNCONFIRMED")
        self.assertRow(row, (1, failed, failed))

    # P6-2c, SY 271-275: an altered pointer readback is READBACK_MISMATCH, a category only the sync emits.
    def test_P6_2c_pointer_readback_mismatch_reaches_the_caller(self):
        fx = Fixture(RUN, "sy")
        self.kv.corrupt_get(POINTER_KEY, 1, b"altered-pointer")
        _, row = self.caller_row(fx)
        failed = ("FAILED", "POINTER_READBACK", "READBACK_MISMATCH", "ATTEMPTED_UNCONFIRMED")
        self.assertRow(row, (1, failed, failed))

    # P6-2d, SY 219 then 224-225: the run id is recorded before the trailing-LF refusal, so the caller accepts the
    # INPUT_INVALID outcome for ITS run (an empty run id would be SYNC_OUTCOME_INVALID, ps1 270).
    def test_P6_2d_trailing_lf_input_refusal_reaches_the_caller(self):
        fx = Fixture(RUN, "sy", s1_body='{"slot":"a"}\n')
        r, row = self.caller_row(fx)
        failed = ("FAILED", "INPUT", "INPUT_INVALID", "NOT_ATTEMPTED")
        self.assertRow(row, (1, failed, failed))
        self.assertEqual(r.ops, ())

    # P6-2e, SY 45-62 and 135-137: the real _cli_command over a mismatched synthetic cloud dir (declared 4.0.1 != locked
    # 4.0.0) launches nothing; the caller reads CLI_UNAVAILABLE with a null exit code (ps1 281 accepts null).
    def test_P6_2e_unavailable_cli_reaches_the_caller(self):
        cloud = make_cloud(self.tmp, "4.0.0", declared="4.0.1")
        node = self.tmp / "node-stub"
        node.write_bytes(b"")
        with cli_environment(node), mock.patch.object(SY, "CLOUD_DIR", cloud):
            r, row = self.caller_row(Fixture(RUN, "sy"), real_cli=True)
        failed = ("FAILED", "OBJECT_PUT", "CLI_UNAVAILABLE", "NOT_ATTEMPTED")
        self.assertRow(row, (1, failed, failed))
        self.assertEqual((r.argv_log, r.counters), ([], (0, 0, None)))

    # P6-2f, SY 348-358: an outcome path that already exists (the caller's guid makes it unreachable in practice) stops
    # the sync before any call; the caller would find only the older bytes and refuse them (SYNC_OUTCOME_UNAVAILABLE).
    def test_P6_2f_existing_outcome_path_runs_nothing(self):
        self.outcome.write_bytes(b"older result bytes")
        r, row = self.caller_row(Fixture(RUN, "sy"))
        self.assertRow(row, (1, ("FAILED", "INPUT", "OUTCOME_WRITE_FAILED", "NOT_ATTEMPTED"), CALLER_REFUSES))
        self.assertEqual((r.ops, self.kv.store[POINTER_KEY]), ((), OLD_POINTER))

    def test_P6_3_every_emitted_wire_value_reaches_both_original_consumers(self):
        cases = []

        def add(operation, label, record, accepted, **kwargs):
            cases.append({"name": f"{operation}:{label}", "operation": operation,
                          "record": record, "accepted": accepted, **kwargs})

        # This is the schema the REAL emitter enforces at serialization, not a
        # scrape/equality check against consumer source or a Python reader mirror.
        for operation, fields in SY.OUTCOME_WIRE_VALUES.items():
            for field, values in fields.items():
                for value in sorted(values, key=repr):
                    add(operation, f"emitted:{field}:{value!r}",
                        wire_record(operation, field, value), True)

            base = wire_record(operation)
            for field in ("operation", "status", "phase", "pointer_state", "error_category"):
                for index, value in enumerate(("SYNTHETIC_UNKNOWN", None, True, 1, 1.0,
                                               [base[field]], {"value": base[field]})):
                    add(operation, f"invalid:{field}:{index}", dict(base, **{field: value}), False)
            for index, value in enumerate((None, True, 1, [RUN], {"value": RUN})):
                add(operation, f"invalid:run_id:{index}", dict(base, run_id=value), False)
            for field in ("schema_version", "cli_attempts_total", "last_cli_attempts",
                          "objects_uploaded", "objects_reused", "objects_verified"):
                for index, value in enumerate((None, True, "1", 1.0, [1], {"value": 1})):
                    add(operation, f"invalid:{field}:type:{index}", dict(base, **{field: value}), False)
                add(operation, f"invalid:{field}:negative", dict(base, **{field: -1}), False)
            limits = {"schema_version": 2, "cli_attempts_total": 2147483648 if operation == "SYNC" else 7,
                      "last_cli_attempts": 4}
            if operation == "WATCHDOG":
                limits.update(objects_uploaded=1, objects_reused=1, objects_verified=1)
            for field, value in limits.items():
                add(operation, f"invalid:{field}:upper", dict(base, **{field: value}), False)
            add(operation, "invalid:attempts:inconsistent", dict(base, last_cli_attempts=1), False)
            for index, value in enumerate((True, "0", 0.0, [], {}, -2147483649, 4294967296)):
                add(operation, f"invalid:exit_code:{index}", dict(base, last_cli_exit_code=value), False)
            for value in (None, -2147483648, 0, 4294967295):
                add(operation, f"valid:exit_code:{value}", dict(base, last_cli_exit_code=value), True)
            for index, value in enumerate(([base], [], True, None, "SYNTHETIC_UNKNOWN")):
                add(operation, f"invalid:json_root:{index}", base, False,
                    raw=json.dumps(value, separators=(",", ":")).encode("utf-8"))
            for field in ("operation", "schema_version", "status", "phase", "pointer_state", "error_category"):
                missing = dict(base)
                del missing[field]
                add(operation, f"invalid:missing:{field}", missing, False)
            add(operation, "invalid:reason_as_category", dict(base, error_category="WRITE_BUDGET"), False)

        # WRITE_BUDGET is a retained-last-good REASON; the unavailable allowance
        # authorization is a distinct SYNC failure CATEGORY, never a reason.
        retained = wire_record("SYNC", "retention_reason", "WRITE_BUDGET")
        add("SYNC", "budget:retention_reason", retained, True)
        add("SYNC", "budget:unavailable_category",
            wire_record("SYNC", "error_category", "WRITE_BUDGET_UNAVAILABLE"), True)
        for index, value in enumerate(("WRITE_BUDGET_UNAVAILABLE", "UNKNOWN", None, True, 1,
                                       ["WRITE_BUDGET"], {"value": "WRITE_BUDGET"})):
            add("SYNC", f"invalid:retention_reason:{index}", dict(retained, retention_reason=value), False)
            if value is not None:
                add("SYNC", f"invalid:failed_retention_reason:{index}",
                    dict(wire_record("SYNC"), retention_reason=value), False)
        for state in ("ATTEMPTED_UNCONFIRMED", "READBACK_CONFIRMED"):
            add("SYNC", f"invalid:ambiguous_retained_pointer:{state}", dict(retained, pointer_state=state), False)
        for category in ("WRITE_BUDGET_UNAVAILABLE", "DAILY_KV_LIMIT"):
            add("SYNC", f"invalid:retained_error:{category}", dict(retained, error_category=category), False)
        add("SYNC", "invalid:retained_phase", dict(retained, phase="PREFLIGHT"), False)
        for index, value in enumerate((None, True, 1, [RUN], "not-a-run")):
            add("SYNC", f"invalid:retained_run_id:{index}", dict(retained, retained_run_id=value), False)
        add("SYNC", "invalid:other_run", wire_record("SYNC"), False, expected_run="different-run")
        add("WATCHDOG", "invalid:sync_budget_category",
            dict(wire_record("WATCHDOG"), error_category="WRITE_BUDGET_UNAVAILABLE"), False)
        for reason in ("NO_CHANGE", "WRITE_BUDGET", "DAILY_KV_LIMIT", "CANDIDATE_UNAVAILABLE"):
            add("SYNC", f"valid:bootstrap_retention_reason:{reason}",
                dict(wire_record("SYNC"), error_category="BOOTSTRAP_REQUIRED", retention_reason=reason), True)
            add("WATCHDOG", f"invalid:sync_retention:{reason}",
                dict(wire_record("WATCHDOG"), retention_reason=reason, retained_run_id=RUN), False)
        for index, value in enumerate((True, 1, ["WRITE_BUDGET"], {"value": "WRITE_BUDGET"})):
            add("WATCHDOG", f"invalid:retention_reason_type:{index}",
                dict(wire_record("WATCHDOG"), retention_reason=value), False)

        # One genuine read-only emitter path, with transport bytes as its only
        # fixture seam, complements the exhaustive enforced-schema value table.
        import sealed_product_policy as products
        at = "2026-11-09T00:00:00Z"
        bodies = {key: "{}" for key in products.core_keys()}
        bodies[products.PIPELINE_KEY] = at
        bodies["v213:top20-report:latest"] = json.dumps({"generated_at": at, "records": [{"name": "合成"}] * 20}, ensure_ascii=False)
        seal = {"schema_version": 1, "run_id": RUN, "transaction_id": "a" * 32,
                "generated_at": at, "public_data_as_of": at, "objects": {
                    key: {"sha256": SY.sha(body), "utf8_bytes": len(body.encode("utf-8"))} for key, body in bodies.items()}}
        seal_text = json.dumps(seal, ensure_ascii=False)
        pointer = json.dumps({"run_id": RUN, "transaction_id": "a" * 32, "seal_sha256": SY.sha(seal_text),
                              "promoted_at": at, "public_data_as_of": at})
        store = {**{f"snapshot:{RUN}:{key}": body for key, body in bodies.items()},
                 f"snapshot:{RUN}:v213:snapshot-seal:v1": seal_text, "snapshot:current": pointer}
        observed = SY._outcome("WATCHDOG")
        with mock.patch.object(SY, "client_get", side_effect=store.get), \
                mock.patch.object(SY, "TOTAL_ATTEMPTS", 0), \
                mock.patch.object(SY, "LAST_CALL", {"attempts": 0, "exit_code": 0, "error_category": "NONE"}):
            self.assertEqual(SY.read_freshness(observed), 0)
        self.assertEqual(observed["anchor"], "2026-11-09T00:00:00+00:00")
        self.assertEqual(observed["report_generated_at"], "2026-11-09T00:00:00+00:00")
        add("WATCHDOG", "actual_read_freshness_emission", observed, True)

        for host in HOSTS:
            answers = read_outcome_cases(cases, host)
            self.assertEqual(set(answers), {case["name"] for case in cases})
            for case in cases:
                with self.subTest(host=host, case=case["name"]):
                    answer = answers[case["name"]]
                    self.assertIs(answer["accepted"], case["accepted"])
                    if case["accepted"]:
                        self.assertEqual(answer["record"], case["record"])



if __name__ == "__main__":
    unittest.main()
