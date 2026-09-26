from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Shared probe prompt (matches v213_local_llm_gateway.CAPABILITY_PROBE_PROMPT);
# the bounded capability probe is distinguished by standard response_format +
# exact probe messages, never a bespoke test flag.
CAPABILITY_PROBE_PROMPT = "Respond with a JSON object."
SELECTED = "exact-model-測試"
CANONICAL = "canonical-model-測試"


class FakeLlamaHandler(BaseHTTPRequestHandler):
    observed_models: list[str] = []
    observed_messages: list[list[dict]] = []
    probe_models: list[str] = []
    delay_seconds = 0.8

    def log_message(self, *_args):
        pass

    def _send(self, value: object) -> None:
        payload = json.dumps(value).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/v1/models") or self.path.startswith("/models"):
            self._send({"data": [{"id": CANONICAL, "aliases": [SELECTED]}]})
        elif self.path in ("/v1/model", "/model"):
            self._send({"id": CANONICAL, "object": "model",
                        "parameters": {"max_seq_len": 262144}})
        else:
            self._send({"ok": True})

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers.get("content-length", "0"))))
        self.observed_models.append(str(body.get("model")))
        self.observed_messages.append(body.get("messages", []))
        time.sleep(self.delay_seconds)
        is_probe = (body.get("response_format") == {"type": "json_object"}
                    and body.get("messages") == [{"role": "user", "content": CAPABILITY_PROBE_PROMPT}])
        if is_probe:
            self.probe_models.append(str(body.get("model")))
        content = '{"probe": true}' if is_probe else "OK"
        self._send({"model": CANONICAL, "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": content}}]})


class FakeDeciderHandler(BaseHTTPRequestHandler):
    calls: list = []

    def log_message(self, *_args):
        pass

    def do_POST(self):  # noqa: N802
        self.calls.append(self.path)
        self.rfile.read(int(self.headers.get("content-length", "0") or "0"))
        payload = json.dumps({"model": "decider", "answers": {
            "Source evidence sufficiency for answering?": {
                "type": "choice", "choice": "SUFFICIENT", "confidence": 0.9,
                "certainty": 0.9, "probabilities": {"SUFFICIENT": 0.9, "NOT_SUFFICIENT": 0.1},
            }}}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def request(url: str, *, body: dict | None = None, secret: str = "") -> tuple[int, dict, dict]:
    data = None if body is None else json.dumps(body).encode()
    headers = {"content-type": "application/json"}
    if secret:
        headers["x-investor-shared-secret"] = secret
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    try:
        response = urllib.request.urlopen(req, timeout=5)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        return response.status, json.loads(response.read()), dict(response.headers)


class R75GatewayProcessTests(unittest.TestCase):
    def test_real_process_from_spaces_unicode_parentheses_exact_pin_and_backpressure(self) -> None:
        fake = ThreadingHTTPServer(("127.0.0.1", 0), FakeLlamaHandler)
        fake_thread = threading.Thread(target=fake.serve_forever, daemon=True)
        fake_thread.start()
        secret = "s" * 40
        with tempfile.TemporaryDirectory(prefix="Investor Intelligence 測試 (1) ") as directory:
            scripts = Path(directory) / "專案 (1)" / "scripts"
            scripts.mkdir(parents=True)
            for name in ("v212_local_llm_gateway.py", "v213_local_llm_gateway.py", "v213_compact_qa_gateway.py", "v213_model_profile.py", "v213_decision_backend_client.py", "v213_adaptive_reasoning.py"):
                shutil.copy2(ROOT / "scripts" / name, scripts / name)
            config = scripts.parent / "config"
            config.mkdir()
            policy = json.loads((ROOT / "config/v213-compact-qa-v1.json").read_text(encoding="utf-8"))
            # Isolated fake catalog only; no change to an installed model/profile.
            policy["model"] = SELECTED
            (config / "v213-compact-qa-v1.json").write_text(json.dumps(policy), encoding="utf-8")
            # Owned fake decider endpoint via fixture config; never the real 8000.
            decider = ThreadingHTTPServer(("127.0.0.1", 0), FakeDeciderHandler)
            threading.Thread(target=decider.serve_forever, daemon=True).start()
            lriv1 = json.loads((ROOT / "config/local-runtime-independence-v1.json").read_text(encoding="utf-8"))
            lriv1["decision_router"]["base_url"] = f"http://127.0.0.1:{decider.server_port}"
            lriv1["decision_router"]["retired"] = False  # this case exercises the decider path explicitly
            (config / "local-runtime-independence-v1.json").write_text(json.dumps(lriv1), encoding="utf-8")
            port = free_port()
            env = os.environ.copy()
            env.update({
                "II_LOCAL_LLM_SHARED_SECRET": secret,
                "II_LOCAL_LLM_MODEL": SELECTED,
                "II_LLAMA_BASE_URL": f"http://127.0.0.1:{fake.server_port}",
                "II_GATEWAY_MAX_CONCURRENT_GENERATIONS": "1",
                "II_GATEWAY_RETRY_AFTER_SECONDS": "3",
                "II_GATEWAY_DISABLE_PUBLIC_ENRICHMENT_FOR_TEST": "1",
                "LOCALAPPDATA": directory,
            })
            process = subprocess.Popen(
                [sys.executable, str(scripts / "v213_local_llm_gateway.py"), "--host", "127.0.0.1", "--port", str(port)],
                cwd=Path(directory) / "專案 (1)", env=env,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            try:
                health_url = f"http://127.0.0.1:{port}/health"
                for _ in range(60):
                    if process.poll() is not None:
                        stdout, stderr = process.communicate(timeout=2)
                        self.fail(f"gateway exited: {stdout[-500:]} {stderr[-500:]}")
                    try:
                        status, health, _ = request(health_url)
                        if status == 200 and health.get("service") == "v213-local-llm-gateway":
                            break
                    except OSError:
                        time.sleep(0.05)
                else:
                    self.fail("gateway health did not start")
                self.assertEqual(health["selected_model"], SELECTED)

                status, mismatch, _ = request(
                    f"http://127.0.0.1:{port}/v1/chat/completions",
                    body={"model": "substitution", "messages": []}, secret=secret,
                )
                self.assertEqual(status, 409)
                self.assertEqual(mismatch["error"], "MODEL_PIN_MISMATCH")

                first: list[tuple[int, dict, dict]] = []
                worker = threading.Thread(target=lambda: first.append(request(
                    f"http://127.0.0.1:{port}/v1/chat/completions",
                    body={"model": SELECTED, "messages": []}, secret=secret,
                )))
                worker.start()
                time.sleep(0.15)
                started = time.monotonic()
                health_status, _, _ = request(health_url)
                self.assertEqual(health_status, 200)
                self.assertLess(time.monotonic() - started, 0.7)
                status, busy, headers = request(
                    f"http://127.0.0.1:{port}/v1/chat/completions",
                    body={"messages": []}, secret=secret,
                )
                self.assertEqual(status, 429)
                self.assertEqual(busy["error"], "GENERATION_CAPACITY_EXHAUSTED")
                self.assertEqual(headers.get("Retry-After"), "3")
                worker.join(timeout=5)
                self.assertEqual(first[0][0], 200)
                self.assertEqual(FakeLlamaHandler.observed_models[-1], SELECTED)
                self.assertFalse(first[0][1]["ii_exact_model_pin"]["request_model_substitution_allowed"])
                self.assertEqual(first[0][1]["model"], CANONICAL)
                self.assertEqual(first[0][1]["ii_exact_model_pin"]["canonical_model"], CANONICAL)
                proof = first[0][1]["ii_methodology_execution"]
                self.assertEqual(proof["lane"], "NO_RESEARCH_ENRICHMENT")
                self.assertFalse(proof["full_skill_executed"])
                self.assertEqual(proof["reference_files_loaded"], [])
                compact_messages = [
                    {"role": "system", "content": policy["system"] + '\nDATA={"v":1,"freshness":"UNAVAILABLE"}'},
                    {"role": "user", "content": "Serenity 研究方法"},
                ]
                status, compact, _ = request(
                    f"http://127.0.0.1:{port}/v1/chat/completions",
                    body={"model": SELECTED, "messages": compact_messages,
                          "ii_context_mode": "compact_public_v1", "max_tokens": 160}, secret=secret,
                )
                self.assertEqual(status, 200)
                self.assertEqual(FakeLlamaHandler.observed_messages[-1], compact_messages)
                self.assertEqual(compact["ii_methodology_execution"]["lane"], "COMPACT_POLICY_ONLY")
                self.assertFalse(compact["ii_methodology_execution"]["full_skill_executed"])
                self.assertEqual(compact["ii_methodology_execution"]["reference_files_loaded"], [])
                self.assertIsNone(compact["ii_methodology_execution"]["directive_sha256"])

                # The owned decider stub was actually driven (explicit fixture
                # config, never the real 8000; parent guard does not cover the
                # child process, so the observed CPU calls are asserted here).
                self.assertGreater(len(FakeDeciderHandler.calls), 0)
                self.assertTrue(all(c == "/v1/systemone" for c in FakeDeciderHandler.calls))

                # The structured-JSON capability probe (both lanes) must send
                # the resolved CANONICAL identity, never the SELECTED alias.
                self.assertGreater(len(FakeLlamaHandler.probe_models), 0)
                self.assertTrue(all(m == CANONICAL for m in FakeLlamaHandler.probe_models))

                # Pre-generation decision gate: decider unavailable => denied,
                # zero reasoner product generation.
                decider.shutdown()
                decider.server_close()
                before = len(FakeLlamaHandler.observed_models)
                status, denied, _ = request(
                    f"http://127.0.0.1:{port}/v1/chat/completions",
                    body={"model": SELECTED, "messages": [{"role": "user", "content": "x"}]}, secret=secret,
                )
                self.assertEqual(status, 503)
                self.assertEqual(denied["error"], "REASONER_DECISION_DENIED")
                self.assertEqual(len(FakeLlamaHandler.observed_models), before)
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
        fake.shutdown()
        fake.server_close()


if __name__ == "__main__":
    unittest.main()
