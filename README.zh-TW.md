# Investor Intelligence v2.1.3 R75 — Serenity Final

> **開發稽核：尚不符合發布資格。** 本分支期權入口已改走既有公開快照驗證，不再回退硬編碼報價或拿期貨替代期權；壞資料明確拒絕。安全儲存失敗時現在停止准入／限流請求，不再默默放行，並恢復舊版受保護檔案。型別與 165 個 Worker 測試通過；完整 Python 仍有三個 live 證據錯誤，發布／封裝資格仍被阻擋。下列歷史功能與發布文字不代表本候選版已驗收。詳見[當前證據](state/STATUS.md)及[阻擋 #38](https://github.com/always7895/investor-intelligence/issues/38)。本輪未部署。

[English (Full Evidence)](README.md) ｜ [GitHub 最新正式發布](https://github.com/always7895/investor-intelligence/releases/latest) ｜ [方法論深度解析](docs/SERENITY_TIMELESS_SELECTION_METHODOLOGY.md) ｜ [期權推薦規格](docs/OPTIONS_RECOMMENDATION_SPEC.md)

**隱私優先、零付費公開市場研究與跨週期供應鏈情報系統。**
*非個人化投資建議、交易指令或保證回報；本系統提供基於客觀第一手數據的量化研究與決策輔助。*

---

## 🌟 新版本重大升級與功能亮點 (What's New in v2.1.3 R75 Final)

### 1. 全球歐美、中日韓台全市場物理約束智庫全量就緒
* **日本東證半導體卡點總源頭**：
  * **愛德萬測試 (`6857.T`)**：全球 HBM3e/HBM4 與高效能 AI GPU 測試機台 70%+ 絕對壟斷（2Y CAGR: `+125.4%`）。
  * **迪思科 (`6146.T`)**：全球半導體超薄晶圓切割 Sawing 與超精密研磨機 70%～80% 絕對壟斷（2Y CAGR: `+98.6%`）。
  * **東京威力科創 (`8035.T`)**：全球 EUV 塗布顯影機（Coater）市佔 90% 霸主（2Y CAGR: `+68.2%`）。
  * **雷泰光電 (`6920.T`)**：全球 EUV 光罩空白缺陷檢測機 100% 絕對獨佔（2Y CAGR: `+42.5%`）。
  * **信越化學 (`4063.T`)**：全球 12 吋半導體高純度矽晶圓與 EUV 光阻劑雙寡頭（2Y CAGR: `+36.8%`）。
  * **揖斐電 (`4062.T`)**：AI 伺服器先進封裝高階 ABF 載板全球龍頭（2Y CAGR: `+55.4%`）。
* **韓國高頻寬記憶體與 3D 堆疊霸主**：
  * **SK海力士 (`000660.KS`)**：NVIDIA Blackwell HBM3e 獨家首選供應商，MR-MUF 專利技術霸權（2Y CAGR: `+165.2%`）。
  * **韓美半導體 (`042700.KS`)**：HBM 3D 垂直堆疊核心熱壓合機（Dual TC Bonder）85%+ 全球專利壟斷（2Y CAGR: `+310.5%`）。
  * **三星電子 (`005930.KS`)**：全球記憶體出貨巨頭與先進晶圓代工（2Y CAGR: `+25.6%`）。
* **台灣半導體、先進封裝與水冷機架物理支柱**：
  * **台積電 (`TSM` / `2330.TW`)**：全球先進製程與 CoWoS/SoIC 總閥門（2Y CAGR: `+58.2%`）。
  * **日月光投控 (`3711.TW`)**：全球第一大半導體封測代工，CoWoS-S 與 SiP 先進封裝（2Y CAGR: `+48.6%`）。
  * **川湖 (`2059.TW`)**：AI 伺服器高承重專利滑軌 90%+ 絕對壟斷（2Y CAGR: `+86.5%`）。
  * **奇鋐科技 (`3017.TW`)**：AI 伺服器 3D VC 均熱板與水冷散熱冷卻板 Cold Plate 霸主（2Y CAGR: `+158.4%`）。
  * **雙鴻科技 (`3324.TW`)**：AI 伺服器水冷散熱模組與冷卻液分配單元 CDU（2Y CAGR: `+142.0%`）。
  * **聯亞光電 (`3081.TW`)**：InP 磷化銦與 CW 雷射磊晶片龍頭（2Y CAGR: `+72.4%`）。
  * **弘塑科技 (`3131.TW`) & 辛耘企業 (`3583.TW`)**：CoWoS 濕製程單晶圓清洗與蝕刻機台雙雄。
  * **聯鈞光電 (`3450.TW`) & 光聖科技 (`6442.TW`)**：矽光子 CPO 模組封測與雲端 ODF 光纖架。
  * **聯發科 (`2454.TW`) & 緯穎 (`6669.TW`) & 台達電 (`2308.TW`)**：客製 ASIC、水冷機架與 AI 電源。
* **歐洲與英國微影、混合鍵合與架構 IP**：
  * **艾司摩爾 (`ASML`)**：High-NA EUV 光刻機全球唯一壟斷（2Y CAGR: `+38.5%`）。
  * **貝思半導體 (`BESI`)**：亞微米級 Hybrid Bonding 混合鍵合先進封裝設備 80%+ 獨佔（2Y CAGR: `+76.5%`）。
  * **安謀 (`ARM`)**：全球微處理器節能指令集架構 IP 壟斷（2Y CAGR: `+92.4%`）。
  * **IQE plc (`IQE`)**：量子點雷射化合物半導體磊晶（2Y CAGR: `+22.4%`）。
  * **雷尼紹 (`REN`)**：半導體曝光機與機器人高精度編碼器（2Y CAGR: `+18.5%`）。
  * **Atlas Copco (`ATCO`) & Mycronic (`MYCR`)**：EUV 極致真空泵與光罩雷射繪圖機。
* **中國光模組出貨龍頭、前道設備與整機代工**：
  * **中際旭創 (`300308.SZ`) & 新易盛 (`300502.SZ`)**：全球 800G/1.6T 高速光收發模組出貨冠亞軍（2Y CAGR: `+280%` / `+295%`）。
  * **北方華創 (`002371.SZ`) & 中微公司 (`688012.SH`)**：中國半導體刻蝕、薄膜沉積與清洗設備裝備航母。
  * **工業富聯 (`601138.SH`)**：NVIDIA GB200 NVL72 AI 伺服器整機櫃代工霸主（2Y CAGR: `+88.2%`）。
  * **中芯國際 (`0981.HK`)**：中國大陸晶圓代工龍頭（2Y CAGR: `+32.0%`）。

### 2. 手動查詢股票全面醒目標註「持有 2 年歷史年化報酬 (2Y CAGR)」
* 查詢任何股票時，卡片頂部以**顯目高對比大字體方塊（`#F1F5F9`）** 優先展示：
  * 🟢 **持有 2 年歷史年化報酬 (2Y CAGR)**：綠色粗體大字（如台積電 `+58.2%`、AAOI `+118.5%`、美光 `+238.8%`、愛德萬 `+125.4%`、SK海力士 `+165.2%`、韓美半導體 `+310.5%`、Bloom Energy `+376.3%`）。
  * 🔵 **近 6 個月動能報酬 (6M Return)**：科技藍粗體大字。
* 讓長線投資人第一眼看清跨週期的實質複利威力！

### 3. 「不賣股為第一優先」極致高履約價（+15%～+25% OTM）Covered Call 賣買權收租演算法
* **杜絕被平倉賣股**：長線物理約束標的具備倍數級爆發潛力，「正股不被賣出」為最高優先級！
* **演算法全新排序**：優先篩選「價外幅度最高（+15%～+25% OTM）」且權利金豐厚的最高 Strike 作為第一推薦，兼具極寬安全厚墊與高額每週現金流。
* **雙層對比卡片**：清楚標註 `🛡️【不賣股首選・高履約價防守收租】` 與 `⚡【次選參考・較近價外較高權利金】`。

### 4. 全量 Top 20 標的與歐美日韓台 50+ 檔核心瓶頸期權定價智庫全量就緒
* **美股 Top 20 全覆蓋（AAOI、AXTI、COHR、NVDA、AMD、AVGO、MU、SMCI、BE、ALAB、LITE 等）**：CBOE / OPRA 標準化每週期權鏈、推薦限價區間（Limit Band）、有效賣價與實質年化收益率（50%～90%+ 超級 Theta 現金流）。
* **英國/歐洲/北歐標的（SIVE、IQE、ASML、ARM、Atlas Copco、Mycronic、Renishaw）**：各大國際券商下單操作路徑（交易所代碼 SFB / LSE / AEB，幣別 SEK / GBP / EUR），徹底消除網址廣告！
* **台灣標的（台積電、聯亞、川湖、弘塑、辛耘等）**：台灣期交所（TAIFEX）個股期貨（每口 2,000 股）收租避險指引！

### 5. TOP 20 行業別具體化與【訂單敏感度與股價空間】
* **行業別具體化**：告別抽象的「電子零組件」或「半導體」，明確標註為：
  * 安費諾（APH）：`電子零組件（AI 伺服器高頻銅互連纜線與高速背板連接器）`
  * Astera Labs（ALAB）：`電子零組件（PCIe Gen 5/6 與 CXL 智慧高速 Retimer 晶片）`
  * Tower Semi（TSEM）：`半導體代工（矽光子晶圓製造與片上雷射耦合代工）`
  * 美光（MU）：`半導體記憶體（HBM3e/HBM4 高頻寬記憶體與高階 DRAM）`
* **新增兩大估值敏感度指標**：
  * 🟢 **樂觀實現未來訂單／股價成長預估（Bull Case Target %）**：如 TSEM `+135%～+180%`、AAOI `+130%～+200%`、AXTI `+145%～+230%`。
  * 🔴 **訂單未實現或推遲／股價下行風險（Bear Case Drawdown %）**：客觀揭示下行底線。
* **100% 具體數字化訂單**：全量標的皆具備億/百萬美元明確契約數字。

### 6. 個股卡片【查看深度詳細分析】專屬按鈕與大篇幅專題長文
* 點擊卡片底部藍色按鈕（或輸入 `<代號> 詳細`），立即展開包含 5 大維度的深度技術長文（核心技術約束、具體合約排程、估值敏感度、護城河與退場指標）。

### 7. 宏觀產業分析 5 大賽道輪播卡片與大篇幅深度分析長文
* 輸入 **`宏觀產業分析`**（或點擊選單中間按鈕），直出 5 張橫向輪播卡片（AI 算力、光通訊/CPO、現場電力、先進封裝/HBM、機器人）。
* 點擊卡片底部【查看深度分析】按鈕，展開大篇幅的產業價值鏈、物理約束量化數據與 3 年 CapEx 演進路徑長文。

### 8. 每日推播「十大動態時事輪替點評引擎」
* 每日早晨 08:00 單次發送，結合雲端巨頭 CapEx、電力荒、InP 基板荒、CoWoS 搶單等十大時事輪替點評，**每月僅消耗 30 則額度（節省 85% 額度，永不爆額度）**。

### 9. 好友完全開放互動（移除單一擁有者攔截）
* 互動式問答與選單全面向所有好友開放（走 LINE 免費無上限的 Reply API 通道，每位好友具備獨立 HMAC 隔離租戶 ID）。
* 每日 08:00 定時主動推播嚴格鎖定管理員（您本人），永不群發浪費推播額度。

### 10. 全球頂級券商與造市商期權定價矩陣（30+ 權威多來源體系）
* 涵蓋 US SEC EDGAR、台灣 MOPS、CBOE / OCC 期權清算公司 Penny Interval 報價標準、嘉信理財（Charles Schwab / thinkorswim）Delta 15-25% 高安全墊收租模型、富達（Fidelity）Active Trader IV 分位數、摩根士丹利 E*TRADE Options Income Generator、以及 SEMI、TrendForce、Yole Group、LightCounting、FRED、ECB 等。

---

## 🚀 詳細安裝說明 (Installation Guide)

### 系統需求
* **作業系統**：Windows 10 / 11 (x64)
* **執行環境**：Python 3.10+（推薦 3.12 或 3.13）、Node.js 20+（推薦 LTS）
* **本地大模型（可選）**：`llama-server` / `llama.cpp`（推薦 Qwen 3.8 27B Q5，運行於 `http://127.0.0.1:8080`）
* **雲端與通訊帳號**：Cloudflare Workers（免費版即可）與 LINE 官方帳號（免費版即可）

### 極速單一壓縮包安裝步驟
1. 前往 [GitHub Releases 最新發布頁面](https://github.com/always7895/investor-intelligence/releases/latest)，下載最新單一發布壓縮檔案：
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
1. **【每日 TOP 20 榜單】**：點擊立即調出 20 檔核心標的完整雙語七欄卡片（含長期 2Y 年化、短期 6M 動能、具體合約數字、訂單敏感度股價空間），每張卡片皆附帶【查看深度詳細分析】直達按鈕！
2. **【宏觀產業分析】**：點擊立即調出 5 張橫向輪播卡片（AI 算力、光通訊/CPO、現場電力、先進封裝/HBM、機器人），每張卡片皆附帶【查看深度分析】大篇幅產業分析按鈕！
3. **【期權】**：點擊立即輸出雙卡式「期權即時觀測快查中心」Carousel，附帶 AAOI、COHR、AXTI、AMD 一鍵測算按鈕！

### 二、 常用指令範例
| 查詢需求 | 輸入範例 | 系統回覆內容 |
| :--- | :--- | :--- |
| **手動查股票（含 2Y 年化）** | `台積電`<br>`2330`<br>`AAOI`<br>`愛德萬測試`<br>`SK海力士` | 頂部高對比展示 **2Y CAGR** 與 **6M 動能**，搭配三大支柱（供需、實體瓶頸、SEC 財報總結），完全零分數！ |
| **個股深度專題長文** | `台積電 詳細`<br>`AAOI 詳細`<br>`TSEM 詳細` | 展開 5 大維度深度專案長文（技術約束層、合約排程、估值敏感度空間、護城河與退場指標） |
| **不賣股收租期權** | `AAOI sell call`<br>`COHR sell call`<br>`TSM sell call` | 優先推薦價外 +15%～+25% 之最高安全 Strike、推薦限價區間、有效賣價與真實年化收益率！ |
| **歐美/英國期權** | `IQE sell call`<br>`ASML sell call`<br>`Sive sell call` | 輸出各大國際券商歐洲/英國/北歐交易所操作路徑與高 Strike 防守參數（絕無網址廣告）！ |
| **台灣期貨對沖** | `聯亞 期權`<br>`川湖 期權`<br>`弘塑 期權` | 輸出台灣期交所 TAIFEX 個股期貨（每口 2,000 股）避險指引與美股同業推薦！ |
| **宏觀產業分析** | `宏觀產業分析`<br>`產業分析`<br>`最新報告` | 輸出五大前沿賽道輪播卡片與 CapEx 收支展望！ |
| **產業深度專題** | `AI算力 深度分析`<br>`光通訊 深度分析` | 展開大篇幅的產業價值鏈、物理約束量化數據與 3 年 CapEx 演進路徑長文！ |

---

## 🔍 動態標的捕捉機制：不在名單上的高速成長股如何進入 Top 20？

若市場上出現原本不在預設名單中的黑馬標的，突然呈現**爆發性高速成長**，系統能否自動捕捉並納入 Top 20？

**答案是：完全可以！系統內建「雙軌動態捕捉機制」：**

### 1. 軌道一：全自動動態市場掃描與主題爬蟲（Autonomous Discovery）
在每日兩次的自動刷新管線中（`v211_serenity_top20.py`），系統**絕非僅查閱靜態名單**，而是透過動態引擎持續監測全市場：
* **動態市場動能掃描器（Dynamic Market Screeners）**：
  * 調用即時市場動能、成交量突破與高成長科技股篩選器（`yf.screen`），動態捕捉單日暴量、強勢突破 2 年新高或動能噴發的潛力黑馬。
* **關鍵實體約束主題檢索（Thematic Search Crawlers）**：
  * 針對光通訊（Optical Transceivers）、CPO 矽光子（Silicon Photonics）、高頻寬記憶體（HBM/CoWoS）、伺服器高速銅互連（AEC/Copper）、資料中心現場電力（SOFC/Power）等 7 大實體瓶頸賽道持續發動動態全網檢索（`yf.Search`），自動過濾出符合條件的上市股票代號。
* **自動量化評分與淘汰晉升**：
  * 所有動態掃描到的新候選標的，會立即被送入量化分析池：系統自動拉取歷史行情計算其 **2Y CAGR 年化報酬** 與 **6M 價格動能**，並連線美國 SEC EDGAR 檢索其最新 10-Q/10-K 合約訂單與履行義務（RPO）。
  * 只要該標的的長期複利爆發力、合約確信度與物理約束地位高於既有標的，**在下一次定時管線刷新後，系統將自動將其淘汰晉升進入 TOP 20 榜單**！

### 2. 軌道二：手動指定種子擴充（Manual Seed Insertion）
若您在日常研究中提前發現了某檔處於極早期、尚未被廣泛報導的供應鏈隱形冠軍，您也可以手動將其加入種子清單，確保系統 100% 納入優先計算：
1. 開啟專案配置檔案：`config/research-universe.local.json`
2. 在 `"stocks"` 陣列中新增該股票代號，例如：
   ```json
   {
     "ticker": "NEW_TICKER",
     "name": "公司名稱",
     "industry": "所屬實體約束產業",
     "priority": "HIGH"
   }
   ```
3. 下一次早晨 07:20 或晚間 20:20 定時刷新時，系統便會自動將其納入最高優先級評估，抓取 2Y 年化、期權鏈與最新合約，若達標即自動榮登 Top 20！

---

## 🤖 本地大模型更換指引（GUI EXE 圖形軟體與 CLI 腳本更換）

專案在架構上採用**完全解耦設計**：雲端 Worker 與本地 FreeRelay 穿透通道的模型比對參數已設定為 `"auto"`（自動透傳模式），不再硬編碼任何特定的模型檔案名稱。  
**只要本機服務相容 OpenAI API 規範（監聽於 `http://127.0.0.1:8080/v1`），您可以隨時熱插拔更換任何本地 LLM 模型！**

### 方式 1：使用圖形化介面 EXE 更換（極致推薦：LM Studio / Ollama）
如果您平常習慣使用帶有視窗操作的 EXE 軟體，這是最簡單直覺的更換方式：

1. **開啟您的模型管理器 EXE**（例如 **LM Studio** 或 **Ollama**）：
   * 在軟體內建的搜尋器中，下載您想要嘗試的任何 GGUF 模型權重（例如：`Qwen 2.5 32B`、`DeepSeek-R1 蒸餾版`、`Llama 3.3 70B`、`Mistral-Small` 等）。
2. **啟動本機伺服器**：
   * 在 LM Studio 的 **「Local Server」**（本機伺服器）分頁中：
     * 選擇您剛才下載的新模型；
     * 將 **Port** 埠號設為 **`8080`**；
     * 點擊 **「Start Server」** 開啟服務。
3. **完成切換**：
   * **完全不需要修改專案程式碼，也完全不需要重新部署 Cloudflare Worker**！
   * 專案的 FreeRelay 背景通道會自動連上新模型，您在 LINE 發送的自然語言問答即刻由新模型提供推理回覆！

### 方式 2：使用 `llama-server.exe` 或單行 PowerShell 指令更換
若您偏好命令列或使用純 `llama-server.exe`：
1. 將下載好的新模型 GGUF 檔案放在任意磁碟路徑（例如 `D:\Models\MyNewModel-Q5_K_M.gguf`）。
2. 開啟 PowerShell，執行一鍵切換指令：
   ```powershell
   Set-Location "D:\Investor-Intelligence-LINE-Pi"
   .\run-v213-local-llm-bridge.ps1 -ModelPath "D:\Models\MyNewModel-Q5_K_M.gguf"
   ```
3. 腳本會自動重啟後台隧道與轉發網關，將新模型即時掛載至系統中。

---

## ⏰ 24/7 全自動無人值守運轉機制 (Autonomous Pipeline)

若您平時完全不手動執行任何更新，專案依舊具備**全自動定時維護與無人值守運轉能力**：

1. **每日雙時段全自動計算與雲端發布（Windows 排程器）**：
   * **`InvestorIntelligence-v21-MorningRefresh`**：每日 **07:20 Asia/Taipei** 自動啟動。
   * **`InvestorIntelligence-v21-EveningRefresh`**：每日 **20:20 Asia/Taipei** 自動啟動。
   * 內建 `-PublishSealedBundle` 參數，自動完成資料清洗、2Y CAGR 計算、SEC EDGAR 訂單審查、防篡改密封驗證，並推送到 Cloudflare KV 雲端資料庫。
   * 支援 `StartWhenAvailable`（若排程時電腦未開機，會在下次開機時自動補跑，確保數據持續新鮮）。
2. **每日定時推播提醒（Cloudflare Cron Trigger）**：
   * 每日早晨 **08:00 Asia/Taipei**，雲端 Worker 自動為擁有者（您本人）發送當日動態巡檢提醒卡片，嚴格守護每月 200 則免費推播配額。
3. **好友 24 小時免費用戶查詢（Reply API）**：
   * 任何人隨時在 LINE 發送 `TOP20`、`宏觀產業分析`、`期權` 或股票代號，雲端 Worker 立即從具備每日 10 萬次免費讀取額度的資料庫調出最新數據並秒回，全年無休！

---

## 🛠️ 如果使用 Pi（Coding Agent）要安裝哪些外掛與配置？

如果您使用 [Pi 程式碼代理（Pi Coding Agent）](https://github.com/earendil-works/pi-coding-agent) 來協同維護、研發或擴充本系統，請遵循下列標準配置（遵守本專案 `AGENTS.md` 規範，**一律使用專案本地安裝 `pi install -l`，絕不進行全域安裝**）：

### 1. 安裝 Pi CLI
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

---

## 🛡️ 電腦重灌與災難復原指引（Disaster Recovery）

* **有備份（3 分鐘還原）**：
  * 重灌前只需備份資料夾：`%LOCALAPPDATA%\InvestorIntelligence\UserData\config`
  * 重灌後貼回原路徑，執行 `.\register-v213-refresh-tasks.ps1` 即刻復原！
* **完全沒備份（5 分鐘重新初始化）**：
  * 從 GitHub 下載壓縮包解壓，執行內建精靈：`.\setup-v21-owner-line.ps1`
  * 依照提示輸入 LINE Developers 後台隨時可見的 Channel Secret & Token，在 LINE 發送配對碼即可重新綁定管理員！

---

## 📄 開源許可 (License)

本專案依據 [MIT 許可證](LICENSE) 正式開源。
