import { fieldLabel, type FieldLocale } from "./field-labels";

export interface V213Top20ReportRecord {
  schema_version: 2;
  rank: number;
  ticker: string;
  long_term_return_pct: number | null;
  short_term_return_pct: number | null;
  industry: string;
  profit_summary: string;
  current_orders: string;
  future_orders_estimate: string;
  long_term_window: "2y_cagr";
  short_term_window: "6m_price_return";
  market_source: "yfinance";
  profit_source: "sec_edgar";
  orders_as_of: string;
  orders_confidence: string;
  current_order_source_urls: string[];
  future_order_source_urls: string[];
  numeric_total_order_estimate_prohibited: true;
  retrieved_at: string;
  provider_scope: "public_only";
  owner_watchlist_inherited: false;
}

export interface V213Top20Report {
  schema_version: 2;
  product_version: "2.1.3";
  generated_at: string;
  display_columns: [
    "股票",
    "長期投資報酬率（近2年年化）",
    "短期投資報酬率（近6個月）",
    "行業別",
    "獲利簡述",
    "公司現在訂單",
    "未來訂單預估",
  ];
  long_term_definition: "trailing_2y_adjusted_close_cagr";
  short_term_definition: "trailing_6m_adjusted_close_price_return";
  records: V213Top20ReportRecord[];
  provider_scope: "public_only";
  owner_watchlist_inherited: false;
}

export const V213_TOP20_DISPLAY_COLUMNS = [
  "股票",
  "長期投資報酬率（近2年年化）",
  "短期投資報酬率（近6個月）",
  "行業別",
  "獲利簡述",
  "公司現在訂單",
  "未來訂單預估",
] as const;

export const V213_TOP20_DISPLAY_COLUMNS_EN = [
  "Ticker",
  "Long-term return (2Y annualized)",
  "Short-term return (6M)",
  "Industry",
  "Profit summary",
  "Current orders",
  "Future order outlook",
] as const;

export const V213_TOP20_DISPLAY_COLUMNS_BILINGUAL = [
  fieldLabel("ticker"),
  fieldLabel("long_term_return_pct"),
  fieldLabel("short_term_return_pct"),
  fieldLabel("industry"),
  fieldLabel("profit_summary"),
  fieldLabel("current_orders"),
  fieldLabel("future_orders_estimate"),
] as const;

export const V213_NO_CURRENT_ORDERS = "未揭露（無可靠公開訂單數字）";
export const V213_NO_FUTURE_ORDER_ESTIMATE = "無可靠公開預估";

const RECORD_KEYS = new Set([
  "schema_version", "rank", "ticker", "long_term_return_pct", "short_term_return_pct",
  "industry", "profit_summary", "current_orders", "future_orders_estimate",
  "long_term_window", "short_term_window", "market_source", "profit_source",
  "orders_as_of", "orders_confidence", "current_order_source_urls",
  "future_order_source_urls", "numeric_total_order_estimate_prohibited", "retrieved_at",
  "provider_scope", "owner_watchlist_inherited",
]);

const DOCUMENT_KEYS = new Set([
  "schema_version", "product_version", "generated_at", "display_columns",
  "long_term_definition", "short_term_definition", "records", "provider_scope",
  "owner_watchlist_inherited",
]);

const TICKER_RE = /^[A-Z0-9][A-Z0-9.-]{0,14}$/;
const TRADITIONAL_CHINESE_RE = /[\u3400-\u9fff]/;

function exactKeys(value: Record<string, unknown>, expected: Set<string>): boolean {
  const keys = Object.keys(value);
  return keys.length === expected.size && keys.every((key) => expected.has(key));
}

function finiteOrNull(value: unknown): value is number | null {
  return value === null || (typeof value === "number" && Number.isFinite(value));
}

function httpsUrls(value: unknown): value is string[] {
  return Array.isArray(value) && value.length <= 8 && value.every((item) =>
    typeof item === "string" && item.startsWith("https://") && item.length <= 1000
  );
}

function lineSafeText(value: unknown, max: number): value is string {
  return typeof value === "string" && value.trim().length > 0 && value.length <= max && !value.includes("｜") && !/[\r\n]/.test(value);
}

export function parseV213Top20Report(raw: unknown): V213Top20Report | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const doc = raw as Record<string, unknown>;
  if (!exactKeys(doc, DOCUMENT_KEYS)) return null;
  if (
    doc.schema_version !== 2 ||
    doc.product_version !== "2.1.3" ||
    doc.provider_scope !== "public_only" ||
    doc.owner_watchlist_inherited !== false ||
    doc.long_term_definition !== "trailing_2y_adjusted_close_cagr" ||
    doc.short_term_definition !== "trailing_6m_adjusted_close_price_return" ||
    !Number.isFinite(Date.parse(String(doc.generated_at ?? ""))) ||
    !Array.isArray(doc.display_columns) ||
    doc.display_columns.length !== V213_TOP20_DISPLAY_COLUMNS.length ||
    doc.display_columns.some((value, index) => value !== V213_TOP20_DISPLAY_COLUMNS[index]) ||
    !Array.isArray(doc.records) || doc.records.length !== 20
  ) return null;

  const records: V213Top20ReportRecord[] = [];
  const seen = new Set<string>();
  for (let index = 0; index < doc.records.length; index += 1) {
    const rawRecord = doc.records[index];
    if (!rawRecord || typeof rawRecord !== "object" || Array.isArray(rawRecord)) return null;
    const item = rawRecord as Record<string, unknown>;
    if (!exactKeys(item, RECORD_KEYS)) return null;
    const ticker = String(item.ticker ?? "").toUpperCase();
    if (
      item.schema_version !== 2 || item.rank !== index + 1 ||
      !TICKER_RE.test(ticker) || seen.has(ticker) ||
      !finiteOrNull(item.long_term_return_pct) || !finiteOrNull(item.short_term_return_pct) ||
      !lineSafeText(item.industry, 100) || !TRADITIONAL_CHINESE_RE.test(item.industry) ||
      !lineSafeText(item.profit_summary, 120) ||
      !lineSafeText(item.current_orders, 150) || !lineSafeText(item.future_orders_estimate, 170) ||
      item.long_term_window !== "2y_cagr" || item.short_term_window !== "6m_price_return" ||
      item.market_source !== "yfinance" || item.profit_source !== "sec_edgar" ||
      typeof item.orders_as_of !== "string" || !Number.isFinite(Date.parse(item.orders_as_of)) ||
      typeof item.orders_confidence !== "string" || !item.orders_confidence.trim() || item.orders_confidence.length > 80 ||
      !httpsUrls(item.current_order_source_urls) || !httpsUrls(item.future_order_source_urls) ||
      item.numeric_total_order_estimate_prohibited !== true ||
      item.provider_scope !== "public_only" || item.owner_watchlist_inherited !== false ||
      !Number.isFinite(Date.parse(String(item.retrieved_at ?? "")))
    ) return null;
    seen.add(ticker);
    records.push({ ...(item as unknown as V213Top20ReportRecord), ticker });
  }
  return { ...(doc as unknown as V213Top20Report), records };
}

function percent(value: number | null): string {
  if (value === null) return "N/A";
  return `${value >= 0 ? "+" : ""}${value.toFixed(1)}%`;
}

function header(locale: FieldLocale): readonly string[] {
  if (locale === "en") return V213_TOP20_DISPLAY_COLUMNS_EN;
  if (locale === "bilingual") return V213_TOP20_DISPLAY_COLUMNS_BILINGUAL;
  return V213_TOP20_DISPLAY_COLUMNS;
}

/**
 * Seven-field renderer accepted by H6B2. Machine keys remain stable English
 * identifiers; display labels are available in Traditional Chinese, English,
 * or bilingual form.
 */
export function formatV213Top20Report(
  report: V213Top20Report,
  locale: FieldLocale = "zh-TW",
): string {
  return [
    header(locale).join("｜"),
    ...report.records.map((item) => [
      item.ticker,
      percent(item.long_term_return_pct),
      percent(item.short_term_return_pct),
      item.industry,
      item.profit_summary,
      item.current_orders,
      item.future_orders_estimate,
    ].join("｜")),
  ].join("\n");
}
