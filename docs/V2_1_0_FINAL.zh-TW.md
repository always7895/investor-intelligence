# Investor Intelligence v2.1.0 正式版完整使用說明

> 本文件描述 v2.1.0 最終 Windows 使用流程。排名是研究工具，不是 Serenity 或 Leopold Aschenbrenner 本人發布的股票名單、背書、投資建議或報酬保證。

## 一、核心行為

v2.1.0 不要求手動輸入股票代號。執行後會由公開候選開始，經 SEC 正式公司身份與公開 evidence 驗證，使用專案自訂的 Serenity-first 七因子產生固定 20 檔公開排名，再依分數、資料品質與 ticker 決定 deterministic order。

99-source catalog 是完整 planning fabric，不代表 99 個來源已全部 live。v2.1.0 目前 reviewed runtime overlay 以 SEC EDGAR 與 World Bank 為主；yfinance 僅作本機 T3 候選發現與市場觀察。Aschenbrenner A/B/C 基礎設施分類獨立顯示，不加入 Serenity 主分數。

## 二、安裝

把正式 Private Release 外層 ZIP 解壓後，雙擊：

```text
install-final.cmd
```

安裝器會先驗證 application ZIP 的 SHA-256，才允許解壓。接著會安裝 verified portable CPython 3.12.10、hash-locked dependencies，執行 distribution tests，並用 Windows .NET Framework C# compiler 建立：

```text
InvestorIntelligence.exe
```

第一次正式安裝時會要求輸入 SEC Fair Access contact email。輸入是隱藏的；本機只保存 Windows DPAPI 保護後的字串，不寫入 Git、Release、LINE 或 Cloudflare。

安裝預設位置：

```text
%LOCALAPPDATA%\InvestorIntelligence
```

桌面捷徑名稱：

```text
Investor Intelligence v2.1
```

## 三、EXE 一鍵執行

雙擊桌面捷徑即可。EXE 只負責啟動已安裝的 `run-local.ps1`，不包含 LINE token、Cloudflare secret、券商憑證或交易功能。

一般執行：

```text
InvestorIntelligence.exe
```

安全 synthetic 驗證：

```text
InvestorIntelligence.exe --synthetic --no-sync --no-open
```

本機執行會依序：

```text
Serenity-first Top 20
→ 99-source plan
→ public report
→ public snapshot envelope
→ 若 owner LINE 已配置，才進行 HMAC signed public snapshot sync
```

## 四、固定時間

本機資料更新預設：

```text
07:20 Asia/Taipei
20:20 Asia/Taipei
```

啟用：

```powershell
& "$env:LOCALAPPDATA\InvestorIntelligence\App\2.1.0\register-task.ps1" -Enable
```

停用：

```powershell
& "$env:LOCALAPPDATA\InvestorIntelligence\App\2.1.0\register-task.ps1" -Disable
```

Cloudflare Owner LINE Worker 固定推送：

```text
08:00 Asia/Taipei
21:00 Asia/Taipei
```

因此本機更新會預留約 40 分鐘緩衝。

## 五、LINE / Cloudflare 啟用

正式安裝本身不會部署 Cloudflare，也不會修改 LINE webhook。完成正式 package 驗證後，才由你在本機明確執行：

```powershell
& "$env:LOCALAPPDATA\InvestorIntelligence\App\2.1.0\setup-v21-owner-line.ps1"
```

setup 會要求你在本機隱藏輸入 LINE channel secret 與 channel access token，建立三個實體分離 KV namespaces，產生 tenant hashing / encryption / HMAC / 一次性 pairing secrets，部署獨立 v2.1 Worker，設定 LINE webhook，並把一次性配對命令複製到剪貼簿。

不要把 LINE token、channel secret、pairing code 或 Cloudflare secret 貼到 GitHub Issue、PR、Release 或聊天。

## 六、LINE Bot

配對完成後常用查詢包含：

```text
Top 20
排名
AAOI 評分
AAOI 風險
AAOI 為什麼進榜
通知狀態
取消配對
```

LINE delivery 僅使用公開 Top 20 snapshot。它沒有 portfolio、持股、成本、損益、IBKR、自動下單或 paid fallback 路徑。

## 七、隱私與 fail-closed

以下條件任一不成立時，系統不應推送：

```text
Top 20 不足 20 檔
snapshot 過期
public schema 不合格
HMAC / timestamp / nonce 不合格
owner 尚未配對
同一 slot / snapshot 已推送
私人欄位進入 public payload
```

原始 LINE user ID 不放在 public KV、Git、Issue、Release 或 logs；owner delivery target 只在隔離的 private KV 以加密形式保存。

## 八、仍然不做的事

v2.1.0 不提供：

```text
自動交易
券商下單
持股個人化 Top 20
IBKR fallback
付費 provider fallback
99 個來源全部 live 的虛假宣稱
```

正式版的目標是可重現、可稽核、public-only 的研究排名與 owner-only LINE delivery。
