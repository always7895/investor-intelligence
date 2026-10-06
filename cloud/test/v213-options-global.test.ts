import { readFileSync } from "node:fs";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { processAuthorizedLineEvent } from "../src/v211/worker";
import { freeRelayRequestEnv } from "../src/v213/production-worker";
import { pinPublicSnapshot } from "../src/v213/public-snapshot";
import { parseQuery } from "../src/core";
import { handleGlobalEquityLookup } from "../src/v213/global-equity-lookup";
import { normalizeCompanyName } from "../src/v213/global-identity";
import { identityNameBucket } from "../src/v213/identity-shards";
import { adrRoute } from "../src/v213/option-routes";
import { v213PublicLineAnswer } from "../src/v213/rich-menu";
import { SNAPSHOT_SEAL_KEY } from "../src/v213/snapshot-seal";
import { asKv, MemoryKv } from "./fake-kv";
import { sealUnboundReport } from "./sealed-report-migration";
import { loadDetailedOptionObservation } from "../src/v213/market-observations";
import * as admission from "../src/v213/public-options-admission";

// OPTIONS_TEST_POLICY1: the reviewed public-options policy is rights NONE (the real catalog admits no provider), so a sealed,
// format-valid covered-call row now renders OPTION_RIGHTS_NOT_ADMITTED instead of its quote; the former unconditional "330.00"
// expectations predate that policy. This file tests routing, identity/ADR mapping, freshness, validation and formatting, which
// are decided before (loader) or after (renderer) the rights decision, so it keeps ONE explicit test-only seam:
// admitPublicOption is partially mocked (the real OptionRightsNotAdmittedError class and constants are kept) and is reset to
// the REAL predicate before every test. Only a test that calls admitSyntheticTickers(...) admits exactly the named sealed
// tickers under a synthetic, non-catalog provider id; every other row still goes through the real catalog. No catalog or
// provider is changed. The real rights-NONE policy at the actual direct/ADR callers, with no mock at all, is tested in
// v213-public-options-admission-regression.test.ts.
vi.mock("../src/v213/public-options-admission", async importOriginal => {
  const real = await importOriginal<typeof import("../src/v213/public-options-admission")>();
  return { ...real, admitPublicOption: vi.fn(real.admitPublicOption) };
});
const realAdmission = await vi.importActual<typeof import("../src/v213/public-options-admission")>("../src/v213/public-options-admission");
const SYNTHETIC_PROVIDER_ID = "synthetic-test-only-not-in-catalog";
/** Per-test opt-in: admit only these sealed tickers (synthetic provider id); all other rows keep the real catalog decision. */
function admitSyntheticTickers(...tickers: string[]): void {
  const allowed = new Set(tickers);
  vi.mocked(admission.admitPublicOption).mockImplementation((subject: unknown, nowMs?: number) => {
    const ticker = typeof subject === "object" && subject !== null ? (subject as { ticker?: unknown }).ticker : undefined;
    return typeof ticker === "string" && allowed.has(ticker)
      ? { ok: true, provider_id: SYNTHETIC_PROVIDER_ID }
      : realAdmission.admitPublicOption(subject, nowMs);
  });
}

const RUN = "20260927T040000Z-abcdefabcde2";
const FIXED_NOW = new Date("2026-09-30T12:00:00.000Z").getTime();
const stamp = new Date(FIXED_NOW - 30 * 60_000).toISOString().replace(/\.\d{3}Z$/, "Z");
const expiry = new Date(FIXED_NOW + 21 * 86400_000).toISOString().slice(0, 10);
const FEEDS = [
  { id: "twse-listed", url: "https://openapi.twse.com.tw/v1/opendata/t187ap03_L", retrieved_at: stamp, sha256: "c".repeat(64), rows: 1 },
  { id: "lse-aim", url: "https://api.londonstockexchange.com/api/v1/components/refresh", retrieved_at: stamp, sha256: "d".repeat(64), rows: 1 },
];
const TSMC_NAME = normalizeCompanyName("台積電");

const NAMES: [string, string, string, string][] = [
  [TSMC_NAME, "2", "2330", "TWSE"],
  [normalizeCompanyName("輝達"), "N", "NVDA", "NASDAQ"],
  [normalizeCompanyName("合成瑞典"), "S", "SIVE", "Nasdaq Stockholm"],
  [normalizeCompanyName("阿斯特捷利康"), "A", "AZN", "NASDAQ"],
  [normalizeCompanyName("阿斯特捷利康"), "A", "AZN", "Nasdaq Stockholm"],
  [normalizeCompanyName("合成雙掛"), "D", "DUAL", "NASDAQ"],
  [normalizeCompanyName("合成雙掛"), "D", "DUAL", "Nasdaq Stockholm"],
];

async function sha(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
}

const TSM_MONTHLY = {
  ticker: "TSM", strategy: "COVERED_CALL", expiry, dte: 21, spot: 300, currency: "USD", multiplier: 100, quote_basis: "delayed",
  timestamp: stamp, source: "Yahoo Finance option chain (unofficial, delayed)", provenance: "https://finance.yahoo.com/quote/TSM/options",
  rights_status: "unadmitted_third_party", suggestions: [{
    role: "HIGH_STRIKE", strike: 330, bid: 2.0, ask: 2.1, mid: 2.05, limit_price: 2.05,
    premium_per_contract: 205, period_yield: 2.05 / 300, annualized_yield: 2.05 / 300 * 365 / 21, upside_to_strike: 330 / 300 - 1,
    delta: 0.18, delta_basis: "QUOTED_IV", iv: 0.4, oi: 900, volume: 50, spread_pct: 0.0488,
  }],
};

async function sealedEnv(mutate: (lazy: Record<string, any>) => void = () => {}, tamper = false, omitOptions = false, postSeal?: (kv: MemoryKv) => void) {
  const kv = new MemoryKv();
  kv.values.set("v213:top20-report:latest", JSON.stringify({ synthetic: "report" }));
  kv.values.set("last_successful_pipeline_timestamp", new Date(FIXED_NOW - 60_000).toISOString().replace(/\.\d{3}Z$/, "Z"));
  await sealUnboundReport(kv, RUN);
  const shard = (bucket: string, rows: unknown[]) => ({ schema: "v213-identity-shard-v2", kind: "symbol", bucket, generated_at: stamp, feeds: FEEDS, rows });
  const lazy: Record<string, unknown> = {
    "v213:identity:v2:sym:2": shard("2", [["2330", "TWSE", "TAIWAN", "Taiwan", "Taiwan Semiconductor Manufacturing", null, "COMMON_STOCK", "TWD", 0, ["台積電", "TWSE"]]]),
    "v213:identity:v2:sym:I": shard("I", [["IQE", "LSE AIM", "UK", "United Kingdom", "IQE PLC", null, "COMMON_STOCK", "GBX", 1]]),
    "v213:identity:v2:sym:A": shard("A", [
      ["AZN", "NASDAQ", "US", "United States", "AstraZeneca PLC ADS", null, "ADR", "USD", 0, ["阿斯特捷利康", "ZHWIKI"]],
      ["AZN", "Nasdaq Stockholm", "SWEDEN", "Sweden", "AstraZeneca PLC", null, "COMMON_STOCK", "SEK", 0, ["阿斯特捷利康", "ZHWIKI"]],
    ]),
    "v213:identity:v2:sym:D": shard("D", [
      ["DUAL", "NASDAQ", "US", "United States", "Synthetic Dual Corp", null, "COMMON_STOCK", "USD", 0, ["合成雙掛", "ZHWIKI"]],
      ["DUAL", "Nasdaq Stockholm", "SWEDEN", "Sweden", "Synthetic Dual AB", null, "COMMON_STOCK", "SEK", 0, ["合成雙掛", "ZHWIKI"]],
    ]),
    "v213:identity:v2:sym:N": shard("N", [["NVDA", "NASDAQ", "US", "United States", "NVIDIA Corp", null, "COMMON_STOCK", "USD", 0, ["輝達", "ZHWIKI"]]]),
    "v213:identity:v2:sym:S": shard("S", [["SIVE", "Nasdaq Stockholm", "SWEDEN", "Sweden", "Sivers Semiconductors AB", null, "COMMON_STOCK", "SEK", 0, ["合成瑞典", "ZHWIKI"]]]),
    "v213:identity:v2:sym:V": shard("V", [["VOLV B", "Nasdaq Stockholm", "SWEDEN", "Sweden", "Volvo AB ser. B", null, "COMMON_STOCK", "SEK", 0]]),
    "v213:quotes:v1": { schema: "v213-quotes-v1", generated_at: stamp, quotes: {
      "2330.TW": { symbol: "2330.TW", price: 1500, previous_close: 1490, change_pct: 0.0067, currency: "TWD", asof: stamp, source: "Yahoo Finance (unofficial, delayed)", source_url: "https://finance.yahoo.com/quote/2330.TW" },
      "IQE.L": { symbol: "IQE.L", price: 15, previous_close: 15, change_pct: 0, currency: "GBp", asof: stamp, source: "Yahoo Finance (unofficial, delayed)", source_url: "https://finance.yahoo.com/quote/IQE.L" },
    } },
  };

  if (!omitOptions) {
    lazy["v213:options:v2"] = {
      schema: "v213-options-v2", generated_at: stamp, options: {
        TSM: { weekly: { unavailable: "合成：TSM 本週無雙邊報價" }, monthly: structuredClone(TSM_MONTHLY) },
        NVDA: { monthly: { unavailable: "合成：NVDA 本月鏈缺漏" } },
        "NVDA.ST": { monthly: { unavailable: "錯誤市場：不應顯示" } },
        "SIVE.ST": { monthly: { unavailable: "合成：SIVE.ST 本月鏈缺漏" } },
        "VOLV-B.ST": { weekly: { unavailable: "合成：VOLV-B.ST 本週無報價" } },
      },
    };
  }

  for (const [name, bucket, symbol, venue] of NAMES) {
    const key = `v213:identity:v2:name:${identityNameBucket(name)}`;
    const doc = (lazy[key] ??= { schema: "v213-identity-shard-v2", kind: "name", bucket: String(identityNameBucket(name)), generated_at: stamp, rows: [] }) as { rows: unknown[] };
    doc.rows.push([name, bucket, symbol, venue]);
  }
  mutate(lazy);
  const sealKey = `snapshot:${RUN}:${SNAPSHOT_SEAL_KEY}`;
  const seal = JSON.parse(kv.values.get(sealKey)!);
  for (const [key, value] of Object.entries(lazy)) {
    // A string value is an exact pre-emitted body (real Python publisher output from the bridge fixture): seal it
    // verbatim, never re-encode it, so the Worker consumes the identical bytes the producer wrote.
    const body = typeof value === "string" ? value : JSON.stringify(value);
    const digest = await sha(body);
    seal.objects[key] = { sha256: digest, utf8_bytes: new TextEncoder().encode(body).byteLength };
    kv.values.set(`blob:v1:${digest}`, tamper && key === "v213:options:v2" ? body + " " : body);
  }
  const sealText = JSON.stringify(seal);
  kv.values.set(sealKey, sealText);
  const pointer = JSON.parse(kv.values.get("snapshot:current")!);
  pointer.seal_sha256 = await sha(sealText);
  kv.values.set("snapshot:current", JSON.stringify(pointer));
  postSeal?.(kv);
  return {
    PUBLIC_CACHE: asKv(kv), TENANT_PRIVATE_CACHE: asKv(new MemoryKv()), EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()),
    V21_TOP20_MAX_AGE_SECONDS: "7200", V213_LINE_PRESENTATION: "text",
  };
}

afterEach(() => vi.unstubAllGlobals());
beforeEach(() => {
  vi.setSystemTime(FIXED_NOW);
  // Reset the admission seam to the REAL predicate before every test; positive admission is a per-test opt-in only.
  vi.mocked(admission.admitPublicOption).mockImplementation(realAdmission.admitPublicOption);
});

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

describe("OPTIONS-GLOBAL-01 acceptance regression tests", () => {
  it("F2 present option document + absent ticker must say TICKER_NOT_IN_SNAPSHOT, not document absent", async () => {
    const env = await sealedEnv();
    const doc = await (await pinPublicSnapshot(env as never)).json<any>(["v213:options:v2"]);
    expect(doc.options.TSM).toBeDefined();
    const reply = await actualReply(env, "ZZZZ 每月期權");
    expect(reply).not.toContain("OPTION_DATA_NOT_ADMITTED");
    expect(reply).toContain("本輪封存快照未包含 ZZZZ 之期權觀察");
  });

  for (const command of ["NVDA 期權指引", "NVDA 選擇權推薦", "NVDA covered call", "NVDA 每月期權指引", "NVDA monthly covered call"]) {
    it(`${command} reaches existing sealed covered-call observation`, async () => {
      admitSyntheticTickers("NVDA"); // routing/formatting check; rights NONE is asserted below and in the regression file
      const env = await sealedEnv(lazy => {
        const monthly = { ...structuredClone(TSM_MONTHLY), ticker: "NVDA" };
        const weekly = { ...structuredClone(monthly), dte: 7, expiry: new Date(FIXED_NOW + 7 * 86400000).toISOString().slice(0, 10) };
        weekly.suggestions[0]!.annualized_yield = weekly.suggestions[0]!.limit_price / weekly.spot * 365 / 7;
        lazy["v213:options:v2"].options.NVDA = { weekly, monthly };
      });
      const reply = await actualReply(env, command);
      expect(reply).toContain("330.00");
      expect(reply).toContain("擷取時間");
      expect(reply).toContain("來源報價時間未提供");
    });
  }

  it("without the opt-in the same aliases reach the real rights-NONE denial and show no quote", async () => {
    const env = await sealedEnv(lazy => {
      const monthly = { ...structuredClone(TSM_MONTHLY), ticker: "NVDA" };
      const weekly = { ...structuredClone(monthly), dte: 7, expiry: new Date(FIXED_NOW + 7 * 86400000).toISOString().slice(0, 10) };
      weekly.suggestions[0]!.annualized_yield = weekly.suggestions[0]!.limit_price / weekly.spot * 365 / 7;
      lazy["v213:options:v2"].options.NVDA = { weekly, monthly };
    });
    for (const command of ["NVDA 期權指引", "NVDA 選擇權推薦", "NVDA covered call", "NVDA 每月期權指引", "NVDA monthly covered call"]) {
      const reply = await actualReply(env, command);
      expect(reply).toContain("OPTION_RIGHTS_NOT_ADMITTED");
      expect(reply).not.toContain("330.00");
      expect(reply).not.toContain("$2.05");
    }
  });

  it("stale row timestamp in fresh document rejects numeric suggestion", async () => {
    admitSyntheticTickers("TSM"); // the rejection must come from validation, not from rights
    const env = await sealedEnv(lazy => {
      lazy["v213:options:v2"].options.TSM.monthly.timestamp = "2020-01-01T00:00:00Z";
    });
    const reply = await actualReply(env, "TSMC 每月期權");
    expect(reply).not.toContain("330.00");
    expect(reply).toContain("封存之期權觀察未通過驗證");
  });

  it("invalid row timestamp rejects numeric suggestion", async () => {
    admitSyntheticTickers("TSM");
    const env = await sealedEnv(lazy => {
      lazy["v213:options:v2"].options.TSM.monthly.timestamp = "not-a-time";
    });
    const reply = await actualReply(env, "TSMC 每月期權");
    expect(reply).not.toContain("330.00");
    expect(reply).toContain("封存之期權觀察未通過驗證");
  });

  it("future row timestamp beyond 5min tolerance rejects numeric suggestion", async () => {
    admitSyntheticTickers("TSM");
    const futureStamp = new Date(FIXED_NOW + 600_000).toISOString().replace(/\.\d{3}Z$/, "Z");
    const env = await sealedEnv(lazy => {
      lazy["v213:options:v2"].options.TSM.monthly.timestamp = futureStamp;
    });
    const reply = await actualReply(env, "TSMC 每月期權");
    expect(reply).not.toContain("330.00");
    expect(reply).toContain("封存之期權觀察未通過驗證");
  });

  it("text mode and trailing punctuation work on covered call aliases", async () => {
    admitSyntheticTickers("NVDA");
    const env = await sealedEnv(lazy => {
      const monthly = { ...structuredClone(TSM_MONTHLY), ticker: "NVDA" };
      const weekly = { ...structuredClone(monthly), dte: 7, expiry: new Date(FIXED_NOW + 7 * 86400000).toISOString().slice(0, 10) };
      weekly.suggestions[0]!.annualized_yield = weekly.suggestions[0]!.limit_price / weekly.spot * 365 / 7;
      lazy["v213:options:v2"].options.NVDA = { weekly, monthly };
    });
    const reply = await actualReply(env, "NVDA covered call 文字！");
    expect(reply).toContain("330.00");
    expect(reply).toContain("【備兌買權建議｜NVDA");
  });

  it("alias-only input without ticker gives syntax help", async () => {
    const env = await sealedEnv();
    for (const cmd of ["covered call", "期權指引", "選擇權推薦", "每月期權指引"]) {
      const reply = await actualReply(env, cmd);
      expect(reply).toContain("期權指引指令說明");
      expect(reply).toContain("NVDA covered call");
      expect(reply).not.toContain("330.00");
    }
  });

  it("unsupported strategy gives explicit educational help, not covered call", async () => {
    const env = await sealedEnv();
    for (const cmd of ["NVDA put", "NVDA 賣權", "NVDA spread", "NVDA csp"]) {
      const reply = await actualReply(env, cmd);
      expect(reply).toContain("策略尚未支援");
      expect(reply).toContain("僅提供備兌買權");
      expect(reply).toContain("期權教學");
      expect(reply).not.toContain("330.00");
    }
  });

  it("differentiates all Section C failure states", async () => {
    // 1. SNAPSHOT_UNAVAILABLE
    const unsealedEnv = { PUBLIC_CACHE: asKv(new MemoryKv()), TENANT_PRIVATE_CACHE: asKv(new MemoryKv()), EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()), V213_LINE_PRESENTATION: "text" };
    expect(await actualReply(unsealedEnv, "TSM 每月期權")).toContain("OPTION_DATA_UNAVAILABLE");

    // 2. DOCUMENT_ABSENT
    const absentDocEnv = await sealedEnv(() => {}, false, true);
    expect(await actualReply(absentDocEnv, "TSM 每月期權")).toContain("OPTION_DATA_NOT_ADMITTED");

    // 3. DOCUMENT_INVALID_OR_UNREADABLE (tampered blob)
    const tamperedEnv = await sealedEnv(() => {}, true);
    const tamperedReply = await actualReply(tamperedEnv, "TSM 每月期權");
    expect(tamperedReply).toContain("無法驗證或讀取");
    expect(tamperedReply).not.toContain("OPTION_DATA_NOT_ADMITTED");

    // 4. DOCUMENT_STALE (> 6h)
    const staleDocEnv = await sealedEnv(lazy => {
      lazy["v213:options:v2"].generated_at = "2020-01-01T00:00:00Z";
    });
    const staleReply = await actualReply(staleDocEnv, "TSM 每月期權");
    expect(staleReply).toContain("期權快照已逾時");

    // 5. TICKER_NOT_IN_SNAPSHOT
    const normalEnv = await sealedEnv();
    const missingTickerReply = await actualReply(normalEnv, "AAPL 每月期權");
    expect(missingTickerReply).toContain("本輪封存快照未包含 AAPL 之期權觀察");

    // 6. PERIOD_UNAVAILABLE
    const missingPeriodReply = await actualReply(normalEnv, "TSMC 每週期權");
    expect(missingPeriodReply).toContain("本週無雙邊報價");
  });

  it("ADR and identity mapping integrity", async () => {
    admitSyntheticTickers("TSM"); // ADR route/note formatting; the real ADR denial is in the regression file
    const env = await sealedEnv();
    // TSMC -> TSM ADR note
    const tsmcReply = await actualReply(env, "TSMC 每月期權");
    expect(tsmcReply).toContain("以其美國 ADR TSM（1 ADR＝5 股普通股）");
    expect(tsmcReply).toContain("330.00");

    // Direct TSM -> No ADR note
    const directReply = await actualReply(env, "TSM 每月期權");
    expect(directReply).not.toContain("台積電為台股掛牌");
    expect(directReply).toContain("330.00");

    // IQE -> Unsupported market
    const iqeReply = await actualReply(env, "IQE 每月期權");
    expect(iqeReply).toContain("尚未採用此市場");

    // Ambiguous dual listing
    const dualReply = await actualReply(env, "合成雙掛 每月期權");
    expect(dualReply).toContain("此名稱對應多個掛牌");
  });

  it("B1: Worker rejects expired, DTE-inconsistent and impossible-calendar expiries on a digest-valid row", async () => {
    admitSyntheticTickers("TSM");
    const mutations: ((lazy: any) => void)[] = [
      lazy => { lazy["v213:options:v2"].options.TSM.monthly.expiry = new Date(FIXED_NOW - 86400000).toISOString().slice(0, 10); },
      lazy => { lazy["v213:options:v2"].options.TSM.monthly.expiry = new Date(FIXED_NOW + 7 * 86400000).toISOString().slice(0, 10); },
      lazy => { lazy["v213:options:v2"].options.TSM.monthly.expiry = "2026-02-30"; },
    ];
    for (const mutate of mutations) {
      const reply = await actualReply(await sealedEnv(mutate), "TSM 每月期權");
      expect(reply).not.toContain("330.00");
      expect(reply).toContain("封存之期權觀察未通過驗證");
    }
    expect(await actualReply(await sealedEnv(), "TSM 每月期權")).toContain("330.00");
  });

  it("B2: Worker rejects a DTE outside the requested weekly/monthly bucket in both directions", async () => {
    admitSyntheticTickers("TSM", "NVDA");
    const weeklyReply = await actualReply(await sealedEnv(lazy => {
      lazy["v213:options:v2"].options.TSM.weekly = structuredClone(TSM_MONTHLY);
    }), "TSM 每週期權");
    expect(weeklyReply).not.toContain("330.00");
    expect(weeklyReply).toContain("封存之期權觀察未通過驗證");

    const monthlyReply = await actualReply(await sealedEnv(lazy => {
      const cycle = structuredClone(TSM_MONTHLY);
      cycle.ticker = "NVDA";
      cycle.dte = 7;
      cycle.expiry = new Date(FIXED_NOW + 7 * 86400000).toISOString().slice(0, 10);
      cycle.suggestions[0]!.annualized_yield = cycle.suggestions[0]!.limit_price / cycle.spot * 365 / 7;
      lazy["v213:options:v2"].options.NVDA = { monthly: cycle };
    }), "NVDA 每月期權");
    expect(monthlyReply).not.toContain("330.00");
    expect(monthlyReply).toContain("封存之期權觀察未通過驗證");
  });

  it("B3: invalid document schema is not mislabeled as absent ticker or a measured stale age", async () => {
    const arrayReply = await actualReply(await sealedEnv(lazy => { lazy["v213:options:v2"].options = []; }), "TSM 每月期權");
    expect(arrayReply).toContain("無法驗證或讀取");
    expect(arrayReply).not.toContain("本輪封存快照未包含");
    expect(arrayReply).not.toContain("OPTION_DATA_NOT_ADMITTED");

    const badTimeReply = await actualReply(await sealedEnv(lazy => { lazy["v213:options:v2"].generated_at = "not-a-time"; }), "TSM 每月期權");
    expect(badTimeReply).toContain("無法驗證或讀取");
    expect(badTimeReply).not.toContain("已逾時");
    expect(badTimeReply).not.toContain("not-a-time");

    const missingBlobReply = await actualReply(await sealedEnv(() => {}, false, false, kv => {
      const seal = JSON.parse(kv.values.get(`snapshot:${RUN}:${SNAPSHOT_SEAL_KEY}`)!);
      kv.values.delete(`blob:v1:${seal.objects["v213:options:v2"].sha256}`);
    }), "TSM 每月期權");
    expect(missingBlobReply).toContain("無法驗證或讀取");
    expect(missingBlobReply).not.toContain("OPTION_DATA_NOT_ADMITTED");
  });

  it("B4: healthy flex exposes provenance, currency, mid, liquidity and delta basis with no NaN", async () => {
    admitSyntheticTickers("TSM");
    const reply = await actualReply({ ...(await sealedEnv()), V213_LINE_PRESENTATION: "flex" }, "TSM 每月期權");
    expect(reply).toContain("https://finance.yahoo.com/quote/TSM/options");
    expect(reply).toContain("計價 USD");
    expect(reply).toContain("中價 $2.05");
    expect(reply).toContain("OI 900");
    expect(reply).toContain("成交量 50");
    expect(reply).toContain("依報價隱含波動率");
    expect(reply).not.toContain("NaN");
  });

  it("B4: an omitted spread renders unknown, never NaN, in both flex and text", async () => {
    admitSyntheticTickers("TSM");
    const drop = (lazy: any) => { delete lazy["v213:options:v2"].options.TSM.monthly.suggestions[0].spread_pct; };
    const flexReply = await actualReply({ ...(await sealedEnv(drop)), V213_LINE_PRESENTATION: "flex" }, "TSM 每月期權");
    expect(flexReply).toContain("330.00");
    expect(flexReply).not.toContain("NaN");
    expect(flexReply).toContain("價差占中價 未提供");
    const textReply = await actualReply(await sealedEnv(drop), "TSM 每月期權");
    expect(textReply).not.toContain("NaN");
    expect(textReply).toContain("價差占中價 未提供");
  });
});

// I1 (amendment-02): a supplied optional liquidity/spread field that is nonfinite (raw JSON 1e309 -> Infinity), a wrong
// type (bool/string/array/object) or negative must fail closed at the shared validator, never reaching text or Flex,
// while the healthy GOOD sibling in the same sealed body still renders. A legitimate null/missing stays 未提供.
const KEY = "v213:options:v2";
function rawOptionsBody(field: "oi" | "volume" | "spread_pct", token: string): string {
  const doc = {
    schema: "v213-options-v2", generated_at: stamp,
    options: {
      TSM: { monthly: structuredClone(TSM_MONTHLY) },
      GOOD: { monthly: { ...structuredClone(TSM_MONTHLY), ticker: "GOOD" } },
    },
  };
  const json = JSON.stringify(doc);
  const original = `"${field}":${JSON.stringify((TSM_MONTHLY.suggestions[0] as Record<string, unknown>)[field])}`;
  return json.replace(original, `"${field}":${token}`);  // first occurrence = TSM; GOOD stays healthy
}

describe("OPTIONS-GLOBAL-01 round2 I1 nonfinite/malformed optional liquidity fields", () => {
  for (const style of ["text", "flex"] as const) {
    for (const field of ["oi", "volume", "spread_pct"] as const) {
      it(`${style}: raw JSON 1e309 ${field} fails closed and preserves the healthy sibling`, async () => {
        admitSyntheticTickers("TSM", "GOOD");
        const env = await sealedEnv(l => { l[KEY] = rawOptionsBody(field, "1e309"); });
        env.V213_LINE_PRESENTATION = style;
        const tsm = await actualReply(env, "TSM 每月期權");
        expect(tsm).not.toContain("330.00");
        expect(tsm).toContain("未通過驗證");
        expect(tsm).not.toMatch(/NaN|Infinity|undefined/);
        const sibling = await actualReply(env, "GOOD 每月期權");
        expect(sibling).toContain("330.00");
        expect(sibling).not.toMatch(/NaN|Infinity|undefined/);
      });
    }
  }
  for (const [label, token] of [["bool", "true"], ["string", '"5"'], ["array", "[]"], ["object", "{}"], ["negative", "-5"]] as const) {
    it(`rejects a wrong-type/negative oi (${label})`, async () => {
      admitSyntheticTickers("TSM", "GOOD");
      const env = await sealedEnv(l => { l[KEY] = rawOptionsBody("oi", token); });
      const reply = await actualReply(env, "TSM 每月期權");
      expect(reply).not.toContain("330.00");
      expect(reply).toContain("未通過驗證");
      expect(await actualReply(env, "GOOD 每月期權")).toContain("330.00");
    });
  }
  for (const style of ["text", "flex"] as const) {
    it(`${style}: null and missing optional fields stay 未提供, never NaN`, async () => {
      admitSyntheticTickers("TSM");
      const nulled = await sealedEnv(l => {
        for (const k of ["oi", "volume", "spread_pct"]) l[KEY].options.TSM.monthly.suggestions[0][k] = null;
      });
      nulled.V213_LINE_PRESENTATION = style;
      const nreply = await actualReply(nulled, "TSM 每月期權");
      expect(nreply).toContain("330.00");
      for (const word of ["OI 未提供", "成交量 未提供", "價差占中價 未提供"]) expect(nreply).toContain(word);
      expect(nreply).not.toMatch(/NaN|Infinity|undefined/);
      const missing = await sealedEnv(l => {
        for (const k of ["oi", "volume", "spread_pct"]) delete l[KEY].options.TSM.monthly.suggestions[0][k];
      });
      missing.V213_LINE_PRESENTATION = style;
      const mreply = await actualReply(missing, "TSM 每月期權");
      expect(mreply).toContain("330.00");
      expect(mreply).not.toMatch(/NaN|Infinity|undefined/);
    });
  }
});

// I3 (amendment-02): a future document beyond the <=5min clock tolerance is invalid, not falsely reported as older than
// six hours. Exact boundaries: future +5:00 admitted, +5:01 invalid; past age 6h admitted, 6h+1s stale.
describe("OPTIONS-GLOBAL-01 round2 I3 future vs stale document classification", () => {
  async function docCase(genAt: string, rowStamp: string) {
    const env = await sealedEnv(l => { l[KEY].generated_at = genAt; l[KEY].options.TSM.monthly.timestamp = rowStamp; });
    const status = (await loadDetailedOptionObservation(await pinPublicSnapshot(env as never), "TSM", "monthly", FIXED_NOW)).status;
    const reply = await actualReply(env, "TSM 每月期權");
    return { status, reply };
  }
  it("a future document just beyond tolerance is invalid, not stale", async () => {
    admitSyntheticTickers("TSM");
    const { status, reply } = await docCase("2026-09-30T12:05:01Z", stamp);
    expect(status).toBe("DOCUMENT_INVALID_OR_UNREADABLE");
    expect(reply).toContain("無法驗證或讀取");
    expect(reply).not.toContain("已逾時");
    expect(reply).not.toContain("330.00");
  });
  it("a future document at exactly +5min tolerance is admitted", async () => {
    admitSyntheticTickers("TSM"); // "admitted" here means freshness-admitted; rights are the synthetic seam
    const { status, reply } = await docCase("2026-09-30T12:05:00Z", stamp);
    expect(status).toBe("FOUND");
    expect(reply).toContain("330.00");
  });
  it("a document exactly 6h old is admitted", async () => {
    admitSyntheticTickers("TSM");
    const { status, reply } = await docCase("2026-09-30T06:00:00Z", "2026-09-30T06:00:00Z");
    expect(status).toBe("FOUND");
    expect(reply).toContain("330.00");
  });
  it("a document 6h+1s old is stale, not invalid", async () => {
    admitSyntheticTickers("TSM");
    const { status, reply } = await docCase("2026-09-30T05:59:59Z", stamp);
    expect(status).toBe("DOCUMENT_STALE");
    expect(reply).toContain("已逾時");
    expect(reply).not.toContain("330.00");
  });
});

// Durable Python-publisher -> sealed-Worker bridge (amendment-02): consume the committed exact emitted bodies produced
// by tests/fixtures/options_global_publisher_cases.py; the Worker seals each body verbatim (never a reconstructed DTO),
// asserts pinned byte-equality, and drives the real authorized caller. Rejected cycles show the publisher's explicit
// unavailable reason; the GOOD sibling always renders. The Python side proves regeneration matches these bytes.
const BRIDGE = JSON.parse(readFileSync(new URL("./fixtures/options-global-publisher.json", import.meta.url), "utf8")) as {
  clock: string; cases: Record<string, { period: "weekly" | "monthly"; admitted: boolean; options_body: string; quotes_body: string }>;
};
describe("OPTIONS-GLOBAL-01 round2 Python publisher -> sealed Worker bridge", () => {
  it("fixture clock matches the Worker fixed clock", () => {
    expect(BRIDGE.clock).toBe(new Date(FIXED_NOW).toISOString().replace(/\.\d{3}Z$/, "Z"));
  });
  for (const [name, fixture] of Object.entries(BRIDGE.cases)) {
    it(`${name}: exact emitted body sealed and consumed (admitted=${fixture.admitted})`, async () => {
      admitSyntheticTickers("TSM", "GOOD"); // publisher validation outcome only; rights NONE is tested without mocks
      const env = await sealedEnv(l => { l[KEY] = fixture.options_body; });
      // Pinned body equality: the sealed bytes are exactly the publisher's emitted string.
      expect(await (await pinPublicSnapshot(env as never)).text([KEY])).toBe(fixture.options_body);
      const reply = await actualReply(env, `TSM ${fixture.period} covered call`);
      expect(reply.includes("330.00")).toBe(fixture.admitted);
      expect(reply).not.toMatch(/NaN|Infinity/);
      if (!fixture.admitted) expect(reply).toContain("未通過驗證");
      // The healthy GOOD sibling in the same sealed document always renders (I2 healthy-sibling invariant).
      expect(await actualReply(env, "GOOD 每月期權")).toContain("330.00");
    });
  }
});
