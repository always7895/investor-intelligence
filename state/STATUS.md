# Current state / 目前狀態

Updated:2026-09-12 UTC (15:35 local). Release identity:`README.md`. Historical lookup:`git show 38860e7:state/STATUS.md`; history is not current acceptance.

## Priority / authority / workspace

2026-09-12 使用者指示：**「承接專案上述工作，以line上線為第一要務」**。本 session 完成：source 修正、runtime 重新安裝、production 新資料發布、LINE 實機驗收（TOP20/Top 20/NVDA）、以及使用者對卡片內容的反饋修復（公司名稱、報酬率 N/A、產業翻譯）+ 重新部署 + 新一輪 FINALIZED。**下一步在操作者：手機 LINE 再發 `Top 20` 驗收新卡片**（snapshot `20260912T072732Z` fresh 至 2026-09-12 09:27 UTC / 17:27 local；20:20 local 排程會再生成下一輪並帶入產業翻譯補齊）。

Source:`_workspace/source`; evidence:`_workspace/audit-runtime`; mixed parent `D:\Investor-Intelligence-LINE-Pi` is not a fixture. One writer; retain worktrees/drafts, locks/journals and failures。

HEAD **`e11b443`**（本輪 commits：6f93242→e11b443），branch`fix/options-provenance-audit`, upstream`8178f72e1acb5d36cf51212a815a1097a28fdf3a`。未 commit 的本地安裝輸入（維持 untracked）：`HOTFIX-REFS.json`、`InvestorIntelligence.exe`、`cloud/wrangler.v213.production.local.toml`（deploy config，僅 KV namespace id）。

## 2026-09-12 完成事項（LINE 上線關鍵路徑）

1. **Morning 排程失敗根因 + 修正**：Stage 4 v2.1.2 build 缺 `--require-known-acquisition` → UNKNOWN market clock → row `retrieved_at=None` → bundle fail-closed 拒絕（正確行為）。兩個 entrypoint 已補 flag；`sec_cache_hours: 2` 明確寫進 policy；測試同步（fixture 24h + 新 2h TTL refetch 測試）。
2. **Production 新資料已上線（evening slot, 2026-09-12 05:09–05:12 UTC）**：
   - run **`20260912T051141Z-f04e8b28cf3a`**, transaction **`21c094ecd78783082b4ea9a89e77fa67`**, bundle sha `6cde50f3…`
   - journal `7525990b770f4e728a4b85a7daab55ce.json` = PASS/FINALIZED, production_mutation=true, 20/20 行皆帶 SEC-anchored retrieved_at，市場欄位 fail-closed UNAVAILABLE（degradation policy 語意）
   - `/health` 200；`/v213/readiness?challenge=…` → **ready=true, compatibility=PASS**, worker `c81e8825-…`
   - 注意：12:20 UTC 排程實際 12:42 才觸發（StartWhenAvailable 補跑；機器/排程疑似 12:20 時 sleep）。13:09 的 FINALIZED 為手動 `Start-ScheduledTask` 觸發（同一 task、同一 code path）。**07:20/20:20 兩個 slot 的「自然觸發」尚未各完成一次**（09-12 07:20 morning 已自然跑過但 publication 被下述 journal 問題擋下）。
3. **修復擋住所有 publication 的 broken journal**：`3df09596…json`（9/6 NOT_COMMITTED probe）9/7 被手動加 `resolved_utc`+`resolution` 欄位 → 超出 closed schema → `Read-V213RefreshJournal` INVALID → JOURNAL_CHECK 永久擋下。已還原 closed schema；註解版存 `.details/annotated-journal-20260907.json`；`.details/rollback.json`（not_committed ack）證據完整。
4. **Installer（coordinator）三個設計缺陷修復 + 端到端驗證**：
   - ownership coverage 原先涵蓋 `data/`：任何 refresh 寫 data 後，下一次 reinstall 必 fail `RUNTIME_OWNERSHIP_DIGEST_MISMATCH` → coverage-aware 驗證（manifest 檔案須 authentic per receipt；live payload 全部為已知且未改動；歷史 payload entries 須仍在且未改動；migration 掉的可變路徑永不 re-attest）。
   - 可變 segment 補齊：`__pycache__`（任意深度）、`reports/`（public_briefing_latest.md）、`.wrangler/`（auth cache）。
   - `cloud/node_modules` 被 name-based /XD 全深度排除 → runtime 無 wrangler → AUTH_CHECK `CommandNotFoundException`（9/12 evening 第二輪失敗根因）→ /XD 改 full top-level path；source 有 wrangler 時 stage 必須帶（否則 RUNTIME_REQUIRED_FILE_MISSING）。
   - 驗證：installer 測試 **35/35 PASS**（PS5.1+pwsh，含新 wrangler 回歸測試）；live reinstall **PASS**（transaction `71921c0f410c4a5ea895a6a21702efc5`，舊 root 保留；wrangler hash == source；manifest 678 files、無 excluded-segment leak）。
5. **Worker**：typecheck PASS；vitest **507/507 PASS**（含 core.ts `TOP20/TOP10` ranking-token 修正 + ticker-research 修復，見 #7）。**2026-09-12 14:20 UTC redeploy：deployed worker `fd50556d-43c3-4a1c-af4c-a886e5df64c9`**（取代 c81e8825；readiness ready=true、publication contract sha 不變 `9b96f2fd…`）。
6. **Python 全量**：941 tests；剩餘 14 broken 全部 pre-existing（HEAD 2b9e143 同失敗）：`test_v213_journal_reconciliation`（3，PS host archive readback）、`test_compiled_exe_profile_persistence_and_child_propagation`、`test_rejects_public_reads_from_private_namespace`（storage.ts 靜態 marker）、`test_repository_passes_v21_delivery_gate`（storage.ts retained v2.0 blob finding）。非 P0 關鍵路徑；不冒充已修。
- `git diff --check`: 0 issues（所有 commit 前）。

7. **Ticker research / TOP20（無空格）修復（使用者 13:28 實測發現）**：deployed c81e8825 把 `TOP20` 解成 ticker → 走 V211 research 路徑讀 `v211:universe:latest` → 該 key 的 R75 carryover chain 在 9/11 17:35 斷裂後永不再生成 → 拒答「沒有通過驗證的 universe」。修復（commit aa9ce3b，**不改 seal schema / commit object list / publication contract**）：research 改讀 sealed snapshot 內的 `v21:top20:latest`（同一批 21-key rows，legacy key 僅供 pre-R75 snapshot 回退）+ `parseV211ResearchUniverse` 接受 `system-operationalization-v2.1.3-diversified`（v2.1.3 rows 的 key set 與 RECORD_KEYS 完全一致，原本只卡 scoring_version 硬編碼）。現行 production snapshot（20260912T051141Z）deploy 後立即恢復 research 能力，rollback 到舊 snapshot 也不受影響。

## 2026-09-12 14:5x–15:3x UTC 卡片內容修復（使用者第二輪反饋）

使用者看 13:11 的 Top20 卡片後回報：**「公司原始名稱和中文翻譯沒有，回率以及相關資訊也沒有，沒有公開訂單」**。

1. **報酬率 N/A 根因（#2）**：yfinance 當時健康（2026-09-12 05:11 run 的 return-evidence 檔：20/20 `CALCULATED_NOT_QUALIFIED`、兩窗皆 AVAILABLE、actual_end 2026-09-11），但 `_market_observation` 從未把 dated acquisition receipt 綁進 market 欄位（`retrieved_at=None` + `UNKNOWN_PROVIDER_ACQUISITION_TIME`）→ `--require-known-acquisition` 下全部 degrade 成 N/A。修正（commit 7c5e42b）：yfinance 回傳且最新 bar ≤7 日（與 market-corroboration degradation policy 同寬）時，鑄 `LOCAL_FETCH_RECEIPT`（本地 fetch 時間 + evidence SHA 綁定）；空/過舊 price data 仍 degrade N/A；provider industry identity 與 price history 解耦。`validate_return_observation` 對 `CALCULATED_NOT_QUALIFIED` 接受鑄出的 receipt，其餘狀態維持舊 UNKNOWN 要求。語意等同 SEC HTTP receipt 的本地 fetch receipt，非 gate waiver（7200s freshness gate 仍界線 row clock）。
2. **公司名稱缺失（#1）**：seven-field v2.1.3 report 加 `name`（official public company name，來自 accepted Top20 universe；missing/invalid fail-closed）；worker parser 驗證 + LINE flex card 在 ticker 下渲染名稱（commit 7c5e42b）。七欄 display contract（display_columns、value tuple）不變。**中文譯名未加**：系統沒有已核對的中文名對照來源，依證據標準不猜譯（company-evidence-report.ts 明列）——如需要是後續工作（curated mapping）。
3. **訂單稀疏（#3）＝設計內**：order 欄只載 SEC-verified RPO；本輪 20 檔中 16 檔非 RPO 產業（銀行/保險/零售/礦業/公用/航太…），故 `未揭露（無可靠公開訂單數字）`。CF/FIS/NTNX/SMCI 4 檔有 RPO 文本。非 bug；若未來要收其他訂單類型揭露（backlog 等）是獨立 feature。
4. **產業翻譯補齊（commit e11b443）**：本輪 universe 的非科技產業（Agricultural Inputs、Property & Casualty Insurance、Retail、Gold、REIT、Solar…）原 fallback 到「其他產業」；加 exact Yahoo industry 表項 + keyword fallback（insurance/mining/solar/apparel/food/hospitality/reit 等）。20:20 local 那輪起生效。
5. **Production 重新部署 + 新資料（本輪，均在上線授權範圍）**：
   - worker **`d3375fe3-55e4-436c-9d12-4cff360a6578`**（14:57 UTC；readiness ready=true；含 name 渲染 + 前輪 research/TOP20 修正）
   - runtime 重新安裝 **PASS**（transaction `d6a03b9456c4482b860051581c853172`；新 code + wrangler 在 live tree 驗證）
   - evening slot 觸發 → run **`20260912T072732Z-2347c4bc506a`**、transaction `c5c07cffadeb8277af053abef452005c`、**PASS/FINALIZED/production_mutation=true**
   - production KV 驗證：`snapshot:current` → 新 run；v213 report **20/20 行有 long-term return、20/20 行有 name**（CF +34.03% 2y / +11.8% 6m；FIS -30.45%/-22.21%；NTNX +4.58%/+72.38%；SMCI -5.12%/+26.14%）
   - 注意：07:11 UTC 前舊 snapshot 已過期、新 commit 07:27 UTC 完成 → 之間約 16 分鐘 Top20 查詢會回 stale 訊息（預期 fail-closed 行為）。
6. **測試**：v212/v213 self-test PASS；`test_report_source_acquisition`/`test_v212_top20_report`/`test_ranked_report_candidates`/`test_debt_source_precision`/`test_v213_windows_security` 全 PASS；Python 全量 942 tests 剩 14 失敗＝與 HEAD 基線相同的 pre-existing 集合（無新增）；worker **507/507 PASS**（`tests/fixtures/source-acquisition-reports.json` 以 actual CLI 再生成，v213 records 含 name）。`test_native_runtime_stage_copy_never_copies_source_node_modules` 依 wrangler 修正後的 /XD 邊界更新（root node_modules 仍排除；cloud/node_modules 進 stage 供排程 AUTH_CHECK）。

## Open findings（未修，非上線阻塞）

- **P2** `options:latest`（期權問題）同屬斷裂 carryover，且 R75 bundle 無 options payload（市場資料 fail-closed 期間無法再生成）→ 期權類問題回 `OPTION_DATA_UNAVAILABLE`；待市場資料 pipeline 恢復後另行處理。

- **P2** manifest `source_commit` 綁定 `HOTFIX-REFS.json`（stale CI 產物，2b9e143）而非安裝當下 git HEAD；檔案 hash（entries_sha256）才是真實完整性綁定。建議：installer 以實際 git HEAD 記錄 source_commit 或要求 fresh refs。
- **P2** evening trigger 延遲 22 分鐘觸發（StartWhenAvailable）；WakeToRun=true 但未能在 12:20 準時喚醒/觸發。觀察明晨 07:20 自然觸發。
- **P2** 14 個 pre-existing Python 環境失敗（上列）。
- AAPL debt conflict：`publication_eligible=false` 持續（不擋 Top20 發布）。
- `/v213/admin/test-push` 仍 `LINE_FREE_PLAN_REVIEW_REQUIRED`（channel SHA pairing 未設）；上線驗證改走使用者真實對話。

## 2026-09-12 真實 LINE 驗收（操作者 14:17 UTC / 22:17 local 前）

- **`TOP20`（無空格）→ ✅ 20 筆七欄卡片全數回傳**（CF、FIS、NTNX、SMCI、ACGL、AFRM、BBY、CDE、FSLR、GAP … DG、NEM、PBR…），run 20260912T051141Z（報告產生 台北 13:11），bilingual 欄位、SEC profit summary（營收年增/益率/淨利率）、SEC RPO current orders（含文件日期與金額，如 CF ≈$1.5B 2026-08-06）、未來訂單展望、市場欄位 N/A（fail-closed 語意）、disclaimer、證據詳情連結。
- **`NVDA 怎麼看` → ✅ 設計內行為**：NVDA 不在本輪 Top20 → 交多來源 on-demand 研究層 → 本機模型橋接未啟用 → 回 `LOCAL_MODEL_NOT_CONFIGURED` 的 humanized 訊息（說明哪些功能仍可直接使用）。非錯誤、非假資料。
- **CP3 LINE Top 20 驗收完成。**

## Next step

1. 明晨 07:20 local morning slot 自然觸發 → 驗證 receipt（含 publication）→ 明晚 20:20 同輪 → CP4 雙 slot 自然跑各一次完成。
2. 其後依 PLAN §13：UI/UX → EXE/THINK → GitHub 上架。

**G01/G02/G11 status updated; W1 installer regression closed（含本輪三個 coverage/toolchain 缺陷）。Production snapshot live（20260912T051141Z）。**
