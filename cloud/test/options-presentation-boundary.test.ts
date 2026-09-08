import { afterEach, describe, expect, it, vi } from "vitest";
import { parseQuery } from "../src/core";
import { deterministicAnswer } from "../src/qa";
import { humanizeFallback } from "../src/v211/research";
import { freeRelayRequestEnv } from "../src/v213/production-worker";
import { v213Top20LineAnswer } from "../src/v213/top20-presentation";
import { processAuthorizedLineEvent } from "../src/v211/worker";
import { MemoryKv, asKv } from "./fake-kv";

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("option presentation cannot bypass the certified public quote path", () => {
  it.each(["AAOI sell call", "AAOI sell call 文字", "2330.TW 期權", "SIVE sell call", "期權", "AAOI 期權 光通訊深度"])(
    "delegates %s before storage or knowledge-base access", async (input) => {
      const env = new Proxy({}, { get() { throw new Error("UNEXPECTED_PRESENTATION_READ"); } });
      const query = parseQuery(input);
      expect(query.intent).toBe("options");
      expect(await v213Top20LineAnswer(env as any, query)).toBeNull();
    },
  );

  it.each(["missing", "malformed", "stale", "future", "status-only"])(
    "actual authorized LINE caller uses certified refusal for %s data", async (scenario) => {
      const kv = new MemoryKv();
      if (scenario !== "missing") {
        kv.values.set("options:latest", scenario === "malformed" ? "{" : JSON.stringify([{
          ticker: "AAOI", status: "OK", quote_source: "yfinance",
          retrieved_at: scenario === "stale" ? "2000-01-01T00:00:00Z" : scenario === "future" ? "9999-01-01T00:00:00Z" : new Date().toISOString(),
          periods: { weekly: { covered_call: { recommended_candidates: [{ strike: 999999, bid: 999999, ask: 999999 }] } } },
        }]));
      }
      const env = await freeRelayRequestEnv({
        PUBLIC_CACHE: asKv(kv), TENANT_PRIVATE_CACHE: asKv(new MemoryKv()),
        EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()), CURRENT_PUBLIC_DATA_ENABLED: "true",
        OPTION_DATA_MAX_AGE_SECONDS: "1800", LINE_CHANNEL_ACCESS_TOKEN: "SYNTHETIC_TOKEN",
        LINE_CHANNEL_SECRET: "SYNTHETIC_SECRET",
      } as any);
      const query = parseQuery("AAOI sell call");
      const expected = scenario === "malformed"
        ? "OPTION_DATA_INVALID：公開期權資料無法驗證；不提供報價或替代交易數字。"
        : humanizeFallback((await deterministicAnswer(env, query, { tenantId: "synthetic-tenant", chatType: "user" }))!, query);
      expect(typeof expected).toBe("string");
      expect(expected).not.toContain("999999");
      const calls: any[] = [];
      vi.stubGlobal("fetch", vi.fn(async (_url, init) => {
        calls.push(JSON.parse(String(init.body))); return new Response("{}");
      }));
      await processAuthorizedLineEvent(env, {} as ExecutionContext, {
        type: "message", replyToken: "SYNTHETIC_REPLY", source: { type: "user", userId: "SYNTHETIC_USER" },
        message: { type: "text", text: query.normalized }, timestamp: Date.now(),
      }, "synthetic-tenant");
      expect(calls).toHaveLength(1);
      expect(calls[0].messages.every((message: any) => message.type === "text")).toBe(true);
      expect(calls[0].messages.map((message: any) => message.text).join("\n")).toBe(expected);
    },
  );
});
