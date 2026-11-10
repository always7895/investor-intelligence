// Synthetic, in-memory actual-reader proof only; no production, provider, account or admission operations.
import { createHash } from "node:crypto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { parseQuery } from "../src/core";
import { loadDelayedQuote } from "../src/v213/market-observations";
import { clearVerifiedLazyBodies, pinPublicSnapshot } from "../src/v213/public-snapshot";
import { buildSnapshotSeal, SNAPSHOT_OBJECT_KEYS, SNAPSHOT_SEAL_KEY } from "../src/v213/snapshot-seal";
import { loadV213FreshTop20Report } from "../src/v213/top20-report";
import { probeLegacyReport } from "./helpers/legacy-report-probe";
import { buildSyntheticSealedReplay, makeOfflineEnv, SYNTHETIC_RUN, SYNTHETIC_STAMP } from "./synthetic-sealed-replay-fixture";

const GLOBAL_RUN = "20260917T120000Z-abcdefabcdef";
const OBSERVED = Date.parse(SYNTHETIC_STAMP) + 48 * 3600_000;
const GLOBAL_STAMP = new Date(OBSERVED).toISOString();
const sha = (body: string) => createHash("sha256").update(body, "utf8").digest("hex");

async function reusedFixture(invalidLegacy = false) {
  const { kv, reportRaw } = await buildSyntheticSealedReplay();
  const pointer = JSON.parse(kv.values.get("snapshot:current")!);
  const bodies: [string, string][] = SNAPSHOT_OBJECT_KEYS.map(key => [key,
    key === "last_successful_pipeline_timestamp" ? GLOBAL_STAMP : kv.values.get(`snapshot:${SYNTHETIC_RUN}:${key}`)!]);
  if (invalidLegacy) bodies.find(([key]) => key === "v213:top20-report:latest")![1] = JSON.stringify({ generated_at: SYNTHETIC_STAMP });
  const root = await buildSnapshotSeal({ run_id: GLOBAL_RUN, core_run_id: SYNTHETIC_RUN, transaction_id: pointer.transaction_id,
    generated_at: GLOBAL_STAMP, public_data_as_of: SYNTHETIC_STAMP, ranking_persisted_at: SYNTHETIC_STAMP,
    product_persisted_at: { market: GLOBAL_STAMP } }, bodies);
  const manifest = JSON.parse(root.text);
  const quotes = JSON.stringify({ schema: "v213-quotes-v1", generated_at: GLOBAL_STAMP, quotes: {
    "SIVE.ST": { symbol: "SIVE.ST", price: 32.78, previous_close: 31.5, change_pct: 0.0406, currency: "SEK",
      asof: GLOBAL_STAMP, source: "Yahoo Finance (unofficial, delayed)", source_url: "https://finance.yahoo.com/quote/SIVE.ST" },
  } });
  manifest.objects["v213:quotes:v1"] = { sha256: sha(quotes), utf8_bytes: new TextEncoder().encode(quotes).byteLength };
  const raw = JSON.stringify(manifest);
  kv.values.set(`snapshot:${GLOBAL_RUN}:${SNAPSHOT_SEAL_KEY}`, raw);
  kv.values.set(`snapshot:${GLOBAL_RUN}:last_successful_pipeline_timestamp`, GLOBAL_STAMP);
  if (invalidLegacy) kv.values.set(`snapshot:${SYNTHETIC_RUN}:v213:top20-report:latest`, bodies.find(([key]) => key === "v213:top20-report:latest")![1]);
  kv.values.set(`blob:v1:${sha(quotes)}`, quotes);
  kv.values.set("snapshot:current", JSON.stringify({ ...pointer, run_id: GLOBAL_RUN, seal_sha256: sha(raw), promoted_at: GLOBAL_STAMP }));
  const f = makeOfflineEnv(kv);
  f.env.V21_TOP20_MAX_AGE_SECONDS = "7200";
  return { ...f, kv, reportRaw };
}

beforeEach(() => { clearVerifiedLazyBodies(); vi.spyOn(Date, "now").mockReturnValue(OBSERVED); });
afterEach(() => { vi.restoreAllMocks(); });

describe("reused-core replay: explicit expired legacy refusal is independent of healthy products", () => {
  it("keeps fresh public quotes readable while the actual legacy route refuses unchanged 48-hour-old report/claim/data", async () => {
    const f = await reusedFixture();
    const view = await pinPublicSnapshot(f.env);
    const report = await loadV213FreshTop20Report(f.env, parseQuery("Top20"));
    expect(view.integrity).toBe("sealed"); expect(view.runId).toBe(SYNTHETIC_RUN); expect(view.sealRunId).toBe(GLOBAL_RUN);
    expect(typeof report).toBe("string");
    expect(await probeLegacyReport(view, f.env, report)).toEqual({ expiredRefused: true, originalGeneratedAt: SYNTHETIC_STAMP, pipelineFresh: true });
    expect(await loadDelayedQuote(view, "SIVE.ST")).toMatchObject({ price: 32.78, asof: GLOBAL_STAMP });
    expect(await view.text(["v213:top20-report:latest"])).toBe(f.reportRaw);
    expect(JSON.parse((await view.text(["v213:activation-claim"]))!).claimed_at).toBe(SYNTHETIC_STAMP);
    expect(JSON.parse(f.kv.values.get("snapshot:current")!).public_data_as_of).toBe(SYNTHETIC_STAMP);
    expect(await probeLegacyReport({ ...view }, f.env, report)).toEqual({ expiredRefused: false, originalGeneratedAt: null, pipelineFresh: false });
    expect(f.privateKv.reads + f.securityKv.reads).toBe(0);
  });

  it("does not excuse stale global liveness or a malformed legacy report as legitimate expired-core reuse", async () => {
    const f = await reusedFixture();
    const view = await pinPublicSnapshot(f.env);
    vi.mocked(Date.now).mockReturnValue(OBSERVED + 3 * 3600_000);
    const report = await loadV213FreshTop20Report(f.env, parseQuery("Top20"));
    expect(await probeLegacyReport(view, f.env, report)).toMatchObject({ expiredRefused: false, pipelineFresh: false });
    vi.mocked(Date.now).mockReturnValue(OBSERVED);
    const broken = await reusedFixture(true);
    const brokenView = await pinPublicSnapshot(broken.env);
    const refusal = await loadV213FreshTop20Report(broken.env, parseQuery("Top20"));
    expect(await probeLegacyReport(brokenView, broken.env, refusal)).toMatchObject({ expiredRefused: false, originalGeneratedAt: null });
  });
});
