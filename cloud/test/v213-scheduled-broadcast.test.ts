import { afterEach, describe, expect, it, vi } from "vitest";
import { deriveTenantId } from "../src/security";
import { createHmac } from "node:crypto";
import { asKv, MemoryKv } from "./fake-kv";
import { storeOwnerPairing } from "../src/v21/owner-storage";
import { broadcastV213Top20 } from "../src/v213/broadcast";
import { ingestV213Top20Report } from "../src/v213/admin";
import { formatV213Top20Report, parseV213Top20Report } from "../src/v213/top20-report";
import { memoryPushNamespace, syntheticPushPolicy, withPushPreflight } from "./line-push-fixture";
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
      orders_state_as_of: generated,
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

function fakeDedupeNamespace(failComplete = false): DurableObjectNamespace {
  return memoryPushNamespace({ failComplete }).namespace;
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
    LINE_FREE_PUSH_POLICY: syntheticPushPolicy(),
    V21_SCHEDULED_PUSH_ENABLED: "true",
    V21_TOP20_MAX_AGE_SECONDS: "7200",
    V213_BROADCAST_DEDUPE: fakeDedupeNamespace(),
  };
  return { publicKv, privateKv, securityKv, env };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("v2.1.3 scheduled seven-field owner broadcast", () => {
  it("blocks the actual manual push caller without a reviewed free plan before any LINE request", async () => {
    const { publicKv, env } = runtime();
    delete (env as any).LINE_FREE_PUSH_POLICY;
    const tenantId = await deriveTenantId({ type: "user", userId: LINE_TARGET }, HASH_KEY);
    await storeOwnerPairing(env, tenantId, LINE_TARGET);
    publicKv.values.set("v21:top20:latest", JSON.stringify(top20()));
    publicKv.values.set("v213:top20-report:latest", JSON.stringify(report()));
    publicKv.values.set("last_successful_pipeline_timestamp", new Date().toISOString());
    const send = vi.fn(async () => new Response("{}")); vi.stubGlobal("fetch", send);
    await expect(broadcastV213Top20(env, "test")).rejects.toThrow("LINE_FREE_PLAN_REVIEW_REQUIRED");
    expect(send).not.toHaveBeenCalled();
  });
  it("keeps both authenticated admin aliases inside the same free/manual attempt gate", async () => {
    const { publicKv, env } = runtime();
    const secret = "SYNTHETIC_PUSH_ADMIN_HMAC_NOT_REAL_123456";
    const e = { ...env, V21_SYNC_HMAC_SECRET: secret };
    const tenantId = await deriveTenantId({ type: "user", userId: LINE_TARGET }, HASH_KEY);
    await storeOwnerPairing(e, tenantId, LINE_TARGET);
    publicKv.values.set("v21:top20:latest", JSON.stringify(top20()));
    publicKv.values.set("v213:top20-report:latest", JSON.stringify(report()));
    publicKv.values.set("last_successful_pipeline_timestamp", new Date().toISOString());
    const post = vi.fn(async () => new Response("{}")); const network = withPushPreflight(post); vi.stubGlobal("fetch", network);
    const call = async (path: string, number: number) => {
      const stamp = String(Math.floor(Date.now() / 1000)); const nonce = String(number).padStart(32, "0");
      const signature = createHmac("sha256", secret).update(`${stamp}.${nonce}.{}`).digest("hex");
      return productionWorker.fetch(new Request(`https://synthetic.workers.dev${path}`, { method: "POST", body: "{}", headers: {
        "x-ii-v21-timestamp": stamp, "x-ii-v21-nonce": nonce, "x-ii-v21-signature": signature,
      } }), e as any, {} as ExecutionContext);
    };
    const approved = e.LINE_FREE_PUSH_POLICY; delete (e as any).LINE_FREE_PUSH_POLICY;
    expect(await (await call("/v213/admin/test-push", 1)).json()).toMatchObject({ ok: false, code: "LINE_FREE_PLAN_REVIEW_REQUIRED" });
    expect(network).not.toHaveBeenCalled();
    e.LINE_FREE_PUSH_POLICY = approved;
    expect(await (await call("/v213/admin/test-push", 2)).json()).toMatchObject({ status: "sent" });
    expect(await (await call("/v21/admin/test-push", 3)).json()).toMatchObject({ ok: false, code: "LINE_PUSH_ALREADY_ATTEMPTED" });
    expect(post).toHaveBeenCalledTimes(1);
  });

  it.each(["transport", "complete"])("does not replay an ambiguous %s outcome through the actual scheduled caller", async failure => {
    vi.useFakeTimers(); vi.setSystemTime(new Date("2026-09-10T04:00:00Z"));
    const { publicKv, env } = runtime();
    env.V213_BROADCAST_DEDUPE = fakeDedupeNamespace(failure === "complete");
    const tenantId = await deriveTenantId({ type: "user", userId: LINE_TARGET }, HASH_KEY);
    await storeOwnerPairing(env, tenantId, LINE_TARGET);
    publicKv.values.set("v21:top20:latest", JSON.stringify(top20()));
    publicKv.values.set("v213:top20-report:latest", JSON.stringify(report()));
    publicKv.values.set("last_successful_pipeline_timestamp", new Date().toISOString());
    const send = vi.fn(async () => {
      if (failure === "transport") throw new Error("SYNTHETIC_AMBIGUOUS_PUSH");
      return new Response("{}");
    });
    vi.stubGlobal("fetch", withPushPreflight(send));
    const run = async () => {
      const pending: Promise<unknown>[] = [];
      await productionWorker.scheduled({ cron: "0 0 * * *", scheduledTime: Date.now() } as ScheduledController,
        env as any, { waitUntil(p: Promise<unknown>) { pending.push(p); } } as unknown as ExecutionContext);
      return Promise.all(pending);
    };
    await expect(run()).rejects.toThrow(failure === "transport" ? "LINE_PUSH_TRANSPORT_UNCERTAIN" : "SYNTHETIC_COMPLETE_FAILED");
    await run();
    vi.setSystemTime(new Date(Date.now() + 11 * 60_000));
    await run();
    expect(send).toHaveBeenCalledTimes(1);
    expect(await broadcastV213Top20(env, "morning")).toMatchObject({ status: "delivery_unknown" });
  });

  it.each([-3 * 3600_000, 6 * 60_000])("blocks stale/future company retrievals despite fresh report and pipeline timestamps (%s)", async offset => {
    const { publicKv, env } = runtime();
    const tenantId = await deriveTenantId({ type: "user", userId: LINE_TARGET }, HASH_KEY);
    await storeOwnerPairing(env, tenantId, LINE_TARGET);
    const data = report(); data.records[19]!.retrieved_at = new Date(Date.now() + offset).toISOString();
    // Two-anchor contract: the stale direction must breach the source-state window
    // (structural_claim = 550d); retrieved_at alone only bounds future/seal drift.
    if (offset < 0) data.records[19]!.orders_state_as_of = "2000-01-01T00:00:00Z";
    publicKv.values.set("v21:top20:latest", JSON.stringify(top20()));
    publicKv.values.set("v213:top20-report:latest", JSON.stringify(data));
    publicKv.values.set("last_successful_pipeline_timestamp", new Date().toISOString());
    const send = vi.fn(async () => new Response("{}")); vi.stubGlobal("fetch", send);
    expect(await broadcastV213Top20(env, "morning")).toMatchObject({ status: "stale" });
    expect(send).not.toHaveBeenCalled();
  });
  it.each(["0 0 * * *", "0 13 * * *"])("runs the actual Production scheduled entrypoint for %s with seven bilingual fields and dedupe", async cron => {
    const { publicKv, env } = runtime();
    const tenantId = await deriveTenantId({type:"user",userId:LINE_TARGET}, HASH_KEY);
    await storeOwnerPairing(env, tenantId, LINE_TARGET);
    publicKv.values.set("v21:top20:latest", JSON.stringify(top20()));
    publicKv.values.set("v213:top20-report:latest", JSON.stringify(report()));
    publicKv.values.set("last_successful_pipeline_timestamp", new Date().toISOString());
    const calls: any[] = [];
    vi.stubGlobal("fetch", withPushPreflight(async (url: string, init: RequestInit) => {
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

  it("refuses the retained transaction-shaped unsealed fixture before LINE transport", async () => {
    const { publicKv, env } = runtime();
    await storeOwnerPairing(env, await deriveTenantId({ type: "user", userId: LINE_TARGET }, HASH_KEY), LINE_TARGET);
    const runId = "20260901T122248Z-fccfd14d3c79";
    publicKv.values.set("snapshot:current", JSON.stringify({ run_id: runId }));
    publicKv.values.set(`snapshot:${runId}:v21:top20:latest`, JSON.stringify(top20()));
    publicKv.values.set(`snapshot:${runId}:v213:top20-report:latest`, JSON.stringify(report()));
    publicKv.values.set(`snapshot:${runId}:last_successful_pipeline_timestamp`, new Date().toISOString());
    const send = vi.fn(async () => new Response("{}")); vi.stubGlobal("fetch", send);
    expect((await broadcastV213Top20(env, "morning")).status).toBe("top20_unavailable");
    expect(send).not.toHaveBeenCalled();
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

  it("retains twenty-card legacy unsealed presentation and mocked slot dedupe", async () => {
    const { publicKv, env } = runtime();
    const tenantId = await deriveTenantId({ type: "user", userId: LINE_TARGET }, HASH_KEY);
    await storeOwnerPairing(env, tenantId, LINE_TARGET);
    const runId = "legacy-synthetic-cards"; // Not current sealed admission; actual ingestion is covered separately.
    const top = top20();
    const rep = report();
    publicKv.values.set("snapshot:current", JSON.stringify({ run_id: runId }));
    publicKv.values.set(`snapshot:${runId}:v21:top20:latest`, JSON.stringify(top));
    publicKv.values.set(`snapshot:${runId}:v213:top20-report:latest`, JSON.stringify(rep));
    publicKv.values.set(`snapshot:${runId}:last_successful_pipeline_timestamp`, new Date().toISOString());

    const calls: Array<Record<string, unknown>> = [];
    vi.stubGlobal("fetch", withPushPreflight(async (_input: RequestInfo | URL, init?: RequestInit) => {
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
    // The bilingual push carries the admission disclosure on every card (it used to be added only for other locales).
    expect(JSON.stringify(messages).split("TEST-ONLY").length - 1).toBeGreaterThanOrEqual(20);
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
    vi.stubGlobal("fetch", withPushPreflight(async (_input: RequestInfo | URL, init?: RequestInit) => {
      payloads.push(String(init?.body)); return new Response("{}");
    }));
    expect(await broadcastV213Top20(env, "morning")).toMatchObject({ status: "sent", run_id: "run-a" });
    expect(kv.pointerReads).toBe(1);
    expect(await broadcastV213Top20(env, "evening")).toMatchObject({ status: "sent", run_id: "run-b" });
    expect((await broadcastV213Top20(env, "evening")).status).toBe("duplicate");
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
    const send = vi.fn(async () => new Response("{}")); vi.stubGlobal("fetch", withPushPreflight(send));
    expect((await broadcastV213Top20(env, "morning")).status).toBe("stale");
    expect(send).not.toHaveBeenCalled();
    publicKv.values.set("snapshot:run-a:last_successful_pipeline_timestamp", new Date().toISOString());
    expect((await broadcastV213Top20(env, "morning")).status).toBe("sent");
    expect(send).toHaveBeenCalledTimes(1);
  });

  it("reserves one mocked send under concurrent legacy unsealed scheduled calls", async () => {
    const { publicKv, env } = runtime();
    const tenantId = await deriveTenantId({ type: "user", userId: LINE_TARGET }, HASH_KEY);
    await storeOwnerPairing(env, tenantId, LINE_TARGET);
    const runId = "legacy-synthetic-concurrent"; // Not native DO or phone exactly-once proof.
    publicKv.values.set("snapshot:current", JSON.stringify({ run_id: runId }));
    publicKv.values.set(`snapshot:${runId}:v21:top20:latest`, JSON.stringify(top20()));
    publicKv.values.set(`snapshot:${runId}:v213:top20-report:latest`, JSON.stringify(report()));
    publicKv.values.set(`snapshot:${runId}:last_successful_pipeline_timestamp`, new Date().toISOString());
    let sends = 0;
    vi.stubGlobal("fetch", withPushPreflight(async () => {
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

  it("retains the order-mismatch guard for legacy unsealed fixtures", async () => {
    const { publicKv, env } = runtime();
    const tenantId = await deriveTenantId({ type: "user", userId: LINE_TARGET }, HASH_KEY);
    await storeOwnerPairing(env, tenantId, LINE_TARGET);
    const runId = "legacy-synthetic-order";
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
