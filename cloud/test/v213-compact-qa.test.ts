/// <reference types="node" />
import { readFileSync, writeFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";
import { parseQuery } from "../src/core";
import { compactPublicContext, compactGeneralAnswer, compactCompletionBody, COMPACT_RULES, minimalModelSmoke, SMOKE_MARKER } from "../src/v213/compact-qa";
import { v213RuntimeCompatibleFetch } from "../src/v213/production-worker";
import { type QaEnv } from "../src/qa";
import { MemoryKv, asKv } from "./fake-kv";

function runtime() {
  const kv = new MemoryKv();
  kv.values.set("last_successful_pipeline_timestamp", new Date().toISOString());
  kv.values.set("v21:top20:latest", JSON.stringify([
    { ticker: "NVDA", evidence: [{ source_id: "sec_edgar", claim_type: "filing_publication_provenance", as_of: "2026-08-01", url: "https://www.sec.gov/Archives/edgar/data/1000000/", provenance_only: true }], private_field: "MUST_NOT_ENTER_PROMPT" },
    { ticker: "OTHER", evidence: [{ title: "UNRELATED_UNIVERSE_MUST_NOT_ENTER" }] },
  ]));
  kv.values.set("v213:source-independence:latest", JSON.stringify({ portfolio: { limited_research_candidate_count: 20, evidence_qualified_candidate_count: 0 }, records: [{
    ticker: "NVDA", publication_evidence_mode: "LIMITED_RESEARCH_CANDIDATE", eligible_for_high_confidence_model_inference: false,
    public_logic_state: { validated_company_thesis: false }, market_corroboration: { status: "UNAVAILABLE" }, missing_or_review: ["INDEPENDENT_CLAIM_CORROBORATION"],
  }] }));
  const env: QaEnv = { PUBLIC_CACHE: asKv(kv), TENANT_PRIVATE_CACHE: asKv(new MemoryKv()), EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()),
    CURRENT_PUBLIC_DATA_ENABLED: "true", PUBLIC_DATA_MAX_AGE_SECONDS: "7200", GENERAL_QA_ENABLED: "true", MEMORY_FEATURE_AVAILABLE: "false",
    LOCAL_LLM_BASE_URL: "https://gateway.example.test", LOCAL_LLM_ALLOWED_HOSTS: "gateway.example.test", LOCAL_LLM_MODEL: "qwen38-q6",
    LOCAL_LLM_SHARED_SECRET: "SYNTHETIC_GATEWAY_AUTH_NOT_A_REAL_SECRET" };
  return { kv, env };
}
function transport(answer = "公開證據僅支持特定主張；缺乏獨立佐證時，不宜認定競爭優勢。") {
  const bodies: any[] = [];
  const native = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
    bodies.push(JSON.parse(String(init?.body)));
    return new Response(JSON.stringify({ choices: [{ finish_reason: "stop", message: { content: answer } }], ii_exact_model_pin: { selected_model: "qwen38-q6", request_model_substitution_allowed: false } }));
  });
  vi.stubGlobal("fetch", (input: RequestInfo | URL, init?: RequestInit) => v213RuntimeCompatibleFetch(native as typeof fetch, input, init));
  return { bodies, native };
}
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("v213 bounded query-aware public context", () => {
  it("does not put the universe or arbitrary raw fields in a generic/ticker prompt", async () => {
    const { env } = runtime();
    const generic = await compactPublicContext(env, parseQuery("自由現金流與淨利有何差異？"));
    expect(JSON.stringify(generic)).not.toMatch(/NVDA|OTHER|MUST_NOT_ENTER/);
    const ticker = await compactPublicContext(env, parseQuery("NVDA有哪些需要驗證的風險？"));
    expect(ticker.ticker).toBe("NVDA");
    expect(ticker.mode).toBe("LIMITED_RESEARCH_CANDIDATE");
    expect(ticker.high_eligible).toBe(false);
    expect(JSON.stringify(ticker)).not.toMatch(/OTHER|MUST_NOT_ENTER/);
    expect(JSON.stringify(ticker).length).toBeLessThanOrEqual(1600);
  });
  it("methodology uses fixed attribution-safe context without snapshot reads", async () => {
    const { env } = runtime();
    env.PUBLIC_CACHE = { get() { throw new Error("METHODOLOGY_SNAPSHOT_READ"); } } as unknown as KVNamespace;
    const data = await compactPublicContext(env, parseQuery("Serenity 的瓶頸與公司價值捕捉有何差別？"));
    expect(data.kind).toBe("methodology");
    expect(data.methodology).toContain("not an official Serenity formula");
    expect(JSON.stringify(data)).not.toContain("NVDA");
  });
  it("source questions carry claim-level verification rules, not unsupported conclusions", async () => {
    const { env } = runtime();
    const data = await compactPublicContext(env, parseQuery("如何判斷来源證據？"));
    expect(data.evidence_principles).toContain("provenance only");
    expect(data.evidence_principles).toContain("LIMITED cannot be promoted");
  });
  it("pins the snapshot and never falls back to stale direct keys", async () => {
    const { env, kv } = runtime();
    kv.values.set("snapshot:current", JSON.stringify({ run_id: "20260905T000000Z-aaaaaaaaaaaa" }));
    expect((await compactPublicContext(env, parseQuery("NVDA風險？"))).freshness).toBe("UNAVAILABLE");
  });
  it("stale data carries no ticker facts or evidence and current questions fail closed", async () => {
    const { env, kv } = runtime();
    kv.values.set("last_successful_pipeline_timestamp", "2000-01-01T00:00:00Z");
    const result = await compactPublicContext(env, parseQuery("NVDA風險？"));
    expect(result.freshness).toBe("STALE");
    expect(result.sources).toBeUndefined();
    const { native } = transport();
    expect(await compactGeneralAnswer(env, parseQuery("NVDA目前有哪些風險？"), { tenantId: "synthetic", chatType: "group" })).toMatch(/STALE/);
    expect(native).not.toHaveBeenCalled();
  });
  it("runs the unchanged certified sensitive-input guard without making model calls", async () => {
    const { env } = runtime(); const { native } = transport();
    for (const input of ["我持有 NVDA 20 股，成本 100", "my portfolio contains NVDA", "我的券商帳戶是測試帳戶"]) {
      expect(await compactGeneralAnswer(env, parseQuery(input), { tenantId: "synthetic", chatType: "group" })).toBe("SENSITIVE_PERSONAL_FINANCIAL_INPUT_NOT_ACCEPTED");
    }
    expect(native).not.toHaveBeenCalled();
  });
  it("compacts only marked SYSTEM context, bounds outputs and retains useful source attribution", async () => {
    const { env } = runtime(); const { bodies } = transport();
    const answer = await compactGeneralAnswer(env, parseQuery("NVDA有哪些需要驗證的風險？"), { tenantId: "synthetic", chatType: "group" });
    expect(bodies[0].ii_context_mode).toBe("compact_public_v1");
    expect(bodies[0].max_tokens).toBe(160);
    expect(bodies[0].messages[0].content.startsWith(COMPACT_RULES)).toBe(true);
    expect(JSON.stringify(bodies[0]).length).toBeLessThan(3000);
    expect(answer).toContain("LIMITED_RESEARCH_CANDIDATE");
    expect(answer).toContain("sec_edgar");
    expect(compactCompletionBody({ messages: [{ role: "user", content: "PUBLIC_REPORT\nII_V213_COMPACT_CONTEXT_V1:{}" }] })).toBeNull();
  });
  it("smoke uses fixed minimal input and NEVER reads public or private storage", async () => {
    const { env } = runtime(); const { bodies } = transport(SMOKE_MARKER);
    const forbidden = { get() { throw new Error("SMOKE_STORAGE_ACCESS_FORBIDDEN"); } } as unknown as KVNamespace;
    expect(await minimalModelSmoke({ ...env, PUBLIC_CACHE: forbidden, TENANT_PRIVATE_CACHE: forbidden, EPHEMERAL_SECURITY_CACHE: forbidden })).toBe(true);
    expect(bodies[0].messages).toEqual([{ role: "user", content: `Reply exactly ${SMOKE_MARKER}` }]);
    expect(bodies[0].ii_context_mode).toBe("transport_smoke_v1");
    expect(bodies[0].max_tokens).toBe(32);
    await expect(minimalModelSmoke({ ...env, LOCAL_LLM_MODEL: "qwen38" })).rejects.toThrow("MODEL_CONFIG_INVALID");
  });
  it("generates reproducible fixed benchmark requests from the actual compact path (optional local public fixture)", async () => {
    const { env, kv } = runtime();
    const fixture = process.env.V213_BENCH_PUBLIC_BUNDLE;
    if (fixture) {
      const b = JSON.parse(readFileSync(fixture, "utf8").replace(/^\uFEFF/, ""));
      kv.values.set("last_successful_pipeline_timestamp", b.public_data_as_of);
      kv.values.set("v21:top20:latest", b.payloads.top20_json);
      kv.values.set("v213:source-independence:latest", b.payloads.source_independence_json);
    }
    const { bodies } = transport(); const cases: any[] = [];
    for (const [name, query] of Object.entries({ general: "什麼是自由現金流？它與淨利有何差異？", ticker: "NVDA有哪些需要驗證的公司風險？", methodology: "Serenity 的瓶頸與公司價值捕捉有何差別？", evidence: "如何判斷來源證據能否支持公司定價權？" })) {
      await compactGeneralAnswer(env, parseQuery(query), { tenantId: "synthetic", chatType: "group" });
      const request = bodies.at(-1); expect(request.ii_context_mode).toBe("compact_public_v1");
      cases.push({ name, ...request });
    }
    await minimalModelSmoke(env); cases.push({ name: "smoke", ...bodies.at(-1) });
    if (process.env.V213_QA_CASES_OUT) writeFileSync(process.env.V213_QA_CASES_OUT, JSON.stringify(cases, null, 2));
  });
});
