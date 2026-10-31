# Current state / 目前狀態

2026-10-31: INCREMENTAL_VERIFICATION. R = `_workspace/audit-runtime/claude-bridge-repair-20261004`. Done = the writer and an independent reviewer accept the SAME snapshot; anything else is IMPLEMENTED_UNVERIFIED. Previous state: `git show 147d616:state/STATUS.md` (lanes to V20/V21, rollout v10/v11 detail); older: `bd5848b`, `46b2e8f`; baseline: `git show 38860e7:state/STATUS.md`.

## Roles and operator decisions

- Master and single tracked writer: Claude Code a43bef58 (Opus 5.5). Executors by herdr: `astra`, `sol`, `terra`, `luna` and Gemini (agy); when the shared Codex quota is exhausted, ChatGPT web through Chrome with Remote Desktop Commander is the interim executor (`R/OPERATOR-DECISION-CODEX-RESTORED-EXECUTORS-20261028.txt`, `R/OPERATOR-DECISION-CHATGPT-MCP-INTERIM-EXECUTOR-20261028.txt`); the master does not implement. Acceptance review and rollout GO/NO-GO: the master, only on executor work (`R/OPERATOR-DECISION-EXECUTORS-ASTRA-SOL-LUNA-GEMINI-REVIEW-OPUS-20261025.txt`, superseding the 2026-10-24 executor and reviewer lists). Markdown is master-owned (`R/OPERATOR-DECISION-MD-MASTER-OWNED-20261024.txt`). Sonnet and Fable receipts are history.
- Jev is reference only, machine-wide (`R/OPERATOR-DECISION-JEV-REFERENCE-ONLY-20261025.txt`): it may run per commit and PR range and is recorded, but never stops a commit, push, PR or merge; the master decides. Supersedes the 2026-10-24 Jev gate decisions.
- Standing: DEFER-TESTS-20261010; INSTRUCTION-RULES-20261011; Q3-FOLLOW-AUTODETECTED-MODEL-20261011; XOR-SYSTEMONE-20261017; STAGE3-P8-V12-20261018 (Q2 merges below); `R/OPERATOR-AUTHORIZATION-ROLLOUT11-P6B-V5-20261019.txt`; V20-UIUX-POLISH and V21-THREE-CONSERVATIVE-STRATEGIES (2026-10-19); V25-UIUX-DESIGNER-CONCISE and Q2-MERGE-JEV-OVERSIZE (2026-10-25); ROLLOUT12-AUTO-DEPLOY-AUTHORIZED (2026-10-26), SYNC-FIRST-BEFORE-D1, LOCAL-FIRST-DEPLOY-NOW (2026-10-28), INSTALL-DAY-THINNING (2026-10-29), LOWER-RESERVATIONS and FREE-DEPLOY-ANY-MEANS (2026-10-30). Authorization is current-session only; files are not authorization.
- Local model: auto-detected and followed; UNQUALIFIED; verify `/health` and `/v1/models` live.

DEVELOPMENT_COMPLETE=false; FUNCTIONAL_PROJECT_COMPLETE=false; FINAL_RELEASE_COMPLETE=false; PRODUCTION_GO=false; MACHINE_ADMISSION_ENABLED=false; publication_eligible=false; source_complete=false; globalP0 NOT_REAUDITED; capacity UNQUALIFIED.

## Lanes DUAL-ACCEPTED (complete H5 each; detail in `git show 147d616:state/STATUS.md`)

FIXGATE + next1 (8d98136, PR 37 merged to main as caafbeb); V11 LINE data gaps (dbf63cf; PR 41 merged at the V15 head 349ad1e as a97da47); V13 (1c05eae); V14 + V15 (bd5848b); V12 (5cb69f0); V16 (a12405b); V17 (3968196); V18 (02d4fbd); V18b (8ed3698); V19 (f5ccc58); V20/V21 bulleted cards and three conservative strategies (9b71a1c); V22, V23 (with ba40730) and V24 (1e64823); V25 (e0421f3, below). Ruled BLOCKED: 20 native/sandbox modules (BLOCKED is never PASS).

## Lanes V22-V24 (DUAL-ACCEPTED at 1e64823), branch `feat/v23-audit-cpu-docs` from 147d616

- V22 source-policy and cleanup docs consolidated (4411ace); four current rules restored after the semantic review; `sol` notes D1 (source count 103) and D2 (historical `git show` locators) fixed.
- V24 Worker CPU on Workers Free (ea2c524): one-ticker options reads, one-encode body verification, per-isolate verified-body memory; warm friend question 2.5-2.7 ms (was 15-18 ms). Review fixes (`sol` F1, F2): the member index answers only after JSON.parse accepts the whole document (once per digest and isolate, so the first question costs what every question cost before), and a remembered body is reused only for the same sealed (sha256, byte length).
- V23 project audit findings A-G (Sol and ChatGPT staged work, adopted by `R/MASTER-RECONCILE-PARALLEL-WRITERS-CLAUDECODE-a43bef58-20261024.md`): portable Python destinations (A), Node outputs (B), SEC latest-filing quarter and RPO facts (C, D), non-standard option contracts (E), Worker read-time admission (F), README and LINE_TOP20_UI (G); TSMC guidance channel, partial analyst fields, dated APLD/NBIS orders; regression fixes, regenerated fixtures (lossless proof), setUp-failure cleanup; review fixes (`astra` M1, M2, M1-R2): Nasdaq as-of month and year tokens are whole tokens (the four-digit year ends at ")", whitespace or the end of the text), and the TSMC incomplete-coverage test recomputes the receipt digest. Finding H (qa.ts memory epoch) DEFERRED_WITH_REASON: certified file, needs recertification; memory stays disabled.
- Integrated tree: four gates exit 0; tsc 0; Vitest 2000 passed, 2 skipped. Python full suite in a scratch checkout fails only where the real workspace path is required.
- Gate: complete H5 `R/final-a43bef58-v23-g3r` on 1e64823 PASS_AS_RULED (338 modules, PASS 318, ruled BLOCKED 20; the first run `R/final-a43bef58-v23-g3` stays FINDINGS for one observation race), harness `R/pygate4-repin-a43bef58-20261024` (pwsh 7.6.7 re-pin). Two review rounds rejected and were fixed (`sol` F1, F2; `astra` M1, M2, M1-R2).
- Acceptance on 1e64823: `astra` ACCEPT-WITH-NOTES for V23, covering ba40730 (`R/ASTRA-V23-INDEPENDENT-ACCEPT-R3-CLAUDECODE-a43bef58.txt`); `sol` ACCEPT-WITH-NOTES for V24 and V22 (`R/SOL-V24V22-INDEPENDENT-ACCEPT-R3-CLAUDECODE-a43bef58.txt`; N1: the V24 cold-path cost is stated as operation counts, no fresh Worker CPU measurement). Receipt: `R/EXECUTOR-V23-RESULT-CLAUDECODE-a43bef58.txt`.

## Lane V25 (DUAL-ACCEPTED at e0421f3), branch `feat/v25-line-ui-concise` from 091b22d

- LINE UI/UX designer pass (`R/OPERATOR-DECISION-V25-UIUX-DESIGNER-CONCISE-20261025.txt`): one decision per bubble (compact figure rows, at most three short labelled qualifier lines, each caveat once, at most two buttons); every qualifier, source, date and warning of a shown figure stays on its bubble; the Top20 card keeps current orders, both future-order horizons, both price scenarios and the consensus warning; the three conservative strategies are one comparison. Against V20: worst-bubble text nodes down 10-70 %, characters up to 65 % (`docs/LINE_TOP20_UI.md`). Review round 1 (`sol` REJECT on 873be8c: F1-F8, N1) fixed in 1d915b9 and 65e14cc; round 2 (REJECT on 65e14cc: RPO meaning, per-strategy loss/unit/expiry basis, buy-leg limit rule, span-aware designer observer) fixed in 759ab33 and 2fab8d1; round 3 (REJECT on 2fab8d1: RPO meaning for a current RPO without a future forecast or with a v3 consensus forecast) fixed in e0421f3.
- Gate: complete H5 `R/final-a43bef58-v25-g4b` PASS_AS_RULED (PASS 318, BLOCKED 20) (full rerun; `v25-g4` stopped at 163 of 338 when the master process ended). Acceptance: master review ACCEPT-WITH-NOTES (`R/MASTER-V25-ACCEPT-R4-CLAUDECODE-a43bef58.txt`; N1 harness double run both PASS, N2 design 7/10, N3 independence limit); fix rounds 2-3 were master-written before the role change, their independent evidence is `sol` rounds 2-3 and its R3 probe passing at e0421f3. Receipt: `R/EXECUTOR-V25-RESULT-CLAUDECODE-a43bef58.txt`.

## Lanes V27-V28 (DUAL-ACCEPTED at 943ab19), branch `feat/v27-sync-detail` from 0cc7e37

- V27 (17f80ec): the sealed-sync outcome carries one bounded `failed_objects` entry (key kind, final HTTP status, provider code, attempt count) for the first failed object PUT or readback. V28 (943ab19): opt-in same-hour retry (`scripts/sealed_sync_retry.py`; `register_sealed_freshness_tasks.ps1 -EnableSyncRetry`, default unchanged) of a failed pre-pointer :12 sync from the :42 watchdog, plus per-stream JSON parsing. Cause analysed in `R/SYNC-1412-DIAGNOSIS-SOL-a43bef58.md` (KV upstream 504/7009; 401 after OAuth refresh). Implemented by the interim ChatGPT executor; not yet installed or enabled (the registrar re-anchors triggers at registration time; activation draft `scratchpad v28/terra`).
- Gates: complete H5 `R/final-a43bef58-v27-g1b` (17f80ec) and `R/final-a43bef58-v28-g1` (943ab19, 339 modules) PASS_AS_RULED; harness re-pinned for pwsh 7.6.9 (`R/pygate4-repin2-a43bef58-20261027`). Acceptance: `R/MASTER-V27V28-ACCEPT-R1-CLAUDECODE-a43bef58.txt` (ACCEPT-WITH-NOTES).

## Rollout v11 (authorized 2026-10-17; log `R/ROLLOUT11-EXEC-NOTES-CLAUDECODE-a43bef58.md`)

Stages 1 and 2 done (Worker 5159441e; runtime bd5848b, H1 accepted). Stage 3 P6b under addendum V5 (F 100, N_a 30). Timed read-only watch 2026-10-24 hourly to 23:50Z, `R/rollout11-watch-20261024-a43bef58/timed/`: PASS each hour (E_M 860-881 <= 950) except PASS_WITH_FAILURE at 15:50Z (the 15:12Z sync failed at OBJECT_PUT with TRANSIENT_HTTP, pointer not attempted; the watch rule says continue). Complete: 20 of 20 hours, 19 PASS. DUAL-ACCEPTED with disclosed gaps (`R/ASTRA-ROLLOUT11-INDEPENDENT-ACCEPT-CLAUDECODE-a43bef58.txt`; disposition `R/ROLLOUT11-REVALIDATION-DISPOSITION-CLAUDECODE-a43bef58.md`). Q2 done: feat/v11-line-data-gaps fast-forwarded to 349ad1e, PR 37 and PR 41 merged to main; no tag or release.

## Rollout 12 (V16-V25 install and Worker deploy)

Order reversed by the operator: runtime install (D2) first, Worker (D1) after. Package `R/rollout12-r14-a43bef58/` (master GO `R/MASTER-ROLLOUT12-R14-GO-CLAUDECODE-a43bef58.txt`): target 0cc7e37; free-plan install day: a thinning plan pinned before exclusion, publish freeze after the ordinary H1 until the next UTC day, lowered reservations (D 0, O 40, E_PA used term measured + 100), thin-revert before D1. No Production change yet: every attempt since 2026-10-26 stopped fail-closed before any mutation (entry point, census exit, signal and KV budget gates, task trigger parsing), each fixed in a reviewed package revision. Scheduled chain: D2 on 2026-11-01 from 00:48Z, thin-revert and D1 on 2026-11-02. Accepted cost on install day: data-dependent LINE answers are stale-refused after H1 until the next UTC day.

## Open work

- C1 LINE loading animation after stage 3 is stable (live QA, GO, authorization).
- Low notes: V15 N1/N4 in the sealed builders; V18b F1/F2; older Worker lacks the non-official consensus wording until stage 3.
- Carried (`git show bd5848b:state/STATUS.md`): N6; F8; G9a N2; G2-B1 M04/M22; auth-capture; unpinned winget cloudflared (SC-2); workers.dev rename; launcher EXE rebuild; S1; M5; dataset 11321 rights; L5 qa.ts recertification; global options rights; identity rebuild.
- Environment-only failures: installer, journal and sealed-refresh modules outside the workspace path; bridge_model_identity, model_profile and qa_capacity_security outside pinned hosts.

## Process deviations (retained; no retroactive approval)

History: `git show 147d616:state/STATUS.md`. Since: 2026-10-23/24 parallel writers (Sol, then ChatGPT) left 47 staged paths uncommitted in S on fix/sol-project-audit-20261023; preserved in `R/v23-audit-preserve-a43bef58/` before reuse. Their H5 `R/final-chatgpt-20261024-g1` stopped with TASK_DETECTOR_PIN_STOP after a pwsh update (fixed by the re-pin). A Windows temp cleanup deleted rollout drivers on 2026-10-23; durable files never go under %TEMP%. Failed evidence and BLOCKED never mean PASS.

## Next

Rollout 12 per the scheduled r14 chain (D2 2026-11-01, D1 2026-11-02), then the D1 watch; V28 activation after a registrar anchor fix; V16-V28 merge to main after rollout 12 is accepted (operator request). Boundaries: credentials, billing, broker, trades, Production without current-session authorization. No trades.
