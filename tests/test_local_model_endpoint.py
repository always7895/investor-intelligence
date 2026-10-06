"""Local model auto-detection (operator 2026-09-26: the local model's port and ID change). No network: catalogs and
listeners are injected, the saved selection and configuration are patched. Three separate concerns are kept apart here:

1. LEGACY MATCHING (ResolveTests): the public selected_intent boundary is MOCKED to return {'mode': 'LEGACY_ABSENT'}, so
   no shared binding resolution, install-state read, metadata read or native/registry work runs. The default positive
   fixtures use the PERMITTED port 5001 (explicit, moved-port and listener cases vary) because the production policy protects
   5000 (IBKR Client Portal) and 8000 (retired decider).
2. PROTECTED-PORT REFUSAL (one ResolveTests case): 5000/8000 are never probed even when given explicitly or through
   saved/configured/env hints. Fake catalogs only; NO broker contact, no policy change.
3. MOCKED SELECTED-INTENT DISPATCH (SelectedIntentDispatchTests): the forwarding between resolve() and the selected
   resolver only.
None of these gives any live, native or binding MODEL QUALIFICATION; PINNED and the other model strings below are
SYNTHETIC compatibility-test input IDs only and are never a claim about a deployed, selected or qualified model."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import local_model_endpoint as endpoint  # noqa: E402

PINNED = "Qwen3.8-27B-EXL3-5.5bpw-v2"  # synthetic family-rule input ID only, not a deployed/selected model claim
LEGACY_INTENT = {"mode": "LEGACY_ABSENT"}


def rows(*ids, aliases=None):
    return [{"id": ident, "aliases": list((aliases or {}).get(ident, []))} for ident in ids]


class ResolveTests(unittest.TestCase):
    """Legacy matching rules only: the selected-intent seam is mocked to LEGACY_ABSENT. The default positive fixtures use the
    permitted port 5001; explicit, moved-port and listener cases use other ports (5000 is the protected broker port and is never
    a model probe)."""

    def setUp(self):
        self.probed = []
        stack = [patch.object(endpoint, "selected_intent", return_value=dict(LEGACY_INTENT)),
                 patch.object(endpoint, "saved_selection", return_value={"model": "", "base": ""}),
                 patch.object(endpoint, "configured_reasoner", return_value={"model": PINNED, "base": "http://127.0.0.1:5001/v1"}),
                 patch.dict("os.environ", {"II_LLAMA_BASE_URL": "", "II_LOCAL_LLM_MODEL": ""})]
        for item in stack:
            item.start()
            self.addCleanup(item.stop)

    def reader(self, servers):
        def read(base):
            self.probed.append(base)
            return servers.get(base)
        return read

    def test_family_model_on_a_moved_port_is_found(self):
        found = endpoint.resolve(catalog_reader=self.reader({"http://127.0.0.1:8080": rows("Qwen3.8-27B")}), listeners=lambda: [])
        self.assertEqual((found["base_url"], found["model"], found["match"], found["changed"]),
                         ("http://127.0.0.1:8080", "Qwen3.8-27B", "family", True))

    def test_exact_model_wins_over_an_earlier_family_match_and_skips_the_listener_scan(self):
        servers = {"http://127.0.0.1:5001": rows("Qwen3.8-27B-UD-Q5"), "http://127.0.0.1:8080": rows(PINNED)}
        listened = []
        found = endpoint.resolve(catalog_reader=self.reader(servers), listeners=lambda: listened.append(1) or [9123])
        self.assertEqual((found["base_url"], found["match"]), ("http://127.0.0.1:8080", "exact"))
        self.assertEqual(listened, [])  # an exact match on the known ports needs no further scan

    def test_any_listening_port_is_scanned_when_the_known_ports_have_no_exact_match(self):
        servers = {"http://127.0.0.1:9123": rows("other-model", PINNED)}
        found = endpoint.resolve(catalog_reader=self.reader(servers), listeners=lambda: [8000, 9123])
        self.assertEqual((found["base_url"], found["model"], found["match"]), ("http://127.0.0.1:9123", PINNED, "exact"))
        self.assertNotIn("http://127.0.0.1:8000", self.probed)  # the System One decider is never probed

    def test_alias_counts_as_exact_and_unrelated_models_are_ambiguous(self):
        servers = {"http://127.0.0.1:5001": rows("canonical-x", aliases={"canonical-x": [PINNED]})}
        found = endpoint.resolve(catalog_reader=self.reader(servers), listeners=lambda: [])
        self.assertEqual((found["model"], found["match"]), ("canonical-x", "exact"))
        many = {"http://127.0.0.1:5001": rows("gemma4", "llama-70B")}
        self.assertEqual(endpoint.resolve(catalog_reader=self.reader(many), listeners=lambda: [])["error"], "LOCAL_MODEL_AMBIGUOUS")
        self.assertEqual(endpoint.resolve(catalog_reader=self.reader({}), listeners=lambda: [])["error"], "LOCAL_MODEL_NOT_FOUND")

    def test_want_and_base_are_tried_first_and_only_loopback_is_probed(self):
        servers = {"http://127.0.0.1:7777": rows("mine-8B")}
        found = endpoint.resolve("mine-8B", "http://localhost:7777/v1", catalog_reader=self.reader(servers), listeners=lambda: [])
        self.assertEqual((found["base_url"], found["match"]), ("http://127.0.0.1:7777", "exact"))
        self.assertEqual(self.probed[0], "http://127.0.0.1:7777")
        # the malformed samples use the permitted 5001 so they test the scheme/host/path/query/userinfo rules themselves,
        # not the protected-port refusal; the 8000 sample stays as the protected-port negative.
        for bad in ("https://127.0.0.1:5001", "http://example.com:5001", "http://user@127.0.0.1:5001", "http://127.0.0.1:8000",
                    "http://127.0.0.1:5001/x", "http://127.0.0.1:5001?k=1"):
            self.assertIsNone(endpoint.loopback_base(bad), bad)

    def test_protected_ports_never_probe_even_with_explicit_or_saved_hints(self):
        """Protected-port refusal (policy proof, fake catalogs only, NO broker/decider contact): 5000 and 8000 stay
        unprobed even when offered as explicit base, saved, configured and env hints. Not a model qualification."""
        with patch.object(endpoint, "saved_selection", return_value={"model": PINNED, "base": "http://127.0.0.1:5000"}), \
                patch.object(endpoint, "configured_reasoner", return_value={"model": PINNED, "base": "http://127.0.0.1:5000"}), \
                patch.dict("os.environ", {"II_LLAMA_BASE_URL": "http://127.0.0.1:5000"}):
            found = endpoint.resolve(PINNED, "http://127.0.0.1:5000",
                                    catalog_reader=self.reader({"http://127.0.0.1:5000": rows(PINNED),
                                                               "http://127.0.0.1:8000": rows(PINNED)}),
                                    listeners=lambda: [5000, 8000])
        self.assertEqual(found["error"], "LOCAL_MODEL_NOT_FOUND")
        self.assertNotIn("http://127.0.0.1:5000", self.probed)
        self.assertNotIn("http://127.0.0.1:8000", self.probed)
        self.assertTrue(self.probed)  # permitted known candidates really were probed: a no-op pass is impossible
        self.assertIsNone(endpoint.loopback_base("http://127.0.0.1:5000"))
        self.assertIsNone(endpoint.loopback_base("http://127.0.0.1:8000"))

    def test_the_only_model_is_offered_last_and_the_listener_scan_is_capped(self):
        servers = {"http://127.0.0.1:5001": rows("gemma4"), "http://127.0.0.1:9001": rows("Qwen3.8-27B")}
        found = endpoint.resolve(catalog_reader=self.reader(servers), listeners=lambda: list(range(9001, 9101)))
        self.assertEqual((found["base_url"], found["match"]), ("http://127.0.0.1:9001", "family"))  # family beats an earlier only
        found = endpoint.resolve(catalog_reader=self.reader({"http://127.0.0.1:5001": rows("gemma4")}), listeners=lambda: [])
        self.assertEqual((found["model"], found["match"], found["changed"]), ("gemma4", "only", True))
        self.probed.clear()
        endpoint.resolve(catalog_reader=self.reader({}), listeners=lambda: list(range(9001, 9201)))
        self.assertEqual(len([base for base in self.probed if 9001 <= int(base.rsplit(":", 1)[1]) <= 9200]), endpoint.MAX_LISTENERS)

    def test_family_rule(self):
        self.assertEqual(endpoint.model_family(PINNED), "qwen3.8-27b")
        self.assertEqual(endpoint.model_family("Qwen3.8-27B-UD-Q5_K_XL-7a1459e88548"), "qwen3.8-27b")
        self.assertEqual(endpoint.model_family("gemma4"), "gemma4")
        self.assertIsNone(endpoint.choose_model(rows("Qwen3.8-27B-A", "Qwen3.8-27B-B"), [PINNED]))  # two of one family


class CatalogTests(unittest.TestCase):
    """Raw catalog parsing through an injected fake opener: no socket is ever used, and these independent fixture URLs are
    not resolve() matching fixtures, so they may name any loopback port, including 5000."""

    def test_openai_list_shape_only(self):
        class Response:
            def __init__(self, url, body): self.url, self.body = url, body
            def __enter__(self): return self
            def __exit__(self, *exc): return False
            def geturl(self): return self.url
            def read(self, limit=None): return self.body

        replies = {"http://127.0.0.1:5000/v1/models": b'{"object":"list","data":[{"id":"m-7B","aliases":["x"]},{"id":""},"s-1B"]}',
                   "http://127.0.0.1:5001/v1/models": b'{"status":"ok"}', "http://127.0.0.1:5001/models": b"<html>",
                   "http://127.0.0.1:5003/v1/models": b'{"data":[{"id":"redirected-7B"}]}'}

        class Opener:
            def open(self, request, timeout):
                if request.full_url not in replies:
                    raise OSError("refused")
                final = "http://127.0.0.1:5003/login" if ":5003/" in request.full_url else request.full_url
                return Response(final, replies[request.full_url])

        with patch.object(endpoint, "build_opener", return_value=Opener()):
            self.assertEqual(endpoint.read_catalog("http://127.0.0.1:5000"),
                             [{"id": "m-7B", "aliases": ["x"]}, {"id": "s-1B", "aliases": []}])
            self.assertIsNone(endpoint.read_catalog("http://127.0.0.1:5001"))
            self.assertIsNone(endpoint.read_catalog("http://127.0.0.1:5002"))
            self.assertIsNone(endpoint.read_catalog("http://127.0.0.1:5003"))  # a redirected reply is not a catalog


class SelectedIntentDispatchTests(unittest.TestCase):
    """Pure boundary tests for the dispatcher inside resolve(): the selected-intent step runs BEFORE any injected catalog
    reader or listener scan. They prove DISPATCH AND FAIL-CLOSED SHAPE ONLY. In particular test (c) does NOT show that a
    selected mode accepts scanning, metadata reads or any real native/binding operation: the real _resolve_selected refuses
    scan_all, and here it is replaced by a synthetic sentinel so only the forwarding is observed."""

    REFUSAL = {"error": "LOCAL_MODEL_BINDING_UNAVAILABLE", "reason": "BINDING_OPERATION_UNAVAILABLE",
               "mode": "SELECTED_INTENT_UNAVAILABLE", "wanted": [], "servers": [], "probed": 0,
               "qualification": "UNQUALIFIED"}

    def probes(self):
        """Injected probes that would fail loudly if resolve reached the legacy scanner."""
        return (Mock(side_effect=AssertionError("catalog_reader must not be called")),
                Mock(side_effect=AssertionError("listeners must not be called")))

    def assert_refusal(self, found):
        self.assertEqual(found, self.REFUSAL)
        self.assertEqual(found["probed"], 0)
        self.assertEqual(found["wanted"], [])
        self.assertEqual(found["servers"], [])

    def test_intent_unavailable_refuses_before_any_probe(self):
        catalog_reader, listeners = self.probes()
        with patch.object(endpoint, "selected_intent", side_effect=endpoint.IntentUnavailable("BINDING_OPERATION_UNAVAILABLE")), \
                patch.object(endpoint, "_resolve_selected") as selected_resolver, \
                patch.object(endpoint, "saved_selection") as saved, \
                patch.object(endpoint, "configured_reasoner") as configured:
            found = endpoint.resolve(catalog_reader=catalog_reader, listeners=listeners)
        self.assert_refusal(found)
        catalog_reader.assert_not_called()
        listeners.assert_not_called()
        selected_resolver.assert_not_called()  # the selected resolver is reached only for an EXPLICIT_STRATA intent
        saved.assert_not_called()
        configured.assert_not_called()

    def test_unexpected_operational_error_refuses_without_legacy_fallback_or_text(self):
        catalog_reader, listeners = self.probes()
        with patch.object(endpoint, "selected_intent", side_effect=RuntimeError("SYNTHETIC_PRIVATE_DETAIL")), \
                patch.object(endpoint, "_resolve_selected") as selected_resolver, \
                patch.object(endpoint, "saved_selection") as saved, \
                patch.object(endpoint, "configured_reasoner") as configured:
            found = endpoint.resolve(catalog_reader=catalog_reader, listeners=listeners)
        self.assert_refusal(found)  # same fixed code: resolve never falls back to the legacy scanner here
        catalog_reader.assert_not_called()
        listeners.assert_not_called()
        selected_resolver.assert_not_called()
        saved.assert_not_called()
        configured.assert_not_called()
        self.assertNotIn("SYNTHETIC_PRIVATE_DETAIL", json.dumps(found, sort_keys=True))  # no exception text escapes

    def test_explicit_strata_intent_is_forwarded_to_the_selected_resolver(self):
        # Dispatch only: the real selected resolver would REFUSE scan_all=True; here both the intent and the resolver are
        # synthetic, so this proves the forwarding of the flag and the arguments, not any accepted scan or native call.
        intent = {"mode": "EXPLICIT_STRATA", "synthetic": True}
        sentinel = {"base_url": "http://127.0.0.1:59999/v1", "model": "synthetic-model", "match": "exact", "synthetic": True}
        explicit = {"model": "synthetic-model", "base_url": "http://127.0.0.1:59999/v1"}
        metadata_reader = Mock()
        catalog_reader, listeners = self.probes()
        with patch.object(endpoint, "selected_intent", return_value=intent) as selector, \
                patch.object(endpoint, "_resolve_selected", return_value=sentinel) as selected_resolver:
            found = endpoint.resolve("synthetic-want", "http://127.0.0.1:59999/v1", catalog_reader=catalog_reader,
                                    listeners=listeners, scan_all=True, explicit=explicit, metadata_reader=metadata_reader)
        self.assertIs(found, sentinel)  # the selected resolver's result is returned unchanged
        selector.assert_called_once_with(explicit)
        selected_resolver.assert_called_once_with(intent, explicit, metadata_reader, True, True)
        catalog_reader.assert_not_called()
        listeners.assert_not_called()


if __name__ == "__main__":
    unittest.main()
