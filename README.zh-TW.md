# Investor Intelligence v2.1.3 R75 FREE_RELAY 繁體中文完整說明

[主 README](README.md)｜[最新不可變正式版](https://github.com/always7895/investor-intelligence/releases/tag/v2.1.3-R75-free-relay-final-92c97f9-33896931576)

> **用途聲明：**本專案是市場研究與資料驗證軟體，不是個人化投資建議，不保證報酬，也不能取代使用者對 SEC、公司公告、交易所資料與其他原始來源的自行查證。

本文件說明目前正式上線的 **Investor Intelligence v2.1.3 R75 FREE_RELAY**。v2.0.0、v2.1.0、R70 與早期 Named Tunnel 文件屬於歷史紀錄，不再是目前安裝、啟用或 Production 判定依據。

## 1. 最新正式版本識別

```text
正式版本：v2.1.3 R75 FREE_RELAY
不可變 Release tag：v2.1.3-R75-free-relay-final-92c97f9-33896931576
正式程式來源 commit：92c97f97694e6e39c7a16986630d248c9ee744fe
權威 Windows CI run：33896931576
正式 ZIP SHA-256：8b29e6b7ad6237042824e4c6af3a9b9cc16ea8a9e716b51fdfa8aca2c7da56ec
Production Worker version：27121388-1e6e-445a-b45e-104a867ca70d
部署前回滾基準：eb52ece1-8749-4526-a464-3356ec2dbc65
穩定公開入口：https://investor-intelligence-v21-owner-line.moon951753.workers.dev
精確本機模型：qwen38-q6
自訂網域：不需要
最終缺陷：P0=0、P1=0、P2=0
```

GitHub 已啟用 Immutable Releases。最新正式 Release 為非草稿、非 prerelease、不可變，並包含 10 個具有 GitHub attestation 的資產。

## 2. 目前正式架構

```text
LINE／外部請求
  ↓
固定 workers.dev Worker
  ↓
HMAC 驗證的 Durable Object route lease
  ↓
短效且可撤換的 TryCloudflare Quick Tunnel
  ↓
本機 v2.1.3 Gateway
  ↓
127.0.0.1:8080 llama.cpp Router
  ↓
精確模型 qwen38-q6
```

### 2.1 為什麼不用付費網域

目前唯一穩定公開入口是既有的：

```text
https://investor-intelligence-v21-owner-line.moon951753.workers.dev
```

`*.trycloudflare.com` 只作為本機後端的短效路由，不會被宣稱為固定網址。每次電腦、Gateway 或 cloudflared 重啟後，系統會先驗證新通道，再以新的 route generation 原子替換舊 lease。

因此目前不需要：

- 購買 `.com`、`.tw` 或其他自訂網域；
- 將網域加入 Cloudflare；
- 使用付費 Cloudflare 方案；
- 依賴付費模型 API 或付費資料源。

Named Tunnel 功能仍保留為未來選配，但不是目前 FREE_RELAY 正式路徑的必要條件。

## 3. FREE_RELAY 安全機制

新的 route 只有在以下條件全部成立時才會發布：

1. Gateway 本機健康。
2. llama.cpp Router 可達。
3. 精確模型必須是 `qwen38-q6`。
4. Health Schema 必須為版本 2。
5. 公開 `/health` 必須連續成功三次。
6. route record 必須使用 HMAC 管理員簽章。
7. route generation 必須唯一且不可倒退。
8. `connected_at`、`expires_at` 與 TTL 必須有效。
9. Worker 端再次驗證公開健康狀態。
10. Durable Object 才能原子切換 current route。

Worker 會拒絕：

- 過期 lease；
- 舊 generation；
- replay nonce；
- model mismatch；
- schema mismatch；
- 非 HTTPS 或非 TryCloudflare URL；
- 缺少簽章或簽章不正確；
- 公開健康檢查失敗；
- malformed route record。

若 heartbeat 無法續租，lease 會過期並 fail closed，不會繼續使用已失效的舊通道。

## 4. Serenity 與 publication contract

R75 將「研究評分」與「是否具備足夠證據公開成高信心結論」分離：

```text
公開來源證據
  ↓
Serenity-compatible diversified operationalization
  ↓
Publication contract
  ├─ EVIDENCE_QUALIFIED
  └─ LIMITED_RESEARCH_CANDIDATE
  ↓
信心、發布與 LINE 閘門
```

### 4.1 不可破壞的保護邊界

FREE_RELAY 只修改部署與傳輸整合，不修改以下核心：

- Serenity scoring 邏輯；
- source federation 門檻；
- publication-mode contract；
- `EVIDENCE_QUALIFIED`／`LIMITED_RESEARCH_CANDIDATE` 語意；
- sealed activation bundle；
- release evidence rules；
- 經認證的 `cloud/src/qa.ts` 內容。

### 4.2 LIMITED 的安全行為

當免費非 Yahoo 市場交叉來源不足時，系統不會捏造證據，也不會把 LIMITED 標的升級成高信心：

- 不得標為 validated thesis；
- 不得標為 HIGH eligible；
- 未受支持的正向敏感因子必須歸零；
- 缺少的交叉驗證必須明確披露；
- market-quality degraded 會限制信心，而不是讓流程靜默通過。

BLS 屬於 optional macro context；真正必要的 source-family、domain 與 claim-level independence 門檻仍維持 fail closed。

## 5. Cloudflare Workers Runtime 相容修正

Cloudflare 正式 Workers Runtime 不接受：

```text
redirect: "error"
```

它會在實際發送 request 前直接丟出 TypeError。R75 的修正方式不是放寬 redirect，而是：

1. 只針對 HTTPS `POST /v1/chat/completions` 使用 `redirect: "manual"`；
2. 自行檢查 response；
3. 所有 3xx 仍直接拒絕；
4. 保持 fail-closed；
5. 不修改經認證的 Q&A 與 Serenity 邏輯。

另有一個 HMAC 驗證、固定 prompt、無 KV 寫入的：

```text
POST /v213/admin/free-relay-smoke
```

用來驗證完整路徑：

```text
workers.dev → route lease → Quick Tunnel → Gateway → qwen38-q6
```

正式 smoke 已取得 HTTP 200，並確認 exact model、Health Schema v2 與固定 marker。

## 6. 驗證結果

權威 release gate：

```text
Python：550 passed / 2 skipped
Worker：19 files / 113 tests PASS
TypeScript typecheck：PASS
Windows PowerShell 5.1：PASS
PowerShell 7：PASS
Security／credential scan：PASS
FREE_RELAY stale/replay/expiry/concurrency：PASS
Heartbeat／reconnect／rollback：PASS
Named Tunnel regression：PASS
Activation preflight／wrapper：PASS
Task Scheduler 實際觸發：result=0
下載後 artifact 獨立驗證：PASS
P0／P1／P2：0／0／0
```

CI 全程維持：

```text
production_mutation_by_ci=false
```

正式 Worker deploy、真實 FREE_RELAY route 與 Windows Task Scheduler 註冊，是使用者明確授權後由操作者執行，不是 CI 偷做的 Production mutation。

## 7. 正式下載與 SHA-256 驗證

從最新不可變 Release 下載：

```text
Investor-Intelligence-v2.1.3-R75-Free-Relay-Hotfix-
92c97f97694e6e39c7a16986630d248c9ee744fe-
33896931576.zip
```

同時下載 `.zip.sha256`。

PowerShell 驗證：

```powershell
$Zip = '.\Investor-Intelligence-v2.1.3-R75-Free-Relay-Hotfix-92c97f97694e6e39c7a16986630d248c9ee744fe-33896931576.zip'
$Actual = (Get-FileHash -LiteralPath $Zip -Algorithm SHA256).Hash.ToLowerInvariant()
$Actual
```

正確值：

```text
8b29e6b7ad6237042824e4c6af3a9b9cc16ea8a9e716b51fdfa8aca2c7da56ec
```

若不一致，不要執行，重新從不可變 Release 下載。

## 8. 解壓與啟動

1. 將 ZIP 完整解壓到獨立資料夾。
2. 不要直接覆蓋仍在執行中的舊資料夾。
3. 執行根目錄的：

```text
InvestorIntelligence.exe
```

4. llama.cpp Router 應位於：

```text
http://127.0.0.1:8080
```

5. 正式模型必須是：

```text
qwen38-q6
```

6. 不要另開第二個 llama-server。正式驗證狀態採：

```text
models-max=1
qwen38-q6=loaded
其他大型模型=unloaded
```

## 9. Windows 自動重連

正式工作名稱：

```text
InvestorIntelligence-v213-FreeRelay
```

設定：

```text
Trigger：使用者登入
StartWhenAvailable=true
MultipleInstances=IgnoreNew
```

它已做過真實 `Start-ScheduledTask` 測試：

- `LastTaskResult=0`；
- 建立新 route generation；
- 舊 Gateway／cloudflared／heartbeat 三個程序停止；
- 新 Gateway／cloudflared／heartbeat 存活；
- 完整 heartbeat 週期後 smoke PASS。

舊工作：

```text
InvestorIntelligence-v212-LocalModelBridge
```

已停用，舊 bridge/tunnel 孤兒程序已清除。

## 10. 日常健康檢查

### 10.1 Router 模型狀態

```powershell
Invoke-RestMethod http://127.0.0.1:8080/models
```

應只看到 `qwen38-q6` 為 loaded。

### 10.2 FREE_RELAY 工作

```powershell
Get-ScheduledTask -TaskName 'InvestorIntelligence-v213-FreeRelay'
Get-ScheduledTaskInfo -TaskName 'InvestorIntelligence-v213-FreeRelay'
```

### 10.3 固定 Worker 健康

```powershell
Invoke-RestMethod https://investor-intelligence-v21-owner-line.moon951753.workers.dev/health
```

### 10.4 本機 route 狀態

本機狀態檔位於：

```text
%LOCALAPPDATA%\InvestorIntelligence\UserData\config\v213-local-model.json
```

可以檢查 model、tunnel mode、PID、health schema 與 generation，但不要把 secret、完整 HMAC 設定或任何 credential 貼到 GitHub Issue、聊天室或截圖。

## 11. 08:00／21:00 LINE 排程

既有 Cloudflare Worker crons 保留：

```text
08:00 Asia/Taipei
21:00 Asia/Taipei
```

正式發布驗證期間沒有額外手動發送 LINE，以避免重複訊息。日常驗收重點：

- 每個時段只收到一則；
- LIMITED 狀態必須明確顯示；
- 不得出現 unsupported HIGH confidence；
- snapshot run ID、順序與 sealed bundle 必須一致；
- dedupe 與 stale-data gate 必須有效。

## 12. 隱私、安全與投資邊界

```text
LINE_DATA_SCOPE=PUBLIC_ONLY
LINE_IBKR_BRIDGE=FORBIDDEN
LINE_PORTFOLIO_TOOLS=FORBIDDEN
LINE_PRIVATE_SYNC=FORBIDDEN
LINE_OWNER_DATA=FORBIDDEN
FREE_ONLY_MODE=FAIL_CLOSED
AUTOMATIC_TRADING=FORBIDDEN
```

- LINE 與 Worker 不得讀取 IBKR、持股、數量、成本、損益、保證金、購買力、owner watchlist 或本機私人報告。
- Public、tenant-private 與 ephemeral-security state 使用分離的 binding。
- Secret 不得 commit，不得出現在 release、log、Issue 或 screenshot。
- 本系統沒有自動下單或 brokerage write 路徑。
- 本機 IBKR 若未來啟用，只能 loopback-only、read-only，且與 LINE／Worker／public KV 分離。

## 13. 回滾

正式 Worker 回滾基準：

```text
eb52ece1-8749-4526-a464-3356ec2dbc65
```

若新路由建立失敗，系統會在可能的情況下保留前一個仍健康的 generation；若前一個也過期，服務應顯示 unavailable，而不是使用 stale route。

不要以降低 source gate、停用 signature、延長無限 TTL、接受 model mismatch 或永久使用 `AllowTestTunnelException` 的方式處理故障。

## 14. GitHub 正式狀態

- Repository description 已更新為繁體中文最新版。
- Homepage 指向最新不可變 Release。
- 最新 Release 標題與完整說明為繁體中文。
- PR #24 為 R75 FREE_RELAY 正式發布整合，已合併。
- PR #25 為登入工作與單模型重連實測補充，已合併。
- `main` 已包含正式程式與後續實機證據文件。
- 舊 v2.1.0 tracker、臨時 Issue 與舊未合併 PR 應標示為已完成或由 R75 取代，不再作為目前權威狀態。

## 15. 文件索引

- [主 README](README.md)
- [R75 FREE_RELAY 架構](docs/V213_FREE_WORKERS_RELAY.md)
- [最新正式發布真相](docs/FINAL_RELEASE.md)
- [目前實作狀態](IMPLEMENTATION_STATUS.md)
- [文件索引](docs/README.md)
- [最終交付與 Production 證據](state/FINAL_DELIVERY_REPORT_R75_FREE_RELAY.md)
- [詳細狀態](state/STATUS.md)

## 16. 歷史文件處理原則

v2.0.0、v2.1.0、R70 與舊 release-candidate 文件保留作為歷史稽核證據，但會加上「已由 R75 FREE_RELAY 取代」的醒目說明。它們不應再提供目前安裝指令、Production 狀態或 release authority。

目前唯一正式權威是：

```text
v2.1.3-R75-free-relay-final-92c97f9-33896931576
```
