/** Delayed public quotes and listed-option observations for the watch universe
 * (scripts/build_market_quotes_options.py), sealed as lazy objects `v213:quotes:v1` and `v213:options:v2`.
 * Observation only: never an order. Documents older than MAX_AGE_MS are ignored (the caller shows unavailable). */
import type { PublicSnapshotView } from "./public-snapshot";
import type { GlobalIdentityRecord } from "./global-identity";

export const QUOTES_KEY = "v213:quotes:v1";
export const OPTIONS_KEY = "v213:options:v2";
const MAX_AGE_MS = 6 * 3600_000;

export interface DelayedQuote {
  symbol: string; price: number; previous_close: number | null; change_pct: number | null; currency: string | null;
  asof: string; source: string; source_url: string;
}

function fresh(generated: unknown, now: number): boolean {
  const time = typeof generated === "string" ? Date.parse(generated) : NaN;
  return Number.isFinite(time) && now - time <= MAX_AGE_MS && time - now <= 300_000;
}

/** The Yahoo Finance symbol for a listing in the identity directory. */
export function observationSymbol(record: Pick<GlobalIdentityRecord, "symbol" | "market" | "venue">): string {
  const base = record.symbol.replace(/ /g, "-");
  if (record.market === "SWEDEN") return `${base}.ST`;
  if (record.market === "TAIWAN") return `${base}.${record.venue.toUpperCase() === "TPEX" ? "TWO" : "TW"}`;
  if (record.market === "JAPAN") return `${base}.T`;
  if (record.market === "KOREA") return `${base}.${record.venue.toUpperCase() === "KOSDAQ" ? "KQ" : "KS"}`;
  const europe: Record<string, string> = { "EURONEXT PARIS": "PA", "EURONEXT AMSTERDAM": "AS", "EURONEXT BRUSSELS": "BR", "BORSA ITALIANA": "MI" };
  if (record.market === "EUROPE" && europe[record.venue.toUpperCase()]) return `${base}.${europe[record.venue.toUpperCase()]}`;
  return base;
}

export async function loadDelayedQuote(view: PublicSnapshotView, symbol: string, now = Date.now()): Promise<DelayedQuote | null> {
  if (view.integrity !== "sealed") return null;
  const doc = await view.json<{ schema?: unknown; generated_at?: unknown; quotes?: Record<string, DelayedQuote> }>([QUOTES_KEY]);
  if (!doc || doc.schema !== "v213-quotes-v1" || !fresh(doc.generated_at, now) || !doc.quotes || typeof doc.quotes !== "object") return null;
  const quote = Object.hasOwn(doc.quotes, symbol) ? doc.quotes[symbol] : undefined;
  if (!quote || typeof quote.price !== "number" || !Number.isFinite(quote.price) || quote.price <= 0
    || typeof quote.source_url !== "string" || !quote.source_url.startsWith("https://")) return null;
  return quote;
}

export const priceShardKey = (market: string) => `v213:prices:v1:${market}`;
const PRICE_MAX_AGE_MS = 4 * 86400_000;  // Friday's close is still the latest on Monday morning
const PRICE_SOURCE_LABEL: Record<string, string> = {
  "nasdaq-us-screener": "Nasdaq 股票篩選器（延遲）", "twse-day-all": "臺灣證交所每日收盤", "tpex-daily-close": "櫃買中心每日收盤",
  "nasdaq-stockholm-main": "Nasdaq Nordic 斯德哥爾摩（延遲）", "nasdaq-stockholm-first-north": "Nasdaq Nordic First North（延遲）",
  "euronext-equities": "Euronext 收盤", "yahoo-daily-close": "Yahoo Finance 日收盤（非官方）",
};

/** The delayed daily price of any listed identity from its market's sealed price shard (scripts/build_price_shards.py,
 * official bulk feeds); null when the shard is missing, stale or has no row. change_pct is a fraction like v1 quotes. */
export async function loadListingPrice(view: PublicSnapshotView, record: Pick<GlobalIdentityRecord, "symbol" | "market" | "venue">,
  now = Date.now()): Promise<DelayedQuote | null> {
  if (view.integrity !== "sealed") return null;
  const doc = await view.json<{ schema?: unknown; market?: unknown; generated_at?: unknown; sources?: unknown; rows?: Record<string, unknown> }>([priceShardKey(record.market)]);
  if (!doc || doc.schema !== "v213-price-shard-v1" || doc.market !== record.market || !Array.isArray(doc.sources)
    || !doc.rows || typeof doc.rows !== "object") return null;
  const generated = typeof doc.generated_at === "string" ? Date.parse(doc.generated_at) : NaN;
  if (!Number.isFinite(generated) || now - generated > PRICE_MAX_AGE_MS || generated - now > 300_000) return null;
  const key = record.market === "EUROPE" ? `${record.venue.toUpperCase()}|${record.symbol}` : record.symbol;
  const row = Object.hasOwn(doc.rows, key) ? doc.rows[key] : undefined;
  if (!Array.isArray(row) || row.length !== 5) return null;
  const [price, changePct, asof, currency, sourceIndex] = row;
  const source = Number.isInteger(sourceIndex) ? (doc.sources as { id?: unknown; url?: unknown }[])[sourceIndex as number] : undefined;
  if (typeof price !== "number" || !Number.isFinite(price) || price <= 0 || !(changePct === null || (typeof changePct === "number" && Number.isFinite(changePct)))
    || !(asof === null || (typeof asof === "string" && /^\d{4}-\d{2}-\d{2}$/.test(asof))) || typeof currency !== "string" || currency.length > 8
    || !source || typeof source.url !== "string" || !source.url.startsWith("https://") || typeof source.id !== "string") return null;
  return { symbol: record.symbol, price, previous_close: null, change_pct: changePct === null ? null : (changePct as number) / 100, currency,
    asof: asof ?? `${String(doc.generated_at)}（擷取時間；來源未載明成交日）`, source: PRICE_SOURCE_LABEL[source.id] ?? source.id, source_url: source.url };
}

/** A covered-call cycle (validated by the caller), an explicit unavailability reason, or null. */
export type OptionObservation = { quote: unknown } | { unavailable: string } | null;

/** The sealed observation for one underlying and cycle: a quote, an explicit unavailability reason, or null. */
export async function loadOptionObservation(view: PublicSnapshotView, ticker: string, period: "weekly" | "monthly", now = Date.now()): Promise<OptionObservation> {
  if (view.integrity !== "sealed") return null;
  const doc = await view.json<{ schema?: unknown; generated_at?: unknown; options?: Record<string, Record<string, unknown>> }>([OPTIONS_KEY]);
  if (!doc || doc.schema !== "v213-options-v2" || !fresh(doc.generated_at, now) || !doc.options || typeof doc.options !== "object") return null;
  const cycles = Object.hasOwn(doc.options, ticker) ? doc.options[ticker] : undefined;
  const entry = cycles && Object.hasOwn(cycles, period) ? cycles[period] as Record<string, unknown> : undefined;
  if (!entry || typeof entry !== "object") return null;
  if (typeof entry.unavailable === "string") return { unavailable: entry.unavailable.slice(0, 200) };
  return { quote: entry };
}
