"""Transaction tests for scripts/sync_sealed_snapshot_kv.py over a fake KV (no network, no credentials,
no real wrangler/npx). Every row runs SY.main() through its real caller and compares a literal
(exit, outcome, ops, store diff, ledger written, stage dir present) designed from the code; the comment
above each row cites the code line it was designed from. Synthetic values only."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import publish_sealed_snapshot as PB  # noqa: E402
import sync_sealed_snapshot_kv as SY  # noqa: E402
from sealed_kv_fakes import (  # noqa: E402
    NETWORK, NOWRITE, OLD_POINTER, POINTER_KEY, Q_OK, RUN, WRITE_THEN_FAIL, FakeKV, Fixture, KvTestCase, Row,
    cli_environment, make_cloud, rewrite_objects, rewrite_pointer, run_pb, run_sy, sha)

PUT5 = (("put", "B1"), ("put", "B2"), ("put", "B3"), ("put", "S1"), ("put", "S2"))
GET5 = (("get", "B1"), ("get", "B2"), ("get", "B3"), ("get", "S1"), ("get", "S2"))
POINTER_PUT_GET = (("put", "POINTER"), ("get", "POINTER"))
HAPPY_OPS = PUT5 + GET5 + POINTER_PUT_GET
NEW5 = (("B1", "NEW"), ("B2", "NEW"), ("B3", "NEW"), ("S1", "NEW"), ("S2", "NEW"))
NEW5_PTR_CHG = (("B1", "NEW"), ("B2", "NEW"), ("B3", "NEW"), ("POINTER", "CHG"), ("S1", "NEW"), ("S2", "NEW"))
INPUT_INVALID = ("FAILED", "INPUT", "INPUT_INVALID", "NOT_ATTEMPTED")
TTLS = (("B1", 2592000), ("B2", 2592000), ("B3", 2592000), ("S1", 1209600), ("S2", 1209600), ("POINTER", None))


class SyRows(KvTestCase):
    def setUp(self):
        super().setUp()
        self.kv = FakeKV({POINTER_KEY: OLD_POINTER})
        self.ledger = self.tmp / "ledger" / "kv-blob-ledger.json"
        self.assertFalse(self.ledger.resolve().is_relative_to(ROOT.resolve()))

    def fixture(self, **kwargs) -> Fixture:
        fx = Fixture(RUN, "sy", **kwargs)
        fx.write_to(self.tmp / "runs" / fx.run)
        return fx

    def sync(self, fx, seam="A", **kwargs):
        return run_sy(SY, self.kv, self.tmp / "runs" / fx.run, self.ledger, fx.names, seam=seam, **kwargs)

    def expected_store(self, fx) -> dict:
        store = fx.store_bytes()
        store[POINTER_KEY] = fx.ptr_raw.encode("utf-8")
        return store

    # SY 250-262, 266, 270: objects put in sorted order, every object read back, pointer LAST then read back.
    def test_TS_1_happy_path(self):
        fx = self.fixture()
        r = self.sync(fx)
        self.assertRow(r.row(), (0, Q_OK, HAPPY_OPS, NEW5_PTR_CHG, True, False))
        last_pointer_put = max(i for i, op in enumerate(r.ops) if op == ("put", "POINTER"))
        last_object_get = max(i for i, op in enumerate(r.ops) if op[0] == "get" and op[1] != "POINTER")
        self.assertEqual(last_pointer_put > last_object_get, True)
        self.assertEqual(r.puts, TTLS)  # SY 250 (blob 30d, run keys 14d), 266 (pointer without ttl)
        self.assertEqual(self.kv.store, self.expected_store(fx))

    # SY 250-252: a failed object put returns 1 before any later put (NOWRITE leaves the key absent).
    def test_TS_2_object_put_nowrite(self):
        fx = self.fixture()
        self.kv.fail_put(fx.key["B2"], 1, NOWRITE)
        r = self.sync(fx)
        self.assertRow(r.row(), (1, ("FAILED", "OBJECT_PUT", "NONE", "NOT_ATTEMPTED"), (("put", "B1"), ("put", "B2")),
                                 (("B1", "NEW"),), False, True))

    def test_TS_2b_object_put_write_then_fail(self):
        fx = self.fixture()
        self.kv.fail_put(fx.key["B2"], 1, WRITE_THEN_FAIL)
        r = self.sync(fx)
        self.assertRow(r.row(), (1, ("FAILED", "OBJECT_PUT", "NONE", "NOT_ATTEMPTED"), (("put", "B1"), ("put", "B2")),
                                 (("B1", "NEW"), ("B2", "NEW")), False, True))

    # SY 258-261: an altered readback is READBACK_MISMATCH, pointer untouched and NOT_ATTEMPTED.
    def test_TS_3_object_readback_altered(self):
        fx = self.fixture()
        self.kv.corrupt_get(fx.key["B2"], 1, b"altered-body")
        r = self.sync(fx)
        self.assertRow(r.row(), (1, ("FAILED", "OBJECT_READBACK", "READBACK_MISMATCH", "NOT_ATTEMPTED"),
                                 PUT5 + (("get", "B1"), ("get", "B2")), NEW5, False, True))

    # SY 260: a missing readback (None) carries no mismatch category (the last CLI category, NONE).
    def test_TS_3b_object_readback_missing(self):
        fx = self.fixture()
        self.kv.missing_get(fx.key["B2"], 1)
        r = self.sync(fx)
        self.assertRow(r.row(), (1, ("FAILED", "OBJECT_READBACK", "NONE", "NOT_ATTEMPTED"),
                                 PUT5 + (("get", "B1"), ("get", "B2")), NEW5, False, True))

    # SY 265-268: a failed pointer put leaves the pointer state ATTEMPTED_UNCONFIRMED (never "untouched").
    def test_TS_4_pointer_put_nowrite(self):
        fx = self.fixture()
        self.kv.fail_put(POINTER_KEY, 1, NOWRITE)
        r = self.sync(fx)
        self.assertRow(r.row(), (1, ("FAILED", "POINTER_PUT", "NONE", "ATTEMPTED_UNCONFIRMED"),
                                 PUT5 + GET5 + (("put", "POINTER"),), NEW5, False, True))

    def test_TS_4b_pointer_put_write_then_fail(self):
        fx = self.fixture()
        self.kv.fail_put(POINTER_KEY, 1, WRITE_THEN_FAIL)
        r = self.sync(fx)
        self.assertRow(r.row(), (1, ("FAILED", "POINTER_PUT", "NONE", "ATTEMPTED_UNCONFIRMED"),
                                 PUT5 + GET5 + (("put", "POINTER"),), NEW5_PTR_CHG, False, True))

    # SY 270-273: the pointer was written; an altered readback is a mismatch and stays unconfirmed.
    def test_TS_5_pointer_readback_altered(self):
        fx = self.fixture()
        self.kv.corrupt_get(POINTER_KEY, 1, b"altered-pointer")
        r = self.sync(fx)
        self.assertRow(r.row(), (1, ("FAILED", "POINTER_READBACK", "READBACK_MISMATCH", "ATTEMPTED_UNCONFIRMED"),
                                 HAPPY_OPS, NEW5_PTR_CHG, False, True))

    # SY 244-249: the ledger (saved at 280 after success) lets a second run omit blob puts (246), but
    # SY 257-261 still reads every object back; the printed count is SY 254.
    def test_TS_6_second_run_reuses_blobs(self):
        fx = self.fixture()
        first = self.sync(fx)
        self.assertRow(first.row(), (0, Q_OK, HAPPY_OPS, NEW5_PTR_CHG, True, False))
        second = self.sync(fx)
        self.assertRow(second.row(), (0, Q_OK, (("put", "S1"), ("put", "S2")) + GET5 + POINTER_PUT_GET, (), True, False))
        self.assertEqual("OBJECTS_UPLOADED 2 BLOBS_REUSED 3" in second.stdout.splitlines(), True)

    # SY 231-232 and 280-281: after a failed first run (ledger unsaved) the same run dir and ledger sync cleanly.
    def test_TS_7_rerun_after_failure(self):
        fx = self.fixture()
        self.kv.fail_put(fx.key["B2"], 1, NOWRITE)
        first = self.sync(fx)
        self.assertRow(first.row(), (1, ("FAILED", "OBJECT_PUT", "NONE", "NOT_ATTEMPTED"), (("put", "B1"), ("put", "B2")),
                                     (("B1", "NEW"),), False, True))
        self.kv.clear_hooks()
        second = self.sync(fx)
        self.assertRow(second.row(), (0, Q_OK, HAPPY_OPS,
                                      (("B2", "NEW"), ("B3", "NEW"), ("POINTER", "CHG"), ("S1", "NEW"), ("S2", "NEW")),
                                      True, False))
        self.assertEqual(self.kv.store, self.expected_store(fx))

    # Seam B: SY 126-160 (ATTEMPTS 26, RETRY_SECONDS 27, sleep 158), classify 111 (fetch failed -> NETWORK_FAILURE).
    def test_TS_8_network_failure_retries(self):
        fx = self.fixture()
        self.kv.fail_put(fx.key["B1"], None, NETWORK)
        r = self.sync(fx, seam="B")
        self.assertRow(r.row("sleeps", "counters"),
                       (1, ("FAILED", "OBJECT_PUT", "NETWORK_FAILURE", "NOT_ATTEMPTED"),
                        (("put", "B1"), ("put", "B1"), ("put", "B1")), (), False, True, (5.0, 10.0), (3, 3, 1)))
        self.assertEqual(len(r.argv_log), 3)

    # F-SY-TRAILING-LF fixed: SY 172 rstrips CR/LF from every readback while SY 238 stages the exact body, so a body
    # ending in LF or CR could never read back identical; SY 224-225 refuse it as input before the stage dir and any call.
    def test_TS_1L_body_ending_in_lf_is_refused_as_input(self):
        fx = self.fixture(s1_body='{"slot":"a"}\n')
        r = self.sync(fx, seam="B")
        self.assertRow(r.row(), (1, INPUT_INVALID, (), (), False, False))
        self.assertEqual((r.argv_log, r.record["run_id"]), ([], RUN))

    def test_TS_1Lb_body_ending_in_cr_is_refused_as_input(self):
        fx = self.fixture(s1_body='{"slot":"a"}\r')
        r = self.sync(fx, seam="B")
        self.assertRow(r.row(), (1, INPUT_INVALID, (), (), False, False))

    # Control for SY 224: only a TRAILING CR/LF is refused; an embedded LF survives the readback strip and syncs.
    def test_TS_1Lc_body_with_embedded_lf_syncs(self):
        fx = self.fixture(s1_body='{"slot":\n"a"}')
        r = self.sync(fx, seam="B")
        self.assertRow(r.row(), (0, Q_OK, HAPPY_OPS, NEW5_PTR_CHG, True, False))
        self.assertEqual(self.kv.store[fx.key["S1"]], b'{"slot":\n"a"}')

    # SY 211-229 and main 347-349: input validation happens before the stage dir (231-232) and any call.
    def _input_invalid(self, fx):
        r = self.sync(fx)
        self.assertRow(r.row(), (1, INPUT_INVALID, (), (), False, False))

    def test_TS_9a_blob_body_edited(self):
        fx = self.fixture()
        edited = dict(fx.objects)
        edited[fx.key["B2"]] = "edited blob body"  # SY 226: sha(body) must equal the digest in the key
        rewrite_objects(self.tmp / "runs" / fx.run, edited)
        self._input_invalid(fx)

    def test_TS_9b_short_digest(self):
        fx = self.fixture()
        edited = dict(fx.objects)
        edited["blob:v1:abc123"] = "short digest body"  # SY 226: the digest must be 64 lowercase hex
        rewrite_objects(self.tmp / "runs" / fx.run, edited)
        self._input_invalid(fx)

    def test_TS_9c_key_without_run_prefix(self):
        fx = self.fixture()
        edited = dict(fx.objects)
        edited["unprefixed:key"] = "{}"  # SY 228
        rewrite_objects(self.tmp / "runs" / fx.run, edited)
        self._input_invalid(fx)

    def test_TS_9d_key_equals_prefix(self):
        fx = self.fixture()
        edited = dict(fx.objects)
        edited[f"snapshot:{fx.run}:"] = "{}"  # SY 228 (key == prefix)
        rewrite_objects(self.tmp / "runs" / fx.run, edited)
        self._input_invalid(fx)

    def test_TS_9e_foreign_run_prefix(self):
        fx = self.fixture()
        edited = dict(fx.objects)
        edited["snapshot:20261002T000000Z-0123456789cd:v213:a:latest"] = "{}"  # SY 228
        rewrite_objects(self.tmp / "runs" / fx.run, edited)
        self._input_invalid(fx)

    def test_TS_9f_serving_pointer_in_objects(self):
        fx = self.fixture()
        edited = dict(fx.objects)
        edited[POINTER_KEY] = "{}"  # SY 228: snapshot:current never enters the object phase
        rewrite_objects(self.tmp / "runs" / fx.run, edited)
        self._input_invalid(fx)

    def test_TS_9g_bad_pointer_run_id(self):
        fx = self.fixture()
        pointer = dict(fx.pointer)
        pointer["run_id"] = "not-a-run-id"  # SY 217
        rewrite_pointer(self.tmp / "runs" / fx.run, pointer)
        self._input_invalid(fx)

    # TS-10: the real _cli_command (SY 45-62) over a synthetic cloud dir; only subprocess.run is faked.
    def _cli_row(self, **cloud_kwargs):
        fx = self.fixture()
        cloud = make_cloud(self.tmp, "4.0.0", **{k: v for k, v in cloud_kwargs.items() if k != "node"})
        node = cloud_kwargs.get("node", self.tmp / "node-stub")
        if node == self.tmp / "node-stub":
            node.write_bytes(b"")
        with cli_environment(node), mock.patch.object(SY, "CLOUD_DIR", cloud):
            return fx, cloud, node, self.sync(fx, seam="B", real_cli=True)

    def test_TS_10_control_all_match(self):
        fx, cloud, node, r = self._cli_row()
        self.assertRow(r.row(), (0, Q_OK, HAPPY_OPS, NEW5_PTR_CHG, True, False))
        self.assertEqual(r.argv_log[0][:2], [str(Path(node).resolve()), str(cloud / "node_modules" / "wrangler" / "bin" / "wrangler.js")])
        self.assertEqual(len(r.argv_log), 12)

    def _refusal(self, r):
        self.assertRow(r.row("counters"), (1, ("FAILED", "OBJECT_PUT", "CLI_UNAVAILABLE", "NOT_ATTEMPTED"), (), (), False, True, (0, 0, None)))
        self.assertEqual(r.argv_log, [])

    def test_TS_10a_declared_differs_from_locked(self):
        self._refusal(self._cli_row(declared="4.0.1")[3])  # SY 58 declared != locked

    def test_TS_10b_installed_differs_from_locked(self):
        self._refusal(self._cli_row(installed="4.0.1")[3])  # SY 58 installed != locked

    def test_TS_10c_cli_file_missing(self):
        self._refusal(self._cli_row(with_cli=False)[3])  # SY 58 not cli.is_file()

    def test_TS_10d_project_node_nonexistent(self):
        self._refusal(self._cli_row(node=self.tmp / "no-such-node")[3])  # SY 57-58: PROJECT_NODE wins, is_file() false

    # TS-11: --outcome-path (SY main 347-355 reserve the file before any call, 369-376 write it after the run).
    def test_TS_11a_outcome_path_new_file(self):
        fx = self.fixture()
        target = self.tmp / "outcome-new.json"
        r = self.sync(fx, outcome_path=target)
        self.assertRow(r.row(), (0, Q_OK, HAPPY_OPS, NEW5_PTR_CHG, True, False))
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), r.record)

    # F-SY-OUTCOME-AFTER-PUBLISH fixed: SY 348-354 reserve the outcome file ('x' mode) BEFORE any call, so an existing
    # file stops the run at INPUT with the pointer NOT_ATTEMPTED (355-358 run nothing): no KV op, no ledger, no stage
    # dir, the old pointer stays and the older result bytes are left as they were.
    def test_TS_11b_outcome_path_existing_file(self):
        fx = self.fixture()
        target = self.tmp / "outcome-old.json"
        target.write_bytes(b"older result bytes")
        r = self.sync(fx, outcome_path=target)
        self.assertRow(r.row("counters"), (1, ("FAILED", "INPUT", "OUTCOME_WRITE_FAILED", "NOT_ATTEMPTED"), (), (), False,
                                           False, (0, 0, None)))
        self.assertEqual(self.kv.store[POINTER_KEY], OLD_POINTER)
        self.assertEqual(target.read_bytes(), b"older result bytes")

    # SY 352-354: an outcome path whose directory does not exist cannot be reserved either; nothing runs or appears.
    def test_TS_11c_outcome_path_unwritable(self):
        fx = self.fixture()
        target = self.tmp / "missing-dir" / "outcome.json"
        r = self.sync(fx, outcome_path=target)
        self.assertRow(r.row(), (1, ("FAILED", "INPUT", "OUTCOME_WRITE_FAILED", "NOT_ATTEMPTED"), (), (), False, False))
        self.assertEqual(target.parent.exists(), False)

    # SY 369-376: a write failure AFTER a completed publish (json.dump raising) still fails the run, but keeps the
    # observed phase COMPLETE and pointer_state READBACK_CONFIRMED; the reserved file stays empty.
    def test_TS_11d_late_outcome_write_failure_keeps_the_observed_state(self):
        fx = self.fixture()
        target = self.tmp / "outcome-late.json"
        with mock.patch.object(SY.json, "dump", side_effect=OSError("synthetic")):
            r = self.sync(fx, outcome_path=target)
        self.assertRow(r.row(), (1, ("FAILED", "COMPLETE", "OUTCOME_WRITE_FAILED", "READBACK_CONFIRMED"), HAPPY_OPS,
                                 NEW5_PTR_CHG, True, False))
        self.assertEqual((target.read_bytes(), self.kv.store[POINTER_KEY]), (b"", fx.ptr_raw.encode("utf-8")))

    # TS-12: the real publisher output (PB.main, --snapshot-root tmp) synced by SY over the fake KV.
    def test_TS_12_publisher_output_syncs(self):
        snap = self.tmp / "snap"
        built = run_pb(PB, snap)
        self.assertEqual(built.exit, 0)
        objects = json.loads((built.run_dir / "objects.json").read_text(encoding="utf-8"))
        ptr_text = (built.run_dir / "pointer.raw.json").read_text(encoding="utf-8").strip()  # SY 213 strips
        r = run_sy(SY, self.kv, built.run_dir, self.ledger, {})
        objects_ok = all(key in self.kv.store and sha(self.kv.store[key].decode("utf-8")) == sha(body)
                         for key, body in objects.items())
        pointer_ok = self.kv.store.get(POINTER_KEY) == ptr_text.encode("utf-8")
        pointer_last = [key for key, _ in r.kv.puts][-1] == POINTER_KEY
        row = Row(("exit", "outcome", "objects_ok", "pointer_ok", "pointer_last", "object_count"),
                  (r.exit, r.outcome, objects_ok, pointer_ok, pointer_last, len(objects)))
        self.assertRow(row, (0, Q_OK, True, True, True, len(PB.OBJECT_KEYS) + 2))  # PB 1094-1095: OBJECT_KEYS + macro + seal


if __name__ == "__main__":
    unittest.main()
