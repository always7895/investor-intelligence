import { afterEach, describe, expect, it, vi } from "vitest";
import { deriveTenantId } from "../src/security";
import { asKv, MemoryKv } from "./fake-kv";
import { storeOwnerPairing } from "../src/v21/owner-storage";
import { parseH6B2Preview, sendH6B2SevenFieldTestPush } from "../src/v213/h6b2-line-test-push";

const HASH_KEY = "SYNTHETIC_H6B2_HASH_KEY_NOT_REAL";
const DATA_KEY = "SYNTHETIC_H6B2_DATA_KEY_NOT_REAL";
const LINE_TARGET = String.fromCharCode(85) + "0".repeat(32);
const R15_SOURCE_SHA = "f1d6790de99c8af981a40e26993a12a444b214ba";
const R15_REPORT_SHA = "cf0ff1a5a1499a8179fb0b68169511ec71c12f548069a3ee3a711955b705c284";
const R15R_PREVIEW_SHA = "ff0e0cfad5fffb6f0ed9c1482bc145f3ced7722f5eb571488e82a4f7b979c2c9";
const R15R_RECEIPT_SHA = "a9298a29ed007f0b697d6d57789dc00c795a1ff34c66c10903a50018ea1b4282";
const TICKERS = [
  "MU", "NVDA", "CRDO", "WDC", "ALAB", "AMD", "PLTR", "APH", "AAOI", "OCC",
  "AVGO", "LIF", "LRCX", "LASE", "NET", "CDE", "GWRE", "SMCI", "ADI", "CF",
];

const PREVIEW = [
  "股票｜長期投資報酬率（近2年年化）｜短期投資報酬率（近6個月）｜行業別｜獲利簡述｜公司現在訂單｜未來訂單預估",
  "MU｜+231.9%｜+132.5%｜半導體｜獲利；營收年增 +48.9%；營益率 70.4%；淨利率 59.9%｜SEC揭露RPO（剩餘履約義務；非全部客戶訂單）約$5 billion（文件日2026-06-25）；RPO常排除短期合約，不能視為公司全部客戶訂單｜公司預期約三分之一的該RPO於未來12個月認列；這是既有合約履約節奏，非新增訂單預測",
  "NVDA｜+43.3%｜+21.1%｜半導體｜獲利；營收年增 +65.5%；營益率 65.9%；淨利率 66.4%｜SEC揭露RPO（剩餘履約義務；非全部客戶訂單）約$3.2 billion（文件日2026-08-26）；RPO常排除短期合約，不能視為公司全部客戶訂單｜公司預期約39%的該RPO於未來12個月認列；這是既有合約履約節奏，非新增訂單預測",
  "CRDO｜+168.7%｜+98.0%｜半導體｜獲利；營收年增 +205.7%；營益率 33.3%；淨利率 35.4%｜SEC揭露RPO（剩餘履約義務；非全部客戶訂單）約$31.9 million（文件日2026-06-15）；RPO常排除短期合約，不能視為公司全部客戶訂單｜公司預期該RPO於下一會計年度認列；屬既有合約履約節奏，非新增訂單預測",
  "WDC｜+209.8%｜+66.9%｜電腦硬體｜獲利；營收年增 +35.7%；營益率 34.5%；淨利率 72.9%｜未揭露（無可靠公開訂單數字）｜無可靠公開預估",
  "ALAB｜+176.9%｜+146.3%｜半導體｜獲利；營收年增 +115.1%；營益率 21.6%；淨利率 33.3%｜未揭露（無可靠公開訂單數字）｜無可靠公開預估",
  "AMD｜+86.0%｜+137.0%｜半導體｜獲利；營收年增 +34.3%；營益率 15.9%；淨利率 16.9%｜SEC揭露RPO（剩餘履約義務；非全部客戶訂單）約$222 million（文件日2026-08-05）；RPO常排除短期合約，不能視為公司全部客戶訂單｜公司預期未來12個月認列約$144 million的該RPO；這是既有合約履約節奏，非新增訂單預測",
  "PLTR｜+148.2%｜+28.4%｜基礎架構軟體｜獲利；營收年增 +56.2%；營益率 46.7%；淨利率 54.2%｜SEC揭露RPO（剩餘履約義務；非全部客戶訂單）約$4.9 billion（文件日2026-08-04）；RPO常排除短期合約，不能視為公司全部客戶訂單｜公司預期約43%的該RPO於未來12個月認列；這是既有合約履約節奏，非新增訂單預測",
  "APH｜+61.7%｜+17.7%｜電子零組件｜獲利；營收年增 +51.7%；營益率 27.0%；淨利率 16.5%｜SEC文件明確揭露backlog約$8.9 billion（文件日2026-02-11）；未以其他來源補估總額｜公司預期幾乎全部既有backlog於未來12個月內履行；屬既有訂單履約節奏，非新增訂單預測",
  "AAOI｜+197.9%｜+5.0%｜通訊設備｜虧損；營收年增 +82.8%；營益率 -11.0%；淨利率 -10.8%｜未揭露（無可靠公開訂單數字）｜無可靠公開預估",
  "OCC｜+119.4%｜+110.3%｜通訊設備｜獲利；營收年增 +37.0%；營益率 1.2%；淨利率 0.7%｜SEC文件明確揭露backlog約$13.3 million（文件日2026-06-08）；未以其他來源補估總額｜無可靠公開預估",
  "AVGO｜+57.5%｜+16.6%｜半導體｜獲利；營收年增 +23.9%；營益率 46.6%；淨利率 40.1%｜SEC揭露RPO（剩餘履約義務；非全部客戶訂單）約$164.6 billion（文件日2026-06-09）；RPO常排除短期合約，不能視為公司全部客戶訂單｜公司預期約30%的該RPO於未來12個月認列；這是既有合約履約節奏，非新增訂單預測",
  "LIF｜+7.3%｜-20.3%｜應用軟體｜獲利；營收年增 +31.8%；營益率 -2.7%；淨利率 2.6%｜SEC揭露RPO（剩餘履約義務；非全部客戶訂單）約$186.8 million（文件日2026-08-10）；RPO常排除短期合約，不能視為公司全部客戶訂單｜公司預期約46%的該RPO於未來12個月認列；這是既有合約履約節奏，非新增訂單預測",
  "LRCX｜+100.8%｜+30.8%｜半導體設備與材料｜獲利；營收年增 +26.0%；營益率 35.3%；淨利率 31.3%｜未揭露（無可靠公開訂單數字）｜無可靠公開預估",
  "LASE｜-34.0%｜+51.6%｜專用工業機械｜虧損；營收年增 +147.7%；營益率 -189.7%；淨利率 -228.7%｜未揭露（無可靠公開訂單數字）｜無可靠公開預估",
  "NET｜+98.3%｜+68.5%｜基礎架構軟體｜虧損；營收年增 +29.8%；營益率 -20.0%；淨利率 -14.4%｜SEC揭露RPO（剩餘履約義務；非全部客戶訂單）約$2,732.0 million（文件日2026-08-06）；RPO常排除短期合約，不能視為公司全部客戶訂單｜公司預期約64%的該RPO於未來12個月認列；這是既有合約履約節奏，非新增訂單預測",
  "CDE｜+95.8%｜-22.8%｜其他產業｜獲利；營收年增 +96.4%；營益率 29.1%；淨利率 19.0%｜未揭露（無可靠公開訂單數字）｜無可靠公開預估",
  "GWRE｜+18.5%｜+37.4%｜應用軟體｜獲利；營收年增 +22.6%；營益率 8.2%；淨利率 10.1%｜SEC揭露RPO（剩餘履約義務；非全部客戶訂單）約$3.6 billion（文件日2026-06-05）；RPO常排除短期合約，不能視為公司全部客戶訂單｜無可靠公開預估",
  "SMCI｜-8.2%｜+17.1%｜電腦硬體｜獲利；營收年增 +46.6%；營益率 4.6%；淨利率 3.8%｜SEC揭露RPO（剩餘履約義務；非全部客戶訂單）約$2,612.0 million（文件日2026-08-31）；RPO常排除短期合約，不能視為公司全部客戶訂單｜公司預期約60%的該RPO於未來12個月認列；這是既有合約履約節奏，非新增訂單預測",
  "ADI｜+30.6%｜+3.4%｜半導體｜獲利；營收年增 +16.9%；營益率 36.9%；淨利率 31.0%｜未揭露（無可靠公開訂單數字）｜無可靠公開預估",
  "CF｜+31.2%｜+25.8%｜其他產業｜獲利；營收年增 +19.3%；營益率 47.1%；淨利率 36.7%｜SEC揭露RPO（剩餘履約義務；非全部客戶訂單）約$1.5 billion（文件日2026-08-06）；RPO常排除短期合約，不能視為公司全部客戶訂單｜既有RPO履約節奏：2026剩餘期間約17%、2027–2029約43%、2030–2032約14%，其餘其後；非新增訂單預測"
].join("\r\n") + "\r\n";

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

function top20(tickers = TICKERS) {
  const generated = new Date().toISOString();
  return tickers.map((ticker, index) => ({
    ticker,
    name: `Synthetic ${ticker}`,
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
    as_of: "2026-08-31T00:00:00+00:00",
  }));
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
    LINE_CHANNEL_ACCESS_TOKEN: "SYNTHETIC_LINE_CHANNEL_ACCESS_NOT_REAL",
  };
  return { publicKv, privateKv, securityKv, env };
}

async function digest(text: string): Promise<string> {
  const result = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(result), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function envelope() {
  return JSON.stringify({
    schema_version: 1,
    stage: "H6B2_REAL_LINE_SEVEN_FIELD_TEST",
    source_sha: R15_SOURCE_SHA,
    report_sha256: R15_REPORT_SHA,
    preview_sha256: R15R_PREVIEW_SHA,
    receipt_sha256: R15R_RECEIPT_SHA,
    preview_text: PREVIEW,
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("v2.1.3 H6B2 order-reconciled seven-field LINE acceptance", () => {
  it("locks the exact R15R reordered preview bytes and seven-field structure", async () => {
    expect(await digest(PREVIEW)).toBe(R15R_PREVIEW_SHA);
    const parsed = parseH6B2Preview(PREVIEW);
    expect(parsed.tickers).toEqual(TICKERS);
    expect(parsed.canonical.split(/\r?\n/)).toHaveLength(21);
    expect(parsed.canonical.split(/\r?\n/).slice(1).every((row) => row.split("｜").length === 7)).toBe(true);
  });

  it("pushes exactly one reconciled seven-field message without public KV writes", async () => {
    const { publicKv, env } = runtime();
    const tenantId = await deriveTenantId({ type: "user", userId: LINE_TARGET }, HASH_KEY);
    await storeOwnerPairing(env, tenantId, LINE_TARGET);
    const runId = "20260901T122248Z-fccfd14d3c79";
    publicKv.values.set("snapshot:current", JSON.stringify({ run_id: runId }));
    publicKv.values.set(`snapshot:${runId}:v21:top20:latest`, JSON.stringify(top20()));
    const beforeKeys = [...publicKv.values.keys()].sort();
    const calls: Array<Record<string, unknown>> = [];
    vi.stubGlobal("fetch", vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      calls.push(JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>);
      return new Response("{}", { status: 200 });
    }));

    const result = await sendH6B2SevenFieldTestPush(env, envelope());
    expect(result.status).toBe("sent");
    expect(result.format).toBe("v213_seven_fields");
    expect(result.message_count).toBe(1);
    expect(result.order_reconciliation).toBe("R15_ORDER_ONLY");
    expect(calls).toHaveLength(1);
    expect(calls[0]?.to).toBe(LINE_TARGET);
    const messages = calls[0]?.messages as Array<Record<string, unknown>>;
    expect(messages).toHaveLength(1);
    expect(messages[0]?.text).toBe(PREVIEW.trim());
    expect([...publicKv.values.keys()].sort()).toEqual(beforeKeys);
  });

  it("fails closed when live public Top20 order drifts after reconciliation", async () => {
    const { publicKv, env } = runtime();
    const tenantId = await deriveTenantId({ type: "user", userId: LINE_TARGET }, HASH_KEY);
    await storeOwnerPairing(env, tenantId, LINE_TARGET);
    const runId = "20260901T122248Z-fccfd14d3c79";
    const wrong = [...TICKERS];
    [wrong[17], wrong[18]] = [wrong[18]!, wrong[17]!];
    publicKv.values.set("snapshot:current", JSON.stringify({ run_id: runId }));
    publicKv.values.set(`snapshot:${runId}:v21:top20:latest`, JSON.stringify(top20(wrong)));
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const result = await sendH6B2SevenFieldTestPush(env, envelope());
    expect(result.status).toBe("top20_order_mismatch");
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
