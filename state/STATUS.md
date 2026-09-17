# Current state / 目前狀態

## INVESTOR_FULL_AUTOPILOT_V2 — UNATTENDED_CONTINUOUS (Continue from Committed-HEAD §1; Local-Only)

CHAPTER 20 — Anchor: pre-prod_local §1 (Committed-HEAD)

Committed HEAD: `ab1bcca` (2026-09-17 17:33 +0800), fix/options-provenance-audit, pushed to origin (open draft PR #37). Prior head `bb75aaf` (2026-09-16; from `f287ba0`; run `2873c2ff6316`) = superseded history. `LINE_LIVE=true` (top20-only, fresh-evidence gated); `FINAL_RELEASE_COMPLETE=false`.
(M1-sealed-audit complete; NO PULL/REBASE/BRANCH)
- VERDICT: `HEAD_RESOLVED_SEALED_OK` (local audit; Pro read-only review; single branch, no remote).
- HEAD authority: latest committed live pointer = `20260916T092839Z-2873c2ff6316` (objects `4d83c1c` -> pointer `6328d93`; `9f87437` is STATUS-only).
- Seal re-verify (zero network): runs `f2a9ea873960` and `2873c2ff6316` PASS the full chain gate (per-key sha, exact manifest, seal == pointer, invariants); tracked files == HEAD blobs.
- Scratch runs cleaned (Task #27); future run dirs ignored via `state/v213-snapshots/*/`.
- LIVE pointer/KV: verified by live read under Tasks #26/#27 (sealed chain re-checked; re-pointed by the 60-min refresh task).
- Local scope: git reads only; 0 KV writes, 0 deploys, 0 LINE sends, 0 re-points.

> Historical anchor retained (not a new claim): `f287ba0` (final readiness ledger; prior `5e42584` v213 pointer-last, `1331ff8` objects, `1c3cfa4` code).

### PRODUCTION FINAL ACCEPTANCE (2026-09-17, Task #30; ChatGPT Pro Accepted; Macro TOP5 & Top20 Resolved)
- **Acceptance Tuple:** HEAD `3c7497e` / Worker `c7abe74d-0cd9-4e06-9e96-906690038a24` / Pointer `20260917T092410Z-d9f86bda2053` / Seal `891b671a67cfe08a47622f09c5c11fa54fe9b7ab07a4aa9db0427fe172391c0a`.
- **Verdict:** `FINAL_ACCEPT` signed off by ChatGPT Pro (conv: `6aab83bf-d1cc-83ee-b96e-c8088e11c134`); Macro TOP5 & Top20 presentation fully verified.
- **Top20 Presentation Root Cause:** `parseTop20ReportWithBounds` required `TRADITIONAL_CHINESE_RE` on `industry`; relaxed to `lineSafeText(100)` and supplied bilingual labels (`重電與綠能設備` / `重電與電網設備`). Both GEV and 6501 render cleanly.
- **Macro TOP5 Admission:** `v213:macro-industry:latest` sealed in 15-object snapshot; 5 verified public-only independent evidence industries (WSTS Packaging & HBM, LightCounting Optical, FERC/DOE Grid, SEMI Equipment, Omdia Cooling); shortfall = 0; `MACRO_TOP5_SHORTFALL` cleared.
- **Freshness & Contract:** Assembly anchor (2026-09-17T09:24:10Z) separated from evidence anchor (2026-09-15T11:00:00Z); zero restamping. Admitted Top20: GEV 96.0 #1, 6501 93.0 #2; 0 padding.
- **Fail-Closed Verified:** SIVE, AAOI, 6508, ENR fail-closed (`sealed_snapshot:unadmitted_symbol`); invalid tickers route to `general_qa` without equity hijack.
- **Durability Hardening:** Hourly scheduled refresh (`InvestorIntelligenceSealedFreshness`) + 30-min read-only watchdog (`InvestorIntelligenceFreshnessWatchdog`) registered with `StartWhenAvailable`, `PT1H` limit, `IgnoreNew` concurrency guard, and mutex lock (`Local\InvestorIntelligence_V213_R75_OPERATION`).
- **Full Verification Suite:** Vitest 818/0/1, Pytest 1521/0/3, TypeScript clean (0 errors), security_check PASS, canonical_release_candidate_gate_v2 PASS, deploy_production_gate post PASS.

### TASK0 — 1C–1F (2026-09-17; Pro; condensed)
- 1C: P1 utf-8 test fix (1e4ad25; pytest 1521/0/3; op-lock NOT_REPRODUCED; 1B gap UNDETERMINED).
- 1D/1E: two-sided MODEL MISMATCH (live worker env literal `qwen38-q6`; tabbyAPI serves EXL3-SC5-H6-V6 only); 16/16 chain rewrite on minimalModelSmoke + strict 2-endpoint boundary (adapter identity + real reply evidence); commits 734a3b1+b353298.
- 1F: W2 DO-read guard (warn + null) TRUE-RED->GREEN 14/14; opt-in harness/manual split (hardened spawn, 2-endpoint boundary, verified release); live 13:57:32Z 1/1; package endpoints 404-dead; commits 8d5fb3f+b227d32.
### TASK0 — 1G-REPAIR (2026-09-17T14:50–15:05Z; Pro)
- Corrigan: approved digest = 270344c6**a32e**… (my 2497… cite = error, retracted); byte0 = 80 DEC = 0x50 (hex misreport corrected); CP950 hypothesis discarded.
- Initial check (Pro verbatim script): IDENTITY_AND_DIRECTORY_READABLE (size 1784534, sha ok, PK0304, 637 entries, 5.2MB). Structure: 0 pathwalk / 0 case-dup / 0 absolute. Internal qualification = BLOCKED_PACKAGE_EVIDENCE_INCOMPLETE (clean_install_acceptance needs checksum+manifest+sbom+policy; production-final release ships the ZIP alone) -> no isolation acceptance this round.
- Verifier repair RED(8 fail/19) -> GREEN: chain+manual now share startDrain (rejections stay rejections, real-time race, round timers cleared); abort path completed (AbortSignal.any + fallback, caller abort = fast failure, 0 forwarded model HTTP, 0 violation); new releaseGateway = 4 states (alive->exit->listener-verified, already-exited no-kill, stuck bounded-fail, reentrant); manual timing = performance.now; stall/recovery MOVED OFFLINE (mock-native 504 -> explicit refusal class); positive QA finishReason==="stop" + modelReturned===EXL3 + completionVerdict (length/empty/mismatch/no-structure all rejected, offline repeatable); opt-in runner measured NON-ZERO exit with 0 python spawn + 0 network; 2 false-positive negative assertions corrected.
- OFFLINE: vitest 853/0/1 x2 (gate set +19), tsc 0, 5 gates PASS. 0 gateway / 0 model this round; 14:34:55Z live remains the archived integration proof (attempt arithmetic recorded: 3 real model forwards [smoke+QA+recovery] + 1 synthetic 504 per run; recovery was over the "2 model" cap -> categorical error documented; recovery removed, capped at smoke+QA).
- Preflight unchanged: W2 deploy = operator build of approved branch (rollback = prior worker). W1 = worker var V213_MODEL_PROFILE_JSON (70077f89…) AFTER pre-state var readout; rollback = restore readout.
- MUTATIONS: 2 commits (code + STATUS) on approved branch; PR#37 body corrected once; 0 PROD/KV/DO/LINE/registry/schedule/flag/image writes.
- OPEN: package companion 4 files (checksum/manifest/sbom/policy) for internal qualification + isolation acceptance; W1 pre-state; P1 DO-excursion rating; scheduling gap.

### Milestones (sessions 2-6, 2026-09-15; compacted) — full detail in git log
### Milestones (2026-09-15 session 7: security gate placeholder fix) — `e43be26` EXAMPLE_* token_urls (gate cleared).

### Archive milestones (sessions 7-15, 2026-09-15; details in git log)

### RELEASE READINESS LEDGER (Task #20, 2026-09-16; superseded by the PRODUCTION DEPLOY block below) — close-of-lane regression + budget invariants + DEPLOYMENT_READY=TRUE; detail in git log.


### PRODUCTION DEPLOY (2026-09-16, Task #22; explicit operator authorization, this session)
- KV `PUBLIC_CACHE` (96142af4…): 14 sealed objects of run `20260915T120000Z-f2a9ea873960` + `snapshot:current` pointer LAST; all 14 read back and byte-verified (seal sha d64b21be == pointer).
- Flag delta: pre-deploy baseline `publication_eligible=false` (Task #20) -> lifted to true by this session; the literal baseline marker is preserved verbatim as the audit anchor.
- Deployed via `wrangler.v213.production.local.toml`; **worker 26454143… / then 928539bd…** at the workers.dev owner-line URL.
- Smoke: /health 200 (v213 2.1.3); /v213/readiness 409 challenge (echoes deployed version); retired /v213/admin/top20-report 410 SEALED_PUBLICATION_REQUIRED; unknown path 404; qualified Top20 (GEV 96.0 #1 / 6501 93.0 #2) served by the verified sealed pointer view.
- Flags: publication_eligible=true; LINE_LIVE=true. Freshness: seal stamp 2026-09-15T12:00Z -> ranking mandatory-latest wall-clock 2026-09-16T12:00Z (86400s cap); re-promote after.
### CURRENT TRUE PRODUCTION ARCHITECTURE (source of truth, 2026-09-16, Task #28)
- Primary Supervisor: Gemini. Local Writer: Qwen (Herdr persistent `qwen-worker`), single-writer discipline; all lanes local-only, no push.
- Production live: Cloudflare Worker `investor-intelligence-v21-owner-line` (v `928539bd…`; worker.ts/qa.ts certified) + KV: PUBLIC_CACHE `96142af4…` / TENANT_PRIVATE_CACHE / EPHEMERAL_SECURITY_CACHE (isolated).
- Active snapshot: run-bound sealed pointer `snapshot:current`; 60-min re-point; committed integrity runs: `897a86efa733` / `2873c2ff6316` / `f2a9ea873960`.
- Operations: fresh rebuild `publish_sealed_snapshot.py --live-clock`; sync `sync_sealed_snapshot_kv.py` (pointer-last, fail-closed); rollback `rollback_sealed_snapshot.py`; operator runbook `docs/OPERATOR_RUNBOOK.md`; gap ledgers `docs/LINE_GAP_LEDGER.md` / `docs/PROJECT_GAP_LEDGER.md`.

### PRODUCTION P0 + GAP LEDGER (Task #26, operator-authorized, 2026-09-16)
- Deployed worker `928539bd-e351-4832-9ad7-cebaeae7be37` (Task 025A fixes + options-guidance in production); re-pointed live run `20260916T131939Z-897a86efa733` (seal c9b19102; sync log: objects 14 -> readback 14/14 -> pointer LAST).
- Live probe (data/cache/probe-live-26.json): fresh Top20 GEV #1 / 6501 #2, no stale notice; SIVE & AAOI -> sealed_snapshot:unadmitted_symbol; ZZZZNOTEXIST -> general_qa, no hijack.
- docs/LINE_GAP_LEDGER.md: 31 items / 8 scopes, format-gated; P0s all closed with live evidence. Gates: npm 816/0/1, tsc 0, pytest 1511/0/3, security/canonical/line-boundary PASSED.

### Objectives Overview & Trust Invariants
Objectives: A = UNKNOWN rights; B = 7 references typed (unresolved outside corpus); C = scoped non-admitting hook; admission still capped TEST_ONLY tier.

Priority: evidence → admission → ranking → acceptance → sealed publication → LINE; identity/macro/options stay UNAVAILABLE (do NOT block LINE); never deploy unaccepted ranking/candidate.

## PROJECT-WIDE GAP AUDIT (Task #29, 2026-09-16)
- **PROJECT_WIDE_GAP_AUDIT = PASS** — `docs/PROJECT_GAP_LEDGER.md`: P0 = 0, P1 = 0; all P2 PASS or reasonably DEFERRED (PG-11 = research-lane DEFER; GEV/6501 admitted; 6508/ENR unadmitted).

## Completed Supervisor Evaluation: STATUTORY_AUTHORITY_FACT_EVALUATION_V1
- Factual non-protectability (17 U.S.C. § 102(b)) and OAL publication role (Gov Code § 11344) narrowed; terms remain binding; artifacts in `G/statutory-authority-facts-v1-*`.

## Completed Objective B Subtask: CARB_STATUTORY_CROSS_REFERENCE_TYPING_V1
- 7 legacy external references typed into structured immutable dataclass in `carb_typed_section_parser.py` (strict taxonomy, source-provenance-bound, `UNRESOLVED_OUTSIDE_CORPUS`); artifacts in `G/carb-statutory-cross-reference-typing-v1-*`.

## Triad Status Assessment
- **A (Unknowns Narrowed vs Remain):** Factual non-protectability (17 U.S.C. § 102(b)) and OAL publication role (Gov Code § 11344) narrowed; 4 preserved HTTP error states, Meidensha Terms, and Barclays online CCR terms remain UNKNOWN.
- **B (7 External References Typed & Unresolved):** Citations in `carb_typed_section_parser.py` are typed into structured immutable records but strictly remain `UNRESOLVED_OUTSIDE_CORPUS` (`limits_complete_interpretation: true`).
- **C (Scoped Non-Admitting Hook):** Accepted scoped non-admitting hook (`G/provider-runtime-hook-supervisor-review-v1-review.md`) is NOT product ready. Runtime admitted companies strictly 0; overall source admission strictly `STILL_BLOCKED_NOT_PASS`.

## Publication anchor
- `publication_eligible=true` since operator-authorized production deploy (2026-09-16); LINE delivery live on the owner-pairing channel; evidence tier stays TEST_ONLY-signed.
- Historical status snapshot for comparison: `git show 38860e7:state/STATUS.md`.

## Next runnable action
- Re-point: 60-min task `InvestorIntelligenceSealedFreshness` (auto).
- Evidence residuals: 6508/ENR 2nd-family sources (G-10); DOE 2026-03-05 before its 180-day window closes (G-11).
- Deferred lanes: R75 production certification chain; device broadcast testing (G-25).
- No outstanding routing/registration fixes (old session-tool routing text retired as stale 2026-09-16).

