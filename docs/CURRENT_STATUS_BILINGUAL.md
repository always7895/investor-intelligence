# 目前狀態／Current status

**尚未完成整體驗收；沒有新的合格 EXE／Production 發布。**
**Whole-product acceptance is incomplete; no newly qualified EXE or Production release.**

- 當前缺陷、測試及下一步以 [state/STATUS.md](../state/STATUS.md) 為準。下載版本身分以 [README](../README.md)、該 ZIP 的 HOTFIX-REFS、checksum 和相鄰 receipts 為準；不把舊版本的通過數字套到候選版。
- Current findings live in STATUS. Release identity belongs in README and each archive's own immutable evidence, not duplicated mutable tables.

## 模型與 EXE／Model and EXE

候選 EXE 有共同 model profile、模型清單、手動 THINK 關閉／強度選擇及子程序傳遞；原生 UI 測試涵蓋實際 Use 按鈕與設定儲存。新增單一 Router、禁止重新導向、大小／時間上限等清單讀取保護，並以原生 EXE 測試。新增「本機回覆測試」與相同呼叫路徑的 CLI；實際候選 EXE → PowerShell → Q5 在 none／low 完成固定回覆。**這不是研究品質、所有 THINK 強度或正式安裝驗收；自動最佳模式仍未實作／驗收。** 舊 Q5 none-thinking PASS 不符合後續來源版本；不得 restamp 或默默換模型／模式。

The candidate shares a profile across the EXE/bridge/gateway/Worker. Catalog transport is bounded and remains on the selected Router. The new local-reply button and CLI share one caller; the compiled candidate completed fixed replies through PowerShell and the real Q5 Router for none/low. This is not research quality, all-effort support or installed/release acceptance. Automatic think selection remains pending. See [model contract](MODEL_RUNTIME_MIGRATION.md).

## 自動更新／Automatic refresh

本輪讀取確認早晚發布任務仍 Disabled，動作指向預期安裝腳本；已知十個鏈路檔案中六個與來源不同、兩個新版模組未安裝。不能只換 EXE 或複製一個腳本就聲稱完成升級。尚未恢復排程、發布新資料或進行真實 LINE 測試。

Both publisher tasks remain disabled. Installed dependency-chain drift requires a coordinated, qualified installation. Fresh sealed publication, readback and actual scheduled-run acceptance remain separate requirements.

## 資料與輸出／Data and outputs

- 卡片候選入口已綁定快照與七欄來源報告 SHA；排程候選固定同輪，使用實際執行時鐘檢查新鮮度。這不代表 sealed claim 已完整驗證。
- Card input identity and broadcast consistency are improved; they do not certify sealed claims or data truth.
- 卡片摘要、詳細資料報告、完整文字分析須不同內容、同一驗證快照。股票／期權／宏觀仍未全面完成；七欄文字重排不是深度分析。見[報告契約](DETAILED_REPORT_CONTRACT.md)。
- No fabricated names, orders, EPS or targets; missing/unavailable/conflicting evidence stays explicit. Historical returns are not forecasts. No LIMITED upgrade based on formatting.
- 券商／國際研究網站候選不是已授權資料 feed；來源數不代表獨立主張佐證。LINE 期權報價來源資格仍未完成。見[來源覆蓋](PUBLIC_SOURCE_COVERAGE.md)與[期權權利審查](OPTIONS_SOURCE_REVIEW.md)。

## 精簡與權限／Lean operation and authority

Pi 套件、執行環境、測試依賴和 rollback 證據不是同一類檔案。先查依賴與實際使用，再清理可重建的多餘項目；不刪 active models、runner、未合併 worktrees 或唯一證據。見[工作區規範](WORKSPACE_MAINTENANCE.md)。

`production_mutation_by_ci=false`. Public LINE stays separated from owner/portfolio/IBKR data; no broker execution, new paid fallback, credential disclosure or stale activation replay. Historical operator approval is not current-session authorization. Old source/model/runner evidence remains historical, not a zero-defect guarantee.

Prior detail remains in Git: `git show dd3cf57:docs/CURRENT_STATUS_BILINGUAL.md`.
