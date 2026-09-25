// Data-driven potential ranking sealed inside the TOP5 overview (synthetic values only).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { assertLineMessages } from "../src/line-messages";
import { processAuthorizedLineEvent } from "../src/v211/worker";
import { freeRelayRequestEnv } from "../src/v213/production-worker";
import { buildSnapshotSeal, SNAPSHOT_OBJECT_KEYS } from "../src/v213/snapshot-seal";
import { MACRO_PRODUCT_KEY } from "../src/v213/macro-industry-product";
import { validatePotentialRanking } from "../src/v213/potential-ranking";
import { asKv, MemoryKv } from "./fake-kv";
import contract from "../../config/v213-r75-publication-mode-v1.json";

const RUN = "20260925T120000Z-0123456789ab";
const STAMP = "2026-09-25T12:00:00Z";
const TX = "5".repeat(32);

const row = (rank: number, ticker: string) => ({
  rank, ticker, name: `Synthetic ${ticker} Corp.`, industry_name: "合成產業", phase: rank === 1 ? "COMMERCIAL_VALIDATION" : "DISCOVERY",
  strength: 70 - rank, revenue_yoy_pct: 25.5, rpo_yoy_pct: rank === 1 ? 68.4 : null, gross_margin_change_pp: 2.5,
  operating_margin_change_pp: -1.2, dilution_yoy_pct: 1.0, next_review_at: "2026-12-08",
});
const REPORT = {
  ticker: "SYNA", name: "Synthetic SYNA Corp.", as_of: "2026-09-25", boundary: "官方資料的計算與整理；不是投資建議、價格預測或機率",
  phase: { phase: "COMMERCIAL_VALIDATION", next_review_at: "2026-12-08" },
  sections: [{ title: "營運動能", text: "營收年增 +25.5%（合成）" }, { title: "訂單能見度", text: "RPO 年增 +68.4%（合成）" },
    { title: "證偽條件", text: "RPO 年增降至 -10% 以下（合成）" }],
  source_references: [{ source: "SEC XBRL company facts", url: "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json" }],
};
const RANKING = { as_of: "2026-09-25", quarter: "2026 Q2", records: [row(1, "SYNA"), row(2, "SYNB")], reports: { SYNA: REPORT } };

async function sealedEnv(ranking: unknown = RANKING) {
  const overview = { schema_version: 1, title: "TOP5產業總覽", generated_at: STAMP, horizon: "12-36M", qualified_count: 0,
    shortfall: 5, status: "SHORTFALL_NOT_QUALIFIED", industries: [], potential_ranking: ranking };
  const bodies: [string, string][] = SNAPSHOT_OBJECT_KEYS.map(key => [key, JSON.stringify({ synthetic_fixture: true, key })]);
  bodies.find(([key]) => key === "last_successful_pipeline_timestamp")![1] = STAMP;
  bodies.find(([key]) => key === "v213:activation-claim")![1] = JSON.stringify({ schema_version: 1, transaction_id: TX, run_id: RUN,
    payload_digests: Object.fromEntries(contract.payload_names.map((name: string) => [name, "a".repeat(64)])), claimed_at: STAMP });
  await buildSnapshotSeal({ run_id: RUN, transaction_id: TX, generated_at: STAMP, public_data_as_of: STAMP }, bodies);
  bodies.push([MACRO_PRODUCT_KEY, JSON.stringify(overview)]);
  const sha = async (text: string) => Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text))),
    b => b.toString(16).padStart(2, "0")).join("");
  const objects: Record<string, { sha256: string; utf8_bytes: number }> = {};
  for (const [key, value] of bodies) objects[key] = { sha256: await sha(value), utf8_bytes: new TextEncoder().encode(value).byteLength };
  const text = JSON.stringify({ schema_version: 1, contract_id: "v213-stored-snapshot-v1", run_id: RUN, transaction_id: TX,
    generated_at: STAMP, public_data_as_of: STAMP, provider_scope: "public_only", owner_watchlist_inherited: false, objects });
  const kv = new MemoryKv();
  for (const [key, value] of bodies) kv.values.set(`snapshot:${RUN}:${key}`, value);
  kv.values.set(`snapshot:${RUN}:v213:snapshot-seal:v1`, text);
  kv.values.set("snapshot:current", JSON.stringify({ schema_version: 2, run_id: RUN, transaction_id: TX, seal_sha256: await sha(text),
    public_data_as_of: STAMP, promoted_at: STAMP, provider_scope: "public_only", owner_watchlist_inherited: false }));
  return { PUBLIC_CACHE: asKv(kv), TENANT_PRIVATE_CACHE: asKv(new MemoryKv()), EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()),
    LINE_CHANNEL_SECRET: "EXAMPLE_NOT_REAL", LINE_CHANNEL_ACCESS_TOKEN: "EXAMPLE_NOT_REAL", CURRENT_PUBLIC_DATA_ENABLED: "true",
    V213_FIELD_LOCALE: "bilingual", V21_TOP20_MAX_AGE_SECONDS: "7200" };
}

async function actualReply(command: string, env: unknown) {
  let messages: any[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
    expect(url).toBe("https://api.line.me/v2/bot/message/reply");
    messages = JSON.parse(String(init.body)).messages;
    return new Response("{}", { status: 200 });
  }));
  await processAuthorizedLineEvent(await freeRelayRequestEnv(env as any),
    { waitUntil() { throw new Error("MODEL_JOB_FORBIDDEN"); } } as unknown as ExecutionContext,
    { type: "message", replyToken: "SYNTHETIC_REPLY", timestamp: Date.now(), message: { id: "SYNTHETIC_MESSAGE", type: "text", text: command } },
    "SYNTHETIC_TENANT");
  assertLineMessages(messages);
  return JSON.stringify(messages);
}

/** Text a LINE user sees: plain text nodes, or the spans of a highlighted text joined. */
const visibleText = (node: any): string => !node || typeof node !== "object" ? ""
  : Array.isArray(node) ? node.map(visibleText).join(" ")
    : node.type === "text" && Array.isArray(node.contents) ? node.contents.map((span: any) => span.text).join("")
      : node.type === "text" && typeof node.text === "string" ? node.text
        : Object.values(node).map(visibleText).filter(Boolean).join(" ");

beforeEach(() => { vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(new Date("2026-09-25T12:30:00Z")); });
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

describe("data-driven potential ranking", () => {
  it("renders the sealed ranking through the actual LINE event path", async () => {
    const body = await actualReply("潛力榜", await sealedEnv());
    expect(body).toContain("資料驅動潛力榜");
    expect(body).toContain("SYNA");
    expect(body).toContain("潛力報告 SYNA");
    expect(body).toContain("商業驗證");
  });

  it("renders a company report without being intercepted by the equity lookup", async () => {
    const body = await actualReply("潛力報告 SYNA", await sealedEnv());
    expect(body).toContain("公司深度報告 · 官方資料計算");
    expect(visibleText(JSON.parse(body))).toContain("RPO 年增 +68.4%");
    const figure = JSON.stringify(JSON.parse(body)).match(/\{"type":"span","text":"\+68\.4%"[^}]*\}/)?.[0];
    expect(figure).toContain('"weight":"bold"');
    expect(JSON.stringify(JSON.parse(body))).toMatch(/"text":"-10%","weight":"bold","color":"#B42318"/);
    const text = JSON.parse(await actualReply("潛力報告 SYNA 文字", await sealedEnv()));
    expect(text.every((m: any) => m.type === "text")).toBe(true);
    expect(text.map((m: any) => m.text).join(" ")).toContain("RPO 年增 +68.4%");
  });

  it("refuses companies outside the ranking or without a validated report", async () => {
    expect(await actualReply("潛力報告 SYNB", await sealedEnv())).toContain("尚未產生或未通過驗證");
    expect(await actualReply("潛力報告 ABCD", await sealedEnv())).toContain("不在本輪資料驅動潛力榜中");
  });

  it("a full 20-company ranking fits LINE limits (4 carousels of 5)", async () => {
    const letters = "ABCDEFGHIJKLMNOPQRST";
    const full = { ...RANKING, records: Array.from(letters, (c, i) => row(i + 1, `SY${c}`)) };
    const body = await actualReply("潛力榜", await sealedEnv(full));
    const messages = JSON.parse(body);
    expect(messages).toHaveLength(4);
    expect(messages.every((m: any) => m.contents.contents.length === 5)).toBe(true);
  });

  it("fails closed when the ranking is missing or malformed", async () => {
    expect(await actualReply("潛力榜", await sealedEnv(null))).toContain("POTENTIAL_RANKING_UNAVAILABLE");
    for (const bad of [
      { ...RANKING, records: [{ ...row(1, "SYNA"), rank: 2 }] },
      { ...RANKING, records: [{ ...row(1, "SYNA-P") }] },
      { ...RANKING, records: [{ ...row(1, "SYNA"), phase: "CONSENSUS" }] },
      { ...RANKING, records: [{ ...row(1, "SYNA"), strength: 101 }] },
      { ...RANKING, as_of: "today" },
    ]) {
      expect(validatePotentialRanking(bad)).toBeNull();
    }
  });
});
