import { fieldLabel, type FieldLocale } from "./field-labels";
import { isPublicCitationUrl } from "./public-citation";
import type { StorageEnv } from "../storage";
import { pinPublicSnapshot, type PublicSnapshotView } from "./public-snapshot";
import type { ParsedQuery } from "../core";

export function v213FieldLocale(value?: string): FieldLocale {
  const locale = (value ?? "bilingual").trim().toLowerCase();
  return ["en", "english"].includes(locale) ? "en" : ["zh-tw", "zh"].includes(locale) ? "zh-TW" : "bilingual";
}

export type V213Top20Env = StorageEnv & { V213_FIELD_LOCALE?: string; V21_TOP20_MAX_AGE_SECONDS?: string };

export interface V213ReportReference {
  readonly snapshot: string;
  readonly reportSha256: string;
}
const reportReferences = new WeakMap<V213Top20Report, V213ReportReference>();
export function getV213ReportReference(report: V213Top20Report): V213ReportReference | null {
  return reportReferences.get(report) ?? null;
}

/** Bind the displayed object to the UTF-8 stored report text and pinned run.
 * This is content identity, not a substitute for sealed-claim/source qualification.
 * Pure parser/formatter inputs do not receive an actionable reference.
 */
export async function readV213Top20Report(view: PublicSnapshotView): Promise<V213Top20Report | null> {
  if (view.kind === "invalid") return null;
  const raw = await view.text(["v213:top20-report:latest"]);
  if (raw === null || raw.length > 2097152) return null;
  let value: unknown;
  try { value = JSON.parse(raw); } catch { return null; }
  const report = parseV213Top20Report(value);
  if (!report) return null;
  const bytes = new TextEncoder().encode(raw);
  if (bytes.byteLength > 2097152) return null;
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  const reportSha256 = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
  for (const row of report.records) {
    Object.freeze(row.current_order_source_urls); Object.freeze(row.future_order_source_urls);
    Object.freeze(row);
  }
  Object.freeze(report.records); Object.freeze(report.display_columns); Object.freeze(report);
  reportReferences.set(report, Object.freeze({ snapshot: view.kind === "legacy" ? "legacy" : `s:${view.runId}`, reportSha256 }));
  return report;
}

export async function loadV213FreshTop20Report(
  env: V213Top20Env,
  query: ParsedQuery,
): Promise<V213Top20Report | string | null> {
  if (query.ticker || query.intent !== "ranking" || !/(?:top\s*20|前\s*20|排行|排名)/i.test(query.normalized)) return null;
  const view = await pinPublicSnapshot(env);
  const report = await readV213Top20Report(view);
  if (!report) return "七欄 Top20 報告尚未通過驗證；不退回五欄。 / Seven-field Top20 unavailable; no five-field fallback.";
  const stamp = await view.text(["last_successful_pipeline_timestamp"]);
  const limit = Math.max(300, Math.min(86400, Number(env.V21_TOP20_MAX_AGE_SECONDS ?? "7200") || 7200));
  if ([stamp, report.generated_at].some(value => {
    const age = (Date.now() - Date.parse(value ?? "")) / 1000;
    return !Number.isFinite(age) || age < -300 || age > limit;
  })) return "七欄 Top20 資料已過期或時間無效，請等待新鮮公開資料。 / Seven-field Top20 is stale or invalid; fresh public data is required.";
  return report;
}

export async function v213Top20ReportAnswer(env: V213Top20Env, query: ParsedQuery): Promise<string | null> {
  const result = await loadV213FreshTop20Report(env, query);
  return result && typeof result !== "string" ? formatV213Top20Report(result, v213FieldLocale(env.V213_FIELD_LOCALE)) : result;
}

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

function returnPercentOrNull(value: unknown): value is number | null {
  // These are positive-price stock returns, not leveraged portfolio P/L.
  return value === null || (typeof value === "number" && Number.isFinite(value) && value >= -100);
}

function httpsUrls(value: unknown): value is string[] {
  return Array.isArray(value) && value.length <= 8 && value.every(isPublicCitationUrl);
}

function lineSafeText(value: unknown, max: number): value is string {
  return typeof value === "string" && value.trim().length > 0 && value.length <= max && !value.includes("｜") && !/[\r\n]/.test(value);
}

function orderEvidenceSemantics(item: Record<string, unknown>): boolean {
  if (typeof item.orders_as_of !== "string" || typeof item.orders_confidence !== "string") return false;
  if (!httpsUrls(item.current_order_source_urls) || !httpsUrls(item.future_order_source_urls)) return false;
  const confidence = item.orders_confidence.trim();
  if (!confidence || confidence.length > 80) return false;
  if (confidence === "UNAVAILABLE") {
    const asOfIsAllowed = item.orders_as_of === "" || Number.isFinite(Date.parse(item.orders_as_of));
    return (
      asOfIsAllowed &&
      item.current_orders === V213_NO_CURRENT_ORDERS &&
      item.future_orders_estimate === V213_NO_FUTURE_ORDER_ESTIMATE &&
      item.current_order_source_urls.length === 0 &&
      item.future_order_source_urls.length === 0
    );
  }
  return Number.isFinite(Date.parse(item.orders_as_of));
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
    typeof doc.generated_at !== "string" || !Number.isFinite(Date.parse(doc.generated_at)) ||
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
    const ticker = typeof item.ticker === "string" ? item.ticker.toUpperCase() : "";
    if (
      item.schema_version !== 2 || item.rank !== index + 1 ||
      !TICKER_RE.test(ticker) || seen.has(ticker) ||
      !returnPercentOrNull(item.long_term_return_pct) || !returnPercentOrNull(item.short_term_return_pct) ||
      !lineSafeText(item.industry, 100) || !TRADITIONAL_CHINESE_RE.test(item.industry) ||
      !lineSafeText(item.profit_summary, 120) ||
      !lineSafeText(item.current_orders, 150) || !lineSafeText(item.future_orders_estimate, 170) ||
      item.long_term_window !== "2y_cagr" || item.short_term_window !== "6m_price_return" ||
      item.market_source !== "yfinance" || item.profit_source !== "sec_edgar" ||
      !orderEvidenceSemantics(item) ||
      item.numeric_total_order_estimate_prohibited !== true ||
      item.provider_scope !== "public_only" || item.owner_watchlist_inherited !== false ||
      typeof item.retrieved_at !== "string" || !Number.isFinite(Date.parse(item.retrieved_at))
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

export function v213Top20DisplayHeader(locale: FieldLocale): readonly string[] {
  if (locale === "en") return V213_TOP20_DISPLAY_COLUMNS_EN;
  if (locale === "bilingual") return V213_TOP20_DISPLAY_COLUMNS_BILINGUAL;
  return V213_TOP20_DISPLAY_COLUMNS;
}

export function v213Top20DisplayValues(item: V213Top20ReportRecord): string[] {
  return [item.ticker, percent(item.long_term_return_pct), percent(item.short_term_return_pct),
    item.industry, item.profit_summary, item.current_orders, item.future_orders_estimate];
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
    v213Top20DisplayHeader(locale).join("｜"),
    ...report.records.map((item) => v213Top20DisplayValues(item).join("｜")),
  ].join("\n");
}
