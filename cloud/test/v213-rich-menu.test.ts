import { afterEach, describe, expect, it, vi } from "vitest";
import { writeFileSync } from "node:fs";
import { parseQuery } from "../src/core";
import { assertLineMessages } from "../src/line-messages";
import { processAuthorizedLineEvent } from "../src/v211/worker";
import { freeRelayRequestEnv } from "../src/v213/production-worker";
import { RICH_MENU_ACTIONS, v213PublicLineAnswer } from "../src/v213/rich-menu";
import { V213_TOP20_DISPLAY_COLUMNS, V213_NO_CURRENT_ORDERS, V213_NO_FUTURE_ORDER_ESTIMATE } from "../src/v213/top20-report";
import { MemoryKv, asKv } from "./fake-kv";

function fixture() {
  const publicKv = new MemoryKv(); const stamp = new Date().toISOString();
  const report = { schema_version: 2, product_version: "2.1.3", generated_at: stamp,
    display_columns: V213_TOP20_DISPLAY_COLUMNS, long_term_definition: "trailing_2y_adjusted_close_cagr",
    short_term_definition: "trailing_6m_adjusted_close_price_return", provider_scope: "public_only", owner_watchlist_inherited: false,
    records: Array.from({ length: 20 }, (_, i) => ({ schema_version: 2, rank: i + 1, ticker: `T${i.toString().padStart(2, "0")}`,
      name: `Synthetic Company ${i}`, industry: i < 10 ? "產業甲" : "產業乙", profit_summary: "合成財務組件",
      current_orders: V213_NO_CURRENT_ORDERS, future_orders_estimate: V213_NO_FUTURE_ORDER_ESTIMATE,
      long_term_return_pct: null, short_term_return_pct: null, long_term_window: "2y_cagr", short_term_window: "6m_price_return",
      market_source: "yfinance", profit_source: "sec_edgar", orders_as_of: stamp, orders_confidence: "UNAVAILABLE",
      current_order_source_urls: [], future_order_source_urls: [], numeric_total_order_estimate_prohibited: true,
      retrieved_at: stamp, provider_scope: "public_only", owner_watchlist_inherited: false })) };
  const save = () => { publicKv.values.set("v213:top20-report:latest", JSON.stringify(report)); publicKv.values.set("last_successful_pipeline_timestamp", report.generated_at); };
  save();
  class NoPrivateReads extends MemoryKv { override async get<T = string>(): Promise<T | null> { throw new Error("PRIVATE_READ_FORBIDDEN"); } }
  return { publicKv, report, save, env: { PUBLIC_CACHE: asKv(publicKv), TENANT_PRIVATE_CACHE: asKv(new NoPrivateReads()),
    EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()), LINE_CHANNEL_SECRET: "EXAMPLE_NOT_REAL", LINE_CHANNEL_ACCESS_TOKEN: "EXAMPLE_NOT_REAL", CURRENT_PUBLIC_DATA_ENABLED: "true" } };
}
async function actualReply(command: string, f = fixture()) {
  let messages: any[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
    expect(url).toBe("https://api.line.me/v2/bot/message/reply");
    messages = JSON.parse(String(init.body)).messages;
    return new Response("{}", { status: 200 });
  }));
  await processAuthorizedLineEvent(await freeRelayRequestEnv(f.env), { waitUntil() { throw new Error("MODEL_JOB_FORBIDDEN"); } } as unknown as ExecutionContext,
    { type: "message", replyToken: "SYNTHETIC_REPLY", timestamp: Date.now(), message: { id: "SYNTHETIC_MESSAGE", type: "text", text: command } }, "SYNTHETIC_TENANT");
  assertLineMessages(messages);
  expect(fetch).toHaveBeenCalledTimes(1);
  return messages;
}
afterEach(() => vi.unstubAllGlobals());
describe("existing LINE rich-menu commands through actual authorized caller", () => {
  it.each(RICH_MENU_ACTIONS)("handles $text without a model/private fallback", async action => {
    const messages = await actualReply(action.text);
    const body = JSON.stringify(messages);
    expect(body).toContain(action.text === "TOP20" ? "T00" : action.text === "期權" ? "期權與個股快查" : "宏觀產業分析");
    expect(body).not.toContain("LOCAL_MODEL_NOT_CONFIGURED");
  });
  it("menu actions exactly match the operator's configured text commands", async () => {
    const messages = await actualReply("選單");
    const actions = messages[0].contents.contents[0].footer.contents.map((b: any) => b.action.text);
    expect(actions).toEqual(["TOP20", "宏觀產業分析", "期權"]);
  });
  it("computes all 20 industry memberships while withholding unsealed macro values", async () => {
    const f = fixture();
    f.publicKv.values.set("v213:source-federation:latest", JSON.stringify({ global_sources: [{ detail: { value: 999999, publication_eligible: false } }] }));
    const body = JSON.stringify(await actualReply("宏觀產業分析 文字", f));
    for (const row of f.report.records) expect(body).toContain(row.ticker);
    expect(body).toContain("10/20家（50%）"); expect(body).toContain("MACRO_PRODUCT_NOT_SEALED");
    expect(body).not.toContain("999999"); expect(body).toContain("不是市值／營收權重");
  });
  it.each(["bad_pointer", "stale_report", "stale_row", "future_row"])("does not use fresh direct keys to rescue %s", async state => {
    const f = fixture();
    if (state === "bad_pointer") f.publicKv.values.set("snapshot:current", "{broken");
    if (state === "stale_report") f.report.generated_at = "2000-01-01T00:00:00Z";
    if (state === "stale_row") f.report.records[0]!.retrieved_at = "2000-01-01T00:00:00Z";
    if (state === "future_row") f.report.records[0]!.retrieved_at = new Date(Date.now() + 600_000).toISOString();
    f.save();
    const body = JSON.stringify(await actualReply("宏觀產業分析", f));
    expect(body).not.toContain("10/20家"); expect(body).not.toContain("T00");
  });
  it("options entry has working quote/help navigation without inventing prices", async () => {
    const body = JSON.stringify(await actualReply("期權"));
    expect(body).toContain("OPTION_DATA_UNAVAILABLE"); expect(body).toContain("最新期權");
    const quote = JSON.stringify(await actualReply("最新期權"));
    expect(quote).toContain("目前沒有可用的公開期權快照");
    const help = JSON.stringify(await actualReply("期權試算說明"));
    expect(help).toContain("期權試算 ticker=");
  });
  it("can export the actual synthetic replies for local visual review only", async () => {
    const replies = [];
    for (const action of RICH_MENU_ACTIONS) replies.push({ command: action.text, messages: await actualReply(action.text) });
    if (process.env.V213_MENU_PREVIEW_OUT) writeFileSync(process.env.V213_MENU_PREVIEW_OUT, JSON.stringify({
      synthetic: true, line_transport_mocked: true, release_qualified: false, replies,
    }, null, 2), "utf8");
    expect(replies).toHaveLength(3);
  });
  it("explicit deep-product requests do not silently receive a menu summary", async () => {
    const result = await v213PublicLineAnswer(fixture().env, parseQuery("宏觀 數據詳報"));
    expect(result).toContain("RESEARCH_PRODUCT_NOT_SEALED");
  });
});
