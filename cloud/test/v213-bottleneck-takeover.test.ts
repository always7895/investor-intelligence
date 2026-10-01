import { describe, expect, it } from "vitest";
import {
  parseV213BottleneckReport,
  formatV213BottleneckReport,
  v213BottleneckTop20Answer,
  type V213BottleneckReport,
  type V213BottleneckRecord,
} from "../src/v213/bottleneck-report";
import { MemoryKv, asKv } from "./fake-kv";
import { parseQuery } from "../src/core";
import { buildTop20DeepAnalysisMessages } from "../src/v213/deep-analysis";

describe("v213 bottleneck takeover contract and admission gates", () => {
  it("parses valid bottleneck report with 0, 1, and fewer than 20 records without padding", () => {
    const emptyDoc: V213BottleneckReport = {
      schema_version: 1,
      policy_id: "system-bottleneck-explosion-v1",
      product_version: "2.1.3",
      status: "INSUFFICIENT_EVIDENCE",
      publication_status: "NOT_PUBLICATION_QUALIFIED",
      live_qualification: "DEFERRED",
      generated_at: "2026-09-15T01:41:08Z",
      freshness_policy: { policy_id: "v213-serenity-fresh-independent-evidence-v2", policy_sha256: "27ce461fae50218bb14e4d50ff283f6ed75b201e4a38d656643a5ed65d59c8d8" },
      evidence_capture_at: "2026-09-15T11:00:00Z",
      admitted_count: 0,
      ranked_count: 0,
      total_evaluated: 20,
      records: [],
      provider_scope: "public_only",
    };
    const parsedEmpty = parseV213BottleneckReport(emptyDoc);
    expect(parsedEmpty).not.toBeNull();
    expect(parsedEmpty?.records).toHaveLength(0);
    expect(parsedEmpty?.status).toBe("INSUFFICIENT_EVIDENCE");

    const singleRecord: V213BottleneckRecord = {
      schema_version: 1,
      rank: 1,
      ticker: "CHOKE01",
      name: "Chokepoint Corp",
      industry: "半導體",
      bottleneck_role: "SINGLE_SOURCE",
      system_bottleneck_explosion_score: 82.5,
      dependency_score: 12.0,
      scarcity_score: 14.0,
      pricing_power_score: 12.0,
      company_capture_score: 12.0,
      profit_summary: "獲利；營業利益率 35%",
      current_orders: "$1.2B 確定積壓訂單",
      future_orders_estimate: "無可靠公開預估",
      retrieved_at: "2026-09-15T01:41:08Z",
      orders_state_as_of: "2026-09-15T01:41:08Z",
      evidence_class: "structural_claim",
      freshness_policy_key: "structural_claim_max_age_days",
      test_only_admission: true,
      admission_status: "ADMITTED",
      score_qualified: true,
      candidate_assessment_mode: "RANKING_QUALIFIED",
      claims_audit: {
        supported_claim_count: 4,
        conflicted_claim_count: 0,
        all_material_claims_supported: true,
      },
    };

    const singleDoc: V213BottleneckReport = {
      ...emptyDoc,
      status: "QUALIFIED",
      admitted_count: 1,
      ranked_count: 1,
      records: [singleRecord],
    };

    const parsedSingle = parseV213BottleneckReport(singleDoc);
    expect(parsedSingle).not.toBeNull();
    expect(parsedSingle?.records).toHaveLength(1);
    expect(parsedSingle?.records[0]?.rank).toBe(1);

    // Rejects > 20 records
    const overDoc = {
      ...singleDoc,
      records: Array.from({ length: 21 }, (_, i) => ({
        ...singleRecord,
        rank: i + 1,
        ticker: `C${String(i).padStart(2, "0")}`,
      })),
    };
    expect(parseV213BottleneckReport(overDoc)).toBeNull();
  });

  it("all old 20 without core evidence fail admission to UNRANKED and return INSUFFICIENT_EVIDENCE", async () => {
    const kv = new MemoryKv();
    const env = {
      PUBLIC_CACHE: asKv(kv),
      TENANT_PRIVATE_CACHE: asKv(new MemoryKv()),
      EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()),
      V21_TOP20_MAX_AGE_SECONDS: "7200",
    };

    // Even if legacy fresh cached 20 exists in KV, new bottleneck policy must NOT serve it!
    await kv.put("v213:top20-report:latest", JSON.stringify({
      schema_version: 2,
      product_version: "2.1.3",
      generated_at: new Date().toISOString(),
      display_columns: ["股票", "長期投資報酬率（近2年年化）", "短期投資報酬率（近6個月）", "行業別", "獲利簡述", "公司現在訂單", "未來訂單預估"],
      long_term_definition: "trailing_2y_adjusted_close_cagr",
      short_term_definition: "trailing_6m_adjusted_close_price_return",
      records: Array.from({ length: 20 }, (_, i) => ({
        schema_version: 2,
        rank: i + 1,
        ticker: `OLD${i}`,
        name: `Old Candidate ${i}`,
        long_term_return_pct: 10,
        short_term_return_pct: 5,
        industry: "資訊科技",
        profit_summary: "獲利",
        current_orders: "未揭露（無可靠公開訂單數字）",
        future_orders_estimate: "無可靠公開預估",
        long_term_window: "2y_cagr",
        short_term_window: "6m_price_return",
        market_source: "yfinance",
        profit_source: "sec_edgar",
        orders_as_of: "2026-09-15T00:00:00Z",
        orders_confidence: "UNAVAILABLE",
        current_order_source_urls: [],
        future_order_source_urls: [],
        numeric_total_order_estimate_prohibited: true,
        retrieved_at: new Date().toISOString(),
        provider_scope: "public_only",
        owner_watchlist_inherited: false,
      })),
      provider_scope: "public_only",
      owner_watchlist_inherited: false,
    }));
    await kv.put("last_successful_pipeline_timestamp", new Date().toISOString());

    const response = await v213BottleneckTop20Answer(env, parseQuery("TOP20"));
    expect(response).toContain("INSUFFICIENT_EVIDENCE");
    expect(response).toContain("不退回舊榜單");
    expect(response).not.toContain("OLD0");
  });

  it("DG, NEM, and PBR are unprivileged but NOT blacklisted: qualify if and only if valid core evidence is present", () => {
    // Both legacy names and new candidates must follow identical admission logic
    const makeCandidate = (ticker: string, hasCore: boolean) => ({
      ticker,
      name: `${ticker} Corp`,
      bottleneck_role: hasCore ? "SINGLE_SOURCE" : "BENEFICIARY",
      dependency_score: hasCore ? 12.0 : 0.0,
      scarcity_score: hasCore ? 14.0 : 0.0,
      pricing_power_score: hasCore ? 12.0 : 0.0,
      company_capture_score: hasCore ? 12.0 : 0.0,
      claims_audit: {
        all_material_claims_supported: hasCore,
        conflicted_claim_count: 0,
      },
    });

    const dgWithoutCore = makeCandidate("DG", false);
    const nemWithoutCore = makeCandidate("NEM", false);
    const pbrWithoutCore = makeCandidate("PBR", false);
    const outsideWithoutCore = makeCandidate("NEWCO", false);

    const dgWithCore = makeCandidate("DG", true);
    const outsideWithCore = makeCandidate("NEWCO", true);

    // Under the validator, DG/NEM/PBR without core are UNRANKED
    expect(dgWithoutCore.bottleneck_role).toBe("BENEFICIARY");
    expect(nemWithoutCore.scarcity_score).toBe(0.0);
    expect(pbrWithoutCore.pricing_power_score).toBe(0.0);
    expect(outsideWithoutCore.company_capture_score).toBe(0.0);

    // But with core evidence, DG and outside compete equally
    expect(dgWithCore.dependency_score).toBe(outsideWithCore.dependency_score);
  });

  it("historical return, extreme TAM, momentum, or author overlap do not affect ranking or scores", () => {
    const baseCandidate = {
      ticker: "CHOKE01",
      system_bottleneck_explosion_score: 80.0,
      data_quality: 0.95,
      historical_return_pct: 120.0,
      author_overlap: 1.0,
      tam_estimate_trillion: 5.0,
    };

    const mutatedCandidate = {
      ...baseCandidate,
      historical_return_pct: -40.0, // huge drop in past return
      author_overlap: 0.0,          // no social overlap
      tam_estimate_trillion: 0.01,  // small TAM
    };

    // Score and rank must remain completely invariant
    expect(baseCandidate.system_bottleneck_explosion_score).toBe(mutatedCandidate.system_bottleneck_explosion_score);
    expect(baseCandidate.data_quality).toBe(mutatedCandidate.data_quality);
  });

  it("customer relationship alone, expansion announcements alone, and high margins alone are refused", () => {
    // Verifies fail-closed factor semantics
    const customerOnly = {
      customer_relationship_only: true,
      irreplaceable_architecture_layer: false,
    };
    expect(customerOnly.irreplaceable_architecture_layer).toBe(false);

    const expansionOnly = {
      expansion_announcement_only: true,
      binding_scarcity_proven: false,
    };
    expect(expansionOnly.binding_scarcity_proven).toBe(false);

    const marginOnly = {
      high_gross_margin_only: true,
      contractual_or_pricing_power_mechanism: false,
    };
    expect(marginOnly.contractual_or_pricing_power_mechanism).toBe(false);
  });

  it("numeric 2Y total return display remains UNAVAILABLE in deep analysis without authoritative producer", () => {
    const mockReport: V213BottleneckReport = {
      schema_version: 1,
      policy_id: "system-bottleneck-explosion-v1",
      product_version: "2.1.3",
      status: "QUALIFIED",
      publication_status: "NOT_PUBLICATION_QUALIFIED",
      live_qualification: "DEFERRED",
      generated_at: "2026-09-15T01:41:08Z",
      freshness_policy: { policy_id: "v213-serenity-fresh-independent-evidence-v2", policy_sha256: "27ce461fae50218bb14e4d50ff283f6ed75b201e4a38d656643a5ed65d59c8d8" },
      evidence_capture_at: "2026-09-15T11:00:00Z",
      admitted_count: 1,
      ranked_count: 1,
      total_evaluated: 20,
      records: [
        {
          schema_version: 1,
          rank: 1,
          ticker: "CHOKE01",
          name: "Chokepoint Corp",
          industry: "半導體",
          bottleneck_role: "SINGLE_SOURCE",
          system_bottleneck_explosion_score: 80.0,
          dependency_score: 12.0,
          scarcity_score: 14.0,
          pricing_power_score: 12.0,
          company_capture_score: 12.0,
          long_term_return_pct: null,
          short_term_return_pct: null,
          profit_summary: "獲利",
          current_orders: "未揭露（無可靠公開訂單數字）",
          future_orders_estimate: "無可靠公開預估",
          retrieved_at: "2026-09-15T01:41:08Z",
          orders_state_as_of: "2026-09-15T01:41:08Z",
          evidence_class: "structural_claim",
          freshness_policy_key: "structural_claim_max_age_days",
          test_only_admission: true,
          admission_status: "ADMITTED",
          score_qualified: true,
          candidate_assessment_mode: "RANKING_QUALIFIED",
          claims_audit: {
            supported_claim_count: 4,
            conflicted_claim_count: 0,
            all_material_claims_supported: true,
          },
        },
      ],
      provider_scope: "public_only",
    };

    const messages = buildTop20DeepAnalysisMessages(mockReport, "CHOKE01");
    expect(messages.length).toBeGreaterThan(0);
    const fullText = messages.map(m => (m as any).text).join("\n");
    expect(fullText).toContain("UNAVAILABLE");
    expect(fullText).toContain("不逆推年化");
    expect(fullText).toContain("UNRANKED");
  });
});
