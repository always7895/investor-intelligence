# Current state / 目前狀態

Updated 2026-09-30 by Claude Code (sole tracked writer; Sonnet 5.5 after the operator model switch). Previous text: `git show 4c8eb3e:state/STATUS.md` (before OPTIONS-GLOBAL-01 final gates); `git show b9a05c4:state/STATUS.md` (before ORDERS-V3-AUTOUPDATE-01 slice A1); `git show e049261:state/STATUS.md` (before rollout v9); `git show 902d893:state/STATUS.md` (ORDERS-V3-01 before acceptance); `git show b0860c9:state/STATUS.md` (options, runbook); `git show ca571aa:state/STATUS.md` (rollout v6); `git show 06a7f28:state/STATUS.md` (L18-5351 detail); `git show 4be0888:state/STATUS.md` (ORDERS-V2-01); `git show 349a332:state/STATUS.md`; `git show 914f0e6:state/STATUS.md`; earlier `git show e2365cd:state/STATUS.md`, `git show 5b15984:state/STATUS.md`, `git show 3ac39a1:state/STATUS.md` (full production record), `git show a8c6e58:state/STATUS.md`, `git show 59049db:state/STATUS.md`, `git show 38860e7:state/STATUS.md`; V12 `git show 0f5358b:state/STATUS.md`. Release identity stays in `README.md`. Root and source `AGENTS.md` override older control-plane text in this file's history.

## Identity

- Branch `fix/options-provenance-audit`, base HEAD `4c8eb3e`. CI on this branch ends COMPLETED_SKIPPED by design (not PASS); non-release-qualified (LOCAL_SOURCE_CHECKOUT). DEVELOPMENT_COMPLETE=false; FINAL_RELEASE_COMPLETE=false.
- Production runs `e049261` (rollout v9), unchanged this session. Frozen candidate = 15 files (prior 14 + `tests/test_current_release_lane.py`); resulting HEAD after joint acceptance is recorded in the session commit/push receipt (`_archive/session-20260930-options-global/`), not pre-written here.

## OPTIONS-GLOBAL-01 — source-only public-options repair (round-3; final gates 2026-09-30)

Bounded repair of one public covered-call caller (truthful failure categories, per-row freshness, explicit aliases, optional-numeric fail-closed). Authority `astra-options-contract.result.txt` + amendment-01/02/03; `cloud/src/qa.ts` unchanged (SHA256 `0107ACA6…681EB2`). R1/R2 substance independently accepted (180 probes + 28 bridge). R3 fixed the last Astra r2 blocker **R2-I2a**: a JSON big-integer (`10**309`) makes `math.isfinite` raise `OverflowError`, uncaught → whole-publisher crash. Fix (single `finite()` helper): reject bool/str/container, then `float(value)` in a guard → `STRICT_FINITE_NUMBER_REQUIRED: {name}`, then `math.isfinite` on the float; `publish_sealed_snapshot.py` unchanged. Regression: representation matrix in `tests/test_v213_market_products.py` + 3 bridge cases in `tests/fixtures/options_global_publisher_cases.py`. Amendment-03: two stale TEXT-mode expectations updated at `cloud/test/v213-covered-call.test.ts:57` and `cloud/test/v213-line-aliases.test.ts:106`.

F1 (Astra final REJECT): staged CRLF (255) in the then-untracked fixture `cloud/test/fixtures/options-global-publisher.json`. r2 fix (line-endings only, no `.gitattributes`/config exception): generator writes `newline="\n"`, fixture LF-normalized (49537→49282 bytes; 0 CR / 255 LF); proof `options-global-publisher.eol-normalize-verify.r2.py` vs preimage shows every `options_body`/`quotes_body` hash identical. Detail in `claude-options-writer.r1/r2/r3.result.txt`, `astra-integrated-review.r3.result.txt` and git.

## OPTIONS-GLOBAL-01 test isolation — amendment-04 (2026-09-30)

Authority `astra-options-contract.amendment-04.txt` (TEST-ISOLATION only; NOT implementation acceptance or release GO). One added tracked file `tests/test_current_release_lane.py` isolates the operation-lock selftest: each invocation builds a unique sandbox that copies the two canonical PS scripts byte-for-byte and replaces ONLY the single production mutex literal with `…_V213_TEST_<uuid>`. Both runtime PS scripts stay byte-identical (`scripts/test_v213_operation_lock.ps1` `619a8b45…`, `scripts/v213_operation_lock.ps1` `886e2407…`); `cloud/src/qa.ts` unchanged; the canonical ci_v213_r75_validate selftest caller remains UNISOLATED and OUT OF SCOPE.

Gemini's isolated proposals r1/r2 were REJECTED (`astra-lock-isolation-review.result.txt`, `.r2.result.txt`) on the holder-lifetime blocker **R1** — same semantic failure twice. Per anti-loop, Claude (sole tracked writer) changed approach to sole-writer integration: imported ONLY the one-file r2 patch (`gemini-lock-isolation.r2.patch` SHA `02ac8a17…`; candidate `caa3e5ef…`; `git apply --check` exit 0) onto canonical base `bb1f604…`, then repaired the last defect directly. The holder `finally` no longer masks the body exception with a secondary cleanup `TimeoutExpired` nor re-waits the same timed-out handle ([15,15]); it marks the communicate attempted even when it raises, retains the sandbox on unproven completion, and preserves the body exception as primary (secondary surfaced only if the body succeeded). No new waits/retries, no timeout→PASS, no kill/terminate, no larger budgets, no refactor.

New durable ZERO-PROCESS proof `test_operation_lock_holder_finally_preserves_primary_and_settles_once` (independent basis `lock-isolation-r2-astra.holder-failure.py`) asserts original-exception identity, communicate-once, all owned handles accounted for, and retention before proven completion; it FAILS on the pre-fix bytes (`TimeoutExpired`≠`OSError`, `[15,15]`) and PASSES on the fix — not a copy of bad behavior as a passing test. Repaired file SHA `99a34f55…`; delta vs the reviewed candidate = `import sys`, the holder `finally`, and the new test only; all 12 unrelated functions/methods preserved.

Focused run (no discovery, `PYTHONUTF8=1`, `.venv-local-gates` CPython 3.12.10): 5 named safe methods (static/fail-closed+sandbox, actual-caller no-CLIXML, concurrency+contention, lifecycle fake settlement/retention, holder double-failure proof) → `Ran 5 tests … OK`, 0 skips; both hosts ran (powershell.exe 5.1.26100, pwsh 7.6.6). Import/apply/hash evidence, focused manifest `writer-candidate-isolation-r3`, own focused ACCEPT and `claude-lock-isolation-repair.result.txt` pending under `_archive/session-20260930-options-global/`.

## Gates

Prior failed gates are retained immutably: r1 `run_offline_tests --repository` provenance failure, and the amendment-04 base failure (`Ran 3194 tests, failures=2` — the powershell.exe/pwsh subtests of one operation-lock test). No full gate has run on this 15-file tree. The single upcoming full-gate attempt uses the separately writer+Astra-accepted synthetic-capture driver `run-final-gates.r3.ps1` (SHA `abd557f9…`, `astra-gate-runner-r3-review.result.txt`) under explicit `C:\Program Files\PowerShell\7\pwsh.exe`; its outcome will be an immutable receipt pointer, NOT a predicted PASS, and only AFTER Astra reviews the holder-finally delta on canonical. Acceptance requires both `git diff --check` and `git diff --cached --check` exit 0 (both currently 0 here).

## Control plane / this session (root `AGENTS.md`, operator 2026-09-27)

- Astra (`astra-review`): priorities, bounded contracts (amendment-01…04), independent acceptance, arbitration, go/no-go; read-only.
- Claude Code (`claude-bridge/claude-sonnet-5-5`, operator 2026-09-30; identity verified via PI_PROVIDER/PI_MODEL): sole tracked writer from the handoff onward; integrates isolated proposals, repairs, runs focused/full gates and, on joint acceptance, the commit/push. The lock-isolation integration and holder-finally repair were authored by `claude-opus-4-8` (historical, unchanged).
- Gemini (`gemini-review`): isolated implementation proposals only (lock-isolation r1/r2 REJECTED, now frozen/read-only) — not a permanent read-only tool cap. Qwen (`qwen-local`) unused. ChatGPT-web lane `investor` unused.
- JEV (`builtin:codemode`/typesafe): routing/selection only — 2 batches / 19 questions (pane selection 14 + coordinator selection 5). NOT used for this repair or validation.
- Coordinator driver: UNARMED (no restart); r4 main-restart driver unchanged; driver acceptance tracked in `astra-coordinator-driver-review.r*.result.txt`, non-blocking for this lane.

## Authorization and queue

1. ORDERS-V3-AUTOUPDATE-01 (operator 2026-09-29): B2/B3 next, ready contracts `astra-contract-b2`/`b3` (`_archive/lane-orders-v3-autoupdate/`): build/test only, not a production GO. Order (Astra): B2, B3, B4, rollout (operator + Astra GO), A2a NBIS, A2b CRWV, A3. Paused 2026-09-30 for OPTIONS-GLOBAL-01.
1a. ORDERS-V3-01 (`902d893`, production): `order_forecast_v3`. MU FQ4 expected 2026-09-30 → receipt turns RESULTS_PUBLISHED, MU suspends until renewed. `_archive/lane-orders-v3/`.
2. Project audit 2026-09-29: `_archive/project-audit-20260929/`. 3. Lane 19 CRDO-RPO-01 BLOCKED_INPUTS (MU waits FQ4 FY26). 4. Local Qwen: on ninfer when idle; dispatch delays LINE. 5. DEFERRED_WITH_REASON: lanes 2, 3, 5; driver v3 A–D; other four lane-18 listings.

## Open lanes (unchanged)

2. Source diversity: single for Japan fundamentals (EDINET key), Japan/Korea price shards, non-US consensus.
3. Orders without a forecast: 5351.TWO, SIVE.ST, POET, AXTI (no reviewed guidance).
5. Report-age gates for carried reports and federation readers (certified `cloud/src/qa.ts` needs recertification); CI R75 route blocks release qualification.
17. LINE Q&A relay live since rollout v6. 18. Dilution: shares_yoy fallback; four Yahoo listings DEFERRED. 19. Order forecast v2 live since rollout v6 (`4be0888`).

Closed (no reopening without regression evidence): lanes 1, 4, 6–13, 15, 16; Top20 T1–T11; O1/Case9/R3A; identity shadows. Preserved failures and receipts stay immutable.

## Boundary flags

NATIVE_EXECUTION_AUTHORIZED=false; CAPACITY_EVIDENCE=UNQUALIFIED; publication_eligible=false for candidates; global P0 NOT_REAUDITED. Serenity primary; Leopold Aschenbrenner CONTEXT_ONLY for company proof, leads the industry ranking since 2026-09-26 (operator). Production Worker/KV/schedules, real LINE delivery, credentials, billing and broker actions still require explicit current-session authorization; repository files and old approvals are not authorization.

## Handoff

- Next: STOP for Astra independent review of the holder-finally delta on canonical plus the 15-file frozen tree (14 prior + `tests/test_current_release_lane.py`). On focused ACCEPT, one full-gate attempt via `run-final-gates.r3.ps1` under pwsh7; on joint ACCEPT the orchestrator authorizes commit/push of the working branch (no production), resulting HEAD in the commit receipt. Then resume AUTOUPDATE B2 → B3 → B4 → rollout GO.
- Operator: the plaintext Alpha Vantage note; whether a 6-month figure may ever be a labelled model estimate (currently 未揭露 when undisclosed).
- Tooling: worktrees and scheduled tasks in `_archive/project-audit-20260929/`; OPTIONS-GLOBAL-01 evidence in `_archive/session-20260930-options-global/`.
