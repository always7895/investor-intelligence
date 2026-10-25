import { describe, expect, it } from "vitest";
import { parseQuery } from "../src/core";
import {
  handleGlobalEquityLookup,
  buildGlobalEquityLookupMessages,
  parseGlobalEquityQuery,
} from "../src/v213/global-equity-lookup";
import { scopePublicSnapshot } from "../src/v213/public-snapshot";
import { MemoryKv, asKv } from "./fake-kv";
import type { StorageEnv } from "../src/storage";

function createMockEnv(overrides?: Record<string, unknown>): StorageEnv & { V213_LINE_PRESENTATION?: string } {
  return {
    PUBLIC_CACHE: asKv(new MemoryKv()),
    TENANT_KV: asKv(new MemoryKv()),
    V211_ADMIN_TOKEN_SALT: "salt",
    LINE_CHANNEL_SECRET: "mock_secret",
    LINE_CHANNEL_ACCESS_TOKEN: "mock_token",
    ...overrides,
  } as any;
}

describe("Core parseQuery Global Equity Classification", () => {
  it("classifies bare ASCII tickers and case variants as global_equity_lookup", () => {
    expect(parseQuery("AAPL").intent).toBe("global_equity_lookup");
    expect(parseQuery("aapl").intent).toBe("global_equity_lookup");
    expect(parseQuery("NVDA").intent).toBe("global_equity_lookup");
    expect(parseQuery("TSLA").intent).toBe("global_equity_lookup");
    expect(parseQuery("IBM").intent).toBe("global_equity_lookup");
  });

  it("classifies bare SIVE across all case variants as canonical global_equity_lookup", () => {
    expect(parseQuery("SIVE").intent).toBe("global_equity_lookup");
    expect(parseQuery("sive").intent).toBe("global_equity_lookup");
    expect(parseQuery("Sive").intent).toBe("global_equity_lookup");
  });

  it("classifies bare numeric tickers and suffixed tickers as global_equity_lookup", () => {
    // Taiwan
    expect(parseQuery("2330").intent).toBe("global_equity_lookup");
    expect(parseQuery("2330.TW").intent).toBe("global_equity_lookup");
    expect(parseQuery("0050").intent).toBe("global_equity_lookup");

    // Japan, Korea, HK, Europe, UK
    expect(parseQuery("7203.T").intent).toBe("global_equity_lookup");
    expect(parseQuery("005930.KS").intent).toBe("global_equity_lookup");
    expect(parseQuery("0700.HK").intent).toBe("global_equity_lookup");
    expect(parseQuery("SIVE.ST").intent).toBe("global_equity_lookup");
    expect(parseQuery("IQE.L").intent).toBe("global_equity_lookup");
    expect(parseQuery("ASML.AS").intent).toBe("global_equity_lookup");
  });

  it("classifies explicit prefix queries and company queries as global_equity_lookup", () => {
    expect(parseQuery("股票 AAPL").intent).toBe("global_equity_lookup");
    expect(parseQuery("個股 2330.TW").intent).toBe("global_equity_lookup");
    expect(parseQuery("公司 台積電").intent).toBe("global_equity_lookup");
    expect(parseQuery("股票 Sivers").intent).toBe("global_equity_lookup");
    expect(parseQuery("查股價 0700.HK").intent).toBe("global_equity_lookup");
    expect(parseQuery("Apple Inc.").intent).toBe("global_equity_lookup");
    expect(parseQuery("Sivers Semiconductors").intent).toBe("global_equity_lookup");
  });

  it("does not steal reserved bot commands or macro abbreviations", () => {
    expect(parseQuery("TOP20").intent).toBe("ranking");
    expect(parseQuery("HELP").intent).toBe("help");
    expect(parseQuery("選單").intent).toBe("help");
    expect(parseQuery("早報").intent).toBe("morning_report");
    expect(parseQuery("晚報").intent).toBe("evening_report");
    expect(parseQuery("最新報告").intent).toBe("latest_report");
    expect(parseQuery("健康").intent).toBe("health");
    expect(parseQuery("記憶狀態").intent).toBe("memory_status");
    expect(parseQuery("刪除我的資料").intent).toBe("delete_data");
    expect(parseQuery("查看結果 1234567890AB").intent).toBe("job_result");
  });
});

describe("Worker handleGlobalEquityLookup Caller Integration", () => {
  it("handles SIVE across all case variants and returns generic card without invented issuer or OTC claim", async () => {
    const env = scopePublicSnapshot(createMockEnv());

    for (const variant of ["SIVE", "sive", "Sive"]) {
      const q = parseQuery(variant);
      const messages = await handleGlobalEquityLookup(env, q);
      expect(messages).not.toBeNull();
      expect(Array.isArray(messages)).toBe(true);

      const flexMsg = (messages as any[])[0];
      expect(flexMsg.type).toBe("flex");
      const jsonStr = JSON.stringify(flexMsg);
      expect(jsonStr).toContain("SIVE");
      expect(jsonStr).not.toContain("Sivers Semiconductors");
      expect(jsonStr).not.toContain("OTC:SIVE");
    }
  });

  it("handles unknown company query with immediate UNAVAILABLE card without leaking to QA or issue tickets", async () => {
    const env = scopePublicSnapshot(createMockEnv());
    const q = parseQuery("公司 UnknownCorpX");
    const messages = await handleGlobalEquityLookup(env, q);

    expect(messages).not.toBeNull();
    const flexMsg = (messages as any[])[0];
    expect(flexMsg.type).toBe("flex");
    const jsonStr = JSON.stringify(flexMsg);
    expect(jsonStr.toLowerCase()).toContain("unknowncorpx");
    expect(jsonStr).toContain("身分資料未封存准入");
    expect(jsonStr).not.toContain("查看結果");
  });

  it("handles bare ticker queries when catalog is unmigrated with honest UNAVAILABLE card", async () => {
    const env = scopePublicSnapshot(createMockEnv());
    const q = parseQuery("AAPL");
    const messages = await handleGlobalEquityLookup(env, q);

    expect(messages).not.toBeNull();
    const jsonStr = JSON.stringify(messages);
    expect(jsonStr).toContain("AAPL");
    expect(jsonStr).toContain("身分資料未封存准入");
  });

  it("respects text presentation mode when V213_LINE_PRESENTATION is text", async () => {
    const env = scopePublicSnapshot(createMockEnv({ V213_LINE_PRESENTATION: "text" }));
    const q = parseQuery("SIVE");
    const messages = await handleGlobalEquityLookup(env, q);

    expect(messages).not.toBeNull();
    const textMsg = (messages as any[])[0];
    expect(textMsg.type).toBe("text");
    expect(textMsg.text).toContain("個股快查 · SIVE");
    expect(textMsg.text).not.toContain("Sivers Semiconductors");
  });

  it("leaves genuine general questions untouched (returns null for non-equity prose)", async () => {
    const env = scopePublicSnapshot(createMockEnv());
    const q = parseQuery("聯準會降息對科技股有什麼影響？");
    const messages = await handleGlobalEquityLookup(env, q);
    expect(messages).toBeNull();
  });
});
