# Current state / 目前狀態

## INVESTOR_FULL_AUTOPILOT_V2 — UNATTENDED_CONTINUOUS

Committed HEAD: `98f4a18` (previous baseline `d15577d`), branch `fix/options-provenance-audit`, no push. `LINE_LIVE=false`; `FINAL_RELEASE_COMPLETE=false`. Aggregate P0/P1/P2 counts UNKNOWN, not zero. Release identity belongs in README.

### Milestones (2026-09-15 verified-green baseline session)
- `cd39599` chore: ignore local build artifacts (InvestorIntelligence.exe, cloud/config/).
- `7d2a9f9` fix: restore reviewed baseline gates - STATUS publication anchors; ECB fx-reference replay admission completed atomically (registration + evidence builder, reviewed route, catalog row, count pins 101->102 / 116->117); credential store extracted to launcher/SecureCredentialStore.cs (launcher = bridge + reflection stub); worker.ts holds reviewed blob 4e0f78af.
- `f031c36` fix(cloud): deterministic option-contract test clocks (evaluatedAt pass-through, pinned fixtures) + reader card-label alignment.
- `dce6d73` feat: bounded statutory and claim-admission modules (carb_typed_section_parser, company_claim_admission_bridge + adapters/company_public_document, provider_runtime_hook) with docs and passing tests.

### Milestones (2026-09-15 session 2: module integration slices)
- `fc145e1` feat: source acquisition & symbol directory enhancements (directory conflict quarantine; typed CompanyFactorBinding + authority gating; independent-lineage dedupe).
- `96fdc1e` feat: bounded bottleneck ranking & claim-admission engine (policy pin, fail-closed admission, trust-boundary + takeover tests).
- `0c0a8f3` feat: global identity resolver & equity lookup module layer (closed taxonomy, sealed catalog admission, presentation-only quotes; no caller wiring; worker.ts / qa.ts untouched).
- All three slices re-verified: pytest 1470 passed / 0 failed / 3 skipped; cloud vitest 759 passed / 0 failed / 1 skipped.
- Still uncommitted/external by policy: 4 quarantined WIP cloud test files (global-equity-worker-flow, bottleneck-takeover(-review)) + 1317-line WIP diff parked at D:\AI-Handoffs\investor-intelligence\wip-cloud\; cloud/wrangler.v213.production.local.toml and HOTFIX-REFS.json remain local-untracked (local config / ops draft).
- Test state verified at every commit: pytest 1470 passed / 0 failed / 3 skipped; cloud vitest 759 passed / 0 failed / 1 skipped.
- Uncommitted by policy: unaccepted WIP (bottleneck takeover, global identity/lookup) incl. 4 quarantined test files and WIP diff parked at D:\AI-Handoffs\investor-intelligence\wip-cloud\; WIP-modified docs (BOTTLENECK_RANKING_V1, LINE_TOP20_UI, README) and in-flight scripts (source_acquisition, source_observation, nasdaq_symbol_directory, bottleneck_ranking, bottleneck_claim_admission, global_identity_index) remain in the worktree pending acceptance.


### Milestones (2026-09-15 session 3: bottleneck takeover & global lookup re-integration)
- `fc2b99b` feat(v213): sealed bottleneck-policy lane (qualified sealed report -> bounded 1..20 projection with bound reference; sealed view without qualified authority -> certified seven-field sealed report, else INSUFFICIENT_EVIDENCE; legacy views keep certified flow); strict two-variant deep-analysis admission; non-hijacking global_equity_lookup intent + v211 worker intercept (worker.ts/qa.ts untouched); 4 quarantined tests restored (checksum-verified); gitignore += cloud/*.local.toml, HOTFIX-REFS.json.
- Test state: vitest 784 passed / 2 residual / 1 skipped (787); pytest 1470 passed / 0 failed / 3 skipped.
- Residual (session-3 ledger, RESOLVED by session-4 `98f4a18`): 2 raw-view takeover assertions conflicted with committed pre-migration serve semantics; arbitrator ruled takeover authoritative - pointerless raw writes now fail closed, pre-migration fixtures migrated to sealed bundles, both assertions green.

### Milestones (2026-09-15 session 4: raw-view contract arbitration)
- `98f4a18` fix(v213): unsealed pointerless raw-key seven-field writes now fail closed to INSUFFICIENT_EVIDENCE (takeover authoritative; sealed-object-integrity + pointer-last mandatory). Ranking intent extended with 前20/排行 so every Top20 alias is policy-gated.
- Test fixtures migrated to sealed run-bound snapshots (verbatim re-packaging via cloud/test/sealed-report-migration.ts) in 7 pre-migration suites incl. the 4 named. v213-bottleneck-takeover-review DEFECT 1 RED + ALL TOP20 aliases now PASS - the session-3 residual conflict ledger entry is RESOLVED by arbitration.
- Test state: vitest **786 passed / 0 failed / 1 skipped (787)**; pytest **1470 passed / 0 failed / 3 skipped**.
- Invariants: cloud/src/worker.ts byte-frozen at reviewed blob 4e0f78af; cloud/src/qa.ts untouched; zero network to real providers; no production mutations.
### Supervisor & Routing Policy (Latest User Override)
- **Primary Supervisor:** Gemini approved route.
- **Requested Primary Executor:** `tabby-local/Qwen3.8-27B-EXL3-SC5-H6-V6` (no llama.cpp cached fallback; no second server).
- **Astra Role:** Irreversible architecture decisions, safety blocker, and final Production-deploy gate only while quota > 0; Gemini supervisor takes acceptance if exhausted. No ordinary research or implementation assigned to Astra.
- **Local Route Status & Corrected Blocker Observation:**
  - Blocker reference: `G/qwen-session-tool-registration-blocker-v1.json`.
  - The retired helper `qwen_route_status` failed and current exposed Agent refuses dispatch.
  - `qwen_routed: false`; reason: `CURRENT_SESSION_TOOL_ROUTING_NOT_BACKEND_HEALTH`.
  - **Factual Correction:** Stale routing helper failures do **NOT** prove that the underlying Tabby backend model is missing, offline, or misconfigured. Rather, the current session tool registration cannot satisfy the project binding in `.pi/agents/qwen-executor.md`. Model binding configuration is distinct from live verification.
  - No Qwen inference occurred, no task ID was created, 0 tokens consumed. No guard bypass, server spawning, model switching, or Pi configuration repair attempted.
  - Gemini mechanical fallback executed for bounded task `CARB_STATUTORY_CROSS_REFERENCE_TYPING_V1`.

### Objectives Overview & Trust Invariants
Zero new provider network requests. Runtime admitted companies strictly 0. Source admission status overall: `STILL_BLOCKED_NOT_PASS` (Objective A UNKNOWN rights remain; Objective B has 7 external references typed as immutable records but still unresolved outside corpus; Objective C hook accepted as scoped non-admitting only).

Priority: company evidence → typed admission → qualified ranking → one final semantic acceptance → sealed publication/new UI → Flex/rich menu/device → LINE_LIVE. Global identity/Macro/Options without Production evidence stay UNAVAILABLE and do NOT block safe LINE launch; preserve identity work. EXE/credentials/R75/private release deferred. Never deploy unaccepted ranking/candidate.

## Completed Supervisor Evaluation: STATUTORY_AUTHORITY_FACT_EVALUATION_V1
- **Lane & Scope:** `INDEPENDENT_SUPERVISOR_STATUTORY_AUTHORITY_FACT_EVALUATION_V1`.
- **Outputs:** `G/statutory-authority-facts-v1-{fetch.py,findings.json,evidence.json,acceptance-summary.txt}` and `G/statutory-authority-facts-v1-public/source-01.txt..source-05.txt`.
- **Core Factual Findings:**
  1. **CCR Publishing Body:** California Office of Administrative Law (OAL) is statutory publisher under Gov Code § 11344(a); contracts with Barclays (Thomson Reuters) for free online access. Mandate provides public access, NOT commercial redistribution licenses. Title 24 maintained by BSC and excluded from OAL CCR.
  2. **Actual § 11344 Text:** Establishes 5 duties (compilation/free Internet access, pending filing links, weekly supplement, rapid printing, citations). Does NOT prove currency of specific regulations or resolve external citations.
  3. **Copyright Scope (Facts vs Expression & Fair Use):** 17 U.S.C. § 102(b) confirms copyright does not protect raw facts/ideas (dates, kV thresholds, citations). Contractual terms remain binding. 17 U.S.C. § 107 requires 4-factor balancing; technical caps (200 words) are architectural limits, not automatic statutory allowances.
  4. **Federal Works vs State/Private:** 17 U.S.C. § 105 applies strictly to federal government works. Edicts of government covers binding legal text, not agency web layouts or commentary.

## Completed Objective B Subtask: CARB_STATUTORY_CROSS_REFERENCE_TYPING_V1
- **Lane & Scope:** `CARB_STATUTORY_CROSS_REFERENCE_TYPING_V1` (Gemini Primary Supervisor fallback execution; `qwen_routed: false`).
- **Target Files:** `scripts/carb_typed_section_parser.py`, `tests/test_carb_statutory_citations.py`, `docs/CARB_TYPED_SECTION_PARSER.md`.
- **Evidence Files:** `G/carb-statutory-cross-reference-typing-v1-{evidence.json,security-diff.md,acceptance-summary.txt,clock.json}`.
- **Core Implementation:**
  1. **Immutable Dataclass:** Added `@dataclass(frozen=True) class StatutoryCitation` with fields `citation_id`, `reference_class`, `statutory_body`, `title`, `section`, `source_anchor`, `span`, `unresolved_outside_corpus=True`, `limits_complete_interpretation=True`, `status="UNRESOLVED_OUTSIDE_CORPUS"`.
  2. **Closed Taxonomy (`ReferenceClass`):** Strict taxonomy distinguishes `HealthSafetyCode` (3), `40CFR` (1), `17CCR` (2), `consensusstandards` (1), `OTHER` (0), `UNPARSEABLE` (0). Total exactly 7 legacy external references.
  3. **Source Provenance:** All 7 citations bound to literal anchors in `carb-final-regulation.md` with exact character spans and SHA-256 hashes.
  4. **Fail-Closed Malformed Input:** `classify_statutory_reference` maps unknown/malformed strings to `UNPARSEABLE` or `OTHER`, retaining unresolved/limits interpretation flags.
  5. **Invariants Preserved:** `runtime_admitted=False`, `company_admissions=0`, 4 core factor gates `UNQUALIFIED`, Table 1 & 2 boundary equality intact, backward compatibility intended; prior21-test suite not rerun, so no fresh full-compatibility claim.
- **Tests & Progression:**
  - Initial RED log retained in `carb-statutory-cross-reference-typing-v1-python-red.log` (1 import error; NOT behavioral RED).
  - INITIAL passed in `carb-statutory-cross-reference-typing-v1-python-initial.log` (8 focused tests, 0 failures, 0 errors, 0.116s).
  - Documentation structure gate passed (106 markdown files, 618,861 bytes).

## Triad Status Assessment
- **A (Unknowns Narrowed vs Remain):** Factual non-protectability (17 U.S.C. § 102(b)) and OAL publication role (Gov Code § 11344) narrowed; 4 preserved HTTP error states, Meidensha Terms, and Barclays online CCR terms remain UNKNOWN.
- **B (7 External References Typed & Unresolved):** Citations in `carb_typed_section_parser.py` are typed into structured immutable records but strictly remain `UNRESOLVED_OUTSIDE_CORPUS` (`limits_complete_interpretation: true`).
- **C (Scoped Non-Admitting Hook):** Accepted scoped non-admitting hook (`G/provider-runtime-hook-supervisor-review-v1-review.md`) is NOT product ready. Runtime admitted companies strictly 0; overall source admission strictly `STILL_BLOCKED_NOT_PASS`.

## Publication anchor
- `publication_eligible=false` until source admission reaches PASS (triad B/C remain blocked).
- Historical status snapshot for comparison: `git show 38860e7:state/STATUS.md`.

## Next runnable action
- **Session Tool Registration:** Update session tool registration to honor `.pi/agents/qwen-executor.md` so local Qwen executor can be dispatched without error.
- **Do not replay C:** Its scoped non-admitting implementation and supervisor review already completed. Prior handoff requesting C again is stale. Qwen dispatch awaits current-session Agent registration; no repeated route checks or alternate-model dispatch.
- **Supervisor Action:** Continue independent semantic auditing without bypass; source admission remains `STILL_BLOCKED_NOT_PASS`.
