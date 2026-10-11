import { sealUnboundReport } from "./sealed-report-migration";
import { afterEach, describe, expect, it, vi } from "vitest";
import { assertLineMessages } from "../src/line-messages";
import { processAuthorizedLineEvent } from "../src/v211/worker";
import { freeRelayRequestEnv } from "../src/v213/production-worker";
import { V213_TOP20_DISPLAY_COLUMNS, V213_NO_CURRENT_ORDERS, V213_NO_FUTURE_ORDER_ESTIMATE } from "../src/v213/top20-report";
import { MemoryKv, asKv } from "./fake-kv";

// G1-21: only the exact Worker env string "1" enables the machine reader through the ordinary TOP20
// rich-menu command. Without a sealed v3 report and binding pair an enabled machine read fails closed
// to the v3-unavailable notice (never the older seven-field list); every other spelling keeps the
// legacy route. Synthetic in-memory KV and a stubbed LINE reply only; no network or credentials.
const V3_UNAVAILABLE = "\u74f6\u9838\u7206\u767c TOP20 \u76ee\u524d\u6c92\u6709\u5df2\u5c01\u5b58\u4e14\u5728\u6642\u6548"
  + "\u5167\u7684\u8cc7\u6599\uff0c\u672a\u4ee5\u820a\u8cc7\u6599\u66ff\u4ee3\u3002\u8f38\u5165\u300c\u4e03\u6b04Top20\u300d"
  + "\u53ef\u770b\u820a\u7248\u4e03\u6b04\u699c\u3002";
type GuidanceEnv = { V213_GUIDANCE_MACHINE_ENABLED?: string; V213_GUIDANCE_WIRE_ENABLED?: string };

async function environment(guidance: GuidanceEnv) {
  const publicKv = new MemoryKv(); const stamp = new Date().toISOString();
  const report = { schema_version: 2, product_version: "2.1.3", generated_at: stamp,
    freshness_policy: { policy_id: "v213-serenity-fresh-independent-evidence-v2", policy_sha256: "27ce461fae50218bb14e4d50ff283f6ed75b201e4a38d656643a5ed65d59c8d8" }, evidence_capture_at: stamp,
    display_columns: V213_TOP20_DISPLAY_COLUMNS, long_term_definition: "trailing_2y_adjusted_close_cagr",
    short_term_definition: "trailing_6m_adjusted_close_price_return", provider_scope: "public_only", owner_watchlist_inherited: false,
    records: Array.from({ length: 20 }, (_, i) => ({ schema_version: 2, rank: i + 1, ticker: `T${i.toString().padStart(2, "0")}`,
      name: `Synthetic Company ${i}`, industry: i < 10 ? "Synthetic Industry A" : "Synthetic Industry B", profit_summary: "synthetic profit",
      current_orders: V213_NO_CURRENT_ORDERS, future_orders_estimate: V213_NO_FUTURE_ORDER_ESTIMATE,
      long_term_return_pct: null, short_term_return_pct: null, long_term_window: "2y_cagr", short_term_window: "6m_price_return",
      market_source: "yfinance", profit_source: "sec_edgar", orders_as_of: stamp, orders_confidence: "UNAVAILABLE",
      current_order_source_urls: [], future_order_source_urls: [], numeric_total_order_estimate_prohibited: true,
      retrieved_at: stamp, orders_state_as_of: stamp, evidence_class: "structural_claim", freshness_policy_key: "structural_claim_max_age_days", test_only_admission: true, provider_scope: "public_only", owner_watchlist_inherited: false })) };
  publicKv.values.set("v213:top20-report:latest", JSON.stringify(report));
  publicKv.values.set("last_successful_pipeline_timestamp", report.generated_at);
  await sealUnboundReport(publicKv);
  class NoPrivateReads extends MemoryKv { override async get<T = string>(): Promise<T | null> { throw new Error("PRIVATE_READ_FORBIDDEN"); } }
  return { PUBLIC_CACHE: asKv(publicKv), TENANT_PRIVATE_CACHE: asKv(new NoPrivateReads()),
    EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()), LINE_CHANNEL_SECRET: "EXAMPLE_NOT_REAL", LINE_CHANNEL_ACCESS_TOKEN: "EXAMPLE_NOT_REAL",
    CURRENT_PUBLIC_DATA_ENABLED: "true", ...guidance };
}
async function top20Reply(guidance: GuidanceEnv) {
  const env = await environment(guidance);
  let messages: any[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
    expect(url).toBe("https://api.line.me/v2/bot/message/reply");
    messages = JSON.parse(String(init.body)).messages;
    return new Response("{}", { status: 200 });
  }));
  await processAuthorizedLineEvent(await freeRelayRequestEnv(env), { waitUntil() { throw new Error("MODEL_JOB_FORBIDDEN"); } } as unknown as ExecutionContext,
    { type: "message", replyToken: "SYNTHETIC_REPLY", timestamp: Date.now(), message: { id: "SYNTHETIC_MESSAGE", type: "text", text: "TOP20" } }, "SYNTHETIC_TENANT");
  assertLineMessages(messages);
  expect(fetch).toHaveBeenCalledTimes(1);
  return JSON.stringify(messages);
}
afterEach(() => vi.unstubAllGlobals());

describe("G1-21 exact Worker env '1' through the ordinary TOP20 rich-menu command", () => {
  it.each<string | undefined>([undefined, "1"])("machine '1' (wire %j) fails closed to the v3 notice, never the seven-field list", async wire => {
    const body = await top20Reply({ V213_GUIDANCE_MACHINE_ENABLED: "1", V213_GUIDANCE_WIRE_ENABLED: wire });
    expect(body).toContain(V3_UNAVAILABLE);
    expect(body).not.toContain("T00");
  });

  it.each<string | undefined>([undefined, "", "0", "true", "TRUE", "yes", "on", " 1", "1 ", "01", "1.0", "\uff11"])(
    "machine %j keeps the legacy TOP20 route", async value => {
      const body = await top20Reply({ V213_GUIDANCE_MACHINE_ENABLED: value });
      expect(body).toContain("T00");
      expect(body).not.toContain(V3_UNAVAILABLE);
    });

  it("wire '1' alone never selects the machine route", async () => {
    const body = await top20Reply({ V213_GUIDANCE_WIRE_ENABLED: "1" });
    expect(body).toContain("T00");
    expect(body).not.toContain(V3_UNAVAILABLE);
  });
});
