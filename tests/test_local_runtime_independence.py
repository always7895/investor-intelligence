"""LOCAL_RUNTIME_INDEPENDENCE_V1 — actual-caller contract tests.

Drives the real GatewayHandler over loopback HTTP with an injected loopback
upstream stub (no model download/load). Enforces LOCAL_AI_ONLY=true,
PAID_INFERENCE_ALLOWED=false, CLOUD_AI_FALLBACK=false: proxy environment
disabled (TESTED against HTTP_PROXY/HTTPS_PROXY/ALL_PROXY), redirects
rejected, explicit degraded/fail-closed, capability evidence (not configured
requirements), decision backend thin client to the existing Mapika endpoint.
"""
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import v212_local_llm_gateway as v212  # noqa: E402
import v213_local_llm_gateway as gw  # noqa: E402
from v213_decision_backend_client import DecisionBackendClient, DeciderError  # noqa: E402

TEST_SECRET = "TEST_lriv1-test-shared-secret-0123456789"


class SocketGuard:
    """Test-owned socket guard (predicate-based; alias/registration safe).

    Rules:
      * PROTECTED ports (real services: 5000/8000/8001/8080) are ALWAYS
        denied — even if allow_port/allow_addr is called for them.
      * Owned ports (allow_port) authorize connections ONLY from loopback
        aliases: 127.0.0.1 / ::1 / localhost / 127.0.0.0/8, in any IPv4 or
        IPv6 sockaddr tuple form (normalized to (host, port)).
      * Non-loopback registration cannot authorize any external connection.
      * Every unexpected attempt is blocked AND counted independently (a
        caught exception never makes a blocked attempt pass silently).
    """

    PROTECTED_PORTS = frozenset({5000, 8000, 8001, 8080})

    def __init__(self):
        self.owned = set()
        self.blocked = []
        self._real_connect = None
        self._real_create = None

    @staticmethod
    def _normalize(address):
        """Normalize any sockaddr tuple form to (host, port)."""
        seq = tuple(address)
        if len(seq) >= 2:
            return seq[0], seq[1]
        return (seq[0] if seq else None), None

    @staticmethod
    def _host_is_loopback(host):
        if not isinstance(host, str):
            return False
        if host in ("127.0.0.1", "::1", "localhost"):
            return True
        try:
            import ipaddress
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    def allow_port(self, port):
        self.owned.add(int(port))

    def allow_addr(self, addr):
        """Only loopback addresses may be registered; external tuples are
        inert (cannot authorize external connections)."""
        host, port = self._normalize(addr)
        if port is None or not self._host_is_loopback(host):
            return
        self.owned.add(int(port))

    def _predicate(self, address):
        host, port = self._normalize(address)
        if port is None:
            return False, "malformed"
        if int(port) in self.PROTECTED_PORTS:
            return False, "protected_port"
        if int(port) in self.owned and self._host_is_loopback(host):
            return True, "owned_loopback"
        return False, "non_owned_or_non_loopback"

    def _deny(self, address, reason):
        # EVERY blocked out-of-fixture connection is counted exactly once
        # (including protected ports) BEFORE raising — a caught exception
        # must never hide a wrong mock/real-service attempt.
        self.blocked.append((reason, address))
        raise RuntimeError("TEST_GUARD_NON_FIXTURE_CONNECT_BLOCKED")

    def start(self):
        import socket as _s
        if self._real_connect is not None:
            return self
        self._real_connect = _s.socket.connect
        self._real_create = _s.create_connection
        guard = self

        def connect(self_, address, *a, **kw):
            ok, reason = guard._predicate(address)
            if not ok:
                guard._deny(address, reason)
            return guard._real_connect(self_, address, *a, **kw)

        def create_connection(address, timeout=..., *a, **kw):
            ok, reason = guard._predicate(address)
            if not ok:
                guard._deny(address, reason)
            return guard._real_create(address, timeout, *a, **kw)

        _s.socket.connect = connect
        _s.create_connection = create_connection
        return self

    def stop(self):
        import socket as _s
        if self._real_connect is not None:
            _s.socket.connect = self._real_connect
            _s.create_connection = self._real_create
            self._real_connect = None
            self._real_create = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()
        return False


class _Stub(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/health":
            body = b'{"ok": true}'
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path in ("/model", "/v1/model"):
            b = self.server.behavior
            if b.get("no_context"):
                card = {"id": b["model"], "object": "model", "parameters": None}
            else:
                card = {"id": b["model"], "object": "model",
                        "parameters": {"max_seq_len": b.get("max_seq_len", 262144)}}
            body = json.dumps(card).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/v1/models":
            served = self.server.behavior.get("catalog_model", self.server.behavior["model"])
            if self.server.behavior.get("no_context"):
                rows = [{"id": served}]
            else:
                rows = [{"id": served, "context_length": 262144}]
            body = json.dumps({"data": rows}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.send_header("content-length", "0")
            self.end_headers()

    def do_POST(self):
        self.server.calls.append(self.path)
        length = int(self.headers.get("content-length", "0") or "0")
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode())
        except ValueError:
            payload = {}
        if self.path == "/v1/systemone":
            b = self.server.behavior
            choice = b.get("decider_choice", "SUFFICIENT")
            confidence = b.get("decider_confidence", 0.9)
            if b.get("malformed_vector"):
                probs = {"SUFFICIENT": 0.5, "NOT_SUFFICIENT": 0.3}  # unnormalized
            else:
                other = "NOT_SUFFICIENT" if choice == "SUFFICIENT" else "SUFFICIENT"
                probs = {choice: confidence, other: round(1.0 - confidence, 4)}
            body = json.dumps({"model": "decider", "answers": {
                "Source evidence sufficiency for answering?": {
                    "type": "choice", "choice": choice, "confidence": confidence,
                    "certainty": confidence,
                    "probabilities": probs,
                }}}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        is_probe = (isinstance(payload, dict)
                    and payload.get("response_format") == {"type": "json_object"}
                    and payload.get("messages") == [{"role": "user", "content": gw.CAPABILITY_PROBE_PROMPT}])
        if not is_probe:
            self.server.product_calls.append(self.path)
        if not is_probe and self.server.behavior.get("invalid_json"):
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", "4")
            self.end_headers()
            self.wfile.write(b"null")
            return
        if not is_probe and self.server.behavior.get("wrong_model"):
            body = json.dumps({"model": "other-model", "choices": [
                {"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}]}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if is_probe:
            content = "{\"probe\": true}" if not self.server.behavior.get("bad_structured") else "not json"
            body = json.dumps({"model": self.server.behavior["model"], "choices": [
                {"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}]}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.server.behavior.get("redirect"):
            self.send_response(302)
            self.send_header("Location", "https://cloud.example/v1/chat/completions")
            self.send_header("content-length", "0")
            self.end_headers()
            return
        body = json.dumps({"model": self.server.behavior["model"], "choices": [
            {"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}]}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _port(server):
    return server.server_address[1]


def _profile_for(model):
    """A valid 7-field request profile (v213_model_profile.FIELDS) for a model.
    enable_thinking=False with reasoning_effort='none' satisfies the
    reasoning-conflict rule. Used to build a REAL valid compact request via
    the existing request-profile seam (no production validation weakened)."""
    return {
        "schema_version": 1,
        "model": model,
        "enable_thinking": False,
        "reasoning_effort": "none",
        "max_output_tokens": 160,
        "smoke_output_tokens": 32,
        "timeout_ms": 20000,
    }


class _LocalRuntimeBase(unittest.TestCase):
    def setUp(self):
        env = {
            "II_LLAMA_BASE_URL": "http://127.0.0.1:1",  # replaced after stub start
            "II_LOCAL_LLM_SHARED_SECRET": TEST_SECRET,
            "II_LOCAL_LLM_MODEL": "fixture-reasoner-v2",
            "II_GATEWAY_DISABLE_PUBLIC_ENRICHMENT_FOR_TEST": "1",
        }
        self._env = patch.dict(os.environ, env, clear=False)
        self._env.start()
        self.behavior = {"model": "fixture-reasoner-v2"}
        self.upstream = ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
        self.upstream.behavior = self.behavior
        self.upstream.calls = []
        self.upstream.product_calls = []
        threading.Thread(target=self.upstream.serve_forever, daemon=True).start()
        os.environ["II_LLAMA_BASE_URL"] = f"http://127.0.0.1:{_port(self.upstream)}"
        # Owned CPU decider stub on an owned port; the gateway is pointed at it
        # via a TEMPORARY actual LOCAL_AI_CONFIG_PATH config (real config copied,
        # hard flags preserved, only decision_router.base_url rewritten). No test
        # case may reach the real 8000.
        self.decider = ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
        self.decider.behavior = {"decider_choice": "SUFFICIENT"}
        self.decider.calls = []
        self.decider.product_calls = []
        threading.Thread(target=self.decider.serve_forever, daemon=True).start()
        self._tmpdir = tempfile.TemporaryDirectory()
        self._cfg_path = Path(self._tmpdir.name) / "local-runtime-independence-v1.json"
        _real_cfg = json.loads(
            (SCRIPTS.parent / "config" / "local-runtime-independence-v1.json").read_text(encoding="utf-8-sig"))
        _real_cfg["decision_router"]["base_url"] = f"http://127.0.0.1:{_port(self.decider)}"
        _real_cfg["decision_router"]["retired"] = False  # these cases exercise the decider path explicitly
        self._cfg_path.write_text(json.dumps(_real_cfg), encoding="utf-8")
        self._cfg_patch = patch.object(gw, "LOCAL_AI_CONFIG_PATH", self._cfg_path)
        self._cfg_patch.start()
        gw._DECIDER_CLIENT = None
        self.gateway = ThreadingHTTPServer(("127.0.0.1", 0), gw.V213GatewayHandler)
        threading.Thread(target=self.gateway.serve_forever, daemon=True).start()
        self.gw_url = f"http://127.0.0.1:{_port(self.gateway)}"

    def tearDown(self):
        self.gateway.shutdown()
        self.gateway.server_close()
        self.decider.shutdown()
        self.decider.server_close()
        self.upstream.shutdown()
        self.upstream.server_close()
        self._cfg_patch.stop()
        gw._DECIDER_CLIENT = None
        self._tmpdir.cleanup()
        self._env.stop()

    def chat(self, model=None, secret=TEST_SECRET, mode=None, profile=None):
        import urllib.request
        payload = {"model": model or self.behavior["model"],
                   "messages": [{"role": "user", "content": "ABCD 評分"}]}
        if mode is not None:
            payload["ii_context_mode"] = mode
            payload["messages"] = [{"role": "user", "content": "Reply exactly R75_FREE_RELAY_E2E_OK"}]
            if profile is not None:
                payload["ii_model_profile"] = profile
                os.environ["V213_MODEL_PROFILE_JSON"] = json.dumps(profile)
        req = urllib.request.Request(
            self.gw_url + "/v1/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"content-type": "application/json", "x-investor-shared-secret": secret},
            method="POST",
        )
        try:
            # Control client: explicit no-proxy opener so the test's own
            # request goes DIRECT to the gateway (the global urllib opener
            # cache would otherwise honor the proxy env). The proxy env stays
            # set so the actual AI-request transport (trust_env=False) is
            # still exercised on the gateway side.
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode() or "{}")


class A_CloudBlockedLocalReasonerTests(_LocalRuntimeBase):
    def test_product_success_with_proxy_env_set_and_no_cloud_creds(self):
        # Proxy env points at a dead endpoint; trust_env=False must make the
        # loopback call direct. No cloud AI credentials exist anywhere.
        dead = ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
        dead.behavior = {"model": "dead-proxy-trap"}
        dead.calls = []
        threading.Thread(target=dead.serve_forever, daemon=True).start()
        proxy = f"http://127.0.0.1:{_port(dead)}"
        try:
            with SocketGuard() as guard:
                guard.allow_port(_port(self.upstream))
                guard.allow_port(_port(dead))
                guard.allow_port(_port(self.gateway))
                guard.allow_port(_port(self.decider))
                with patch.dict(os.environ, {"HTTP_PROXY": proxy, "HTTPS_PROXY": proxy, "ALL_PROXY": proxy}):
                    status, body = self.chat()
                self.assertEqual(status, 200)
                self.assertEqual(body["model"], self.behavior["model"])
                self.assertIn("/v1/chat/completions", self.upstream.calls)
                report = gw.capability_report(self.behavior["model"])
                self.assertEqual(report["capability"], "READY")
                self.assertEqual(report["context"], 262144)
                self.assertTrue(report["structured_json"])
            self.assertEqual(guard.blocked, [])
            # Zero calls to the dead proxy trap: no unexpected proxy access
            # (the trap records any request it receives; not swallowed).
            self.assertEqual(dead.calls, [])
        finally:
            dead.shutdown()
            dead.server_close()

    def test_no_secret_is_auth_negative_only(self):
        status, _ = self.chat(secret="")
        self.assertEqual(status, 401)

    def test_redirect_escape_refused(self):
        self.behavior["redirect"] = True
        status, body = self.chat()
        self.assertEqual(status, 502)
        self.assertEqual(body.get("error"), "LOOPBACK_REDIRECT_REFUSED")


class B_LocalOperationalTests(_LocalRuntimeBase):
    def test_reasoner_decider_and_failed_state_caller_operational(self):
        class FakeDecider:
            def answer(self, state, question, options):
                return "SUFFICIENT", 0.91

        ok = lambda source: v212.SourceResult(source, True, "2026-08-31T00:00:00Z", {"ok": True})
        os.environ.pop("II_GATEWAY_DISABLE_PUBLIC_ENRICHMENT_FOR_TEST", None)
        with patch.object(gw, "_DECIDER_CLIENT", FakeDecider()), \
             patch.object(v212, "collect_sec", return_value=ok("sec_edgar")), \
             patch.object(v212, "collect_yahoo", return_value=ok("yahoo_finance_public_unofficial")), \
             patch.object(v212, "collect_gleif", return_value=ok("gleif_lei")), \
             patch.object(v212, "collect_bls", return_value=ok("bls_public_data")), \
             patch.object(v212, "collect_world_bank", return_value=ok("world_bank_indicators")):
            status, body = self.chat()
        self.assertEqual(status, 200)
        self.assertEqual(body["ii_decision"], {
            "sufficiency": "SUFFICIENT", "confidence": 0.91,
            "authority": "decider_plus_source_qualification", "decider": "OK",
        })
        # Zero cloud calls: only the loopback upstream stub was contacted.
        # One required structured-JSON probe + one product completion.
        self.assertEqual(len(self.upstream.calls), 2)
        self.assertEqual(len(self.upstream.product_calls), 1)
        self.assertTrue(self.upstream.calls[0].endswith("/v1/chat/completions"))
        self.assertEqual(body["choices"][0]["message"]["content"], "ok")

    def test_failed_source_state_authoritative_decider_not_consulted(self):
        class ConsultingDecider:
            def answer(self, state, question, options):
                raise AssertionError("decider must not be consulted for failed evidence")

        with patch.object(gw, "_DECIDER_CLIENT", ConsultingDecider()):
            decision = gw._decision_seam(
                {"source_diversity_status": "CONFLICTED", "successful_source_families": ["a", "b"]},
                self.behavior["model"],
            )
        self.assertEqual(decision["sufficiency"], "NOT_SUFFICIENT")
        self.assertEqual(decision["authority"], "source_qualification")
        self.assertEqual(decision["decider"], "NOT_CONSULTED")


class C_D_AlternateIdentityTests(_LocalRuntimeBase):
    def test_alternate_reasoner_identity_via_config_only(self):
        self.behavior["model"] = "fixture-reasoner-alt-q5"
        os.environ["II_LOCAL_LLM_MODEL"] = "fixture-reasoner-alt-q5"
        status, body = self.chat()
        self.assertEqual(status, 200)
        self.assertEqual(body["model"], "fixture-reasoner-alt-q5")
        # Same business code; model label is diagnostic/selection only.
        self.assertEqual(gw.capability_report("fixture-reasoner-alt-q5")["capability"], "READY")

    def test_alternate_decider_identity_via_config_drives_actual_http(self):
        # Config-swapped decider endpoint + identity driving the ACTUAL
        # gateway HTTP path (legacy lane) and the compact lane; the decider
        # stub captures the canonical request.
        ok = lambda source: v212.SourceResult(source, True, "2026-08-31T00:00:00Z", {"ok": True})
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {"schema_version": 1, "LOCAL_AI_ONLY": True, "PAID_INFERENCE_ALLOWED": False,
                   "CLOUD_AI_FALLBACK": False,
                   "primary_reasoner": {"base_url": f"http://127.0.0.1:{_port(self.upstream)}/v1",
                                        "model": self.behavior["model"]},
                   "decision_router": {"base_url": f"http://127.0.0.1:{_port(self.upstream)}",
                                       "model": "fixture-decider-alt-v9"},
                   "capability_requirements": {"min_context": 32768, "min_decision_confidence": 0.70,
                                               "structured_json": True,
                                               "timeout_ms": 20000, "format_as_used": "openai_chat_completions"}}
            cfg_file = Path(tmp) / "config.json"
            cfg_file.write_text(json.dumps(cfg), encoding="utf-8")
            os.environ.pop("II_GATEWAY_DISABLE_PUBLIC_ENRICHMENT_FOR_TEST", None)
            with patch.object(gw, "LOCAL_AI_CONFIG_PATH", cfg_file), \
                 patch.object(gw, "_DECIDER_CLIENT", None), \
                 patch.object(v212, "collect_sec", return_value=ok("sec_edgar")), \
                 patch.object(v212, "collect_yahoo", return_value=ok("yahoo_finance_public_unofficial")), \
                 patch.object(v212, "collect_gleif", return_value=ok("gleif_lei")), \
                 patch.object(v212, "collect_bls", return_value=ok("bls_public_data")), \
                 patch.object(v212, "collect_world_bank", return_value=ok("world_bank_indicators")):
                # Legacy lane: decider approval via the swapped config endpoint.
                status, body = self.chat()
                self.assertEqual(status, 200)
                self.assertEqual(body["ii_decision"]["decider"], "OK")
                self.assertIn("/v1/systemone", self.upstream.calls)
                # Compact lane: approval + structured probe + completion.
                # Real valid compact request via the existing request-profile
                # seam (profile model == fixture-selected model); no production
                # compact validation weakened, no magic smoke bypass.
                status, body = self.chat(mode="transport_smoke_v1",
                                         profile=_profile_for(self.behavior["model"]))
                self.assertEqual(status, 200)

    def test_alternate_decider_identity_via_config_only(self):
        # The decider endpoint identity is config-supplied; the client contract
        # (fixed choice/confidence envelope) is identity-agnostic.
        client = DecisionBackendClient("http://127.0.0.1:8000")
        self.assertEqual(client.base_url, "http://127.0.0.1:8000")
        with self.assertRaises(DeciderError):
            DecisionBackendClient("https://decider.example:8000")


class E_FailClosedNegativesTests(_LocalRuntimeBase):
    def test_missing_context_evidence_is_capability_unknown(self):
        self.behavior["no_context"] = True
        report = gw.capability_report(self.behavior["model"])
        self.assertIsNone(report["context"])
        self.assertEqual(report["capability"], "CAPABILITY_UNKNOWN")

    def test_catalog_identity_missing_fails_closed(self):
        self.behavior["model"] = "served-model-x"
        self.behavior["catalog_model"] = "another-served-model"
        os.environ["II_LOCAL_LLM_MODEL"] = "served-model-x"
        status, body = self.chat(model="served-model-x")
        self.assertEqual(status, 503)
        self.assertEqual(body.get("error"), "MODEL_CATALOG_IDENTITY_UNAVAILABLE")

    def test_invalid_hard_flags_fail_closed(self):
        bad = {"LOCAL_AI_ONLY": False, "PAID_INFERENCE_ALLOWED": False, "CLOUD_AI_FALLBACK": False}
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            bad_file = Path(tmp) / "bad.json"
            bad_file.write_text(json.dumps(bad), encoding="utf-8")
            with patch.object(gw, "LOCAL_AI_CONFIG_PATH", bad_file):
                with self.assertRaises(SystemExit):
                    gw._load_local_ai_config()

    def test_decision_envelope_strict_negatives(self):
        # Pure envelope validation via the transport seam: the canned
        # response is returned by a patched _post, so NO socket is opened
        # and the real decider endpoint is never contacted.
        client = DecisionBackendClient("http://127.0.0.1:8000")
        cases = [
            {"choice": "MAYBE", "confidence": 0.5, "probabilities": {}},                       # unknown choice
            {"choice": "SUFFICIENT", "confidence": 1.5, "probabilities": {}},                   # out of range
            {"choice": "SUFFICIENT", "confidence": float("nan"), "probabilities": {}},          # NaN
            {"choice": "SUFFICIENT", "confidence": True, "probabilities": {}},                  # bool
            {"choice": "SUFFICIENT", "probabilities": {}},                                      # missing confidence
            {"choice": "SUFFICIENT", "confidence": 0.5},                                        # missing probabilities
            # Probabilities-vector negatives (valid choice + confidence >= 0.70,
            # malformed vector): empty / wrong keys / bool / non-numeric / NaN /
            # inf / out-of-range / unnormalized / choice-confidence mismatch.
            {"choice": "SUFFICIENT", "confidence": 0.7, "probabilities": {}},
            {"choice": "SUFFICIENT", "confidence": 0.7, "probabilities": {"SUFFICIENT": 0.7, "WRONG": 0.3}},
            {"choice": "SUFFICIENT", "confidence": 0.7, "probabilities": {"SUFFICIENT": True, "NOT_SUFFICIENT": False}},
            {"choice": "SUFFICIENT", "confidence": 0.7, "probabilities": {"SUFFICIENT": "0.7", "NOT_SUFFICIENT": "0.3"}},
            {"choice": "SUFFICIENT", "confidence": 0.7, "probabilities": {"SUFFICIENT": float("nan"), "NOT_SUFFICIENT": 0.3}},
            {"choice": "SUFFICIENT", "confidence": 0.7, "probabilities": {"SUFFICIENT": float("inf"), "NOT_SUFFICIENT": 0.3}},
            {"choice": "SUFFICIENT", "confidence": 0.7, "probabilities": {"SUFFICIENT": 1.5, "NOT_SUFFICIENT": -0.5}},
            {"choice": "SUFFICIENT", "confidence": 0.7, "probabilities": {"SUFFICIENT": 0.5, "NOT_SUFFICIENT": 0.3}},
            {"choice": "SUFFICIENT", "confidence": 0.7, "probabilities": {"SUFFICIENT": 0.5, "NOT_SUFFICIENT": 0.5}},
        ]
        with SocketGuard() as guard:
            for entry in cases:
                with patch.object(client, "_post", return_value={"model": "m", "answers": {"q?": entry}}):
                    with self.assertRaises(DeciderError, msg=repr(entry)):
                        client.answer("state", "q?", ["SUFFICIENT", "NOT_SUFFICIENT"])
        self.assertEqual(guard.blocked, [])

    def test_v212_legacy_upstream_redirect_refused(self):
        self.behavior["redirect"] = True
        handler_url = f"http://127.0.0.1:{_port(self.upstream)}"
        import urllib.request
        # Drive the v212 handler directly (its own server would need a secret
        # too; the transport seam is what is under test).
        server = ThreadingHTTPServer(("127.0.0.1", 0), v212.GatewayHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        ok = lambda source: v212.SourceResult(source, True, "2026-08-31T00:00:00Z", {"ok": True})
        try:
            with patch.object(v212, "collect_sec", return_value=ok("sec_edgar")), \
                 patch.object(v212, "collect_yahoo", return_value=ok("yahoo_finance_public_unofficial")), \
                 patch.object(v212, "collect_gleif", return_value=ok("gleif_lei")), \
                 patch.object(v212, "collect_bls", return_value=ok("bls_public_data")), \
                 patch.object(v212, "collect_world_bank", return_value=ok("world_bank_indicators")), \
                 patch.dict(os.environ, {"II_LLAMA_BASE_URL": handler_url}):
                r = urllib.request.Request(
                    f"http://127.0.0.1:{_port(server)}/v1/chat/completions",
                    data=json.dumps({"model": "m", "messages": [{"role": "user", "content": "x"}]}).encode(),
                    headers={"content-type": "application/json", "x-investor-shared-secret": TEST_SECRET},
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(r, timeout=10) as resp:
                        status, body = resp.status, json.loads(resp.read().decode())
                except urllib.error.HTTPError as exc:
                    status, body = exc.code, json.loads(exc.read().decode() or "{}")
            self.assertEqual(status, 502)
            self.assertEqual(body.get("error"), "UPSTREAM_LOOPBACK_REFUSED")
        finally:
            server.shutdown()
            server.server_close()


class F_ReviewGapClosureTests(_LocalRuntimeBase):
    def test_hard_flags_reject_numeric_one_zero(self):
        import tempfile
        for bad in ({"LOCAL_AI_ONLY": 1, "PAID_INFERENCE_ALLOWED": 0, "CLOUD_AI_FALLBACK": 0},
                    {"LOCAL_AI_ONLY": True, "PAID_INFERENCE_ALLOWED": 0, "CLOUD_AI_FALLBACK": False}):
            with tempfile.TemporaryDirectory() as tmp:
                bad_file = Path(tmp) / "bad.json"
                bad_file.write_text(json.dumps(bad), encoding="utf-8")
                with patch.object(gw, "LOCAL_AI_CONFIG_PATH", bad_file):
                    with self.assertRaises(SystemExit):
                        gw._load_local_ai_config()

    def test_reasoner_config_identity_drives_actual_gateway_request(self):
        # Owned temporary config fixture at an ephemeral fixture port proves
        # the config drives the actual GatewayHandler request (never binds
        # the real 5000).
        os.environ.pop("II_LLAMA_BASE_URL", None)
        os.environ.pop("II_LOCAL_LLM_MODEL", None)
        stub = ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
        stub.behavior = {"model": "fixture-config-model"}
        stub.calls = []
        stub.product_calls = []
        threading.Thread(target=stub.serve_forever, daemon=True).start()
        try:
            import tempfile
            with tempfile.TemporaryDirectory() as tmp:
                cfg = {"schema_version": 1, "LOCAL_AI_ONLY": True, "PAID_INFERENCE_ALLOWED": False,
                       "CLOUD_AI_FALLBACK": False,
                       "primary_reasoner": {"base_url": f"http://127.0.0.1:{_port(stub)}/v1",
                                            "model": "fixture-config-model"},
                       "decision_router": {"base_url": f"http://127.0.0.1:{_port(self.decider)}", "model": "Mapika-decider-2b-v9"},
                       "capability_requirements": {"min_context": 32768, "min_decision_confidence": 0.70,
                                                   "structured_json": True,
                                                   "timeout_ms": 20000, "format_as_used": "openai_chat_completions"}}
                cfg_file = Path(tmp) / "config.json"
                cfg_file.write_text(json.dumps(cfg), encoding="utf-8")
                with patch.object(gw, "LOCAL_AI_CONFIG_PATH", cfg_file):
                    self.assertEqual(gw.local_llm_base_url(), f"http://127.0.0.1:{_port(stub)}/v1")
                    self.assertEqual(gw.selected_model_id(), "fixture-config-model")
                    status, body = self.chat(model="fixture-config-model")
                    self.assertEqual(status, 200)
                    self.assertEqual(body["model"], "fixture-config-model")
                    self.assertTrue(stub.calls[0].endswith("/chat/completions"))
        finally:
            stub.shutdown()
            stub.server_close()

    def test_shipped_config_default_labels_exact_no_network(self):
        # Pure default-config assertion: the SHIPPED config carries the exact
        # local defaults (no networking, no binding). Read the real shipped
        # file directly (not the per-test patched LOCAL_AI_CONFIG_PATH).
        shipped = SCRIPTS.parent / "config" / "local-runtime-independence-v1.json"
        cfg = json.loads(shipped.read_text(encoding="utf-8-sig"))
        self.assertEqual(cfg["primary_reasoner"]["base_url"], "http://127.0.0.1:5000/v1")
        self.assertEqual(cfg["primary_reasoner"]["model"], "Qwen3.8-27B-EXL3-5.5bpw-v2")
        self.assertEqual(cfg["decision_router"]["model"], "Mapika-decider-2b-v9")
        self.assertEqual(cfg["decision_router"]["alias_diagnostic_only"], "decider-v8")

    def test_configured_env_precedence_overrides_config(self):
        os.environ["II_LOCAL_LLM_MODEL"] = "env-override-model"
        self.assertEqual(gw.selected_model_id(), "env-override-model")
        self.assertEqual(gw.local_llm_base_url(), f"http://127.0.0.1:{_port(self.upstream)}")

    def test_capability_evidence_from_served_metadata_api(self):
        self.behavior["model"] = "cap-model"
        os.environ["II_LOCAL_LLM_MODEL"] = "cap-model"
        # Actual missing-served-context negative: explicit no_context fixture
        # (card.parameters = null) on the shared stub => unknown, never guessed.
        self.behavior["no_context"] = True
        with patch.object(gw, "local_llm_base_url", return_value=f"http://127.0.0.1:{_port(self.upstream)}"):
            report = gw.capability_report("cap-model")
        self.assertIsNone(report["context"])
        self.assertEqual(report["capability"], "CAPABILITY_UNKNOWN")
        self.behavior["no_context"] = False
        # Served /model fixture: strict id match + int max_seq_len.
        srv = ThreadingHTTPServer(("127.0.0.1", 0), _ModelStub)
        srv.behavior = {"model": "cap-model", "max_seq_len": 262144}
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            with patch.dict(os.environ, {"II_CAPABILITY_METADATA_URL": f"http://127.0.0.1:{_port(srv)}/model"}):
                self.assertEqual(gw.capability_context_evidence("cap-model"), 262144)
            srv.behavior["model"] = "other-current"
            with patch.dict(os.environ, {"II_CAPABILITY_METADATA_URL": f"http://127.0.0.1:{_port(srv)}/model"}):
                self.assertIsNone(gw.capability_context_evidence("cap-model"))  # id mismatch
            srv.behavior["model"] = "cap-model"
            srv.behavior["max_seq_len"] = "262144"  # wrong type
            with patch.dict(os.environ, {"II_CAPABILITY_METADATA_URL": f"http://127.0.0.1:{_port(srv)}/model"}):
                self.assertIsNone(gw.capability_context_evidence("cap-model"))
        finally:
            srv.shutdown()
            srv.server_close()

    def test_structured_json_probe_proven_and_malformed_fails_closed(self):
        self.behavior["model"] = "struct-model"
        os.environ["II_LOCAL_LLM_MODEL"] = "struct-model"
        with patch.object(gw, "local_llm_base_url", return_value=f"http://127.0.0.1:{_port(self.upstream)}"):
            self.assertTrue(gw.structured_json_probe())
        self.behavior["bad_structured"] = True
        with patch.object(gw, "local_llm_base_url", return_value=f"http://127.0.0.1:{_port(self.upstream)}"):
            self.assertFalse(gw.structured_json_probe())

    def test_reasoner_unavailable_and_malformed_responses_fail_closed(self):
        # Unavailable endpoint = owned bound-then-closed ephemeral port.
        holder = ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
        closed_port = _port(holder)
        holder.server_close()
        with SocketGuard() as guard:
            guard.allow_port(closed_port)
            guard.allow_port(_port(self.gateway))
            guard.allow_port(_port(self.upstream))
            guard.allow_port(_port(self.decider))
            os.environ["II_LLAMA_BASE_URL"] = f"http://127.0.0.1:{closed_port}"
            status, body = self.chat()
            # Closed base: catalog admission fails closed BEFORE completion.
            self.assertEqual(status, 503)
            self.assertEqual(body.get("error"), "MODEL_CATALOG_IDENTITY_UNAVAILABLE")
            self.assertEqual(guard.blocked, [])
        os.environ["II_LLAMA_BASE_URL"] = f"http://127.0.0.1:{_port(self.upstream)}"
        self.behavior["invalid_json"] = True
        status, body = self.chat()
        self.assertEqual(status, 502)
        self.behavior["invalid_json"] = False
        self.behavior["wrong_model"] = True
        status, body = self.chat()
        self.assertEqual(status, 502)
        self.assertEqual(body.get("error"), "COMPACT_RESPONSE_INCOMPLETE_OR_MODEL_MISMATCH")
        self.behavior["wrong_model"] = False

    def test_decider_unavailable_is_explicit_degraded(self):
        class DownDecider:
            def answer(self, state, question, options):
                raise DeciderError("DECIDER_UPSTREAM_FAILED:503")

        with patch.object(gw, "_DECIDER_CLIENT", DownDecider()):
            decision = gw._decision_seam(
                {"source_diversity_status": "PASS", "successful_source_families": ["a", "b", "c"]},
                "m",
            )
        self.assertEqual(decision["decider"], "DEGRADED")
        self.assertEqual(decision["sufficiency"], "UNKNOWN")

    def test_v212_legacy_ai_transports_ignore_proxy_env(self):
        import urllib.request
        dead = ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
        dead.behavior = {"model": "x"}
        threading.Thread(target=dead.serve_forever, daemon=True).start()
        proxy = f"http://127.0.0.1:{_port(dead)}"
        server = ThreadingHTTPServer(("127.0.0.1", 0), v212.GatewayHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            ok = lambda source: v212.SourceResult(source, True, "2026-08-31T00:00:00Z", {"ok": True})
            with patch.object(v212, "collect_sec", return_value=ok("sec_edgar")), \
                 patch.object(v212, "collect_yahoo", return_value=ok("yahoo_finance_public_unofficial")), \
                 patch.object(v212, "collect_gleif", return_value=ok("gleif_lei")), \
                 patch.object(v212, "collect_bls", return_value=ok("bls_public_data")), \
                 patch.object(v212, "collect_world_bank", return_value=ok("world_bank_indicators")), \
                 patch.dict(os.environ, {"II_LLAMA_BASE_URL": f"http://127.0.0.1:{_port(self.upstream)}",
                                         "HTTP_PROXY": proxy, "HTTPS_PROXY": proxy, "ALL_PROXY": proxy}):
                health = urllib.request.urlopen(f"http://127.0.0.1:{_port(server)}/health", timeout=10)
                self.assertEqual(health.status, 200)
                self.assertTrue(json.loads(health.read().decode())["llama_reachable"])
                r = urllib.request.Request(
                    f"http://127.0.0.1:{_port(server)}/v1/chat/completions",
                    data=json.dumps({"model": self.behavior["model"],
                                     "messages": [{"role": "user", "content": "x"}]}).encode(),
                    headers={"content-type": "application/json", "x-investor-shared-secret": TEST_SECRET},
                    method="POST",
                )
                with urllib.request.urlopen(r, timeout=10) as resp:
                    self.assertEqual(resp.status, 200)
                    self.assertEqual(json.loads(resp.read().decode())["model"], self.behavior["model"])
        finally:
            server.shutdown()
            server.server_close()
            dead.shutdown()
            dead.server_close()


class G_PreGenerationGateTests(_LocalRuntimeBase):
    """Actual-caller negatives for the pre-generation decision/capability
    gates: every denial must be explicit non-200 with ZERO reasoner product
    completion. Hermetic owned ports + guard counter."""

    def _no_product_completion(self, before):
        self.assertEqual(len(self.upstream.calls), before)

    def test_decider_not_sufficient_denies_before_completion(self):
        # Set the ACTUAL owned decider response choice (not the reasoner
        # behavior); keep 503 and zero reasoner calls.
        self.decider.behavior["decider_choice"] = "NOT_SUFFICIENT"
        before = len(self.upstream.calls)
        status, body = self.chat()
        self.assertEqual(status, 503)
        self.assertEqual(body.get("error"), "REASONER_DECISION_DENIED")
        self.assertEqual(body.get("sufficiency"), "NOT_SUFFICIENT")
        self._no_product_completion(before)

    def test_low_confidence_below_minimum_denies_no_reasoner_calls(self):
        # Boundary: 0.69 < 0.70 declared minimum => denied locally, no
        # reasoner product/probe calls (never Astra).
        self.decider.behavior["decider_confidence"] = 0.69
        before = len(self.upstream.calls)
        status, body = self.chat()
        self.assertEqual(status, 503)
        self.assertEqual(body.get("error"), "REASONER_DECISION_DENIED")
        self._no_product_completion(before)

    def test_confidence_at_minimum_permitted_with_valid_fixture(self):
        # Boundary: 0.70 == 0.70 declared minimum => permitted with otherwise
        # valid fixtures (product success).
        self.decider.behavior["decider_confidence"] = 0.70
        status, body = self.chat()
        self.assertEqual(status, 200)
        self.assertEqual(body["model"], self.behavior["model"])

    def test_single_cpu_call_and_annotation_matches_admitted(self):
        # Exactly ONE decider (CPU) call for the pre-generation gate; the
        # annotation derives from that same gate (no CPU re-query after
        # generation) and matches the admitted result.
        status, body = self.chat()
        self.assertEqual(status, 200)
        self.assertEqual(self.decider.calls, ["/v1/systemone"])
        self.assertEqual(body["ii_decision"]["decider"], "OK")
        self.assertEqual(body["ii_decision"]["sufficiency"], "SUFFICIENT")

    def test_malformed_decider_vector_denies_before_reasoner(self):
        # A malformed decider probability vector must deny (503) BEFORE any
        # reasoner probe/product call (fail closed, no healthy default).
        self.decider.behavior["malformed_vector"] = True
        status, body = self.chat()
        self.assertEqual(status, 503)
        self.assertEqual(body.get("error"), "REASONER_DECISION_DENIED")
        self.assertEqual(self.upstream.calls, [])
        self.assertEqual(self.upstream.product_calls, [])

    def test_decider_unavailable_denies_before_completion(self):
        holder = ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
        closed_port = _port(holder)
        holder.server_close()
        before = len(self.upstream.calls)
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            cfg = json.loads(gw.LOCAL_AI_CONFIG_PATH.read_text(encoding="utf-8-sig"))
            cfg["decision_router"]["base_url"] = f"http://127.0.0.1:{closed_port}"
            cfg_file = Path(tmp) / "config.json"
            cfg_file.write_text(json.dumps(cfg), encoding="utf-8")
            with patch.object(gw, "LOCAL_AI_CONFIG_PATH", cfg_file), \
                 patch.object(gw, "_DECIDER_CLIENT", None):
                status, body = self.chat()
        self.assertEqual(status, 503)
        self.assertEqual(body.get("error"), "REASONER_DECISION_DENIED")
        self.assertEqual(body.get("authority"), "decider_unavailable")
        self._no_product_completion(before)

    def test_failed_source_evidence_denies_without_consulting_decider(self):
        class ConsultingDecider:
            def answer(self, state, question, options):
                raise AssertionError("decider must not be consulted for failed evidence")

        ok = lambda source: v212.SourceResult(source, True, "2026-08-31T00:00:00Z", {"ok": True})
        before = len(self.upstream.calls)
        os.environ.pop("II_GATEWAY_DISABLE_PUBLIC_ENRICHMENT_FOR_TEST", None)
        # Capture the ORIGINAL build_source_context BEFORE patching so the
        # callback calls the real one exactly once (no recursion into the
        # patched version), then forces CONFLICTED.
        original_build_source_context = v212.build_source_context
        with patch.object(gw, "_DECIDER_CLIENT", ConsultingDecider()), \
             patch.object(v212, "collect_sec", return_value=ok("sec_edgar")), \
             patch.object(v212, "collect_yahoo", return_value=ok("yahoo_finance_public_unofficial")), \
             patch.object(v212, "collect_gleif", return_value=ok("gleif_lei")), \
             patch.object(v212, "collect_bls", return_value=ok("bls_public_data")), \
             patch.object(v212, "collect_world_bank", return_value=ok("world_bank_indicators")):
            # Force a failed diversity status through the actual context.
            def _conflicted(*a, **kw):
                ctx = original_build_source_context(*a, **kw)
                ctx["source_diversity_status"] = "CONFLICTED"
                return ctx

            with patch.object(v212, "build_source_context", side_effect=_conflicted):
                status, body = self.chat()
        self.assertEqual(status, 503)
        self.assertEqual(body.get("error"), "REASONER_DECISION_DENIED")
        self.assertEqual(body.get("authority"), "source_qualification")
        self._no_product_completion(before)

    def test_missing_served_context_denies_before_completion(self):
        self.behavior["no_context"] = True
        before = len(self.upstream.calls)
        status, body = self.chat()
        self.assertEqual(status, 503)
        self.assertEqual(body.get("error"), "REASONER_CAPABILITY_CONTEXT_UNKNOWN")
        self.assertIsNone(body.get("observed_context"))
        self._no_product_completion(before)

    def test_malformed_structured_probe_denies_compact_lane(self):
        self.behavior["bad_structured"] = True
        # Real valid compact request via the request-profile seam so admission
        # passes and the request reaches the actual structured-JSON capability
        # gate (the bounded probe itself is expected to run; the product
        # completion must not).
        status, body = self.chat(mode="transport_smoke_v1",
                                 profile=_profile_for(self.behavior["model"]))
        self.assertEqual(status, 503)
        self.assertEqual(body.get("error"), "REASONER_CAPABILITY_STRUCTURED_JSON_UNSUPPORTED")
        # The probe was legitimately called, but ZERO product completions.
        self.assertEqual(self.upstream.product_calls, [])

    def test_malformed_structured_probe_denies_legacy_lane(self):
        # The required structured-JSON capability applies to BOTH lanes. A
        # malformed probe in the legacy (natural-prose) lane must deny with
        # the exact 503 and ZERO product completions (probe called, product
        # not). Decider approval already passed (pre-generation gate).
        self.behavior["bad_structured"] = True
        status, body = self.chat()
        self.assertEqual(status, 503)
        self.assertEqual(body.get("error"), "REASONER_CAPABILITY_STRUCTURED_JSON_UNSUPPORTED")
        # The probe was legitimately called, but ZERO product completions.
        self.assertEqual(self.upstream.product_calls, [])

    def test_reasoner_unavailable_after_valid_capability(self):
        holder = ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
        closed_port = _port(holder)
        holder.server_close()
        before = len(self.upstream.calls)
        with SocketGuard() as guard:
            guard.allow_port(closed_port)
            guard.allow_port(_port(self.gateway))
            guard.allow_port(_port(self.upstream))
            guard.allow_port(_port(self.decider))
            os.environ["II_LLAMA_BASE_URL"] = f"http://127.0.0.1:{closed_port}"
            status, body = self.chat()
            self.assertEqual(guard.blocked, [])
        self.assertEqual(status, 503)
        self.assertEqual(body.get("error"), "MODEL_CATALOG_IDENTITY_UNAVAILABLE")
        self._no_product_completion(before)

    def test_missing_decision_confidence_minimum_fails_closed(self):
        # A config missing the mandatory min_decision_confidence must fail
        # closed (503 REASONER_DECISION_DENIED), never default-healthy.
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {"schema_version": 1, "LOCAL_AI_ONLY": True, "PAID_INFERENCE_ALLOWED": False,
                   "CLOUD_AI_FALLBACK": False,
                   "primary_reasoner": {"base_url": f"http://127.0.0.1:{_port(self.upstream)}/v1",
                                        "model": self.behavior["model"]},
                   "decision_router": {"base_url": f"http://127.0.0.1:{_port(self.decider)}",
                                       "model": "Mapika-decider-2b-v9"},
                   "capability_requirements": {"min_context": 32768, "structured_json": True,
                                               "timeout_ms": 20000, "format_as_used": "openai_chat_completions"}}
            cfg_file = Path(tmp) / "config.json"
            cfg_file.write_text(json.dumps(cfg), encoding="utf-8")
            with patch.object(gw, "LOCAL_AI_CONFIG_PATH", cfg_file), \
                 patch.object(gw, "_DECIDER_CLIENT", None):
                status, body = self.chat()
        self.assertEqual(status, 503)
        self.assertEqual(body.get("error"), "REASONER_DECISION_DENIED")


class _ModelStub(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        b = self.server.behavior
        params = {"max_seq_len": b["max_seq_len"]}
        body = json.dumps({"id": b["model"], "object": "model", "parameters": params}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _unused():
    pass


if __name__ == "__main__":
    unittest.main()