# Runtime Repair Review: V4 Candidate

## Header
- **Task ID**: QA_CAPACITY_HARNESS_RUNTIME_REPAIR_6922278_V4
- **V4 Namespace**: `D:/Investor-Intelligence-LINE-Pi/_workspace/audit-runtime/qa-capacity-harness-runtime-repair-6922278-v4-1790038449819`
- **V3 Parent Namespace**: `D:/Investor-Intelligence-LINE-Pi/_workspace/audit-runtime/qa-capacity-harness-test-only-repair-6922278-v3-1790010999893`
- **Capacity Module**: Pinned unmodified @ FIXUP_SHA `6922278ac865727fdcdded96535f94aaaabeb8b3`
  - File SHA-256: `aa2b4dc0130f7b6d1548717763dbc7c04f5697c252aa970a525749e2a51456cd`
  - Git Blob: `64ab98a1a5ba0f7c7f6959ec8ba15d03d6b0f0ec`

## Trigger
- **Review**: Master exact-SHA review of V3 candidate (Review SHA `f9a8a88ec9581f3b8a7ebf1fa8679d40d2329983`, branch `qa-capacity-harness-v3`, 16/16 files hash-verified).
- **Verdict**: REWORK
- **Status**: F1/F2 CLOSED (retained, not reopened).
- **Prescribed Defects**: Five harness runtime defects R1-R5.
- **Usage Strictness Ruling**: `requires_fix` with exact minimal boolean guard.
- **Response Persistence**: `web-review-response-v3.json` (SHA-256 `6c2638003a21434f51c188f8d39dc4692772c55e79bcf853c3f39cae1385a45a`) in V3 namespace.
- **Checkpoints**:
  - JEV: PROCEED_TO_IMPLEMENTATION 0.94 (Scope CLEAR 0.95 / SUFFICIENT 0.94; Test Plan ADEQUATE 0.99).
  - Mapika: EXECUTE_R1_R5_REPAIR 0.9416.

## V4 Changes (Scope per Master REPAIR_SCOPE)

### 1. `native_inference_runner.py` (R1-R5)
- **R1 Request Identity**:
  - New constants: `APPROVED_REQUEST_SHA256` (`1fa1910c8db0dda712d6997717e7c5519c22de9465222dd302e96456bcc3f7b0`) and `EXPECTED_REQUEST_FIELDS` (8 approved fields).
  - `load_request_bytes` now takes `approved_digest` (default constant).
  - Rejects top-level field sets different from the 8 approved fields.
  - Applies strict boolean guard: `isinstance dict + set(so) == {"include_usage"} + so["include_usage"] is not True` -> `request_invariant_violated`.
  - Verifies `sha256(raw) == approved_digest` before returning (`request_digest_mismatch`).
  - Dispatches the same verified byte buffer.
- **R2 Source/Authority Binding**:
  - `run_live` requires `plan.authorized_source_sha == EXPECTED_FIXUP_SHA` and `plan.approved_request_sha256 == APPROVED_REQUEST_SHA256` (`run_plan_mismatch`).
  - Authority records must affirmatively declare window `CURRENT` in `run-authority.json` and `operator-handoff.json` plus non-empty operator identity (`authority_stale` otherwise).
  - Authority must carry matching `authorized_source_sha` and `run_plan_sha256` (`authority_mismatch` otherwise).
  - Observed git HEAD must exactly equal `EXPECTED_FIXUP_SHA` (`source_head_mismatch`). `RESOLVE_AT_RUNTIME` rule removed.
  - `run_live` gains test-injection points: `transport=None`, `git_head_fn=None`, `collector=None`.
- **R3 HTTP Framing**:
  - Premature EOF before Content-Length satisfied raises `incomplete_body` (previously break-accept).
  - Chunked branch tracks/decrements `chunk_remaining`, raises `malformed_chunk` on invalid chunk-size lines, validates 2-byte CRLF delimiters and terminating zero chunk, raises `incomplete_body` on EOF mid-chunk.
  - Deadline/cancel/size cap/no-retry semantics unchanged.
- **R4 Cancel Rechecks**:
  - Transport rechecks `cancel_event` + deadline immediately after connect and before sending (`cancelled_during_connect`).
  - `inference_callback` rechecks `cancel_event` after transport completes and before publishing success evidence (`cancelled_after_response`).
  - No retries, no deadline extension.
- **R5 Terminal Path**:
  - Side-effect-free import preserved with `if __name__ == "__main__": sys.exit(main())`.
  - `run_live` persists full returned receipt (including negative outcomes) to `native-receipt.json` via pre-check + `O_EXCL` (never overwritten; `receipt_already_persisted` on re-run).
  - Receipt SHA-256 and request SHA-256 linked into `workload-evidence.json`.
  - `main` returns explicit non-pass process result (1, `RESULT=NON_PASS`) for UNQUALIFIED or incomplete evidence and 0 (`RESULT=PASS`) only for QUALIFIED + complete evidence.

### 2. `test_native_inference_runner.py`
- All 27 V3 tests + F1/F2 retained byte-identical.
- 12 new R1-R5 discriminating regressions added (suite now 39):
  - `test_request_identity_negative_cases`
  - `test_run_live_digest_mismatch_zero_dispatch`
  - `test_run_live_source_head_mismatch_rejected`
  - `test_run_live_authority_stale_rejected`
  - `test_chunked_valid_accepted`
  - `test_incomplete_cl_rejected`
  - `test_malformed_chunk_rejected`
  - `test_cancel_during_connect_zero_post`
  - `test_cancel_after_response_rejected`
  - `test_main_result_codes`
  - `test_receipt_persisted_full_no_overwrite`
  - `test_script_entrypoint_refuses_without_authority`
- `EphemeralServer` gained `chunked_valid`, `incomplete_cl`, `malformed_chunk` modes.
- `import unittest.mock` added.

### 3. `run-plan.json`
- `RESOLVE_AT_RUNTIME` rule replaced by `EXACT_EQUALITY` `source_identity_rule` with `authorized_source_sha` (`6922278ac865727fdcdded96535f94aaaabeb8b3`).
- `approved_request_sha256` declared.
- Authority rule requires affirmative window `CURRENT` + matching `authorized_source_sha` + `run_plan_sha256`.
- `runtime_window=REQUIRES_CURRENT_AFFIRMATIVE_OPERATOR_HANDOFF`.
- `v4_rework` record added.

### 4. Unchanged
- `request.json` (approved payload, `1fa1910c...`)
- `binding-template.json`
- `implementation-review.md` (V3's)
- Capacity module
- Lease/monitoring contract
- Model/backend settings
- Historical evidence

## V4 Identities
- **HARNESS**: `334aea435ee3430b8161610ab820ed40ae0b63004612f9a574bd5cce28784d25`
- **TEST**: `7b0db177362487829abc58e757cf6238ab6a0ca3ad40a208057b6ebd80d560b0`
- **REQUEST**: `1fa1910c8db0dda712d6997717e7c5519c22de9465222dd302e96456bcc3f7b0`
- **RUN_PLAN**: `6b4b0b6559f3741bf224af72f33295fd1ede26bce7e8352229b992723af40809`
- **BINDING_TEMPLATE**: `5a453b450056ce69b55358f840d65a9bcd69e1cd64e322b170f193e16b6482ab`
- **REVIEW** (V3, unchanged): `1c75467ec58b8ce723a0ab451826e94c4b27955ef6094cdc25286e2b0fb46a27`
- **REPAIR_DIFF** (V3->V4): `9353a20ce404af61f7f4da1ec308aa81ca38f185950adccc377be23674e4d339`

## Fixture Evidence
- **Run 1** (First full focused run):
  - `Ran 39 tests in 10.537s` — FAILED (failures=1), exit 1.
  - Single failure: `test_receipt_persisted_full_no_overwrite`.
  - Root Cause: Windows Python build applies LF->CRLF conversion to `os.open()+os.write()` file handles. Persisted `native-receipt.json` on disk (CRLF) did not match digested bytes (LF).
  - Minimal Repair: `os.O_BINARY` added to `os.open` flags at both persistence sites (`freeze_binding` expected-binding.json; `run_live` native-receipt.json).
- **Run 2** (Budgeted focused retry):
  - `Ran 39 tests in 9.483s` — OK, exit 0, 39/39 pass, 0 skips.
- **Logs**: `fixture-logs/v4-fixture-run1.log` and `v4-fixture-run2.log`.

## Remaining State
- **Status**: FIXTURE_PASS
- **Acceptance**: Exact-source acceptance pending the master's next exact-SHA review of the V4 candidate.
- **Native Execution**: `NATIVE_EXECUTION_AUTHORIZED=false`; no live inference.
- **Repository**: No tracked repository changes (V4 candidate lives in the audit-runtime namespace; a review branch will be prepared for exact-SHA review per the transport protocol).
- **Completion**: No completion claim.