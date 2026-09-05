"""Explicit opt-in, serial inference benchmark; never deploys or accesses Production.

Cold/warm refer to the prompt KV cache, NOT model reload or machine reboot.
No preset edits, model switches, llama-server launches, or persistent credentials.
--isolated-gateway starts a temporary loopback HTTP gateway, never a public route.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import time
import os
import secrets
import threading
import subprocess
from http.server import ThreadingHTTPServer
import requests

MODEL = "qwen38-q6"
QUESTIONS = {
    "general": "什麼是自由現金流？它與淨利有何差異？",
    "ticker": "NVDA有哪些需要驗證的公司風險？",
    "methodology": "Serenity 的瓶頸與公司價值捕捉有何差別？",
    "evidence": "SEC 申報文件能否單獨證明公司有定價權？",
    "smoke": "Reply exactly R75_FREE_RELAY_E2E_OK",
}


def router_limits():
    # Select only numeric flags and process IDs; never return raw command lines.
    command = "Get-CimInstance Win32_Process -Filter \"Name='llama-server.exe'\" | ForEach-Object { $m=[regex]::Match($_.CommandLine,'--models-max[ =]+(\\d+)'); if($m.Success){[pscustomobject]@{pid=$_.ProcessId;models_max=[int]$m.Groups[1].Value}} } | ConvertTo-Json -Compress"
    raw = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command], capture_output=True, text=True, check=True, timeout=20).stdout
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get("models_max") != 1:
        raise RuntimeError("exactly one Router with models-max=1 required")
    return value


def run_case(origin, name, messages, max_tokens, mode=None, auth=None):
    result = []
    for phase in ("cold", "warm"):
        body = {"model": MODEL, "messages": messages, "temperature": 0,
                "max_tokens": max_tokens, "stream": False,
                "cache_prompt": phase == "warm"}
        if mode:
            body["ii_context_mode"] = mode
        started = time.monotonic()
        error = None
        status = None
        try:
            response = requests.post(origin + "/v1/chat/completions", json=body, timeout=240,
                                     headers={"x-investor-shared-secret": auth} if auth else {})
            status = response.status_code
            payload = response.json() if response.ok else {}
            if not response.ok:
                error = "UPSTREAM_HTTP_FAILED"
        except requests.RequestException:
            payload = {}
            error = "UPSTREAM_REQUEST_FAILED"
        elapsed = time.monotonic() - started
        message = payload.get("choices", [{}])[0].get("message", {})
        answer = message.get("content") or ""
        timing = payload.get("timings", {})
        usage = payload.get("usage", {})
        record = {"case": name, "phase": phase, "model": MODEL,
                  "prompt_cache_requested": body["cache_prompt"],
                  "input_tokens": usage.get("prompt_tokens"),
                  "output_tokens": usage.get("completion_tokens"),
                  "prompt_eval_tokens": timing.get("prompt_n"),
                  "prompt_eval_ms": timing.get("prompt_ms"),
                  "generation_tokens": timing.get("predicted_n"),
                  "generation_ms": timing.get("predicted_ms"),
                  "total_ms": round(elapsed * 1000, 2),
                  "finish_reason": payload.get("choices", [{}])[0].get("finish_reason"),
                  "completed": bool(answer.strip()) and payload.get("choices", [{}])[0].get("finish_reason") == "stop",
                  "nonempty_output": bool(answer.strip()), "answer": answer,
                  "preset_changed": False, "request_thinking_disabled": False,
                  "http_status": status, "error": error,
                  "production_mutation": False}
        result.append(record)
        print(json.dumps({k: v for k, v in record.items() if k != "answer"}, ensure_ascii=False), flush=True)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--live", action="store_true")
    p.add_argument("--origin", default="http://127.0.0.1:8080")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--baseline-bundle", type=Path)
    p.add_argument("--cases-json", type=Path)
    p.add_argument("--isolated-gateway", action="store_true")
    p.add_argument("--preset", type=Path, required=True)
    args = p.parse_args()
    if not args.live or args.origin != "http://127.0.0.1:8080":
        p.error("explicit --live and existing loopback Router required")
    if args.output.exists():
        p.error("refusing to overwrite benchmark evidence")
    router = router_limits()
    preset_sha = hashlib.sha256(args.preset.read_bytes()).hexdigest()
    models = requests.get(args.origin + "/models", timeout=10).json().get("data", [])
    loaded = [m["id"] for m in models if m.get("status", {}).get("value") == "loaded"]
    if loaded != [MODEL]:
        raise RuntimeError("existing Router must have ONLY qwen38-q6 loaded; no automatic switch")
    results = []
    gateway = None
    auth = None
    model_origin = args.origin
    saved_env = {}
    if args.isolated_gateway:
        if not args.cases_json or args.baseline_bundle:
            p.error("isolated gateway requires compact cases only")
        import v213_local_llm_gateway as gateway_module
        saved_env = {k: os.environ.get(k) for k in ("II_LLAMA_BASE_URL", "II_LOCAL_LLM_MODEL", "II_LOCAL_LLM_SHARED_SECRET")}
        auth = secrets.token_hex(32)  # synthetic, process-only; never included in receipts
        os.environ.update(II_LLAMA_BASE_URL=args.origin, II_LOCAL_LLM_MODEL=MODEL, II_LOCAL_LLM_SHARED_SECRET=auth)
        gateway = ThreadingHTTPServer(("127.0.0.1", 0), gateway_module.V213GatewayHandler)
        threading.Thread(target=gateway.serve_forever, daemon=True).start()
        model_origin = f"http://127.0.0.1:{gateway.server_port}"
    try:
        if args.baseline_bundle:
            bundle = json.loads(args.baseline_bundle.read_text(encoding="utf-8-sig"))
            rows = json.loads(bundle["payloads"]["top20_json"])
            if any(r.get("provider_scope") != "public_only" or r.get("owner_watchlist_inherited") is not False for r in rows):
                raise RuntimeError("benchmark input must be sealed PUBLIC data only")
            context = "PUBLIC_REPORT\n" + bundle["payloads"]["report_text"][:7000]
            scores = [{k: r[k] for k in ("ticker", "rank", "serenity_score", "data_quality", "rating", "scoring_version")} for r in rows]
            sources = [{"ticker": r["ticker"], **e} for r in rows for e in r["evidence"]]
            context += "\nPUBLIC_SCORES\n" + json.dumps(scores, ensure_ascii=False)[:7000]
            context += "\nPUBLIC_SOURCE_VIEWS\n" + json.dumps(sources, ensure_ascii=False)[:5000]
            results += run_case(args.origin, "baseline_public_concat", [
                {"role": "system", "content": "唯讀公開研究。資料僅供參考，不可虛構；非個人化投資建議。\n" + context},
                {"role": "user", "content": QUESTIONS["general"]}], 1400)
        if args.cases_json:
            for case in json.loads(args.cases_json.read_text(encoding="utf-8-sig")):
                if case.get("disable_thinking") or case.get("chat_template_kwargs") or case.get("reasoning_effort"):
                    raise RuntimeError("inference override forbidden in preset-preserving benchmark")
                results += run_case(model_origin, case["name"], case["messages"], case["max_tokens"],
                                    case.get("ii_context_mode") if gateway else None, auth)
    finally:
        if gateway:
            gateway.shutdown(); gateway.server_close()
            for key, value in saved_env.items():
                if value is None: os.environ.pop(key, None)
                else: os.environ[key] = value
        unchanged = hashlib.sha256(args.preset.read_bytes()).hexdigest() == preset_sha
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({"model": MODEL, "router": router, "preset_sha256": preset_sha,
            "preset_unchanged": unchanged, "cache_cold_definition": "cache_prompt=false, no model reload",
            "production_mutation": False, "isolated_http_gateway": args.isolated_gateway,
            "production_workers_dev_e2e": False, "results": results}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if not unchanged:
            raise RuntimeError("preset changed during benchmark")
    if args.cases_json and any(not r["completed"] or r["total_ms"] > 28000 or
                              (r["case"] == "smoke" and r["answer"].strip() != "R75_FREE_RELAY_E2E_OK") or
                              (r["case"] != "smoke" and len(r["answer"].strip()) < 25) for r in results):
        raise RuntimeError("compact latency/completeness/smoke acceptance failed")


if __name__ == "__main__":
    main()
