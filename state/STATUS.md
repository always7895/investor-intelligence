# Current engineering status

Updated2026-09-09. This is NOT a release certificate. Prior detail: `git show 309a93a:state/STATUS.md`; full historical record: `git show 38860e7:state/STATUS.md`. Receipts, failed runs and journals remain intact. Release identity belongs in README.

## Authority and workspace

- Fetched clean starting HEADcf8370fc5b42e8eeb4a1d0a88381fa781fc43ee5, branch `fix/options-provenance-audit`/PR37. Source: `D:\Investor-Intelligence-LINE-Pi\_workspace\source`. PR39 isolated at d58fdaf in `_workspace/review-source-views`; baseline52e285f in `_workspace/review-baseline`. One writer, no implicit integration.
- User authorizes repairs and LINE integration only after all data/work/validation acceptance. No real LINE sends, broker operations, new paid services, arbitrary credentials or stale activation replay. This step changes source/tests/docs only; no Production mutation.
- Outer project is installed runtime, not the Git root. Audit tools/evidence: `_workspace/audit-runtime`; history: `_archive/history-backups`. Never package or scan these as runtime market data. Root/source AGENTS have distinct roles.

## Current audit: public snapshot selection

- Found2 additional logic defects: an existing malformed/empty pointer could resolve to absence and resurrect direct public keys; separate report/stamp reads could resolve different snapshots and borrow another run's fresh stamp.
- Current Top20 uses `v213/public-snapshot.ts`: absent/invalid/valid pointer states, no invalid-pointer fallback, compatible bare IDs/runId alias, frozen read context shared by report/stamp. Retained storage.ts/qa.ts remain byte-identical. Other legacy consumers still require migration or recertification; NOT a global storage fix.
- Tests include malformed-pointer JSON/text reads with populated direct keys, legacy compatibility, immutable view metadata and pointer switches. Actual Top20 caller must reject run A's stale pipeline stamp even when pointer changes to fresh run B between reads. This fixes read consistency, NOT stored-content integrity or full card run/report-SHA binding.
- Initial Python failed3 guards: status12008-byte budget, old namespace-negative coverage and retained storage blob. Original log `snapshot-view-python.log` preserved. Restored storage exactly; moved modern reader to its own module and EXPANDED namespace/write-negative checks, no baseline-hash relaxation. Final Python676/2 skipped PASS (`snapshot-view-python-final.log`), Worker208/typecheck, five gates, retained-blob gate and PS5.1/7 parse PASS. Top20 source fixes2/deployed0; global/card-hash/data/release blockers remain.

## Retained audit: citation admission before publication

- Found report schema accepted any bounded https:// string, while evidence rendering rejected credential URLs later. An unsafe-to-display report could pass schema/activation. Formatter-only checks were insufficient.
- Shared `cloud/src/v213/public-citation.ts` now serves schema and renderer. Reject userinfo, IP/local-host shapes, nonstandard ports, controls/backslashes and credential query/hash keys, including nested encoding. Preserve ordinary escaped-space/percent filenames. This is URL-shape checking, NOT DNS, authority, rights or claim corroboration.
- Tests exercise normal Top20/detail loaders and actual activation: unsafe citation with correctly recomputed payload digests rejects before any KV write; same fixture with safe citation succeeds. No certified qa.ts or scoring changes. Python producer parity and other admission fields still need audit; no claim that every disclosure/privacy issue is solved.
- Citation source regression passed Python675/2 skipped, Worker185 and gates; original failures and final proof remain in `citation-admission-python*.log` and Gitcf8370f. Not latest release qualification.
- Commands: pinned Python `-B -m unittest discover -s tests -p 'test_*.py'`; `npm run typecheck`; `npm test -- --run`; repository gates and PS5.1/7 parse. Local tests do not replace live/install acceptance.

## Production and release blockers

- Last checked tasks `InvestorIntelligence-v21-MorningRefresh` and `InvestorIntelligence-v21-EveningRefresh` both Disabled. No restoration, Worker/model/EXE replacement or new sealed publication. Last confirmed remote data2026-09-08T12:20:02Z, promoted12:22:09.595Z; not freshly reverified here.
- Prior signed reconciliation returned NOT_COMMITTED, original FAIL/byte-identical archive preserved; prior journal scan unresolved0. Never replay that stale bundle. Sealed object integrity, exact rollback and pointer-last commit remain mandatory.
- Schema4 still seals seven payloads, excluding fresh options/universe and detailed-report datasets. Stale carry-forward removed, but replacement contracts, both builders/preflight/consumers and readback/replay/rollback/finalize acceptance remain incomplete.
- Current receipt verification fails LIVE_SOURCE_MANIFEST_MISMATCH. Historical Q5 thinking=false/effort=none matrix passed10 cases844–1890ms; receipt `r75-qa-live-model-profile-qualification.json` starts2026-09-09T05:26:24.943379Z.24h/source/profile binding applies. Original xhigh failure remains. Do not restamp evidence or use another Router/model/preset/paid fallback.
- Fresh exact-source model proof, protected-source recertification, Windows self-hosted acceptance, immutable source-SHA/run-ID ZIP and independent archive/receipt/extracted-install/download verification remain incomplete. No new qualified release.
- Whole-product P0 inventory NOT closed. PR39 historically retains3 Python evidence errors, not rerun/fixed here. New scoped regression results never establish whole-product zero defects.

## Actual report delivery gaps

- Candidate company evidence button checks ticker/generation/membership/row freshness. Authorized LINE event→card action→response and stale/unknown/unsafe-URL/citation-capacity tests exist. Candidate is not installed. Generation equality is NOT immutable run/report-SHA binding.
- [Detailed report contract](../docs/DETAILED_REPORT_CONTRACT.md): card summary, detailed data report and explanatory analysis need distinct content from one validated snapshot. Existing seven-field schema lacks verified Chinese/legal identity, detailed financial/order/capacity tables, diluted shares and valuation assumptions. `numeric_total_order_estimate_prohibited=true` remains.
- [TSEM operating draft](../docs/research/TSEM-20260909.md) covers contracts/prepayments, customers, capacity, cash flow, management model and competitor evidence. Receipt `research-dossiers/TSEM-20260909.json` retains passages/calculations/report SHA/Pi reference evidence and failed checks. Four pages/three publishers do not independently verify Tower contracts; draft SHA is not sealed binding.
- Scope:1 dated stock draft,0 newly delivered deep-report routes. Other company dossiers,6m/1y/2y valuations, options and macro reports remain incomplete. No invented names, orders, EPS or price targets; no summary clone labelled complete.
- Return builder now rejects600/120-day spans mislabeled2y/6m. Shared calendar-window calculator retains exact endpoints, cumulative/CAGR and file SHA in a `publication_eligible=false` sidecar. Currency/adjustment/dividend/calendar verification remains missing; not a public/sealed payload or live20-stock refresh. Actual CLI/synthetic/negative proofs remain in `return-evidence-python-final2.log` and Git2b5419b; installed dependency acceptance pending.

## Source expansion and data qualification

- Added15 broker/manager/media T3 discovery-only candidates via the SAME loader/gates/source fragments. Explicit `config/authoritative-source-catalog.research-candidate.json`:116 entries; default reviewed catalog unchanged101. No second collector or automatic activation. [Coverage/probes](../docs/PUBLIC_SOURCE_COVERAGE.md) records publishers and exact scope.
- Six public probes: four article/landing-page readable returns, Goldman403, Morgan Stanley aborted. Remaining sites are leads/proposals, not licensed feeds. Initial default expansion caused6 engine errors (`116 != 101`), preserved in `broker-source-catalog-python.log`; fixed by explicit candidate manifest, not weaker engine/activation checks. Candidate/base policy and original-record equality plus forced-activation negatives are tested. Prior Python675/2 skipped, Worker163/gates PASS (`broker-source-catalog-python-final.log`).
- Installed raw options:24 records, September9 retrievals, incomplete public eligibility/privacy attestations. Retrieval is not BBO time. Yahoo DTO stays line_public_eligible=false; no broker/private fallback.
- [Rights review](../docs/PUBLIC_SOURCE_RIGHTS_REVIEW_20260909.md): TAIFEX11320 is Taiwan daily/EOD with attribution, not realtime/US options. Last provider gate: public-access reviewed1, pending7, prohibited4; fully eligible/runtime/LINE-quote providers0, production selected false. Nasdaq terms failure and indicative-data permission gaps retained. No provider activated.
- Installed universe:30 rows, September7 generation, legacy policy. June30 may be a financial period, not stale-filing proof. No date/scoring relabelling. Broad directory collection1094 TWSE+890 TPEx, September8 dates, zero warnings; all PRIMARY_ONLY/discovery pending/publication false, not ranked global research.
- Collector7 endpoints/14,417 observations, news5 recent/55 stale; these counts do not corroborate company claims. Fixed-theme120/240 discovery and40/80 SEC reserves remain uncorrected. AMD Q2 original retrieved (mtttvgu2ollk18), Broadcom original aborted; no search-number promotion.

## Method, history and cleanup boundaries

- Serenity remains primary public-method lens; Leopold CONTEXT_ONLY, never company proof or score bonus. `research-method-refresh-20260909.json` records actual reference/tool evidence. X direct403 then truncated July31 oEmbed is not current/full stance; another404 remains unverified. Leopold original is historical2024, not today's holdings/facts.
- Three canonical source/installed skill files hash-matched at synchronization; originals archived `_archive/instruction-sync-20260909T070339Z`. Unsupported installed case sheet replaced by pointer. Documentation is not proof of an unbiased executed screen.
- Malformed-date-prefix rescue removed at snapshot/bundle admission in2a88e8e; legitimate date-only and actual-caller negatives preserved. Other time consumers require role-specific review.
- Consolidation1113a1c preserved HEADs/branches/evidence; five old roots absent, no junction substitutes. Relocated tests passed (`consolidation-*.log`), runtime unchanged. Bounded cleanup proofs remain in Git; no unique evidence/locks/rollback/runtime deletion.
- Old-named registered runner last observed Running/Auto with2.337.0 junction targets: not disposable. Installed inventory had57 file-stat errors, not complete deletion-safety proof. Models/Router/unrelated projects retained. [Workspace maintenance](../docs/WORKSPACE_MAINTENANCE.md) governs cleanup; no broad git clean, junction traversal or drive-wide deletion.

## Next actions

1. Audit remaining producer/admission/time/source-binding logic. Complete genuine company/financial/order data and separate stock/options/macro report producers; preserve failures/conflicts and independent lineage. Fix actual thematic selection without changing scoring.
2. Complete rights, identity/currency/session/freshness qualification; connect evidence and three distinct report outputs through one reviewed versioned sealed contract and actual Worker routes. No unsealed fallback or researcher-draft promotion.
3. Requalify exact source/model/Windows/package/installed actions. Publish only newly validated immutable data, read back bytes/claim/pointer, restore exactly the paused tasks and verify an actual scheduled run. No real LINE test sending; do not claim completion before these gates pass.
