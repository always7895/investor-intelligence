# 正式交付與安裝／Release and installation

[最新不可變 Release／Latest immutable release](https://github.com/always7895/investor-intelligence/releases/latest) · [中英狀態／Bilingual status](CURRENT_STATUS_BILINGUAL.md)

Use the ZIP's own HOTFIX-REFS, external SHA256 and adjacent Windows/Worker/delivery receipts. Dated documentation describes its recorded baseline, not automatically every later package. Never overwrite an older ZIP/tag or borrow its qualification.

請先驗證 ZIP 的外部 SHA256，再解壓與執行 `install-v213-source-diverse-runtime.ps1`。固定 runtime 為 `%LOCALAPPDATA%\InvestorIntelligence\V213Runtime`，入口 `InvestorIntelligence.exe`。必要時在該 runtime 的 `cloud` 目錄執行 `npm ci --ignore-scripts --no-audit --no-fund`；依賴不隨 ZIP 分發，更新時既有 node_modules 應保留，lock 改變時需重新準備。

Code installation is distinct from authorization to deploy, publish or register Production jobs. The qualified user-machine cutover separately updated the runtime/relay/Worker, generated and finalized fresh all-LIMITED snapshots, and migrated07:20/20:20 refresh tasks to explicit sealed publication. Worker08:00/21:00 cron remains unchanged.

已完成 PS5.1/7、Python、full Worker/typecheck、實際新鮮 all-LIMITED preflight、隔離交易負向測試、ZIP獨立驗證、安裝與遠端讀回。CI未變更Production；另有當前使用者授權的正式操作。沒有額外真實LINE測試；正常排程送達／真機顯示仍待自然觀察。

Current limitations: owner must remain logged in with PC/network available; no logged-out guarantee. This workflow does not produce GitHub artifact attestation. Separate legacy `InvestorDailyBriefing` ownership remains unresolved. These limits are not hidden by the release's scoped PASS.

[操作文件／Operations](V213_FREE_WORKERS_RELAY.md) · [交付歷史／Delivery history](https://github.com/always7895/investor-intelligence/blob/main/state/FINAL_DELIVERY_REPORT_R75_FREE_RELAY.md)
