# V7 Runtime-Repair Review (QA_CAPACITY_HARNESS_RUNTIME_REPAIR_6922278_V7)

## 1. Scope and parent verdict
This review covers the V7 runtime repairs for task `QA_CAPACITY_HARNESS_RUNTIME_REPAIR_6922278_V7`, a child of `QA_CAPACITY_HARNESS_RUNTIME_REPAIR_6922278_V6`. The parent verdict was a master exact-SHA REWORK at review SHA `36c07a364425af90cc5e168436e2736629109cd3` (17/17 files verified). The master closed R3 (Transfer-Encoding) and R5-L (finite evidence timestamps) and confirmed the finite-bound and pre-admission portions of R2-A. The prescribed remaining repairs were strictly: R2-A (revalidate the unchanged window at callback entry and immediately before HTTP dispatch; expiry after native PRE must fail closed) and R2-B (canonical ABSOLUTE namespace; reject relative grants; prevent same-grant replay through another namespace; preserve same-namespace single-use). Route authority for V7 is the master's explicit V6 NEXT_ACTION plus the operator session-rotation directive; the recorded Mapika V7 route was a low-confidence tie (EXECUTE=CLARIFY 0.4065, certainty 0.1945) and is recorded as-is, not as Mapika approval.

## 2. R2-A revalidation at callback entry and immediately before HTTP dispatch
Two shared helpers were introduced: `_validate_window_records(auth, handoff)` (finite non-Boolean bounds, `valid_from < valid_until`, identical bounds across both records) and `_check_window_current(auth)` (finite wall clock + containment of the unchanged grant; raises `clock_invalid` / `authority_stale`). The inline admission logic in `run_live` now calls these helpers, so the accepted finite-bound / finite-clock enforcement is retained byte-for-byte in behavior. The revalidation points are now: (1) admission in `run_live` (before process attestation/collector/Git/binding), (2) immediately before the `run_native_window` call (native admission), (3) at work-callback entry in `work_factory`'s `work()` (after the native PRE phase, before the transport call), and (4) immediately before HTTP dispatch inside `inference_callback` (directly before `transport(request_bytes, cancel_event)`). A grant that expires after the native PRE sample but before/during the native HTTP dispatch raises `authority_stale` at point (3) or (4); the capacity module records an UNQUALIFIED receipt, no evidence timestamps are written, and no successful evidence publication occurs. The `auth` binding is an optional keyword parameter on `inference_callback`/`work_factory` (default `None`), so all 61 pre-existing call sites are untouched; `run_live` always binds the parsed grant.

## 3. R2-B canonical ABSOLUTE namespace
In `run_live`, after the existing string equality check between the two records' `run_namespace`, the declared namespace must satisfy `pathlib.PurePath(ns_a).is_absolute()`; a relative grant is rejected with `authority_mismatch` before any further check. The existing resolved-namespace comparison (`pathlib.Path(ns_a).resolve() != pathlib.Path(namespace).resolve()` → `authority_mismatch`) is retained, so a deceptively-absolute but non-anchored path (e.g. root-only `/x`) or any different absolute namespace is still rejected. Same-grant/different-namespace replay is therefore prevented by the resolved comparison, and same-namespace single-use is preserved by the unchanged per-namespace exclusive persistence protection (`expected-binding.json` + `native-receipt.json` O_EXCL pre-checks). The capacity module and canonical capacity lease remain unchanged.

## 4. Test changes (7 new boundary regressions)
The test suite retains all 61 V6 tests (F1/F2 and all closed R-series logic untouched) and adds 7 new V7 boundary regressions, totaling 68 planned / 67 executed suite members:
1. **R2-A work-callback entry revalidation**: expired grant bound to `work_factory`; `work()` raises `authority_stale` with zero transport calls and empty evidence.
2. **R2-A pre-dispatch revalidation**: expired grant bound to `inference_callback`; raises `authority_stale` before the transport call, zero transport calls.
3. **R2-A valid-grant control**: in-window grant; `work()` dispatches exactly once and records all three finite evidence timestamps.
4. **R2-A expiry-after-native-PRE fails closed**: end-to-end through `run_live` with a module-contract fake (`run_native_window` mimics PRE-phase latency then work invocation; work failure → UNQUALIFIED receipt). Grant valid at admission (0.3s), expires during the PRE phase (fake latency 0.45s). Asserts UNQUALIFIED receipt with `authority_stale` reason, zero transport calls, empty in-memory and persisted evidence, and that the negative receipt is still persisted to `native-receipt.json`.
5. **R2-B relative namespace grant**: both records declare the identical relative namespace (equality passes; absoluteness rejects) → `authority_mismatch`, zero transport calls.
6. **R2-B root-only namespace grant**: both records declare `/x` (absolute on Windows but not anchored) → `authority_mismatch` via the retained resolved comparison, zero transport calls.
7. **Retained (pre-existing, not reopened)**: same-grant/different-namespace replay (`test_authority_namespace_mismatch`) and same-namespace duplicate attempt (`test_duplicate_attempt_same_namespace_rejected`) remain the bounded single-use / cross-namespace protections.

Note: item 7 is a retention statement, not a new test; the new count is 6, giving 61 + 6 = 67 suite members. The "7" in the heading counts the retention item for completeness of the R2-B requirement mapping.

## 5. Run-plan changes
`run-plan.json` gained a `v7_rework` documentation section (verdict, closed items, findings, test budget) and sharpened the `window_contract.rule` / `authority.rule` wording to state the four revalidation points, the fail-closed expiry-after-PRE requirement, and the canonical-ABSOLUTE-namespace requirement. `task_id` remains `QA_CAPACITY_OPERATOR_HANDOFF_NATIVE_ONE_SHOT_6922278_V5` (prospective; the new-task-ID requirement was satisfied at V5 and not reopened), `fixup_sha`/`authorized_source_sha` remain `6922278ac865727fdcdded96535f94aaaabeb8b3`, and the approved request digest is unchanged.

## 6. Fixture run (single budgeted run)
One run was executed (the budgeted one). Command: `python -B -m unittest test_native_inference_runner -v`. Results: `Ran 67 tests in 16.359s OK`, exit 0. 67/67 pass, 0 failures, 0 errors, 0 skips. No repair was needed. No mis-targeted runs occurred in V7. The dispatch precondition was applied: the destination was resolved from the explicit V7 namespace, the V6 baseline hashes (harness `b17b40db`, test `4c87e17d`, request `1fa1910c`, run-plan `fb8de167`, binding-template `5a453b45`, implementation-review `1c75467e`) were verified before editing, and post-apply hashes were verified against the intended change set.

## 7. Evidence governance
- **Chronology**: `chronology.json` in the V7 namespace is append-only and includes the dispatch-precondition application record, the baseline-verification record, the single fixture-run record, and this review's artifact hashes.
- **No incident record**: no orchestration error or budget deviation occurred in V7.
- **Historical namespaces**: V3/V4/V5/V6 namespaces and review branches are preserved unmodified.

## 8. Unchanged surface and constraints
Constraints held: 0 native attempts, 0 live inference, no tracked repository changes, approved request payload byte-identical (`1fa1910c`), capacity module unmodified @ `6922278`, lease/monitoring contract unchanged, binding policy scope unchanged, model/backend settings unchanged, R1/F1/F2/R3/R4/R5-canonical-key-argv/R5-L/R6 logic not reworked, no old candidates rerun. `NATIVE_EXECUTION_AUTHORIZED=false`; the V5 task ID remains prospective (preparation only).

## 9. Status labels
FIXTURE_PASS=true
SOURCE_ACCEPTANCE=PENDING_EXACT_SHA_REVIEW
NATIVE_EXECUTION_AUTHORIZED=false
CAPACITY_EVIDENCE=UNQUALIFIED
PROVISIONAL_LOCAL_ONLY=true
DEVELOPMENT_COMPLETE=false
FINAL_RELEASE_COMPLETE=false