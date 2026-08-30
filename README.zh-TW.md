# Investor Intelligence v2.0.0 繁體中文完整使用說明

[English README](README.md)｜[v2.0.0 私人 Release](https://github.com/always7895/investor-intelligence/releases/tag/v2.0.0)

> 本專案是隱私優先、免費模式優先的市場研究軟體。它不是個人化投資建議，不保證報酬，也不能取代使用者對原始資料與正式公告的自行查證。

本文件說明已正式交付的 Investor Intelligence v2.0.0。繁體中文文件可以在正式 Release 之後更新，但正式程式內容仍以 `v2.0.0` tag、下列 commit 與 SHA-256 為準。

## 1. 正式版本識別

```text
版本：2.0.0
正式 source commit：4aebf8e828666424bdd2bc0411478c9ef621ddbd
正式 source tree：7054e640fdc3887fe72c449c155577c5689cfe45
Application ZIP SHA-256：82b526e72f71d870c5d4d371ae5f79437230a47e77df3534882e69c1efe30ee4
Outer delivery ZIP SHA-256：0dbe29cb3258c1074df2490b5473e69a1c45665af0a061420a09981793f7268e
```

正式外層交付檔名：

```text
Investor-Intelligence-v2.0.0-Final-Private-Delivery.zip
```

其獨立校驗檔：

```text
Investor-Intelligence-v2.0.0-Final-Private-Delivery.sha256
```

正式 Release 位於 private repository，因此只有獲授權並登入 GitHub 的帳戶才能看見或下載。

## 2. 可以放在別的資料夾或磁碟嗎？

可以，但要區分「下載／保存位置」與「實際安裝位置」。

### 2.1 正式交付 ZIP 的保存位置

正式外層 ZIP 與 `.sha256` 可以放在任何一般、可讀取的本機資料夾，例如：

```text
D:\Investor-Intelligence-Downloads
E:\Software\InvestorIntelligence
C:\Users\<你的帳戶>\Downloads
```

建議把外層 ZIP 與其 `.sha256` 放在同一資料夾，不要改名，也不要只保留其中一個。

### 2.2 實際安裝位置

預設安裝位置是：

```text
%LOCALAPPDATA%\InvestorIntelligence
```

也可以用 `-BaseInstallRoot` 指定另一個本機資料夾或磁碟，例如：

```powershell
$InstallRoot = 'D:\InvestorIntelligence'

powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install-final.ps1 `
  -BaseInstallRoot $InstallRoot
```

第一次安裝建議使用專用且可寫入的資料夾。不要安裝在 GitHub Actions Runner 工作目錄，例如包含下列片段的路徑：

```text
\_work\
\_diag\
\actions-runner
\runner\_work\
```

### 2.3 程式、Python runtime、設定與報告能否完全分開？

v2.0.0 可以把整個 `BaseInstallRoot` 搬到另一個磁碟，但目前沒有獨立的 `DataRoot`、`ConfigRoot` 或 `ReportsRoot` 安裝參數。因此正式支援的是「整套根目錄改到其他位置」，不是把設定、報告與程式拆散到不同磁碟。

不建議安裝完成後直接用檔案總管拖曳已安裝資料夾，因為 `install-state.json`、排程與啟動命令會記錄絕對路徑。要換位置，請在新位置重新安裝。

### 2.4 自訂安裝路徑的桌面捷徑注意事項

v2.0.0 內建的 `-CreateDesktopShortcut` 捷徑只適用預設安裝根目錄。自訂 `BaseInstallRoot` 時，請不要依賴該自動捷徑；改用含有 `-BaseInstallRoot` 的啟動命令。

例如將下列內容存成桌面的 `啟動 Investor Intelligence.cmd`：

```bat
@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "D:\InvestorIntelligence\App\2.0.0\run-local.ps1" -BaseInstallRoot "D:\InvestorIntelligence" -OpenReports
```

若安裝到其他位置，請把兩個 `D:\InvestorIntelligence` 一起改成實際路徑。

## 3. 系統需求

- 64 位元 Windows。
- 能寫入選定的安裝資料夾。
- 第一次安裝需要網路，用來取得已驗證的 portable CPython 3.12.10 與 hash-locked Python dependencies。
- 執行市場研究時需要網路，資料供應商暫時無回應或限流時，部分資料可能無法取得。
- 一般使用不需要自行預裝 Python；正式 installer 會管理獨立 runtime。
- 安裝不需要 LINE token、Cloudflare credential、IBKR 帳戶資料、持股資料或其他秘密值。

預設安裝到 `%LOCALAPPDATA%` 通常不需要系統管理員權限。若選擇受 Windows 保護的目錄，可能因寫入權限而失敗，建議改用自己的資料磁碟專用資料夾。

## 4. 下載後先驗證外層 ZIP

在外層 ZIP 與 `.sha256` 所在資料夾開啟 PowerShell：

```powershell
$Zip = '.\Investor-Intelligence-v2.0.0-Final-Private-Delivery.zip'
$Checksum = '.\Investor-Intelligence-v2.0.0-Final-Private-Delivery.sha256'

(Get-FileHash -LiteralPath $Zip -Algorithm SHA256).Hash.ToLowerInvariant()
Get-Content -LiteralPath $Checksum
```

兩邊都應顯示：

```text
0dbe29cb3258c1074df2490b5473e69a1c45665af0a061420a09981793f7268e
```

若不一致，不要安裝，重新從 private Release 下載正式檔案。

## 5. 最簡單的預設安裝

1. 解壓縮外層 ZIP。
2. 確認下列檔案位於同一資料夾：

```text
install-final.cmd
install-final.ps1
investor-intelligence-2.0.0.zip
investor-intelligence-2.0.0.sha256
```

3. 雙擊：

```text
install-final.cmd
```

`install-final.cmd` 會呼叫正式 PowerShell installer、驗證內層 application ZIP、安裝 portable Python、安裝固定 hash dependencies、執行 `pip check` 與 distribution-safe offline tests，並建立預設桌面捷徑。

預設安裝完成後的主要位置：

```text
程式：%LOCALAPPDATA%\InvestorIntelligence\App\2.0.0
Python：%LOCALAPPDATA%\InvestorIntelligence\Runtime\Python-3.12.10
本機設定：%LOCALAPPDATA%\InvestorIntelligence\UserData\config
安裝狀態：%LOCALAPPDATA%\InvestorIntelligence\install-state.json
報告：%LOCALAPPDATA%\InvestorIntelligence\App\2.0.0\reports
快取／歷史：%LOCALAPPDATA%\InvestorIntelligence\App\2.0.0\data
執行記錄：%LOCALAPPDATA%\InvestorIntelligence\App\2.0.0\daily_briefing.log
```

## 6. 安裝到其他磁碟的完整做法

外層 ZIP 解壓後，在該資料夾開啟 PowerShell：

```powershell
$InstallRoot = 'D:\InvestorIntelligence'

powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install-final.ps1 `
  -BaseInstallRoot $InstallRoot
```

安裝後請用：

```powershell
$InstallRoot = 'D:\InvestorIntelligence'

powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  "$InstallRoot\App\2.0.0\run-local.ps1" `
  -BaseInstallRoot $InstallRoot `
  -OpenReports
```

自訂根目錄下的結構會是：

```text
D:\InvestorIntelligence\
├─ App\2.0.0\
├─ Runtime\Python-3.12.10\
├─ UserData\config\
└─ install-state.json
```

## 7. 第一次啟動：設定研究股票

第一次執行時，若 `research-universe.local.json` 仍含有 `EXAMPLE`，程式會開啟記事本並停止。這是刻意的首次設定流程，不是錯誤。

預設設定檔：

```text
%LOCALAPPDATA%\InvestorIntelligence\UserData\config\research-universe.local.json
```

自訂安裝例：

```text
D:\InvestorIntelligence\UserData\config\research-universe.local.json
```

可將內容替換成下列公開股票範例：

```json
{
  "schema_version": 1,
  "privacy_class": "local_user_configuration",
  "stocks": [
    {
      "ticker": "AAPL",
      "name": "Apple",
      "category": "Technology",
      "source": "local-user-defined",
      "primary_evidence": [],
      "corroborating_evidence": [],
      "disconfirmation_conditions": []
    },
    {
      "ticker": "MSFT",
      "name": "Microsoft",
      "category": "Technology",
      "source": "local-user-defined",
      "primary_evidence": [],
      "corroborating_evidence": [],
      "disconfirmation_conditions": []
    }
  ]
}
```

儲存後關閉記事本，再啟動一次。

### 7.1 Ticker 規則

- 至少一個 ticker。
- 建議使用大寫。
- 不可重複。
- 只接受英數字、`.` 與 `-` 的安全格式。
- 不可包含 `..`。
- 不可用 `.` 或 `-` 結尾。
- 不要在這個檔案填入持股數量、成本、損益、帳號、LINE ID、broker credential 或 token。

頂層支援的欄位是：

```text
schema_version
privacy_class
updated（可省略）
stocks
```

未知頂層欄位會 fail closed，而不是被靜默忽略。

## 8. 本機偏好設定

另一個本機檔案是：

```text
UserData\config\user-preferences.local.json
```

它包含可選的長期研究 overlay。預設：

```text
long_term_overlay.enabled = false
minimum_holding_years = 2
```

這個 overlay 是本機使用者偏好層，不會改寫原始來源，也不會被當成公開證據或傳給 shared LINE／public KV。

## 9. 日常執行方式

### 9.1 預設安裝

可雙擊桌面上的 `Investor Intelligence` 捷徑，或執行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  "$env:LOCALAPPDATA\InvestorIntelligence\App\2.0.0\run-local.ps1" `
  -OpenReports
```

### 9.2 自訂安裝

```powershell
$InstallRoot = 'D:\InvestorIntelligence'

powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  "$InstallRoot\App\2.0.0\run-local.ps1" `
  -BaseInstallRoot $InstallRoot `
  -OpenReports
```

`-OpenReports` 會在成功完成後開啟報告資料夾。省略此參數仍會執行，只是不自動開啟檔案總管。

### 9.3 本機研究流程會做什麼

本機 pipeline 依序執行：

1. 取得主要市場指數與公開市場資料。
2. 依 `research-universe.local.json` 取得股票資料。
3. 產生本機 options observations；IBKR read-only 預設關閉時使用已標示的 yfinance fallback。
4. 執行 scoring／ranking。
5. 執行 active scan；預設不套用自動變更。
6. 掃描 movers。
7. 產生本機報告。

資料供應商、網路或 ticker 本身缺少欄位時，報告可能顯示資料不足。這不代表系統可自行補造資料。

## 10. 查看報告與除錯記錄

預設報告資料夾：

```text
%LOCALAPPDATA%\InvestorIntelligence\App\2.0.0\reports
```

預設 log：

```text
%LOCALAPPDATA%\InvestorIntelligence\App\2.0.0\daily_briefing.log
```

自訂安裝時，把 `%LOCALAPPDATA%\InvestorIntelligence` 換成自訂 `BaseInstallRoot`。

執行失敗時，先查看 `daily_briefing.log` 最後一段。常見原因包括網路中斷、供應商限流、ticker 不存在、JSON 格式錯誤或自訂路徑沒有寫入權限。

## 11. 排程：預設關閉，必須明確啟用

安裝不會自動建立排程。請先完成研究股票設定，並至少手動成功執行一次，再啟用排程。

### 11.1 預設時間

星期一到星期五：

```text
早上 07:30
晚上 20:30
```

### 11.2 啟用預設排程

```powershell
& "$env:LOCALAPPDATA\InvestorIntelligence\App\2.0.0\register-task.ps1" -Enable
```

### 11.3 自訂時間

```powershell
& "$env:LOCALAPPDATA\InvestorIntelligence\App\2.0.0\register-task.ps1" `
  -Enable `
  -MorningTime '08:00' `
  -EveningTime '21:00'
```

### 11.4 自訂安裝根目錄的排程

```powershell
$InstallRoot = 'D:\InvestorIntelligence'

& "$InstallRoot\App\2.0.0\register-task.ps1" `
  -BaseInstallRoot $InstallRoot `
  -Enable `
  -MorningTime '07:30' `
  -EveningTime '20:30'
```

### 11.5 查看排程狀態

預設安裝：

```powershell
& "$env:LOCALAPPDATA\InvestorIntelligence\App\2.0.0\register-task.ps1"
```

自訂安裝：

```powershell
$InstallRoot = 'D:\InvestorIntelligence'
& "$InstallRoot\App\2.0.0\register-task.ps1" -BaseInstallRoot $InstallRoot
```

### 11.6 停用排程

```powershell
& "$env:LOCALAPPDATA\InvestorIntelligence\App\2.0.0\register-task.ps1" -Disable
```

排程使用目前登入的 Windows 使用者、Limited 權限、`StartWhenAvailable`，並防止同一任務重複並行。由於使用 Interactive logon，使用者未登入時不應假設一定會執行。

## 12. 重新安裝與更新同一版本

同一位置已存在 v2.0.0 時，若只是重新驗證 runtime，直接再次執行 installer 即可。若要明確重裝程式檔案，使用 `-Force`：

預設位置：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install-final.ps1 `
  -CreateDesktopShortcut `
  -Force
```

自訂位置：

```powershell
$InstallRoot = 'D:\InvestorIntelligence'

powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install-final.ps1 `
  -BaseInstallRoot $InstallRoot `
  -Force
```

正式 `-Force` reinstall 會保留既有 `data`、`reports`、`daily_briefing.log`，而 `UserData` 位於 application 目錄之外，也不會被一般程式替換刪除。仍建議在重要操作前自行備份 `UserData` 與報告。

## 13. 從舊位置移到新位置

不建議直接剪下貼上整個已安裝資料夾。建議流程：

1. 停用舊位置排程。
2. 在新 `BaseInstallRoot` 重新安裝。
3. 關閉程式後，視需要複製舊位置的 `UserData`、`reports`、`data` 與 `daily_briefing.log`。
4. 用新位置命令手動執行並確認成功。
5. 確認新位置正常後，再卸載舊位置。

跨根目錄搬移使用者資料目前不是 installer 的自動交易，因此複製前請自行保留備份。

## 14. 卸載

### 14.1 一般卸載，保留本機設定與報告

```powershell
& "$env:LOCALAPPDATA\InvestorIntelligence\App\2.0.0\uninstall.ps1"
```

一般卸載會先停用兩個排程，並把本機設定與可用的報告／資料／log 移到：

```text
%LOCALAPPDATA%\InvestorIntelligence\Preserved-<UTC時間>
```

### 14.2 自訂安裝位置卸載

```powershell
$InstallRoot = 'D:\InvestorIntelligence'

& "$InstallRoot\App\2.0.0\uninstall.ps1" `
  -BaseInstallRoot $InstallRoot
```

### 14.3 永久刪除全部本機資料

只有在確定不要保留設定、報告、資料與 log 時才使用：

```powershell
& "$env:LOCALAPPDATA\InvestorIntelligence\App\2.0.0\uninstall.ps1" `
  -RemoveLocalData
```

`-RemoveLocalData` 是不可逆的本機資料刪除選項。

## 15. 常見問題

### 問題：第一次執行只開啟記事本

原因：研究 universe 還有 `EXAMPLE`。替換成一個以上有效 ticker，儲存後再執行。

### 問題：顯示 `Investor Intelligence is not installed at ...`

原因：啟動命令使用錯誤的根目錄。自訂安裝必須在 `run-local.ps1`、`register-task.ps1` 與 `uninstall.ps1` 一致傳入同一個 `-BaseInstallRoot`。

### 問題：顯示 checksum 或 SHA-256 不符

不要略過。確認 application ZIP 與 `.sha256` 是同一份正式 Release，檔名沒有變更，且下載完整。

### 問題：顯示 destination already exists

該位置已有其他內容或另一份安裝。只有在確定是同一套正式安裝且要替換時才使用 `-Force`。

### 問題：portable Python 或 dependencies 遺失

重新從正式交付資料夾執行：

```powershell
.\install-final.ps1 -Force
```

自訂根目錄要加上相同的 `-BaseInstallRoot`。

### 問題：排程沒有產生報告

依序確認：

1. `research-universe.local.json` 已移除 `EXAMPLE`。
2. 手動執行成功。
3. 目前 Windows 使用者已登入。
4. `register-task.ps1` 顯示兩個 task 已註冊。
5. 查看 `daily_briefing.log`。
6. 自訂安裝路徑的排程有傳入正確 `-BaseInstallRoot`。

### 問題：市場資料缺欄位或暫時失敗

本機 runtime 使用公開資料來源，供應商可用性、ticker 支援與網路狀況會影響結果。系統會保留錯誤／資料不足狀態，不應把缺失資料當成已驗證事實。

## 16. 隱私與功能邊界

正式安裝預設狀態：

```text
LINE_ENABLED = false
LINE_PUSH_ENABLED = false
PUBLIC_KV_SYNC_ENABLED = false
CURRENT_PUBLIC_DATA_ENABLED = false
CLOUD_INFERENCE_ENABLED = false
MEMORY_FEATURE_AVAILABLE = false
IBKR_READONLY_ENABLED = false
FREE_ONLY_MODE = true
PAID_FALLBACK_ENABLED = false
SCHEDULES_ENABLED = false
```

重要邊界：

- 沒有自動下單路徑。
- 本機 report 不會自動送到 LINE、Worker 或 public KV。
- Shared LINE 不得取得 IBKR、券商帳戶、持股、數量、成本、損益或本機 watchlist／報告。
- 本機設定與報告不包含在正式 Release package，也不應提交到 Git。
- 本機 options service 在 IBKR read-only 未啟用時可使用標示來源的 yfinance fallback；它不會要求或推測券商持股。
- 啟用 LINE、Cloudflare、IBKR、memory、public KV 或外部使用者都是之後的獨立審查／部署交易，不是本文件的安裝步驟。

## 17. 正式驗證狀態

v2.0.0 已完成：

- GitHub Support sensitive-history purge。
- 最終 Git history／all-object privacy confirmation。
- Trusted Windows full-stack validation。
- 完整 Python regression。
- Worker TypeScript 與 tests。
- Formal package build、checksum、manifest、SPDX SBOM。
- Distinct clean-install acceptance。
- Windows PowerShell 5.1 真實 installer acceptance。
- Final acceptance receipt。
- 兩次 byte-identical outer delivery build。
- Private Release inner／outer ZIP 回下載 SHA-256 驗證。

GitHub Actions 的 formal workflow 曾因帳戶 artifact-storage quota 在 upload-artifact 步驟失敗；package、clean-install、PS5.1 installer 與 receipt 本身已通過，正式檔案已改由 private Release assets 交付並完成回下載驗證。

## 18. 需要保存哪些檔案

建議長期保存：

```text
Investor-Intelligence-v2.0.0-Final-Private-Delivery.zip
Investor-Intelligence-v2.0.0-Final-Private-Delivery.sha256
```

外層 ZIP 內另含：

```text
investor-intelligence-2.0.0.zip
investor-intelligence-2.0.0.sha256
investor-intelligence-2.0.0.manifest.json
investor-intelligence-2.0.0.sbom.spdx.json
final-acceptance-receipt.json
PRIVATE-DISTRIBUTION-NOTICE.md
install-final.ps1
install-final.cmd
```

不要把本機 `UserData`、reports、logs、券商資料、LINE ID、tokens 或 credentials 上傳到 GitHub Issue、PR、Release 或公開位置。
