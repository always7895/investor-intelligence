"""Real host entrypoints with in-memory lease/origin collaborators only.

These prove caller contracts, not protected admission, native custody or durability.
No bootstrap/native API, filesystem enrollment, credential or task action is used.
"""
from __future__ import annotations

import copy
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import revenue_guidance_host as host

A = "gir1:" + "a" * 64
B = "gir1:" + "b" * 64


def state(revision=A, pending=None, intent=None):
    return {"Schema": "guidance-provider-journal-v1", "StateRequired": True,
            "InputRevision": revision, "PendingRevision": pending, "Intent": intent}


class FakeLease:
    def __init__(self, initial):
        self.state = copy.deepcopy(initial)
        self.token = object()
        self.commits = []
        self.close = mock.Mock()

    def read_journal(self):
        return SimpleNamespace(state=copy.deepcopy(self.state), version=self.token, state_required=True)

    def commit_journal(self, token, requested):
        self.commits.append((token, copy.deepcopy(requested)))
        if token is not self.token:
            raise AssertionError("Host reconstructed or replaced the original version token")
        self.state = copy.deepcopy(requested)
        self.token = object()
        return SimpleNamespace(success=True, state=copy.deepcopy(self.state), version=self.token)


def session(lease, revision=A):
    value = host._Session(time.monotonic() + 30, {})
    value.lease = lease
    value.phase = "idle"
    # Native snapshot acquisition is outside this mocked host contract.
    value.input_revision = lambda: revision
    return value


class HostJournalContractTests(unittest.TestCase):
    def test_begin_and_restart_recovery_keep_original_tokens_and_pending(self):
        lease = FakeLease(state())
        current = session(lease, B)
        original_ticket = lease.token
        ref = current.journal()["VersionRef"]
        intent = {"Id": "a" * 32, "BaseInputRevision": A,
                  "ObservedAtBeginRevision": B, "PriorPendingRevision": None}
        begun = state(intent=intent)
        result = current.commit({"VersionRef": ref, "NewState": begun})
        self.assertTrue(result["Committed"])
        self.assertIs(lease.commits[0][0], original_ticket)
        self.assertEqual(current.phase, "begun")
        # A fresh host has no live completion witness after an interrupted intent.
        recovered = session(lease, B)
        original = lease.token
        recovered_ref = recovered.journal()["VersionRef"]
        result = recovered.commit({"VersionRef": recovered_ref, "NewState": state(B, B)})
        self.assertTrue(result["Committed"])
        self.assertIs(lease.commits[1][0], original)
        self.assertEqual(result["State"], state(B, B))
        self.assertEqual(recovered.phase, "idle")
        self.assertEqual(recovered.completion(B), {"Completed": False, "Revision": B})

    def test_json_ack_without_live_witness_cannot_clear_pending(self):
        lease = FakeLease(state(A, A))
        current = session(lease)
        ref = current.journal()["VersionRef"]
        with self.assertRaises(host.HostUnavailable):
            current.commit({"VersionRef": ref, "NewState": state(A, None)})
        self.assertEqual(lease.commits, [])
        self.assertEqual(lease.state, state(A, A))
        self.assertIsNone(current.witness)

    def test_unresolved_close_roots_exact_owner_graph_without_retry(self):
        lease = FakeLease(state(A, A))
        current = session(lease)
        current.operation = mock.MagicMock()
        owner = SimpleNamespace(live_owner_handle=object(), close=mock.Mock())
        current.live_owner = owner
        retained = []
        with mock.patch.object(host.windows, "native_custody_status", return_value="UNRESOLVED"), \
                mock.patch.object(host.provisioner, "retain_live_owner_custody", side_effect=retained.append):
            with self.assertRaises(host.HostUnavailable):
                current.close()
            self.assertTrue(current.closed)
            self.assertIs(owner._host_session_custody, current)
            self.assertIs(current.lease, lease)
            self.assertEqual(retained, [owner])
            lease.close.assert_not_called()
            owner.close.assert_not_called()
            current.operation.__exit__.assert_not_called()
            with self.assertRaises(host.HostUnavailable):
                current.close()
            self.assertEqual(retained, [owner])


if __name__ == "__main__":
    unittest.main()
