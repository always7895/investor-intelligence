import { describe, expect, it } from "vitest";
import type { V21AdminEnv } from "../src/v21/admin";
import { ingestV211PublicSnapshot } from "../src/v211/admin";
import { MemoryKv, asKv } from "./fake-kv";

function record(index: number) {
  const ticker = `U${String(index).padStart(2, "0")}`;
  return {
    ticker,
    name: `Universe ${index}`,
    serenity_score: 100 - index,
    serenity_raw_score: 100 - index,
    risk_penalty: 0,
    data_quality: 0.9,
    rating: "A",
    category: "Semiconductors",
    serenity_factors: {
      demand_wave: 15,
      chokepoint: 14,
      pricing_power: 13,
      replacement_friction: 9,
      tam_capture: 14,
      valuation_expectations: 13,
      evidence_quality: 12,
    },
    risk_flags: [],
    aschenbrenner_overlay: {
      domain: "C",
      fit_score: 60,
      included_in_serenity_score: false,
      attribution: "system_operationalization_not_aschenbrenner_stock_score",
    },
    evidence: [{
      source_id: "sec_edgar",
      tier: "T0",
      claim_type: "xbrl_fact",
      title: `SEC ${ticker}`,
      url: `https://www.sec.gov/example/${ticker}`,
      as_of: "2026-08-31T00:00:00Z",
    }],
    evidence_count: 1,
    source_count: 2,
    scoring_version: "serenity-first-v2.1.0",
    line_public_eligible: true,
    provider_scope: "public_only",
    owner_watchlist_inherited: false,
    rank: index + 1,
    generated_at: "2026-08-31T00:00:00Z",
    as_of: "2026-08-31T00:00:00Z",
  };
}

function option(ticker: string) {
  return {
    schema_version: 1,
    ticker,
    provider_symbol: ticker,
    currency: "USD",
    current_price: 100,
    retrieved_at: "2026-08-31T00:00:00Z",
    status: "NO_ELIGIBLE_LIQUID_QUOTE",
    quote_source: "yfinance",
    quote_delay_status: "THIRD_PARTY_DELAY_UNKNOWN",
    provider_scope: "public_only",
    line_public_eligible: true,
    ibkr_connected: false,
    brokerage_data_included: false,
    account_data_included: false,
    position_data_included: false,
    owner_watchlist_inherited: false,
    periods: {},
  };
}

async function digest(value: string): Promise<string> {
  const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(bytes), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

describe("v2.1.1 public snapshot ingestion", () => {
  it("promotes Top20 plus research universe and public options under one run", async () => {
    const universe = Array.from({ length: 25 }, (_, index) => record(index));
    const top20 = universe.slice(0, 20);
    const options = universe.map((item) => option(item.ticker));
    const plan = {
      schema_version: 1,
      catalog_count: 99,
      automatic_activation: false,
      owner_watchlist_inherited: false,
      provider_scope: "public_only",
      line_public_eligible: true,
      inventory: { source_count: 99, runtime_enabled_count: 0, topic_counts: {} },
      v211_discovery: {
        product_version: "2.1.1",
        scoring_formula_changed: false,
        owner_watchlist_inherited: false,
        scored_universe_count: 25,
      },
    };
    const report = [
      "<!-- line-public-eligible: true -->",
      "<!-- provider-scope: public_only -->",
      "<!-- owner-watchlist-inherited: false -->",
      "<!-- scoring-version: serenity-first-v2.1.0 -->",
      "# v2.1.1 test",
      "public evidence ".repeat(30),
    ].join("\n");
    const payloads = {
      top20_json: JSON.stringify(top20),
      research_universe_json: JSON.stringify(universe),
      options_json: JSON.stringify(options),
      source_plan_json: JSON.stringify(plan),
      report_text: report,
    };
    const sha256: Record<string, string> = {};
    for (const [name, value] of Object.entries(payloads)) sha256[name] = await digest(value);
    const body = JSON.stringify({
      schema_version: 2,
      run_id: "20260831T000000Z-123456789abc",
      generated_at: "2026-08-31T00:00:00Z",
      public_data_as_of: "2026-08-31T00:00:00Z",
      payloads,
      sha256,
    });

    const publicKv = new MemoryKv();
    const env: V21AdminEnv = {
      PUBLIC_CACHE: asKv(publicKv),
      TENANT_PRIVATE_CACHE: asKv(new MemoryKv()),
      EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()),
    };
    const accepted = await ingestV211PublicSnapshot(body, env);
    expect(accepted.research_universe_count).toBe(25);
    expect(accepted.options_count).toBe(25);
    expect(publicKv.values.has("snapshot:20260831T000000Z-123456789abc:v211:universe:latest")).toBe(true);
    expect(publicKv.values.has("snapshot:20260831T000000Z-123456789abc:options:latest")).toBe(true);
  });
});
