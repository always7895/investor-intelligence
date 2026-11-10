export interface HistoricalVolatility {
  ticker: string;
  currency: string;
  hv20: number;
  hv60: number;
  observations: 61;
  start_date_20: string;
  start_date_60: string;
  asof_date: string;
  source_url: string;
  source_sha256: string;
  price_basis: "PROVIDER_ADJUSTED_CLOSE";
}

const WIRE_KEYS = new Set([
  "ticker", "currency", "hv20", "hv60", "observations", "start_date_20", "start_date_60",
  "asof_date", "source_url", "source_sha256", "price_basis",
]);
const QUERY_KEYS: Record<string, true> = {
  period1: true, period2: true, interval: true, events: true, includeAdjustedClose: true, range: true,
};
const DAY_MS = 86_400_000;

function calendarDay(value: unknown): number | null {
  if (typeof value !== "string" || !/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(value) || value.startsWith("0000-")) return null;
  const timestamp = Date.parse(`${value}T00:00:00.000Z`);
  if (!Number.isFinite(timestamp) || new Date(timestamp).toISOString().slice(0, 10) !== value) return null;
  return timestamp / DAY_MS;
}

function validSourceUrl(value: unknown, ticker: string): boolean {
  if (typeof value !== "string" || /[\s\\#]/.test(value) || /[\u0000-\u001f\u007f]/.test(value)) return false;
  // Validate original spelling: URL parsers otherwise normalize dot segments and backslashes.
  const source = /^https:\/\/query1\.finance\.yahoo\.com(?::443)?(\/[^?]*)(?:\?(.*))?$/.exec(value);
  if (!source || source[1] !== `/v8/finance/chart/${ticker}`) return false;
  const url = new URL(value);
  if (url.pathname !== source[1] || url.username !== "" || url.password !== "") return false;
  for (const key of url.searchParams.keys()) {
    if (!Object.prototype.hasOwnProperty.call(QUERY_KEYS, key)) return false;
  }
  return true;
}

export function validHistoricalVolatility(
  value: unknown, ticker: string, currency: string, captureDate: string,
): value is HistoricalVolatility {
  try {
    if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
    const keys = Reflect.ownKeys(value);
    if (keys.length !== WIRE_KEYS.size || keys.some(key => typeof key !== "string" || !WIRE_KEYS.has(key))) return false;
    if (!("ticker" in value) || !("currency" in value) || !("hv20" in value) || !("hv60" in value)
      || !("observations" in value) || !("start_date_20" in value) || !("start_date_60" in value)
      || !("asof_date" in value) || !("source_url" in value) || !("source_sha256" in value)
      || !("price_basis" in value)) return false;
    if (!/^[A-Z0-9][A-Z0-9.\-]{0,31}$/.test(ticker) || ticker.includes("..") || value.ticker !== ticker
      || (currency !== "USD" && currency !== "SEK") || value.currency !== currency) return false;
    if (value.price_basis !== "PROVIDER_ADJUSTED_CLOSE" || value.observations !== 61) return false;
    if (typeof value.hv20 !== "number" || !Number.isFinite(value.hv20) || value.hv20 < 0
      || typeof value.hv60 !== "number" || !Number.isFinite(value.hv60) || value.hv60 < 0) return false;
    const capture = calendarDay(captureDate);
    const start20 = calendarDay(value.start_date_20);
    const start60 = calendarDay(value.start_date_60);
    const asof = calendarDay(value.asof_date);
    if (capture === null || start20 === null || start60 === null || asof === null) return false;
    for (const day of [start20, start60, asof]) {
      const weekday = new Date(day * DAY_MS).getUTCDay();
      if (weekday === 0 || weekday === 6) return false;
    }
    const age = capture - asof;
    if (age < 1 || age > 4 || start60 >= start20
      || asof - start20 < 20 || asof - start20 > 47 || asof - start60 < 60 || asof - start60 > 127) return false;
    if (typeof value.source_sha256 !== "string" || !/^[0-9a-f]{64}$/.test(value.source_sha256)) return false;
    return validSourceUrl(value.source_url, ticker);
  } catch {
    return false;
  }
}
