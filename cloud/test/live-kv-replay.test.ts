// Operator-run reader replay over sealed public KV bytes (skipped in CI and normal runs).
// scripts/deploy_production_gate.ps1 -Phase post downloads the live pointer, seal and sealed objects read-only;
// scripts/stage_sealed_replay.py stages a locally sealed run before any KV write. Both set V213_LIVE_REPLAY_DIR /
// V213_LIVE_REPLAY_OUT and read the result this test writes. The previous gate read a result file that no test
// wrote any more, so a stale Production snapshot could still pass.
import { describe, expect, it, vi } from "vitest";
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { parseQuery, type ParsedQuery } from "../src/core";
import { pinPublicSnapshot } from "../src/v213/public-snapshot";
import { getV213ReportReference, loadV213FreshTop20Report } from "../src/v213/top20-report";
import { INSUFFICIENT_EVIDENCE_MESSAGE } from "../src/v213/bottleneck-report";
import { buildV213Top20Messages, v213Top20LineAnswer } from "../src/v213/top20-presentation";
import { MACRO_PRODUCT_KEY } from "../src/v213/macro-industry-product";
import { validatePotentialRanking } from "../src/v213/potential-ranking";
import { parseV21Top20 } from "../src/v21/top20";
import { parseV212Top20Report } from "../src/v212/top20-report";
import { resolveGlobalIdentity } from "../src/v213/global-identity";
import { loadIdentityCatalogForQuery } from "../src/v213/identity-shards";
import { loadListingPrice } from "../src/v213/market-observations";
import { buildBottleneckTop20Messages, buildIndustryExplosionMessages, loadBottleneckV3 } from "../src/v213/bottleneck-v3";
import { asKv, MemoryKv } from "./fake-kv";

// Bumped whenever the fields below change, so the gate and the staged replay can refuse an older reader.
const READER_CONTRACT_VERSION = "v213-reader-replay-v2";
const dir = process.env.V213_LIVE_REPLAY_DIR;
const out = process.env.V213_LIVE_REPLAY_OUT;
const query: ParsedQuery = { intent: "ranking", ticker: null, period: "weekly", referenceId: null, normalized: "Top 20" };

const messageCount = (answer: unknown): number => Array.isArray(answer) ? answer.length : 0;

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
    // The LINE answers users get (flex and text), and the broadcast's own pre-push checks (v21 order + build);
    // the push itself needs an owner and is never replayed.
    const flex = await v213Top20LineAnswer(env as never, parseQuery("Top20"));
    const text = await v213Top20LineAnswer(env as never, parseQuery("Top20 文字"));
    const v21 = view.integrity === "sealed" ? parseV21Top20(await view.json<unknown>(["v21:top20:latest"])) : null;
    const v212 = view.integrity === "sealed" ? parseV212Top20Report(await view.json<unknown>(["v212:top20-report:latest"])) : null;
    let broadcastReady = false;
    if (fresh && v21) {
      const rows = (report as { records: { ticker: string }[] }).records;
      broadcastReady = rows.every((row, position) => row.ticker === v21[position]?.ticker)
        && messageCount(buildV213Top20Messages(report as never, "bilingual", "flex")) > 0
        && messageCount(buildV213Top20Messages(report as never, "bilingual", "text")) > 0;
    }
    const records = fresh ? (report as { records: { test_only_admission?: unknown }[] }).records : [];
    const bottleneck = await loadBottleneckV3(view);
    // Identity lookups through the sealed shards (the LINE stock/options entry): status and resolved listing.
    const identityProbe: Record<string, string> = {};
    // Prices the lookup would show for listings outside the watch universe (market price shards).
    const priceProbe: Record<string, string> = {};
    for (const probe of ["SIVE", "NVDA", "2330", "台積電", "4062.T", "005930.KS", "SOI.PA", "IQE.L", "輝達", "2059"]) {
      const resolution = resolveGlobalIdentity(await loadIdentityCatalogForQuery(view, probe), probe);
      identityProbe[probe] = resolution.status === "RESOLVED" ? `RESOLVED:${resolution.record.venue}:${resolution.record.symbol}` : resolution.status;
      if (resolution.status === "RESOLVED") {
        const price = await loadListingPrice(view, resolution.record);
        priceProbe[probe] = price ? `${price.price} ${price.currency} @${price.asof.slice(0, 10)}` : "NO_PRICE";
      }
    }
    const result = {
      reader_contract_version: READER_CONTRACT_VERSION,
      fresh, integrity: view.integrity, run_id: view.integrity === "sealed" ? view.runId : null,
      reference: fresh ? getV213ReportReference(report as never) : null,
      refusal: fresh ? null : typeof report === "string" ? report.slice(0, 200) : "NO_REPORT",
      refusal_is_insufficient: report === INSUFFICIENT_EVIDENCE_MESSAGE,
      top20_records: records.length,
      test_only_admission: fresh ? records[0]?.test_only_admission ?? null : null,
      report_generated_at: fresh ? (report as { generated_at: string }).generated_at : null,
      line_flex_messages: messageCount(flex), line_text_messages: messageCount(text),
      v21_records: v21?.length ?? 0, v212_records: v212?.records.length ?? 0, broadcast_ready: broadcastReady,
      identity_probe: identityProbe, price_probe: priceProbe,
      bottleneck_v3_zh_named: bottleneck ? bottleneck.top.filter(entry => entry.name_zh).length : 0,
      bottleneck_v3_records: bottleneck?.top.length ?? 0, bottleneck_v3_flex: bottleneck ? messageCount(buildBottleneckTop20Messages(bottleneck, "flex")) : 0,
      industry_v3_flex: bottleneck ? messageCount(buildIndustryExplosionMessages(bottleneck, "flex")) : 0,
      macro_overview_sealed: !!overview, potential_ranking_records: ranking?.records.length ?? 0,
      evaluated_at: new Date().toISOString(),
    };
    writeFileSync(out!, JSON.stringify(result, null, 1));
    vi.unstubAllGlobals();
    expect(result.integrity).toBe("sealed");
  });
});
