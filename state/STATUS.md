# Current state / 目前狀態

Updated 2026-09-25 by an operator-directed Claude Code session (master and writer for this change). Previous registers: V12 `git show 0f5358b:state/STATUS.md`; older history `git show 38860e7:state/STATUS.md`. Release identity stays in `README.md` (historical 2026-09-06 baseline).

## Identity

- Branch `fix/options-provenance-audit`, draft PR #37 to `main`. Base for this change: `292f274` (pushed).
- PR #37 CI has only reported COMPLETED_SKIPPED (latest run 36092036399). Skipped is not PASS and not release qualification.
- DEVELOPMENT_COMPLETE=false; FINAL_RELEASE_COMPLETE=false; PRODUCTION_CUTOVER_PENDING=false.

## This change — LINE card design (operator-approved direction) and source activation plan

- LINE Flex cards: black-to-graphite 135° gradient identity band (solid black fallback) with a brand-green rank chip, 3xl bold ticker and bold company name; body split into framed sections by information level with tinted title strips — Returns (green), Company (slate), Orders (amber); section titles sm bold; key values bold (return KPIs, industry, profit summary, current orders). Same system on options order, position sizing and menu panels; all product headers share the dark band. Earlier warm and plain variants were rejected by the operator. All text at WCAG AA or better; seven-field order, single footer button, shared button style, 4×5 carousels and LINE size limits unchanged (Top20 bubble ≈6.5 KB). Preview (version 6): https://claude.ai/artifact/CqRyqkqvhwDUqCZDLb6rcU
- [SOURCE_ACTIVATION_PLAN_V1](../docs/SOURCE_ACTIVATION_PLAN_V1.md): operator rule "no single source". Measured: 158 catalogued sources, 1 runtime-enabled (ECB FX), 125 planned adapters, 32 manual-only; Top20 prices and industry come from yfinance only. Plan: per-source rights → adapter → access → admission → wiring, in three waves starting with official open data whose adapters already exist.

## Previous changes

- `6ba8e6d`, `292f274` installer fixture retention, C2b local artifact and recorded operator decisions (full Python 2502 OK).
- `0c61b53` removal of 74 unreferenced docs, scripts and workflows (full Python 2497 OK).
- `34417b9` Top20 sourced-wording guard, phase 1 (full Python 2497 OK, 429.4 s).
- `79438c2` weekly/monthly options guidance (Worker 900 passed; full Python 2490 OK, 437.3 s).
- `c665684` LINE Flex redesign on a shared design system (Worker 895 passed; full Python 2490 OK, 439.0 s). Preview: https://claude.ai/artifact/CqRyqkqvhwDUqCZDLb6rcU
- `7b88bf7`, `79d23f8` research method refresh (SERENITY_LOGIC, ASCHENBRENNER_CONTEXT; full Python 2490 OK, 423.5 s) and C2b decision record.
- `4ee66d8` C2a forward comparison renderer (5 tests; full Python 2490 OK, 435.0 s).
- `c824b23` C1 `assess_forward_premises` premise-state shadow (12 tests; full Python 2485 OK, 460.6 s).
- `b88dd9f`, `51c7132` instructions, skill, MCP and design:
  - `AGENTS.md` (4774 B) and the research skill (SKILL.md 3955 B) restructured per agents.md, the Agent Skills specification and Anthropic authoring guidance; tested markers and the pinned oEmbed archive bytes kept. Installed skill resynchronized from `51c7132` (hashes match; backup `_archive/instruction-sync-20260925T065208Z/`).
  - Local, untracked: workspace `AGENTS.md`, `.pi/HANDOFF.md` current pointer, GitHub MCP server in `.mcp.json` (token read from the `gh` keyring at connect time; handshake HTTP 200). Untracked leftovers relocated to `_workspace/audit-runtime/v12-overnight-checkpoint-20260925/` and `_archive/`, not deleted.
  - Gates for that change: security, documentation boundary/structure, workflow supply chain and owner-config PASS; Worker typecheck PASS and 895 passed / 1 named manual skip; full Python 2473 OK in 424.3 s on a clean rerun. The first full run had 2 lock-contention failures while the live SealedFreshness task (14:56:15) held the operation lock; kept as evidence.
  - Observation only: `InvestorIntelligenceFreshnessWatchdog` returned 1 at 14:56:15 (not STALE code 3) without a watch line; the 15:26:15 run returned 0. No task changed.

## Latest gate run

- Worker: `npm run typecheck` PASS; `npm test` 900 passed / 1 named manual skip.
- `security_check`, documentation boundary/structure, workflow supply chain, owner config: PASS.
- Full Python 17:42:35–17:50:26: 2502 tests OK, 470.9 s.

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

Operator: review the UI preview before any Worker deployment (deployment needs explicit authorization). C2b needs an operator choice between build-time digest, an archived-receipt contract or a separate local artifact (recommended), because SEC receipts are in-process only. Serenity originals need a permitted retrieval channel (oEmbed now HTTP 402); paid access requires explicit operator authorization.
