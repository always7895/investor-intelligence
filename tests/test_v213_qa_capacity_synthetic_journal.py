from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from v213_qa_capacity_control_state import (  # noqa: E402
    StateEventClaims,
    append_event,
    initial_history,
    validate_state_binding,
)
from v213_qa_capacity_synthetic_journal import (  # noqa: E402
    AUTHORIZES_EXECUTION,
    NON_PRODUCTION,
    SYNTHETIC,
    SyntheticClaim,
    SyntheticFixtureRoot,
    SyntheticJournalError,
    SyntheticJournalSnapshot,
    append_record,
    claim_checkpoint,
    load_journal,
    require_fixture_root,
    synthetic_fixture,
)


class _Hostile:
    """Wrong-type object recording any attr/equality touch (must be unused)."""

    def __init__(self):
        self.hits = []

    def __getattr__(self, name):
        self.hits.append("attr:" + name)
        raise AttributeError(name)

    def __eq__(self, other):
        self.hits.append("eq")
        return True


def _canon(obj):
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _build_history(binding, steps):
    """Build a valid history from steps=(event_id, phase, now)."""
    hist = initial_history(binding, steps[0][0], steps[0][2])
    for event_id, phase, now in steps[1:]:
        hist = append_event(hist, event_id, phase, now)
    return hist


def _build_journal(root, binding, history):
    """Handbuilt fixture following the C1 protocol (independent of reader)."""
    fixture_path = require_fixture_root(root)
    ck = binding.checkpoint_key
    claim_payload = {
        "format": "SYNTHETIC_CHECKPOINT_CLAIM_V1",
        "SYNTHETIC": True,
        "NON_PRODUCTION": True,
        "AUTHORIZES_EXECUTION": False,
        "checkpoint_key": ck,
        "run_id": binding.run_id,
        "run_binding_sha256": binding.run_binding_sha256,
        "deadline": binding.deadline,
    }
    claim_bytes = _canon(claim_payload)
    (fixture_path / ("SYNTHETIC-claim-%s.json" % ck)).write_bytes(claim_bytes)
    prev = hashlib.sha256(claim_bytes).hexdigest()
    for ev in history:
        payload = {
            "format": "SYNTHETIC_EVENT_V1",
            "SYNTHETIC": True,
            "NON_PRODUCTION": True,
            "AUTHORIZES_EXECUTION": False,
            "previous_sha256": prev,
            "event": {
                "checkpoint_key": ev.checkpoint_key,
                "run_id": ev.run_id,
                "run_binding_sha256": ev.run_binding_sha256,
                "deadline": ev.deadline,
                "sequence": ev.sequence,
                "event_id": ev.event_id,
                "phase": ev.phase,
                "observed_now": ev.observed_now,
            },
        }
        pb = _canon(payload)
        (fixture_path / ("SYNTHETIC-event-%s-%04d.json" % (ck, ev.sequence))).write_bytes(pb)
        seal = {
            "format": "SYNTHETIC_EVENT_SEAL_V1",
            "SYNTHETIC": True,
            "NON_PRODUCTION": True,
            "AUTHORIZES_EXECUTION": False,
            "checkpoint_key": ck,
            "sequence": ev.sequence,
            "payload_sha256": hashlib.sha256(pb).hexdigest(),
            "payload_bytes": len(pb),
        }
        sb = _canon(seal)
        (fixture_path / ("SYNTHETIC-event-%s-%04d.seal.json" % (ck, ev.sequence))).write_bytes(sb)
        prev = hashlib.sha256(pb).hexdigest()
    return fixture_path


class SyntheticRootTests(unittest.TestCase):
    # --- five core root tests --------------------------------------------
    def test_normal_construction_refuses(self):
        with self.assertRaises(SyntheticJournalError):
            SyntheticFixtureRoot("/tmp/does-not-matter")
        with self.assertRaises(SyntheticJournalError):
            SyntheticFixtureRoot()

    def test_factory_yields_exact_live_root(self):
        with synthetic_fixture() as root:
            self.assertIs(type(root), SyntheticFixtureRoot)
            path = require_fixture_root(root)
            self.assertTrue(Path(path).is_dir())

    def test_non_root_types_refuse(self):
        with synthetic_fixture() as root:
            path = require_fixture_root(root)
            for bad in (str(path), path, 123, None, []):
                with self.assertRaises(SyntheticJournalError):
                    require_fixture_root(bad)

    def test_closed_root_refuses(self):
        root = None
        with synthetic_fixture() as r:
            root = r
        with self.assertRaises(SyntheticJournalError):
            require_fixture_root(root)

    def test_flags_immutable(self):
        self.assertIs(SYNTHETIC, True)
        self.assertIs(NON_PRODUCTION, True)
        self.assertIs(AUTHORIZES_EXECUTION, False)
        self.assertIs(SyntheticFixtureRoot.SYNTHETIC, True)
        self.assertIs(SyntheticFixtureRoot.NON_PRODUCTION, True)
        self.assertIs(SyntheticFixtureRoot.AUTHORIZES_EXECUTION, False)

    # --- deletion / flag mutation (new immutability guards) --------------
    def test_normal_assignment_blocked(self):
        with synthetic_fixture() as root:
            with self.assertRaises(AttributeError):
                root._path = Path("/tmp/forged")
            with self.assertRaises(AttributeError):
                root._open = False

    def test_normal_deletion_blocked(self):
        with synthetic_fixture() as root:
            with self.assertRaises(AttributeError):
                del root._path
            with self.assertRaises(AttributeError):
                del root._open

    # --- fabricated root (bypasses factory; not in live registry) --------
    def test_fabricated_root_refused(self):
        forged = object.__new__(SyntheticFixtureRoot)
        with self.assertRaises(SyntheticJournalError):
            require_fixture_root(forged)

    # --- hostile wrong type rejected before attr/equality ----------------
    def test_hostile_wrong_type_rejected_before_attr(self):
        hostile = _Hostile()
        with self.assertRaises(SyntheticJournalError):
            require_fixture_root(hostile)
        self.assertEqual(hostile.hits, [])

    # --- missing marker is not repaired ----------------------------------
    def test_missing_marker_not_repaired(self):
        with synthetic_fixture() as root:
            path = require_fixture_root(root)
            marker = Path(path) / "NON_PRODUCTION.marker"
            marker.unlink()
            with self.assertRaises(SyntheticJournalError):
                require_fixture_root(root)
            self.assertFalse(marker.exists())

    # --- context-body exception revokes and cleans its own dir -----------
    def test_context_body_exception_revokes_cleans(self):
        root = None
        dirpath = None
        try:
            with synthetic_fixture() as r:
                root = r
                dirpath = require_fixture_root(root)
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        self.assertFalse(Path(dirpath).exists())
        with self.assertRaises(SyntheticJournalError):
            require_fixture_root(root)


class SyntheticClaimTests(unittest.TestCase):
    def _make_binding(self, run_id="run-0001", deadline=1000):
        return validate_state_binding("a" * 40, run_id, "b" * 64, deadline)

    def _claim_path(self, path, binding):
        return Path(path) / ("SYNTHETIC-claim-%s.json" % binding.checkpoint_key)

    # --- correct fixed schema/flags/hash and untouched input binding -----
    def test_correct_schema_flags_hash_and_untouched_binding(self):
        with synthetic_fixture() as root:
            b1 = self._make_binding()
            claim = claim_checkpoint(root, b1)
            self.assertIs(claim.SYNTHETIC, True)
            self.assertIs(claim.NON_PRODUCTION, True)
            self.assertIs(claim.AUTHORIZES_EXECUTION, False)
            path = require_fixture_root(root)
            on_disk = self._claim_path(path, b1).read_bytes()
            self.assertEqual(
                claim.header_sha256, hashlib.sha256(on_disk).hexdigest())
            payload = json.loads(on_disk.decode("utf-8"))
            self.assertEqual(payload["format"], "SYNTHETIC_CHECKPOINT_CLAIM_V1")
            self.assertIs(payload["SYNTHETIC"], True)
            self.assertIs(payload["NON_PRODUCTION"], True)
            self.assertIs(payload["AUTHORIZES_EXECUTION"], False)
            self.assertEqual(payload["checkpoint_key"], b1.checkpoint_key)
            self.assertEqual(payload["run_id"], b1.run_id)
            self.assertEqual(payload["run_binding_sha256"], b1.run_binding_sha256)
            self.assertEqual(payload["deadline"], b1.deadline)
            self.assertEqual(claim.binding.checkpoint_key, b1.checkpoint_key)
            self.assertEqual(claim.binding.run_id, b1.run_id)
            self.assertEqual(claim.binding.run_binding_sha256, b1.run_binding_sha256)
            self.assertEqual(claim.binding.deadline, b1.deadline)

    # --- duplicate same binding + changed runid/deadline same checkpoint -
    def test_duplicate_and_changed_runid_deadline_refuse(self):
        with synthetic_fixture() as root:
            b1 = self._make_binding(run_id="run-0001", deadline=1000)
            claim_checkpoint(root, b1)
            path = require_fixture_root(root)
            cp = self._claim_path(path, b1)
            before = cp.read_bytes()
            with self.assertRaises(SyntheticJournalError):
                claim_checkpoint(
                    root, self._make_binding(run_id="run-0001", deadline=1000))
            with self.assertRaises(SyntheticJournalError):
                claim_checkpoint(
                    root, self._make_binding(run_id="run-0002", deadline=1000))
            with self.assertRaises(SyntheticJournalError):
                claim_checkpoint(
                    root, self._make_binding(run_id="run-0001", deadline=2000))
            self.assertEqual(cp.read_bytes(), before)

    # --- invalid/fabricated/closed root + malformed binding fail before ---
    def test_invalid_root_and_malformed_binding_fail_before_claim(self):
        with synthetic_fixture() as root:
            path = require_fixture_root(root)
            b1 = self._make_binding()
            forged = object.__new__(SyntheticFixtureRoot)
            with self.assertRaises(SyntheticJournalError):
                claim_checkpoint(forged, b1)
            with self.assertRaises(SyntheticJournalError):
                claim_checkpoint(str(path), b1)
            with self.assertRaises(SyntheticJournalError):
                claim_checkpoint(root, "not-a-binding")
            with self.assertRaises(SyntheticJournalError):
                claim_checkpoint(root, 12345)
            self.assertFalse(self._claim_path(path, b1).exists())
        closed = None
        with synthetic_fixture() as r:
            closed = r
        with self.assertRaises(SyntheticJournalError):
            claim_checkpoint(closed, self._make_binding())

    # --- racing same checkpoint: exactly one winner ----------------------
    def test_racing_same_checkpoint_exactly_one_winner(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        with synthetic_fixture() as root:
            binding = self._make_binding()
            n = 8
            barrier = Barrier(n)

            def worker():
                barrier.wait()
                try:
                    claim_checkpoint(root, binding)
                    return "success"
                except SyntheticJournalError:
                    return "refusal"

            with ThreadPoolExecutor(max_workers=n) as ex:
                futures = [ex.submit(worker) for _ in range(n)]
                results = [f.result() for f in futures]
            self.assertEqual(results.count("success"), 1)
            self.assertEqual(results.count("refusal"), n - 1)

    # --- existing empty/partial claim refuses, bytes unchanged -----------
    def test_existing_empty_partial_claim_refuses(self):
        with synthetic_fixture() as root:
            path = require_fixture_root(root)
            b1 = self._make_binding()
            cp = self._claim_path(path, b1)
            cp.write_bytes(b"")
            with self.assertRaises(SyntheticJournalError):
                claim_checkpoint(root, b1)
            self.assertEqual(cp.read_bytes(), b"")
            cp.write_bytes(b"{'partial':")
            with self.assertRaises(SyntheticJournalError):
                claim_checkpoint(root, b1)
            self.assertEqual(cp.read_bytes(), b"{'partial':")

    # --- injected short write leaves partial file; retry refuses ---------
    def test_injected_short_write_leaves_partial_and_retry_refuses(self):
        import builtins
        real_open = builtins.open

        class _ShortWriteFile:
            def __init__(self, fh):
                self._fh = fh

            def write(self, data):
                n = len(data) // 2
                self._fh.write(data[:n])
                return n

            def __getattr__(self, name):
                return getattr(self._fh, name)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return self._fh.__exit__(*exc)

        def fake_open(file, mode="r", *a, **k):
            fh = real_open(file, mode, *a, **k)
            if mode == "xb":
                return _ShortWriteFile(fh)
            return fh

        with synthetic_fixture() as root:
            path = require_fixture_root(root)
            b1 = self._make_binding()
            cp = self._claim_path(path, b1)
            builtins.open = fake_open
            try:
                with self.assertRaises(SyntheticJournalError):
                    claim_checkpoint(root, b1)
            finally:
                builtins.open = real_open
            self.assertTrue(cp.exists())
            partial = cp.read_bytes()
            self.assertGreater(len(partial), 0)
            with self.assertRaises(SyntheticJournalError):
                claim_checkpoint(root, b1)
            self.assertEqual(cp.read_bytes(), partial)

    # --- ordinary claim/flag mutation/replacement flags refuse -----------
    def test_claim_mutation_and_flag_replacement_refuse(self):
        with synthetic_fixture() as root:
            b1 = self._make_binding()
            claim = claim_checkpoint(root, b1)
            with self.assertRaises(SyntheticJournalError):
                SyntheticClaim("x", "y")
            with self.assertRaises(AttributeError):
                claim.SYNTHETIC = False
            with self.assertRaises(AttributeError):
                claim.header_sha256 = "z" * 64
            with self.assertRaises(AttributeError):
                del claim._binding

    # --- carry forward bounded marker-read instrumentation ---------------
    def test_marker_read_bounded_instrumentation(self):
        import builtins
        real_open = builtins.open
        read_args = []

        class _TrackingFile:
            def __init__(self, fh):
                self._fh = fh

            def read(self, *a):
                if a:
                    read_args.append(a[0])
                return self._fh.read(*a)

            def __getattr__(self, name):
                return getattr(self._fh, name)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return self._fh.__exit__(*exc)

        def fake_open(file, mode="r", *a, **k):
            fh = real_open(file, mode, *a, **k)
            if mode == "rb":
                return _TrackingFile(fh)
            return fh

        builtins.open = fake_open
        try:
            with synthetic_fixture() as root:
                require_fixture_root(root)
                with self.assertRaises(AttributeError):
                    root._open = False
                with self.assertRaises(AttributeError):
                    del root._path
        finally:
            builtins.open = real_open
        self.assertTrue(read_args)
        for n in read_args:
            self.assertLessEqual(n, 4097)


class SyntheticJournalReaderTests(unittest.TestCase):
    def _binding(self, checkpoint="a" * 40, run_id="run-0001", deadline=1000):
        return validate_state_binding(checkpoint, run_id, "b" * 64, deadline)

    # --- valid handbuilt RESERVED chain and terminal/abort ---------------
    def test_valid_reserved_chain(self):
        b = self._binding()
        hist = _build_history(
            b, [("e" * 64, "RESERVED", 100), ("f" * 64, "VERIFIED", 200)])
        with synthetic_fixture() as root:
            _build_journal(root, b, hist)
            snap = load_journal(root, b)
            self.assertEqual(snap.head_sequence, 1)
            self.assertEqual(len(snap.history), 2)
            self.assertEqual(snap.facts.phase, "VERIFIED")
            self.assertIs(snap.facts.terminal, False)
            self.assertEqual(snap.history, hist)

    def test_valid_terminal_chain(self):
        b = self._binding()
        hist = _build_history(b, [
            ("e" * 64, "RESERVED", 100),
            ("f" * 64, "VERIFIED", 200),
            ("1" * 64, "ACTIVATION_RESERVED", 300),
            ("2" * 64, "RUNNER_STARTED", 400),
            ("3" * 64, "TERMINAL", 500),
        ])
        with synthetic_fixture() as root:
            _build_journal(root, b, hist)
            snap = load_journal(root, b)
            self.assertEqual(snap.head_sequence, 4)
            self.assertIs(snap.facts.terminal, True)
            snap2 = load_journal(root, b, require_terminal=True)
            self.assertIs(snap2.facts.terminal, True)

    def test_valid_abort_chain(self):
        b = self._binding()
        hist = _build_history(
            b, [("e" * 64, "RESERVED", 100), ("f" * 64, "ABORT", 200)])
        with synthetic_fixture() as root:
            _build_journal(root, b, hist)
            snap = load_journal(root, b)
            self.assertIs(snap.facts.terminal, True)
            self.assertEqual(snap.facts.phase, "ABORT")

    # --- header only / require terminal ----------------------------------
    def test_header_only_incomplete(self):
        b = self._binding()
        with synthetic_fixture() as root:
            _build_journal(root, b, ())
            snap = load_journal(root, b)
            self.assertEqual(snap.head_sequence, -1)
            self.assertIsNone(snap.facts)
            self.assertEqual(len(snap.history), 0)
            self.assertEqual(snap.head_sha256, snap.header_sha256)

    def test_header_only_require_terminal_refuses(self):
        b = self._binding()
        with synthetic_fixture() as root:
            _build_journal(root, b, ())
            with self.assertRaises(SyntheticJournalError):
                load_journal(root, b, require_terminal=True)

    def test_nonterminal_require_terminal_refuses(self):
        b = self._binding()
        hist = _build_history(b, [("e" * 64, "RESERVED", 100)])
        with synthetic_fixture() as root:
            _build_journal(root, b, hist)
            with self.assertRaises(SyntheticJournalError):
                load_journal(root, b, require_terminal=True)

    def _single_payload_path(self, root, b):
        """Build valid single-event journal; return (fixture_path, payload_path)."""
        hist = _build_history(b, [("e" * 64, "RESERVED", 100)])
        fp = _build_journal(root, b, hist)
        pp = fp / ("SYNTHETIC-event-%s-0000.json" % b.checkpoint_key)
        return fp, pp

    def _event_dict(self, b, seq=0, event_id="e" * 64, phase="RESERVED",
                    now=100):
        return {
            "checkpoint_key": b.checkpoint_key,
            "run_id": b.run_id,
            "run_binding_sha256": b.run_binding_sha256,
            "deadline": b.deadline,
            "sequence": seq,
            "event_id": event_id,
            "phase": phase,
            "observed_now": now,
        }

    # --- wrong expected run/checkpoint/deadline --------------------------
    def test_wrong_expected_run_refuses(self):
        b = self._binding(run_id="run-0001")
        with synthetic_fixture() as root:
            self._single_payload_path(root, b)
            with self.assertRaises(SyntheticJournalError):
                load_journal(root, self._binding(run_id="run-0002"))

    def test_wrong_expected_checkpoint_refuses(self):
        b = self._binding(checkpoint="a" * 40)
        with synthetic_fixture() as root:
            self._single_payload_path(root, b)
            with self.assertRaises(SyntheticJournalError):
                load_journal(root, self._binding(checkpoint="c" * 40))

    def test_wrong_expected_deadline_refuses(self):
        b = self._binding(deadline=1000)
        with synthetic_fixture() as root:
            self._single_payload_path(root, b)
            with self.assertRaises(SyntheticJournalError):
                load_journal(root, self._binding(deadline=2000))

    # --- malformed: duplicate keys / extras / flags 1 / bad json / utf8 ---
    def test_malformed_duplicate_keys_refuses(self):
        b = self._binding()
        with synthetic_fixture() as root:
            _, pp = self._single_payload_path(root, b)
            pp.write_bytes(b'{"format":"X","format":"Y"}')
            with self.assertRaises(SyntheticJournalError):
                load_journal(root, b)

    def test_malformed_extra_key_refuses(self):
        b = self._binding()
        with synthetic_fixture() as root:
            _, pp = self._single_payload_path(root, b)
            payload = {
                "format": "SYNTHETIC_EVENT_V1",
                "SYNTHETIC": True,
                "NON_PRODUCTION": True,
                "AUTHORIZES_EXECUTION": False,
                "previous_sha256": "0" * 64,
                "event": self._event_dict(b),
                "EXTRA": True,
            }
            pp.write_bytes(_canon(payload))
            with self.assertRaises(SyntheticJournalError):
                load_journal(root, b)

    def test_malformed_flag_integer_refuses(self):
        b = self._binding()
        with synthetic_fixture() as root:
            _, pp = self._single_payload_path(root, b)
            payload = {
                "format": "SYNTHETIC_EVENT_V1",
                "SYNTHETIC": 1,
                "NON_PRODUCTION": True,
                "AUTHORIZES_EXECUTION": False,
                "previous_sha256": "0" * 64,
                "event": self._event_dict(b),
            }
            pp.write_bytes(_canon(payload))
            with self.assertRaises(SyntheticJournalError):
                load_journal(root, b)

    def test_malformed_invalid_json_refuses(self):
        b = self._binding()
        with synthetic_fixture() as root:
            _, pp = self._single_payload_path(root, b)
            pp.write_bytes(b'this is not json')
            with self.assertRaises(SyntheticJournalError):
                load_journal(root, b)

    def test_malformed_invalid_utf8_refuses(self):
        b = self._binding()
        with synthetic_fixture() as root:
            _, pp = self._single_payload_path(root, b)
            pp.write_bytes(b'\xff\xfe\x00 bad utf8')
            with self.assertRaises(SyntheticJournalError):
                load_journal(root, b)

    def test_malformed_overbound_refuses(self):
        b = self._binding()
        with synthetic_fixture() as root:
            _, pp = self._single_payload_path(root, b)
            pp.write_bytes(b'X' * 16385)
            with self.assertRaises(SyntheticJournalError):
                load_journal(root, b)

    def _rewrite_seal(self, fp, b, seq, **overrides):
        seal_path = fp / ("SYNTHETIC-event-%s-%04d.seal.json" % (b.checkpoint_key, seq))
        obj = json.loads(seal_path.read_bytes().decode("utf-8"))
        obj.update(overrides)
        seal_path.write_bytes(_canon(obj))

    def _corrupt_event_field(self, fp, b, seq, field, value):
        """Corrupt a payload event field and update the seal to match."""
        ck = b.checkpoint_key
        payload_path = fp / ("SYNTHETIC-event-%s-%04d.json" % (ck, seq))
        obj = json.loads(payload_path.read_bytes().decode("utf-8"))
        obj["event"][field] = value
        pb = _canon(obj)
        payload_path.write_bytes(pb)
        seal_path = fp / ("SYNTHETIC-event-%s-%04d.seal.json" % (ck, seq))
        seal = json.loads(seal_path.read_bytes().decode("utf-8"))
        seal["payload_sha256"] = hashlib.sha256(pb).hexdigest()
        seal["payload_bytes"] = len(pb)
        seal_path.write_bytes(_canon(seal))

    # --- payload hash / bytecount / link mismatch ------------------------
    def test_seal_wrong_payload_hash_refuses(self):
        b = self._binding()
        with synthetic_fixture() as root:
            fp, _ = self._single_payload_path(root, b)
            self._rewrite_seal(fp, b, 0, payload_sha256="0" * 64)
            with self.assertRaises(SyntheticJournalError):
                load_journal(root, b)

    def test_seal_wrong_payload_bytes_refuses(self):
        b = self._binding()
        with synthetic_fixture() as root:
            fp, _ = self._single_payload_path(root, b)
            self._rewrite_seal(fp, b, 0, payload_bytes=999999)
            with self.assertRaises(SyntheticJournalError):
                load_journal(root, b)

    def test_payload_wrong_previous_link_refuses(self):
        b = self._binding()
        with synthetic_fixture() as root:
            fp, pp = self._single_payload_path(root, b)
            obj = json.loads(pp.read_bytes().decode("utf-8"))
            obj["previous_sha256"] = "0" * 64
            pp.write_bytes(_canon(obj))
            with self.assertRaises(SyntheticJournalError):
                load_journal(root, b)

    # --- missing predecessor / gap ---------------------------------------
    def test_gap_missing_predecessor_refuses(self):
        b = self._binding()
        hist = _build_history(b, [
            ("e" * 64, "RESERVED", 100),
            ("f" * 64, "VERIFIED", 200),
            ("1" * 64, "ACTIVATION_RESERVED", 300),
        ])
        with synthetic_fixture() as root:
            fp = _build_journal(root, b, hist)
            ck = b.checkpoint_key
            (fp / ("SYNTHETIC-event-%s-0001.json" % ck)).unlink()
            (fp / ("SYNTHETIC-event-%s-0001.seal.json" % ck)).unlink()
            with self.assertRaises(SyntheticJournalError):
                load_journal(root, b)

    # --- orphan payload / seal -------------------------------------------
    def test_orphan_payload_without_seal_refuses(self):
        b = self._binding()
        hist = _build_history(
            b, [("e" * 64, "RESERVED", 100), ("f" * 64, "VERIFIED", 200)])
        with synthetic_fixture() as root:
            fp = _build_journal(root, b, hist)
            (fp / ("SYNTHETIC-event-%s-0001.seal.json" % b.checkpoint_key)).unlink()
            with self.assertRaises(SyntheticJournalError):
                load_journal(root, b)

    def test_orphan_seal_without_payload_refuses(self):
        b = self._binding()
        hist = _build_history(
            b, [("e" * 64, "RESERVED", 100), ("f" * 64, "VERIFIED", 200)])
        with synthetic_fixture() as root:
            fp = _build_journal(root, b, hist)
            (fp / ("SYNTHETIC-event-%s-0001.json" % b.checkpoint_key)).unlink()
            with self.assertRaises(SyntheticJournalError):
                load_journal(root, b)

    # --- wrong phase / eventid / order -----------------------------------
    def test_wrong_phase_refuses(self):
        b = self._binding()
        with synthetic_fixture() as root:
            fp, _ = self._single_payload_path(root, b)
            self._corrupt_event_field(fp, b, 0, "phase", "VERIFIED")
            with self.assertRaises(SyntheticJournalError):
                load_journal(root, b)

    def test_wrong_sequence_field_refuses(self):
        b = self._binding()
        with synthetic_fixture() as root:
            fp, _ = self._single_payload_path(root, b)
            self._corrupt_event_field(fp, b, 0, "sequence", 1)
            with self.assertRaises(SyntheticJournalError):
                load_journal(root, b)

    def test_duplicate_event_id_refuses(self):
        b = self._binding()
        ck = b.checkpoint_key
        ev0 = StateEventClaims(
            ck, b.run_id, b.run_binding_sha256, b.deadline, 0,
            "e" * 64, "RESERVED", 100)
        ev1 = StateEventClaims(
            ck, b.run_id, b.run_binding_sha256, b.deadline, 1,
            "e" * 64, "VERIFIED", 200)
        with synthetic_fixture() as root:
            _build_journal(root, b, (ev0, ev1))
            with self.assertRaises(SyntheticJournalError):
                load_journal(root, b)

    # --- immutable snapshots + no file mutation on failed reads ----------
    def test_snapshot_immutable(self):
        b = self._binding()
        hist = _build_history(b, [("e" * 64, "RESERVED", 100)])
        with synthetic_fixture() as root:
            _build_journal(root, b, hist)
            snap = load_journal(root, b)
            with self.assertRaises(SyntheticJournalError):
                SyntheticJournalSnapshot("x")
            with self.assertRaises(AttributeError):
                snap.history = ()
            with self.assertRaises(AttributeError):
                snap.facts = None
            with self.assertRaises(AttributeError):
                del snap._binding

    def test_no_file_mutation_on_failed_read(self):
        b = self._binding()
        with synthetic_fixture() as root:
            fp, pp = self._single_payload_path(root, b)
            seal_path = fp / ("SYNTHETIC-event-%s-0000.seal.json" % b.checkpoint_key)
            seal_before = seal_path.read_bytes()
            pp.write_bytes(b'corrupted')
            with self.assertRaises(SyntheticJournalError):
                load_journal(root, b)
            self.assertEqual(pp.read_bytes(), b'corrupted')
            self.assertEqual(seal_path.read_bytes(), seal_before)

    # --- boundary repair regressions -------------------------------------
    def test_alias_orphan_refuses(self):
        b = self._binding()
        with synthetic_fixture() as root:
            fp = _build_journal(root, b, ())
            (fp / ("SYNTHETIC-EVENT-%s-0000.json" % b.checkpoint_key)).write_bytes(b"{}")
            with self.assertRaises(SyntheticJournalError):
                load_journal(root, b)

    def test_listdir_fault_normalizes(self):
        import v213_qa_capacity_synthetic_journal as mod
        b = self._binding()
        real_listdir = mod.os.listdir

        def boom(d):
            raise OSError("injected listdir")

        mod.os.listdir = boom
        try:
            with synthetic_fixture() as root:
                _build_journal(root, b, ())
                with self.assertRaises(SyntheticJournalError):
                    load_journal(root, b)
        finally:
            mod.os.listdir = real_listdir

    def test_giant_json_int_normalizes(self):
        b = self._binding()
        with synthetic_fixture() as root:
            fp = _build_journal(root, b, ())
            (fp / ("SYNTHETIC-event-%s-0000.json" % b.checkpoint_key)).write_bytes(
                b'{"deadline":' + b"9" * 5000 + b"}")
            (fp / ("SYNTHETIC-event-%s-0000.seal.json" % b.checkpoint_key)).write_bytes(b"{}")
            with self.assertRaises(SyntheticJournalError):
                load_journal(root, b)

    def test_recursion_depth_normalizes(self):
        b = self._binding()
        with synthetic_fixture() as root:
            fp = _build_journal(root, b, ())
            deep = b"[" * 3000 + b"]" * 3000
            (fp / ("SYNTHETIC-event-%s-0000.json" % b.checkpoint_key)).write_bytes(deep)
            (fp / ("SYNTHETIC-event-%s-0000.seal.json" % b.checkpoint_key)).write_bytes(b"{}")
            with self.assertRaises(SyntheticJournalError):
                load_journal(root, b)


class SyntheticAppendTests(unittest.TestCase):
    def _binding(self, checkpoint="a" * 40, run_id="run-0001", deadline=1000):
        return validate_state_binding(checkpoint, run_id, "b" * 64, deadline)

    def _run_chain(self, root, b, steps):
        claim = claim_checkpoint(root, b)
        prev = claim.header_sha256
        snap = None
        for i, (eid, ph, now) in enumerate(steps):
            snap = append_record(root, b, eid, ph, now,
                                 expected_sequence=i,
                                 expected_previous_sha256=prev)
            prev = snap.head_sha256
        return claim, snap

    # --- normal RES->VER->ACT->RUN->TERMINAL producer/reader roundtrip ----
    def test_full_roundtrip(self):
        b = self._binding()
        steps = [
            ("e" * 64, "RESERVED", 100),
            ("f" * 64, "VERIFIED", 200),
            ("1" * 64, "ACTIVATION_RESERVED", 300),
            ("2" * 64, "RUNNER_STARTED", 400),
            ("3" * 64, "TERMINAL", 500),
        ]
        with synthetic_fixture() as root:
            _, snap = self._run_chain(root, b, steps)
            self.assertEqual(snap.head_sequence, 4)
            self.assertIs(snap.facts.terminal, True)
            loaded = load_journal(root, b)
            self.assertEqual(loaded.head_sequence, 4)
            self.assertEqual(len(loaded.history), 5)
            self.assertIs(loaded.facts.terminal, True)
            self.assertEqual(loaded.history, snap.history)

    # --- ABORT preserving invocation_count 0/None/1 ----------------------
    def test_abort_preserves_flags(self):
        b = self._binding()
        with synthetic_fixture() as root:
            _, snap = self._run_chain(root, b, [
                ("e" * 64, "RESERVED", 100), ("f" * 64, "ABORT", 200)])
            self.assertIs(snap.facts.terminal, True)
            self.assertEqual(snap.facts.invocation_count, 0)
        with synthetic_fixture() as root:
            _, snap = self._run_chain(root, b, [
                ("e" * 64, "RESERVED", 100),
                ("f" * 64, "VERIFIED", 200),
                ("1" * 64, "ACTIVATION_RESERVED", 300),
                ("2" * 64, "ABORT", 400)])
            self.assertIs(snap.facts.terminal, True)
            self.assertIsNone(snap.facts.invocation_count)
        with synthetic_fixture() as root:
            _, snap = self._run_chain(root, b, [
                ("e" * 64, "RESERVED", 100),
                ("f" * 64, "VERIFIED", 200),
                ("1" * 64, "ACTIVATION_RESERVED", 300),
                ("2" * 64, "RUNNER_STARTED", 400),
                ("3" * 64, "ABORT", 500)])
            self.assertIs(snap.facts.terminal, True)
            self.assertEqual(snap.facts.invocation_count, 1)

    # --- wrong/stale expected head sequence/hash -------------------------
    def test_stale_head_sequence_and_hash(self):
        b = self._binding()
        with synthetic_fixture() as root:
            claim, s0 = self._run_chain(
                root, b, [("e" * 64, "RESERVED", 100)])
            with self.assertRaises(SyntheticJournalError):
                append_record(root, b, "f" * 64, "VERIFIED", 200,
                              expected_sequence=5,
                              expected_previous_sha256=s0.head_sha256)
            with self.assertRaises(SyntheticJournalError):
                append_record(root, b, "f" * 64, "VERIFIED", 200,
                              expected_sequence=1,
                              expected_previous_sha256="0" * 64)

    # --- first wrong phase ------------------------------------------------
    def test_first_wrong_phase(self):
        b = self._binding()
        with synthetic_fixture() as root:
            claim = claim_checkpoint(root, b)
            with self.assertRaises(SyntheticJournalError):
                append_record(root, b, "e" * 64, "VERIFIED", 100,
                              expected_sequence=0,
                              expected_previous_sha256=claim.header_sha256)

    # --- malformed id/time/binding no new files --------------------------
    def test_malformed_id_time_binding_no_new_files(self):
        b = self._binding()
        with synthetic_fixture() as root:
            claim = claim_checkpoint(root, b)
            fp = require_fixture_root(root)
            before = sorted(x.name for x in fp.iterdir())
            with self.assertRaises(SyntheticJournalError):
                append_record(root, b, "not-a-sha", "RESERVED", 100,
                              expected_sequence=0,
                              expected_previous_sha256=claim.header_sha256)
            with self.assertRaises(SyntheticJournalError):
                append_record(root, b, "e" * 64, "RESERVED", float("nan"),
                              expected_sequence=0,
                              expected_previous_sha256=claim.header_sha256)
            wrong = self._binding(run_id="run-0002")
            with self.assertRaises(SyntheticJournalError):
                append_record(root, wrong, "e" * 64, "RESERVED", 100,
                              expected_sequence=0,
                              expected_previous_sha256=claim.header_sha256)
            after = sorted(x.name for x in fp.iterdir())
            self.assertEqual(before, after)

    # --- duplicate event and post-terminal append refuse -----------------
    def test_duplicate_event_and_post_terminal_refuse(self):
        b = self._binding()
        with synthetic_fixture() as root:
            claim = claim_checkpoint(root, b)
            s0 = append_record(root, b, "e" * 64, "RESERVED", 100,
                               expected_sequence=0,
                               expected_previous_sha256=claim.header_sha256)
            with self.assertRaises(SyntheticJournalError):
                append_record(root, b, "e" * 64, "VERIFIED", 200,
                              expected_sequence=1,
                              expected_previous_sha256=s0.head_sha256)
            s1 = append_record(root, b, "f" * 64, "ABORT", 200,
                               expected_sequence=1,
                               expected_previous_sha256=s0.head_sha256)
            with self.assertRaises(SyntheticJournalError):
                append_record(root, b, "9" * 64, "VERIFIED", 300,
                              expected_sequence=2,
                              expected_previous_sha256=s1.head_sha256)

    # --- phase exact builtin str enforced before comparison (C2 repair) --
    def test_phase_str_subclass_spoof_poison_rejected(self):
        b = self._binding()
        with synthetic_fixture() as root:
            claim = claim_checkpoint(root, b)
            fp = require_fixture_root(root)
            before = sorted(x.name for x in fp.iterdir())

            # (1) str subclass of RESERVED (exact value, wrong type)
            class _SubReserved(str):
                pass
            with self.assertRaises(SyntheticJournalError):
                append_record(root, b, "e" * 64, _SubReserved("RESERVED"), 100,
                              expected_sequence=0,
                              expected_previous_sha256=claim.header_sha256)

            # (2) equality spoof: compares equal to RESERVED, not exact str
            class _Spoof(str):
                def __eq__(self, other):
                    return True
                def __ne__(self, other):
                    return False
                def __hash__(self):
                    return 0
            with self.assertRaises(SyntheticJournalError):
                append_record(root, b, "e" * 64, _Spoof("RESERVED"), 100,
                              expected_sequence=0,
                              expected_previous_sha256=claim.header_sha256)

            # (3) poison: custom __ne__ raises (must not leak)
            class _Poison(str):
                def __ne__(self, other):
                    raise RuntimeError("poison __ne__ leaked")
            with self.assertRaises(SyntheticJournalError):
                append_record(root, b, "e" * 64, _Poison("RESERVED"), 100,
                              expected_sequence=0,
                              expected_previous_sha256=claim.header_sha256)

            after = sorted(x.name for x in fp.iterdir())
            self.assertEqual(before, after)

    # --- writer root + arg validation before IO/comparisons (C2 repair) --
    def test_writer_root_and_arg_validation(self):
        import v213_qa_capacity_synthetic_journal as mod
        b = self._binding()
        with synthetic_fixture() as root:
            fp = require_fixture_root(root)
            before = sorted(x.name for x in fp.iterdir())
            ck = b.checkpoint_key

            # raw root (Path) rejected
            with self.assertRaises(SyntheticJournalError):
                mod._write_exclusive(fp, ck, 0, "payload", b"x", "raw-root")
            # raw root (str) rejected
            with self.assertRaises(SyntheticJournalError):
                mod._write_exclusive(str(fp), ck, 0, "payload", b"x",
                                     "str-root")
            # fabricated root (not factory-issued) rejected
            fab = object.__new__(SyntheticFixtureRoot)
            with self.assertRaises(SyntheticJournalError):
                mod._write_exclusive(fab, ck, 0, "payload", b"x", "fab-root")

            # malformed checkpoint (hostile non-str) rejected, no eq touch
            hostile = _Hostile()
            with self.assertRaises(SyntheticJournalError):
                mod._write_exclusive(root, hostile, 0, "payload", b"x",
                                     "hostile-ck")
            self.assertEqual(hostile.hits, [])

            # str subclass checkpoint rejected (exact builtin str required)
            class _SubCk(str):
                pass
            with self.assertRaises(SyntheticJournalError):
                mod._write_exclusive(root, _SubCk(ck), 0, "payload", b"x",
                                     "sub-ck")

            # non-canonical checkpoint (40 chars, not hex) rejected
            with self.assertRaises(SyntheticJournalError):
                mod._write_exclusive(root, "z" * 40, 0, "payload", b"x",
                                     "bad-ck")

            # malformed seq: bool rejected
            with self.assertRaises(SyntheticJournalError):
                mod._write_exclusive(root, ck, True, "payload", b"x",
                                     "bool-seq")
            # malformed seq: out of range rejected
            with self.assertRaises(SyntheticJournalError):
                mod._write_exclusive(root, ck, 5, "payload", b"x", "range-seq")
            # malformed seq: negative rejected
            with self.assertRaises(SyntheticJournalError):
                mod._write_exclusive(root, ck, -1, "payload", b"x", "neg-seq")

            # malformed kind: non-str rejected
            with self.assertRaises(SyntheticJournalError):
                mod._write_exclusive(root, ck, 0, 123, b"x", "int-kind")
            # malformed kind: wrong value rejected
            with self.assertRaises(SyntheticJournalError):
                mod._write_exclusive(root, ck, 0, "claim", b"x", "bad-kind")

            after = sorted(x.name for x in fp.iterdir())
            self.assertEqual(before, after)

    # --- prior bytes unchanged on failed append --------------------------
    def test_prior_bytes_unchanged(self):
        b = self._binding()
        with synthetic_fixture() as root:
            _, s0 = self._run_chain(
                root, b, [("e" * 64, "RESERVED", 100)])
            fp = require_fixture_root(root)
            ck = b.checkpoint_key
            p0 = (fp / ("SYNTHETIC-event-%s-0000.json" % ck)).read_bytes()
            s0s = (fp / ("SYNTHETIC-event-%s-0000.seal.json" % ck)).read_bytes()
            with self.assertRaises(SyntheticJournalError):
                append_record(root, b, "f" * 64, "VERIFIED", 200,
                              expected_sequence=9,
                              expected_previous_sha256=s0.head_sha256)
            self.assertEqual(
                (fp / ("SYNTHETIC-event-%s-0000.json" % ck)).read_bytes(), p0)
            self.assertEqual(
                (fp / ("SYNTHETIC-event-%s-0000.seal.json" % ck)).read_bytes(), s0s)

    # --- missing seal injected failure leaves orphan; retry refuses ------
    def test_missing_seal_injected_failure(self):
        import v213_qa_capacity_synthetic_journal as mod
        b = self._binding()
        with synthetic_fixture() as root:
            _, s0 = self._run_chain(
                root, b, [("e" * 64, "RESERVED", 100)])
            fp = require_fixture_root(root)
            ck = b.checkpoint_key
            real_write = mod._write_exclusive

            def flaky_write(root, checkpoint, seq, kind, data, context):
                if kind == "seal":
                    raise SyntheticJournalError("injected seal failure")
                return real_write(root, checkpoint, seq, kind, data, context)

            mod._write_exclusive = flaky_write
            try:
                with self.assertRaises(SyntheticJournalError):
                    append_record(root, b, "f" * 64, "VERIFIED", 200,
                                  expected_sequence=1,
                                  expected_previous_sha256=s0.head_sha256)
            finally:
                mod._write_exclusive = real_write
            self.assertTrue(
                (fp / ("SYNTHETIC-event-%s-0001.json" % ck)).exists())
            self.assertFalse(
                (fp / ("SYNTHETIC-event-%s-0001.seal.json" % ck)).exists())
            with self.assertRaises(SyntheticJournalError):
                append_record(root, b, "f" * 64, "VERIFIED", 200,
                              expected_sequence=1,
                              expected_previous_sha256=s0.head_sha256)

    # --- actual readback mismatch fail closed ----------------------------
    def test_readback_mismatch_fail_closed(self):
        import v213_qa_capacity_synthetic_journal as mod
        b = self._binding()
        with synthetic_fixture() as root:
            real_bounded_read = mod._bounded_read

            def mismatch_read(path, limit, context):
                return b"mismatch"

            mod._bounded_read = mismatch_read
            try:
                with self.assertRaises(SyntheticJournalError):
                    mod._write_exclusive(
                        root, b.checkpoint_key, 0, "payload",
                        b"payload-data", "test")
            finally:
                mod._bounded_read = real_bounded_read


class SyntheticDTests(unittest.TestCase):
    """T05-D bounded synthetic qualification: competing appends/claims,
    deterministic fault matrix, lost response, restart/recovery, poison
    preservation. Synthetic-only; no process/native/real-namespace.
    """

    def _binding(self, checkpoint="a" * 40, run_id="run-0001", deadline=1000):
        return validate_state_binding(checkpoint, run_id, "b" * 64, deadline)

    def _run_chain(self, root, b, steps):
        claim = claim_checkpoint(root, b)
        prev = claim.header_sha256
        snap = None
        for i, (eid, ph, now) in enumerate(steps):
            snap = append_record(root, b, eid, ph, now,
                                 expected_sequence=i,
                                 expected_previous_sha256=prev)
            prev = snap.head_sha256
        return claim, snap

    @staticmethod
    def _file_map(fp):
        return {p.name: p.read_bytes() for p in fp.iterdir()}

    def _attempt_append(self, root, b, seq, prev_sha):
        return append_record(root, b, "f" * 64, "VERIFIED", 200,
                             expected_sequence=seq,
                             expected_previous_sha256=prev_sha)

    def _reference_event_bytes(self, b):
        """Full canonical seq-1 payload/seal bytes from a clean fixture."""
        with synthetic_fixture() as root:
            _, s0 = self._run_chain(root, b, [("e" * 64, "RESERVED", 100)])
            self._attempt_append(root, b, 1, s0.head_sha256)
            fp = require_fixture_root(root)
            ck = b.checkpoint_key
            pb = (fp / ("SYNTHETIC-event-%s-0001.json" % ck)).read_bytes()
            sb = (fp / ("SYNTHETIC-event-%s-0001.seal.json" % ck)).read_bytes()
        return pb, sb

    def _arm_fault(self, mod, root, target_name, stage, counter):
        """Arm a fault at `stage` on the file named `target_name` only.

        Wraps the real owned temp-fixture handles at the chosen operation;
        all other IO is preserved (delegated to the real handle). Appends to
        `counter` on each actual fault occurrence. Returns a restore().
        """
        import builtins
        real_open = builtins.open
        real_fsync = mod.os.fsync
        target_is_seal = target_name.endswith(".seal.json")
        target_fsync_index = 2 if target_is_seal else 1

        if stage in ("create", "short_write", "flush"):
            class _FaultFile:
                def __init__(self, fh):
                    self._fh = fh

                def write(self, data):
                    if stage == "short_write":
                        counter.append("short_write")
                        n = len(data) // 2
                        self._fh.write(data[:n])
                        return n
                    return self._fh.write(data)

                def flush(self):
                    if stage == "flush":
                        counter.append("flush")
                        raise OSError("injected flush failure")
                    return self._fh.flush()

                def __getattr__(self, name):
                    return getattr(self._fh, name)

                def __enter__(self):
                    return self

                def __exit__(self, *exc):
                    return self._fh.__exit__(*exc)

            def fake_open(file, mode="r", *a, **k):
                if mode == "xb" and Path(file).name == target_name:
                    if stage == "create":
                        counter.append("create")
                        raise OSError("injected create failure")
                    return _FaultFile(real_open(file, mode, *a, **k))
                return real_open(file, mode, *a, **k)

            builtins.open = fake_open
        elif stage == "fsync":
            state = {"calls": 0}

            def fake_fsync(fd):
                state["calls"] += 1
                if state["calls"] == target_fsync_index:
                    counter.append("fsync")
                    raise OSError("injected fsync failure")
                return real_fsync(fd)

            mod.os.fsync = fake_fsync
        elif stage in ("readback_mismatch", "readback_error"):
            # Inject through the real target file handle rb open/read so the
            # real _bounded_read executes and normalizes the actual OSError
            # to SyntheticJournalError (preserves the production boundary).
            class _ReadFaultFile:
                def __init__(self, fh):
                    self._fh = fh

                def read(self, *a):
                    counter.append(stage)
                    if stage == "readback_error":
                        raise OSError("injected readback error")
                    return b"mismatch"

                def __getattr__(self, name):
                    return getattr(self._fh, name)

                def __enter__(self):
                    return self

                def __exit__(self, *exc):
                    return self._fh.__exit__(*exc)

            def fake_open_rb(file, mode="r", *a, **k):
                if mode == "rb" and Path(file).name == target_name:
                    return _ReadFaultFile(real_open(file, mode, *a, **k))
                return real_open(file, mode, *a, **k)

            builtins.open = fake_open_rb

        def restore():
            builtins.open = real_open
            mod.os.fsync = real_fsync

        return restore

    # --- competing exclusive appends at same expected head ---------------
    def test_competing_appends_same_head_one_winner(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        b = self._binding()
        with synthetic_fixture() as root:
            _, s0 = self._run_chain(root, b, [("e" * 64, "RESERVED", 100)])
            fp = require_fixture_root(root)
            before = self._file_map(fp)
            n = 8
            barrier = Barrier(n)

            def worker():
                barrier.wait(timeout=5)
                try:
                    self._attempt_append(root, b, 1, s0.head_sha256)
                    return "success"
                except SyntheticJournalError:
                    return "refusal"

            with ThreadPoolExecutor(max_workers=n) as ex:
                futures = [ex.submit(worker) for _ in range(n)]
                results = [f.result(timeout=60) for f in futures]
            self.assertEqual(results.count("success"), 1)
            self.assertEqual(results.count("refusal"), n - 1)
            after = self._file_map(fp)
            for name, data in before.items():
                self.assertEqual(after[name], data)
            ck = b.checkpoint_key
            self.assertIn("SYNTHETIC-event-%s-0001.json" % ck, after)
            self.assertIn("SYNTHETIC-event-%s-0001.seal.json" % ck, after)
            self.assertEqual(len(after), len(before) + 2)
            loaded = load_journal(root, b)
            self.assertEqual(loaded.head_sequence, 1)
            # loser retry with the same old expected head refuses (no retry)
            with self.assertRaises(SyntheticJournalError):
                self._attempt_append(root, b, 1, s0.head_sha256)

    # --- competing claims same checkpoint (differing run_id/deadline) ----
    def test_competing_claims_differing_runid_deadline_one_winner(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        b = self._binding()
        with synthetic_fixture() as root:
            fp = require_fixture_root(root)
            n = 8
            barrier = Barrier(n)
            variants = [
                self._binding(run_id="run-%04d" % (i + 1), deadline=1000 + i)
                for i in range(n)
            ]

            def worker(i):
                barrier.wait(timeout=5)
                try:
                    claim_checkpoint(root, variants[i])
                    return "success"
                except SyntheticJournalError:
                    return "refusal"

            with ThreadPoolExecutor(max_workers=n) as ex:
                futures = [ex.submit(worker, i) for i in range(n)]
                results = [f.result(timeout=60) for f in futures]
            self.assertEqual(results.count("success"), 1)
            self.assertEqual(results.count("refusal"), n - 1)
            cp = fp / ("SYNTHETIC-claim-%s.json" % b.checkpoint_key)
            self.assertTrue(cp.exists())
            self.assertGreater(len(cp.read_bytes()), 0)
            claims = [p for p in fp.iterdir()
                      if p.name.startswith("SYNTHETIC-claim-")]
            self.assertEqual(len(claims), 1)

    # --- deterministic fault matrix: payload/seal x stage ----------------
    def test_fault_matrix_payload_seal_stages(self):
        import v213_qa_capacity_synthetic_journal as mod
        b = self._binding()
        ref_payload, ref_seal = self._reference_event_bytes(b)
        stages = ("create", "short_write", "flush", "fsync",
                  "readback_mismatch", "readback_error")
        for target in ("payload", "seal"):
            for stage in stages:
                with self.subTest(target=target, stage=stage):
                    with synthetic_fixture() as root:
                        _, s0 = self._run_chain(
                            root, b, [("e" * 64, "RESERVED", 100)])
                        fp = require_fixture_root(root)
                        ck = b.checkpoint_key
                        seq = 1
                        prev_sha = s0.head_sha256
                        payload_name = ("SYNTHETIC-event-%s-%04d.json"
                                        % (ck, seq))
                        seal_name = ("SYNTHETIC-event-%s-%04d.seal.json"
                                     % (ck, seq))
                        target_name = (payload_name if target == "payload"
                                       else seal_name)
                        before = self._file_map(fp)
                        counter = []
                        restore = self._arm_fault(
                            mod, root, target_name, stage, counter)
                        try:
                            with self.assertRaises(SyntheticJournalError):
                                self._attempt_append(root, b, seq, prev_sha)
                        finally:
                            restore()
                        # exact occurrence counter: fault hit exactly once
                        self.assertEqual(counter, [stage])
                        after = self._file_map(fp)
                        for name, data in before.items():
                            self.assertEqual(after[name], data)
                        new_files = set(after) - set(before)
                        if target == "payload":
                            expected_new = (set() if stage == "create"
                                            else {payload_name})
                        else:
                            expected_new = ({payload_name}
                                            if stage == "create"
                                            else {payload_name, seal_name})
                        self.assertEqual(new_files, expected_new)
                        full = ref_payload if target == "payload" else ref_seal
                        if target_name in after:
                            if stage == "short_write":
                                self.assertGreater(len(after[target_name]), 0)
                                self.assertLess(len(after[target_name]),
                                                len(full))
                            else:
                                # flush/fsync/readback*: full canonical bytes
                                # (a readable committed record may exist;
                                #  never infer durability)
                                self.assertEqual(after[target_name], full)
                        # load behavior after refusal:
                        #  - clean pre-reservation (payload/create): oldhead
                        #    readable (head 0, seq-0 event intact)
                        #  - complete canonical seal after late flush/fsync/
                        #    readback error: may read committed (head 1)
                        #  - partial/orphan/missing seal: failclosed
                        if target == "payload" and stage == "create":
                            loaded = load_journal(root, b)
                            self.assertEqual(loaded.head_sequence, 0)
                        elif target == "seal" and stage in (
                                "flush", "fsync", "readback_mismatch",
                                "readback_error"):
                            loaded = load_journal(root, b)
                            self.assertEqual(loaded.head_sequence, 1)
                        else:
                            with self.assertRaises(SyntheticJournalError):
                                load_journal(root, b)
                        # reclaim an occupied checkpoint refuses and changes
                        # no bytes; a clean pre-reservation failure invokes no
                        # new append (oldhead unchanged + fault counter above;
                        # a later explicit append is covered by the existing
                        # successful roundtrip tests)
                        if new_files:
                            with self.assertRaises(SyntheticJournalError):
                                self._attempt_append(root, b, seq, prev_sha)
                            self.assertEqual(self._file_map(fp), after)

    # --- lost response AFTER complete commit -----------------------------
    def test_lost_response_after_complete_commit(self):
        b = self._binding()
        with synthetic_fixture() as root:
            claim = claim_checkpoint(root, b)
            s0 = append_record(root, b, "e" * 64, "RESERVED", 100,
                               expected_sequence=0,
                               expected_previous_sha256=claim.header_sha256)
            seq0_head_sha = s0.head_sha256
            s1 = append_record(root, b, "f" * 64, "VERIFIED", 200,
                               expected_sequence=1,
                               expected_previous_sha256=seq0_head_sha)
            fp = require_fixture_root(root)
            before = self._file_map(fp)
            # lost response: drop the returned snapshot; no retry from it
            del s1
            # fresh load recognizes the committed full chain
            loaded = load_journal(root, b)
            self.assertEqual(loaded.head_sequence, 1)
            self.assertEqual(len(loaded.history), 2)
            # old expected head retry refuses (stale); no duplicate/overwrite
            with self.assertRaises(SyntheticJournalError):
                append_record(root, b, "f" * 64, "VERIFIED", 200,
                              expected_sequence=1,
                              expected_previous_sha256=seq0_head_sha)
            after = self._file_map(fp)
            self.assertEqual(before, after)

    # --- restart/recovery within synthetic scope -------------------------
    def test_restart_recovery_same_live_fixture_closed_root_refuses(self):
        b = self._binding()
        with synthetic_fixture() as root:
            self._run_chain(root, b, [
                ("e" * 64, "RESERVED", 100),
                ("f" * 64, "VERIFIED", 200)])
            # restart/recovery: discard snapshots, reread with fresh calls
            # and handles on the SAME live fixture
            loaded = load_journal(root, b)
            self.assertEqual(loaded.head_sequence, 1)
            self.assertEqual(len(loaded.history), 2)
            # continue appending from the reread head (fresh handles)
            s2 = append_record(root, b, "1" * 64, "ACTIVATION_RESERVED", 300,
                               expected_sequence=2,
                               expected_previous_sha256=loaded.head_sha256)
            self.assertEqual(s2.head_sequence, 2)
        # closed root refuses reopening (no production path-reopen API)
        with self.assertRaises(SyntheticJournalError):
            load_journal(root, b)
        with self.assertRaises(SyntheticJournalError):
            append_record(root, b, "2" * 64, "RUNNER_STARTED", 400,
                          expected_sequence=3,
                          expected_previous_sha256="0" * 64)

    # --- incomplete terminal incl activation/run: no invocation0 infer ---
    def test_incomplete_terminal_cannot_infer_invocation0(self):
        b = self._binding()
        with synthetic_fixture() as root:
            self._run_chain(root, b, [
                ("e" * 64, "RESERVED", 100),
                ("f" * 64, "VERIFIED", 200),
                ("1" * 64, "ACTIVATION_RESERVED", 300)])
            loaded = load_journal(root, b)
            self.assertIs(loaded.facts.terminal, False)
            self.assertIsNone(loaded.facts.invocation_count)
            self.assertIs(loaded.facts.activation_history_ambiguous, True)
        with synthetic_fixture() as root:
            self._run_chain(root, b, [
                ("e" * 64, "RESERVED", 100),
                ("f" * 64, "VERIFIED", 200),
                ("1" * 64, "ACTIVATION_RESERVED", 300),
                ("2" * 64, "RUNNER_STARTED", 400)])
            loaded = load_journal(root, b)
            self.assertIs(loaded.facts.terminal, False)
            self.assertEqual(loaded.facts.invocation_count, 1)


if __name__ == "__main__":
    unittest.main()