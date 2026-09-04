import { describe, expect, it } from "vitest";
import { formatV21Top20, parseV21Top20 } from "../src/v21/top20";

function records() {
  const generated = "2026-09-02T00:00:00Z";
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
      demand_wave: 12,
      chokepoint: 0,
      pricing_power: 9,
      replacement_friction: 0,
      tam_capture: 6,
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
      {
        source_id: "yahoo_finance_public_unofficial",
        tier: "T3",
        claim_type: "public_market_observation",
        title: `Yahoo observation ${index}`,
        url: `https://finance.yahoo.com/quote/T${String(index).padStart(2, "0")}`,
        as_of: generated,
      },
    ],
    evidence_count: 3,
    source_count: 3,
    scoring_version: "system-operationalization-v2.1.3-diversified" as const,
    line_public_eligible: true as const,
    provider_scope: "public_only" as const,
    owner_watchlist_inherited: false as const,
    rank: index + 1,
    generated_at: generated,
    as_of: generated,
  }));
}

describe("v2.1.3 diversified Top20", () => {
  it("accepts transparent multi-source rows and uses corrected labels", () => {
    const parsed = parseV21Top20(records());
    expect(parsed).not.toBeNull();
    const text = formatV21Top20(parsed!, "Investor Intelligence");
    expect(text).toContain("系統量化分");
    expect(text).toContain("101 個來源是受審查目錄");
    expect(text).toContain("Yahoo/yfinance 僅為 T3 觀測");
    expect(text).toContain("非 Serenity 官方公式");
  });

  it("rejects proxy-only chokepoint or replacement-friction points", () => {
    const value = records();
    value[0]!.serenity_factors.chokepoint = 1;
    expect(parseV21Top20(value)).toBeNull();
    value[0]!.serenity_factors.chokepoint = 0;
    value[0]!.serenity_factors.replacement_friction = 1;
    expect(parseV21Top20(value)).toBeNull();
  });

  it("rejects source-count inflation", () => {
    const value = records();
    value[0]!.source_count = 4;
    expect(parseV21Top20(value)).toBeNull();
  });
});
