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
import { SNAPSHOT_OBJECT_KEYS, SNAPSHOT_SEAL_KEY, buildSnapshotSeal } from "../src/v213/snapshot-seal";
import sealContract from "../../config/v213-r75-publication-mode-v1.json";

const SENTINEL = "UNADMITTED_ACQUISITION_SENTINEL_999999";
const SYNTHETIC_FORGED_ACQUISITION = JSON.stringify({
  schema_version: 1,
  synthetic: true,
  run_uuid: "00000000-0000-4000-8000-000000000001",
  status: "ACQUIRED",
  source_health: "HEALTHY",
  publication_eligible: true,
  clocks: { acquired_at: new Date().toISOString(), retrieved_at: new Date().toISOString() },
  normalized_hashes: { sha256: "0".repeat(64) },
  body: { candidate_ticker: SENTINEL, value: 999999, sentinel: SENTINEL },
  acquisition_summary: { candidate_tickers: [SENTINEL], status: "ACQUIRED" },
  global_sources: [{ id: SENTINEL, status: "ACQUIRED", source_health: "HEALTHY", publication_eligible: true, detail: { value: 999999 } }],
});

function applyForgedAcquisitionMetadata(publicKv: MemoryKv) {
  publicKv.values.set("v213:source-federation:latest", SYNTHETIC_FORGED_ACQUISITION);
  publicKv.values.set("v213:source-independence:latest", SYNTHETIC_FORGED_ACQUISITION);
  publicKv.values.set("v213:acquisition-summary:latest", SYNTHETIC_FORGED_ACQUISITION);
}

async function fixture(opts: { withReport?: boolean; overrides?: Record<string, string> } = {}) {
  const publicKv = new MemoryKv();
  const privateKv = new MemoryKv();
  const privateSpy = vi.spyOn(privateKv, "get");
  const stamp = new Date().toISOString();
  if (opts.withReport) {
    const report = {
      schema_version: 2, product_version: "2.1.3", generated_at: stamp,
      display_columns: V213_TOP20_DISPLAY_COLUMNS, long_term_definition: "trailing_2y_adjusted_close_cagr",
      short_term_definition: "trailing_6m_adjusted_close_price_return", provider_scope: "public_only", owner_watchlist_inherited: false,
      records: Array.from({ length: 20 }, (_, i) => ({
        schema_version: 2, rank: i + 1, ticker: `T${i.toString().padStart(2, "0")}`,
        name: `Synthetic Company ${i}`, industry: i < 10 ? "產業甲" : "產業乙", profit_summary: "合成財務組件",
        current_orders: V213_NO_CURRENT_ORDERS, future_orders_estimate: V213_NO_FUTURE_ORDER_ESTIMATE,
        long_term_return_pct: null, short_term_return_pct: null, long_term_window: "2y_cagr", short_term_window: "6m_price_return",
        market_source: "yfinance", profit_source: "sec_edgar", orders_as_of: stamp, orders_confidence: "UNAVAILABLE",
        current_order_source_urls: [], future_order_source_urls: [], numeric_total_order_estimate_prohibited: true,
        retrieved_at: stamp, provider_scope: "public_only", owner_watchlist_inherited: false,
      })),
    };
    const RUN_ID = "20260910T100000Z-123456789abc";
    const TX_ID = "1".repeat(32);
    const bodies: [string, string][] = SNAPSHOT_OBJECT_KEYS.map(key => [key, JSON.stringify({ synthetic: key })]);
    bodies.find(([key]) => key === "last_successful_pipeline_timestamp")![1] = stamp;
    bodies.find(([key]) => key === "v213:top20-report:latest")![1] = JSON.stringify(report);
    bodies.find(([key]) => key === "v213:activation-claim")![1] = JSON.stringify({ schema_version: 1, transaction_id: TX_ID, run_id: RUN_ID, payload_digests: Object.fromEntries(sealContract.payload_names.map((name) => [name, "a".repeat(64)])), claimed_at: stamp });
    const seal = await buildSnapshotSeal({ run_id: RUN_ID, transaction_id: TX_ID, generated_at: stamp, public_data_as_of: stamp }, bodies);
    for (const [key, body] of bodies) publicKv.values.set(`snapshot:${RUN_ID}:${key}`, body);
    publicKv.values.set(`snapshot:${RUN_ID}:${SNAPSHOT_SEAL_KEY}`, seal.text);
    publicKv.values.set("snapshot:current", JSON.stringify({ schema_version: 2, run_id: RUN_ID, transaction_id: TX_ID, seal_sha256: seal.sha256, public_data_as_of: stamp, promoted_at: stamp, provider_scope: "public_only", owner_watchlist_inherited: false }));

  }
  return {
    publicKv, privateKv, privateSpy,
    env: {
      PUBLIC_CACHE: asKv(publicKv), TENANT_PRIVATE_CACHE: asKv(privateKv),
      EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()),
      LINE_CHANNEL_SECRET: "EXAMPLE_NOT_REAL", LINE_CHANNEL_ACCESS_TOKEN: "EXAMPLE_NOT_REAL",
      CURRENT_PUBLIC_DATA_ENABLED: "true", ...opts.overrides,
    },
  };
}

async function actualReply(command: string, f?) {
  if (!f) f = await fixture();

  let messages: any[] = [];
  const fetchSpy = vi.fn(async (url: string, init: RequestInit) => {
    expect(url).toBe("https://api.line.me/v2/bot/message/reply");
    messages = JSON.parse(String(init.body)).messages;
    return new Response("{}", { status: 200 });
  });
  vi.stubGlobal("fetch", fetchSpy);
  const modelJob = vi.fn(() => { throw new Error("MODEL_JOB_FORBIDDEN"); });
  await processAuthorizedLineEvent(
    await freeRelayRequestEnv(f.env as any),
    { waitUntil: modelJob } as unknown as ExecutionContext,
    {
      type: "message", replyToken: "SYNTHETIC_REPLY", timestamp: Date.now(),
      message: { id: "SYNTHETIC_MESSAGE", type: "text", text: command },
    },
    "SYNTHETIC_TENANT",
  );
  assertLineMessages(messages);
  expect(fetchSpy).toHaveBeenCalledTimes(1);
  expect(f.privateSpy).not.toHaveBeenCalled();
  expect(modelJob).not.toHaveBeenCalled();
  return messages;
}

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("LINE caller acquisition metadata isolation and publication refusal", () => {
  it("TOP20 default flex rejects forged acquisition metadata without valid report", async () => {
    const f = await fixture();
    applyForgedAcquisitionMetadata(f.publicKv);
    const messages = await actualReply("TOP20", f);
    expect(messages.length).toBeGreaterThan(0);
    const body = JSON.stringify(messages);
    expect(body).toContain("七欄 Top20 報告尚未通過驗證；不退回五欄");
    expect(body).not.toContain(SENTINEL);
    expect(body).not.toContain("999999");
    expect(body).not.toContain("LOCAL_MODEL_NOT_CONFIGURED");
  });

  it("TOP20 text presentation rejects forged acquisition metadata without valid report", async () => {
    const f = await fixture({ overrides: { V213_LINE_PRESENTATION: "text" } });
    applyForgedAcquisitionMetadata(f.publicKv);
    const messages = await actualReply("TOP20", f);
    expect(messages.length).toBeGreaterThan(0);
    expect(messages.every(m => m.type === "text")).toBe(true);
    const body = JSON.stringify(messages);
    expect(body).toContain("七欄 Top20 報告尚未通過驗證；不退回五欄");
    expect(body).not.toContain(SENTINEL);
    expect(body).not.toContain("999999");
  });

  it("宏觀產業分析 default flex presents unavailable panel with navigation and no forged facts", async () => {
    const f = await fixture();
    applyForgedAcquisitionMetadata(f.publicKv);
    const messages = await actualReply("宏觀產業分析", f);
    expect(messages.length).toBeGreaterThan(0);
    expect(messages.every(m => m.type === "flex")).toBe(true);
    const body = JSON.stringify(messages);
    expect(body).toContain("宏觀產業分析");
    expect(body).toContain("當輪產業資料不可用");
    expect(body).toContain("不以舊快照、候選宏觀資料或模型猜測補齊。");
    expect(body).toContain("TOP20");
    expect(body).toContain("宏觀資料說明");
    expect(body).toContain("選單");
    expect(body).not.toContain(SENTINEL);
    expect(body).not.toContain("999999");
  });

  it("宏觀產業分析 text presentation presents unavailable text with navigation and no forged facts", async () => {
    const f = await fixture({ overrides: { V213_LINE_PRESENTATION: "text" } });
    applyForgedAcquisitionMetadata(f.publicKv);
    const messages = await actualReply("宏觀產業分析", f);
    expect(messages.length).toBeGreaterThan(0);
    expect(messages.every(m => m.type === "text")).toBe(true);
    const body = JSON.stringify(messages);
    expect(body).toContain("當輪產業資料不可用");
    expect(body).toContain("不以舊快照、候選宏觀資料或模型猜測補齊。");
    expect(body).toContain("TOP20 公司證據：TOP20");
    expect(body).toContain("回功能選單：選單");
    expect(body).not.toContain(SENTINEL);
  });

  it("options entry remains OPTION_DATA_UNAVAILABLE despite forged acquisition flags", async () => {
    const f = await fixture();
    applyForgedAcquisitionMetadata(f.publicKv);
    const messages = await actualReply("期權", f);
    const body = JSON.stringify(messages);
    expect(body).toContain("OPTION_DATA_UNAVAILABLE");
    expect(body).toContain("最新期權");
    expect(body).toContain("期權試算說明");
    expect(body).toContain("選單");
    expect(body).not.toContain(SENTINEL);
    expect(body).not.toContain("999999");
  });

  it.each(["宏觀產業分析", "TOP20"])("corrupted pinned snapshot cannot be rescued by direct report or forged metadata for %s", async cmd => {
    const f = await fixture({ withReport: true });
    applyForgedAcquisitionMetadata(f.publicKv);
    f.publicKv.values.set("snapshot:current", "{broken");
    const messages = await actualReply(cmd, f);
    const body = JSON.stringify(messages);
    if (cmd === "宏觀產業分析") {
      expect(body).toContain("當輪產業資料不可用");
    } else {
      expect(body).toContain("七欄 Top20 報告尚未通過驗證；不退回五欄");
    }
    expect(body).not.toContain("T00");
    expect(body).not.toContain(SENTINEL);
  });

  it("legitimate TOP20 displays genuine tickers and ignores unadmitted candidate sentinel", async () => {
    const f = await fixture({ withReport: true });
    applyForgedAcquisitionMetadata(f.publicKv);
    const messages = await actualReply("TOP20", f);
    expect(messages.length).toBeGreaterThan(0);
    const body = JSON.stringify(messages);
    expect(body).toContain("T00");
    expect(body).toContain("T19");
    expect(body).toContain("歷史報酬，非預測");
    expect(body).not.toContain(SENTINEL);
    expect(body).not.toContain("999999");
  });

  it("legitimate macro analysis computes real distribution and withholds forged macro sentinel", async () => {
    const f = await fixture({ withReport: true });
    applyForgedAcquisitionMetadata(f.publicKv);
    const messages = await actualReply("宏觀產業分析", f);
    const body = JSON.stringify(messages);
    expect(body).toContain("產業甲");
    expect(body).toContain("產業乙");
    expect(body).toContain("10/20家（50%）");
    expect(body).toContain("MACRO_PRODUCT_NOT_SEALED");
    expect(body).not.toContain(SENTINEL);
    expect(body).not.toContain("999999");
  });
});
