// Bottleneck-explosion Top20 v3 and the industry ranking: strict parsing, report-age bound, LINE rendering.
import { describe, expect, it } from "vitest";
import {
  buildBottleneckDetail, buildBottleneckTop20Messages, buildIndustryExplosionMessages, parseBottleneckV3,
} from "../src/v213/bottleneck-v3";

const HOUR = 3600_000;
const iso = (ms: number) => new Date(ms).toISOString().replace(/\.\d{3}Z$/, "Z");

function doc(generatedMs: number, overrides: Record<string, unknown> = {}) {
  const top = Array.from({ length: 20 }, (_, index) => ({
    rank: index + 1, symbol: index === 0 ? "SIVE.ST" : `S${index}`, name: `Synthetic ${index}`, layer: index % 2 ? "optics" : "memory",
    archetype: index < 5 ? "EXPLOSION" : "COMPOUNDER", score: 80 - index,
    role: "synthetic scarce layer role", role_source: { url: "https://example.com/source", date: "2026-09-01" },
    parts: { layer_heat: 20, capture: 20, lead: 15, confirmation: 12, size: 8, penalty: index === 3 ? 2 : 0 },
    fundamentals: { source: "SEC EDGAR XBRL companyfacts", source_url: "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json",
      quarter_end: "2026-06-30", revenue_yoy: 1.09, revenue_yoy_prev: 0.9, gross_margin: 0.42, gross_margin_change: 0.14, rpo_yoy: null, shares_yoy: 0.02 },
    market: { source: "Yahoo Finance adjusted daily close (unofficial)", source_url: "https://finance.yahoo.com/quote/X", asof: "2026-09-25",
      ret_6m: 0.8, ret_1y: 2.1, cagr_2y: index === 2 ? null : 1.1, currency: "USD" },
    market_cap_usd: 1.05e9 * (index + 1),
    serenity: index % 3 === 0 ? null : { mentions: 30, bullish: 12, bearish: 1, stance: "BULLISH", latest_at: "2026-09-03T10:00:00Z",
      latest_url: "https://x.com/aleabitoreddit/status/1" },
    leopold: index === 1 ? { long_weight: 0.28, status: "HELD" } : null,
  }));
  const industries = ["memory", "optics", "power_generation"].map((id, index) => ({
    rank: index + 1, id, name_zh: `產業${index}`, chain: "chips_memory", leopold_constraint: "HBM and CoWoS are near-term constraints.",
    explosiveness: 90 - index * 10, median_revenue_yoy: 1.9, median_acceleration: 0.22, median_return_6m: 0.5,
    fund_13f_weight: 0.55, serenity_heat: 40, news: { source: "SEC EDGAR full-text search", source_url: "https://efts.sec.gov/LATEST/search-index?q=x",
      recent_30d: 296, prior_60d: 197, ratio: 3.0 },
  }));
  return { schema: "v213-bottleneck-top20-v3-sealed", generated_at: iso(generatedMs),
    serenity_source: { url: "https://raw.githubusercontent.com/yan-labs/serenity-aleabitoreddit/main/data/aleabitoreddit_tweets.json", latest_post_at: "2026-09-17T23:56:29Z" },
    leopold_filing: { period: "2026-06-30", filed: "2026-08-14", url: "https://www.sec.gov/Archives/edgar/data/2045724/x.xml" },
    top, industries, ...overrides };
}

describe("bottleneck-explosion Top20 v3", () => {
  it("parses a fresh document and refuses stale, malformed or mis-ranked ones", () => {
    const now = Date.now();
    expect(parseBottleneckV3(doc(now - HOUR))?.top).toHaveLength(20);
    expect(parseBottleneckV3(doc(now - 15 * HOUR))).toBeNull();
    const bad = doc(now - HOUR); (bad.top[4] as any).fundamentals.source_url = "http://insecure.example"; expect(parseBottleneckV3(bad)).toBeNull();
    const shuffled = doc(now - HOUR); (shuffled.top[0] as any).rank = 2; expect(parseBottleneckV3(shuffled)).toBeNull();
    expect(parseBottleneckV3(doc(now - HOUR, { schema: "other" }))).toBeNull();
  });

  it("renders LINE carousels within limits, a sourced detail and the industry ranking", () => {
    const parsed = parseBottleneckV3(doc(Date.now() - HOUR))!;
    const flex = buildBottleneckTop20Messages(parsed, "flex");
    expect(flex.length).toBeGreaterThanOrEqual(4);
    const serialized = JSON.stringify(flex);
    expect(serialized).toContain("SIVE.ST");
    expect(serialized).toContain("瓶頸詳情 SIVE.ST");
    expect(serialized).toContain("+109%");
    const text = buildBottleneckTop20Messages(parsed, "text") as { text: string }[];
    expect(text[0]!.text).toContain("長期報酬為負者排除");
    const detail = buildBottleneckDetail(parsed, "sive.st") as { text: string }[];
    expect(detail[0]!.text).toContain("https://data.sec.gov/api/xbrl/companyfacts/");
    expect(detail[0]!.text).toContain("線索只影響排序權重");
    expect(buildBottleneckDetail(parsed, "ZZZ")).toContain("不在本輪");
    const industries = JSON.stringify(buildIndustryExplosionMessages(parsed, "flex"));
    expect(industries).toContain("Leopold 邏輯");
    expect(industries).toContain("3.00x");
  });
});
