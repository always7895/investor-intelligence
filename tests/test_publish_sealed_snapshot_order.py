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

    # TP-2b DESIGNED. PROMOTED_AT feeds only pointer_text (PB 1008-1015) and summary.json (PB 1116); it feeds neither
    # the seal manifest (PB 988-1005), the run id (digest_seed 339, run_suffix 340, run_id 342) nor any body
    # (no lazy coverage body without lazy flags). F-PB-OVERWRITE: the existing run dir is overwritten silently
    # (PB 1092 mkdir exist_ok, 1099/1101 write_bytes), so a re-run with a different promotion time rewrites the pointer.
    def test_TP_2b_promoted_at_changes_only_the_pointer(self):
        snap = self.tmp / "snap"
        first = run_pb(PB, snap)
        objects_before = read(first.run_dir, "objects.json")
        pointer_before = read(first.run_dir, "pointer.raw.json")
        with mock.patch.object(PB, "PROMOTED_AT", "2026-09-16T14:30:00Z"):
            second = run_pb(PB, snap)
        row = Row(("exit", "run_id_same", "objects_changed", "pointer_changed"),
                  (second.exit, second.run_id == first.run_id,
                   read(second.run_dir, "objects.json") != objects_before,
                   read(second.run_dir, "pointer.raw.json") != pointer_before))
        self.assertRow(row, (0, True, False, True))
        self.assertEqual(PB.PROMOTED_AT, "2026-09-15T13:00:00Z")  # precondition: the golden value (PB 62) was patched only inside the second run
        self.assertEqual(b"2026-09-16T14:30:00Z" in read(second.run_dir, "pointer.raw.json"), True)


if __name__ == "__main__":
    unittest.main()
