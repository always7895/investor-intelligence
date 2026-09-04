# Investor Intelligence v2.1.3 Bilingual Fields / 中英雙語欄位

Machine keys remain stable English identifiers for API, KV, signature and historical compatibility. Current public-schema labels are split into reviewed dictionaries so each machine key has both `zh-TW` and `en` display names:

- `config/field-labels.zh-en.json`: Top20, evidence, snapshot, options and seven-field reports.
- `config/field-labels-source-federation.zh-en.json`: live source federation, source families, per-ticker coverage, concentration and diversified methodology metadata.
- `config/field-labels-source-federation-gate.zh-en.json`: gate outcome and publisher-family deduplication fields.

機器欄位名稱維持英文 key，以保留 API、KV、簽章與歷史相容性；公開顯示層透過上述三個字典提供繁中與英文。`scripts/audit_v213_bilingual_public_fields.py` 在 CI 中合併三個字典，只要必要公開欄位缺少 `zh-TW` 或 `en`、字典重複 key，或七欄正式名稱被改動，就會 fail closed。

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

The renderer supports `zh-TW`, `en`, and `bilingual` header modes. Production defaults to `zh-TW` because it matches the H6B2 accepted LINE payload; English and bilingual modes never rename machine keys.

## Methodology and federation labels / 方法與來源聯邦欄位

Legacy keys `serenity_score`, `serenity_raw_score`, and `serenity_factors` are labelled as **System operationalization** fields. They are not described as an official Serenity formula or score.

Source-federation fields such as `successful_families`, `ticker_coverage_ratio`, `market_provider_confidence`, `largest_family_share`, `catalog_source_count_is_not_live_use` and `official_serenity_formula_claimed` also have exact Chinese and English labels. This preserves the distinction between:

1. reviewed source-catalog inventory;
2. source families actually reached in the current run;
3. claim-specific evidence for each ticker;
4. the project-authored System operationalization;
5. model inference.

舊 `serenity_*` machine key 只為相容性保留，顯示名稱明確標成「系統量化」。來源聯邦欄位也全部提供中英對照，避免把 101 項來源目錄誤寫成本輪實際使用 101 個來源，或把 Yahoo 市場觀測誤寫成公司／訂單／瓶頸的權威來源。
