/// <reference types="node" />
import { describe, expect, it, vi } from "vitest";
import { readFileSync, writeFileSync } from "node:fs";
import { createHash, createHmac } from "node:crypto";
import productionWorker from "../src/v213/production-worker";
import { publicJson } from "../src/storage";
import { parseQuery } from "../src/core";
import { deterministicAnswer } from "../src/qa";
import { compactPublicContext } from "../src/v213/compact-qa";
import { parseV21Top20 } from "../src/v21/top20";
import { v213Top20ReportAnswer, readV213Top20Report } from "../src/v213/top20-report";
import { pinPublicSnapshot } from "../src/v213/public-snapshot";
import { SNAPSHOT_OBJECT_KEYS, SNAPSHOT_SEAL_KEY } from "../src/v213/snapshot-seal";
import { broadcastV213Top20 } from "../src/v213/broadcast";
import { storeOwnerPairing } from "../src/v21/owner-storage";
import { deriveTenantId } from "../src/security";
import { memoryPushNamespace, syntheticPushPolicy, withPushPreflight } from "./line-push-fixture";
import { asKv, MemoryKv } from "./fake-kv";
import approvedProfile from "../../config/v213-model-profile-v1.json";
import {
  finalizeV213Activation,
  ingestV213ActivationBundle,
  rollbackV213Activation,
} from "../src/v213/activation-v3";

const SCORING_VERSION = "system-operationalization-v2.1.3-diversified";
const MARKET_DEGRADATION = "INSUFFICIENT_NON_YAHOO_MARKET_COVERAGE";
const MARKET_MISSING = "NON_YAHOO_MARKET_CORROBORATION";
const RUN_ID = "20260902T150000Z-123456789abc";
const TRANSACTION_ID = "1".repeat(32);

function runtime() {
  const publicKv = new MemoryKv();
  const privateKv = new MemoryKv();
  const securityKv = new MemoryKv();
  return {
    publicKv,
    privateKv,
    securityKv,
    env: {
      PUBLIC_CACHE: asKv(publicKv),
      TENANT_PRIVATE_CACHE: asKv(privateKv),
      EPHEMERAL_SECURITY_CACHE: asKv(securityKv),
    },
  };
}

function top20(generated: string) {
  return Array.from({ length: 20 }, (_, index) => ({
    ticker: `T${String(index).padStart(2, "0")}`,
    name: `Synthetic ${index}`,
    serenity_score: 60 - index,
    serenity_raw_score: 62 - index,
    risk_penalty: 2,
    data_quality: 0.8,
    rating: index < 10 ? "A" : "B",
    category: "Synthetic",
    serenity_factors: {
      demand_wave: 0,
      chokepoint: 0,
      pricing_power: 0,
      replacement_friction: 0,
      tam_capture: 0,
      valuation_expectations: 3.75,
      evidence_quality: 14,
    },
    risk_flags: ["single_market_provider_degraded"],
    aschenbrenner_overlay: {
      domain: "C" as const,
      fit_score: 20,
      included_in_serenity_score: false as const,
      attribution: "system_operationalization_not_aschenbrenner_stock_score",
    },
    evidence: [
      {
        source_id: "sec_edgar",
        tier: "T0",
        claim_type: "xbrl_fact",
        title: `SEC fact ${index}`,
        url: `https://www.sec.gov/Archives/edgar/data/${1000000 + index}/synthetic.htm`,
        as_of: generated,
      },
      {
        source_id: "nasdaq_symbol_directory",
        tier: "T2",
        claim_type: "regulated_listing_identity",
        title: `Nasdaq identity ${index}`,
        url: "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
        as_of: generated,
      },
    ],
    evidence_count: 2,
    source_count: 2,
    scoring_version: SCORING_VERSION,
    line_public_eligible: true,
    provider_scope: "public_only",
    owner_watchlist_inherited: false,
    rank: index + 1,
    generated_at: generated,
    as_of: generated,
  }));
}

function v212(generated: string) {
  return {
    schema_version: 2,
    calculation_cutoff: generated,
    product_version: "2.1.2",
    generated_at: generated,
    display_columns: [
      "股票", "長期投資報酬率（近2年年化）", "短期投資報酬率（近6個月）",
      "行業別", "獲利簡述",
    ],
    long_term_definition: "trailing_2y_adjusted_close_cagr",
    short_term_definition: "trailing_6m_adjusted_close_price_return",
    records: Array.from({ length: 20 }, (_, index) => ({
      schema_version: 2,
      // Explicit synthetic clock control, not a source HTTP certification.
      source_acquisition: Object.fromEntries(Object.entries({
        long_term_return_pct: 40 - index, short_term_return_pct: 20 - index, industry: "半導體",
        profit_summary: "獲利；營收年增 +20.0%；營益率 15.0%；淨利率 10.0%",
      }).map(([key, value]) => [key, { status: "KNOWN", value, retrieved_at: generated, evidence_sha256: "1".repeat(64) }])),
      rank: index + 1,
      ticker: `T${String(index).padStart(2, "0")}`,
      long_term_return_pct: 40 - index,
      short_term_return_pct: 20 - index,
      industry: "半導體",
      profit_summary: "獲利；營收年增 +20.0%；營益率 15.0%；淨利率 10.0%",
      long_term_window: "2y_cagr",
      short_term_window: "6m_price_return",
      market_source: "yfinance",
      profit_source: "sec_edgar",
      retrieved_at: generated,
      provider_scope: "public_only",
      owner_watchlist_inherited: false,
    })),
    provider_scope: "public_only",
    owner_watchlist_inherited: false,
  };
}

function v213(generated: string) {
  return {
    schema_version: 2,
    product_version: "2.1.3",
    generated_at: generated,
    display_columns: [
      "股票", "長期投資報酬率（近2年年化）", "短期投資報酬率（近6個月）",
      "行業別", "獲利簡述", "公司現在訂單", "未來訂單預估",
    ],
    long_term_definition: "trailing_2y_adjusted_close_cagr",
    short_term_definition: "trailing_6m_adjusted_close_price_return",
    records: Array.from({ length: 20 }, (_, index) => ({
      schema_version: 2,
      rank: index + 1,
      ticker: `T${String(index).padStart(2, "0")}`,
      long_term_return_pct: 40 - index,
      short_term_return_pct: 20 - index,
      industry: "半導體",
      profit_summary: "獲利；營收年增 +20.0%；營益率 15.0%；淨利率 10.0%",
      current_orders: "未揭露（無可靠公開訂單數字）",
      future_orders_estimate: "無可靠公開預估",
      long_term_window: "2y_cagr",
      short_term_window: "6m_price_return",
      market_source: "yfinance",
      profit_source: "sec_edgar",
      orders_as_of: "",
      orders_confidence: "UNAVAILABLE",
      current_order_source_urls: [],
      future_order_source_urls: [],
      numeric_total_order_estimate_prohibited: true,
      retrieved_at: generated,
      provider_scope: "public_only",
      owner_watchlist_inherited: false,
    })),
    provider_scope: "public_only",
    owner_watchlist_inherited: false,
  };
}

function sourcePlan(generated: string) {
  return {
    schema_version: 1,
    catalog_count: 101,
    automatic_activation: false,
    owner_watchlist_inherited: false,
    provider_scope: "public_only",
    line_public_eligible: true,
    inventory: { source_count: 101, runtime_enabled_count: 0, topic_counts: { positions: 1 } },
    live_source_federation: {
      schema_version: 1,
      generated_at: generated,
      successful_families: ["us_sec", "nasdaq", "world_bank", "ecb"],
      official_successful_families: ["us_sec", "nasdaq", "world_bank", "ecb"],
      ticker_coverage_ratio: 1,
      largest_family_share: 0.4,
      unresolved_material_conflict_count: 0,
      yahoo_authoritative: false,
      catalog_source_count_is_not_live_use: true,
      claim_scope_separation_enforced: true,
      publisher_family_deduplication_enforced: true,
    },
    scoring_methodology: {
      scoring_version: SCORING_VERSION,
      official_serenity_formula_claimed: false,
      private_process_reproduction_claimed: false,
    },
  };
}

function federation(generated: string) {
  return {
    schema_version: 1,
    product_version: "2.1.3",
    generated_at: generated,
    ticker_sources: Array.from({ length: 20 }, (_, index) => ({
      rank: index + 1,
      ticker: `T${String(index).padStart(2, "0")}`,
      independent_family_count: 2,
    })),
    gates: {
      pass: true,
      successful_families: ["us_sec", "nasdaq", "world_bank", "ecb"],
      official_successful_families: ["us_sec", "nasdaq", "world_bank", "ecb"],
      ticker_coverage_ratio: 1,
      unresolved_material_conflict_count: 0,
      concentration_pass: true,
      yahoo_authoritative: false,
      catalog_source_count_is_not_live_use: true,
    },
  };
}

function sourceAudit(generated: string) {
  return {
    schema_version: 3,
    product_version: "2.1.3",
    generated_at: generated,
    status: "PASS",
    quality_status: "PASS_WITH_DEGRADATION",
    violations: [],
    blocking_violations: [],
    degradations: [MARKET_DEGRADATION],
    portfolio: {
      independent_source_families: 3,
      independent_domains: 4,
      claim_primary_coverage_ratio: 1,
      claim_source_families: 2,
      claim_source_domains: 3,
      maximum_single_family_share: 0.5,
      market_conflict_ticker_count: 0,
      non_yahoo_market_coverage_ratio: 0,
      non_yahoo_market_coverage_target_ratio: 0.75,
      market_corroboration_status: "DEGRADED",
      market_corroboration_global_blocker: false,
      evidence_qualified_candidate_count: 0,
      limited_research_candidate_count: 20,
      all_rows_publication_provenance_multi_source: true,
      limited_rows_high_confidence_eligible_count: 0,
      high_confidence_model_inference_eligible_count: 0,
    },
    methodology_notice: {
      official_serenity_formula: false,
      official_serenity_score: false,
      private_method_reproduced: false,
      single_source_inference_allowed: false,
      source_diversity_is_not_truth_by_itself: true,
      official_macro_is_not_company_claim_evidence: true,
      market_corroboration_unavailable_is_global_blocker: false,
      market_corroboration_required_for_high_confidence_model_inference: true,
      market_corroboration_required_for_uncapped_valuation_factor: true,
      uncorroborated_valuation_factor_max: 3.75,
      provider_failure_must_be_disclosed: true,
      provider_failure_must_not_be_silently_relabelled_as_success: true,
      market_data_is_not_averaged_into_published_returns: true,
    },
    freshness_audit: {
      status: "PASS",
      ticker_count: 20,
      evidence_qualified_candidate_count: 0,
      limited_research_candidate_count: 20,
      all_tickers_publication_provenance_multi_source: true,
      all_positive_advantages_fresh_multi_source: true,
    },
    records: Array.from({ length: 20 }, (_, index) => ({
      rank: index + 1,
      ticker: `T${String(index).padStart(2, "0")}`,
      source_metrics: {
        claim_relevant_independent_families: 2,
        claim_relevant_independent_domains: 3,
        claim_relevant_primary_sources: 1,
        claim_dated_evidence_ratio: 1,
      },
      market_corroboration: { status: "UNAVAILABLE", independent_provider_count: 0 },
      publication_evidence_mode: "LIMITED_RESEARCH_CANDIDATE",
      public_logic_state: {
        publication_evidence_mode: "LIMITED_RESEARCH_CANDIDATE",
        model_inference_confidence: "LIMITED",
        validated_company_thesis: false,
      },
      freshness_state: {
        status: "PASS",
        publication_evidence_mode: "LIMITED_RESEARCH_CANDIDATE",
        claim_primary_units: 1,
        publication_provenance_origin_count: 2,
        publication_provenance_domain_count: 2,
      },
      missing_or_review: [
        MARKET_MISSING,
        "LIMITED_RESEARCH_CANDIDATE",
        "INDEPENDENT_CLAIM_CORROBORATION",
      ],
      eligible_for_high_confidence_model_inference: false,
    })),
  };
}

async function digest(text: string): Promise<string> {
  const value = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(value), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function bundle(
  transactionId = TRANSACTION_ID,
  reportSuffix = "",
) {
  const generated = new Date().toISOString();
  const payloads = {
    top20_json: JSON.stringify(top20(generated)),
    source_plan_json: JSON.stringify(sourcePlan(generated)),
    report_text: [
      "<!-- line-public-eligible: true -->",
      "<!-- provider-scope: public_only -->",
      "<!-- owner-watchlist-inherited: false -->",
      `<!-- scoring-version: ${SCORING_VERSION} -->`,
      "<!-- official-serenity-formula-claimed: false -->",
      "# Synthetic public report",
      ("Evidence-bound public report. " + reportSuffix).repeat(20),
    ].join("\n"),
    v212_top20_report_json: JSON.stringify(v212(generated)),
    v213_top20_report_json: JSON.stringify(v213(generated)),
    source_federation_json: JSON.stringify(federation(generated)),
    source_independence_json: JSON.stringify(sourceAudit(generated)),
  };
  return {
    schema_version: 4,
    product_version: "2.1.3",
    transaction_id: transactionId,
    run_id: RUN_ID,
    generated_at: generated,
    public_data_as_of: generated,
    payloads,
    sha256: Object.fromEntries(
      await Promise.all(Object.entries(payloads).map(async ([name, text]) => [name, await digest(text)])),
    ),
  };
}

async function replacePayload(value: any, name: string, document: unknown): Promise<void> {
  const text = JSON.stringify(document);
  value.payloads[name] = text;
  value.sha256[name] = await digest(text);
}

async function makeMixed(value: any, highEligible = true): Promise<void> {
  const source = JSON.parse(value.payloads.source_independence_json);
  for (let index = 0; index < 10; index += 1) {
    const row = source.records[index];
    row.publication_evidence_mode = "EVIDENCE_QUALIFIED";
    row.public_logic_state.publication_evidence_mode = "EVIDENCE_QUALIFIED";
    row.freshness_state.publication_evidence_mode = "EVIDENCE_QUALIFIED";
    row.missing_or_review = [MARKET_MISSING];
  }
  if (highEligible) {
    source.records[0].eligible_for_high_confidence_model_inference = true;
    source.records[0].market_corroboration = { status: "CORROBORATED", independent_provider_count: 1 };
    source.records[0].missing_or_review = [];
  }
  source.portfolio.evidence_qualified_candidate_count = 10;
  source.portfolio.limited_research_candidate_count = 10;
  source.portfolio.high_confidence_model_inference_eligible_count = highEligible ? 1 : 0;
  source.freshness_audit.evidence_qualified_candidate_count = 10;
  source.freshness_audit.limited_research_candidate_count = 10;
  await replacePayload(value, "source_independence_json", source);
}

function control(transactionId = TRANSACTION_ID) {
  return JSON.stringify({ schema_version: 1, transaction_id: transactionId, run_id: RUN_ID });
}

function withFilingProvenance(rows: ReturnType<typeof top20>) {
  const filing = new Date().toISOString().slice(0, 10);
  return rows.map((row) => ({ ...row, evidence: row.evidence.map((evidence, index) => index ? evidence : {
    ...evidence, family: "regulator_filing", claim_type: "filing_publication_provenance",
    url: "https://www.sec.gov/Archives/edgar/data/1000000/000100000026000001/",
    as_of: filing, publication_date: filing, period_end: "2026-06-30",
    accession_number: "0001000000-26-000001", primary: true, claim_primary: true,
    provenance_only: true, can_prove_positive_serenity_factor: false,
    retrieval_timestamp_used_as_publication_date: false,
  }) }));
}

async function qaWebhookFixture(compact = true) {
  const fixture = runtime();
  const env = { ...fixture.env, LINE_CHANNEL_SECRET: "SYNTHETIC_QA_SIGNATURE_NOT_REAL", LINE_CHANNEL_ACCESS_TOKEN: "SYNTHETIC_QA_REPLY_NOT_REAL",
    TENANT_HASH_SECRET: "SYNTHETIC_QA_TENANT_NOT_REAL", TENANT_DATA_ENCRYPTION_KEY: "SYNTHETIC_QA_DATA_NOT_REAL", MEMORY_FEATURE_AVAILABLE: "false",
    CURRENT_PUBLIC_DATA_ENABLED: "true", GENERAL_QA_ENABLED: "true", V213_COMPACT_QA_ENABLED: compact ? "true" : "false",
    LOCAL_LLM_BASE_URL: "https://synthetic-qa.example.test", LOCAL_LLM_ALLOWED_HOSTS: "synthetic-qa.example.test",
    LOCAL_LLM_SHARED_SECRET: "SYNTHETIC_QA_MODEL_NOT_REAL", LOCAL_LLM_MODEL: approvedProfile.model,
    V213_MODEL_PROFILE_JSON: JSON.stringify(approvedProfile) };
  const target = String.fromCharCode(85) + "1".repeat(32);
  await storeOwnerPairing(env, await deriveTenantId({ type: "user", userId: target }, env.TENANT_HASH_SECRET), target);
  const prompts: string[] = []; const replies: string[] = [];
  const network = vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(input instanceof Request ? input.url : String(input)); const body = JSON.parse(String(init?.body));
    if (url.origin === "https://synthetic-qa.example.test" && url.pathname === "/v1/chat/completions") {
      prompts.push(JSON.stringify(body.messages));
      return new Response(JSON.stringify({ choices: [{ message: { content: "SYNTHETIC_QA_ANSWER_NOT_LIVE" } }] }));
    }
    if (url.origin === "https://api.line.me" && url.pathname === "/v2/bot/message/reply") {
      replies.push(JSON.stringify(body.messages)); return new Response("{}");
    }
    throw new Error("UNEXPECTED_SYNTHETIC_QA_TRANSPORT");
  });
  let sequence = 0;
  async function deliver(text: string) {
    const body = JSON.stringify({ events: [{ type: "message", timestamp: Date.now(), webhookEventId: `synthetic-qa-event-${++sequence}`,
      replyToken: "synthetic-qa-reply", source: { type: "user", userId: target }, message: { type: "text", text } }] });
    const signature = createHmac("sha256", env.LINE_CHANNEL_SECRET).update(body).digest("base64");
    const tasks: Promise<unknown>[] = [];
    const response = await productionWorker.fetch(new Request("https://synthetic-worker.example.test/webhook", {
      method: "POST", headers: { "x-line-signature": signature }, body,
    }), env, { waitUntil(task: Promise<unknown>) { tasks.push(task); } } as ExecutionContext);
    expect(response.status).toBe(200); await Promise.all(tasks);
  }
  return { ...fixture, env, prompts, replies, deliver, restore: () => network.mockRestore() };
}

describe("v2.1.3 atomic activation transaction", () => {
  it.each(["missing", "malformed"])("preserves pairing after a %s target read in the signed webhook", async failure => {
    const f = await qaWebhookFixture();
    const before = [...f.privateKv.values];
    const originalGet = f.privateKv.get.bind(f.privateKv);
    const remove = vi.spyOn(f.privateKv, "delete");
    const put = vi.spyOn(f.privateKv, "put");
    let interrupted = false;
    vi.spyOn(f.privateKv, "get").mockImplementation(async (key, type) => {
      if (!interrupted && key.endsWith(":v21:owner-line:push-target")) {
        interrupted = true;
        return failure === "missing" ? null : '{"v":99}';
      }
      return originalGet(key, type);
    });
    try {
      await f.deliver("通知狀態");
      expect(interrupted).toBe(true); expect(f.replies).toHaveLength(0);
      // A later successful read must recover without a new pairing or repair write.
      await f.deliver("通知狀態");
      expect(f.replies).toHaveLength(1); expect(f.replies[0]).toContain("PAIRED（已配對）");
      expect(remove).not.toHaveBeenCalled(); expect(put).not.toHaveBeenCalled();
      expect([...f.privateKv.values]).toEqual(before); expect(f.prompts).toHaveLength(0);
    } finally { f.restore(); }
  });
  it.each(["missing", "malformed"])("refuses the push but preserves pairing after a %s target read", async failure => {
    const f = await qaWebhookFixture();
    const before = [...f.privateKv.values];
    const originalGet = f.privateKv.get.bind(f.privateKv);
    const remove = vi.spyOn(f.privateKv, "delete");
    const put = vi.spyOn(f.privateKv, "put");
    let interrupted = false;
    vi.spyOn(f.privateKv, "get").mockImplementation(async (key, type) => {
      if (!interrupted && key.endsWith(":v21:owner-line:push-target")) {
        interrupted = true;
        return failure === "missing" ? null : '{"v":99}';
      }
      return originalGet(key, type);
    });
    try {
      expect(await broadcastV213Top20(f.env, "test")).toEqual({ status: "owner_not_paired" });
      expect(interrupted).toBe(true);
      // No public report was installed: recovered pairing must reach, not bypass, that gate.
      expect(await broadcastV213Top20(f.env, "test")).toEqual({ status: "top20_unavailable" });
      expect(remove).not.toHaveBeenCalled(); expect(put).not.toHaveBeenCalled();
      expect([...f.privateKv.values]).toEqual(before);
      expect(f.replies).toHaveLength(0); expect(f.prompts).toHaveLength(0);
    } finally { f.restore(); }
  });
  it("still deletes pairing only for the explicit authorized unpair command", async () => {
    const f = await qaWebhookFixture();
    const remove = vi.spyOn(f.privateKv, "delete");
    try {
      await f.deliver("取消配對");
      expect(f.replies).toHaveLength(1); expect(f.replies[0]).toContain("配對已取消");
      expect(f.privateKv.values.has("v21:owner-line:tenant")).toBe(false);
      expect([...f.privateKv.values.keys()].some(key => key.endsWith(":v21:owner-line:push-target"))).toBe(false);
      expect(remove).toHaveBeenCalledTimes(2); expect(f.prompts).toHaveLength(0);
      await f.deliver("通知狀態");
      expect(f.replies).toHaveLength(1); // Unpaired messages remain unauthorized.
    } finally { f.restore(); }
  });
  it.each(["false", "true"])("does not certify delivery from pairing in the signed webhook (schedule=%s)", async enabled => {
    const f = await qaWebhookFixture();
    Object.assign(f.env, { V21_SCHEDULED_PUSH_ENABLED: enabled });
    const get = vi.spyOn(f.publicKv, "get");
    try {
      await f.deliver("通知狀態");
      expect(f.replies).toHaveLength(1);
      expect(f.replies[0]).toContain("PAIRED");
      expect(f.replies[0]).toContain("本指令只確認配對");
      expect(f.replies[0]).toContain("不代表排程已啟用、資料已通過發布驗收或 LINE 已送達");
      expect(f.replies[0]).not.toContain("排程為 08:00／21:00");
      expect(f.prompts).toHaveLength(0); expect(get).not.toHaveBeenCalled();
    } finally { f.restore(); }
  });
  it.each(["help", "說明", "说明"])("qualifies notification and product availability in signed LINE help (%s)", async text => {
    const f = await qaWebhookFixture();
    Object.assign(f.env, { V21_SCHEDULED_PUSH_ENABLED: "false" });
    const get = vi.spyOn(f.publicKv, "get");
    try {
      await f.deliver(text);
      expect(f.replies).toHaveLength(1);
      expect(f.replies[0]).toContain("配對不代表推送已上線");
      expect(f.replies[0]).toContain("完整數據報告／深入分析須另經當輪資料與發布驗收");
      expect(f.replies[0]).not.toContain("Top 20 固定只顯示");
      expect(f.replies[0]).not.toContain("通知：每天 08:00");
      expect(f.prompts).toHaveLength(0); expect(get).not.toHaveBeenCalled();
      expect(f.replies[0]).not.toContain("SYNTHETIC_QA_REPLY_NOT_REAL");
    } finally { f.restore(); }
  });
  it("does not turn explanatory questions into standalone help commands", () => {
    for (const text of ["說明 CPI 對航運的影響", "说明 ALPHA 每週期權", "期權試算說明", "如何閱讀完整文字分析"]) {
      expect(parseQuery(text).intent).not.toBe("help");
    }
    for (const text of [" 說明 ", "说明\n", "ＨＥＬＰ"]) expect(parseQuery(text).intent).toBe("help");
  });
  it.each(["Top20 數據詳報", "Top20 深入分析", "宏觀 數據詳報", "T00 期權 數據詳報", "股票 T00 narrative_analysis", "Top20 card_summary"])("does not downgrade the explicit product request %s in the actual signed webhook", async text => {
    const f = await qaWebhookFixture();
    try {
      await ingestV213ActivationBundle(JSON.stringify(await bundle()), f.env);
      await f.deliver(text);
      expect(f.replies).toHaveLength(1);
      expect(f.replies[0]).toContain("RESEARCH_PRODUCT_NOT_SEALED");
      expect(f.replies[0]).not.toContain('"type":"flex"');
      expect(f.replies[0]).not.toContain("SYNTHETIC_QA_ANSWER_NOT_LIVE");
      expect(f.prompts).toHaveLength(0);
    } finally { f.restore(); }
  });
  it.each(["Top20", "Top20 文字"])("retains the separately requested seven-field %s after refusing an unsealed kind", async text => {
    const f = await qaWebhookFixture();
    try {
      await ingestV213ActivationBundle(JSON.stringify(await bundle()), f.env);
      const get = vi.spyOn(f.publicKv, "get");
      await f.deliver("Top20 data_report");
      expect(f.replies[0]).toContain("RESEARCH_PRODUCT_NOT_SEALED"); expect(get).not.toHaveBeenCalled();
      await f.deliver(text);
      expect(f.replies).toHaveLength(2); expect(f.prompts).toHaveLength(0);
      const messages = JSON.parse(f.replies[1]!) as { type: string }[];
      expect(messages.length).toBeGreaterThan(0); expect(messages.length).toBeLessThanOrEqual(5);
      expect(messages.every(message => message.type === (text.includes("文字") ? "text" : "flex"))).toBe(true);
      for (let i = 0; i < 20; i++) expect(f.replies[1]).toContain(`T${String(i).padStart(2, "0")}`);
      expect(f.replies[1]).not.toContain("RESEARCH_PRODUCT_NOT_SEALED");
      expect(get.mock.calls.filter(([key]) => key === "snapshot:current")).toHaveLength(1);
    } finally { f.restore(); }
  });
  it("does not make planted direct or unlisted candidate products actionable in the signed webhook", async () => {
    const f = await qaWebhookFixture(false);
    try {
      await ingestV213ActivationBundle(JSON.stringify(await bundle()), f.env);
      const forged = JSON.stringify({ schema_version: 1, complete: true, publication_eligible: true,
        content_utf8: "SYNTHETIC_UNSEALED_PRODUCT_MUST_NOT_LEAK" });
      for (const key of ["v213:research-products:latest", `snapshot:${RUN_ID}:v213:research-products:latest`, "financial-products-candidate.json"])
        f.publicKv.values.set(key, forged);
      const before = [...f.publicKv.values]; const get = vi.spyOn(f.publicKv, "get");
      await f.deliver("T00 data_report");
      expect(f.replies).toHaveLength(1); expect(f.replies[0]).toContain("RESEARCH_PRODUCT_NOT_SEALED");
      expect(f.replies[0]).not.toContain("SYNTHETIC_UNSEALED_PRODUCT_MUST_NOT_LEAK");
      expect(f.prompts).toHaveLength(0); expect(get).not.toHaveBeenCalled(); expect([...f.publicKv.values]).toEqual(before);
    } finally { f.restore(); }
  });
  it.each([true, false])("blocks corrupt context in the actual signed direct-chat webhook before model transport (compact=%s)", async compact => {
    const f = await qaWebhookFixture(compact);
    try {
      await ingestV213ActivationBundle(JSON.stringify(await bundle()), f.env);
      await f.deliver("目前景氣循環如何影響企業融資？");
      expect(f.prompts).toHaveLength(1); expect(f.replies).toHaveLength(1);
      const key = `snapshot:${RUN_ID}:v213:source-independence:latest`; const audit = JSON.parse(f.publicKv.values.get(key)!);
      audit.portfolio.evidence_qualified_candidate_count = 20; f.publicKv.values.set(key, JSON.stringify(audit));
      await f.deliver("目前景氣循環如何影響企業融資？");
      expect(f.prompts).toHaveLength(1);
      expect(f.replies).toHaveLength(2); expect(f.replies[1]).toContain("CURRENT_DATA_TIMESTAMP_MISSING");
    } finally { f.restore(); }
  });
  it("pins one signed webhook question across certified QA reads but not across later questions", async () => {
    const f = await qaWebhookFixture(false); const second = runtime();
    try {
      const a = await bundle(TRANSACTION_ID, "SYNTHETIC_ROUND_A"); await ingestV213ActivationBundle(JSON.stringify(a), f.env);
      const b = await bundle("b".repeat(32), "SYNTHETIC_ROUND_B"); b.run_id = "20260902T150001Z-abcdef123456";
      await ingestV213ActivationBundle(JSON.stringify(b), second.env);
      for (const [key, value] of second.publicKv.values) if (key !== "snapshot:current") f.publicKv.values.set(key, value);
      const get = f.publicKv.get.bind(f.publicKv); let pointers = 0;
      const reads = vi.spyOn(f.publicKv, "get").mockImplementation(async (key: string, type?: "text" | "json") => {
        const result = await get(key, type); if (key === "snapshot:current") pointers += 1;
        if (key === `snapshot:${RUN_ID}:reports:latest`) f.publicKv.values.set("snapshot:current", second.publicKv.values.get("snapshot:current")!);
        return result;
      });
      try {
        await f.deliver("目前景氣循環如何影響企業融資？");
        expect(f.replies).toHaveLength(1); expect(f.prompts).toHaveLength(1);
        expect(pointers).toBe(1);
        expect(f.prompts[0]).toContain("SYNTHETIC_ROUND_A"); expect(f.prompts[0]).not.toContain("SYNTHETIC_ROUND_B");
        await f.deliver("目前景氣循環如何影響企業融資？");
        expect(pointers).toBe(2); expect(f.prompts[1]).toContain("SYNTHETIC_ROUND_B");
      } finally { reads.mockRestore(); }
    } finally { f.restore(); }
  });
  it("uses post-verification execution time for compact freshness without renewing the source stamp", async () => {
    vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(new Date("2026-09-10T16:00:00.000Z"));
    const { env, publicKv } = runtime(); let reads: ReturnType<typeof vi.spyOn> | undefined;
    try {
      const b = await bundle(); await ingestV213ActivationBundle(JSON.stringify(b), env);
      const get = publicKv.get.bind(publicKv);
      reads = vi.spyOn(publicKv, "get").mockImplementation(async (key: string, type?: "text" | "json") => {
        const result = await get(key, type);
        if (key === `snapshot:${RUN_ID}:v213:activation-claim`) vi.setSystemTime(new Date("2026-09-10T16:01:01.000Z"));
        return result;
      });
      const data = await compactPublicContext({ ...env, CURRENT_PUBLIC_DATA_ENABLED: "true", PUBLIC_DATA_MAX_AGE_SECONDS: "60" }, parseQuery("景氣如何？"));
      expect(data.freshness).toBe("STALE"); expect(data.as_of).toBe(b.public_data_as_of);
      expect(data.evidence_qualified).toBeUndefined();
    } finally { reads?.mockRestore(); vi.useRealTimers(); }
  });
  it("does not pin public data or run a model for an invalid webhook signature", async () => {
    const f = await qaWebhookFixture(); const get = vi.spyOn(f.publicKv, "get");
    try {
      const response = await productionWorker.fetch(new Request("https://synthetic-worker.example.test/webhook", {
        method: "POST", headers: { "x-line-signature": "invalid" }, body: '{"events":[]}',
      }), f.env, { waitUntil() { throw new Error("UNAUTHENTICATED_TASK"); } } as unknown as ExecutionContext);
      expect(response.status).toBe(401); expect(get).not.toHaveBeenCalled();
      expect(f.prompts).toHaveLength(0); expect(f.replies).toHaveLength(0);
    } finally { get.mockRestore(); f.restore(); }
  });
  it("does not fall back to direct compact facts for malformed or referenced unsealed pointers", async () => {
    const { env, publicKv } = runtime(); const b = await bundle(); await ingestV213ActivationBundle(JSON.stringify(b), env);
    const qa = { ...env, CURRENT_PUBLIC_DATA_ENABLED: "true" };
    publicKv.values.set("last_successful_pipeline_timestamp", b.public_data_as_of);
    publicKv.values.set("v213:source-independence:latest", b.payloads.source_independence_json);
    publicKv.values.set("snapshot:legacy-test:last_successful_pipeline_timestamp", b.public_data_as_of);
    publicKv.values.set("snapshot:legacy-test:v213:source-independence:latest", b.payloads.source_independence_json);
    for (const pointer of ["", "null", "{}", '{"run_id":null}', JSON.stringify({ run_id: RUN_ID }), '{"run_id":"legacy-test"}']) {
      publicKv.values.set("snapshot:current", pointer);
      const data = await compactPublicContext(qa, parseQuery("目前景氣如何？"));
      expect(data.freshness).toBe("UNAVAILABLE"); expect(data.as_of).toBeNull(); expect(data.evidence_qualified).toBeUndefined();
    }
  });
  it("does not expose unlisted injected options or universe through compatibility storage", async () => {
    const { env, publicKv } = runtime(); await ingestV213ActivationBundle(JSON.stringify(await bundle()), env);
    for (const key of ["options:latest", "v211:universe:latest"]) {
      publicKv.values.set(`snapshot:${RUN_ID}:${key}`, JSON.stringify([{ ticker: "T00", source: "UNCOMMITTED_MEMBER" }]));
      publicKv.values.set(key, JSON.stringify([{ ticker: "T00", source: "UNCOMMITTED_DIRECT_FALLBACK" }]));
      expect(await publicJson(env, [key])).toBeNull();
    }
    expect(await deterministicAnswer(env, parseQuery("T00 期權"), { tenantId: "synthetic", chatType: "group" })).toBe("OPTION_DATA_UNAVAILABLE");
    expect((await pinPublicSnapshot(env)).integrity).toBe("sealed");
  });
  it("does not serve changed sealed report text through the certified legacy QA caller", async () => {
    const { env, publicKv } = runtime(); const value = await bundle();
    await ingestV213ActivationBundle(JSON.stringify(value), env);
    const qa = { ...env, CURRENT_PUBLIC_DATA_ENABLED: "true" };
    const context = { tenantId: "synthetic-only", chatType: "group" as const };
    expect(await deterministicAnswer(qa, parseQuery("最新報告"), context)).toContain("Synthetic public report");
    publicKv.values.set(`snapshot:${RUN_ID}:reports:latest`, "SYNTHETIC_CHANGED_QA_REPORT");
    expect(await deterministicAnswer(qa, parseQuery("最新報告"), context)).toBe("CURRENT_DATA_TIMESTAMP_MISSING");
  });
  it("does not promote altered LIMITED audit flags through the actual compact context caller", async () => {
    const { env, publicKv } = runtime(); await ingestV213ActivationBundle(JSON.stringify(await bundle()), env);
    const qa = { ...env, CURRENT_PUBLIC_DATA_ENABLED: "true" }; const query = parseQuery("T00 風險分析");
    expect(query.ticker).toBe("T00");
    expect(await compactPublicContext(qa, query)).toMatchObject({ mode: "LIMITED_RESEARCH_CANDIDATE", high_eligible: false });
    const key = `snapshot:${RUN_ID}:v213:source-independence:latest`; const audit = JSON.parse(publicKv.values.get(key)!);
    audit.records[0].publication_evidence_mode = "EVIDENCE_QUALIFIED";
    audit.records[0].eligible_for_high_confidence_model_inference = true;
    publicKv.values.set(key, JSON.stringify(audit));
    const data = await compactPublicContext(qa, query);
    expect(data.high_eligible).not.toBe(true);
    expect(data.freshness).toBe("UNAVAILABLE");
  });
  it("does not turn altered sealed bytes into a newly identified Top20 answer", async () => {
    const { env, publicKv } = runtime();
    const value = await bundle();
    await ingestV213ActivationBundle(JSON.stringify(value), env);
    const key = `snapshot:${RUN_ID}:v213:top20-report:latest`;
    const changed = JSON.parse(publicKv.values.get(key)!);
    changed.records[19].profit_summary = "SYNTHETIC_ALTERED_AFTER_SEAL";
    publicKv.values.set(key, JSON.stringify(changed));
    const answer = await v213Top20ReportAnswer(env, parseQuery("Top20 文字"));
    expect(answer).not.toContain("SYNTHETIC_ALTERED_AFTER_SEAL");
    expect(answer).toContain("尚未通過驗證");
  });
  it("binds actual normalized storage bytes separately from differently encoded upload digests", async () => {
    const { env, publicKv } = runtime(); const value = await bundle();
    for (const key of Object.keys(value.payloads) as Array<keyof typeof value.payloads>) {
      if (key === "report_text") continue;
      value.payloads[key] = JSON.stringify(JSON.parse(value.payloads[key]), null, 2);
      value.sha256[key] = await digest(value.payloads[key]);
    }
    const result = await ingestV213ActivationBundle(JSON.stringify(value), env);
    expect(result.object_count).toBe(14);
    const prefix = `snapshot:${RUN_ID}:`; const pointer = JSON.parse(publicKv.values.get("snapshot:current")!);
    const raw = publicKv.values.get(prefix + SNAPSHOT_SEAL_KEY)!; const manifest = JSON.parse(raw);
    expect(pointer.schema_version).toBe(2); expect(pointer.seal_sha256).toBe(await digest(raw));
    for (const key of SNAPSHOT_OBJECT_KEYS) {
      const body = publicKv.values.get(prefix + key)!;
      expect(manifest.objects[key]).toEqual({ sha256: await digest(body), utf8_bytes: new TextEncoder().encode(body).byteLength });
    }
    expect(manifest.objects["v213:top20-report:latest"].sha256).not.toBe(value.sha256.v213_top20_report_json);
    const view = await pinPublicSnapshot(env); expect(view.integrity).toBe("sealed");
    const report = await readV213Top20Report(view); expect(report!.records[19]!.profit_summary).toContain("淨利率");
    expect((await v213Top20ReportAnswer(env, parseQuery("Top20 文字")))).toContain("T19");
  });
  it("keeps normal replay read-only and refuses replay after finalize without recreating a rollback journal", async () => {
    const { env, publicKv, privateKv } = runtime(); const value = await bundle();
    await ingestV213ActivationBundle(JSON.stringify(value), env);
    const pub = vi.spyOn(publicKv, "put"); const priv = vi.spyOn(privateKv, "put");
    expect((await ingestV213ActivationBundle(JSON.stringify(value), env)).idempotent_replay).toBe(true);
    expect(pub).not.toHaveBeenCalled(); expect(priv).not.toHaveBeenCalled();
    await finalizeV213Activation(control(), env);
    await expect(ingestV213ActivationBundle(JSON.stringify(value), env)).rejects.toThrow("V213_ACTIVATION_FINALIZED_OR_UNOWNED_REPLAY");
    expect(pub).not.toHaveBeenCalled(); expect(priv).not.toHaveBeenCalled();
    expect(privateKv.values.has(`v213:activation-rollback:${TRANSACTION_ID}`)).toBe(false);
  });
  it.each(["missing_manifest", "legacy_pointer", "corrupt_manifest", "corrupt_claim"])("never synthesizes a promoted seal on %s replay", async mode => {
    const { env, publicKv, privateKv } = runtime(); const value = await bundle();
    await ingestV213ActivationBundle(JSON.stringify(value), env); const prefix = `snapshot:${RUN_ID}:`;
    if (mode === "missing_manifest") publicKv.values.delete(prefix + SNAPSHOT_SEAL_KEY);
    if (mode === "legacy_pointer") publicKv.values.set("snapshot:current", JSON.stringify({ schema_version: 1, run_id: RUN_ID }));
    if (mode === "corrupt_manifest") publicKv.values.set(prefix + SNAPSHOT_SEAL_KEY, "{}");
    if (mode === "corrupt_claim") publicKv.values.set(prefix + "v213:activation-claim", "");
    const pub = new Map(publicKv.values); const priv = new Map(privateKv.values);
    await expect(ingestV213ActivationBundle(JSON.stringify(value), env)).rejects.toThrow();
    expect(publicKv.values).toEqual(pub); expect(privateKv.values).toEqual(priv);
    expect((await pinPublicSnapshot(env)).kind).toBe("invalid");
  });
  it.each(["reports:evening:latest", "scores:latest", "v213:activation-claim", SNAPSHOT_SEAL_KEY])("does not finalize a corrupt %s or delete its recovery journal", async key => {
    const { env, publicKv, privateKv } = runtime();
    await ingestV213ActivationBundle(JSON.stringify(await bundle()), env);
    publicKv.values.set(`snapshot:${RUN_ID}:${key}`, "SYNTHETIC_CORRUPTION");
    const before = new Map(privateKv.values); const pointer = publicKv.values.get("snapshot:current");
    await expect(finalizeV213Activation(control(), env)).rejects.toThrow("V213_SNAPSHOT_SEAL_INVALID");
    expect(privateKv.values).toEqual(before); expect(publicKv.values.get("snapshot:current")).toBe(pointer);
    expect((await pinPublicSnapshot(env)).kind).toBe("invalid");
  });
  it("rechecks the exact current pointer after finalize object verification", async () => {
    const { env, publicKv, privateKv } = runtime(); await ingestV213ActivationBundle(JSON.stringify(await bundle()), env);
    const before = new Map(privateKv.values); const get = publicKv.get.bind(publicKv);
    vi.spyOn(publicKv, "get").mockImplementation(async (key: string, type?: "text" | "json") => {
      const result = await get(key,type);
      if (key.endsWith("source_views:latest")) publicKv.values.set("snapshot:current", "SYNTHETIC_CONCURRENT_POINTER");
      return result;
    });
    await expect(finalizeV213Activation(control(), env)).rejects.toThrow("V213_ACTIVATION_FINALIZE_POINTER_MISMATCH");
    expect(privateKv.values).toEqual(before);
  });
  it("bounds stored objects and rejects malformed UTF-16 before any journal/claim write", async () => {
    for (const mode of ["oversized", "surrogate"]) {
      const { env, publicKv, privateKv } = runtime(); const value = await bundle();
      if (mode === "oversized") {
        const doc = JSON.parse(value.payloads.source_federation_json); doc.synthetic_padding = "x".repeat(2097153);
        await replacePayload(value, "source_federation_json", doc);
      } else {
        value.payloads.report_text += "\ud800"; value.sha256.report_text = await digest(value.payloads.report_text);
      }
      await expect(ingestV213ActivationBundle(JSON.stringify(value), env)).rejects.toThrow("V213_SNAPSHOT_SEAL_INVALID");
      expect(publicKv.values.size).toBe(0); expect(privateKv.values.size).toBe(0);
    }
  });
  it("refuses altered sealed data in the paired actual push caller before LINE/quota transport", async () => {
    const { env, publicKv } = runtime(); const value = await bundle(); await ingestV213ActivationBundle(JSON.stringify(value), env);
    const e = { ...env, TENANT_HASH_SECRET: "SYNTHETIC_SEAL_HASH_NOT_REAL", TENANT_DATA_ENCRYPTION_KEY: "SYNTHETIC_SEAL_DATA_NOT_REAL",
      LINE_CHANNEL_ACCESS_TOKEN: "SYNTHETIC_SEAL_LINE_NOT_REAL" };
    const target = String.fromCharCode(85) + "0".repeat(32);
    await storeOwnerPairing(e, await deriveTenantId({ type: "user", userId: target }, e.TENANT_HASH_SECRET), target);
    const network = vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("NETWORK_FORBIDDEN"));
    try {
      // Positive reader control reaches the existing free-plan gate, not a sender bypass.
      await expect(broadcastV213Top20(e, "test")).rejects.toThrow("LINE_FREE_PLAN_REVIEW_REQUIRED");
      publicKv.values.set(`snapshot:${RUN_ID}:reports:evening:latest`, "SYNTHETIC_ALTERED_OTHER_MEMBER");
      expect((await broadcastV213Top20(e, "test")).status).toBe("top20_unavailable");
      expect(network).not.toHaveBeenCalled();
    } finally { network.mockRestore(); }
  });
  it.each(["morning", "evening"] as const)("passes the actual admitted synthetic seal through the %s caller and mocked free sender once", async slot => {
    const { env } = runtime(); await ingestV213ActivationBundle(JSON.stringify(await bundle()), env);
    const e = { ...env, TENANT_HASH_SECRET: "SYNTHETIC_SEALED_HASH_NOT_REAL", TENANT_DATA_ENCRYPTION_KEY: "SYNTHETIC_SEALED_DATA_NOT_REAL",
      LINE_CHANNEL_ACCESS_TOKEN: "SYNTHETIC_SEALED_LINE_NOT_REAL", LINE_FREE_PUSH_POLICY: syntheticPushPolicy(),
      V21_SCHEDULED_PUSH_ENABLED: "true", V213_BROADCAST_DEDUPE: memoryPushNamespace().namespace };
    const target = String.fromCharCode(85) + "0".repeat(32);
    await storeOwnerPairing(e, await deriveTenantId({ type: "user", userId: target }, e.TENANT_HASH_SECRET), target);
    const messages: unknown[] = [];
    const network = vi.spyOn(globalThis, "fetch").mockImplementation(withPushPreflight(async (_url: RequestInfo | URL, init?: RequestInit) => {
      messages.push(JSON.parse(String(init?.body)).messages); return new Response("{}", { status: 200 });
    }));
    try {
      expect(await broadcastV213Top20(e, slot)).toMatchObject({ status: "sent", run_id: RUN_ID, count: 20 });
      expect((await broadcastV213Top20(e, slot)).status).toBe("duplicate");
      expect(messages).toHaveLength(1); expect(JSON.stringify(messages[0])).toContain("T19");
    } finally { network.mockRestore(); }
    // Mock provider acceptance is NOT a real free-plan review or phone receipt.
  });
  it("refuses actual CLI cached source time before sealed writes despite fresh outer clocks", async () => {
    const vectors = JSON.parse(readFileSync(new URL("../../tests/fixtures/source-acquisition-reports.json", import.meta.url), "utf8"));
    const data = vectors.cases.stale;
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(data.v212.generated_at));
    try {
      const { env, publicKv, privateKv } = runtime();
      const value = await bundle();
      await replacePayload(value, "v212_top20_report_json", data.v212);
      await replacePayload(value, "v213_top20_report_json", data.v213);
      await expect(ingestV213ActivationBundle(JSON.stringify(value), env)).rejects.toThrow("V213_ACTIVATION_SOURCE_ACQUISITION_STALE");
      expect(publicKv.values.size).toBe(0); expect(privateKv.values.size).toBe(0);
    } finally { vi.useRealTimers(); }
  });
  it.each(["fresh", "unknown"])("checks actual CLI %s clock metadata in sealed admission and readback", async name => {
    const vectors = JSON.parse(readFileSync(new URL("../../tests/fixtures/source-acquisition-reports.json", import.meta.url), "utf8"));
    const data = vectors.cases[name];
    vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(new Date(data.v212.generated_at));
    try {
      const { env, publicKv, privateKv } = runtime(); const value = await bundle();
      await replacePayload(value, "v212_top20_report_json", data.v212);
      await replacePayload(value, "v213_top20_report_json", data.v213);
      if (name === "unknown") {
        await expect(ingestV213ActivationBundle(JSON.stringify(value), env)).rejects.toThrow("V213_ACTIVATION_REPORT_SCHEMA_INVALID");
        expect(publicKv.values.size).toBe(0); expect(privateKv.values.size).toBe(0);
      } else {
        expect((await ingestV213ActivationBundle(JSON.stringify(value), env)).status).toBe("accepted");
        const stored = JSON.parse(publicKv.values.get(`snapshot:${RUN_ID}:v212:top20-report:latest`)!);
        expect(stored.records[19].retrieved_at).toBe(data.source_time);
        expect(stored.records[19].source_acquisition).toEqual(data.v212.records[19].source_acquisition);
        const view = await pinPublicSnapshot(env); expect(view.integrity).toBe("sealed");
        expect((await readV213Top20Report(view))!.records[19]!.retrieved_at).toBe(data.source_time);
        expect((await ingestV213ActivationBundle(JSON.stringify(value), env)).idempotent_replay).toBe(true);
      }
    } finally { vi.useRealTimers(); }
  });

  it.each(["legacy_downgrade", "changed_profit", "renewed_seven_clock", "old_last_row"])("refuses %s with valid hashes before any sealed write", async mode => {
    const { env, publicKv, privateKv } = runtime(); const value = await bundle();
    const five = JSON.parse(value.payloads.v212_top20_report_json); const seven = JSON.parse(value.payloads.v213_top20_report_json);
    let code = "V213_ACTIVATION_REPORT_ACQUISITION_MISMATCH";
    if (mode === "legacy_downgrade") {
      five.schema_version = 1; delete five.calculation_cutoff;
      for (const row of five.records) { row.schema_version = 1; delete row.source_acquisition; }
      await replacePayload(value, "v212_top20_report_json", five); code = "V213_ACTIVATION_REPORT_SCHEMA_INVALID";
    } else {
      if (mode === "changed_profit") seven.records[19].profit_summary = "獲利；淨利率 99.0%";
      if (mode === "renewed_seven_clock") seven.records[19].retrieved_at = new Date(Date.parse(value.generated_at) + 1000).toISOString();
      if (mode === "old_last_row") { seven.records[19].retrieved_at = new Date(Date.parse(value.generated_at) - 3 * 3600_000).toISOString(); code = "V213_ACTIVATION_SOURCE_ACQUISITION_STALE"; }
      await replacePayload(value, "v213_top20_report_json", seven);
    }
    await expect(ingestV213ActivationBundle(JSON.stringify(value), env)).rejects.toThrow(code);
    expect(publicKv.values.size).toBe(0); expect(privateKv.values.size).toBe(0);
  });

  it("rechecks execution-clock freshness before pointer-last commit and retains failed transaction history", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    try {
      const { env, publicKv, privateKv } = runtime(); const value = await bundle();
      const prior = JSON.stringify({ run_id: "20260901T000000Z-aaaaaaaaaaaa" }); publicKv.values.set("snapshot:current", prior);
      const original = publicKv.put.bind(publicKv); let advanced = false;
      const write = vi.spyOn(publicKv, "put").mockImplementation(async (key, body) => {
        await original(key, body);
        if (!advanced && key.startsWith(`snapshot:${RUN_ID}:`)) { advanced = true; vi.setSystemTime(Date.now() + 3 * 3600_000); }
      });
      await expect(ingestV213ActivationBundle(JSON.stringify(value), env)).rejects.toThrow("V213_ACTIVATION_SOURCE_ACQUISITION_STALE");
      expect(advanced).toBe(true); expect(publicKv.values.get("snapshot:current")).toBe(prior);
      expect(write.mock.calls.some(call => call[0] === "snapshot:current")).toBe(false);
      expect(privateKv.values.size).toBeGreaterThan(0); // retained journal, no pretend rollback
    } finally { vi.useRealTimers(); }
  });

  it("rejects credential citations even with valid payload digests before any KV write", async () => {
    const { env, publicKv, privateKv, securityKv } = runtime();
    const value = await bundle();
    const report = JSON.parse(value.payloads.v213_top20_report_json);
    report.records[0].orders_confidence = "PRIMARY_ONLY";
    report.records[0].orders_as_of = value.generated_at;
    report.records[0].current_order_source_urls = ["https://example.com/report?access%255ftoken=synthetic"];
    await replacePayload(value, "v213_top20_report_json", report);
    await expect(ingestV213ActivationBundle(JSON.stringify(value), env)).rejects.toThrow("V213_ACTIVATION_REPORT_SCHEMA_INVALID");
    expect(publicKv.values.size).toBe(0);
    expect(privateKv.values.size).toBe(0);
    expect(securityKv.values.size).toBe(0);
    report.records[0].current_order_source_urls = ["https://example.com/report"];
    await replacePayload(value, "v213_top20_report_json", report);
    expect((await ingestV213ActivationBundle(JSON.stringify(value), env)).status).toBe("accepted");
  });
  it("preflights the exact supplied sealed bundle through Worker commit/readback/replay/rollback/finalize without network", async () => {
    const network = vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("OFFLINE_PREFLIGHT_NETWORK_FORBIDDEN"));
    try {
      const archived = process.env.V213_WORKER_ARCHIVED_BUNDLE;
      if (archived && process.env.V213_WORKER_PREFLIGHT_BUNDLE) throw new Error("AMBIGUOUS_PREFLIGHT_MODE");
      const supplied = archived ?? process.env.V213_WORKER_PREFLIGHT_BUNDLE;
      const candidate = await bundle();
      await replacePayload(candidate, "top20_json", withFilingProvenance(top20(candidate.generated_at)));
      const original = supplied ? readFileSync(supplied) : Buffer.from(JSON.stringify(candidate));
      const body = original.toString("utf8").replace(/^\uFEFF/, "");
      const identity = JSON.parse(body);
      const request = JSON.stringify({ schema_version: 1, transaction_id: identity.transaction_id, run_id: identity.run_id });
      const { publicKv, env } = runtime();
      const prior = JSON.stringify({ run_id: "20260901T000000Z-aaaaaaaaaaaa", marker: "exact rollback" });
      publicKv.values.set("snapshot:current", prior);
      if (archived) {
        // Regression replay only: real-time freshness rejection remains mandatory.
        // This receipt can NEVER satisfy the product's status=PASS predeploy gate.
        await expect(ingestV213ActivationBundle(body, env)).rejects.toThrow("V213_ACTIVATION_BUNDLE_STALE");
        expect(publicKv.values.get("snapshot:current")).toBe(prior);
        vi.useFakeTimers({ toFake: ["Date"] });
        vi.setSystemTime(Date.parse(identity.generated_at) + 60_000);
      }
      const accepted = await ingestV213ActivationBundle(body, env);
      expect(accepted.status).toBe("accepted");
      expect(accepted.pointer_written_last).toBe(true);
      const objectKey = `snapshot:${identity.run_id}:v21:top20:latest`;
      const stored = publicKv.values.get(objectKey)!;
      expect(JSON.stringify(JSON.parse(stored)) === JSON.stringify(JSON.parse(identity.payloads.top20_json))).toBe(true);
      expect((await ingestV213ActivationBundle(body, env)).idempotent_replay).toBe(true);
      publicKv.values.set(objectKey, "corrupt synthetic readback");
      await expect(ingestV213ActivationBundle(body, env)).rejects.toThrow("V213_ACTIVATION_REPLAY_CORRUPT");
      publicKv.values.set(objectKey, stored);
      expect((await rollbackV213Activation(request, env)).exact_pointer_restored).toBe(true);
      expect(publicKv.values.get("snapshot:current")).toBe(prior);
      expect((await ingestV213ActivationBundle(body, env)).status).toBe("accepted");
      expect((await finalizeV213Activation(request, env)).status).toBe("finalized");
      expect(network).not.toHaveBeenCalled();
      if (supplied) {
        const receiptPath = process.env.V213_WORKER_PREFLIGHT_RECEIPT;
        if (receiptPath) writeFileSync(receiptPath, JSON.stringify({
          status: archived ? "PASS_HISTORICAL_SCHEMA_ONLY" : "PASS", bundle_sha256: createHash("sha256").update(original).digest("hex"),
          historical_clock: Boolean(archived), current_time_freshness: archived ? "REJECTED_STALE" : "PASS",
          commit_readback_replay_rollback_finalize: "PASS", network: false, production_mutation: false,
        }));
        console.log(`V213_EXACT_BUNDLE_WORKER_PREFLIGHT = ${archived ? "PASS_HISTORICAL_SCHEMA_ONLY; current_time=REJECTED_STALE" : "PASS"}; commit_readback_replay_rollback_finalize=PASS; network=false; production_mutation=false`);
      }
    } finally { network.mockRestore(); vi.useRealTimers(); }
  });

  it("retains the closed SEC filing provenance schema without treating it as positive-factor support", () => {
    const rows = withFilingProvenance(top20(new Date().toISOString()));
    expect(parseV21Top20(rows)).toEqual(rows);
  });

  it("rejects unknown evidence fields, false provenance assertions, wrong dates and accession URLs", () => {
    const rows = withFilingProvenance(top20(new Date().toISOString()));
    for (const change of [
      { extra: true }, { can_prove_positive_serenity_factor: true },
      { retrieval_timestamp_used_as_publication_date: true }, { provenance_only: false },
      { claim_primary: false }, { primary: false }, { family: "issuer_primary" },
      { publication_date: "2026-02-30" }, { publication_date: "2099-01-01", as_of: "2099-01-01" },
      { period_end: "2099-01-01" }, { accession_number: "incorrect" },
      { url: "https://example.com/Archives/edgar/data/1000000/000100000026000001/" },
      { url: "https://www.sec.gov/Archives/edgar/data/1000000/000100000026000002/" },
    ]) {
      const invalid = structuredClone(rows);
      Object.assign(invalid[0]!.evidence[0]!, change);
      expect(parseV21Top20(invalid)).toBeNull();
    }
    const missing = structuredClone(rows) as any[];
    delete missing[0].evidence[0].period_end;
    expect(parseV21Top20(missing)).toBeNull();
  });
  it("writes all immutable objects before switching the pointer and rolls back exact text", async () => {
    const { publicKv, privateKv, env } = runtime();
    const oldPointer = JSON.stringify({ schema_version: 1, run_id: "20260901T000000Z-aaaaaaaaaaaa", marker: "exact" });
    publicKv.values.set("snapshot:current", oldPointer);
    publicKv.values.set("snapshot:20260901T000000Z-aaaaaaaaaaaa:v211:universe:latest", "old-universe");
    publicKv.values.set("snapshot:20260901T000000Z-aaaaaaaaaaaa:options:latest", "old-options");

    const value = await bundle();
    const body = JSON.stringify(value);
    const key = "synthetic-test-only-key-".repeat(3);
    const timestamp = String(Math.floor(Date.now() / 1000));
    const nonce = "a".repeat(32);
    const version = "12345678-1234-1234-1234-123456789abc";
    const response = await productionWorker.fetch(new Request("https://synthetic.invalid/v213/admin/activation-bundle", {
      method: "POST", body, headers: {
        "x-ii-expected-worker-version": version, "x-ii-v21-timestamp": timestamp,
        "x-ii-v21-nonce": nonce,
        "x-ii-v21-signature": createHmac("sha256", key).update(`${timestamp}.${nonce}.${body}`).digest("hex"),
      },
    }), { ...env, V21_SYNC_HMAC_SECRET: key, CF_VERSION_METADATA: { id: version } } as any,
    { waitUntil: () => undefined } as unknown as ExecutionContext);
    expect(response.status).toBe(200);
    const accepted = await response.json<Record<string, unknown>>();
    expect(accepted.status).toBe("accepted");
    expect(accepted.pointer_written_last).toBe(true);
    expect(accepted.rollback_available).toBe(true);
    expect(accepted.publication_mode).toEqual({ evidenceQualified: 0, limited: 20, highEligible: 0 });
    expect(accepted.publication_mode_contract_sha256).toMatch(/^[0-9a-f]{64}$/);
    expect(JSON.parse(publicKv.values.get("snapshot:current")!).run_id).toBe(RUN_ID);
    expect(publicKv.values.get(`snapshot:${RUN_ID}:v212:top20-report:latest`)).toBeTruthy();
    expect(publicKv.values.get(`snapshot:${RUN_ID}:v213:top20-report:latest`)).toBeTruthy();
    expect(publicKv.values.get(`snapshot:${RUN_ID}:v213:source-independence:latest`)).toBeTruthy();
    expect(publicKv.values.has(`snapshot:${RUN_ID}:v211:universe:latest`)).toBe(false);
    expect(publicKv.values.has(`snapshot:${RUN_ID}:options:latest`)).toBe(false);
    publicKv.values.set('options:latest', JSON.stringify([{ source: 'stale-direct-key' }]));
    publicKv.values.set('v211:universe:latest', JSON.stringify({ source: 'stale-direct-key' }));
    expect(await publicJson(env, ['options:latest', 'latest_options'])).toBeNull();
    expect(await publicJson(env, ['v211:universe:latest'])).toBeNull();
    expect(await deterministicAnswer(env, parseQuery('AAOI options'), {
      tenantId: 'synthetic-public-only', chatType: 'user',
    })).toBe('OPTION_DATA_UNAVAILABLE');
    expect(privateKv.values.has(`v213:activation-rollback:${TRANSACTION_ID}`)).toBe(true);

    const replay = await ingestV213ActivationBundle(JSON.stringify(value), env);
    expect(replay.idempotent_replay).toBe(true);
    expect(replay.object_count).toBe(0);

    const rolledBack = await rollbackV213Activation(control(), env);
    expect(rolledBack.status).toBe("rolled_back");
    expect(rolledBack.exact_pointer_restored).toBe(true);
    expect(publicKv.values.get("snapshot:current")).toBe(oldPointer);
    expect(publicKv.values.get('snapshot:20260901T000000Z-aaaaaaaaaaaa:options:latest')).toBe('old-options');
    expect(publicKv.values.get('snapshot:20260901T000000Z-aaaaaaaaaaaa:v211:universe:latest')).toBe('old-universe');
    expect(privateKv.values.has(`v213:activation-rollback:${TRANSACTION_ID}`)).toBe(false);
  });

  it("finalizes only the matching current pointer and removes the rollback handle", async () => {
    const { publicKv, privateKv, env } = runtime();
    await ingestV213ActivationBundle(JSON.stringify(await bundle()), env);
    const finalized = await finalizeV213Activation(control(), env);
    expect(finalized.status).toBe("finalized");
    expect(finalized.rollback_handle_deleted).toBe(true);
    expect(privateKv.values.has(`v213:activation-rollback:${TRANSACTION_ID}`)).toBe(false);
    await expect(rollbackV213Activation(control(), env)).rejects.toThrow("V213_ACTIVATION_ROLLBACK_STATE_MISSING");
    expect(JSON.parse(publicKv.values.get("snapshot:current")!).run_id).toBe(RUN_ID);
  });

  it("deletes a newly-created pointer when there was no prior snapshot", async () => {
    const { publicKv, env } = runtime();
    await ingestV213ActivationBundle(JSON.stringify(await bundle()), env);
    await rollbackV213Activation(control(), env);
    expect(publicKv.values.has("snapshot:current")).toBe(false);
  });

  it("rejects a digest defect without changing the existing pointer", async () => {
    const { publicKv, securityKv, env } = runtime();
    const oldPointer = JSON.stringify({ run_id: "20260901T000000Z-aaaaaaaaaaaa" });
    publicKv.values.set("snapshot:current", oldPointer);
    const value = await bundle();
    value.sha256.top20_json = "0".repeat(64);
    await expect(ingestV213ActivationBundle(JSON.stringify(value), env)).rejects.toThrow("V213_ACTIVATION_DIGEST_MISMATCH_TOP20_JSON");
    expect(publicKv.values.get("snapshot:current")).toBe(oldPointer);
    expect(securityKv.values.size).toBe(0);
  });

  it("does not promote the pointer when object readback differs", async () => {
    const { publicKv, privateKv, env } = runtime();
    const oldPointer = JSON.stringify({ run_id: "20260901T000000Z-aaaaaaaaaaaa" });
    publicKv.values.set("snapshot:current", oldPointer);
    const value = await bundle();
    const originalGet = publicKv.get.bind(publicKv);
    publicKv.get = (async (key: string, type?: "text" | "json") => {
      if (key === `snapshot:${RUN_ID}:v213:source-independence:latest` && publicKv.values.has(key)) return "corrupt";
      return originalGet(key, type);
    }) as typeof publicKv.get;
    await expect(ingestV213ActivationBundle(JSON.stringify(value), env)).rejects.toThrow("V213_ACTIVATION_SNAPSHOT_READBACK_FAILED");
    expect(publicKv.values.get("snapshot:current")).toBe(oldPointer);
    expect(privateKv.values.has(`v213:activation-rollback:${TRANSACTION_ID}`)).toBe(true);
    publicKv.get = originalGet as typeof publicKv.get;
    const recovered = await ingestV213ActivationBundle(JSON.stringify(value), env);
    expect(recovered.recovery_status).toBe("PREPARED_JOURNAL_RESUMED");
    expect(JSON.parse(publicKv.values.get("snapshot:current")!).run_id).toBe(RUN_ID);
  });

  it("rejects corrupt or missing snapshot objects during idempotent replay", async () => {
    for (const corrupt of [false, true]) {
      const { publicKv, env } = runtime();
      const value = await bundle();
      await ingestV213ActivationBundle(JSON.stringify(value), env);
      const key = `snapshot:${RUN_ID}:v213:source-independence:latest`;
      if (corrupt) publicKv.values.set(key, "corrupt");
      else publicKv.values.delete(key);
      await expect(ingestV213ActivationBundle(JSON.stringify(value), env)).rejects.toThrow("V213_ACTIVATION_REPLAY_CORRUPT");
    }
  });

  it("rejects different content that collides with an already-claimed run ID", async () => {
    const { env } = runtime();
    await ingestV213ActivationBundle(JSON.stringify(await bundle()), env);
    await rollbackV213Activation(control(), env);
    const secondTransaction = "2".repeat(32);
    const changed = await bundle(secondTransaction, "changed");
    await expect(ingestV213ActivationBundle(JSON.stringify(changed), env)).rejects.toThrow("V213_ACTIVATION_RUN_ID_COLLISION");
  });

  it("rejects a public source sidecar that attempts to smuggle a private holding", async () => {
    const { env } = runtime();
    const value = await bundle();
    const source = JSON.parse(value.payloads.source_independence_json);
    source.portfolio.holdings = [{ ticker: "PRIVATE", shares: 1 }];
    value.payloads.source_independence_json = JSON.stringify(source);
    value.sha256.source_independence_json = await digest(value.payloads.source_independence_json);
    await expect(ingestV213ActivationBundle(JSON.stringify(value), env)).rejects.toThrow("V213_ACTIVATION_PRIVATE_FIELD");
  });

  it("accepts mixed publication modes and strict HIGH eligibility", async () => {
    const { env } = runtime();
    const value: any = await bundle("3".repeat(32));
    await makeMixed(value, true);
    const accepted = await ingestV213ActivationBundle(JSON.stringify(value), env);
    expect(accepted.publication_mode).toEqual({ evidenceQualified: 10, limited: 10, highEligible: 1 });
  });

  it("accepts a negative LIMITED factor while rejecting every unsafe LIMITED invariant", async () => {
    const negativeRuntime = runtime();
    const negative: any = await bundle("4".repeat(32));
    const negativeTop = JSON.parse(negative.payloads.top20_json);
    negativeTop[0].serenity_factors.demand_wave = -1;
    await replacePayload(negative, "top20_json", negativeTop);
    await expect(ingestV213ActivationBundle(JSON.stringify(negative), negativeRuntime.env)).resolves.toMatchObject({ status: "accepted" });

    const mutations: Array<[string, (value: any) => Promise<void>, string]> = [
      ["positive factor", async (value) => {
        const rows = JSON.parse(value.payloads.top20_json);
        rows[0].serenity_factors.demand_wave = 1;
        await replacePayload(value, "top20_json", rows);
      }, "V213_ACTIVATION_LIMITED_PUBLICATION_INVALID"],
      ["HIGH eligibility", async (value) => {
        const source = JSON.parse(value.payloads.source_independence_json);
        source.records[0].eligible_for_high_confidence_model_inference = true;
        source.portfolio.high_confidence_model_inference_eligible_count = 1;
        source.portfolio.limited_rows_high_confidence_eligible_count = 1;
        await replacePayload(value, "source_independence_json", source);
      }, "V213_ACTIVATION_UNCORROBORATED_CONFIDENCE_INVALID"],
      ["validated thesis", async (value) => {
        const source = JSON.parse(value.payloads.source_independence_json);
        source.records[0].public_logic_state.validated_company_thesis = true;
        await replacePayload(value, "source_independence_json", source);
      }, "V213_ACTIVATION_LIMITED_PUBLICATION_INVALID"],
      ["single provenance origin", async (value) => {
        const source = JSON.parse(value.payloads.source_independence_json);
        source.records[0].freshness_state.publication_provenance_origin_count = 1;
        await replacePayload(value, "source_independence_json", source);
      }, "V213_ACTIVATION_LIMITED_PUBLICATION_INVALID"],
      ["single provenance domain", async (value) => {
        const source = JSON.parse(value.payloads.source_independence_json);
        source.records[0].freshness_state.publication_provenance_domain_count = 1;
        await replacePayload(value, "source_independence_json", source);
      }, "V213_ACTIVATION_LIMITED_PUBLICATION_INVALID"],
    ];
    for (const [name, mutate, code] of mutations) {
      const value: any = await bundle();
      await mutate(value);
      await expect(ingestV213ActivationBundle(JSON.stringify(value), runtime().env), name).rejects.toThrow(code);
    }
  });

  it("rejects each insufficient EVIDENCE_QUALIFIED metric", async () => {
    const fields: Array<[string, number]> = [
      ["claim_relevant_independent_families", 1],
      ["claim_relevant_independent_domains", 1],
      ["claim_relevant_primary_sources", 0],
      ["claim_dated_evidence_ratio", 0.79],
    ];
    for (const [field, invalid] of fields) {
      const value: any = await bundle();
      await makeMixed(value, false);
      const source = JSON.parse(value.payloads.source_independence_json);
      source.records[0].source_metrics[field] = invalid;
      await replacePayload(value, "source_independence_json", source);
      await expect(ingestV213ActivationBundle(JSON.stringify(value), runtime().env), field).rejects.toThrow("V213_ACTIVATION_EVIDENCE_QUALIFIED_INVALID");
    }
  });

  it("rejects publication count, order, freshness, and digest defects", async () => {
    const count: any = await bundle();
    const countSource = JSON.parse(count.payloads.source_independence_json);
    countSource.portfolio.limited_research_candidate_count = 19;
    await replacePayload(count, "source_independence_json", countSource);
    await expect(ingestV213ActivationBundle(JSON.stringify(count), runtime().env)).rejects.toThrow("V213_ACTIVATION_PUBLICATION_MODE_COUNT_INVALID");

    const order: any = await bundle();
    const orderSource = JSON.parse(order.payloads.source_independence_json);
    [orderSource.records[0], orderSource.records[1]] = [orderSource.records[1], orderSource.records[0]];
    await replacePayload(order, "source_independence_json", orderSource);
    await expect(ingestV213ActivationBundle(JSON.stringify(order), runtime().env)).rejects.toThrow("V213_ACTIVATION_SOURCE_AUDIT_ORDER_INVALID");

    const freshness: any = await bundle();
    const freshnessSource = JSON.parse(freshness.payloads.source_independence_json);
    freshnessSource.records[0].freshness_state.status = "STALE";
    await replacePayload(freshness, "source_independence_json", freshnessSource);
    await expect(ingestV213ActivationBundle(JSON.stringify(freshness), runtime().env)).rejects.toThrow("V213_ACTIVATION_PUBLICATION_FRESHNESS_INVALID");

    const stale: any = await bundle();
    stale.generated_at = new Date(Date.now() - 7_201_000).toISOString();
    await expect(ingestV213ActivationBundle(JSON.stringify(stale), runtime().env)).rejects.toThrow("V213_ACTIVATION_BUNDLE_STALE");
  });

});
