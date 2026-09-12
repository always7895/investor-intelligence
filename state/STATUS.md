# Current state / 目前狀態

Updated: 2026-09-12. Release identity: [README](../README.md). Previous complete state: `git show 6ffe6c86877c220c28b67f712edb38ea125806ca:state/STATUS.md`; maintenance history: `git show 1ba1a97713f4b152ffcb3cae4950c17076c8d0d0:state/STATUS.md`; older lookup: `git show 38860e7:state/STATUS.md`. History is not current acceptance or authorization.

## Scope and authority / 範圍與依據

使用者要求：完成 **TOP20／宏觀產業分析／期權** 三個LINE圖文選單入口，補公司原文／中文名稱、量化訂單及履約時程、6個月／1年／2年實現與未實現情境；按黑白貓咪／綠色金融圖片改善UI。優先：**LINE上線 → UI/UX → EXE模型切換確認／GitHub更新**。

本輪從已fetch的 **`6ffe6c86877c220c28b67f712edb38ea125806ca`** 繼續，branch `fix/options-provenance-audit`，upstream `8178f72e1acb5d36cf51212a815a1097a28fdf3a`。一位writer在`_workspace/source`；新證據在`_workspace/audit-runtime/line-data-20260912`。原3個untracked安裝輸入`HOTFIX-REFS.json`、`InvestorIntelligence.exe`、`cloud/wrangler.v213.production.local.toml`未改且不提交。混合installed parent不是fixture。

本輪修復與記錄的提交身分以`git log -4`及audit的`final-source-state.json`核對；本STATUS所在提交不是已安裝／已發布版本。

**未推送／dispatch、未安裝至實際runtime、未改Production Worker/KV/storage/排程、未送真實LINE、未切換實際模型／preset、未操作credentials/billing。** 既有批准不重播。測試使用隔離installer、原生EXE及合成transport；本機Edge只渲染合成HTML，不是第二個模型／HTTP伺服器。

Earlier Pi extension update is recorded at6ffe6c8; subsequent SoL-Pi unmet dependencies remain unexplained. No new dependency installation.

## Newly reproduced and repaired / 新反例與修復

1. **訂單時鐘被錯誤更新：** reconciliation把fresh五欄公司資料的`retrieved_at`填給沒有取得時間的旧訂單，繞過後段strict七欄builder。整串實際CLI的RED紀錄顯示錯誤通過且`acquisition_unknown=0`。現已移除借用；R15只從成功且被引用的source-text讀取保留最早取得起點，未讀／失敗URL不給時鐘。舊兩類已知clock-inheriting runtime baseline不能重用這些未證實時間；原輸入不覆寫。
2. **五欄完成時間不是七欄完成時間：** 新訂單可在五欄報告之後取得。七欄artifact現在使用自己的完成時間，但row仍是所有貢獻來源最早的取得時間；新完成時間不能更新舊來源。未知時鐘、來源在完成時間之後、重複取得錯誤排序均有反例。缺時鐘的strict CLI保留既有output/preview sentinels，不能寫出假新報告。
3. **合成測試污染開發快取：** 查見source預設TOP20含`Synthetic Company`，追到舊v2.1/v2.1.1測試直接`run(synthetic=True)`。在owned fixture重現舊程式覆寫4個default sentinels；不是對live runtime做重播。已改成synthetic必須指定非預設`--output-root`，live不接受這個override；self-test使用自有暫存目錄且不改全域路徑。
4. **相容wrapper也必須隔離：** 第一次完整回歸揭露coverage wrapper未接新參數，3 errors。已補forwarding，獨立計算plan目的地、驗證回傳路徑後才讀寫。progress CLI同樣forward；未刪歷史wrapper或放寬scoring。實際child CLI測試的default路徑本身也是隔離sentinels，回歸也不會再改真實checkout。

**現存6個source預設cache/report檔仍須視為不可信研究輸入。** 已記錄hash並保留現況，沒有假裝恢復真實行情或直接刪除；修正後完整測試前後6檔SHA一致。這證明不再覆寫這6個檔案，不等於原先合成內容已變成有效市場資料。完整fresh source-bound重新採集／驗收仍需執行。

Details: [engineering contract for synthetic output](../docs/ENGINEERING_MAINTENANCE.md), [research execution and clock audit](../docs/RESEARCH_EXECUTION_AUDIT.md).

## Verification / 指令與結果

- Existing CPython3.12.10: `-m unittest discover -s tests -p 'test_*.py' -v` final **967 tests, failures=0, errors=0, skipped=2**, **279.868s**. Two original skips are unavailable symlink creation. `full-python-corrected.log`. Earlier `full-python.log` retains966 tests/3 wrapper errors; `order-clock-red.log` retains the actual clock-bypass failure.
- Worker `npm run typecheck` PASS; full `npm test -- --reporter=default --reporter=json ...`: **521/521 PASS**, `full-typecheck.log`, `full-worker.json`, `full-worker.log`. Cloud code unchanged since6ffe6c8. Actual authorized menu/evidence callers use mocked LINE; these are not delivery receipts.
- Documentation boundary/structure, workflow supply chain, Actions storage, security, canonical candidate, KV isolation and owner delivery: **8/8 PASS**. `compileall`, `pip check`, `git diff --check` PASS; locks/dependencies/workflows unchanged. A later STATUS rewrite exceeded12000 bytes; failed document logs retained, shortened text rechecked separately.
- Full Python includes **84/84 tracked PS1 parse** under PS5.1/7,12 pure good/bad/missing guard cases per host, original-byte journal recovery and native launcher profile/selection/child/route negatives. Separate isolated `test_v213_activation_core.ps1` and `sync-v213-activation-bundle.ps1 -SelfTest` PASS on both hosts. No installed operation mutex, audit or normalize entrypoint used as fixture.
- `source-comparison.json`: **11 protected files byte-identical** to6ffe6c8 (certified`qa.ts`, `storage.ts`, production journal recovery, Worker/Python locks, scoring/compact/publication policy, canonical SKILL and references). In4 IO-touched Python modules, **77 other functions' AST and top-level assignments unchanged**; actual live output destinations retained. This comparison is not full semantic or model-adherence certification.
- `synthetic-cache-observation.json`, `legacy-synthetic-write-proof.json` preserve discovery and owned-fixture reproduction;6 default source-file hashes remain unchanged through corrected full regression. `output-wrapper-corrected.log` and `universe-wrappers-corrected.log` retain targeted corrections.
- Latest remote fetch/list:5 listed audits still skipped; historical R75 PASS `34422382127` belongs to`ec03f044…`, not this source. No matching-HEAD remote qualification, fresh source-bound live proof, immutable ZIP/receipt or release acceptance.

## LINE/UI status / 功能與視覺邊界

At6ffe6c8, three menu commands use the authorized/rate-limited caller and one pinned public view, not compact Q&A. TOP20 retains20 seven-field cards, original name/disclosure windows and ticker/date/snapshot/report-SHA-bound **證據詳情／本公司七欄文字** actions; not a deep report.

Macro gives20-candidate industry counts, not economic forecasts/weights/allocation: `MACRO_PRODUCT_NOT_SEALED`. Options links existing quotes/manual help; payload presence is not freshness/quote qualification: `OPTION_DATA_UNAVAILABLE` remains.

Shared monochrome/dark-green source theme and explicit missing-data labels are implemented. Chinese names remain unverified, not guessed. No restored literal MU/SMCI`TOP20_SENSITIVITY` ranges, arbitrary scenario percentages or promotion of candidate macro numbers.

**Local approximate visual review completed:** existing Edge headless opened owned HTML with isolated profiles, no added HTTP server. Reviewed `menu-local-approximation.png` and4 `top20-review-*.png` sheets: all20 short synthetic cards retain fields/warnings/actions without clipping; macro/options panels also reviewed. Supplied mascot appears in the local wrapper only; no uploaded/remote Flex asset. Not LINE device, maximum-length visual or live-data acceptance. Earlier managed-browser failure evidence retained.

See [LINE UI](../docs/LINE_TOP20_UI.md) and [preserved detailed-report contract](../docs/DETAILED_REPORT_CONTRACT.md).

## Open findings / 未完成（不刪需求）

1. **Data acquisition/admission:** tainted source cache cannot seed current research. No admitted bilingual company/security identity path, per-order ledger, complete20-company SKILL run or separate sealed data/narrative products. Need original passages/URLs/hashes, currency/units, counterparties, revision/cancellation/recognition periods, fiscal/calendar precision and independent lineage/rights. Aggregate RPO is not individual contracts; overlapping backlog/RPO/prepayments cannot be summed. Some businesses do not disclose meaningful order totals; do not fabricate them.
2. **6/12/24-month scenario numbers:** still unavailable. Need sourced shipment/recognition→revenue/margin/tax/capex/working capital→funding/dilution→appropriate valuation, dated reference price and explicit assumptions, separately realized/delayed/failed. No unsupported probabilities; missing operands are not0% growth/loss. Current UI warning and clock fixes do not implement this engine or acquire its inputs.
3. **Prior P2 options and macro delivery:** sealed `options:latest` gap persists; help/navigation do not supply Bid/Ask/Delta or qualified recommendations. Independent macro product absent; source HEALTHY and `publication_eligible=false` federation candidates cannot be promoted. Need versioned admission/pinned-consumer proof, not direct-key carryover.
4. **Prior P2 installed identity:** installed HOTFIX-REFS labels stale source`2b9e143`; actual hashes differ from source-bound release identity. Need fresh package/receipt/install proof, not silent ref edits. Synthetic compiled-EXE selection/routing tests do not close actual installed EXE→gateway→Worker completed-answer or real-model-switch acceptance.
5. **Prior P2 automation:** natural07:20/20:20 Taipei slots each still need publication acceptance. Previous evening catch-up delay22min; this slice made no task change and did not observe natural triggers. The supplied rich-menu manager screenshot's「已預約」is not current activation/delivery proof.
6. AAPL debt conflict stays`publication_eligible=false`; previous admin test-push had`LINE_FREE_PLAN_REVIEW_REQUIRED`, not bypassed. Real LINE device and independently verified release acceptance remain open.

Measured storage/journal failures from the earlier slice and the new clock/isolation regressions are locally repaired. Three previously tracked P2 groups (options, installed identity, automation), tainted-source-input recovery and research/UI/delivery gaps remain. **Whole-product P0/P1/P2 totals and release eligibility are not recertified** by local passing tests.

## Dated operator report (not re-read here)

Earlier authorized2026-09-12 work reportedly finalized snapshot`20260912T072732Z-2347c4bc506a`, Worker`d3375fe3-55e4-436c-9d12-4cff360a6578`,20/20 original names/returns. Another TOP20 report was`20260912T051141Z`; NVDA outside it returned designed`LOCAL_MODEL_NOT_CONFIGURED`. These are dated reports, not currently fresh evidence. Historical local/UTC labels are retained. Do not copy obsolete「no Production publication / both tasks Disabled」claims into current state.

## Next action

Fresh SEC collection is blocked here: `SEC_CONTACT_ENV_PRESENT=False` (presence only checked). Operator must set a valid contact locally or authorize field-only use of the existing runtime SEC contact; do not paste credentials/contact into chat. Then collect into isolation, admit bilingual identity/order operands and build scenario/macro/options products. Never reuse synthetic cache or unproven clocks. Deployment needs concrete scope/rollback plus fresh Windows/CI/archive/install and LINE-device proof; actual EXE/model/GitHub steps follow. No old activation replay or local-PASS-as-release claim.
