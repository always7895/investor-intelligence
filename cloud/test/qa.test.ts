import { afterEach, describe, expect, it, vi } from "vitest";
import { parseQuery } from "../src/core";
import {
  deterministicAnswer,
  generalAnswer,
  type QaEnv,
  type RequestContext,
} from "../src/qa";
import {
  conversation,
  setMemoryEnabled,
} from "../src/storage";
import { MemoryKv, asKv } from "./fake-kv";

const LOCAL_MODEL_CONFIG: Partial<QaEnv> = {
  LOCAL_LLM_BASE_URL: "https://local-model.example",
  LOCAL_LLM_ALLOWED_HOSTS: "local-model.example",
  LOCAL_LLM_SHARED_SECRET: "EXAMPLE_LOCAL_MODEL_SHARED_SECRET_NOT_REAL",
};

function env(
  publicKv: MemoryKv,
  overrides: Partial<QaEnv> = {},
  privateKv = new MemoryKv(),
  securityKv = new MemoryKv(),
): QaEnv {
  return {
    PUBLIC_CACHE: asKv(publicKv),
    TENANT_PRIVATE_CACHE: asKv(privateKv),
    EPHEMERAL_SECURITY_CACHE: asKv(securityKv),
    TENANT_HASH_SECRET: "EXAMPLE_TENANT_HASH_SECRET_NOT_REAL",
    TENANT_DATA_ENCRYPTION_KEY: "EXAMPLE_TENANT_DATA_KEY_NOT_REAL",
    MEMORY_FEATURE_AVAILABLE: "false",
    GENERAL_QA_ENABLED: "true",
    CURRENT_PUBLIC_DATA_ENABLED: "false",
    PUBLIC_DATA_MAX_AGE_SECONDS: "1800",
    OPTION_DATA_MAX_AGE_SECONDS: "1800",
    ...overrides,
  };
}

const firstContext: RequestContext = {
  tenantId: "tenant-first",
  chatType: "user",
};

const secondContext: RequestContext = {
  tenantId: "tenant-second",
  chatType: "user",
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("Q&A public-only privacy, namespace isolation and freshness", () => {
  it("does not expose user long-term overlay in the public ranking", async () => {
    const publicKv = new MemoryKv();
    publicKv.values.set(
      "scores:latest",
      JSON.stringify([
        {
          rank: 1,
          ticker: "TEST",
          total_score: 75,
          data_quality: 0.8,
          user_long_term_overlay: { label: "OWNER_PRIVATE_LONG_TERM_LABEL" },
        },
      ]),
    );
    const answer = await deterministicAnswer(env(publicKv), parseQuery("排名"), firstContext);
    expect(answer).toContain("TEST");
    expect(answer).not.toContain("OWNER_PRIVATE_LONG_TERM_LABEL");
    expect(answer).toContain("不含任何人的持倉");
  });

  it("never reads TENANT_PRIVATE_CACHE when assembling model context", async () => {
    const publicKv = new MemoryKv();
    const privateKv = new MemoryKv();
    publicKv.values.set("reports:latest", "PUBLIC REPORT CONTEXT");
    privateKv.values.set(
      "tenant:tenant-first:legacy-portfolio",
      JSON.stringify({
        ticker: "OWNER_PRIVATE_SENTINEL",
        account_id: "BROKER_ACCOUNT_SENTINEL",
        covered_contract_capacity: 9,
      }),
    );
    privateKv.values.set(
      "tenant:tenant-first:legacy-options",
      JSON.stringify({ quote_source: "IBKR_PRIVATE_SENTINEL" }),
    );

    let sentBody = "";
    let sentInit: RequestInit | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
        sentBody = String(init?.body ?? "");
        sentInit = init;
        return new Response(
          JSON.stringify({ choices: [{ message: { content: "public answer" } }] }),
          { status: 200, headers: { "content-type": "application/json" } },
        );
      }),
    );

    const answer = await generalAnswer(
      env(publicKv, LOCAL_MODEL_CONFIG, privateKv),
      parseQuery("解釋什麼是光子交換器"),
      firstContext,
    );
    expect(answer).toBe("public answer");
    expect(sentBody).toContain("PUBLIC REPORT CONTEXT");
    expect(sentBody).not.toContain("OWNER_PRIVATE_SENTINEL");
    expect(sentBody).not.toContain("BROKER_ACCOUNT_SENTINEL");
    expect(sentBody).not.toContain("IBKR_PRIVATE_SENTINEL");
    expect(sentInit?.redirect).toBe("error");
    expect(sentInit?.headers).toMatchObject({
      "x-investor-shared-secret": "EXAMPLE_LOCAL_MODEL_SHARED_SECRET_NOT_REAL",
      "cache-control": "no-store",
    });
  });

  it("never injects public option chains into arbitrary model prompts", async () => {
    const publicKv = new MemoryKv();
    publicKv.values.set("reports:latest", "PUBLIC REPORT CONTEXT");
    publicKv.values.set(
      "options:latest",
      JSON.stringify([
        {
          ticker: "TEST",
          quote_source: "PUBLIC_OPTION_SENTINEL",
          bid: 123.45,
        },
      ]),
    );

    let sentBody = "";
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
        sentBody = String(init?.body ?? "");
        return new Response(
          JSON.stringify({ choices: [{ message: { content: "business answer" } }] }),
          { status: 200, headers: { "content-type": "application/json" } },
        );
      }),
    );

    const answer = await generalAnswer(
      env(publicKv, LOCAL_MODEL_CONFIG),
      parseQuery("解釋 TEST 的商業模式"),
      firstContext,
    );
    expect(answer).toBe("business answer");
    expect(sentBody).toContain("PUBLIC REPORT CONTEXT");
    expect(sentBody).not.toContain("PUBLIC_OPTION_SENTINEL");
    expect(sentBody).not.toContain("123.45");
    expect(sentBody).not.toContain("PUBLIC_OPTIONS");
  });

  it("rejects first-person financial disclosures before model use or memory storage", async () => {
    const publicKv = new MemoryKv();
    const privateKv = new MemoryKv();
    const securityKv = new MemoryKv();
    const runtime = env(
      publicKv,
      { ...LOCAL_MODEL_CONFIG, MEMORY_FEATURE_AVAILABLE: "true" },
      privateKv,
      securityKv,
    );
    await setMemoryEnabled(runtime, firstContext.tenantId, true);
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const answer = await generalAnswer(
      runtime,
      parseQuery("我持有 250 股 TEST，成本 123.45，請幫我分析"),
      firstContext,
    );
    expect(answer).toBe("SENSITIVE_PERSONAL_FINANCIAL_INPUT_NOT_ACCEPTED");
    expect(fetchMock).not.toHaveBeenCalled();
    await expect(conversation(runtime, firstContext.tenantId)).resolves.toEqual([]);
    expect(JSON.stringify([...privateKv.values.values()])).not.toContain("250");
    expect(JSON.stringify([...privateKv.values.values()])).not.toContain("123.45");
    expect(publicKv.values.size).toBe(0);
    expect([...securityKv.values.values()].join("\n")).not.toContain("250");
  });

  it("rejects an unallowlisted, unauthenticated or redirectable model route", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const unallowlisted = await generalAnswer(
      env(new MemoryKv(), {
        LOCAL_LLM_BASE_URL: "https://untrusted.example",
        LOCAL_LLM_ALLOWED_HOSTS: "local-model.example",
        LOCAL_LLM_SHARED_SECRET: "EXAMPLE_SECRET_NOT_REAL",
      }),
      parseQuery("解釋 HBM"),
      firstContext,
    );
    expect(unallowlisted).toBe("LOCAL_MODEL_NOT_CONFIGURED");

    const unauthenticated = await generalAnswer(
      env(new MemoryKv(), {
        LOCAL_LLM_BASE_URL: "https://local-model.example",
        LOCAL_LLM_ALLOWED_HOSTS: "local-model.example",
      }),
      parseQuery("解釋 HBM"),
      firstContext,
    );
    expect(unauthenticated).toBe("LOCAL_MODEL_NOT_CONFIGURED");

    const ipLiteral = await generalAnswer(
      env(new MemoryKv(), {
        LOCAL_LLM_BASE_URL: "https://127.0.0.1",
        LOCAL_LLM_ALLOWED_HOSTS: "127.0.0.1",
        LOCAL_LLM_SHARED_SECRET: "EXAMPLE_SECRET_NOT_REAL",
      }),
      parseQuery("解釋 HBM"),
      firstContext,
    );
    expect(ipLiteral).toBe("LOCAL_MODEL_NOT_CONFIGURED");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("uses only PUBLIC_CACHE option snapshots", async () => {
    const publicKv = new MemoryKv();
    const privateKv = new MemoryKv();
    // A valid timestamp containing 999 must not be mistaken for a private bid.
    const clock = new Date(); clock.setUTCMilliseconds(999);
    const now = clock.toISOString();
    publicKv.values.set(
      "options:latest",
      JSON.stringify([
        {
          ticker: "TEST",
          status: "OK",
          quote_source: "yfinance",
          retrieved_at: now,
          provider_scope: "public_only",
          line_public_eligible: true,
          periods: {
            weekly: {
              status: "OK",
              expiration: "2026-08-28",
              actual_dte: 4,
              call_observations: {
                status: "OK",
                recommended_candidates: [
                  {
                    strike: 100,
                    bid: 2,
                    ask: 2.2,
                    midpoint: 2.1,
                    quote_source: "yfinance",
                    retrieved_at: now,
                    liquidity_pass: true,
                  },
                ],
              },
              put_observations: {
                status: "NO_ELIGIBLE_LIQUID_QUOTE",
                recommended_candidates: [],
              },
            },
          },
        },
      ]),
    );
    privateKv.values.set(
      "tenant:tenant-first:options:latest",
      JSON.stringify({ ticker: "TEST", quote_source: "IBKR_PRIVATE_SENTINEL", bid: 999 }),
    );

    const privateRead = vi.spyOn(privateKv, "get");
    const answer = await deterministicAnswer(
      env(publicKv, {}, privateKv),
      parseQuery("TEST 每週期權 BID ASK"),
      firstContext,
    );
    expect(answer).toContain("Bid USD 2.00");
    expect(answer).toContain(".999Z");
    expect(answer).not.toContain("Bid USD 999.00");
    expect(answer).not.toContain("IBKR_PRIVATE_SENTINEL");
    expect(privateRead).not.toHaveBeenCalled();
  });

  it("always denies portfolio and brokerage queries for every tenant", async () => {
    expect(
      await deterministicAnswer(env(new MemoryKv()), parseQuery("我的持倉"), firstContext),
    ).toBe("LINE_PUBLIC_ONLY_NO_PORTFOLIO_OR_BROKER_DATA");
    expect(
      await deterministicAnswer(env(new MemoryKv()), parseQuery("我的持倉"), secondContext),
    ).toBe("LINE_PUBLIC_ONLY_NO_PORTFOLIO_OR_BROKER_DATA");
  });

  it("fails closed on current questions until a live public-data adapter is enabled", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const answer = await generalAnswer(
      env(new MemoryKv(), LOCAL_MODEL_CONFIG),
      parseQuery("今天 TEST 最新消息是什麼？"),
      firstContext,
    );
    expect(answer).toBe("CURRENT_LIVE_SOURCE_DISABLED");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects stale current-data timestamps even when public context exists", async () => {
    const publicKv = new MemoryKv();
    publicKv.values.set("reports:latest", "PUBLIC REPORT");
    publicKv.values.set(
      "last_successful_pipeline_timestamp",
      new Date(Date.now() - 60 * 60 * 1000).toISOString(),
    );
    const answer = await generalAnswer(
      env(publicKv, {
        ...LOCAL_MODEL_CONFIG,
        CURRENT_PUBLIC_DATA_ENABLED: "true",
        PUBLIC_DATA_MAX_AGE_SECONDS: "300",
      }),
      parseQuery("目前 TEST 價格如何？"),
      firstContext,
    );
    expect(answer).toBe("CURRENT_DATA_STALE");
  });

  it("never invokes an injected legacy cloud AI binding", async () => {
    const fakeAi = {
      run: vi.fn(async () => ({ response: "should-not-run" })),
    };
    const legacyEnv = Object.assign(env(new MemoryKv()), {
      AI: fakeAi as unknown as Ai,
      CLOUD_INFERENCE_ENABLED: "true",
      WORKERS_AI_FREE_QUOTA_AVAILABLE: "true",
      CLOUDFLARE_PLAN: "workers_free",
    });
    const answer = await generalAnswer(legacyEnv, parseQuery("解釋 HBM"), firstContext);
    expect(answer).toBe("LOCAL_MODEL_NOT_CONFIGURED");
    expect(fakeAi.run).not.toHaveBeenCalled();
  });
});
