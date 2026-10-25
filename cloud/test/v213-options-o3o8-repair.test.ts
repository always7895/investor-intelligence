// Port ONLY the two BATCH04 quarantined option defects; sealed synthetic fixtures, no rights/catalog changes or sends.
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import fixture from "../../tests/fixtures/identity-batch04-functional.json";
import { parseQuery } from "../src/core";
import { assertLineMessages, type LineOutboundMessage } from "../src/line-messages";
import type { CoveredCallCycle } from "../src/v213/covered-call";
import { identityNameBucket } from "../src/v213/identity-shards";
import { loadDetailedOptionObservation } from "../src/v213/market-observations";
import { pinPublicSnapshot } from "../src/v213/public-snapshot";
import { v213PublicLineAnswer } from "../src/v213/rich-menu";
import { asKv, MemoryKv } from "./fake-kv";

const diagnostic = vi.hoisted(() => ({ permitSynthetic: false }));
vi.mock("../src/v213/public-options-admission", async importOriginal => {
  const real = await importOriginal<typeof import("../src/v213/public-options-admission")>();
  return { ...real, admitPublicOption: (subject: CoveredCallCycle, now?: number) =>
    diagnostic.permitSynthetic && subject?.source === "Synthetic delayed observation"
      ? { ok: true, provider_id: "synthetic-test-only-not-in-catalog" }
      : real.admitPublicOption(subject, now) };
});
const SEAL = `snapshot:${fixture.run}:v213:snapshot-seal:v1`;
const OPTIONS = "v213:options:v2";
const sha = async (body: string) => Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(body))),
  n => n.toString(16).padStart(2, "0")).join("");

async function environment(style: "text" | "flex", replacements: Record<string, unknown>) {
  const kv = new MemoryKv();
  for (const [key, body] of Object.entries(fixture.values)) kv.values.set(key, body);
  const seal = JSON.parse(kv.values.get(SEAL)!);
  for (const [logical, value] of Object.entries(replacements)) {
    const body = JSON.stringify(value), digest = await sha(body);
    seal.objects[logical] = { sha256: digest, utf8_bytes: new TextEncoder().encode(body).length };
    kv.values.set("blob:v1:" + digest, body);
  }
  const body = JSON.stringify(seal);
  kv.values.set(SEAL, body);
  const pointer = JSON.parse(kv.values.get("snapshot:current")!);
  pointer.seal_sha256 = await sha(body);
  kv.values.set("snapshot:current", JSON.stringify(pointer));
  return { kv, env: { PUBLIC_CACHE: asKv(kv), TENANT_PRIVATE_CACHE: asKv(new MemoryKv()),
    EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()), V213_LINE_PRESENTATION: style, V21_TOP20_MAX_AGE_SECONDS: "7200" } };
}
function strings(value: unknown): string[] {
  if (!value || typeof value !== "object") return [];
  if (Array.isArray(value)) return value.flatMap(strings);
  const obj = value as Record<string, unknown>;
  return [...(obj.type === "text" && typeof obj.text === "string" ? [obj.text] : []), ...Object.values(obj).flatMap(strings)];
}
async function answer(f: Awaited<ReturnType<typeof environment>>, query: string) {
  const messages = await v213PublicLineAnswer(f.env as never, parseQuery(query)) as LineOutboundMessage[];
  expect(Array.isArray(messages)).toBe(true);
  assertLineMessages(messages);
  expect(messages[0]?.type).toBe(f.env.V213_LINE_PRESENTATION);
  return strings(messages).join("\n");
}
function diagnosticCycle(ticker = "SIVE.ST", currency: "USD" | "SEK" = "USD", jurisdiction?: string): CoveredCallCycle {
  return { ticker, currency, ...(jurisdiction === undefined ? {} : { jurisdiction }), strategy: "COVERED_CALL",
    expiry: "2026-10-06", dte: 21, spot: 300, multiplier: 100, quote_basis: "delayed",
    timestamp: fixture.stamp, source: "Synthetic delayed observation", provenance: "https://synthetic.invalid/options",
    rights_status: "unadmitted_third_party", suggestions: [{
      role: "HIGH_STRIKE", strike: 330, bid: 2, ask: 2.1, mid: 2.05, limit_price: 2.05,
      premium_per_contract: 205, period_yield: 2.05 / 300, annualized_yield: 2.05 / 300 * 365 / 21,
      upside_to_strike: 330 / 300 - 1, delta: 0.18, delta_basis: "QUOTED_IV", iv: 0.4,
      oi: 900, volume: 50, spread_pct: 0.0488,
    }] };
}
function optionDocument(cycle: CoveredCallCycle) {
  return { [OPTIONS]: { schema: "v213-options-v2", generated_at: fixture.stamp, options: { [cycle.ticker]: { monthly: cycle } } } };
}
function ambiguityObjects(count: number) {
  const source = fixture.document.symbol_shards.A;
  const rows = Array.from({ length: count }, (_, i) => ["A" + String(i).padStart(2, "0"), "NASDAQ STOCKHOLM", "SWEDEN", "Sweden",
    "\u{1f6f0}".repeat(120) + String(i), null, "COMMON_STOCK", "SEK", 4, ["軌道", "WIKIDATA_LABEL"]]);
  const bucket = identityNameBucket("軌道");
  return { "v213:identity:v2:sym:A": { ...source, rows },
    ["v213:identity:v2:name:" + bucket]: { schema: source.schema, kind: "name", bucket: String(bucket), generated_at: fixture.stamp,
      rows: rows.map(r => ["軌道", "A", r[0], r[1]]) },
    [OPTIONS]: { schema: "v213-options-v2", generated_at: fixture.stamp, options: {} } };
}
beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-09-15T12:01:00Z"));
  diagnostic.permitSynthetic = false;
  vi.stubGlobal("fetch", vi.fn(() => { throw new Error("O3O8_NETWORK_FORBIDDEN"); }));
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

it("O3 admitted incoherence refuses after rights; coherent, legacy, unknown and absent-jurisdiction controls survive", async () => {
  const cases: [string, "USD" | "SEK", string | undefined, "FOUND" | "QUOTE_INVALID_OR_STALE"][] = [
    ["SIVE.ST", "USD", "US", "QUOTE_INVALID_OR_STALE"], // original quarantine defect
    ["SIVE.ST", "USD", "SE", "QUOTE_INVALID_OR_STALE"], // currency only
    ["SIVE.ST", "SEK", "US", "QUOTE_INVALID_OR_STALE"], // jurisdiction only
    ["ACME", "USD", "SE", "QUOTE_INVALID_OR_STALE"],
    ["LEGACY", "SEK", "US", "QUOTE_INVALID_OR_STALE"],
    ["SIVE.ST", "USD", undefined, "QUOTE_INVALID_OR_STALE"], // absent jurisdiction is not a currency bypass
    ["7203.T", "USD", "US", "FOUND"], // no contract-defined currency/jurisdiction vocabulary for Japan
    ["ACME", "USD", "US", "FOUND"],
    ["ACME", "USD", undefined, "FOUND"],
    ["SIVE.ST", "SEK", "SE", "FOUND"],
    ["SIVE.ST", "SEK", undefined, "FOUND"],
    ["LEGACY", "SEK", "SE", "FOUND"],
    ["LEGACY", "SEK", undefined, "FOUND"],
    ["ABCDEFGHIJK.ST", "SEK", "SE", "FOUND"], // not the narrower identity-query grammar
    ["7203.T", "USD", "JP", "FOUND"],
    ["7203.T", "SEK", undefined, "FOUND"],
    ["ACME.ZZ", "USD", "SE", "FOUND"], // unmapped suffix must not become US
    ["ACME.ZZ", "SEK", "US", "FOUND"], // nor a legacy Stockholm key
  ];
  for (const [ticker, currency, jurisdiction, status] of cases) {
    const cycle = diagnosticCycle(ticker, currency, jurisdiction);
    const f = await environment("text", optionDocument(cycle));
    const view = await pinPublicSnapshot(f.env as never);
    expect(view.integrity).toBe("sealed");
    diagnostic.permitSynthetic = false;
    expect((await loadDetailedOptionObservation(view, ticker, "monthly")).status).toBe("RIGHTS_NOT_ADMITTED");
    diagnostic.permitSynthetic = true;
    const result = await loadDetailedOptionObservation(view, ticker, "monthly");
    expect.soft(result.status, JSON.stringify([ticker, currency, jurisdiction])).toBe(status);
    if (status === "FOUND") expect(result.quote).toEqual(cycle);
    else expect.soft(result.quote).toBeUndefined();
  }
  for (const style of ["text", "flex"] as const) {
    const f = await environment(style, optionDocument(diagnosticCycle("SIVE.ST", "USD", "US")));
    const text = await answer(f, "SIVE.ST 每月期權");
    expect.soft(text).toContain("封存之期權觀察未通過驗證");
    expect.soft(text).not.toContain("履約價");
    expect(await answer(await environment(style, optionDocument(diagnosticCycle("LEGACY", "SEK", "SE"))), "LEGACY 每月期權"))
      .toContain("履約價");
  }
});

it("R3 ISO jurisdiction SE admits Stockholm; non-contract markets remain unchanged", async () => {
  diagnostic.permitSynthetic = true;
  const cases: [string, "USD" | "SEK", string, "FOUND" | "QUOTE_INVALID_OR_STALE"][] = [
    ["SIVE.ST", "SEK", "SE", "FOUND"],
    ["SIVE.ST", "SEK", "US", "QUOTE_INVALID_OR_STALE"],
    ["SIVE.ST", "USD", "SE", "QUOTE_INVALID_OR_STALE"],
    ["SIVE.ST", "SEK", "SWEDEN", "QUOTE_INVALID_OR_STALE"], // no pre-R2 fixture evidence for this alias
    ["LEGACY", "SEK", "SE", "FOUND"],
    ["0700.HK", "USD", "HK", "FOUND"],
    ["7203.T", "USD", "JP", "FOUND"],
    ["7203.T", "SEK", "JP", "FOUND"],
    ["7203.T", "USD", "US", "FOUND"], // even a differing code is not positive evidence without a contract
  ];
  for (const [ticker, currency, jurisdiction, status] of cases) {
    const cycle = diagnosticCycle(ticker, currency, jurisdiction);
    const f = await environment("text", optionDocument(cycle));
    const result = await loadDetailedOptionObservation(await pinPublicSnapshot(f.env as never), ticker, "monthly");
    expect.soft(result.status, JSON.stringify([ticker, currency, jurisdiction])).toBe(status);
    if (status === "FOUND") expect.soft(result.quote).toEqual(cycle);
    else expect.soft(result.quote).toBeUndefined();
  }
});

it("O8 option ambiguity discloses 5/12 and more remaining with ordered text/Flex parity, but no noise at the limit", async () => {
  for (const count of [12, 5, 4]) {
    const visible: string[][] = [];
    for (const style of ["text", "flex"] as const) {
      const text = await answer(await environment(style, ambiguityObjects(count)), "軌道 每月期權");
      expect(text).toContain("此名稱對應多個掛牌");
      const labels = text.match(/A\d\d（NASDAQ STOCKHOLM）/g) ?? [];
      expect(labels).toEqual(Array.from({ length: Math.min(count, 5) }, (_, i) => `A0${i}（NASDAQ STOCKHOLM）`));
      expect(text).not.toContain("A05");
      if (count > 5) {
        expect.soft(text).toContain("已顯示 5/12 筆候選");
        expect.soft(text).toContain("尚有其他掛牌未顯示");
      } else {
        expect(text).not.toContain("已顯示");
        expect(text).not.toContain("尚有其他掛牌未顯示");
        expect(text).not.toMatch(/\d+\/\d+ 筆候選/);
      }
      visible.push(labels);
    }
    expect(visible[0]).toEqual(visible[1]);
  }
});
