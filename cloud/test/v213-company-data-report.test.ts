// Data-driven company deep report embedded in the sealed report (synthetic values only).
import { describe, expect, it } from "vitest";
import { buildTop20DeepAnalysisMessages, companyDataReportFromSealed } from "../src/v213/deep-analysis";
import type { V213BottleneckReport } from "../src/v213/bottleneck-report";

const REPORT: V213BottleneckReport = {
  schema_version: 1, policy_id: "system-bottleneck-explosion-v1", product_version: "2.1.3", status: "QUALIFIED",
  publication_status: "NOT_PUBLICATION_QUALIFIED", live_qualification: "DEFERRED", generated_at: "2026-09-25T11:56:15Z",
  freshness_policy: { policy_id: "v213-serenity-fresh-independent-evidence-v2", policy_sha256: "27ce461fae50218bb14e4d50ff283f6ed75b201e4a38d656643a5ed65d59c8d8" },
  evidence_capture_at: "2026-09-15T11:00:00Z", admitted_count: 1, ranked_count: 1, total_evaluated: 2,
  records: [{
    schema_version: 1, rank: 1, ticker: "SYN", name: "Synthetic Devices Inc.", industry: "合成", bottleneck_role: "CAPACITY_BOTTLENECK",
    system_bottleneck_explosion_score: 80, dependency_score: 12, scarcity_score: 10, pricing_power_score: 12, company_capture_score: 12,
    long_term_return_pct: null, short_term_return_pct: null, profit_summary: "合成", current_orders: "合成", future_orders_estimate: "合成",
    retrieved_at: "2026-09-15T11:00:00Z", orders_state_as_of: "2026-09-15T00:00:00Z", evidence_class: "structural_claim",
    freshness_policy_key: "structural_claim_max_age_days", test_only_admission: true, admission_status: "ADMITTED", score_qualified: true,
    candidate_assessment_mode: "RANKING_QUALIFIED",
    claims_audit: { supported_claim_count: 4, conflicted_claim_count: 0, all_material_claims_supported: true },
  } as any],
  provider_scope: "public_only",
} as V213BottleneckReport;

const DATA = {
  ticker: "SYN", name: "Synthetic Devices Inc.", as_of: "2026-09-25", boundary: "官方資料的計算與整理；不是投資建議、價格預測或機率",
  phase: { phase: "COMMERCIAL_VALIDATION", next_review_at: "2026-11-12" },
  sections: [
    { title: "營運動能", text: "CY2026Q2 營收 US$1.00B，年增 +25.0%（合成）" },
    { title: "訂單能見度", text: "剩餘履約義務（RPO）US$5.00B，年增 +100.0%（合成）" },
    { title: "證偽條件", text: "RPO 年增降至 -10% 以下（合成）" },
  ],
  source_references: [{ source: "SEC XBRL company facts", url: "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json", period: "CY2026Q2" }],
};

const sealed = (deep: unknown) => JSON.stringify({ ...REPORT, deep_reports: { SYN: deep } });

describe("company data report", () => {
  it("renders computed sections and sources instead of the audit template", () => {
    const data = companyDataReportFromSealed(sealed(DATA), "syn");
    expect(data?.phase).toBe("COMMERCIAL_VALIDATION");
    const text = buildTop20DeepAnalysisMessages(REPORT, "SYN", data).map(m => (m as any).text).join("\n");
    expect(text).toContain("公司深度報告 · 官方資料計算");
    expect(text).toContain("二、訂單能見度");
    expect(text).toContain("https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json");
    expect(text).not.toContain("WITHHELD");
  });

  it("rejects malformed or foreign data and falls back to the audit template", () => {
    for (const bad of [
      { ...DATA, ticker: "OTHER" },
      { ...DATA, sections: DATA.sections.slice(0, 2) },
      { ...DATA, sections: [...DATA.sections, { title: "x", text: "line\nbreak" }] },
      { ...DATA, source_references: [{ source: "insecure", url: "http://example.com/x" }] },
      { ...DATA, as_of: "yesterday" },
    ]) {
      expect(companyDataReportFromSealed(sealed(bad), "SYN")).toBeNull();
    }
    expect(companyDataReportFromSealed("{", "SYN")).toBeNull();
    expect(companyDataReportFromSealed(null, "SYN")).toBeNull();
    const text = buildTop20DeepAnalysisMessages(REPORT, "SYN", null).map(m => (m as any).text).join("\n");
    expect(text).toContain("WITHHELD");
  });
});
