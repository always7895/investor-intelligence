# Macro Industry & Options Products Architecture (v2.1.3) — Review Revision 2

## 1. 概述 / Overview

本文件規範 **宏觀產業分析 (12–36M)** 與 **期權與個股快查** 兩項公開研究產品之工程架構、公開文獻依據、數值驗證門檻與封存整合邊界。

本功能經 Astra Review 2 嚴格財務安全審查修復，依循嚴格之工程邊界：
- **宏觀產業實質入口**：已正式綁定 `RICH_MENU_ACTIONS` 實體按鈕指令 `宏觀產業分析`。主首頁絕不以候選公司家數占比冒充 TOP5 宏觀產業分析。當當輪合格產業未達 5 個時，主首頁明確通報短缺（`MACRO_TOP5_SHORTFALL`，5/5 短缺），並標示 `NOT_PUBLICATION_QUALIFIED`。未准入候選產業標記 `rank: null`，嚴禁將模型原始機會分數直接排定為正式合格名次。
- **期權實質入口**：已正式綁定 `RICH_MENU_ACTIONS` 實體按鈕指令 `期權`。直接呈現整合雙邊報價查詢與 4 種標準期權教學範例卡片（Covered Call、Cash-Secured Put、Bull Call Spread、Protective Put）之輪播／文字介面。
- **裸報價與損益指標分離（Finding A）**：單合約裸報價（OptionContractQuote）未綁定具體策略、部位股數與持倉成本，**嚴格禁止調用端傳入非 null 之損益指標**（`breakeven`、`maxprofit`、`maxloss`、`annualized_yield` 必須為 null，傳入非空數值直接拋出 `BARE_QUOTE_STRATEGY_METRICS_PROHIBITED` 拒絕）。所有損益與回報率僅限於包含明確假設（合約乘數 100、現股成本、保證金、摩擦成本）之獨立教學策略卡片中呈現。
- **新鮮度與日曆一致性政策（Finding B）**：依循既有 public options policy 與 closed DTO 閘門，淘汰任意 7 天寬鬆期限。合約即時報價上限 86,400 秒（24 小時），盤後報價上限 345,600 秒（4 天，覆蓋週末假日）。合約到期日嚴格比對評估時鐘（evaluatedAt）之日曆天數，拒絕已過期合約（`EXPIRED_CONTRACT_REJECTED`）與 DTE 不一致（`EXPIRY_DTE_INCONSISTENT`），嚴禁將過期合約靜默截斷為 0 天。延遲與盤後報價明確標註「【非即時可執行報價 · 僅供參考】」，絕不暗示為可執行委託價格。
- **出處憑證與合約屬性綁定（Finding C）**：報價必須具備非空 `source`、非空 `provenance`、貨幣 `USD`、合約乘數 `100`、及已審查之 `rights_status`（如 `reviewed_public_access`）。未通過審查之來源維持 `NOT_ADMITTED`，實際調用路徑維持 fail-closed UNAVAILABLE。
- **宏觀成長率出處溯源（Finding D）**：宏觀成長率必須包含已認證之 `source_id`、單位、期間、發布者、日期與實質引文／URL。拒絕未來日期，拒絕無出處溯源之任意段落。未准入候選產業維持 `growth: null`，`rank: null`，不湊數捏造 TOP5。
- **教學策略數學驗證與 LINE 限制（Finding E）**：四大教學卡片皆具備結構化 `payoff_reference` 數值參考與嚴格算術驗證。Carousel 嚴格遵循 `assertLineMessages` 限制（每容器 <= 5 個 bubble，最多 5 個訊息，字數 <= 4900 字元）。超過 5 個候選產業時，總覽呈現排名前 5 名卡片並完整揭露候選池規模與短缺報告，不遺失揭露內容。

---

## 2. 公開參考文獻與檢索憑證 / Public Reference Receipts

依據單次公開檢索（`macro-options-public-references-v1/receipts.json`）之客觀結果：

1. **WSTS (World Semiconductor Trade Statistics)**
   - 文獻：*Global Semiconductor Market Surges Beyond $1.5T 2026* (Spring 2026 Forecast)
   - source_id：`wsts-outlook`
   - URL：`https://www.wsts.org/76/Recent-News-Release`
   - 狀態：HTTP 200，`RETRIEVED_NOT_ADMITTED`（先導線索，非直接准入 5 產業報告）。
   - 數據：2026 年半導體市場預估年增 90% 至 1.51 兆美元；記憶體（Memory）領域預估年增 250% 至 8,000 億美元。

2. **IFR (International Federation of Robotics)**
   - 文獻：*The Impact of Robots: Employment, Productivity and Competitiveness* (2026-08-11)
   - source_id：`ifr-robotics`
   - URL：`https://ifr.org/ifr-press-releases/news/world-robotics-2025`
   - 狀態：HTTP 200，`RETRIEVED_NOT_ADMITTED`。僅質化論述，缺乏單一可驗證之 12–36M 全球市場複合成長率數值，成長率標示 `UNAVAILABLE`，不可准入。

3. **IEA (International Energy Agency)**
   - source_id：`iea-ai-demand`、`iea-electricity`
   - URL：`https://www.iea.org/reports/energy-and-ai/energy-demand-from-ai` 及 `electricity-2026`
   - 狀態：HTTP 403 `UNAVAILABLE`。保留原始 403 失敗狀態，絕不捏造能源成長率。

4. **OIC (Options Industry Council)**
   - 文獻：Covered Call (`oic-covered-call`), Cash-Secured Put (`oic-cash-secured-put`), Bull Call Spread (`oic-bull-call-spread`) 教學規範
   - URL：`https://www.optionseducation.org/strategies/all-strategies/...`
   - 狀態：HTTP 200，`RETRIEVED_NOT_ADMITTED`。
   - Protective Put (`oic-protective-put`)：檢索 URL 回傳 HTTP 404 `UNAVAILABLE`，保留原始 404 紀錄。合成教學卡片依據 OCC 標準期權結算手冊架構算術模型。

---

## 3. 宏觀產業評選與 10 維深度展開 / Macro Industry Evaluation

### 3.1 准入門檻與短缺通報 (Shortfall Reporting)
- **成長率驗證**：必須具備數值 (`rate_pct`)、單位 (`% YoY` / `% CAGR`)、格式化期間 (`YYYY` / `YYYY-YYYY` / `YYYY Q1-Q4`)、發布者 (`publisher`)、日曆日期 (`YYYY-MM` / `YYYY-MM-DD`)、已認證來源代號 (`source_id`) 及來源憑證 (有效 URL 或 >=10 字元實質引文字句)。
- **反偽冒限制**：候選公司家數占比絕不得冒充市場成長率。
- **短缺處理**：合格產業候選少於 5 個時，系統強制回傳短缺報告，短缺數 `shortfall = 5 - qualified_count`，狀態為 `SHORTFALL_NOT_QUALIFIED`，標記 `NOT_PUBLICATION_QUALIFIED`。未合格候選產業之 `rank` 設為 `null`，不捏造排名。

### 3.2 機會分數（Opportunity Score）
為 0–100 之量化工程指標（System Operationalization），明確聲明**非投資勝率或機率**：
- 需求能見度 (0–25)
- 瓶頸緊繃度 (0–25)
- 定價權與毛利防禦 (0–20)
- 價值鏈捕獲 (0–15)
- 催化時程與風險平衡 (0–15)

### 3.3 深度化分析（10 維因果鏈展開）
深度路由指令 `宏觀產業 深度化分析 [ID]` 不重複卡片文字，依序展開 10 維因果鏈：
1. 需求傳導 (Demand)
2. 供給現況 (Supply)
3. 核心瓶頸 (Bottleneck)
4. 定價機制 (Pricing)
5. 資本支出 (Capex)
6. 競爭格局 (Competition)
7. 關鍵受益廠商 (Beneficiaries)
8. 催化時程 (Catalysts: 6M / 1Y / 2Y)
9. 產業風險 (Risks)
10. 邏輯證偽點 (Thesis Killers)

---

## 4. 期權報價與四大教學策略卡片 / Options Quotes & Educational Strategies

### 4.1 裸合約報價驗證門檻
- Bid >= 0, Ask >= Bid, Mid = (Bid + Ask) / 2。
- 拒絕 Crossed quotes（Bid > Ask）、負值與不合理時間戳記。
- 拒絕調用端提供之損益指標（`breakeven`、`maxprofit`、`maxloss`、`annualized_yield` 必須為 null）。
- 幣別嚴格綁定 `USD`，合約乘數嚴格綁定 `100`。
- 到期日與 DTE 必須與評估時鐘具備日曆一致性；拒絕已過期合約。
- 缺少 Greeks 或成交量時維持 `UNAVAILABLE` / `null`，不捏造為 0。
- 當封存快照未包含期權物件時，回傳 `OPTION_DATA_UNAVAILABLE`，絕不以 Black-Scholes 估算充當市場報價。

### 4.2 四大教學策略卡片（Educational Strategy Cards）
所有教學卡片皆具備結構化 `payoff_reference`，標註 `教學範例，非推薦` 與 `SYNTHETIC_EDUCATIONAL`：
1. **Covered Call（掩護性買權）**：成本 $100，賣 $105 Call 收 $3 -> 損益平衡 $97.00，最大利潤 $8.00 ($800.00)，最大損失 $97.00 ($9,700.00)。以 100 股現股作為完全掩護。
2. **Cash-Secured Put（現金擔保賣權）**：賣 $90 Put 收 $2.50 -> 損益平衡 $87.50，最大利潤 $2.50 ($250.00)，最大損失 $87.50 ($8,750.00)。要求 100% 全額現金擔保 $9,000.00。
3. **Bull Call Spread（買權多頭價差）**：買 $100 Call 付 $4，賣 $110 Call 收 $1.50 -> 淨支出 $2.50 ($250.00)，損益平衡 $102.50，最大利潤 $7.50 ($750.00)，最大損失 $2.50 ($250.00)。揭露 Legging Risk 與提前指派風險。
4. **Protective Put（保護性賣權）**：成本 $100，買 $95 Put 付 $3 -> 損益平衡 $103.00，最大損失 $8.00 ($800.00)，**最大獲利 UNBOUNDED（理論無限）**。揭露長期保費時間耗損（Premium Drag）。

---

## 5. 已知阻礙點與未解決邊界 / Known Blockers & Project Boundaries

本工程切片嚴格區分「可用教學範例／預設 UI 通過」與「真實宏觀／期權資料延後准入」：
1. **真實資料短缺阻礙 (Real-data Shortfall: DEFERRED)**：IEA 403 與 IFR 無公認成長率，真實合格產業未滿 5 個，TOP5 正式發布維持短缺阻礙狀態（DEFER）。
2. **真實期權報價准入阻礙 (Real Options Quote: DEFERRED)**：免費公開期權提供者尚未通過審查，封存快照契約 SNAPSHOT_OBJECT_KEYS 不含期權鍵，生產調用維持 fail-closed UNAVAILABLE（DEFER）。
3. **教學範例與介面合約 (Educational & Default UI: PASS)**：四大教學策略卡片、結構化損益驗證、短缺通報、LINE Carousel 限制完全合格通過（PASS）。
4. **封存契約邊界 (Seal Migration Blocker)**：現行生產快照契約 `v213-stored-snapshot-v1` 不含宏觀與期權物件；升級封存契約需獨立版本遷移審查。
5. **歷史報酬與排序缺口 (Ranking & 2Y Total Return Gap)**：2Y CAGR 歷史報酬與排序機制之歷史遺留缺口仍列為專案整體阻礙點。
6. **生產環境零更動**：本 Slice 嚴格限定於原始碼與本地驗證，無生產部署、無 KV 寫入、無真實 LINE 推播、無憑證變更。
