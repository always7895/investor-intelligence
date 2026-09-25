/** Delayed public quotes and listed-option observations for the watch universe
 * (scripts/build_market_quotes_options.py), sealed as lazy objects `v213:quotes:v1` and `v213:options:v1`.
 * Observation only: never an order. Documents older than MAX_AGE_MS are ignored (the caller shows unavailable). */
import type { PublicSnapshotView } from "./public-snapshot";
import type { GlobalIdentityRecord } from "./global-identity";

export const QUOTES_KEY = "v213:quotes:v1";
export const OPTIONS_KEY = "v213:options:v1";
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

export type OptionObservation = { quote: unknown } | { unavailable: string } | null;

/** The sealed observation for one underlying and cycle: a quote, an explicit unavailability reason, or null. */
export async function loadOptionObservation(view: PublicSnapshotView, ticker: string, period: "weekly" | "monthly", now = Date.now()): Promise<OptionObservation> {
  if (view.integrity !== "sealed") return null;
  const doc = await view.json<{ schema?: unknown; generated_at?: unknown; options?: Record<string, Record<string, unknown>> }>([OPTIONS_KEY]);
  if (!doc || doc.schema !== "v213-options-v1" || !fresh(doc.generated_at, now) || !doc.options || typeof doc.options !== "object") return null;
  const cycles = Object.hasOwn(doc.options, ticker) ? doc.options[ticker] : undefined;
  const entry = cycles && Object.hasOwn(cycles, period) ? cycles[period] as Record<string, unknown> : undefined;
  if (!entry || typeof entry !== "object") return null;
  if (typeof entry.unavailable === "string") return { unavailable: entry.unavailable.slice(0, 200) };
  return { quote: entry };
}
