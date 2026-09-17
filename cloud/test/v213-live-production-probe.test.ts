import { it, expect } from "vitest";
import { readFileSync, writeFileSync } from "node:fs";
import { pinPublicSnapshot } from "../src/v213/public-snapshot";
import { loadV213FreshTop20Report, getV213ReportReference } from "../src/v213/top20-report";
import { handleGlobalEquityLookup } from "../src/v213/global-equity-lookup";
import { v213PublicLineAnswer } from "../src/v213/rich-menu";
import { parseQuery } from "../src/core";
import { asKv, MemoryKv } from "./fake-kv";
import type { ParsedQuery } from "../src/core";

const RUN = "20260917T083454Z-37bd9d27e3ef";
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
    V213_FIELD_LOCALE: "bilingual",
    V213_LINE_PRESENTATION: "text",
    V21_TOP20_MAX_AGE_SECONDS: "7200",
  } as unknown as Parameters<typeof v213PublicLineAnswer>[0];
}

const out: Record<string, unknown> = { run: RUN, wall: new Date().toISOString() };

it("production live acceptance for Macro TOP5 and Top20 invariants", async () => {
  const e = env();

  // 1) Test LINE "宏觀產業分析"
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
  out.macro_reply_admitted = true;
  out.macro_has_no_shortfall = !macroStr.includes("MACRO_TOP5_SHORTFALL");

  // 2) Test "TOP5產業總覽"
  const top5Reply = await v213PublicLineAnswer(e, parseQuery("TOP5產業總覽 文字"));
  expect(top5Reply).not.toBeNull();
  const top5Str = JSON.stringify(top5Reply);
  expect(top5Str).not.toContain("MACRO_TOP5_SHORTFALL");
  expect(top5Str).toContain("TOP5產業總覽");
  out.top5_overview_admitted = true;

  // 3) Test "TOP20"
  const q20: ParsedQuery = { intent: "ranking", ticker: null, period: "weekly", referenceId: null, normalized: "Top 20" };
  const report = await loadV213FreshTop20Report(e, q20);
  expect(typeof report).toBe("object");
  const recs = (report as { records: { rank: number; ticker: string }[] }).records;
  expect(recs).toHaveLength(2);
  expect(recs[0]!.ticker).toBe("GEV");
  expect(recs[1]!.ticker).toBe("6501");
  out.top20_records = recs;

  // 4) Test "宏觀資料說明"
  const macroDataDesc = await v213PublicLineAnswer(e, parseQuery("宏觀資料說明"));
  expect(macroDataDesc).not.toBeNull();
  const macroDescStr = JSON.stringify(macroDataDesc);
  expect(macroDescStr).toContain("GDP");
  expect(macroDescStr).toContain("CPI");
  expect(macroDescStr).toContain("利率");
  expect(macroDescStr).toContain("匯率");
  out.macro_data_desc_ok = true;

  // 5) SIVE / AAOI fail-closed
  const sive = await handleGlobalEquityLookup(e, { intent: "global_equity_lookup", ticker: null, period: "weekly", referenceId: null, normalized: "SIVE" });
  expect(JSON.stringify(sive)).toContain("sealed_snapshot:unadmitted_symbol");
  const aaoi = await handleGlobalEquityLookup(e, { intent: "global_equity_lookup", ticker: null, period: "weekly", referenceId: null, normalized: "AAOI" });
  expect(JSON.stringify(aaoi)).toContain("sealed_snapshot:unadmitted_symbol");

  // 6) Invalid ticker
  const z = parseQuery("ZZZZNOTEXIST");
  const zOut = await handleGlobalEquityLookup(e, z);
  expect(zOut).toBeNull();

  writeFileSync(new URL("../../data/cache/probe-live-macro.json", import.meta.url), JSON.stringify(out, null, 2));
});
