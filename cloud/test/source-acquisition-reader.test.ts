/// <reference types="node" />
/** Actual Python CLI outputs, synthetic HTTP/clock fixtures only; no live or native KV qualification. */
import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";
import { parseQuery } from "../src/core";
import { parseV212Top20Report, v212Top20ReportAnswer, type V212Top20Report } from "../src/v212/top20-report";
import { parseV213Top20Report, v213Top20ReportAnswer, type V213Top20Report } from "../src/v213/top20-report";
import { v213Top20LineAnswer } from "../src/v213/top20-presentation";
import { asKv, MemoryKv } from "./fake-kv";

const vectors = JSON.parse(readFileSync(new URL("../../tests/fixtures/source-acquisition-reports.json", import.meta.url), "utf8")) as {
  scope: string; cases: Record<string, { v212: V212Top20Report; v213: V213Top20Report; source_time: string; cli_http_calls: number }>;
};
function runtime(name: string, kv = new MemoryKv()) {
  const data = vectors.cases[name]!;
  vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(new Date(data.v212.generated_at));
  kv.values.set("snapshot:current", JSON.stringify({ run_id: "clock-a" }));
  kv.values.set("snapshot:clock-a:v212:top20-report:latest", JSON.stringify(data.v212));
  kv.values.set("snapshot:clock-a:v213:top20-report:latest", JSON.stringify(data.v213));
  kv.values.set("snapshot:clock-a:last_successful_pipeline_timestamp", data.v212.generated_at);
  return { data, kv, env: { PUBLIC_CACHE: asKv(kv), TENANT_PRIVATE_CACHE: asKv(new MemoryKv()), EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()) } };
}
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

describe("actual CLI acquisition metadata at pinned readers", () => {
  it.each(["fresh", "stale"])("preserves original %s acquisition fields, not assembly time", name => {
    const data = vectors.cases[name]!;
    expect(data.cli_http_calls).toBe(0);
    const five = parseV212Top20Report(data.v212)!; const seven = parseV213Top20Report(data.v213)!;
    expect(five.schema_version).toBe(2); expect(five.records[19]!.retrieved_at).toBe(data.source_time);
    expect(seven.records[19]!.retrieved_at).toBe(data.source_time);
    expect(data.source_time).not.toBe(five.generated_at);
  });
  it("refuses unknown populated market clocks instead of dropping values or falling back", async () => {
    const { env, data } = runtime("unknown");
    expect(data.v212.records[0]!.long_term_return_pct).toBe(12);
    expect(parseV212Top20Report(data.v212)).toBeNull(); expect(parseV213Top20Report(data.v213)).toBeNull();
    expect(await v212Top20ReportAnswer(env, parseQuery("Top20"))).toContain("尚未");
    expect(await v213Top20LineAnswer(env, parseQuery("Top20"))).toContain("no five-field fallback");
  });
  it.each(["v212", "v213", "flex"])("refuses three-hour-old source data at the actual %s pinned reader", async kind => {
    const { env } = runtime("stale"); const query = parseQuery("Top20");
    const result = kind === "v212" ? await v212Top20ReportAnswer(env, query) : kind === "v213" ? await v213Top20ReportAnswer(env, query) : await v213Top20LineAnswer(env, query);
    expect(result).toContain("retrieval time is stale");
  });
  it("retains valid fresh synthetic data through both text and bound card readers", async () => {
    const { env } = runtime("fresh"); const query = parseQuery("Top20");
    expect(await v212Top20ReportAnswer(env, query)).toContain("T19");
    expect(await v213Top20ReportAnswer(env, query)).toContain("T19");
    const cards = await v213Top20LineAnswer(env, query);
    expect(Array.isArray(cards)).toBe(true); expect(JSON.stringify(cards)).toContain("深度化分析");
  });
  it.each(["row_clock", "value", "missing", "digest", "status", "future", "calendar", "coercion", "private"])("rejects %s metadata mutation on the last displayed row", mode => {
    const doc = structuredClone(vectors.cases.fresh!.v212); const row = doc.records[19]!;
    const clocks = row.source_acquisition!;
    if (mode === "row_clock") row.retrieved_at = doc.generated_at;
    if (mode === "value") clocks.profit_summary.value = "不同摘要";
    if (mode === "missing") Reflect.deleteProperty(clocks, "industry");
    if (mode === "digest") clocks.profit_summary.evidence_sha256 = "bad";
    if (mode === "status") clocks.profit_summary.status = "UNAVAILABLE";
    if (mode === "future") clocks.profit_summary.retrieved_at = "9999-01-01T00:00:00Z";
    if (mode === "calendar") clocks.profit_summary.retrieved_at = "2026-02-31T00:00:00Z";
    if (mode === "coercion") Reflect.set(clocks.profit_summary, "retrieved_at", [row.retrieved_at]);
    if (mode === "private") Reflect.set(clocks, "private_extension", "SYNTHETIC_PRIVATE_MARKER");
    expect(parseV212Top20Report(doc)).toBeNull();
  });
  it("keeps legacy parsing explicit without granting new receipt provenance", () => {
    const doc = structuredClone(vectors.cases.fresh!.v212);
    doc.schema_version = 1; delete doc.calculation_cutoff;
    for (const row of doc.records) { row.schema_version = 1; delete row.source_acquisition; }
    expect(parseV212Top20Report(doc)?.schema_version).toBe(1);
  });
  it("does not switch to a newer pipeline stamp after pinning the five-field report", async () => {
    class SwitchingKv extends MemoryKv {
      reads = 0;
      override async get<T = string>(key: string, type?: "text" | "json"): Promise<T | string | null> {
        if (key === "snapshot:current") this.reads++;
        const value = await super.get<T>(key, type);
        if (key === "snapshot:clock-a:v212:top20-report:latest") this.values.set("snapshot:current", JSON.stringify({ run_id: "clock-b" }));
        return value;
      }
    }
    const kv = new SwitchingKv(); const { env, data } = runtime("fresh", kv);
    kv.values.set("snapshot:clock-a:last_successful_pipeline_timestamp", new Date(Date.now() - 3 * 3600_000).toISOString());
    kv.values.set("snapshot:clock-b:last_successful_pipeline_timestamp", data.v212.generated_at);
    expect(await v212Top20ReportAnswer(env, parseQuery("Top20"))).toContain("retrieval time is stale");
    expect(kv.reads).toBe(1);
  });
});
