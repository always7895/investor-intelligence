import type { ParsedQuery } from "../core";
import { publicJson, type StorageEnv } from "../storage";

export interface V212Top20ReportRecord {
  schema_version: 1;
  rank: number;
  ticker: string;
  long_term_return_pct: number | null;
  short_term_return_pct: number | null;
  industry: string;
  profit_summary: string;
  long_term_window: "2y_cagr";
  short_term_window: "6m_price_return";
  market_source: "yfinance";
  profit_source: "sec_edgar";
  retrieved_at: string;
  provider_scope: "public_only";
  owner_watchlist_inherited: false;
}

export interface V212Top20Report {
  schema_version: 1;
  product_version: "2.1.2";
  generated_at: string;
  display_columns: ["股票", "長期投資報酬率", "短期投資報酬率", "行業別", "獲利簡述"];
  long_term_definition: "trailing_2y_adjusted_close_cagr";
  short_term_definition: "trailing_6m_adjusted_close_price_return";
  records: V212Top20ReportRecord[];
  provider_scope: "public_only";
  owner_watchlist_inherited: false;
}

const RECORD_KEYS = new Set([
  "schema_version", "rank", "ticker", "long_term_return_pct", "short_term_return_pct",
  "industry", "profit_summary", "long_term_window", "short_term_window", "market_source",
  "profit_source", "retrieved_at", "provider_scope", "owner_watchlist_inherited",
]);
const DOCUMENT_KEYS = new Set([
  "schema_version", "product_version", "generated_at", "display_columns",
  "long_term_definition", "short_term_definition", "records", "provider_scope",
  "owner_watchlist_inherited",
]);
const DISPLAY_COLUMNS = ["股票", "長期投資報酬率", "短期投資報酬率", "行業別", "獲利簡述"] as const;

function exactKeys(value: Record<string, unknown>, expected: Set<string>): boolean {
  const keys = Object.keys(value);
  return keys.length === expected.size && keys.every((key) => expected.has(key));
}

function finiteOrNull(value: unknown): value is number | null {
  return value === null || (typeof value === "number" && Number.isFinite(value));
}

export function parseV212Top20Report(raw: unknown): V212Top20Report | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const doc = raw as Record<string, unknown>;
  if (!exactKeys(doc, DOCUMENT_KEYS)) return null;
  if (
    doc.schema_version !== 1 ||
    doc.product_version !== "2.1.2" ||
    doc.provider_scope !== "public_only" ||
    doc.owner_watchlist_inherited !== false ||
    doc.long_term_definition !== "trailing_2y_adjusted_close_cagr" ||
    doc.short_term_definition !== "trailing_6m_adjusted_close_price_return" ||
    !Number.isFinite(Date.parse(String(doc.generated_at ?? ""))) ||
    !Array.isArray(doc.display_columns) ||
    doc.display_columns.length !== DISPLAY_COLUMNS.length ||
    doc.display_columns.some((value, index) => value !== DISPLAY_COLUMNS[index]) ||
    !Array.isArray(doc.records) || doc.records.length !== 20
  ) return null;

  const records: V212Top20ReportRecord[] = [];
  const seen = new Set<string>();
  for (let index = 0; index < doc.records.length; index += 1) {
    const rawRecord = doc.records[index];
    if (!rawRecord || typeof rawRecord !== "object" || Array.isArray(rawRecord)) return null;
    const item = rawRecord as Record<string, unknown>;
    if (!exactKeys(item, RECORD_KEYS)) return null;
    const ticker = String(item.ticker ?? "").toUpperCase();
    if (
      item.schema_version !== 1 || item.rank !== index + 1 ||
      !/^[A-Z0-9][A-Z0-9.-]{0,14}$/.test(ticker) || seen.has(ticker) ||
      !finiteOrNull(item.long_term_return_pct) || !finiteOrNull(item.short_term_return_pct) ||
      typeof item.industry !== "string" || !item.industry.trim() || item.industry.length > 100 ||
      typeof item.profit_summary !== "string" || !item.profit_summary.trim() || item.profit_summary.length > 120 ||
      item.long_term_window !== "2y_cagr" || item.short_term_window !== "6m_price_return" ||
      item.market_source !== "yfinance" || item.profit_source !== "sec_edgar" ||
      item.provider_scope !== "public_only" || item.owner_watchlist_inherited !== false ||
      !Number.isFinite(Date.parse(String(item.retrieved_at ?? "")))
    ) return null;
    seen.add(ticker);
    records.push({ ...(item as unknown as V212Top20ReportRecord), ticker });
  }
  return { ...(doc as unknown as V212Top20Report), records };
}

function percent(value: number | null): string {
  if (value === null) return "N/A";
  return `${value >= 0 ? "+" : ""}${value.toFixed(1)}%`;
}

export function formatV212Top20Report(report: V212Top20Report): string {
  return [
    "股票｜長期投資報酬率｜短期投資報酬率｜行業別｜獲利簡述",
    ...report.records.map((item) =>
      `${item.ticker}｜${percent(item.long_term_return_pct)}｜${percent(item.short_term_return_pct)}｜${item.industry}｜${item.profit_summary}`,
    ),
  ].join("\n");
}

export async function v212Top20ReportAnswer(env: StorageEnv, query: ParsedQuery): Promise<string | null> {
  if (query.ticker || query.intent !== "ranking" || !/(?:top\s*20|前\s*20|排行|排名)/i.test(query.normalized)) {
    return null;
  }
  const report = parseV212Top20Report(await publicJson<unknown>(env, ["v212:top20-report:latest"]));
  return report ? formatV212Top20Report(report) : null;
}
