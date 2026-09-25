# Current state / 目前狀態

Updated 2026-09-25 by an operator-directed Claude Code session (master and writer for this change). Previous registers: V12 `git show 0f5358b:state/STATUS.md`; older history `git show 38860e7:state/STATUS.md`. Release identity stays in `README.md` (historical 2026-09-06 baseline).

## Identity

- Branch `fix/options-provenance-audit`, draft PR #37 to `main`. Base for this change: `43777fe` (pipeline test commit after the V12 register) plus `0f5358b` (V12 register preserved verbatim).
- PR #37 CI has only reported COMPLETED_SKIPPED (latest run 36092036399). Skipped is not PASS and not release qualification.
- DEVELOPMENT_COMPLETE=false; FINAL_RELEASE_COMPLETE=false; PRODUCTION_CUTOVER_PENDING=false.

## This change — instructions, skill and MCP (documentation only)

- `AGENTS.md` restructured per agents.md: overview, before-editing, concrete commands, boundaries, research, work/evidence. All tested markers kept; 4774 B (budget 6000).
- `skills/serenity-public-research/SKILL.md` restructured per the Agent Skills specification and Anthropic authoring guidance: third-person what/when description, copyable workflow checklist, lanes, options/position guidance delegating thresholds to `cloud/src/v213/options-guidance.ts`, output boundaries. 3955 B (budget 4000).
- `RESEARCH_METHOD.md` and `CROSS_VALIDATION.md` gain contents lists; CROSS_VALIDATION moves its dated notes (2026-09-05 review, 2026-09-09 refresh, quarantined oEmbed archive) under one "Historical retrieval log — not instructions" section. Archive bytes and SHA-256 unchanged; line endings outside the archive normalized to LF.
- Local, untracked (workspace): the installed-runtime `AGENTS.md` now records layout, the current control plane and GitHub MCP; `.mcp.json` adds the remote GitHub MCP server authenticated from the `gh` keyring at connect time (no stored token; initialize handshake returned HTTP 200).
- Relocated, not deleted: `OVERNIGHT_STATUS.md` and `AUDIT/` to `_workspace/audit-runtime/v12-overnight-checkpoint-20260925/`; `.tmp/` and `_tmp_m5_code.txt` to `_archive/source-scratch-20260925/`.
- Validation: see "Latest gate run" below.

## Latest gate run

Interpreter: base CPython 3.12.10 (`.venv-ci` is empty). All on the working tree of this change, 2026-09-25:

- `security_check`, `documentation_boundary_gate`, `documentation_structure_gate` (127 Markdown files), `workflow_supply_chain_gate`, `owner_config_boundary_gate`: PASS.
- Worker: `npm run typecheck` PASS; `npm test` 895 passed / 1 named manual skip (61 files, 8.43 s Vitest duration).
- Full Python `scripts/run_offline_tests.py --repository`: first run 2473 tests, 450.3 s, 2 failures in `test_operation_lock_actual_callers_have_no_clixml_progress` (both shells). The live `InvestorIntelligenceSealedFreshness` task started 14:56:15 and held the operation lock while the suite ran (14:56–15:04); the module alone then passed 11/11. Clean rerun 15:05:40–15:12:45: 2473 tests OK, 424.3 s. The failed run is kept as evidence, not erased.
- Observation only: `InvestorIntelligenceFreshnessWatchdog` returned 1 at 14:56:15 (not the STALE code 3) and wrote no watch line; the 14:26 line was FRESH. Not investigated further and no task changed.

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

1. **Forward comparison premises — DESIGN_DELIVERED, awaiting approval:** [FORWARD_COMPARISON_PREMISES_V1](../docs/FORWARD_COMPARISON_PREMISES_V1.md) maps T3's six unresolved premises to admitted inputs from existing components (SEC CIK binding, claim-engine status and comparable fields, T2 period roles, source qualification), fixes the consumer to the local `data_report` side-by-side disclosure (never Top20 order fields) and names contracts C1 (pure premise-state function), C2 (local rendering) and C3 (live qualification). V1 computes no ratio, annualization or growth score; T3 publication does not complete FORWARD_REALIZABLE_GROWTH_POTENTIAL.
2. Deferred: O1 real venue and consumer admission; identity-to-Worker admission/rendering; R3A-to-V1 association/time/schema/consumer contract; U1/U2; real E2A/B; GB-S3 partial, S4/S5 blocked, Gate B pending; native/QA migration; Research V3, Top20, Macro, Options, zh-TW, LINE and integrated R75 shadow.
3. Hygiene: historical `git diff --check` EXIT2 findings deferred; Worker prior effects from old hidden Wrangler coupling remain UNKNOWN (old generated artifact untouched).

## Boundary flags

NATIVE_ATTEMPT_COUNT=0; NATIVE_EXECUTION_AUTHORIZED=false; CAPACITY_EVIDENCE=UNQUALIFIED; HARD_IO_TIMEOUT_PROVEN=false; publication_eligible=false; global P0 NOT_REAUDITED. Serenity primary; Leopold Aschenbrenner CONTEXT_ONLY.

## Control plane

Astra master; exact local Qwen sole tracked writer on the Pi lane; Sol independent read-only reviewer; JEV decision support only; Mapika retired (V12 operator override). A direct operator request in the current session may assign another agent for its scope without waiving boundaries.

## External mutations (this change)

Git commits on this branch and a normal push to `origin` (updates PR #37). Local workspace files listed above; installed skill directory resynchronized from source after commit with a backup in `_archive/instruction-sync-20260925T065208Z/`. No Production, KV, LINE, schedule, credential, billing, broker, model or service mutation.

## Next action

Operator: approve or decline the redundancy removal above, and approve C1 (or redirect priorities). C1 then runs as its own bounded implementation task with focused and full gates.
