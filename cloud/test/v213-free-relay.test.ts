import { afterEach, describe, expect, it, vi } from "vitest";
import productionWorker, { freeRelayRequestEnv, v213RuntimeCompatibleFetch } from "../src/v213/production-worker";
import { parseQuery } from "../src/core";
import * as sevenFieldBroadcast from "../src/v213/broadcast";
import { generalAnswer } from "../src/qa";
import {
  V213FreeRelayRoute,
  applyFreeRelayUpdate,
  freeRelayGatewaySecret,
  parseFreeRelayRoute,
  verifyFreeRelayPublicHealth,
  type FreeRelayEnv,
  type FreeRelayRouteRecord,
} from "../src/v213/free-relay";
import { MemoryKv, asKv } from "./fake-kv";
import type { V211Env } from "../src/v211/worker";

const HMAC_SECRET = "EXAMPLE_FREE_RELAY_HMAC_SECRET_NOT_REAL_123456789";
const MODEL = "qwen38-q6";

function route(generation: string, connectedOffsetMs = 0, ttlSeconds = 180): FreeRelayRouteRecord {
  const now = Date.now();
  return {
    schema_version: 1,
    tunnel_mode: "quick_free_relay",
    model: MODEL,
    public_url: `https://${generation.slice(0, 12)}.trycloudflare.com`,
    connected_at: new Date(now + connectedOffsetMs).toISOString(),
    expires_at: new Date(now + ttlSeconds * 1000).toISOString(),
    health_schema_version: 2,
    route_generation: generation,
    consecutive_health_checks: 3,
  };
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

function relayObject(storage = new FakeStorage()) {
  const state = { storage } as unknown as DurableObjectState;
  return { object: new V213FreeRelayRoute(state), storage };
}

function namespace(object: V213FreeRelayRoute): DurableObjectNamespace {
  return {
    idFromName: () => ({ toString: () => "free-relay" }),
    get: () => ({ fetch: (input: RequestInfo | URL, init?: RequestInit) => object.fetch(new Request(input, init)) }),
  } as unknown as DurableObjectNamespace;
}

function env(object: V213FreeRelayRoute): V211Env & FreeRelayEnv {
  const kv = new MemoryKv();
  return {
    PUBLIC_CACHE: asKv(kv),
    TENANT_PRIVATE_CACHE: asKv(new MemoryKv()),
    EPHEMERAL_SECURITY_CACHE: asKv(kv),
    V21_SYNC_HMAC_SECRET: HMAC_SECRET,
    V21_MAX_SYNC_AGE_SECONDS: "300",
    V213_FREE_RELAY_ROUTE: namespace(object),
    FREE_RELAY_ENABLED: "true",
    FREE_RELAY_MAX_TTL_SECONDS: "300",
    LOCAL_LLM_MODEL: MODEL,
  } as unknown as V211Env & FreeRelayEnv;
}

function context(): ExecutionContext {
  return { waitUntil() {}, passThroughOnException() {} } as unknown as ExecutionContext;
}

function hex(bytes: ArrayBuffer): string {
  return Array.from(new Uint8Array(bytes), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function signedAdminRequest(path: string, value: unknown, nonce: string): Promise<Request> {
  const body = JSON.stringify(value);
  const timestamp = String(Math.floor(Date.now() / 1000));
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(HMAC_SECRET), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const signature = hex(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(`${timestamp}.${nonce}.${body}`)));
  return new Request(`https://stable-worker.workers.dev${path}`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-ii-v21-timestamp": timestamp,
      "x-ii-v21-nonce": nonce,
      "x-ii-v21-signature": signature,
    },
    body,
  });
}

async function signedRequest(record: FreeRelayRouteRecord, nonce = "1234567890abcdef1234567890abcdef"): Promise<Request> {
  return signedAdminRequest("/v213/admin/free-relay-route", record, nonce);
}

function healthy(model = MODEL): Response {
  return Response.json({
    ok: true,
    service: "v213-local-llm-gateway",
    health_schema_version: 2,
    llama_reachable: true,
    selected_model_available: true,
    selected_model: model,
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("R75 FREE_RELAY route lease", () => {
  it("keeps legacy test-push authenticated but routes it to the seven-field broadcaster", async () => {
    const e = env(relayObject().object);
    const spy = vi.spyOn(sevenFieldBroadcast, "broadcastV213Top20").mockResolvedValue({status:"synthetic_no_send",format:"v213_seven_fields"});
    try {
      const denied = await productionWorker.fetch(new Request("https://synthetic.workers.dev/v21/admin/test-push", {method:"POST",body:"{}"}), e, context());
      expect(denied.status).toBe(401); expect(spy).not.toHaveBeenCalled();
      const signed = await signedAdminRequest("/v21/admin/test-push", {}, "abcdef0123456789abcdef0123456789");
      const response = await productionWorker.fetch(signed, e, context());
      expect(response.status).toBe(200);
      expect(await response.json()).toMatchObject({format:"v213_seven_fields"});
      expect(spy).toHaveBeenCalledWith(e, "test");
    } finally { spy.mockRestore(); }
  });
  it("requires exactly three public schema-v2 health checks before atomic publication", async () => {
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      calls.push(String(input));
      return healthy();
    }));
    const relay = relayObject();
    const record = route("11111111111111111111111111111111");
    const response = await productionWorker.fetch(await signedRequest(record), env(relay.object), context());
    expect(response.status).toBe(200);
    expect(calls).toHaveLength(3);
    expect(calls.every((value) => value.endsWith(".trycloudflare.com/health"))).toBe(true);
    const current = await relay.object.fetch(new Request("https://free-relay.internal/current"));
    expect(current.status).toBe(200);
  });

  it("rejects replay of an otherwise valid signed route request", async () => {
    const relay = relayObject();
    const fetchMock = vi.fn(async () => healthy());
    vi.stubGlobal("fetch", fetchMock);
    const request = await signedRequest(route("12121212121212121212121212121212"));
    const replay = request.clone();
    const runtime = env(relay.object);
    expect((await productionWorker.fetch(request, runtime, context())).status).toBe(200);
    const rejected = await productionWorker.fetch(replay as any, runtime, context());
    expect(rejected.status).toBe(401);
    expect(await rejected.json()).toMatchObject({ ok: false, code: "V21_SYNC_REPLAY" });
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("rejects unsigned registration and exact-model mismatch without changing the old route", async () => {
    const relay = relayObject();
    const old = route("22222222222222222222222222222222", -10_000);
    await relay.object.fetch(new Request("https://free-relay.internal/update", { method: "POST", body: JSON.stringify(old) }));
    const unsigned = await productionWorker.fetch(new Request("https://stable-worker.workers.dev/v213/admin/free-relay-route", { method: "POST", body: JSON.stringify(route("33333333333333333333333333333333")) }), env(relay.object), context());
    expect(unsigned.status).toBe(401);
    const wrong = { ...route("44444444444444444444444444444444", 1_000), model: "other-model" } as FreeRelayRouteRecord;
    await expect(() => parseFreeRelayRoute(JSON.stringify(wrong), env(relay.object))).toThrow("FREE_RELAY_ROUTE_INVALID");
    const current = await (await relay.object.fetch(new Request("https://free-relay.internal/current"))).json<FreeRelayRouteRecord>();
    expect(current.route_generation).toBe(old.route_generation);
  });

  it("rejects malformed, expired, stale and replayed records", async () => {
    const runtime = env(relayObject().object);
    expect(() => parseFreeRelayRoute("{}", runtime)).toThrow("FREE_RELAY_ROUTE_KEYS_INVALID");
    expect(() => parseFreeRelayRoute(JSON.stringify({ ...route("55555555555555555555555555555555"), tunnel_mode: "quick_test" }), runtime)).toThrow("FREE_RELAY_ROUTE_INVALID");
    const first = route("66666666666666666666666666666666", -20_000);
    const applied = applyFreeRelayUpdate(null, first, []);
    expect(() => applyFreeRelayUpdate(applied.route, first, applied.seen)).toThrow("FREE_RELAY_ROUTE_REPLAY");
    const stale = route("77777777777777777777777777777777", -30_000);
    expect(() => applyFreeRelayUpdate(applied.route, stale, applied.seen)).toThrow("FREE_RELAY_ROUTE_STALE_GENERATION");
    const expired = { ...route("88888888888888888888888888888888"), expires_at: new Date(Date.now() - 1_000).toISOString() };
    expect(() => applyFreeRelayUpdate(null, expired, [])).toThrow("FREE_RELAY_ROUTE_EXPIRED");
  });

  it("serializes concurrent generations and keeps the newest route", async () => {
    const relay = relayObject();
    const newer = route("99999999999999999999999999999999", 2_000);
    const older = route("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", 1_000);
    const [newResult, oldResult] = await Promise.all([
      relay.object.fetch(new Request("https://free-relay.internal/update", { method: "POST", body: JSON.stringify(newer) })),
      relay.object.fetch(new Request("https://free-relay.internal/update", { method: "POST", body: JSON.stringify(older) })),
    ]);
    expect(newResult.status).toBe(200);
    expect(oldResult.status).toBe(409);
    const current = await (await relay.object.fetch(new Request("https://free-relay.internal/current"))).json<FreeRelayRouteRecord>();
    expect(current.route_generation).toBe(newer.route_generation);
  });

  it("allows monotonic heartbeat only and makes an expired PC route unavailable", async () => {
    const relay = relayObject();
    const first = route("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", -10_000, 60);
    const accepted = await relay.object.fetch(new Request("https://free-relay.internal/update", { method: "POST", body: JSON.stringify(first) }));
    expect(accepted.status).toBe(200);
    const heartbeat = { ...first, expires_at: new Date(Date.now() + 120_000).toISOString() };
    const extended = await relay.object.fetch(new Request("https://free-relay.internal/update", { method: "POST", body: JSON.stringify(heartbeat) }));
    expect(extended.status).toBe(200);
    expect((await extended.json<Record<string, unknown>>()).action).toBe("heartbeat");
    relay.storage.values.set("route:current", { ...heartbeat, expires_at: new Date(Date.now() - 1).toISOString(), accepted_at: new Date().toISOString() });
    expect((await relay.object.fetch(new Request("https://free-relay.internal/current"))).status).toBe(404);
  });

  it("fails health validation on schema/model mismatch before the third check", async () => {
    const fetchMock = vi.fn(async () => healthy("wrong-model"));
    vi.stubGlobal("fetch", fetchMock);
    await expect(verifyFreeRelayPublicHealth(route("cccccccccccccccccccccccccccccccc"))).rejects.toThrow("FREE_RELAY_PUBLIC_HEALTH_MISMATCH");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("uses the production-runtime-supported manual redirect mode and rejects redirects", async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(null, {
      status: 302,
      headers: { location: "https://redirected.example/health" },
    }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(verifyFreeRelayPublicHealth(route("cdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcd"))).rejects.toThrow("FREE_RELAY_PUBLIC_HEALTH_MISMATCH");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({ redirect: "manual" });
  });

  it("adapts the certified Q&A redirect policy for production and still rejects 3xx", async () => {
    const successFetch = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      expect(init?.redirect).toBe("manual");
      return Response.json({ ok: true });
    });
    const input = "https://ephemeral.trycloudflare.com/v1/chat/completions";
    expect((await v213RuntimeCompatibleFetch(successFetch as typeof fetch, input, {
      method: "POST",
      redirect: "error",
    })).status).toBe(200);

    const redirectFetch = vi.fn(async () => new Response(null, {
      status: 307,
      headers: { location: "https://redirected.example/v1/chat/completions" },
    }));
    await expect(v213RuntimeCompatibleFetch(redirectFetch as typeof fetch, input, {
      method: "POST",
      redirect: "error",
    })).rejects.toThrow("V213_LOCAL_MODEL_REDIRECT_REJECTED");
  });

  it("routes Q&A through the current lease with exact model and per-generation authentication", async () => {
    const relay = relayObject();
    const current = route("dddddddddddddddddddddddddddddddd", -1_000);
    await relay.object.fetch(new Request("https://free-relay.internal/update", { method: "POST", body: JSON.stringify(current) }));
    let target = "";
    let sent: RequestInit | undefined;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      target = String(input); sent = init;
      return Response.json({ choices: [{ message: { content: "relay answer" } }] });
    }));
    const runtime = env(relay.object);
    const answer = await generalAnswer(await freeRelayRequestEnv(runtime), parseQuery("explain photonics"), { tenantId: "synthetic", chatType: "user" });
    expect(answer).toBe("relay answer");
    expect(target).toBe(`${current.public_url}/v1/chat/completions`);
    expect(JSON.parse(String(sent?.body))).toMatchObject({ model: MODEL });
    const expectedSecret = await freeRelayGatewaySecret(runtime, current.route_generation);
    expect(sent?.headers).toMatchObject({ "x-investor-shared-secret": expectedSecret });
    expect(target).not.toContain("workers.dev");
  });

  it("provides a signed, fixed-prompt smoke without snapshot writes (auth nonce is written)", async () => {
    const relay = relayObject();
    const current = route("efefefefefefefefefefefefefefefef", -1_000);
    await relay.object.fetch(new Request("https://free-relay.internal/update", {
      method: "POST",
      body: JSON.stringify(current),
    }));
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      expect(String(input)).toBe(`${current.public_url}/v1/chat/completions`);
      return Response.json({ choices: [{ finish_reason: "stop", message: { content: "R75_FREE_RELAY_E2E_OK" } }], ii_exact_model_pin: { selected_model: "qwen38-q6", request_model_substitution_allowed: false } });
    });
    vi.stubGlobal("fetch", fetchMock);
    const response = await productionWorker.fetch(
      await signedAdminRequest("/v213/admin/free-relay-smoke", { schema_version: 1 }, "fedcba0987654321fedcba0987654321"),
      env(relay.object),
      context(),
    );
    expect(response.status).toBe(200);
    expect(await response.json()).toMatchObject({
      ok: true,
      status: "PASS",
      model: MODEL,
      expected_token_observed: true,
      stable_entrypoint: "workers_dev",
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("derives the same non-persisted per-generation gateway secret deterministically", async () => {
    const runtime = env(relayObject().object);
    const first = await freeRelayGatewaySecret(runtime, "dddddddddddddddddddddddddddddddd");
    const second = await freeRelayGatewaySecret(runtime, "dddddddddddddddddddddddddddddddd");
    const other = await freeRelayGatewaySecret(runtime, "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee");
    expect(first).toMatch(/^[0-9a-f]{64}$/);
    expect(first).toBe(second);
    expect(first).not.toBe(other);
  });
});
