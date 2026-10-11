"""Write-order and re-run tests for scripts/publish_sealed_snapshot.py (golden path, offline, no KV).

PB.main always gets --snapshot-root <tmp> (the default and II_SNAPSHOT_ROOT point into state/), and the
wall-clock globals PB rewrites under --live-clock are saved and restored around every call. Each row compares
a literal designed from the code; the comment above each row cites the lines it was designed from."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import publish_sealed_snapshot as PB  # noqa: E402
from sealed_kv_fakes import KvTestCase, Row, WriteBytesRecorder, run_pb  # noqa: E402


def read(run_dir, name):
    """Bytes of a run-dir file, or None (never raises: a failed run shows up in the row tuple)."""
    try:
        return (run_dir / name).read_bytes()
    except (OSError, TypeError):
        return None


class PublishRows(KvTestCase):
    def setUp(self):
        super().setUp()
        # The golden path has one wall-clock stamp: the macro overview's generated_at (build_v213_macro_industry_research
        # build_macro_overview_output). A second run in a later second would build different objects.json bytes under
        # the same run id, which PB 1102-1104 refuse; pin that stamp to the golden GENERATED_AT (PB 60) for every row.
        real = PB.macro_builder.build_macro_overview_output

        def pinned(*args, **kwargs):
            overview = real(*args, **kwargs)
            overview["generated_at"] = PB.GENERATED_AT
            return overview

        patcher = mock.patch.object(PB.macro_builder, "build_macro_overview_output", pinned)
        patcher.start()
        self.addCleanup(patcher.stop)

    # PB 1098-1101 write objects.json, then pointer.raw.json (the pointer is committed LAST); 1102-1103 write
    # seven-field-projection.json (the golden path has a Top20 projection); 1135 writes summary.json.
    def test_TP_1_write_order(self):
        snap = self.tmp / "snap"
        with WriteBytesRecorder(snap) as recorder:
            built = run_pb(PB, snap)
        row = Row(("exit", "write_order"), (built.exit, recorder.names))
        self.assertRow(row, (0, ("objects.json", "pointer.raw.json", "seven-field-projection.json", "summary.json")))
        self.assertEqual(recorder.pointer_existed_at("objects.json"), False)  # precondition: pointer absent at the objects write

    # PB 1091-1092 (run_id from the sealed bodies, no clock in the golden path) and 1099-1135 (overwrite in place):
    # a second golden run on the same root reproduces every artifact byte for byte.
    def test_TP_2_golden_twice_is_byte_identical(self):
        snap = self.tmp / "snap"
        first = run_pb(PB, snap)
        files = {name: read(first.run_dir, name) for name in ("objects.json", "pointer.raw.json", "summary.json")}
        second = run_pb(PB, snap)
        row = Row(("exit_1", "exit_2", "objects_same", "pointer_same", "summary_same"),
                  (first.exit, second.exit) + tuple(read(second.run_dir, name) == files[name]
                                                    for name in ("objects.json", "pointer.raw.json", "summary.json")))
        self.assertRow(row, (0, 0, True, True, True))

    # TP-2b, F-PB-OVERWRITE fixed. PROMOTED_AT feeds only pointer_text (PB 1008-1015) and summary.json; it feeds
    # neither the seal manifest (PB 988-1005), the run id (digest_seed 339, run_suffix 340, run_id 342) nor any body
    # (no lazy coverage body without lazy flags). A re-run with a different promotion time therefore builds the same
    # run id with a different pointer: PB 1102-1104 refuse it (SystemExit SEALED_RUN_DIR_CONFLICT) before the mkdir
    # (1105) and any write (1106-1107), no summary is printed, and every artifact of the first run stays byte-identical.
    def test_TP_2b_different_pointer_for_an_existing_run_is_refused(self):
        snap = self.tmp / "snap"
        first = run_pb(PB, snap)
        files = {name: read(first.run_dir, name) for name in ("objects.json", "pointer.raw.json", "summary.json")}
        with mock.patch.object(PB, "PROMOTED_AT", "2026-09-16T14:30:00Z"):
            second = run_pb(PB, snap)
        row = Row(("exit_1", "exit_2", "summary_2", "objects_same", "pointer_same", "summary_same"),
                  (first.exit, second.exit, second.summary) + tuple(read(first.run_dir, name) == files[name]
                                                                    for name in ("objects.json", "pointer.raw.json", "summary.json")))
        self.assertRow(row, (0, "SystemExit", None, True, True, True))
        self.assertEqual(PB.PROMOTED_AT, "2026-09-15T13:00:00Z")  # precondition: the golden value (PB 62) was patched only inside the second run
        self.assertEqual(b"2026-09-16T14:30:00Z" in read(first.run_dir, "pointer.raw.json"), False)

    # TP-2c: a run dir left by a crash between the objects and the pointer write (PB 1106-1107) holds only identical
    # objects.json bytes; PB 1102-1104 accept them, so the re-run completes and writes the same pointer.
    def test_TP_2c_identical_partial_run_dir_is_completed(self):
        snap = self.tmp / "snap"
        first = run_pb(PB, snap)
        pointer = read(first.run_dir, "pointer.raw.json")
        (first.run_dir / "pointer.raw.json").unlink()
        second = run_pb(PB, snap)
        row = Row(("exit_1", "exit_2", "run_id_same", "pointer_restored"),
                  (first.exit, second.exit, second.run_id == first.run_id, read(first.run_dir, "pointer.raw.json") == pointer))
        self.assertRow(row, (0, 0, True, True))
        self.assertEqual(pointer is not None, True)  # precondition: the first run wrote a pointer

    # TP-2d: different objects.json bytes under the same run id (pointer absent) are refused as well (PB 1102-1104
    # compare objects.json too): exit SystemExit, the edited bytes stay and no pointer is written.
    def test_TP_2d_different_objects_for_an_existing_run_are_refused(self):
        snap = self.tmp / "snap"
        first = run_pb(PB, snap)
        (first.run_dir / "pointer.raw.json").unlink()
        (first.run_dir / "objects.json").write_bytes(b'{"edited":"objects"}')
        second = run_pb(PB, snap)
        row = Row(("exit_1", "exit_2", "objects", "pointer"),
                  (first.exit, second.exit, read(first.run_dir, "objects.json"), read(first.run_dir, "pointer.raw.json")))
        self.assertRow(row, (0, "SystemExit", b'{"edited":"objects"}', None))


if __name__ == "__main__":
    unittest.main()
