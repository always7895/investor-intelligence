import { afterAll, afterEach, describe, expect, it, vi } from "vitest";
import { createHmac, createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { generalAnswer } from "../src/qa";
import { SMOKE_MARKER, minimalModelSmoke as minimumModelSmokeExport, compactGeneralAnswer } from "../src/v213/compact-qa";
import {
  V213FreeRelayRoute,
  freeRelayGatewaySecret,
  type FreeRelayEnv,
  type FreeRelayRouteRecord,
} from "../src/v213/free-relay";
import { modelProfileSha256, validateModelProfile, type ModelProfile } from "../src/v213/model-profile";
import { parseQuery } from "../src/core";
import { storeOwnerPairing } from "../src/v21/owner-storage";
import { deriveTenantId } from "../src/security";
import { asKv, MemoryKv } from "./fake-kv";
import type { V211Env } from "../src/v211/worker";

/**
 * TASK0 Phase-1E — general-QA chain: formal-caller webhook replay (E1) and
 * real-gateway loopback completion (E2), plus the Phase-1D partial
 * direct-caller chain kept as a contract subset.
 *
 * Boundary discipline:
 * - The single in-test fetch boundary is installed BEFORE the production
 *   worker module is imported, so the module-installed
 *   v213RuntimeCompatibleFetch adapter stays the runtime wrapper (it never
 *   gets replaced by the stub). The boundary is the only native layer.
 * - Allowlisted URLs: the lease host (https://HOST, model origin) and the
 *   LINE reply URL (destination; captured in-memory, never sent externally).
 * - Any other URL or an unexpected method: recorded + test fails fast.
 * - When BOUNDARY.gateway is armed, lease-host model+health requests are
 *   forwarded (fwd) to the local loopback gateway child process; all other
 *   outcomes are synthesized by the boundary. No other local ports are
 *   touched.
 */
const HOST = "task0e-phase1e.trycloudflare.com";
const LINE_REPLY = "https://api.line.me/v2/bot/message/reply";
const EXL3 = "Qwen3.8-27B-EXL3-SC5-H6-V6";
const UD = "Qwen3.8-27B-UD-Q5_K_XL-7a1459e88548";
const CANDIDATE_SHA_EXPECTED = "70077f89fa117e915de73b4c9477d2af85dd8ce3ee6b397f11d5864329c20192";
const NATIVE_FETCH: typeof fetch = globalThis.fetch.bind(globalThis);
const LINE_SECRET = "EXAMPLE_TASK0_PHASE1E_LINE_CHANNEL_SECRET_NOT_REAL_98765";
const LINE_TOKEN = "EXAMPLE_TASK0_PHASE1E_LINE_ACCESS_TOKEN_NOT_REAL";
const HMAC_SECRET = "EXAMPLE_TASK0_PHASE1E_HMAC_SECRET_NOT_REAL_0123456789";
const TENANT_SECRET = "EXAMPLE_TASK0_PHASE1E_TENANT_HASH_NOT_REAL_0123";

type ChatShape = {
  model: string;
  ii_context_mode?: string;
  ii_model_profile?: unknown;
  max_tokens?: number;
  messages?: Array<{ role: string; content: string }>;
};

type CallRecord = {
  url: string;
  method: string;
  init?: RequestInit | null;
};

const FINAL_TEXT =
  "股票代表公司所有權，債券代表債權。股票的收益來自股價變動與現金流，波動通常較高；債券通常有固定票息，波動較低，償還優先。（TEST_LOCAL_CANDIDATE_FINAL）";

const BOUNDARY: {
  calls: CallRecord[];
  lineTexts: string[];
  forbidden: Array<{ url: string; method: string }>;
  mode: "ok" | "http500" | "redirect-307" | "substitution" | "wrongpin" | "finish-length";
  gateway: { port: number; secret: string } | null;
} = { calls: [], lineTexts: [], forbidden: [], mode: "ok", gateway: null };

async function boundaryFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const url = String(input);
  const method = String(init?.method ?? (input instanceof Request ? input.method : "GET")).toUpperCase();
  BOUNDARY.calls.push({ url, method, init });
  if (url.startsWith(`https://${HOST}/`)) {
    if (BOUNDARY.gateway) {
      const path = url.slice(`https://${HOST}`.length) || "/";
      const fwd = await NATIVE_FETCH(`http://127.0.0.1:${BOUNDARY.gateway.port}${path}`, {
        method,
        headers: {
          ...(init?.headers as Record<string, string> | undefined),
          "x-investor-shared-secret": BOUNDARY.gateway.secret,
          "content-type": "application/json",
        },
        body: init?.body ?? undefined,
      });
      return new Response(await fwd.text(), { status: fwd.status, headers: { "content-type": "application/json" } });
    }
    if (url.endsWith("/health")) {
      return new Response(
        JSON.stringify({
          ok: true,
          service: "v213-local-llm-gateway",
          health_schema_version: 2,
          llama_reachable: true,
          selected_model_available: true,
          selected_model: EXL3,
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    }
    if (url.endsWith("/v1/chat/completions")) {
      const chat = (init?.body ? (JSON.parse(String(init.body)) as ChatShape) : {}) as ChatShape;
      if (BOUNDARY.mode === "http500") return new Response("synthetic down", { status: 500 });
      if (BOUNDARY.mode === "redirect-307") {
        return new Response(null, { status: 307, headers: { location: "https://somewhere-else.example.com/chat" } });
      }
      const smoke = chat.ii_context_mode === "transport_smoke_v1";
      const substitution = BOUNDARY.mode === "substitution";
      const wrongpin = BOUNDARY.mode === "wrongpin";
      const finishLength = BOUNDARY.mode === "finish-length";
      const profileSha = chat.ii_model_profile
        ? await modelProfileSha256(chat.ii_model_profile as ModelProfile)
        : CANDIDATE_SHA_EXPECTED;
      const reply = {
        id: "task0-phase1e",
        model: chat.model,
        ii_exact_model_pin: {
          selected_model: chat.model,
          canonical_model: chat.model,
          model_profile_sha256: wrongpin ? "0".repeat(64) : profileSha,
          request_model_substitution_allowed: substitution,
        },
        choices: [
          {
            index: 0,
            message: { role: "assistant", content: smoke ? SMOKE_MARKER : FINAL_TEXT, tool_calls: [] },
            finish_reason: finishLength ? "length" : "stop",
          },
        ],
        usage: { prompt_tokens: 8, completion_tokens: 40, total_tokens: 48 },
      };
      return new Response(JSON.stringify(reply), { status: 200, headers: { "content-type": "application/json" } });
    }
    return new Response("boundary: no such lease path", { status: 404 });
  }
  if (url === LINE_REPLY) {
    const body = init?.body ? (JSON.parse(String(init.body)) as { messages?: Array<{ text?: string }> }) : {};
    for (const m of body.messages ?? []) if (typeof m.text === "string") BOUNDARY.lineTexts.push(m.text);
    return new Response(JSON.stringify({ endpoint: "https://api.line.me/v2/bot/message/reply", detail: [] }), {
      status: 200,
      headers: { "content-type": "application/json", "x-line-request-id": "task0-phase1e-synthetic" },
    });
  }
  BOUNDARY.forbidden.push({ url, method });
  throw new Error(`BOUNDARY_FORBIDDEN: ${method} ${url}`);
}

vi.stubGlobal("fetch", boundaryFetch);

// Import AFTER the boundary is installed: the module wraps this exact
// boundary with v213RuntimeCompatibleFetch, so all production calls keep the
// real adapter layer.
const { default: productionWorker, freeRelayRequestEnv } = await import("../src/v213/production-worker");

const RELAY_PATH = "./fixtures/task0-phase1d";
const ASSEMBLY_AT = Date.parse("2026-09-17T09:24:10Z");

function fixtureObjects(): Record<string, string> {
  return JSON.parse(readFileSync(new URL(`${RELAY_PATH}/objects.json`, import.meta.url), "utf-8"));
}
function fixturePointer(): string {
  return readFileSync(new URL(`${RELAY_PATH}/pointer.raw.json`, import.meta.url), "utf-8").trim();
}

class FakeStorage {
  values = new Map<string, unknown>();
  private serial = Promise.resolve();
  get<T>(key: string): Promise<T | undefined> {
    return Promise.resolve(this.values.get(key) as T | undefined);
  }
  put(key: string, value: unknown): Promise<void> {
    this.values.set(key, structuredClone(value));
    return Promise.resolve();
  }
  transaction<T>(callback: (txn: FakeStorage) => Promise<T>): Promise<T> {
    const result = this.serial.then(() => callback(this));
    this.serial = result.then(() => undefined, () => undefined);
    return result;
  }
}

function relayDevice() {
  const storage = new FakeStorage();
  const state = { storage } as unknown as DurableObjectState;
  const object = new V213FreeRelayRoute(state);
  const seed = (rec: FreeRelayRouteRecord) =>
    object.fetch(new Request("https://free-relay.internal/update", { method: "POST", body: JSON.stringify(rec) }));
  const namespace = {
    idFromName: () => ({ toString: () => "task0-general-qa" }),
    get: () => ({ fetch: (input: RequestInfo | URL, init?: RequestInit) => object.fetch(new Request(input, init)) }),
  } as unknown as DurableObjectNamespace;
  return { seed, namespace };
}

function relayThrower(): DurableObjectNamespace {
  return {
    idFromName: () => ({ toString: () => "task0-general-qa-fault" }),
    get: () => ({
      fetch: () => {
        throw new Error("DO_STORAGE_HINT_FAULT");
      },
    }),
  } as unknown as DurableObjectNamespace;
}

function routeRec(generation: string, model: string): FreeRelayRouteRecord {
  const now = Date.now();
  return {
    schema_version: 1,
    tunnel_mode: "quick_free_relay",
    model,
    public_url: `https://${HOST}`,
    connected_at: new Date(now - 60_000).toISOString(),
    expires_at: new Date(now + 300_000).toISOString(),
    health_schema_version: 2,
    route_generation: generation,
    consecutive_health_checks: 3,
  };
}

function candidateProfileJson(): string {
  return readFileSync(new URL(`../../config/v213-model-profile-exl3-sc5-h6-v6.candidate.json`, import.meta.url), "utf-8").trim();
}

type WorkerEnv = V211Env & FreeRelayEnv & { V213_MODEL_PROFILE_JSON?: string };

function workerEnv(
  namespace: DurableObjectNamespace | null,
  opts: { profile?: boolean; freshBase?: boolean; pairOwner?: boolean } = {},
): WorkerEnv {
  const kv = new MemoryKv();
  if (opts.freshBase) {
    for (const [k, v] of Object.entries(fixtureObjects())) kv.values.set(k, v);
    kv.values.set("snapshot:current", fixturePointer());
  }
  return {
    PUBLIC_CACHE: asKv(kv),
    TENANT_PRIVATE_CACHE: asKv(new MemoryKv()),
    EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()),
    V21_SYNC_HMAC_SECRET: HMAC_SECRET,
    TENANT_DATA_ENCRYPTION_KEY: "e".repeat(64),
    V21_MAX_SYNC_AGE_SECONDS: "300",
    TENANT_HASH_SECRET: TENANT_SECRET,
    LINE_CHANNEL_SECRET: LINE_SECRET,
    LINE_CHANNEL_ACCESS_TOKEN: LINE_TOKEN,
    FREE_RELAY_ENABLED: "true",
    FREE_RELAY_MAX_TTL_SECONDS: "300",
    V213_LINE_PRESENTATION: "text",
    LOCAL_LLM_MODEL: EXL3,
    V213_COMPACT_QA_ENABLED: "true",
    ...(namespace ? { V213_FREE_RELAY_ROUTE: namespace } : {}),
    ...(opts.profile ? { V213_MODEL_PROFILE_JSON: candidateProfileJson() } : {}),
  } as unknown as WorkerEnv;
}

async function paired(env: WorkerEnv, pairOwner: boolean): Promise<WorkerEnv> {
  if (!pairOwner) return env;
  const t = await deriveTenantId({ type: "user", userId: "u_task0_phase1e" } as never, TENANT_SECRET);
  await storeOwnerPairing(env as never, t, "U" + "a".repeat(32));
  return env;
}

function signWebhook(rawBody: string): string {
  return createHmac("sha256", LINE_SECRET).update(rawBody).digest("base64");
}

function webhook(rawBody: string): Request {
  return new Request("https://investor-intelligence-v21-owner-line.example/webhook", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "content-length": String(new TextEncoder().encode(rawBody).length),
      "x-line-signature": signWebhook(rawBody),
    },
    body: rawBody,
  });
}

function textMessage(id: number, replyToken: string, text: string): string {
  return JSON.stringify({
    destination: "cli_user",
    events: [
      {
        replyToken,
        source: { type: "user", userId: "u_task0_phase1e" },
        timestamp: Date.now(),
        type: "message",
        message: { id, type: "text", text },
      },
    ],
  });
}

function context(collect: Array<Promise<unknown>>): ExecutionContext {
  return {
    waitUntil(p: Promise<unknown>) {
      collect.push(p.catch(() => "V212_LINE_EVENT_FAILED:caught"));
    },
    passThroughOnException() {},
  } as unknown as ExecutionContext;
}

async function drain(collect: Array<Promise<unknown>>): Promise<{ fulfilled: number; rejected: number }> {
  let fulfilled = 0;
  let rejected = 0;
  const start = performance.now();
  for (;;) {
    const batch = collect.splice(0, collect.length);
    if (batch.length > 0) {
      const results = await Promise.allSettled(batch);
      for (const r of results) {
        if (r.status === "fulfilled") fulfilled++;
        else rejected++;
      }
    } else if (performance.now() - start > 400) {
      break; // settled + one quiet window: no new waitUntil work
    }
    await new Promise((r) => setTimeout(r, 20));
    if (performance.now() - start > 5_000) throw new Error("TASK0_DRAIN_TIMEOUT");
  }
  return { fulfilled, rejected };
}

async function runWebhook(
  env: WorkerEnv,
  rawBody: string,
): Promise<{ status: number | "threw"; error: string; rejects: { fulfilled: number; rejected: number }; lines: string[] }> {
  const collect: Array<Promise<unknown>> = [];
  BOUNDARY.calls.length = 0;
  BOUNDARY.lineTexts.length = 0;
  let res: Response;
  try {
    res = await productionWorker.fetch(webhook(rawBody), env as never, context(collect));
  } catch (err) {
    const rejects = await drain(collect);
    return { status: "threw", error: err instanceof Error ? err.message : String(err), rejects, lines: [...BOUNDARY.lineTexts] };
  }
  const rejects = await drain(collect);
  return { status: res.status, error: "", rejects, lines: [...BOUNDARY.lineTexts] };
}

afterEach(() => {
  BOUNDARY.mode = "ok";
  BOUNDARY.calls.length = 0;
  BOUNDARY.lineTexts.length = 0;
  vi.useRealTimers();
});

afterAll(async () => {
  vi.unstubAllGlobals();
});

describe("E2 candidate profile: cross-language hash gate (test-only, not release-canonical)", () => {
  it("raw node sha256 + TS modelProfileSha256 both equal the expected candidate sha", async () => {
    const raw = candidateProfileJson();
    const profile = validateModelProfile(JSON.parse(raw));
    expect(profile.model).toBe(EXL3);
    const fields = ["schema_version", "model", "enable_thinking", "reasoning_effort", "max_output_tokens", "smoke_output_tokens", "timeout_ms"] as const;
    const canonical = JSON.stringify(fields.map((k) => profile[k]));
    const rawNode = createHash("sha256").update(new TextEncoder().encode(canonical)).digest("hex");
    expect(rawNode).toBe(CANDIDATE_SHA_EXPECTED);
    expect(await modelProfileSha256(profile)).toBe(CANDIDATE_SHA_EXPECTED);
  });
});

describe("partial chain (direct generalAnswer) — Phase-1D contract subset", () => {
  it("relay disabled -> LOCAL_MODEL_NOT_CONFIGURED (deterministic closed code)", async () => {
    const envoy = workerEnv(null);
    (envoy as unknown as Record<string, string>).FREE_RELAY_ENABLED = "false";
    const env = await freeRelayRequestEnv(envoy as never);
    expect(await generalAnswer(env as never, parseQuery("請說明股票與債券的一項主要差異"), { tenantId: "synthetic", chatType: "user" })).toBe("LOCAL_MODEL_NOT_CONFIGURED");
    expect(BOUNDARY.calls.length).toBe(0);
  });

  it("no route (empty DO) -> LOCAL_MODEL_NOT_CONFIGURED and no chat attempt", async () => {
    const { namespace } = relayDevice();
    const env = await freeRelayRequestEnv(workerEnv(namespace));
    expect(await generalAnswer(env as never, parseQuery("請說明股票與債券的一項主要差異"), { tenantId: "synthetic", chatType: "user" })).toBe("LOCAL_MODEL_NOT_CONFIGURED");
    expect(BOUNDARY.calls.filter((c) => c.url.endsWith("/v1/chat/completions")).length).toBe(0);
  });

  it("nominal lease: adapter sees redirect:manual, full model id, stop, gen-secret, final content", async () => {
    const gen = "7ea1b2c3d4e5f60718293a4b5c6d7e07";
    const { seed, namespace } = relayDevice();
    await seed(routeRec(gen, EXL3));
    const envoy = workerEnv(namespace, { profile: true });
    const env = await freeRelayRequestEnv(envoy);
    const answer = await generalAnswer(env as never, parseQuery("請說明股票與債券的一項主要差異"), { tenantId: "synthetic", chatType: "user" });
    expect(answer).toBe(FINAL_TEXT);
    const chat = BOUNDARY.calls.find((c) => c.url.endsWith("/v1/chat/completions"));
    expect(chat, "chat completion must hit the lease origin exactly once").toBeTruthy();
    if (chat) {
      expect(chat.url).toBe(`https://${HOST}/v1/chat/completions`);
      expect((chat.init as { redirect?: string }).redirect).toBe("manual"); // real adapter in place
      const body = JSON.parse(String(chat.init?.body)) as { model: string };
      expect(body.model).toBe(EXL3);
      expect((chat.init?.headers as Record<string, string>)["x-investor-shared-secret"])
        .toBe(await freeRelayGatewaySecret(envoy as never, gen));
    }
  });

  it("substitution flag -> reject; wrong pin sha -> reject (deterministic smoke outcomes)", async () => {
    const dev = relayDevice();
    await dev.seed(routeRec("7ea1b2c3d4e5f60718293a4b5c6d7e08", EXL3));
    BOUNDARY.mode = "substitution";
    let env = await freeRelayRequestEnv(workerEnv(dev.namespace, { profile: true }));
    expect(await minimumModelSmokeExport(env as never)).toBe(false);
    BOUNDARY.mode = "wrongpin";
    env = await freeRelayRequestEnv(workerEnv(dev.namespace, { profile: true }));
    expect(await minimumModelSmokeExport(env as never)).toBe(false);
    BOUNDARY.mode = "ok";
  });

  it("wrong route model -> no overrides, zero chat (per-request model gate)", async () => {
    const dev = relayDevice();
    await dev.seed(routeRec("7ea1b2c3d4e5f60718293a4b5c6d7e09", UD));
    const env = await freeRelayRequestEnv(workerEnv(dev.namespace));
    expect(await generalAnswer(env as never, parseQuery("請說明股票與債券的一項主要差異"), { tenantId: "synthetic", chatType: "user" })).toBe("LOCAL_MODEL_NOT_CONFIGURED");
    expect(BOUNDARY.calls.filter((c) => c.url.endsWith("/v1/chat/completions")).length).toBe(0);
  });

  it("500 -> LOCAL_MODEL_OFFLINE; redirect (manual) -> adapter rejects -> LOCAL_MODEL_OFFLINE", async () => {
    const dev = relayDevice();
    await dev.seed(routeRec("7ea1b2c3d4e5f60718293a4b5c6d7e0a", EXL3));
    BOUNDARY.mode = "http500";
    let env = await freeRelayRequestEnv(workerEnv(dev.namespace));
    expect(await generalAnswer(env as never, parseQuery("請說明股票與債券的一項主要差異"), { tenantId: "synthetic", chatType: "user" })).toBe("LOCAL_MODEL_OFFLINE");
    BOUNDARY.mode = "redirect-307";
    env = await freeRelayRequestEnv(workerEnv(dev.namespace));
    expect(await generalAnswer(env as never, parseQuery("請說明股票與債券的一項主要差異"), { tenantId: "synthetic", chatType: "user" })).toBe("LOCAL_MODEL_OFFLINE");
    const redirected = BOUNDARY.calls.filter((c) => c.url.endsWith("/v1/chat/completions")).pop();
    if (redirected) expect((redirected.init as { redirect?: string }).redirect).toBe("manual");
    BOUNDARY.mode = "ok";
  });

  it("smoke mode returns the marker; compact mode must NOT return the marker", async () => {
    const dev = relayDevice();
    const gen = "7ea1b2c3d4e5f60718293a4b5c6d7e0b";
    await dev.seed(routeRec(gen, EXL3));
    const envoy = workerEnv(dev.namespace, { profile: true });
    const env = await freeRelayRequestEnv(envoy);
    expect(await minimumModelSmokeExport(env as never)).toBe(true);
    const smokeBody = JSON.parse(String(BOUNDARY.calls.filter((c) => c.url.endsWith("/v1/chat/completions")).pop()?.init?.body)) as ChatShape;
    expect(smokeBody.ii_context_mode).toBe("transport_smoke_v1");
    expect(await generalAnswer(env as never, parseQuery("請說明股票與債券的一項主要差異"), { tenantId: "synthetic", chatType: "user" })).toBe(FINAL_TEXT);
    const compactBody = JSON.parse(String(BOUNDARY.calls.filter((c) => c.url.endsWith("/v1/chat/completions")).pop()?.init?.body)) as ChatShape;
    expect(compactBody.ii_context_mode).not.toBe("transport_smoke_v1");
    expect(compactBody.ii_context_mode).not.toBe(smokeBody.ii_context_mode);
  });

  it("finish_reason=length is a non-complete outcome (reject on smoke path)", async () => {
    const dev = relayDevice();
    await dev.seed(routeRec("7ea1b2c3d4e5f60718293a4b5c6d7e0c", EXL3));
    BOUNDARY.mode = "finish-length";
    const env = await freeRelayRequestEnv(workerEnv(dev.namespace, { profile: true }));
    expect(await minimumModelSmokeExport(env as never)).toBe(false);
    BOUNDARY.mode = "ok";
  });
});

describe("E1 formal-caller synthetic LINE webhook (signature-auth, owner, event dispatch, compact handler, runtime adapter)", () => {
  it("candidate profile + healthy test lease: webhook -> general answer ends with final content (no external writes)", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(ASSEMBLY_AT + 3_600_000));
    const gen = "9f0e1d2c3b4a5968778695a4b3c2d1e0";
    const dev = relayDevice();
    await dev.seed(routeRec(gen, EXL3));
    const env = await paired(workerEnv(dev.namespace, { profile: true, freshBase: true }), true);
    const res = await runWebhook(env, textMessage(1, "reply_task0_phase1e", "請說明股票與債券的一項主要差異"));
    expect(res.status).toBe(200);
    expect(res.rejects.rejected).toBe(0);
    const joined = res.lines.join("\n");
    // direct quick answer OR job reference + completed job; both end in FINAL_TEXT
    if (joined.includes("參考編號")) {
      const { TENANT_PRIVATE_CACHE } = env as unknown as { TENANT_PRIVATE_CACHE: { values: Map<string, unknown> } };
      const jobRaw = [...TENANT_PRIVATE_CACHE.values.values()].find((v) => String(v).includes("TEST_LOCAL_CANDIDATE_FINAL"));
      expect(jobRaw, "job must carry the completed final content").toBeTruthy();
      expect(String(jobRaw)).toContain("TEST_LOCAL_CANDIDATE_FINAL");
    } else {
      expect(joined, "reply must contain the canonical final content").toContain("TEST_LOCAL_CANDIDATE_FINAL");
    }
    const chat = BOUNDARY.calls.find((c) => c.url.endsWith("/v1/chat/completions"));
    expect(chat).toBeTruthy();
    if (chat) expect((chat.init as { redirect?: string }).redirect).toBe("manual");
    expect(BOUNDARY.forbidden.length).toBe(0);
  });

  it("no lease + fresh sealed data: Top20 and Macro still complete via the same dispatcher", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(ASSEMBLY_AT + 3_600_000));
    const { namespace } = relayDevice(); // never seeded
    const env = await paired(workerEnv(namespace, { freshBase: true }), true);
    const res20 = await runWebhook(env, textMessage(2, "reply_top20", "Top 20"));
    expect(res20.status).toBe(200);
    expect(res20.rejects.rejected).toBe(0);
    expect(res20.lines.join("\n")).toContain("GEV");
    const resMacro = await runWebhook(env, textMessage(3, "reply_macro", "宏觀產業分析 文字"));
    expect(resMacro.status).toBe(200);
    expect(resMacro.lines.join("\n")).toContain("TOP5產業總覽");
    expect(BOUNDARY.calls.filter((c) => c.url.endsWith("/v1/chat/completions")).length).toBe(0);
    expect(BOUNDARY.forbidden.length).toBe(0);
  });

  it("no lease + general question: deterministic unavailable reply (not pretended success)", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(ASSEMBLY_AT + 3_600_000));
    const { namespace } = relayDevice();
    const env = await paired(workerEnv(namespace, { freshBase: true }), true);
    const res = await runWebhook(env, textMessage(4, "reply_noqa", "請說明股票與債券的一項主要差異"));
    expect(res.status).toBe(200);
    expect(res.rejects.rejected).toBe(0);
    const joined = res.lines.join("\n");
    expect(joined.length).toBeGreaterThan(0);
    expect(joined).toContain("本機模型橋接尚未啟用");
    expect(BOUNDARY.calls.filter((c) => c.url.endsWith("/v1/chat/completions")).length).toBe(0);
  });

    it("DO /current read throws: contract = fail-soft isolation (RED until repair)", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(ASSEMBLY_AT + 3_600_000));
    const env = await paired(workerEnv(relayThrower(), { freshBase: true }), true);

    const res20 = await runWebhook(env, textMessage(5, "reply_do_throw_top20", "Top 20"));
    expect(res20.status, "webhook must not abort on DO read fault").toBe(200);
    expect(res20.rejects.rejected, "no unexpected background rejection").toBe(0);
    expect(res20.lines.join("\n")).toContain("GEV");
    expect(res20.lines.join("\n")).toContain("6501");

    const resMacro = await runWebhook(env, textMessage(6, "reply_do_throw_macro", "宏觀產業分析 文字"));
    expect(resMacro.status).toBe(200);
    expect(resMacro.rejects.rejected).toBe(0);
    expect(resMacro.lines.join("\n")).toContain("TOP5產業總覽");

    const resQa = await runWebhook(env, textMessage(7, "reply_do_throw_qa", "請說明股票與債券的一項主要差異"));
    expect(resQa.status).toBe(200);
    expect(resQa.rejects.rejected).toBe(0);
    expect(resQa.lines.join("\n")).toContain("本機模型橋接尚未啟用");
    expect(BOUNDARY.calls.filter((c) => c.url.endsWith("/v1/chat/completions")).length).toBe(0);
    expect(BOUNDARY.forbidden.length).toBe(0);
  });

  it("bad signature rejected: no reply, no model request, auth not bypassed", async () => {
    const env = workerEnv(null, { freshBase: true });
    const raw = textMessage(6, "reply_badsig", "health");
    const badReq = new Request("https://investor-intelligence-v21-owner-line.example/webhook", {
      method: "POST",
      headers: { "content-type": "application/json", "x-line-signature": "AAAA-BOGUS-SIGNATURE" },
      body: raw,
    });
    BOUNDARY.calls.length = 0;
    BOUNDARY.lineTexts.length = 0;
    const ok = await productionWorker.fetch(badReq, env as never, context([]));
    expect(ok.status).toBe(401);
    expect(BOUNDARY.lineTexts.length).toBe(0);
    expect(BOUNDARY.calls.filter((c) => c.url.endsWith("/v1/chat/completions")).length).toBe(0);
  });
});
