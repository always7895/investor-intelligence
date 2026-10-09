"""Transaction tests for scripts/rollback_sealed_snapshot.py over a fake KV (no network, no credentials,
no real wrangler/npx, no process launched at all). Each row runs RB.main(argv) against a per-row plain tmp
ROOT (RB.ROOT and RB.SNAP_DIR patched, never the real repository; no git repository exists) and compares a
literal (exit, outcome, ops, store diff, ledger, stage) designed from the code; RB's tracked check
(`git ls-files`, RB 87-92) is served by a subprocess fake from the row's declared tracked set. The comment
above each row cites the lines it was designed from. TR-7 chains the real sync (SY.main) and rollback over
one fake KV; TR-8 is the characterized unpatched-kv-layer row. Synthetic values only."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import rollback_sealed_snapshot as RB  # noqa: E402
import sync_sealed_snapshot_kv as SY  # noqa: E402
from sealed_kv_fakes import (  # noqa: E402
    NOWRITE, POINTER_KEY, RUN, RUN2, WRITE_THEN_FAIL, FakeKV, Fixture, KvTestCase, Q_OK, make_rb_root, run_rb,
    run_sy)

GET_O = (("get", "O1"), ("get", "O2"), ("get", "O3"))
GET_PTR = (("get", "POINTER"),)
PUT_PTR = (("put", "POINTER"),)
GET_B5 = (("get", "B1"), ("get", "B2"), ("get", "B3"), ("get", "S1"), ("get", "S2"))
PTR_CHG = (("POINTER", "CHG"),)


class RbRows(KvTestCase):
    def setUp(self):
        super().setUp()
        self.target = Fixture(RUN, "rb")
        self.other = Fixture(RUN2, "rb")
        self.repo, self.tracked = make_rb_root(self.tmp, [self.target, self.other])
        self.assertFalse(self.repo.is_relative_to(ROOT.resolve()))
        self.names = dict(self.target.names)
        self.target_pointer = self.target.ptr_raw.encode("utf-8")
        self.other_pointer = self.other.ptr_raw.encode("utf-8")
        store = self.target.store_bytes()
        store[POINTER_KEY] = self.other_pointer
        self.kv = FakeKV(store)

    def rollback(self, *flags, run=RUN, names=None, kv=None, seam="A", tracked=None):
        return run_rb(RB, kv or self.kv, self.repo, self.tracked if tracked is None else tracked,
                      ["--target-run", run, *flags], names or self.names, seam=seam)

    # RB 119-141, 135-141: verify the three objects, read the pointer, put the target pointer, read it back.
    def test_TR_1_apply_rolls_back(self):
        r = self.rollback("--apply")
        self.assertRow(r.row, (0, "ROLLED_BACK", GET_O + GET_PTR + PUT_PTR + GET_PTR, PTR_CHG, False, False))
        self.assertEqual(self.kv.store[POINTER_KEY], self.target_pointer)

    # RB 137-138: the second POINTER read (the readback) differs, the abort is exit 1; the pointer WAS written.
    def test_TR_2_pointer_readback_corrupt(self):
        self.kv.corrupt_get(POINTER_KEY, 2, b"corrupt-readback")
        r = self.rollback("--apply")
        self.assertRow(r.row, (1, "ABORT", GET_O + GET_PTR + PUT_PTR + GET_PTR, PTR_CHG, False, False))
        self.assertEqual(self.kv.store[POINTER_KEY], self.target_pointer)

    # RB 135-136: a failed put aborts; NOWRITE leaves the old pointer in place.
    def test_TR_3_pointer_put_nowrite(self):
        self.kv.fail_put(POINTER_KEY, 1, NOWRITE)
        r = self.rollback("--apply")
        self.assertRow(r.row, (1, "ABORT", GET_O + GET_PTR + PUT_PTR, (), False, False))
        self.assertEqual(self.kv.store[POINTER_KEY], self.other_pointer)

    # F-RB-MSG: RB 136 says "previous pointer untouched" for every failed put, but a put that wrote and then
    # failed has already replaced the pointer; the row asserts the stored bytes, never the message.
    def test_TR_3b_pointer_put_write_then_fail(self):
        self.kv.fail_put(POINTER_KEY, 1, WRITE_THEN_FAIL)
        r = self.rollback("--apply")
        self.assertRow(r.row, (1, "ABORT", GET_O + GET_PTR + PUT_PTR, PTR_CHG, False, False))
        self.assertEqual(self.kv.store[POINTER_KEY], self.target_pointer)

    # RB 105-113: the first unverified object aborts the run; no later object is read and nothing is written.
    def test_TR_4a_object_missing(self):
        del self.kv.store[self.target.key["O2"]]
        r = self.rollback("--apply")
        self.assertRow(r.row, (1, "ABORT", (("get", "O1"), ("get", "O2")), (), False, False))

    def test_TR_4b_object_altered(self):
        self.kv.store[self.target.key["O2"]] = b"altered-object"
        r = self.rollback("--apply")
        self.assertRow(r.row, (1, "ABORT", (("get", "O1"), ("get", "O2")), (), False, False))

    # RB 121-123: a live pointer equal to the target text is a NOOP (second apply writes nothing).
    def test_TR_5_apply_twice_is_noop(self):
        first = self.rollback("--apply")
        self.assertRow(first.row, (0, "ROLLED_BACK", GET_O + GET_PTR + PUT_PTR + GET_PTR, PTR_CHG, False, False))
        second = self.rollback("--apply")
        self.assertRow(second.row, (0, "NOOP", GET_O + GET_PTR, (), False, False))

    # RB 132-134: without --apply the run is a DRY_RUN that reads everything and writes nothing.
    def test_TR_6_dry_run(self):
        pointer_before = self.kv.store[POINTER_KEY]
        r = self.rollback()
        self.assertRow(r.row, (0, "DRY_RUN", GET_O + GET_PTR, (), False, False))
        self.assertEqual(r.document["from_run"], RUN2)
        self.assertEqual(pointer_before, self.other_pointer)  # precondition: the valid RUN2 pointer ...
        self.assertEqual(pointer_before != self.target_pointer, True)  # ... which differs from the target

    # RB 87-92: the target run dir exists locally but `git ls-files` lists nothing for it (the declared tracked set
    # holds only the other run), so the run is refused before any kv read: exit 1, ABORT, no ops, nothing written.
    def test_TR_9_target_run_not_tracked(self):
        only_other = frozenset(path for path in self.tracked if f"/{RUN2}/" in path)
        r = self.rollback("--apply", tracked=only_other)
        self.assertRow(r.row, (1, "ABORT", (), (), False, False))
        self.assertEqual(len(only_other), 1)  # precondition: the other run stays tracked, the target is not
        self.assertEqual(r.git_calls, [(("git", "ls-files", f"state/v213-snapshots/{RUN}/pointer.raw.json"), str(self.repo))])
        self.assertEqual(self.kv.store[POINTER_KEY], self.other_pointer)

    # RB 85-86: pointer.raw.json is missing from the target run dir, so the run is refused as incomplete before the
    # tracked check and before any kv read: exit 1, ABORT, no ops, no git call, nothing written.
    def test_TR_9b_target_pointer_file_missing(self):
        (self.repo / "state" / "v213-snapshots" / RUN / "pointer.raw.json").unlink()
        r = self.rollback("--apply")
        self.assertRow(r.row, (1, "ABORT", (), (), False, False))
        self.assertEqual(r.git_calls, [])
        self.assertEqual(self.kv.store[POINTER_KEY], self.other_pointer)

    # TR-7: real sync passes (SY seam A) into one FakeKV, then a rollback over a repo holding both runs.
    def _chain(self):
        sy_one = Fixture(RUN, "sy")
        sy_two = Fixture(RUN2, "sy")
        self.repo, self.tracked = make_rb_root(self.tmp / "chain", [sy_one, sy_two])
        for fixture in (sy_one, sy_two):
            fixture.write_to(self.tmp / "runs" / fixture.run)
        self.chain_kv = FakeKV({POINTER_KEY: b'{"run_id":"previous-pointer-placeholder"}'})
        ledger = self.tmp / "ledger.json"
        first = run_sy(SY, self.chain_kv, self.tmp / "runs" / RUN, ledger, sy_one.names)
        return sy_one, sy_two, ledger, first

    # (a) RUN published, RUN2 fails at its second object put: the pointer is RUN's, so rolling back to RUN is a NOOP.
    def test_TR_7a_failed_second_sync_then_rollback_to_first_is_noop(self):
        sy_one, sy_two, ledger, first = self._chain()
        self.assertRow(first.row(), (0, Q_OK, (("put", "B1"), ("put", "B2"), ("put", "B3"), ("put", "S1"), ("put", "S2")) + GET_B5 + (("put", "POINTER"), ("get", "POINTER")),
                                     (("B1", "NEW"), ("B2", "NEW"), ("B3", "NEW"), ("POINTER", "CHG"), ("S1", "NEW"), ("S2", "NEW")), True, False))
        self.chain_kv.fail_put(sy_two.key["B2"], 1, NOWRITE)
        second = run_sy(SY, self.chain_kv, self.tmp / "runs" / RUN2, ledger, sy_two.names)
        self.assertEqual(second.exit, 1)
        r = self.rollback("--apply", kv=self.chain_kv, names=sy_one.names)
        self.assertRow(r.row, (0, "NOOP", GET_B5 + GET_PTR, (), False, False))
        self.assertEqual([op for op in r.ops if op[0] == "put"], [])

    # (b) RUN2 reached the pointer (put done, readback altered, pointer is RUN2): rollback to RUN rewrites it.
    def test_TR_7b_unconfirmed_second_sync_then_rollback_restores_first(self):
        sy_one, sy_two, ledger, first = self._chain()
        self.assertEqual(first.exit, 0)
        self.chain_kv.corrupt_get(POINTER_KEY, 1, b"altered-pointer")
        second = run_sy(SY, self.chain_kv, self.tmp / "runs" / RUN2, ledger, sy_two.names)
        self.assertEqual(second.exit, 1)
        self.assertEqual(self.chain_kv.store[POINTER_KEY], sy_two.ptr_raw.encode("utf-8"))
        r = self.rollback("--apply", kv=self.chain_kv, names=sy_one.names)
        self.assertRow(r.row, (0, "ROLLED_BACK", GET_B5 + GET_PTR + PUT_PTR + GET_PTR, PTR_CHG, False, False))
        self.assertEqual(self.chain_kv.store[POINTER_KEY], sy_one.ptr_raw.encode("utf-8"))
        self.assertEqual(r.ops[-2:], PUT_PTR + GET_PTR)

    # (c) RUN2's sync stopped after B1 (B2 absent): rolling back TO RUN2 aborts at B2 without any write.
    def test_TR_7c_rollback_to_partially_published_run_aborts(self):
        sy_one, sy_two, ledger, first = self._chain()
        self.assertEqual(first.exit, 0)
        self.chain_kv.fail_put(sy_two.key["B2"], 1, NOWRITE)
        second = run_sy(SY, self.chain_kv, self.tmp / "runs" / RUN2, ledger, sy_two.names)
        self.assertEqual(second.exit, 1)
        r = self.rollback("--apply", run=RUN2, kv=self.chain_kv, names=sy_two.names)
        self.assertRow(r.row, (1, "ABORT", (("get", "B1"), ("get", "B2")), (), False, False))

    # TR-8 CHARACTERIZED, F-RB-NPX: RB runs an unlocked `npx --yes wrangler` (SY 48 forbids npx --yes). The row
    # leaves RB.wrangler_kv_get/put unpatched; only subprocess.run is faked (kv argv by FakeKV, `git ls-files` by the
    # tracked set; nothing is launched). Argv pins are symbolic (RB 59, 73-74).
    def test_TR_8_characterized_real_kv_layer_argv(self):
        stage = self.repo / "data" / "cache" / "rollback-stage.txt"

        def get_argv(key):
            return [RB.NPX, "--yes", "wrangler", "kv", "key", "get", key, "--namespace-id", RB.NS, "--remote"]

        def put_argv(key):
            return [RB.NPX, "--yes", "wrangler", "kv", "key", "put", key, "--path", str(stage), "--namespace-id", RB.NS, "--remote"]

        r = self.rollback("--apply", seam="B")
        self.assertRow(r.row, (0, "ROLLED_BACK", GET_O + GET_PTR + PUT_PTR + GET_PTR, PTR_CHG, False, False))
        keys = [self.target.key["O1"], self.target.key["O2"], self.target.key["O3"], POINTER_KEY]
        self.assertEqual(self.kv.argv_log, [get_argv(k) for k in keys] + [put_argv(POINTER_KEY), get_argv(POINTER_KEY)])
        self.assertEqual(stage.read_bytes(), self.target_pointer)
        self.assertEqual(all("--remote" in argv and RB.NS in argv for argv in self.kv.argv_log), True)


if __name__ == "__main__":
    unittest.main()
