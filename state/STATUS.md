# Current state / 目前狀態

Updated 2026-09-26 by an operator-directed Claude Code session (master and writer; the operator granted full authority to finish the Top20 publication work overnight, 2026-09-25). Previous registers: V12 `git show 0f5358b:state/STATUS.md`; older history `git show 38860e7:state/STATUS.md`. Release identity stays in `README.md` (historical 2026-09-06 baseline).

## Identity

- Branch `fix/options-provenance-audit`, draft PR #37 to `main`, HEAD `8cdf6b8` (pushed). PR CI only reports COMPLETED_SKIPPED; skipped is not PASS or release qualification.
- DEVELOPMENT_COMPLETE=false; FINAL_RELEASE_COMPLETE=false.

## Production (2026-09-26 16:09Z)

- Worker `a815e7f9-6b87-4e95-b422-2607c0253965` (report age split, admission disclosure, activation kill-switch `V213_ACTIVATION_COMMIT_ENABLED="false"`); post gate PASS against Production KV (pointer `20260925T160733Z-21edec0dba10`, live replay fresh, macro sealed, 20 potential-ranking records). Rollback order: `13d665be…`, `2cfb7d0b…`, `70dd7e15…`.
- Hourly `InvestorIntelligenceSealedFreshness` publishes to Production (`--remote`, pointer last). The 15:56Z run exited 1 after publishing with no log line (PS 5.1 Stop + native stderr); `8cdf6b8` logs every failure and syncs the run id the publisher printed; re-synced by hand, then verified live.
- Top20 in Production is still the GEV/6501 test-only corpus (now labelled TEST-ONLY on every card); v21/v212 Top20 are empty/INSUFFICIENT until the cutover below.

## Top20 single-writer programme (design workflow `wf_0fceff70-f50`: investigate → design → 2 adversarial reviews)

Root causes found: Morning/Evening publication failed at COMMIT_REQUEST since 2026-09-17 because the Worker requires the two-anchor fields (e22cd9f) that no producer emitted (HTTP 400 before any KV write); the source-tree refresh failed at the live federation because `fetch_nasdaq` counted the `(listings, conflicts)` tuple (fc145e1); business-profile phrases picked accounting/legal/TOC text; profit metrics came from filings up to 15 years old or implausible denominators (HIG 979% margin).

| Task | State |
| --- | --- |
| T1 Nasdaq unpack, extractor v6, served-model check | DONE `90563ee` `e55f4a0` |
| T2 current, same-period, plausible profit metrics (latest-quarter YoY, withheld reasons in `*.profit-display-candidate.json`) | DONE `84089e6` |
| T3 producer two-anchor contract (claim rows at oldest filing date, market rows at latest bar, 14 h margin, stale order claims withheld; `scripts/v213_evidence_policy.py` mirrors the Worker) | DONE `de595a9` `84089e6` |
| T4 Worker: seal liveness vs report age (`config/v213-top20-report-freshness-v1.json`, 14 h), carried-row age gates, disclosure on every surface, re-sealed cards need a sealed run with the same SHA, commit kill-switch | DONE `472a309`, deployed |
| T5 hourly publisher carries the validated Top20 bundle (off by default), seal first, bounded refresh, replay fallback | NEXT |
| T6 gate asserts Top20 records/age · T7 LOCAL_SOURCE_CHECKOUT installer · T8 retire second writers (launcher -NoSync, stage-8 switch, Morning/Evening data-only) · T9 reinstall · T10 cutover (resumes owner pushes) · T11 docs | PENDING |

Live data-only refresh from the source tree (16:00Z): all 8 stages PASS, 20 sourced business-profile phrases, profit text from 2026-07/08 filings, report valid under the Worker-contract mirror now and at +14 h; NUE's 212-day order claim withheld.

## Earlier today (details in Git history and docs)

- Order-realization scenario (「訂單實現情境」, 「訂單實現榜」, 6M/1Y/2Y coverage) and card body visuals; data-driven industry rotation, potential ranking and company deep reports ([INDUSTRY_ROTATION_V1](../docs/INDUSTRY_ROTATION_V1.md)); Production KV `--remote` fix and truthful deploy gate (`be4e2f0`, `dc47bd3`); EXE/bridge model auto-detection; TWSE/TPEx monthly revenue.
- `e97fd00` thesis phase engine and Serenity/Aschenbrenner refresh; `41058f2` adaptive THINK; `0b3946d` ink monochrome cards (preview https://claude.ai/artifact/CqRyqkqvhwDUqCZDLb6rcU); `47a3f19` SEC industry detail; `3e80273` Wave 1 feeds (none runtime-enabled).

## Latest gate run

- `security_check`, documentation boundary/structure, workflow supply chain, owner config: PASS (2026-09-26 00:00 local).
- Worker typecheck PASS; 923 passed / 2 skipped. Full Python 2616 OK (T2/T3 tree); focused suites after T4 and the hourly hardening OK.

## Closed components — no reopening without regression evidence

- T1 finite fractional ordering (`5208d64`), T2 nonauthorizing period declarations (`26842de`), T3 forward comparison declaration diagnostic (`689a682` → `a944410`); O1 options venue coverage shadow (`11436e6`), Case9 (`c178127`), R3A (`e45c1d6`), research method quarantine (`c6ce527`); I1/I2/I3 identity shadows, E2A synthetic capacity, hermetic fixtures. Preserved failures and receipts remain immutable (V12 register).

## Open lanes

1. Top20 programme T5–T11 (above). Carrying reports:*, source-independence and federation needs a sealed data-as-of object or report-age gates in their readers (certified `cloud/src/qa.ts` needs recertification): deferred.
2. Runtime reinstall: the V213Runtime (2b9e143) identity cites run 34440909069, a skipped non-R75 pull_request run; the CI R75 route needs a Sol review of 375 paths and a Tabby port of the live QA gate. T7 adds an honest LOCAL_SOURCE_CHECKOUT mode (release_qualified=false).
3. Forward comparison premises C2b (trust-model decision); deferred O1/identity/R3A/U1/U2/E2A-B/Gate B lanes; BLS v1 quota; IFRS metrics for 20-F filers (PBR shows 「SEC 可用獲利指標不足」).

## Boundary flags

NATIVE_ATTEMPT_COUNT=0; NATIVE_EXECUTION_AUTHORIZED=false; CAPACITY_EVIDENCE=UNQUALIFIED; publication_eligible=false for candidates; global P0 NOT_REAUDITED. Serenity primary; Leopold Aschenbrenner CONTEXT_ONLY.

## Control plane

Astra master; exact local Qwen sole tracked writer on the Pi lane; Sol independent read-only reviewer. The operator assigned Claude Code as master and writer for this work (2026-09-25) without waiving boundaries.

## External mutations (this change)

Commits and normal pushes to `origin` (PR #37). Worker deployments under the operator's authorization: `2cfb7d0b…`, `13d665be…`, `a815e7f9…`. Production public KV: hourly sealed syncs (`--remote`) plus manual syncs of runs `20260925T155616Z` and `20260925T160733Z`. Read-only SEC/Nasdaq/Tabby calls; local data-only refreshes (no Production mutation). No LINE delivery, schedule, credential, billing or broker change.

## Next action

T5 (carry-forward publisher behind `-CarryForwardTop20`, off by default), then T6–T11 in order; T8 must precede T9, and T10 resumes owner pushes (00:00Z/13:00Z) under the operator's authorization, recorded as a dated exception to source AGENTS.md shipping rules.
