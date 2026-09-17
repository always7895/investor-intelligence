import { it } from "vitest";
import { readFileSync, writeFileSync } from "node:fs";
import { pinPublicSnapshot } from "../src/v213/public-snapshot";
import { loadV213FreshTop20Report, getV213ReportReference } from "../src/v213/top20-report";
import { handleGlobalEquityLookup } from "../src/v213/global-equity-lookup";
import { parseQuery } from "../src/core";
import { asKv, MemoryKv } from "./fake-kv";
import type { ParsedQuery } from "../src/core";

const RUN = "20260917T055736Z-3bf287ab34fd";
const P = `../../state/v213-snapshots/${RUN}`;

function env() {
  const objects = JSON.parse(readFileSync(new URL(`${P}/objects.json`, import.meta.url), "utf-8")) as Record<string, string>;
  const pointer = readFileSync(new URL(`${P}/pointer.raw.json`, import.meta.url), "utf-8").trim();
  const kv = new MemoryKv();
  for (const [k, v] of Object.entries(objects)) kv.values.set(k, v);
  kv.values.set("snapshot:current", pointer);
  return {
    PUBLIC_CACHE: asKv(kv),
    TENANT_PRIVATE_CACHE: asKv(new MemoryKv()),
    EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()),
    V213_FIELD_LOCALE: "en",
    V213_LINE_PRESENTATION: "text",
    V21_TOP20_MAX_AGE_SECONDS: "7200",
  } as unknown as Parameters<typeof handleGlobalEquityLookup>[0];
}

const out: Record<string, unknown> = { run: RUN, wall: new Date().toISOString() };

it("TASK #26 live smoke probe on freshly synced run", async () => {
  // 1) fresh Top20, no stale message
  const e = env();
  const q20: ParsedQuery = { intent: "ranking", ticker: null, period: "weekly", referenceId: null, normalized: "Top 20 bottleneck" };
  const report = await loadV213FreshTop20Report(e, q20);
  out.top20_is_stale_string = typeof report === "string";
  out.top20_contains_stale_text = typeof report === "string" ? /資料已過期/.test(report) : false;
  if (typeof report !== "string") {
    out.top20_records = (report as { records: { rank: number; ticker: string }[] }).records.map(r => ({ rank: r.rank, ticker: r.ticker }));
    out.top20_ref = getV213ReportReference(report as never);
    // SIVE
    const sive = await handleGlobalEquityLookup(e, { intent: "global_equity_lookup", ticker: null, period: "weekly", referenceId: null, normalized: "SIVE" });
    const siveJson = JSON.stringify(sive);
    out.sive_source_sealed_unadmitted = siveJson.includes("sealed_snapshot:unadmitted_symbol");
    out.sive_source_not_unsealed = !siveJson.includes("unsealed_or_missing");
    // AAOI
    const aaoi = await handleGlobalEquityLookup(e, { intent: "global_equity_lookup", ticker: null, period: "weekly", referenceId: null, normalized: "AAOI" });
    const aaoiJson = JSON.stringify(aaoi);
    out.aaoi_source_sealed_unadmitted = aaoiJson.includes("sealed_snapshot:unadmitted_symbol");
    out.aaoi_source_not_unsealed = !aaoiJson.includes("unsealed_or_missing");
    // ZZZZNOTEXIST must NOT be hijacked by equity lookup
    const z = parseQuery("ZZZZNOTEXIST");
    out.zzz_intent = z.intent;
    const zOut = await handleGlobalEquityLookup(e, z);
    out.zzz_equity_hijack = zOut !== null;
  }
  writeFileSync(new URL("../../data/cache/probe-live-26.json", import.meta.url), JSON.stringify(out, null, 2));
});