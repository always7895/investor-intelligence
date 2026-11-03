# Current state / 目前狀態

2026-11-03: INCREMENTAL_VERIFICATION. R = `_workspace/audit-runtime/claude-bridge-repair-20261004`. Done = the writer and an independent reviewer accept the SAME snapshot; anything else is IMPLEMENTED_UNVERIFIED. Previous state: `git show c431eee:state/STATUS.md` (V22-V28 lane detail, rollout 12 D1); older: `147d616`, `bd5848b`, `46b2e8f`; baseline: `git show 38860e7:state/STATUS.md`. HEAD: this commit on `feat/v32-d2-force-pair` (parent `d13e336`, branch `perf/v31-top20-cpu`).

## Roles and operator decisions

- Master & writer: Claude Code a43bef58 (Opus 5.5). Executors: `astra`, `sol`, `terra`, `luna`, Gemini (agy). While the shared Codex quota is exhausted (since 2026-11-03): Sonnet 5.5 / Haiku 5.5 subagents and ChatGPT web via Chrome and Remote Desktop Commander (`R/OPERATOR-DECISION-CODEX-EXHAUSTED-FALLBACK-SONNET-HAIKU-CHATGPT-20261103.txt`). Master reviews only (`R/OPERATOR-DECISION-EXECUTORS-ASTRA-SOL-LUNA-GEMINI-REVIEW-OPUS-20261025.txt`). Markdown master-owned (`R/OPERATOR-DECISION-MD-MASTER-OWNED-20261024.txt`).
- Jev: reference only machine-wide (`R/OPERATOR-DECISION-JEV-REFERENCE-ONLY-20261025.txt`): recorded, never blocks workflow; master decides.
- Standing: DEFER-TESTS-20261010; INSTRUCTION-RULES-20261011; Q3-FOLLOW-AUTODETECTED-MODEL-20261011; XOR-SYSTEMONE-20261017; STAGE3-P8-V12-20261018; `R/OPERATOR-AUTHORIZATION-ROLLOUT11-P6B-V5-20261019.txt`; V20-UIUX-POLISH & V21-THREE-CONSERVATIVE-STRATEGIES; V25-UIUX-DESIGNER-CONCISE & Q2-MERGE-JEV-OVERSIZE; ROLLOUT12-AUTO-DEPLOY-AUTHORIZED, SYNC-FIRST-BEFORE-D1, LOCAL-FIRST-DEPLOY-NOW, INSTALL-DAY-THINNING, LOWER-RESERVATIONS & FREE-DEPLOY-ANY-MEANS; LINE-BOT-FIRST-20261101; GLOBAL-OPTIONS-SOURCE-RIGHTS-LANE-20261102 & FREE-ONLY-API-REGISTRATION-20261102; ROLLOUT13-R4-DEPLOY-APPROVED-20261103. Current session only.
- WeMM-JEV-27B advisory paused by the operator; Jev (reference only) gives the second opinion instead (`R/OPERATOR-DECISION-WEMM-PAUSED-USE-JEV-20261103.txt`).
- Local model: auto-detected and followed; UNQUALIFIED; verify `/health` and `/v1/models` live.

DEVELOPMENT_COMPLETE=false; FUNCTIONAL_PROJECT_COMPLETE=false; FINAL_RELEASE_COMPLETE=false; PRODUCTION_GO=false; MACHINE_ADMISSION_ENABLED=false; publication_eligible=false; source_complete=false; globalP0 NOT_REAUDITED; capacity UNQUALIFIED.

## Lanes DUAL-ACCEPTED (detail in `git show c431eee:state/STATUS.md` and `git show 147d616:state/STATUS.md`)

FIXGATE + next1 (8d98136, PR 37 merged as caafbeb); V11 LINE data gaps (dbf63cf, PR 41 merged as a97da47); V13 (1c05eae); V14 + V15 (bd5848b); V12 (5cb69f0); V16 (a12405b); V17 (3968196); V18 (02d4fbd); V18b (8ed3698); V19 (f5ccc58); V20/V21 (9b71a1c); V22, V23 & V24 (1e64823); V25 (e0421f3); V27 (17f80ec); V28 (943ab19, anchor fix bc19ff4). Complete H5 for each through V28. Ruled BLOCKED: 20 native/sandbox modules (BLOCKED is never PASS).

## Lanes V29-V31 (Worker and options; H5 not run, Worker Vitest + focused Python)

- V29 (4065fbe, `feat/v29-ui-options`): visual cards and monthly options fallback. `R/MASTER-V29-ACCEPT-CLAUDECODE-a43bef58.txt`.
- V30 (89aec96, `feat/v30-options-rights`): 2026-11-02 global options source rights review (18 candidate providers, `licence_required`, TAIFEX underlyings; no free licensed global source found; TAIFEX display deferred). DUAL-ACCEPTED (`R/MASTER-V30-ACCEPT-CLAUDECODE-a43bef58.txt`, `R/MASTER-V30-RIGHTS-REVIEW-CLAUDECODE-a43bef58.txt`).
- V31/V31b (c44f1ad, d13e336, `perf/v31-top20-cpu`): additive Flex carousel byte count on plain shapes; Top20 offline p95 9.01 ms (criterion 10 ms, `R/MASTER-ROLLOUT13-CPU-QUALIFICATION-CLAUDECODE-a43bef58.json`). Master-accepted with recorded `astra` dissent EQ6-EQ9 (`R/MASTER-V31-ACCEPT-CLAUDECODE-a43bef58.txt`).

## Lane V32 (this commit; IMPLEMENTED_UNVERIFIED until the complete H5 and acceptance)

- `scripts/run_daily_data_refresh.ps1`: default-off `-D2ForceGuidanceRankingPair` (disabled mode only: `guidance_release_check` and `bottleneck_v3` with `--if-older-than-hours 0`); off = unchanged arguments. Tests in `tests/test_v11_consensus_refresh_wiring.py` (pwsh 7 and Windows PowerShell 5.1); doc line in `docs/REVENUE_GUIDANCE_AUTOUPDATE.md`. Executor Sonnet 5.5; decisions `R/MASTER-ROLLOUT14-D2-DECISIONS-CLAUDECODE-a43bef58.txt`. Purpose: D2 install-day refresh fits the schedule when the ranking time falls in the :08:00-:17:34 band (astra design, 3600/3600 feasible).

## Rollout 12 (V16-V25) and Rollout 13 (Worker d13e336)

- Rollout 12 D1: Worker 54854c20 (0cc7e377) deployed 2026-11-01T06:54:57Z (`R/MASTER-ROLLOUT12-D1-DEPLOYED-CLAUDECODE-a43bef58.txt`). D2 r17f/r17h stopped fail-closed code 33 (refresh schedule infeasible on band days; `R/MASTER-ROLLOUT12-R17H-D2-STOP33-CLAUDECODE-a43bef58.txt`).
- Rollout 13 D1 (Worker d13e336): R1 NO-GO (CPU); R3 GO, 2026-11-03 attempts stopped code 41 before any deploy (Cloudflare APJC incident, then coverage OK unsatisfiable on the real seal; `R/MASTER-ROLLOUT13-R3-D1-STOP41-CLAUDECODE-a43bef58.txt`). R4 = R3 + coverage non-regression criterion, GO (`R/MASTER-ROLLOUT13-R4-GO-CLAUDECODE-a43bef58.txt`), operator-approved; gated hourly :48 windows on 2026-11-03, then D1 watch (three hourly cycles + 23:12) with the exceeded-CPU live guard.
- Production defect (pre-existing): options-coverage view returns COVERAGE_SCHEMA_INVALID on both Workers because the installed producer catalog (bd5848b) lags; fixed by D2.

## Open work

- Rollout 14 D2: install V32 on the producer (package `R/rollout14-d2-a43bef58`, retarget to this commit, complete H5, GO, operator go-ahead); first slot 2026-11-04T00:48Z after the R4 D1 watch.
- Producer defect: `price_shards` exit 2 on every real execution since 2026-11-01T08:12Z (diagnosis pending).
- C1 LINE loading animation after stage 3 is stable (live QA, GO, authorization).
- Low notes: V15 N1/N4; V18b F1/F2. Carried (`git show bd5848b:state/STATUS.md`): N6; F8; G9a N2; G2-B1 M04/M22; auth-capture; unpinned winget cloudflared (SC-2); workers.dev rename; launcher EXE rebuild; S1; M5; dataset 11321 rights; L5 qa.ts recertification; identity rebuild; TAIFEX EOD display.
- Environment-only failures: installer, journal and sealed-refresh outside workspace; bridge_model_identity, model_profile, qa_capacity_security outside pinned hosts.
- V28 task registration and activation on the real host.

## Process deviations (retained; no retroactive approval)

History: `git show c431eee:state/STATUS.md`. Since: rollout 13 R3 reached GO without a real current-seal run of its new coverage criterion (lesson recorded); R4 fixed it with a real-seal master rerun. Failed evidence and BLOCKED never mean PASS.

## Next

R4 D1 deploy and watch; complete H5 on this commit, acceptance, push; rollout 14 D2 package review, GO and operator go-ahead; V16-V32 merge to main after rollout acceptance (operator request). Boundaries: credentials, billing, broker, trades, Production without current-session authorization. No trades.
