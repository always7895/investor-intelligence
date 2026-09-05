"""Explicit opt-in isolated workers.dev -> leased tunnel -> Gateway -> existing Q6.
Creates/deletes ONLY uniquely named non-Production Worker/KV/DO. No real LINE,
Production config/bindings, preset edits or second llama-server. Credentials are
random process-only values, uploaded via stdin and never written to receipts.
"""
from __future__ import annotations
import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
import requests
from v213_compact_qa_gateway import POLICY

ROOT = Path(__file__).resolve().parents[1]

def router_limits():
    # Return numeric limits only, never the raw process command/preset contents.
    command = "Get-CimInstance Win32_Process -Filter \"Name='llama-server.exe'\" | ForEach-Object { $m=[regex]::Match($_.CommandLine,'--models-max[ =]+(\\d+)'); if($m.Success){[pscustomobject]@{pid=$_.ProcessId;models_max=[int]$m.Groups[1].Value}} } | ConvertTo-Json -Compress"
    raw = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command], capture_output=True, text=True, check=True, timeout=20).stdout
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get("models_max") != 1:
        raise RuntimeError("Exactly one existing Router with models-max=1 required")
    return value


def source_manifest():
    paths = subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "cloud/src", "scripts/v21*.py", "config/*.json", "cloud/test/r75-live-bench-worker.ts", "scripts/v213_edge_readiness.ps1"], cwd=ROOT, text=True).splitlines()
    return {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in sorted(set(paths))}

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--live-isolated", action="store_true")
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if not args.live_isolated or args.output.exists():
        p.error("explicit opt-in and new evidence output required")
    router = router_limits()
    loaded = [m["id"] for m in requests.get("http://127.0.0.1:8080/models", timeout=10).json()["data"] if m.get("status", {}).get("value") == "loaded"]
    if loaded != ["qwen38-q6"]: raise RuntimeError("Only existing qwen38-q6 may be loaded")
    preset = Path(os.environ["LOCALAPPDATA"]) / "InvestorIntelligence/UserData/config/v213-llama-router.preset.ini"
    preset_sha = hashlib.sha256(preset.read_bytes()).hexdigest()
    manifest = source_manifest()
    name = "ii-r75-qa-bench-" + secrets.token_hex(5)
    generation = secrets.token_hex(16)
    secret = secrets.token_hex(32)
    gateway_secret = hmac.new(secret.encode(), ("v213-free-relay-gateway." + generation).encode(), hashlib.sha256).hexdigest()
    session = requests.Session()
    evidence = {"schema_version": 1, "status": "FAIL", "source_manifest": manifest, "router": router, "preset_sha256": preset_sha,
                "exact_model": "qwen38-q6", "request_enable_thinking": False, "synthetic_public_fixture": True,
                "production_mutation": False, "real_line_sent": False, "results": [], "worker_name": name}
    wrangler = str(ROOT / "cloud/node_modules/.bin/wrangler.cmd")
    def wr(*argv, stdin=None):
        result = subprocess.run([wrangler, *argv], cwd=ROOT / "cloud", input=stdin, text=True, capture_output=True, timeout=120)
        if result.returncode: raise RuntimeError("ISOLATED_WRANGLER_FAILED:" + argv[0])
        return result.stdout
    def signed(origin, path, body):
        text = json.dumps(body, separators=(",", ":"))
        stamp, nonce = str(int(time.time())), secrets.token_hex(16)
        sig = hmac.new(secret.encode(), f"{stamp}.{nonce}.{text}".encode(), hashlib.sha256).hexdigest()
        return session.post(origin + path, data=text.encode(), headers={"content-type": "application/json", "x-ii-v21-timestamp": stamp, "x-ii-v21-nonce": nonce, "x-ii-v21-signature": sig}, timeout=35)
    gateway = tunnel = None
    namespace = None
    deployed = False
    metrics = []
    phase = "cold"
    old_env = {k: os.environ.get(k) for k in ("II_LLAMA_BASE_URL", "II_LOCAL_LLM_MODEL", "II_LOCAL_LLM_SHARED_SECRET")}
    original_post = requests.post
    def measured_post(url, **kwargs):
        if str(url).startswith("http://127.0.0.1:8080/"):
            kwargs["json"]["cache_prompt"] = phase == "warm"
            started = time.monotonic()
            response = original_post(url, **kwargs)
            if response.ok:
                body = response.json()
                metrics.append({"usage": body.get("usage", {}), "timings": body.get("timings", {}), "upstream_ms": round(1000*(time.monotonic()-started),2), "model": body.get("model"), "finish_reason": body.get("choices", [{}])[0].get("finish_reason")})
            return response
        return original_post(url, **kwargs)
    try:
        with tempfile.TemporaryDirectory(prefix="ii-r75-isolated-qa-", ignore_cleanup_errors=True) as temp:
            tmp = Path(temp)
            cfg = tmp / "wrangler.toml"
            namespace_output = wr("kv", "namespace", "create", name)
            found = re.search(r'(?:"id"\s*:|\bid\s*=)\s*"([0-9a-f]{32})"', namespace_output)
            if not found: raise RuntimeError("ISOLATED_KV_ID_UNAVAILABLE")
            namespace = found[1]
            cfg.write_text(f'name = "{name}"\nmain = {json.dumps(str(ROOT / "cloud/test/r75-live-bench-worker.ts"))}\ncompatibility_date = "2026-01-01"\nworkers_dev = true\n[version_metadata]\nbinding = "CF_VERSION_METADATA"\n[vars]\nFREE_RELAY_ENABLED = "true"\nFREE_RELAY_MAX_TTL_SECONDS = "600"\nLOCAL_LLM_MODEL = "qwen38-q6"\nGENERAL_QA_ENABLED = "true"\nCURRENT_PUBLIC_DATA_ENABLED = "true"\nPUBLIC_DATA_MAX_AGE_SECONDS = "7200"\nMEMORY_FEATURE_AVAILABLE = "false"\nLINE_CHANNEL_ACCESS_TOKEN = "SYNTHETIC_TEST_ONLY"\n' + ''.join(f'\n[[kv_namespaces]]\nbinding = "{b}"\nid = "{namespace}"\n' for b in ("PUBLIC_CACHE", "TENANT_PRIVATE_CACHE", "EPHEMERAL_SECURITY_CACHE")) + '\n[[durable_objects.bindings]]\nname = "V213_FREE_RELAY_ROUTE"\nclass_name = "V213FreeRelayRoute"\n[[migrations]]\ntag = "isolated-bench-v1"\nnew_sqlite_classes = ["V213FreeRelayRoute"]\n', encoding="utf-8")
            output = wr("deploy", "--config", str(cfg))
            deployed = True
            origin_match = re.search(r'https://'+re.escape(name)+r'\.[a-z0-9-]+\.workers\.dev', output)
            if not origin_match: raise RuntimeError("ISOLATED_WORKER_ORIGIN_UNAVAILABLE")
            origin = origin_match[0]
            wr("secret", "bulk", "--config", str(cfg), stdin=json.dumps({"V21_SYNC_HMAC_SECRET": secret, "TENANT_DATA_ENCRYPTION_KEY": secrets.token_hex(32)}))
            deployments = json.loads(wr("deployments", "list", "--json", "--config", str(cfg)))
            versions = sorted(deployments, key=lambda d: d["created_on"])[-1]["versions"]
            if len(versions) != 1 or versions[0]["percentage"] != 100: raise RuntimeError("ISOLATED_ACTIVE_VERSION_INVALID")
            version = versions[0]["version_id"]
            policy_hash = hashlib.sha256(json.dumps(POLICY, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
            # Exercise the SAME bounded readiness gate used by the product;
            # do not maintain another deploy/sleep/retry implementation here.
            command = f". '{ROOT / 'scripts/v213_edge_readiness.ps1'}'; $proof=Wait-V213EdgeReadiness -Origin '{origin}' -ExpectedVersion '{version}' -ProjectRoot '{ROOT}'; $proof|ConvertTo-Json -Compress"
            check = subprocess.run(["pwsh", "-NoProfile", "-Command", command], text=True, capture_output=True, timeout=120)
            if check.returncode:
                codes = sorted(set(re.findall(r'V213_[A-Z_]+', check.stderr)))
                evidence["readiness_error_codes"] = codes
                raise RuntimeError("ISOLATED_READINESS_GATE_FAILED:" + ",".join(codes))
            proof = json.loads(check.stdout[check.stdout.index('{'):])
            proofs = [proof]
            current = sorted(json.loads(wr("deployments", "list", "--json", "--config", str(cfg))), key=lambda d:d["created_on"])[-1]["versions"]
            if current != versions: raise RuntimeError("ISOLATED_ACTIVE_VERSION_CHANGED")
            mismatch = session.get(origin+"/v213/readiness", params={"expected_version": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "challenge": secrets.token_hex(16)}, timeout=15)
            if mismatch.status_code != 409: raise RuntimeError("VERSION_MISMATCH_ACCEPTED")
            evidence.update(worker_version=version, active_percentage=100, readiness=proofs, convergence="PASS_REAL_ISOLATED", compact_policy_sha256=policy_hash)
            os.environ.update(II_LLAMA_BASE_URL="http://127.0.0.1:8080", II_LOCAL_LLM_MODEL="qwen38-q6", II_LOCAL_LLM_SHARED_SECRET=gateway_secret)
            import v213_local_llm_gateway as gateway_module
            requests.post = measured_post
            gateway = ThreadingHTTPServer(("127.0.0.1", 0), gateway_module.V213GatewayHandler)
            threading.Thread(target=gateway.serve_forever, daemon=True).start()
            cloudflared = shutil.which("cloudflared") or r"C:\Program Files (x86)\cloudflared\cloudflared.exe"
            logpath = tmp / "tunnel.log"
            with logpath.open("w", encoding="utf-8") as log:
                tunnel = subprocess.Popen([cloudflared, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{gateway.server_port}", "--protocol", "http2"], stdout=log, stderr=log)
                public = None
                for _ in range(60):
                    urls = re.findall(r'https://[a-z0-9-]+\.trycloudflare\.com', logpath.read_text(encoding="utf-8", errors="replace"))
                    if urls:
                        public = urls[0]
                        try:
                            h = session.get(public+"/health", timeout=5)
                            if h.ok and h.json().get("selected_model") == "qwen38-q6": break
                        except requests.RequestException: pass
                    time.sleep(1)
                else: raise RuntimeError("ISOLATED_TUNNEL_NOT_READY")
                now = time.time()
                iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))
                route = {"schema_version": 1, "tunnel_mode": "quick_free_relay", "model": "qwen38-q6", "public_url": public, "connected_at": iso(now), "expires_at": iso(now+550), "health_schema_version": 2, "route_generation": generation, "consecutive_health_checks": 3}
                r = signed(origin, "/v213/admin/free-relay-route", route)
                if not r.ok: raise RuntimeError("ISOLATED_ROUTE_FAILED:"+str(r.json().get("code")))
                for key, value in [("model", "qwen38"), ("expires_at", iso(now-60))]:
                    bad = signed(origin, "/v213/admin/free-relay-route", {**route, key: value})
                    if bad.ok: raise RuntimeError("NEGATIVE_ROUTE_ACCEPTED")
                if signed(origin, "/v213/admin/free-relay-route", route).ok: raise RuntimeError("REPLAY_ROUTE_ACCEPTED")
                auth = {"authorization": "Bearer " + secret}
                session.post(origin+"/setup", headers=auth, timeout=15).raise_for_status()
                for case in ("smoke", "general", "ticker", "methodology", "evidence"):
                    for phase in ("cold", "warm"):
                        before = len(metrics); started = time.monotonic()
                        r = signed(origin, "/v213/admin/free-relay-smoke", {"schema_version": 1}) if case == "smoke" else session.get(origin+"/qa", params={"case": case}, headers=auth, timeout=30)
                        total = round(1000*(time.monotonic()-started),2)
                        body = r.json(); metric = metrics[-1] if len(metrics) > before else {}
                        answer = body.get("answer", "")
                        ok = r.ok and bool(metric) and metric.get("finish_reason") == "stop" and metric.get("model") == "qwen38-q6" and total <= 28000
                        ok = ok and (body.get("expected_token_observed") is True if case == "smoke" else len(answer) >= 25 and not answer.startswith("LOCAL_MODEL_"))
                        row = {"case": case, "phase": phase, "total_ms": total, "pass": ok, "http_status": r.status_code, **metric, "answer": answer}
                        evidence["results"].append(row)
                        print(json.dumps({k:v for k,v in row.items() if k != "answer"}), flush=True)
                r = session.get(origin+"/reference-start", headers=auth, timeout=30); r.raise_for_status()
                reference = re.search(r'參考編號 ([A-Z0-9]+)', r.json().get("reply", ""))
                if not reference: raise RuntimeError("REFERENCE_BRANCH_NOT_REACHED")
                for _ in range(20):
                    time.sleep(1)
                    job = session.get(origin+"/reference-result", params={"id": reference[1]}, headers=auth, timeout=10).json()
                    if job and job.get("status") == "complete": break
                else: raise RuntimeError("REFERENCE_COMPLETION_FAILED")
                if not job.get("result") or "LOCAL_MODEL_" in job["result"]: raise RuntimeError("REFERENCE_MODEL_RESULT_INVALID")
                evidence.update(reference_job="PASS_REAL_WAITUNTIL_SYNTHETIC_LINE", test_only_reference_floor_ms=8000, stale_lease="PASS", replay="PASS", exact_model_mismatch="PASS")
                if not all(row["pass"] for row in evidence["results"]): raise RuntimeError("LIVE_LATENCY_OR_MODEL_GATE_FAILED")
                evidence["status"] = "PASS"
    except Exception:
        evidence["status"] = "FAIL"
        raise
    finally:
        requests.post = original_post
        if tunnel:
            tunnel.terminate(); tunnel.wait(timeout=15)
        if gateway: gateway.shutdown(); gateway.server_close()
        for key, value in old_env.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value
        cleanup = True
        try:
            if 'temp' in locals() and Path(temp).exists(): shutil.rmtree(temp)
            if deployed: wr("delete", "--name", name, "--force")
            if namespace: wr("kv", "namespace", "delete", "--namespace-id", namespace)
        except Exception: cleanup = False
        evidence["isolated_resources_deleted"] = cleanup
        evidence["preset_unchanged"] = hashlib.sha256(preset.read_bytes()).hexdigest() == preset_sha
        evidence["source_unchanged_during_benchmark"] = source_manifest() == manifest
        if not cleanup or not evidence["preset_unchanged"] or not evidence["source_unchanged_during_benchmark"]: evidence["status"] = "FAIL"
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    if evidence["status"] != "PASS": raise RuntimeError("ISOLATED_LIVE_GATE_FAILED")

if __name__ == "__main__": main()
