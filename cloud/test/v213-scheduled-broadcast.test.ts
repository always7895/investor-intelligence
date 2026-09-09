import { afterEach, describe, expect, it, vi } from "vitest";
import { deriveTenantId } from "../src/security";
import { asKv, MemoryKv } from "./fake-kv";
import { storeOwnerPairing } from "../src/v21/owner-storage";
import { broadcastV213Top20 } from "../src/v213/broadcast";
import { ingestV213Top20Report } from "../src/v213/admin";
import { formatV213Top20Report, parseV213Top20Report } from "../src/v213/top20-report";
import { V213BroadcastDedupe } from "../src/v213/broadcast-dedupe";
import productionWorker from "../src/v213/production-worker";
import { inspectSevenFieldFlex } from "./r75-line-presentation-proof";

const HASH_KEY = "SYNTHETIC_V213_HASH_KEY_NOT_REAL";
const DATA_KEY = "SYNTHETIC_V213_DATA_KEY_NOT_REAL";
const LINE_TARGET = String.fromCharCode(85) + "0".repeat(32);

function evidence(index: number) {
  return [{
    source_id: "sec_edgar",
    tier: "T0",
    claim_type: "xbrl_fact",
    title: `Synthetic SEC fact ${index}`,
    url: `https://www.sec.gov/Archives/edgar/data/${1000000 + index}/synthetic.htm`,
    as_of: "2026-08-31T00:00:00+00:00",
  }];
}

function top20() {
  const generated = new Date().toISOString();
  return Array.from({ length: 20 }, (_, index) => ({
    ticker: `T${String(index).padStart(2, "0")}`,
    name: `Synthetic ${index}`,
    serenity_score: 98 - index,
    serenity_raw_score: 98 - index,
    risk_penalty: 0,
    data_quality: 1,
    rating: "S",
    category: "Synthetic",
    serenity_factors: {
      demand_wave: 15, chokepoint: 13, pricing_power: 15,
      replacement_friction: 10, tam_capture: 15,
      valuation_expectations: 15, evidence_quality: 15,
    },
    risk_flags: [],
    aschenbrenner_overlay: {
      domain: "C",
      fit_score: 20,
      included_in_serenity_score: false,
      attribution: "system_operationalization_not_aschenbrenner_stock_score",
    },
    evidence: evidence(index),
    evidence_count: 1,
    source_count: 2,
    scoring_version: "serenity-first-v2.1.0",
    line_public_eligible: true,
    provider_scope: "public_only",
    owner_watchlist_inherited: false,
    rank: index + 1,
    generated_at: generated,
    as_of: "2026-08-31T00:00:00+00:00",
  }));
}

function report() {
  const generated = new Date().toISOString();
  return {
    schema_version: 2,
    product_version: "2.1.3",
    generated_at: generated,
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
      short_term_return_pct: 20 - index,
      industry: "半導體",
      profit_summary: "獲利；營收年增 +20.0%；營益率 15.0%；淨利率 10.0%",
      current_orders: "未揭露（無可靠公開訂單數字）",
      future_orders_estimate: "無可靠公開預估",
      long_term_window: "2y_cagr",
      short_term_window: "6m_price_return",
      market_source: "yfinance",
      profit_source: "sec_edgar",
      orders_as_of: "",
      orders_confidence: "UNAVAILABLE",
      current_order_source_urls: [],
      future_order_source_urls: [],
      numeric_total_order_estimate_prohibited: true,
      retrieved_at: generated,
      provider_scope: "public_only",
      owner_watchlist_inherited: false,
    })),
    provider_scope: "public_only",
    owner_watchlist_inherited: false,
  };
}

function fakeDedupeStub() {
  const values = new Map<string, unknown>();
  let chain = Promise.resolve();
  const state = {
    storage: {
      get: async (key: string) => values.get(key),
      put: async (key: string, value: unknown) => { values.set(key, value); },
      delete: async (key: string) => values.delete(key),
    },
  } as unknown as DurableObjectState;
  const instance = new V213BroadcastDedupe(state);
  const stub = {
    fetch: (input: RequestInfo | URL, init?: RequestInit) => {
      const request = input instanceof Request ? input : new Request(input, init);
      const result = chain.then(() => instance.fetch(request));
      chain = result.then(() => undefined, () => undefined);
      return result;
    },
  };
  return stub;
}

function fakeDedupeNamespace(): DurableObjectNamespace {
  const stubs = new Map<string, ReturnType<typeof fakeDedupeStub>>();
  return {
    idFromName: (name: string) => name,
    get: (id: string) => {
      if (!stubs.has(id)) stubs.set(id, fakeDedupeStub());
      return stubs.get(id)!;
    },
  } as unknown as DurableObjectNamespace;
}

function runtime(publicKv = new MemoryKv()) {
  const privateKv = new MemoryKv();
  const securityKv = new MemoryKv();
  const env = {
    PUBLIC_CACHE: asKv(publicKv),
    TENANT_PRIVATE_CACHE: asKv(privateKv),
    EPHEMERAL_SECURITY_CACHE: asKv(securityKv),
    TENANT_HASH_SECRET: HASH_KEY,
    TENANT_DATA_ENCRYPTION_KEY: DATA_KEY,
    LINE_CHANNEL_ACCESS_TOKEN: "SYNTHETIC_LINE_ACCESS_NOT_REAL",
    V21_SCHEDULED_PUSH_ENABLED: "true",
    V21_TOP20_MAX_AGE_SECONDS: "7200",
    V213_BROADCAST_DEDUPE: fakeDedupeNamespace(),
  };
  return { publicKv, privateKv, securityKv, env };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("v2.1.3 scheduled seven-field owner broadcast", () => {
  it.each(["0 0 * * *", "0 13 * * *"])("runs the actual Production scheduled entrypoint for %s with seven bilingual fields and dedupe", async cron => {
    const { publicKv, env } = runtime();
    const tenantId = await deriveTenantId({type:"user",userId:LINE_TARGET}, HASH_KEY);
    await storeOwnerPairing(env, tenantId, LINE_TARGET);
    publicKv.values.set("v21:top20:latest", JSON.stringify(top20()));
    publicKv.values.set("v213:top20-report:latest", JSON.stringify(report()));
    publicKv.values.set("last_successful_pipeline_timestamp", new Date().toISOString());
    const calls: any[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
      expect(String(url)).toBe("https://api.line.me/v2/bot/message/push");
      calls.push(JSON.parse(String(init.body)));
      return new Response("{}");
    }));
    const pending: Promise<unknown>[] = [];
    const ctx = {waitUntil(p: Promise<unknown>) {pending.push(p);}} as unknown as ExecutionContext;
    const controller = {cron, scheduledTime:Date.now()} as ScheduledController;
    await productionWorker.scheduled(controller, env as any, ctx);
    await Promise.all(pending);
    await productionWorker.scheduled(controller, env as any, ctx);
    await Promise.all(pending);
    expect(calls).toHaveLength(1);
    const proof = inspectSevenFieldFlex(calls[0].messages, parseV213Top20Report(report())!);
    expect(proof).toMatchObject({ rows: 20, fields: Array(21).fill(7), presentation: "flex_carousel", message_count: 4, values_match: true });
  });
  it("parses seven fields and exposes Chinese, English and bilingual labels", () => {
    const parsed = parseV213Top20Report(report());
    expect(parsed).not.toBeNull();
    expect(formatV213Top20Report(parsed!, "zh-TW")).toContain("公司現在訂單");
    expect(formatV213Top20Report(parsed!, "en")).toContain("Current orders");
    expect(formatV213Top20Report(parsed!, "bilingual")).toContain("公司現在訂單 / Current orders");
  });

  it("ingests only when the report order matches the promoted Top20", async () => {
    const { publicKv, env } = runtime();
    const runId = "20260901T122248Z-fccfd14d3c79";
    publicKv.values.set("snapshot:current", JSON.stringify({ run_id: runId }));
    publicKv.values.set(`snapshot:${runId}:v21:top20:latest`, JSON.stringify(top20()));
    const result = await ingestV213Top20Report(JSON.stringify(report()), env);
    expect(result.report_count).toBe(20);
    expect(publicKv.values.has(`snapshot:${runId}:v213:top20-report:latest`)).toBe(true);
  });

  it("sends all twenty seven-field cards in one request and deduplicates a scheduled slot", async () => {
    const { publicKv, env } = runtime();
    const tenantId = await deriveTenantId({ type: "user", userId: LINE_TARGET }, HASH_KEY);
    await storeOwnerPairing(env, tenantId, LINE_TARGET);
    const runId = "20260901T122248Z-fccfd14d3c79";
    const top = top20();
    const rep = report();
    publicKv.values.set("snapshot:current", JSON.stringify({ run_id: runId }));
    publicKv.values.set(`snapshot:${runId}:v21:top20:latest`, JSON.stringify(top));
    publicKv.values.set(`snapshot:${runId}:v213:top20-report:latest`, JSON.stringify(rep));
    publicKv.values.set(`snapshot:${runId}:last_successful_pipeline_timestamp`, new Date().toISOString());

    const calls: Array<Record<string, unknown>> = [];
    vi.stubGlobal("fetch", vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      calls.push(JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>);
      return new Response("{}", { status: 200 });
    }));

    expect((await broadcastV213Top20(env, "morning")).status).toBe("sent");
    expect((await broadcastV213Top20(env, "morning")).status).toBe("duplicate");
    expect(calls).toHaveLength(1);
    const messages = calls[0]?.messages as Array<Record<string, unknown>>;
    const proof = inspectSevenFieldFlex(messages, parseV213Top20Report(rep)!);
    expect(proof).toMatchObject({ rows: 20, fields: Array(21).fill(7), presentation: "flex_carousel", message_count: 4, values_match: true });
    expect(JSON.stringify(messages)).not.toContain("Serenity");
  });

  it("keeps payload and dedupe on one run when the pointer changes mid-read", async () => {
    class SwitchingKv extends MemoryKv {
      pointerReads = 0;
      override async get<T = string>(key: string, type?: "text" | "json"): Promise<T | string | null> {
        if (key === "snapshot:current") this.pointerReads++;
        const value = await super.get<T>(key, type);
        if (key === "snapshot:run-a:v21:top20:latest") this.values.set("snapshot:current", JSON.stringify({ run_id: "run-b" }));
        return value;
      }
    }
    const kv = new SwitchingKv();
    const { env } = runtime(kv);
    const tenantId = await deriveTenantId({ type: "user", userId: LINE_TARGET }, HASH_KEY);
    await storeOwnerPairing(env, tenantId, LINE_TARGET);
    kv.values.set("snapshot:current", JSON.stringify({ run_id: "run-a" }));
    for (const runId of ["run-a", "run-b"]) {
      const rep = report(); rep.records[0]!.industry = `合成 ${runId}`;
      expect(parseV213Top20Report(rep)).not.toBeNull();
      kv.values.set(`snapshot:${runId}:v21:top20:latest`, JSON.stringify(top20()));
      kv.values.set(`snapshot:${runId}:v213:top20-report:latest`, JSON.stringify(rep));
      kv.values.set(`snapshot:${runId}:last_successful_pipeline_timestamp`, new Date().toISOString());
    }
    const payloads: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      payloads.push(String(init?.body)); return new Response("{}");
    }));
    expect(await broadcastV213Top20(env, "morning")).toMatchObject({ status: "sent", run_id: "run-a" });
    expect(kv.pointerReads).toBe(1);
    expect(await broadcastV213Top20(env, "morning")).toMatchObject({ status: "sent", run_id: "run-b" });
    expect((await broadcastV213Top20(env, "morning")).status).toBe("duplicate");
    expect(payloads).toHaveLength(2);
    expect(payloads[0]).toContain("合成 run-a");
    expect(payloads[0]).not.toContain("合成 run-b");
    expect(payloads[1]).toContain("合成 run-b");
  });

  it.each(["{}", "", '{"run_id":""}'])("does not broadcast legacy keys behind an invalid pointer %s", async pointer => {
    const { publicKv, env } = runtime();
    const tenantId = await deriveTenantId({ type: "user", userId: LINE_TARGET }, HASH_KEY);
    await storeOwnerPairing(env, tenantId, LINE_TARGET);
    publicKv.values.set("snapshot:current", pointer);
    publicKv.values.set("v21:top20:latest", JSON.stringify(top20()));
    publicKv.values.set("v213:top20-report:latest", JSON.stringify(report()));
    publicKv.values.set("last_successful_pipeline_timestamp", new Date().toISOString());
    const send = vi.fn(async () => new Response("{}")); vi.stubGlobal("fetch", send);
    expect((await broadcastV213Top20(env, "morning")).status).toBe("top20_unavailable");
    expect(send).not.toHaveBeenCalled();
  });

  it("does not use a delayed cron's nominal clock to qualify stale data", async () => {
    const { publicKv, env } = runtime();
    const tenantId = await deriveTenantId({ type: "user", userId: LINE_TARGET }, HASH_KEY);
    await storeOwnerPairing(env, tenantId, LINE_TARGET);
    const nominal = Date.now() - 3 * 3600000;
    const stamp = new Date(nominal).toISOString();
    const top = top20(); top.forEach(row => { row.generated_at = stamp; });
    const rep = report(); rep.generated_at = stamp; rep.records.forEach(row => { row.retrieved_at = stamp; });
    publicKv.values.set("v21:top20:latest", JSON.stringify(top));
    publicKv.values.set("v213:top20-report:latest", JSON.stringify(rep));
    publicKv.values.set("last_successful_pipeline_timestamp", stamp);
    const send = vi.fn(async () => new Response("{}")); vi.stubGlobal("fetch", send);
    expect((await broadcastV213Top20(env, "morning", nominal)).status).toBe("stale");
    expect(send).not.toHaveBeenCalled();
  });

  it("does not substitute report generation for a missing pipeline success stamp", async () => {
    const { publicKv, env } = runtime();
    const tenantId = await deriveTenantId({ type: "user", userId: LINE_TARGET }, HASH_KEY);
    await storeOwnerPairing(env, tenantId, LINE_TARGET);
    publicKv.values.set("snapshot:current", JSON.stringify({ run_id: "run-a" }));
    publicKv.values.set("snapshot:run-a:v21:top20:latest", JSON.stringify(top20()));
    publicKv.values.set("snapshot:run-a:v213:top20-report:latest", JSON.stringify(report()));
    const send = vi.fn(async () => new Response("{}")); vi.stubGlobal("fetch", send);
    expect((await broadcastV213Top20(env, "morning")).status).toBe("stale");
    expect(send).not.toHaveBeenCalled();
    publicKv.values.set("snapshot:run-a:last_successful_pipeline_timestamp", new Date().toISOString());
    expect((await broadcastV213Top20(env, "morning")).status).toBe("sent");
    expect(send).toHaveBeenCalledTimes(1);
  });

  it("atomically sends exactly once under concurrent scheduled delivery", async () => {
    const { publicKv, env } = runtime();
    const tenantId = await deriveTenantId({ type: "user", userId: LINE_TARGET }, HASH_KEY);
    await storeOwnerPairing(env, tenantId, LINE_TARGET);
    const runId = "20260901T122248Z-fccfd14d3c79";
    publicKv.values.set("snapshot:current", JSON.stringify({ run_id: runId }));
    publicKv.values.set(`snapshot:${runId}:v21:top20:latest`, JSON.stringify(top20()));
    publicKv.values.set(`snapshot:${runId}:v213:top20-report:latest`, JSON.stringify(report()));
    publicKv.values.set(`snapshot:${runId}:last_successful_pipeline_timestamp`, new Date().toISOString());
    let sends = 0;
    vi.stubGlobal("fetch", vi.fn(async () => {
      sends += 1;
      await new Promise((resolve) => setTimeout(resolve, 20));
      return new Response("{}", { status: 200 });
    }));
    const results = await Promise.all([
      broadcastV213Top20(env, "morning"),
      broadcastV213Top20(env, "morning"),
    ]);
    expect(results.map((item) => item.status).sort()).toEqual(["in_progress", "sent"]);
    expect(sends).toBe(1);
  });

  it("fails closed when live Top20 order drifts", async () => {
    const { publicKv, env } = runtime();
    const tenantId = await deriveTenantId({ type: "user", userId: LINE_TARGET }, HASH_KEY);
    await storeOwnerPairing(env, tenantId, LINE_TARGET);
    const runId = "20260901T122248Z-fccfd14d3c79";
    const top = top20();
    [top[18], top[19]] = [top[19]!, top[18]!];
    top.forEach((item, index) => { item.rank = index + 1; item.serenity_score = 98 - index; item.serenity_raw_score = 98 - index; });
    publicKv.values.set("snapshot:current", JSON.stringify({ run_id: runId }));
    publicKv.values.set(`snapshot:${runId}:v21:top20:latest`, JSON.stringify(top));
    publicKv.values.set(`snapshot:${runId}:v213:top20-report:latest`, JSON.stringify(report()));
    publicKv.values.set(`snapshot:${runId}:last_successful_pipeline_timestamp`, new Date().toISOString());
    expect((await broadcastV213Top20(env, "morning")).status).toBe("top20_report_order_mismatch");
  });
});
