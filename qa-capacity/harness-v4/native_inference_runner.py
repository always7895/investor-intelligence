import json
import os
import sys
import time
import hashlib
import http.client
import socket
import subprocess
import pathlib
import urllib.parse

_SCRIPTS_DIR = r"D:/Investor-Intelligence-LINE-Pi/_workspace/source/scripts"
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)
import v213_qa_capacity as qc

PINNED_ENDPOINT_URL = "http://127.0.0.1:5000/v1/chat/completions"
CONNECT_DEADLINE_S = 2.0
TOTAL_HTTP_DEADLINE_S = 10.0
RESPONSE_BODY_BYTES_MAX = 65536
READ_TIMEOUT_S = 0.25
MODEL_ID = "Qwen3.8-27B-EXL3-5.5bpw-v2"
APPROVED_CONTEXT = 262144
MAX_TOKENS_BOUND = 384
APPROVED_REQUEST_SHA256 = "1fa1910c8db0dda712d6997717e7c5519c22de9465222dd302e96456bcc3f7b0"
EXPECTED_REQUEST_FIELDS = ("model", "n", "stream", "temperature", "max_tokens", "enable_thinking", "stream_options", "messages")
QWEN_WORKER_NAMES = ("qwen-writer",)
MONITORING = {"interval_s": 2, "max_gap_s": 5, "timeout_s": 15, "ttl_s": 30}
EXPECTED_TASK_ID = "QA_CAPACITY_OPERATOR_HANDOFF_NATIVE_ONE_SHOT_6922278_V1"
EXPECTED_FIXUP_SHA = "6922278ac865727fdcdded96535f94aaaabeb8b3"
REPO_ROOT = r"D:/Investor-Intelligence-LINE-Pi/_workspace/source"


class WorkloadError(RuntimeError):
    def __init__(self, code, message=None):
        self.code = code
        super().__init__(message or code)


def load_request_bytes(namespace, approved_digest=None):
    if approved_digest is None:
        approved_digest = APPROVED_REQUEST_SHA256
    ns = pathlib.Path(namespace)
    req_path = ns / "request.json"
    raw = req_path.read_bytes()
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        raise WorkloadError("request_not_json")
    if not isinstance(data, dict):
        raise WorkloadError("request_invariant_violated")
    if set(data) != set(EXPECTED_REQUEST_FIELDS):
        raise WorkloadError("request_invariant_violated")
    if data.get("model") != MODEL_ID:
        raise WorkloadError("request_invariant_violated")
    if not isinstance(data.get("n"), int) or isinstance(data.get("n"), bool) or data.get("n") != 1:
        raise WorkloadError("request_invariant_violated")
    if data.get("stream") is not False:
        raise WorkloadError("request_invariant_violated")
    if data.get("temperature") != 0:
        raise WorkloadError("request_invariant_violated")
    if not isinstance(data.get("max_tokens"), int) or isinstance(data.get("max_tokens"), bool) or data.get("max_tokens") != 384:
        raise WorkloadError("request_invariant_violated")
    if data.get("enable_thinking") is not False:
        raise WorkloadError("request_invariant_violated")
    so = data.get("stream_options")
    if (
        not isinstance(so, dict)
        or set(so) != {"include_usage"}
        or so["include_usage"] is not True
    ):
        raise WorkloadError("request_invariant_violated")
    msgs = data.get("messages")
    if not isinstance(msgs, list) or not msgs:
        raise WorkloadError("request_invariant_violated")
    for m in msgs:
        if not isinstance(m, dict):
            raise WorkloadError("request_invariant_violated")
        role = m.get("role")
        content = m.get("content")
        if not isinstance(role, str) or not role:
            raise WorkloadError("request_invariant_violated")
        if not isinstance(content, str):
            raise WorkloadError("request_invariant_violated")
    if hashlib.sha256(raw).hexdigest() != approved_digest:
        raise WorkloadError("request_digest_mismatch")
    return raw


def build_binding(source_head, raw, runner_pid, runner_birth):
    import re
    if not isinstance(source_head, str) or not re.match(r"^[0-9a-f]{40}$", source_head):
        raise WorkloadError("source_head_invalid")
    if not isinstance(raw, dict):
        raise WorkloadError("model_mismatch")
    model = raw.get("model")
    if not isinstance(model, dict) or model.get("id") != MODEL_ID:
        raise WorkloadError("model_mismatch")
    params = model.get("parameters")
    if not isinstance(params, dict) or not isinstance(params.get("max_seq_len"), int) or isinstance(params.get("max_seq_len"), bool) or params.get("max_seq_len") != APPROVED_CONTEXT:
        raise WorkloadError("context_invalid")
    service = raw.get("service")
    if not isinstance(service, dict):
        raise WorkloadError("service_identity_invalid")
    required_keys = {"pid", "created", "image_sha256", "parent_pid", "parent_created", "parent_image_sha256", "main_sha256"}
    allowed_keys = required_keys | {"listener_port"}
    if not required_keys.issubset(service.keys()) or not set(service.keys()).issubset(allowed_keys):
        raise WorkloadError("service_identity_invalid")
    if "listener_port" in service:
        lp = service["listener_port"]
        if not isinstance(lp, int) or isinstance(lp, bool) or lp != 5000:
            raise WorkloadError("service_identity_invalid")
    if not isinstance(service.get("pid"), int) or isinstance(service.get("pid"), bool) or service.get("pid") <= 0:
        raise WorkloadError("service_identity_invalid")
    if not isinstance(service.get("created"), str) or not service.get("created"):
        raise WorkloadError("service_identity_invalid")
    for k in ("image_sha256", "parent_image_sha256", "main_sha256"):
        v = service.get(k)
        if not isinstance(v, str) or len(v) != 64 or not re.match(r"^[0-9a-f]{64}$", v):
            raise WorkloadError("service_identity_invalid")
    if not isinstance(service.get("parent_pid"), int) or isinstance(service.get("parent_pid"), bool) or service.get("parent_pid") <= 0:
        raise WorkloadError("service_identity_invalid")
    if not isinstance(service.get("parent_created"), str) or not service.get("parent_created"):
        raise WorkloadError("service_identity_invalid")
    gpu_xml = raw.get("gpu_xml")
    if not isinstance(gpu_xml, str):
        raise WorkloadError("gpu_xml_invalid")
    try:
        parsed = qc.parse_nvidia_xml(gpu_xml)
    except Exception:
        raise WorkloadError("gpu_xml_invalid")
    if not isinstance(parsed, dict) or not parsed.get("uuid"):
        raise WorkloadError("gpu_xml_invalid")
    if not isinstance(runner_pid, int) or isinstance(runner_pid, bool) or runner_pid <= 0:
        raise WorkloadError("runner_pid_invalid")
    if not isinstance(runner_birth, str) or not re.match(r"^[0-9a-f]{16}$", runner_birth):
        raise WorkloadError("runner_birth_invalid")
    return {
        "source_head": source_head,
        "model_id": MODEL_ID,
        "context": APPROVED_CONTEXT,
        "service": {k: v for k, v in service.items() if k != "listener_port"},
        "gpu_uuid": parsed["uuid"],
        "allowed_clients": [{"pid": runner_pid, "created": runner_birth}],
        "qwen_worker_names": list(QWEN_WORKER_NAMES),
        "model_artifacts": {"config_sha256": None, "weights_sha256": None, "availability": "NOT_EXPOSED_BY_ACTIVE_CARD"}
    }


def freeze_binding(binding, namespace):
    try:
        qc._validate_binding(binding)
    except qc.CapacityError:
        raise WorkloadError("binding_invalid")
    ns = pathlib.Path(namespace)
    out_path = ns / "expected-binding.json"
    if out_path.exists():
        raise WorkloadError("binding_already_frozen")
    data = json.dumps(binding, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    fd = os.open(str(out_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_BINARY, 0o644)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    digest = hashlib.sha256(data).hexdigest()
    import copy
    return (copy.deepcopy(binding), digest)


def make_transport(url=PINNED_ENDPOINT_URL, connect_deadline_s=CONNECT_DEADLINE_S, total_deadline_s=TOTAL_HTTP_DEADLINE_S, body_bytes_max=RESPONSE_BODY_BYTES_MAX, read_timeout_s=READ_TIMEOUT_S):
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or "127.0.0.1"
    port = parts.port or 5000
    path = parts.path or "/"

    def _interruptible_read(sock, n, cancel_event, deadline, read_timeout_s):
        buf = b""
        while len(buf) < n:
            now = time.monotonic()
            remaining = deadline - now
            if remaining <= 0:
                raise WorkloadError("deadline_exceeded")
            if cancel_event.is_set():
                raise WorkloadError("cancelled_during_response")
            sock.settimeout(min(read_timeout_s, remaining))
            try:
                chunk = sock.recv(n - len(buf))
                if not chunk:
                    break
                buf += chunk
            except socket.timeout:
                if cancel_event.is_set():
                    raise WorkloadError("cancelled_during_response")
                continue
        return buf

    def transport(request_bytes, cancel_event):
        t0 = time.monotonic()
        deadline = t0 + total_deadline_s
        if cancel_event.is_set():
            raise WorkloadError("cancelled_before_dispatch")
        now = time.monotonic()
        remaining = deadline - now
        if remaining <= 0:
            raise WorkloadError("deadline_exceeded")
        conn = http.client.HTTPConnection(host, port, timeout=min(connect_deadline_s, remaining))
        try:
            try:
                conn.connect()
            except (socket.timeout, TimeoutError):
                if cancel_event.is_set():
                    raise WorkloadError("cancelled_during_connect")
                raise WorkloadError("connect_deadline_exceeded")
            if cancel_event.is_set():
                raise WorkloadError("cancelled_during_connect")
            now = time.monotonic()
            if deadline - now <= 0:
                raise WorkloadError("deadline_exceeded")
            conn.request("POST", path, body=request_bytes, headers={"Content-Type": "application/json"})
            sock = conn.sock
            status_line = _interruptible_read(sock, 1, cancel_event, deadline, read_timeout_s)
            while not status_line.endswith(b"\r\n"):
                status_line += _interruptible_read(sock, 1, cancel_event, deadline, read_timeout_s)
            status_str = status_line.decode("utf-8", errors="replace").strip()
            status_parts = status_str.split(" ")
            if len(status_parts) < 2:
                raise WorkloadError("malformed_status")
            try:
                status = int(status_parts[1])
            except ValueError:
                raise WorkloadError("malformed_status")
            headers_buf = b""
            while not headers_buf.endswith(b"\r\n\r\n"):
                headers_buf += _interruptible_read(sock, 1, cancel_event, deadline, read_timeout_s)
            headers_str = headers_buf.decode("utf-8", errors="replace")
            content_length = None
            transfer_encoding = None
            for line in headers_str.split("\r\n"):
                if ":" in line:
                    k, v = line.split(":", 1)
                    k = k.strip().lower()
                    v = v.strip()
                    if k == "content-length":
                        try:
                            content_length = int(v)
                        except ValueError:
                            pass
                    elif k == "transfer-encoding":
                        transfer_encoding = v.lower()
            body = b""
            if content_length is not None:
                while len(body) < content_length:
                    if cancel_event.is_set():
                        raise WorkloadError("cancelled_during_body")
                    now = time.monotonic()
                    if deadline - now <= 0:
                        raise WorkloadError("deadline_exceeded")
                    chunk = _interruptible_read(sock, min(8192, content_length - len(body)), cancel_event, deadline, read_timeout_s)
                    if not chunk:
                        raise WorkloadError("incomplete_body")
                    body += chunk
                    if len(body) > body_bytes_max:
                        raise WorkloadError("oversize_body")
            elif transfer_encoding and "chunked" in transfer_encoding:
                while True:
                    if cancel_event.is_set():
                        raise WorkloadError("cancelled_during_body")
                    now = time.monotonic()
                    if deadline - now <= 0:
                        raise WorkloadError("deadline_exceeded")
                    size_line = b""
                    while not size_line.endswith(b"\r\n"):
                        size_line += _interruptible_read(sock, 1, cancel_event, deadline, read_timeout_s)
                    size_str = size_line.decode("utf-8", errors="replace").strip()
                    try:
                        chunk_size = int(size_str.split(";")[0], 16)
                    except ValueError:
                        raise WorkloadError("malformed_chunk")
                    if chunk_size < 0:
                        raise WorkloadError("malformed_chunk")
                    if chunk_size == 0:
                        trailer = _interruptible_read(sock, 2, cancel_event, deadline, read_timeout_s)
                        if trailer != b"\r\n":
                            raise WorkloadError("malformed_chunk")
                        break
                    chunk_remaining = chunk_size
                    while chunk_remaining > 0:
                        if cancel_event.is_set():
                            raise WorkloadError("cancelled_during_body")
                        now = time.monotonic()
                        if deadline - now <= 0:
                            raise WorkloadError("deadline_exceeded")
                        chunk = _interruptible_read(sock, min(8192, chunk_remaining), cancel_event, deadline, read_timeout_s)
                        if not chunk:
                            raise WorkloadError("incomplete_body")
                        body += chunk
                        chunk_remaining -= len(chunk)
                        if len(body) > body_bytes_max:
                            raise WorkloadError("oversize_body")
                    trailer = _interruptible_read(sock, 2, cancel_event, deadline, read_timeout_s)
                    if trailer != b"\r\n":
                        raise WorkloadError("malformed_chunk")
            else:
                while True:
                    if cancel_event.is_set():
                        raise WorkloadError("cancelled_during_body")
                    now = time.monotonic()
                    if deadline - now <= 0:
                        raise WorkloadError("deadline_exceeded")
                    chunk = _interruptible_read(sock, 8192, cancel_event, deadline, read_timeout_s)
                    if not chunk:
                        break
                    body += chunk
                    if len(body) > body_bytes_max:
                        raise WorkloadError("oversize_body")
            return (status, body)
        finally:
            conn.close()

    return transport


def inference_callback(request_bytes, transport, cancel_event, evidence):
    if cancel_event.is_set():
        raise WorkloadError("cancelled_before_dispatch")
    t_start = time.monotonic()
    status, body = transport(request_bytes, cancel_event)
    if cancel_event.is_set():
        raise WorkloadError("cancelled_after_response")
    t_complete = time.monotonic()
    if status != 200:
        raise WorkloadError("http_status_%d" % status)
    if len(body) > RESPONSE_BODY_BYTES_MAX:
        raise WorkloadError("oversize_body")
    try:
        resp = json.loads(body.decode("utf-8"))
    except Exception:
        raise WorkloadError("malformed_json")
    if not isinstance(resp, dict):
        raise WorkloadError("malformed_json")
    choices = resp.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise WorkloadError("choice_count")
    choice = choices[0]
    if not isinstance(choice, dict):
        raise WorkloadError("choice_count")
    finish_reason = choice.get("finish_reason")
    if finish_reason is None:
        raise WorkloadError("finish_reason_missing")
    elif finish_reason == "length":
        raise WorkloadError("truncated")
    elif finish_reason != "stop":
        raise WorkloadError("finish_reason_%s" % str(finish_reason))
    msg = choice.get("message")
    if not isinstance(msg, dict):
        raise WorkloadError("empty_content")
    content = msg.get("content")
    if not isinstance(content, str) or not content:
        raise WorkloadError("empty_content")
    if resp.get("model") != MODEL_ID:
        raise WorkloadError("model_mismatch")
    usage = resp.get("usage")
    if not isinstance(usage, dict):
        raise WorkloadError("usage_missing")
    ct = usage.get("completion_tokens")
    if not isinstance(ct, int) or isinstance(ct, bool):
        raise WorkloadError("usage_invalid")
    if ct < 1 or ct > MAX_TOKENS_BOUND:
        raise WorkloadError("token_bound_exceeded")
    evidence["request_start_s"] = t_start
    evidence["response_complete_s"] = t_complete
    evidence["callback_end_s"] = time.monotonic()
    return None


def work_factory(request_bytes, transport, evidence):
    def work(cancel_event):
        inference_callback(request_bytes, transport, cancel_event, evidence)
    return work


def run_live(namespace, *, transport=None, git_head_fn=None, collector=None):
    ns = pathlib.Path(namespace)
    plan_path = ns / "run-plan.json"
    if not plan_path.exists():
        raise WorkloadError("run_plan_mismatch")
    plan_bytes = plan_path.read_bytes()
    try:
        plan = json.loads(plan_bytes.decode("utf-8"))
    except Exception:
        raise WorkloadError("run_plan_mismatch")
    if not isinstance(plan, dict) or plan.get("task_id") != EXPECTED_TASK_ID or plan.get("fixup_sha") != EXPECTED_FIXUP_SHA:
        raise WorkloadError("run_plan_mismatch")
    if plan.get("authorized_source_sha") != EXPECTED_FIXUP_SHA:
        raise WorkloadError("run_plan_mismatch")
    if plan.get("approved_request_sha256") != APPROVED_REQUEST_SHA256:
        raise WorkloadError("run_plan_mismatch")
    auth_path = ns / "run-authority.json"
    handoff_path = ns / "operator-handoff.json"
    if not auth_path.exists() or not handoff_path.exists():
        raise WorkloadError("authority_missing")
    try:
        auth = json.loads(auth_path.read_bytes().decode("utf-8"))
        handoff = json.loads(handoff_path.read_bytes().decode("utf-8"))
    except Exception:
        raise WorkloadError("authority_missing")
    if not isinstance(auth, dict) or not isinstance(handoff, dict):
        raise WorkloadError("authority_missing")
    if auth.get("task_id") != EXPECTED_TASK_ID or handoff.get("task_id") != EXPECTED_TASK_ID:
        raise WorkloadError("authority_mismatch")
    if auth.get("fixup_sha") != EXPECTED_FIXUP_SHA:
        raise WorkloadError("authority_mismatch")
    if auth.get("authorized_source_sha") != EXPECTED_FIXUP_SHA:
        raise WorkloadError("authority_mismatch")
    if auth.get("run_plan_sha256") != hashlib.sha256(plan_bytes).hexdigest():
        raise WorkloadError("authority_mismatch")
    if auth.get("window") != "CURRENT" or handoff.get("window") != "CURRENT":
        raise WorkloadError("authority_stale")
    if not isinstance(handoff.get("operator"), str) or not handoff.get("operator"):
        raise WorkloadError("authority_stale")
    runner_pid = os.getpid()
    runner_birth = qc.process_identity(runner_pid)
    if not isinstance(runner_birth, str) or len(runner_birth) != 16 or not all(c in "0123456789abcdef" for c in runner_birth):
        raise WorkloadError("runner_birth_invalid")
    if collector is None:
        collector = qc.collect_windows_snapshot
    raw = collector({})
    if git_head_fn is None:
        def git_head_fn():
            result = subprocess.run(["git", "-C", REPO_ROOT, "rev-parse", "HEAD"], timeout=10, capture_output=True, text=True)
            return result.stdout.strip()
    try:
        source_head = git_head_fn()
    except Exception:
        raise WorkloadError("source_head_invalid")
    if not isinstance(source_head, str) or len(source_head) != 40 or not all(c in "0123456789abcdef" for c in source_head):
        raise WorkloadError("source_head_invalid")
    if source_head != EXPECTED_FIXUP_SHA:
        raise WorkloadError("source_head_mismatch")
    receipt_path = ns / "native-receipt.json"
    if receipt_path.exists():
        raise WorkloadError("receipt_already_persisted")
    binding = build_binding(source_head, raw, runner_pid, runner_birth)
    frozen_binding, binding_digest = freeze_binding(binding, namespace)
    request_bytes = load_request_bytes(namespace, APPROVED_REQUEST_SHA256)
    if transport is None:
        transport = make_transport()
    evidence = {}
    work = work_factory(request_bytes, transport, evidence)
    receipt = qc.run_native_window(frozen_binding, work, interval_s=2, max_gap_s=5, timeout_s=15, ttl_s=30)
    req_digest = hashlib.sha256(request_bytes).hexdigest()
    receipt_bytes = json.dumps(receipt, indent=2, sort_keys=True).encode("utf-8")
    fd = os.open(str(receipt_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_BINARY, 0o644)
    try:
        os.write(fd, receipt_bytes)
    finally:
        os.close(fd)
    receipt_digest = hashlib.sha256(receipt_bytes).hexdigest()
    evidence_out = {"request_sha256": req_digest, "binding_digest": binding_digest, "receipt_sha256": receipt_digest, "evidence": evidence}
    (ns / "workload-evidence.json").write_bytes(json.dumps(evidence_out, indent=2).encode("utf-8"))
    return (receipt, evidence)


def main(argv=None, namespace=None):
    if argv is not None and len(argv) > 0:
        print("Usage: native_inference_runner [no flags]")
        return 2
    if namespace is None:
        namespace = os.environ.get("QA_CAPACITY_HARNESS_NAMESPACE")
    if namespace is None:
        print("Namespace required")
        return 2
    try:
        receipt, evidence = run_live(namespace)
    except WorkloadError as e:
        print("REFUSED code=" + e.code)
        if e.code in ("authority_missing", "authority_mismatch", "authority_stale", "run_plan_mismatch"):
            return 2
        return 1
    except Exception as e:
        print("FAILED " + type(e).__name__)
        return 1
    print("NATIVE_RECEIPT_DIGEST=" + receipt["digest"])
    summary = receipt.get("summary", {})
    qualified = summary.get("summary") == "QUALIFIED"
    complete = all(k in evidence for k in ("request_start_s", "response_complete_s", "callback_end_s"))
    if not qualified or not complete:
        print("RESULT=NON_PASS")
        return 1
    print("RESULT=PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
