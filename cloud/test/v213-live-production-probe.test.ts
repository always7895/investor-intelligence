import { afterEach, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { loadV213FreshTop20Report } from "../src/v213/top20-report";
import { INSUFFICIENT_EVIDENCE_MESSAGE } from "../src/v213/bottleneck-report";
import { handleGlobalEquityLookup } from "../src/v213/global-equity-lookup";
import { v213PublicLineAnswer } from "../src/v213/rich-menu";
import { parseQuery } from "../src/core";
import { asKv, MemoryKv } from "./fake-kv";
import type { ParsedQuery } from "../src/core";

/**
 * TASK0 Phase-1D: Sealed snapshot replay — in-memory contract.
 *
 * The fixture is a byte-identical copy of the accepted local run
 * 20260917T092410Z-d9f86bda2053 (see fixtures/task0-phase1d/README.md).
 * Clocks: each case sets the system Date deterministically (toFake ["Date"]
 * only) and restores the real runner clock afterwards. The runner clock is
 * never an input to pass/fail.
 * No writes: this test never writes to data/cache or the production snapshot
 * dir; all mutations are in-memory MemoryKv copies.
 */
const FX = "fixtures/task0-phase1d";
const ASSEMBLY_AT = Date.parse("2026-09-17T09:24:10Z"); // assembly anchor (single source)

function fixtureObjects(): Record<string, string> {
  return JSON.parse(readFileSync(new URL(`./${FX}/objects.json`, import.meta.url), "utf-8"));
}
function fixturePointer(): string {
  return readFileSync(new URL(`./${FX}/pointer.raw.json`, import.meta.url), "utf-8").trim();
}

type LineEnv = Parameters<typeof v213PublicLineAnswer>[0];

function envAt(offsetSeconds: number, mutate?: (kv: MemoryKv) => void): LineEnv {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(ASSEMBLY_AT + offsetSeconds * 1000);
  const kv = new MemoryKv();
  for (const [k, v] of Object.entries(fixtureObjects())) kv.values.set(k, v);
  kv.values.set("snapshot:current", fixturePointer());
  mutate?.(kv);
  return {
    PUBLIC_CACHE: asKv(kv),
    TENANT_PRIVATE_CACHE: asKv(new MemoryKv()),
    EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()),
    V213_FIELD_LOCALE: "bilingual",
    V213_LINE_PRESENTATION: "text",
    V21_TOP20_MAX_AGE_SECONDS: "7200",
  } as unknown as LineEnv;
}

const RANKING: ParsedQuery = { intent: "ranking", ticker: null, period: "weekly", referenceId: null, normalized: "Top 20" };

function admit(report: Awaited<ReturnType<typeof loadV213FreshTop20Report>>, label: string): void {
  expect(report, `${label}: expected an admitted report object`).not.toBeNull();
  expect(typeof report, `${label}: expected object, got ${typeof report}`).toBe("object");
  const recs = ((report as { records?: { rank: number; ticker: string }[] }).records ?? []);
  expect(recs, `${label}: two admitted records`).toHaveLength(2);
  expect(recs[0]).toMatchObject({ rank: 1, ticker: "GEV" });
  expect(recs[1]).toMatchObject({ rank: 2, ticker: "6501" });
}

afterEach(() => vi.useRealTimers());

it("Top20 freshness boundary (deterministic Date only): 3600s / 7199s / 7200s admitted; 7201s stale", async () => {
  const e1 = envAt(3600);
  admit(await loadV213FreshTop20Report(e1 as never, RANKING), "age 3600s");
  vi.useRealTimers();

  const e2 = envAt(7199);
  admit(await loadV213FreshTop20Report(e2 as never, RANKING), "age 7199s");
  vi.useRealTimers();

  const e3 = envAt(7200);
  admit(await loadV213FreshTop20Report(e3 as never, RANKING), "age 7200s (inclusive bound)");
  vi.useRealTimers();

  const e4 = envAt(7201);
  const stale = await loadV213FreshTop20Report(e4 as never, RANKING);
  expect(typeof stale, "age 7201s must be a closed string, not an object").toBe("string");
  if (typeof stale === "string") {
    expect(stale).toContain("fresh public data is required");
  }
  vi.useRealTimers();
});

it("seal/object tamper (in-memory copy) is rejected fail-closed", async () => {
  const e = envAt(3600, (kv) => {
    const key = "snapshot:20260917T092410Z-d9f86bda2053:v213:top20-report:latest";
    const body = kv.values.get(key);
    if (typeof body !== "string") throw new Error(`fixture missing: ${key}`);
    // Corrupt one character inside the sealed object body (exact-byte seal will fail).
    kv.values.set(key, `X${body.slice(1)}`);
  });
  const out = await loadV213FreshTop20Report(e as never, RANKING);
  expect(out, "tampered seal must not produce a report object").not.toBe(null);
  expect(typeof out, "closed reason string expected").toBe("string");
  if (typeof out === "string") {
    expect(out).toBe(INSUFFICIENT_EVIDENCE_MESSAGE);
  }
});

it("sealed snapshot replay (fresh clock): Macro TOP5, TOP5, query gates and fail-closed grid", async () => {
  const e = envAt(3600);

  // 1) LINE text "宏觀產業分析"
  const macroReply = await v213PublicLineAnswer(e, parseQuery("宏觀產業分析 文字"));
  expect(macroReply).not.toBeNull();
  const macroStr = JSON.stringify(macroReply);
  expect(macroStr).not.toContain("MACRO_TOP5_SHORTFALL");
  expect(macroStr).not.toContain("TOP5 宏觀產業總覽准入門檻未達成");
  expect(macroStr).toContain("TOP5產業總覽");
  expect(macroStr).toContain("先進封裝與高頻寬記憶體");
  expect(macroStr).toContain("高速光通訊與 CPO");
  expect(macroStr).toContain("電網與電力基礎設施");
  expect(macroStr).toContain("半導體前段設備與關鍵特用化學材料");
  expect(macroStr).toContain("先進散熱與液冷系統");

  // 2) "TOP5產業總覽"
  const top5Reply = await v213PublicLineAnswer(e, parseQuery("TOP5產業總覽 文字"));
  expect(top5Reply).not.toBeNull();
  expect(JSON.stringify(top5Reply)).not.toContain("MACRO_TOP5_SHORTFALL");
  expect(JSON.stringify(top5Reply)).toContain("TOP5產業總覽");

  // 3) Top20 admitted (same fixture, fresh clock)
  admit(await loadV213FreshTop20Report(e as never, RANKING), "replay Top20");

  // 4) "宏觀資料說明"
  const macroDataDesc = await v213PublicLineAnswer(e, parseQuery("宏觀資料說明"));
  expect(macroDataDesc).not.toBeNull();
  const descStr = JSON.stringify(macroDataDesc);
  for (const needle of ["GDP", "CPI", "利率", "匯率"]) expect(descStr).toContain(needle);

  // 5) SIVE / AAOI / 6508 / ENR fail-closed
  for (const ticker of ["SIVE", "AAOI", "6508", "ENR"]) {
    const out = await handleGlobalEquityLookup(e, { intent: "global_equity_lookup", ticker: null, period: "weekly", referenceId: null, normalized: ticker });
    expect(JSON.stringify(out)).toContain("sealed_snapshot:unadmitted_symbol");
  }

  // 6) Invalid ticker -> null (routes to general_qa; not an equity hijack)
  expect(await handleGlobalEquityLookup(e, parseQuery("ZZZZNOTEXIST"))).toBeNull();
});