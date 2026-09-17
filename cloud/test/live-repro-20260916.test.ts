// Disposable live replay: real pinned reader + real freshness gate on current
// local bytes of the latest sealed run against the 7200-second production env.
import { it, expect, vi, afterAll } from "vitest";
import { readFileSync } from "node:fs";
import { pinPublicSnapshot } from "../src/v213/public-snapshot";
import { loadV213FreshTop20Report, getV213ReportReference } from "../src/v213/top20-report";
import { asKv, MemoryKv } from "./fake-kv";
import type { ParsedQuery } from "../src/core";

const RUN_DIR = "20260917T043132Z-3233b3055b9d";
const objects = JSON.parse(readFileSync(new URL(`../../state/v213-snapshots/${RUN_DIR}/objects.json`, import.meta.url), "utf-8")) as Record<string, string>;
const pointer = readFileSync(new URL(`../../state/v213-snapshots/${RUN_DIR}/pointer.raw.json`, import.meta.url), "utf-8").trim();

function env() {
  const kv = new MemoryKv();
  for (const [key, value] of Object.entries(objects)) kv.values.set(key, value);
  kv.values.set("snapshot:current", pointer);
  return {
    PUBLIC_CACHE: asKv(kv),
    TENANT_PRIVATE_CACHE: asKv(new MemoryKv()),
    EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()),
    V213_FIELD_LOCALE: "bilingual",
    V21_TOP20_MAX_AGE_SECONDS: "7200",
  } as never;
}

afterAll(() => { vi.useRealTimers(); });

it("live replay: pinned sealed snapshot resolves and serves fresh Top20", async () => {
  // The replay run is pinned in time: evaluate the freshness gate inside the
  // run's own 7200s window (real wall clock will have moved past it later).
  // Run 3233b3055b9d is also the first run published under the current
  // two-anchor freshness-policy binding that the loader now requires.
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-09-17T04:36:32Z"));
  const e = env();
  const view = await pinPublicSnapshot(e);
  console.log("PIN:", JSON.stringify({ runId: view.runId, kind: view.kind, integrity: view.integrity }));
  expect(view.kind).toBe("snapshot");
  expect(view.integrity).toBe("sealed");
  const q: ParsedQuery = { intent: "ranking", ticker: null, period: "weekly", referenceId: null, normalized: "Top 20 bottleneck" };
  const report = await loadV213FreshTop20Report(e, q);
  if (typeof report === "string") {
    console.log("STALE_OR_ERROR_STRING:", report.slice(0, 200));
  }
  expect(typeof report).toBe("object");
  const recs = (report as { records: { rank: number; ticker: string }[] }).records;
  console.log("RECORDS:", JSON.stringify(recs.map((r) => [r.rank, r.ticker])));
  console.log("REF:", JSON.stringify(getV213ReportReference(report as never)));
});