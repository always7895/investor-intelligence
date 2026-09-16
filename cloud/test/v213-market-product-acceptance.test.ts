import { afterEach, describe, expect, it, vi } from "vitest";
import { assertLineMessages } from "../src/line-messages";
import { processAuthorizedLineEvent } from "../src/v211/worker";
import { freeRelayRequestEnv } from "../src/v213/production-worker";
import {
  V213_TOP20_DISPLAY_COLUMNS,
  V213_NO_CURRENT_ORDERS,
  V213_NO_FUTURE_ORDER_ESTIMATE,
} from "../src/v213/top20-report";
import {
  validateMacroGrowthRate,
  validateOptionContractQuote,
} from "../src/v213/market-product-schema";
import { asKv, MemoryKv } from "./fake-kv";

function acceptanceFixture(overrides: Record<string, string> = {}) {
  const publicKv = new MemoryKv();
  const stamp = new Date().toISOString();
  const report = {
    schema_version: 2,
    product_version: "2.1.3",
    generated_at: stamp,
    display_columns: V213_TOP20_DISPLAY_COLUMNS,
    long_term_definition: "trailing_2y_adjusted_close_cagr",
    short_term_definition: "trailing_6m_adjusted_close_price_return",
    provider_scope: "public_only",
    owner_watchlist_inherited: false,
    records: Array.from({ length: 20 }, (_, i) => ({
      schema_version: 2,
      rank: i + 1,
      ticker: `T${i.toString().padStart(2, "0")}`,
      name: `Synthetic Company ${i}`,
      industry: i < 10 ? "半導體" : "光通訊",
      profit_summary: "合成財務組件",
      current_orders: V213_NO_CURRENT_ORDERS,
      future_orders_estimate: V213_NO_FUTURE_ORDER_ESTIMATE,
      long_term_return_pct: null,
      short_term_return_pct: null,
      long_term_window: "2y_cagr",
      short_term_window: "6m_price_return",
      market_source: "yfinance",
      profit_source: "sec_edgar",
      orders_as_of: stamp,
      orders_confidence: "UNAVAILABLE",
      current_order_source_urls: [],
      future_order_source_urls: [],
      numeric_total_order_estimate_prohibited: true,
      retrieved_at: stamp,
      provider_scope: "public_only",
      owner_watchlist_inherited: false,
    })),
  };
  const save = () => {
    publicKv.values.set("v213:top20-report:latest", JSON.stringify(report));
    publicKv.values.set("last_successful_pipeline_timestamp", report.generated_at);
  };
  save();

  class NoPrivateReads extends MemoryKv {
    override async get<T = string>(): Promise<T | null> {
      throw new Error("PRIVATE_READ_FORBIDDEN");
    }
  }

  return {
    publicKv,
    report,
    save,
    env: {
      PUBLIC_CACHE: asKv(publicKv),
      TENANT_PRIVATE_CACHE: asKv(new NoPrivateReads()),
      EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()),
      LINE_CHANNEL_SECRET: "EXAMPLE_NOT_REAL",
      LINE_CHANNEL_ACCESS_TOKEN: "EXAMPLE_NOT_REAL",
      CURRENT_PUBLIC_DATA_ENABLED: "true",
      ...overrides,
    },
  };
}

async function reply(command: string, f = acceptanceFixture()) {
  let messages: any[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
    expect(url).toBe("https://api.line.me/v2/bot/message/reply");
    messages = JSON.parse(String(init.body)).messages;
    return new Response("{}", { status: 200 });
  }));
  await processAuthorizedLineEvent(
    await freeRelayRequestEnv(f.env as any),
    {
      waitUntil() {
        throw new Error("MODEL_JOB_FORBIDDEN");
      },
    } as unknown as ExecutionContext,
    {
      type: "message",
      replyToken: "SYNTHETIC_REPLY",
      timestamp: Date.now(),
      message: { id: "SYNTHETIC_MESSAGE", type: "text", text: command },
    },
    "SYNTHETIC_TENANT",
  );
  assertLineMessages(messages);
  return messages;
}

afterEach(() => vi.unstubAllGlobals());

describe("Astra Acceptance Review 1 Verification Suite", () => {
  // Finding 1: Entry routing for 宏觀產業分析 and 期權
  describe("Finding 1: Entry commands and routing", () => {
    it("macro entry command 宏觀產業分析 routes to macro overview / shortfall report, NOT shallow company share count as macro analysis", async () => {
      const messages = await reply("宏觀產業分析");
      const body = JSON.stringify(messages);
      // Main macro home must NOT present company share as TOP5 industry analysis
      expect(body).toContain("TOP5");
      expect(body).toContain("MACRO_TOP5_SHORTFALL");
      expect(body).toContain("宏觀數據要求");
    });

    it("options entry command 期權 routes to educational options carousel / overview navigation", async () => {
      const messages = await reply("期權");
      const body = JSON.stringify(messages);
      // Real entry must wire to educational strategy cards or active period/quote navigation
      expect(body).toContain("教學範例，非推薦");
      expect(body).toContain("Covered Call");
      expect(body).toContain("OPTION_DATA_UNAVAILABLE");
    });
  });

  // Finding 2: Education strategy matcher
  describe("Finding 2: Education strategy matcher", () => {
    it("protective_put resolves to Protective Put, NOT Cash-Secured Put", async () => {
      const messages = await reply("期權教學 protective_put");
      const body = JSON.stringify(messages);
      expect(body).toContain("Protective Put");
      expect(body).toContain("UNBOUNDED");
      expect(body).not.toContain("Cash-Secured Put");
    });

    it("handles all 4 canonical educational strategies explicitly", async () => {
      const cc = JSON.stringify(await reply("期權教學 covered_call"));
      expect(cc).toContain("Covered Call");
      expect(cc).toContain("$97.00");

      const csp = JSON.stringify(await reply("期權教學 cash_secured_put"));
      expect(csp).toContain("Cash-Secured Put");
      expect(csp).toContain("$87.50");

      const bcs = JSON.stringify(await reply("期權教學 bull_call_spread"));
      expect(bcs).toContain("Bull Call Spread");
      expect(bcs).toContain("$102.50");

      const pp = JSON.stringify(await reply("期權教學 protective_put"));
      expect(pp).toContain("Protective Put");
      expect(pp).toContain("UNBOUNDED");
    });

    it("rejects unknown strategy ID rather than substring collision or default wrong strategy", async () => {
      const messages = await reply("期權教學 iron_condor");
      const body = JSON.stringify(messages);
      expect(body).toContain("UNKNOWN_STRATEGY");
    });
  });

  // Finding 3: Strict quote validation & no coercion
  describe("Finding 3: Strict quote validation", () => {
    const baseQuote = {
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
      assignment_risk: "買方持有權利",
      liquidity_warning: "流動性良好",
      timestamp: "2026-09-14T12:00:00Z",
      quote_basis: "delayed",
      source: "yfinance_public",
      provenance: "OP_TEST",
      currency: "USD",
      multiplier: 100,
      rights_status: "reviewed_public_access",
    };

    it("rejects non-numeric string types and coercions", () => {
      // String instead of finite number
      expect(() => validateOptionContractQuote({ ...baseQuote, strike: "125.0" as any }, { evaluatedAt: "2026-09-14T12:00:00Z" })).toThrow("STRICT_FINITE_NUMBER_REQUIRED");
      expect(() => validateOptionContractQuote({ ...baseQuote, bid: "" as any }, { evaluatedAt: "2026-09-14T12:00:00Z" })).toThrow("STRICT_FINITE_NUMBER_REQUIRED");
      expect(() => validateOptionContractQuote({ ...baseQuote, dte: null as any }, { evaluatedAt: "2026-09-14T12:00:00Z" })).toThrow("STRICT_FINITE_NUMBER_REQUIRED");
    });

    it("rejects caller-supplied payoff metrics on bare quotes", () => {
      expect(() => validateOptionContractQuote({ ...baseQuote, breakeven: 129.35 as any }, { evaluatedAt: "2026-09-14T12:00:00Z" })).toThrow("BARE_QUOTE_STRATEGY_METRICS_PROHIBITED");
      expect(() => validateOptionContractQuote({ ...baseQuote, maxprofit: "UNBOUNDED" as any }, { evaluatedAt: "2026-09-14T12:00:00Z" })).toThrow("BARE_QUOTE_STRATEGY_METRICS_PROHIBITED");
      expect(() => validateOptionContractQuote({ ...baseQuote, maxloss: 4.35 as any }, { evaluatedAt: "2026-09-14T12:00:00Z" })).toThrow("BARE_QUOTE_STRATEGY_METRICS_PROHIBITED");
      expect(() => validateOptionContractQuote({ ...baseQuote, annualized_yield: 12.5 as any }, { evaluatedAt: "2026-09-14T12:00:00Z" })).toThrow("BARE_QUOTE_STRATEGY_METRICS_PROHIBITED");
    });

    it("rejects stale timestamps older than allowable freshness policy", () => {
      const staleQuote = {
        ...baseQuote,
        timestamp: "2021-01-01T00:00:00Z", // 5+ years stale!
      };
      expect(() => validateOptionContractQuote(staleQuote, { evaluatedAt: "2026-09-14T12:00:00Z" })).toThrow("STALE_TIMESTAMP_REJECTED");
    });

    it("enforces calendar consistency between expiry date and DTE", () => {
      const inconsistentQuote = {
        ...baseQuote,
        dte: 999, // Impossible DTE for 2026-09-25 when evaluated near 2026-09-14
      };
      expect(() => validateOptionContractQuote(inconsistentQuote, { evaluatedAt: "2026-09-14T12:00:00Z" })).toThrow("EXPIRY_DTE_INCONSISTENT");
    });
  });

  // Finding 4: Macro growth schema
  describe("Finding 4: Macro growth schema validation", () => {
    it("rejects malformed date and invalid period formats", () => {
      const badPeriod = {
        rate_pct: 25.0,
        units: "% YoY",
        period: "invalid-period",
        type: "forecast",
        publisher: "WSTS",
        date: "2026-06",
        source_id: "wsts-outlook",
        url: "https://example.com",
      };
      expect(() => validateMacroGrowthRate(badPeriod)).toThrow("INVALID_GROWTH_PERIOD");

      const badDate = {
        rate_pct: 25.0,
        units: "% YoY",
        period: "2026",
        type: "forecast",
        publisher: "WSTS",
        date: "not-a-valid-date",
        source_id: "wsts-outlook",
        url: "https://example.com",
      };
      expect(() => validateMacroGrowthRate(badDate)).toThrow("INVALID_GROWTH_DATE");
    });

    it("requires source URL or verifiable passage binding", () => {
      const noSourceBinding = {
        rate_pct: 25.0,
        units: "% YoY",
        period: "2026",
        type: "forecast",
        publisher: "WSTS",
        date: "2026-06",
        source_id: "wsts-outlook",
      };
      expect(() => validateMacroGrowthRate(noSourceBinding)).toThrow("SOURCE_BINDING_REQUIRED");
    });

    it("requires source_id lineage binding", () => {
      const noSourceId = {
        rate_pct: 25.0,
        units: "% YoY",
        period: "2026",
        type: "forecast",
        publisher: "WSTS",
        date: "2026-06",
        url: "https://example.com",
      };
      expect(() => validateMacroGrowthRate(noSourceId)).toThrow("UNADMITTED_GROWTH_SOURCE");
    });
  });

  // Finding 5: Sealed reader safety & no arbitrary product admission
  describe("Finding 5: Sealed reader safety", () => {
    it("sealed round with unsealed product keys injected in MemoryKv returns UNAVAILABLE", async () => {
      const f = acceptanceFixture();
      // Inject unsealed product keys into KV
      f.publicKv.values.set("v213:macro-industry:latest", JSON.stringify({ title: "FAKE_MACRO" }));
      f.publicKv.values.set("options:NVDA:weekly:latest", JSON.stringify({ ticker: "NVDA" }));

      // Commands must fail-closed UNAVAILABLE, not read unsealed keys
      const macroBody = JSON.stringify(await reply("TOP5產業總覽", f));
      expect(macroBody).toContain("MACRO_TOP5_SHORTFALL");
      expect(macroBody).not.toContain("FAKE_MACRO");

      const optionsBody = JSON.stringify(await reply("NVDA 每週期權", f));
      expect(optionsBody).toContain("OPTION_DATA_UNAVAILABLE");
    });
  });
});
