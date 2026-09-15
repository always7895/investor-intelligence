import { sealUnboundReport } from "./sealed-report-migration";
import { afterEach, describe, expect, it, vi } from "vitest";
import { assertLineMessages } from "../src/line-messages";
import { processAuthorizedLineEvent } from "../src/v211/worker";
import { freeRelayRequestEnv } from "../src/v213/production-worker";
import {
  V213_TOP20_DISPLAY_COLUMNS,
  V213_NO_CURRENT_ORDERS,
  V213_NO_FUTURE_ORDER_ESTIMATE,
  V213_STALE_RECORDS_MESSAGE,
} from "../src/v213/top20-report";
import { buildSnapshotSeal, SNAPSHOT_OBJECT_KEYS, SNAPSHOT_SEAL_KEY } from "../src/v213/snapshot-seal";
import contract from "../../config/v213-r75-publication-mode-v1.json";
import { MemoryKv, asKv } from "./fake-kv";

async function textFixture(overrides: Record<string, string> = {}) {
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
      industry: `產業${String(i).padStart(2, "0")}`,
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
  const save = async () => {
    publicKv.values.set("v213:top20-report:latest", JSON.stringify(report));
    publicKv.values.set("last_successful_pipeline_timestamp", report.generated_at);
    await sealUnboundReport(publicKv);
  };
  await save();

  class PrivateForbidden extends MemoryKv {
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
      TENANT_PRIVATE_CACHE: asKv(new PrivateForbidden()),
      EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()),
      LINE_CHANNEL_SECRET: "EXAMPLE_NOT_REAL",
      LINE_CHANNEL_ACCESS_TOKEN: "EXAMPLE_NOT_REAL",
      CURRENT_PUBLIC_DATA_ENABLED: "true",
      V213_LINE_PRESENTATION: "text",
      ...overrides,
    },
  };
}

async function actualReply(command: string, f?) {
  if (!f) f = (await textFixture());
  let messages: any[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
    expect(url).toBe("https://api.line.me/v2/bot/message/reply");
    messages = JSON.parse(String(init.body)).messages;
    return new Response("{}", { status: 200 });
  }));
  await processAuthorizedLineEvent(
    await freeRelayRequestEnv(f.env),
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

describe("v213 text presentation hotfix through actual authorized Line event caller", () => {
  it.each([
    ["選單", "TOP20"],
    ["期權", "教學範例，非推薦"],
    ["宏觀資料說明", "CONTEXT_ONLY"],
    ["宏觀產業分析", "MACRO_TOP5_SHORTFALL"],
  ])("original RED equivalent reaches text output in text env: %s", async (command, required) => {
    const messages = await actualReply(command);
    expect(messages.length).toBeGreaterThan(0);
    expect(messages.every(m => m.type === "text")).toBe(true);
    const body = JSON.stringify(messages);
    expect(body).toContain(required);
  });

  it("main macro entry 宏觀產業分析 in text env routes to shortfall report", async () => {
    const f = await textFixture();
    const messages = await actualReply("宏觀產業分析", f);
    expect(messages.every(m => m.type === "text")).toBe(true);
    const body = JSON.stringify(messages);
    expect(body).toContain("MACRO_TOP5_SHORTFALL");
    expect(body).not.toContain("當輪產業分布");
  });

  it("compatibility industry distribution command retains all groups without silent slicing", async () => {
    const f = await textFixture();
    const messages = await actualReply("當輪產業分布", f);
    expect(messages.every(m => m.type === "text")).toBe(true);
    const body = JSON.stringify(messages);
    for (const row of f.report.records) {
      expect(body).toContain(row.industry);
      expect(body).toContain(row.ticker);
    }
    expect(body).not.toContain("摘要顯示");
    expect(body).toContain("MACRO_PRODUCT_NOT_SEALED");
  });

  it("compatibility industry distribution on unavailable returns bounded text messages with navigation", async () => {
    const f = await textFixture();
    await f.save();
    f.publicKv.values.set("snapshot:current", "{broken");
    const messages = await actualReply("當輪產業分布", f);
    expect(messages.every(m => m.type === "text")).toBe(true);
    const body = JSON.stringify(messages);
    expect(body).toContain("當輪產業資料不可用");
    expect(body).toContain("不以舊快照、候選宏觀資料或模型猜測補齊。");
    expect(body).toContain("TOP20 公司證據：TOP20");
    expect(body).toContain("回功能選單：選單");
  });

  it("compatibility industry distribution on stale returns bounded text messages with navigation", async () => {
    const f = await textFixture();
    f.report.records[0]!.retrieved_at = "2000-01-01T00:00:00Z";
    await f.save();
    const messages = await actualReply("當輪產業分布", f);
    expect(messages.every(m => m.type === "text")).toBe(true);
    const body = JSON.stringify(messages);
    expect(body).toContain("公司資料過期");
    expect(body).toContain(V213_STALE_RECORDS_MESSAGE);
    expect(body).toContain("TOP20 公司證據：TOP20");
    expect(body).toContain("回功能選單：選單");
  });

  it("explicit compatibility distribution 文字 on unavailable forces text output without env text", async () => {
    const f = await textFixture({ V213_LINE_PRESENTATION: "" });
    await f.save();
    f.publicKv.values.set("snapshot:current", "{broken");
    const messages = await actualReply("當輪產業分布 文字", f);
    expect(messages.every(m => m.type === "text")).toBe(true);
    const body = JSON.stringify(messages);
    expect(body).toContain("當輪產業資料不可用");
    expect(body).toContain("不以舊快照、候選宏觀資料或模型猜測補齊。");
    expect(body).toContain("TOP20 公司證據：TOP20");
    expect(body).toContain("回功能選單：選單");
  });

  it("explicit compatibility distribution 文字 on stale forces text output without env text", async () => {
    const f = await textFixture({ V213_LINE_PRESENTATION: "" });
    f.report.records[0]!.retrieved_at = "2000-01-01T00:00:00Z";
    await f.save();
    const messages = await actualReply("當輪產業分布 文字", f);
    expect(messages.every(m => m.type === "text")).toBe(true);
    const body = JSON.stringify(messages);
    expect(body).toContain("公司資料過期");
    expect(body).toContain(V213_STALE_RECORDS_MESSAGE);
    expect(body).toContain("TOP20 公司證據：TOP20");
    expect(body).toContain("回功能選單：選單");
  });

  it.each(["選單", "期權", "宏觀資料說明", "宏觀產業分析"])(
    "default Flex mode is retained for %s without env text",
    async command => {
      const f = await textFixture({ V213_LINE_PRESENTATION: "" });
      const messages = await actualReply(command, f);
      expect(messages.every(m => m.type === "flex")).toBe(true);
      if (command === "宏觀產業分析") {
        const body = JSON.stringify(messages);
        expect(body).toContain("TOP5");
        expect(body).toContain("短缺通報");
      }
      if (command === "期權") {
        const body = JSON.stringify(messages);
        expect(body).toContain("教學範例，非推薦");
      }
    },
  );

  it("sealed snapshot options in text env preserves OPTION_DATA_NOT_ADMITTED disclosure in text", async () => {
    const f = await textFixture();
    const SEAL_RUN = "20260910T100000Z-123456789abc";
    const TX = "1".repeat(32);
    const TIME = "2026-09-10T10:00:00Z";
    const bodies: [string, string][] = SNAPSHOT_OBJECT_KEYS.map(key => [key, JSON.stringify({ synthetic: key })]);
    bodies.find(([key]) => key === "last_successful_pipeline_timestamp")![1] = TIME;
    bodies.find(([key]) => key === "v213:activation-claim")![1] = JSON.stringify({
      schema_version: 1,
      run_id: SEAL_RUN,
      transaction_id: TX,
      payload_digests: Object.fromEntries(contract.payload_names.map(name => [name, "a".repeat(64)])),
      claimed_at: TIME,
    });
    const seal = await buildSnapshotSeal({ run_id: SEAL_RUN, transaction_id: TX, generated_at: TIME, public_data_as_of: TIME }, bodies);
    const prefix = `snapshot:${SEAL_RUN}:`;
    for (const [key, body] of bodies) f.publicKv.values.set(prefix + key, body);
    f.publicKv.values.set(prefix + SNAPSHOT_SEAL_KEY, seal.text);
    f.publicKv.values.set("snapshot:current", JSON.stringify({
      schema_version: 2,
      run_id: SEAL_RUN,
      transaction_id: TX,
      seal_sha256: seal.sha256,
      public_data_as_of: TIME,
      promoted_at: TIME,
      provider_scope: "public_only",
      owner_watchlist_inherited: false,
    }));
    const messages = await actualReply("最新期權", f);
    expect(messages.every(m => m.type === "text")).toBe(true);
    const body = JSON.stringify(messages);
    expect(body).toContain("OPTION_DATA_NOT_ADMITTED");
    expect(body).toContain("期權策略教學：期權教學");
    expect(body).toContain("期權試算說明：期權試算說明");
    expect(body).toContain("TOP20 個股入口：TOP20");
    expect(body).toContain("回功能選單：選單");
  });
});
