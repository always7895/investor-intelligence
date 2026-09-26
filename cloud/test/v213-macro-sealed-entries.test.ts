// Industry card and deep analysis are read from inside the sealed TOP5 overview (synthetic data only).
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { buildSnapshotSeal, SNAPSHOT_OBJECT_KEYS } from "../src/v213/snapshot-seal";
import { MACRO_PRODUCT_KEY } from "../src/v213/macro-industry-product";
import { v213PublicLineAnswer } from "../src/v213/rich-menu";
import { parseQuery } from "../src/core";
import { asKv, MemoryKv } from "./fake-kv";
import contract from "../../config/v213-r75-publication-mode-v1.json";

const RUN = "20260925T120000Z-0123456789ab";
const STAMP = "2026-09-25T12:00:00Z";
const TX = "4".repeat(32);

const card = (id: string, rank: number) => ({
  rank, industry_id: id, industry_name: `合成產業 ${id} (Synthetic ${id})`,
  current_state: "BLS 生產者物價指數年增 +10.0%（合成）", outlook_12_36m: "資料階段：驗證中（合成）",
  growth: { rate_pct: 25, units: "% YoY", period: "2026 Q2", type: "actual", publisher: "SEC EDGAR XBRL frames (issuer filings)",
    date: "2026-06-30", source_id: "sec-xbrl-frames-revenue", url: "https://data.sec.gov/api/xbrl/frames/x.json", raw_passage: "synthetic" },
  demand_drivers: ["合成營收年增"], supply_constraint_chokepoint: "合成 RPO", pricing: "合成 PPI", value_chain_position: "合成 SIC",
  beneficiaries_key_suppliers: ["Synthetic Issuer"], catalysts: { m6: "下次資料檢查", y1: "每季", y2: "無已公告催化劑（不捏造）" },
  risks_lifecycle: "合成風險", opportunity_score: 70 - rank,
  confidence: { data_completeness: 100, source_independence: 100, verification_status: "OFFICIAL_DATA_COMPUTED" },
});

const deep = (id: string) => ({
  industry_id: id, industry_name: `合成產業 ${id}`, demand: "合成需求（SEC XBRL）", supply: "合成供給", bottleneck: "合成瓶頸（RPO）",
  pricing: "合成定價（BLS PPI）", capex: "本資料集未量測買方資本支出；不以推估代替", competition: "合成競爭",
  beneficiaries: ["Synthetic Issuer"], catalysts: { m6: "下次資料檢查", y1: "每季", y2: "無已公告催化劑（不捏造）" },
  risks: ["合成風險"], killers: ["PPI 年增降至 -3% 以下"],
  source_references: [{ source: "BLS PPI synthetic", url: "https://data.bls.gov/timeseries/PCU000", period: "2026-08" }],
});

async function sealedEnv() {
  const ids = ["alpha", "beta", "gamma", "delta", "epsilon"];
  const overview = { schema_version: 1, title: "TOP5產業總覽", generated_at: STAMP, horizon: "12-36M", qualified_count: 5,
    shortfall: 0, status: "ADMITTED_TOP5", industries: ids.map((id, i) => card(id, i + 1)),
    deep_analyses: Object.fromEntries(ids.map(id => [id, deep(id)])) };
  const bodies: [string, string][] = SNAPSHOT_OBJECT_KEYS.map(key => [key, JSON.stringify({ synthetic_fixture: true, key })]);
  bodies.find(([key]) => key === "last_successful_pipeline_timestamp")![1] = STAMP;
  bodies.find(([key]) => key === "v213:activation-claim")![1] = JSON.stringify({
    schema_version: 1, transaction_id: TX, run_id: RUN,
    payload_digests: Object.fromEntries(contract.payload_names.map((name: string) => [name, "a".repeat(64)])), claimed_at: STAMP,
  });
  // The Python publisher writes core + macro manifests; mirror its exact manifest shape here.
  await buildSnapshotSeal({ run_id: RUN, transaction_id: TX, generated_at: STAMP, public_data_as_of: STAMP }, bodies);
  bodies.push([MACRO_PRODUCT_KEY, JSON.stringify(overview)]);
  const sha = async (text: string) => Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text))),
    b => b.toString(16).padStart(2, "0")).join("");
  const objects: Record<string, { sha256: string; utf8_bytes: number }> = {};
  for (const [key, value] of bodies) objects[key] = { sha256: await sha(value), utf8_bytes: new TextEncoder().encode(value).byteLength };
  const text = JSON.stringify({ schema_version: 1, contract_id: "v213-stored-snapshot-v1", run_id: RUN, transaction_id: TX,
    generated_at: STAMP, public_data_as_of: STAMP, provider_scope: "public_only", owner_watchlist_inherited: false, objects });
  const seal = { text, sha256: await sha(text) };
  const kv = new MemoryKv();
  for (const [key, value] of bodies) kv.values.set(`snapshot:${RUN}:${key}`, value);
  kv.values.set(`snapshot:${RUN}:v213:snapshot-seal:v1`, seal.text);
  kv.values.set("snapshot:current", JSON.stringify({ schema_version: 2, run_id: RUN, transaction_id: TX, seal_sha256: seal.sha256,
    public_data_as_of: STAMP, promoted_at: STAMP, provider_scope: "public_only", owner_watchlist_inherited: false }));
  return { PUBLIC_CACHE: asKv(kv), TENANT_PRIVATE_CACHE: asKv(new MemoryKv()), EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()),
    V213_FIELD_LOCALE: "bilingual", V21_TOP20_MAX_AGE_SECONDS: "7200" } as never;
}

beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(new Date("2026-09-25T12:30:00Z")); });
afterEach(() => { vi.useRealTimers(); });

it("renders the deep analysis embedded in the sealed overview", async () => {
  const body = JSON.stringify(await v213PublicLineAnswer(await sealedEnv(), parseQuery("宏觀產業 深度化分析 beta")));
  expect(body).not.toContain("MACRO_DEEP_UNAVAILABLE");
  expect(body).toContain("合成瓶頸（RPO）");
  expect(body).toContain("本資料集未量測買方資本支出");
});

it("renders the industry card embedded in the sealed overview", async () => {
  const body = JSON.stringify(await v213PublicLineAnswer(await sealedEnv(), parseQuery("宏觀產業 卡片 gamma")));
  expect(body).not.toContain("MACRO_CARD_UNAVAILABLE");
  expect(body).toContain("合成產業 gamma");
});

it("an industry outside the sealed overview stays unavailable", async () => {
  const body = JSON.stringify(await v213PublicLineAnswer(await sealedEnv(), parseQuery("宏觀產業 深度化分析 omega")));
  expect(body).toContain("MACRO_DEEP_UNAVAILABLE");
});
