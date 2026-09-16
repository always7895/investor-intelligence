"""Contract tests for scripts/rollback_sealed_snapshot.py (no network, fake kv).

Covers: git-tracked-only target rule, live-object sha verification, NO-OP when the
pointer already matches, dry-run never writes, --apply writes the pointer exactly
once and readback-verifies, and every failure path leaves the pointer untouched.
"""
import copy
import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import rollback_sealed_snapshot as rb  # noqa: E402

RUN = "20260916T092839Z-2873c2ff6316"


def sha(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class FakeKv:
    def __init__(self, store: dict):
        self.store = dict(store)
        self.puts: list[str] = []

    def get(self, key: str):
        v = self.store.get(key)
        return None if v is None else v

    def put(self, key: str, body: str):
        self.puts.append(key)
        self.store[key] = body
        return True


def committed_run():
    return rb.load_target(RUN)


class RollbackSealedSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.target = committed_run()
        self.store = dict(self.target["objects"])
        self.store["snapshot:current"] = json.dumps({
            "schema_version": 2, "run_id": "20260916T999999Z-deadbeef0000",
            "transaction_id": "0" * 32, "seal_sha256": "f" * 64,
            "public_data_as_of": "2026-09-16T00:00:00Z", "promoted_at": "2026-09-16T00:00:00Z",
            "provider_scope": "public_only", "owner_watchlist_inherited": False,
        })
        self.kv = FakeKv(self.store)

    def test_target_is_git_tracked(self):
        out = subprocess.run(["git", "ls-files", f"state/v213-snapshots/{RUN}/pointer.raw.json"],
                             cwd=str(ROOT), capture_output=True, text=True)
        self.assertEqual(out.stdout.strip(), f"state/v213-snapshots/{RUN}/pointer.raw.json")

    def test_verify_objects_passes_on_intact_store(self):
        rows = rb.verify_objects(self.target, self.kv.get)
        self.assertEqual(len(rows), 14)

    def test_dry_run_never_writes_pointer(self):
        res = rb.rollback(RUN, apply=False, kv_get=self.kv.get, kv_put=self.kv.put)
        self.assertEqual(res["status"], "DRY_RUN")
        self.assertEqual(res["verified_objects"], 14)
        self.assertEqual(self.kv.puts, [])
        self.assertEqual(self.kv.store["snapshot:current"], self.store["snapshot:current"])

    def test_apply_rewrites_pointer_once_and_readback_verifies(self):
        res = rb.rollback(RUN, apply=True, kv_get=self.kv.get, kv_put=self.kv.put)
        self.assertEqual(res["status"], "ROLLED_BACK")
        self.assertTrue(res["applied"])
        self.assertEqual(self.kv.puts, ["snapshot:current"])
        self.assertEqual(self.kv.store["snapshot:current"], self.target["pointer_text"])

    def test_pointer_already_target_is_noop(self):
        self.kv.store["snapshot:current"] = self.target["pointer_text"]
        res = rb.rollback(RUN, apply=True, kv_get=self.kv.get, kv_put=self.kv.put)
        self.assertEqual(res["status"], "NOOP")
        self.assertEqual(self.kv.puts, [])

    def test_object_mismatch_aborts_without_pointer_write(self):
        bad = dict(self.target["objects"])
        list(bad)[0]  # any
        for k in bad:
            bad[k] = bad[k] + "x"
            break
        kv = FakeKv(bad)
        kv.store["snapshot:current"] = self.store["snapshot:current"]
        with self.assertRaises(rb.RollbackError):
            rb.rollback(RUN, apply=True, kv_get=kv.get, kv_put=kv.put)
        self.assertEqual(kv.puts, [])
        self.assertEqual(kv.store["snapshot:current"], self.store["snapshot:current"])

    def test_missing_object_key_aborts(self):
        store = dict(self.store)
        for k in list(store):
            if k.startswith("snapshot:") and k != "snapshot:current":
                del store[k]
                break
        kv = FakeKv(store)
        with self.assertRaises(rb.RollbackError):
            rb.rollback(RUN, apply=True, kv_get=kv.get, kv_put=kv.put)
        self.assertEqual(kv.puts, [])

    def test_pointer_put_failure_aborts(self):
        def bad_put(key, body):
            return False
        with self.assertRaises(rb.RollbackError):
            rb.rollback(RUN, apply=True, kv_get=self.kv.get, kv_put=bad_put)
        self.assertEqual(self.kv.store["snapshot:current"], self.store["snapshot:current"])

    def test_untracked_run_dir_is_refused(self):
        with self.assertRaises(rb.RollbackError):
            rb.load_target("20260916T000000Z-ffffffffffff")

    def test_cli_dry_run_prints_json_and_exit_0(self):
        fake = FakeKv(self.store)
        orig_g, orig_p = rb.wrangler_kv_get, rb.wrangler_kv_put
        rb.wrangler_kv_get = fake.get
        rb.wrangler_kv_put = fake.put
        try:
            code = rb.main(["--target-run", RUN])
        finally:
            rb.wrangler_kv_get, rb.wrangler_kv_put = orig_g, orig_p
        self.assertEqual(code, 0)
        self.assertEqual(fake.puts, [])


if __name__ == "__main__":
    unittest.main()