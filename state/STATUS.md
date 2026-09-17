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

### TASK0 Operability Audit — Phase 1B (2026-09-17T10:55–11:05Z; Pro-supervised)
- AUDITED_CODE_SHA `ab1bcca`; BASE_CHECKOUT_SHA at 1B close = `ea07194` (docs-only delta over audited code); docs commits `4c57264`→`ea07194` pushed to branch (CI inert: workflow eval vs branch+PR#37 verified; Draft).
- REMOTE (1× per endpoint): /health 200 @10:55:12Z (v2.1.3, owner_only); /v213/readiness 200 `worker_version=c7abe74d…`, challenge echo matches, no_write=true, ready=true → version/readiness checkpoint passed (synthetic probe, not a functional test). KV CLI read 401 → **BLOCKED_READ_ACCESS** (no local CLI creds; sealing holds). Remote pointer = UNVERIFIED; newest **local refresh record (not an observation)** = `095616Z` (17:56+08, 15/15 readback, REFRESH OK).
- Scheduling mismatch (task display vs hourly disk runs): cause undetermined (task path / dup task / other process / TZ conversion unexcluded); display-only.
- CALLERS (LOCAL_FULL_CALLER_REPLAY; exported fetch → fixed run `092410Z` MemoryKv → memory LINE transport; 0 net writes; waits concluded):
  PASS (in-memory scope only): Macro TOP5 / TOP5 / Top20 (GEV 96.0 #1, 6501 93.0 #2, 7-field + anchor + TEST_ONLY disclosures), SIVE/AAOI/6508/ENR unadmitted fail-closed with correct closed reason, invalid ticker fallback + answer-after verified, stale/seal-mismatch in-memory negatives rejected.
  Suite: vitest 818/0/1; tsc 0; pytest 1520 passed / **3 FAIL** / 3 skip (local suite scope, not live E2E).
- TOP_DEFECTS: (1) **reproduced P1** `test_cli_builder_synthetic_fixture` — subprocess text pipe cp950 vs UTF-8 CLI output (byte 43/0xE7) → stdout None → json.loads None; file byte-identical at 3c7497e (not a version regression); min fix = pin that call `encoding="utf-8"` (CLI-side hardening scope pending Pro sign-off). (2) **P2 pending** operation-lock subtests fail full-suite load only (standalone PASS); 0s lock-timeout race hypothesis; discriminator = full-suite rerun + subtest -v. (3) **P1 suspect (unverified)**: worker local model chain — free-relay DurableObject `current-local-route` lease (TTL 300s, generation-guarded; expiry → `FREE_RELAY_UNAVAILABLE`) + model profile pin (`model_profile_sha256`, `selected_model`, substitution forbidden); toml name `qwen38-q6` vs tabbyAPI served `Qwen3.8-27B-EXL3-SC5-H6-V6` — lease expiry / name mismatch = top general-QA candidate; route producer unverified; report only, no refresh.
- LOCAL_CHAIN: `127.0.0.1:5000` = **UNKNOWN / dependency pending confirmation** (operational identity: PID exe `D:\tabbyAPI\venv\python.exe start.py`, OpenAI-compatible /v1 shape, /health 200 ⇒ serving tabbyAPI locally); 8080 relay absent (contract residue). Direct tabby oneshot: finish=stop + exact echo = PASS direct only; worker-route chain unverified (see P1 lease).
- SCOPE caveat: any FAIL-0 claim is limited to the executed in-memory scope; live E2E / LINE delivery / remote pointer NOT covered (BLOCKED_*).

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

