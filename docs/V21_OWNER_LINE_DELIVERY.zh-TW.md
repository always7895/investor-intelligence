# Investor Intelligence v2.1.0：私人擁有者 LINE Top 20

## 功能範圍

v2.1.0 以 **Serenity-first** 七因子框架產生公開研究 Top 20，依序以 Serenity 分數、資料品質與股票代號排序。Aschenbrenner A/B/C 只作獨立基礎設施 overlay，不加入 Serenity 主分數。

系統保留 99 個已審查來源的目錄與啟用計畫；這不代表每次執行都已擷取 99 個來源。只有通過合法性、存取條件、解析器、資料品質與執行邊界的來源才會被當作本輪證據。yfinance 僅作公開市場候選發現與觀察，不能取代 SEC 等 authoritative evidence。

## LINE 功能

部署並完成一次性配對後，同一個私人擁有者可以：

- 每天 **08:00** 與 **21:00**（Asia/Taipei）收到最新公開 Top 20；
- 輸入 `Top 20`、`排名` 查看完整排序；
- 輸入 `AAOI 評分`、`為什麼 AAOI` 查看分數、七因子、風險旗標與公開證據；
- 使用既有公開報告、公開期權觀察與一般問答；
- 輸入 `通知狀態`、`取消配對` 或 `刪除我的資料` 控制私人配對與租戶資料。

資料過期、Top 20 結構不完整、LINE push 失敗或免費額度不足時，系統會 fail closed，不會改用付費服務，也不會傳送舊資料冒充最新資料。

## 隔離架構

v2.0.0 的 `cloud/src/worker.ts` 與 `cloud/src/line.ts` 保持不變，繼續代表既有共享 reply-only 邊界。v2.1.0 使用獨立入口：

```text
cloud/src/v21/worker.ts
cloud/wrangler.v21.production.template.toml
```

三個 Cloudflare KV namespace 必須使用不同 ID：

1. `PUBLIC_CACHE`：只有公開 Top 20、公開報告與公開來源摘要。
2. `TENANT_PRIVATE_CACHE`：只保存 AES-GCM 加密後的擁有者 LINE push 目的地與選用租戶資料。
3. `EPHEMERAL_SECURITY_CACHE`：Webhook 去重、速率限制、一次性配對碼狀態、同步 nonce 與排程去重。

原始 LINE user ID 不會寫入 Git、公開 KV、日誌或回覆內容；只會用租戶衍生金鑰加密後放入私人 KV。

## 公開快照同步

本機 Serenity 執行完成後：

```powershell
python scripts/v21_serenity_top20.py
python scripts/build_v21_public_snapshot.py
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\sync-v21-public-snapshot.ps1
```

同步封包只包含：

- exact Top 20；
- 99-source plan 的公開摘要；
- 公開研究報告；
- 每個 payload 的 SHA-256；
- HMAC timestamp、nonce 與 signature。

Cloudflare Worker 會重新驗證 SHA-256、HMAC、nonce、時間窗、Top 20 closed schema、固定排序與 public-only attestation，最後才更新 `snapshot:current` 指標。

## 排程

Cloudflare Cron 使用 UTC：

```text
0 0 * * *   = 08:00 Asia/Taipei
0 13 * * *  = 21:00 Asia/Taipei
```

正式安裝器會在本機較早執行 Serenity refresh 與公開快照同步，使 08:00／21:00 推送能取得新鮮資料。若本機未開機或同步失敗，Worker 會因 freshness gate 停止推送。

## 安全界線

v2.1 LINE 不讀取或傳送：

- IBKR 或任何券商帳戶；
- 持股、成本、損益、覆蓋口數；
- owner watchlist；
- 私人訊息或本機報告；
- 自動交易或委託；
- 未驗證的付費／受限來源。

Stage B 原始碼交易不會部署 Cloudflare、不會修改 LINE webhook、不會寫入任何 secret，也不會修改 `main`、integration 或 v2.0.0 Release。正式啟用由後續獨立、可驗證的本機部署交易完成。
