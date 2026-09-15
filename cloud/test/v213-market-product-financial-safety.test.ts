import { afterEach, describe, expect, it, vi } from "vitest";
import { assertLineMessages } from "../src/line-messages";
import { processAuthorizedLineEvent } from "../src/v211/worker";
import { freeRelayRequestEnv } from "../src/v213/production-worker";
import {
  EDUCATIONAL_STRATEGIES,
  buildEducationalStrategyFlex,
  buildEducationalStrategyText,
} from "../src/v213/educational-options";
import {
  validateMacroGrowthRate,
  validateOptionContractQuote,
  type OptionContractQuote,
} from "../src/v213/market-product-schema";
import {
  buildOptionContractFlex,
  buildOptionContractText,
  optionsUnavailableReport,
} from "../src/v213/options-product";
import { asKv, MemoryKv } from "./fake-kv";

function createValidBareQuote(overrides: Record<string, unknown> = {}): OptionContractQuote {
  return {
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
    provenance: "RECEIPT_PUBLIC_CHAIN_20260914",
    currency: "USD",
    multiplier: 100,
    rights_status: "reviewed_public_access",
    admission_status: "ADMITTED",
    ...overrides,
  } as OptionContractQuote;
}

describe("v213 Market Product Financial Safety Suite", () => {
  // Review Finding A: Prohibit caller-supplied strategy metrics on bare contract quotes
  describe("Review Finding A: Payoff and Strategy Metric Separation", () => {
    it("rejects caller-supplied breakeven on bare option quote", () => {
      const quote = createValidBareQuote({ breakeven: 129.35 });
      expect(() => validateOptionContractQuote(quote)).toThrow("BARE_QUOTE_STRATEGY_METRICS_PROHIBITED");
    });

    it("rejects caller-supplied maxprofit on bare option quote", () => {
      const quote = createValidBareQuote({ maxprofit: "UNBOUNDED" });
      expect(() => validateOptionContractQuote(quote)).toThrow("BARE_QUOTE_STRATEGY_METRICS_PROHIBITED");

      const quoteNumeric = createValidBareQuote({ maxprofit: 500.0 });
      expect(() => validateOptionContractQuote(quoteNumeric)).toThrow("BARE_QUOTE_STRATEGY_METRICS_PROHIBITED");
    });

    it("rejects caller-supplied maxloss on bare option quote", () => {
      const quote = createValidBareQuote({ maxloss: 4.35 });
      expect(() => validateOptionContractQuote(quote)).toThrow("BARE_QUOTE_STRATEGY_METRICS_PROHIBITED");
    });

    it("rejects caller-supplied annualized_yield on bare option quote", () => {
      const quote = createValidBareQuote({ annualized_yield: 18.5 });
      expect(() => validateOptionContractQuote(quote)).toThrow("BARE_QUOTE_STRATEGY_METRICS_PROHIBITED");
    });

    it("normalizes absent/null strategy metrics to explicitly UNAVAILABLE in renderer without leaking raw numbers", () => {
      const bare = createValidBareQuote();
      const validated = validateOptionContractQuote(bare, { evaluatedAt: "2026-09-14T12:00:00Z" });
      expect(validated.breakeven).toBeNull();
      expect(validated.maxprofit).toBeNull();
      expect(validated.maxloss).toBeNull();
      expect(validated.annualized_yield).toBeNull();

      const flex = buildOptionContractFlex(validated, { evaluatedAt: "2026-09-14T12:00:00Z" });
      assertLineMessages(flex);
      const flexBody = JSON.stringify(flex);
      expect(flexBody).toContain("UNAVAILABLE（無定義策略）");
      expect(flexBody).not.toContain("129.35");

      const text = buildOptionContractText(validated, { evaluatedAt: "2026-09-14T12:00:00Z" });
      assertLineMessages(text);
      const textBody = JSON.stringify(text);
      expect(textBody).toContain("UNAVAILABLE（無定義策略）");
    });
  });

  // Review Finding B: Strict Freshness, Strict ISO, Calendar DTE, and Evaluation Clock
  describe("Review Finding B: Quote Freshness, Calendar DTE & Nonexecutable Markers", () => {
    it("rejects non-strict ISO timestamps or timestamps missing UTC offset", () => {
      const missingOffset = createValidBareQuote({ timestamp: "2026-09-14 12:00:00" });
      expect(() => validateOptionContractQuote(missingOffset)).toThrow("INVALID_QUOTE_TIMESTAMP");

      const dateOnly = createValidBareQuote({ timestamp: "2026-09-14" });
      expect(() => validateOptionContractQuote(dateOnly)).toThrow("INVALID_QUOTE_TIMESTAMP");
    });

    it("rejects invalid evaluatedAt clock instead of silently skipping validation checks", () => {
      const bare = createValidBareQuote();
      expect(() => validateOptionContractQuote(bare, { evaluatedAt: "NOT_AN_ISO_DATE" })).toThrow("INVALID_EVALUATION_CLOCK");
    });

    it("rejects expired contracts where expiry date is before evaluation date", () => {
      const expiredQuote = createValidBareQuote({
        expiry: "2026-09-10",
        dte: 0,
      });
      expect(() => validateOptionContractQuote(expiredQuote, { evaluatedAt: "2026-09-14T12:00:00Z" })).toThrow("EXPIRED_CONTRACT_REJECTED");
    });

    it("rejects mismatched DTE derived from old quote timestamp rather than current evaluation clock", () => {
      const quote = createValidBareQuote({
        expiry: "2026-09-25",
        dte: 20, // Claimed DTE 20, but relative to 2026-09-14 it is 11 days
        timestamp: "2026-09-05T12:00:00Z", // Old quote timestamp
      });
      expect(() => validateOptionContractQuote(quote, { evaluatedAt: "2026-09-14T12:00:00Z" })).toThrow("EXPIRY_DTE_INCONSISTENT");
    });

    it("rejects quotes exceeding maximum freshness age", () => {
      // delayed quotes older than allowable limit relative to evaluatedAt
      const oldQuote = createValidBareQuote({
        timestamp: "2026-09-01T12:00:00Z",
        quote_basis: "delayed",
      });
      expect(() => validateOptionContractQuote(oldQuote, { evaluatedAt: "2026-09-14T12:00:00Z" })).toThrow("STALE_TIMESTAMP_REJECTED");
    });

    it("enforces period filter matching weekly (3-14 DTE) vs monthly (21-45 DTE)", () => {
      const weeklyQuoteWithMonthlyDte = createValidBareQuote({
        expiry: "2026-10-16",
        dte: 32,
      });
      expect(() =>
        validateOptionContractQuote(weeklyQuoteWithMonthlyDte, {
          evaluatedAt: "2026-09-14T12:00:00Z",
          period: "weekly",
        }),
      ).toThrow("QUOTE_PERIOD_MISMATCH");

      const monthlyQuoteWithWeeklyDte = createValidBareQuote({
        expiry: "2026-09-21",
        dte: 7,
      });
      expect(() =>
        validateOptionContractQuote(monthlyQuoteWithWeeklyDte, {
          evaluatedAt: "2026-09-14T12:00:00Z",
          period: "monthly",
        }),
      ).toThrow("QUOTE_PERIOD_MISMATCH");
    });

    it("enforces ticker subject match when queried for a specific ticker", () => {
      const quote = createValidBareQuote({ ticker: "AAPL" });
      expect(() =>
        validateOptionContractQuote(quote, {
          evaluatedAt: "2026-09-14T12:00:00Z",
          ticker: "NVDA",
        }),
      ).toThrow("QUOTE_TICKER_MISMATCH");
    });

    it("clearly labels delayed and as-of-close quotes as non-executable", () => {
      const delayedQuote = createValidBareQuote({ quote_basis: "delayed" });
      const text = JSON.stringify(buildOptionContractText(delayedQuote, { evaluatedAt: "2026-09-14T12:00:00Z" }));
      expect(text).toContain("非即時可執行報價");

      const asofCloseQuote = createValidBareQuote({ quote_basis: "asof_close" });
      const flex = JSON.stringify(buildOptionContractFlex(asofCloseQuote, { evaluatedAt: "2026-09-14T12:00:00Z" }));
      expect(flex).toContain("非即時可執行報價");
    });
  });

  // Review Finding C: Provenance, Currency, Multiplier & Rights Status
  describe("Review Finding C: Source Provenance, Currency, Multiplier & Rights Status", () => {
    it("rejects empty or whitespace-only source and provenance", () => {
      const emptySource = createValidBareQuote({ source: "   " });
      expect(() => validateOptionContractQuote(emptySource)).toThrow("MISSING_QUOTE_SOURCE");

      const emptyProvenance = createValidBareQuote({ provenance: "" });
      expect(() => validateOptionContractQuote(emptyProvenance)).toThrow("MISSING_QUOTE_PROVENANCE");
    });

    it("enforces explicit currency and multiplier binding", () => {
      const badCurrency = createValidBareQuote({ currency: "EUR" as any });
      expect(() => validateOptionContractQuote(badCurrency)).toThrow("INVALID_CURRENCY");

      const badMultiplier = createValidBareQuote({ multiplier: 50 as any });
      expect(() => validateOptionContractQuote(badMultiplier)).toThrow("INVALID_MULTIPLIER");
    });

    it("validates rights_status and flags unadmitted rights", () => {
      const unreviewed = createValidBareQuote({ rights_status: "review_before_enable" as any });
      const validated = validateOptionContractQuote(unreviewed, { evaluatedAt: "2026-09-14T12:00:00Z" });
      expect(validated.admission_status).toBe("NOT_ADMITTED");

      const invalidRights = createValidBareQuote({ rights_status: "bogus_rights" as any });
      expect(() => validateOptionContractQuote(invalidRights)).toThrow("INVALID_RIGHTS_STATUS");
    });
  });

  // Review Finding D: Macro Growth Lineage and Admission
  describe("Review Finding D: Macro Growth Source Lineage and Builder Rank Safety", () => {
    it("rejects arbitrary text passages without an admitted reference identity", () => {
      const unadmittedGrowth = {
        rate_pct: 35.0,
        units: "% YoY",
        period: "2026",
        type: "forecast",
        publisher: "Random Blogger",
        date: "2026-06",
        raw_passage: "A completely arbitrary passage claiming 35% growth without source_id lineage.",
      };
      expect(() => validateMacroGrowthRate(unadmittedGrowth)).toThrow("UNADMITTED_GROWTH_SOURCE");
    });

    it("rejects future dates on macro growth rates", () => {
      const futureGrowth = {
        rate_pct: 25.0,
        units: "% YoY",
        period: "2026",
        type: "forecast",
        publisher: "WSTS",
        date: "2030-01",
        source_id: "wsts-outlook",
        url: "https://www.wsts.org/76/Recent-News-Release",
      };
      expect(() => validateMacroGrowthRate(futureGrowth, { evaluatedAt: "2026-09-14T00:00:00Z" })).toThrow("FUTURE_GROWTH_DATE_REJECTED");
    });
  });

  // Review Finding E: Educational Strategy Payoff Verification & LINE Limits
  describe("Review Finding E: Educational Cards Payoff Math and LINE Limits", () => {
    it("verifies all 4 educational strategy cards contain explicit mathematical payoff references", () => {
      expect(EDUCATIONAL_STRATEGIES).toHaveLength(4);
      for (const card of EDUCATIONAL_STRATEGIES) {
        expect(card.disclaimer).toBe("教學範例，非推薦");
        expect(card.status).toBe("SYNTHETIC_EDUCATIONAL");
        expect(card.payoff_reference).toBeDefined();
        expect(card.payoff_reference.contract_multiplier).toBe(100);
        expect(card.payoff_reference.underlying_cost_basis).toBeGreaterThan(0);
      }

      // 1. Covered Call
      const cc = EDUCATIONAL_STRATEGIES.find(c => c.strategy_id === "covered_call")!;
      expect(cc.payoff_reference.breakeven_price).toBe(97.0);
      expect(cc.payoff_reference.max_profit_amount).toBe(800.0);
      expect(cc.payoff_reference.max_loss_amount).toBe(9700.0);

      // 2. Cash-Secured Put
      const csp = EDUCATIONAL_STRATEGIES.find(c => c.strategy_id === "cash_secured_put")!;
      expect(csp.payoff_reference.breakeven_price).toBe(87.5);
      expect(csp.payoff_reference.max_profit_amount).toBe(250.0);
      expect(csp.payoff_reference.max_loss_amount).toBe(8750.0);

      // 3. Bull Call Spread
      const bcs = EDUCATIONAL_STRATEGIES.find(c => c.strategy_id === "bull_call_spread")!;
      expect(bcs.payoff_reference.breakeven_price).toBe(102.5);
      expect(bcs.payoff_reference.max_profit_amount).toBe(750.0);
      expect(bcs.payoff_reference.max_loss_amount).toBe(250.0);

      // 4. Protective Put
      const pp = EDUCATIONAL_STRATEGIES.find(c => c.strategy_id === "protective_put")!;
      expect(pp.payoff_reference.breakeven_price).toBe(103.0);
      expect(pp.payoff_reference.max_profit_amount).toBe("UNBOUNDED");
      expect(pp.payoff_reference.max_loss_amount).toBe(800.0);
    });

    it("verifies educational Flex and Text obey assertLineMessages strict limits", () => {
      const flex = buildEducationalStrategyFlex();
      expect(() => assertLineMessages(flex)).not.toThrow();

      const text = buildEducationalStrategyText();
      expect(() => assertLineMessages(text)).not.toThrow();
    });
  });
});
