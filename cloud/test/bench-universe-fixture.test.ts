import { describe, expect, it } from "vitest";
import { parseV211ResearchUniverse } from "../src/v211/research";

// Mirrors the bench fixture exactly; guarantees the seeded universe stays
// structurally valid so ticker/evidence questions fall through to the model
// lane (Pi) instead of the deterministic "no universe" fallback.
function syntheticUniverse() {
  const stamp = new Date().toISOString();
  return Array.from({ length: 20 }, (_, n) => {
    const i = n + 1;
    return {
      ticker: `BENCH${String(i).padStart(2, "0")}`,
      name: `Synthetic Bench ${i}`,
      serenity_score: 90 - i,
      serenity_raw_score: 95 - i,
      risk_penalty: 5,
      data_quality: 0.9,
      rating: "A",
      category: "Synthetic",
      serenity_factors: { demand_wave: 1, chokepoint: 1, pricing_power: 1, replacement_friction: 1, tam_capture: 1, valuation_expectations: 1, evidence_quality: 1 },
      risk_flags: [],
      aschenbrenner_overlay: { included_in_serenity_score: false, fit_score: 50 },
      evidence: [{ title: "Synthetic filing", url: "https://www.sec.gov/Archives/edgar/data/1000000/" }],
      evidence_count: 1,
      source_count: 1,
      scoring_version: "serenity-first-v2.1.0",
      line_public_eligible: true,
      provider_scope: "public_only",
      owner_watchlist_inherited: false,
      rank: i,
      generated_at: stamp,
      as_of: stamp,
    };
  });
}

describe("bench synthetic universe fixture", () => {
  it("is structurally valid and excludes NVDA so ticker falls to the model lane", () => {
    const universe = parseV211ResearchUniverse(syntheticUniverse());
    expect(universe).not.toBeNull();
    expect(universe!.length).toBe(20);
    expect(universe!.some((r) => r.ticker === "NVDA")).toBe(false);
    // Descending serenity_score ordering is preserved.
    const scores = universe!.map((r) => r.serenity_score);
    expect(scores.every((s, i) => i === 0 || (scores[i - 1] ?? 0) >= s)).toBe(true);
  });
});
