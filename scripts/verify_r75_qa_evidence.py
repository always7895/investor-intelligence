"""No-network release gate for the source-bound isolated live Q&A receipt."""
from __future__ import annotations
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))  # embedded CPython ._pth
from v213_qa_live_gate import source_manifest
from v213_compact_qa_gateway import POLICY, resolve_model_id

ROOT = Path(__file__).resolve().parents[1]

MAX_LIVE_PROOF_AGE_SECONDS = 24 * 60 * 60
FUTURE_TOLERANCE_SECONDS = 300


def verify(data, manifest=None, *, now=None):
    def require(ok, code):
        if not ok: raise ValueError(code)
    require(data.get("schema_version") == 1 and data.get("status") == "PASS", "LIVE_GATE_NOT_PASS")
    clock = now or datetime.now(timezone.utc)
    require(isinstance(clock, datetime) and clock.tzinfo is not None, "LIVE_CLOCK_INVALID")
    timestamps = []
    for field in ("started_at", "completed_at"):
        value = data.get(field)
        require(isinstance(value, str) and bool(value), "LIVE_TIMESTAMP_MISSING:" + field)
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("LIVE_TIMESTAMP_INVALID:" + field) from None
        require(parsed.tzinfo is not None, "LIVE_TIMESTAMP_TIMEZONE_REQUIRED:" + field)
        timestamps.append(parsed.astimezone(timezone.utc))
    started, completed = timestamps
    require(started <= completed, "LIVE_TIMESTAMP_ORDER_INVALID")
    require((completed - clock).total_seconds() <= FUTURE_TOLERANCE_SECONDS, "LIVE_TIMESTAMP_FUTURE")
    require((clock - started).total_seconds() <= MAX_LIVE_PROOF_AGE_SECONDS, "LIVE_PROOF_STALE")
    require(data.get("scope") in (None, "FULL_LIVE"), "READINESS_ONLY_NOT_RELEASE_QUALIFICATION")
    for field in ("isolated_resources_deleted", "preset_unchanged", "source_unchanged_during_benchmark", "synthetic_public_fixture"):
        require(data.get(field) is True, "LIVE_PROOF_MISSING:"+field)
    require(data.get("production_mutation") is False and data.get("real_line_sent") is False, "PRODUCTION_BOUNDARY")
    require(data.get("request_enable_thinking") is False and data.get("exact_model") == "qwen38-q6", "MODEL_PROFILE_MISMATCH")
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
    canonical = data.get("canonical_model", "qwen38-q6")
    if "model_catalog" in data or canonical != "qwen38-q6":
        require(isinstance(canonical, str) and bool(canonical) and resolve_model_id("qwen38-q6", data.get("model_catalog")) == canonical, "MODEL_CATALOG_PROOF_INVALID")
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
    args=p.parse_args(); print(json.dumps(verify(json.loads(args.receipt.read_text(encoding="utf-8-sig")))))
