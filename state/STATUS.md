# Current state / 目前狀態

Updated 2026-09-25 by an operator-directed Claude Code session (master and writer for this change). Previous registers: V12 `git show 0f5358b:state/STATUS.md`; older history `git show 38860e7:state/STATUS.md`. Release identity stays in `README.md` (historical 2026-09-06 baseline).

## Identity

- Branch `fix/options-provenance-audit`, draft PR #37 to `main`. Base for this change: `4ee66d8` (pushed).
- PR #37 CI has only reported COMPLETED_SKIPPED (latest run 36092036399). Skipped is not PASS and not release qualification.
- DEVELOPMENT_COMPLETE=false; FINAL_RELEASE_COMPLETE=false; PRODUCTION_CUTOVER_PENDING=false.

## This change — research method refresh (Serenity depth, Aschenbrenner context)

Operator request 2026-09-25: refresh the method from the latest public sources and make the Serenity and Leopold Aschenbrenner logic detailed. Boundaries unchanged: Serenity primary, Aschenbrenner CONTEXT_ONLY, no scoring, universe or weight change.

- New `references/SERENITY_LOGIC.md`: constraint-in-time model (demand ramp, effective supply, time to substitute; bottleneck/chokepoint/beneficiary mapped to existing labels), ten-question chain with the evidence that answers each, layer-first worked stack, information-gap timing, financing override, macro overlays, risk/reflexivity/survivorship, falsifier checklist, verification status.
- New `references/ASCHENBRENNER_CONTEXT.md`: the essay's quantitative chain from primary pages (OOM counting, cluster and investment tables, power then CoWoS/HBM as binding constraints, stated error bars), testable variables with falsifiers, a secondary two-year scorecard, and a dated SEC snapshot (13F 2026-03-31 and 2026-06-30, SharonAI 13D/13D-A) with explicit 13F limits.
- SKILL.md links both (3990 B); CROSS_VALIDATION records the 2026-09-25 refresh: X oEmbed now returns HTTP 402, so Serenity originals stay UNVERIFIED; EDGAR filings are primary. Packaged research payload, its verifier, validator allowlist and payload tests now include the two references. Legacy `skills/*.md` point to them.
- Validation: see "Latest gate run" below.

## Previous changes

- `4ee66d8` C2a forward comparison renderer (5 tests; full Python 2490 OK, 435.0 s).
- `c824b23` C1 `assess_forward_premises` premise-state shadow (12 tests; full Python 2485 OK, 460.6 s).
- `b88dd9f`, `51c7132` instructions, skill, MCP and design:
  - `AGENTS.md` (4774 B) and the research skill (SKILL.md 3955 B) restructured per agents.md, the Agent Skills specification and Anthropic authoring guidance; tested markers and the pinned oEmbed archive bytes kept. Installed skill resynchronized from `51c7132` (hashes match; backup `_archive/instruction-sync-20260925T065208Z/`).
  - Local, untracked: workspace `AGENTS.md`, `.pi/HANDOFF.md` current pointer, GitHub MCP server in `.mcp.json` (token read from the `gh` keyring at connect time; handshake HTTP 200). Untracked leftovers relocated to `_workspace/audit-runtime/v12-overnight-checkpoint-20260925/` and `_archive/`, not deleted.
  - Gates for that change: security, documentation boundary/structure, workflow supply chain and owner-config PASS; Worker typecheck PASS and 895 passed / 1 named manual skip; full Python 2473 OK in 424.3 s on a clean rerun. The first full run had 2 lock-contention failures while the live SealedFreshness task (14:56:15) held the operation lock; kept as evidence.
  - Observation only: `InvestorIntelligenceFreshnessWatchdog` returned 1 at 14:56:15 (not STALE code 3) without a watch line; no task changed.

## Latest gate run

Interpreter: base CPython 3.12.10. Working tree of this change, 2026-09-25:

- `security_check`, `documentation_boundary_gate`, `documentation_structure_gate`, `workflow_supply_chain_gate`, `owner_config_boundary_gate`: PASS.
- Focused: skill structure, attribution, packaged research payload and both documentation-gate test modules — 39 OK.
- Full Python `scripts/run_offline_tests.py --repository` 15:32:22–15:39:27: 2490 tests OK, 423.5 s (includes PowerShell syntax checks of the edited packaging scripts).
- Worker unchanged (no `cloud/` edits).

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

1. **Forward comparison premises — C1 and C2a IMPLEMENTED, next C2b:** [FORWARD_COMPARISON_PREMISES_V1](../docs/FORWARD_COMPARISON_PREMISES_V1.md) maps T3's six unresolved premises to admitted inputs from existing components (SEC CIK binding, claim-engine status and comparable fields, T2 period roles, source qualification), fixes the consumer to the local `data_report` side-by-side disclosure (never Top20 order fields) and names contracts C1 (pure premise-state function), C2 (local rendering) and C3 (live qualification). V1 computes no ratio, annualization or growth score; T3 publication does not complete FORWARD_REALIZABLE_GROWTH_POTENTIAL.
2. Deferred: O1 real venue and consumer admission; identity-to-Worker admission/rendering; R3A-to-V1 association/time/schema/consumer contract; U1/U2; real E2A/B; GB-S3 partial, S4/S5 blocked, Gate B pending; native/QA migration; Research V3, Top20, Macro, Options, zh-TW, LINE and integrated R75 shadow.
3. Hygiene: historical `git diff --check` EXIT2 findings deferred; Worker prior effects from old hidden Wrangler coupling remain UNKNOWN (old generated artifact untouched).

## Boundary flags

NATIVE_ATTEMPT_COUNT=0; NATIVE_EXECUTION_AUTHORIZED=false; CAPACITY_EVIDENCE=UNQUALIFIED; HARD_IO_TIMEOUT_PROVEN=false; publication_eligible=false; global P0 NOT_REAUDITED. Serenity primary; Leopold Aschenbrenner CONTEXT_ONLY.

## Control plane

Astra master; exact local Qwen sole tracked writer on the Pi lane; Sol independent read-only reviewer; JEV decision support only; Mapika retired (V12 operator override). A direct operator request in the current session may assign another agent for its scope without waiving boundaries.

## External mutations (this change)

Git commits on this branch and a normal push to `origin` (updates PR #37). Local workspace files listed above; installed skill directory resynchronized from source after commit with a backup in `_archive/instruction-sync-20260925T065208Z/`. No Production, KV, LINE, schedule, credential, billing, broker, model or service mutation.

## Next action

Operator: approve or decline the redundancy removal above. Development continues with C2b (replayable `data_report` wiring, still `publication_eligible=false`). Serenity originals need a permitted retrieval channel (oEmbed now HTTP 402); paid access requires explicit operator authorization.
