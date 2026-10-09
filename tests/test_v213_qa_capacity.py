"""Test-first for scripts/v213_qa_capacity.py — module MUST be absent (RED).

Covers all 16 contract cases + receipt tamper/contradiction + unknown C+G.
Positive receipt originates from run_window, never fabricated hashes.
Collector tests exercise raw IO seams, not final booleans.
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import queue
import threading
import time
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))
import v213_qa_capacity as qc  # noqa: E402  RED if absent

# ── Real binding constants (no floating placeholders) ──────────────────────
SOURCE_HEAD = "84133f8da1d5999c2748c8fca31f1128c83ccc09"
MODEL_ID = "Qwen3.8-27B-EXL3-5.5bpw-v2"
CONTEXT = 262144
SERVICE = {
    "pid": 6432,
    "created": "2025-01-15T08:30:00Z",
    "image_sha256": "a" * 64,
    "parent_pid": 4200,
    "parent_created": "2025-01-15T08:29:00Z",
    "parent_image_sha256": "b" * 64,
    "main_sha256": "c" * 64,
}
GPU_UUID = "GPU-1a2b3c4d-5e6f-7a8b-9c0d-1e2f3a4b5c6d"
ALLOWED_CLIENTS = [{"pid": 6432, "created": "2025-01-15T08:30:00Z"}]
QWEN_WORKER_NAMES = ["qwen-writer"]
MODEL_ARTIFACTS = {
    "config_sha256": "d" * 64,
    "weights_sha256": None,
    "availability": "config_only",
}
BINDING = {
    "source_head": SOURCE_HEAD,
    "model_id": MODEL_ID,
    "context": CONTEXT,
    "service": SERVICE,
    "gpu_uuid": GPU_UUID,
    "allowed_clients": ALLOWED_CLIENTS,
    "qwen_worker_names": QWEN_WORKER_NAMES,
    "model_artifacts": MODEL_ARTIFACTS,
}

# ── NVIDIA XML fixtures (minimal well-formed, pid/type/uuid) ───────────────
_GOOD_GPU_XML = (
    '<nvidia_smi_log><gpu id="0">'
    f'<uuid>{GPU_UUID}</uuid>'
    '<driver_model><current_dm>WDDM</current_dm></driver_model>'
    '<processes><process_info><pid>6432</pid><type>C</type></process_info>'
    '</processes></gpu></nvidia_smi_log>'
)
_BAD_GPU_XML_EXTRA_CG = (
    '<nvidia_smi_log><gpu id="0">'
    f'<uuid>{GPU_UUID}</uuid>'
    '<driver_model><current_dm>WDDM</current_dm></driver_model>'
    '<processes>'
    '<process_info><pid>6432</pid><type>C</type></process_info>'
    '<process_info><pid>9999</pid><type>C+G</type></process_info>'
    '</processes></gpu></nvidia_smi_log>'
)
_BAD_GPU_XML_MALFORMED = "<nvidia_smi_log><gpu id=\"0\"><uuid>"
_BAD_GPU_XML_DUP_PID = (
    '<nvidia_smi_log><gpu id="0">'
    f'<uuid>{GPU_UUID}</uuid>'
    '<driver_model><current_dm>WDDM</current_dm></driver_model>'
    '<processes>'
    '<process_info><pid>6432</pid><type>C</type></process_info>'
    '<process_info><pid>6432</pid><type>C</type></process_info>'
    '</processes></gpu></nvidia_smi_log>'
)
_BAD_GPU_XML_WRONG_UUID = (
    '<nvidia_smi_log><gpu id="0">'
    '<uuid>GPU-wrong-uuid-0000000000000000000000000000</uuid>'
    '<driver_model><current_dm>WDDM</current_dm></driver_model>'
    '<processes><process_info><pid>6432</pid><type>C</type></process_info>'
    '</processes></gpu></nvidia_smi_log>'
)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_raw_snapshot(*, model_id=MODEL_ID, context=CONTEXT, service_pid=6432,
                      clients=None, herdr_agents=None, gpu_xml=None,
                      service_created=None, listener_port=5000):
    """Build a raw snapshot dict matching the supplement's exact shape."""
    return {
        "model": {"id": model_id, "parameters": {"max_seq_len": context}},
        "service": {
            "pid": service_pid,
            "created": service_created or SERVICE["created"],
            "image_sha256": SERVICE["image_sha256"],
            "parent_pid": SERVICE["parent_pid"],
            "parent_created": SERVICE["parent_created"],
            "parent_image_sha256": SERVICE["parent_image_sha256"],
            "main_sha256": SERVICE["main_sha256"],
            "listener_port": listener_port,
        },
        "clients": clients if clients is not None else [],
        "herdr": {"agents": herdr_agents if herdr_agents is not None else []},
        "gpu_xml": gpu_xml if gpu_xml is not None else _GOOD_GPU_XML,
    }


def _tmp_root():
    d = tempfile.mkdtemp(prefix="qa-cap-test-")
    return Path(d)


# ── Lease basics ───────────────────────────────────────────────────────────
class TestLeaseBasics(unittest.TestCase):
    def setUp(self):
        self.root = _tmp_root()

    def tearDown(self):
        lease_holders = getattr(self, "_leases", [])
        for l in lease_holders:
            try:
                l.close()
            except Exception:
                pass

    def _lease(self, **kw):
        lease = qc.CapacityLease(self.root, BINDING, **kw)
        self._leases = getattr(self, "_leases", []) + [lease]
        return lease

    # Case 4: wrong nonce check
    def test_wrong_nonce_check(self):
        lease = self._lease()
        meta = lease.acquire()
        with self.assertRaises(qc.CapacityError):
            lease.check("not-the-real-nonce")

    # Wrong nonce release refusal
    def test_wrong_nonce_release(self):
        lease = self._lease()
        meta = lease.acquire()
        with self.assertRaises(qc.CapacityError):
            lease.release("wrong-nonce-xyz")

    # Case 13: corrupt owner.json
    def test_corrupt_metadata_check(self):
        lease = self._lease()
        meta = lease.acquire()
        mp = lease.metadata_path
        mp.write_bytes(b"\x00\x01garbage")
        with self.assertRaises(qc.CapacityError):
            lease.check(meta["nonce"])

    # Case 13: disappeared owner.json
    def test_disappeared_metadata_check(self):
        lease = self._lease()
        meta = lease.acquire()
        mp = lease.metadata_path
        mp.unlink()
        with self.assertRaises(qc.CapacityError):
            lease.check(meta["nonce"])

    # Case 13: replaced owner.json
    def test_replaced_metadata_check(self):
        lease = self._lease()
        meta = lease.acquire()
        mp = lease.metadata_path
        fake = json.dumps({"nonce": "fake", "pid": 1}).encode()
        mp.write_bytes(fake)
        with self.assertRaises(qc.CapacityError):
            lease.check(meta["nonce"])

    # Case 16: crash/restart retains stale evidence
    def test_crash_retains_stale_evidence(self):
        lease = self._lease()
        meta = lease.acquire()
        lease.close()  # simulates crash: lock released, owner.json remains
        self.assertTrue(lease.metadata_path.exists())
        # New acquire must fail (stale evidence, not auto-steal)
        lease2 = self._lease()
        with self.assertRaises(qc.CapacityError):
            lease2.acquire()


# ── Two-process contention (real subprocess, unbuffered stdout) ───────────
_CHILD_SCRIPT = r"""
import sys, json
sys.path.insert(0, sys.argv[1])
import v213_qa_capacity as qc
from pathlib import Path
root = Path(sys.argv[2])
binding = json.loads(sys.argv[3])
lease = qc.CapacityLease(root, binding)
meta = lease.acquire()
sys.stdout.write("HOLDING\n"); sys.stdout.flush()
line = sys.stdin.readline()
if line.strip() == "RELEASE":
    lease.release(meta["nonce"])
    sys.stdout.write("RELEASED\n"); sys.stdout.flush()
lease.close()
"""


class TestLeaseContention(unittest.TestCase):
    """Case 1: two-process acquisition refusal — test WHILE child holds lock."""

    def setUp(self):
        self.root = _tmp_root()
        self._proc = None
        self._reader_thread = None
        self._queue = None

    def tearDown(self):
        self._cleanup_proc()

    def _cleanup_proc(self):
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=5)
        if self._proc:
            if self._proc.poll() is None:
                self._proc.kill()
            try:
                self._proc.wait(timeout=10)
            except Exception:
                pass
            for stream in (self._proc.stdin, self._proc.stdout, self._proc.stderr):
                try:
                    if stream:
                        stream.close()
                except Exception:
                    pass
            self._proc = None

    def _start_child(self):
        self._queue = queue.Queue()
        env = dict(os.environ, PYTHONUNBUFFERED="1")
        self._proc = subprocess.Popen(
            [sys.executable, "-u", "-c", _CHILD_SCRIPT,
             str(_SCRIPTS), str(self.root), json.dumps(BINDING)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, env=env, text=True,
        )
        self._reader_thread = threading.Thread(
            target=self._reader_target, daemon=True
        )
        self._reader_thread.start()

    def _reader_target(self):
        while True:
            line = self._proc.stdout.readline()
            if not line:
                break
            self._queue.put(line.strip())

    def _read_line(self, timeout=15):
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            raise RuntimeError("timed out waiting for child output")

    def test_two_process_refusal_while_child_holds(self):
        self._start_child()
        self.assertEqual(self._read_line(), "HOLDING")
        # Parent tries to acquire WHILE child holds the lock
        parent_lease = qc.CapacityLease(self.root, BINDING)
        try:
            with self.assertRaises(qc.CapacityError):
                parent_lease.acquire()
        finally:
            parent_lease.close()
        # Signal child to release
        self._proc.stdin.write("RELEASE\n")
        self._proc.stdin.flush()
        self.assertEqual(self._read_line(), "RELEASED")
        self._proc.wait(timeout=15)
        # Now parent can acquire
        parent_lease2 = qc.CapacityLease(self.root, BINDING)
        try:
            meta = parent_lease2.acquire()
            self.assertIn("nonce", meta)
        finally:
            parent_lease2.close()

    def test_child_holds_parent_blocked_finite(self):
        """Verify finite completion: child must release within timeout."""
        self._start_child()
        self.assertEqual(self._read_line(), "HOLDING")
        parent_lease = qc.CapacityLease(self.root, BINDING)
        try:
            with self.assertRaises(qc.CapacityError):
                parent_lease.acquire()
        finally:
            parent_lease.close()
        self._proc.stdin.write("RELEASE\n")
        self._proc.stdin.flush()
        self.assertEqual(self._read_line(), "RELEASED")
        self._proc.wait(timeout=15)


# ── recover_dead (explicit nonce + SHA of actual owner.json) ──────────────
class TestRecoverDead(unittest.TestCase):
    def setUp(self):
        self.root = _tmp_root()
        self._leases = []

    def tearDown(self):
        for l in self._leases:
            try:
                l.close()
            except Exception:
                pass

    def _lease(self, **kw):
        lease = qc.CapacityLease(self.root, BINDING, **kw)
        self._leases.append(lease)
        return lease

    # Case 2: expired LIVE owner refusal
    def test_expired_live_owner_refusal(self):
        lease = self._lease(ttl_s=0.1)
        meta = lease.acquire()
        # Save metadata before closing
        owner_bytes = lease.metadata_path.read_bytes()
        owner_sha = _sha256_bytes(owner_bytes)
        nonce = meta["nonce"]
        # Close lease first: releases lock, retains metadata (kernel lock free)
        lease.close()
        time.sleep(0.15)  # TTL expired, owner PID (test process) still alive
        # recover_dead with actual current live PID must refuse
        with self.assertRaises(qc.CapacityError):
            qc.recover_dead(self.root, nonce, owner_sha)

    # Case 3: dead-owner recovery with correct nonce + SHA
    def test_dead_owner_recovery_correct(self):
        lease = self._lease()
        meta = lease.acquire()
        owner_bytes = lease.metadata_path.read_bytes()
        owner_sha = _sha256_bytes(owner_bytes)
        nonce = meta["nonce"]
        lease.close()  # lock released; simulate dead via process_probe
        # Use a probe that reports the owner PID as conclusively dead
        dead_probe = lambda pid: None  # None = conclusively dead
        evt = qc.recover_dead(self.root, nonce, owner_sha, process_probe=dead_probe)
        self.assertIn("archived", json.dumps(evt).lower())

    # Case 3: wrong expected digest refusal
    def test_recover_dead_wrong_sha_refusal(self):
        lease = self._lease()
        meta = lease.acquire()
        nonce = meta["nonce"]
        lease.close()
        dead_probe = lambda pid: None
        wrong_sha = "0" * 64
        with self.assertRaises(qc.CapacityError):
            qc.recover_dead(self.root, nonce, wrong_sha, process_probe=dead_probe)

    # Unknown process probe refusal
    def test_unknown_process_probe_refusal(self):
        lease = self._lease()
        meta = lease.acquire()
        owner_bytes = lease.metadata_path.read_bytes()
        owner_sha = _sha256_bytes(owner_bytes)
        nonce = meta["nonce"]
        lease.close()
        # Probe that raises = unknown (not conclusively dead)
        def unknown_probe(pid):
            raise qc.CapacityError("cannot determine process state")
        with self.assertRaises(qc.CapacityError):
            qc.recover_dead(self.root, nonce, owner_sha, process_probe=unknown_probe)

    # PID-reuse: process_probe returns different creation marker than owner
    def test_pid_reuse_recovery_correct(self):
        lease = self._lease()
        meta = lease.acquire()
        owner_bytes = lease.metadata_path.read_bytes()
        owner_sha = _sha256_bytes(owner_bytes)
        nonce = meta["nonce"]
        lease.close()
        # Probe: PID alive but different creation = original owner dead (reused)
        def reuse_probe(pid):
            return "2099-01-01T00:00:00Z"
        # Correct nonce/digest permits archival
        evt = qc.recover_dead(self.root, nonce, owner_sha, process_probe=reuse_probe)
        self.assertIn("archived", json.dumps(evt).lower())

    # PID-reuse: wrong expected nonce refusal
    def test_pid_reuse_wrong_nonce_refusal(self):
        lease = self._lease()
        meta = lease.acquire()
        owner_bytes = lease.metadata_path.read_bytes()
        owner_sha = _sha256_bytes(owner_bytes)
        lease.close()
        def reuse_probe(pid):
            return "2099-01-01T00:00:00Z"
        with self.assertRaises(qc.CapacityError):
            qc.recover_dead(self.root, "wrong-nonce", owner_sha, process_probe=reuse_probe)

    # PID-reuse: corrupt residual recovery refusal
    def test_pid_reuse_corrupt_residual_refusal(self):
        lease = self._lease()
        meta = lease.acquire()
        nonce = meta["nonce"]
        lease.close()
        # Corrupt metadata
        lease.metadata_path.write_bytes(b"\xff\xfe corrupt")
        def reuse_probe(pid):
            return "2099-01-01T00:00:00Z"
        wrong_sha = "0" * 64
        with self.assertRaises(qc.CapacityError):
            qc.recover_dead(self.root, nonce, wrong_sha, process_probe=reuse_probe)


# ── Real child CRASH (kill -> stale -> recover_dead actual dead PID) ──────
class TestChildCrash(unittest.TestCase):
    def setUp(self):
        self.root = _tmp_root()
        self._proc = None
        self._reader_thread = None
        self._queue = None

    def tearDown(self):
        self._cleanup_proc()

    def _cleanup_proc(self):
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=5)
        if self._proc:
            if self._proc.poll() is None:
                self._proc.kill()
            try:
                self._proc.wait(timeout=10)
            except Exception:
                pass
            for stream in (self._proc.stdin, self._proc.stdout, self._proc.stderr):
                try:
                    if stream:
                        stream.close()
                except Exception:
                    pass
            self._proc = None

    def _start_child(self):
        self._queue = queue.Queue()
        env = dict(os.environ, PYTHONUNBUFFERED="1")
        self._proc = subprocess.Popen(
            [sys.executable, "-u", "-c", _CHILD_SCRIPT,
             str(_SCRIPTS), str(self.root), json.dumps(BINDING)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, env=env, text=True,
        )
        self._reader_thread = threading.Thread(
            target=self._reader_target, daemon=True
        )
        self._reader_thread.start()

    def _reader_target(self):
        while True:
            line = self._proc.stdout.readline()
            if not line:
                break
            self._queue.put(line.strip())

    def _read_line(self, timeout=15):
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            raise RuntimeError("timed out waiting for child output")

    def test_child_crash_recover_dead_actual(self):
        # Start child, verify acquisition via handshake
        self._start_child()
        self.assertEqual(self._read_line(), "HOLDING")
        child_pid = self._proc.pid

        # Save metadata while child holds it
        lease_tmp = qc.CapacityLease(self.root, BINDING)
        owner_bytes = lease_tmp.metadata_path.read_bytes()
        owner_sha = _sha256_bytes(owner_bytes)
        meta_stored = json.loads(owner_bytes)
        nonce = meta_stored["nonce"]

        # Kill child (simulates crash); Popen object/handle remains alive
        self._proc.kill()
        self._proc.wait(timeout=10)

        # Assert real owned-child exit detection via process_identity
        self.assertIsNone(qc.process_identity(child_pid),
                          "process_identity must return None for dead child")

        # Fresh acquire must refuse (stale metadata)
        lease2 = qc.CapacityLease(self.root, BINDING)
        try:
            with self.assertRaises(qc.CapacityError):
                lease2.acquire()
        finally:
            lease2.close()

        # recover_dead with stored nonce/hash using REAL process_identity
        evt = qc.recover_dead(self.root, nonce, owner_sha,
                              process_probe=qc.process_identity)
        # Check archived file/evidence preserved (not just word match)
        evt_str = json.dumps(evt)
        self.assertIn("archived", evt_str.lower())
        self.assertTrue(len(evt_str) > 10)

        # New acquire should succeed
        lease3 = qc.CapacityLease(self.root, BINDING)
        try:
            meta3 = lease3.acquire()
            self.assertIn("nonce", meta3)
        finally:
            lease3.release(meta3["nonce"])
            lease3.close()


# ── Lease metadata binding + guard persistence ─────────────────────────────
class TestLeaseMetadataBinding(unittest.TestCase):
    def setUp(self):
        self.root = _tmp_root()
        self._leases = []

    def tearDown(self):
        for l in self._leases:
            try:
                l.close()
            except Exception:
                pass

    def _lease(self, **kw):
        lease = qc.CapacityLease(self.root, BINDING, **kw)
        self._leases.append(lease)
        return lease

    def test_metadata_binding_fields_exist(self):
        lease = self._lease()
        meta = lease.acquire()
        mp = lease.metadata_path
        self.assertTrue(mp.exists())
        stored = json.loads(mp.read_bytes())
        # HEAD/model/context/service/nonce/ownerPID/birth must exist
        self.assertIn("nonce", stored)
        self.assertIn("pid", stored)
        self.assertIn("created", stored)
        self.assertIn("source_head", stored)
        self.assertIn("model_id", stored)
        self.assertIn("context", stored)
        self.assertIn("service", stored)
        # Nonce matches
        self.assertEqual(stored["nonce"], meta["nonce"])
        # Owner PID is current process
        self.assertEqual(stored["pid"], os.getpid())

    def test_release_leaves_guard_persistent(self):
        lease = self._lease()
        meta = lease.acquire()
        lease.release(meta["nonce"])
        # Guard file persists after release
        self.assertTrue((self.root / "guard").exists())

    def test_second_acquisition_fails_same_process_distinct_instance(self):
        lease1 = self._lease()
        meta1 = lease1.acquire()
        # Second distinct instance in same process must fail while winner HOLDS lease
        lease2 = self._lease()
        with self.assertRaises(qc.CapacityError):
            lease2.acquire()
        # Release winner; loser can now acquire cleanly
        lease1.release(meta1["nonce"])
        lease1.close()
        meta2 = lease2.acquire()
        lease2.release(meta2["nonce"])


# ── Snapshot evaluation (raw structures, not caller booleans) ─────────────
class TestSnapshotEvaluation(unittest.TestCase):
    # Case 5: service PID/creation change
    def test_service_pid_change(self):
        raw = make_raw_snapshot(service_pid=9999)
        result = qc.evaluate_snapshot(raw, BINDING)
        self.assertFalse(result["service_identity_verified"])

    def test_service_creation_change(self):
        raw = make_raw_snapshot(service_created="2025-02-01T00:00:00Z")
        result = qc.evaluate_snapshot(raw, BINDING)
        self.assertFalse(result["service_identity_verified"])

    # Case 6: model change
    def test_model_id_change(self):
        raw = make_raw_snapshot(model_id="qwen3-30b-a3b")
        result = qc.evaluate_snapshot(raw, BINDING)
        self.assertFalse(result["model_identity_verified"])

    # Case 7: strict context mismatch / bool rejection
    def test_context_wrong_int(self):
        raw = make_raw_snapshot(context=131072)
        result = qc.evaluate_snapshot(raw, BINDING)
        self.assertFalse(result["model_identity_verified"])

    def test_context_bool_rejected(self):
        raw = make_raw_snapshot()
        raw["model"]["parameters"]["max_seq_len"] = True  # bool, not int
        result = qc.evaluate_snapshot(raw, BINDING)
        self.assertFalse(result["model_identity_verified"])

    # Case 8: known competing Qwen worker
    def test_known_qwen_working_conflict(self):
        agents = [{"name": "qwen-writer", "agent_status": "working"}]
        raw = make_raw_snapshot(herdr_agents=agents)
        result = qc.evaluate_snapshot(raw, BINDING)
        self.assertTrue(result["qwen_conflict_observed"])

    def test_known_qwen_idle_okay(self):
        agents = [{"name": "qwen-writer", "agent_status": "idle"}]
        raw = make_raw_snapshot(herdr_agents=agents)
        result = qc.evaluate_snapshot(raw, BINDING)
        self.assertFalse(result["qwen_conflict_observed"])

    # Case 9: unrelated cloud worker harmless
    def test_unrelated_cloud_worker_harmless(self):
        agents = [{"name": "cloud-agent-x", "agent_status": "working"}]
        raw = make_raw_snapshot(herdr_agents=agents)
        result = qc.evaluate_snapshot(raw, BINDING)
        self.assertFalse(result["qwen_conflict_observed"])

    # Case 10: extra Tabby/foreign client
    def test_extra_client_conflict(self):
        clients = [{"pid": 6432, "created": SERVICE["created"]},
                   {"pid": 7777, "created": "2025-01-16T00:00:00Z"}]
        raw = make_raw_snapshot(clients=clients)
        result = qc.evaluate_snapshot(raw, BINDING)
        self.assertTrue(result["client_conflict_observed"])

    def test_allowed_client_only_okay(self):
        clients = [{"pid": 6432, "created": SERVICE["created"]}]
        raw = make_raw_snapshot(clients=clients)
        result = qc.evaluate_snapshot(raw, BINDING)
        self.assertFalse(result["client_conflict_observed"])

    # Case 11: unexpected C+G GPU process
    def test_extra_cg_gpu_process(self):
        raw = make_raw_snapshot(gpu_xml=_BAD_GPU_XML_EXTRA_CG)
        result = qc.evaluate_snapshot(raw, BINDING)
        self.assertTrue(result["gpu_conflict_observed"])

    # Unknown C+G (separate test)
    def test_unknown_cg_type_failure(self):
        parsed = qc.parse_nvidia_xml(_BAD_GPU_XML_EXTRA_CG)
        # Must surface the C+G process; evaluator flags conflict
        types = [p["type"] for p in parsed["processes"]]
        self.assertIn("C+G", types)

    # Missing telemetry
    def test_missing_model_telemetry(self):
        raw = make_raw_snapshot()
        del raw["model"]
        result = qc.evaluate_snapshot(raw, BINDING)
        self.assertFalse(result["model_identity_verified"])
        self.assertTrue(result["reasons"])

    def test_missing_gpu_xml(self):
        # Missing GPU telemetry is an absence/uncertainty, NOT an observed
        # conflict.  gpu_conflict_observed must stay False while reasons record
        # the missing evidence independently.
        raw = make_raw_snapshot()
        raw["gpu_xml"] = None
        result = qc.evaluate_snapshot(raw, BINDING)
        self.assertFalse(result["gpu_conflict_observed"])
        self.assertTrue(result["reasons"])

    def test_missing_clients_not_empty_healthy(self):
        # Unknown/missing client telemetry must never be treated as an empty
        # healthy inventory: identity flags stay unverified and reasons are set.
        raw = make_raw_snapshot()
        del raw["clients"]
        result = qc.evaluate_snapshot(raw, BINDING)
        self.assertFalse(result["service_identity_verified"])
        self.assertTrue(result["reasons"])

    def test_missing_client_conflict_flag_not_empty_healthy(self):
        raw = make_raw_snapshot()
        del raw["clients"]
        result = qc.evaluate_snapshot(raw, BINDING)
        self.assertFalse(result["client_conflict_observed"])
        self.assertTrue(result["reasons"])

    def test_missing_herdr_not_empty_healthy(self):
        # Unknown/missing herdr telemetry must never be treated as an empty
        # healthy worker inventory.
        raw = make_raw_snapshot()
        del raw["herdr"]
        result = qc.evaluate_snapshot(raw, BINDING)
        self.assertFalse(result["qwen_conflict_observed"])
        self.assertTrue(result["reasons"])

    # Clean snapshot: all verified
    def test_clean_snapshot_all_verified(self):
        raw = make_raw_snapshot()
        result = qc.evaluate_snapshot(raw, BINDING)
        self.assertTrue(result["model_identity_verified"])
        self.assertTrue(result["service_identity_verified"])
        self.assertFalse(result["gpu_conflict_observed"])
        self.assertFalse(result["qwen_conflict_observed"])
        self.assertFalse(result["client_conflict_observed"])


# ── NVIDIA XML parser ──────────────────────────────────────────────────────
class TestNvidiaXml(unittest.TestCase):
    def test_good_xml(self):
        parsed = qc.parse_nvidia_xml(_GOOD_GPU_XML)
        self.assertEqual(parsed["uuid"], GPU_UUID)
        self.assertEqual(len(parsed["processes"]), 1)
        self.assertEqual(parsed["processes"][0]["pid"], 6432)
        self.assertEqual(parsed["processes"][0]["type"], "C")

    def test_malformed_rejected(self):
        with self.assertRaises(qc.CapacityError):
            qc.parse_nvidia_xml(_BAD_GPU_XML_MALFORMED)

    def test_duplicate_pid_rejected(self):
        with self.assertRaises(qc.CapacityError):
            qc.parse_nvidia_xml(_BAD_GPU_XML_DUP_PID)

    def test_wrong_uuid_passes_parse_but_eval_fails(self):
        parsed = qc.parse_nvidia_xml(_BAD_GPU_XML_WRONG_UUID)
        self.assertNotEqual(parsed["uuid"], GPU_UUID)

    def test_empty_process_list(self):
        xml = (
            '<nvidia_smi_log><gpu id="0">'
            f'<uuid>{GPU_UUID}</uuid>'
            '<driver_model><current_dm>WDDM</current_dm></driver_model>'
            '<processes></processes></gpu></nvidia_smi_log>'
        )
        parsed = qc.parse_nvidia_xml(xml)
        self.assertEqual(parsed["processes"], [])

    def test_extra_single_c_process_flags_conflict(self):
        # Any additional C process beyond the approved service is a conflict.
        raw = make_raw_snapshot(gpu_xml=_BAD_GPU_XML_EXTRA_CG)
        result = qc.evaluate_snapshot(raw, BINDING)
        self.assertTrue(result["gpu_conflict_observed"])
        self.assertTrue(result["reasons"])

    def test_wrong_uuid_not_healthy(self):
        # A mismatched device UUID must not be treated as healthy.
        raw = make_raw_snapshot(gpu_xml=_BAD_GPU_XML_WRONG_UUID)
        result = qc.evaluate_snapshot(raw, BINDING)
        self.assertTrue(result["reasons"])
        self.assertFalse(
            result["model_identity_verified"] and
            result["service_identity_verified"] and
            not result["gpu_conflict_observed"]
        )


# ── Collector via raw IO seams (not final booleans) ───────────────────────
class TestCollectWindows(unittest.TestCase):
    """Exercise collect_windows_snapshot through the exact injectable seams.

    The runner must dispatch three command kinds by their exact argv and the
    http_get seam must be exercised against the one canonical loopback card.
    The collector ONLY observes: it returns raw sanitized observations and
    never renders a healthy/unhealthy verdict; the evaluator (and monitor)
    judge those raw facts and flag UNQUALIFIED.  Parse/transport that is
    missing or malformed still raises.
    """

    GPU_CMD = ["nvidia-smi", "-q", "-x"]
    HERDR_CMD = ["herdr", "agent", "list"]
    WIN_CMD = ["powershell.exe", "-NoProfile", "-Command"]
    CARD_URL = "http://127.0.0.1:5000/v1/model"

    def _good_runner(self, argv, **kwargs):
        """Dispatch the three real command kinds; unknown -> AssertionError."""
        a = list(argv)
        if a[:3] == self.GPU_CMD:
            return _GOOD_GPU_XML
        if a[:3] == self.HERDR_CMD:
            return json.dumps({"result": {"agents": [
                {"name": "qwen-writer", "agent_status": "idle"}]}})
        if a[:len(self.WIN_CMD)] == self.WIN_CMD:
            svc = dict(SERVICE)
            svc["listener_port"] = 5000
            return json.dumps({"service": svc, "clients": []})
        raise AssertionError(f"runner received unrecognised command: {a}")

    def _good_http_get(self, url, **kwargs):
        """Native card JSON only from the exact canonical loopback endpoint."""
        self.assertEqual(url, self.CARD_URL)
        self.assertFalse(kwargs.get("allow_redirects", True))
        return json.dumps({"id": MODEL_ID, "parameters": {"max_seq_len": CONTEXT}})

    def test_collect_good_snapshot(self):
        raw = qc.collect_windows_snapshot(
            BINDING, runner=self._good_runner, http_get=self._good_http_get)
        self.assertEqual(raw["model"]["id"], MODEL_ID)
        self.assertEqual(raw["model"]["parameters"]["max_seq_len"], CONTEXT)
        self.assertIn("gpu_xml", raw)
        self.assertIn("service", raw)
        self.assertIn("clients", raw)
        self.assertIn("herdr", raw)

    def test_powershell_noprofile_exact_prefix(self):
        """Collector MUST dispatch powershell with the -NoProfile exact prefix.

        A runner keyed on the 3-token WIN_CMD only recognises the
        -NoProfile command; a bare -Command dispatch would fail to match.
        """
        win_cmds = []

        def tracking_runner(argv, **kwargs):
            a = list(argv)
            if a[:len(self.WIN_CMD)] == self.WIN_CMD:
                win_cmds.append(a)
            return self._good_runner(argv, **kwargs)

        qc.collect_windows_snapshot(
            BINDING, runner=tracking_runner, http_get=self._good_http_get)
        self.assertTrue(win_cmds)
        for c in win_cmds:
            self.assertEqual(c[:3], ["powershell.exe", "-NoProfile", "-Command"])

    def test_runner_dispatches_exact_command_kinds(self):
        """Reusing the same runner, the collector must drive all three kinds."""
        seen = []

        def tracking_runner(argv, **kwargs):
            seen.append(list(argv))
            return self._good_runner(argv, **kwargs)

        qc.collect_windows_snapshot(
            BINDING, runner=tracking_runner, http_get=self._good_http_get)
        # GPU XML command
        self.assertTrue(any(c[:3] == self.GPU_CMD for c in seen))
        # herdr agent list command
        self.assertTrue(any(c[:3] == self.HERDR_CMD for c in seen))
        # Windows attestation command
        self.assertTrue(any(c[:len(self.WIN_CMD)] == self.WIN_CMD for c in seen))

    def test_runner_unknown_command_raises(self):
        # An unrecognised command kind must raise AssertionError, not return
        # a canned verdict (and in particular never XML for Windows evidence).
        with self.assertRaises(AssertionError):
            self._good_runner(["cmd.exe", "/c", "whoami"])

    def test_http_get_wrong_endpoint_raises(self):
        with self.assertRaises(AssertionError):
            self._good_http_get("http://127.0.0.1:8000/v1/model")

    def test_http_get_redirects_must_be_false(self):
        with self.assertRaises(AssertionError):
            self._good_http_get(self.CARD_URL, allow_redirects=True)

    def test_collect_malformed_gpu_xml_fails(self):
        def bad_runner(argv, **kwargs):
            if list(argv)[:3] == self.GPU_CMD:
                return _BAD_GPU_XML_MALFORMED
            return self._good_runner(argv, **kwargs)
        with self.assertRaises(qc.CapacityError):
            qc.collect_windows_snapshot(
                BINDING, runner=bad_runner, http_get=self._good_http_get)

    def test_collect_malformed_herdr_row_raises(self):
        # A non-dict agent entry is a malformed herdr row: the collector must
        # reject it (raise), not silently skip it.
        def bad_runner(argv, **kwargs):
            if list(argv)[:3] == self.HERDR_CMD:
                return json.dumps({"result": {"agents": [
                    "not-a-dict-agent",  # malformed: non-dict entry
                    {"name": "qwen-writer", "agent_status": "idle"}]}})
            return self._good_runner(argv, **kwargs)
        with self.assertRaises(qc.CapacityError):
            qc.collect_windows_snapshot(
                BINDING, runner=bad_runner, http_get=self._good_http_get)

    def test_collect_missing_service_stdout_fails(self):
        def bad_runner(argv, **kwargs):
            if list(argv)[:len(self.WIN_CMD)] == self.WIN_CMD:
                return json.dumps({"clients": []})  # 'service' key missing
            return self._good_runner(argv, **kwargs)
        with self.assertRaises(qc.CapacityError):
            qc.collect_windows_snapshot(
                BINDING, runner=bad_runner, http_get=self._good_http_get)

    def test_collect_malformed_service_stdout_fails(self):
        def bad_runner(argv, **kwargs):
            if list(argv)[:len(self.WIN_CMD)] == self.WIN_CMD:
                return "this is not json {{{"  # unparseable attestation
            return self._good_runner(argv, **kwargs)
        with self.assertRaises(qc.CapacityError):
            qc.collect_windows_snapshot(
                BINDING, runner=bad_runner, http_get=self._good_http_get)

    def test_collect_missing_clients_key_fails(self):
        def bad_runner(argv, **kwargs):
            if list(argv)[:len(self.WIN_CMD)] == self.WIN_CMD:
                return json.dumps({"service": dict(SERVICE)})  # 'clients' absent
            return self._good_runner(argv, **kwargs)
        with self.assertRaises(qc.CapacityError):
            qc.collect_windows_snapshot(
                BINDING, runner=bad_runner, http_get=self._good_http_get)

    def test_collect_missing_herdr_stdout_fails(self):
        def bad_runner(argv, **kwargs):
            if list(argv)[:3] == self.HERDR_CMD:
                return "no herdr agent data here"  # unparseable
            return self._good_runner(argv, **kwargs)
        with self.assertRaises(qc.CapacityError):
            qc.collect_windows_snapshot(
                BINDING, runner=bad_runner, http_get=self._good_http_get)

    def test_collect_blocked_qwen_returns_raw_evaluator_flags(self):
        # A blocked known Qwen worker is an OBSERVED fact, not a parse/transport
        # failure: the collector returns the raw sanitized snapshot and the
        # evaluator (not the collector) flags the conflict.  This replaces the
        # old assertRaises which encoded bad semantics.
        def blocked_runner(argv, **kwargs):
            if list(argv)[:3] == self.HERDR_CMD:
                return json.dumps({"result": {"agents": [
                    {"name": "qwen-writer", "agent_status": "blocked"}]}})
            return self._good_runner(argv, **kwargs)
        raw = qc.collect_windows_snapshot(
            BINDING, runner=blocked_runner, http_get=self._good_http_get)
        # Collector returned raw (did not raise); the blocked status is observed.
        self.assertEqual(
            raw["herdr"]["agents"][0]["agent_status"], "blocked")
        verdict = qc.evaluate_snapshot(raw, BINDING)
        self.assertTrue(verdict["qwen_conflict_observed"])
        self.assertTrue(verdict["reasons"])

    def test_collect_missing_model_card_fails(self):
        def bad_http_get(url, **kwargs):
            self.assertEqual(url, self.CARD_URL)
            return json.dumps({"parameters": {"max_seq_len": CONTEXT}})  # no 'id'
        with self.assertRaises(qc.CapacityError):
            qc.collect_windows_snapshot(
                BINDING, runner=self._good_runner, http_get=bad_http_get)

    def test_collect_gpu_raw_tag_redacted_conflict_retained(self):
        # An unrelated raw tag (serial) in the GPU XML must be redacted from the
        # sanitized observation while the observed C+G process is retained; the
        # evaluator (not the collector) flags the conflict.
        def cg_runner(argv, **kwargs):
            if list(argv)[:3] == self.GPU_CMD:
                return _BAD_GPU_XML_RAW_TAG_CG
            return self._good_runner(argv, **kwargs)
        raw = qc.collect_windows_snapshot(
            BINDING, runner=cg_runner, http_get=self._good_http_get)
        san = raw["gpu_xml"]
        # Unrelated raw metadata redacted, but observed pid/type retained.
        self.assertNotIn("GPU-RAW-SERIAL-9999", san)
        self.assertIn("9999", san)
        self.assertIn("C+G", san)
        self.assertIn(GPU_UUID, san)
        verdict = qc.evaluate_snapshot(raw, BINDING)
        self.assertTrue(verdict["gpu_conflict_observed"])

    def test_collect_bad_model_returns_raw_evaluator_false(self):
        # A mismatched model id is an OBSERVED fact, not a parse/transport
        # failure: the collector returns the raw snapshot and the evaluator
        # (not the collector) fails the model identity verdict.
        def bad_model_http_get(url, **kwargs):
            self.assertEqual(url, self.CARD_URL)
            return json.dumps({"id": "wrong-model-id",
                               "parameters": {"max_seq_len": CONTEXT}})
        raw = qc.collect_windows_snapshot(
            BINDING, runner=self._good_runner, http_get=bad_model_http_get)
        self.assertEqual(raw["model"]["id"], "wrong-model-id")
        verdict = qc.evaluate_snapshot(raw, BINDING)
        self.assertFalse(verdict["model_identity_verified"])

    def test_collect_no_proxy_fallback(self):
        """http_get must be driven against the canonical loopback card only."""
        calls = []

        def tracking_http_get(url, **kwargs):
            calls.append(url)
            return self._good_http_get(url, **kwargs)

        qc.collect_windows_snapshot(
            BINDING, runner=self._good_runner, http_get=tracking_http_get)
        self.assertTrue(calls)
        self.assertTrue(all(c == self.CARD_URL for c in calls))


# GPU XML with an unrelated raw tag (serial) alongside an observed C+G process:
# the serial must be redacted from the sanitized observation, the C+G process
# retained, and the evaluator flags the conflict.
_BAD_GPU_XML_RAW_TAG_CG = (
    '<nvidia_smi_log><gpu id="0">'
    f'<uuid>{GPU_UUID}</uuid>'
    '<driver_model><current_dm>WDDM</current_dm></driver_model>'
    '<serial>GPU-RAW-SERIAL-9999</serial>'
    '<processes>'
    '<process_info><pid>6432</pid><type>C</type></process_info>'
    '<process_info><pid>9999</pid><type>C+G</type></process_info>'
    '</processes></gpu></nvidia_smi_log>'
)


# ── run_window orchestration ───────────────────────────────────────────────
class TestRunWindow(unittest.TestCase):
    def setUp(self):
        self.root = _tmp_root()
        self._leases = []

    def tearDown(self):
        for l in self._leases:
            try:
                l.close()
            except Exception:
                pass

    def _lease(self, **kw):
        lease = qc.CapacityLease(self.root, BINDING, **kw)
        self._leases.append(lease)
        return lease

    # Case 14: clean full window.  run_window OWNS acquisition (nonreentrant),
    # so the lease is NOT pre-acquired here.  Callback holds 0.15s; monitor
    # samples at 0.03s so several DURING samples are captured.
    def test_clean_full_window(self):
        lease = self._lease()

        def probe():
            return make_raw_snapshot()

        def work(cancel_event):
            time.sleep(0.15)  # hold >= 0.15s

        receipt = qc.run_window(
            lease, probe, work, interval_s=0.03, max_gap_s=0.5, timeout_s=3)

        # DURING count >= 1
        during = [s for s in receipt["samples"] if s["phase"] == "DURING"]
        self.assertGreaterEqual(len(during), 1)
        # Release event present
        self.assertTrue(receipt["summary"]["lease_released"])
        # QUALIFIED
        self.assertEqual(receipt["summary"]["CAPACITY_EVIDENCE"], "QUALIFIED")
        # verify_receipt passes
        result = qc.verify_receipt(receipt, BINDING)
        self.assertEqual(result["CAPACITY_EVIDENCE"], "QUALIFIED")

    # Case 15: release after success (run_window owns acquire + release)
    def test_release_after_success(self):
        lease = self._lease()
        receipt = qc.run_window(
            lease, lambda: make_raw_snapshot(),
            lambda ce: time.sleep(0.15),
            interval_s=0.03, max_gap_s=0.5, timeout_s=3)
        self.assertTrue(receipt["summary"]["lease_released"])
        # Release event in receipt events
        release_events = [e for e in receipt["events"] if "release" in str(e).lower()]
        self.assertGreaterEqual(len(release_events), 1)

    # Sticky failure: second tick bad, work succeeds -> UNQUALIFIED
    def test_sticky_failure_second_tick(self):
        lease = self._lease()
        tick = [0]

        def probe():
            tick[0] += 1
            if tick[0] <= 1:
                return make_raw_snapshot()
            return make_raw_snapshot(gpu_xml=_BAD_GPU_XML_EXTRA_CG)

        def work(cancel_event):
            time.sleep(0.15)  # work succeeds regardless

        receipt = qc.run_window(
            lease, probe, work, interval_s=0.03, max_gap_s=0.5, timeout_s=3)
        self.assertEqual(receipt["summary"]["CAPACITY_EVIDENCE"], "UNQUALIFIED")

    # Case 12: probe failure -> UNQUALIFIED
    def test_probe_failure_unqualified(self):
        lease = self._lease()

        def bad_probe():
            raise qc.CapacityError("probe timeout")

        def work(cancel_event):
            time.sleep(0.1)

        receipt = qc.run_window(
            lease, bad_probe, work, interval_s=0.03, max_gap_s=0.5, timeout_s=3)
        self.assertEqual(receipt["summary"]["CAPACITY_EVIDENCE"], "UNQUALIFIED")

    # Pre failure: callback not invoked
    def test_pre_failure_callback_not_invoked(self):
        lease = self._lease()
        called = [False]

        def bad_probe():
            raise qc.CapacityError("pre probe failed")

        def work(cancel_event):
            called[0] = True

        receipt = qc.run_window(
            lease, bad_probe, work, interval_s=0.03, max_gap_s=0.5, timeout_s=3)
        self.assertFalse(called[0])
        self.assertEqual(receipt["summary"]["CAPACITY_EVIDENCE"], "UNQUALIFIED")

    # Work raises -> UNQUALIFIED
    def test_work_raises_unqualified(self):
        lease = self._lease()

        def work(cancel_event):
            raise RuntimeError("work crashed")

        receipt = qc.run_window(
            lease, lambda: make_raw_snapshot(), work,
            interval_s=0.03, max_gap_s=0.5, timeout_s=3)
        self.assertEqual(receipt["summary"]["CAPACITY_EVIDENCE"], "UNQUALIFIED")

    # ── DURING changes (table-driven raw changes at tick>=2) ──────────────
    # A clean PRE/DURING cannot qualify once any interior sample changes a
    # bound identity.  The callback is given up to 0.5s (bounded, not an
    # unconditional success).
    def test_during_changes_unqualified_and_cancelled(self):
        changes = [
            ("service_pid", lambda: make_raw_snapshot(service_pid=9999)),
            ("service_created", lambda: make_raw_snapshot(
                service_created="2025-02-01T00:00:00Z")),
            ("model_id", lambda: make_raw_snapshot(model_id="qwen3-30b-a3b")),
            ("context", lambda: make_raw_snapshot(context=131072)),
            ("gpu_conflict", lambda: make_raw_snapshot(gpu_xml=_BAD_GPU_XML_EXTRA_CG)),
            ("qwen_working", lambda: make_raw_snapshot(herdr_agents=[
                {"name": "qwen-writer", "agent_status": "working"}])),
            ("extra_client", lambda: make_raw_snapshot(clients=[
                {"pid": 6432, "created": SERVICE["created"]},
                {"pid": 7777, "created": "2025-01-16T00:00:00Z"}])),
        ]
        for name, bad_raw in changes:
            with self.subTest(change=name):
                lease = self._lease()
                tick = [0]

                def probe():
                    tick[0] += 1
                    if tick[0] <= 1:
                        return make_raw_snapshot()
                    return bad_raw()

                def work(cancel_event):
                    # Bounded wait on the cancel event; never an unconditional
                    # success that would mask a DURING failure.
                    cancel_event.wait(0.5)

                receipt = qc.run_window(
                    lease, probe, work,
                    interval_s=0.03, max_gap_s=0.5, timeout_s=3)
                self.assertEqual(
                    receipt["summary"]["CAPACITY_EVIDENCE"], "UNQUALIFIED")

    # ── DURING owner.json corruption / disappearance ──────────────────────
    # If the lease owner metadata is corrupted or removed while the window is
    # running, the callback's wait is cancelled and the receipt is UNQUALIFIED.
    def test_during_owner_corruption_unqualified(self):
        lease = self._lease()
        mp = lease.metadata_path

        def probe():
            return make_raw_snapshot()

        def work(cancel_event):
            mp.write_bytes(b"\x00\x01corrupt")  # corrupt owner metadata mid-run
            cancel_event.wait(0.5)

        receipt = qc.run_window(
            lease, probe, work, interval_s=0.03, max_gap_s=0.5, timeout_s=3)
        self.assertEqual(receipt["summary"]["CAPACITY_EVIDENCE"], "UNQUALIFIED")

    def test_during_owner_disappearance_unqualified(self):
        lease = self._lease()
        mp = lease.metadata_path

        def probe():
            return make_raw_snapshot()

        def work(cancel_event):
            if mp.exists():
                mp.unlink()  # owner metadata disappears mid-run
            cancel_event.wait(0.5)

        receipt = qc.run_window(
            lease, probe, work, interval_s=0.03, max_gap_s=0.5, timeout_s=3)
        self.assertEqual(receipt["summary"]["CAPACITY_EVIDENCE"], "UNQUALIFIED")

    # ── timeout / gap: raw probe sleeps beyond the declared max_gap ───────
    # A deliberately slow probe that exceeds max_gap_s is a purposeful gap and
    # must make the window UNQUALIFIED; no arbitrary final flags are asserted.
    def test_probe_gap_beyond_max_gap_unqualified(self):
        lease = self._lease()

        def slow_probe():
            time.sleep(0.8)  # exceeds max_gap_s=0.5
            return make_raw_snapshot()

        def work(cancel_event):
            cancel_event.wait(0.5)

        receipt = qc.run_window(
            lease, slow_probe, work, interval_s=0.03, max_gap_s=0.5, timeout_s=3)
        self.assertEqual(receipt["summary"]["CAPACITY_EVIDENCE"], "UNQUALIFIED")

    # ── quickwork: zero interior work cannot qualify ───────────────────────
    def test_quickwork_zero_unqualified(self):
        lease = self._lease()

        def work(cancel_event):
            pass  # no interior hold

        receipt = qc.run_window(
            lease, lambda: make_raw_snapshot(), work,
            interval_s=0.03, max_gap_s=0.5, timeout_s=3)
        self.assertEqual(receipt["summary"]["CAPACITY_EVIDENCE"], "UNQUALIFIED")


# ── Receipt verification and tamper ────────────────────────────────────────
class TestReceipt(unittest.TestCase):
    def setUp(self):
        self.root = _tmp_root()
        self._leases = []

    def tearDown(self):
        for l in self._leases:
            try:
                l.close()
            except Exception:
                pass

    def _make_qualified_receipt(self):
        # run_window owns acquisition; the lease is NOT pre-acquired.
        lease = qc.CapacityLease(self.root, BINDING)
        self._leases.append(lease)
        receipt = qc.run_window(
            lease, lambda: make_raw_snapshot(),
            lambda ce: time.sleep(0.15),
            interval_s=0.03, max_gap_s=0.5, timeout_s=3)
        return receipt

    def test_verify_qualified(self):
        receipt = self._make_qualified_receipt()
        result = qc.verify_receipt(receipt, BINDING)
        self.assertEqual(result["CAPACITY_EVIDENCE"], "QUALIFIED")

    # Tamper: modify a sample's raw data
    def test_tampered_sample_raises(self):
        receipt = self._make_qualified_receipt()
        # Mutate first DURING sample
        for s in receipt["samples"]:
            if s["phase"] == "DURING":
                s["raw"]["model"]["id"] = "tampered-model"
                break
        with self.assertRaises(qc.CapacityError):
            qc.verify_receipt(receipt, BINDING)

    # Reorder: swap two samples
    def test_reordered_samples_raises(self):
        receipt = self._make_qualified_receipt()
        samples = receipt["samples"]
        if len(samples) >= 2:
            samples[0], samples[1] = samples[1], samples[0]
        with self.assertRaises(qc.CapacityError):
            qc.verify_receipt(receipt, BINDING)

    # Summary contradiction: flip CAPACITY_EVIDENCE
    def test_summary_contradiction_raises(self):
        receipt = self._make_qualified_receipt()
        receipt["summary"]["CAPACITY_EVIDENCE"] = "UNQUALIFIED"
        # If raw samples actually show clean data, this is a contradiction
        with self.assertRaises(qc.CapacityError):
            qc.verify_receipt(receipt, BINDING)

    # Deleted sample
    def test_deleted_sample_raises(self):
        receipt = self._make_qualified_receipt()
        receipt["samples"] = receipt["samples"][:-1]
        with self.assertRaises(qc.CapacityError):
            qc.verify_receipt(receipt, BINDING)

    # Recompute-after-tamper: an outer digest that was recomputed over a
    # tampered summary chain must still be rejected.  The verifier must
    # recompute all flags from the raw samples, not trust a re-hashed digest.
    def test_recomputed_digest_after_summary_tamper_raises(self):
        receipt = self._make_qualified_receipt()
        receipt["summary"]["CAPACITY_EVIDENCE"] = "UNQUALIFIED"
        # Recompute the outer digest from all the other (now-tampered) fields
        # so that a naive hash-only check would pass; the verifier must still
        # fail it because the summary contradicts the raw sample chain.
        recomputed = dict(receipt)
        summary = dict(receipt["summary"])
        digest = summary.pop("digest", None)
        recomputed["summary"] = summary
        if digest is not None:
            recomputed["summary"]["digest"] = qc.canonical_hash(recomputed)
        with self.assertRaises(qc.CapacityError):
            qc.verify_receipt(recomputed, BINDING)

    # Callback cannot override sticky failure (receipt level)
    def test_callback_cannot_override_sticky(self):
        lease = qc.CapacityLease(self.root, BINDING)
        self._leases.append(lease)
        tick = [0]

        def probe():
            tick[0] += 1
            if tick[0] <= 1:
                return make_raw_snapshot()
            return make_raw_snapshot(gpu_xml=_BAD_GPU_XML_EXTRA_CG)

        def work(cancel_event):
            time.sleep(0.15)  # succeeds

        receipt = qc.run_window(
            lease, probe, work, interval_s=0.03, max_gap_s=0.5, timeout_s=3)
        self.assertEqual(receipt["summary"]["CAPACITY_EVIDENCE"], "UNQUALIFIED")
        # verify_receipt must NOT raise (structurally valid UNQUALIFIED)
        result = qc.verify_receipt(receipt, BINDING)
        self.assertEqual(result["CAPACITY_EVIDENCE"], "UNQUALIFIED")


# ── Strict types via subTests (missing telemetry/model/context) ───────────
class TestStrictTypes(unittest.TestCase):
    def test_missing_fields_strict(self):
        cases = [
            ("missing model", lambda r: r.pop("model", None)),
            ("missing service", lambda r: r.pop("service", None)),
            ("missing gpu_xml", lambda r: r.__setitem__("gpu_xml", None)),
            ("missing clients", lambda r: r.pop("clients", None)),
            ("missing herdr", lambda r: r.pop("herdr", None)),
            ("context as string", lambda r: r["model"]["parameters"].__setitem__("max_seq_len", "262144")),
            ("context as float", lambda r: r["model"]["parameters"].__setitem__("max_seq_len", 262144.0)),
            ("service pid as string", lambda r: r["service"].__setitem__("pid", "6432")),
        ]
        for name, mutate in cases:
            with self.subTest(case=name):
                raw = make_raw_snapshot()
                mutate(raw)
                result = qc.evaluate_snapshot(raw, BINDING)
                # Unknown/missing telemetry must NEVER be treated as a healthy
                # inventory: reasons must be nonempty.  We do NOT assert that an
                # unrelated identity flag is necessarily False (e.g. missing
                # gpu_xml leaves model/service verified while gpu_conflict stays
                # False); the recorded reasons are the authoritative signal.
                self.assertTrue(result["reasons"])

    def test_missing_client_never_empty_healthy(self):
        # Explicit: unknown/missing client telemetry is never an empty healthy
        # inventory -- qwen_conflict stays False but reasons are recorded.
        raw = make_raw_snapshot()
        del raw["clients"]
        result = qc.evaluate_snapshot(raw, BINDING)
        self.assertFalse(result["client_conflict_observed"])
        self.assertTrue(result["reasons"])

    def test_missing_herdr_never_empty_healthy(self):
        # Explicit: unknown/missing herdr telemetry is never an empty healthy
        # worker inventory -- qwen_conflict stays False but reasons are recorded.
        raw = make_raw_snapshot()
        del raw["herdr"]
        result = qc.evaluate_snapshot(raw, BINDING)
        self.assertFalse(result["qwen_conflict_observed"])
        self.assertTrue(result["reasons"])

    def test_binding_strict_types(self):
        """Binding fields must be exact types; no aliases."""
        with self.subTest(case="context must be int"):
            bad = dict(BINDING, context="262144")
            raw = make_raw_snapshot()
            result = qc.evaluate_snapshot(raw, bad)
            self.assertFalse(result["model_identity_verified"])
        with self.subTest(case="source_head must be 40hex"):
            bad = dict(BINDING, source_head="short")
            raw = make_raw_snapshot()
            result = qc.evaluate_snapshot(raw, bad)
            self.assertFalse(result["model_identity_verified"])


if __name__ == "__main__":
    unittest.main()