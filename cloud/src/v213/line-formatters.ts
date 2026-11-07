/** Shared LINE display-only numeric and timestamp presentation. Never mutates source data. */
const CURRENCY: Readonly<Record<string, string>> = Object.freeze({
  USD: "US$", TWD: "NT$", NTD: "NT$", JPY: "¥", HKD: "HK$", KRW: "₩",
  EUR: "€", GBP: "£",
});
const finite = (v: number): boolean => Number.isFinite(v);
const fixed = (n: number, digits: number): string => n.toLocaleString("en-US", {
  useGrouping: true, minimumFractionDigits: digits, maximumFractionDigits: digits,
});
/** Thousands separators start at 10,000; smaller integers stay ungrouped. */
export function formatCount(n: number): string {
  if (!finite(n)) return "未提供";
  return Number.isInteger(n) && Math.abs(n) >= 10000 ? fixed(n, 0) : String(n);
}
/** Display percent values are percentage points by default; pass ratio=true for a 0..1 ratio. */
export function formatPercent(n: number, ratio = false, signed = true): string {
  if (!finite(n)) return "未提供";
  const pct = ratio ? n * 100 : n;
  const display = Object.is(pct, -0) ? 0 : pct;
  const precision = Math.abs(display) < 10 ? 1 : 0;
  return `${signed && display >= 0 ? "+" : ""}${fixed(display, precision)}%`;
}
/** Compact large amounts (ten-thousands and hundreds of millions); money always has an explicit currency. */
export function formatCurrency(n: number, currency = "USD", decimals = 2): string {
  if (!finite(n)) return "未提供";
  const prefix = CURRENCY[currency.toUpperCase()] ?? `${currency} `;
  const amount = Math.abs(n);
  const divisor = amount >= 100_000_000 ? 100_000_000 : amount >= 10_000 ? 10_000 : 1;
  const suffix = divisor === 100_000_000 ? "億" : divisor === 10_000 ? "萬" : "";
  const digits = divisor === 1 ? decimals : (n / divisor % 1 === 0 ? 0 : 1);
  return `${prefix}${fixed(n / divisor, digits)}${suffix}`;
}
/** Date-only values are never converted across time zones. */
export function formatDate(value: string | number | Date | null | undefined): string {
  if (value == null || value === "") return "日期未揭露";
  const raw = value instanceof Date ? (Number.isFinite(value.getTime()) ? value.toISOString().slice(0, 10) : "") : String(value);
  const candidate = /^\d{4}-\d{2}-\d{2}/.exec(raw)?.[0];
  if (!candidate || !Number.isFinite(Date.parse(candidate + "T00:00:00Z"))
      || new Date(candidate + "T00:00:00Z").toISOString().slice(0, 10) !== candidate) return "日期未揭露";
  return candidate;
}
/** Timestamp follows the user-selected Taiwan display timezone, with explicit localization. */
export function formatTaipeiTimestamp(value: string | number | Date | null | undefined): string {
  if (value == null || value === "") return "時間未知";
  const date = value instanceof Date ? value : new Date(value);
  if (!Number.isFinite(date.getTime())) return "時間未知";
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Taipei", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).formatToParts(date);
  const part = (type: string) => parts.find(item => item.type === type)?.value ?? "--";
  return `${part("month")}-${part("day")} ${part("hour")}:${part("minute")}（台北）`;
}
