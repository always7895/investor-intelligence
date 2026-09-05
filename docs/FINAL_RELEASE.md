# Investor Intelligence v2.1.3 R75 FREE_RELAY 最終正式發布

[返回主 README](../README.md)｜[繁體中文完整說明](../README.zh-TW.md)｜[不可變正式 Release](https://github.com/always7895/investor-intelligence/releases/tag/v2.1.3-R75-free-relay-final-92c97f9-33896931576)

> 本文件是目前正式 release truth。舊 v2.0.0、v2.1.0、R70 與 release-candidate 文件只保留為歷史稽核資料。

## 正式版本識別｜Release identity

| 欄位 | 值 |
|---|---|
| 版本 | `v2.1.3 R75 FREE_RELAY` |
| Release tag | `v2.1.3-R75-free-relay-final-92c97f9-33896931576` |
| Release source commit | `92c97f97694e6e39c7a16986630d248c9ee744fe` |
| Authoritative Windows run | `33896931576` — PASS |
| ZIP SHA-256 | `8b29e6b7ad6237042824e4c6af3a9b9cc16ea8a9e716b51fdfa8aca2c7da56ec` |
| Production Worker | `27121388-1e6e-445a-b45e-104a867ca70d` — 100% active |
| Rollback baseline | `eb52ece1-8749-4526-a464-3356ec2dbc65` |
| Stable entrypoint | `https://investor-intelligence-v21-owner-line.moon951753.workers.dev` |
| Exact model | `qwen38-q6` |
| Custom domain | not required / 不需要 |
| Final defect count | `P0=0, P1=0, P2=0` |

GitHub Immutable Releases 已啟用。本次正式 Release 為 `immutable=true`、非草稿、非 prerelease，並已通過 `gh release verify`。10 個 release assets 包含正式 ZIP、checksum、MANIFEST、SHA256SUMS、SBOM、Windows receipt、deployment receipt、delivery receipt、independent verification 與 post-download verification。

## 正式部署架構｜Production deployment

```text
LINE / external clients
  -> stable workers.dev Worker
  -> authenticated Durable Object route lease
  -> ephemeral TryCloudflare Quick Tunnel
  -> local v2.1.3 Gateway
  -> llama.cpp Router (127.0.0.1:8080)
  -> exact model qwen38-q6
```

FREE_RELAY 不要求自訂網域，不購買網域，也不把短效 `*.trycloudflare.com` hostname 當成穩定入口。Worker 只在新 route 通過本機與 Worker 端三次 Health Schema v2、exact-model 驗證後，才以 Durable Object 原子切換 current generation。

## 正式上線結果｜Production result

- Production Worker version `27121388-1e6e-445a-b45e-104a867ca70d` 承接 100% 流量。
- 真實 FREE_RELAY signed route registration：PASS。
- Stable `workers.dev → lease → Quick Tunnel → Gateway → qwen38-q6` 固定 marker smoke：HTTP 200 / PASS。
- Heartbeat 完整週期：PASS。
- `InvestorIntelligence-v213-FreeRelay` Task Scheduler 實際觸發：result `0`。
- Task 建立新的 generation、停止舊 bridge/tunnel/heartbeat，並維持新三程序存活。
- 舊 `InvestorIntelligence-v212-LocalModelBridge` 已停用；舊 bridge/tunnel 孤兒已清理。
- Router 採單一實例與 `models-max=1`；正式驗證時僅 `qwen38-q6` loaded。
- 08:00／21:00 Asia/Taipei Worker crons 保留；正式上線期間沒有額外手動發送 LINE。

## Serenity 與證據邏輯保護｜Protected semantics

FREE_RELAY 是 transport/deployment integration，不修改：

- Serenity scoring；
- source-federation thresholds；
- publication-mode contract；
- LIMITED／EVIDENCE_QUALIFIED 語意；
- sealed activation bundle；
- release-evidence rules；
- certified `cloud/src/qa.ts` blob。

Publication gate 仍保持：

- LIMITED 不得 HIGH eligible；
- LIMITED 不得 validated thesis；
- unsupported positive sensitive factors 必須歸零；
- market corroboration 不足必須披露並限制信心；
- BLS 是 optional macro context，但必要 source-family/domain/claim independence 維持 fail closed。

## Cloudflare Runtime compatibility

Cloudflare 正式 Workers Runtime 會拒絕 `redirect: "error"`。R75 production wrapper 僅對 HTTPS `POST /v1/chat/completions` 使用 `redirect: "manual"`，並自行拒絕所有 3xx，維持原本 redirect fail-closed 語意。認證 Q&A blob 未被修改。

HMAC 驗證的固定 prompt smoke endpoint：

```text
POST /v213/admin/free-relay-smoke
```

不接受任意 prompt、不寫入 KV，只有在 current lease 能正確連到 exact model 並取得預期固定 marker 時才 PASS。

## 驗證證據｜Acceptance evidence

```text
Python complete suite                 PASS (550 / 2 skipped)
Worker typecheck                      PASS
Worker Vitest                         PASS (19 files / 113 tests)
Windows PowerShell 5.1               PASS
PowerShell 7                          PASS
Security / credential scan            PASS
Activation preflight / wrapper        PASS
FREE_RELAY stale/replay/expiry gates  PASS
Heartbeat / reconnect / rollback      PASS
Named Tunnel regression               PASS
Task Scheduler actual trigger         PASS (result=0)
Artifact post-download verification   PASS
GitHub release verification           PASS
```

CI 的正式證據仍標示 `production_mutation_by_ci=false`。Worker deploy、真實 route 與 Task Scheduler 註冊是使用者明確授權後的 operator-controlled actions，並未由 CI 偷做。

## 正式下載與驗證｜Download and verify

正式 ZIP：

```text
Investor-Intelligence-v2.1.3-R75-Free-Relay-Hotfix-
92c97f97694e6e39c7a16986630d248c9ee744fe-
33896931576.zip
```

PowerShell SHA-256 驗證：

```powershell
$Zip = '.\Investor-Intelligence-v2.1.3-R75-Free-Relay-Hotfix-92c97f97694e6e39c7a16986630d248c9ee744fe-33896931576.zip'
(Get-FileHash -LiteralPath $Zip -Algorithm SHA256).Hash.ToLowerInvariant()
```

預期：

```text
8b29e6b7ad6237042824e4c6af3a9b9cc16ea8a9e716b51fdfa8aca2c7da56ec
```

若 hash 不一致，不得執行。

## 執行與日常維護｜Run and maintain

1. 解壓到獨立資料夾。
2. 執行 `InvestorIntelligence.exe`。
3. 保持既有 llama.cpp Router 位於 `http://127.0.0.1:8080`。
4. 只允許 exact model `qwen38-q6` 作為目前 Production model。
5. 不要同時啟動第二個 llama-server。
6. FREE_RELAY at-logon task 與 heartbeat 會維護短效 lease；若 PC、Gateway、Router、cloudflared 或網路失效，route 應過期並 fail closed。

快速檢查：

```powershell
Invoke-RestMethod http://127.0.0.1:8080/models
Get-ScheduledTask -TaskName 'InvestorIntelligence-v213-FreeRelay'
Get-ScheduledTaskInfo -TaskName 'InvestorIntelligence-v213-FreeRelay'
Invoke-RestMethod https://investor-intelligence-v21-owner-line.moon951753.workers.dev/health
```

## 隱私與安全邊界｜Privacy and safety

```text
LINE_DATA_SCOPE=PUBLIC_ONLY
LINE_IBKR_BRIDGE=FORBIDDEN
LINE_PORTFOLIO_TOOLS=FORBIDDEN
LINE_PRIVATE_SYNC=FORBIDDEN
LINE_OWNER_DATA=FORBIDDEN
FREE_ONLY_MODE=FAIL_CLOSED
AUTOMATIC_TRADING=FORBIDDEN
```

Release 不包含 Cloudflare、LINE、GitHub、Gateway、HMAC 或 brokerage secrets。LINE／Worker 無權取得 IBKR、持股、數量、成本、損益、margin、buying power、owner watchlist 或本機私人報告。本系統沒有自動交易或 broker-write path。

## English summary

Investor Intelligence v2.1.3 R75 FREE_RELAY is the current immutable production release. It uses a stable `workers.dev` Worker and an authenticated expiring route lease to an ephemeral TryCloudflare tunnel. The exact model is `qwen38-q6`; no custom domain is required. Authoritative Windows CI, full Python and Worker tests, PowerShell 5.1/7, real Worker deployment, route registration, task-trigger reconnect, heartbeat and end-to-end model smoke all passed. Serenity and publication semantics remain protected and unchanged.
