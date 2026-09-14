import { afterEach, describe, expect, it, vi } from "vitest";
import { assertLineMessages } from "../src/line-messages";
import { parseQuery } from "../src/core";
import { v213PublicLineAnswer } from "../src/v213/rich-menu";
import {
  parseV213Top20Report,
  V213_NO_CURRENT_ORDERS,
  V213_NO_FUTURE_ORDER_ESTIMATE,
  V213_TOP20_DISPLAY_COLUMNS,
} from "../src/v213/top20-report";
import {
  validateTwoYearReturnCandidate,
  validateTwoYearReturnEvidence,
  getTwoYearTotalReturnDisplay,
  type TwoYearReturnEvidence,
} from "../src/v213/top20-return-evidence";
import { asKv, MemoryKv } from "./fake-kv";

function makeCandidateReturnEvidence(ticker: string, overrides: Partial<TwoYearReturnEvidence> = {}): TwoYearReturnEvidence {
  return {
    ticker,
    window: "two_year",
    actual_start: "2024-09-09",
    actual_end: "2026-09-09",
    start_adjusted_close: 80.0,
    end_adjusted_close: 120.0,
    elapsed_days: 730,
    total_return_pct: 50.0,
    market_source: "yfinance",
    basis: "adjusted_close",
    dividend_split_semantics: "auto_adjusted",
    currency: "USD",
    ...overrides,
  };
}

function fixtureWithCandidateEvidence() {
  const publicKv = new MemoryKv();
  const stamp = new Date().toISOString();
  const today = stamp.slice(0, 10);
  const twoYearsAgo = new Date(Date.parse(today) - 730 * 86400000).toISOString().slice(0, 10);

  const report = {
    schema_version: 2,
    product_version: "2.1.3",
    generated_at: stamp,
    display_columns: V213_TOP20_DISPLAY_COLUMNS,
    long_term_definition: "trailing_2y_adjusted_close_cagr",
    short_term_definition: "trailing_6m_adjusted_close_price_return",
    provider_scope: "public_only",
    owner_watchlist_inherited: false,
    records: Array.from({ length: 20 }, (_, i) => {
      const ticker = i === 0 ? "ACGL" : `T${i.toString().padStart(2, "0")}`;
      const rec: any = {
        schema_version: 2,
        rank: i + 1,
        ticker,
        name: i === 0 ? "Arch Capital Group Ltd." : `Synthetic Co ${i}`,
        industry: i === 0 ? "保險" : "半導體材料",
        profit_summary: "獲利；營收年增 +12.0%，營業利益率 15.0%",
        current_orders: V213_NO_CURRENT_ORDERS,
        future_orders_estimate: V213_NO_FUTURE_ORDER_ESTIMATE,
        long_term_return_pct: 18.0,
        short_term_return_pct: 5.0,
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
      };
      if (i === 0) {
        rec.two_year_total_return_pct = 50.0;
        rec.two_year_return_evidence = makeCandidateReturnEvidence("ACGL", {
          actual_start: twoYearsAgo,
          actual_end: today,
          elapsed_days: 730,
        });
      }
      return rec;
    }),
  };

  publicKv.values.set("v213:top20-report:latest", JSON.stringify(report));
  publicKv.values.set("last_successful_pipeline_timestamp", report.generated_at);

  class NoPrivateKv extends MemoryKv {
    override async get<T = string>(): Promise<T | null> {
      throw new Error("PRIVATE_READ_FORBIDDEN");
    }
  }

  return {
    publicKv,
    report,
    stamp,
    env: {
      PUBLIC_CACHE: asKv(publicKv),
      TENANT_PRIVATE_CACHE: asKv(new NoPrivateKv()),
      EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()),
      LINE_CHANNEL_SECRET: "ACCEPTANCE_TEST_SECRET",
      LINE_CHANNEL_ACCESS_TOKEN: "ACCEPTANCE_TEST_TOKEN",
      CURRENT_PUBLIC_DATA_ENABLED: "true",
    },
  };
}

afterEach(() => vi.unstubAllGlobals());

describe("TOP20 Source Authority & Return Admission Boundary (Review 2 Acceptance)", () => {
  it("withholds numeric 2Y total through actual v213PublicLineAnswer card AND deep callers even with well-formed candidate evidence", async () => {
    const f = fixtureWithCandidateEvidence();

    // 1. Check LINE card answer
    const answer = await v213PublicLineAnswer(f.env, parseQuery("Top20"));
    expect(Array.isArray(answer)).toBe(true);
    const messages = answer as any[];
    assertLineMessages(messages);

    const firstBubble = messages[0].contents.contents[0];
    const bodyStr = JSON.stringify(firstBubble.body);

    // Card contains 2Y total return label and explicit UNAVAILABLE
    expect(bodyStr).toContain("2Y 總報酬");
    // MUST NOT show numeric +50.0% or 50.0% for 2Y total return
    expect(bodyStr).not.toContain("+50.0%");
    expect(bodyStr).not.toContain("50.0%");
    // Must display UNAVAILABLE for 2Y total return
    expect(bodyStr).toContain("UNAVAILABLE");

    // Legacy returns (2Y CAGR and 6M) remain unchanged
    expect(bodyStr).toContain("+18.0%");
    expect(bodyStr).toContain("+5.0%");

    // Card has exactly one action button routing to deep analysis
    const buttons = firstBubble.footer.contents.filter((c: any) => c.type === "button");
    expect(buttons).toHaveLength(1);
    const deepActionText = buttons[0].action.text;
    expect(deepActionText).toMatch(/^Top20\s+深度化分析\s+ACGL\s+/);

    // 2. Route button directly through v213PublicLineAnswer
    const deepResult = await v213PublicLineAnswer(f.env, parseQuery(deepActionText));
    expect(Array.isArray(deepResult)).toBe(true);
    const deepMessages = deepResult as any[];
    assertLineMessages(deepMessages);
    expect(deepMessages.length).toBeGreaterThanOrEqual(1);
    expect(deepMessages.length).toBeLessThanOrEqual(5);

    const fullDeepText = deepMessages.map(m => m.text).join("\n\n");

    // Deep flow section 10 must withhold numeric 2Y total return and display UNAVAILABLE
    expect(fullDeepText).toContain("兩年總報酬還原端點：UNAVAILABLE");
    expect(fullDeepText).not.toContain("+50.0%（起日");
    expect(fullDeepText).not.toContain("50.0%");

    // Legacy CAGR and 6M remain present in deep analysis section 10
    expect(fullDeepText).toContain("近兩年年化 +18.0%");
    expect(fullDeepText).toContain("近六個月 +5.0%");
  });

  it("distinguishes candidate arithmetic validation from admission capability", () => {
    const candidate = makeCandidateReturnEvidence("NVDA");
    // Candidate pure math validator returns valid arithmetic
    const mathResult = validateTwoYearReturnCandidate(candidate, "NVDA", "2026-09-10T00:00:00Z");
    expect(mathResult.valid).toBe(true);
    expect(mathResult.candidateTotalReturnPct).toBe(50.0);
    // But does not grant authoritative admission
    expect((mathResult as any).admitted).toBe(false);

    // Actual presentation helper unconditionally returns UNAVAILABLE
    const display = getTwoYearTotalReturnDisplay({
      ticker: "NVDA",
      retrieved_at: "2026-09-10T00:00:00Z",
      two_year_total_return_pct: 50.0,
      two_year_return_evidence: candidate,
    });
    expect(display).toBe("UNAVAILABLE");
  });

  it("plain matching digest, health, or status fields do not promote candidate to admitted", () => {
    // Injecting fake authority fields into candidate evidence
    const pseudoAuthoritative = makeCandidateReturnEvidence("NVDA", {
      ...({
        admission_status: "VERIFIED",
        source_digest: "a".repeat(64),
        hash_match: true,
        admit: true,
      } as any),
    });

    // Extra unknown fields cause candidate validation to fail closed
    const res = validateTwoYearReturnCandidate(pseudoAuthoritative, "NVDA");
    expect(res.valid).toBe(false);
    expect(res.display).toBe("UNAVAILABLE");
  });

  it("rejects unknown/new fields and malformed inputs with bounded UNAVAILABLE without leaking errors", () => {
    const f = fixtureWithCandidateEvidence();
    const badReport = JSON.parse(JSON.stringify(f.report));
    badReport.records[0].unknown_injected_field = "exploit";
    expect(parseV213Top20Report(badReport)).toBeNull();

    // Scalar without envelope
    const scalarOnly = JSON.parse(JSON.stringify(f.report));
    delete scalarOnly.records[0].two_year_return_evidence;
    scalarOnly.records[0].two_year_total_return_pct = 50.0;
    expect(parseV213Top20Report(scalarOnly)).toBeNull();
  });

  it("routes button strictly with pinned snapshot reference; no view/pointer race or fallback", async () => {
    const f = fixtureWithCandidateEvidence();
    const answer = await v213PublicLineAnswer(f.env, parseQuery("Top20"));
    const button = (answer as any)[0].contents.contents[0].footer.contents.find((c: any) => c.type === "button");
    const cmd = button.action.text;

    // Mutate snapshot reference
    const tamperedCmd = cmd.replace(/s:[A-Za-z0-9._-]+|legacy/, "s:forged_snapshot_run");
    const tamperedRes = await v213PublicLineAnswer(f.env, parseQuery(tamperedCmd));
    expect(typeof tamperedRes).toBe("string");
    expect(tamperedRes).toContain("內容不符");

    // Non-existent ticker in snapshot
    const wrongTickerCmd = cmd.replace("ACGL", "NONEXISTENT");
    const wrongTickerRes = await v213PublicLineAnswer(f.env, parseQuery(wrongTickerCmd));
    expect(typeof wrongTickerRes).toBe("string");
    expect(wrongTickerRes).toContain("不在本輪 Top20 快照");
  });
});
