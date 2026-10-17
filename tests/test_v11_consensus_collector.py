"""Operator 2026-10-13 (A1): the analyst-consensus revenue route. The refresh step is scripts/revenue_consensus_quarterly.py main():
it follows the registry's consensus_enabled gate, serves the registry's NOT_DISCLOSED issuers, keeps the last good capture on a
failed read and never overwrites an unreadable cache. The transport is a fake (no network); the CLI entry is called as the
refresh calls it (argv), and the cache it writes feeds the real selector and sealer."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import revenue_consensus_quarterly as collector  # noqa: E402


def load_generator():
    path = ROOT / "tests" / "fixtures" / "make_v11_consensus_sealed.py"
    spec = importlib.util.spec_from_file_location("make_v11_consensus_sealed", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GEN = load_generator()
KR = GEN.yahoo_raw("KRW", [("0q", "2026-09-30", 1.0e14, 37), ("+1q", "2026-12-31", 1.1e14, 36)])
THIN = GEN.yahoo_raw("KRW", [("0q", "2026-09-30", 1.0e14, 2)])


class CollectorStepTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.cache = self.dir / "revenue_consensus_quarterly.json"

    def registry(self, gate, statuses=(("000660.KS", "NOT_DISCLOSED"), ("005930.KS", "NOT_DISCLOSED"), ("NVDA", "GUIDANCE"))):
        data = {"schema": "revenue-guidance-v1", "version": 1,
                "issuers": [{"symbol": symbol, "status": status} for symbol, status in statuses]}
        if gate is not None:
            data["consensus_enabled"] = gate
        path = self.dir / "registry.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def run_step(self, registry, transport, *extra):
        """Run main() exactly as `scripts\\revenue_consensus_quarterly.py --if-older-than-hours 6` does; returns (exit code, stdout)."""
        calls = []

        def session_fetch(symbol):
            calls.append(symbol)
            value = transport(symbol)
            if isinstance(value, Exception):
                raise value
            return value

        argv = ["revenue_consensus_quarterly.py", "--if-older-than-hours", "6", "--cache-path", str(self.cache),
                "--registry-path", str(registry), *extra]
        out = io.StringIO()
        with mock.patch.object(sys, "argv", argv), mock.patch.object(collector, "_session_fetch", session_fetch), \
                contextlib.redirect_stdout(out):
            code = collector.main()
        self.calls = calls
        return code, out.getvalue()

    def test_the_gate_off_makes_no_provider_request_and_writes_no_cache(self):
        for gate in (None, False):
            code, out = self.run_step(self.registry(gate), lambda symbol: self.fail("no request while the gate is off"))
            self.assertEqual((code, self.calls), (0, []), repr(gate))
            self.assertIn("CONSENSUS_COLLECTION_SKIPPED", out)
            self.assertFalse(self.cache.exists())

    def test_only_a_json_true_opens_the_gate(self):
        for text in ('{"consensus_enabled": "true", "issuers": []}', '{"consensus_enabled": 1, "issuers": []}', '{"consensus_enabled": null}',
                     "[]", "not json", ""):
            path = self.dir / "gate.json"
            path.write_text(text, encoding="utf-8")
            self.assertFalse(collector.registry_consensus_enabled(path), text)
        self.assertFalse(collector.registry_consensus_enabled(self.dir / "missing.json"))
        self.assertTrue(collector.registry_consensus_enabled(self.registry(True)))

    def test_the_gate_on_serves_the_not_disclosed_issuers_only(self):
        code, out = self.run_step(self.registry(True), lambda symbol: KR)
        self.assertEqual((code, sorted(self.calls)), (0, ["000660.KS", "005930.KS"]))  # NVDA (a guidance record) is never read
        self.assertIn("CONSENSUS_REFRESH symbols=2 refreshed=2 unusable=0 failed=0", out)
        cache = collector.load_cache(self.cache)
        self.assertEqual(sorted(cache), ["000660.KS", "005930.KS"])
        entry = collector.history_of(cache, "000660.KS")[-1]
        self.assertTrue(collector.validate_consensus_entry(entry, "000660.KS"))
        self.assertEqual(entry["source_url"], GEN.YAHOO.format(symbol="000660.KS"))

    def test_an_explicit_symbol_list_bypasses_the_gate(self):
        code, _ = self.run_step(self.registry(False), lambda symbol: KR, "--symbols", "ACME")
        self.assertEqual((code, self.calls), (0, ["ACME"]))
        self.assertEqual(sorted(collector.load_cache(self.cache)), ["ACME"])

    def test_the_cadence_keeps_one_request_per_window(self):
        registry = self.registry(True)
        self.run_step(registry, lambda symbol: KR)
        self.assertEqual(len(self.calls), 2)
        code, _ = self.run_step(registry, lambda symbol: KR)  # the captures are minutes old: reused, no request
        self.assertEqual((code, self.calls), (0, []))

    def test_a_symbol_without_a_usable_capture_is_reported_and_is_not_a_failed_step(self):
        code, out = self.run_step(self.registry(True), lambda symbol: THIN if symbol == "000660.KS" else KR)
        self.assertEqual(code, 0)  # fewer than three analysts is a data state, not a failed refresh
        self.assertIn("No usable consensus for 000660.KS", out)
        self.assertIn("refreshed=1 unusable=1 failed=0", out)
        self.assertEqual(sorted(collector.load_cache(self.cache)), ["005930.KS"])  # no capture kept for the thin one

    def test_a_failed_read_fails_the_step_and_keeps_the_last_good_capture(self):
        old = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=7)  # older than the six-hour cadence
        collector.refresh_symbol("000660.KS", old, max_age_hours=6, fetch_json=lambda url: KR, cache_path=self.cache)
        before = collector.history_of(collector.load_cache(self.cache), "000660.KS")
        code, out = self.run_step(self.registry(True), lambda symbol: RuntimeError("HTTP 401") if symbol == "000660.KS" else KR)
        self.assertEqual(code, 1)
        self.assertIn("Error refreshing 000660.KS: HTTP 401", out)
        self.assertIn("refreshed=1 unusable=0 failed=1", out)
        self.assertEqual(collector.history_of(collector.load_cache(self.cache), "000660.KS"), before)  # the last good capture stays
        self.assertEqual(len(collector.history_of(collector.load_cache(self.cache), "005930.KS")), 1)  # the other symbol still refreshed

    def test_an_unreadable_cache_fails_the_step_and_is_never_overwritten(self):
        self.cache.write_bytes(b'{"000660.KS": [')
        code, out = self.run_step(self.registry(True), lambda symbol: KR)
        self.assertEqual(code, 1)
        self.assertIn("MALFORMED_CACHE_FILE", out)
        self.assertEqual(self.cache.read_bytes(), b'{"000660.KS": [')  # kept as found for the operator, never silently replaced

    def test_a_bad_cadence_argument_is_refused(self):
        argv = ["x", "--if-older-than-hours", "-1", "--cache-path", str(self.cache), "--registry-path", str(self.registry(True))]
        with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(collector.main(), 2)

    def test_the_cache_the_step_wrote_feeds_the_sealers_selector(self):
        """The refresh's cache -> the selection every hourly build makes (a build never binds a later capture)."""
        self.run_step(self.registry(True), lambda symbol: KR)
        # the capture the step just wrote is stamped now(); select at the capture's own instant plus one hour
        stamp = collector.history_of(collector.load_cache(self.cache), "000660.KS")[-1]["captured_at"]
        cutoff = GEN.utc(stamp) + timedelta(hours=1)
        picked = collector.select_for_cutoff(collector.load_cache(self.cache), cutoff)
        self.assertEqual(sorted(picked), ["000660.KS", "005930.KS"])
        self.assertEqual(picked["000660.KS"]["captured_at"], stamp)
        self.assertEqual(collector.select_for_cutoff(collector.load_cache(self.cache), GEN.utc(stamp) - timedelta(seconds=1)), {})


if __name__ == "__main__":
    unittest.main()
