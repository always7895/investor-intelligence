# V6 Runtime-Repair Review (QA_CAPACITY_HARNESS_RUNTIME_REPAIR_6922278_V6)

## 1. Scope and parent verdict
This review covers the V6 runtime repairs for task `QA_CAPACITY_HARNESS_RUNTIME_REPAIR_6922278_V6`, a child of `QA_CAPACITY_HARNESS_RUNTIME_REPAIR_6922278_V5`. The parent verdict was a master exact-SHA REWORK at review SHA `5c1ac9edcf732f37299751a4d9268601b4bf4b44` (19/19 files verified, ~20m). The master closed the review with final cancel checks (R4), persistence verification (R6), canonical key/argv resolution (R5), and retention of R1/F1/F2. The prescribed remaining repairs were: R2-A (grant expiry during preparation + non-finite bounds), R2-B (cross-namespace grant replay), R3 (present-but-empty Transfer-Encoding), and R5-L (infinite evidence timestamps). Additionally, two evidence/governance `requires_fix` rulings were addressed: `MINIMAL_REPAIR_CHAIN` (budget deviation disclosure + per-run fingerprints + append-only chronology) and `ORCHESTRATION_ERROR` (incident record completion + dispatch precondition).

## 2. R2-A finite bounds and fresh grant validation
The implementation introduces `import math` to enforce finite validity bounds. Validity bounds must be finite (`math.isfinite`) non-Boolean numbers; otherwise, `authority_bounds_invalid` is raised. A counterexample of `1e309` (which evaluates to `inf`) is now rejected. The wall-clock value must itself be finite; otherwise, `clock_invalid` is raised. Crucially, the unchanged grant is revalidated immediately before native admission and workload dispatch. A second wall-clock check occurs right before the `run_native_window` call, with no extension or restamping. This ensures that a grant expiring during process attestation, collection, Git resolution, binding persistence, or request validation cannot reach native admission.

## 3. R2-B namespace-bound single-use grant
Both authority records must declare an identical non-empty `run_namespace`. `run_live` validates that the declared `run_namespace` resolves to the actual execution namespace via `pathlib` resolve comparison; otherwise, `authority_mismatch` is raised. Combined with existing per-namespace exclusive persistence protection (`expected-binding.json` + `native-receipt.json` `O_EXCL` pre-checks), the same grant cannot be replayed through another namespace or re-attempted in the bound one. The capacity module and canonical capacity lease remain unchanged.

## 4. R3 Transfer-Encoding presence vs value
Transfer-Encoding header presence is now tracked separately from a nonempty value using a `te_present` counter. A present but empty or whitespace-only TE value is rejected (`empty_transfer_encoding`) before body consumption. Content-Length (CL) combined with any TE field (including empty) is rejected (`mixed_framing`). The numeric-CL, conflicting-CL, unsupported-nonempty-TE, chunked, deadline, cancel, and no-retry behaviors are retained. `framing_required` remains scoped to 2xx responses.

## 5. R5-L finite evidence validation
The three terminal evidence values must additionally be finite (`math.isfinite`) in addition to being non-Boolean numeric and ordered. `+/-inf` and `NaN` evidence now fail closed (`RESULT=NON_PASS`, exit 1). A finite control case still passes. The resolved canonical-key and argv defects are not reopened.

## 6. Test changes (7 new boundary regressions)
The test suite retains 54 V5 tests (F1/F2 untouched) and adds 7 new V6 boundary regressions, totaling 61 tests:
1. **R2-A expiry-during-preparation**: Grant valid for 5ms; collector sleeps 200ms; results in `authority_stale` with zero native admission.
2. **R2-A non-finite bounds**: `valid_until=1e309`; results in `authority_bounds_invalid` with zero admission.
3. **R2-B same-grant/different-namespace**: Identical plan/request/authority/handoff copied to a fresh namespace; results in `authority_mismatch` with zero admission.
4. **R2-B duplicate attempt in bound namespace**: First attempt persists receipt; second is rejected with `receipt_already_persisted`/`binding_already_frozen`.
5. **R3 empty TE**: CL + empty TE header, otherwise valid completion JSON; results in `empty_transfer_encoding`.
6. **R3 whitespace TE**: CL + whitespace TE; results in `empty_transfer_encoding`.
7. **R5-L infinite evidence**: All-inf, -inf, and NaN cases are rejected; finite control passes.

## 7. Fixture run (single budgeted run)
One run was executed (the budgeted one). Results: `Ran 61 tests in 15.804s OK`, exit 0. 61/61 pass, 0 failures, 0 errors, 0 skips. No repair was needed. No mis-targeted runs occurred in V6; the dispatch precondition was applied, resolving the destination from the explicit V6 namespace and verifying V5 baseline hashes before editing.

## 8. Evidence corrections (chronology, incident record, dispatch precondition)
- **Chronology**: `chronology.json` (append-only) records the run-budget deviation (runs 2/3/4 = three runs vs. the documented one-full-run-plus-one-retry budget, no extension authorization). Per-run harness/test fingerprints are preserved where available (run1 harness `334aea43`, run3/run4 test `749c530d`, run4 harness `8c70e35d`, run-plan `6b6a7b22` for all runs). Intermediate states are recorded but not preserved as standalone artifacts.
- **Incident Record**: The V4 orchestration-error incident record is completed. The resolved erroneous destination was the V4 namespace. The affected file set was `native_inference_runner.py` only. Pre-error hash `334aea43`, detected `8d0cb8cb`, post-restoration `334aea43`. Accidentally modified bytes were not preserved. Post-restoration hash inventory for all six V4 candidate files was verified byte-identical to the reviewed branch.
- **Dispatch Precondition**: Future writes must resolve the destination from the current task's explicit namespace, verify the task marker + expected baseline, reject immutable parent namespaces, and verify post-apply hashes.

## 9. Unchanged surface and constraints
Constraints held: 0 native attempts, 0 live inference, no tracked repository changes, approved request payload byte-identical, capacity module unmodified @ `6922278`, lease/monitoring contract unchanged, binding policy scope unchanged, model/backend settings unchanged, historical namespaces preserved, R1/R4/R5-canonical/R6 and F1/F2 logic not reworked, the four V5 raw logs unaltered, no old candidates rerun. `NATIVE_EXECUTION_AUTHORIZED=false`; the V5 task ID remains prospective (preparation only).

## 10. Status labels
FIXTURE_PASS=true
SOURCE_ACCEPTANCE=PENDING_EXACT_SHA_REVIEW
NATIVE_EXECUTION_AUTHORIZED=false
CAPACITY_EVIDENCE=UNQUALIFIED
PROVISIONAL_LOCAL_ONLY=true
DEVELOPMENT_COMPLETE=false
FINAL_RELEASE_COMPLETE=false
