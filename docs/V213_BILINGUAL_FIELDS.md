# Investor Intelligence v2.1.3 Bilingual Fields / 中英雙語欄位

Machine keys remain stable English identifiers for API, KV, signature and historical compatibility. The complete public-schema display-label dictionary is `config/field-labels.zh-en.json`; each listed machine key has both `zh-TW` and `en` labels. The TypeScript source of truth used by the renderer is `cloud/src/v213/field-labels.ts`.

機器欄位名稱維持既有英文 key，以保留 API、KV、簽章與歷史資料相容性。完整的公開 schema 顯示名稱對照位於 `config/field-labels.zh-en.json`，每個列入的 machine key 都同時提供 `zh-TW` 與 `en`。Formatter 使用的 TypeScript 對照表位於 `cloud/src/v213/field-labels.ts`。

## Seven-field LINE contract / LINE 七欄合約

| Machine key | 繁體中文 | English |
|---|---|---|
| `ticker` | 股票 | Ticker |
| `long_term_return_pct` | 長期投資報酬率（近2年年化） | Long-term return (2Y annualized) |
| `short_term_return_pct` | 短期投資報酬率（近6個月） | Short-term return (6M) |
| `industry` | 行業別 | Industry |
| `profit_summary` | 獲利簡述 | Profit summary |
| `current_orders` | 公司現在訂單 | Current orders |
| `future_orders_estimate` | 未來訂單預估 | Future order outlook |

The renderer supports `zh-TW`, `en`, and `bilingual` header modes. Production defaults to `zh-TW` because that is the H6B2 visually/content-accepted LINE payload; the English and bilingual modes do not rename machine keys.

Renderer 支援 `zh-TW`、`en`、`bilingual` 三種表頭模式。Production 預設仍為 `zh-TW`，因為這是 H6B2 已完成內容驗收的 LINE payload；英文與雙語模式不會更改 machine key。

Legacy keys named `serenity_score`, `serenity_raw_score`, and `serenity_factors` are labelled as **System operationalization** fields in the bilingual dictionary; they are not described as an official Serenity formula or score.

舊 machine key `serenity_score`、`serenity_raw_score`、`serenity_factors` 在雙語字典中明確標記為 **System operationalization / 系統量化** 欄位，不宣稱為 Serenity 官方公式或官方分數。
