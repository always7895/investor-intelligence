# Investor Intelligence v2.1.3 R75 FREE_RELAY — 最新實作狀態

_Last reconciled / 最後核對：2026-09-05 Asia/Taipei_

## 目前權威狀態｜Authoritative state

```text
APPLICATION_VERSION = v2.1.3 R75 FREE_RELAY
RELEASE_TAG = v2.1.3-R75-free-relay-final-92c97f9-33896931576
RELEASE_SOURCE_COMMIT = 92c97f97694e6e39c7a16986630d248c9ee744fe
AUTHORITATIVE_WINDOWS_RUN = 33896931576
RELEASE_ZIP_SHA256 = 8b29e6b7ad6237042824e4c6af3a9b9cc16ea8a9e716b51fdfa8aca2c7da56ec
PRODUCTION_WORKER_VERSION = 27121388-1e6e-445a-b45e-104a867ca70d
PRODUCTION_WORKER_TRAFFIC = 100%
ROLLBACK_BASELINE = eb52ece1-8749-4526-a464-3356ec2dbc65
STABLE_ENTRYPOINT = https://investor-intelligence-v21-owner-line.moon951753.workers.dev
LOCAL_MODEL = qwen38-q6
CUSTOM_DOMAIN_REQUIRED = false
P0 = 0
P1 = 0
P2 = 0
```

GitHub Immutable Releases 已啟用。最新正式 Release 為不可變、非草稿、非 prerelease，且已通過 `gh release verify` 與下載後獨立驗證。

## 正式運作狀態｜Production operation

- Production Worker `27121388-1e6e-445a-b45e-104a867ca70d` 目前承接 100% 流量。
- FREE_RELAY 以既有 `workers.dev` 作為唯一穩定公開入口，不需要購買或設定自訂網域。
- TryCloudflare hostname 屬於短效後端，不宣稱固定；新 route 必須通過三次 Health Schema v2 與 exact-model 驗證後才可原子替換。
- `InvestorIntelligence-v213-FreeRelay` at-logon 工作已啟用，實際觸發 `LastTaskResult=0`，成功建立新 generation、停止舊 bridge 三程序，並在一個完整 heartbeat 週期後再次通過端到端 smoke。
- 舊 `InvestorIntelligence-v212-LocalModelBridge` 工作已停用；舊 bridge/tunnel 孤兒程序已清理。
- llama.cpp Router 採單一實例、`models-max=1`；正式驗證時僅 `qwen38-q6` loaded。
- 既有 08:00／21:00 Asia/Taipei Worker crons 保留；正式發布過程未額外手動發送 LINE。

## 端到端路徑｜End-to-end path

```text
workers.dev
  -> authenticated Durable Object route lease
  -> ephemeral TryCloudflare tunnel
  -> v2.1.3 local Gateway
  -> llama.cpp Router
  -> qwen38-q6
```

HMAC 驗證的固定提示詞 smoke endpoint 已回傳 HTTP 200、`status=PASS`、exact model `qwen38-q6`、Health Schema v2 與 expected marker。

## Serenity／publication 保護邊界

FREE_RELAY 是部署與傳輸層修正，不改寫研究方法：

- Serenity scoring：未變更；
- source federation thresholds：未變更；
- publication-mode contract：未變更；
- LIMITED／EVIDENCE_QUALIFIED 語意：未變更；
- sealed activation bundle：未變更；
- release evidence rules：未變更；
- `cloud/src/qa.ts`：與 R75 認證基準 byte-identical。

Publication contract 仍要求：

- LIMITED 不得 HIGH eligible；
- LIMITED 不得 validated thesis；
- 不受支持的正向敏感因子必須歸零；
- missing market corroboration 必須披露並限制信心；
- BLS 為 optional macro context，但必要的 source-family/domain/claim independence 仍 fail closed。

## Cloudflare Runtime 修正

Cloudflare 正式 Workers Runtime 不支援 `redirect: "error"`。目前 v2.1.3 wrapper 只對 HTTPS `POST /v1/chat/completions` 改用 `redirect: "manual"`，並自行拒絕所有 3xx，保留原本 fail-closed 語意。認證 Q&A blob 未修改。

## 驗證矩陣｜Validation matrix

```text
Python complete suite                 PASS (550 passed / 2 skipped)
Worker TypeScript typecheck           PASS
Worker Vitest                         PASS (19 files / 113 tests)
Windows PowerShell 5.1               PASS
PowerShell 7                          PASS
Security / credential scan            PASS
FREE_RELAY health / route / replay    PASS
Expiry / stale / mismatch rejection   PASS
Heartbeat / reconnect / rollback      PASS
Named Tunnel regression               PASS
Activation preflight / wrapper        PASS
Task Scheduler actual trigger         PASS (result=0)
Artifact post-download verification   PASS
GitHub immutable release verification PASS
```

CI 保持 `production_mutation_by_ci=false`。正式 Worker deploy、真實 route 與 Windows task 註冊均是獨立、明確授權的操作者動作。

## 隱私與安全不變條件

```text
LINE_DATA_SCOPE = PUBLIC_ONLY
LINE_IBKR_BRIDGE = FORBIDDEN
LINE_PORTFOLIO_TOOLS = FORBIDDEN
LINE_PRIVATE_SYNC = FORBIDDEN
LINE_OWNER_DATA = FORBIDDEN
FREE_ONLY_MODE = FAIL_CLOSED
AUTOMATIC_TRADING = FORBIDDEN
```

- Worker／LINE 不得取得 IBKR、帳戶、持股、數量、成本、損益、保證金、購買力或 owner 私人資料。
- Public、tenant-private、ephemeral-security state 保持物理／binding 分離。
- Secret 不得出現在 Git、Issue、Release、log 或 screenshot。
- 失效 route、模型 mismatch、heartbeat 中斷或健康檢查失敗時，模型路徑必須 unavailable，而不是降級為 stale route。

## GitHub 顯示狀態

- Repository description：已更新為繁體中文 R75 FREE_RELAY 正式版。
- Homepage：指向最新不可變 Release。
- Latest Release：繁體中文標題與完整說明。
- PR #24：R75 FREE_RELAY 正式發布，已合併。
- PR #25：登入工作與單模型重連實測，已合併。
- `main`：已包含正式程式與後續 Production 證據文件。
- 舊 v2.1.0 trackers、臨時 Issue 與未合併的舊 R75 PR：應關閉並標示由目前不可變正式版取代。

## 目前結論｜Current conclusion

**R75 FREE_RELAY 已完成正式發布與上線，P0/P1/P2 = 0/0/0。**

後續屬於日常營運監控：保持 Router、`qwen38-q6`、網路、heartbeat 與 08:00／21:00 排程正常；任何失敗都應 fail closed。歷史 v2.0.0、v2.1.0、R70 文件只保留作稽核，不再是目前安裝或 Production 權威。
