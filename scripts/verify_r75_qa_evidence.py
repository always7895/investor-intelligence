"""No-network release gate for the source-bound isolated live Q&A receipt."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))  # embedded CPython ._pth
from v213_qa_live_gate import source_manifest
from v213_compact_qa_gateway import POLICY, resolve_model_id

ROOT = Path(__file__).resolve().parents[1]

def verify(data, manifest=None, require_pi=False):
    def require(ok, code):
        if not ok: raise ValueError(code)
    require(type(data.get("schema_version")) is int and data['schema_version'] in (1, 2) and data.get("status") == "PASS", "LIVE_GATE_NOT_PASS")
    pi_backend = data.get('schema_version') == 2
    pi_profile = json.loads((ROOT / 'config/v213-pi-inference-v1.json').read_text(encoding='utf-8'))
    require(not require_pi or pi_backend, 'PI_LIVE_QUALIFICATION_REQUIRED')
    selected = pi_profile['model_id'] if pi_backend else 'qwen38-q6'
    require(data.get("scope") in (None, "FULL_LIVE"), "READINESS_ONLY_NOT_RELEASE_QUALIFICATION")
    for field in ("isolated_resources_deleted", "preset_unchanged", "source_unchanged_during_benchmark", "synthetic_public_fixture"):
        require(data.get(field) is True, "LIVE_PROOF_MISSING:"+field)
    require(data.get("production_mutation") is False and data.get("real_line_sent") is False, "PRODUCTION_BOUNDARY")
    require(data.get('exact_model') == selected and data.get('request_enable_thinking') is pi_backend, 'MODEL_PROFILE_MISMATCH')
    if pi_backend:
        require(data.get('inference_backend') == 'pi' and data.get('thinking_level') == 'xhigh', 'PI_XHIGH_PROFILE_REQUIRED')
        processes = data.get('router_processes', [])
        require(data.get('router_processes_unchanged') is True and isinstance(processes, list) and len(processes) == 2, 'PI_ROUTER_PROCESS_PROOF_INVALID')
        require(all(isinstance(p, dict) and type(p.get('pid')) is int and p['pid'] > 0 and isinstance(p.get('started_utc'), str)
                    and isinstance(p.get('binary_sha256'), str) and len(p['binary_sha256']) == 64 for p in processes)
                and any(p.get('parent_pid') == q['pid'] for p in processes for q in processes if p != q), 'PI_ROUTER_PROCESS_IDENTITY_INVALID')
    # The original receipt retains the exact test-driver hash for provenance.
    # A driver-only refactor is not an executable Worker/Gateway change. Bind
    # the Worker/Gateway runtime exercised here, not later verifier tooling.
    # Windows/package receipts separately bind launcher, installer and refresh code.
    runtime_only = lambda files: {p:h for p,h in files.items() if p != 'scripts/v213_qa_live_gate.py'}
    recorded = data.get("source_manifest")
    require(isinstance(recorded, dict), "LIVE_SOURCE_MANIFEST_MISSING")
    require(runtime_only(recorded) == runtime_only(source_manifest() if manifest is None else manifest), "LIVE_SOURCE_MANIFEST_MISMATCH")
    capacity = data.get("router", {}).get("models_max")
    require(type(capacity) is int and capacity == 1, "ROUTER_CAPACITY_MISMATCH")
    canonical = data.get("canonical_model", selected)
    if "model_catalog" in data or canonical != selected or pi_backend:
        require(isinstance(canonical, str) and bool(canonical) and resolve_model_id(selected, data.get("model_catalog")) == canonical, "MODEL_CATALOG_PROOF_INVALID")
    if pi_backend: require(canonical == selected, 'PI_CANONICAL_ID_REQUIRED')
    policy_hash = hashlib.sha256(json.dumps(POLICY, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    require(data.get("compact_policy_sha256") == policy_hash, "LIVE_POLICY_MISMATCH")
    require(data.get("active_percentage") == 100 and data.get("convergence") == "PASS_REAL_ISOLATED", "READINESS_NOT_PROVEN")
    proofs = data.get("readiness", [])
    require(bool(proofs), "READINESS_PROOF_MISSING")
    for proof in proofs:
        require(proof.get("ready") is True and proof.get("no_write") is True and proof.get("worker_version") == data.get("worker_version") and proof.get("parser_schema") == "v213-r75-sec-filing-provenance-v1" and proof.get("compact_policy_sha256") == policy_hash and proof.get("publication_contract_sha256") == "9b96f2fd68318e6476dc00d0d003162c0343d2aece5ef25f522fe7c33dca7bfd", "READINESS_PROOF_INVALID")
    expected = {(c,p) for c in ("smoke", "general", "ticker", "methodology", "evidence") for p in ("cold", "warm")}
    rows = data.get("results", [])
    require(len(rows) == len(expected) and {(r.get("case"),r.get("phase")) for r in rows} == expected, "LIVE_CASE_MATRIX_INCOMPLETE")
    for row in rows:
        require(row.get("pass") is True and row.get("finish_reason") == "stop" and row.get("model") == canonical and row.get("http_status") == 200, "LIVE_RESPONSE_INVALID")
        require(type(row.get("total_ms")) in (int,float) and 0 < row["total_ms"] <= POLICY["absolute_budget_ms"], "LIVE_LATENCY_FAILED")
        if pi_backend:
            proof = row.get('pi_proof', {})
            require(proof.get('provider') == pi_profile['provider'] and proof.get('thinking_level') == 'xhigh'
                    and proof.get('xhigh_payload_validated') is True and type(proof.get('tools_executed')) is int
                    and proof['tools_executed'] == 0 and proof.get('qualification_cache_prompt') is (row['phase'] == 'warm'), 'PI_CALL_PROOF_INVALID')
            require(type(proof.get('thinking_chars')) is int and proof['thinking_chars'] >= 0, 'PI_THINKING_METRIC_MISSING')
            if row['case'] != 'smoke': require(proof['thinking_chars'] > 0, 'PI_THINKING_NOT_OBSERVED')
            usage = row.get('pi_usage', {})
            require(all(type(usage.get(k)) is int and usage[k] >= 0 for k in ('input_tokens', 'output_tokens', 'cache_read_tokens')), 'PI_USAGE_INVALID')
            require(0 < usage['input_tokens'] + usage['cache_read_tokens'] <= 4096, 'PROMPT_TOKEN_PROOF_INVALID')
            require(0 < usage['output_tokens'] <= pi_profile['max_output_tokens'], 'OUTPUT_TOKEN_PROOF_INVALID')
            if row['phase'] == 'cold': require(usage['cache_read_tokens'] == 0, 'PI_COLD_CACHE_PROOF_INVALID')
        else:
            usage = row.get("usage", {})
            require(type(usage.get("prompt_tokens")) is int and 0 < usage["prompt_tokens"] <= 1500, "PROMPT_TOKEN_PROOF_INVALID")
            require(type(usage.get("completion_tokens")) is int and 0 < usage["completion_tokens"] <= POLICY["max_output_tokens"], "OUTPUT_TOKEN_PROOF_INVALID")
        if row["case"] != "smoke": require(isinstance(row.get("answer"),str) and len(row["answer"]) >= 25 and not row["answer"].startswith("LOCAL_MODEL_"), "EMPTY_OR_ERROR_ANSWER")
    require(data.get("seven_field_line_reply") == "PASS_REAL_WORKER_MOCK_LINE" and data.get("bilingual_field_count") == 7 and data.get("top20_rows") == 20 and data.get("production_health_presentation") == "seven_fields", "SEVEN_FIELD_LINE_REPLY_UNPROVEN")
    require(data.get("line_presentation") == "flex_carousel" and data.get("line_message_count") == 4 and data.get("line_values_match") is True, "LINE_FLEX_UI_UNPROVEN")
    require(data.get("text_fallback_values_match") is True and type(data.get("text_message_count")) is int and 1 <= data["text_message_count"] <= 5, "LINE_TEXT_FALLBACK_UNPROVEN")
    require(data.get("reference_job") == "PASS_REAL_WAITUNTIL_SYNTHETIC_LINE", "REFERENCE_JOB_UNPROVEN")
    for field in ("stale_lease", "replay", "exact_model_mismatch"): require(data.get(field) == "PASS", "NEGATIVE_GATE_UNPROVEN:"+field)
    return {"status":"PASS", "live_qa":"PASS", "live_free_relay_smoke":"PASS", "release_ready":True, "max_latency_ms":max(r["total_ms"] for r in rows), "production_mutation_by_ci":False}

if __name__ == "__main__":
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("--receipt",type=Path,required=True)
    p.add_argument('--require-pi', action='store_true')
    args=p.parse_args(); print(json.dumps(verify(json.loads(args.receipt.read_text(encoding="utf-8-sig")), require_pi=args.require_pi)))
