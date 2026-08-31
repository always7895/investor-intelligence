import { afterEach, describe, expect, it, vi } from "vitest";
import { parseQuery } from "../src/core";
import { deriveTenantId } from "../src/security";
import { asKv, MemoryKv } from "./fake-kv";
import { authenticateV21AdminRequest, ingestV21PublicSnapshot } from "../src/v21/admin";
import { broadcastV21Top20 } from "../src/v21/broadcast";
import { getOwnerPushTarget, storeOwnerPairing } from "../src/v21/owner-storage";
import { parseV21Top20, v21Top20Answer } from "../src/v21/top20";

const HASH_KEY = "SYNTHETIC_V21_HASH_KEY_NOT_REAL";
const DATA_KEY = "SYNTHETIC_V21_DATA_KEY_NOT_REAL";
const SYNC_KEY = "SYNTHETIC_V21_SYNC_KEY_NOT_REAL_1234567890";
const LINE_TARGET = String.fromCharCode(85) + "0".repeat(32);

function evidence(index: number) {
  return [{
    source_id: "sec_edgar",
    tier: "T0",
    claim_type: "xbrl_fact",
    title: `Synthetic SEC fact T${String(index).padStart(2, "0")}`,
    url: `https://www.sec.gov/Archives/edgar/data/${1000000 + index}/synthetic.htm`,
    as_of: "2026-06-30T00:00:00+00:00",
  }];
}

function top20() {
  const generated = new Date().toISOString();
  return Array.from({ length: 20 }, (_, index) => ({
    ticker: `T${String(index).padStart(2, "0")}`,
    name: `Synthetic Company ${index}`,
    serenity_score: 98 - index,
    serenity_raw_score: 98 - index,
    risk_penalty: 0,
    data_quality: 1,
    rating: "S",
    category: "Synthetic",
    serenity_factors: {
      demand_wave: 15,
      chokepoint: 13,
      pricing_power: 15,
      replacement_friction: 10,
      tam_capture: 15,
      valuation_expectations: 15,
      evidence_quality: 15,
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
    as_of: "2026-06-30T00:00:00+00:00",
  }));
}

function top20Report() {
  return {
    schema_version: 1,
    product_version: "2.1.2",
    generated_at: new Date().toISOString(),
    display_columns: ["股票", "長期投資報酬率", "短期投資報酬率", "行業別", "獲利簡述"],
    long_term_definition: "trailing_2y_adjusted_close_cagr",
    short_term_definition: "trailing_6m_adjusted_close_price_return",
    records: Array.from({ length: 20 }, (_, index) => ({
      schema_version: 1,
      rank: index + 1,
      ticker: `T${String(index).padStart(2, "0")}`,
      long_term_return_pct: 40 - index,
      short_term_return_pct: 12 - index / 2,
      industry: "Synthetic Industry",
      profit_summary: "獲利；營收年增 +20.0%；營益率 15.0%；淨利率 10.0%",
      long_term_window: "2y_cagr",
      short_term_window: "6m_price_return",
      market_source: "yfinance",
      profit_source: "sec_edgar",
      retrieved_at: new Date().toISOString(),
      provider_scope: "public_only",
      owner_watchlist_inherited: false,
    })),
    provider_scope: "public_only",
    owner_watchlist_inherited: false,
  };
}

function runtime() {
  const publicKv = new MemoryKv();
  const privateKv = new MemoryKv();
  const securityKv = new MemoryKv();
  const env = {
    PUBLIC_CACHE: asKv(publicKv),
    TENANT_PRIVATE_CACHE: asKv(privateKv),
    EPHEMERAL_SECURITY_CACHE: asKv(securityKv),
    TENANT_HASH_SECRET: HASH_KEY,
    TENANT_DATA_ENCRYPTION_KEY: DATA_KEY,
    LINE_CHANNEL_SECRET: "SYNTHETIC_LINE_CHANNEL_KEY_NOT_REAL",
    LINE_CHANNEL_ACCESS_TOKEN: "SYNTHETIC_LINE_CHANNEL_ACCESS_NOT_REAL",
    V21_SYNC_HMAC_SECRET: SYNC_KEY,
    V21_SCHEDULED_PUSH_ENABLED: "true",
    V21_TOP20_MAX_AGE_SECONDS: "7200",
  };
  return { publicKv, privateKv, securityKv, env };
}

async function digest(text: string): Promise<string> {
  const value = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(value), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function signature(value: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(SYNC_KEY),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const result = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(value));
  return Array.from(new Uint8Array(result), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function envelope() {
  const rows = top20();
  const top20Json = JSON.stringify(rows);
  const sourcePlanJson = JSON.stringify({
    schema_version: 1,
    catalog_count: 99,
    automatic_activation: false,
    owner_watchlist_inherited: false,
    provider_scope: "public_only",
    line_public_eligible: true,
    inventory: {
      source_count: 99,
      runtime_enabled_count: 0,
      topic_counts: { positions: 1 },
    },
  });
  const report = [
    "<!-- line-public-eligible: true -->",
    "<!-- provider-scope: public_only -->",
    "<!-- owner-watchlist-inherited: false -->",
    "<!-- scoring-version: serenity-first-v2.1.0 -->",
    "# Synthetic public report",
    "evidence ".repeat(40),
  ].join("\n");
  return {
    schema_version: 1,
    run_id: "20260830T000000Z-0123456789ab",
    generated_at: new Date().toISOString(),
    public_data_as_of: new Date().toISOString(),
    payloads: { top20_json: top20Json, source_plan_json: sourcePlanJson, report_text: report },
    sha256: {
      top20_json: await digest(top20Json),
      source_plan_json: await digest(sourcePlanJson),
      report_text: await digest(report),
    },
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("v2.1 private owner LINE delivery", () => {
  it("accepts only an exact sorted Top 20 and answers ticker detail", async () => {
    const rows = top20();
    expect(parseV21Top20(rows)).toHaveLength(20);
    const { publicKv, env } = runtime();
    publicKv.values.set("snapshot:current", JSON.stringify({ run_id: "RUN" }));
    publicKv.values.set("snapshot:RUN:v21:top20:latest", JSON.stringify(rows));
    const answer = await v21Top20Answer(env, parseQuery("T00 評分"));
    expect(answer).toContain("#1 T00");
    expect(answer).toContain("Aschenbrenner");
  });

  it("encrypts the raw LINE push target in tenant-private KV", async () => {
    const { privateKv, publicKv, env } = runtime();
    const tenantId = await deriveTenantId({ type: "user", userId: LINE_TARGET }, HASH_KEY);
    await storeOwnerPairing(env, tenantId, LINE_TARGET);
    expect((await getOwnerPushTarget(env))?.lineUserId).toBe(LINE_TARGET);
    expect([...privateKv.values.values()].join("\n")).not.toContain(LINE_TARGET);
    expect([...publicKv.values.values()].join("\n")).not.toContain(LINE_TARGET);
  });

  it("authenticates one signed public snapshot and rejects nonce replay", async () => {
    const { publicKv, env } = runtime();
    const body = JSON.stringify(await envelope());
    const timestamp = String(Math.floor(Date.now() / 1000));
    const nonce = "a".repeat(32);
    const signed = await signature(`${timestamp}.${nonce}.${body}`);
    const makeRequest = () => new Request("https://example.test/v21/admin/public-snapshot", {
      method: "POST",
      headers: {
        "x-ii-v21-timestamp": timestamp,
        "x-ii-v21-nonce": nonce,
        "x-ii-v21-signature": signed,
      },
      body,
    });
    expect(await authenticateV21AdminRequest(makeRequest(), env)).toBe(body);
    await expect(authenticateV21AdminRequest(makeRequest(), env)).rejects.toThrow("V21_SYNC_REPLAY");
    const result = await ingestV21PublicSnapshot(body, env);
    expect(result.object_count).toBe(8);
    expect(publicKv.values.has("snapshot:current")).toBe(true);
  });

  it("fails closed on a future pipeline timestamp", async () => {
    const { publicKv, env } = runtime();
    const tenantId = await deriveTenantId({ type: "user", userId: LINE_TARGET }, HASH_KEY);
    await storeOwnerPairing(env, tenantId, LINE_TARGET);
    const runId = "20260830T000000Z-0123456789ab";
    publicKv.values.set("snapshot:current", JSON.stringify({ run_id: runId }));
    publicKv.values.set(`snapshot:${runId}:v21:top20:latest`, JSON.stringify(top20()));
    publicKv.values.set(`snapshot:${runId}:v212:top20-report:latest`, JSON.stringify(top20Report()));
    publicKv.values.set(
      `snapshot:${runId}:last_successful_pipeline_timestamp`,
      new Date(Date.now() + 10 * 60 * 1000).toISOString(),
    );
    expect((await broadcastV21Top20(env, "morning")).status).toBe("stale");
  });

  it("pushes exactly one five-field fresh scheduled message and deduplicates the slot", async () => {
    const { publicKv, env } = runtime();
    const tenantId = await deriveTenantId({ type: "user", userId: LINE_TARGET }, HASH_KEY);
    await storeOwnerPairing(env, tenantId, LINE_TARGET);
    const runId = "20260830T000000Z-0123456789ab";
    publicKv.values.set("snapshot:current", JSON.stringify({ run_id: runId }));
    publicKv.values.set(`snapshot:${runId}:v21:top20:latest`, JSON.stringify(top20()));
    publicKv.values.set(`snapshot:${runId}:v212:top20-report:latest`, JSON.stringify(top20Report()));
    publicKv.values.set(`snapshot:${runId}:last_successful_pipeline_timestamp`, new Date().toISOString());
    const calls: Array<Record<string, unknown>> = [];
    vi.stubGlobal("fetch", vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      calls.push(JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>);
      return new Response("{}", { status: 200 });
    }));
    expect((await broadcastV21Top20(env, "morning")).status).toBe("sent");
    expect((await broadcastV21Top20(env, "morning")).status).toBe("duplicate");
    expect(calls).toHaveLength(1);
    expect(String(calls[0]?.to ?? "")).toBe(LINE_TARGET);
    const body = JSON.stringify(calls[0]);
    expect(body).toContain("股票｜長期投資報酬率｜短期投資報酬率｜行業別｜獲利簡述");
    expect(body).not.toContain("Serenity");
    expect(body).not.toContain("Aschenbrenner");
  });
});
