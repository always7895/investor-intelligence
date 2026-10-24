// Synthetic, offline, digest-bound macro data; fiscal dates intentionally predate calculation dates.
import { buildSnapshotSeal, SNAPSHOT_OBJECT_KEYS, SNAPSHOT_SEAL_KEY } from "../src/v213/snapshot-seal";
import { MACRO_PRODUCT_KEY } from "../src/v213/macro-industry-product";
import { asKv, MemoryKv } from "./fake-kv";
import contract from "../../config/v213-r75-publication-mode-v2.json";

export const MACRO_STAMP = "2026-09-25T12:00:00Z";
export const MACRO_NOW = "2026-09-25T12:30:00Z";
const RUN = "20260925T120000Z-0123456789ab";
const TX = "6".repeat(32);

export function macroDocument(stamp = MACRO_STAMP, basis = "2026-09-25") {
  const ids = ["alpha", "beta", "gamma", "delta", "epsilon"];
  return {
    schema_version: 1, title: "TOP5產業總覽", generated_at: stamp, horizon: "12-36M", qualified_count: 5,
    shortfall: 0, status: "ADMITTED_TOP5", data_basis: { as_of: basis },
    industries: ids.map((id, index) => ({
      rank: index + 1, industry_id: id, industry_name: `合成產業 ${id} (Synthetic ${id})`,
      current_state: "合成市場現況", outlook_12_36m: "合成資料階段",
      growth: { rate_pct: 25, units: "% YoY", period: "2026 Q2", type: "actual", publisher: "SEC EDGAR XBRL frames (issuer filings)",
        date: "2026-06-30", source_id: "sec-xbrl-frames-revenue", url: "https://data.sec.gov/api/xbrl/frames/x.json", raw_passage: "synthetic" },
      demand_drivers: ["合成需求"], supply_constraint_chokepoint: "合成 RPO", pricing: "合成 PPI", value_chain_position: "合成 SIC",
      beneficiaries_key_suppliers: ["Synthetic Issuer"], catalysts: { m6: "下次資料檢查", y1: "每季", y2: "無已公告催化劑" },
      risks_lifecycle: "合成風險", opportunity_score: 70 - index,
      confidence: { data_completeness: 100, source_independence: 100, verification_status: "OFFICIAL_DATA_COMPUTED" },
    })),
    deep_analyses: Object.fromEntries(ids.map(id => [id, {
      industry_id: id, industry_name: `合成產業 ${id}`, demand: "合成需求", supply: "合成供給", bottleneck: "合成瓶頸",
      pricing: "合成定價", capex: "合成資本支出", competition: "合成競爭", beneficiaries: ["Synthetic Issuer"],
      catalysts: { m6: "下次資料檢查", y1: "每季", y2: "無已公告催化劑" }, risks: ["合成風險"], killers: ["合成證偽"],
      source_references: [{ source: "BLS PPI synthetic", url: "https://data.bls.gov/timeseries/PCU000", period: "2026-08" }],
    }])),
    potential_ranking: {
      as_of: basis, quarter: "2026 Q2", records: [{
        rank: 1, ticker: "SYNA", name: "Synthetic SYNA Corp.", industry_name: "合成產業", phase: "COMMERCIAL_VALIDATION",
        strength: 70, revenue_yoy_pct: 25, rpo_yoy_pct: 68, gross_margin_change_pp: 2, operating_margin_change_pp: 1,
        dilution_yoy_pct: 1, next_review_at: null,
        orders: { as_of: "2026-06-30", filed: "2026-07-29", form: "10-Q",
          coverage_pct: { m6: 110, m12: 110, m24: 110 }, floor_growth_pct: { m6: 10, m12: 10, m24: 10 } },
      }], reports: { SYNA: {
        ticker: "SYNA", name: "Synthetic SYNA Corp.", as_of: stamp.slice(0, 10), boundary: "合成官方資料計算",
        phase: { phase: "COMMERCIAL_VALIDATION", next_review_at: null },
        sections: [{ title: "營運動能", text: "合成報告數據" }, { title: "訂單能見度", text: "合成 RPO" }, { title: "證偽", text: "合成證偽" }],
        source_references: [{ source: "SEC XBRL company facts", url: "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json" }],
      } },
    },
  };
}

export async function macroEnv(doc: unknown = macroDocument(), stamp = MACRO_STAMP, afterRead?: () => void) {
  const bodies: [string, string][] = SNAPSHOT_OBJECT_KEYS.map(key => [key, JSON.stringify({ synthetic_fixture: true, key })]);
  bodies.find(([key]) => key === "last_successful_pipeline_timestamp")![1] = stamp;
  bodies.find(([key]) => key === "v213:activation-claim")![1] = JSON.stringify({ schema_version: 1, transaction_id: TX, run_id: RUN,
    payload_digests: Object.fromEntries(contract.payload_names.map(name => [name, "a".repeat(64)])), claimed_at: stamp });
  const meta = { run_id: RUN, transaction_id: TX, generated_at: stamp, public_data_as_of: stamp };
  const base = await buildSnapshotSeal(meta, bodies);
  const sha = async (value: string) => Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value))),
    b => b.toString(16).padStart(2, "0")).join("");
  const manifest = JSON.parse(base.text);
  const raw = JSON.stringify(doc);
  manifest.objects[MACRO_PRODUCT_KEY] = { sha256: await sha(raw), utf8_bytes: new TextEncoder().encode(raw).byteLength };
  bodies.push([MACRO_PRODUCT_KEY, raw]);
  const sealText = JSON.stringify(manifest);
  class DelayedKv extends MemoryKv {
    override async get<T = string>(key: string, type?: "text" | "json") {
      const result = await super.get<T>(key, type);
      if (key.endsWith(MACRO_PRODUCT_KEY)) afterRead?.();
      return result;
    }
  }
  const kv = new DelayedKv();
  for (const [key, value] of bodies) kv.values.set(`snapshot:${RUN}:${key}`, value);
  kv.values.set(`snapshot:${RUN}:${SNAPSHOT_SEAL_KEY}`, sealText);
  kv.values.set("snapshot:current", JSON.stringify({ schema_version: 2, ...meta, generated_at: undefined, seal_sha256: await sha(sealText),
    promoted_at: stamp, provider_scope: "public_only", owner_watchlist_inherited: false }));
  return {
    kv,
    env: { PUBLIC_CACHE: asKv(kv), TENANT_PRIVATE_CACHE: asKv(new MemoryKv()), EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()),
      LINE_CHANNEL_SECRET: "SYNTHETIC_ONLY", LINE_CHANNEL_ACCESS_TOKEN: "SYNTHETIC_ONLY", CURRENT_PUBLIC_DATA_ENABLED: "true",
      V213_FIELD_LOCALE: "bilingual", V21_TOP20_MAX_AGE_SECONDS: "7200" },
  };
}
