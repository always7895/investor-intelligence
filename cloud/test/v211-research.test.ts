import { afterEach, describe, expect, it, vi } from "vitest";
import { freeRelayRequestEnv } from "../src/v213/production-worker";
import { processAuthorizedLineEvent, V211_GENERAL_QA } from "../src/v211/worker";
import { parseQuery } from "../src/core";
import type { StorageEnv } from "../src/storage";
import { humanizeFallback, parseV211ResearchUniverse, v211ResearchAnswer } from "../src/v211/research";
import { MemoryKv, asKv } from "./fake-kv";

function record(index: number) {
  const ticker = `T${String(index).padStart(2, "0")}`;
  return {
    ticker,
    name: `Company ${index}`,
    serenity_score: 100 - index,
    serenity_raw_score: 100 - index,
    risk_penalty: 0,
    data_quality: 0.9,
    rating: "A",
    category: index % 2 ? "Semiconductors" : "Communication Equipment",
    serenity_factors: {
      demand_wave: 15, chokepoint: 14, pricing_power: 13,
      replacement_friction: 9, tam_capture: 14,
      valuation_expectations: 13, evidence_quality: 12,
    },
    risk_flags: [],
    aschenbrenner_overlay: {
      domain: "C", fit_score: 60, included_in_serenity_score: false,
      attribution: "system_operationalization_not_aschenbrenner_stock_score",
    },
    evidence: [{
      source_id: "sec_edgar", tier: "T0", claim_type: "xbrl_fact",
      title: `SEC evidence ${ticker}`, url: `https://www.sec.gov/example/${ticker}`,
      as_of: "2026-08-31T00:00:00Z",
    }],
    evidence_count: 1,
    source_count: 2,
    scoring_version: "serenity-first-v2.1.0",
    line_public_eligible: true,
    provider_scope: "public_only",
    owner_watchlist_inherited: false,
    rank: index + 1,
    generated_at: "2026-08-31T00:00:00Z",
    as_of: "2026-08-31T00:00:00Z",
  } as const;
}

async function envWithUniverse(): Promise<StorageEnv> {
  const publicKv = new MemoryKv();
  await publicKv.put("snapshot:current", JSON.stringify({ run_id: "run-1" }));
  await publicKv.put(
    "snapshot:run-1:v211:universe:latest",
    JSON.stringify(Array.from({ length: 25 }, (_, index) => record(index))),
  );
  return {
    PUBLIC_CACHE: asKv(publicKv),
    TENANT_PRIVATE_CACHE: asKv(new MemoryKv()),
    EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()),
  };
}

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers(); });

describe("v2.1.3 signed-universe + attribution-safe local-research routing", () => {
  it.each([
    "宏觀產業分析",
    "分析 CPI 與 FOMC 對航運的影響",
    "分析利率變化對航運與能源的影響",
    "醫療產業的供需與監管風險",
    "比較農業與工業的成本傳導",
    "Serenity 如何分析非科技產業",
  ])("does not require or read a stock universe for %s", async text => {
    const kv = new MemoryKv();
    kv.values.set("snapshot:current", "malformed-pointer");
    const get = vi.spyOn(kv, "get");
    const env = { PUBLIC_CACHE: asKv(kv) } as StorageEnv;
    const query = parseQuery(text);
    expect(query.ticker).toBeNull();
    expect(await v211ResearchAnswer(env, query)).toBeNull();
    expect(get).not.toHaveBeenCalled();
  });

  it.each(["T20 我持有，分析部位", "T20 每週期權", "最新報告"])("leaves non-research intent %s to its own guarded handler", async text => {
    const kv = new MemoryKv();
    const get = vi.spyOn(kv, "get");
    expect(await v211ResearchAnswer({ PUBLIC_CACHE: asKv(kv) } as StorageEnv, parseQuery(text))).toBeNull();
    expect(get).not.toHaveBeenCalled();
  });

  it.each(["T20 怎麼看", "T20 vs T21 比較", "研究範圍"])("still rejects an unavailable stock universe for %s", async text => {
    const env = { PUBLIC_CACHE: asKv(new MemoryKv()) } as StorageEnv;
    expect(await v211ResearchAnswer(env, parseQuery(text))).toContain("沒有通過驗證");
  });

  it.each([
    ["SYNTHETIC_MACRO_RESPONSE", "SYNTHETIC_MACRO_RESPONSE"],
    ["LOCAL_MODEL_OFFLINE", "本機模型橋接目前離線"],
    ["CURRENT_DATA_UNAVAILABLE", "沒有通過 freshness / evidence gate"],
  ])("routes actual authorized LINE macro requests to QA and preserves %s", async (answer, expected) => {
    vi.useFakeTimers();
    const env = await freeRelayRequestEnv({
      PUBLIC_CACHE: asKv(new MemoryKv()), TENANT_PRIVATE_CACHE: asKv(new MemoryKv()),
      EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()), LINE_CHANNEL_ACCESS_TOKEN: "SYNTHETIC_NOT_REAL",
    } as any);
    const qa = vi.fn(async () => answer);
    env[V211_GENERAL_QA] = qa;
    const messages: any[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
      expect(String(url)).toBe("https://api.line.me/v2/bot/message/reply");
      messages.push(...JSON.parse(String(init.body)).messages);
      return new Response("{}");
    }));
    const ctx = { waitUntil() {}, passThroughOnException() {} } as unknown as ExecutionContext;
    await processAuthorizedLineEvent(env, ctx, { type: "message", replyToken: "SYNTHETIC_REPLY",
      source: { type: "user", userId: "SYNTHETIC_USER" }, message: { type: "text", text: "分析 CPI 與 FOMC 對航運的影響" }, timestamp: Date.now() }, "synthetic-macro-tenant");
    expect(qa).toHaveBeenCalledOnce();
    expect(qa).toHaveBeenCalledWith(env, expect.objectContaining({ intent: "general_qa", ticker: null }), expect.objectContaining({ chatType: "user" }));
    expect(messages).toHaveLength(1);
    expect(messages[0].text).toContain(expected);
    expect(messages[0].text).not.toContain("沒有通過驗證的公開系統量化 universe");
  });
  it("accepts a ranked research universe larger than Top 20", () => {
    const parsed = parseV211ResearchUniverse(Array.from({ length: 25 }, (_, index) => record(index)));
    expect(parsed).not.toBeNull();
    expect(parsed?.[20]?.rank).toBe(21);
  });

  it("accepts the R75 v2.1.3-diversified scoring universe", () => {
    const rows = Array.from({ length: 20 }, (_, index) => ({ ...record(index), scoring_version: "system-operationalization-v2.1.3-diversified" }));
    const parsed = parseV211ResearchUniverse(rows);
    expect(parsed).not.toBeNull();
    expect(parsed?.[0]?.ticker).toBe("T00");
  });

  it("serves ticker research from the sealed v21:top20:latest object", async () => {
    const publicKv = new MemoryKv();
    await publicKv.put("snapshot:current", JSON.stringify({ run_id: "run-1" }));
    const rows = Array.from({ length: 20 }, (_, index) => ({ ...record(index), scoring_version: "system-operationalization-v2.1.3-diversified" }));
    await publicKv.put("snapshot:run-1:v21:top20:latest", JSON.stringify(rows));
    const env = {
      PUBLIC_CACHE: asKv(publicKv),
      TENANT_PRIVATE_CACHE: asKv(new MemoryKv()),
      EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()),
    };
    const answer = await v211ResearchAnswer(env as StorageEnv, parseQuery("T00 怎麼看"));
    expect(answer).toContain("T00");
    expect(answer).toContain("#1/20");
    expect(answer).toContain("系統量化 Top 20");
  });

  it("answers greetings without exposing LOCAL_MODEL_NOT_CONFIGURED", async () => {
    const answer = await v211ResearchAnswer(await envWithUniverse(), parseQuery("你好"));
    expect(answer).toContain("公開研究問答");
    expect(answer).not.toContain("LOCAL_MODEL_NOT_CONFIGURED");
  });

  it("answers a ticker outside Top 20 from the scored universe with attribution-safe labels", async () => {
    const answer = await v211ResearchAnswer(await envWithUniverse(), parseQuery("T20 怎麼看"));
    expect(answer).toContain("T20");
    expect(answer).toContain("#21/25");
    expect(answer).toContain("未進系統量化 Top 20");
    expect(answer).toContain("系統量化分");
    expect(answer).toContain("不是 Serenity 本人公布的公式");
    expect(answer).not.toContain("Serenity-first universe");
  });

  it("compares two scored tickers without calling the project score a Serenity score", async () => {
    const answer = await v211ResearchAnswer(await envWithUniverse(), parseQuery("T20 vs T21 比較"));
    expect(answer).toContain("T20 vs T21");
    expect(answer).toContain("需求");
    expect(answer).toContain("估值");
    expect(answer).toContain("系統量化分");
    expect(answer).toContain("不是 Serenity 本人公布的分數或權重");
  });

  it("falls through an explicit ticker outside the signed universe", async () => {
    const answer = await v211ResearchAnswer(await envWithUniverse(), parseQuery("ZZZZ 怎麼看"));
    expect(answer).toBeNull();
  });

  it("falls through a comparison if either ticker is outside the signed universe", async () => {
    const answer = await v211ResearchAnswer(await envWithUniverse(), parseQuery("T20 vs ZZZZ 比較"));
    expect(answer).toBeNull();
  });

  it("does not intercept the options intent", async () => {
    const answer = await v211ResearchAnswer(await envWithUniverse(), parseQuery("T20 這週 sell call"));
    expect(answer).toBeNull();
  });

  it("humanizes raw availability codes", () => {
    expect(humanizeFallback("LOCAL_MODEL_NOT_CONFIGURED", parseQuery("任意問題"))).not.toContain("LOCAL_MODEL_NOT_CONFIGURED");
    expect(humanizeFallback("OPTION_DATA_UNAVAILABLE", parseQuery("T20 這週 sell call"))).toContain("T20");
  });
});
