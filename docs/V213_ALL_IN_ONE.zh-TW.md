# Investor Intelligence v2.1.3 All-in-One

這個交付版把 v2.1.0、v2.1.1、v2.1.2、v2.1.3 的來源快照整合在同一個外層 ZIP，避免分散下載。

## 一鍵啟動

完整解壓後雙擊 `InvestorIntelligence.exe`。不要直接從 ZIP 壓縮檔內執行。

新版維護修正版標示為 `ModelSelect-R43 HealthSchema2`，提供：
- 掃描目前 llama.cpp router 的全部 model ID。
- 明確選擇並持久化本地模型；預設首選是 `RVN-Q6_K-multilingual-mtp`。
- 啟動所選本地模型並更新 Investor Intelligence 公開資料。
- 只啟動所選模型的 v2.1.3 bridge。
- 經二次確認後正式啟用每天 08:00 / 21:00 的 v2.1.3 七欄 LINE 推送。
- 開啟封裝資料夾。

任何 PowerShell 失敗都會顯示實際錯誤尾端，完整記錄保存於 `%LOCALAPPDATA%\InvestorIntelligence\logs\launcher\`；不再只顯示 `Exit code 1`。

## 選擇本地模型

啟動器會讀取目前 router 的 `/v1/models?reload=1`、`/models?reload=1` 或 `/v1/models`，並把實際 `data[].id` 顯示在下拉選單。除了固定探測 `8080 / 7905 / 14410 / 8813 / 8081 / 8000`，PowerShell bridge 也會檢查正在執行的 llama/localai/kobold 類程序實際 listening port。

操作順序：
1. 按「掃描 / Scan」。
2. 從下拉選單選擇 `RVN-Q6_K-multilingual-mtp`，或選擇你之後要使用的其他現有 model ID。
3. 按「使用 / Use」。
4. 再按「啟動所選模型並更新資料」，或「正式啟用」。

選擇結果保存在 `%LOCALAPPDATA%\InvestorIntelligence\UserData\config\v213-model-selection.json`。後續手動刷新、排程刷新、bridge 與正式 activation 都使用同一個選擇；系統不再默默取模型清單第一筆，也不再自動退回 Gemma 或 `qwen3.8-27b`。

正式使用前，bridge 會對選定 model ID 執行最小 `/v1/chat/completions` routing probe，以確認 router 能實際載入並回應該模型。Gateway 的本機與公開 `/health` 也都必須回報同一個 `selected_model` 且 `selected_model_available=true`；任何名稱不一致都在 Production deployment 前 fail closed。

HealthSchema2 另要求 `/health` 回傳 `service=v213-local-llm-gateway` 與 `health_schema_version=2`。若 8814 被舊版 v2.1.2 gateway 或其他程序占用，程式會安全辨識並停止自己的舊 gateway，或改用下一個可用 loopback port；缺少 `selected_model_available` 等舊 schema 欄位只會 fail closed，不會再因 PowerShell StrictMode 直接崩潰。

如果沒有偵測到 llama.cpp 服務，會嘗試既有 `D:\LocalAI\Start-LocalAI.cmd` 或 `D:\llama.cpp\Start-LocalAI.cmd`。

本地 model gateway 為 `scripts/v213_local_llm_gateway.py`。Shared secret 只在程序記憶體中使用，持久化時使用 Windows DPAPI 保護。Cloudflare quick tunnel 必須先通過公開 exact-model `/health`；若 Windows DNS 尚未看見新 tunnel hostname，會使用 Cloudflare DNS + `curl --resolve` 做保留 HTTPS SNI／憑證驗證的 fallback。

## 七欄 scheduled activation

正式 activation 使用 `cloud/src/v213/production-worker.ts`：
- EXE 會先完成一次 fresh 資料刷新與所選模型 bridge。
- 「正式啟用」要求公開 bridge 的 exact-model health gate 通過；否則 Production 不變。
- Wrangler `--json` stdout 與狀態文字／spinner stderr 分離，只解析單一 JSON document，不會再把 `search...` 當 JSON。
- 取得並驗證 deployment 前唯一 100% Worker version 後，才允許 secret／Worker mutation。
- 一般 fetch / Q&A 行為委派給既有 v2.1.2 owner Worker，因此保留 v2.1.1/v2.1.2 研究與本地模型路徑。
- 新增 authenticated `/v213/admin/top20-report`。
- 08:00 / 21:00 scheduled push 改用 v2.1.3 七欄 formatter。
- 仍要求 owner pairing、freshness、Top20 exact order、single-message、dedupe。
- activation 後續任一關失敗時回復部署前精確 Worker version。

正式啟用成功後，程式會複製到穩定位置 `%LOCALAPPDATA%\InvestorIntelligence\V213Runtime`，並把既有本地刷新工作更新為：
- 07:20：刷新公開資料、所選本地模型 bridge、v2.1.3 七欄 report。
- 20:20：同上。
- 08:00 / 21:00：Cloudflare Worker 通過 freshness gate 後才推送 LINE。

若未來某次本地模型 bridge 暫時失敗，資料刷新仍會繼續，已啟用的 Worker 不會因為一次 tunnel 失敗就被改成無模型版本；v2.1.3 report 仍會同步，開放式本地模型生成則 fail closed，下一次同一個所選模型 bridge 成功時再刷新 route。

`activate-v213-seven-field-schedule.ps1` 不會在下載或解壓時自動執行；必須由 EXE 中的「正式啟用」按鈕再次確認。

## 中英雙語欄位

所有目前公開 schema 的 machine key 維持英文以確保 API／KV／歷史資料相容性；`config/field-labels.zh-en.json` 為完整繁中／英文顯示字典，涵蓋 Top20、evidence、signed snapshot、source metadata、公開期權 DTO、v2.1.2 與 v2.1.3 report。CI 會執行 `scripts/audit_v213_bilingual_public_fields.py`，只要目前公開 schema 有任何必要欄位缺少 `zh-TW` 或 `en` 就 fail closed。

v2.1.3 formatter 支援 `zh-TW`、`en`、`bilingual` 三種 header 模式。Production 預設 `zh-TW` 保留 H6B2 已驗收格式。

## 版本快照

`versions/` 內含：
- v2.1.0：正式 tag 對應 commit
- v2.1.1：v2.1.2 開發前的整合里程碑
- v2.1.2：v2.1.3 renderer 開始前的最後完整 commit
- v2.1.3：本次 All-in-One 精確 commit

實際 SHA 由 ZIP 內的 `VERSION-REFS.json` 固定；`MANIFEST.json` 與 `SHA256SUMS.txt` 可用於檔案完整性驗證。
