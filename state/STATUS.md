# Current state / 目前狀態

Updated 2026-09-27 17:58 Asia/Taipei by Claude Code (sole tracked writer): batch PY-LOCAL-01 revision 2 (local Python resolver; Astra REJECTED revision 1 with three fixes, all applied), contracted by Astra, on base `e2365cd9182ec0aa672e707cfcb2e68a4741b05c`. Previous text: `git show e2365cd:state/STATUS.md`; earlier `git show dec7bd0:state/STATUS.md`, `git show 5b15984:state/STATUS.md`, `git show 3ac39a1:state/STATUS.md` (full production record), `git show a8c6e58:state/STATUS.md`, `git show 59049db:state/STATUS.md`, `git show 38860e7:state/STATUS.md`; V12 `git show 0f5358b:state/STATUS.md`. Release identity stays in `README.md`. Root and source `AGENTS.md` override older control-plane text in this file's history.

## Identity

- Branch `fix/options-provenance-audit`, draft PR #37 to `main`. CI runs on this branch end COMPLETED_SKIPPED by design (`final-release-candidate-v3-pre-rewrite-audit.yml` runs only for head `integration/final-release-candidate-v3`): not PASS. Non-release-qualified (LOCAL_SOURCE_CHECKOUT). DEVELOPMENT_COMPLETE=false; FINAL_RELEASE_COMPLETE=false.
- This batch: `scripts/resolve_python.ps1`, `tests/test_local_python_resolver.py` (new), `tests/test_ci_python_bootstrap.py`, `docs/DEPENDENCY_LOCKING.md`, `AGENTS.md`, this file. Done only after writer and Astra accept the same snapshot. Receipt: `_archive\jev-panes-20260927T0930Z` (workspace, outside the repository).

## PY-LOCAL-01 result (this batch)

- Defects fixed (local branch only; CI bootstrap branch unchanged): the resolver deleted and recreated `-VenvPath` on every call, never set `$env:PROJECT_PYTHON` in the calling process (all three callers read it) and wrote interpreter output to the success stream, so `Resolve-R75Python` in both activation scripts would have returned an array.
- Now: a compatible existing venv is reused; any other existing destination (empty, non-venv, broken, incompatible directory or a file) fails untouched; drive roots, the checkout, the current directory, profile/system directories and reparse-point paths are refused; `PROJECT_PYTHON` is cleared first and set last, after every check and after the optional GitHub files were written (a failed write leaves it unset). Generic mode (default, activation fallbacks) installs nothing and keeps version/bitness-only semantics. `-InstallLockedDependencies` accepts only 64-bit CPython 3.12.10, implementation included, for the base and a reused venv (`-BasePython` pins the base only at creation), installs `requirements-ci.txt` with the CI command and runs `pip check` on every call.
- Tests: 14 behavioral cases under PowerShell 5.1 and 7 (fake base interpreter, recording fake pip, fixture checkouts, junction via `mklink /J`; activation function bodies loaded by AST with task/network APIs forbidden; R70 call pattern) plus one policy test. The first test revision failed 38 subtests on the old resolver; the revision-2 negatives (PyPy base and reused venv, empty directory, unwritable GITHUB_ENV/GITHUB_OUTPUT) fail 10 subtests on revision 1 (receipt). Installed task actions were NOT validated or changed; shipping/live acceptance remains outstanding.
- Local gates: `.venv-local-gates` created with `-InstallLockedDependencies` (CPython 3.12.10 64-bit, lock sha256 `54b7d4ed…`, wheels from pip cache, hash-verified, `pip check` clean; a repeat call reused it). With `PYTHONUTF8=1`: security, documentation boundary/structure, workflow supply-chain gates exit 0; `run_offline_tests.py --repository` ran 2,854 tests OK on revision 2 (17:45–17:56, outside :12–:25; revision 1: 2,852 OK). No Worker change, Worker gates not run. The old `.venv-ci` (pip only) was left untouched.

## Production — historical observations, not currently verified

Nothing here was re-read today after 14:53; live Worker, runtime, tasks, pointer/object set and relay are UNKNOWN.

- Last recorded (rollout v5 P0, 14:53): Worker `25377354-0ff5-4a28-a78b-82ec2457729f` (source `16cb1b3`, rollback target); runtime LOCAL_SOURCE_CHECKOUT `ff6dc42`, tx `75cc59dc…` FINALIZED; tasks SealedFreshness, FreshnessWatchdog, FreeRelay, DailyBriefing recorded Enabled/Ready; hourly seal task `InvestorIntelligenceSealedFreshness` (:12). Rollback order: `git show 3ac39a1:state/STATUS.md`.
- Outage 2026-09-26 22:45 – 09-27 08:12 on Cloudflare's free KV write quota (code 10048); recovered after the 08:00 reset (09:12 seal `20260927T011233Z-80d7c5b186c1`, post gate `-ExpectTop20Records 20` PASS, v3 20, NVDA options VALID).
- New validators refuse historical SIVE.ST/VOLV-B.ST option cycles, so a new Worker may only go live after data built by the new runtime is sealed.

## Rollout record (lane 14)

Astra NO_GO on plans 1–4; plan v5 got a conditional GO (`%TEMP%\ii-live\astra-rollout5.result.md`) for one supervised manual window on `dec7bd0` with ten stop conditions: not driver acceptance, deployment completion or later-session authorization. Journal `%TEMP%\ii-live\rollout5\journal.md` records only P0 identities and preparation; `p1-*` files (15:16) prove no effect. Post-P0 execution, deploy, publication, recovery and task states are UNKNOWN, not "nothing happened". Historical counters (reinstalls, manual seals, `NATIVE_ATTEMPT_COUNT=0`) are records, not current.

## Priorities (Astra, 2026-09-27 17:06)

1. PY-LOCAL-01: this batch (complete after Astra ACCEPT, commit, push).
2. Lane 19 MU/CRDO source-checkout v8 extraction evidence: READY after rank 1, local and isolated only (`order_timing.py` also writes `data/cache/v21/order_timing`). Gemini (unverified, `_archive\lane-dispatch-20260927T0905Z\gemini-lane19.result.md`): MU 10-Q to 2026-05-28 RPO ~$5B, ~1/3 within 12 months, 6M not disclosed; MU reports Q4 FY26 on 2026-09-30, so its extraction waits for that 10-K. CRDO 10-Q to 2026-08-01 RPO ~$4.2M, all within 12 months, 6M not disclosed.
3. Lane 14: BLOCKED_AUTHORIZATION / OUTCOME_UNKNOWN (operator must authorize reading back and, if needed, reconciling production under v5's conditions).
4. Local Qwen: BLOCKED_CONFIGURATION (Tabby `:5000` unreachable at 17:03; exact `Qwen3.8-27B-EXL3-5.5bpw-v2` not established; `:8080`/`ninfer-local` are not fallbacks).
5. DEFERRED_WITH_REASON: lane 18 (five Yahoo quarters cannot give the previous quarter's YoY; needs an independently sourced sixth quarter, the current null is correct), lanes 2, 3, 5 (reasons below), driver v3 A–D (v5: not required for a supervised window).

## Commits after 20:45 (deployment state unknown)

`13d7c85` … `5b15984`: lanes 2/3/4/6, KV quota handling, ChatGPT Pro reviews, reader replay v3. `aa54416`/`bb95f97`: lanes 15/16. `33d7938`: lanes 17/18. `eca78a1`: lane 19. `dec7bd0`: `AGENTS.md`. `e2365cd`: STATUS reconcile.

## Operator decisions (2026-09-26)

ChatGPT review MCP is `chatgpt-web` (workspace `AGENTS.md`); `scripts/codex_review_mcp.py` stays in the repo. No pointless questions. Alpha Vantage key is DPAPI ciphertext; the plaintext desktop note is the operator's to delete. No OpenDART/data.go.kr key; Nasdaq data accepted; Google Finance rejected.

## Open lanes

2. Source diversity: official fundamentals beside Yahoo for Taiwan (TWSE/TPEx), Stockholm (SIVE via Cision) and Korea (curated IR config; refresh after earnings). Still single: Japan fundamentals (EDINET needs a key), Japan/Korea price shards, consensus outside the US.
3. Orders: CRWV (24M only) and SNDK (12M only) disclose no other horizon. AXTI and NBIS have no deep report (domestic SEC filers only): deferred until foreign-filer deep reports exist. Korea HD Hyundai Electric deck unreadable keylessly.
5. Deferred: report-age gates for carried reports and federation readers (certified `cloud/src/qa.ts` needs recertification); the CI R75 route blocks release qualification.
14. Rollout of `3ac39a1..e2365cd`: see Rollout record. Material in `_archive\rollout-2026-09-27`.
17. LINE Q&A relay (Worker → quick tunnel → gateway :8814 → ninfer :8080), healthy on 2026-09-27 morning (not re-verified). Nightly heartbeat failures from one KV nonce per heartbeat fixed in 33d7938 (nonce in the relay Durable Object); undeployed versions risk repeats. Three short failures on 2026-09-27 unexplained; the heartbeat now logs the code.
18. Dilution: shares_yoy from the quarter's diluted weighted average when shares outstanding are missing. No stated Chinese name for NBIS, SIVE, POET, CRWV, AXTI. Remaining: see priority 5.
19. Order tiles (operator 2026-09-27: 6-month and 1-year figures, dated, must differ): `scripts/order_forecast.py` + `cloud/src/v213/order-forecast.ts` (rules `git show eca78a1:state/STATUS.md`; fixture `tests/fixtures/v213-order-forecast-sealed.json`); extractor v8. Local matrix (`%TEMP%\ii-live\order-matrix.md`): 1-year orders SNDK 11.36B (coverage 32%), NVDA 1.25B, AMD 0.14B, AVGO 44.8B (38%); CRWV 24M only; MU and CRDO need v8 re-extraction (priority 2). Curated non-RPO records deferred (no company discloses 6M/1Y orders outside RPO).

Closed: lanes 1, 4, 6–13, 15, 16. Lane 15 upkeep: a new IPO or spin-off stays excluded (`HISTORY_OR_LINEAGE_UNVERIFIED`) until `config/listing-lineage-v1.json` has its primary-source record; check `excluded` after each v3 build.

Lane 4 compatibility exception (Astra review 2): with a valid fresh v3 document every ranking word opens v3. Without one, words the certified seven-field path already matched (`top 20`, `前20`, `排行`, `排名` as substrings, so also `瓶頸排名`, `瓶頸TOP20`) keep that path, which can show the sealed seven-field report; only `瓶頸榜`, `前二十` and `瓶頸爆發榜` answer the v3 unavailability notice. Retiring the seven-field path needs its own product decision and recertification.

## Closed components — no reopening without regression evidence

Top20 single-writer programme T1–T11 (`90563ee` … `f5bfe78`); T1 (`5208d64`), T2 (`26842de`), T3 (`689a682` → `a944410`); O1 options venue coverage shadow (`11436e6`), Case9 (`c178127`), R3A (`e45c1d6`), research method quarantine (`c6ce527`); I1/I2/I3 identity shadows, E2A synthetic capacity, hermetic fixtures. Preserved failures and receipts stay immutable (V12 register).

## Boundary flags

NATIVE_EXECUTION_AUTHORIZED=false; CAPACITY_EVIDENCE=UNQUALIFIED; publication_eligible=false for candidates; global P0 NOT_REAUDITED. Serenity primary; Leopold Aschenbrenner CONTEXT_ONLY for company proof, leads the industry ranking since 2026-09-26 (operator).

## Control plane (root `AGENTS.md`, operator 2026-09-27)

Astra (`astra-review`, w9:pA): priorities, contracts, acceptance, arbitration, go/no-go; read-only. Claude Code: sole tracked writer. Gemini (`gemini-review`, w9:pB): research and audits. Both restarted at ~17:15 with JEV (`pi-typesafe`, enabled, daily cap 60) on the operator's request; Qwen (w9:pC) stays the parked shell `qwen-local-blocked` without JEV (JEV .74). Receipts: `_archive\jev-panes-20260927T0930Z\RECEIPT.md`, `_archive\pane-restart-20260927T081056Z\RECEIPT.md`. Each Herdr task starts with `/new` (send with `MSYS_NO_PATHCONV=1` from Git Bash). The wB panes belong to another project. `chatgpt-web` selectors do not see answers; read them from the tab.

## Handoff

- Next: Astra acceptance of this snapshot, commit and push; then lane 19 CRDO evidence (MU after its 10-K).
- Operator: lane 14 authorization, restoring the exact Tabby backend for Qwen, the plaintext Alpha Vantage note.
- Tooling: old-reader worktree `%TEMP%\ii-live\wt-16cb1b3` (`cloud\node_modules` is a junction to the source checkout's); `chatgpt-web` lane `investor` (branch `local/zh-tw-lanes`). Scratch: `%TEMP%\ii-live`.
