# V8 Runtime-Repair Review (QA_CAPACITY_HARNESS_RUNTIME_REPAIR_6922278_V8)

## 1. Scope and parent verdict
This review covers the V8 runtime repair for task `QA_CAPACITY_HARNESS_RUNTIME_REPAIR_6922278_V8`, a child of `QA_CAPACITY_HARNESS_RUNTIME_REPAIR_6922278_V7`. The parent verdict was a master exact-SHA REWORK at review SHA `d98aa796c8648bbb454d185f70c28adcbbf7d28b` (17/17 files verified). The master closed R1, F1/F2, R2-B, R3, R4, R5 canonical-key/argv, R5-L, and R6. The ONLY remaining runtime defect was R2-A HIGH: the default live transport performs `conn.connect()` -> cancel/deadline checks -> `conn.request("POST", ...)`, so a grant that expires during `conn.connect()` can still issue the POST. Route authority for V8 is the master's explicit V7 NEXT_ACTION plus the operator V8 session directive; the recorded Mapika V8 route (PROCEED) is a routing gate, not master approval.

## 2. R2-A post-connect/pre-POST guard (the single V8 repair)
The unchanged validated grant guard is now bound into the DEFAULT live transport via `make_transport(..., grant_check=None)`. `run_live` supplies a closure over the already-validated unchanged auth record calling the existing `_check_window_current(auth)` (finite wall clock + containment; `clock_invalid` / `authority_stale`). Inside the transport, the guard executes after successful `conn.connect()`, after the existing cancel check, after the existing deadline check, and immediately before `conn.request("POST", ...)`. An expired authority or non-finite clock therefore fails closed BEFORE the POST; the connection still closes through the existing `finally: conn.close()` cleanup. The runner diff is exactly 3 hunks vs the V7 baseline (harness 459cd777d6d61e04); every existing authority/cancel/deadline/cleanup check is preserved; no grant extension or restamping; no check was added anywhere else (in particular, no duplicate check was added merely before `transport(...)`).

## 3. Four revalidation stages (named precisely)
1. **admission** — `run_live` (before process attestation/collector/Git/binding).
2. **work-callback entry** — `work_factory`'s `work()` (after the native PRE phase, before the transport call).
3. **pre-transport** — immediately before HTTP dispatch inside `inference_callback`.
4. **post-connect/pre-POST** — NEW: inside the default live transport, after successful `conn.connect()` and after the existing cancel/deadline checks, immediately before `conn.request("POST", ...)`.

## 4. Test changes (3 new; 67 V7 tests byte-for-byte unchanged)
New deterministic tests exercise `make_transport` itself with an in-memory `http.client.HTTPConnection` substitute and a controlled wall clock:
1. expiry during successful connect -> `authority_stale`, ZERO POST requests, empty success evidence, connection closed.
2. valid-window control -> exactly one POST, normal successful path preserved (200/'ok'), connection closed.
3. non-finite clock at the post-connect dispatch boundary -> `clock_invalid`, ZERO POST, no success evidence, connection closed.
The pre-existing `test_expiry_after_native_pre_fails_closed` remains a **SYNTHETIC fixture** (module-contract fake of `run_native_window`); it is NOT native replay evidence and is labeled as such.

## 5. Run-plan changes
`run-plan.json` gained a `v8_rework` documentation section (verdict, closed items, findings, test budget) and the `window_contract.rule` / `authority.rule` wording now names the four revalidation stages precisely. `task_id` remains `QA_CAPACITY_OPERATOR_HANDOFF_NATIVE_ONE_SHOT_6922278_V5` (prospective; not reopened), `fixup_sha`/`authorized_source_sha` remain `6922278ac865727fdcdded96535f94aaaabeb8b3`, approved request digest unchanged (`1fa1910c8db0dda7`).

## 6. Fixture runs (budget: 1 full + 1 diagnosed repair/retry)
- run1 (full): `Ran 70 tests in 16.826s — FAILED (errors=3)`, exit 1. All 67 retained V7 tests pass; the 3 new tests errored at a test-side unit-test API misuse (`patch.object` with a class new-value returns the class, not a mock). Log: `fixture-logs/v8-fixture-run1.log`.
- Diagnosed repair (test-only): `_V8FakeConn.last_instance` tracker; three tests read the tracker instead of the mock return value. Runner/run-plan/request untouched.
- run2 (retry): `Ran 70 tests in 16.828s — OK`, exit 0. 70/70 pass. Log: `fixture-logs/v8-fixture-run2.log`.
No third run; no mis-targeted executions beyond the two documented runs.

## 7. Evidence governance
- `chronology.json` is append-only (entries 1-10) and records the dispatch precondition, Qwen dispatch, implementation, both fixture runs, the diagnosed repair, JEV, Mapika, and delivery.
- Windows documentation correction: `PureWindowsPath("/x").is_absolute()` is FALSE (V7 explanation error; implementation was correct).
- Artifact manifest uses actual relative paths for the fixture logs (`fixture-logs/v8-fixture-run1.log`, `fixture-logs/v8-fixture-run2.log`).
- Raw JEV output preserved; JEV decision grade 2.4 is an ORDINAL SCORE, not a probability.
- V7 packet/branch preserved byte-for-byte; no V7 evidence rewritten.

## 8. Unchanged surface and constraints
Constraints held: 0 native attempts, 0 live inference, no tracked repository changes (edits confined to the V8 namespace), approved request payload byte-identical (`1fa1910c`), capacity module unmodified @ `6922278`, lease/monitoring contract unchanged, binding policy scope unchanged, model/backend settings unchanged, no retry-policy change, no request payload change, R1/F1/F2/R2-B/R3/R4/R5/R5-L/R6 logic not reworked, no old candidates rerun. `NATIVE_EXECUTION_AUTHORIZED=false`; the V5 task ID remains prospective (preparation only).

## 9. Status labels
FIXTURE_PASS=true
SOURCE_ACCEPTANCE=PENDING_EXACT_SHA_REVIEW
NATIVE_EXECUTION_AUTHORIZED=false
CAPACITY_EVIDENCE=UNQUALIFIED
PROVISIONAL_LOCAL_ONLY=true
DEVELOPMENT_COMPLETE=false
FINAL_RELEASE_COMPLETE=false