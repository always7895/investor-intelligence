import { describe, expect, it } from "vitest";
import { parseQuery } from "../src/core";
import type { StorageEnv } from "../src/storage";
import { humanizeFallback, parseV211ResearchUniverse, v211ResearchAnswer } from "../src/v211/research";
import { MemoryKv, asKv } from "./fake-kv";

function record(index: number) {
  const ticker = `T${String(index).padStart(2, "0")}`;
  return {
    ticker,
    name: `Company ${index}`,
    serenity_score: 100 - index,
    serenity_raw_score: 100 - index,
    risk_penalty: 0,
    data_quality: 0.9,
    rating: "A",
    category: index % 2 ? "Semiconductors" : "Communication Equipment",
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
      title: `SEC evidence ${ticker}`,
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
  } as const;
}

async function envWithUniverse(): Promise<StorageEnv> {
  const publicKv = new MemoryKv();
  await publicKv.put("snapshot:current", JSON.stringify({ run_id: "run-1" }));
  await publicKv.put(
    "snapshot:run-1:v211:universe:latest",
    JSON.stringify(Array.from({ length: 25 }, (_, index) => record(index))),
  );
  return {
    PUBLIC_CACHE: asKv(publicKv),
    TENANT_PRIVATE_CACHE: asKv(new MemoryKv()),
    EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()),
  };
}

describe("v2.1.1 signed-snapshot research Q&A", () => {
  it("accepts a ranked research universe larger than Top 20", () => {
    const parsed = parseV211ResearchUniverse(Array.from({ length: 25 }, (_, index) => record(index)));
    expect(parsed).not.toBeNull();
    expect(parsed?.[20]?.rank).toBe(21);
  });

  it("answers greetings without exposing LOCAL_MODEL_NOT_CONFIGURED", async () => {
    const answer = await v211ResearchAnswer(await envWithUniverse(), parseQuery("你好"));
    expect(answer).toContain("公開研究問答");
    expect(answer).not.toContain("LOCAL_MODEL_NOT_CONFIGURED");
  });

  it("answers a ticker outside Top 20 from the scored universe", async () => {
    const answer = await v211ResearchAnswer(await envWithUniverse(), parseQuery("T20 怎麼看"));
    expect(answer).toContain("T20");
    expect(answer).toContain("#21/25");
    expect(answer).toContain("未進 Top 20");
  });

  it("compares two scored tickers deterministically", async () => {
    const answer = await v211ResearchAnswer(await envWithUniverse(), parseQuery("T20 vs T21 比較"));
    expect(answer).toContain("T20 vs T21");
    expect(answer).toContain("需求");
    expect(answer).toContain("估值");
  });

  it("does not intercept the options intent", async () => {
    const answer = await v211ResearchAnswer(await envWithUniverse(), parseQuery("T20 這週 sell call"));
    expect(answer).toBeNull();
  });

  it("humanizes raw availability codes", () => {
    expect(humanizeFallback("LOCAL_MODEL_NOT_CONFIGURED", parseQuery("任意問題"))).not.toContain("LOCAL_MODEL_NOT_CONFIGURED");
    expect(humanizeFallback("OPTION_DATA_UNAVAILABLE", parseQuery("T20 這週 sell call"))).toContain("T20");
  });
});
