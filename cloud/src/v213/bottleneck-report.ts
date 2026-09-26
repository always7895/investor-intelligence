import type { StorageEnv } from "../storage";
import { pinPublicSnapshot, type PublicSnapshotView } from "./public-snapshot";
import type { ParsedQuery } from "../core";
import type { FieldLocale } from "./field-labels";
import type { V213Top20Env, V213Top20Report, V213Top20ReportRecord } from "./top20-report";

export const INSUFFICIENT_EVIDENCE_MESSAGE =
  "系統瓶頸爆發 Top20 核心證據不足（INSUFFICIENT_EVIDENCE）；候選標的尚未取得獨立一級瓶頸與股權捕捉佐證。依政策扣留排名，不退回舊榜單、不補零至20名。 / Top20 bottleneck evidence insufficient; no legacy fallback.";

export interface V213BottleneckClaimsAudit {
  supported_claim_count: number;
  conflicted_claim_count: number;
  all_material_claims_supported: boolean;
}

export interface V213BottleneckRecord {
  schema_version: 1;
  rank: number;
  ticker: string;
  name: string;
  industry: string;
  bottleneck_role: string;
  system_bottleneck_explosion_score: number;
  dependency_score: number;
  scarcity_score: number;
  pricing_power_score: number;
  company_capture_score: number;
  long_term_return_pct?: number | null;
  short_term_return_pct?: number | null;
  profit_summary: string;
  current_orders: string;
  future_orders_estimate: string;
  current_order_source_urls?: string[];
  future_order_source_urls?: string[];
  retrieved_at: string;
  /** Source-state date the cited disclosure describes (never retrieval time). */
  orders_state_as_of: string;
  /** Allowlisted evidence class (top20-report EVIDENCE_CLASS_POLICY_KEY). */
  evidence_class: string;
  /** Freshness-policy key bound by the class. */
  freshness_policy_key: string;
  /** Licensed test-only qualification provenance (honesty, not admission). */
  test_only_admission: true;
  admission_status: string;
  score_qualified: boolean | null;
  candidate_assessment_mode: string;
  claims_audit: V213BottleneckClaimsAudit;
}

export interface V213BottleneckReport {
  schema_version: 1;
  policy_id: "system-bottleneck-explosion-v1";
  product_version: "2.1.3";
  status: "QUALIFIED" | "INSUFFICIENT_EVIDENCE";
  publication_status: "NOT_PUBLICATION_QUALIFIED" | "PUBLICATION_QUALIFIED";
  live_qualification: "DEFERRED" | "ACTIVE";
  generated_at: string;
  /** Exact freshness-policy binding (digest), re-verified against worker config. */
  freshness_policy: { policy_id: string; policy_sha256: string };
  /** Real offline corpus capture time; never re-labelled to the live clock. */
  evidence_capture_at: string;
  admitted_count: number;
  ranked_count: number;
  total_evaluated: number;
  records: V213BottleneckRecord[];
  provider_scope: "public_only";
}

const TICKER_RE = /^[A-Z0-9][A-Z0-9.-]{0,14}$/;

function lineSafeText(value: unknown, max: number): value is string {
  return typeof value === "string" && value.trim().length > 0 && value.length <= max && !value.includes("｜") && !/[\r\n]/.test(value);
}

function isValidIsoDate(raw: unknown): raw is string {
  if (typeof raw !== "string") return false;
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?Z$/.test(raw)) return false;
  const ms = Date.parse(raw);
  if (!Number.isFinite(ms)) return false;
  const iso = new Date(ms).toISOString();
  const expected = raw.includes(".") ? raw : raw.replace("Z", ".000Z");
  return iso === expected;
}

export function parseV213BottleneckReport(raw: unknown): V213BottleneckReport | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const doc = raw as Record<string, unknown>;

  if (
    doc.schema_version !== 1 ||
    doc.policy_id !== "system-bottleneck-explosion-v1" ||
    doc.product_version !== "2.1.3" ||
    doc.provider_scope !== "public_only" ||
    !isValidIsoDate(doc.generated_at) ||
    !doc.freshness_policy || typeof doc.freshness_policy !== "object" || Array.isArray(doc.freshness_policy) ||
    typeof (doc.freshness_policy as { policy_id?: unknown }).policy_id !== "string" ||
    typeof (doc.freshness_policy as { policy_sha256?: unknown }).policy_sha256 !== "string" ||
    !/^[0-9a-f]{64}$/.test((doc.freshness_policy as { policy_sha256: string }).policy_sha256) ||
    !isValidIsoDate(doc.evidence_capture_at) ||
    !Array.isArray(doc.records) ||
    doc.records.length > 20
  ) {
    return null;
  }

  const status = doc.status;
  if (status !== "QUALIFIED" && status !== "INSUFFICIENT_EVIDENCE") return null;

  const pubStatus = doc.publication_status;
  if (pubStatus !== "NOT_PUBLICATION_QUALIFIED" && pubStatus !== "PUBLICATION_QUALIFIED") return null;

  const liveQual = doc.live_qualification;
  if (liveQual !== "DEFERRED" && liveQual !== "ACTIVE") return null;

  if (
    typeof doc.admitted_count !== "number" || !Number.isInteger(doc.admitted_count) ||
    typeof doc.ranked_count !== "number" || !Number.isInteger(doc.ranked_count) ||
    typeof doc.total_evaluated !== "number" || !Number.isInteger(doc.total_evaluated)
  ) {
    return null;
  }

  const admittedCount = doc.admitted_count;
  const rankedCount = doc.ranked_count;
  const totalEvaluated = doc.total_evaluated;

  if (admittedCount < 0 || rankedCount < 0 || totalEvaluated < 0) return null;
  if (totalEvaluated < admittedCount || admittedCount < rankedCount) return null;
  if (rankedCount > 20 || rankedCount !== doc.records.length) return null;

  const records: V213BottleneckRecord[] = [];
  const seen = new Set<string>();

  for (let i = 0; i < doc.records.length; i++) {
    const rawRow = doc.records[i];
    if (!rawRow || typeof rawRow !== "object" || Array.isArray(rawRow)) return null;
    const r = rawRow as Record<string, unknown>;

    const ticker = typeof r.ticker === "string" ? r.ticker.toUpperCase().trim() : "";
    if (!TICKER_RE.test(ticker) || seen.has(ticker)) return null;
    seen.add(ticker);

    if (
      r.schema_version !== 1 ||
      r.rank !== i + 1 ||
      !lineSafeText(r.name, 120) ||
      !lineSafeText(r.industry, 100) ||
      !lineSafeText(r.bottleneck_role, 50) ||
      typeof r.system_bottleneck_explosion_score !== "number" ||
      !Number.isFinite(r.system_bottleneck_explosion_score) ||
      r.system_bottleneck_explosion_score < 0 ||
      r.system_bottleneck_explosion_score > 100 ||
      typeof r.dependency_score !== "number" ||
      !Number.isFinite(r.dependency_score) ||
      r.dependency_score < 0 ||
      r.dependency_score > 12 ||
      typeof r.scarcity_score !== "number" ||
      !Number.isFinite(r.scarcity_score) ||
      r.scarcity_score < 0 ||
      r.scarcity_score > 14 ||
      typeof r.pricing_power_score !== "number" ||
      !Number.isFinite(r.pricing_power_score) ||
      r.pricing_power_score < 0 ||
      r.pricing_power_score > 12 ||
      typeof r.company_capture_score !== "number" ||
      !Number.isFinite(r.company_capture_score) ||
      r.company_capture_score < 0 ||
      r.company_capture_score > 12 ||
      !lineSafeText(r.profit_summary, 120) ||
      !lineSafeText(r.current_orders, 150) ||
      !lineSafeText(r.future_orders_estimate, 170) ||
      !isValidIsoDate(r.retrieved_at) ||
      !isValidIsoDate(r.orders_state_as_of) ||
      typeof r.evidence_class !== "string" ||
      typeof r.freshness_policy_key !== "string" ||
      r.test_only_admission !== true ||
      r.admission_status !== "ADMITTED" ||
      r.score_qualified !== true ||
      r.candidate_assessment_mode !== "RANKING_QUALIFIED"
    ) {
      return null;
    }

    // Monotonic score check
    if (i > 0 && (r.system_bottleneck_explosion_score as number) > (doc.records[i - 1] as any).system_bottleneck_explosion_score) {
      return null;
    }

    const audit = r.claims_audit as Record<string, unknown> | undefined;
    if (!audit || typeof audit !== "object") return null;
    if (
      typeof audit.supported_claim_count !== "number" ||
      !Number.isInteger(audit.supported_claim_count) ||
      audit.supported_claim_count <= 0 ||
      typeof audit.conflicted_claim_count !== "number" ||
      typeof audit.all_material_claims_supported !== "boolean" ||
      audit.conflicted_claim_count > 0 ||
      !audit.all_material_claims_supported
    ) {
      return null;
    }

    records.push({
      schema_version: 1,
      rank: r.rank as number,
      ticker,
      name: r.name as string,
      industry: r.industry as string,
      bottleneck_role: r.bottleneck_role as string,
      system_bottleneck_explosion_score: r.system_bottleneck_explosion_score as number,
      dependency_score: r.dependency_score as number,
      scarcity_score: r.scarcity_score as number,
      pricing_power_score: r.pricing_power_score as number,
      company_capture_score: r.company_capture_score as number,
      long_term_return_pct: typeof r.long_term_return_pct === "number" ? r.long_term_return_pct : null,
      short_term_return_pct: typeof r.short_term_return_pct === "number" ? r.short_term_return_pct : null,
      profit_summary: r.profit_summary as string,
      current_orders: r.current_orders as string,
      future_orders_estimate: r.future_orders_estimate as string,
      current_order_source_urls: Array.isArray(r.current_order_source_urls) ? (r.current_order_source_urls as string[]) : [],
      future_order_source_urls: Array.isArray(r.future_order_source_urls) ? (r.future_order_source_urls as string[]) : [],
      retrieved_at: r.retrieved_at as string,
      orders_state_as_of: r.orders_state_as_of as string,
      evidence_class: r.evidence_class as string,
      freshness_policy_key: r.freshness_policy_key as string,
      test_only_admission: true,
      admission_status: r.admission_status as string,
      score_qualified: true,
      candidate_assessment_mode: "RANKING_QUALIFIED",
      claims_audit: {
        supported_claim_count: audit.supported_claim_count as number,
        conflicted_claim_count: audit.conflicted_claim_count as number,
        all_material_claims_supported: audit.all_material_claims_supported as boolean,
      },
    });
  }

  return {
    schema_version: 1,
    policy_id: "system-bottleneck-explosion-v1",
    product_version: "2.1.3",
    status: status as "QUALIFIED" | "INSUFFICIENT_EVIDENCE",
    publication_status: pubStatus as "NOT_PUBLICATION_QUALIFIED" | "PUBLICATION_QUALIFIED",
    live_qualification: liveQual as "DEFERRED" | "ACTIVE",
    generated_at: doc.generated_at as string,
    freshness_policy: doc.freshness_policy as { policy_id: string; policy_sha256: string },
    evidence_capture_at: doc.evidence_capture_at as string,
    admitted_count: admittedCount,
    ranked_count: records.length,
    total_evaluated: totalEvaluated,
    records,
    provider_scope: "public_only",
  };
}

export function bottleneckReportToTop20Report(report: V213BottleneckReport): V213Top20Report {
  const records: V213Top20ReportRecord[] = report.records.map(r => ({
    schema_version: 2,
    rank: r.rank,
    ticker: r.ticker,
    name: r.name,
    industry: r.industry,
    profit_summary: r.profit_summary,
    current_orders: r.current_orders,
    future_orders_estimate: r.future_orders_estimate,
    long_term_return_pct: r.long_term_return_pct ?? null,
    short_term_return_pct: r.short_term_return_pct ?? null,
    two_year_total_return_pct: null,
    two_year_return_evidence: null,
    long_term_window: "2y_cagr",
    short_term_window: "6m_price_return",
    market_source: "yfinance",
    profit_source: "sec_edgar",
    orders_as_of: r.orders_state_as_of,
    orders_state_as_of: r.orders_state_as_of,
    orders_confidence: r.current_orders && r.current_orders !== "未揭露（無可靠公開訂單數字）" ? "EVIDENCE_BOUND" : "UNAVAILABLE",
    current_order_source_urls: Array.isArray(r.current_order_source_urls) ? r.current_order_source_urls : [],
    future_order_source_urls: Array.isArray(r.future_order_source_urls) ? r.future_order_source_urls : [],
    numeric_total_order_estimate_prohibited: true,
    retrieved_at: r.retrieved_at,
    evidence_class: r.evidence_class,
    freshness_policy_key: r.freshness_policy_key,
    test_only_admission: r.test_only_admission,
    provider_scope: "public_only",
    owner_watchlist_inherited: false,
  }));

  return {
    schema_version: 2,
    product_version: "2.1.3",
    generated_at: report.generated_at,
    freshness_policy: report.freshness_policy,
    evidence_capture_at: report.evidence_capture_at,
    display_columns: [
      "股票",
      "長期投資報酬率（近2年年化）",
      "短期投資報酬率（近6個月）",
      "行業別",
      "獲利簡述",
      "公司現在訂單",
      "未來訂單預估",
    ],
    long_term_definition: "trailing_2y_adjusted_close_cagr",
    short_term_definition: "trailing_6m_adjusted_close_price_return",
    provider_scope: "public_only",
    owner_watchlist_inherited: false,
    records,
  };
}

export function formatV213BottleneckReport(
  report: V213BottleneckReport,
  locale: FieldLocale = "zh-TW",
): string {
  if (report.status === "INSUFFICIENT_EVIDENCE" || report.records.length === 0) {
    return INSUFFICIENT_EVIDENCE_MESSAGE;
  }
  const headers = ["排名", "股票", "瓶頸角色", "爆發評分", "行業別", "現在訂單", "未來預估"];
  const rows = report.records.map(r => [
    `#${r.rank}`,
    r.ticker,
    r.bottleneck_role,
    `${r.system_bottleneck_explosion_score.toFixed(1)}分`,
    r.industry,
    r.current_orders,
    r.future_orders_estimate,
  ].join("｜"));
  return [headers.join("｜"), ...rows].join("\n");
}

export async function readV213BottleneckReport(view: PublicSnapshotView): Promise<V213BottleneckReport | null> {
  // Reject unsealed views: unsealed keys have no publication authority
  if (view.integrity !== "sealed" || view.kind !== "snapshot") return null;
  const raw = await view.text(["v213:top20-report:latest", "v213:bottleneck-report:latest"]);
  if (!raw || raw.length > 2097152) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  return parseV213BottleneckReport(parsed);
}

export async function v213BottleneckTop20Answer(
  env: V213Top20Env,
  query: ParsedQuery,
): Promise<string | null> {
  if (query.ticker || query.intent !== "ranking" || !/(?:top\s*20|前\s*20|排行|排名)/i.test(query.normalized)) {
    return null;
  }
  const view = await pinPublicSnapshot(env);
  const bottleneckReport = await readV213BottleneckReport(view);
  if (bottleneckReport) {
    if (bottleneckReport.status === "INSUFFICIENT_EVIDENCE" || bottleneckReport.records.length === 0) {
      return INSUFFICIENT_EVIDENCE_MESSAGE;
    }
    return formatV213BottleneckReport(bottleneckReport, "zh-TW");
  }

  // Under new bottleneck policy takeover, fail closed without falling back to old 20
  return INSUFFICIENT_EVIDENCE_MESSAGE;
}
