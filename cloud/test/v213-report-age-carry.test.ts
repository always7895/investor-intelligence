// Seal liveness vs report age, the admission disclosure and hourly re-seals (T4, 2026-09-26). Synthetic values only.
// One report may be re-sealed hourly byte for byte: the seal keeps V21_TOP20_MAX_AGE_SECONDS, the report and its
// row times stay inside report_max_age_hours (config/v213-top20-report-freshness-v1.json) and are never re-stamped.
import { afterEach, describe, expect, it, vi } from "vitest";
import { parseQuery } from "../src/core";
import { v213Top20LineAnswer } from "../src/v213/top20-presentation";
import { parseV213Top20Report, v213ReportMaxAgeSeconds, V213_NO_CURRENT_ORDERS, V213_NO_FUTURE_ORDER_ESTIMATE } from "../src/v213/top20-report";
import { asKv, MemoryKv } from "./fake-kv";
import { sealUnboundReport } from "./sealed-report-migration";

const HOUR = 3600_000;
const iso = (ms: number) => new Date(ms).toISOString();

function limitedReport(generatedMs: number, overrides: Record<number, Record<string, unknown>> = {}) {
  const generated = iso(generatedMs);
  return {
    schema_version: 2, product_version: "2.1.3", generated_at: generated,
    freshness_policy: { policy_id: "v213-serenity-fresh-independent-evidence-v2", policy_sha256: "27ce461fae50218bb14e4d50ff283f6ed75b201e4a38d656643a5ed65d59c8d8" },
    evidence_capture_at: generated,
    display_columns: ["股票", "長期投資報酬率（近2年年化）", "短期投資報酬率（近6個月）", "行業別", "獲利簡述", "公司現在訂單", "未來訂單預估"],
    long_term_definition: "trailing_2y_adjusted_close_cagr", short_term_definition: "trailing_6m_adjusted_close_price_return",
    records: Array.from({ length: 20 }, (_, index) => ({
      schema_version: 2, rank: index + 1, ticker: `T${String(index).padStart(2, "0")}`, name: `Synthetic ${index}`,
      long_term_return_pct: 40 - index, short_term_return_pct: 10 - index / 2, industry: "合成產業：合成業務描述",
      profit_summary: "獲利；營收年增 +20.0%；淨利率 12.0%", current_orders: V213_NO_CURRENT_ORDERS,
      future_orders_estimate: V213_NO_FUTURE_ORDER_ESTIMATE, long_term_window: "2y_cagr", short_term_window: "6m_price_return",
      market_source: "yfinance", profit_source: "sec_edgar", orders_as_of: "", orders_confidence: "UNAVAILABLE",
      current_order_source_urls: [], future_order_source_urls: [], numeric_total_order_estimate_prohibited: true,
      retrieved_at: generated, orders_state_as_of: iso(generatedMs - 20 * 24 * HOUR), evidence_class: "current_state_claim",
      freshness_policy_key: "current_state_claim_max_age_days", test_only_admission: false,
      provider_scope: "public_only", owner_watchlist_inherited: false, ...(overrides[index] ?? {}),
    })),
    provider_scope: "public_only", owner_watchlist_inherited: false,
  };
}

async function sealedEnv(kv: MemoryKv, body: string, stampMs: number, runId: string) {
  kv.values.set("v213:top20-report:latest", body);
  kv.values.set("last_successful_pipeline_timestamp", iso(stampMs));
  await sealUnboundReport(kv, runId);
  return { PUBLIC_CACHE: asKv(kv), TENANT_PRIVATE_CACHE: asKv(new MemoryKv()), EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()),
    V21_TOP20_MAX_AGE_SECONDS: "7200", V213_FIELD_LOCALE: "bilingual" };
}

const RUN_A = "20260926T010000Z-aaaaaaaaaaaa";
const RUN_B = "20260926T020000Z-bbbbbbbbbbbb";
const RUN_C = "20260926T030000Z-cccccccccccc";

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

describe("report age is separate from seal liveness", () => {
  it("serves a 13 h old report under a fresh seal, with the research-candidate disclosure on every card", async () => {
    expect(v213ReportMaxAgeSeconds()).toBe(14 * 3600);
    const now = Date.now();
    const env = await sealedEnv(new MemoryKv(), JSON.stringify(limitedReport(now - 13 * HOUR)), now - 5 * 60_000, RUN_A);
    const cards = await v213Top20LineAnswer(env as never, parseQuery("Top20"));
    expect(Array.isArray(cards)).toBe(true);
    const messages = cards as any[];
    expect(messages).toHaveLength(4);
    for (const bubble of messages.flatMap(m => m.contents.contents)) {
      const footer = JSON.stringify(bubble.footer);
      expect(footer).toContain("LIMITED_RESEARCH_CANDIDATE");
      expect(footer).toContain("資料擷取");
      expect(footer).not.toContain("TEST-ONLY");
    }
    const text = await v213Top20LineAnswer(env as never, parseQuery("Top20 文字"));
    expect((text as any[])[0].text).toContain("研究候選 LIMITED_RESEARCH_CANDIDATE");
  });

  it("refuses a report past the report bound, and any report under a stale seal", async () => {
    const now = Date.now();
    const old = await sealedEnv(new MemoryKv(), JSON.stringify(limitedReport(now - 15 * HOUR)), now - 5 * 60_000, RUN_A);
    expect(await v213Top20LineAnswer(old as never, parseQuery("Top20"))).toContain("已過期");
    const staleSeal = await sealedEnv(new MemoryKv(), JSON.stringify(limitedReport(now - 4 * HOUR)), now - 3 * HOUR, RUN_A);
    expect(await v213Top20LineAnswer(staleSeal as never, parseQuery("Top20"))).toContain("已過期");
  });

  it("refuses rows acquired outside their evidence window even inside the report bound", async () => {
    const now = Date.now();
    const report = limitedReport(now - HOUR, { 4: { evidence_class: "market_observation", freshness_policy_key: "market_observation_max_age_days",
      orders_state_as_of: iso(now - 2 * 24 * HOUR), retrieved_at: iso(now - 8 * 24 * HOUR) } });
    const env = await sealedEnv(new MemoryKv(), JSON.stringify(report), now - 5 * 60_000, RUN_A);
    expect(await v213Top20LineAnswer(env as never, parseQuery("Top20"))).not.toBeInstanceOf(Array);
  });

  it("requires one admission value across all records", () => {
    const now = Date.now();
    expect(parseV213Top20Report(limitedReport(now))).not.toBeNull();
    expect(parseV213Top20Report(limitedReport(now, { 7: { test_only_admission: true } }))).toBeNull();
    expect(parseV213Top20Report(limitedReport(now, { 7: { test_only_admission: "false" } }))).toBeNull();
  });
});

describe("cards survive hourly re-seals of the same report bytes", () => {
  it("opens a previous run's card when that run is sealed with the same report SHA, and refuses changed bytes", async () => {
    const now = Date.now();
    const kv = new MemoryKv();
    const body = JSON.stringify(limitedReport(now - 2 * HOUR));
    let env = await sealedEnv(kv, body, now - 70 * 60_000, RUN_A);
    const cards = await v213Top20LineAnswer(env as never, parseQuery("Top20")) as any[];
    const command = cards[0].contents.contents[0].footer.contents.find((item: any) => item.type === "button").action.text as string;
    expect(command).toContain(`s:${RUN_A}`);

    env = await sealedEnv(kv, body, now - 10 * 60_000, RUN_B);  // hourly re-seal, identical bytes
    const detail = await v213Top20LineAnswer(env as never, parseQuery(command));
    expect(typeof detail === "string" ? detail : "").not.toContain("內容不符");
    expect(Array.isArray(detail)).toBe(true);

    const forged = command.replace(`s:${RUN_A}`, "s:20260926T000000Z-ffffffffffff");  // never sealed
    expect(await v213Top20LineAnswer(env as never, parseQuery(forged))).toContain("內容不符");

    const changed = limitedReport(now - 2 * HOUR, { 0: { industry: "合成異動內容" } });
    env = await sealedEnv(kv, JSON.stringify(changed), now - 5 * 60_000, RUN_C);  // different bytes
    expect(await v213Top20LineAnswer(env as never, parseQuery(command))).toContain("內容不符");
  });
});
