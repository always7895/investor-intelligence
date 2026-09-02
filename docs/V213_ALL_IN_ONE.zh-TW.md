# Investor Intelligence v2.1.3 SourceFederation-R44 All-in-One

這個交付版把 v2.1.0、v2.1.1、v2.1.2、v2.1.3 的來源快照整合在同一個外層 ZIP，並包含 EXE、本地模型選擇器、多來源資料聯邦、七欄 LINE 與正式 activation rollback。

## 一鍵啟動

完整解壓後雙擊 `InvestorIntelligence.exe`。不要直接從 ZIP 內執行。

啟動器提供：
- 掃描 llama.cpp router 目前真正公開的所有 model ID。
- 明確選擇並持久化本地模型；預設首選為 `RVN-Q6_K-multilingual-mtp`，但不會用 Gemma 或其他模型偷偷替代。
- 啟動所選模型並執行十階段資料刷新。
- 只啟動 exact-model bridge。
- 經二次確認後正式啟用每天 08:00 / 21:00 的 v2.1.3 七欄 LINE 推送。

完整記錄保存於 `%LOCALAPPDATA%\InvestorIntelligence\logs\launcher\` 與 `%LOCALAPPDATA%\InvestorIntelligence\logs\v213-refresh\`。

## 十階段刷新

1. Python、hash-locked dependencies 與方法政策稽核。
2. 所選 llama.cpp 模型、Gateway schema v2 與 tunnel 健康驗證。
3. 候選發現與 SEC facts；Yahoo 僅為 T3 候選／市場觀測。
4. v2.1.2 市場／SEC 五欄資料。
5. 訂單證據與當下 Top20 membership reconciliation。
6. 初始 v2.1.3 七欄資料。
7. 建立 live source federation 並執行來源真實性 gate。
8. 套用多來源、證據約束的 System operationalization。
9. 在最終重新排序後建立 signed public snapshot。
10. Signed sync；已正式啟用時才更新 exact-model Worker route。

## Serenity 標準與邏輯

本專案使用 `Serenity public-logic high-fidelity reconstruction`，不宣稱取得 Serenity 的私人流程，也不宣稱存在 Serenity 官方 100 分公式。歷史 machine key `serenity_score`／`serenity_factors` 為相容性保留；介面一律標成「System operationalization／系統量化」。

Evidence Standard v3 的重要規則：
- 關鍵字、產業標籤、高毛利、營收成長、beta、short interest 或股價上漲都不能單獨證明 bottleneck。
- Bottleneck 正向成立必須有觸及該公司的 evidence-bound supply-chain graph edge、至少兩個獨立 primary/corroborating publisher families、至少一個 primary family，而且至少一個 family 必須獨立於 focal issuer。
- 高毛利不能單獨證明 replacement friction；需要 qualification、switching cost、供應集中或獨特 process/IP 證據。
- 營收成長單獨只可貢獻 TAM-capture 欄位上限 40%；不能等同市占、BOM share 或訂單捕捉。
- Issuer-only commercial statement 只算 provisional；strong validation 需要 counterparty、regulator 或已實現 audited revenue。
- 嚴重且高品質的 primary thesis killer 可以非對稱地推翻正向論點；不會為了形式上的「兩來源對稱」而忽略直接破壞證據。
- 衝突的重大 primary 數值不取平均，維持 `CONFLICT_UNRESOLVED` 並 fail closed。
- 同一 publisher 的不同網址、鏡像、syndication 或相同內容 hash 只算一個 family；搜尋摘要與社群轉貼不能形成獨立證明。

完整政策位於：
- `config/v213-serenity-evidence-standard-v3.json`
- `config/v213-source-federation-policy.json`
- `scripts/v213_apply_diversified_operationalization.py`

## 多來源資料聯邦

受審查 catalog 目前有 101 個來源項目，但 catalog 是 inventory，不代表本輪真的使用 101 個來源。每輪會另外輸出 `data/cache/v213_source_federation_latest.json`，明確記錄本輪真正成功的來源 families、每檔股票來源、濃度、衝突與 gate。

正式 required live families：
- SEC EDGAR：issuer filings 與公司財務 facts。
- Nasdaq Trader Symbol Directory：受監管市場的 listing identity。
- World Bank：官方 macro context。
- U.S. BLS：官方 inflation／labor context。
- ECB SDMX：官方 FX／financial context。

額外來源：
- GLEIF：可匹配時提供獨立 legal-entity identity。
- Yahoo/yfinance：T3 候選發現與市場觀測，永遠不是 issuer、訂單、供應鏈或 bottleneck authority。
- Alpha Vantage：有使用者自己的 API key 時可作 optional 第二個市場觀測 family；不存在時不得把 Yahoo-only observation 升為高信心。

Gate 至少要求：五個 required global families 成功、至少四個 official families、80% Top20 同時具備至少兩個 independent families 與至少兩個 official identity/filing families、單一 family evidence share 不超過 65%、重大 unresolved conflicts 為零。

多來源不代表把不同 claim scope 混成假 corroboration。例如 Nasdaq listing identity 不能證明營收；World Bank macro 不能證明單一公司的訂單；SEC filing 也不能單獨證明市場價格。每個 factor 仍按照 claim-specific evidence threshold 判定。

## 本地模型

EXE 會查詢 `/v1/models?reload=1`、`/models?reload=1`、`/v1/models`，只有 router 實際回傳的 exact model ID 才可使用。選擇結果保存於：

`%LOCALAPPDATA%\InvestorIntelligence\UserData\config\v213-model-selection.json`

Bridge 需要：model catalog exact match、最小 completion probe、Gateway health schema v2、public tunnel exact-model health。8814 被舊 Gateway 占用時只會安全停止可識別的 Investor Intelligence Gateway；其他程序不會被強制終止，系統會改用下一個可用 loopback port。

本地模型只做 evidence-aware interpretation；它不能創造來源成功、訂單總額、bottleneck graph edge 或已不存在的 corroboration。

## 七欄 scheduled activation

`activate-v213-seven-field-schedule.ps1` 現在是 canonical diversified preflight：任何 Worker mutation 前，先驗證 live federation freshness、required families、每檔來源 coverage、來源濃度、衝突、最終 Top20 scoring version 與七欄 exact order；通過後才呼叫 `activate-v213-seven-field-schedule-core.ps1` 的 Wrangler stdout/stderr isolation 與 exact prior Worker rollback。

正式啟用成功後會複製到 `%LOCALAPPDATA%\InvestorIntelligence\V213Runtime`，並建立 07:20／20:20 本機刷新，供 08:00／21:00 Cloudflare Worker 通過 freshness gate 後推送。

## 中英雙語欄位

所有 machine key 維持穩定英文，以保留 API、KV、簽章與歷史相容性；`config/field-labels.zh-en.json` 提供繁中與英文顯示名稱。七欄 formatter 支援 `zh-TW`、`en`、`bilingual`，Production 預設仍為已驗收的 `zh-TW`。

## 版本快照與完整性

`versions/` 內含 v2.1.0～v2.1.3 source ZIP；精確 SHA 在 `VERSION-REFS.json`。`MANIFEST.json` 與 `SHA256SUMS.txt` 可驗證完整性。打包 workflow 不會修改 Production；正式切換只能由本機 EXE 在所有 fail-closed gates 通過後執行。
