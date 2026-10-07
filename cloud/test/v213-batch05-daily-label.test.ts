// BATCH05: real sealed stock caller; label drift is a metadata fixture, not a caller mock.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import fixture from "../../tests/fixtures/identity-batch04-functional.json";
import { parseQuery } from "../src/core";
import { handleGlobalEquityLookup } from "../src/v213/global-equity-lookup";
import { assertLineMessages, type LineOutboundMessage } from "../src/line-messages";
import { asKv, MemoryKv } from "./fake-kv";

vi.mock("../src/v213/market-observations", async importOriginal => {
  const real = await importOriginal<typeof import("../src/v213/market-observations")>();
  // Change the shared source label before the lookup module builds its equivalence set.
  real.PRICE_SOURCE_LABEL["yahoo-daily-close"] = "Yahoo 日收盤（合成改名）";
  return real;
});
const sha = async (body: string) => Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(body))),
  b => b.toString(16).padStart(2, "0")).join("");
const NOW = "2026-09-15T12:01:00Z";
async function answer(style: "text" | "flex", asof: string | null, source = "yahoo-daily-close") {
  const kv = new MemoryKv();
  for (const [key, body] of Object.entries(fixture.values)) kv.values.set(key, body);
  const sealKey = `snapshot:${fixture.run}:v213:snapshot-seal:v1`;
  const seal = JSON.parse(kv.values.get(sealKey)!);
  const lazy = {
    "v213:prices:v1:SWEDEN": { schema: "v213-price-shard-v1", market: "SWEDEN", generated_at: fixture.stamp,
      sources: [{ id: source, url: "https://example.com/synthetic-daily" }], rows: { SIVE: [32.5, 1, asof, "SEK", 0] } },
    "v213:quotes:v1": { schema: "v213-quotes-v1", generated_at: fixture.stamp, quotes: {
      "SIVE.ST": { symbol: "SIVE.ST", price: 33, previous_close: 32, change_pct: 0.03, currency: "SEK",
        asof: fixture.stamp, source: "Yahoo Finance (unofficial, delayed)", source_url: "https://example.com/synthetic-hourly" }
    } },
  };
  for (const [key, value] of Object.entries(lazy)) {
    const body = JSON.stringify(value), digest = await sha(body);
    seal.objects[key] = { sha256: digest, utf8_bytes: new TextEncoder().encode(body).length };
    kv.values.set("blob:v1:" + digest, body);
  }
  const raw = JSON.stringify(seal);
  kv.values.set(sealKey, raw);
  const pointer = JSON.parse(kv.values.get("snapshot:current")!);
  pointer.seal_sha256 = await sha(raw);
  kv.values.set("snapshot:current", JSON.stringify(pointer));
  const messages = await handleGlobalEquityLookup({ PUBLIC_CACHE: asKv(kv), TENANT_PRIVATE_CACHE: asKv(new MemoryKv()),
    EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()), V213_LINE_PRESENTATION: style } as never, parseQuery("SIVE.ST")) as LineOutboundMessage[];
  assertLineMessages(messages);
  return JSON.stringify(messages);
}
beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(new Date(NOW));
  vi.stubGlobal("fetch", vi.fn(() => { throw new Error("OFFLINE_ONLY"); }));
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });
describe("BATCH05 daily source and date contract", () => {
  it("B05-I5 renamed daily Yahoo label is still one provider on text and Flex", async () => {
    for (const style of ["text", "flex"] as const) {
      const reply = await answer(style, "2026-09-14");
      expect(reply).toContain("Yahoo 日收盤（合成改名）");
      expect(reply).toContain("2026-09-14");
      expect(reply).not.toContain("交叉比對");
      expect(reply).not.toContain("2026-09-14T");
    }
  });
  it("B05-I5 missing trade date is explicitly acquisition-only, never an invented close date", async () => {
    for (const style of ["text", "flex"] as const) {
      const reply = await answer(style, null);
      expect(reply).toContain(fixture.stamp + "（擷取時間；來源未載明成交日）");
      expect(reply).not.toContain("交叉比對");
    }
  });
  it("B05-I5 unknown source labels retain the existing comparison, never inferred as Yahoo", async () => {
    expect(await answer("text", "2026-09-14", "synthetic-independent-label")).toContain("交叉比對");
  });
});
