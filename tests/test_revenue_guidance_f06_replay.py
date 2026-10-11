"""G7 / F06 offline producer -> wire -> sealed run -> staged replay layout (Python half; no KV, no vitest, no network).

tests/fixtures/make_revenue_guidance_f06_replay.py runs the real same-owner export reader, publisher main()
--guidance-machine, activation claim, seal, pointer and stage() over the genuine AUTO producer bytes; the Worker half,
cloud/test/v213-revenue-guidance-f06-replay.test.ts, reads the committed staged layout through the real
pinPublicSnapshot -> loadBottleneckV3 route. These rows prove the committed layout is a fresh regeneration, pin what the
wire carries (the exact producer bytes as content-addressed lazy blobs bound by the seal, the seal bound by the pointer)
and show that a mismatched channel digest or a missing or tampered export is refused before any run directory exists.
Every store is a temporary directory."""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "fixtures"))
sys.path.insert(0, str(ROOT / "scripts"))

import make_revenue_guidance_f06_replay as f06  # noqa: E402
import revenue_guidance_machine as machine  # noqa: E402

REGENERATE = "python -I -B -X utf8 tests/fixtures/make_revenue_guidance_f06_replay.py"
# Literal on purpose (tests/test_publish_sealed_snapshot_keyset.py EXPECTED_BODY_KEYS): the 13 OBJECT_KEYS, the macro
# overview, then the two lazy guidance objects in sorted order (publish_sealed_snapshot.build_seal).
EAGER = ["v21:top20:latest", "scores:latest", "source_views:latest", "source_plan:latest", "reports:latest",
         "reports:morning:latest", "reports:evening:latest", "last_successful_pipeline_timestamp",
         "v212:top20-report:latest", "v213:top20-report:latest", "v213:source-federation:latest",
         "v213:source-independence:latest", "v213:activation-claim", "v213:macro-industry:latest"]
LAZY = ["v213:bottleneck-top20:v3", "v213:revenue-guidance-binding:v1"]


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class F06ReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = f06.generate()

    def test_committed_worker_fixture_is_a_fresh_regeneration(self):
        name = f06.FIXTURE_PATH.relative_to(ROOT).as_posix()
        self.assertTrue(f06.FIXTURE_PATH.is_file(), f"{name} is missing; regenerate with {REGENERATE}")
        self.assertEqual(f06.serialize(self.document), f06.FIXTURE_PATH.read_text(encoding="utf-8"),
                         f"{name} is stale; regenerate with {REGENERATE}")
        self.assertEqual(f06.serialize(f06.generate()), f06.serialize(self.document))

    def test_wire_carries_the_exact_producer_bytes_bound_by_seal_and_pointer(self):
        doc = self.document
        self.assertEqual((doc["schema"], doc["scope"], doc["cutoff"]), (f06.SCHEMA, f06.SCOPE, "2026-02-27T13:00:00Z"))
        self.assertEqual((doc["top20_state"], doc["top20_reason"], doc["lazy_objects"]),
                         ("INSUFFICIENT", f06.TOP20_REASON, 2))
        index = list(doc["index"].items())
        self.assertEqual(index[0], ("snapshot:current", "k0.txt"))
        self.assertEqual([name for _key, name in index], [f"k{number}.txt" for number in range(len(index))])
        kv = {key: doc["files"][name] for key, name in index}
        pointer = json.loads(kv["snapshot:current"])
        run_id = pointer["run_id"]
        self.assertEqual((run_id, run_id[:17]), (doc["run_id"], "20260227T130000Z-"))
        prefix = f"snapshot:{run_id}:"
        seal_raw = kv[prefix + "v213:snapshot-seal:v1"]
        self.assertEqual(pointer["seal_sha256"], sha(seal_raw))
        seal = json.loads(seal_raw)
        self.assertEqual(list(seal["objects"]), EAGER + LAZY)
        self.assertEqual((seal["run_id"], seal["transaction_id"], seal["generated_at"], seal["public_data_as_of"]),
                         (run_id, pointer["transaction_id"], f06.CUTOFF, f06.CUTOFF))
        self.assertEqual((pointer["public_data_as_of"], pointer["promoted_at"]), (f06.CUTOFF, f06.CUTOFF))
        for name in EAGER:
            body = kv[prefix + name]
            self.assertEqual(seal["objects"][name], {"sha256": sha(body), "utf8_bytes": len(body.encode("utf-8"))}, name)
        report, binding = f06.producer_bundle()
        blobs = []
        for name, raw in zip(LAZY, (report, binding)):
            entry = seal["objects"][name]
            self.assertEqual(entry, {"sha256": hashlib.sha256(raw).hexdigest(), "utf8_bytes": len(raw)}, name)
            self.assertEqual(kv["blob:v1:" + entry["sha256"]].encode("utf-8"), raw, name)
            self.assertNotIn(prefix + name, kv)  # lazy objects are stored only under their content address
            blobs.append("blob:v1:" + entry["sha256"])
        self.assertEqual(sorted(key for key in kv if key.startswith("blob:v1:")), sorted(blobs))
        self.assertEqual(len(kv), 1 + len(EAGER) + 1 + len(LAZY))
        # The Python mirror of the Worker's sealed selection accepts the staged bytes under the sealed digests.
        selected = machine.validate_public_bundle(report, binding, seal["objects"][LAZY[0]]["sha256"],
                                                  seal["objects"][LAZY[1]]["sha256"])
        self.assertEqual((selected["cutoff"], selected["report_sha256"], selected["issuers"]["NVDA"]["disposition"]),
                         (f06.CUTOFF, hashlib.sha256(report).hexdigest(), "AUTO_VERIFIED"))
        top20 = kv[prefix + "v213:top20-report:latest"]
        self.assertEqual(json.loads(top20), {"status": "INSUFFICIENT_EVIDENCE", "reason": f06.TOP20_REASON, "records": []})
        claim = json.loads(kv[prefix + "v213:activation-claim"])
        self.assertEqual((claim["run_id"], claim["claimed_at"], claim["payload_digests"]["v213_top20_report_json"]),
                         (run_id, f06.CUTOFF, sha(top20)))
        self.assertEqual(kv[prefix + "last_successful_pipeline_timestamp"], f06.CUTOFF)
        macro = json.loads(kv[prefix + "v213:macro-industry:latest"])
        self.assertEqual((macro["generated_at"], macro["status"], macro["qualified_count"]),
                         (f06.CUTOFF, "SHORTFALL_NOT_QUALIFIED", 0))

    def test_mismatched_or_missing_channel_input_is_refused_before_any_run_dir(self):
        report, binding = f06.producer_bundle()
        good = (machine.sha256(report), machine.sha256(binding))
        zero = "0" * 64
        # case: (binding file bytes or None, report digest, binding digest, export name, --guidance-machine, reason)
        cases = {
            "report_digest": (binding, zero, good[1], f06.EXPORT_ID, True, "MACHINE_INPUTS_UNAVAILABLE"),
            "binding_digest": (binding, good[0], zero, f06.EXPORT_ID, True, "MACHINE_INPUTS_UNAVAILABLE"),
            "swapped_digests": (binding, good[1], good[0], f06.EXPORT_ID, True, "MACHINE_INPUTS_UNAVAILABLE"),
            "export_tampered": (binding + b" ", good[0], good[1], f06.EXPORT_ID, True, "MACHINE_INPUTS_UNAVAILABLE"),
            "export_missing": (None, good[0], good[1], f06.EXPORT_ID, True, "MACHINE_EXPORT_UNAVAILABLE"),
            "export_name": (binding, good[0], good[1], f06.EXPORT_ID.upper(), True, "MACHINE_EXPORT_UNAVAILABLE"),
            "flags_without_machine": (binding, good[0], good[1], f06.EXPORT_ID, False, "MACHINE_INPUTS_UNAVAILABLE"),
        }
        for case, (staged_binding, report_sha, binding_sha, export_id, enabled, reason) in cases.items():
            with self.subTest(case=case), tempfile.TemporaryDirectory(prefix="ii-f06-refuse-") as tmp:
                base = Path(tmp).resolve()
                f06.write_export(base / "guidance-public-exports", report, staged_binding)
                argv = f06.machine_argv(base, report_sha, binding_sha, export_id)
                if not enabled:
                    argv.remove("--guidance-machine")
                with self.assertRaises(machine.MachinePublicationBlocked) as raised:
                    f06.run_publisher(argv, base / "guidance-public-exports")
                self.assertEqual(raised.exception.reason, reason)
                self.assertFalse((base / "snapshots").exists())


if __name__ == "__main__":
    unittest.main()
