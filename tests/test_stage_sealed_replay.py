"""Byte-layout tests for stage() of scripts/stage_sealed_replay.py (offline; vitest never runs, replay() only with a fake runner).

stage(run_dir, out) turns a sealed run (objects.json + pointer.raw.json) into the k<N>.txt files plus index.json that
cloud/test/live-kv-replay.test.ts reads. No test of the repository executes it, so these rows pin the exact bytes,
the file numbering, the index key order, the write order and the failure behaviour. Every output root is a temporary
directory outside the repository; subprocess.run, vitest_runner and the network are guarded (StageCase, also the base of the machine-binding rows). Each row compares a
literal designed from the code; the comment above each row cites the lines it was designed from."""
from __future__ import annotations

import hashlib
import json
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import stage_sealed_replay as replay  # noqa: E402

LF = "\n"
RUN = "20261001T000000Z-0123456789ab"
K_SEAL = "snapshot:" + RUN + ":v213:snapshot-seal:v1"
K_MACRO = "snapshot:" + RUN + ":v213:macro-industry:latest"
BODY_SEAL = '{"schema_version":1,"objects":{}}'
BODY_BLOB = '{"lazy":"synthetic"}'
K_BLOB = "blob:v1:" + hashlib.sha256(BODY_BLOB.encode("utf-8")).hexdigest()
BODY_MACRO = "合成產業：台積電 é\r\nsecond line\n"
# Insertion order is deliberately not sorted (sorted order would be K_BLOB, K_MACRO, K_SEAL).
OBJECTS_BYTES = json.dumps({K_SEAL: BODY_SEAL, K_BLOB: BODY_BLOB, K_MACRO: BODY_MACRO},
                           ensure_ascii=False, separators=(",", ":")).encode("utf-8")
POINTER_BYTES = ('{"schema_version":2,"run_id":"%s","seal_sha256":"seal-%s"}' % (RUN, RUN) + LF).encode("utf-8")
INDEX_BYTES = ('{"snapshot:current": "k0.txt", "%s": "k1.txt", "%s": "k2.txt", "%s": "k3.txt"}'
               % (K_SEAL, K_BLOB, K_MACRO)).encode("ascii")
FULL_LISTING = (("index.json", INDEX_BYTES), ("k0.txt", POINTER_BYTES), ("k1.txt", BODY_SEAL.encode("utf-8")),
                ("k2.txt", BODY_BLOB.encode("utf-8")), ("k3.txt", BODY_MACRO.encode("utf-8")))
FIELDS_1 = ("outcome", "top_level", "listing", "index_order", "write_log", "guard_counts")
FIELDS_LIST = ("outcome", "listing", "index_order")
FIELDS_FAIL = ("outcome", "out_exists")


def outcome_of(fn):
    """("RESULT", value) or ("RAISED", exception class name); never raises."""
    try:
        return ("RESULT", fn())
    except Exception as error:  # noqa: BLE001 - the class name is the row's observation
        return ("RAISED", type(error).__name__)


def diff_fields(names, got, want):
    fields = [name for name, a, b in zip(names, got, want) if a != b]
    if len(got) != len(want):
        fields.append("arity")
    return "DIFF_FIELDS=" + ",".join(fields)


class StageCase(unittest.TestCase):
    def setUp(self):
        self.counts = {"run": 0, "vitest": 0}

        def blocked(label):
            def refuse(*args, **kwargs):
                self.counts[label] += 1
                raise AssertionError("guard: " + label + " must never run")
            return refuse

        def refuse_network(*args, **kwargs):
            raise AssertionError("guard: network must never be used")

        self.patchers = [
            mock.patch.object(replay.subprocess, "run", side_effect=blocked("run")),
            mock.patch.object(replay, "vitest_runner", side_effect=blocked("vitest")),
            mock.patch.object(socket, "create_connection", side_effect=refuse_network),
            mock.patch.object(socket, "getaddrinfo", side_effect=refuse_network),
        ]
        for patcher in self.patchers:
            patcher.start()
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        self.run_dir = self.base / "run"
        self.run_dir.mkdir()
        self.out = self.base / "nested" / "kv"
        self.assertEqual(self.base.is_relative_to(ROOT.resolve()), False)
        self.assertEqual(self.out.resolve().is_relative_to(ROOT.resolve()), False)

    def tearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.tmp.cleanup()

    def fixture(self, objects=OBJECTS_BYTES, pointer=POINTER_BYTES):
        if objects is not None:
            (self.run_dir / "objects.json").write_bytes(objects)
        if pointer is not None:
            (self.run_dir / "pointer.raw.json").write_bytes(pointer)

    def staged(self):
        """Run stage() once; returns the observation dict (the call is the only code that writes under out)."""
        log = []
        base = self.base
        original_bytes, original_text = Path.write_bytes, Path.write_text

        def entry(kind, path):
            try:
                return (kind, Path(path).relative_to(base).as_posix())
            except ValueError:
                return ("OUTSIDE", str(path))

        def write_bytes(path, data):
            log.append(entry("write_bytes", path))
            return original_bytes(path, data)

        def write_text(path, data, *args, **kwargs):
            log.append(entry("write_text", path))
            return original_text(path, data, *args, **kwargs)

        with mock.patch.object(Path, "write_bytes", write_bytes), mock.patch.object(Path, "write_text", write_text):
            outcome = outcome_of(lambda: replay.stage(self.run_dir, self.out))
        listing = tuple(sorted((p.name, p.read_bytes()) for p in self.out.iterdir())) if self.out.is_dir() else ()
        index_path = self.out / "index.json"
        index_order = tuple(json.loads(index_path.read_bytes().decode("utf-8"))) if index_path.is_file() else None
        return {"outcome": outcome, "top_level": tuple(sorted(p.name for p in self.base.iterdir())),
                "listing": listing, "index_order": index_order, "write_log": tuple(log),
                "guard_counts": (self.counts["run"], self.counts["vitest"]), "out_exists": self.out.exists()}


class StageRows(StageCase):
    # SR 36-46: objects.json is read (36), the pointer bytes are read unstripped (37), the run id is taken from the
    # pointer (38), the missing out directory and its parent are created (39, parents=True), the pointer is written
    # first as k0.txt (41), the bodies follow in objects.json insertion order from k1 (42-44), and index.json is last (45).
    def test_SR_1_byte_layout_happy_path(self):
        self.fixture()
        seen = self.staged()
        got = tuple(seen[name] for name in FIELDS_1)
        want = (("RESULT", RUN), ("nested", "run"), FULL_LISTING, ("snapshot:current", K_SEAL, K_BLOB, K_MACRO),
                (("write_bytes", "nested/kv/k0.txt"), ("write_bytes", "nested/kv/k1.txt"),
                 ("write_bytes", "nested/kv/k2.txt"), ("write_bytes", "nested/kv/k3.txt"),
                 ("write_text", "nested/kv/index.json")), (0, 0))
        self.assertEqual(got, want, diff_fields(FIELDS_1, got, want))

    # SR 43 encodes each body as UTF-8 and writes the bytes untouched (no newline translation): the CJK text and the
    # e-acute stay UTF-8, the embedded CR LF pair and the trailing LF survive.
    def test_SR_2_non_ascii_and_line_endings_are_exact(self):
        self.fixture()
        seen = self.staged()
        k3 = dict(seen["listing"]).get("k3.txt", b"")
        names = ("outcome", "k3_bytes", "has_crlf", "has_trailing_lf")
        got = (seen["outcome"], k3, b"\r\n" in k3, k3.endswith(b"\n"))
        want = (("RESULT", RUN), BODY_MACRO.encode("utf-8"), True, True)
        self.assertEqual(got, want, diff_fields(names, got, want))
        self.assertEqual(k3.count(b"\r"), 1)

    # SR 40 starts the index with the pointer entry, 41 writes k0 from the pointer; with no objects the loop 42-44
    # never runs, so only k0.txt and an index with one entry exist.
    def test_SR_3_empty_objects(self):
        self.fixture(objects=b"{}")
        seen = self.staged()
        got = tuple(seen[name] for name in FIELDS_LIST)
        want = (("RESULT", RUN), (("index.json", b'{"snapshot:current": "k0.txt"}'), ("k0.txt", POINTER_BYTES)),
                ("snapshot:current",))
        self.assertEqual(got, want, diff_fields(FIELDS_LIST, got, want))

    # F-STAGE-STALE fixed, SR 43-44: an existing out directory that is not empty is refused before any write, so a
    # stale k9.txt can never sit next to a new index; the old files stay as they were and no index.json appears.
    def test_SR_4_existing_nonempty_out_directory_is_refused(self):
        self.fixture()
        self.out.mkdir(parents=True)
        (self.out / "k0.txt").write_bytes(b"OLD")
        (self.out / "k9.txt").write_bytes(b"STALE")
        seen = self.staged()
        got = tuple(seen[name] for name in FIELDS_LIST)
        want = (("RAISED", "FileExistsError"), (("k0.txt", b"OLD"), ("k9.txt", b"STALE")), None)
        self.assertEqual(got, want, diff_fields(FIELDS_LIST, got, want))
        self.assertEqual(seen["write_log"], ())

    # SR 43 and 45 (exist_ok=True): an existing EMPTY out directory is still accepted and staged as in SR-1.
    def test_SR_4b_existing_empty_out_directory_is_used(self):
        self.fixture()
        self.out.mkdir(parents=True)
        seen = self.staged()
        got = tuple(seen[name] for name in FIELDS_LIST)
        want = (("RESULT", RUN), FULL_LISTING, ("snapshot:current", K_SEAL, K_BLOB, K_MACRO))
        self.assertEqual(got, want, diff_fields(FIELDS_LIST, got, want))

    # SR 36-39 read objects (36), pointer (37) and the run id (38) before mkdir (39): a failure leaves no out directory.
    def test_SR_5a_missing_pointer_leaves_no_out(self):
        self.fixture(pointer=None)
        seen = self.staged()
        got = (seen["outcome"], seen["out_exists"])
        want = (("RAISED", "FileNotFoundError"), False)
        self.assertEqual(got, want, diff_fields(FIELDS_FAIL, got, want))

    # SR 38: a pointer without run_id raises KeyError before the mkdir at 39.
    def test_SR_5b_pointer_without_run_id_leaves_no_out(self):
        self.fixture(pointer=b'{"schema_version":2}')
        seen = self.staged()
        got = (seen["outcome"], seen["out_exists"])
        want = (("RAISED", "KeyError"), False)
        self.assertEqual(got, want, diff_fields(FIELDS_FAIL, got, want))

    # SR 36: malformed objects.json raises JSONDecodeError at the first read.
    def test_SR_5c_malformed_objects_leaves_no_out(self):
        self.fixture(objects=b"{not json")
        seen = self.staged()
        got = (seen["outcome"], seen["out_exists"])
        want = (("RAISED", "JSONDecodeError"), False)
        self.assertEqual(got, want, diff_fields(FIELDS_FAIL, got, want))

    # SR 36: a missing objects.json raises FileNotFoundError at the first read.
    def test_SR_5d_missing_objects_leaves_no_out(self):
        self.fixture(objects=None)
        seen = self.staged()
        got = (seen["outcome"], seen["out_exists"])
        want = (("RAISED", "FileNotFoundError"), False)
        self.assertEqual(got, want, diff_fields(FIELDS_FAIL, got, want))

    # SR 38 str(): a numeric run_id is returned as text; SR 41 keeps the pointer bytes unchanged.
    def test_SR_6_numeric_run_id_is_returned_as_text(self):
        pointer = b'{"run_id":12345}'
        self.fixture(pointer=pointer)
        seen = self.staged()
        k0 = dict(seen["listing"]).get("k0.txt")
        names = ("outcome", "k0_bytes")
        got = (seen["outcome"], k0)
        want = (("RESULT", "12345"), pointer)
        self.assertEqual(got, want, diff_fields(names, got, want))

    # F-STAGE-CURRENT-COLLISION fixed, SR 41-42: an objects.json key equal to the pointer key would replace the
    # pointer's index entry (46/50) and orphan k0.txt, so stage() raises ValueError before the mkdir at 45.
    def test_SR_7_object_named_like_the_pointer_is_refused(self):
        objects = json.dumps({K_SEAL: BODY_SEAL, "snapshot:current": BODY_BLOB}, separators=(",", ":")).encode("utf-8")
        self.fixture(objects=objects)
        seen = self.staged()
        got = (seen["outcome"], seen["out_exists"])
        want = (("RAISED", "ValueError"), False)
        self.assertEqual(got, want, diff_fields(FIELDS_FAIL, got, want))


class MachineBindingExpectationRows(StageCase):
    """F06-REPLAY-GATE-BINDING: a staged run whose seal carries the machine binding must read it through the real machine
    loader (reader contract v4, guidance_machine_probe); a run without the binding is judged exactly as before."""

    BASE = {"reader_contract_version": replay.READER_CONTRACT_VERSION, "integrity": "sealed", "run_id": "R",
            "macro_overview_sealed": True, "fresh": True}

    def test_MB_1_contract_version_is_v4(self):
        self.assertEqual(replay.READER_CONTRACT_VERSION, "v213-reader-replay-v4")

    def test_MB_2_binding_present_and_admitted_passes(self):
        result = {**self.BASE, "guidance_machine_probe": "ADMITTED"}
        self.assertEqual(replay.expectations(result, "OTHER", "R", machine=True), [])

    def test_MB_3_binding_present_but_not_admitted_names_only_the_new_expectation(self):
        for probe in ("REFUSED", "ABSENT", None, "admitted"):
            result = {**self.BASE, "guidance_machine_probe": probe}
            self.assertEqual(replay.expectations(result, "OTHER", "R", machine=True), ["GUIDANCE_MACHINE_BINDING"], probe)
        self.assertEqual(replay.expectations(self.BASE, "OTHER", "R", machine=True), ["GUIDANCE_MACHINE_BINDING"])

    def test_MB_4_binding_absent_does_not_require_the_expectation(self):
        for probe in ("ABSENT", "REFUSED", None):
            result = {**self.BASE, "guidance_machine_probe": probe}
            self.assertEqual(replay.expectations(result, "OTHER", "R"), [], probe)
            self.assertEqual(replay.expectations(result, "OTHER", "R", False, False, False), [], probe)

    def test_MB_5_other_tiers_keep_their_expectation_lists(self):
        carried = {**self.BASE, "top20_records": 20, "line_flex_messages": 1, "line_text_messages": 1, "broadcast_ready": True,
                   "v21_records": 20, "v212_records": 20, "test_only_admission": False}
        self.assertEqual(replay.expectations({**carried, "top20_records": 2}, "CARRIED_FORWARD", "R", True, True),
                         ["TOP20_RECORDS", "IDENTITY_NVDA", "IDENTITY_2330", "IDENTITY_TW_NAME", "BOTTLENECK_V3", "INDUSTRY_V3"])
        self.assertEqual(replay.expectations({**carried, "top20_records": 2}, "CARRIED_FORWARD", "R", True, True, True),
                         ["TOP20_RECORDS", "IDENTITY_NVDA", "IDENTITY_2330", "IDENTITY_TW_NAME", "BOTTLENECK_V3", "INDUSTRY_V3",
                          "GUIDANCE_MACHINE_BINDING"])

    def test_MB_6_replay_detects_the_binding_in_the_seal_and_carries_the_probe(self):
        seal = json.dumps({"schema_version": 1, "objects": {"v213:revenue-guidance-binding:v1": {}}})
        outputs = {}
        for name, with_binding, probe in (("tier_machine_ok", True, "ADMITTED"), ("tier_machine_bad", True, "REFUSED"),
                                          ("tier_plain", False, "ABSENT")):
            run = self.base / name
            run.mkdir()
            objects = {K_SEAL: seal if with_binding else BODY_SEAL}
            (run / "objects.json").write_bytes(json.dumps(objects).encode("utf-8"))
            (run / "pointer.raw.json").write_bytes(POINTER_BYTES)
            (run / "summary.json").write_text(json.dumps({"top20_state": None}), encoding="utf-8")

            def fake_runner(replay_dir, result_path, probe=probe):
                result_path.write_text(json.dumps({**self.BASE, "run_id": RUN, "guidance_machine_probe": probe}), encoding="utf-8")
                return 0

            outputs[name] = replay.replay(run, fake_runner)
        self.assertEqual([(k, v["status"], v["failed"], v["guidance_machine_probe"]) for k, v in outputs.items()],
                         [("tier_machine_ok", "PASS", [], "ADMITTED"),
                          ("tier_machine_bad", "FAIL", ["GUIDANCE_MACHINE_BINDING"], "REFUSED"),
                          ("tier_plain", "PASS", [], "ABSENT")])

    # F06-REPLAY-GATE-BINDING (wiring): the only code that computes the probe is the operator-gate reader, which is
    # skipped without V213_LIVE_REPLAY_DIR, so the wiring is pinned statically, together with the cross-language
    # parity of the binding key and of the reader contract version.
    def test_MB_7_live_replay_reader_wires_the_probe_and_the_key_matches_the_producer(self):
        reader = (ROOT / "cloud" / "test" / "live-kv-replay.test.ts").read_text(encoding="utf-8")
        helper = (ROOT / "cloud" / "test" / "helpers" / "guidance-machine-probe.ts").read_text(encoding="utf-8")
        worker = (ROOT / "cloud" / "src" / "v213" / "revenue-guidance-machine.ts").read_text(encoding="utf-8")
        import revenue_guidance_machine as producer
        self.assertEqual(replay.GUIDANCE_BINDING_KEY, producer.BINDING_KEY)
        for needle in ('const READER_CONTRACT_VERSION = "' + replay.READER_CONTRACT_VERSION + '";',
                       'import { probeGuidanceMachine } from "./helpers/guidance-machine-probe";',
                       "const guidanceMachineProbe = await probeGuidanceMachine(view);",
                       "guidance_machine_probe: guidanceMachineProbe,"):
            self.assertIn(needle, reader)
        self.assertIn("loadBottleneckV3(view, { guidanceMachineEnabled: true })", helper)
        self.assertIn('export const GUIDANCE_BINDING_KEY = "' + replay.GUIDANCE_BINDING_KEY + '";', worker)


if __name__ == "__main__":
    unittest.main()
