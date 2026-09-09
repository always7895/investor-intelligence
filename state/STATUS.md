# Current engineering status

Updated2026-09-09. Current acceptance, NOT a release certificate. Detailed history remains in Git: `git show e79554e:state/STATUS.md`, and the older full record via `git show 38860e7:state/STATUS.md`. Historical receipts, failures and journals are not removed or restamped. Release identity remains in README.

## Authority and workspaces

- Fetched clean starting HEAD e79554e99d5f0eadd0b99b7f907abbb1ca9d5692 on `fix/options-provenance-audit` (PR37). Source: `D:\Investor-Intelligence-LINE-Pi\_workspace\source`. PR39 stays isolated at d58fdaf in `_workspace/review-source-views`; baseline52e285f in `_workspace/review-baseline`. One writer; no implicit review-branch integration.
- User currently authorizes completing verified data and subsequent LINE integration, alongside earlier reviewed Production/schedule repair. No real LINE sends, broker operations, new paid services, arbitrary credentials or stale activation replay. This step changes source/tests/docs only; network research is public/read-only.
- Outer `D:\Investor-Intelligence-LINE-Pi` is installed runtime, NOT this Git worktree. Audit tools/evidence are `_workspace/audit-runtime`; backups `_archive/history-backups`. Never package/scan those two trees as runtime market data.

## Current implementation: honest historical-return inputs

- Actual pre-fix builder admitted600 days as two-year annualized return and120 days as six-month return. Executed old e79554e caller on synthetic100→120 inputs:600d yielded0.11738177496958224 annualized;120d yielded0.19999999999999996 short return. New caller returns unavailable for those incomplete windows. This is a synthetic regression, not market performance.
- Existing `build_v212_top20_report.py` now uses shared `historical_return_evidence.py`: complete24/6 calendar-month targets, leap/month-end handling, last available observation on/before target within7 days, actual elapsed days/365.25. Reject invalid prices, duplicate/reversed dates and non-finite results; do not drop an invalid final observation and advance retrieval time over an older price.
- Existing CLI also writes an explicitly unqualified return-evidence sidecar containing actual start/end dates/prices, cumulative/annualized calculations and matching report-file SHA. It is NOT in the public seven-field schema or sealed payload. Currency/adjustment/dividend/calendar verification remains unknown; public eligibility false. No live Yahoo collection or new20-stock data qualification claimed.
- Required-module check added to source `run-v212-local.ps1`; compatibility function and normal CLI remain. Current package stages `git archive`, so tracked helper is included; actual extracted installation still needs qualification. Reviewed CI inventory updated with exact paths, no wildcard exemption.
- New tests10 PASS plus existing report tests4 PASS, including real CLI→build→market caller→calculation→atomic report/sidecar with20 synthetic tickers; only external inputs mocked. Includes insufficient history, leap/month ends, bounded alignment, NaN/duplicate/reversal/overflow, output collision and file-SHA checks. First full regression failed only the required historical-status command pointer; restored it without changing the test. Initial log `return-evidence-python.log` preserved. Final Python674/2 skipped PASS (`return-evidence-python-final2.log`); Worker163/typecheck, security/docs/workflow/storage and PS5.1/7 parse PASS.
- Validation commands: pinned Python `-B -m unittest discover -s tests -p 'test_*.py'`; `npm run typecheck`; `npm test -- --run`; four repository gates above and PS5.1/7 AST parsing of both changed PowerShell files.
- Public research refresh: AMD original Q2 release retrieved at `https://ir.amd.com/news-events/press-releases/detail/1295/amd-reports-second-quarter-2026-financial-results` (fetch response mtttvgu2ollk18). Broadcom original Q3 release fetch aborted; search numbers not admitted. AMD remains an issuer-only source, not an independently qualified detailed report.

## Production remains in maintenance

- Rechecked `InvestorIntelligence-v21-MorningRefresh` and `InvestorIntelligence-v21-EveningRefresh`: both Disabled. Not restored; no Worker/model/EXE replacement or new sealed publication in this step. Last confirmed remote data2026-09-08T12:20:02Z, promoted12:22:09.595Z; not freshly reverified here.
- Prior signed recovery returned NOT_COMMITTED; original FAIL and byte-identical journal archive preserved. Previous journal scan unresolved0. Never replay the stale bundle or bypass pointer-last activation.
- Sealed schema4 still has seven payloads, excluding fresh options/universe and detailed-report datasets. Stale carry-forward was removed; replacement schemas/builders/preflight, exact-key readback, replay/rollback/finalize acceptance remain incomplete.
- Known whole-product P0 inventory is NOT closed. PR39 historically retains3 Python evidence errors; not rerun or fixed here. No new scoped defects found after final regressions; whole-product release acceptance pending.

## Report depth and actual delivery boundary

- Candidate company button now selects ticker and generation, checks membership/row freshness and returns evidence/definitions/gaps rather than identical Top20 text. Actual authorized LINE event→card action→response and stale/unknown/unsafe-URL/maximum-citation cases passed. It explicitly is NOT full valuation. Generation equality is NOT immutable run/report-SHA binding. Candidate not installed.
- [Detailed report contract](../docs/DETAILED_REPORT_CONTRACT.md) covers legal/Chinese identity, exact return inputs, capacity/qualification, contracts/prepayments, customers, management revisions, income/cash/dilution, valuation scenarios, options and macro. Existing seven-field schema still lacks these structured report inputs. `numeric_total_order_estimate_prohibited=true` remains.
- [TSEM operating draft](../docs/research/TSEM-20260909.md) has actual contract/prepayment, customer/capacity, financial/cash-flow, management-model and competitor analysis. Receipt `research-dossiers/TSEM-20260909.json` retains passages, inputs, report-byte SHA, actual Pi identity/reference hashes and failed retrieval checks. Four pages/three publisher families do NOT independently corroborate Tower contracts. Report SHA is not sealed binding.
- Scope remains1 dated stock draft and0 newly delivered deep-report routes. Other stock dossiers, verified historical inputs,6m/1y/2y valuation, options and macro detailed reports remain incomplete. No guessed names/orders/EPS/price targets, no card-summary clone relabelled complete.
- Historical draft validation: Python664/2 skipped, Worker163/typecheck, security/docs/workflow/storage and PS5.1/7 parse passed (`tsem-depth-python.log`). Those results are not current-source release qualification.

## Data and methodology blockers

- Installed raw options:24 records with September9 retrievals, no complete public eligibility/privacy attestation. Retrieval is not BBO time. Development Yahoo DTO stays `line_public_eligible=false` on success/no-underlying paths; no private/broker fallback.
- [Rights review](../docs/PUBLIC_SOURCE_RIGHTS_REVIEW_20260909.md): TAIFEX11320 open license is dataset-specific Taiwan daily/EOD with attribution, not realtime/US options. Provider gate last checked: reviewed public access1, pending7, prohibited4; fully eligible runtime0, production selected false. Nasdaq terms fetch failed; indicative documentation is not redistribution permission. No provider activated.
- Installed universe:30 rows, September7 generation, legacy serenity-first policy. June30 as_of may be financial period, not proof of stale filing. Scoring/dates not relabelled.
- Broad Taiwan directory collection:1094 TWSE +890 TPEx issuers, September8 source dates, zero warnings; all PRIMARY_ONLY / DISCOVERED_EVIDENCE_AND_SCORING_PENDING / publication_eligible=false. Discovery is not ranked global research.
- Research collector7 endpoints/14,417 observations, news5 recent/55 stale. Neither endpoint nor observation counts corroborate company claims. Legacy fixed themes still reserve120/240 discovery seeds and40/80 SEC slots; actual selector repair remains open.
- Serenity is primary public-method lens; Leopold Aschenbrenner CONTEXT_ONLY, never company proof/score bonus. `research-method-refresh-20260909.json` records actual reference/tool evidence. X direct403 followed by author-matched truncated July31 oEmbed is not full/latest stance; other lead404 remains unverified. Leopold original is historical2024, not today's facts.
- Three canonical research skill files source/installed hash-matched at synchronization; originals archived `_archive/instruction-sync-20260909T070339Z`. Unsupported installed case sheet replaced by pointer. Root/source AGENTS intentionally have distinct runtime/development roles. Rules are not proof of an executed unbiased screen.

## Model and release blockers

- Historical Q5 thinking=false/effort=none live matrix passed10 cases844–1890ms with negatives/reference completion/mock LINE/isolated cleanup. `r75-qa-live-model-profile-qualification.json` starts2026-09-09T05:26:24.943379Z;24h/source/profile binding applies. Old xhigh failure preserved.
- Actual old receipt verifier rejects changed runtime source with LIVE_SOURCE_MANIFEST_MISMATCH. Do not restamp, bypass source manifests, start another Router/model, change presets or use paid fallback. Model smoke PASS is not data/delivery/release PASS.
- Fresh source-bound model proof, protected-source recertification, Windows self-hosted acceptance, immutable SHA/run-ID ZIP and independent archive/receipt/extracted-install/download verification remain incomplete. Certified `cloud/src/qa.ts`, scoring and installed actions unchanged.
- Earlier malformed-date-prefix rescue was removed at snapshot/bundle admission in2a88e8e; legitimate date-only and actual-caller negatives preserved. Other date-prefix consumers need role-specific review.

## Consolidation and cleanup retained

- Physical move in1113a1c used worktree move/repair; source/reviews/tools under `_workspace`, history under `_archive`. Five old roots absent, no junction substitutes, HEADs/branches/signed evidence preserved. Relocated full regressions passed (`consolidation-*.log`); runtime actions unchanged.
- Prior bounded cleanup:654 untracked pyc/10 directories/7,837,559 bytes across three worktrees; earlier source467/4/5,755,638. Ownership/containment/type/identity checked. No source, locks, unique evidence, rollback or active runtime deleted.
- Old-named registered runner is Running/Auto with2.337.0 junction targets, not disposable. Installed inventory had57 file-stat errors; no complete dependency/deletion-safety claim. Models/Router/unrelated projects retained. [Workspace maintenance](../docs/WORKSPACE_MAINTENANCE.md) governs further cleanup.
- Instruction budgets enforced by tests; history kept in Git rather than growing STATUS. Fewer bytes do not prove latency/accuracy. No broad git clean, junction traversal or drive-wide deletion.

## Next actions

1. Complete genuine company-specific evidence/financial/order inputs and stock/options/macro report producers; preserve absent/failed evidence and independent lineage. Repair actual fixed-theme selection without changing scoring.
2. Finish rights, currency/session/freshness and financial/identity admission; connect calculation evidence and separate reports through one versioned sealed contract, both builders and actual Worker callers. No unsealed-key fallback.
3. Requalify exact source/model, Windows, package and installed actions. Publish only newly validated immutable data, read back bytes/claim/pointer, then restore exactly the paused schedules and verify an actual scheduled run. Do not use real LINE delivery as a test.
