# V8.1 Evidence-Only Correction Record (append-only)

Task: QA_CAPACITY_HARNESS_RUNTIME_REPAIR_6922278_V8
Namespace: D:/Investor-Intelligence-LINE-Pi/_workspace/audit-runtime/qa-capacity-harness-runtime-repair-6922278-v8-1790073020041
Trigger: master exact-SHA review of V8 candidate at REVIEW_SHA=ee86f15ba73ab4a0fdcf158dc7d8cebfed957601 (branch qa-capacity-harness-v8, 18 files; raw response preserved: _master_response_v8_raw.txt / web-review-response-v8.json in the namespace)

## Master V8 verdict (authoritative)

VERDICT=REWORK; SHA_VERIFIED=true; VERIFIED_FILES=18/18; FAILED_FETCH_OR_HASH_CHECKS=[].
R2-A_STATUS=CLOSED — the post-connect/pre-POST runtime repair is accepted within its review scope (master independently re-executed the run_live path: expiry-during-connect 0 POST authority_stale; valid 1 POST; non-finite clock 0 POST clock_invalid; cancel retained; guard-removal control reproduces the old failure). SOURCE_ACCEPTANCE=ACCEPT_SCOPED_RUNTIME_REPAIR; PACKET_ACCEPTANCE=REWORK_ROUTING_EVIDENCE_ONLY; RUNTIME_REPAIR_SCOPE=NONE.
SOLE FINDING: EVAL-IDENTITY-01 (HIGH, evidence-only): mapika-result.json wrapper declares model=decider-v10 / served_model_id=Mapika-decider-2b-v10, but the raw completion embedded in the same file declares model=Qwen3.8-27B-EXL3-5.5bpw-v2 on the executor port-5000 chat-completions route; the recorded PROCEED answer is not attributable to the declared Mapika decider; /v1/models catalog observation does not establish the completion's model.

## Diagnosis (per master instruction: wrong route invoked vs wrong response attached)

WRONG ROUTE INVOKED. The routing call was sent to the TabbyAPI executor endpoint http://127.0.0.1:5000/v1/chat/completions with model=Mapika-decider-2b-v10 (a catalog label); the returned completion's model field — the controlling execution evidence — is Qwen3.8-27B-EXL3-5.5bpw-v2, i.e. TabbyAPI processed the request with the Qwen executor model, not Mapika. The wrapper then mis-declared the result as Mapika based on the catalog label. No genuine existing Mapika result existed for the V8 candidate, so the master-authorized single re-run was performed through the existing authorized Mapika service (the decider-system-one CPU sidecar — the same service that produced the V7 mapika-result.json shape).

## Service/model identity verification (not catalog label)

- Sidecar process: `C:\Users\moon9\AppData\Local\Programs\Python\Python312\python.exe -m uvicorn sidecar_server:app --app-dir D:\AI\decider-system-one-dual --host 127.0.0.1 --port 8000 --workers 1` (PID 37300, listening 127.0.0.1:8000).
- Load profile: `D:/AI/decider-system-one-dual/profiles/system-one/mapika-decider-2b.json` -> model_dir `D:\Models\Mapika-decider-2b-v10` (cpu_threads 12, max_state_tokens 1536).
- Revision record: `Mapika/decider-2b` sha b37f7e1ba3fbc9238004cf531fabbee2619973fd -> destination `D:\Models\Mapika-decider-2b-v10`.
- Weights: `D:/models/Mapika-decider-2b-v10/model.safetensors` sha256 1bf79b6aa6966a0faf930940799b1f54a831368d9738123722d483597c0ac2e7; decider_config.json version=v10 (base Qwen/Qwen3.5-2B-Base, release 2026-09-19, parent decider-2b v8).
- Health report: {"ok":true,"backend":"cpu","model":"decider-v10","device":"cpu","dtype":"torch.bfloat16","max_state_tokens":1536,"torch":"2.12.1+cpu","cuda_available":false,"cpu_threads":12}.
- Response self-identity: the evaluation response declares model=decider-v10 (the sidecar's own response field for this call).

## Single authorized routing evaluation (bound to candidate)

Endpoint: http://127.0.0.1:8000/v1/systemone (decider-system-one extension `system_one_decide` tool). Bound to:
REVIEW_SHA=ee86f15ba73ab4a0fdcf158dc7d8cebfed957601
CORE_DIGEST=0247939d3357c39992b1c11cecebf4898149a9ad1c686ba1cdb78a23f866168d
JEV_RESULT_SHA256=2a7c83ac34332e8df49d421bc65f6d38f54e5a61efa724cbb9dae74ed61e8d52

Response (raw): {"model":"decider-v10","answers":{"routing_decision":{"type":"choice","choice":"PROCEED","confidence":0.9855,"certainty":0.9248,"probabilities":{"PROCEED":0.9855,"REWORK_FIRST":0.0118,"ESCALATE":0.0027}}},"usage":{"input_tokens":600,"output_tokens":0}}

Result: PROCEED (confidence 0.9855, certainty 0.9248). Routing gate only — route authority = master V8 next_action (evidence-only correction) + operator V8 session directive; not master approval. Full attributable request/response: mapika-v8-routing-attributable.json.

## Preserved (unchanged, per master instruction)

- Accepted V8 harness, tests, request, plan, core manifest, and both fixture logs: byte-for-byte unchanged in this commit.
- Disputed mapika-result.json: preserved as historical evidence, NOT overwritten.
- No additional fixture run; no JEV rerun; no runtime-repair iteration; no native execution authorization change (NATIVE_EXECUTION_AUTHORIZED=false); no Qwen or other provider substituted for Mapika.

## Deliverables in this correction commit

1. chronology.json — append-only entries 12-13 (master V8 review received; EVAL-IDENTITY-01 diagnosis + attributable re-run).
2. evidence-correction-v8.1.md — this append-only correction record.
3. mapika-v8-routing-attributable.json — attributable routing request/response with the full service-identity chain.
4. artifact-manifest.json — evidence manifest updated for the 20-file packet (2 new files + re-hashed append-only chronology).

## Post-correction state

SOURCE_ACCEPTANCE per master: ACCEPT_SCOPED_RUNTIME_REPAIR (may be lifted without re-reviewing accepted code once this evidence checkpoint is accepted). A separate native one-shot authorization and affirmative operator handoff are still required for any native execution.