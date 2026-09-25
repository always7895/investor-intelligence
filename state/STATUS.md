# Current state / 目前狀態

Updated 2026-09-25 by an operator-directed Claude Code session (master and writer for this change). Previous registers: V12 `git show 0f5358b:state/STATUS.md`; older history `git show 38860e7:state/STATUS.md`. Release identity stays in `README.md` (historical 2026-09-06 baseline).

## Identity

- Branch `fix/options-provenance-audit`, draft PR #37 to `main`. Base for this change: `6d21066` (pushed).
- PR #37 CI has only reported COMPLETED_SKIPPED (latest run 36092036399). Skipped is not PASS and not release qualification.
- DEVELOPMENT_COMPLETE=false; FINAL_RELEASE_COMPLETE=false; PRODUCTION_CUTOVER_PENDING=false.

## Production state (2026-09-25 13:58Z) — stale-KV P0 closed

- Worker `13d665be-2ac5-4704-9ab3-38a64ec518b2` (order coverage, 14:11Z; post gate PASS against Production) after `2cfb7d0b-e931-42d2-b574-5a23e4bbee4b` (card visuals, 13:30Z); rollback targets in that order, then `70dd7e15-0a98-4513-b156-5ebb2e807761`.
- Root cause of 8.6 days of stale Production data: Wrangler 4 KV commands default to the local Miniflare store; sync, rollback, gate and watchdog passed no `--remote`, so hourly syncs since 2026-09-16 wrote locally and the gate read the same copy (plus a PowerShell 7 +8 h anchor shift and a reader replay of a leftover 2026-09-24 file). Fixed in `be4e2f0` (gate: `--remote`, UTC parse, exact-byte copy `scripts/fetch_live_public_snapshot.py`, `cloud/test/live-kv-replay.test.ts`) and `dc47bd3` (sync/rollback/watchdog `--remote`, operator-authorized); 8 tests.
- The 13:56Z scheduled run published to Production: post gate PASS against remote KV, pointer `20260925T135616Z-3ef7a902d969` (105 s), live replay fresh Top20, TOP5 overview sealed, 20 potential-ranking records.

## Order-realization scenario (operator rule: 6M/1Y/2Y if orders are realised)

- Company reports gain 「訂單實現情境」 and a 1Y coverage tile: RPO × disclosed cumulative share versus latest quarter revenue × quarters; a revenue/price growth floor only above 100% (constant margin, shares and P/E; no new orders); period agreement ≤45 days; 10-Q text cached per accession. Potential-ranking cards show 6M/1Y/2Y coverage; 「訂單實現榜」 lists only companies with all three horizons, ordered by 2Y. Live: CRWV 206%, GEV 103/103/90% (+3.0% floor 6M/1Y), DELL 54/54/32%, HUBS 21%; 12 of 21 disclose no timing. Tests: 5 Python + 1 Worker (actual LINE path).

## Card body visuals (operator 2026-09-25: card bodies read as flat text)

- `line-theme.ts` body visuals: figures in running text bolded via spans (negatives red, dates untouched), meters, rank badges, rail titles, timelines, stat tiles, phase ladder, stacked score bar; `packCarousels` splits by bytes (≤5 bubbles, ≤46 KB); oversized macro bubbles fall back to spans-free text.
- TOP5 overview/industry cards/10-step deep analysis redrawn; 潛力報告 and the Top20 data-report detail are now a swipeable Flex report (`… 文字` keeps text); company reports carry optional validated `kpis` tiles from `company_deep_report.load_reports`. Top20 seven-field cards unchanged. Worker 916 passed (5 new visual tests); preview republished at the artifact below.
- `05d86a5` RPO recognition timing from the latest 10-Q/10-K (`scripts/order_timing.py`, 5 tests).

## Earlier today — data-driven industry rotation (operator rules 2026-09-25)

Operator: all data must move with the latest market data, nothing hand-written; macro industry analysis rotates to the industries with potential at the time; deep analyses are detailed; sources are diverse and keep updating after the project is done.

- `scripts/industry_rotation.py` + `config/industry-rotation-v1.json` (22 industries defined by SIC codes and BLS PPI series only): BLS PPI YoY (public API v1), SEC XBRL frames RPO / inventory / revenue summed over EDGAR SIC members (≥3 matched issuers) → `thesis_phase` (industry scope) → data strength. Cards and 10-part deep analyses are generated from the numbers with period, source and URL. Live run 2026-09-25 (2026 Q2 filings, PPI to 2026-08): TOP5 computers and storage (EARLY_VALIDATION, PPI +45.0%, RPO +86.3%), semiconductors, oil and gas extraction, construction machinery, steel (DISCOVERY).
- `build_v213_macro_industry_research.py` and `publish_sealed_snapshot.py` now read the rotation (max age 45 days) and embed deep analyses in the sealed overview; the old hand-written rows are a test-only synthetic fixture. Stale or missing data publish an honest shortfall.
- Worker `rich-menu.ts`: industry card and deep analysis come from the sealed overview (they were unreachable before because the seal admits one macro object); 3 new tests.
- Refresh: `scripts/run_daily_data_refresh.ps1` (DPAPI contact in-process only, ≤ one refresh per 20 h), called non-fatally from the hourly sealed refresh, so the rotation keeps updating on its own. Details: [INDUSTRY_ROTATION_V1](../docs/INDUSTRY_ROTATION_V1.md).
- EXE and bridge auto-detect the local model server (operator request): saved/default address first, then loopback ports 5000, 8080, 11434, 1234, 5001, 8081 (never 8000); move only to a server holding the configured model; explicit addresses never move. The bridge now also reads `/v1/models` at the same base, which TabbyAPI needs. Tests: bridge discovery (PS 5.1 and 7), EXE self-test candidate order.
- TWSE and TPEx monthly revenue (OpenAPI, open-data licence) added as a third independent family (`SUPPLIER_REVENUE`); live TOP5 with it: computers and storage (PPI, SEC RPO and TW revenue +90.6% all confirm), semiconductors (TW +61.3%), software, electronic components, oil and gas extraction.
- Data-driven potential ranking (「潛力榜」, 「潛力報告 代號」): members of admitted industries, phase gate, confirmed tier first, published strength, ≤5 per industry, sealed with compact reports in the TOP5 overview. Live: NVDA, DELL, APH, CRWV, FROG, HUBS, KVYO, BRZE, LOGI, BELFA, DGII, FTNT, OMCL, POWL, then MU, AMD, MCHP, ADI, BDCO, CHRD. BLS refusal falls back to a ≤35-day cache. Worker 909 passed.
- Company deep reports (`scripts/company_deep_report.py`, daily with the rotation): SEC XBRL same-quarter revenue/margins, RPO, capex, cash, debt, dilution, industry signals and company-scope phase with sources, embedded as `deep_reports` in the sealed report; the Worker renders them instead of the audit template when valid and from the same snapshot. Live: GEV revenue +21.9%, operating margin +1.7 pp, RPO US$176.28B (+37.0%). 6 Python + 2 Worker tests.

## Previous changes

- `e97fd00` time-aware thesis phase engine and Serenity/Aschenbrenner refresh (EDGAR timeline, verified secondary quotes); `18b5927` option cycle chip back to yellow.
- `41058f2` adaptive THINK under the profile ceiling (time budget, measured decode rate, System One screen, one answer-only retry) and TabbyAPI `:5000` as the EXE/bridge default router; 11 + 11 + 2 tests; full Python 2537 after a payload-list fix.
- `0b3946d` ink monochrome LINE cards: three-stop black-to-graphite header gradient, section levels by lightness, grey secondary buttons on white footers, accounting-convention value colours, no green; every text/ground pair ≥4.5:1; Worker 900 passed. Preview: https://claude.ai/artifact/CqRyqkqvhwDUqCZDLb6rcU
- `47a3f19` Top20 industry detail from SEC annual reports ([TOP20_UPSIDE_BRIDGE_V1](../docs/TOP20_UPSIDE_BRIDGE_V1.md) Phase 0): validated loopback-Qwen phrase, per-accession cache, 403/429 fence; 20 tests.
- `3e80273` Wave 1 official public feeds: eight reviewed T1 entries at `ADAPTER_CONTRACT_VALIDATED`, none runtime-enabled yet.

## Latest gate run

- `security_check`, documentation boundary/structure, workflow supply chain, owner config: PASS (22:10).
- Worker typecheck PASS; 917 passed / 2 skipped. Focused Python: company deep reports, order timing, deploy gate — OK.
- Full Python (order scenario working tree): 2588 tests OK in 432.1 s.

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

Git commits on this branch and a normal push to `origin` (updates PR #37). Read-only SEC EDGAR and loopback Tabby calls. Worker deployments at the operator's request / standing authorization: `2cfb7d0b…` (13:30Z), `13d665be…` (14:11Z). Production public KV now receives the hourly sealed sync again (operator-authorized `--remote`, first run 13:56Z). No LINE delivery, schedule definition, credential, billing, broker, model or service mutation.

## Next action

Confirm the 14:56Z publish seals order coverage (reports refreshed ~14:00Z), then next engineering lane. DEFERRED_WITH_REASON: the V213 runtime reinstall (morning/evening Top20 runner still lacks `--business-profile`) needs a CI-built R75 package (`HOTFIX-REFS.json` with a workflow run id); PR #37 CI only reports SKIPPED, and the identity is not fabricated. Engineering next: Top20 upside phases 2–5 (order ledger, valuation bridge, 6M/1Y/2Y sort key) and acquisition kinds for Wave 1 bulk/news feeds. Serenity originals still need a permitted retrieval channel (oEmbed HTTP 402); paid access requires explicit operator authorization.
