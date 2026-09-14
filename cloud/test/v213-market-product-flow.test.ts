import { afterEach, describe, expect, it, vi } from "vitest";
import { assertLineMessages } from "../src/line-messages";
import { processAuthorizedLineEvent } from "../src/v211/worker";
import { freeRelayRequestEnv } from "../src/v213/production-worker";
import {
  V213_TOP20_DISPLAY_COLUMNS,
  V213_NO_CURRENT_ORDERS,
  V213_NO_FUTURE_ORDER_ESTIMATE,
} from "../src/v213/top20-report";
import { asKv, MemoryKv } from "./fake-kv";

function fixture(overrides: Record<string, string> = {}) {
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
      industry: i < 10 ? "產業甲" : "產業乙",
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

async function actualReply(command: string, f = fixture()) {
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
  expect(fetch).toHaveBeenCalledTimes(1);
  return messages;
}

afterEach(() => vi.unstubAllGlobals());

describe("End-to-End Market Product Flow (Macro & Options)", () => {
  it("public command TOP5產業總覽 returns shortfall report when unsealed / unqualified", async () => {
    const messages = await actualReply("TOP5產業總覽");
    const body = JSON.stringify(messages);
    expect(body).toContain("准入門檻未達成");
    expect(body).toContain("MACRO_TOP5_SHORTFALL");
    expect(body).toContain("宏觀資料說明");
  });

  it("public command TOP5產業總覽 文字 returns text shortfall report", async () => {
    const messages = await actualReply("TOP5產業總覽 文字");
    expect(messages.every(m => m.type === "text")).toBe(true);
    const body = JSON.stringify(messages);
    expect(body).toContain("TOP5產業總覽 · 准入門檻未達成");
    expect(body).toContain("MACRO_TOP5_SHORTFALL");
  });

  it("educational options commands return 4 strategy cards without network/model reads", async () => {
    const messages = await actualReply("期權教學");
    assertLineMessages(messages);
    const body = JSON.stringify(messages);
    expect(body).toContain("教學範例，非推薦");
    expect(body).toContain("Covered Call");
    expect(body).toContain("Cash-Secured Put");
    expect(body).toContain("Bull Call Spread");
    expect(body).toContain("Protective Put");
    expect(body).toContain("UNBOUNDED（理論無限）");
  });

  it("educational options in text mode returns text cards within 5 messages", async () => {
    const f = fixture({ V213_LINE_PRESENTATION: "text" });
    const messages = await actualReply("期權教學", f);
    expect(messages.every(m => m.type === "text")).toBe(true);
    expect(messages.length).toBeLessThanOrEqual(5);
    const body = JSON.stringify(messages);
    expect(body).toContain("教學範例，非推薦");
    expect(body).toContain("UNBOUNDED（理論無限）");
  });

  it("educational options single strategy command returns focused card", async () => {
    const messages = await actualReply("期權教學 cash_secured_put");
    const body = JSON.stringify(messages);
    expect(body).toContain("Cash-Secured Put");
    expect(body).toContain("$87.50");
    expect(body).toContain("$9,000.00");
  });

  it("functional query for ticker weekly/monthly options returns fail-closed UNAVAILABLE", async () => {
    const weeklyMessages = await actualReply("NVDA 每週期權");
    const weeklyBody = JSON.stringify(weeklyMessages);
    expect(weeklyBody).toContain("OPTION_DATA_UNAVAILABLE");
    expect(weeklyBody).toContain("NVDA 每週期權");
    expect(weeklyBody).toContain("期權教學");

    const monthlyMessages = await actualReply("AAPL 每月期權");
    const monthlyBody = JSON.stringify(monthlyMessages);
    expect(monthlyBody).toContain("OPTION_DATA_UNAVAILABLE");
    expect(monthlyBody).toContain("AAPL 每月期權");
  });

  it("unsealed macro card query reports explicit unavailable", async () => {
    const messages = await actualReply("宏觀產業 卡片 ind_hbm");
    const body = JSON.stringify(messages);
    expect(body).toContain("MACRO_CARD_UNAVAILABLE");
    expect(body).toContain("ind_hbm");
  });

  it("unsealed macro deep analysis query reports explicit unavailable with 10-dimension notice", async () => {
    const messages = await actualReply("宏觀產業 深度化分析 ind_hbm");
    const body = JSON.stringify(messages);
    expect(body).toContain("MACRO_DEEP_UNAVAILABLE");
    expect(body).toContain("10維完整展開");
  });

  it("guarantees zero private cache reads across all macro and options flows", async () => {
    const f = fixture();
    // Running all commands; if any touches TENANT_PRIVATE_CACHE, it throws PRIVATE_READ_FORBIDDEN
    await actualReply("選單", f);
    await actualReply("TOP5產業總覽", f);
    await actualReply("宏觀產業 卡片 test", f);
    await actualReply("宏觀產業 深度化分析 test", f);
    await actualReply("期權教學", f);
    await actualReply("NVDA 每週期權", f);
    await actualReply("期權試算說明", f);
  });
});
