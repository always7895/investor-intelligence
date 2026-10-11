"""P2 two-slot journal through the real lease methods over an in-memory file.

Real NativeStorageLease.read_journal/commit_journal; only the native read_at,
write_at and flush calls are replaced by a recording in-memory journal. The B1
parent-deadline budget helpers are pure. No volume, handle, ACL, write-through
durability or native binding is exercised (G3).
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import struct
import sys
import time
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import revenue_guidance_storage as storage

A = "gir1:" + "a" * 64
B = "gir1:" + "b" * 64
BOOT = "synthetic-bootstrap"
MAGIC = b"GJSLT001"


def state(revision=A, pending=None, intent=None):
    return {"Schema": "guidance-provider-journal-v1", "StateRequired": True,
            "InputRevision": revision, "PendingRevision": pending, "Intent": intent}


def slot(sequence, value, *, bootstrap=BOOT, magic=MAGIC, digest=None, tail=b""):
    payload = json.dumps({"schema": "guidance-provider-storage-v1", "bootstrap_id": bootstrap,
                          "sequence": sequence, "state": value}, separators=(",", ":")).encode("utf-8")
    sha = hashlib.sha256(payload).digest() if digest is None else digest
    header = struct.pack("<8s I I Q I I 32s", magic, 1, storage.JOURNAL_HEADER_SIZE, sequence, len(payload), 0, sha)
    raw = header + payload + tail
    return raw + bytes(storage.JOURNAL_SLOT_SIZE - len(raw))


class FakeJournal:
    """131072-byte in-memory journal recording every native-shaped call in order."""
    def __init__(self, first, second):
        self.data = bytearray(first + second)
        self.handle = object()
        self.calls = []
        self.override = None  # (offset, count, full_reads) -> bytes | None
        self.full_reads = 0

    def read_at(self, handle, offset, count):
        if handle is not self.handle:
            raise AssertionError("foreign journal handle")
        self.calls.append(("read", offset, count))
        if count == storage.JOURNAL_FILE_SIZE:
            self.full_reads += 1
        if self.override is not None:
            value = self.override(offset, count, self.full_reads)
            if value is not None:
                return value
        return bytes(self.data[offset:offset + count])

    def write_at(self, handle, offset, data):
        if handle is not self.handle:
            raise AssertionError("foreign journal handle")
        self.calls.append(("write", offset, len(data), bytes(data) if len(data) == 8 else None))
        self.data[offset:offset + len(data)] = data

    def flush(self, handle):
        if handle is not self.handle:
            raise AssertionError("foreign journal handle")
        self.calls.append(("flush",))

    def writes(self):
        return [call for call in self.calls if call[0] == "write"]


def lease_over(journal):
    # Acquisition/anchor admission is outside this mocked journal contract.
    lease = storage.NativeStorageLease.__new__(storage.NativeStorageLease)
    lease.anchor = SimpleNamespace(bootstrap_id=BOOT, state_required=True)
    lease._initialize_custody(storage.NativeLimits())
    lease._state = "READY"
    lease.journal_handle = journal.handle
    return lease


@contextmanager
def native(journal):
    with mock.patch.object(storage.win32, "read_at", journal.read_at), \
            mock.patch.object(storage.win32, "write_at", journal.write_at), \
            mock.patch.object(storage.win32, "flush", journal.flush), \
            mock.patch.object(storage.win32, "_lazy_bind", side_effect=AssertionError("native binding reached")):
        yield


class TwoSlotJournalTests(unittest.TestCase):
    def setUp(self):
        self.journal = FakeJournal(slot(7, state(A)), slot(8, state(A, A)))
        self.original = bytes(self.journal.data)
        self.lease = lease_over(self.journal)
        self.enterContext(native(self.journal))

    def test_read_selects_newer_adjacent_slot_and_reissues_the_same_token(self):
        first = self.lease.read_journal()
        second = self.lease.read_journal()
        self.assertEqual(first.state, state(A, A))
        self.assertTrue(first.state_required)
        self.assertIs(first.version, second.version)
        self.assertEqual(first.version._seq, 8)
        self.assertEqual(self.journal.calls, [("read", 0, storage.JOURNAL_FILE_SIZE)] * 2)
        reversed_journal = FakeJournal(slot(9, state(B)), slot(8, state(A)))
        with native(reversed_journal):
            self.assertEqual(lease_over(reversed_journal).read_journal().state, state(B))

    def test_commit_cas_invalidates_older_slot_writes_magic_last_and_reads_back(self):
        issued = self.lease.read_journal().version
        self.journal.calls.clear()
        result = self.lease.commit_journal(issued, state(B, B))
        self.assertTrue(result.success)
        self.assertEqual(result.state, state(B, B))
        self.assertEqual(result.version._seq, 9)
        self.assertIsNot(result.version, issued)
        body = storage.JOURNAL_SLOT_SIZE - 8
        self.assertEqual(self.journal.calls, [
            ("read", 0, storage.JOURNAL_FILE_SIZE),
            ("write", 0, 8, b"INVALID!"), ("flush",), ("read", 0, 8),
            ("write", 8, body, None), ("flush",),
            ("write", 0, 8, MAGIC), ("flush",),
            ("read", 0, storage.JOURNAL_FILE_SIZE)])
        # The newer previous slot is untouched; the older slot now holds sequence 9.
        self.assertEqual(bytes(self.journal.data[storage.JOURNAL_SLOT_SIZE:]), self.original[storage.JOURNAL_SLOT_SIZE:])
        reread = self.lease.read_journal()
        self.assertEqual(reread.state, state(B, B))
        self.assertIs(reread.version, result.version)
        # The superseded token now loses the CAS without any write.
        before = len(self.journal.writes())
        stale = self.lease.commit_journal(issued, state(A))
        self.assertFalse(stale.success)
        self.assertEqual(stale.state, state(B, B))
        self.assertIs(stale.version, result.version)
        self.assertEqual(len(self.journal.writes()), before)
        # The next commit alternates to the other slot.
        self.journal.calls.clear()
        self.assertTrue(self.lease.commit_journal(result.version, state(B)).success)
        self.assertEqual(self.journal.writes()[0], ("write", storage.JOURNAL_SLOT_SIZE, 8, b"INVALID!"))
        self.assertEqual(bytes(self.journal.data[:8]), MAGIC)

    def test_reconstructed_foreign_or_missing_token_is_refused_before_io(self):
        issued = self.lease.read_journal().version
        self.journal.calls.clear()
        forged = storage.JournalVersionToken(issued._seq, issued._digest)
        for candidate in (forged, None, "8", SimpleNamespace(_seq=issued._seq, _digest=issued._digest)):
            with self.subTest(candidate=type(candidate).__name__):
                with self.assertRaises(storage.win32.StorageValidationFault):
                    self.lease.commit_journal(candidate, state(B, B))
        self.assertEqual(self.journal.calls, [])
        self.assertEqual(bytes(self.journal.data), self.original)
        self.assertFalse(self.lease._closed)

    def test_invalid_requested_state_is_refused_before_io(self):
        issued = self.lease.read_journal().version
        self.journal.calls.clear()
        intent = {"Id": "a" * 32, "BaseInputRevision": A, "ObservedAtBeginRevision": A, "PriorPendingRevision": None}
        for name, value in (("extra", {**state(), "Witness": True}), ("state-not-required", {**state(), "StateRequired": False}),
                            ("revision", state("gir1:" + "A" * 64)), ("pending", state(A, "gir1:")),
                            ("intent-extra", state(A, None, {**intent, "Acked": True})),
                            ("intent-id", state(A, None, {**intent, "Id": ""})), ("not-dict", [state()])):
            with self.subTest(name):
                with self.assertRaises(storage.win32.StorageValidationFault):
                    self.lease.commit_journal(issued, value)
        self.assertEqual(self.journal.calls, [])
        self.assertEqual(bytes(self.journal.data), self.original)

    def test_torn_foreign_nonadjacent_and_short_journals_fail_closed(self):
        current = state(A, A)
        cases = {
            "torn-digest": (slot(7, state(A)), slot(8, current, digest=bytes(32))),
            "invalidated-magic": (slot(7, state(A)), slot(8, current, magic=b"INVALID!")),
            "foreign-bootstrap": (slot(7, state(A)), slot(8, current, bootstrap="other-bootstrap")),
            "nonadjacent": (slot(7, state(A)), slot(9, current)),
            "equal-sequences": (slot(8, state(A)), slot(8, current)),
            "nonzero-tail": (slot(7, state(A)), slot(8, current, tail=b"\x01")),
            "invalid-p1-state": (slot(7, state(A)), slot(8, {**current, "StateRequired": False})),
        }
        for name, (first, second) in cases.items():
            with self.subTest(name):
                journal = FakeJournal(first, second)
                with native(journal):
                    with self.assertRaises(storage.JournalRecoveryRequired):
                        lease_over(journal).read_journal()
                self.assertEqual(journal.writes(), [])
        short = FakeJournal(slot(7, state(A)), slot(8, current))
        del short.data[-1]
        with native(short):
            with self.assertRaises(storage.JournalRecoveryRequired):
                lease_over(short).read_journal()

    def test_slot_torn_after_token_issue_blocks_commit_before_any_write(self):
        issued = self.lease.read_journal().version
        self.journal.data[storage.JOURNAL_SLOT_SIZE:storage.JOURNAL_SLOT_SIZE + 8] = b"INVALID!"
        with self.assertRaises(storage.JournalRecoveryRequired):
            self.lease.commit_journal(issued, state(B, B))
        self.assertEqual(self.journal.writes(), [])
        self.assertFalse(self.lease._closed)  # recovery is required; no write was attempted

    def test_invalidation_readback_mismatch_closes_lease_without_body_write(self):
        issued = self.lease.read_journal().version
        self.journal.override = lambda offset, count, _full: MAGIC if (offset, count) == (0, 8) else None
        with self.assertRaises(storage.StorageLeaseError) as raised:
            self.lease.commit_journal(issued, state(B, B))
        self.assertIs(type(raised.exception), storage.StorageLeaseError)
        self.assertEqual(self.journal.writes(), [("write", 0, 8, b"INVALID!")])
        self.assertTrue(self.lease._closed)
        # The newer slot survives; the invalidated older slot is never reported clean.
        self.assertEqual(bytes(self.journal.data[storage.JOURNAL_SLOT_SIZE:]), self.original[storage.JOURNAL_SLOT_SIZE:])
        # The custody guard refuses a closed lease before any further journal I/O.
        with self.assertRaises(storage.win32.StorageValidationFault):
            self.lease.read_journal()
        self.assertEqual(self.journal.writes(), [("write", 0, 8, b"INVALID!")])

    def test_final_readback_mismatch_closes_lease_and_issues_no_token(self):
        issued = self.lease.read_journal().version
        original = self.original
        # The commit's second full read (the final verify) observes the pre-commit file.
        self.journal.override = lambda offset, count, full: original if count == storage.JOURNAL_FILE_SIZE and full == 3 else None
        with self.assertRaises(storage.StorageLeaseError) as raised:
            self.lease.commit_journal(issued, state(B, B))
        self.assertIs(type(raised.exception), storage.StorageLeaseError)
        self.assertTrue(self.lease._closed)
        self.assertEqual([t._seq for t in self.lease._issued_tokens], [8])

    def test_issued_token_custody_is_bounded_before_any_write(self):
        issued = self.lease.read_journal().version
        for index in range(63):
            result = self.lease.commit_journal(issued, state(A if index % 2 else B))
            self.assertTrue(result.success)
            issued = result.version
        self.assertEqual(len(self.lease._issued_tokens), 64)
        before = bytes(self.journal.data)
        self.journal.calls.clear()
        with self.assertRaises(storage.win32.StorageValidationFault):
            self.lease.commit_journal(issued, state(B, B))
        self.assertEqual(self.journal.writes(), [])
        self.assertEqual(bytes(self.journal.data), before)


class ParentDeadlineBudgetTests(unittest.TestCase):
    def test_b1_limits_require_a_live_absolute_parent_deadline(self):
        limits = storage.NativeLimits.b1(600000)
        for deadline in (None, 5, float("inf"), float("nan"), time.monotonic() - 1):
            with self.subTest(deadline=deadline):
                with self.assertRaises(storage.BudgetExceededError):
                    storage._remaining_b1_limits(limits, deadline)
        narrowed = storage._remaining_b1_limits(limits, time.monotonic() + 5)
        self.assertEqual(narrowed.profile, "b1")
        self.assertTrue(0 < narrowed.max_elapsed_ms <= 5000)

    def test_constrain_remaining_only_tightens_and_expired_budget_refuses(self):
        budget = storage.NativeBudget(storage.NativeLimits(), [None])
        original = budget.deadline
        budget.constrain_remaining(1000)
        tightened = budget.deadline
        self.assertLessEqual(tightened, original)
        self.assertLessEqual(tightened, time.monotonic() + 1)
        budget.constrain_remaining(9000)
        self.assertEqual(budget.deadline, tightened)
        for value in (-1, "1", 1.5, True):
            with self.subTest(value=value):
                with self.assertRaises(storage.BudgetExceededError):
                    budget.constrain_remaining(value)
        budget.deadline = time.monotonic() - 1
        with self.assertRaises(storage.BudgetExceededError):
            budget.precharge_read(1)
        self.assertEqual(budget.bytes_read, 0)


if __name__ == "__main__":
    unittest.main()
