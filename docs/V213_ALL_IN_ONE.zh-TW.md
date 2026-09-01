# Investor Intelligence v2.1.3 All-in-One

這個交付版把 v2.1.0、v2.1.1、v2.1.2、v2.1.3 的來源快照整合在同一個外層 ZIP，避免分散下載。

## 一鍵啟動

雙擊 `InvestorIntelligence.exe`。

啟動器提供：
- 啟動本地 llama.cpp 模型並更新 Investor Intelligence 公開資料。
- 啟動 v2.1.3 本地模型 bridge。
- 經二次確認後正式啟用每天 08:00 / 21:00 的 v2.1.3 七欄 LINE 推送。
- 開啟封裝資料夾。

## 本地模型

v2.1.3 使用 OpenAI-compatible llama.cpp endpoint。預設優先探測 `127.0.0.1:8080`，並支援其他既有 loopback endpoint。
預設會自動讀取 `/v1/models` 的第一個模型；只有在無法取得 model ID 時才回退 `qwen3.8-27b`。可透過 PowerShell `-Model` 參數指定其他 model ID。
如果沒有偵測到正在執行的 llama.cpp，bridge 會嘗試啟動 `D:\LocalAI\Start-LocalAI.cmd`。

本地 model gateway 為 `scripts/v213_local_llm_gateway.py`。Shared secret 只在程序記憶體中使用，持久化時使用 Windows DPAPI 保護。

## 七欄 scheduled activation

正式 activation 使用 `cloud/src/v213/production-worker.ts`：
- 一般 fetch / Q&A 行為委派給既有 v2.1.2 owner Worker，因此保留 v2.1.1/v2.1.2 研究與本地模型路徑。
- 新增 authenticated `/v213/admin/top20-report`。
- 08:00 / 21:00 scheduled push 改用 v2.1.3 七欄 formatter。
- 仍要求 owner pairing、freshness、Top20 exact order、single-message、dedupe。
- activation 失敗時回復部署前精確 Worker version。

`activate-v213-seven-field-schedule.ps1` 不會在下載或解壓時自動執行；必須由 EXE 中的「正式啟用」按鈕再次確認。

## 中英雙語欄位

所有公開 schema 的 machine key 維持英文以確保相容性；`config/field-labels.zh-en.json` 提供繁中與英文欄位名稱。
v2.1.3 formatter 支援 `zh-TW`、`en`、`bilingual` 三種 header 模式。預設 `zh-TW` 保留 H6B2 已驗收格式。

## 版本快照

`versions/` 內含：
- v2.1.0：正式 tag 對應 commit
- v2.1.1：v2.1.2 開發前的整合里程碑
- v2.1.2：v2.1.3 renderer 開始前的最後完整 commit
- v2.1.3：本次 All-in-One 精確 commit

實際 SHA 由 ZIP 內的 `VERSION-REFS.json` 固定。
