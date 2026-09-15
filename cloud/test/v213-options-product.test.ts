import { describe, expect, it } from "vitest";
import { assertLineMessages } from "../src/line-messages";
import type { OptionContractQuote } from "../src/v213/market-product-schema";
import { validateOptionContractQuote } from "../src/v213/market-product-schema";
import {
  buildOptionContractFlex,
  buildOptionContractText,
  optionsUnavailableReport,
} from "../src/v213/options-product";

const validQuote: OptionContractQuote = {
  ticker: "NVDA",
  expiry: "2026-09-25",
  dte: 11,
  strike: 125.0,
  type: "call",
  bid: 4.20,
  mid: 4.35,
  ask: 4.50,
  spread: 0.30,
  delta: 0.52,
  iv: 0.45,
  oi: 2500,
  volume: 480,
  breakeven: null,
  maxprofit: null,
  maxloss: null,
  annualized_yield: null,
  assignment_risk: "買方持有權利，無被動指派風險",
  liquidity_warning: "雙邊價差合理，流動性良好",
  timestamp: "2026-09-14T12:00:00Z",
  quote_basis: "delayed",
  source: "yfinance_public",
  provenance: "OP_TEST_SUITE",
  currency: "USD",
  multiplier: 100,
  rights_status: "reviewed_public_access",
  admission_status: "ADMITTED",
};

describe("Options Product Contract and Validation", () => {
  it("validates a compliant option quote contract", () => {
    const validated = validateOptionContractQuote(validQuote, { evaluatedAt: "2026-09-14T12:00:00Z" });
    expect(validated.ticker).toBe("NVDA");
    expect(validated.bid).toBe(4.20);
    expect(validated.ask).toBe(4.50);
    expect(validated.mid).toBe(4.35);
    expect(validated.maxprofit).toBeNull();
    expect(validated.breakeven).toBeNull();
    expect(validated.currency).toBe("USD");
    expect(validated.multiplier).toBe(100);
  });

  it("rejects caller-supplied payoff metrics on bare quotes", () => {
    expect(() => validateOptionContractQuote({ ...validQuote, maxprofit: "UNBOUNDED" as any })).toThrow("BARE_QUOTE_STRATEGY_METRICS_PROHIBITED");
    expect(() => validateOptionContractQuote({ ...validQuote, breakeven: 129.35 as any })).toThrow("BARE_QUOTE_STRATEGY_METRICS_PROHIBITED");
    expect(() => validateOptionContractQuote({ ...validQuote, maxloss: 4.35 as any })).toThrow("BARE_QUOTE_STRATEGY_METRICS_PROHIBITED");
    expect(() => validateOptionContractQuote({ ...validQuote, annualized_yield: 12.0 as any })).toThrow("BARE_QUOTE_STRATEGY_METRICS_PROHIBITED");
  });

  it("rejects non-numeric string types without numeric coercion", () => {
    const stringStrike = { ...validQuote, strike: "125.0" as any };
    expect(() => validateOptionContractQuote(stringStrike)).toThrow("STRICT_FINITE_NUMBER_REQUIRED");

    const nullBid = { ...validQuote, bid: null as any };
    expect(() => validateOptionContractQuote(nullBid)).toThrow("STRICT_FINITE_NUMBER_REQUIRED");
  });

  it("rejects crossed market quotes where bid exceeds ask", () => {
    const crossed = { ...validQuote, bid: 5.00, ask: 4.00, mid: 4.50 };
    expect(() => validateOptionContractQuote(crossed)).toThrow("CROSSED_MARKET_QUOTE_BID_EXCEEDS_ASK");
  });

  it("rejects negative bid or ask", () => {
    const negativeBid = { ...validQuote, bid: -1.00, ask: 2.00, mid: 0.50 };
    expect(() => validateOptionContractQuote(negativeBid)).toThrow("INVALID_BID");
  });

  it("rejects mid quote that deviates from bid/ask average", () => {
    const badMid = { ...validQuote, mid: 99.00 };
    expect(() => validateOptionContractQuote(badMid)).toThrow("INVALID_MID_QUOTE_MUST_MATCH_BID_ASK_AVERAGE");
  });

  it("retains missing Greeks and volume as null without zero coercion", () => {
    const missingGreeks = {
      ...validQuote,
      delta: null,
      iv: null,
      oi: null,
      volume: null,
    };
    const validated = validateOptionContractQuote(missingGreeks, { evaluatedAt: "2026-09-14T12:00:00Z" });
    expect(validated.delta).toBeNull();
    expect(validated.iv).toBeNull();
    expect(validated.oi).toBeNull();
    expect(validated.volume).toBeNull();

    const flex = buildOptionContractFlex(validated, { evaluatedAt: "2026-09-14T12:00:00Z" });
    assertLineMessages(flex);
    const bodyStr = JSON.stringify(flex);
    expect(bodyStr).toContain("Delta: UNAVAILABLE");
    expect(bodyStr).toContain("OI: UNAVAILABLE");
  });

  it("rejects future timestamps beyond allowable tolerance", () => {
    const futureTime = new Date(Date.now() + 600_000).toISOString();
    const futureQuote = { ...validQuote, timestamp: futureTime };
    expect(() => validateOptionContractQuote(futureQuote)).toThrow("FUTURE_TIMESTAMP_REJECTED");
  });

  it("rejects stale timestamps older than allowable policy", () => {
    const staleQuote = { ...validQuote, timestamp: "2020-01-01T00:00:00Z" };
    expect(() => validateOptionContractQuote(staleQuote, { evaluatedAt: "2026-09-14T12:00:00Z" })).toThrow("STALE_TIMESTAMP_REJECTED");
  });

  it("enforces calendar consistency between expiry date and DTE", () => {
    const badDte = { ...validQuote, dte: 999 };
    expect(() => validateOptionContractQuote(badDte, { evaluatedAt: "2026-09-14T12:00:00Z" })).toThrow("EXPIRY_DTE_INCONSISTENT");
  });

  it("renders valid Flex and text contracts with payoff unavailable on bare quotes", () => {
    const flex = buildOptionContractFlex(validQuote, { evaluatedAt: "2026-09-14T12:00:00Z" });
    assertLineMessages(flex);
    const flexStr = JSON.stringify(flex);
    expect(flexStr).toContain("NVDA 2026-09-25 125CALL");
    expect(flexStr).toContain("UNAVAILABLE（無定義策略）");
    expect(flexStr).toContain("Bid $4.20");

    const text = buildOptionContractText(validQuote, { evaluatedAt: "2026-09-14T12:00:00Z" });
    assertLineMessages(text);
    const textStr = JSON.stringify(text);
    expect(textStr).toContain("【公開期權合約報價】NVDA");
    expect(textStr).toContain("最大利潤：UNAVAILABLE（無定義策略）");
  });

  it("renders explicit unavailable report when no admitted quotes exist with period selector navigation", () => {
    const flex = optionsUnavailableReport("AAPL", "weekly", "封存快照不含期權物件");
    assertLineMessages(flex);
    const flexStr = JSON.stringify(flex);
    expect(flexStr).toContain("OPTION_DATA_UNAVAILABLE");
    expect(flexStr).toContain("AAPL 每週期權");
    expect(flexStr).toContain("AAPL 每月期權");
    expect(flexStr).toContain("期權教學");

    const text = optionsUnavailableReport("AAPL", "monthly", "封存快照不含期權物件", true);
    assertLineMessages(text);
    const textStr = JSON.stringify(text);
    expect(textStr).toContain("OPTION_DATA_UNAVAILABLE");
    expect(textStr).toContain("AAPL 每月期權");
    expect(textStr).toContain("AAPL 每週期權");
    expect(textStr).toContain("快捷指令：");
  });
});
