import { afterEach, describe, expect, it, vi } from "vitest";
import { createHash } from "node:crypto";
import worker, { freeRelayRequestEnv } from "../src/v213/production-worker";
import { processAuthorizedLineEvent } from "../src/v211/worker";
import { v213Top20ReportAnswer } from "../src/v213/top20-report";
import { parseQuery } from "../src/core";
import { buildV213Top20Messages, v213Top20LineAnswer } from "../src/v213/top20-presentation";
import { assertLineMessages } from "../src/line-messages";
import { inspectSevenFieldFlex } from "./r75-line-presentation-proof";
import { asKv, MemoryKv } from "./fake-kv";
import { sealUnboundReport } from "./sealed-report-migration";
import {
  formatV213Top20Report,
  loadV213FreshTop20Report,
  parseV213Top20Report,
  v213Top20DisplayValues,
  V213_NO_CURRENT_ORDERS,
  V213_NO_FUTURE_ORDER_ESTIMATE,
} from "../src/v213/top20-report";

function report() {
  return {
    schema_version: 2,
    product_version: "2.1.3",
    generated_at: "2026-09-01T00:00:00Z",
    freshness_policy: { policy_id: "v213-serenity-fresh-independent-evidence-v2", policy_sha256: "27ce461fae50218bb14e4d50ff283f6ed75b201e4a38d656643a5ed65d59c8d8" },
    evidence_capture_at: "2026-09-15T11:00:00Z",
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
      name: `Synthetic ${index}`,
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
      orders_state_as_of: "2026-09-01T00:00:00Z",
      evidence_class: "structural_claim",
      freshness_policy_key: "structural_claim_max_age_days",
      test_only_admission: true,
      provider_scope: "public_only",
      owner_watchlist_inherited: false,
    })),
    provider_scope: "public_only",
    owner_watchlist_inherited: false,
  };
}

function freshReport() {
  const data = report(); data.generated_at = new Date().toISOString();
  data.records.forEach(row => { row.retrieved_at = data.generated_at; });
  return data;
}

// Only the closed synthetic T00..T19 fixture vocabulary, not a real identity resolver.
function hasFixtureTickerToken(text: string, ticker: string): boolean {
  if (!/^T[0-9]{2}$/.test(ticker)) throw new Error("INVALID_SYNTHETIC_TICKER");
  return new RegExp(`\\b${ticker}\\b`).test(text);
}

async function evidenceCommand(env: Parameters<typeof v213Top20LineAnswer>[0]): Promise<string> {
  const cards = await v213Top20LineAnswer(env, parseQuery("Top20"));
  if (!Array.isArray(cards)) throw new Error("EXPECTED_BOUND_CARDS");
  return (cards[0] as any).contents.contents[0].footer.contents.find((item: any) => item.type === "button").action.text;
}

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });
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

  it.each([
    ["ticker", true], ["ticker", 2330], ["ticker", ["T00"]],
    ["generated_at", 0], ["generated_at", ["2026-09-09T00:00:00Z"]],
    ["retrieved_at", 0], ["retrieved_at", ["2026-09-09T00:00:00Z"]],
  ])("does not coerce %s identities or clocks from non-string values", (field, value) => {
    const data = report();
    if (field === "generated_at") (data as any)[field] = value;
    else (data.records[0] as any)[String(field)] = value;
    expect(parseV213Top20Report(data)).toBeNull();
  });

  it.each(["long_term_return_pct", "short_term_return_pct"] as const)("rejects impossible stock-price losses in %s", field => {
    const data = report(); data.records[0]![field] = -100.01;
    expect(parseV213Top20Report(data)).toBeNull();
    data.records[0]![field] = -100;
    expect(parseV213Top20Report(data)).not.toBeNull();
  });

  it("refuses delimiter injection in order summaries", () => {
    const bad = report();
    bad.records[0]!.current_orders = "A｜B";
    expect(parseV213Top20Report(bad)).toBeNull();
  });

  it.each([-3 * 3600_000, 6 * 60_000])("refuses stale/future rows in actual card/text replies with a fresh envelope (%s)", async offset => {
    const kv = new MemoryKv(); const data = freshReport();
    data.records[19]!.retrieved_at = new Date(Date.now() + offset).toISOString();
    // Stale direction must breach the evidence window itself (structural_claim
    // is 550d); retrieved_at is never the row freshness anchor. Future offset
    // stays retrieval-future only.
    if (offset < 0) data.records[19]!.orders_state_as_of = "2000-01-01T00:00:00Z";
    kv.values.set("v213:top20-report:latest", JSON.stringify(data));
    kv.values.set("last_successful_pipeline_timestamp", data.generated_at);
    await sealUnboundReport(kv);
    const env = await freeRelayRequestEnv({ PUBLIC_CACHE: asKv(kv), TENANT_PRIVATE_CACHE: asKv(new MemoryKv()), EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()), LINE_CHANNEL_ACCESS_TOKEN: "SYNTHETIC_TOKEN", LINE_CHANNEL_SECRET: "SYNTHETIC_SECRET" } as any);
    const messages: any[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url, init) => {
      expect(String(url)).toBe("https://api.line.me/v2/bot/message/reply");
      messages.push(...JSON.parse(String(init.body)).messages); return new Response("{}");
    }));
    for (const text of ["Top20", "Top20 文字"]) {
      messages.length = 0;
      await processAuthorizedLineEvent(env, {} as ExecutionContext, { type: "message", replyToken: "SYNTHETIC_REPLY", source: { type: "user", userId: "SYNTHETIC_USER" }, message: { type: "text", text }, timestamp: Date.now() }, "synthetic-stale-tenant");
      expect(messages).toHaveLength(1);
      expect(messages[0]).toMatchObject({ type: "text", text: expect.stringContaining("取得時間已過期") });
      expect(messages[0].text).not.toContain("Top20 證據詳情");
    }
    expect(await v213Top20ReportAnswer(env, parseQuery("Top20"))).toContain("取得時間已過期");
  });

  it("distinguishes synthetic identity tokens from ISO UTC01 timestamps", () => {
    const timestamp = "2026-09-25T01:00:00.000Z";
    expect(timestamp).toContain("T01");
    expect(hasFixtureTickerToken(timestamp, "T01")).toBe(false);
    for (const text of ["T01", "【T01｜深度化分析】", "公司代號 T01、名稱", "── 2/20 · T01｜原文：Synthetic 1 ──"]) {
      expect(hasFixtureTickerToken(text, "T01")).toBe(true);
    }
    expect(hasFixtureTickerToken("T010 AT01 T01A", "T01")).toBe(false);
    expect(() => hasFixtureTickerToken("T01", "T01|.*")).toThrow("INVALID_SYNTHETIC_TICKER");
  });

  it.each([0, 1, 12, 23])("routes the actual authorized LINE Top20 reply through all seven bilingual columns, never legacy five (UTC hour %i)", async hour => {
    // Synthetic Date-only regression fixture, not current Production freshness proof.
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(Date.UTC(2026, 8, 25, hour));
    const kv = new MemoryKv();
    const data = freshReport();
    kv.values.set("v213:top20-report:latest", JSON.stringify(data));
    kv.values.set("last_successful_pipeline_timestamp", data.generated_at);
    await sealUnboundReport(kv);
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
    const buttons = messages[0].contents.contents[0].footer.contents.filter((x: any) => x.type === "button");
    expect(buttons).toHaveLength(1);
    const command = buttons[0].action.text;
    expect(command).toContain("Top20 深度化分析 T00");
    const fullTextCommand = command.replace("深度化分析", "公司文字");
    expect(fullTextCommand).toContain("Top20 公司文字 T00");
    expect(JSON.stringify(messages)).toContain("6個月／1年／2年");
    expect(command).toContain("T00");
    expect(command).not.toBe("Top20 文字");
    messages.length = 0;
    await processAuthorizedLineEvent(env, ctx, { type: "message", replyToken: "SYNTHETIC_REPLY", source: { type: "user", userId: "SYNTHETIC_USER" }, message: { type: "text", text: command }, timestamp: Date.now() }, "synthetic-report-tenant");
    const detail = messages.map(x => x.text ?? "").join("\n");
    expect(detail).toContain("T00｜深度化分析");
    expect(detail).toContain(`原文公司名稱：${data.records[0]!.name}`);
    expect(detail).toContain("供應鏈瓶頸定位與價值鏈角色");
    expect(detail).toContain("未來結構性缺口");
    expect(detail).toContain("需求／供給／定價權分析");
    expect(detail).toContain("公司捕捉度與毛利槓桿");
    expect(detail).toContain("合約、訂單、資本支出、產能與客戶證據");
    expect(detail).toContain("6個月／1年／2年催化劑與情境分析");
    expect(detail).toContain("假說殺手與下檔風險");
    expect(detail).toContain("多軸證據信心與來源品質");
    expect(detail).toContain("候選排位說明與為何為第N名");
    expect(detail).toContain("明確未明與待查事項");
    for (const other of data.records.slice(1)) {
      expect(hasFixtureTickerToken(detail, other.ticker)).toBe(false);
    }
    expect(detail).toContain("https://www.sec.gov/example/current");
    expect(detail).not.toBe(formatV213Top20Report(parseV213Top20Report(data)!));
    assertLineMessages(messages);
    messages.length = 0;
    await processAuthorizedLineEvent(env, ctx, { type: "message", replyToken: "SYNTHETIC_REPLY", source: { type: "user", userId: "SYNTHETIC_USER" }, message: { type: "text", text: fullTextCommand }, timestamp: Date.now() }, "synthetic-report-tenant");
    const fullText = messages.map(x => x.text ?? "").join("\n");
    expect(fullText).toContain(data.records[0]!.name);
    for (const value of v213Top20DisplayValues(parseV213Top20Report(data)!.records[0]!)) expect(fullText).toContain(value);
    for (const other of data.records.slice(1)) {
      expect(hasFixtureTickerToken(fullText, other.ticker)).toBe(false);
    }
    expect(fullText).toContain("七欄摘要");
    expect(fullText).not.toBe(detail);
    assertLineMessages(messages);
  });

  it.each(["content", "representation", "run"])("rejects an actual old card click after same-date %s replacement", async mutation => {
    const kv = new MemoryKv();
    const data = freshReport();
    const raw = JSON.stringify(data);
    kv.values.set("snapshot:current", JSON.stringify({ run_id: "run-a" }));
    const save = (run: string, body: string) => {
      kv.values.set(`snapshot:${run}:v213:top20-report:latest`, body);
      kv.values.set(`snapshot:${run}:last_successful_pipeline_timestamp`, data.generated_at);
    };
    save("run-a", raw);
    const env = await freeRelayRequestEnv({ PUBLIC_CACHE: asKv(kv), TENANT_PRIVATE_CACHE: asKv(new MemoryKv()), EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()), LINE_CHANNEL_ACCESS_TOKEN: "SYNTHETIC_LINE_TOKEN_NOT_REAL", LINE_CHANNEL_SECRET: "SYNTHETIC_LINE_SECRET_NOT_REAL" } as any);
    const messages: any[] = [];
    vi.stubGlobal("fetch", vi.fn(async (_url, init) => {
      messages.push(...JSON.parse(String(init.body)).messages); return new Response("{}");
    }));
    const send = async (text: string) => {
      messages.length = 0;
      await processAuthorizedLineEvent(env, {} as ExecutionContext, { type: "message", replyToken: "SYNTHETIC_REPLY", source: { type: "user", userId: "SYNTHETIC_USER" }, message: { type: "text", text }, timestamp: Date.now() }, "synthetic-binding-tenant");
    };
    await send("Top20");
    const commands = messages[0].contents.contents[0].footer.contents.filter((item: any) => item.type === "button").map((item: any) => item.action.text);
    expect(commands).toHaveLength(1);
    for (const command of commands) expect(command).toContain(`s:run-a ${createHash("sha256").update(raw, "utf8").digest("hex")}`);
    if (mutation === "run") {
      save("run-b", raw); kv.values.set("snapshot:current", JSON.stringify({ run_id: "run-b" }));
    } else if (mutation === "representation") save("run-a", JSON.stringify(data, null, 2));
    else { data.records[0]!.industry = "合成異動內容"; save("run-a", JSON.stringify(data)); }
    for (const command of commands) {
      await send(command);
      expect(messages).toHaveLength(1);
      expect(messages[0].text).toContain("內容不符");
      expect(messages[0].text).not.toContain("合成異動內容");
    }
  });

  it("freezes admitted report objects and refuses malformed/oversized report text", async () => {
    const kv = new MemoryKv(); const data = report(); data.generated_at = new Date().toISOString();
    const env = { PUBLIC_CACHE: asKv(kv), TENANT_PRIVATE_CACHE: asKv(new MemoryKv()), EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()) };
    kv.values.set("last_successful_pipeline_timestamp", data.generated_at);
    kv.values.set("v213:top20-report:latest", JSON.stringify(data));
    await sealUnboundReport(kv);
    const loaded = await loadV213FreshTop20Report(env, parseQuery("Top20"));
    if (!loaded || typeof loaded === "string") throw new Error("EXPECTED_REPORT");
    expect(Object.isFrozen(loaded)).toBe(true);
    expect(Object.isFrozen(loaded.records[0]!.current_order_source_urls)).toBe(true);
    expect(() => { loaded.records[0]!.industry = "異動"; }).toThrow();
    for (const action of ["深度化分析", "證據詳情", "公司文字"]) {
      expect(await v213Top20LineAnswer(env, parseQuery(`Top20 ${action} T00 ${data.generated_at}`))).toContain("有效");
    }
    for (const raw of ["{broken", " ".repeat(2097153) + JSON.stringify(data)]) {
      kv.values.delete("snapshot:current");
      kv.values.set("v213:top20-report:latest", raw);
      expect(await v213Top20LineAnswer(env, parseQuery("Top20"))).toContain("未通過驗證");
    }
  });

  it.each(["證據詳情", "公司文字"])("refuses obsolete card generations, stale row retrievals and unknown companies (%s)", async action => {
    const data = freshReport();
    const kv = new MemoryKv();
    const env = { PUBLIC_CACHE: asKv(kv), TENANT_PRIVATE_CACHE: asKv(new MemoryKv()), EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()) };
    const save = async () => {
      kv.values.set("v213:top20-report:latest", JSON.stringify(data));
      kv.values.set("last_successful_pipeline_timestamp", data.generated_at);
      await sealUnboundReport(kv);
    };
    await save();
    const command = (await evidenceCommand(env)).replace("證據詳情", action);
    expect(await v213Top20LineAnswer(env, parseQuery(command.replace("T00 ", "ZZZZ ")))).toContain("不在本輪");
    data.records[0]!.retrieved_at = "2000-01-01T00:00:00Z"; data.records[0]!.orders_state_as_of = "2000-01-01T00:00:00Z"; // two-anchor staleness
    await save();
    // Under the two-anchor contract, row staleness outranks command-hash
    // matching: a command carrying an old row's reference is refused as stale,
    // not as a content mismatch.
    expect(await v213Top20LineAnswer(env, parseQuery(command))).toContain("取得時間已過期");
    expect(await v213Top20LineAnswer(env, parseQuery("Top20"))).toContain("取得時間已過期");
    // Even a correctly hashed manual reference cannot bypass row freshness.
    const staleRowCommand = command.replace(/[a-f0-9]{64}$/, createHash("sha256").update(JSON.stringify(data), "utf8").digest("hex"));
    expect(await v213Top20LineAnswer(env, parseQuery(staleRowCommand))).toContain("取得時間已過期");
    // Envelope-fresh-up also requires the staled row to be re-freshed on BOTH
    // anchors (freshReport binding pattern), else the report stays rejected as stale.
    const freshStamp = new Date(Date.now() + 1000).toISOString();
    data.generated_at = freshStamp;
    data.records[0]!.retrieved_at = freshStamp;
    data.records[0]!.orders_state_as_of = freshStamp;
    await save();
    expect(await v213Top20LineAnswer(env, parseQuery(command))).toContain("Top20 已更新");
  });

  it("does not combine a report with another run's fresh pipeline stamp", async () => {
    class SwitchingKv extends MemoryKv {
      pointerReads = 0;
      override async get<T = string>(key: string, type?: "text" | "json"): Promise<T | string | null> {
        if (key === "snapshot:current") this.pointerReads++;
        const value = await super.get<T>(key, type);
        if (key === "snapshot:run-a:v213:top20-report:latest") this.values.set("snapshot:current", JSON.stringify({ run_id: "run-b" }));
        return value;
      }
    }
    const data = report(); data.generated_at = new Date().toISOString();
    const kv = new SwitchingKv();
    kv.values.set("snapshot:current", JSON.stringify({ run_id: "run-a" }));
    kv.values.set("snapshot:run-a:v213:top20-report:latest", JSON.stringify(data));
    kv.values.set("snapshot:run-a:last_successful_pipeline_timestamp", new Date(Date.now() - 86400000).toISOString());
    kv.values.set("snapshot:run-b:last_successful_pipeline_timestamp", data.generated_at);
    const env = { PUBLIC_CACHE: asKv(kv), TENANT_PRIVATE_CACHE: asKv(new MemoryKv()), EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()) };
    expect(await v213Top20LineAnswer(env, parseQuery("Top20"))).toContain("已過期");
    expect(kv.pointerReads).toBe(1);
  });

  it("rejects credential-bearing citations instead of displaying them", async () => {
    const data = report(); data.generated_at = new Date().toISOString(); data.records[0]!.retrieved_at = data.generated_at;
    const kv = new MemoryKv(); kv.values.set("last_successful_pipeline_timestamp", data.generated_at);
    for (const url of ["https://fixture@example.com/report", "https://www.sec.gov/report?access%5Ftoken=fixture", "https://www.sec.gov/report#access_token=fixture"]) {
      data.records[0]!.current_order_source_urls = [url];
      kv.values.set("v213:top20-report:latest", JSON.stringify(data));
      expect(parseV213Top20Report(data)).toBeNull();
      const env = { PUBLIC_CACHE: asKv(kv), TENANT_PRIVATE_CACHE: asKv(new MemoryKv()), EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()) };
      for (const command of ["Top20", ...["證據詳情", "公司文字"].map(action => `Top20 ${action} T00 ${data.generated_at} legacy ${"0".repeat(64)}`)]) {
        const response = await v213Top20LineAnswer(env, parseQuery(command));
        expect(response).toContain("未通過驗證");
        expect(response).not.toContain(url);
      }
    }
  });

  it("keeps all long evidence citations within LINE message limits", async () => {
    const data = freshReport();
    const urls = Array.from({ length: 8 }, (_, i) => `https://issuer.example/${"x".repeat(900)}/${i}`);
    data.records[0]!.current_order_source_urls = urls;
    data.records[0]!.future_order_source_urls = urls.map(url => `${url}/future`);
    const kv = new MemoryKv(); kv.values.set("v213:top20-report:latest", JSON.stringify(data)); kv.values.set("last_successful_pipeline_timestamp", data.generated_at);
    await sealUnboundReport(kv);
    const env = { PUBLIC_CACHE: asKv(kv), TENANT_PRIVATE_CACHE: asKv(new MemoryKv()), EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()) };
    const result = await v213Top20LineAnswer(env, parseQuery(await evidenceCommand(env)));
    expect(Array.isArray(result)).toBe(true);
    if (!Array.isArray(result)) throw new Error("expected evidence messages");
    assertLineMessages(result);
    const body = result.map(m => m.type === "text" ? m.text : "").join("\n");
    for (const url of [...urls, ...data.records[0]!.future_order_source_urls]) expect(body).toContain(url);
    expect(body).toContain("完整研究必須補齊");
  });

  it("preserves all maximum-length fields in cards and complete text blocks without clipping", async () => {
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
    expect(JSON.stringify(cards)).toContain("Unbound detail reference");
    expect(JSON.stringify(cards)).not.toContain("Top20 證據詳情");
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
    data.generated_at = new Date().toISOString();
    data.records.forEach(row => { row.retrieved_at = data.generated_at; });
    const runId = "r".repeat(128);
    const kv = new MemoryKv();
    kv.values.set("snapshot:current", JSON.stringify({ run_id: runId }));
    kv.values.set(`snapshot:${runId}:v213:top20-report:latest`, JSON.stringify(data));
    kv.values.set(`snapshot:${runId}:last_successful_pipeline_timestamp`, data.generated_at);
    const env = { PUBLIC_CACHE: asKv(kv), TENANT_PRIVATE_CACHE: asKv(new MemoryKv()), EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()) };
    const bound = await v213Top20LineAnswer(env, parseQuery("Top20"));
    if (!Array.isArray(bound)) throw new Error("EXPECTED_BOUND_CARDS");
    assertLineMessages(bound);
    expect(JSON.stringify(bound)).toContain(`s:${runId}`);
    const command = await evidenceCommand(env);
    expect(command.length).toBeLessThanOrEqual(300);
    expect(Array.isArray(await v213Top20LineAnswer(env, parseQuery(command)))).toBe(true);
  });

  it("offers a complete explicit text fallback through the authorized LINE caller", async () => {
    const kv = new MemoryKv(); const data = freshReport();
    kv.values.set("v213:top20-report:latest", JSON.stringify(data));
    kv.values.set("last_successful_pipeline_timestamp", data.generated_at);
    await sealUnboundReport(kv);
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
    await sealUnboundReport(kv);
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
