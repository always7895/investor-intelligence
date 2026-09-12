# Current state / 目前狀態

Updated: 2026-09-12. Release identity: [README](../README.md). Prior complete state: `git show 4ba2a606c9e459884e15354aa91798ec432df0ba:state/STATUS.md`; older lookup: `git show 38860e7:state/STATUS.md`. History is not current acceptance or authorization.

## Current work / 本輪範圍

使用者要求：根據近期社群資訊精簡／最佳化文件及除錯；比對LINE新舊截圖，確認Serenity／Leopold SKILL實際運作，保留逐筆訂單數據、履約時間、半年／1年／2年有依據的股價情境。

Fetched starting HEAD **`4ba2a606c9e459884e15354aa91798ec432df0ba`**, branch `fix/options-provenance-audit`, upstream `8178f72e1acb5d36cf51212a815a1097a28fdf3a` (ahead43 before this work). One writer in `_workspace/source`; audit evidence `_workspace/audit-runtime/lean-docs-20260912`. Existing untracked `HOTFIX-REFS.json`, `InvestorIntelligence.exe`, `cloud/wrangler.v213.production.local.toml` retained untouched. Mixed installed parent is not a fixture.

**This source-maintenance phase: source changes/tests/public web reads only. No runtime install, deploy, KV/storage/schedule mutation, real LINE send, credentials/billing change, real-model call/switch or preset change.** Existing Production authorizations are historical, not reused. Installed task actions have not been revalidated here.

Earlier separate user-requested `pi update --extensions` completed: SoL-Pi `2138669→d7ecfc0`, npm reported up-to-date/zero vulnerabilities. Subsequent SoL-Pi `npm ls` reported unmet dependencies; their origin was not established, so do not call them proven pre-existing. No additional Pi/package installation in this source cleanup.

## Findings and corrections / 查核與修正

- Old screenshot's MU/SMCI bull/bear price ranges were literal `TOP20_SENSITIVITY` strings at `6444dcd`, not calculated from per-order/financial/valuation data. Do not restore these as evidence. Different screenshot companies/runs are not themselves a loss/regression.
- Corrected evidence detail to use the accepted snapshot's existing company `name`; preserve disclosed order recognition text/windows and distinguish filing vs delivery dates. Chinese-name/product mapping remains unqualified, not guessed.
- Candidate cards now expose bound evidence and **本公司七欄文字** actions. Both use ticker/date/snapshot/report SHA; changed content/run fails closed. The 6/12/24-month valuation gap is visible, not silently removed. Seven-field text is not a deep report.
- Pi SKILL and both references were read; installed/source hashes matched. Top20 is deterministic and compact Q&A bypasses full legacy enrichment. Added truthful gateway `ii_methodology_execution` lane metadata; full skill execution/model adherence remain false. Legacy directive now explicitly treats Leopold as CONTEXT_ONLY and requires dated per-order/valuation premises. Scoring/compact policy unchanged.
- Replaced stale duplicated current-state/release tables with authority links; shortened historical handoff/model narratives with exact Git-history references. Complete data contract, historical receipts/negative evidence retained. Added full Markdown index and stdlib-only offline file-link/size gate in existing R75 caller; no new workflow/trigger/dependency.
- Fixed secondary Windows workflow's stale lock hash to the already-reviewed R75/current lock; no lockfile or package version changes.
- Broader parse-only inspection found4 previously unedited PS scripts with missing parentheses/quotes or UTF8-without-BOM PS5.1 decoding. Fixed punctuation/BOM only; preserved source/scoring thresholds and missing-data refusal. Added84-file dual-host parsing and actual isolated guard-expression tests, without executing audit/normalization entrypoints.

Details and source checks: [research execution audit](../docs/RESEARCH_EXECUTION_AUDIT.md), [engineering rationale](../docs/ENGINEERING_MAINTENANCE.md).

## Verification / Commands and results

Local review commits: `2e62d63` (bound company content / honest methodology lanes), `e3a33f5927605695d28212b302fd854544f45437` (PS syntax/encoding and guard tests). Documentation/CI/index changes are the commit containing this STATUS; resolve with `git log -1 -- state/STATUS.md`. These are local commits, not a release, remote CI run or installed source identity.

- Baseline: approved CPython3.12.10 `pip check` PASS; `-m unittest discover -s tests -p 'test_*.py' -v`: **942 tests, failures=3, errors=8, skipped=2**, 276.433s. Failure groups: STATUS12122>12000 bytes; two legacy storage static gates; journal reconciliation eight native-host subcases. Earlier STATUS's blanket “14 environment failures” is not this run's count.
- Baseline current CI inspected: R75 `34422382127` PASS on `ec03f044…`, not current HEAD; latest listed PR audit skipped. No workflow dispatched/pushed this session.
- New card regression initially RED (missing second action), then Vitest targeted PASS. Typecheck caught readonly/test-fixture types during implementation; corrected before final gates. Initial embedded-Python dotted unittest invocation could not import `tests`; use discovery, not count that toolchain invocation as product failure.
- Final `-m unittest discover -s tests -p 'test_*.py' -v`: **952 tests, failures=2, errors=8, skipped=2**, 275.507s. Exact case comparison: **no new failures**, STATUS size case resolved. Remaining two failures: `test_rejects_public_reads_from_private_namespace`, `test_repository_passes_v21_delivery_gate`; eight journal errors retain the same native-host/case IDs. Not overall PASS.
- Worker `npm run typecheck` PASS; `npm test -- --reporter=default --reporter=json ...`: **508/508 PASS**, including actual authorized Worker button routes, both stale/unknown/malformed action paths and no real LINE delivery.
- `documentation_boundary_gate.py`, `documentation_structure_gate.py`, `workflow_supply_chain_gate.py`, `actions_storage_policy_gate.py`, `security_check.py`, `canonical_release_candidate_gate_v2.py`: all PASS; `compileall` and `pip check` PASS. No dependency installation.
- PS5.1 `5.1.26100.9444` / PS7 `7.6.6`: **84/84 tracked PS1 parse PASS** on both;12 actual guard good/bad/missing cases per host plus max expression PASS. Isolated `test_v213_activation_core.ps1` and no-network transaction client self-test PASS both hosts. No normalize/audit entrypoint or actual operation mutex test run against the installed runtime.
- 92→94 Markdown files; baseline638588 bytes, final about20% smaller despite adding a complete index/research audit. Historical handoff120396→4173 bytes; full original remains in Git. Exact final totals in `comparison.json`; this is document-byte reduction, not measured model latency/token savings.
- Evidence retained under audit directory: `baseline-python-complete.log`, `card-red.log`, `final-python-complete.log`, `final-worker-tests.json`, `final-gates.log`, `after-powershell.log` (initial failures), `powershell-syntax-regression.log`, `gateway-process-final.log`, `comparison.json`. No new source-bound release receipt issued for this dirty checkout.
- Exact-byte comparison to starting HEAD: certified `cloud/src/qa.ts` (Git blob `94184bc8937b413eb327b3d773926db00e22b3b9`), Worker/Python locks, scoring weights and compact-QA policy unchanged. Failed/RED evidence retained.

## Open findings / 未完成（不刪需求）

1. **Order/scenario products incomplete:** current seal has no admitted per-order ledger or separate data/narrative valuation products. Must acquire/review values, original passages, currency, counterparties, periods/cancellation/recognition conditions and lineage; RPO aggregate cannot become invented individual orders. Need sourced operating→financing/dilution→valuation bridge for 6/12/24-month on-time/delay/failure scenarios and versioned sealed/pinned consumer acceptance. Current actions explicitly show missing data, not fabricated targets. No complete20-company SKILL research run is claimed.
2. **Prior P2 options:** `options:latest` carryover/payload gap returns `OPTION_DATA_UNAVAILABLE`; no quote/provenance gate relaxed.
3. **Prior P2 installer identity:** local HOTFIX-REFS binds stale source `2b9e143`; actual entries hashes, not the stale label, bind installed bytes. Needs fresh source-bound packaging/receipt acceptance; not silently rewritten.
4. **Prior P2 automation:** natural07:20/20:20 slots have not each completed publication acceptance. Earlier evening catch-up delay was22min; no current task change or natural-run observation here.
5. **Regression debt:** baseline two storage static assertions and eight native journal errors remain open; final comparison found no new failure cases. These are not waived/skipped to advertise green. Journal archive `FileNotFoundError` requires separate root-cause work; this audit does not label it conclusively environmental.
6. AAPL debt conflict remains `publication_eligible=false`. Administrative test-push still had `LINE_FREE_PLAN_REVIEW_REQUIRED`; not changed. Automatic THINK capability/full installed model chain acceptance remains separate.

Known new P0 found in this scoped work: none; **whole-product P0/P1/P2 totals not recertified**. Four previously tracked P2 groups remain (options, installer identity, automation, regression); missing research products are an explicit delivery gap, not closed by UI text.

## Last operator-reported operational evidence (not re-read this session)

On2026-09-12, prior authorized work installed runtime fixes and finalized snapshot `20260912T072732Z-2347c4bc506a`; Worker `d3375fe3-55e4-436c-9d12-4cff360a6578` was recorded deployed. That snapshot reportedly had20/20 original names and historical returns. These timestamps are not a claim the old snapshot is still fresh now. Earlier ledger notes mixed local/UTC labels; retain original evidence rather than invent corrected event times.

Operator reported `TOP20` returning20 seven-field cards for prior run `20260912T051141Z`; NVDA outside Top20 returned designed `LOCAL_MODEL_NOT_CONFIGURED`. Later cards/name/industry changes and natural slot acceptance require their own observations. Do not copy older “no Production publication / both tasks Disabled” into a current overview.

## Next action

Resolve the retained storage/journal regression debt and implement/review per-order data and reproducible scenario products under the preserved [report contract](../docs/DETAILED_REPORT_CONTRACT.md). New source changes require fresh release/model proof and independent archive/install checks before any separately authorized cutover. Do not replay the old activation.
