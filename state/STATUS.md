# Current state / 目前狀態

## INVESTOR_FULL_AUTOPILOT_V2 — UNATTENDED_CONTINUOUS

Committed HEAD: `bba00fa` (statutory authority resolution; prior `78d4dee`/`e43be26`/`98f4a18`), branch `fix/options-provenance-audit`, no push. `LINE_LIVE=false`; `FINAL_RELEASE_COMPLETE=false`. Aggregate P0/P1/P2 counts UNKNOWN, not zero. Release identity belongs in README.

### Milestones (2026-09-15 verified-green baseline session)
- `cd39599` chore: ignore local build artifacts.
- `7d2a9f9` fix: reviewed baseline gates restored (STATUS anchors; ECB fx-reference atomic admission + catalog row 101->102/116->117; credential store -> launcher/; worker.ts = blob 4e0f78af).
- `f031c36` fix(cloud): deterministic option-contract test clocks (evaluatedAt pass-through) + reader label alignment.
- `dce6d73` feat: bounded statutory & claim-admission modules (carb parser, company claim bridge, provider hook) + tests.

### Milestones (2026-09-15 session 2: module integration slices)
- `fc145e1` feat: source acquisition & symbol directory (conflict quarantine; typed CompanyFactorBinding + authority gating; lineage dedupe).
- `96fdc1e` feat: bounded bottleneck ranking (factors, evidence, resolution, answer) + bounded claim-admission bridge.
- `0c0a8f3` feat: global equity lookup + sealed global identity index (module layer; NO worker/rich-menu/core call-side wiring - defers to acceptance lane).
Each step: pytest 1470/0/3 green; vitest 759/0/1 green.

### Milestones (2026-09-15 session 3: bottleneck takeover & global lookup re-integration)
- `fc2b99b` feat(v213): sealed bottleneck-policy lane; strict two-variant deep-analysis admission; non-hijacking global_equity_lookup intent + v211 intercept; 4 quarantined tests restored (checksum-verified); worker.ts/qa.ts untouched.
- Residual ledger: 2 raw-view takeover assertions conflicted with committed pre-migration serve suites; resolved by session-4 arbitration.

### Milestones (2026-09-15 session 4: raw-view arbitration)
- `98f4a18`: pointerless raw 7-field writes fail closed to INSUFFICIENT_EVIDENCE (takeover authoritative); ranking intent now gates every Top20 alias (incl. 2H20/hai-power forms).
- 7 pre-migration fixtures (incl. named 4) migrated to sealed run-bound bundles (sealed-report-migration.ts); DEFECT-1 RED + ALL TOP20 aliases PASS.
- vitest 786/0/1; pytest 1470/0/3.

### Milestones (2026-09-15 session 5: typecheck cleanup)
- `f297a43`: 4 optional helper params typed (Awaited<ReturnType<typeof ...>>); tsc --noEmit 0. vitest 786/0/1.

### Milestones (2026-09-15 session 6: routing resolution & evidence bridge)
- ROUTING RESOLVED: blocker `qwen-session-tool-registration-blocker-v1.json` (sha 6e7bfe9a) superseded by dedicated Herdr worker `qwen-worker` w4:p2 (tabby-local / Qwen3.8-27B-EXL3-SC5-H6-V6); no SKYRIM context sharing; GLOBAL_QWEN_ACTIVE<=1 task-boundary lock; record state/qwen-routing-resolution-v1.json.
- Company Evidence bridge: 12/12; fail-closed (INVALID_JSON / schema / record-count rejects); empty canonical run -> 0 candidates, 0 runtime_admitted_claims, scope RESEARCH_CANDIDATES_ONLY_NOT_ADMITTED, zero network.
- `da57db6` test(Options): evaluatedAt pinned on validator call sites (16 wall-clock DTE drift failures eliminated).
- Baseline: pytest 1470/0/3; vitest 786/0/1; tsc 0.

### Milestones (2026-09-15 session 7: security gate placeholder fix)
- `e43be26` test(claim-bridge): token_urls vector now uses ALLOWED_VALUE_PATTERNS-compliant EXAMPLE_* prefixes (EXAMPLE_TOKEN_123 / EXAMPLE_API_KEY_456 / EXAMPLE_AUTH_789) with matching assertNotIn leak checks. `python scripts/security_check.py` -> SECURITY CHECK PASSED (exit 0). No behavior change; pytest 1470/0/3, vitest 786/0/1 re-confirmed.


### Milestones (2026-09-15 sessions 8-9: options guidance & statutory authority)
- `78d4dee` feat(v213): options order guidance + Serenity position sizing engine (delta band 0.20-0.30, LIMIT-only mid band, exact yield, liquidity gates, caps 12/4/2%, 20% reserve); 20 tests; no broker mutation. vitest 806/0/1, tsc 0.
- `bba00fa` docs+test: docs/STATUTORY_AUTHORITY_RESOLUTION_V1.md (11344(a) OAL duties; 17 U.S.C. 102(b) + Georgia v. PUBLIC.RESOURCE.ORG edicts; CCR Title 17 95350-95359.1 approved 2021-12-30 / effective 2022-01-01; 7 typed citations; preserved 404/301 states) + tests/test_statutory_authority_resolution.py (anchors/spans/SHA-256, fail-closed UNPARSEABLE/OTHER, runtime_admitted False, company_admissions 0) + docs/README gate link.
- Baseline: pytest 1477/0/3 (1470 + 7); vitest 806/0/1; tsc 0.

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
