"""Synthetic TASK0 acquisition fixture through the real offline publisher.

Owned temp outputs are retained for audited fixture export; never publish them.
The historical corpus and its original stale fixture are never re-stamped.
"""
from contextlib import ExitStack, redirect_stdout
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import publish_sealed_snapshot as publisher

FIXTURE = ROOT / "cloud/test/fixtures/task0-phase1d"
ASSEMBLY = "2026-09-17T09:24:10Z"
ACQUIRED = "2026-09-17T09:00:00Z"


def generate(snapshot_root):
    """Only acquisition inputs are synthetic; writer/claim/seal/pointer are real."""
    original = json.loads((FIXTURE / "objects.json").read_bytes())
    pointer = json.loads((FIXTURE / "pointer.raw.json").read_bytes())
    prefix = f"snapshot:{pointer['run_id']}:"
    report = json.loads(original[prefix + "v213:top20-report:latest"])
    macro = json.loads(original[prefix + publisher.MACRO_KEY])
    clocks = dict.fromkeys(("EVALUATED_AT", "GENERATED_AT", "CLAIMED_AT",
                           "PROMOTED_AT", "PUBLISHED_DATA_AS_OF"), ASSEMBLY)
    clocks.update(RETRIEVED_AT=ACQUIRED, EVIDENCE_CAPTURE_AT=ACQUIRED,
                  LIVE_NOW=datetime(2026, 9, 17, 9, 24, 10, tzinfo=timezone.utc),
                  LIVE_STAMP="20260917T092410Z")
    with ExitStack() as stack:
        for name, value in clocks.items():
            stack.enter_context(mock.patch.object(publisher, name, value))
        # Close ambient data reads at their input boundaries. Neither the
        # report producer nor the activation/seal/digest writer is mocked.
        stack.enter_context(mock.patch.object(publisher.company_deep_report, "load_reports",
                                             return_value=report.get("deep_reports", {})))
        stack.enter_context(mock.patch.object(publisher.macro_builder, "load_rotation_candidates",
                                             return_value=([], {}, None)))
        stack.enter_context(mock.patch.object(publisher.macro_builder, "build_macro_overview_output",
                                             return_value=macro))
        output = stack.enter_context(redirect_stdout(io.StringIO()))
        publisher.main(["--snapshot-root", str(snapshot_root)])
    summary = json.loads(output.getvalue())
    return Path(snapshot_root) / summary["run_id"]


class Task0FixtureBatch05Tests(unittest.TestCase):
    def test_real_writer_binds_fresh_synthetic_acquisition_and_keeps_original_stale(self):
        # H5 confines this retained export to its owned private TEMP directory.
        root = Path(tempfile.mkdtemp(prefix="batch05-task0-export-"))
        generated = generate(root)
        for name in ("objects.json", "pointer.raw.json"):
            self.assertEqual((generated / name).read_bytes(), (FIXTURE / ("fresh-" + name)).read_bytes())
        pointer = json.loads((generated / "pointer.raw.json").read_bytes())
        objects = json.loads((generated / "objects.json").read_bytes())
        prefix = f"snapshot:{pointer['run_id']}:"
        sha = lambda raw: hashlib.sha256(raw.encode("utf-8")).hexdigest()
        seal_raw = objects[prefix + publisher.SEAL_KEY]
        self.assertEqual(pointer["seal_sha256"], sha(seal_raw))
        seal = json.loads(seal_raw)
        self.assertEqual(seal["run_id"], pointer["run_id"])
        self.assertEqual(seal["transaction_id"], pointer["transaction_id"])
        for key, binding in seal["objects"].items():
            raw = objects[prefix + key]
            self.assertEqual(binding["sha256"], sha(raw))
            self.assertEqual(binding["utf8_bytes"], len(raw.encode("utf-8")))
        claim = json.loads(objects[prefix + "v213:activation-claim"])
        for name, digest in claim["payload_digests"].items():
            self.assertEqual(digest, sha(objects[prefix + publisher.PAYLOAD_OBJECT[name]]))
        report = json.loads(objects[prefix + "v213:top20-report:latest"])
        self.assertEqual(report["generated_at"], ASSEMBLY)
        self.assertEqual(report["evidence_capture_at"], ACQUIRED)
        self.assertEqual([row["ticker"] for row in report["records"]], ["GEV", "6501"])
        self.assertTrue(all(row["retrieved_at"] == ACQUIRED and row["test_only_admission"]
                            for row in report["records"]))
        self.assertEqual(hashlib.sha256((FIXTURE / "objects.json").read_bytes()).hexdigest(),
                         "5f775cdd52198594cdff0b121f4daf5278db5ca35e8159574a9d640e5b6ce4b5")
        self.assertEqual(hashlib.sha256((FIXTURE / "pointer.raw.json").read_bytes()).hexdigest(),
                         "8d3125b9a668f226249e23baab6a725c92057ccc6c09322c5665d918d5554e0f")


if __name__ == "__main__":
    unittest.main()
