# Current state / 目前狀態

Updated 2026-09-25 by an operator-directed Claude Code session (master and writer for this change). Previous registers: V12 `git show 0f5358b:state/STATUS.md`; older history `git show 38860e7:state/STATUS.md`. Release identity stays in `README.md` (historical 2026-09-06 baseline).

## Identity

- Branch `fix/options-provenance-audit`, draft PR #37 to `main`. Base for this change: `6d21066` (pushed).
- PR #37 CI has only reported COMPLETED_SKIPPED (latest run 36092036399). Skipped is not PASS and not release qualification.
- DEVELOPMENT_COMPLETE=false; FINAL_RELEASE_COMPLETE=false; PRODUCTION_CUTOVER_PENDING=false.

## This change — data-driven industry rotation (operator rules 2026-09-25)

Operator: all data must move with the latest market data, nothing hand-written; macro industry analysis rotates to the industries with potential at the time; deep analyses are detailed; sources are diverse and keep updating after the project is done.

- `scripts/industry_rotation.py` + `config/industry-rotation-v1.json` (22 industries defined by SIC codes and BLS PPI series only): BLS PPI YoY (public API v1), SEC XBRL frames RPO / inventory / revenue summed over EDGAR SIC members (≥3 matched issuers) → `thesis_phase` (industry scope) → data strength. Cards and 10-part deep analyses are generated from the numbers with period, source and URL. Live run 2026-09-25 (2026 Q2 filings, PPI to 2026-08): TOP5 computers and storage (EARLY_VALIDATION, PPI +45.0%, RPO +86.3%), semiconductors, oil and gas extraction, construction machinery, steel (DISCOVERY).
- `build_v213_macro_industry_research.py` and `publish_sealed_snapshot.py` now read the rotation (max age 45 days) and embed deep analyses in the sealed overview; the old hand-written rows are a test-only synthetic fixture. Stale or missing data publish an honest shortfall.
- Worker `rich-menu.ts`: industry card and deep analysis come from the sealed overview (they were unreachable before because the seal admits one macro object); 3 new tests.
- Refresh: `scripts/run_daily_data_refresh.ps1` (DPAPI contact in-process only, ≤ one refresh per 20 h), called non-fatally from the hourly sealed refresh, so the rotation keeps updating on its own. Details: [INDUSTRY_ROTATION_V1](../docs/INDUSTRY_ROTATION_V1.md).
- EXE and bridge auto-detect the local model server (operator request): saved/default address first, then loopback ports 5000, 8080, 11434, 1234, 5001, 8081 (never 8000); move only to a server holding the configured model; explicit addresses never move. The bridge now also reads `/v1/models` at the same base, which TabbyAPI needs. Tests: bridge discovery (PS 5.1 and 7), EXE self-test candidate order.
- TWSE and TPEx monthly revenue (OpenAPI, open-data licence) added as a third independent family (`SUPPLIER_REVENUE`); live TOP5 with it: computers and storage (PPI, SEC RPO and TW revenue +90.6% all confirm), semiconductors (TW +61.3%), software, electronic components, oil and gas extraction.
- Data-driven potential ranking (「潛力榜」, 「潛力報告 代號」): members of admitted industries, phase gate, confirmed tier first, published strength, ≤5 per industry, sealed with compact reports in the TOP5 overview. Live: NVDA, DELL, APH, CRWV, FROG, HUBS, KVYO, BRZE, LOGI, BELFA, DGII, FTNT, OMCL, POWL, then MU, AMD, MCHP, ADI, BDCO, CHRD. BLS refusal falls back to a ≤35-day cache. Worker 909 passed.
- Company deep reports (`scripts/company_deep_report.py`, daily with the rotation): SEC XBRL same-quarter revenue/margins, RPO, capex, cash, debt, dilution, industry signals and company-scope phase with sources, embedded as `deep_reports` in the sealed report; the Worker renders them instead of the audit template when valid and from the same snapshot. Live: GEV revenue +21.9%, operating margin +1.7 pp, RPO US$176.28B (+37.0%). 6 Python + 2 Worker tests.
- Tests: `test_industry_rotation` (11); Worker 903 passed / 1 skipped. Full Python 2561: 10 failures came from mid-edit bridge states and the explicit `--model-catalog-check` probing other ports; both fixed (explicit addresses never move) and rerun green (29 OK).

## Previous changes

- `e97fd00` time-aware thesis phase engine and Serenity/Aschenbrenner refresh (EDGAR timeline, verified secondary quotes); `18b5927` option cycle chip back to yellow.
- `41058f2` adaptive THINK under the profile ceiling (time budget, measured decode rate, System One screen, one answer-only retry) and TabbyAPI `:5000` as the EXE/bridge default router; 11 + 11 + 2 tests; full Python 2537 after a payload-list fix.
- `0b3946d` ink monochrome LINE cards: three-stop black-to-graphite header gradient, section levels by lightness, grey secondary buttons on white footers, accounting-convention value colours, no green; every text/ground pair ≥4.5:1; Worker 900 passed. Preview: https://claude.ai/artifact/CqRyqkqvhwDUqCZDLb6rcU
- `47a3f19` Top20 industry detail from SEC annual reports ([TOP20_UPSIDE_BRIDGE_V1](../docs/TOP20_UPSIDE_BRIDGE_V1.md) Phase 0): latest 10-K/20-F business excerpt → validated loopback-Qwen phrase → 「細分產業：主要業務」; per-accession cache, index re-read each run, 403/429 fence; scheduled runners pass `--business-profile`; live canary 22/22 Top20 plus TSM/ASML; 20 tests; full Python 2525 (one CI-env-only error, passes with `PYTHONUTF8=1`).
- `3e80273` Wave 1 official public feeds: eight reviewed T1 entries (Fed, ECB, SEC press, TWSE/TPEx EOD and issuer directories, TAIFEX options) registered at `ADAPTER_CONTRACT_VALIDATED`; the claim-evidence acquisition factory rejects bulk datasets and news leads, so none is runtime-enabled yet (receipts `_workspace/audit-runtime/source-activation-wave1-20260925/`).
- Earlier today (`b88dd9f` … `7c01ef1`): instructions/skill/MCP restructure, C1/C2a forward comparisons, research refresh, LINE redesign, weekly/monthly options, sourced-wording guard, 74-file cleanup, installer retention; each with full Python OK at the time (details in Git history of this file).

## Latest gate run

- `security_check`, documentation boundary/structure, workflow supply chain, owner config: PASS (20:22).
- Worker typecheck PASS; 905 passed / 1 skipped. Focused Python: rotation, deep reports, market products, thesis phase, model profile (compiled EXE), bridge identity — OK.
- Full Python 20:24 (after `a90bdfe`): 2568 tests OK in 423.0 s. Earlier 20:06 run: 10 mid-edit failures, fixed.

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
