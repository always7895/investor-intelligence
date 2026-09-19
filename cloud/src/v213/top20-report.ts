import { fieldLabel, type FieldLocale } from "./field-labels";
import { isPublicCitationUrl } from "./public-citation";
import { validateTwoYearReturnCandidate, validateTwoYearReturnEvidence, type TwoYearReturnEvidence } from "./top20-return-evidence";
import type { StorageEnv } from "../storage";
import { pinPublicSnapshot, type PublicSnapshotView } from "./public-snapshot";
import type { ParsedQuery } from "../core";
import {
  INSUFFICIENT_EVIDENCE_MESSAGE,
  bottleneckReportToTop20Report,
  readV213BottleneckReport,
  type V213BottleneckReport,
  type V213BottleneckRecord,
} from "./bottleneck-report";
import evidencePolicy from "../../../config/v213-serenity-evidence-freshness-policy.json";

/** Trusted ALLOWLIST (PRO review 2A/B): evidence class -> freshness-policy key.
 * The worker re-verifies the report policy binding against its OWN config
 * copy; reports are never trusted for a self-reported hash.
 */
export const EVIDENCE_CLASS_POLICY_KEY: Readonly<Record<string, string>> = {
  current_state_claim: "current_state_claim_max_age_days",
  market_observation: "market_observation_max_age_days",
  market_high_confidence: "market_high_confidence_freshest_max_age_days",
  structural_claim: "structural_claim_max_age_days",
};

function canonicalJson(node: unknown): string {
  if (node === null || typeof node !== "object") return JSON.stringify(node) ?? "null";
  if (Array.isArray(node)) return `[${node.map(canonicalJson).join(",")}]`;
  const record = node as Record<string, unknown>;
  return `{${Object.keys(record).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(record[key])}`).join(",")}}`;
}

async function sha256Hex(raw: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(raw));
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

/** Re-verify the report's freshness-policy binding against the trusted
 * in-worker policy digest (any drift => reject; fail closed).
 * Exposed for test fixtures that must construct a compliant binding.
 */
export async function v213PolicyBindingMatches(
  binding: { policy_id?: unknown; policy_sha256?: unknown } | null | undefined,
): Promise<boolean> {
  if (!binding || typeof binding !== "object") return false;
  const trusted = evidencePolicy as { policy_id: string };
  if (binding.policy_id !== trusted.policy_id) return false;
  if (typeof binding.policy_sha256 !== "string" || !/^[0-9a-f]{64}$/.test(binding.policy_sha256)) return false;
  return (await sha256Hex(canonicalJson(evidencePolicy))) === binding.policy_sha256;
}

/** Canonical digest of the trusted freshness-policy config (test fixtures).
 */
export async function v213EvidencePolicyDigest(): Promise<string> {
  return sha256Hex(canonicalJson(evidencePolicy));
}

export interface EvidenceObservation {
  /** Source-state date the record's claim describes (never the retrieval time). */
  freshAsOf: string;
  /** Corpus capture time of the bundled corpus. */
  retrievedAt?: string | null;
  /** Allowlisted evidence class name (see EVIDENCE_CLASS_POLICY_KEY). */
  evidenceClass?: string;
  /** Seal time: captures may not be claimed later than assembly. */
  sealTime?: string | null;
}

/** Per-record EVIDENCE anchor gate (trusted policy windows). generated_at /
 * promoted_at / pointer as-of NEVER serve as evidence freshness.
 */
export async function v213EvidenceWithinWindow(
  observations: readonly EvidenceObservation[],
  observedAt: number = Date.now(),
): Promise<boolean> {
  if (observations.length === 0) return false;
  const trusted = evidencePolicy as Record<string, unknown>;
  for (const observation of observations) {
    const policyKey = observation.evidenceClass ? EVIDENCE_CLASS_POLICY_KEY[observation.evidenceClass] : undefined;
    if (!policyKey) return false;
    const windowDays = trusted[policyKey];
    if (typeof windowDays !== "number" || !Number.isFinite(windowDays) || windowDays <= 0) return false;
    if (typeof observation.freshAsOf !== "string" || !Number.isFinite(Date.parse(observation.freshAsOf))) return false;
    const asOfMs = Date.parse(observation.freshAsOf);
    const ageSeconds = (observedAt - asOfMs) / 1000;
    if (!Number.isFinite(ageSeconds) || ageSeconds < -300 || ageSeconds > windowDays * 86400) return false;
    const retrievedRaw = observation.retrievedAt ?? "";
    if (!retrievedRaw || !Number.isFinite(Date.parse(retrievedRaw))) return false;
    const retrievedMs = Date.parse(retrievedRaw);
    const retrievedAge = (observedAt - retrievedMs) / 1000;
    if (Number.isFinite(retrievedAge) && retrievedAge < -300) return false;
    const sealMs = observation.sealTime ? Date.parse(observation.sealTime) : NaN;
    if (Number.isFinite(sealMs) && retrievedMs > sealMs + 300_000) return false;
  }
  return true;
}

/** TEST-ONLY evidence disclosure (PRO review C: honesty only, no admission
 * change; rankings are not production-qualified live evidence).
 */
export function v213TestOnlyDisclosure(captureAt: string | null | undefined, locale: FieldLocale = "bilingual"): string {
  const stamp = captureAt ?? "-";
  if (locale === "en") {
    return `[TEST-ONLY display] Rankings below were produced by the licensed test-qualification path; data captured ${stamp} UTC; parts of the original disclosures date from 2025 and have not undergone formal current-state verification.`;
  }
  if (locale === "zh-TW") {
    return `【TEST-ONLY 測試展示】以下排名與分數經測試資格流程產生；資料擷取於 ${stamp} UTC，部分原始披露為 2025 年，尚未完成正式現況驗證。`;
  }
  return `【TEST-ONLY 測試展示】以下排名經測試資格流程產生；資料擷取於 ${stamp} UTC，部分原始披露為 2025 年，尚未完成正式現況驗證。 / [TEST-ONLY display] Rankings produced by the licensed test-qualification path; captured ${stamp} UTC; parts of the original disclosures date from 2025, formal current-state verification pending.`;
}

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
  if (!(await v213PolicyBindingMatches(report.freshness_policy))) return null;
  const bytes = new TextEncoder().encode(raw);
  if (bytes.byteLength > 2097152) return null;
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  const reportSha256 = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
  for (const row of report.records) {
    Object.freeze(row.current_order_source_urls); Object.freeze(row.future_order_source_urls);
    if (row.two_year_return_evidence) Object.freeze(row.two_year_return_evidence);
    Object.freeze(row);
  }
  Object.freeze(report.records); Object.freeze(report.display_columns); Object.freeze(report);
  reportReferences.set(report, Object.freeze({ snapshot: view.kind === "legacy" ? "legacy" : `s:${view.runId}`, reportSha256 }));
  return report;
}

export const V213_STALE_RECORDS_MESSAGE = "公司資料取得時間已過期或無效，不能以新的報告日期掩蓋舊資料。 / Company retrieval time is stale or invalid.";

/** Shared execution-clock gate. Retrieval freshness does not certify quote timeliness. */
export function v213TimesAreFresh(
  env: Pick<V213Top20Env, "V21_TOP20_MAX_AGE_SECONDS">,
  times: readonly (string | null)[], observedAt = Date.now(),
): boolean {
  const limit = Math.max(300, Math.min(86400, Number(env.V21_TOP20_MAX_AGE_SECONDS ?? "7200") || 7200));
  return times.length > 0 && times.every(value => {
    const age = (observedAt - Date.parse(value ?? "")) / 1000;
    return Number.isFinite(age) && age >= -300 && age <= limit;
  });
}

export async function loadV213FreshTop20Report(
  env: V213Top20Env,
  query: ParsedQuery,
): Promise<V213Top20Report | string | null> {
  if (query.ticker || query.intent !== "ranking" || !/(?:top\s*20|前\s*20|排行|排名)/i.test(query.normalized)) return null;
  const view = await pinPublicSnapshot(env);

  // Sealed run-bound views are governed by the bottleneck policy: a qualified
  // sealed bottleneck report is the only publication authority; legacy rows are
  // never borrowed, and missing or evidence-lacking payloads fail closed.
  if (view.integrity === "sealed") {
    const bottleneck = await readV213BottleneckReport(view);
    if (bottleneck && bottleneck.status === "QUALIFIED" && bottleneck.records.length > 0) {
    const sealStamp = await view.text(["last_successful_pipeline_timestamp"]);
    if (!v213TimesAreFresh(env, [sealStamp, bottleneck.generated_at])) {
      return "七欄 Top20 資料已過期或時間無效，請等待新鮮公開資料。 / Seven-field Top20 is stale or invalid; fresh public data is required.";
    }
    if (!(await v213PolicyBindingMatches(bottleneck.freshness_policy))) return V213_STALE_RECORDS_MESSAGE;
    if (!(await v213EvidenceWithinWindow(bottleneck.records.map(row => ({
      freshAsOf: row.orders_state_as_of,
      retrievedAt: row.retrieved_at,
      evidenceClass: row.evidence_class,
      sealTime: bottleneck.generated_at,
    }))))) return V213_STALE_RECORDS_MESSAGE;
    const sealedReport = bottleneckReportToTop20Report(bottleneck);
    const sealedRaw = await view.text(["v213:top20-report:latest", "v213:bottleneck-report:latest"]);
    const sealBytes = new TextEncoder().encode(sealedRaw ?? "");
    const sealDigest = await crypto.subtle.digest("SHA-256", sealBytes);
    const sealedSha = Array.from(new Uint8Array(sealDigest), byte => byte.toString(16).padStart(2, "0")).join("");
    for (const row of sealedReport.records) {
      Object.freeze(row.current_order_source_urls); Object.freeze(row.future_order_source_urls);
      if (row.two_year_return_evidence) Object.freeze(row.two_year_return_evidence);
      Object.freeze(row);
    }
    Object.freeze(sealedReport.records); Object.freeze(sealedReport.display_columns); Object.freeze(sealedReport);
      reportReferences.set(sealedReport, Object.freeze({ snapshot: `s:${view.runId}`, reportSha256: sealedSha }));
      return sealedReport;
    }
  }

  // Sealed views without qualified bottleneck authority still allow the
  // certified seven-field sealed report; pointerless unsealed single-report
  // writes carry no publication authority under the takeover policy.
  const report = await readV213Top20Report(view);
  if (view.integrity === "legacy" && view.runId === null && report) {
    return INSUFFICIENT_EVIDENCE_MESSAGE;
  }
  if (!report) {
    // A present-but-rejected pointer (tampered seal / broken manifest) is a
    // liveness failure, not a bootstrap state: fail closed to INSUFFICIENT.
    // Only an absent-pointer bootstrap keeps the pre-publication message.
    if (view.integrity === "sealed" || view.kind === "invalid") return INSUFFICIENT_EVIDENCE_MESSAGE;
    return "七欄 Top20 報告尚未通過驗證；不退回五欄。 / Seven-field Top20 unavailable; no five-field fallback.";
  }
  const stamp = await view.text(["last_successful_pipeline_timestamp"]);
  if (!v213TimesAreFresh(env, [stamp, report.generated_at])) return "七欄 Top20 資料已過期或時間無效，請等待新鮮公開資料。 / Seven-field Top20 is stale or invalid; fresh public data is required.";
  if (!(await v213EvidenceWithinWindow(report.records.map(row => ({
    freshAsOf: row.orders_state_as_of,
    retrievedAt: row.retrieved_at,
    evidenceClass: row.evidence_class,
    sealTime: report.generated_at,
  }))))) return V213_STALE_RECORDS_MESSAGE;
  return report;
}

export async function v213Top20ReportAnswer(env: V213Top20Env, query: ParsedQuery): Promise<string | null> {
  const result = await loadV213FreshTop20Report(env, query);
  if (!result || typeof result === "string") return result;
  if (!(await v213EvidenceWithinWindow(result.records.map(row => ({
    freshAsOf: row.orders_state_as_of,
    retrievedAt: row.retrieved_at,
    evidenceClass: row.evidence_class,
    sealTime: result.generated_at,
  }))))) return V213_STALE_RECORDS_MESSAGE;
  const locale = v213FieldLocale(env.V213_FIELD_LOCALE);
  return [v213TestOnlyDisclosure(result.evidence_capture_at, locale), formatV213Top20Report(result, locale)].join("\n");
}

export interface V213Top20ReportRecord {
  schema_version: 2;
  rank: number;
  ticker: string;
  /** Official public company name from the accepted universe; public data, not a rights statement. */
  name: string;
  long_term_return_pct: number | null;
  short_term_return_pct: number | null;
  two_year_total_return_pct?: number | null;
  two_year_return_evidence?: TwoYearReturnEvidence | null;
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
  /** Source-state date the cited disclosure describes (never retrieval time). */
  orders_state_as_of: string;
  /** Allowlisted evidence class (EVIDENCE_CLASS_POLICY_KEY). */
  evidence_class: string;
  /** Freshness-policy key the class maps to; re-validated against the allowlist. */
  freshness_policy_key: string;
  /** Licensed test-only qualification provenance (honesty, not admission). */
  test_only_admission: true;
  provider_scope: "public_only";
  owner_watchlist_inherited: false;
}

export interface V213Top20Report {
  schema_version: 2;
  product_version: "2.1.3";
  generated_at: string;
  /** Binds the exact freshness-policy bytes (digest), not the filename. */
  freshness_policy: { policy_id: string; policy_sha256: string };
  /** Real offline corpus capture time; never re-labelled to the live clock. */
  evidence_capture_at: string;
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

const REQUIRED_RECORD_KEYS = new Set([
  "schema_version", "rank", "ticker", "name", "long_term_return_pct", "short_term_return_pct",
  "industry", "profit_summary", "current_orders", "future_orders_estimate",
  "long_term_window", "short_term_window", "market_source", "profit_source",
  "orders_as_of", "orders_confidence", "current_order_source_urls",
  "future_order_source_urls", "numeric_total_order_estimate_prohibited", "retrieved_at",
  "orders_state_as_of", "evidence_class", "freshness_policy_key", "test_only_admission",
  "provider_scope", "owner_watchlist_inherited",
]);

const OPTIONAL_RECORD_KEYS = new Set([
  "two_year_total_return_pct",
  "two_year_return_evidence",
]);

const RECORD_KEYS = REQUIRED_RECORD_KEYS;

const DOCUMENT_KEYS = new Set([
  "schema_version", "product_version", "generated_at", "freshness_policy",
  "evidence_capture_at", "display_columns",
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

function parseTop20ReportWithBounds(raw: unknown, exactTwenty: boolean): V213Top20Report | null {
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
    !doc.freshness_policy || typeof doc.freshness_policy !== "object" || Array.isArray(doc.freshness_policy) ||
    typeof (doc.freshness_policy as { policy_id?: unknown }).policy_id !== "string" ||
    typeof (doc.freshness_policy as { policy_sha256?: unknown }).policy_sha256 !== "string" ||
    !/^[0-9a-f]{64}$/.test((doc.freshness_policy as { policy_sha256: string }).policy_sha256) ||
    typeof doc.evidence_capture_at !== "string" || !Number.isFinite(Date.parse(doc.evidence_capture_at)) ||
    !Array.isArray(doc.display_columns) ||
    doc.display_columns.length !== V213_TOP20_DISPLAY_COLUMNS.length ||
    doc.display_columns.some((value, index) => value !== V213_TOP20_DISPLAY_COLUMNS[index]) ||
    !Array.isArray(doc.records) ||
    (exactTwenty ? doc.records.length !== 20 : doc.records.length < 1 || doc.records.length > 20)
  ) return null;

  const records: V213Top20ReportRecord[] = [];
  const seen = new Set<string>();
  for (let index = 0; index < doc.records.length; index += 1) {
    const rawRecord = doc.records[index];
    if (!rawRecord || typeof rawRecord !== "object" || Array.isArray(rawRecord)) return null;
    const item = rawRecord as Record<string, unknown>;
    const itemKeys = Object.keys(item);
    if (!itemKeys.every(key => REQUIRED_RECORD_KEYS.has(key) || OPTIONAL_RECORD_KEYS.has(key))) return null;
    if (![...REQUIRED_RECORD_KEYS].every(key => key in item)) return null;
    const ticker = typeof item.ticker === "string" ? item.ticker.toUpperCase() : "";
    if (
      item.schema_version !== 2 || item.rank !== index + 1 ||
      !TICKER_RE.test(ticker) || seen.has(ticker) ||
      !lineSafeText(item.name, 120) ||
      !returnPercentOrNull(item.long_term_return_pct) || !returnPercentOrNull(item.short_term_return_pct) ||
      !lineSafeText(item.industry, 100) ||
      !lineSafeText(item.profit_summary, 120) ||
      !lineSafeText(item.current_orders, 150) || !lineSafeText(item.future_orders_estimate, 170) ||
      item.long_term_window !== "2y_cagr" || item.short_term_window !== "6m_price_return" ||
      item.market_source !== "yfinance" || item.profit_source !== "sec_edgar" ||
      !orderEvidenceSemantics(item) ||
      item.numeric_total_order_estimate_prohibited !== true ||
      item.provider_scope !== "public_only" || item.owner_watchlist_inherited !== false ||
      typeof item.retrieved_at !== "string" || !Number.isFinite(Date.parse(item.retrieved_at)) ||
      typeof item.orders_state_as_of !== "string" || !Number.isFinite(Date.parse(item.orders_state_as_of)) ||
      typeof item.evidence_class !== "string" || EVIDENCE_CLASS_POLICY_KEY[item.evidence_class] === undefined ||
      item.freshness_policy_key !== EVIDENCE_CLASS_POLICY_KEY[item.evidence_class] ||
      item.test_only_admission !== true
    ) return null;

    let twoYearTotalReturnPct: number | null | undefined = undefined;
    let twoYearReturnEvidence: TwoYearReturnEvidence | null | undefined = undefined;

    if ("two_year_total_return_pct" in item || "two_year_return_evidence" in item) {
      const rawPct = item.two_year_total_return_pct;
      const rawEv = item.two_year_return_evidence;

      // Reject scalar-only injected value without evidence and dates
      if (rawPct !== undefined && rawPct !== null) {
        if (!rawEv) return null;
      }

      if (rawEv !== undefined && rawEv !== null) {
        const evValidation = validateTwoYearReturnCandidate(
          rawEv,
          ticker,
          typeof item.retrieved_at === "string" ? item.retrieved_at : undefined,
        );
        if (!evValidation.valid) return null;
        twoYearReturnEvidence = rawEv as TwoYearReturnEvidence;
        if (rawPct !== undefined && rawPct !== null) {
          if (typeof rawPct !== "number" || !Number.isFinite(rawPct) || rawPct < -100) return null;
          if (Math.abs(rawPct - evValidation.totalReturnPct!) > 0.05) return null;
          twoYearTotalReturnPct = rawPct;
        } else {
          twoYearTotalReturnPct = evValidation.totalReturnPct;
        }
      } else if (rawPct === null) {
        if (rawEv !== null && rawEv !== undefined) return null;
        twoYearTotalReturnPct = null;
        twoYearReturnEvidence = null;
      }
    }

    seen.add(ticker);
    const cleanedRecord: V213Top20ReportRecord = {
      ...(item as unknown as V213Top20ReportRecord),
      ticker,
    };
    if (twoYearTotalReturnPct !== undefined) cleanedRecord.two_year_total_return_pct = twoYearTotalReturnPct;
    if (twoYearReturnEvidence !== undefined) cleanedRecord.two_year_return_evidence = twoYearReturnEvidence;
    records.push(cleanedRecord);
  }
  return { ...(doc as unknown as V213Top20Report), records };
}

export function parseV213Top20Report(raw: unknown): V213Top20Report | null {
  return parseTop20ReportWithBounds(raw, true);
}

// Sealed bottleneck-policy projections may carry 1..20 records; the strict
// twenty-record contract remains the default entry point.
export function parseV213BoundedTop20Report(raw: unknown): V213Top20Report | null {
  return parseTop20ReportWithBounds(raw, false);
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
