import { afterEach, describe, expect, it, vi } from "vitest";
import { generalAnswer } from "../src/qa";
import { freeRelayRequestEnv } from "../src/v213/production-worker";
import { SMOKE_MARKER, minimalModelSmoke } from "../src/v213/compact-qa";
import {
  V213FreeRelayRoute,
  freeRelayGatewaySecret,
  type FreeRelayEnv,
  type FreeRelayRouteRecord,
} from "../src/v213/free-relay";
import { modelProfileSha256, validateModelProfile, type ModelProfile } from "../src/v213/model-profile";
import { parseQuery } from "../src/core";
import { asKv, MemoryKv } from "./fake-kv";
import type { V211Env } from "../src/v211/worker";

/**
 * TASK0 Phase-1D — general-QA chain contract replay (in-memory).
 *
 * Scope: MemoryKv + test DurableObject + in-memory fetch transport standing in
 * for the free-relay public tunnel (gateway /health + OpenAI
 * /v1/chat/completions boundaries). No production KV writes, no tunnel, no DI
 * gateway process in this gate; the TEMP real-gateway knock is a separate
 * diagnostic (not committed). The profile below is a TEST-ONLY test-local
 * candidate talking the operator-approved executor model ID; it is not a
 * release dent claim. Completion is asserted from protocol: full model ID
 * in flight (no alias), finish_reason stop, exact pin fields, canonical
 * final content.
 */
const HOST = "task0probe-phase1d.trycloudflare.com"; // synthetic contract-shaped lease host (fetched in-memory only; resolve never happens)
const CANDIDATE_MODEL = "Qwen3.8-27B-EXL3-SC5-H6-V6"; // LOCAL_CANDIDATE model id (test-only)
const OLD_UD_MODEL = "Qwen3.8-27B-UD-Q5_K_XL-7a1459e88548"; // legacy repo-template id (negative gate)
const CANDIDATE_PROFILE = validateModelProfile({
  schema_version: 1,
  model: CANDIDATE_MODEL,
  enable_thinking: false,
  reasoning_effort: "none",
  max_output_tokens: 1024,
  smoke_output_tokens: 128,
  timeout_ms: 18000,
});
const HMAC_SECRET = "EXAMPLE_TASK0_PHASE1D_HMAC_SECRET_NOT_REAL_0123456789";
const FIXED_FINAL =
  "股票代表公司所有權，債券代表債權。股票的收益來自股價變動與現金流，波動通常較高；債券通常有固定票息，波動較低，償還優先。（TEST_LOCAL_CANDIDATE_FINAL）";

type RelayEnv = V211Env & FreeRelayEnv;

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

function record(generation: string, model: string, connectedOffsetMs = -60_000, ttlSeconds = 300): FreeRelayRouteRecord {
  const now = Date.now();
  return {
    schema_version: 1,
    tunnel_mode: "quick_free_relay",
    model,
    public_url: `https://${HOST}`,
    connected_at: new Date(now + connectedOffsetMs).toISOString(),
    expires_at: new Date(now + ttlSeconds * 1000).toISOString(),
    health_schema_version: 2,
    route_generation: generation,
    consecutive_health_checks: 3,
  };
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

function envWithRelay(namespace: DurableObjectNamespace | null, extra: Record<string, string> = {}): RelayEnv {
  return {
    PUBLIC_CACHE: asKv(new MemoryKv()),
    TENANT_PRIVATE_CACHE: asKv(new MemoryKv()),
    EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()),
    V21_SYNC_HMAC_SECRET: HMAC_SECRET,
    V21_MAX_SYNC_AGE_SECONDS: "300",
    FREE_RELAY_ENABLED: "true",
    FREE_RELAY_MAX_TTL_SECONDS: "300",
    LOCAL_LLM_MODEL: CANDIDATE_MODEL,
    ...(namespace ? { V213_FREE_RELAY_ROUTE: namespace } : {}),
    ...extra,
  } as unknown as RelayEnv;
}

function healthOk(model: string): string {
  return JSON.stringify({
    ok: true,
    service: "v213-local-llm-gateway",
    health_schema_version: 2,
    llama_reachable: true,
    selected_model_available: true,
    selected_model: model,
  });
}

type Captured = { url: string; body?: unknown; headers?: Record<string, unknown> };
const captured: Captured[] = [];

function installTransport(mode: "ok" | "http500" | "redirect-307") {
  const handler = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = String(input);
    const chatBody = init?.body ? (JSON.parse(String(init.body)) as { model: string; ii_model_profile?: unknown; ii_context_mode?: string }) : undefined;
    captured.push({ url, body: chatBody, headers: init?.headers as Record<string, unknown> });
    if (url.endsWith("/health")) {
      return new Response(healthOk(CANDIDATE_MODEL), { status: 200, headers: { "content-type": "application/json" } });
    }
    if (url.endsWith("/v1/chat/completions")) {
      if (mode === "http500") return new Response("synthetic down", { status: 500 });
      if (mode === "redirect-307") return new Response(null, { status: 307, headers: { location: "https://somewhere-else.example.com/chat" } });
      const reply = {
        id: "task0-phase1d-synthetic",
        model: chatBody?.model, // full model id spoken by the transport (no alias)
        ii_exact_model_pin: {
          selected_model: chatBody?.model,
          model_profile_sha256: chatBody?.ii_model_profile ? await modelProfileSha256(chatBody.ii_model_profile as ModelProfile) : null,
          request_model_substitution_allowed: false,
        },
        choices: [
          {
            index: 0,
            message: { role: "assistant", content: chatBody?.ii_context_mode ? SMOKE_MARKER : FIXED_FINAL, tool_calls: [] },
            finish_reason: "stop",
          },
        ],
        usage: { prompt_tokens: 8, completion_tokens: 40, total_tokens: 48 },
      };
      return new Response(JSON.stringify(reply), { status: 200, headers: { "content-type": "application/json" } });
    }
    return new Response("unexpected", { status: 404 });
  };
  vi.stubGlobal("fetch", handler);
  captured.length = 0;
}

afterEach(() => {
  vi.unstubAllGlobals();
  captured.length = 0;
});

const QUESTION = "請說明股票與債券的一項主要差異";
const CTX = { tenantId: "synthetic", chatType: "user" } as const;

describe("general-QA chain (contract replay)", () => {
  it("relay disabled -> LOCAL_MODEL_NOT_CONFIGURED (deterministic closed code)", async () => {
    const env = await freeRelayRequestEnv(envWithRelay(null, { FREE_RELAY_ENABLED: "false" }));
    expect(await generalAnswer(env as never, parseQuery(QUESTION), CTX)).toBe("LOCAL_MODEL_NOT_CONFIGURED");
  });

  it("lease missing (empty DO) -> LOCAL_MODEL_NOT_CONFIGURED", async () => {
    const { namespace } = relayDevice(); // never seeded
    const env = await freeRelayRequestEnv(envWithRelay(namespace));
    expect(await generalAnswer(env as never, parseQuery(QUESTION), CTX)).toBe("LOCAL_MODEL_NOT_CONFIGURED");
    expect(captured.filter((c) => c.url.endsWith("/v1/chat/completions")).length).toBe(0);
  });

  it("nominal lease + transport: full model id, stop completion, canonical final content + per-generation gateway secret", async () => {
    installTransport("ok");
    const gen = "01a2b3c4d5e6f708192a3b4c5d6e0f01";
    const { seed, namespace } = relayDevice();
    await seed(record(gen, CANDIDATE_MODEL));
    const envoy = envWithRelay(namespace);
    const env = await freeRelayRequestEnv(envoy);
    const answer = await generalAnswer(env as never, parseQuery(QUESTION), CTX);
    expect(answer).toBe(FIXED_FINAL);
    const chat = captured.find((c) => c.url.endsWith("/v1/chat/completions"));
    expect(chat, "chat completion must hit the lease origin").toBeTruthy();
    if (chat) {
      expect(chat.url).toBe(`https://${HOST}/v1/chat/completions`);
      expect((chat.body as { model: string }).model).toBe(CANDIDATE_MODEL);
      expect((chat.headers as Record<string, string>)["x-investor-shared-secret"])
        .toBe(await freeRelayGatewaySecret(envoy as never, gen));
    }
  });

  it("compact smoke with local-candidate profile: exact pin sha + stop + marker, no alias id", async () => {
    installTransport("ok");
    const gen = "02a2b3c4d5e6f708192a3b4c5d6e0f02";
    const { seed, namespace } = relayDevice();
    await seed(record(gen, CANDIDATE_MODEL));
    const envoy = envWithRelay(namespace, { V213_MODEL_PROFILE_JSON: JSON.stringify(CANDIDATE_PROFILE) });
    const env = await freeRelayRequestEnv(envoy);
    expect(await minimalModelSmoke(env as never)).toBe(true);
    const chat = captured.find((c) => c.url.endsWith("/v1/chat/completions"));
    if (chat) {
      expect((chat.body as { model: string }).model).toBe(CANDIDATE_MODEL);
      expect(JSON.stringify(chat.body)).toContain(CANDIDATE_MODEL);
      expect(JSON.stringify(chat.body)).not.toContain(`"model":"${OLD_UD_MODEL}"`);
    }
  });

  it("substitution-flag tripwire: request_model_substitution_allowed=true -> smoke rejects", async () => {
    const prev = globalThis.fetch;
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/health")) {
        return new Response(healthOk(CANDIDATE_MODEL), { status: 200, headers: { "content-type": "application/json" } });
      }
      const body = (init?.body ?? "{}") as string;
      const requested = JSON.parse(body) as { model: string };
      return new Response(
        JSON.stringify({
          id: "x",
          model: requested.model,
          ii_exact_model_pin: {
            selected_model: requested.model,
            model_profile_sha256: await modelProfileSha256(CANDIDATE_PROFILE),
            request_model_substitution_allowed: true,
          },
          choices: [{ index: 0, message: { role: "assistant", content: SMOKE_MARKER }, finish_reason: "stop" }],
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    });
    const { seed, namespace } = relayDevice();
    await seed(record("03a2b3c4d5e6f708192a3b4c5d6e0f03", CANDIDATE_MODEL));
    const envoy = envWithRelay(namespace, { V213_MODEL_PROFILE_JSON: JSON.stringify(CANDIDATE_PROFILE) });
    const env = await freeRelayRequestEnv(envoy);
    expect(await minimalModelSmoke(env as never).catch(() => false)).toBe(false);
    vi.stubGlobal("fetch", prev);
  });

  it("route model != env expected model -> no lease, zero chat attempts (per-request model gate)", async () => {
    installTransport("ok");
    const { seed, namespace } = relayDevice();
    await seed(record("04a2b3c4d5e6f708192a3b4c5d6e0f04", OLD_UD_MODEL));
    const env = await freeRelayRequestEnv(envWithRelay(namespace));
    expect(await generalAnswer(env as never, parseQuery(QUESTION), CTX)).toBe("LOCAL_MODEL_NOT_CONFIGURED");
    expect(captured.filter((c) => c.url.endsWith("/v1/chat/completions")).length).toBe(0);
  });

  it("llm 500 -> LOCAL_MODEL_OFFLINE (fail-closed to identity)", async () => {
    installTransport("http500");
    const { seed, namespace } = relayDevice();
    await seed(record("05a2b3c4d5e6f708192a3b4c5d6e0f05", CANDIDATE_MODEL));
    const env = await freeRelayRequestEnv(envWithRelay(namespace));
    expect(await generalAnswer(env as never, parseQuery(QUESTION), CTX)).toBe("LOCAL_MODEL_OFFLINE");
  });

  it("redirected chat response -> rejected (redirect:error), LOCAL_MODEL_OFFLINE", async () => {
    installTransport("redirect-307");
    const { seed, namespace } = relayDevice();
    await seed(record("06a2b3c4d5e6f708192a3b4c5d6e0f06", CANDIDATE_MODEL));
    const env = await freeRelayRequestEnv(envWithRelay(namespace));
    expect(await generalAnswer(env as never, parseQuery(QUESTION), CTX)).toBe("LOCAL_MODEL_OFFLINE");
    expect(captured.filter((c) => c.url.endsWith("/v1/chat/completions")).length).toBeGreaterThan(0);
  });
});