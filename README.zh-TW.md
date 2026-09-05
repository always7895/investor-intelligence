# Investor Intelligence v2.1.3 R75 FREE_RELAY

[English／完整驗證表](README.md)｜[最新不可變 Release](https://github.com/always7895/investor-intelligence/releases/tag/v2.1.3-R75-qa-readiness-2cf585d-33960014393)｜[交付證據](state/FINAL_DELIVERY_REPORT_R75_FREE_RELAY.md)

研究軟體，非個人化投資建議。舊文件中的 v2.0.0、92c97f9 與舊全面完成敘述屬歷史記錄；目前以本頁連結的實際 release／receipts 為準。

## 已知問題／Known issue：LINE 七欄入口不一致

**不能宣稱整個產品已全部完成。** 下列正式修正版完成的是 Q&A／readiness；其互動 Top20 與舊 `/v21/admin/test-push` 仍走五欄，v213 排程則已有七欄。新修正已通過本機 TypeScript 與 133 個 Worker tests，但隔離 workers.dev 驗收遇 HTTP404，**尚未發布、安裝或部署**，也未宣稱真實使用者 LINE 七欄驗收完成。

The published hotfix qualifies Q&A/readiness, not every feature. Seven-field route unification is not yet released. [七欄定義與完整中英狀態／Bilingual status](docs/CURRENT_STATUS_BILINGUAL.md)。

## 最新驗證狀態（2026-09-05）

- Executable source：`2cf585d317a4ba3ca784641b1515bfa862fb38bd`
- Windows self-hosted CI：`33960014393` PASS
- ZIP SHA256：`da39073a3a0e8367ba7eb06b019a27e0e81bc133acac1fbfc57fcd91fa813e65`
- Production Worker：`c3cb4024-48f0-403d-9dd2-714d544af024`，100%
- 本次 Q&A latency／readiness 修復範圍 P0/P1/P2：**0/0/0**。這不是宣稱所有未測情境、實際使用者 LINE 傳送或市場資料完整性皆已驗證。

## 簡化後的行為

只有一條免費模型路徑：workers.dev → 簽章短期 lease → TryCloudflare → Gateway → 既有 llama.cpp → `qwen38-q6`。

- ticker 問題只取該 ticker 的公開證據；一般問題使用限長摘要；方法論使用固定 context；排名維持 deterministic renderer。
- 經本次明確授權，只有 compact Q&A／固定 smoke request 設定 `enable_thinking=false`。不修改使用者 preset、不切換模型、不啟動第二台 llama-server。
- 刪除重複 readiness 等待與舊獨立 benchmark；正式提交客戶端與隔離實測共用同一 readiness gate。
- 版本／parser／publication contract／policy 不符會 fail closed；不以 TOP20_INVALID 當成可重試的 propagation signal。
- smoke 只確認固定 marker 與 exact model，不載入整份 Top20，也不把 health PASS 當成回答 PASS。

## 實測與限制

真實隔離 workers.dev／Q6、合成公開資料 fixture：一般問題 cache cold／warm **5.733／4.627 秒**；ticker **3.737／2.985 秒**；方法論 **4.362／4.115 秒**；證據 **4.999／4.273 秒**。詳細 prompt／generation tokens 見英文首頁及 QA-Live-Receipt。

Production fixed smoke **2.902／2.647 秒 PASS**。7 秒 reference／waitUntil 在隔離 Worker 真實完成，LINE transport 為 mock，未發實際 LINE。Cache cold 指停用 prompt cache，不是重新載入模型。

Python565 tests／2 skipped、Worker22 files／131 tests、typecheck、security、PS5.1／7、final ZIP 解壓與隔離安裝、下載後獨立驗證全部 PASS。

**Production 原 snapshot／sealed bundle 未改、未重新 activation。** 舊 bundle 的歷史時鐘離線交易 PASS；在當前時間過期時仍拒絕，沒有放寬 freshness。LIMITED 不升 HIGH；分數、權重、claim independence、optional BLS、privacy／IBKR 分離均不變。08:00／21:00 任務與 cron 不變。

CI 一律 `production_mutation_by_ci=false`。Worker 程式更新、FREE_RELAY 橋接與 at-logon task 路徑更新，是本次授權後的獨立 operator 動作，不是 CI 部署。

## 本機安裝與啟動

本次已安裝並啟動於：

```text
%LOCALAPPDATA%\InvestorIntelligence\V213Runtime
```

桌面捷徑：**Investor Intelligence R75**。舊 Downloads／UserData／原 snapshot 保留。

其他機器請先下載 Release ZIP 與 `.zip.sha256`、比對 SHA256，再解壓並執行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install-v213-source-diverse-runtime.ps1
& "$env:LOCALAPPDATA\InvestorIntelligence\V213Runtime\InvestorIntelligence.exe"
```

保留既有 `127.0.0.1:8080` Router、`models-max=1`、exact `qwen38-q6`。不需購買 domain、API 或付費模型。FREE_RELAY lease 過期時拒絕使用舊 tunnel；既有 at-logon task 會從穩定 runtime 重建橋接。

不要將 LINE ID、HMAC／Cloudflare／Gateway secrets、券商資料或 `.env` 放入 Git、issue、日誌或模型提示。
