// Synthetic sealed bottleneck-explosion Top20 v3 document shared by the v3 rendering and LINE routing tests.

export const HOUR = 3600_000;
const iso = (ms: number) => new Date(ms).toISOString().replace(/\.\d{3}Z$/, "Z");

const CONSENSUS = { revenue_fy0: 400e9, revenue_fy1: 680e9, revenue_growth: 0.7, revenue_analysts: 58, eps_fy0: 9.3, eps_fy1: 15.7,
  eps_growth: 0.688, eps_analysts: 50, target_mean: 327.7, target_analysts: 59, price: 225.07, target_upside: 0.456,
  source: "Yahoo Finance analyst estimates (unofficial)", source_url: "https://finance.yahoo.com/quote/S1/analysis", asof: "2026-09-26" };
export const OUTLOOKS: Record<number, unknown> = {
  0: { orders: null, consensus: { ...CONSENSUS, revenue_growth: 28.6, revenue_analysts: 1, eps_growth: null, eps_analysts: 1, target_analysts: 1,
    target_upside: 0.9, source_url: "https://finance.yahoo.com/quote/SIVE.ST/analysis" },
    scenarios: [{ kind: "REVENUE_CONSTANT_PS", change: 28.6 }, { kind: "ANALYST_TARGET", change: 0.9 }] },
  1: { orders: { kind: "RPO", amount: 3.2e9, currency: "USD", as_of: "2026-07-26", yoy: 0.68, source: "SEC EDGAR XBRL companyfacts",
    source_url: "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json" }, consensus: CONSENSUS,
    scenarios: [{ kind: "REVENUE_CONSTANT_PS", change: 0.7 }, { kind: "EPS_CONSTANT_PE", change: 0.688 }, { kind: "ANALYST_TARGET", change: 0.456 }],
    consensus_second: { target_mean: 250, target_upside: 0.11, target_analysts: 33, eps_fy0: 9.25, eps_fy1: 13.5, eps_growth: 0.459, eps_analysts: 15,
      eps_fiscal_end: "Jan 2028", source: "Nasdaq.com analyst estimates", source_url: "https://www.nasdaq.com/market-activity/stocks/s1/analyst-research", asof: "2026-09-26" } },
  4: { orders: { kind: "BACKLOG", amount: 17507e9, currency: "KRW", as_of: "2026-06-30", yoy: 0.63, scope: "重工業部門（連結）",
    source: "효성중공업 26.2분기 p.9", source_url: "https://www.hyosungheavyindustries.com/download/5816",
    intake_quarter: { amount: 3324.2e9, yoy: 0.51 }, guidance: { kind: "ANNUAL_NEW_ORDERS", year: 2026, amount: 12e12, previous: 8.4e12 } },
    consensus: null, scenarios: [] },
  5: { orders: { kind: "NOT_DISCLOSED", reason: "SK海力士未揭露在手訂單" }, consensus: null, scenarios: [] },
};

export function doc(generatedMs: number, overrides: Record<string, unknown> = {}) {
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
      history_start: index === 2 ? "2025-02-13" : "2023-09-26", currency: "USD",
      ...(index === 0 ? { cross_check: { source_id: "nasdaq-stockholm-main", source_url: "https://api.nasdaq.com/api/nordic/screener/shares",
        price: 32.78, asof: "2026-09-25", currency: "SEK", diff: 0.0012 } } : {}) },
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
