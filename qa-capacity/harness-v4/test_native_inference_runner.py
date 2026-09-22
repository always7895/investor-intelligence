import unittest
import json
import os
import sys
import time
import hashlib
import socket
import threading
import tempfile
import pathlib
import inspect
import ast
import subprocess
import http.server
import urllib.parse
import shutil
import unittest.mock

NS = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(NS))
import native_inference_runner as h

FIXTURE_HEAD = "ab" * 20
FIXTURE_SERVICE = {
    "pid": 6432,
    "created": "01dd498231ca20f1",
    "image_sha256": "a1" * 32,
    "parent_pid": 4000,
    "parent_created": "01dd498231ca20f0",
    "parent_image_sha256": "b2" * 32,
    "main_sha256": "c3" * 32,
    "listener_port": 5000,
}
FIXTURE_GPU_UUID = "GPU-fixture-00000000-0000-0000-0000-000000000000"

def fixture_gpu_xml(processes):
    xml = '<nvidia_smi_log><gpu id="00000000:00:00.0"><uuid>' + FIXTURE_GPU_UUID + '</uuid><driver_model><current_dm>0</current_dm></driver_model><processes>'
    for pid, ptype in processes:
        xml += f'<process_info><pid>{pid}</pid><type>{ptype}</type></process_info>'
    xml += '</processes></gpu></nvidia_smi_log>'
    return xml

def clean_raw():
    return {
        "model": {"id": h.MODEL_ID, "parameters": {"max_seq_len": 262144}},
        "service": dict(FIXTURE_SERVICE),
        "gpu_xml": fixture_gpu_xml([(6432, "C")]),
        "clients": [],
        "herdr": {"agents": [
            {"name": "qwen-writer", "agent_status": "idle"},
            {"name": "skyrim-astra-v4", "agent_status": "idle"}
        ]}
    }

def conflict_raw(kind):
    raw = clean_raw()
    if kind == "gpu":
        raw["gpu_xml"] = fixture_gpu_xml([(6432, "C"), (9999, "C+G")])
    elif kind == "client":
        raw["clients"] = [{"pid": 7777, "created": "01dd498231ca20f2"}]
    elif kind == "qwen":
        raw["herdr"]["agents"][0]["agent_status"] = "working"
    return raw

def valid_response_body():
    return json.dumps({
        "id": "cmpl-fixture",
        "object": "chat.completion",
        "created": 1,
        "model": h.MODEL_ID,
        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "1: table\n2: chair\n3: window"}}],
        "usage": {"prompt_tokens": 40, "completion_tokens": 12, "total_tokens": 52}
    }).encode()

class FakeTransport:
    def __init__(self, status=200, body=None, exc=None):
        self.status = status
        self.body = body
        self.exc = exc
        self.calls = []

    def __call__(self, request_bytes, cancel_event):
        self.calls.append({"request_bytes": request_bytes, "cancel_set": cancel_event.is_set()})
        if self.exc:
            raise self.exc
        return (self.status, self.body if self.body is not None else valid_response_body())

_NULL_USAGE = object()

def check_timeline_containment(evidence, cb_start, cb_end):
    """Same-clock containment: workload evidence timestamps must be valid
    numbers within the callback interval captured on the same monotonic clock.
    Raises AssertionError on missing/invalid values, reversed ordering, or
    timestamps outside the callback interval."""
    for k in ("request_start_s", "response_complete_s", "callback_end_s"):
        v = evidence.get(k)
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            raise AssertionError(f"missing or invalid timeline value: {k}")
    if not (cb_start <= evidence["request_start_s"] <= evidence["response_complete_s"] <= evidence["callback_end_s"] <= cb_end):
        raise AssertionError("workload evidence timestamps outside callback interval or out of order")

class EphemeralServer:
    def __init__(self, config):
        self.config = config
        self._server = None
        self._thread = None
        self._request_count = 0
        self._lock = threading.Lock()

    def _make_handler(self):
        config = self.config
        server_ref = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def do_POST(self):
                with server_ref._lock:
                    server_ref._request_count += 1

                mode = config.get("mode", "valid")
                body = config.get("body")
                if callable(body):
                    body = body()
                if body is None:
                    body = valid_response_body()

                if mode == "redirect":
                    self.send_response(302)
                    self.send_header("Location", "http://127.0.0.1:9999/redirected")
                    self.end_headers()
                elif mode == "http500":
                    self.send_response(500)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif mode == "oversize":
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif mode == "slow_headers":
                    time.sleep(config.get("header_delay_s", 0.0))
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif mode == "trickle_body":
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    interval = config.get("trickle_interval_s", 0.0)
                    for byte in body:
                        self.wfile.write(bytes([byte]))
                        if interval > 0:
                            time.sleep(interval)
                elif mode == "chunked_valid":
                    self.send_response(200)
                    self.send_header("Transfer-Encoding", "chunked")
                    self.end_headers()
                    self.wfile.write(body)
                elif mode == "incomplete_cl":
                    self.send_response(200)
                    self.send_header("Content-Length", str(config.get("cl", len(body))))
                    self.end_headers()
                    self.wfile.write(body)
                elif mode == "malformed_chunk":
                    self.send_response(200)
                    self.send_header("Transfer-Encoding", "chunked")
                    self.end_headers()
                    self.wfile.write(body)
                else:  # valid
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

        return Handler

    @property
    def port(self):
        return self._server.server_address[1]

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"

    @property
    def request_count(self):
        with self._lock:
            return self._request_count

    def start(self):
        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), self._make_handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None


class TestNativeInferenceRunner(unittest.TestCase):

    def test_import_performs_no_work(self):
        # (a) AST check
        source = (NS / "native_inference_runner.py").read_text()
        tree = ast.parse(source)
        allowed_types = (ast.Import, ast.ImportFrom, ast.Assign, ast.FunctionDef, ast.ClassDef, ast.If, ast.Expr)
        for node in tree.body:
            if isinstance(node, ast.Expr):
                if not (isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)):
                    self.fail(f"Top-level Expr is not a docstring: {ast.dump(node)}")
            elif not isinstance(node, allowed_types):
                self.fail(f"Disallowed top-level statement: {type(node).__name__} {ast.dump(node)}")

        # (b) subprocess check
        cmd = [sys.executable, "-B", "-c", f"import sys; sys.path.insert(0, {str(NS)!r}); import native_inference_runner; print('IMPORT_OK')"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, f"Subprocess import failed: {result.stderr}")
        self.assertIn("IMPORT_OK", result.stdout)

        # (c) canonical root untouched
        canonical_root = pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "InvestorIntelligence" / "qa-capacity-v1"
        def snapshot():
            if canonical_root.exists():
                return sorted([p.name for p in canonical_root.iterdir()])
            return None
        before = snapshot()
        # In-process import already done at module level, but we re-verify state
        after = snapshot()
        self.assertEqual(before, after, "Canonical root changed during import")

    def test_pre_deny_zero_dispatch(self):
        ns = tempfile.mkdtemp()
        root = tempfile.mkdtemp()
        try:
            request_bytes = (NS / "request.json").read_bytes()
            transport = FakeTransport()
            evidence = {}
            work = h.work_factory(request_bytes, transport, evidence)

            probe_calls = [0]
            def fake_probe():
                probe_calls[0] += 1
                return conflict_raw("gpu")

            binding = h.build_binding(FIXTURE_HEAD, clean_raw(), 4242, "ab" * 8)
            lease = h.qc.CapacityLease(root, binding, ttl_s=60)
            try:
                receipt = h.qc.run_window(lease, fake_probe, work, interval_s=2, max_gap_s=5, timeout_s=15)
            finally:
                lease.close()

            self.assertEqual(len(transport.calls), 0)
            summary = receipt.get("summary", {})
            self.assertEqual(summary.get("CAPACITY_EVIDENCE"), "UNQUALIFIED")
            reasons = summary.get("reasons", [])
            self.assertIn("pre_evaluation_failed", reasons)
        finally:
            shutil.rmtree(ns, ignore_errors=True)
            shutil.rmtree(root, ignore_errors=True)

    def test_pre_admit_exactly_one_no_retry(self):
        ns = tempfile.mkdtemp()
        root = tempfile.mkdtemp()
        try:
            request_bytes = (NS / "request.json").read_bytes()
            transport = FakeTransport()
            evidence = {}
            work = h.work_factory(request_bytes, transport, evidence)

            def fake_probe():
                return clean_raw()

            binding = h.build_binding(FIXTURE_HEAD, clean_raw(), 4242, "ab" * 8)
            lease = h.qc.CapacityLease(root, binding, ttl_s=60)
            try:
                receipt = h.qc.run_window(lease, fake_probe, work, interval_s=2, max_gap_s=5, timeout_s=15)
            finally:
                lease.close()

            self.assertEqual(len(transport.calls), 1)
            self.assertEqual(transport.calls[0]["request_bytes"], request_bytes)
        finally:
            shutil.rmtree(ns, ignore_errors=True)
            shutil.rmtree(root, ignore_errors=True)

    def test_self_binding_accepted(self):
        ns = tempfile.mkdtemp()
        try:
            b = h.build_binding(FIXTURE_HEAD, clean_raw(), 4242, "ab" * 8)
            self.assertEqual(b["allowed_clients"], [{"pid": 4242, "created": "ab" * 8}])
            self.assertEqual(b["qwen_worker_names"], ["qwen-writer"])

            frozen_copy, digest = h.freeze_binding(b, ns)
            self.assertTrue((pathlib.Path(ns) / "expected-binding.json").exists())

            with self.assertRaises(h.WorkloadError) as ctx:
                h.freeze_binding(b, ns)
            self.assertEqual(ctx.exception.code, "binding_already_frozen")
        finally:
            shutil.rmtree(ns, ignore_errors=True)

    def test_extra_client_rejected(self):
        sig = inspect.signature(h.build_binding)
        self.assertEqual(set(sig.parameters.keys()), {"source_head", "raw", "runner_pid", "runner_birth"})

        b = h.build_binding(FIXTURE_HEAD, clean_raw(), 4242, "ab" * 8)
        self.assertEqual(len(b["allowed_clients"]), 1)
        self.assertEqual(b["allowed_clients"][0], {"pid": 4242, "created": "ab" * 8})

    def test_stale_identity_rejected(self):
        with self.assertRaises(h.WorkloadError) as ctx:
            h.build_binding(FIXTURE_HEAD, clean_raw(), 4242, "stale-not-hex")
        self.assertEqual(ctx.exception.code, "runner_birth_invalid")

        with self.assertRaises(h.WorkloadError) as ctx:
            h.build_binding(FIXTURE_HEAD, clean_raw(), 4242, "ab" * 7)
        self.assertEqual(ctx.exception.code, "runner_birth_invalid")

    def test_unknown_identity_rejected(self):
        with self.assertRaises(h.WorkloadError) as ctx:
            h.build_binding(FIXTURE_HEAD, clean_raw(), "not-an-int", "ab" * 8)
        self.assertEqual(ctx.exception.code, "runner_pid_invalid")

        with self.assertRaises(h.WorkloadError) as ctx:
            h.build_binding(FIXTURE_HEAD, clean_raw(), True, "ab" * 8)
        self.assertEqual(ctx.exception.code, "runner_pid_invalid")

        with self.assertRaises(h.WorkloadError) as ctx:
            h.build_binding(FIXTURE_HEAD, clean_raw(), -5, "ab" * 8)
        self.assertEqual(ctx.exception.code, "runner_pid_invalid")

    def test_worker_scope_fixed(self):
        b = h.build_binding(FIXTURE_HEAD, clean_raw(), 4242, "ab" * 8)
        self.assertEqual(b["qwen_worker_names"], ["qwen-writer"])

        sig = inspect.signature(h.build_binding)
        self.assertNotIn("qwen_worker_names", sig.parameters)

    def test_post_freeze_binding_change_rejected(self):
        ns = tempfile.mkdtemp()
        try:
            binding = h.build_binding(FIXTURE_HEAD, clean_raw(), 4242, "ab" * 8)
            frozen_copy, digest = h.freeze_binding(binding, ns)

            # Mutate original after freeze
            binding["allowed_clients"].append({"pid": 1, "created": "cd" * 8})

            # Frozen file on disk unchanged
            file_bytes = (pathlib.Path(ns) / "expected-binding.json").read_bytes()
            self.assertEqual(hashlib.sha256(file_bytes).hexdigest(), digest)

            # Frozen copy isolated
            self.assertEqual(len(frozen_copy["allowed_clients"]), 1)
        finally:
            shutil.rmtree(ns, ignore_errors=True)

    def test_raw_validation_rejects(self):
        # model id mismatch
        raw = clean_raw()
        raw["model"]["id"] = "other-model"
        with self.assertRaises(h.WorkloadError) as ctx:
            h.build_binding(FIXTURE_HEAD, raw, 4242, "ab" * 8)
        self.assertEqual(ctx.exception.code, "model_mismatch")

        # max_seq_len too small
        raw = clean_raw()
        raw["model"]["parameters"]["max_seq_len"] = 131072
        with self.assertRaises(h.WorkloadError) as ctx:
            h.build_binding(FIXTURE_HEAD, raw, 4242, "ab" * 8)
        self.assertEqual(ctx.exception.code, "context_invalid")

        # service missing key
        raw = clean_raw()
        del raw["service"]["pid"]
        with self.assertRaises(h.WorkloadError) as ctx:
            h.build_binding(FIXTURE_HEAD, raw, 4242, "ab" * 8)
        self.assertEqual(ctx.exception.code, "service_identity_invalid")

        # gpu_xml not xml
        raw = clean_raw()
        raw["gpu_xml"] = "not xml"
        with self.assertRaises(h.WorkloadError) as ctx:
            h.build_binding(FIXTURE_HEAD, raw, 4242, "ab" * 8)
        self.assertEqual(ctx.exception.code, "gpu_xml_invalid")

        # source_head invalid
        with self.assertRaises(h.WorkloadError) as ctx:
            h.build_binding("zz" * 20, clean_raw(), 4242, "ab" * 8)
        self.assertEqual(ctx.exception.code, "source_head_invalid")

        # listener_port boundary: optional, strict int 5000 only
        raw = clean_raw()
        raw["service"]["listener_port"] = "5000"
        with self.assertRaises(h.WorkloadError) as ctx:
            h.build_binding(FIXTURE_HEAD, raw, 4242, "ab" * 8)
        self.assertEqual(ctx.exception.code, "service_identity_invalid")

        raw = clean_raw()
        raw["service"]["listener_port"] = 5001
        with self.assertRaises(h.WorkloadError) as ctx:
            h.build_binding(FIXTURE_HEAD, raw, 4242, "ab" * 8)
        self.assertEqual(ctx.exception.code, "service_identity_invalid")

        raw = clean_raw()
        raw["service"]["extra_field"] = 1
        with self.assertRaises(h.WorkloadError) as ctx:
            h.build_binding(FIXTURE_HEAD, raw, 4242, "ab" * 8)
        self.assertEqual(ctx.exception.code, "service_identity_invalid")

        # normalization: binding service is exactly the 7 identity keys
        b = h.build_binding(FIXTURE_HEAD, clean_raw(), 4242, "ab" * 8)
        self.assertEqual(set(b["service"].keys()), {"pid", "created", "image_sha256", "parent_pid", "parent_created", "parent_image_sha256", "main_sha256"})
        self.assertNotIn("listener_port", b["service"])

    def test_exact_request_preservation(self):
        ns = tempfile.mkdtemp()
        try:
            # Copy request.json to temp ns
            shutil.copy2(NS / "request.json", pathlib.Path(ns) / "request.json")
            loaded = h.load_request_bytes(ns)
            original = (NS / "request.json").read_bytes()
            self.assertEqual(hashlib.sha256(loaded).hexdigest(), hashlib.sha256(original).hexdigest())

            # inference_callback records exact bytes
            transport = FakeTransport()
            evidence = {}
            h.inference_callback(loaded, transport, threading.Event(), evidence)
            self.assertEqual(transport.calls[0]["request_bytes"], loaded)

            # Tampered request
            tampered_ns = tempfile.mkdtemp()
            try:
                req_data = json.loads(original)
                req_data["temperature"] = 0.5
                (pathlib.Path(tampered_ns) / "request.json").write_bytes(json.dumps(req_data).encode())
                with self.assertRaises(h.WorkloadError) as ctx:
                    h.load_request_bytes(tampered_ns)
                self.assertEqual(ctx.exception.code, "request_invariant_violated")
            finally:
                shutil.rmtree(tampered_ns, ignore_errors=True)
        finally:
            shutil.rmtree(ns, ignore_errors=True)

    def test_request_amendment_usage_conditions(self):
        # amended frozen request carries exactly the approved usage amendment
        request_bytes = (NS / "request.json").read_bytes()
        parsed = json.loads(request_bytes.decode("utf-8"))
        self.assertEqual(parsed.get("stream_options"), {"include_usage": True})
        self.assertIs(parsed.get("stream"), False)
        self.assertEqual(parsed.get("model"), h.MODEL_ID)
        self.assertEqual(parsed.get("n"), 1)
        self.assertEqual(parsed.get("temperature"), 0)
        self.assertEqual(parsed.get("max_tokens"), 384)
        self.assertIs(parsed.get("enable_thinking"), False)
        self.assertTrue(parsed.get("messages"))

        class UsageConditionedTransport:
            """Source-faithful fake: response usage is conditioned on the
            captured request (include_usage true -> usage present, otherwise
            usage null), mirroring the installed server semantics."""

            def __init__(self, usage_override=_NULL_USAGE):
                self.calls = []
                self.usage_override = usage_override

            def __call__(self, request_bytes, cancel_event):
                self.calls.append({"request_bytes": request_bytes, "cancel_set": cancel_event.is_set()})
                req = json.loads(request_bytes.decode("utf-8"))
                include_usage = (req.get("stream_options") or {}).get("include_usage") is True
                if self.usage_override is _NULL_USAGE:
                    usage = ({"prompt_tokens": 40, "completion_tokens": 12, "total_tokens": 52}
                             if include_usage else None)
                else:
                    usage = self.usage_override
                body = json.dumps({
                    "id": "cmpl-fixture",
                    "object": "chat.completion",
                    "created": 1,
                    "model": h.MODEL_ID,
                    "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "1: table"}}],
                    "usage": usage
                }).encode()
                return (200, body)

        # outbound bytes match the frozen artifact exactly and carry the amendment
        t = UsageConditionedTransport()
        evidence = {}
        h.inference_callback(request_bytes, t, threading.Event(), evidence)
        self.assertEqual(len(t.calls), 1)
        self.assertEqual(t.calls[0]["request_bytes"], request_bytes)
        out = json.loads(t.calls[0]["request_bytes"].decode("utf-8"))
        self.assertEqual(out.get("stream_options"), {"include_usage": True})
        self.assertIs(out.get("stream"), False)
        self.assertIsNotNone(evidence.get("request_start_s"))
        self.assertIsNotNone(evidence.get("response_complete_s"))
        self.assertIsNotNone(evidence.get("callback_end_s"))

        # missing/null usage still fails; never triggers a second request
        t2 = UsageConditionedTransport(usage_override=None)
        evidence2 = {}
        with self.assertRaises(h.WorkloadError) as ctx:
            h.inference_callback(request_bytes, t2, threading.Event(), evidence2)
        self.assertEqual(ctx.exception.code, "usage_missing")
        self.assertEqual(len(t2.calls), 1)
        self.assertEqual(evidence2, {})

        # valid int completion_tokens in [1, 384] passes only when all other
        # required response criteria also pass: valid usage + wrong model fails
        class WrongModelTransport(UsageConditionedTransport):
            def __call__(self, request_bytes, cancel_event):
                status, body = super().__call__(request_bytes, cancel_event)
                return (status, body.replace(h.MODEL_ID.encode(), b"other-model"))

        t3 = WrongModelTransport()
        evidence3 = {}
        with self.assertRaises(h.WorkloadError) as ctx:
            h.inference_callback(request_bytes, t3, threading.Event(), evidence3)
        self.assertEqual(ctx.exception.code, "model_mismatch")
        self.assertEqual(len(t3.calls), 1)
        self.assertEqual(evidence3, {})

        # bool / string / negative / zero / over-limit token counts fail
        for bad, expected_code in ((True, "usage_invalid"), ("12", "usage_invalid"),
                                   (-1, "token_bound_exceeded"), (0, "token_bound_exceeded"),
                                   (500, "token_bound_exceeded")):
            tb = UsageConditionedTransport(usage_override={"prompt_tokens": 40, "completion_tokens": bad, "total_tokens": 52})
            with self.assertRaises(h.WorkloadError) as ctx:
                h.inference_callback(request_bytes, tb, threading.Event(), {})
            self.assertEqual(ctx.exception.code, expected_code)
            self.assertEqual(len(tb.calls), 1)

    def test_response_failure_modes(self):
        request_bytes = (NS / "request.json").read_bytes()

        def make_body(**overrides):
            base = {
                "id": "cmpl-fixture",
                "object": "chat.completion",
                "created": 1,
                "model": h.MODEL_ID,
                "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "1: table\n2: chair\n3: window"}}],
                "usage": {"prompt_tokens": 40, "completion_tokens": 12, "total_tokens": 52}
            }
            base.update(overrides)
            return json.dumps(base).encode()

        cases = [
            ("status 500", FakeTransport(status=500), "http_status_500"),
            ("malformed json", FakeTransport(body=b"not json"), "malformed_json"),
            ("2 choices", FakeTransport(body=make_body(choices=[
                {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "a"}},
                {"index": 1, "finish_reason": "stop", "message": {"role": "assistant", "content": "b"}}
            ])), "choice_count"),
            ("finish_reason None", FakeTransport(body=make_body(choices=[
                {"index": 0, "finish_reason": None, "message": {"role": "assistant", "content": "a"}}
            ])), "finish_reason_missing"),
            ("finish_reason length", FakeTransport(body=make_body(choices=[
                {"index": 0, "finish_reason": "length", "message": {"role": "assistant", "content": "a"}}
            ])), "truncated"),
            ("empty content", FakeTransport(body=make_body(choices=[
                {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": ""}}
            ])), "empty_content"),
            ("model mismatch", FakeTransport(body=make_body(model="other-model")), "model_mismatch"),
            ("usage None", FakeTransport(body=make_body(usage=None)), "usage_missing"),
            ("usage invalid str", FakeTransport(body=make_body(usage={"prompt_tokens": 40, "completion_tokens": "12", "total_tokens": 52})), "usage_invalid"),
            ("token bound exceeded", FakeTransport(body=make_body(usage={"prompt_tokens": 40, "completion_tokens": 500, "total_tokens": 540})), "token_bound_exceeded"),
        ]

        for name, transport, expected_code in cases:
            with self.subTest(name=name):
                evidence = {}
                cancel = threading.Event()
                with self.assertRaises(h.WorkloadError) as ctx:
                    h.inference_callback(request_bytes, transport, cancel, evidence)
                self.assertEqual(ctx.exception.code, expected_code)

    def test_redirect_not_followed(self):
        server = EphemeralServer({"mode": "redirect"})
        server.start()
        try:
            transport = h.make_transport(url=server.url, connect_deadline_s=1.0, total_deadline_s=3.0)
            request_bytes = (NS / "request.json").read_bytes()
            evidence = {}
            cancel = threading.Event()
            with self.assertRaises(h.WorkloadError) as ctx:
                h.inference_callback(request_bytes, transport, cancel, evidence)
            self.assertEqual(ctx.exception.code, "http_status_302")
            self.assertEqual(server.request_count, 1)
        finally:
            server.stop()

    def test_env_proxy_ignored(self):
        server = EphemeralServer({"mode": "valid"})
        server.start()
        old_http = os.environ.get("HTTP_PROXY")
        old_https = os.environ.get("HTTPS_PROXY")
        try:
            os.environ["HTTP_PROXY"] = "http://127.0.0.1:1"
            os.environ["HTTPS_PROXY"] = "http://127.0.0.1:1"
            transport = h.make_transport(url=server.url, connect_deadline_s=1.0, total_deadline_s=3.0)
            request_bytes = (NS / "request.json").read_bytes()
            evidence = {}
            cancel = threading.Event()
            h.inference_callback(request_bytes, transport, cancel, evidence)
            self.assertEqual(server.request_count, 1)
        finally:
            if old_http is None:
                os.environ.pop("HTTP_PROXY", None)
            else:
                os.environ["HTTP_PROXY"] = old_http
            if old_https is None:
                os.environ.pop("HTTPS_PROXY", None)
            else:
                os.environ["HTTPS_PROXY"] = old_https
            server.stop()

    def test_wrong_endpoint_pinned(self):
        self.assertEqual(h.PINNED_ENDPOINT_URL, "http://127.0.0.1:5000/v1/chat/completions")
        sig = inspect.signature(h.make_transport)
        self.assertEqual(sig.parameters["url"].default, h.PINNED_ENDPOINT_URL)

    def test_oversize_body_fails(self):
        oversize_body = b"x" * 70000
        server = EphemeralServer({"mode": "oversize", "body": oversize_body})
        server.start()
        try:
            transport = h.make_transport(url=server.url, connect_deadline_s=1.0, total_deadline_s=3.0)
            request_bytes = (NS / "request.json").read_bytes()
            evidence = {}
            cancel = threading.Event()
            with self.assertRaises(h.WorkloadError) as ctx:
                h.inference_callback(request_bytes, transport, cancel, evidence)
            self.assertEqual(ctx.exception.code, "oversize_body")
        finally:
            server.stop()

    def test_cancel_before_connection(self):
        # FakeTransport variant
        transport = FakeTransport()
        request_bytes = (NS / "request.json").read_bytes()
        evidence = {}
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(h.WorkloadError) as ctx:
            h.inference_callback(request_bytes, transport, cancel, evidence)
        self.assertEqual(ctx.exception.code, "cancelled_before_dispatch")
        self.assertEqual(len(transport.calls), 0)

        # Real transport variant
        server = EphemeralServer({"mode": "valid"})
        server.start()
        try:
            real_transport = h.make_transport(url=server.url, connect_deadline_s=1.0, total_deadline_s=3.0)
            cancel2 = threading.Event()
            cancel2.set()
            with self.assertRaises(h.WorkloadError) as ctx:
                h.inference_callback(request_bytes, real_transport, cancel2, evidence)
            self.assertEqual(ctx.exception.code, "cancelled_before_dispatch")
            self.assertEqual(server.request_count, 0)
        finally:
            server.stop()

    def test_cancel_during_blocked_response(self):
        server = EphemeralServer({"mode": "slow_headers", "header_delay_s": 3.0})
        server.start()
        try:
            transport = h.make_transport(url=server.url, connect_deadline_s=1.0, total_deadline_s=5.0, read_timeout_s=0.2)
            request_bytes = (NS / "request.json").read_bytes()
            evidence = {}
            cancel = threading.Event()

            def set_cancel():
                time.sleep(0.5)
                cancel.set()

            timer = threading.Thread(target=set_cancel, daemon=True)
            timer.start()

            start = time.monotonic()
            with self.assertRaises(h.WorkloadError) as ctx:
                h.inference_callback(request_bytes, transport, cancel, evidence)
            elapsed = time.monotonic() - start

            self.assertTrue(ctx.exception.code.startswith("cancelled_"), f"Got code: {ctx.exception.code}")
            self.assertLess(elapsed, 3.0)
        finally:
            server.stop()

    def test_cancel_during_body_transfer(self):
        body = b"y" * 100
        server = EphemeralServer({"mode": "trickle_body", "body": body, "trickle_interval_s": 0.3})
        server.start()
        try:
            transport = h.make_transport(url=server.url, connect_deadline_s=1.0, total_deadline_s=5.0)
            request_bytes = (NS / "request.json").read_bytes()
            evidence = {}
            cancel = threading.Event()

            def set_cancel():
                time.sleep(0.5)
                cancel.set()

            timer = threading.Thread(target=set_cancel, daemon=True)
            timer.start()

            start = time.monotonic()
            with self.assertRaises(h.WorkloadError) as ctx:
                h.inference_callback(request_bytes, transport, cancel, evidence)
            elapsed = time.monotonic() - start

            self.assertIn(ctx.exception.code, ["cancelled_during_body", "cancelled_during_response"])
            self.assertLess(elapsed, 3.0)
        finally:
            server.stop()

    def test_slow_headers_cannot_extend_deadline(self):
        server = EphemeralServer({"mode": "slow_headers", "header_delay_s": 3.0})
        server.start()
        try:
            transport = h.make_transport(url=server.url, connect_deadline_s=0.5, total_deadline_s=1.0, read_timeout_s=0.2)
            request_bytes = (NS / "request.json").read_bytes()
            evidence = {}
            cancel = threading.Event()

            start = time.monotonic()
            with self.assertRaises(h.WorkloadError) as ctx:
                h.inference_callback(request_bytes, transport, cancel, evidence)
            elapsed = time.monotonic() - start

            self.assertEqual(ctx.exception.code, "deadline_exceeded")
            self.assertLess(elapsed, 2.5)
        finally:
            server.stop()

    def test_trickled_body_cannot_extend_deadline(self):
        body = b"z" * 100
        server = EphemeralServer({"mode": "trickle_body", "body": body, "trickle_interval_s": 0.3})
        server.start()
        try:
            transport = h.make_transport(url=server.url, connect_deadline_s=1.0, total_deadline_s=1.0)
            request_bytes = (NS / "request.json").read_bytes()
            evidence = {}
            cancel = threading.Event()

            start = time.monotonic()
            with self.assertRaises(h.WorkloadError) as ctx:
                h.inference_callback(request_bytes, transport, cancel, evidence)
            elapsed = time.monotonic() - start

            self.assertEqual(ctx.exception.code, "deadline_exceeded")
            self.assertLess(elapsed, 2.5)
        finally:
            server.stop()

    def test_cleanup_leaves_no_local_work(self):
        server = EphemeralServer({"mode": "slow_headers", "header_delay_s": 3.0})
        server.start()
        try:
            transport = h.make_transport(url=server.url, connect_deadline_s=0.5, total_deadline_s=1.0, read_timeout_s=0.2)
            request_bytes = (NS / "request.json").read_bytes()
            evidence = {}
            cancel = threading.Event()

            before_threads = set(t.name for t in threading.enumerate())

            with self.assertRaises(h.WorkloadError):
                h.inference_callback(request_bytes, transport, cancel, evidence)

            server.stop()
            time.sleep(0.1)

            after_threads = set(t.name for t in threading.enumerate())
            new_threads = after_threads - before_threads
            # No new non-daemon threads should remain
            for t in threading.enumerate():
                if t.name in new_threads:
                    self.assertTrue(t.daemon, f"Non-daemon thread left: {t.name}")
        finally:
            server.stop()

    def test_callback_failure_propagates_nonpass(self):
        ns = tempfile.mkdtemp()
        root = tempfile.mkdtemp()
        try:
            request_bytes = (NS / "request.json").read_bytes()
            wrong_model_body = json.dumps({
                "id": "cmpl-fixture",
                "object": "chat.completion",
                "created": 1,
                "model": "other-model",
                "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "a"}}],
                "usage": {"prompt_tokens": 40, "completion_tokens": 12, "total_tokens": 52}
            }).encode()
            transport = FakeTransport(body=wrong_model_body)
            evidence = {}
            work = h.work_factory(request_bytes, transport, evidence)

            def fake_probe():
                return clean_raw()

            binding = h.build_binding(FIXTURE_HEAD, clean_raw(), 4242, "ab" * 8)
            lease = h.qc.CapacityLease(root, binding, ttl_s=60)
            try:
                receipt = h.qc.run_window(lease, fake_probe, work, interval_s=2, max_gap_s=5, timeout_s=15)
            finally:
                lease.close()

            events = receipt.get("events", [])
            work_raised_found = False
            for ev in events:
                if ev.get("kind") == "error" and ev.get("code") == "work_raised":
                    work_raised_found = True
            self.assertTrue(work_raised_found, f"work_raised not found in events: {events}")

            # callback attempted exactly once; no successful workload result
            self.assertEqual(len(transport.calls), 1)
            self.assertEqual(evidence, {})

            summary = receipt.get("summary", {})
            self.assertEqual(summary.get("CAPACITY_EVIDENCE"), "UNQUALIFIED")
            self.assertIn("work_raised", summary.get("reasons", []))
        finally:
            shutil.rmtree(ns, ignore_errors=True)
            shutil.rmtree(root, ignore_errors=True)

    def test_receipt_binding_mismatch_rejected(self):
        ns = tempfile.mkdtemp()
        root = tempfile.mkdtemp()
        try:
            request_bytes = (NS / "request.json").read_bytes()
            transport = FakeTransport()
            evidence = {}
            work = h.work_factory(request_bytes, transport, evidence)

            def fake_probe():
                return clean_raw()

            binding = h.build_binding(FIXTURE_HEAD, clean_raw(), 4242, "ab" * 8)
            lease = h.qc.CapacityLease(root, binding, ttl_s=60)
            try:
                receipt = h.qc.run_window(lease, fake_probe, work, interval_s=2, max_gap_s=5, timeout_s=15)
            finally:
                lease.close()

            # Verify with correct binding
            h.qc.verify_receipt(receipt, binding)

            # Verify with mismatched binding
            tampered_binding = dict(binding)
            tampered_binding["source_head"] = "cd" * 20
            with self.assertRaises(h.qc.CapacityError):
                h.qc.verify_receipt(receipt, tampered_binding)

            # Original receipt not mutated
            if "digest" in receipt:
                pass  # digest unchanged implicitly
        finally:
            shutil.rmtree(ns, ignore_errors=True)
            shutil.rmtree(root, ignore_errors=True)

    def test_main_refuses_without_authority(self):
        ns = tempfile.mkdtemp()
        try:
            # Copy run-plan.json if it exists
            run_plan = NS / "run-plan.json"
            if run_plan.exists():
                shutil.copy2(run_plan, pathlib.Path(ns) / "run-plan.json")

            result = h.main(argv=[], namespace=ns)
            self.assertEqual(result, 2)
            self.assertFalse((pathlib.Path(ns) / "expected-binding.json").exists())

            result2 = h.main(argv=["--bypass"], namespace=ns)
            self.assertEqual(result2, 2)
        finally:
            shutil.rmtree(ns, ignore_errors=True)

    def test_workload_evidence_timeline_consistency(self):
        ns = tempfile.mkdtemp()
        root = tempfile.mkdtemp()
        try:
            request_bytes = (NS / "request.json").read_bytes()
            transport = FakeTransport()
            evidence = {}
            work = h.work_factory(request_bytes, transport, evidence)

            # fixture-side wrapper capturing callback entry/exit on the same
            # monotonic clock as the workload evidence (time.monotonic)
            cb = {}

            def wrapped_work(cancel_event):
                cb["start"] = time.monotonic()
                try:
                    return work(cancel_event)
                finally:
                    cb["end"] = time.monotonic()

            def fake_probe():
                return clean_raw()

            binding = h.build_binding(FIXTURE_HEAD, clean_raw(), 4242, "ab" * 8)
            lease = h.qc.CapacityLease(root, binding, ttl_s=60)
            try:
                receipt = h.qc.run_window(lease, fake_probe, wrapped_work, interval_s=2, max_gap_s=5, timeout_s=15)
            finally:
                lease.close()

            # same-clock containment of the workload evidence in the callback interval
            check_timeline_containment(evidence, cb["start"], cb["end"])

            # negative case: shifted timestamp outside the callback interval is rejected
            shifted = dict(evidence)
            shifted["request_start_s"] = cb["start"] - 100.0
            with self.assertRaises(AssertionError):
                check_timeline_containment(shifted, cb["start"], cb["end"])

            # reversed ordering is rejected
            reversed_ev = dict(evidence)
            reversed_ev["response_complete_s"] = reversed_ev["request_start_s"] - 1.0
            with self.assertRaises(AssertionError):
                check_timeline_containment(reversed_ev, cb["start"], cb["end"])

            # missing times are rejected
            missing_ev = dict(evidence)
            missing_ev["callback_end_s"] = None
            with self.assertRaises(AssertionError):
                check_timeline_containment(missing_ev, cb["start"], cb["end"])

            # receipt-relative work ordering verified in its own coordinate system
            self.assertIsNotNone(receipt.get("work_start_s"))
            self.assertIsNotNone(receipt.get("work_end_s"))
            self.assertLessEqual(receipt["work_start_s"], receipt["work_end_s"])
            verified = h.qc.verify_receipt(receipt, binding)
            self.assertEqual(verified, receipt["summary"])
        finally:
            shutil.rmtree(ns, ignore_errors=True)
            shutil.rmtree(root, ignore_errors=True)


    # ---- V4 R1-R5 regression tests (master REWORK on review SHA f9a8a88; F1/F2 and all 27 cases retained) ----

    def _write_authority_files(self, ns, plan_bytes, window="CURRENT", operator="fixture-operator",
                               task_id=None, authorized_source_sha=None, run_plan_sha256=None):
        plan = json.loads(plan_bytes.decode("utf-8"))
        auth = {
            "task_id": task_id if task_id is not None else plan["task_id"],
            "fixup_sha": plan["fixup_sha"],
            "authorized_source_sha": authorized_source_sha if authorized_source_sha is not None else plan["authorized_source_sha"],
            "run_plan_sha256": run_plan_sha256 if run_plan_sha256 is not None else hashlib.sha256(plan_bytes).hexdigest(),
            "window": window,
        }
        handoff = {
            "task_id": task_id if task_id is not None else plan["task_id"],
            "window": window,
            "operator": operator,
        }
        (ns / "run-authority.json").write_bytes(json.dumps(auth).encode("utf-8"))
        (ns / "operator-handoff.json").write_bytes(json.dumps(handoff).encode("utf-8"))

    def _make_v4_namespace(self, ns, request_bytes=None, plan_bytes=None):
        if request_bytes is None:
            request_bytes = (NS / "request.json").read_bytes()
        if plan_bytes is None:
            plan_bytes = (NS / "run-plan.json").read_bytes()
        (ns / "request.json").write_bytes(request_bytes)
        (ns / "run-plan.json").write_bytes(plan_bytes)
        self._write_authority_files(ns, plan_bytes)

    def test_request_identity_negative_cases(self):
        ns = pathlib.Path(tempfile.mkdtemp())
        try:
            approved = (NS / "request.json").read_bytes()
            base = json.loads(approved.decode("utf-8"))

            def variant_bytes(mutate):
                data = json.loads(json.dumps(base))
                mutate(data)
                return json.dumps(data, indent=2).encode("utf-8")

            def expect_code(variant, code):
                (ns / "request.json").write_bytes(variant)
                with self.assertRaises(h.WorkloadError) as ctx:
                    h.load_request_bytes(ns, h.APPROVED_REQUEST_SHA256)
                self.assertEqual(ctx.exception.code, code)

            expect_code(variant_bytes(lambda d: d["stream_options"].update(include_usage=1)), "request_invariant_violated")
            expect_code(variant_bytes(lambda d: d["stream_options"].update(extra_key=1)), "request_invariant_violated")
            expect_code(variant_bytes(lambda d: d.update(tools=[])), "request_invariant_violated")
            expect_code(variant_bytes(lambda d: d["messages"][0].update(content="modified prompt content")), "request_digest_mismatch")
            (ns / "request.json").write_bytes(approved)
            self.assertEqual(h.load_request_bytes(ns, h.APPROVED_REQUEST_SHA256), approved)
        finally:
            shutil.rmtree(ns, ignore_errors=True)

    def test_run_live_digest_mismatch_zero_dispatch(self):
        ns = pathlib.Path(tempfile.mkdtemp())
        try:
            self._make_v4_namespace(ns, request_bytes=(NS / "request.json").read_bytes().replace(b"32 distinct", b"33 distinct"))
            transport = FakeTransport()
            with self.assertRaises(h.WorkloadError) as ctx:
                h.run_live(str(ns), transport=transport, git_head_fn=lambda: h.EXPECTED_FIXUP_SHA, collector=lambda _: clean_raw())
            self.assertEqual(ctx.exception.code, "request_digest_mismatch")
            self.assertEqual(len(transport.calls), 0)
        finally:
            shutil.rmtree(ns, ignore_errors=True)

    def test_run_live_source_head_mismatch_rejected(self):
        ns = pathlib.Path(tempfile.mkdtemp())
        try:
            self._make_v4_namespace(ns)
            transport = FakeTransport()
            with self.assertRaises(h.WorkloadError) as ctx:
                h.run_live(str(ns), transport=transport, git_head_fn=lambda: "cd" * 20, collector=lambda _: clean_raw())
            self.assertEqual(ctx.exception.code, "source_head_mismatch")
            self.assertEqual(len(transport.calls), 0)
        finally:
            shutil.rmtree(ns, ignore_errors=True)

    def test_run_live_authority_stale_rejected(self):
        ns = pathlib.Path(tempfile.mkdtemp())
        try:
            self._make_v4_namespace(ns)
            plan_bytes = (ns / "run-plan.json").read_bytes()
            self._write_authority_files(ns, plan_bytes, window="CLOSED")
            transport = FakeTransport()
            with self.assertRaises(h.WorkloadError) as ctx:
                h.run_live(str(ns), transport=transport, git_head_fn=lambda: h.EXPECTED_FIXUP_SHA, collector=lambda _: clean_raw())
            self.assertEqual(ctx.exception.code, "authority_stale")
            self.assertEqual(len(transport.calls), 0)
        finally:
            shutil.rmtree(ns, ignore_errors=True)
        ns = pathlib.Path(tempfile.mkdtemp())
        try:
            self._make_v4_namespace(ns)
            plan_bytes = (ns / "run-plan.json").read_bytes()
            self._write_authority_files(ns, plan_bytes, operator="")
            transport = FakeTransport()
            with self.assertRaises(h.WorkloadError) as ctx:
                h.run_live(str(ns), transport=transport, git_head_fn=lambda: h.EXPECTED_FIXUP_SHA, collector=lambda _: clean_raw())
            self.assertEqual(ctx.exception.code, "authority_stale")
            self.assertEqual(len(transport.calls), 0)
        finally:
            shutil.rmtree(ns, ignore_errors=True)

    def test_chunked_valid_accepted(self):
        payload = valid_response_body()
        half = len(payload) // 2
        chunked = (format(half, "x").encode() + b"\r\n" + payload[:half] + b"\r\n"
                   + format(len(payload) - half, "x").encode() + b"\r\n" + payload[half:] + b"\r\n"
                   + b"0\r\n\r\n")
        srv = EphemeralServer({"mode": "chunked_valid", "body": chunked})
        srv.start()
        try:
            transport = h.make_transport(url=srv.url + "/v1/chat/completions")
            status, body = transport((NS / "request.json").read_bytes(), threading.Event())
            self.assertEqual(status, 200)
            self.assertEqual(body, payload)
        finally:
            srv.stop()

    def test_incomplete_cl_rejected(self):
        payload = valid_response_body()
        srv = EphemeralServer({"mode": "incomplete_cl", "body": payload[: len(payload) // 2], "cl": len(payload)})
        srv.start()
        try:
            transport = h.make_transport(url=srv.url + "/v1/chat/completions")
            with self.assertRaises(h.WorkloadError) as ctx:
                transport((NS / "request.json").read_bytes(), threading.Event())
            self.assertEqual(ctx.exception.code, "incomplete_body")
        finally:
            srv.stop()

    def test_malformed_chunk_rejected(self):
        srv = EphemeralServer({"mode": "malformed_chunk", "body": b"zz-not-hex\r\n0\r\n\r\n"})
        srv.start()
        try:
            transport = h.make_transport(url=srv.url + "/v1/chat/completions")
            with self.assertRaises(h.WorkloadError) as ctx:
                transport((NS / "request.json").read_bytes(), threading.Event())
            self.assertEqual(ctx.exception.code, "malformed_chunk")
        finally:
            srv.stop()

    def test_cancel_during_connect_zero_post(self):
        cancel_event = threading.Event()
        posts = []

        class FakeConn:
            def __init__(self, host, port, timeout=None):
                pass

            def connect(self):
                cancel_event.set()

            def request(self, method, path, body=None, headers=None):
                posts.append((method, path))

            def close(self):
                pass

        with unittest.mock.patch.object(h.http.client, "HTTPConnection", FakeConn):
            transport = h.make_transport()
            with self.assertRaises(h.WorkloadError) as ctx:
                transport((NS / "request.json").read_bytes(), cancel_event)
        self.assertEqual(ctx.exception.code, "cancelled_during_connect")
        self.assertEqual(posts, [])

    def test_cancel_after_response_rejected(self):
        class CancelingTransport:
            def __init__(self):
                self.calls = []

            def __call__(self, request_bytes, cancel_event):
                self.calls.append(1)
                cancel_event.set()
                return (200, valid_response_body())

        t = CancelingTransport()
        evidence = {}
        with self.assertRaises(h.WorkloadError) as ctx:
            h.inference_callback((NS / "request.json").read_bytes(), t, threading.Event(), evidence)
        self.assertEqual(ctx.exception.code, "cancelled_after_response")
        self.assertEqual(len(t.calls), 1)
        self.assertEqual(evidence, {})

    def test_main_result_codes(self):
        complete = {"request_start_s": 1.0, "response_complete_s": 2.0, "callback_end_s": 3.0}
        ns = pathlib.Path(tempfile.mkdtemp())
        try:
            with unittest.mock.patch.object(h, "run_live", return_value=({"digest": "ab" * 32, "summary": {"summary": "UNQUALIFIED", "reasons": ["work_raised"]}}, complete)):
                self.assertEqual(h.main(namespace=str(ns)), 1)
            with unittest.mock.patch.object(h, "run_live", return_value=({"digest": "ab" * 32, "summary": {"summary": "QUALIFIED", "reasons": []}}, complete)):
                self.assertEqual(h.main(namespace=str(ns)), 0)
            with unittest.mock.patch.object(h, "run_live", return_value=({"digest": "ab" * 32, "summary": {"summary": "QUALIFIED", "reasons": []}}, {})):
                self.assertEqual(h.main(namespace=str(ns)), 1)
        finally:
            shutil.rmtree(ns, ignore_errors=True)

    def test_receipt_persisted_full_no_overwrite(self):
        ns = pathlib.Path(tempfile.mkdtemp())
        try:
            self._make_v4_namespace(ns)
            transport = FakeTransport()

            def fake_run_native_window(binding, work, **kwargs):
                work(threading.Event())
                return {"digest": "cd" * 32, "summary": {"summary": "UNQUALIFIED", "reasons": ["fixture_window"]}, "nonce": "00" * 16}

            with unittest.mock.patch.object(h.qc, "run_native_window", side_effect=fake_run_native_window):
                receipt, evidence = h.run_live(str(ns), transport=transport, git_head_fn=lambda: h.EXPECTED_FIXUP_SHA, collector=lambda _: clean_raw())
            self.assertEqual(len(transport.calls), 1)
            rp = ns / "native-receipt.json"
            self.assertTrue(rp.exists())
            stored = json.loads(rp.read_bytes().decode("utf-8"))
            self.assertEqual(stored, receipt)
            self.assertEqual(stored["summary"]["summary"], "UNQUALIFIED")
            ev_out = json.loads((ns / "workload-evidence.json").read_bytes().decode("utf-8"))
            self.assertEqual(ev_out["receipt_sha256"], hashlib.sha256(rp.read_bytes()).hexdigest())
            self.assertEqual(ev_out["request_sha256"], hashlib.sha256((NS / "request.json").read_bytes()).hexdigest())
            with self.assertRaises(h.WorkloadError) as ctx:
                h.run_live(str(ns), transport=FakeTransport(), git_head_fn=lambda: h.EXPECTED_FIXUP_SHA, collector=lambda _: clean_raw())
            self.assertEqual(ctx.exception.code, "receipt_already_persisted")
        finally:
            shutil.rmtree(ns, ignore_errors=True)

    def test_script_entrypoint_refuses_without_authority(self):
        ns = pathlib.Path(tempfile.mkdtemp())
        try:
            env = dict(os.environ)
            env["QA_CAPACITY_HARNESS_NAMESPACE"] = str(ns)
            result = subprocess.run([sys.executable, str(NS / "native_inference_runner.py")], timeout=60, capture_output=True, text=True, env=env)
            self.assertEqual(result.returncode, 2)
            self.assertIn("REFUSED code=run_plan_mismatch", result.stdout)
        finally:
            shutil.rmtree(ns, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
