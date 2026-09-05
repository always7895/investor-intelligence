/// <reference types="node" />
import { describe, expect, it, vi } from "vitest";
import { readFileSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { parseV21Top20 } from "../src/v21/top20";
import { asKv, MemoryKv } from "./fake-kv";
import {
  finalizeV213Activation,
  ingestV213ActivationBundle,
  rollbackV213Activation,
} from "../src/v213/activation-v2";

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
    schema_version: 1,
    product_version: "2.1.2",
    generated_at: generated,
    display_columns: [
      "股票", "長期投資報酬率（近2年年化）", "短期投資報酬率（近6個月）",
      "行業別", "獲利簡述",
    ],
    long_term_definition: "trailing_2y_adjusted_close_cagr",
    short_term_definition: "trailing_6m_adjusted_close_price_return",
    records: Array.from({ length: 20 }, (_, index) => ({
      schema_version: 1,
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

describe("v2.1.3 atomic activation transaction", () => {
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
    const accepted = await ingestV213ActivationBundle(JSON.stringify(value), env);
    expect(accepted.status).toBe("accepted");
    expect(accepted.pointer_written_last).toBe(true);
    expect(accepted.rollback_available).toBe(true);
    expect(accepted.publication_mode).toEqual({ evidenceQualified: 0, limited: 20, highEligible: 0 });
    expect(accepted.publication_mode_contract_sha256).toMatch(/^[0-9a-f]{64}$/);
    expect(JSON.parse(publicKv.values.get("snapshot:current")!).run_id).toBe(RUN_ID);
    expect(publicKv.values.get(`snapshot:${RUN_ID}:v212:top20-report:latest`)).toBeTruthy();
    expect(publicKv.values.get(`snapshot:${RUN_ID}:v213:top20-report:latest`)).toBeTruthy();
    expect(publicKv.values.get(`snapshot:${RUN_ID}:v213:source-independence:latest`)).toBeTruthy();
    expect(publicKv.values.get(`snapshot:${RUN_ID}:v211:universe:latest`)).toBe("old-universe");
    expect(publicKv.values.get(`snapshot:${RUN_ID}:options:latest`)).toBe("old-options");
    expect(privateKv.values.has(`v213:activation-rollback:${TRANSACTION_ID}`)).toBe(true);

    const replay = await ingestV213ActivationBundle(JSON.stringify(value), env);
    expect(replay.idempotent_replay).toBe(true);
    expect(replay.object_count).toBe(0);

    const rolledBack = await rollbackV213Activation(control(), env);
    expect(rolledBack.status).toBe("rolled_back");
    expect(rolledBack.exact_pointer_restored).toBe(true);
    expect(publicKv.values.get("snapshot:current")).toBe(oldPointer);
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
