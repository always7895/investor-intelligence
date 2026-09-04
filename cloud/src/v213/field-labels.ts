export type FieldLocale = "zh-TW" | "en" | "bilingual";

export interface BilingualFieldLabel {
  zh_TW: string;
  en: string;
}

export const INVESTOR_INTELLIGENCE_FIELD_LABELS: Readonly<Record<string, BilingualFieldLabel>> = Object.freeze({
  schema_version: { zh_TW: "結構版本", en: "Schema version" },
  product_version: { zh_TW: "產品版本", en: "Product version" },
  generated_at: { zh_TW: "產生時間", en: "Generated at" },
  display_columns: { zh_TW: "顯示欄位", en: "Display columns" },
  long_term_definition: { zh_TW: "長期報酬定義", en: "Long-term return definition" },
  short_term_definition: { zh_TW: "短期報酬定義", en: "Short-term return definition" },
  records: { zh_TW: "資料列", en: "Records" },
  provider_scope: { zh_TW: "資料提供範圍", en: "Provider scope" },
  owner_watchlist_inherited: { zh_TW: "是否繼承擁有者觀察清單", en: "Owner watchlist inherited" },
  rank: { zh_TW: "排名", en: "Rank" },
  ticker: { zh_TW: "股票", en: "Ticker" },
  name: { zh_TW: "公司名稱", en: "Company name" },
  long_term_return_pct: { zh_TW: "長期投資報酬率（近2年年化）", en: "Long-term return (2Y annualized)" },
  short_term_return_pct: { zh_TW: "短期投資報酬率（近6個月）", en: "Short-term return (6M)" },
  industry: { zh_TW: "行業別", en: "Industry" },
  profit_summary: { zh_TW: "獲利簡述", en: "Profit summary" },
  current_orders: { zh_TW: "公司現在訂單", en: "Current orders" },
  future_orders_estimate: { zh_TW: "未來訂單預估", en: "Future order outlook" },
  long_term_window: { zh_TW: "長期報酬視窗", en: "Long-term return window" },
  short_term_window: { zh_TW: "短期報酬視窗", en: "Short-term return window" },
  market_source: { zh_TW: "市場資料來源", en: "Market data source" },
  profit_source: { zh_TW: "獲利資料來源", en: "Profit data source" },
  orders_as_of: { zh_TW: "訂單資料截至日", en: "Orders as of" },
  orders_confidence: { zh_TW: "訂單證據信心", en: "Order evidence confidence" },
  current_order_source_urls: { zh_TW: "現在訂單來源網址", en: "Current-order source URLs" },
  future_order_source_urls: { zh_TW: "未來訂單來源網址", en: "Future-order source URLs" },
  numeric_total_order_estimate_prohibited: { zh_TW: "禁止推估訂單總額", en: "Numeric total-order estimate prohibited" },
  retrieved_at: { zh_TW: "擷取時間", en: "Retrieved at" },
  serenity_score: { zh_TW: "系統量化分（舊欄位 serenity_score）", en: "System operationalization score (legacy serenity_score key)" },
  serenity_raw_score: { zh_TW: "系統量化原始分（舊欄位 serenity_raw_score）", en: "System operationalization raw score (legacy serenity_raw_score key)" },
  risk_penalty: { zh_TW: "風險扣分", en: "Risk penalty" },
  data_quality: { zh_TW: "資料品質", en: "Data quality" },
  rating: { zh_TW: "評級", en: "Rating" },
  category: { zh_TW: "分類", en: "Category" },
  serenity_factors: { zh_TW: "系統量化因子（舊欄位 serenity_factors）", en: "System operationalization factors (legacy serenity_factors key)" },
  risk_flags: { zh_TW: "風險旗標", en: "Risk flags" },
  aschenbrenner_overlay: { zh_TW: "Aschenbrenner 獨立覆蓋層", en: "Aschenbrenner independent overlay" },
  evidence: { zh_TW: "證據", en: "Evidence" },
  evidence_count: { zh_TW: "證據數", en: "Evidence count" },
  source_count: { zh_TW: "來源數", en: "Source count" },
  scoring_version: { zh_TW: "評分版本", en: "Scoring version" },
  line_public_eligible: { zh_TW: "LINE 公開推送資格", en: "LINE public eligibility" },
  source_id: { zh_TW: "來源識別碼", en: "Source ID" },
  tier: { zh_TW: "來源層級", en: "Source tier" },
  claim_type: { zh_TW: "主張類型", en: "Claim type" },
  title: { zh_TW: "標題", en: "Title" },
  url: { zh_TW: "網址", en: "URL" },
  as_of: { zh_TW: "截至時間", en: "As of" },
  demand_wave: { zh_TW: "需求浪潮", en: "Demand wave" },
  chokepoint: { zh_TW: "瓶頸", en: "Chokepoint" },
  pricing_power: { zh_TW: "定價能力", en: "Pricing power" },
  replacement_friction: { zh_TW: "替代摩擦", en: "Replacement friction" },
  tam_capture: { zh_TW: "TAM 捕捉能力", en: "TAM capture" },
  valuation_expectations: { zh_TW: "估值預期", en: "Valuation expectations" },
  evidence_quality: { zh_TW: "證據品質", en: "Evidence quality" },
  domain: { zh_TW: "領域", en: "Domain" },
  fit_score: { zh_TW: "適配分數", en: "Fit score" },
  included_in_serenity_score: { zh_TW: "是否納入舊 serenity_score 欄位", en: "Included in legacy serenity_score field" },
  attribution: { zh_TW: "歸因", en: "Attribution" },
});

export function fieldLabel(key: string, locale: FieldLocale = "bilingual"): string {
  const label = INVESTOR_INTELLIGENCE_FIELD_LABELS[key];
  if (!label) return key;
  if (locale === "zh-TW") return label.zh_TW;
  if (locale === "en") return label.en;
  return `${label.zh_TW} / ${label.en}`;
}
