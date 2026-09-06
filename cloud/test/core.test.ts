import { describe, expect, it } from "vitest";
import {
  extractPeriod,
  extractTicker,
  formatOptionsAnswer,
  helpText,
  parseQuery,
  splitLineText,
} from "../src/core";

describe("LINE bot public-only core", () => {
  it("routes named methodology questions to Q&A without replacing original-view commands", () => {
    expect(parseQuery("Serenity 的瓶頸與價值捕捉有何差異？").intent).toBe("general_qa");
    expect(parseQuery("How does Serenity assess bottleneck capture?").intent).toBe("general_qa");
    expect(parseQuery("Serenity 原始觀點").intent).toBe("source_views");
    expect(parseQuery("Aschenbrenner 原始觀點").intent).toBe("source_views");
    expect(parseQuery("Serenity").intent).toBe("source_views");
  });
  it("parses a synthetic weekly BID ASK query", () => {
    const value = parseQuery("ALPHA 每週期權 BID ASK");
    expect(value.intent).toBe("options");
    expect(value.ticker).toBe("ALPHA");
    expect(value.period).toBe("weekly");
  });

  it("parses a synthetic monthly query and tenant memory controls", () => {
    expect(extractTicker("BETA 每月期權")).toBe("BETA");
    expect(extractPeriod("BETA 每月期權")).toBe("monthly");
    expect(parseQuery("記憶狀態").intent).toBe("memory_status");
    expect(parseQuery("刪除我的資料").intent).toBe("delete_data");
    expect(parseQuery("我的持倉").intent).toBe("portfolio");
    const result = parseQuery("查看結果 ABCD2345");
    expect(result.intent).toBe("job_result");
    expect(result.referenceId).toBe("ABCD2345");
  });

  it("parses only explicit or finance-context ticker tokens", () => {
    expect(extractTicker("alpha 每週期權")).toBe("ALPHA");
    expect(extractTicker("$beta 最新消息")).toBe("BETA");
    expect(extractTicker("ticker: 0700.HK")).toBe("0700.HK");
    expect(extractTicker("what is option price")).toBeNull();
    expect(extractTicker("applied opto electronics")).toBeNull();
  });

  it("does not hard-code owner-specific ticker aliases or examples", () => {
    expect(extractTicker("applied opto electronics")).toBeNull();
    expect(helpText()).toContain("ALPHA 每週期權");
    expect(helpText()).toContain("BETA 每月期權");
    expect(helpText()).not.toContain("AAOI");
    expect(helpText()).not.toContain("SIVE");
  });

  it("accepts arbitrary general questions", () => {
    expect(parseQuery("量子糾纏是什麼？").intent).toBe("general_qa");
  });

  it("splits output into no more than five LINE messages", () => {
    const text = Array.from({ length: 100 }, (_, index) => `段落 ${index} ${"x".repeat(100)}`).join("\n\n");
    const chunks = splitLineText(text, 500, 5);
    expect(chunks.length).toBeLessThanOrEqual(5);
    expect(chunks.every((chunk) => chunk.length <= 500)).toBe(true);
  });

  it("formats public call and put BID ASK without position or coverage fields", () => {
    const data = [
      {
        ticker: "ALPHA",
        status: "OK",
        quote_source: "yfinance",
        retrieved_at: "2026-08-23T16:00:00Z",
        provider_scope: "public_only",
        line_public_eligible: true,
        periods: {
          weekly: {
            status: "OK",
            expiration: "2026-08-28",
            actual_dte: 5,
            call_observations: {
              status: "OK",
              recommended_candidates: [
                {
                  option_type: "call",
                  strike: 120,
                  bid: 4.0,
                  ask: 4.2,
                  midpoint: 4.1,
                  spread_pct_of_mid: 4.88,
                  open_interest: 100,
                  volume: 20,
                  implied_volatility_pct: 80.0,
                  delta: null,
                  quote_source: "yfinance",
                  quote_delay_status: "TEST_FIXTURE",
                  retrieved_at: "2026-08-23T16:00:00Z",
                  liquidity_pass: true,
                  sell_limit_observation: {
                    observed_limit_low: 4.05,
                    observed_limit_high: 4.1,
                  },
                  annualized_yield_pct: { bid: 100.0, mid: 102.5, ask: 105.0 },
                },
              ],
            },
            put_observations: {
              status: "NO_ELIGIBLE_LIQUID_QUOTE",
              recommended_candidates: [],
            },
          },
        },
      },
    ];
    const answer = formatOptionsAnswer(data, "ALPHA", "weekly");
    expect(answer).toContain("公開期權 BID / ASK");
    expect(answer).toContain("買權報價｜OK");
    expect(answer).toContain("Bid USD 4.00");
    expect(answer).toContain("Ask USD 4.20");
    expect(answer).toContain("2026-08-23T16:00:00.000Z");
    expect(answer).not.toContain("可覆蓋口數");
    expect(answer).not.toContain("持倉摘要");
  });

  it("does not relabel a monthly-only expiration as weekly", () => {
    const answer = formatOptionsAnswer(
      [
        {
          ticker: "BETA",
          status: "OK",
          quote_source: "yfinance",
          retrieved_at: "2026-08-23T16:00:00Z",
          provider_scope: "public_only",
          line_public_eligible: true,
          periods: {
            weekly: {
              status: "NO_EXPIRATION_IN_WINDOW",
              target_dte: 7,
            },
            monthly: {
              status: "OK",
              expiration: "2026-09-18",
              actual_dte: 26,
              call_observations: { status: "NO_ELIGIBLE_LIQUID_QUOTE", recommended_candidates: [] },
              put_observations: { status: "NO_ELIGIBLE_LIQUID_QUOTE", recommended_candidates: [] },
            },
          },
        },
      ],
      "BETA",
      null,
    );
    expect(answer).toContain("每週｜NO_EXPIRATION_IN_WINDOW");
    expect(answer).toContain("每月｜OK｜到期 2026-09-18");
  });
});
