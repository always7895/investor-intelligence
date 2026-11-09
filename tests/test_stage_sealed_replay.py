"""Byte-layout tests for stage() of scripts/stage_sealed_replay.py (offline; vitest never runs, replay() only with a fake runner).

stage(run_dir, out) turns a sealed run (objects.json + pointer.raw.json) into the k<N>.txt files plus index.json that
cloud/test/live-kv-replay.test.ts reads. No test of the repository executes it, so these rows pin the exact bytes,
the file numbering, the index key order, the write order and the failure behaviour. Every output root is a temporary
directory outside the repository; subprocess.run, vitest_runner and the network are guarded (StageCase, also the base of the machine-binding rows). Each row compares a
literal designed from the code; the comment above each row cites the lines it was designed from."""
from __future__ import annotations

import hashlib
import json
import os
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
            self.addCleanup(patcher.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.run_dir = self.base / "run"
        self.run_dir.mkdir()
        self.out = self.base / "nested" / "kv"
        self.assertEqual(self.base.is_relative_to(ROOT.resolve()), False)
        self.assertEqual(self.out.resolve().is_relative_to(ROOT.resolve()), False)

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


class SetupCleanupTests(unittest.TestCase):
    def test_inside_root_setup_failure_restores_guards_and_temp_ownership(self):
        ran = []

        class InsideRootCase(StageCase):
            def runTest(self):
                ran.append(True)

        original_tempdir = tempfile.TemporaryDirectory
        originals = replay.subprocess.run, replay.vitest_runner, socket.create_connection, socket.getaddrinfo
        original_modules = {name: sys.modules[name] for name in ("socket", "subprocess", "tempfile", replay.__name__)}
        original_environment = dict(os.environ)
        owned = []
        with original_tempdir() as directory:
            root = Path(directory).resolve()

            def temporary_directory():
                temp = original_tempdir(dir=root)
                owned.append(temp)
                return temp

            case = InsideRootCase()
            result = unittest.TestResult()
            with mock.patch(__name__ + ".ROOT", root), \
                    mock.patch.object(tempfile, "TemporaryDirectory", temporary_directory):
                case.run(result)
            self.assertEqual((result.testsRun, len(result.failures), result.errors), (1, 1, []))
            self.assertEqual(ran, [])
            for actual, original in zip(
                    (replay.subprocess.run, replay.vitest_runner, socket.create_connection, socket.getaddrinfo), originals):
                self.assertIs(actual, original)
            self.assertEqual(len(owned), 1)
            self.assertFalse(Path(owned[0].name).exists())
        for name, module in original_modules.items():
            self.assertIs(sys.modules[name], module)
        self.assertEqual(dict(os.environ), original_environment)


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

    # A numeric pointer cannot authorize the fixture's unrelated transaction-run keys.
    def test_SR_6_numeric_run_id_cannot_stage_an_unrelated_run(self):
        self.fixture(pointer=b'{"run_id":12345}')
        seen = self.staged()
        self.assertEqual((seen["outcome"], seen["out_exists"]), (("RAISED", "ValueError"), False))

    # F-STAGE-CURRENT-COLLISION fixed, SR 41-42: an objects.json key equal to the pointer key would replace the
    # pointer's index entry (46/50) and orphan k0.txt, so stage() raises ValueError before the mkdir at 45.
    def test_SR_7_object_named_like_the_pointer_is_refused(self):
        objects = json.dumps({K_SEAL: BODY_SEAL, "snapshot:current": BODY_BLOB}, separators=(",", ":")).encode("utf-8")
        self.fixture(objects=objects)
        seen = self.staged()
        got = (seen["outcome"], seen["out_exists"])
        want = (("RAISED", "ValueError"), False)
        self.assertEqual(got, want, diff_fields(FIELDS_FAIL, got, want))


class ReusedCoreRows(StageCase):
    CORE = "20261001T000000Z-aaaaaaaaaaaa"
    CORE_TIME = "2026-10-01T00:00:00Z"
    GLOBAL_TIME = "2026-10-01T02:00:00Z"

    def reused(self):
        logicals = ("v21:top20:latest", "scores:latest", "source_views:latest", "source_plan:latest",
                    "reports:latest", "reports:morning:latest", "reports:evening:latest",
                    "last_successful_pipeline_timestamp", "v212:top20-report:latest", "v213:top20-report:latest",
                    "v213:source-federation:latest", "v213:source-independence:latest", "v213:activation-claim",
                    "v213:macro-industry:latest")
        bodies = {key: json.dumps({"synthetic": key}) for key in logicals}
        bodies["last_successful_pipeline_timestamp"] = self.GLOBAL_TIME
        contract = json.loads((ROOT / "config" / "v213-r75-publication-mode-v2.json").read_text(encoding="utf-8"))
        bodies["v213:activation-claim"] = json.dumps({
            "schema_version": 1, "transaction_id": "1" * 32, "run_id": self.CORE,
            "payload_digests": {name: "a" * 64 for name in contract["payload_names"]}, "claimed_at": self.CORE_TIME,
        }, separators=(",", ":"))
        lazy = {"v213:bottleneck-top20:v3": '{"marker":"UNCHANGED_RANKING","generated_at":"' + self.CORE_TIME + '"}',
                "v213:quotes:v1": '{"marker":"FRESH_QUOTES","generated_at":"' + self.GLOBAL_TIME + '"}'}
        definitions = {key: self.entry(body) for key, body in {**bodies, **lazy}.items()}
        objects = {f"snapshot:{RUN if key == replay.LIVENESS_KEY else self.CORE}:{key}": body for key, body in bodies.items()}
        objects.update({"blob:v1:" + self.entry(body)["sha256"]: body for body in lazy.values()})
        seal = {"schema_version": 1, "contract_id": "v213-stored-snapshot-v1", "run_id": RUN,
                "transaction_id": "1" * 32, "generated_at": self.GLOBAL_TIME, "public_data_as_of": self.CORE_TIME,
                "core_run_id": self.CORE, "ranking_persisted_at": self.CORE_TIME,
                "product_persisted_at": {"market": self.GLOBAL_TIME, "prices": self.CORE_TIME, "identity": self.CORE_TIME},
                "provider_scope": "public_only", "owner_watchlist_inherited": False, "objects": definitions}
        pointer = {"schema_version": 2, "run_id": RUN, "transaction_id": "1" * 32,
                   "public_data_as_of": self.CORE_TIME, "promoted_at": self.GLOBAL_TIME,
                   "provider_scope": "public_only", "owner_watchlist_inherited": False}
        self.root(objects, pointer, seal)
        return objects, pointer, seal

    @staticmethod
    def entry(body):
        encoded = body.encode("utf-8")
        return {"sha256": hashlib.sha256(encoded).hexdigest(), "utf8_bytes": len(encoded)}

    @staticmethod
    def root(objects, pointer, seal):
        objects[K_SEAL] = json.dumps(seal, ensure_ascii=False, separators=(",", ":"))
        pointer["seal_sha256"] = hashlib.sha256(objects[K_SEAL].encode("utf-8")).hexdigest()

    def store(self, objects, pointer):
        self.fixture(json.dumps(objects, ensure_ascii=False).encode("utf-8"),
                     (json.dumps(pointer, separators=(",", ":")) + "\n").encode("utf-8"))

    def test_complete_reused_core_map_stages_without_cloning_or_relabeling(self):
        objects, pointer, seal = self.reused()
        self.store(objects, pointer)
        self.assertEqual(replay.stage(self.run_dir, self.out), RUN)
        index = json.loads((self.out / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(set(index), {"snapshot:current", *objects})
        for key, body in objects.items():
            self.assertEqual((self.out / index[key]).read_bytes(), body.encode("utf-8"))
        self.assertEqual(set(key for key in index if key.startswith(f"snapshot:{RUN}:")),
                         {K_SEAL, f"snapshot:{RUN}:{replay.LIVENESS_KEY}"})
        self.assertEqual(objects[f"snapshot:{RUN}:{replay.LIVENESS_KEY}"], self.GLOBAL_TIME)
        self.assertEqual(pointer["public_data_as_of"], self.CORE_TIME)
        self.assertEqual(json.loads(objects[f"snapshot:{self.CORE}:v213:activation-claim"])["claimed_at"], self.CORE_TIME)
        self.assertEqual(seal["ranking_persisted_at"], self.CORE_TIME)
        self.assertEqual(self.counts, {"run": 0, "vitest": 0})

    def test_ranking_only_clock_and_blobs_can_advance_while_the_core_authority_stays_exact(self):
        objects, pointer, seal = self.reused()
        before_core = {key: value for key, value in objects.items() if key.startswith(f"snapshot:{self.CORE}:")}
        product_clocks = dict(seal["product_persisted_at"])
        ranking_key = "v213:bottleneck-top20:v3"
        del objects["blob:v1:" + seal["objects"][ranking_key]["sha256"]]
        for logical, marker in ((ranking_key, "NEW_RANKING"), (replay.GUIDANCE_BINDING_KEY, "NEW_BINDING")):
            body = json.dumps({"generated_at": self.GLOBAL_TIME, "approval_approved_at": self.CORE_TIME, "marker": marker})
            seal["objects"][logical] = self.entry(body)
            objects["blob:v1:" + self.entry(body)["sha256"]] = body
        seal["ranking_persisted_at"] = self.GLOBAL_TIME
        self.root(objects, pointer, seal)
        self.store(objects, pointer)
        self.assertEqual(replay.stage(self.run_dir, self.out), RUN)
        self.assertEqual(seal["core_run_id"], self.CORE)
        self.assertEqual(seal["product_persisted_at"], product_clocks)
        self.assertEqual({key: value for key, value in objects.items() if key.startswith(f"snapshot:{self.CORE}:")}, before_core)

    def test_replay_compares_worker_core_identity_but_returns_global_publication_identity(self):
        for worker_id in (self.CORE, RUN):
            with self.subTest(worker_id=worker_id):
                objects, pointer, _ = self.reused()
                self.store(objects, pointer)
                (self.run_dir / "summary.json").write_text('{"top20_state":null}', encoding="utf-8")

                def fake_runner(replay_dir, result_path):
                    result_path.write_text(json.dumps({"reader_contract_version": replay.READER_CONTRACT_VERSION,
                        "integrity": "sealed", "run_id": worker_id, "seal_run_id": RUN, "macro_overview_sealed": True, "fresh": True,
                        "seal_sha256": pointer["seal_sha256"],
                        "bottleneck_v3_records": 10, "bottleneck_v3_flex": 1, "industry_v3_flex": 1}), encoding="utf-8")
                    return 0

                result = replay.replay(self.run_dir, fake_runner)
                self.assertEqual(result["run_id"], RUN)
                self.assertEqual(result["failed"], [] if worker_id == self.CORE else ["RUN_ID"])

    def test_replay_binds_exact_hash_before_runner_and_rejects_source_mutation_or_same_id_seal_replacement(self):
        for mode in ("missing", "wrong", "same_ids_different_seal", "changed_source_original_result", "changed_source_new_result"):
            with self.subTest(mode=mode):
                objects, pointer, seal = self.reused()
                original_hash = pointer["seal_sha256"]
                self.store(objects, pointer)
                (self.run_dir / "summary.json").write_text('{"top20_state":null}', encoding="utf-8")

                def fake_runner(replay_dir, result_path):
                    staged_index = json.loads((replay_dir / "index.json").read_text(encoding="utf-8"))
                    staged_pointer = json.loads((replay_dir / staged_index["snapshot:current"]).read_bytes())
                    self.assertEqual(staged_pointer["seal_sha256"], original_hash)
                    result = {"reader_contract_version": replay.READER_CONTRACT_VERSION, "integrity": "sealed",
                              "run_id": self.CORE, "seal_run_id": RUN, "seal_sha256": original_hash, "macro_overview_sealed": True,
                              "fresh": True, "bottleneck_v3_records": 10, "bottleneck_v3_flex": 1, "industry_v3_flex": 1}
                    if mode == "missing":
                        del result["seal_sha256"]
                    elif mode == "wrong":
                        result["seal_sha256"] = "f" * 64
                    elif mode == "same_ids_different_seal":
                        changed_root = json.loads(objects[K_SEAL])
                        changed_root["product_persisted_at"]["identity"] = self.GLOBAL_TIME
                        raw = json.dumps(changed_root, separators=(",", ":"))
                        new_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
                        (replay_dir / staged_index[K_SEAL]).write_text(raw, encoding="utf-8")
                        staged_pointer["seal_sha256"] = new_hash
                        (replay_dir / staged_index["snapshot:current"]).write_text(json.dumps(staged_pointer), encoding="utf-8")
                        result["seal_sha256"] = new_hash
                    else:
                        seal["product_persisted_at"]["identity"] = self.GLOBAL_TIME
                        self.root(objects, pointer, seal)
                        self.store(objects, pointer)
                        if mode == "changed_source_new_result":
                            result["seal_sha256"] = pointer["seal_sha256"]
                    result_path.write_text(json.dumps(result), encoding="utf-8")
                    return 0

                outcome = replay.replay(self.run_dir, fake_runner)
                expected = ["STAGED_SOURCE_CHANGED"] if mode.startswith("changed_source") else []
                if mode != "changed_source_original_result":
                    expected.append("SEAL_SHA256")
                self.assertEqual(outcome["status"], "FAIL")
                self.assertEqual(outcome["failed"], expected)
                self.assertEqual(outcome["seal_sha256"], original_hash)

    def test_reused_root_rejects_partial_wrong_cross_run_or_corrupt_maps_before_staging(self):
        modes = ("core_only", "clock_only", "bad_core", "wrong_core", "future_clock", "wrong_root", "root_digest",
                 "foreign_key", "old_root", "global_clone", "missing_core", "core_digest", "lazy_digest",
                 "renewed_claim", "renewed_claim_time", "renewed_data", "extra_product", "future_product", "bad_product",
                 "missing_liveness", "old_liveness_extra", "core_liveness_only", "old_liveness_clock")
        for mode in modes:
            with self.subTest(mode=mode):
                objects, pointer, seal = self.reused()
                core_key = f"snapshot:{self.CORE}:reports:latest"
                if mode == "core_only":
                    del seal["ranking_persisted_at"]
                elif mode == "clock_only":
                    del seal["core_run_id"]
                elif mode == "bad_core":
                    seal["core_run_id"] = "not-a-run"
                elif mode == "wrong_core":
                    seal["core_run_id"] = "20261001T010000Z-bbbbbbbbbbbb"
                elif mode == "future_clock":
                    seal["ranking_persisted_at"] = "2026-10-01T03:00:00Z"
                elif mode == "wrong_root":
                    seal["run_id"] = self.CORE
                elif mode == "foreign_key":
                    objects["snapshot:20261001T010000Z-bbbbbbbbbbbb:reports:latest"] = "FOREIGN"
                elif mode == "old_root":
                    objects[f"snapshot:{self.CORE}:{replay.SEAL_KEY}"] = "{}"
                elif mode == "global_clone":
                    objects[f"snapshot:{RUN}:reports:latest"] = objects.pop(core_key)
                elif mode == "missing_core":
                    del objects[core_key]
                elif mode == "core_digest":
                    objects[core_key] += " "
                elif mode == "lazy_digest":
                    objects["blob:v1:" + seal["objects"]["v213:quotes:v1"]["sha256"]] += " "
                elif mode in ("renewed_claim", "renewed_claim_time"):
                    key = f"snapshot:{self.CORE}:v213:activation-claim"
                    claim = json.loads(objects[key])
                    claim["run_id" if mode == "renewed_claim" else "claimed_at"] = RUN if mode == "renewed_claim" else self.GLOBAL_TIME
                    objects[key] = json.dumps(claim, separators=(",", ":"))
                    seal["objects"]["v213:activation-claim"] = self.entry(objects[key])
                elif mode == "renewed_data":
                    seal["public_data_as_of"] = pointer["public_data_as_of"] = self.GLOBAL_TIME
                elif mode == "extra_product":
                    seal["product_persisted_at"]["other"] = self.CORE_TIME
                elif mode == "future_product":
                    seal["product_persisted_at"]["market"] = "2026-10-01T03:00:00Z"
                elif mode == "bad_product":
                    seal["product_persisted_at"] = None
                elif mode == "missing_liveness":
                    del objects[f"snapshot:{RUN}:{replay.LIVENESS_KEY}"]
                elif mode == "old_liveness_extra":
                    objects[f"snapshot:{self.CORE}:{replay.LIVENESS_KEY}"] = self.CORE_TIME
                elif mode == "core_liveness_only":
                    objects[f"snapshot:{self.CORE}:{replay.LIVENESS_KEY}"] = objects.pop(f"snapshot:{RUN}:{replay.LIVENESS_KEY}")
                elif mode == "old_liveness_clock":
                    objects[f"snapshot:{RUN}:{replay.LIVENESS_KEY}"] = self.CORE_TIME
                    seal["objects"][replay.LIVENESS_KEY] = self.entry(self.CORE_TIME)
                self.root(objects, pointer, seal)
                if mode == "root_digest":
                    pointer["seal_sha256"] = "f" * 64
                self.store(objects, pointer)
                out = self.base / ("bad-" + mode)
                self.assertEqual(outcome_of(lambda: replay.stage(self.run_dir, out)), ("RAISED", "ValueError"))
                self.assertFalse(out.exists())


class MachineBindingExpectationRows(StageCase):
    """F06-REPLAY-GATE-BINDING: a staged run whose seal carries the machine binding must read it through the real machine
    loader (reader contract v5, guidance_machine_probe); a run without the binding retains the machine expectation."""

    BASE = {"reader_contract_version": replay.READER_CONTRACT_VERSION, "integrity": "sealed", "run_id": "R", "seal_run_id": "R",
            "seal_sha256": "a" * 64,
            "macro_overview_sealed": True, "fresh": True}

    def test_MB_1_contract_version_is_v5(self):
        self.assertEqual(replay.READER_CONTRACT_VERSION, "v213-reader-replay-v5")

    def test_MB_2_binding_present_and_admitted_passes(self):
        result = {**self.BASE, "guidance_machine_probe": "ADMITTED"}
        self.assertEqual(replay.expectations(result, "OTHER", "R", machine=True, seal_run_id="R", seal_sha256="a" * 64), [])

    def test_MB_3_binding_present_but_not_admitted_names_only_the_new_expectation(self):
        for probe in ("REFUSED", "ABSENT", None, "admitted"):
            result = {**self.BASE, "guidance_machine_probe": probe}
            self.assertEqual(replay.expectations(result, "OTHER", "R", machine=True, seal_run_id="R", seal_sha256="a" * 64), ["GUIDANCE_MACHINE_BINDING"], probe)
        self.assertEqual(replay.expectations(self.BASE, "OTHER", "R", machine=True, seal_run_id="R", seal_sha256="a" * 64), ["GUIDANCE_MACHINE_BINDING"])

    def test_MB_4_binding_absent_does_not_require_the_expectation(self):
        for probe in ("ABSENT", "REFUSED", None):
            result = {**self.BASE, "guidance_machine_probe": probe}
            self.assertEqual(replay.expectations(result, "OTHER", "R", seal_run_id="R", seal_sha256="a" * 64), [], probe)
            self.assertEqual(replay.expectations(result, "OTHER", "R", False, False, False, seal_run_id="R", seal_sha256="a" * 64), [], probe)

    def test_MB_5_other_tiers_keep_their_expectation_lists(self):
        carried = {**self.BASE, "top20_records": 20, "line_flex_messages": 1, "line_text_messages": 1, "broadcast_ready": True,
                   "v21_records": 20, "v212_records": 20, "test_only_admission": False}
        self.assertEqual(replay.expectations({**carried, "top20_records": 2}, "CARRIED_FORWARD", "R", True, True, seal_run_id="R", seal_sha256="a" * 64),
                         ["TOP20_RECORDS", "IDENTITY_NVDA", "IDENTITY_2330", "IDENTITY_TW_NAME", "BOTTLENECK_V3", "INDUSTRY_V3"])
        self.assertEqual(replay.expectations({**carried, "top20_records": 2}, "CARRIED_FORWARD", "R", True, True, True, seal_run_id="R", seal_sha256="a" * 64),
                         ["TOP20_RECORDS", "IDENTITY_NVDA", "IDENTITY_2330", "IDENTITY_TW_NAME", "BOTTLENECK_V3", "INDUSTRY_V3",
                          "GUIDANCE_MACHINE_BINDING"])

    def test_reused_expired_legacy_refusal_does_not_force_new_ranking_or_refresh_old_forecasts(self):
        facts = {**self.BASE, "run_id": "CORE", "seal_run_id": "GLOBAL", "fresh": False,
                 "legacy_report_expired_refused": True, "legacy_report_original_generated_at": "2026-10-01T00:00:00Z",
                 "pipeline_liveness_fresh": True, "top20_records": 0, "report_generated_at": None, "broadcast_ready": False,
                 "v21_records": 20, "v212_records": 20, "guidance_machine_probe": "REFUSED", "guidance_machine_dated_facts_only": True,
                 "bottleneck_v3_records": 10, "bottleneck_v3_flex": 1, "industry_v3_flex": 1}
        kwargs = {"bottleneck": True, "machine": True, "seal_run_id": "GLOBAL", "seal_sha256": "a" * 64}
        self.assertEqual(replay.expectations(facts, "CARRIED_FORWARD", "CORE", **kwargs), [])
        for changed, failure in (({"pipeline_liveness_fresh": False}, "FRESH"),
                                 ({"legacy_report_expired_refused": False}, "FRESH"),
                                 ({"legacy_report_original_generated_at": None}, "LEGACY_EXPIRED_REFUSAL"),
                                 ({"broadcast_ready": True}, "LEGACY_EXPIRED_REFUSAL"),
                                 ({"bottleneck_v3_records": 0}, "BOTTLENECK_V3"),
                                 ({"guidance_machine_dated_facts_only": False}, "GUIDANCE_MACHINE_BINDING"),
                                 ({"guidance_machine_probe": "ABSENT"}, "GUIDANCE_MACHINE_BINDING"),
                                 ({"seal_sha256": "b" * 64}, "SEAL_SHA256")):
            self.assertIn(failure, replay.expectations({**facts, **changed}, "CARRIED_FORWARD", "CORE", **kwargs), changed)
        not_reused = {**facts, "run_id": "GLOBAL"}
        errors = replay.expectations(not_reused, "CARRIED_FORWARD", "GLOBAL", **kwargs)
        self.assertIn("FRESH", errors); self.assertIn("GUIDANCE_MACHINE_BINDING", errors)

    def test_MB_6_replay_detects_the_binding_in_the_seal_and_carries_the_probe(self):
        seal = json.dumps({"schema_version": 1, "objects": {"v213:revenue-guidance-binding:v1": {}}})
        outputs = {}
        for name, with_binding, probe in (("tier_machine_ok", True, "ADMITTED"), ("tier_machine_bad", True, "REFUSED"),
                                          ("tier_plain", False, "ABSENT")):
            run = self.base / name
            run.mkdir()
            objects = {K_SEAL: seal if with_binding else BODY_SEAL}
            (run / "objects.json").write_bytes(json.dumps(objects).encode("utf-8"))
            pointer = {**json.loads(POINTER_BYTES), "seal_sha256": hashlib.sha256(objects[K_SEAL].encode("utf-8")).hexdigest()}
            (run / "pointer.raw.json").write_bytes(json.dumps(pointer).encode("utf-8"))
            (run / "summary.json").write_text(json.dumps({"top20_state": None}), encoding="utf-8")

            def fake_runner(replay_dir, result_path, probe=probe):
                result_path.write_text(json.dumps({**self.BASE, "run_id": RUN, "seal_run_id": RUN,
                    "seal_sha256": pointer["seal_sha256"], "guidance_machine_probe": probe}), encoding="utf-8")
                return 0

            outputs[name] = replay.replay(run, fake_runner)
        self.assertEqual([(k, v["status"], v["failed"], v["guidance_machine_probe"]) for k, v in outputs.items()],
                         [("tier_machine_ok", "PASS", [], "ADMITTED"),
                          ("tier_machine_bad", "FAIL", ["GUIDANCE_MACHINE_BINDING"], "REFUSED"),
                          ("tier_plain", "PASS", [], "ABSENT")])

    def test_replay_requires_both_exact_identities_never_an_either_or_match(self):
        good = {**self.BASE, "run_id": "CORE", "seal_run_id": "GLOBAL"}
        self.assertEqual(replay.expectations(good, None, "CORE", seal_run_id="GLOBAL", seal_sha256="a" * 64), [])
        for fields, failures in (({"run_id": "GLOBAL"}, ["RUN_ID"]),
                                 ({"seal_run_id": "CORE"}, ["SEAL_RUN_ID"]),
                                 ({"seal_run_id": None}, ["SEAL_RUN_ID"]),
                                 ({"seal_sha256": None}, ["SEAL_SHA256"]),
                                 ({"seal_sha256": "b" * 64}, ["SEAL_SHA256"]),
                                 ({"reader_contract_version": "v213-reader-replay-v4"}, ["READER_CONTRACT"])):
            self.assertEqual(replay.expectations({**good, **fields}, None, "CORE", seal_run_id="GLOBAL", seal_sha256="a" * 64), failures)
        no_hash = {key: value for key, value in good.items() if key != "seal_sha256"}
        self.assertEqual(replay.expectations(no_hash, None, "CORE", seal_run_id="GLOBAL", seal_sha256="a" * 64), ["SEAL_SHA256"])

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
                       "guidance_machine_probe: guidanceMachineProbe.status,",
                       "guidance_machine_dated_facts_only: guidanceMachineProbe.datedFactsOnly,",
                       'import { probeLegacyReport } from "./helpers/legacy-report-probe";',
                       "const legacyProbe = await probeLegacyReport(view, env, report);",
                       "legacy_report_expired_refused: legacyProbe.expiredRefused,",
                       'run_id: view.integrity === "sealed" ? view.runId : null,',
                       'seal_run_id: view.integrity === "sealed" ? view.sealRunId : null,',
                       'seal_sha256: view.integrity === "sealed" ? view.sealSha256 : null,'):
            self.assertIn(needle, reader)
        self.assertIn("loadBottleneckV3(view, { guidanceMachineEnabled: true })", helper)
        self.assertIn('export const GUIDANCE_BINDING_KEY = "' + replay.GUIDANCE_BINDING_KEY + '";', worker)


if __name__ == "__main__":
    unittest.main()
