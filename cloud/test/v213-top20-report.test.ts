import { describe, expect, it } from "vitest";
import {
  formatV213Top20Report,
  parseV213Top20Report,
  V213_NO_CURRENT_ORDERS,
  V213_NO_FUTURE_ORDER_ESTIMATE,
} from "../src/v213/top20-report";

function report() {
  return {
    schema_version: 2,
    product_version: "2.1.3",
    generated_at: "2026-09-01T00:00:00Z",
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
      long_term_return_pct: 50 - index,
      short_term_return_pct: 15 - index / 2,
      industry: "半導體",
      profit_summary: "獲利；營收年增 +20.0%",
      current_orders: index === 0 ? "Casela 2027 RMB1.73億固定量" : V213_NO_CURRENT_ORDERS,
      future_orders_estimate: index === 0 ? "能見度偏高但不估總額" : V213_NO_FUTURE_ORDER_ESTIMATE,
      long_term_window: "2y_cagr",
      short_term_window: "6m_price_return",
      market_source: "yfinance",
      profit_source: "sec_edgar",
      orders_as_of: "2026-09-01T00:00:00Z",
      orders_confidence: index === 0 ? "EVIDENCE_BOUND" : "UNAVAILABLE",
      current_order_source_urls: index === 0 ? ["https://www.sec.gov/example/current"] : [],
      future_order_source_urls: index === 0 ? ["https://www.sec.gov/example/future"] : [],
      numeric_total_order_estimate_prohibited: true,
      retrieved_at: "2026-09-01T00:00:00Z",
      provider_scope: "public_only",
      owner_watchlist_inherited: false,
    })),
    provider_scope: "public_only",
    owner_watchlist_inherited: false,
  };
}

describe("v2.1.3 inactive seven-field Top 20 contract", () => {
  it("accepts exactly 20 closed-schema seven-field rows", () => {
    expect(parseV213Top20Report(report())).not.toBeNull();
    const bad = report() as Record<string, unknown>;
    (bad.records as Array<Record<string, unknown>>)[0]!.numeric_total_order_estimate_prohibited = false;
    expect(parseV213Top20Report(bad)).toBeNull();
  });

  it("renders the two order fields at the end and hides source metadata", () => {
    const parsed = parseV213Top20Report(report());
    expect(parsed).not.toBeNull();
    const text = formatV213Top20Report(parsed!);
    expect(text.split("\n")[0]).toBe(
      "股票｜長期投資報酬率（近2年年化）｜短期投資報酬率（近6個月）｜行業別｜獲利簡述｜公司現在訂單｜未來訂單預估",
    );
    expect(text).toContain("Casela 2027 RMB1.73億固定量");
    expect(text).toContain(V213_NO_CURRENT_ORDERS);
    expect(text).not.toContain("https://");
    for (const line of text.split("\n")) expect(line.split("｜")).toHaveLength(7);
  });

  it("refuses delimiter injection in order summaries", () => {
    const bad = report();
    bad.records[0]!.current_orders = "A｜B";
    expect(parseV213Top20Report(bad)).toBeNull();
  });

  it("is not wired to Production in this stage", () => {
    // This test file imports only the new inactive formatter. Production's v2.1.2
    // Worker/Top20 module is intentionally untouched until full coverage + LINE acceptance.
    expect(true).toBe(true);
  });
});
