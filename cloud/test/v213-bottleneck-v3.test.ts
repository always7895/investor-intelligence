// Bottleneck-explosion Top20 v3 and the industry ranking: strict parsing, report-age bound, LINE rendering.
import { describe, expect, it } from "vitest";
import {
  buildBottleneckDetail, buildBottleneckTop20Messages, buildIndustryExplosionMessages, parseBottleneckV3,
} from "../src/v213/bottleneck-v3";

const HOUR = 3600_000;
const iso = (ms: number) => new Date(ms).toISOString().replace(/\.\d{3}Z$/, "Z");

const CONSENSUS = { revenue_fy0: 400e9, revenue_fy1: 680e9, revenue_growth: 0.7, revenue_analysts: 58, eps_fy0: 9.3, eps_fy1: 15.7,
  eps_growth: 0.688, eps_analysts: 50, target_mean: 327.7, target_analysts: 59, price: 225.07, target_upside: 0.456,
  source: "Yahoo Finance analyst estimates (unofficial)", source_url: "https://finance.yahoo.com/quote/S1/analysis", asof: "2026-09-26" };
const OUTLOOKS: Record<number, unknown> = {
  0: { orders: null, consensus: { ...CONSENSUS, revenue_growth: 28.6, revenue_analysts: 1, eps_growth: null, eps_analysts: 1, target_analysts: 1,
    target_upside: 0.9, source_url: "https://finance.yahoo.com/quote/SIVE.ST/analysis" },
    scenarios: [{ kind: "REVENUE_CONSTANT_PS", change: 28.6 }, { kind: "ANALYST_TARGET", change: 0.9 }] },
  1: { orders: { kind: "RPO", amount: 3.2e9, currency: "USD", as_of: "2026-07-26", yoy: 0.68, source: "SEC EDGAR XBRL companyfacts",
    source_url: "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json" }, consensus: CONSENSUS,
    scenarios: [{ kind: "REVENUE_CONSTANT_PS", change: 0.7 }, { kind: "EPS_CONSTANT_PE", change: 0.688 }, { kind: "ANALYST_TARGET", change: 0.456 }] },
  4: { orders: { kind: "BACKLOG", amount: 17507e9, currency: "KRW", as_of: "2026-06-30", yoy: 0.63, scope: "重工業部門（連結）",
    source: "효성중공업 26.2분기 p.9", source_url: "https://www.hyosungheavyindustries.com/download/5816",
    intake_quarter: { amount: 3324.2e9, yoy: 0.51 }, guidance: { kind: "ANNUAL_NEW_ORDERS", year: 2026, amount: 12e12, previous: 8.4e12 } },
    consensus: null, scenarios: [] },
  5: { orders: { kind: "NOT_DISCLOSED", reason: "SK海力士未揭露在手訂單" }, consensus: null, scenarios: [] },
};

function doc(generatedMs: number, overrides: Record<string, unknown> = {}) {
  const top = Array.from({ length: 20 }, (_, index) => ({
    rank: index + 1, symbol: index === 0 ? "SIVE.ST" : `S${index}`, name: `Synthetic ${index}`, layer: index % 2 ? "optics" : "memory",
    name_zh: index === 1 ? "合成一號" : null, name_zh_source: index === 1 ? "ZHWIKI" : null,
    archetype: index < 5 ? "EXPLOSION" : "COMPOUNDER", score: 80 - index,
    role: "synthetic scarce layer role", role_source: { url: "https://example.com/source", date: "2026-09-01" },
    parts: { layer_heat: 20, capture: 20, lead: 15, confirmation: 12, size: 8, penalty: index === 3 ? 2 : 0 },
    fundamentals: { source: "SEC EDGAR XBRL companyfacts", source_url: "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json",
      quarter_end: "2026-06-30", revenue_yoy: 1.09, revenue_yoy_prev: 0.9, gross_margin: 0.42, gross_margin_change: 0.14, rpo_yoy: null, shares_yoy: 0.02 },
    market: { source: "Yahoo Finance adjusted daily close (unofficial)", source_url: "https://finance.yahoo.com/quote/X", asof: "2026-09-25",
      ret_6m: 0.8, ret_1y: 2.1, cagr_2y: index === 2 ? null : 1.1, cagr_listed: index === 2 ? 0.64 : null,
      history_start: index === 2 ? "2025-02-13" : "2023-09-26", currency: "USD" },
    market_cap_usd: 1.05e9 * (index + 1),
    serenity: index % 3 === 0 ? null : { mentions: 30, bullish: 12, bearish: 1, stance: "BULLISH", latest_at: "2026-09-03T10:00:00Z",
      latest_url: "https://x.com/aleabitoreddit/status/1" },
    leopold: index === 1 ? { long_weight: 0.28, status: "HELD" } : null,
    role_zh: index === 0 ? "合成稀缺層角色" : undefined,
    outlook: OUTLOOKS[index] ? structuredClone(OUTLOOKS[index]) : null,
  }));
  const industries = ["memory", "optics", "power_generation"].map((id, index) => ({
    rank: index + 1, id, name_zh: `產業${index}`, chain: "chips_memory", leopold_constraint: "HBM and CoWoS are near-term constraints.",
    leopold_constraint_zh: index === 0 ? "HBM 與 CoWoS 是近期限制。" : undefined,
    explosiveness: 90 - index * 10, median_revenue_yoy: 1.9, median_acceleration: 0.22, median_return_6m: 0.5,
    fund_13f_weight: 0.55, serenity_heat: 40, news: { source: "SEC EDGAR full-text search", source_url: "https://efts.sec.gov/LATEST/search-index?q=x",
      recent_30d: 296, prior_60d: 197, ratio: 3.0 },
  }));
  return { schema: "v213-bottleneck-top20-v3-sealed", generated_at: iso(generatedMs),
    serenity_source: { url: "https://raw.githubusercontent.com/yan-labs/serenity-aleabitoreddit/main/data/aleabitoreddit_tweets.json", latest_post_at: "2026-09-17T23:56:29Z" },
    leopold_filing: { period: "2026-06-30", filed: "2026-08-14", url: "https://www.sec.gov/Archives/edgar/data/2045724/x.xml" },
    top, industries, deep_reports: { "SIVE.ST": null, S1: {
      ticker: "S1", name: "Synthetic One", as_of: "2026-09-25", boundary: "公開資料研究，非投資建議",
      phase: { phase: "EARLY_VALIDATION", next_review_at: "2026-11-01" },
      sections: [{ title: "業務", text: "合成業務描述" }, { title: "財務", text: "營收年增 +109%" }, { title: "訂單", text: "未揭露" }],
      source_references: [{ source: "SEC 10-Q", url: "https://www.sec.gov/Archives/edgar/data/1/x.htm", period: "2026Q2" }],
      kpis: [{ label: "RPO 年增", value: 35.2, unit: "%", signed: true, period: "2026-06-30" }],
      orders: { as_of: "2026-06-30", form: "10-Q", filed: "2026-08-05", coverage_pct: { m6: 40, m12: 132.5, m24: null },
        floor_growth_pct: { m6: null, m12: 32.5, m24: null } },
    } }, ...overrides };
}

describe("bottleneck-explosion Top20 v3", () => {
  it("parses a fresh document and refuses stale, malformed or mis-ranked ones", () => {
    const now = Date.now();
    expect(parseBottleneckV3(doc(now - HOUR))?.top).toHaveLength(20);
    expect(parseBottleneckV3(doc(now - 15 * HOUR))).toBeNull();
    const bad = doc(now - HOUR); (bad.top[4] as any).fundamentals.source_url = "http://insecure.example"; expect(parseBottleneckV3(bad)).toBeNull();
    const translated = doc(now - HOUR); (translated.top[3] as any).name_zh = "機翻名"; (translated.top[3] as any).name_zh_source = "MACHINE";
    expect(parseBottleneckV3(translated)).toBeNull();
    const shuffled = doc(now - HOUR); (shuffled.top[0] as any).rank = 2; expect(parseBottleneckV3(shuffled)).toBeNull();
    const insecure = doc(now - HOUR); (insecure.top[1] as any).outlook.orders.source_url = "http://x"; expect(parseBottleneckV3(insecure)).toBeNull();
    const invented = doc(now - HOUR); (invented.top[1] as any).outlook.scenarios.push({ kind: "MOON", change: 9 }); expect(parseBottleneckV3(invented)).toBeNull();
    const older = doc(now - HOUR); for (const entry of older.top as any[]) { delete entry.outlook; delete entry.role_zh; }
    expect(parseBottleneckV3(older)?.top).toHaveLength(20);  // documents sealed before outlooks still render
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
    // Chinese name next to the original, or the explicit statement that none exists (never a translation).
    expect(serialized).toContain("S1｜合成一號");
    expect(serialized).toContain("中文名來源：中文維基百科");
    expect(serialized).toContain("SIVE.ST｜無公認中文名");
    // One long-term standard on every card: 6-month return and 2-year CAGR; younger listings say so.
    expect(serialized.match(/"2年年化"/g)).toHaveLength(20);
    expect(serialized).not.toContain("1年報酬");
    expect(serialized).toContain("上市未滿2年");
    expect(serialized).toContain("2025-02-13起年化 +64%");
    // Lead scores are not shown; signed-order floors from the sealed SEC report are.
    expect(serialized).not.toMatch(/Serenity|Leopold 基金|"線索"/);
    expect(serialized).toContain("訂單實現下限（已簽約 RPO）");
    expect(serialized).toContain("≥+33%");
    expect(serialized).toContain("非 SEC 定期申報公司");
    // Operator 2026-09-26: current orders, the future estimate and the price scenario if realized, on every card.
    expect(serialized.match(/"訂單與成長情境"/g)).toHaveLength(20);
    expect(serialized).toContain("目前訂單：RPO US$3.2B（2026-07-26，+68%）");
    expect(serialized).toContain("目前訂單：在手訂單 17.51兆 KRW（2026-06-30，+63%）；2026年接單指引 12.00兆 KRW");
    expect(serialized).toContain("目前訂單：未揭露");
    expect(serialized).toContain("未來預估：下一財年營收 +70%（58位分析師）");
    expect(serialized).toContain("若實現股價情境：營收實現·市銷率不變 +70%｜EPS實現·本益比不變 +69%｜分析師目標價 +46%");
    expect(serialized).toContain("分析師樣本不足（1 位），不列推算");  // one analyst: no scenario on the card
    expect(serialized).not.toContain("+2860%");
    expect(serialized).toContain("未來預估：分析師樣本不足（1位），見瓶頸詳情");
    expect(serialized).toContain("非預測、非投資建議");
    // Chinese first, the original kept; source labels in Chinese.
    expect(serialized).toContain("合成稀缺層角色");
    expect(serialized).not.toContain("原文：");  // the English original is on the detail card
    expect(serialized).toContain("財報：SEC EDGAR XBRL 財報資料");
    expect(serialized).toContain("股價：Yahoo Finance 還原收盤價（非官方）");
    expect(flex.length).toBeLessThanOrEqual(5);  // one LINE reply
    const text = buildBottleneckTop20Messages(parsed, "text") as { text: string }[];
    expect(text[0]!.text).toContain("為負者排除");
    expect(text[0]!.text).toContain("S1 合成一號（Synthetic 1）");
    const detail = buildBottleneckDetail(parsed, "sive.st") as { text: string }[];
    expect(detail[0]!.text).toContain("https://data.sec.gov/api/xbrl/companyfacts/");
    expect(detail[0]!.text).not.toMatch(/Serenity|Leopold/);
    expect(detail[0]!.text).toContain("瓶頸位置：合成稀缺層角色（原文：synthetic scarce layer role）");
    expect(detail[0]!.text).toContain("僅 1 位分析師，參考性低");
    expect(buildBottleneckDetail(parsed, "ZZZ")).toContain("不在本輪");
    // Operator 2026-09-26: every detail is a card with the full figures, orders, estimate, scenarios and sources;
    // an SEC filer's sealed company report follows it.
    const withReport = buildBottleneckDetail(parsed, "S1", "flex") as { type: string; altText: string }[];
    expect(withReport.length).toBeGreaterThanOrEqual(2);
    expect(withReport.length).toBeLessThanOrEqual(5);
    expect(withReport[0]!.altText).toBe("瓶頸詳情｜S1 合成一號");  // the detail card first, then the company report
    const s1 = JSON.stringify(withReport);
    expect(s1).toContain("Synthetic One");
    for (const label of ["財報數據", "前一季年增", "加速度", "股數年增", "市場數據", "訂單與成長情境", "EPS實現·本益比不變",
      "50 位", "預估來源：https://finance.yahoo.com/quote/S1/analysis", "訂單來源：SEC EDGAR XBRL 財報資料"]) expect(s1).toContain(label);
    expect(s1).toContain("目前訂單：剩餘履約義務（RPO，已簽約未認列） US$3.2B（2026-07-26，年增 +68%）");
    expect(s1).toContain("下一財年營收 +70.0%（58 位）");
    const korea = JSON.stringify(buildBottleneckDetail(parsed, "S4", "flex"));
    expect(korea).toContain("目前訂單：在手訂單（重工業部門（連結）） 17.51兆 KRW（2026-06-30，年增 +63%）");
    expect(korea).toContain("最新一季新接訂單 3.32兆 KRW（年增 +51%）");
    expect(korea).toContain("公司指引：2026 年新接訂單 12.00兆 KRW（原 8.40兆 KRW）");
    expect(JSON.stringify(buildBottleneckDetail(parsed, "S5", "flex"))).toContain("目前訂單：未揭露（SK海力士未揭露在手訂單）");
    const sive = buildBottleneckDetail(parsed, "SIVE.ST", "flex") as { contents: unknown }[];
    expect(sive).toHaveLength(1);  // no sealed report: the detail card only
    const sivePayload = JSON.stringify(sive);
    expect(sivePayload).toContain("+2860%");  // the detail shows the thin estimate, marked as such
    expect(sivePayload).toContain("僅 1 位分析師，參考性低");
    expect(sivePayload).toContain("原文：synthetic scarce layer role");
    expect(sivePayload).not.toMatch(/Serenity|Leopold/);
    expect(sivePayload).toContain("回瓶頸 TOP20");
    expect(sivePayload).toContain("市場若已反映部分成長，實際漲幅較小");  // the scenario states its basis
    const textWithReport = buildBottleneckDetail(parsed, "S1", "text") as { type: string; text: string }[];
    expect(textWithReport.length).toBeLessThanOrEqual(5);
    expect(textWithReport[0]!.text).toContain("若實現的股價情境：營收實現·市銷率不變 +70%");
    expect(textWithReport.every(message => message.type === "text" && message.text.length <= 4900)).toBe(true);
    const industries = JSON.stringify(buildIndustryExplosionMessages(parsed, "flex"));
    expect(industries).toContain("Leopold 邏輯");
    expect(industries).toContain("HBM 與 CoWoS 是近期限制。");
    expect(industries).toContain("原文：HBM and CoWoS are near-term constraints.");
    expect(industries).toContain("3.00x");
    expect(industries).not.toMatch(/Serenity 熱度|基金13F占比/);
  });

  it("falls back to lean cards instead of a failed reply when twenty full cards exceed five carousels", () => {
    const heavy = doc(Date.now() - HOUR);
    for (const entry of heavy.top as any[]) {
      entry.role_source.url = `https://example.com/${"r".repeat(170)}`;
      entry.outlook = structuredClone(OUTLOOKS[1]);
      entry.name = "N".repeat(80);
    }
    const parsed = parseBottleneckV3(heavy)!;
    const bubbles = buildBottleneckTop20Messages(parsed, "flex") as unknown as { contents: { contents: unknown[] } }[];
    expect(bubbles.length).toBeLessThanOrEqual(5);
    expect(bubbles.reduce((total, message) => total + message.contents.contents.length, 0)).toBe(20);
    const serialized = JSON.stringify(bubbles);
    expect(serialized.match(/"訂單與成長情境"/g)).toHaveLength(20);
    expect(serialized).toContain("目前訂單：RPO US$3.2B");
  });
});
