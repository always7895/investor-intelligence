# Investor Intelligence v2.1.3 R75 — Serenity Final

[English (Full Evidence)](README.md) ｜ [GitHub 最新正式發布](https://github.com/always7895/investor-intelligence/releases/latest) ｜ [方法論深度解析](docs/SERENITY_TIMELESS_SELECTION_METHODOLOGY.md) ｜ [期權推薦規格](docs/OPTIONS_RECOMMENDATION_SPEC.md)

**隱私優先、零付費公開市場研究與跨週期供應鏈情報系統。**
*非個人化投資建議、交易指令或保證回報；本系統提供基於客觀第一手數據的量化研究與決策輔助。*

---

## 🌟 新版本重大升級與功能亮點 (What's New in v2.1.3 R75 Final)

### 1. 跨週期物理約束層動態選股（Serenity 方法論落地）
* **打破死板板塊限制**：貫徹 Serenity（@aleabitoreddit）底層物理約束層思維，動態追獵涵蓋光電共封裝（CPO/雷射/InP基板）、先進封裝（CoWoS/SoIC）、成熟與高頻寬記憶體（HBM/利基DRAM）、現場發電與資料中心微電網、人形機器人精密物理致動零部件（行星滾柱絲槓/諧波減速機）等跨週期浪潮。
* **100% 實體合約能見度**：全量 20 檔標的 **100% 綁定第一方法定待履行訂單（SEC RPO / Backlog）或官方大型客戶多年商業協議**（如 TSEM 13 億美元合約/2.9 億預付款、COHR 與 NVIDIA 數十億美元協議、AXTI 數千萬預付定金協議），徹底告別「未揭露」空白。

### 2. 宏觀產業深度審查（最新報告全新進化）
* **不再重複個股清單**：個股細部 7 欄數據由 `TOP20` 圖文選單專責呈現；**「最新報告」全面聚焦於宏觀五大核心賽道深度產業評析**：
  1. 🤖 **AI 算力與超大規模叢集網路**（推論需求、功耗牆、四大雲端巨頭 CapEx 突破 3,500 億美元）
  2. ⚡ **光通訊、CPO 與矽光子**（800G/1.6T 放量、InP 基板與連續波 CW 雷射產能缺口 40-60%）
  3. 🔋 **AI 電力基礎設施與現場自備能源**（電網接入排隊 4-7 年、SOFC 燃料電池與 SMR 長約能見度）
  4. 📦 **先進封裝與高頻寬記憶體**（CoWoS 產能吃緊、HBM 包攬至 2027、成熟 DRAM 抽擠結構真空）
  5. 🦾 **人形機器人與精密物理致動**（2026-2027 試產、行星滾柱絲槓與空心杯電機磨削良率瓶頸）
* **前瞻資本支出（CapEx）與未來收入展望**：每一大產業均具備明確的「未來支出展望」與「未來收入能見度」量化研判。

### 3. 自由支援任意美股代號之選擇權觀測（無限制查詢）
* **不指定特定標的**：可自由輸入任意美股代號配合期權（如 `AAOI sell call`、`AXTI 每週期權`、`COHR 期權`、`AMD sell call`、`MU 每月期權`、`TSM 選擇權`）。
* **高精度限價與流動性計算**：自動精算履約價 K（價外 %）、即時 Bid/Ask/Mid 報價、**推薦限價區間（Limit Order Band）**、有效賣價、損益平衡點、隱含波動率（IV）、年化收益率（Mid % / Bid %）及流動性檢驗（PASS / 觀察）。
* **非標準期權標的客觀指引**：對掛牌於歐陸小微市場或台股等無美股標準化選擇權之標的（如 Sivers Semiconductors、晶豪科、IQE），系統自動精準解釋掛牌市場特性，建議以現貨配置為主，並推薦具備豐富流動性之同業替代標的。

### 4. 每日推播「一天一次・極致省額度」與動態不重複文案
* **極致省額度架構**：推播鎖定為**每日早盤 08:00（台北時間）單次發送**，晚間不再重複推播，**每月僅消耗 30 則推播配額（LINE 免費額度 200 則，節省 85% 額度，永不爆額度）**。
* **動態不重複引擎**：推播文案融合台北日曆、星期一至星期日專屬幽默點評、當日三大焦點領跑股、最強動能指標、以及每日輪替的實體合約照妖鏡，天天靈活不死板。
* **圖文選單 0 額度消耗**：好友與用戶透過 LINE 圖文選單點擊查看 Top20、大盤報告或查詢個股期權，全數走 LINE Reply API 免費通道，完全不扣推播額度！

### 5. 統一標準化 UI/UX 卡片排版
* 最新報告、期權限價觀測與 Top20 卡片全面套用統一精美 UI/UX 範本（鮮明 Emoji 標記、卡片式層級、清晰分隔線、限價單交易心法提示），徹底移除所有內部 HTML 註解標籤，手機端排版工整賞心悅目。

### 6. 本地模型動態探測解綁與 GPU 衝突雙軌守護
* **解除模型硬編碼**：本地模型橋接不再鎖死特定模型字串，可隨時熱插拔切換 Router 上的任何模型（Qwen 3.8、DeepSeek、Llama 3.3 等）。
* **雙軌無縫守護**：當本地顯卡正被其他專案重型運算佔用時，系統自動無縫切換至審核快照事實庫直接回答，確保 24 小時服務不中斷。

### 7. 審核體系擴充納入 Google 與全球權威數據
* 納入 **Google（Google Finance / Google Cloud / Alphabet CapEx 10-K 申報）**、美國證券交易委員會 (US SEC EDGAR)、Nasdaq 官方目錄、芝加哥期權交易所 (CBOE)、台灣公開資訊觀測站 (MOPS)、國際半導體產業協會 (SEMI)、TrendForce 集邦科技、歐洲央行 (ECB)、世界銀行 (World Bank) 與全球法人識別碼 (GLEIF)。

---

## 🚀 詳細安裝說明 (Installation Guide)

### 系統需求
* **作業系統**：Windows 10 / 11 (x64)
* **執行環境**：Python 3.10+（推薦 3.12 或 3.13）、Node.js 20+（推薦 LTS）
* **本地大模型（可選）**：`llama-server` / `llama.cpp`（推薦 Qwen 3.8 27B Q5，運行於 `http://127.0.0.1:8080`）
* **雲端與通訊帳號**：Cloudflare Workers（免費版即可）與 LINE 官方帳號（免費版即可）

### 極速單一壓縮包安裝步驟
1. 前往 [GitHub Releases](https://github.com/always7895/investor-intelligence/releases/latest)，下載最新單一發布壓縮檔案：
   * **`Investor-Intelligence-v2.1.3-R75-final.zip`**
2. 解壓至自選目錄（例如 `D:\Investor-Intelligence-LINE-Pi`）。
3. 以系統管理員身分開啟 PowerShell，執行安裝腳本：
   ```powershell
   Set-Location "D:\Investor-Intelligence-LINE-Pi"
   .\install-v213-source-diverse-runtime.ps1
   ```
4. （可選）若需配置 Cloudflare Worker 或更新依賴：
   ```powershell
   Set-Location "D:\Investor-Intelligence-LINE-Pi\cloud"
   npm ci --ignore-scripts --no-audit --no-fund
   ```
5. 完成後即可透過桌面捷徑 **Investor Intelligence R75** 啟動服務。

---

## 📱 詳細使用說明與指令大全 (Usage Guide)

### 一、 LINE 圖文選單三大核心功能
1. **【每日 TOP 20 榜單】**：點擊立即調出 20 檔核心標的完整雙語七欄卡片（含長期 2Y 年化、短期 6M 動能、公司現在訂單、未來展望與法定合約金額）。
2. **【大盤與最新報告】**：點擊立即輸出純繁體中文、五大核心賽道（AI 算力、光通訊、電力、先進封裝、機器人）之宏觀產業深度審查與 CapEx 收支展望。
3. **【個股與期權快查】**：點擊立即取得期權即時查詢指引。

### 二、 自然語言即時查詢範例（支援任意股票）
| 查詢需求 | 輸入範例 | 系統回覆重點 |
| :--- | :--- | :--- |
| **賣買權收租 (Covered Call)** | `AAOI sell call`<br>`COHR sell call`<br>`AMD sell call` | 價外 7-15% 履約價、即時 Bid/Ask/Mid、**推薦限價區間**、有效賣價、年化收益率、流動性 PASS |
| **每週期權鏈 (Weekly)** | `AXTI 每週期權`<br>`NVDA 每週期權`<br>`BE options` | 最新到期日（DTE）、買權與賣權雙向限價觀測、IV、Delta |
| **每月期權鏈 (Monthly)** | `MU 每月期權`<br>`TSM 選擇權`<br>`TSEM 期權` | 月選合約 Strike 分布、損益平衡點、推薦限價區間 |
| **個股物理瓶頸研析** | `SIVE`<br>`AXTI`<br>`3006.TW`<br>`COHR` | 第一手產能擴產、官方生產訂單、客戶預付款合約與稀釋風險提示 |
| **最新宏觀產業報告** | `最新報告`<br>`大盤報告`<br>`早報` | 五大賽道實體約束層評析、CSP 資本支出展望、未來收入能見度與核心風控原則 |
| **Top 20 完整文字版** | `TOP20`<br>`Top20 文字` | 20 檔公司依序分組之完整七欄文字，完整呈現合約細節 |

---

## 🛠️ 如果使用 Pi（Coding Agent）要安裝哪些外掛與配置？

如果您使用 [Pi 程式碼代理（Pi Coding Agent）](https://github.com/earendil-works/pi-coding-agent) 來協同維護、研發或擴充本系統，請遵循下列標準配置（遵守本專案 `AGENTS.md` 規範，**一律使用專案本地安裝 `pi install -l`，絕不進行全域安裝**）：

### 1. 安裝 Pi 命令列工具
```powershell
npm install -g @earendil-works/pi-coding-agent
```

### 2. 專案本地安裝必備外掛（Plugins & Packages）
進入專案根目錄，執行專案本地安裝指令：
```powershell
Set-Location "D:\Investor-Intelligence-LINE-Pi"

# 依序安裝本地模型橋接、聯網檢索、MCP 轉接器、UI 操作與核心代理 SDK
pi install -l npm:pi-llama-cpp npm:pi-web-access npm:pi-mcp-adapter npm:@injaneity/pi-computer-use npm:@earendil-works/pi-coding-agent@0.85.1 npm:pi-antigravity
```

#### 外掛功能說明：
* **`npm:pi-llama-cpp`**：連接本地 `llama-server` / Router（預設 `http://127.0.0.1:8080`），實現零外洩、零付費之本地大模型推理。
* **`npm:pi-web-access`**：提供多角度多來源公開資訊檢索與研報抓取工具。
* **`npm:pi-mcp-adapter`**：模型上下文協議（MCP）轉接器，支援工具批次鏈路調用。
* **`npm:@injaneity/pi-computer-use`**：桌面 UI 自動化與畫面元素檢驗工具。
* **`npm:@earendil-works/pi-coding-agent@0.85.1`**：Pi Agent 核心 SDK 與擴充運行環境。
* **`npm:pi-antigravity`**：安全身分驗證與繪圖工具支援。

### 3. 配置 `.pi/settings.json`
專案已預先配置 `.pi/settings.json`，核心設定如下：
```json
{
  "packages": [
    "npm:pi-llama-cpp",
    "npm:pi-web-access",
    "npm:pi-mcp-adapter",
    "npm:@injaneity/pi-computer-use",
    "npm:@earendil-works/pi-coding-agent@0.85.1",
    "npm:pi-antigravity"
  ],
  "llamaServerUrl": "http://127.0.0.1:8080",
  "defaultProvider": "llama.cpp",
  "defaultModel": "auto",
  "skills": [
    "skills/serenity-public-research"
  ],
  "enableSkillCommands": true,
  "defaultThinkingLevel": "xhigh",
  "defaultTools": [
    "read",
    "powershell",
    "bash",
    "edit",
    "write",
    "grep",
    "find",
    "ls"
  ]
}
```

### 4. 自動載入之專用技能（Skill）
* **`skills/serenity-public-research`**：內建《Serenity 公開研究方法論技能》，Pi 會自動依據 `SKILL.md` 規範執行跨週期價值鏈挖掘、物理約束層檢驗與第一手合約證據審查。

---

## 🛡️ 安全、隱私與架構防護界線

1. **嚴格隱私與 IBKR 實體隔離**：
   * 本系統為唯讀公開市場研究工具，**絕不連接券商下單 API、絕不讀取或儲存個人帳戶密碼、持倉或資金資訊**。
2. **Fail-Closed 審查守門機制**：
   * 若公開來源數據超過 24 小時（86,400 秒）未通過 Freshness Gate，系統自動拒絕輸出猜測數據，杜絕過期報價誤導。
3. **零成本運行架構**：
   * Cloudflare Workers Free Tier（每日 100,000 次請求免費）
   * LINE Official Account Free Tier（每月 200 則主動推播；圖文選單與互動對話全走免費 Reply API）
   * 本地 Llama-server / Qwen 27B（0 API Token 費用）

---

## 📄 開源許可 (License)

本專案依據 [MIT 許可證](LICENSE) 正式開源。歡迎全球投資人、開發者與研究者自由研讀、分叉、擴充與交流！
