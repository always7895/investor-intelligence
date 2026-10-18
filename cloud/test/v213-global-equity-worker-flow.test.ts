import { afterEach, describe, expect, it, vi } from "vitest";
import { assertLineMessages } from "../src/line-messages";
import { processAuthorizedLineEvent } from "../src/v211/worker";
import { freeRelayRequestEnv } from "../src/v213/production-worker";
import { MemoryKv, asKv } from "./fake-kv";

function fixture() {
  const publicKv = new MemoryKv();
  const stamp = new Date().toISOString();
  const report = {
    schema_version: 2,
    product_version: "2.1.3",
    generated_at: stamp,
    display_columns: ["公司代號", "產業分類", "估值狀態", "訂單能見度", "毛利表現", "兩年CAGR", "六個月報酬"],
    long_term_definition: "trailing_2y_adjusted_close_cagr",
    short_term_definition: "trailing_6m_adjusted_close_price_return",
    provider_scope: "public_only",
    owner_watchlist_inherited: false,
    records: [
      {
        schema_version: 2,
        rank: 1,
        ticker: "AAPL",
        name: "Apple Inc.",
        industry: "消費電子",
        profit_summary: "獲利穩定",
        current_orders: "SEC-EDGAR-RPO",
        future_orders_estimate: "NO_FUTURE_ESTIMATE",
        long_term_return_pct: 25.5,
        short_term_return_pct: 10.2,
        long_term_window: "2y_cagr",
        short_term_window: "6m_price_return",
        market_source: "yfinance",
        profit_source: "sec_edgar",
        orders_as_of: stamp,
        orders_confidence: "VERIFIED",
        current_order_source_urls: [],
        future_order_source_urls: [],
        numeric_total_order_estimate_prohibited: true,
        retrieved_at: stamp,
        provider_scope: "public_only",
        owner_watchlist_inherited: false,
      },
    ],
  };

  publicKv.values.set("v213:top20-report:latest", JSON.stringify(report));
  publicKv.values.set("last_successful_pipeline_timestamp", stamp);

  class NoPrivateReads extends MemoryKv {
    override async get<T = string>(): Promise<T | null> {
      throw new Error("PRIVATE_READ_FORBIDDEN");
    }
  }

  return {
    publicKv,
    report,
    env: {
      PUBLIC_CACHE: asKv(publicKv),
      TENANT_PRIVATE_CACHE: asKv(new NoPrivateReads()),
      EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()),
      LINE_CHANNEL_SECRET: "EXAMPLE_NOT_REAL",
      LINE_CHANNEL_ACCESS_TOKEN: "EXAMPLE_NOT_REAL",
      CURRENT_PUBLIC_DATA_ENABLED: "true",
    },
  };
}

async function sendAuthorizedMessage(text: string, f = fixture()) {
  let messages: any[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit) => {
      expect(url).toBe("https://api.line.me/v2/bot/message/reply");
      messages = JSON.parse(String(init.body)).messages;
      return new Response("{}", { status: 200 });
    }),
  );

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
      message: { id: "SYNTHETIC_MESSAGE", type: "text", text },
    },
    "SYNTHETIC_TENANT",
  );

  assertLineMessages(messages);
  return messages;
}

afterEach(() => vi.unstubAllGlobals());

describe("Global Equity Worker Flow", () => {
  it.each(["sive", "Sive", "SIVE"])(
    "intercepts %s before generic QA / issue intake / local model and returns dedicated stock Flex card",
    async (command) => {
      const messages = await sendAuthorizedMessage(command);
      expect(messages).toHaveLength(1);
      const json = JSON.stringify(messages[0]);

      // Must be a dedicated stock card
      expect(json).toContain("個股快查 · SIVE");
      expect(json).toContain("QUOTE_UNAVAILABLE");
      // Must NOT contain issue ID or local model waiting
      expect(json).not.toContain("問題已收到");
      expect(json).not.toContain("查看結果");
      expect(json).not.toContain("LOCAL_MODEL");
      // Must NOT falsely show legacy top 20 or AAPL data
      expect(json).not.toContain("消費電子");
      // Must NOT invent unverified US OTC
      expect(json).not.toContain("US OTC");
    },
  );

  it("handles Swedish scheme SIVE.ST with dedicated card and no local model fallback", async () => {
    const messages = await sendAuthorizedMessage("SIVE.ST");
    expect(messages).toHaveLength(1);
    const json = JSON.stringify(messages[0]);
    expect(json).toContain("個股快查 · SIVE.ST");
    expect(json).toContain("Nasdaq Stockholm");
    expect(json).not.toContain("問題已收到");
    expect(json).not.toContain("查看結果");
  });

  it("handles other international equity symbols without falling back to local model", async () => {
    const testSymbols = [
      "AAPL",
      "7203.T",
      "005930.KS",
      "0700.HK",
      "600519.SS",
      "000001.SZ",
      "2330.TW",
      "IQE.L",
      "ASML.AS",
    ];

    for (const sym of testSymbols) {
      const messages = await sendAuthorizedMessage(sym);
      expect(messages).toHaveLength(1);
      const json = JSON.stringify(messages[0]);
      expect(json).toContain(`個股快查 · ${sym}`);
      expect(json).not.toContain("問題已收到");
      expect(json).not.toContain("查看結果");
    }
  });

  it("preserves standard menu commands and does not divert them to equity lookup", async () => {
    const menuResp = await sendAuthorizedMessage("TOP20");
    const json = JSON.stringify(menuResp);
    expect(json.toUpperCase()).toContain("TOP20");
    expect(json).toContain("Top20");
    expect(json).not.toContain("個股快查");
  });
});
