import { afterEach, describe, expect, it, vi } from "vitest";
import worker, { freeRelayRequestEnv } from "../src/v213/production-worker";
import { processAuthorizedLineEvent } from "../src/v211/worker";
import { v213Top20ReportAnswer } from "../src/v213/top20-report";
import { parseQuery } from "../src/core";
import { buildV213Top20Messages, v213Top20LineAnswer } from "../src/v213/top20-presentation";
import { assertLineMessages } from "../src/line-messages";
import { inspectSevenFieldFlex } from "./r75-line-presentation-proof";
import { asKv, MemoryKv } from "./fake-kv";
import {
  formatV213Top20Report,
  parseV213Top20Report,
  V213_NO_CURRENT_ORDERS,
  V213_NO_FUTURE_ORDER_ESTIMATE,
} from "../src/v213/top20-report";

function report() {
  return {
    schema_version: 2,
    product_version: "2.1.3",
    generated_at: "2026-09-01T00:00:00Z",
    display_columns: [
      "股票", "長期投資報酬率（近2年年化）", "短期投資報酬率（近6個月）",
      "行業別", "獲利簡述", "公司現在訂單", "未來訂單預估",
    ],
    long_term_definition: "trailing_2y_adjusted_close_cagr",
    short_term_definition: "trailing_6m_adjusted_close_price_return",
    records: Array.from({ length: 20 }, (_, index) => ({
      schema_version: 2,
      rank: index + 1,
      ticker: `T${String(index).padStart(2, "0")}`,
      long_term_return_pct: 50 - index,
      short_term_return_pct: 15 - index / 2,
      industry: "半導體",
      profit_summary: "獲利；營收年增 +20.0%",
      current_orders: index === 0 ? "Casela 2027 RMB1.73億固定量" : V213_NO_CURRENT_ORDERS,
      future_orders_estimate: index === 0 ? "能見度偏高但不估總額" : V213_NO_FUTURE_ORDER_ESTIMATE,
      long_term_window: "2y_cagr",
      short_term_window: "6m_price_return",
      market_source: "yfinance",
      profit_source: "sec_edgar",
      orders_as_of: "2026-09-01T00:00:00Z",
      orders_confidence: index === 0 ? "EVIDENCE_BOUND" : "UNAVAILABLE",
      current_order_source_urls: index === 0 ? ["https://www.sec.gov/example/current"] : [],
      future_order_source_urls: index === 0 ? ["https://www.sec.gov/example/future"] : [],
      numeric_total_order_estimate_prohibited: true,
      retrieved_at: "2026-09-01T00:00:00Z",
      provider_scope: "public_only",
      owner_watchlist_inherited: false,
    })),
    provider_scope: "public_only",
    owner_watchlist_inherited: false,
  };
}

afterEach(() => vi.unstubAllGlobals());
describe("v2.1.3 seven-field Top20 contract and production routing", () => {
  it("accepts exactly 20 closed-schema seven-field rows", () => {
    expect(parseV213Top20Report(report())).not.toBeNull();
    const bad = report() as Record<string, unknown>;
    (bad.records as Array<Record<string, unknown>>)[0]!.numeric_total_order_estimate_prohibited = false;
    expect(parseV213Top20Report(bad)).toBeNull();
  });

  it("renders the two order fields at the end and hides source metadata", () => {
    const parsed = parseV213Top20Report(report());
    expect(parsed).not.toBeNull();
    const text = formatV213Top20Report(parsed!);
    expect(text.split("\n")[0]).toBe(
      "股票｜長期投資報酬率（近2年年化）｜短期投資報酬率（近6個月）｜行業別｜獲利簡述｜公司現在訂單｜未來訂單預估",
    );
    expect(text).toContain("Casela 2027 RMB1.73億固定量");
    expect(text).toContain(V213_NO_CURRENT_ORDERS);
    expect(text).not.toContain("https://");
    for (const line of text.split("\n")) expect(line.split("｜")).toHaveLength(7);
  });

  it("refuses delimiter injection in order summaries", () => {
    const bad = report();
    bad.records[0]!.current_orders = "A｜B";
    expect(parseV213Top20Report(bad)).toBeNull();
  });

  it("routes the actual authorized LINE Top20 reply through all seven bilingual columns, never legacy five", async () => {
    const kv = new MemoryKv();
    const data = report(); data.generated_at = new Date().toISOString();
    data.records[0]!.retrieved_at = data.generated_at;
    kv.values.set("v213:top20-report:latest", JSON.stringify(data));
    kv.values.set("last_successful_pipeline_timestamp", data.generated_at);
    const env = await freeRelayRequestEnv({ PUBLIC_CACHE: asKv(kv), TENANT_PRIVATE_CACHE: asKv(new MemoryKv()), EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()), LINE_CHANNEL_ACCESS_TOKEN: "SYNTHETIC_LINE_TOKEN_NOT_REAL", LINE_CHANNEL_SECRET: "SYNTHETIC_LINE_SECRET_NOT_REAL" } as any);
    const ctx = { waitUntil() {}, passThroughOnException() {} } as unknown as ExecutionContext;
    const messages: any[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
      expect(String(url)).toBe("https://api.line.me/v2/bot/message/reply");
      messages.push(...JSON.parse(String(init.body)).messages);
      return new Response("{}");
    }));
    await processAuthorizedLineEvent(env, ctx, { type: "message", replyToken: "SYNTHETIC_REPLY", source: { type: "user", userId: "SYNTHETIC_USER" }, message: { type: "text", text: "Top20" }, timestamp: Date.now() }, "synthetic-report-tenant");
    const proof = inspectSevenFieldFlex(messages, parseV213Top20Report(data)!);
    expect(proof).toMatchObject({ rows: 20, fields: Array(21).fill(7), presentation: "flex_carousel", message_count: 4, values_match: true });
    expect(proof.header).toContain("公司現在訂單 / Current orders");
    expect(proof.header).toContain("未來訂單預估 / Future order outlook");
    const command = messages[0].contents.contents[0].footer.contents.find((x: any) => x.type === "button").action.text;
    expect(command).toContain("T00");
    expect(command).not.toBe("Top20 文字");
    messages.length = 0;
    await processAuthorizedLineEvent(env, ctx, { type: "message", replyToken: "SYNTHETIC_REPLY", source: { type: "user", userId: "SYNTHETIC_USER" }, message: { type: "text", text: command }, timestamp: Date.now() }, "synthetic-report-tenant");
    const detail = messages.map(x => x.text ?? "").join("\n");
    expect(detail).toContain("T00｜本輪 Top20");
    expect(detail).not.toContain("T01");
    expect(detail).toContain("https://www.sec.gov/example/current");
    expect(detail).toContain("6 個月情境");
    expect(detail).toContain("1 年情境");
    expect(detail).toContain("2 年情境");
    expect(detail).toContain("尚非完整深度估值報告");
    expect(detail).toContain("兩年累積報酬：缺少");
    expect(detail).not.toBe(formatV213Top20Report(parseV213Top20Report(data)!));
    assertLineMessages(messages);
  });

  it("refuses obsolete card generations, stale row retrievals and unknown companies", async () => {
    const data = report(); data.generated_at = new Date().toISOString();
    data.records[0]!.retrieved_at = data.generated_at;
    const kv = new MemoryKv();
    const env = { PUBLIC_CACHE: asKv(kv), TENANT_PRIVATE_CACHE: asKv(new MemoryKv()), EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()) };
    const save = () => { kv.values.set("v213:top20-report:latest", JSON.stringify(data)); kv.values.set("last_successful_pipeline_timestamp", data.generated_at); };
    save();
    const command = `Top20 證據詳情 T00 ${data.generated_at}`;
    expect(await v213Top20LineAnswer(env, parseQuery(command.replace("T00 ", "ZZZZ ")))).toContain("不在本輪");
    data.records[0]!.retrieved_at = "2000-01-01T00:00:00Z"; save();
    expect(await v213Top20LineAnswer(env, parseQuery(command))).toContain("取得時間已過期");
    data.generated_at = new Date(Date.now() + 1000).toISOString(); save();
    expect(await v213Top20LineAnswer(env, parseQuery(command))).toContain("Top20 已更新");
  });

  it("rejects credential-bearing citations instead of displaying them", async () => {
    const data = report(); data.generated_at = new Date().toISOString(); data.records[0]!.retrieved_at = data.generated_at;
    const kv = new MemoryKv(); kv.values.set("last_successful_pipeline_timestamp", data.generated_at);
    for (const url of ["https://fixture@example.com/report", "https://www.sec.gov/report?access%5Ftoken=fixture", "https://www.sec.gov/report#access_token=fixture"]) {
      data.records[0]!.current_order_source_urls = [url];
      kv.values.set("v213:top20-report:latest", JSON.stringify(data));
      expect(parseV213Top20Report(data)).toBeNull();
      const env = { PUBLIC_CACHE: asKv(kv), TENANT_PRIVATE_CACHE: asKv(new MemoryKv()), EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()) };
      for (const command of ["Top20", `Top20 證據詳情 T00 ${data.generated_at}`]) {
        const response = await v213Top20LineAnswer(env, parseQuery(command));
        expect(response).toContain("未通過驗證");
        expect(response).not.toContain(url);
      }
    }
  });

  it("keeps all long evidence citations within LINE message limits", async () => {
    const data = report(); data.generated_at = new Date().toISOString(); data.records[0]!.retrieved_at = data.generated_at;
    const urls = Array.from({ length: 8 }, (_, i) => `https://issuer.example/${"x".repeat(900)}/${i}`);
    data.records[0]!.current_order_source_urls = urls;
    data.records[0]!.future_order_source_urls = urls.map(url => `${url}/future`);
    const kv = new MemoryKv(); kv.values.set("v213:top20-report:latest", JSON.stringify(data)); kv.values.set("last_successful_pipeline_timestamp", data.generated_at);
    const result = await v213Top20LineAnswer({ PUBLIC_CACHE: asKv(kv), TENANT_PRIVATE_CACHE: asKv(new MemoryKv()), EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()) }, parseQuery(`Top20 證據詳情 T00 ${data.generated_at}`));
    expect(Array.isArray(result)).toBe(true);
    if (!Array.isArray(result)) throw new Error("expected evidence messages");
    assertLineMessages(result);
    const body = result.map(m => m.type === "text" ? m.text : "").join("\n");
    for (const url of [...urls, ...data.records[0]!.future_order_source_urls]) expect(body).toContain(url);
    expect(body).toContain("完整研究必須補齊");
  });

  it("preserves all maximum-length fields in cards and complete text blocks without clipping", () => {
    const data = report();
    for (const row of data.records) {
      row.industry = "業".repeat(100); row.profit_summary = "利".repeat(120);
      row.current_orders = "訂".repeat(150); row.future_orders_estimate = "望".repeat(170);
      row.orders_confidence = "EVIDENCE_BOUND";
      row.current_order_source_urls = ["https://www.sec.gov/synthetic"];
      row.future_order_source_urls = ["https://www.sec.gov/synthetic"];
    }
    const parsed = parseV213Top20Report(data)!;
    const cards = buildV213Top20Messages(parsed);
    expect(inspectSevenFieldFlex(cards, parsed).values_match).toBe(true);
    expect(JSON.stringify(cards)).not.toMatch(/maxLines|height.*px/);
    const messages = buildV213Top20Messages(parsed, "bilingual", "text");
    expect(messages.length).toBeLessThanOrEqual(5);
    const all = messages.map(m => m.type === "text" ? m.text : "").join("\n");
    for (const row of data.records) {
      expect(all).toContain(`股票 / Ticker：${row.ticker}`);
      expect(all).toContain(row.profit_summary); expect(all).toContain(row.current_orders); expect(all).toContain(row.future_orders_estimate);
    }
    expect(all).toContain("Historical returns, not forecasts");
  });

  it("offers a complete explicit text fallback through the authorized LINE caller", async () => {
    const kv = new MemoryKv(); const data = report(); data.generated_at = new Date().toISOString();
    kv.values.set("v213:top20-report:latest", JSON.stringify(data));
    kv.values.set("last_successful_pipeline_timestamp", data.generated_at);
    const env = await freeRelayRequestEnv({ PUBLIC_CACHE: asKv(kv), TENANT_PRIVATE_CACHE: asKv(new MemoryKv()), EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()), LINE_CHANNEL_ACCESS_TOKEN: "SYNTHETIC_TOKEN", LINE_CHANNEL_SECRET: "SYNTHETIC_SECRET" } as any);
    const calls: any[] = [];
    vi.stubGlobal("fetch", vi.fn(async (_url, init) => { calls.push(JSON.parse(String(init.body))); return new Response("{}"); }));
    await processAuthorizedLineEvent(env, {} as ExecutionContext, { type: "message", replyToken: "SYNTHETIC_REPLY", source: { type: "user", userId: "SYNTHETIC_USER" }, message: { type: "text", text: "Top20 文字" }, timestamp: Date.now() }, "synthetic-text-tenant");
    expect(calls).toHaveLength(1);
    expect(calls[0].messages.every((m: any) => m.type === "text")).toBe(true);
    const text = calls[0].messages.map((m: any) => m.text).join("\n");
    expect((text.match(/股票 \/ Ticker：T\d\d/g) ?? []).length).toBe(20);
    expect((text.match(/未來訂單預估 \/ Future order outlook：/g) ?? []).length).toBe(20);
  });

  it("rejects oversized/invalid outbound payloads instead of silent truncation", () => {
    expect(() => assertLineMessages([])).toThrow();
    expect(() => assertLineMessages(Array(6).fill({ type: "text", text: "test" }))).toThrow();
    expect(() => assertLineMessages([{ type: "text", text: "x".repeat(4901) }])).toThrow();
    const cards = buildV213Top20Messages(parseV213Top20Report(report())!);
    const bad = structuredClone(cards) as any[];
    bad[0].contents.contents[0].body.contents.push({ type: "text", text: "大".repeat(15000) });
    expect(() => assertLineMessages(bad)).toThrow();
    const invalid = report(); invalid.records.pop();
    expect(() => buildV213Top20Messages(invalid as any)).toThrow("REPORT_INVALID");
  });

  it("does not fall back to five fields when the seven-field report is missing or stale", async () => {
    const kv = new MemoryKv(); const env = { PUBLIC_CACHE: asKv(kv) } as any;
    expect(await v213Top20ReportAnswer(env, parseQuery("Top20"))).toContain("no five-field fallback");
    kv.values.set("v213:top20-report:latest", JSON.stringify(report()));
    kv.values.set("last_successful_pipeline_timestamp", new Date().toISOString());
    expect(await v213Top20ReportAnswer(env, parseQuery("Top20"))).toContain("stale");
    expect(await v213Top20LineAnswer(env, parseQuery("Top20"))).toContain("stale");
    expect(await v213Top20ReportAnswer(env, parseQuery("什麼是自由現金流？"))).toBeNull();
  });

  it("production health truthfully advertises v213 and seven bilingual fields without reading storage", async () => {
    const env = new Proxy({}, { get(_target, key) { if (key === "V213_FIELD_LOCALE") return undefined; throw new Error("UNEXPECTED_HEALTH_STORAGE"); } });
    const response = await worker.fetch(new Request("https://synthetic.workers.dev/health"), env as any, {} as ExecutionContext);
    expect(await response.json()).toMatchObject({ product_version: "2.1.3", top20_presentation: "seven_fields", top20_field_locale: "bilingual" });
  });
});
