# v2.1.3 Serenity 公開邏輯高保真重建與多來源標準

## 定位與非主張

Investor Intelligence 不宣稱取得或重製 Serenity 的私人方法、私人流程、官方公式或官方分數。系統的 `serenity_score` 等歷史 machine key 只為相容性保留，顯示與推論時一律稱為「系統量化／System operationalization」。

本階段的正確定位是：**Serenity 公開邏輯高保真重建**。只有具日期、可識別、可回溯的 Serenity 公開內容，才能形成「Serenity source view」；沒有來源時必須標為 `NOT_ATTACHED`，不能以模型常識代填。

## 邏輯層與狀態機

分析必須分開呈現：

1. 公開來源觀點與日期。
2. 架構／需求浪潮。
3. 有證據綁定的供應鏈依賴圖。
4. 瓶頸或擴產狀態。
5. 公司價值捕捉與選擇權。
6. 估值已反映的預期。
7. 反證與 thesis killers。
8. thesis 生命週期與公司特定時間。
9. 系統量化覆蓋層。
10. 模型推論及不確定性。
11. 使用者長期偏好覆蓋層。

狀態只能沿著證據推進：`UNPROVEN → EVIDENCE_FORMING → COMMERCIAL_VALIDATION → INSTITUTIONAL_VALIDATION`；若證據惡化則進入 `THESIS_IMPAIRED` 或 `THESIS_BROKEN`。商業事件本身不能讓一個仍未證實的 thesis 跳級。

## 不得使用的捷徑

下列資訊單獨存在時，不能證明 bottleneck／chokepoint：關鍵字、產業標籤、營收成長、高毛利率、高 beta、高放空比、知名客戶、熱門 AI 題材。

瓶頸至少需要：

- 可驗證的 dependency-graph edge；
- 供應集中、認證摩擦、受限產能或難以替代的製程／IP 證據；
- 直接 primary evidence；
- 至少一個獨立來源家族的交叉佐證。

公司 capture 另外檢查合格產能／市占、價格與合約、融資耐久度、BOM／產品組合、垂直整合、客戶集中、執行與資本支出，以及架構繞過風險。

## 多來源獨立性

來源數量不等於來源獨立性。以下情況只計一次：

- 同一篇內容被多站轉載；
- 同一 registrable domain 的重複頁面；
- 同一公司集團或同一資料供應商的不同 API／頁面；
- 同一原始新聞稿的改寫或摘要。

社群貼文只能證明作者說過什麼，不能單獨證明公司基本面。單一 SEC／監管或公司正式揭露可證明其狹義揭露事實；從該事實延伸到供應鏈、瓶頸、捕捉能力或未來訂單時，仍必須有獨立交叉佐證。

## 市場資料來源

為保留歷史相容性，兩年年化與六個月報酬的正式計算仍使用既有 yfinance adjusted-close pipeline；但 Yahoo／yfinance 只扮演 **calculation provider**，不能單獨作為 thesis evidence。

每輪資料更新另以非 Yahoo 來源獨立驗證市場路徑：

- Stooq daily CSV；
- Nasdaq historical API；
- 已提供 API key 時的 Alpha Vantage adjusted series；
- FRED 官方總體資料作為利率／通膨背景，而非個股價格替代品。

多來源數值不會被平均成一個看似精確的答案。若差異超出容忍值，系統保留 `CONFLICT_REVIEW`，降低模型信心並要求查核拆股、幣別、交易所、調整後價格與日期邊界。

## Fail-closed 門檻

正式資料 promotion 前，portfolio 必須至少達成：

- 3 個獨立來源家族；
- 3 個獨立 domain；
- 至少 75% Top20 具有一個可用的非 Yahoo 市場交叉來源；
- 任一來源家族占比不得高於 70%；
- 高信心模型推論至少需要一個 primary／official source、兩個獨立來源家族、非 Yahoo 市場佐證，且不存在未解決的來源衝突。

Stooq／Nasdaq 暫時故障時，可使用不超過 72 小時的本機公開資料快取；超過時限後不會默默降回 Yahoo-only，而是停止 promotion。API key、憑證或使用者識別資料不寫入此快取。

## 產物

- 標準：`config/v213-serenity-public-logic-policy.json`
- 執行 gate：`scripts/v213_source_independence_gate.py`
- 最新 sidecar：`data/cache/v213_source_independence_latest.json`
- 公開 observation cache：`data/cache/v213_source_observation_cache.json`
- 本地模型 gateway：`scripts/v213_local_llm_gateway.py`

Sidecar 會把來源家族、domain、primary／official coverage、非 Yahoo 市場佐證、來源衝突、缺漏證據及每一層 public-logic state 交給本地模型。模型沒有通過條件時只能輸出 `LIMITED`、`UNPROVEN` 或 `INSUFFICIENT_EVIDENCE`，不得以流暢文句掩蓋來源不足。
