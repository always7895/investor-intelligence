"""Local model auto-detection (operator 2026-09-26: the local model's port and ID change). No network: catalogs and
listeners are injected, the saved selection and configuration are patched."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import local_model_endpoint as endpoint  # noqa: E402

PINNED = "Qwen3.8-27B-EXL3-5.5bpw-v2"


def rows(*ids, aliases=None):
    return [{"id": ident, "aliases": list((aliases or {}).get(ident, []))} for ident in ids]


class ResolveTests(unittest.TestCase):
    def setUp(self):
        self.probed = []
        stack = [patch.object(endpoint, "saved_selection", return_value={"model": "", "base": ""}),
                 patch.object(endpoint, "configured_reasoner", return_value={"model": PINNED, "base": "http://127.0.0.1:5000/v1"}),
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
        servers = {"http://127.0.0.1:5000": rows("Qwen3.8-27B-UD-Q5"), "http://127.0.0.1:8080": rows(PINNED)}
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
        servers = {"http://127.0.0.1:5000": rows("canonical-x", aliases={"canonical-x": [PINNED]})}
        found = endpoint.resolve(catalog_reader=self.reader(servers), listeners=lambda: [])
        self.assertEqual((found["model"], found["match"]), ("canonical-x", "exact"))
        many = {"http://127.0.0.1:5000": rows("gemma4", "llama-70B")}
        self.assertEqual(endpoint.resolve(catalog_reader=self.reader(many), listeners=lambda: [])["error"], "LOCAL_MODEL_AMBIGUOUS")
        self.assertEqual(endpoint.resolve(catalog_reader=self.reader({}), listeners=lambda: [])["error"], "LOCAL_MODEL_NOT_FOUND")

    def test_want_and_base_are_tried_first_and_only_loopback_is_probed(self):
        servers = {"http://127.0.0.1:7777": rows("mine-8B")}
        found = endpoint.resolve("mine-8B", "http://localhost:7777/v1", catalog_reader=self.reader(servers), listeners=lambda: [])
        self.assertEqual((found["base_url"], found["match"]), ("http://127.0.0.1:7777", "exact"))
        self.assertEqual(self.probed[0], "http://127.0.0.1:7777")
        for bad in ("https://127.0.0.1:5000", "http://example.com:5000", "http://user@127.0.0.1:5000", "http://127.0.0.1:8000",
                    "http://127.0.0.1:5000/x", "http://127.0.0.1:5000?k=1"):
            self.assertIsNone(endpoint.loopback_base(bad), bad)

    def test_the_only_model_is_offered_last_and_the_listener_scan_is_capped(self):
        servers = {"http://127.0.0.1:5000": rows("gemma4"), "http://127.0.0.1:9001": rows("Qwen3.8-27B")}
        found = endpoint.resolve(catalog_reader=self.reader(servers), listeners=lambda: list(range(9001, 9101)))
        self.assertEqual((found["base_url"], found["match"]), ("http://127.0.0.1:9001", "family"))  # family beats an earlier only
        found = endpoint.resolve(catalog_reader=self.reader({"http://127.0.0.1:5000": rows("gemma4")}), listeners=lambda: [])
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


if __name__ == "__main__":
    unittest.main()
