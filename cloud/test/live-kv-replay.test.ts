// Operator-run reader replay over Production public KV bytes (skipped in CI and normal runs).
// scripts/deploy_production_gate.ps1 -Phase post downloads the live pointer, seal and sealed objects read-only,
// sets V213_LIVE_REPLAY_DIR / V213_LIVE_REPLAY_OUT, and reads the result this test writes. The previous gate read
// a result file that no test wrote any more, so a stale Production snapshot could still pass.
import { describe, expect, it, vi } from "vitest";
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import type { ParsedQuery } from "../src/core";
import { pinPublicSnapshot } from "../src/v213/public-snapshot";
import { getV213ReportReference, loadV213FreshTop20Report } from "../src/v213/top20-report";
import { MACRO_PRODUCT_KEY } from "../src/v213/macro-industry-product";
import { validatePotentialRanking } from "../src/v213/potential-ranking";
import { asKv, MemoryKv } from "./fake-kv";

const dir = process.env.V213_LIVE_REPLAY_DIR;
const out = process.env.V213_LIVE_REPLAY_OUT;
const query: ParsedQuery = { intent: "ranking", ticker: null, period: "weekly", referenceId: null, normalized: "Top 20" };

describe.skipIf(!dir || !out)("live public KV reader replay (operator gate only)", () => {
  it("replays the Production sealed snapshot through the actual readers at the real clock", async () => {
    vi.stubGlobal("fetch", vi.fn(() => { throw new Error("LIVE_REPLAY_NETWORK_FORBIDDEN"); }));
    const index = JSON.parse(readFileSync(join(dir!, "index.json"), "utf8").replace(/^﻿/, "")) as Record<string, string>;
    const kv = new MemoryKv();
    for (const [key, file] of Object.entries(index)) kv.values.set(key, readFileSync(join(dir!, file), "utf8"));
    const forbidden = new MemoryKv();
    const env = { PUBLIC_CACHE: asKv(kv), TENANT_PRIVATE_CACHE: asKv(forbidden), EPHEMERAL_SECURITY_CACHE: asKv(forbidden),
      V213_FIELD_LOCALE: "bilingual", V21_TOP20_MAX_AGE_SECONDS: process.env.V213_LIVE_REPLAY_MAX_AGE ?? "7200" };
    const view = await pinPublicSnapshot(env as never);
    const report = await loadV213FreshTop20Report(env as never, query);
    const fresh = !!report && typeof report === "object";
    const overview = view.integrity === "sealed" ? await view.json<Record<string, unknown>>([MACRO_PRODUCT_KEY]) : null;
    const ranking = validatePotentialRanking(overview?.potential_ranking);
    const result = {
      fresh, integrity: view.integrity, run_id: view.integrity === "sealed" ? view.runId : null,
      reference: fresh ? getV213ReportReference(report as never) : null,
      refusal: fresh ? null : typeof report === "string" ? report.slice(0, 200) : "NO_REPORT",
      macro_overview_sealed: !!overview, potential_ranking_records: ranking?.records.length ?? 0,
      evaluated_at: new Date().toISOString(),
    };
    writeFileSync(out!, JSON.stringify(result, null, 1));
    vi.unstubAllGlobals();
    expect(result.integrity).toBe("sealed");
  });
});
