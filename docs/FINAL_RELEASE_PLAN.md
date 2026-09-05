# Investor Intelligence v2.1.3 R75 FREE_RELAY 營運與維護計畫

> 檔名 `FINAL_RELEASE_PLAN.md` 為相容既有連結而保留；本文件現在描述已正式發布後的營運、驗證、故障與下一版變更規則，而不是舊 v2.0.0 release candidate 計畫。

[最新正式發布](FINAL_RELEASE.md)｜[繁體中文完整說明](../README.zh-TW.md)｜[FREE_RELAY 架構](V213_FREE_WORKERS_RELAY.md)

## 1. 目前正式基線

```text
VERSION = v2.1.3 R75 FREE_RELAY
RELEASE_TAG = v2.1.3-R75-free-relay-final-92c97f9-33896931576
RELEASE_SOURCE = 92c97f97694e6e39c7a16986630d248c9ee744fe
WINDOWS_CI = 33896931576 / PASS
ZIP_SHA256 = 8b29e6b7ad6237042824e4c6af3a9b9cc16ea8a9e716b51fdfa8aca2c7da56ec
PRODUCTION_WORKER = 27121388-1e6e-445a-b45e-104a867ca70d / 100%
ROLLBACK_BASELINE = eb52ece1-8749-4526-a464-3356ec2dbc65
STABLE_ENTRYPOINT = workers.dev
EXACT_MODEL = qwen38-q6
CUSTOM_DOMAIN_REQUIRED = false
P0_P1_P2 = 0_0_0
```

## 2. 不可變規則｜Non-negotiable boundaries

```text
LINE_DATA_SCOPE=PUBLIC_ONLY
LINE_IBKR_BRIDGE=FORBIDDEN
LINE_PORTFOLIO_TOOLS=FORBIDDEN
LINE_PRIVATE_SYNC=FORBIDDEN
LINE_OWNER_DATA=FORBIDDEN
FREE_ONLY_MODE=FAIL_CLOSED
AUTOMATIC_TRADING=FORBIDDEN
```

任何後續維護不得：

- 把 IBKR、brokerage、持股、數量、成本、損益、margin、buying power 或 owner 私人資料導入 LINE／Worker／public state；
- 以付費 provider 或付費模型作為靜默 fallback；
- 關閉 signature、TTL、replay、exact-model、health 或 publication gate；
- 把短效 TryCloudflare hostname 宣稱為固定入口；
- 修改不可變 release tag 或替換既有 release assets；
- 在 CI 中執行未授權 Production mutation；
- 自動下單或新增 brokerage write path。

## 3. 日常營運檢查

### 3.1 llama.cpp Router

```powershell
Invoke-RestMethod http://127.0.0.1:8080/models
```

要求：

- Router 單一實例；
- `models-max=1`；
- `qwen38-q6` 為 loaded；
- 其他大型模型為 unloaded；
- 不另開第二個 llama-server。

### 3.2 FREE_RELAY Windows 工作

```powershell
Get-ScheduledTask -TaskName 'InvestorIntelligence-v213-FreeRelay'
Get-ScheduledTaskInfo -TaskName 'InvestorIntelligence-v213-FreeRelay'
```

要求：

- enabled；
- at-logon；
- `StartWhenAvailable=true`；
- `MultipleInstances=IgnoreNew`；
- 最近一次正常觸發結果為 `0`。

### 3.3 Worker 健康

```powershell
Invoke-RestMethod https://investor-intelligence-v21-owner-line.moon951753.workers.dev/health
```

穩定入口只能是 `workers.dev`。後端 TryCloudflare URL 可更換且不應出現在公開文件、Issue 或 screenshot 中作為固定連結。

### 3.4 Heartbeat 與 route lease

本機狀態：

```text
%LOCALAPPDATA%\InvestorIntelligence\UserData\config\v213-local-model.json
```

Log：

```text
%LOCALAPPDATA%\InvestorIntelligence\logs\v213-local-model\free-relay-heartbeat.stdout.log
%LOCALAPPDATA%\InvestorIntelligence\logs\v213-local-model\free-relay-heartbeat.stderr.log
```

Heartbeat 只有在 Gateway、cloudflared、Worker-side health 與 exact model 全部正常時才能續租。失敗時 lease 必須自然過期並 fail closed。

## 4. 08:00／21:00 排程驗收

保留的 Production crons：

```text
08:00 Asia/Taipei
21:00 Asia/Taipei
```

每次實際時段驗收：

1. 只收到一則 LINE；
2. 沒有 duplicate broadcast；
3. public snapshot 為 fresh；
4. Top 20 順序與 sealed bundle 一致；
5. LIMITED 狀態醒目；
6. unsupported HIGH 不得出現；
7. Worker／route／model mismatch 時不送出不可信內容；
8. log 與 receipt 不包含 secret 或 owner 私人資料。

## 5. FREE_RELAY route 更新流程

```text
建立新 Gateway generation
  -> 建立新 Quick Tunnel
  -> 本機 health schema v2 / exact-model checks
  -> Worker 端三次公開 health checks
  -> HMAC signed route registration
  -> Durable Object atomic generation switch
  -> 啟動 heartbeat
  -> 停止舊 generation
```

禁止先停舊 bridge 再驗證新 route。新 generation 失敗時，應保留前一個仍健康的 route；若前一個已過期，應顯示 unavailable。

## 6. 故障處理

### Router `/models` 為空

1. 不要開第二個 server。
2. 停止空的既有 Router。
3. 以同一個 `D:\llama.cpp\llama-server.exe`、同一個 `127.0.0.1:8080` 串行重啟。
4. 使用專案專用 preset，維持 `models-max=1`。
5. 確認 `qwen38-q6=loaded` 後再觸發 FREE_RELAY 工作。

### Heartbeat 失敗

- 檢查 Router model、Gateway PID、cloudflared PID、網路與 Worker health；
- 不要手動延長過期 lease；
- 不要關閉 expiry/replay gate；
- 修復後建立新的 generation。

### Cloudflare redirect 錯誤

Production wrapper 必須只在 HTTPS `POST /v1/chat/completions` 使用 `redirect: "manual"`，並拒絕所有 3xx。不得改回 Runtime 不支援的 `redirect: "error"`，也不得跟隨 redirect。

### Worker 回滾

已記錄 rollback baseline：

```text
eb52ece1-8749-4526-a464-3356ec2dbc65
```

回滾時仍需重新驗證 route、signature、exact model、schema、LINE 與 public-only 邊界，不能回復 revoked secret 或 stale route。

## 7. 變更與 release gate

任何影響 Runtime、Worker、Gateway、activation、scheduler 或 publication 的新變更，必須在新的 branch／PR 進行，且至少通過：

- current-tree security scan；
- Python complete suite；
- TypeScript typecheck；
- full Worker Vitest；
- Windows PowerShell 5.1；
- PowerShell 7；
- exact-model、schema-v2、3-health checks；
- stale／replay／expiry／malformed／mismatch negative tests；
- heartbeat／reconnect／rollback；
- Named Tunnel regression；
- activation preflight/wrapper；
- package ZIP CRC、path safety、MANIFEST、SHA256SUMS、SBOM、receipts；
- post-download verification；
- `production_mutation_by_ci=false`。

舊 commit 的 PASS 不可轉移到新 HEAD。

## 8. Serenity／publication 變更規則

下列檔案與語意屬於 release-protected boundary：

- `config/v213-r75-publication-mode-v1.json`；
- `scripts/v213_r75_activation_preflight.py`；
- `cloud/src/v213/publication-mode.ts`；
- `cloud/src/v213/activation-v2.ts`；
- `cloud/src/qa.ts`；
- sealed bundle schema、order、digest、freshness、provenance；
- LIMITED／EVIDENCE_QUALIFIED 與 HIGH eligibility 規則。

若下一版確實需要改動，必須視為新的 methodology/release 版本，不得偽裝成單純部署 hotfix。

## 9. GitHub 文件維護

每次正式版後必須同步更新：

- Repository description；
- Homepage；
- latest Release title/body；
- `README.md`；
- `README.zh-TW.md`；
- `IMPLEMENTATION_STATUS.md`；
- `docs/FINAL_RELEASE.md`；
- `docs/V213_FREE_WORKERS_RELAY.md`；
- open Issue/PR trackers；
- 文件索引與歷史版本標示。

歷史 release 與已關閉 tracker 應保留，但要明確寫出「已由目前不可變正式版取代」，不得讓讀者誤認成最新安裝指令。

## 10. 目前下一步

R75 FREE_RELAY 已正式發布與上線。正常情況下不再執行開發或重建 release；只進行：

- 08:00／21:00 實際排程觀察；
- heartbeat／route lease／Router 健康監控；
- 嚴格的安全與資料來源品質維護；
- 有明確需求時，另開下一版本 branch。
