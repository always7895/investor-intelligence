"""Synthetic readiness-wrapper tests: no Cloudflare, no live Worker, no pwsh.

Covers the isolated-harness bounded 404 convergence wrapper only. The shared
production gate v213_edge_readiness.ps1 is not exercised and must keep its
fail-fast semantics.
"""
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import v213_qa_live_gate as gate

TRANSIENT_404 = 'V213_READINESS_HTTP_FAILED; http_status=404; exception_type=WebException'


def result(returncode, stderr):
    return SimpleNamespace(returncode=returncode, stderr=stderr, stdout='{"ready": true}')


class IsolatedReadinessWrapperTests(unittest.TestCase):
    def setUp(self):
        self.slept = []
        self.calls = []

    def run_gate(self, results, **kwargs):
        def fake_run(cmd, **opts):
            self.calls.append((list(cmd), opts))
            return results[min(len(self.calls) - 1, len(results) - 1)]
        return gate.run_isolated_readiness_gate('shared-gate', run=fake_run, sleep=self.slept.append, **kwargs)

    def test_transient_404_retries_same_shared_gate_then_passes(self):
        results = [result(1, TRANSIENT_404), result(0, '')]
        check, attempts, retries = self.run_gate(results)
        self.assertEqual(check.returncode, 0)
        self.assertEqual((attempts, retries), (2, 1))
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.slept, [5.0])
        # Same shared-gate command is re-invoked, never a new readiness implementation.
        self.assertEqual(self.calls[0][0], self.calls[1][0])

    def test_persistent_404_fails_after_bounded_retries(self):
        bad = result(1, TRANSIENT_404)
        check, attempts, retries = self.run_gate([bad], max_404_retries=4)
        self.assertEqual(check.returncode, 1)
        self.assertEqual((attempts, retries), (5, 4))
        self.assertEqual(len(self.slept), 4)

    def test_every_other_failure_fails_closed_immediately(self):
        cases = {
            '409': 'V213_READINESS_HTTP_FAILED; http_status=409; exception_type=WebException',
            '503': 'V213_READINESS_HTTP_FAILED; http_status=503; exception_type=WebException',
            'network_status_0': 'V213_READINESS_HTTP_FAILED; http_status=0; exception_type=WebException',
            'mixed_404_and_mismatch': 'V213_READINESS_HTTP_FAILED; http_status=404; V213_READINESS_VERSION_MISMATCH',
            'schema_mismatch': 'V213_READINESS_SCHEMA_OR_CONTRACT_MISMATCH',
            'no_status_observed': 'V213_READINESS_HTTP_FAILED; exception_type=WebException',
            'malformed_no_code': 'exception_type=WebException',
            'empty_stderr': '',
        }
        for label, stderr in cases.items():
            with self.subTest(label=label):
                self.slept.clear()
                self.calls.clear()
                check, attempts, retries = self.run_gate([result(1, stderr)])
                self.assertEqual(check.returncode, 1)
                self.assertEqual((attempts, retries), (1, 0))
                self.assertEqual(len(self.calls), 1)
                self.assertEqual(self.slept, [])

if __name__ == '__main__':
    unittest.main()
