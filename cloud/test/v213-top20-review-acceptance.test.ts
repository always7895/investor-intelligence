import { afterEach, describe, expect, it, vi } from "vitest";
import { assertLineMessages } from "../src/line-messages";
import { processAuthorizedLineEvent } from "../src/v211/worker";
import { freeRelayRequestEnv } from "../src/v213/production-worker";
import { v213PublicLineAnswer } from "../src/v213/rich-menu";
import { parseQuery } from "../src/core";
import {
  parseV213Top20Report,
  V213_NO_CURRENT_ORDERS,
  V213_NO_FUTURE_ORDER_ESTIMATE,
  V213_TOP20_DISPLAY_COLUMNS,
} from "../src/v213/top20-report";
import {
  validateTwoYearReturnEvidence,
  getTwoYearTotalReturnDisplay,
  type TwoYearReturnEvidence,
} from "../src/v213/top20-return-evidence";
import { buildTop20DeepAnalysisMessages } from "../src/v213/deep-analysis";
import { asKv, MemoryKv } from "./fake-kv";

function makeSyntheticReturnEvidence(ticker: string, overrides: Partial<TwoYearReturnEvidence> = {}): TwoYearReturnEvidence {
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
    ...overrides,
  };
}

function fixtureWithNonAICompany() {
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
      const ticker = i === 0 ? "ACGL" : i === 1 ? "BBY" : `T${i.toString().padStart(2, "0")}`;
      const industry = i === 0 ? "保險" : i === 1 ? "零售（週期性）" : "半導體材料";
      const name = i === 0 ? "Arch Capital Group Ltd." : i === 1 ? "Best Buy Co., Inc." : `Synthetic Co ${i}`;
      const rec: any = {
        schema_version: 2,
        rank: i + 1,
        ticker,
        name,
        industry,
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
        rec.two_year_return_evidence = makeSyntheticReturnEvidence("ACGL", {
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
      LINE_CHANNEL_SECRET: "ACCEPTANCE_TEST_NOT_REAL",
      LINE_CHANNEL_ACCESS_TOKEN: "ACCEPTANCE_TEST_NOT_REAL",
      CURRENT_PUBLIC_DATA_ENABLED: "true",
    },
  };
}

afterEach(() => vi.unstubAllGlobals());

describe("TOP20 review acceptance suite (Reviewer RED cases)", () => {
  describe("Finding 1: Return evidence strict calendar, elapsed derive, and freshness checks", () => {
    it("rejects one-day price change masquerading as 730 days", () => {
      // 1-day difference between actual_start and actual_end, but claiming elapsed_days = 730
      const masquerade = makeSyntheticReturnEvidence("NVDA", {
        actual_start: "2026-09-08",
        actual_end: "2026-09-09",
        elapsed_days: 730,
      });
      const result = validateTwoYearReturnEvidence(masquerade, "NVDA", "2026-09-10T00:00:00Z");
      expect(result.valid).toBe(false);
      expect(result.display).toBe("UNAVAILABLE");
    });

    it("rejects impossible calendar dates such as Feb 30 and Apr 31", () => {
      const feb30 = makeSyntheticReturnEvidence("NVDA", {
        actual_start: "2024-02-30",
        actual_end: "2026-03-01",
        elapsed_days: 730,
      });
      expect(validateTwoYearReturnEvidence(feb30, "NVDA", "2026-09-10T00:00:00Z").valid).toBe(false);

      const apr31 = makeSyntheticReturnEvidence("NVDA", {
        actual_start: "2024-04-31",
        actual_end: "2026-05-01",
        elapsed_days: 730,
      });
      expect(validateTwoYearReturnEvidence(apr31, "NVDA", "2026-09-10T00:00:00Z").valid).toBe(false);

      const feb29NonLeap = makeSyntheticReturnEvidence("NVDA", {
        actual_start: "2023-02-29",
        actual_end: "2025-03-01",
        elapsed_days: 730,
      });
      expect(validateTwoYearReturnEvidence(feb29NonLeap, "NVDA", "2026-09-10T00:00:00Z").valid).toBe(false);
    });

    it("rejects future end dates relative to retrieval clock", () => {
      const futureEnd = makeSyntheticReturnEvidence("NVDA", {
        actual_start: "2024-09-15",
        actual_end: "2026-09-15",
        elapsed_days: 730,
      });
      // Retrieved on 2026-09-10, actual_end is in the future (2026-09-15)
      const res = validateTwoYearReturnEvidence(futureEnd, "NVDA", "2026-09-10T00:00:00Z");
      expect(res.valid).toBe(false);
    });

    it("rejects stale end dates years ago under freshness policy", () => {
      const staleEnd = makeSyntheticReturnEvidence("NVDA", {
        actual_start: "2022-09-09",
        actual_end: "2024-09-09",
        elapsed_days: 731,
      });
      // Retrieved in 2026, but end date is from 2024 (> 7 days stale)
      const res = validateTwoYearReturnEvidence(staleEnd, "NVDA", "2026-09-10T00:00:00Z");
      expect(res.valid).toBe(false);
    });

    it("rejects invalid or malformed retrievedAt clock instead of silently skipping", () => {
      const ev = makeSyntheticReturnEvidence("NVDA");
      expect(validateTwoYearReturnEvidence(ev, "NVDA", "NOT_A_VALID_DATE").valid).toBe(false);
      expect(validateTwoYearReturnEvidence(ev, "NVDA", "2026-99-99T99:99:99Z").valid).toBe(false);
    });

    it("rejects quote/basis/currency/price/key tampering", () => {
      // Wrong basis
      expect(validateTwoYearReturnEvidence(makeSyntheticReturnEvidence("NVDA", { basis: "raw_close" as any }), "NVDA").valid).toBe(false);
      // Wrong semantics
      expect(validateTwoYearReturnEvidence(makeSyntheticReturnEvidence("NVDA", { dividend_split_semantics: "split_only" as any }), "NVDA").valid).toBe(false);
      // Boolean price
      expect(validateTwoYearReturnEvidence(makeSyntheticReturnEvidence("NVDA", { start_adjusted_close: true as any }), "NVDA").valid).toBe(false);
      // Mismatched calculation
      expect(validateTwoYearReturnEvidence(makeSyntheticReturnEvidence("NVDA", { total_return_pct: 99.0 }), "NVDA").valid).toBe(false);
      // Duplicate or tampered extra keys
      const tampered = { ...makeSyntheticReturnEvidence("NVDA"), forged_field: "injected" };
      expect(validateTwoYearReturnEvidence(tampered, "NVDA").valid).toBe(false);
    });

    it("accepts valid zero and negative return cases with exact endpoints", () => {
      const flat = makeSyntheticReturnEvidence("NVDA", {
        start_adjusted_close: 100.0,
        end_adjusted_close: 100.0,
        total_return_pct: 0.0,
      });
      const flatRes = validateTwoYearReturnEvidence(flat, "NVDA", "2026-09-10T00:00:00Z");
      expect(flatRes.valid).toBe(true);
      expect(flatRes.display).toBe("+0.0%");

      const down = makeSyntheticReturnEvidence("NVDA", {
        start_adjusted_close: 100.0,
        end_adjusted_close: 70.0,
        total_return_pct: -30.0,
      });
      const downRes = validateTwoYearReturnEvidence(down, "NVDA", "2026-09-10T00:00:00Z");
      expect(downRes.valid).toBe(true);
      expect(downRes.display).toBe("-30.0%");
    });
  });

  describe("Finding 2: Source authority and scalar+envelope consistency", () => {
    it("rejects scalar return in parseV213Top20Report when envelope is missing or mismatched", () => {
      const f = fixtureWithNonAICompany();
      const reportWithoutEvidence = JSON.parse(JSON.stringify(f.report));
      // Forged scalar with no envelope
      reportWithoutEvidence.records[1].two_year_total_return_pct = 50.0;
      expect(parseV213Top20Report(reportWithoutEvidence)).toBeNull();

      // Mismatched scalar vs envelope
      const reportWithMismatch = JSON.parse(JSON.stringify(f.report));
      reportWithMismatch.records[0].two_year_total_return_pct = 99.0; // envelope has 50.0
      expect(parseV213Top20Report(reportWithMismatch)).toBeNull();
    });

    it("displays UNAVAILABLE when two-year return evidence is missing, and withholds numeric 2Y total when candidate evidence is present", () => {
      const recordWithoutEvidence = {
        ticker: "T01",
        retrieved_at: "2026-09-10T00:00:00Z",
      };
      expect(getTwoYearTotalReturnDisplay(recordWithoutEvidence)).toBe("UNAVAILABLE");

      const recordWithCandidateEvidence = {
        ticker: "NVDA",
        retrieved_at: "2026-09-10T00:00:00Z",
        two_year_total_return_pct: 50.0,
        two_year_return_evidence: makeSyntheticReturnEvidence("NVDA"),
      };
      // Authoritative return admission is withheld in actual presentation
      expect(getTwoYearTotalReturnDisplay(recordWithCandidateEvidence)).toBe("UNAVAILABLE");
    });
  });

  describe("Finding 3: Removing fabricated company claims from deep analysis", () => {
    it("does NOT write generic AI beneficiary thesis for non-AI company ACGL/BBY", () => {
      const f = fixtureWithNonAICompany();
      const report = parseV213Top20Report(f.report)!;
      const messages = buildTop20DeepAnalysisMessages(report, "ACGL");
      const text = messages.map(m => (m as any).text).join("\n\n");

      // Review finding 3: ACGL/BBY/unknown nonAI industry cannot inherit AI beneficiary / named customer / pricing story
      expect(text).not.toContain("市場將其視為整體 AI/伺服器擴張受惠者");
      expect(text).not.toContain("AI 算力建設需求屬於宏觀整體脈絡");

      // Framework items must be labeled 研究待辦 / NOT_A_COMPANY_FINDING, not SUPPORTED/INFERENCE findings
      expect(text).not.toContain("[INFERENCE] 市場將其視為整體 AI/伺服器擴張受惠者");
    });

    it("does NOT falsely claim industry source is SEC EDGAR", () => {
      const f = fixtureWithNonAICompany();
      const report = parseV213Top20Report(f.report)!;
      const messages = buildTop20DeepAnalysisMessages(report, "ACGL");
      const text = messages.map(m => (m as any).text).join("\n\n");

      // Review finding 3: remove '[SUPPORTED] ...來源SEC EDGAR' for industry where actual source may differ
      expect(text).not.toContain("公開上市營運實體（來源：SEC EDGAR）");
      expect(text).not.toMatch(/行業分類.*來源：SEC EDGAR/);
    });
  });

  describe("Finding 4 & 5: Honest ranking, LINE mobile UX limits, and card actions", () => {
    it("preserves honesty on display position vs System Bottleneck Explosion Rank and Score", () => {
      const f = fixtureWithNonAICompany();
      const report = parseV213Top20Report(f.report)!;
      const messages = buildTop20DeepAnalysisMessages(report, "ACGL");
      const text = messages.map(m => (m as any).text).join("\n\n");

      expect(text).toContain("舊版候選展示序位");
      expect(text).toContain("絕非");
      expect(text).toContain("System Bottleneck Explosion Rank");
      expect(text).toContain("System Bottleneck Explosion Score");
      expect(text).toContain("UNAVAILABLE / UNRANKED");
    });

    it("formats card with short return labels (2Y 總報酬, 2Y 年化, 6M 報酬), no duplicate card action, and adheres to LINE limits", async () => {
      const f = fixtureWithNonAICompany();
      const answer = await v213PublicLineAnswer(f.env, parseQuery("Top20"));
      expect(Array.isArray(answer)).toBe(true);
      const messages = answer as any[];
      assertLineMessages(messages);
      expect(messages.length).toBeLessThanOrEqual(5);

      const firstBubble = messages[0].contents.contents[0];
      const bodyStr = JSON.stringify(firstBubble.body);
      // Short readable card return labels
      expect(bodyStr).toContain("2Y 總報酬");
      expect(bodyStr).toContain("2年年化");
      expect(bodyStr).toContain("6個月");
      // Authoritative admission withheld in actual LINE cards
      expect(bodyStr).toContain("UNAVAILABLE");
      expect(bodyStr).not.toContain("+50.0%");

      // No duplicate card action
      const footerStr = JSON.stringify(firstBubble.footer);
      expect(footerStr).not.toContain("本公司七欄文字");
      expect(footerStr).not.toContain("證據詳情");

      // Exactly one primary button for deep analysis
      const buttons = firstBubble.footer.contents.filter((c: any) => c.type === "button");
      expect(buttons).toHaveLength(1);
      expect(buttons[0].action.label).toContain("深度化分析");

      // Emitted button action flows cleanly through publicLineAnswer to pinned snapshot
      const deepActionText = buttons[0].action.text;
      expect(deepActionText).toMatch(/^Top20\s+深度化分析\s+ACGL\s+/);

      const deepResult = await v213PublicLineAnswer(f.env, parseQuery(deepActionText));
      expect(Array.isArray(deepResult)).toBe(true);
      const deepMessages = deepResult as any[];
      assertLineMessages(deepMessages);
      expect(deepMessages.length).toBeGreaterThanOrEqual(1);
      expect(deepMessages.length).toBeLessThanOrEqual(5);
      for (const msg of deepMessages) {
        expect(msg.text.length).toBeLessThanOrEqual(4900);
      }
    });

    it("bounds foreign/unknown ticker cleanly without model or network fallback", async () => {
      const f = fixtureWithNonAICompany();
      const unknownQuery = parseQuery("Top20 深度化分析 UNKNOWN " + f.stamp + " legacy " + "0".repeat(64));
      const res = await v213PublicLineAnswer(f.env, unknownQuery);
      expect(typeof res).toBe("string");
      expect(res).toContain("內容不符");
    });
  });
});
