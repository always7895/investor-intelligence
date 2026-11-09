import { describe, expect, it } from "vitest";
import { doc } from "./bottleneck-v3-fixture";
import { buildBottleneckDetail, estimateTop20Fallback, parseBottleneckV3, type BottleneckV3 } from "../src/v213/bottleneck-v3";

const AT = Date.parse("2026-11-09T02:15:59Z");
function fixture(ownGrowth: number | null, layerGrowth: number | null): BottleneckV3 {
  const parsed = parseBottleneckV3(doc(AT), AT);
  if (!parsed) throw new Error("FALLBACK_FIXTURE_INVALID");
  const first = parsed.top[0]!;
  first.fundamentals = { ...first.fundamentals!, revenue: 100_000_000, revenue_unit: "USD",
    revenue_yoy: ownGrowth, revenue_yoy_prev: null };
  first.outlook = undefined;
  first.forecast = undefined;
  first.trend = undefined;
  parsed.deep_reports = {};
  const layer = parsed.industries.find(row => row.id === first.layer);
  if (!layer) throw new Error("FALLBACK_LAYER_MISSING");
  layer.median_revenue_yoy = layerGrowth;
  return parsed;
}

describe("Top20 conservative growth fallback", () => {
  it("clips a high-growth industry observation explicitly rather than inventing a flat median", () => {
    const ranking = fixture(3.78, 3.78);
    const result = estimateTop20Fallback(ranking, ranking.top[0]!);
    expect(result?.m6.change).toBe(0.25);
    expect(result?.m12.change).toBe(0.5);
    expect(result?.m6.amount).toBe(250_000_000);
    expect(result?.m12.amount).toBe(600_000_000);
    expect(result?.m12.basis).toBe("產業成長截尾推估");
    expect(result?.m12.explanation).toContain("+378%");
    expect(result?.m12.explanation).toContain("截尾至+300%");
  });

  it.each([null, -0.96])("keeps missing or rejected growth %s unknown on both detail surfaces", layerGrowth => {
    const ranking = fixture(null, layerGrowth);
    const entry = ranking.top[0]!;
    expect(estimateTop20Fallback(ranking, entry)).toBeNull();
    for (const style of ["text", "flex"] as const) {
      const rendered = JSON.stringify(buildBottleneckDetail(ranking, entry.symbol, style));
      expect(rendered).toContain("未驗證");
      expect(rendered).toContain("缺可核對");
      expect(rendered).not.toMatch(/(?:半年|1年)股價情境[：:]\s*[+＋]?0(?:\.0+)?%/);
    }
  });

  it("preserves genuinely observed zero growth instead of confusing it with missing data", () => {
    const ranking = fixture(0, null);
    const result = estimateTop20Fallback(ranking, ranking.top[0]!);
    expect(result?.m12.change).toBe(0);
    expect(result?.m12.amount).toBe(400_000_000);
    expect(result?.m12.basis).toBe("歷史推估");
  });
});
