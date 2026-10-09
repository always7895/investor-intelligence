"""Byte-layout tests for stage() of scripts/stage_sealed_replay.py (offline; replay() and vitest never run).

stage(run_dir, out) turns a sealed run (objects.json + pointer.raw.json) into the k<N>.txt files plus index.json that
cloud/test/live-kv-replay.test.ts reads. No test of the repository executes it, so these rows pin the exact bytes,
the file numbering, the index key order, the write order and the failure behaviour. Every output root is a temporary
directory outside the repository; subprocess.run, vitest_runner and the network are guarded. Each row compares a
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

    # SR 39 exist_ok=True: an existing out directory is accepted; 41-45 overwrite k0..k3 and index.json but nothing
    # removes other files, so k9.txt survives and index.json does not list it (F-STAGE-STALE, traced behaviour).
    def test_SR_4_existing_out_directory_keeps_stale_files(self):
        self.fixture()
        self.out.mkdir(parents=True)
        (self.out / "k0.txt").write_bytes(b"OLD")
        (self.out / "k9.txt").write_bytes(b"STALE")
        seen = self.staged()
        got = tuple(seen[name] for name in FIELDS_LIST)
        want = (("RESULT", RUN), FULL_LISTING + (("k9.txt", b"STALE"),),
                ("snapshot:current", K_SEAL, K_BLOB, K_MACRO))
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


if __name__ == "__main__":
    unittest.main()
