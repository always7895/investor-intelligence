import rotationPolicy from "../../../config/industry-rotation-v1.json";
import { MACRO_PRODUCT_KEY, macroOverviewState } from "./macro-industry-product";
import type { PublicSnapshotView } from "./public-snapshot";
import { v213TimesAreFresh, type V213Top20Env } from "./top20-report";
import { validateCompanyDataReport } from "./deep-analysis";
import type { PotentialRanking } from "./potential-ranking";

const DAY_MS = 86_400_000;
const taipeiDate = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Taipei", year: "numeric", month: "2-digit", day: "2-digit",
});
const object = (raw: unknown): Record<string, unknown> | null =>
  raw !== null && typeof raw === "object" && !Array.isArray(raw) ? raw as Record<string, unknown> : null;

function dayNumber(raw: unknown): number {
  if (typeof raw !== "string" || !/^(?!0000)\d{4}-\d{2}-\d{2}$/.test(raw)) return NaN;
  const value = Date.parse(`${raw}T00:00:00Z`);
  return Number.isFinite(value) && new Date(value).toISOString().slice(0, 10) === raw ? value / DAY_MS : NaN;
}

function taipeiDayNumber(time: number): number {
  const parts = taipeiDate.formatToParts(new Date(time));
  const part = (type: string) => parts.find(value => value.type === type)!.value;
  return dayNumber(`${part("year")}-${part("month")}-${part("day")}`);
}

function instant(raw: unknown): number {
  if (typeof raw !== "string" || !/^(?!0000)\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?Z$/.test(raw)) return NaN;
  const value = Date.parse(raw);
  return Number.isFinite(value) && new Date(value).toISOString() === (raw.includes(".") ? raw : raw.replace("Z", ".000Z")) ? value : NaN;
}

/** Producer policies use date.today() on the Taipei host, including the last permitted day.
 * Fiscal periods and filing dates are not calculation clocks. */
export function macroCalculationDayIsFresh(raw: unknown, maxAgeDays: number, generatedAt: string, now = Date.now()): boolean {
  const day = dayNumber(raw);
  const today = taipeiDayNumber(now);
  const generated = instant(generatedAt);
  return Number.isFinite(day) && Number.isFinite(generated) && day <= taipeiDayNumber(generated)
    && day <= today && today - day <= maxAgeDays;
}

/** The producer copies order coverage from company_deep_report.load_reports (seven days).
 * A still-valid 45-day rotation cannot extend that calculation window. */
export function freshPotentialCompanyData(ranking: PotentialRanking, generatedAt: string, now = Date.now()): PotentialRanking {
  const reports = Object.fromEntries(Object.entries(ranking.reports).filter(([ticker, raw]) => {
    const report = validateCompanyDataReport(raw, ticker);
    return report && macroCalculationDayIsFresh(report.as_of, 7, generatedAt, now);
  }));
  return { ...ranking, reports, records: ranking.records.map(row => Object.hasOwn(reports, row.ticker)
    ? row : { ...row, orders: null, orders_freshness: "STALE_OR_UNVERIFIED" as const }) };
}

/** A fresh publication carrier cannot renew its original rotation basis. Observe the clock only
 * after all awaited reads so an in-flight KV read cannot preserve an expired seal or calendar day. */
export async function loadFreshMacroDocument(env: V213Top20Env, view: PublicSnapshotView): Promise<Record<string, unknown> | null> {
  if (view.integrity !== "sealed") return null;
  const raw = await view.json<unknown>([MACRO_PRODUCT_KEY]);
  const seal = await view.text(["last_successful_pipeline_timestamp"]);
  const now = Date.now();
  const doc = object(raw);
  if (!doc || typeof doc.generated_at !== "string" || !Number.isFinite(instant(doc.generated_at)) || !Number.isFinite(instant(seal))
    || !v213TimesAreFresh(env, [seal, doc.generated_at], now)
    || instant(doc.generated_at) > instant(seal) + 300_000) return null;

  const basis = object(doc.data_basis);
  const ranking = object(doc.potential_ranking);
  if (doc.potential_ranking != null && !ranking) return null;
  if (!basis) {
    // A valid, empty shortfall has no rotation facts to age; absence must remain an honest zero.
    const state = macroOverviewState(doc);
    const deep = object(doc.deep_analyses);
    return doc.data_basis == null && !ranking && (doc.deep_analyses == null || (deep && Object.keys(deep).length === 0))
      && state.kind === "VALID" && state.overview.qualified_count === 0 && state.overview.industries.length === 0 ? doc : null;
  }
  const maxDays = rotationPolicy.thresholds.rotation_max_age_days;
  if (!macroCalculationDayIsFresh(basis.as_of, maxDays, doc.generated_at, now)) return null;
  if (ranking && (ranking.as_of !== basis.as_of || !macroCalculationDayIsFresh(ranking.as_of, maxDays, doc.generated_at, now))) return null;
  return doc;
}
