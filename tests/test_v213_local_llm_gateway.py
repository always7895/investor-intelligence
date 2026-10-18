from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

SPEC = importlib.util.spec_from_file_location("v213_local_llm_gateway", SCRIPTS / "v213_local_llm_gateway.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class V213LocalGatewayFidelityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original = MODULE.ORIGINAL_ENRICH

        def fake_enrich(messages):
            user = next((str(item.get("content") or "") for item in reversed(messages) if item.get("role") == "user"), "")
            ticker = MODULE.base.extract_ticker(user)
            return ([{"role": "system", "content": "base rules"}] + [dict(item) for item in messages], {
                "ticker": ticker,
                "successful_source_families": ["sec_edgar", "yahoo_finance_public_unofficial", "gleif_lei"],
                "source_diversity_status": "PASS",
            })

        MODULE.ORIGINAL_ENRICH = fake_enrich

    def tearDown(self) -> None:
        MODULE.ORIGINAL_ENRICH = self.original

    def test_stock_question_injects_public_logic_fidelity(self) -> None:
        enriched, context = MODULE.enrich_messages([{"role": "user", "content": "AXTI 怎麼看"}])
        system = enriched[0]["content"]
        self.assertIn("SERENITY PUBLIC-LOGIC HIGH-FIDELITY RECONSTRUCTION", system)
        self.assertIn("legacy deterministic score", system)
        self.assertIn("Evidence-bound dependency graph", system)
        self.assertIn("company capture", system)
        self.assertIn("thesis killers", system)
        self.assertIn("public-logic reconstruction", system)
        self.assertEqual(context["serenity_public_logic_fidelity"], "2.1.3-source-independence-v3")
        self.assertFalse(context["private_process_reproduction_claimed"])
        self.assertFalse(context["official_serenity_formula_claimed"])
        self.assertEqual(context["model_confidence_cap"], "LIMITED")

    def test_methodology_question_injects_fidelity_even_without_ticker(self) -> None:
        enriched, context = MODULE.enrich_messages([{"role": "user", "content": "Serenity 的投資邏輯是什麼"}])
        self.assertIn("SERENITY PUBLIC-LOGIC HIGH-FIDELITY RECONSTRUCTION", enriched[0]["content"])
        self.assertEqual(context["legacy_quantitative_overlay_label"], "System operationalization score")

    def test_supply_chain_question_injects_fidelity_even_without_ticker(self) -> None:
        enriched, _ = MODULE.enrich_messages([{"role": "user", "content": "這個供應鏈瓶頸怎麼判斷"}])
        self.assertIn("SERENITY PUBLIC-LOGIC HIGH-FIDELITY RECONSTRUCTION", enriched[0]["content"])

    def test_leopold_is_context_only_and_does_not_certify_full_skill(self) -> None:
        enriched, context = MODULE.enrich_messages([{"role": "user", "content": "Leopold Aschenbrenner 的方法"}])
        self.assertIn("CONTEXT_ONLY", enriched[0]["content"])
        self.assertIn("6/12/24-month", enriched[0]["content"])
        self.assertIn("a filing/retrieval date is not delivery", enriched[0]["content"])
        proof = MODULE.methodology_execution_evidence(None, context)
        self.assertEqual(proof["lane"], "LEGACY_SYSTEM_DIRECTIVE")
        self.assertFalse(proof["full_skill_executed"])
        self.assertFalse(proof["model_adherence_verified"])
        self.assertEqual(proof["reference_files_loaded"], [])
        self.assertRegex(proof["directive_sha256"], r"^[a-f0-9]{64}$")
        self.assertEqual(proof["aschenbrenner_role"], "CONTEXT_ONLY")

    def test_compact_and_smoke_cannot_borrow_legacy_methodology_evidence(self) -> None:
        _, context = MODULE.enrich_messages([{"role": "user", "content": "Serenity"}])
        for mode, lane in (("compact_public_v1", "COMPACT_POLICY_ONLY"),
                           ("transport_smoke_v1", "TRANSPORT_SMOKE")):
            proof = MODULE.methodology_execution_evidence(mode, context)
            self.assertEqual(proof["lane"], lane)
            self.assertIsNone(proof["directive_sha256"])
            self.assertFalse(proof["full_skill_executed"])
            self.assertEqual(proof["reference_files_loaded"], [])
        self.assertEqual(MODULE.methodology_execution_evidence(None, {})["lane"], "NO_RESEARCH_ENRICHMENT")

    def test_non_stock_general_question_does_not_force_serenity_method(self) -> None:
        enriched, context = MODULE.enrich_messages([{"role": "user", "content": "你好"}])
        self.assertNotIn("SERENITY PUBLIC-LOGIC HIGH-FIDELITY RECONSTRUCTION", enriched[0]["content"])
        self.assertNotIn("serenity_public_logic_fidelity", context)

    def test_directive_forbids_false_official_score_and_unbound_signals(self) -> None:
        directive = MODULE.PUBLIC_LOGIC_DIRECTIVE
        self.assertIn("never as a Serenity score", directive)
        self.assertIn("named customer alone", directive)
        self.assertIn("evidence-bound graph edge", directive)
        self.assertIn("UNPROVEN/INSUFFICIENT_EVIDENCE", directive)
        self.assertIn("claim-relevant primary source", directive)
        self.assertIn("Company capture", directive)
        self.assertIn("independent corroboration", directive)
        self.assertIn("Conflicting sources", directive)
        self.assertIn("FRED is official macro context only", directive)


class LoopbackTransportIgnoresHostProxyTests(unittest.TestCase):
    """The startup model pin and the /health upstream check reach the loopback model server directly; a host proxy (env, or
    the Windows registry proxy that requests/urllib read) never receives them. Fake loopback servers, synthetic model id."""

    def setUp(self) -> None:
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        class Upstream(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                body = b'{"data": [{"id": "synthetic-model-a"}]}' if self.path == "/v1/models" else b'{"status": "ok"}'
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args) -> None:
                pass

        class Proxy(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                self.server.hits += 1
                self.send_response(502)
                self.send_header("content-length", "0")
                self.end_headers()

            def log_message(self, *args) -> None:
                pass

        self.servers = []
        for handler in (Upstream, Proxy):
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            server.hits = 0
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.servers.append(server)
        self.upstream, self.proxy = self.servers
        proxy = f"http://127.0.0.1:{self.proxy.server_port}"
        self.env = {"II_LLAMA_BASE_URL": f"http://127.0.0.1:{self.upstream.server_port}", "II_LOCAL_LLM_MODEL": "synthetic-model-a",
                    "HTTP_PROXY": proxy, "HTTPS_PROXY": proxy, "ALL_PROXY": proxy, "NO_PROXY": ""}

    def tearDown(self) -> None:
        for server in self.servers:
            server.shutdown()
            server.server_close()

    def test_startup_model_pin_reads_the_loopback_model_list_directly(self) -> None:
        import contextlib
        import io
        import os
        from unittest.mock import patch
        out = io.StringIO()
        with patch.dict(os.environ, self.env), contextlib.redirect_stdout(out):
            try:
                MODULE.verify_served_model("127.0.0.1", deadline_seconds=1.0)
            except SystemExit as exc:  # the gateway refuses to start: a failure of this row, not an error
                self.fail(f"startup model pin refused (exit {exc.code}): {out.getvalue().strip()[-200:]}")
        self.assertIn("V213_LOCAL_LLM_GATEWAY_MODEL_PIN = PASS", out.getvalue())
        self.assertEqual(self.proxy.hits, 0)

    def test_health_reaches_the_loopback_model_server_directly(self) -> None:
        import json
        import os
        import threading
        import urllib.request
        from http.server import ThreadingHTTPServer
        from unittest.mock import patch
        with patch.dict(os.environ, self.env), patch.object(MODULE, "_explicit_runtime", return_value=None),                 patch.object(MODULE, "_available_model_catalog", return_value=[{"id": "synthetic-model-a"}]),                 patch.object(MODULE, "_source_audit_health", return_value={}),                 patch.object(MODULE.V213GatewayHandler, "log_message", return_value=None):
            server = ThreadingHTTPServer(("127.0.0.1", 0), MODULE.V213GatewayHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # the test client itself goes direct
                with direct.open(f"http://127.0.0.1:{server.server_port}/health", timeout=10) as response:
                    health = json.load(response)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
        self.assertTrue(health["llama_reachable"])
        self.assertEqual(self.proxy.hits, 0)


if __name__ == "__main__":
    unittest.main()
