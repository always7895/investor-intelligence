# Current state / 目前狀態

Updated 2026-09-25 by an operator-directed Claude Code session (master and writer for this change). Previous registers: V12 `git show 0f5358b:state/STATUS.md`; older history `git show 38860e7:state/STATUS.md`. Release identity stays in `README.md` (historical 2026-09-06 baseline).

## Identity

- Branch `fix/options-provenance-audit`, draft PR #37 to `main`. Base for this change: `6d21066` (pushed).
- PR #37 CI has only reported COMPLETED_SKIPPED (latest run 36092036399). Skipped is not PASS and not release qualification.
- DEVELOPMENT_COMPLETE=false; FINAL_RELEASE_COMPLETE=false; PRODUCTION_CUTOVER_PENDING=false.

## This change — adaptive THINK and TabbyAPI router default (operator request 2026-09-25)

Operator: the EXE must switch local models and thinking, pick thinking strength from an appropriate response time, and use the System One model for fast screening.

- `scripts/v213_adaptive_reasoning.py` + gateway: the profile effort is the ceiling; each compact answer gets the highest effort whose thinking fits the time budget at the measured decode rate (about 90 tokens/s measured on the RTX 5090 lane); a 0.8 s System One screen sends SIMPLE questions to no-thinking with content-free features only; a thinking overrun gets one answer-only retry inside the timeout; responses carry `ii_reasoning`. Profile, hash and certified deadline unchanged. Details: [MODEL_RUNTIME_MIGRATION](../docs/MODEL_RUNTIME_MIGRATION.md).
- EXE and bridge default router moved from the retired llama.cpp `:8080` to TabbyAPI `:5000` (saved selections still win); the EXE THINK label now reads as the ceiling.
- Tests: `tests/test_v213_adaptive_reasoning.py` (11, including the authenticated gateway handler), model profile 11 (compiled EXE and THINK UI self-test), bridge identity 2; the module is added to the explicit gateway payload lists (R75 verifier, isolated-process test). Full Python 2537: the one failure was that missing payload entry, fixed and rerun (15 OK).

## Previous changes

- `0b3946d` ink monochrome LINE cards: three-stop black-to-graphite header gradient, section levels by lightness, grey secondary buttons on white footers, accounting-convention value colours, no green; every text/ground pair ≥4.5:1; Worker 900 passed. Preview: https://claude.ai/artifact/CqRyqkqvhwDUqCZDLb6rcU
- `47a3f19` Top20 industry detail from SEC annual reports ([TOP20_UPSIDE_BRIDGE_V1](../docs/TOP20_UPSIDE_BRIDGE_V1.md) Phase 0): latest 10-K/20-F business excerpt → validated loopback-Qwen phrase → 「細分產業：主要業務」; per-accession cache, index re-read each run, 403/429 fence; scheduled runners pass `--business-profile`; live canary 22/22 Top20 plus TSM/ASML; 20 tests; full Python 2525 (one CI-env-only error, passes with `PYTHONUTF8=1`).
- `3e80273` Wave 1 official public feeds: eight reviewed T1 entries (Fed, ECB, SEC press, TWSE/TPEx EOD and issuer directories, TAIFEX options) registered at `ADAPTER_CONTRACT_VALIDATED`; the claim-evidence acquisition factory rejects bulk datasets and news leads, so none is runtime-enabled yet (receipts `_workspace/audit-runtime/source-activation-wave1-20260925/`).
- `7c01ef1`, `6d21066` layered LINE card design with black gradient band; source activation plan (full Python 2502 OK).
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

- `security_check`, documentation boundary/structure, workflow supply chain, owner config: PASS.
- Focused: business profile 20, v212 report, source acquisition, public JSON refresh, progress runner, entrypoints, installer boundaries, sealed refresh — 118 OK.
- Full Python 18:38:42–18:45:45: 2525 tests, 2524 OK; the one error (`test_v213_market_products` CLI pipe) came from running without CI's `PYTHONUTF8=1` and passes with it (12 OK). Worker typecheck PASS, 900 passed / 1 skipped.

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

Git commits on this branch and a normal push to `origin` (updates PR #37). Read-only SEC EDGAR and loopback Tabby calls for the business-profile canary and a decode-rate measurement. Worker deployment: pre-gate PASS at 2026-09-25T10:57:56Z (pointer `20260925T105615Z-db4377bdbedc`, 103 s), then `wrangler deploy` was refused by this session's permission classifier; Production still serves version `70dd7e15-0a98-4513-b156-5ebb2e807761` (2026-09-17). No Production, KV, LINE, schedule, credential, billing, broker, model or service mutation.

## Next action

Operator: deploy the Worker from `cloud/` when ready (`npx wrangler deploy -c wrangler.v213.production.local.toml`, then `scripts/deploy_production_gate.ps1 -Phase post -WorkerVersion <new id>`; rollback target `70dd7e15-0a98-4513-b156-5ebb2e807761`), and reinstall the runtime so the scheduled runners pick up `--business-profile`. Engineering next: Top20 upside phases 2–5 (order ledger, valuation bridge, 6M/1Y/2Y sort key) and acquisition kinds for Wave 1 bulk/news feeds. Serenity originals still need a permitted retrieval channel (oEmbed HTTP 402); paid access requires explicit operator authorization.
