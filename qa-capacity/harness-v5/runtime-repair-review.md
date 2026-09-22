# V5 Runtime-Repair Review (QA_CAPACITY_HARNESS_RUNTIME_REPAIR_6922278_V5)

## 1. Scope and parent verdict
Task `QA_CAPACITY_HARNESS_RUNTIME_REPAIR_6922278_V5` is the child of `QA_CAPACITY_HARNESS_RUNTIME_REPAIR_6922278_V4`. The parent verdict was a master exact-SHA REWORK at review SHA `7caa887eca1e616ffb5ebb46db960636e7bac6e3` (17/17 files verified, 25m19s). The master closed the review with: R1 request identity resolved on the normal live path; F1/F2 CLOSED_RETAINED; O_BINARY ruling correct_and_complete. The prescribed remaining repairs were R2 (current execution authority), R3 (header framing validation), R4 (final cancel check at publication boundary), R5 (canonical result classification + evidence validation + argv handling), and R6 (checked complete persistence + byte/hash verification). The master reserved the prospective task ID `QA_CAPACITY_OPERATOR_HANDOFF_NATIVE_ONE_SHOT_6922278_V5` for this repair (preparation only, not execution authorization).

V5 core digest: `c0ba20bcf599dd44b8ddcaa0959cb2f5d7889f044a0d7e5669c646dd3bfdfc4d`.
Key file hashes:
- Harness: `8c70e35d6e419f3ad8c6f4ac41e249b2218ab4d9f4122cd9338cbd602f8efb18`
- Test: `749c530df7f0b71d5325ee93a4b1d610a2aba608b9b8e20897118a1e9ae995d9`
- Request: `1fa1910c8db0dda712d6997717e7c5519c22de9465222dd302e96456bcc3f7b0` (byte-identical to V3/V4)
- Run-plan: `6b6a7b2221a18e93eb6ddf3d9e617073a89eedd8c01d259bd4b51d842c1fbc05`
- Binding-template: `5a453b450056ce69b55358f840d65a9bcd69e1cd64e322b170f193e16b6482ab` (unchanged)
- Implementation-review.md: `1c75467ec58b8ce723a0ab451826e94c4b27955ef6094cdc25286e2b0fb46a27` (V3's, unchanged)

## 2. R2 current execution authority
`EXPECTED_TASK_ID` is updated to the new prospective V5 task ID. The run-plan declares `task_id` (V5), `authorized_source_sha` with an `EXACT_EQUALITY` rule, `approved_request_sha256`, and a `window_contract` (uniquely identified `window_id` + `valid_from`/`valid_until` epoch bounds + single-use rule + `CURRENT` is descriptive only). `artifact_identity` declares `authorized_source_sha`, `run_plan_sha256`, `harness_sha256`, and `request_sha256` in both authority records.

`run_live` checks:
- Task ID equality (old closed task rejected).
- Fixup/`authorized_source_sha` equality.
- `run_plan_sha256` == `sha256(plan bytes)`.
- `request_sha256` == approved digest.
- `harness_sha256` == self-digest of the accepted harness file (`pathlib.Path(__file__).resolve().read_bytes()`).
- Cross-record identity equality for all four identity fields.
- `window_id` non-empty and equal across records.
- Numeric (non-bool) validity bounds with `from < until` in both records and equal across records.
- Runtime wall-clock check (`valid_from <= now < valid_until`; outside = `authority_stale`).
- Non-empty operator.
- Default git reader requires `returncode == 0` before accepting stdout (else `source_head_invalid`).

## 3. R3 header framing validation
Header framing is validated before consuming the body:
- All `Content-Length` values are collected; duplicates must be identical (else `conflicting_content_length`); value must be all-digits (else `invalid_content_length`).
- All `Transfer-Encoding` values are collected; duplicates must be identical (else `conflicting_transfer_encoding`).
- Mixed TE+CL is rejected (`mixed_framing`).
- TE must be exactly `chunked` (else `unsupported_transfer_encoding`).
- A 2xx response with neither CL nor TE is rejected (`framing_required`); no-body 3xx/4xx/5xx keep the original read-until-EOF behavior (status check remains the gate).
- The fixed chunk loop (remaining-byte tracking, `malformed_chunk`, `incomplete_body`), deadline, cancel, size cap, and no-retry are preserved.

## 4. R4 final cancel check
Existing checks are retained (`cancelled_during_connect` after connect; `cancelled_after_response` after transport). A new final check `cancelled_after_validation` is added after successful response validation, immediately before publishing the evidence timestamps.

## 5. R5 canonical result classification and entry point
`main` classifies via the canonical `receipt["summary"]["CAPACITY_EVIDENCE"] == "QUALIFIED"` (module field verified in `scripts/v213_qa_capacity.py` @6922278). It fails closed on malformed shapes (summary not a dict, or `CAPACITY_EVIDENCE` not `QUALIFIED`). Evidence validation requires all three timing keys present with numeric (non-bool) values and `request_start_s <= response_complete_s <= callback_end_s` (presence-only checks removed). The `__main__` entry point forwards `sys.argv[1:]` to `main` so real CLI args reach the no-flags check.

## 6. R6 checked complete persistence
A new `_write_complete(fd, data)` loops `os.write` over a memoryview, advancing by the returned byte count and raising `persistence_no_progress` on zero/negative progress. Both persistence sites (`freeze_binding` expected-binding.json and `run_live` native-receipt.json) use it under `O_WRONLY|O_CREAT|O_EXCL|O_BINARY` and then read the closed file back, requiring byte equality (else `persistence_verify_failed`) before treating the binding as frozen or linking the receipt. A failed binding persistence raises before native admission; a failed receipt persistence raises before any passing terminal result.

## 7. Test changes (15 new boundary regressions)
39 V4 tests are retained (F1/F2 untouched) + 15 new V5 boundary regressions = 54 total:
- Canonical module receipts (real `run_window`: `UNQUALIFIED` via `work_raised`; `QUALIFIED` via 3.0s slow work so a `DURING` probe lands interior to the work window; both classified through `main`).
- R2: expired window, mismatched handoff `window_id`, wrong harness digest, old closed task ID, nonzero git result (zero native admission each).
- R3: non-numeric CL, conflicting duplicate CL, mixed TE/CL, unsupported TE (bodies are otherwise valid completion JSON so the failure comes from framing validation).
- R4: validation-time cancel via a `json.loads` wrapper that sets the cancel event during decode (cancel outcome, no success evidence).
- R5: argv forwarded (`main(["unexpected-flag"])` -> 2 without `run_live`) + subprocess regression (unexpected flag -> exit 2 + usage line).
- R6: short-write/no-progress at `freeze_binding` and at the receipt (no evidence file written).

## 8. Fixture run chain and minimal repairs
Raw logs `v5-fixture-run1..4.log`:
- **run1**: 54 tests FAILED (18F+1E) — invalidated: orchestration error, a dispatch script still reading `v4_ns.txt` applied the 10 harness hunks to the V4 namespace; the V4 harness was restored byte-identical from the reviewed branch (`qa-capacity-harness-v4` @ `7caa887`; hash `334aea435ee3430b8161610ab820ed40ae0b63004612f9a574bd5cce28784d25`) and all V4 files verified intact; the hunks were then applied to the V5 namespace and verified.
- **run2**: 54 tests in 10.168s FAILED (7F+1E) — root causes: (a) harness bug, the TE check `len(set(values)) != 1` fired on the zero-header case (empty set has length 0); fixed by guarding with `if transfer_encoding_values`; (b) test bug, the module calls `probe()` with no arguments (test used `probe(_binding)`); (c) test bug, instant work leaves no genuinely interior `DURING` sample, so the canonical `QUALIFIED` fixture uses a 3.0s slow-work wrapper; (d) test bug, the receipt short-write simulation let the loop continuation write the remainder fully (which is correct `_write_complete` behavior); the simulation now returns 0 (no progress) on continuation.
- **run3**: 54 tests in 14.684s FAILED (1F) — root cause: the added `framing_required` check fired on no-body 3xx responses (302 redirect carries no CL/TE) before the status check; fixed by scoping `framing_required` to 2xx only (no-body 3xx/4xx/5xx keep the original read-until-EOF behavior).
- **run4**: 54 tests in 14.699s OK, exit 0 — 54/54 pass, 0 failures, 0 errors, 0 skips.

## 9. Orchestration-error record (V4 namespace corruption and restoration)
During run1, a dispatch script erroneously applied V5 harness hunks to the V4 namespace due to a stale reference to `v4_ns.txt`. This invalidated the run. The V4 harness was immediately restored byte-identical from the reviewed branch (`qa-capacity-harness-v4` @ `7caa887eca1e616ffb5ebb46db960636e7bac6e3`), verified against hash `334aea435ee3430b8161610ab820ed40ae0b63004612f9a574bd5cce28784d25`, and all V4 files were confirmed intact. The V5 hunks were then correctly applied to the V5 namespace and verified before proceeding to run2.

## 10. Unchanged surface and constraints
Constraints held: 0 native attempts, 0 live inference, no tracked repository changes, approved request payload byte-identical, capacity module unmodified @ 6922278, lease/monitoring contract unchanged, binding policy scope unchanged, model/backend settings unchanged, historical namespaces preserved (V4 restored to reviewed state after the orchestration error), R1 and F1/F2 logic not reworked. `NATIVE_EXECUTION_AUTHORIZED=false`; the V5 task ID is prospective (preparation only).

## 11. Status labels
FIXTURE_PASS=true
SOURCE_ACCEPTANCE=PENDING_EXACT_SHA_REVIEW
NATIVE_EXECUTION_AUTHORIZED=false
CAPACITY_EVIDENCE=UNQUALIFIED
PROVISIONAL_LOCAL_ONLY=true
DEVELOPMENT_COMPLETE=false
FINAL_RELEASE_COMPLETE=false
