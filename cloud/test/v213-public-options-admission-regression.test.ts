import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import catalog from "../../config/public-options-provider-candidates.json";
import { processAuthorizedLineEvent } from "../src/v211/worker";
import { buildCoveredCallMessages, validateCoveredCallCycle } from "../src/v213/covered-call";
import { normalizeCompanyName } from "../src/v213/global-identity";
import { identityNameBucket } from "../src/v213/identity-shards";
import { loadDetailedOptionObservation } from "../src/v213/market-observations";
import { freeRelayRequestEnv } from "../src/v213/production-worker";
import { admitPublicOption, OPTION_RIGHTS_NOT_ADMITTED, OptionRightsNotAdmittedError } from "../src/v213/public-options-admission";
import { pinPublicSnapshot } from "../src/v213/public-snapshot";
import { SNAPSHOT_SEAL_KEY } from "../src/v213/snapshot-seal";
import { asKv, MemoryKv } from "./fake-kv";
import { sealUnboundReport } from "./sealed-report-migration";

// OPTIONS_TEST_POLICY1 policy regression: the REAL canonical catalog (config/public-options-provider-candidates.json) and the
// REAL admitPublicOption, with no mock anywhere in this file, at the actual loader, renderer and LINE direct/ADR callers.
// The reviewed policy is rights NONE: a structurally valid sealed covered-call row must never leak a strike, price or
// liquidity value. Synthetic in-memory snapshot and synthetic LINE credentials only; every non-LINE network call throws.
const RUN = "20260927T040000Z-abcdefabcde3";
const FIXED_NOW = new Date("2026-09-30T12:00:00.000Z").getTime();
const stamp = new Date(FIXED_NOW - 30 * 60_000).toISOString().replace(/\.\d{3}Z$/, "Z");
const expiry = new Date(FIXED_NOW + 21 * 86400_000).toISOString().slice(0, 10);
const weeklyExpiry = new Date(FIXED_NOW + 7 * 86400_000).toISOString().slice(0, 10);
const FEEDS = [{ id: "twse-listed", url: "https://openapi.twse.com.tw/v1/opendata/t187ap03_L", retrieved_at: stamp, sha256: "c".repeat(64), rows: 1 }];
const QUOTE_MARKERS = ["330.00", "$2.05", "OI 900", "成交量 50", "中價"];

const TSM_MONTHLY = {
  ticker: "TSM", strategy: "COVERED_CALL", expiry, dte: 21, spot: 300, currency: "USD", multiplier: 100, quote_basis: "delayed",
  timestamp: stamp, source: "Yahoo Finance option chain (unofficial, delayed)", provenance: "https://finance.yahoo.com/quote/TSM/options",
  rights_status: "unadmitted_third_party", suggestions: [{
    role: "HIGH_STRIKE", strike: 330, bid: 2.0, ask: 2.1, mid: 2.05, limit_price: 2.05,
    premium_per_contract: 205, period_yield: 2.05 / 300, annualized_yield: 2.05 / 300 * 365 / 21, upside_to_strike: 330 / 300 - 1,
    delta: 0.18, delta_basis: "QUOTED_IV", iv: 0.4, oi: 900, volume: 50, spread_pct: 0.0488,
  }],
};

async function sha(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
}

async function sealedEnv(style: "text" | "flex" = "text") {
  const kv = new MemoryKv();
  kv.values.set("v213:top20-report:latest", JSON.stringify({ synthetic: "report" }));
  kv.values.set("last_successful_pipeline_timestamp", new Date(FIXED_NOW - 60_000).toISOString().replace(/\.\d{3}Z$/, "Z"));
  await sealUnboundReport(kv, RUN);
  const shard = (bucket: string, rows: unknown[]) => ({ schema: "v213-identity-shard-v2", kind: "symbol", bucket, generated_at: stamp, feeds: FEEDS, rows });
  const nvdaMonthly = { ...structuredClone(TSM_MONTHLY), ticker: "NVDA" };
  const nvdaWeekly = { ...structuredClone(nvdaMonthly), dte: 7, expiry: weeklyExpiry };
  nvdaWeekly.suggestions[0]!.annualized_yield = nvdaWeekly.suggestions[0]!.limit_price / nvdaWeekly.spot * 365 / 7;
  const lazy: Record<string, unknown> = {
    "v213:identity:v2:sym:2": shard("2", [["2330", "TWSE", "TAIWAN", "Taiwan", "Taiwan Semiconductor Manufacturing", null, "COMMON_STOCK", "TWD", 0, ["台積電", "TWSE"]]]),
    "v213:identity:v2:sym:N": shard("N", [["NVDA", "NASDAQ", "US", "United States", "NVIDIA Corp", null, "COMMON_STOCK", "USD", 0, ["輝達", "ZHWIKI"]]]),
    "v213:quotes:v1": { schema: "v213-quotes-v1", generated_at: stamp, quotes: {
      "2330.TW": { symbol: "2330.TW", price: 1500, previous_close: 1490, change_pct: 0.0067, currency: "TWD", asof: stamp, source: "Yahoo Finance (unofficial, delayed)", source_url: "https://finance.yahoo.com/quote/2330.TW" },
    } },
    "v213:options:v2": { schema: "v213-options-v2", generated_at: stamp, options: {
      TSM: { monthly: structuredClone(TSM_MONTHLY) },
      NVDA: { weekly: nvdaWeekly, monthly: nvdaMonthly },
    } },
  };
  for (const [name, bucket, symbol, venue] of [[normalizeCompanyName("台積電"), "2", "2330", "TWSE"], [normalizeCompanyName("輝達"), "N", "NVDA", "NASDAQ"]]) {
    const key = `v213:identity:v2:name:${identityNameBucket(name!)}`;
    const doc = (lazy[key] ??= { schema: "v213-identity-shard-v2", kind: "name", bucket: String(identityNameBucket(name!)), generated_at: stamp, rows: [] }) as { rows: unknown[] };
    doc.rows.push([name, bucket, symbol, venue]);
  }
  const sealKey = `snapshot:${RUN}:${SNAPSHOT_SEAL_KEY}`;
  const seal = JSON.parse(kv.values.get(sealKey)!);
  for (const [key, value] of Object.entries(lazy)) {
    const body = JSON.stringify(value);
    const digest = await sha(body);
    seal.objects[key] = { sha256: digest, utf8_bytes: new TextEncoder().encode(body).byteLength };
    kv.values.set(`blob:v1:${digest}`, body);
  }
  const sealText = JSON.stringify(seal);
  kv.values.set(sealKey, sealText);
  const pointer = JSON.parse(kv.values.get("snapshot:current")!);
  pointer.seal_sha256 = await sha(sealText);
  kv.values.set("snapshot:current", JSON.stringify(pointer));
  return {
    PUBLIC_CACHE: asKv(kv), TENANT_PRIVATE_CACHE: asKv(new MemoryKv()), EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()),
    V21_TOP20_MAX_AGE_SECONDS: "7200", V213_LINE_PRESENTATION: style,
  };
}

async function actualReply(env: any, command: string) {
  let messages: any[] = [];
  const network = vi.fn(async (url: string, init: RequestInit) => {
    if (url !== "https://api.line.me/v2/bot/message/reply") throw new Error("NETWORK_FORBIDDEN");
    messages = JSON.parse(String(init.body)).messages;
    return new Response("{}", { status: 200 });
  });
  vi.stubGlobal("fetch", network);
  await processAuthorizedLineEvent(await freeRelayRequestEnv({
    ...env,
    LINE_CHANNEL_SECRET: "SYNTHETIC_NOT_REAL",
    LINE_CHANNEL_ACCESS_TOKEN: "SYNTHETIC_NOT_REAL",
    CURRENT_PUBLIC_DATA_ENABLED: "true",
  }), { waitUntil() { throw new Error("MODEL_JOB_FORBIDDEN"); } } as any,
  {
    type: "message", replyToken: "SYNTHETIC_REPLY", timestamp: FIXED_NOW,
    message: { id: "SYNTHETIC_MESSAGE", type: "text", text: command },
  }, "SYNTHETIC_TENANT");
  expect(network).toHaveBeenCalledTimes(1);
  return JSON.stringify(messages);
}

function expectDeniedWithoutQuote(reply: string): void {
  expect(reply).toContain(OPTION_RIGHTS_NOT_ADMITTED);
  for (const marker of QUOTE_MARKERS) expect(reply).not.toContain(marker);
}

const DENIED = { ok: false, reason: OPTION_RIGHTS_NOT_ADMITTED };
const providers = (catalog as unknown as { providers: Array<Record<string, unknown>> }).providers;

afterEach(() => vi.unstubAllGlobals());
beforeEach(() => { vi.setSystemTime(FIXED_NOW); });

describe("OPTIONS_TEST_POLICY1 real catalog: public options rights NONE", () => {
  it("uses the real, unmocked predicate and a catalog that selects and enables no provider", () => {
    expect(vi.isMockFunction(admitPublicOption)).toBe(false);
    expect((catalog as unknown as { production_quote_provider_selected: unknown }).production_quote_provider_selected).toBe(false);
    expect(providers.length).toBeGreaterThan(0);
    for (const provider of providers) expect(provider.runtime_enabled === true && provider.line_quote_eligible === true).toBe(false);
  });

  it("denies a structurally valid cycle whatever rights label or claimed identity the payload carries", () => {
    const cycle = validateCoveredCallCycle(structuredClone(TSM_MONTHLY), FIXED_NOW, stamp, "monthly");
    expect(cycle).not.toBeNull();
    expect(admitPublicOption(cycle, FIXED_NOW)).toEqual(DENIED);
    expect(admitPublicOption({ ...cycle, rights_status: "reviewed_public_access", admission_status: "ADMITTED" }, FIXED_NOW)).toEqual(DENIED);
    // Claims are join keys, never authority: neither any catalog provider id nor a synthetic one admits a row.
    const scope = { jurisdiction: "US", venue: "SYNTHETIC", instrument_kind: "equity_option", quote_basis: "delayed", publication_scope: "public_line_quote" };
    for (const id of [...providers.map(provider => String(provider.id)), "synthetic-test-only-not-in-catalog"]) {
      expect(admitPublicOption({ ...cycle, ...scope, provider_id: id }, FIXED_NOW)).toEqual(DENIED);
    }
  });

  it("the renderer refuses independently with the typed rights error in text and flex", () => {
    const cycle = validateCoveredCallCycle(structuredClone(TSM_MONTHLY), FIXED_NOW, stamp, "monthly");
    expect(cycle).not.toBeNull();
    expect(() => buildCoveredCallMessages(cycle!, "每月期權", "text")).toThrow(OptionRightsNotAdmittedError);
    expect(() => buildCoveredCallMessages(cycle!, "每月期權", "flex")).toThrow(OptionRightsNotAdmittedError);
  });

  it("the loader reports RIGHTS_NOT_ADMITTED for a valid sealed row and returns no quote", async () => {
    const detailed = await loadDetailedOptionObservation(await pinPublicSnapshot(await sealedEnv() as never), "TSM", "monthly", FIXED_NOW);
    expect(detailed.status).toBe("RIGHTS_NOT_ADMITTED");
    expect((detailed as { quote?: unknown }).quote).toBeUndefined();
  });

  for (const style of ["text", "flex"] as const) {
    it(`${style}: direct ticker and covered-call aliases show the rights denial and no quote value`, async () => {
      const env = await sealedEnv(style);
      for (const command of ["TSM 每月期權", "NVDA 期權指引", "NVDA covered call", "NVDA monthly covered call", "NVDA 每週期權"]) {
        expectDeniedWithoutQuote(await actualReply(env, command));
      }
    });

    it(`${style}: the TSMC -> TSM ADR route shows the rights denial and no quote value`, async () => {
      const env = await sealedEnv(style);
      for (const command of ["TSMC 每月期權", "台積電 每月期權"]) {
        expectDeniedWithoutQuote(await actualReply(env, command));
      }
    });
  }
});
