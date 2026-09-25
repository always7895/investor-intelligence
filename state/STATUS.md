# Current state / 目前狀態

Updated 2026-09-25 by an operator-directed Claude Code session (master and writer for this change). Previous registers: V12 `git show 0f5358b:state/STATUS.md`; older history `git show 38860e7:state/STATUS.md`. Release identity stays in `README.md` (historical 2026-09-06 baseline).

## Identity

- Branch `fix/options-provenance-audit`, draft PR #37 to `main`. Base for this change: `79d23f8` (pushed).
- PR #37 CI has only reported COMPLETED_SKIPPED (latest run 36092036399). Skipped is not PASS and not release qualification.
- DEVELOPMENT_COMPLETE=false; FINAL_RELEASE_COMPLETE=false; PRODUCTION_CUTOVER_PENDING=false.

## This change — LINE Flex UI/UX redesign (development only)

Operator request 2026-09-25: a professional visual redesign of the existing UI. Source change only; no Worker deployment, LINE send, rich-menu upload or Production mutation.

- `cloud/src/v213/line-theme.ts` becomes a small design system: existing tokens unchanged, new semantic tokens (subtle, night/deepGreen header, on-dark text, negative, caution, alert) all at WCAG AA or better on their surfaces; components `productHeader`/`headerStyle` (gradient with solid fallback), `chip`, `sectionTitle`, `labelValue`, `kpiTile` (sign-aware colour, sign kept in text), `panel`, `divider`, `footnote`. Shared button contract kept (link, md, brand green).
- Top20 card: rank chip, 3xl ticker, three return KPI tiles, Returns/Company/Orders sections with the orders pair in a bordered green panel; seven labels still appear once each directly before their values; one footer button; 4 carousels × 5 kept.
- Options order and position-sizing cards rebuilt with KPI tiles, label/value rows and a caution panel; typo 認能價格 fixed to 標的價格 (Flex and text).
- Product headers and alert colours unified across rich menu, options product, macro industry, educational options and global equity lookup.
- Review preview (synthetic data, rendered from actual before/after JSON): private artifact https://claude.ai/artifact/CqRyqkqvhwDUqCZDLb6rcU
- Validation: see "Latest gate run" below.

## Previous changes

- `7b88bf7`, `79d23f8` research method refresh (SERENITY_LOGIC, ASCHENBRENNER_CONTEXT; full Python 2490 OK, 423.5 s) and C2b decision record.
- `4ee66d8` C2a forward comparison renderer (5 tests; full Python 2490 OK, 435.0 s).
- `c824b23` C1 `assess_forward_premises` premise-state shadow (12 tests; full Python 2485 OK, 460.6 s).
- `b88dd9f`, `51c7132` instructions, skill, MCP and design:
  - `AGENTS.md` (4774 B) and the research skill (SKILL.md 3955 B) restructured per agents.md, the Agent Skills specification and Anthropic authoring guidance; tested markers and the pinned oEmbed archive bytes kept. Installed skill resynchronized from `51c7132` (hashes match; backup `_archive/instruction-sync-20260925T065208Z/`).
  - Local, untracked: workspace `AGENTS.md`, `.pi/HANDOFF.md` current pointer, GitHub MCP server in `.mcp.json` (token read from the `gh` keyring at connect time; handshake HTTP 200). Untracked leftovers relocated to `_workspace/audit-runtime/v12-overnight-checkpoint-20260925/` and `_archive/`, not deleted.
  - Gates for that change: security, documentation boundary/structure, workflow supply chain and owner-config PASS; Worker typecheck PASS and 895 passed / 1 named manual skip; full Python 2473 OK in 424.3 s on a clean rerun. The first full run had 2 lock-contention failures while the live SealedFreshness task (14:56:15) held the operation lock; kept as evidence.
  - Observation only: `InvestorIntelligenceFreshnessWatchdog` returned 1 at 14:56:15 (not STALE code 3) without a watch line; the 15:26:15 run returned 0. No task changed.

## Latest gate run

Working tree of this change, 2026-09-25:

- Worker: `npm run typecheck` PASS; `npm test` 895 passed / 1 named manual skip (61 files) — existing contracts (seven-field inspector, one footer button, shared button style, header risk text, 4×5 carousels, no px/maxLines, LINE size limits) all hold.
- `security_check`, `documentation_boundary_gate`, `documentation_structure_gate`, `workflow_supply_chain_gate`, `owner_config_boundary_gate`: PASS.
- Full Python 15:57:27–16:04:47 (started after the 15:56 SealedFreshness run finished, result 0): 2490 tests OK, 439.0 s.

## Pending operator decision — redundancy removal

Bulk deletion of tracked files was stopped by the session permission guard and needs explicit operator approval. Read-only triage (no code, test, packaging or scheduled-task reference) found:

- 40 historical docs: `docs/SERENITY_H2…H6*` (25), `docs/SERENITY_PUBLIC_LOGIC_*` (3), `documents/TASK0-3E…3J` (6), `VALIDATION_TRANSACTION_NOTE_V2`, `W1_ATOMIC_IO_REVIEW_20260910`, `LUNA_MAX_IMPLEMENTATION_PLAN_20260910`, `CANONICAL_RELEASE_CANDIDATE_V2`, `V213_SERENITY_LOGIC_SOURCE_DIVERSITY_AUDIT`, `state/PHASE3_SOURCE_FEDERATION_STATUS.md`.
- Scripts/payloads: `run-v211-local.ps1`, `register-v211-task.ps1` (can re-point live v21 refresh task names), `register-v212-local-llm-bridge-task.ps1`, `.github/patch-payload/hotfix6.part0*`, `.github/patches/*.b64`, `cloud/wrangler.v211.production.template.toml`, `scripts/apply_final_serenity_r3_patch.py`, `scripts/normalize_v213_final_source_gate.ps1`, `scripts/ci_v213_hotfix6_validate.ps1`, superseded `audit_v213_serenity_release{,_v3,_v5,_v6}.ps1` and `audit_v213_generated_snapshot_v3.ps1`, one-off `scripts/test_v213_3*.py` harnesses, `scripts/test_v213_r75_publication_contract.ps1`.
- Workflows on dead branches: `phase3-authoritative-{adapters,catalog}-audit`, `phase3-source-diversity-audit`, `phase3-staged-gleif-ecb-audit`, `public-options-provider-candidates-audit`, `v21-serenity-engine`.
- Same change must lower two inventory floors: `tests/test_documentation_structure_gate.py` (Markdown ≥92) and `tests/test_powershell_source_syntax.py` (`.ps1` ≥84). Keep `audit_v213_generated_snapshot.ps1`/`_v5.ps1` (syntax-test probes), receipts, rollback jars, schemas and live-task scripts.

## Closed components — no reopening without regression evidence

All scoped development components; none is live, native, admission or release qualification.

- T1 finite fractional ordering (`5208d64`), T2 nonauthorizing period declarations (`26842de`), T3 forward comparison declaration diagnostic (`689a682` → token-naming repair `a944410`).
- O1 options venue coverage shadow (`11436e6`), Case9 sealed-view catalog exclusion (`c178127`), R3A declared capacity-headroom shadow (`e45c1d6`), research method quarantine (`c6ce527`).
- I1/I2/I3 identity shadows, E2A pure synthetic capacity component, hermetic company/statutory/Worker fixtures, capacity control/evidence/creation helpers.
- `43777fe` (baseline vs forward guidance claim-support tests) was committed after the V12 register; it is covered only by the full-suite run recorded here.
- Preserved failures and receipts (actual-SHA security failure of `689a682`, invalid targeted-scan coverage, harness defects, CI skips) remain immutable; details in the V12 register.

## Open lanes

1. **Forward comparison premises — C1 and C2a IMPLEMENTED; C2b awaits a trust-model decision:** [FORWARD_COMPARISON_PREMISES_V1](../docs/FORWARD_COMPARISON_PREMISES_V1.md) maps T3's six unresolved premises to admitted inputs from existing components (SEC CIK binding, claim-engine status and comparable fields, T2 period roles, source qualification), fixes the consumer to the local `data_report` side-by-side disclosure (never Top20 order fields) and names contracts C1 (pure premise-state function), C2 (local rendering) and C3 (live qualification). V1 computes no ratio, annualization or growth score; T3 publication does not complete FORWARD_REALIZABLE_GROWTH_POTENTIAL.
2. Deferred: O1 real venue and consumer admission; identity-to-Worker admission/rendering; R3A-to-V1 association/time/schema/consumer contract; U1/U2; real E2A/B; GB-S3 partial, S4/S5 blocked, Gate B pending; native/QA migration; Research V3, Top20, Macro, Options, zh-TW, LINE and integrated R75 shadow.
3. Hygiene: historical `git diff --check` EXIT2 findings deferred; Worker prior effects from old hidden Wrangler coupling remain UNKNOWN (old generated artifact untouched).

## Boundary flags

NATIVE_ATTEMPT_COUNT=0; NATIVE_EXECUTION_AUTHORIZED=false; CAPACITY_EVIDENCE=UNQUALIFIED; HARD_IO_TIMEOUT_PROVEN=false; publication_eligible=false; global P0 NOT_REAUDITED. Serenity primary; Leopold Aschenbrenner CONTEXT_ONLY.

## Control plane

Astra master; exact local Qwen sole tracked writer on the Pi lane; Sol independent read-only reviewer; JEV decision support only; Mapika retired (V12 operator override). A direct operator request in the current session may assign another agent for its scope without waiving boundaries.

## External mutations (this change)

Git commits on this branch and a normal push to `origin` (updates PR #37). Local workspace files listed above; installed skill directory resynchronized from source after commit with a backup in `_archive/instruction-sync-20260925T065208Z/`. No Production, KV, LINE, schedule, credential, billing, broker, model or service mutation.

## Next action

Operator: approve or decline the redundancy removal above; review the UI preview before any Worker deployment (deployment needs explicit authorization). C2b needs an operator choice between build-time digest, an archived-receipt contract or a separate local artifact (recommended), because SEC receipts are in-process only. Serenity originals need a permitted retrieval channel (oEmbed now HTTP 402); paid access requires explicit operator authorization.
