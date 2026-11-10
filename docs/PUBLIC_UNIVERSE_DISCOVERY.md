# Independent Public Universe Identity Discovery / 獨立公開市場清單發現規範

## 1. Scope and Identity Role / 範疇與識別定位

本模組（`scripts/public_universe_discovery.py`）提供獨立、離線的公開市場掛牌證券與發行機構識別發現機制，嚴格遵守下列邊界：

- **僅限線索識別（Lead Identity Evidence Only）：** 官方交易所掛牌清單僅證明該證券/發行人在特定市場之掛牌代碼與法定名稱，**絕非**市場成長、瓶頸定價權、商業模式、營收捕捉、財務真實性或排名的證明。發現候選數量（7,016 檔候選股、8,599 檔不重複證券）反映官方清單之登錄行數，**絕非**產業成長或資本擴張指標。
- **無任何公司錄取（Zero Admission）：** 輸出狀態為 `DISCOVERY_ONLY`、`NOT_PUBLICATION_QUALIFIED`，`score=null`、`rank=null`、`admitted_company_count=0`。掛牌識別必須經由後續公司資料收集器（Company Collector）與實質產業/供應鏈圖譜研究（Graph Research）驗證，絕不因掛牌或JSON雜湊而自動晉升為受審公司或發布標的。
- **不依賴前置名單與特定題材：** 完全獨立於歷史 TOP20、Serenity 意見貼文或任何永久性 AI 題材過濾器，涵蓋所有合法掛牌產業（包含傳統製造、原物料、基礎設施、公用事業等），維持題材中立。

## 2. Partial Coverage Boundary and Venue State / 部分覆蓋邊界與交易所狀態

本系統嚴格區分「程式碼配置交易所（Configured Venues）」與「實際觀察有效交易所（Observed Active Venues）」，絕不因程式碼映射表存在即聲稱交易所已被覆蓋：

- **程式碼配置交易所（Configured Supported Venues）：**
  - NASDAQ, NYSE, NYSE American, NYSE Arca, Cboe BZX, IEX, TWSE。
- **實際觀察有效覆蓋交易所（Observed Active Venues / Covered Venues）：**
  - 美國：NASDAQ（4,330 筆）、NYSE（2,845 筆）、NYSE American（309 筆）、NYSE Arca（17 筆）、Cboe BZX（4 筆）。
  - 臺灣：TWSE（1,094 筆上市公司）。
- **觀察覆蓋缺口（Observed Coverage Gaps）：**
  - **IEX：** 雖然在代碼映射表中配置，但當前來源資料中實際觀察筆數為 0，嚴格標記為 `ZERO_OBSERVED_RECORDS_IN_FEED` 覆蓋缺口，**嚴禁**列入 `covered_venues`。
- **嚴禁稱為全市場覆蓋（Strict Partial Coverage Boundary）：** 美國與臺灣局部資料**絕對不得**聲稱為全球或全市場覆蓋。來源失敗、部分失敗或缺漏絕不可包裝為技術覆蓋通過。
- **明確列舉未涵蓋市場與資產類別（Explicitly Uncovered Regions & Assets）：**
  1. 歐洲主要交易所：LSE（倫敦）、Euronext（泛歐交易所）、XETRA（德意志交易所）、SIX（瑞士交易所）等。
  2. 日本：JPX / 東京證券交易所（TSE）。
  3. 香港：香港交易所（HKEX）。
  4. 韓國：韓國交易所（KRX）。
  5. 加拿大：多倫多證券交易所（TSX / TSXV）。
  6. 中國大陸：上海證券交易所（SSE）、深圳證券交易所（SZSE）。
  7. 美國場外交易市場：OTC Markets / Pink Sheets。
  8. 臺灣證券櫃檯買賣中心：TPEx（上櫃股票）及興櫃市場。
  9. 固定收益與債券市場（Global Fixed Income & Bonds）。
  10. 大宗商品與衍生品市場（Commodities & Derivatives）。
  11. 未上市企業與私募股權（Private Equity & Unlisted Companies）。

## 3. Strict Parser, Classification, and Lineage Rules / 嚴格解析、分類與血統規則

1. **原樣保存與非強制型別轉換（Strict Preservation & No Coercion）：**
   - 保留原始交易所代碼、符號、安全類別、法定名稱、來源與時間。
   - TWSE 股票代碼嚴格保留前導零（例如 `"0050"`, `"01001T"`），一律視為字串處理，嚴禁轉型為整數。
   - 官方中文名稱（例如 `"臺灣水泥股份有限公司"`、`"台泥"`）原樣保存為發現標籤，嚴禁未經驗證的機器翻譯或冒然登錄為卡片名稱。
   - 符號中的點與連字號（例如 `"BRK.A"`, `"BF.B"`）完整保留，嚴禁剝離。
   - 嚴禁布林值/字串強制轉換：ETF 與 Test Issue 標記必須為嚴格字串 `'Y'` 或 `'N'`，非字串或布林值一律視為結構違規（Schema Violation）。
2. **排除規則（Documented Exclusions）：**
   - `Test Issue == 'Y'`：標記為 `EXCLUDED`，原因 `TEST_ISSUE`（共 38 筆）。
   - `ETF == 'Y'`（或名稱明確載明 ETF/指數股票型）：標記為 `EXCLUDED`，原因 `EXCHANGE_TRADED_FUND`（共 5,677 筆）。
3. **待審查類別（Review Required Flags）：**
   - 特別股（Preferred Stock / Pfd / 特殊系列）、認股權證（Warrants / Wts）、單位（Units / U）、認股權（Rights）、基金與公司債（Funds / Notes / Debentures）一律標記為 `REVIEW_REQUIRED`，**絕對不默認**歸類為普通股（Common Equity）。
   - 未知之交易所代碼或市場類別代碼一律列入待審查覆蓋缺口（Coverage Gap）。
4. **衝突重複隔離與嚴禁第一筆勝出（Conflicting Duplicate Quarantine, No First-Wins）：**
   - 僅依據穩定的 `(venue, symbol)` 二元組進行去重。
   - 若兩筆紀錄具有完全相同的名稱、分類與狀態，視為確定重複（Exact Duplicate）並去重。
   - 若同一 `(venue, symbol)` 出現名稱、分類或狀態衝突，**嚴禁採第一筆勝出（First-Wins）**，亦絕不依來源優先順序覆蓋或提升權重；必須立即隔離並標記為 `REVIEW_REQUIRED`（原因 `CONFLICTING_DUPLICATE_IDENTITY`），完整保留衝突紀錄之欄位與來源雜湊，絕不作為不透明事件吞吐。
5. **未驗證名稱相似群組非權威發行機構血統（Unverified Name Leads, Not Authoritative Lineage）：**
   - 從證券名稱前綴擷取之 `issuer_name_lead` 僅為啟發式名稱相似群組（Unverified Name-Similarity Leads），**絕非**權威發行機構識別或血統。
   - 真實發行機構關聯必須仰賴權威機構識別碼（CIK, LEI, ISIN）及其官方揭露關係，當前公開掛牌清單完全欠缺此等欄位（`authoritative_lineage_available=false`）。
   - 發現報告中的 573 組多證券名稱群組僅為「未驗證名稱相似群組」，**嚴禁**宣稱為 573 家已驗證獨立發行公司，亦不得據此合併實體身份或聲稱獨立佐證來源。原始交易所與代碼識別完全保留，不同股權類別與 ADR 絕不合併。
6. **非報價聲明（Not Market Quotes）：**
   - 掛牌清單不包含市場報價，嚴禁據此推論價格、報酬率、成交量或市值。候選分類絕不影響價格推論或定價權評估。

## 4. Provenance, Privacy, and Security Guards / 來源、隱私與安全性防護

- **雜湊收據與證明範疇界定（SHA256 Receipts & Proof Scopes）：**
  - 執行前必須驗證收集目錄內 `receipts.json` 與所有投射檔案的 SHA256 雜湊值。
  - **證明範疇界定：** 本地 SHA256 雜湊檢查**僅能證明**檔案自收據生成至本次執行期間未遭篡改（Tamper-detection only）；**絕對無法證明**未受信任的收據確實來自官方擷取，亦**不代表獲得再發布或授權權利**。
- **時鐘嚴格分離（Distinct Clocks）：**
  - `sourcePublishedAt`：原始資料發布時間（公開清單常無精確簽署發布戳記，標示為 `UNVERIFIED`，資料時效維持 `UNKNOWN`）。
  - `retrievedUtc`：核准之固定擷取指令取得時間。
  - `generated_at_utc`：本次發現與覆蓋分析之執行時間。
  - 擷取時間（Retrieval）**不等於**發布時間（Publication/As-of），嚴禁將擷取時間倒填為發布時間。
- **網址防偽與拒絕憑證網址（Fail-Closed Official URLs & Privacy）：**
  - 來源收據網址必須嚴格比對預期之固定官方網址清單（`EXPECTED_OFFICIAL_URLS`），來源不符即拒絕。
  - 嚴格拒絕內嵌帳密憑證之網址（`http(s)://user:pass@...`）。
  - CLI 完全離線執行，禁止任何對外網路連線或重導向。
- **隱私序列化保護（Sanitized Error Serialization）：**
  - 錯誤日誌與報告中僅允許序列化標準錯誤型別與代碼（如 `JSONDecodeError`, `JSON_DECODE_FAILURE`），嚴禁輸出原始例外字串（Raw Exception Strings）或可能包含敏感路徑與帳密的輸入片段。
  - 嚴禁洩漏任何私有鍵值（如 `tenant_id`, `line_user_id`, `cost_basis` 等）。
- **實體安全性與路徑界限（Security Guards & Path Bounds）：**
  - 拒絕目錄遍歷（Path Traversal）、符號連結（Symlinks）、Windows 目錄接合點（Junctions）及重分析點（Reparse Points），並遞迴檢查所有上層祖先路徑。
  - 限制單一專屬收集目錄，檔案數量上限鎖定（<= 10），禁止遞迴遍歷工作區。
  - 讀取前強制驗證常規檔案（Regular File）屬性與位元組上限（50 MB）及紀錄上限，防範拒絕服務攻擊。
  - 收據中之動態來源路徑值嚴格鎖定於白名單基準名稱（`ALLOWLISTED_BASENAMES`），禁止逃逸收集目錄。
  - 輸出報告採互斥寫入（Create Exclusive, `'x'` 模式），禁止覆寫現有證據。

## 5. Technical Pass vs. Business Qualification / 技術解析與業務資格分離

- **技術通過（Parser PASS）：** 僅代表輸入資料格式合規、雜湊一致、去重與分類邏輯無誤。來源失敗、部分失敗或未連線絕不可視為技術覆蓋通過。
- **業務未合格（Business Research Unqualified）：** 掛牌清單通過解析**不等於**已完成研究。所有產出均為候選發現庫存（Candidate Inventory），必須維持 `admitted_company_count=0`，絕不具備 LINE 產出或發布資格。
