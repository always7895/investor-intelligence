/** Report-age bound shared with the Python publisher (config/v213-top20-report-freshness-v1.json).
 * Seal liveness (V21_TOP20_MAX_AGE_SECONDS) proves the pipeline ran; this bound limits how long one report, and
 * the row times it carries, may be re-sealed and shown. Standalone so every reader can import it without cycles. */
import reportFreshness from "../../../config/v213-top20-report-freshness-v1.json";

export function v213ReportMaxAgeSeconds(): number {
  const hours = Number((reportFreshness as { report_max_age_hours?: unknown }).report_max_age_hours);
  return Math.max(3600, Math.min(86400, Number.isFinite(hours) ? hours * 3600 : 7200));
}

/** Every time is a real report or row time within the report bound, never in the future. */
export function v213ReportAgeFresh(times: readonly (string | null | undefined)[], observedAt = Date.now()): boolean {
  const limit = v213ReportMaxAgeSeconds();
  return times.length > 0 && times.every(value => {
    const age = (observedAt - Date.parse(value ?? "")) / 1000;
    return Number.isFinite(age) && age >= -300 && age <= limit;
  });
}
