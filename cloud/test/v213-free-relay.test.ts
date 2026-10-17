import { afterEach, describe, expect, it, vi } from "vitest";
import productionWorker, { freeRelayRequestEnv, v213RuntimeCompatibleFetch } from "../src/v213/production-worker";
import { parseQuery } from "../src/core";
import * as sevenFieldBroadcast from "../src/v213/broadcast";
import { generalAnswer } from "../src/qa";
import {
  V213FreeRelayRoute,
  applyFreeRelayClaim,
  FREE_RELAY_SIGNATURE_PURPOSE,
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

function env(object: V213FreeRelayRoute, kv = new MemoryKv()): V211Env & FreeRelayEnv {
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

async function signedAdminRequest(path: string, value: unknown, nonce: string, at = Math.floor(Date.now() / 1000), purpose = ""): Promise<Request> {
  const body = JSON.stringify(value);
  const timestamp = String(at);
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(HMAC_SECRET), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const signature = hex(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(`${purpose ? `${purpose}
` : ""}${timestamp}.${nonce}.${body}`)));
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

/** A route refresh as the heartbeat signs it (purpose-bound). */
async function signedRequest(record: FreeRelayRouteRecord, nonce = "1234567890abcdef1234567890abcdef", at = Math.floor(Date.now() / 1000)): Promise<Request> {
  return signedAdminRequest("/v213/admin/free-relay-route", record, nonce, at, FREE_RELAY_SIGNATURE_PURPOSE);
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
  it.each(["/v21/admin/public-snapshot", "/v212/admin/top20-report", "/v213/admin/top20-report"])("retires %s before any nonce, storage or model access, including signed legacy clients", async path => {
    const blockedEnv = new Proxy({}, {get() {throw new Error("UNEXPECTED_RETIRED_ROUTE_ACCESS");}});
    const requests = [new Request("https://synthetic.workers.dev"+path, {method:"POST",body:"{}"}), await signedAdminRequest(path, {}, "1234abcd5678ef901234abcd5678ef90")];
    for (const request of requests) {
      const response = await productionWorker.fetch(request, blockedEnv as any, context());
      expect(response.status).toBe(410);
      expect(await response.json()).toEqual({ok:false,code:"V213_SEALED_PUBLICATION_REQUIRED"});
    }
  });
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

  it("refreshes the route every minute without a single KV write (the replay guard lives in the Durable Object)", async () => {
    // 2026-09-26: a KV nonce per heartbeat (~1,400 a day) alone exceeded the free plan's 1,000 KV writes a day.
    const relay = relayObject();
    const kv = new MemoryKv();
    const put = vi.spyOn(kv, "put");
    vi.stubGlobal("fetch", vi.fn(async () => healthy()));
    const runtime = env(relay.object, kv);
    const first = route("13131313131313131313131313131313", -10_000, 60);
    const now = Math.floor(Date.now() / 1000);
    for (let beat = 0; beat < 5; beat += 1) {
      const record = { ...first, expires_at: new Date(Date.now() + 60_000 + beat * 10_000).toISOString() };
      const response = await productionWorker.fetch(await signedRequest(record, `${String(beat).repeat(32)}`, now - 4 + beat), runtime, context());
      expect(response.status, `beat ${beat}`).toBe(200);
    }
    expect(put).not.toHaveBeenCalled();
    expect(kv.values.size).toBe(0);
    expect(relay.storage.values.get("route:admin-claims")).toMatchObject({ timestamp: now });
  });

  it("refuses an older signed refresh with a fresh nonce and a reused nonce within the same second, before any health check", async () => {
    const relay = relayObject();
    const fetchMock = vi.fn(async () => healthy());
    vi.stubGlobal("fetch", fetchMock);
    const runtime = env(relay.object);
    const now = Math.floor(Date.now() / 1000);
    const record = route("14141414141414141414141414141414", -10_000, 60);
    expect((await productionWorker.fetch(await signedRequest(record, "a".repeat(32), now), runtime, context())).status).toBe(200);
    const later = { ...record, expires_at: new Date(Date.now() + 90_000).toISOString() };
    const older = await productionWorker.fetch(await signedRequest(later, "b".repeat(32), now - 1), runtime, context());
    expect(older.status).toBe(401);
    expect(await older.json()).toMatchObject({ ok: false, code: "V21_SYNC_REPLAY" });
    const sameSecondReused = await productionWorker.fetch(await signedRequest(later, "a".repeat(32), now), runtime, context());
    expect(sameSecondReused.status).toBe(401);
    expect(fetchMock).toHaveBeenCalledTimes(3);  // only the first request reached the health checks
    const sameSecondFresh = await productionWorker.fetch(await signedRequest(later, "c".repeat(32), now), runtime, context());
    expect(sameSecondFresh.status).toBe(200);
    const unsigned = await productionWorker.fetch(new Request("https://stable-worker.workers.dev/v213/admin/free-relay-route", { method: "POST", body: JSON.stringify(later) }), runtime, context());
    expect(unsigned.status).toBe(401);
    expect(await unsigned.json()).toMatchObject({ ok: false, code: "V21_SYNC_AUTH_INVALID" });
  });

  it("never lets a route refresh authenticate at another admin endpoint, in either direction (delivery mocked)", async () => {
    const spy = vi.spyOn(sevenFieldBroadcast, "broadcastV213Top20").mockResolvedValue({ status: "synthetic_no_send", format: "v213_seven_fields" });
    vi.stubGlobal("fetch", vi.fn(async () => healthy()));
    try {
      for (const alias of ["/v213/admin/test-push", "/v21/admin/test-push"]) {
        const relay = relayObject();
        const kv = new MemoryKv();
        const runtime = env(relay.object, kv);
        const record = route("15151515151515151515151515151515", -10_000, 60);
        // (1) A purpose-bound refresh succeeds without KV; its exact bytes are refused at test-push (signature mismatch).
        const refresh = await signedRequest(record, "d".repeat(32));
        const captured = refresh.clone();
        expect((await productionWorker.fetch(refresh, runtime, context())).status).toBe(200);
        expect(kv.values.size).toBe(0);
        const replayed = await productionWorker.fetch(new Request(`https://stable-worker.workers.dev${alias}`, {
          method: "POST", headers: captured.headers, body: await captured.text() }), runtime, context());
        expect(replayed.status, alias).toBe(401);
        expect(await replayed.json()).toMatchObject({ ok: false, code: "V21_SYNC_SIGNATURE_INVALID" });
        // (2) A generic admin signature at the route endpoint takes the legacy path and spends its KV nonce there, so the same
        // bytes are then refused at test-push as a replay; and a test-push first makes the route endpoint refuse them.
        const later = { ...record, expires_at: new Date(Date.now() + 100_000).toISOString() };
        const legacy = await signedAdminRequest("/v213/admin/free-relay-route", later, "e".repeat(32));
        const legacyCopy = legacy.clone();
        expect((await productionWorker.fetch(legacy, runtime, context())).status).toBe(200);
        expect([...kv.values.keys()].some(key => key.startsWith("v21:sync-nonce:"))).toBe(true);
        const legacyReplay = await productionWorker.fetch(new Request(`https://stable-worker.workers.dev${alias}`, {
          method: "POST", headers: legacyCopy.headers, body: await legacyCopy.text() }), runtime, context());
        expect(await legacyReplay.json()).toMatchObject({ ok: false, code: "V21_SYNC_REPLAY" });
        const push = await signedAdminRequest(alias, later, "f".repeat(32));
        const pushCopy = push.clone();
        expect((await productionWorker.fetch(push, runtime, context())).status).toBe(200);
        const pushReplay = await productionWorker.fetch(new Request("https://stable-worker.workers.dev/v213/admin/free-relay-route", {
          method: "POST", headers: pushCopy.headers, body: await pushCopy.text() }), runtime, context());
        expect(pushReplay.status).toBe(401);
        expect(await pushReplay.json()).toMatchObject({ ok: false, code: "V21_SYNC_REPLAY" });
      }
      expect(spy).toHaveBeenCalledTimes(2);  // only the two genuinely signed test-push requests
    } finally { spy.mockRestore(); }
  });

  it("admits concurrent same-second refreshes once each, survives a restart on the same storage, and recovers from a clock step back", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => healthy()));
    const storage = new FakeStorage();
    const first = relayObject(storage);
    const kv = new MemoryKv();
    const runtime = env(first.object, kv);
    const now = Math.floor(Date.now() / 1000);
    const record = route("16161616161616161616161616161616", -10_000, 60);
    const beats = [0, 1, 2].map(i => ({ ...record, expires_at: new Date(Date.now() + 70_000 + i * 5_000).toISOString() }));
    const requests = await Promise.all(beats.map((beat, i) => signedRequest(beat, String(i + 1).repeat(32), now)));
    const copies = requests.map(request => request.clone());
    const results = await Promise.all(requests.map(request => productionWorker.fetch(request, runtime, context())));
    expect(results.every(response => response.status < 500)).toBe(true);
    expect(results.filter(response => response.status === 200).length).toBeGreaterThanOrEqual(1);
    expect(kv.values.size).toBe(0);
    // A fresh object on the same durable storage (eviction/restart) still refuses every admitted request.
    const restarted = relayObject(storage);
    const afterRestart = env(restarted.object, kv);
    for (const copy of copies) {
      const replay = await productionWorker.fetch(copy as any, afterRestart, context());
      expect(replay.status).toBe(401);
    }
    // A signer whose clock stepped back is refused until it passes the stored second again (bounded by the 300 s window).
    const stepped = await productionWorker.fetch(await signedRequest(beats[2]!, "7".repeat(32), now - 30), afterRestart, context());
    expect(stepped.status).toBe(401);
    const recovered = await productionWorker.fetch(await signedRequest({ ...record, expires_at: new Date(Date.now() + 90_000).toISOString() },
      "8".repeat(32), now + 1), afterRestart, context());
    expect(recovered.status).toBe(200);
  });

  it("models a skewed PC clock end to end: lease dates and signature both from the PC, fail closed, recover after resync", async () => {
    // The heartbeat builds connected_at/expires_at AND the signed timestamp from the PC clock (New-V213FreeRelayRouteRecord,
    // Publish-V213FreeRelayRoute). The Worker judges them against its own clock.
    vi.useFakeTimers({ toFake: ["Date"] });
    try {
      vi.stubGlobal("fetch", vi.fn(async () => healthy()));
      const worker = Date.UTC(2026, 8, 27, 6, 0, 0);
      vi.setSystemTime(worker);
      const relay = relayObject();
      const runtime = env(relay.object);
      let nonce = 0;
      const connected = new Date(worker - 600_000).toISOString();  // fixed when the tunnel connected (same generation)
      const beat = async (skewSeconds: number) => {
        const pc = Date.now() + skewSeconds * 1000;  // the PC's idea of "now"
        const record = { ...route("17171717171717171717171717171717"), connected_at: connected, expires_at: new Date(pc + 180_000).toISOString() };
        nonce += 1;
        return productionWorker.fetch(await signedRequest(record, nonce.toString(16).padStart(32, "0"), Math.floor(pc / 1000)), runtime, context());
      };
      expect((await beat(0)).status).toBe(200);
      // PC 180 s behind: every lease it writes expires on arrival (expires_at <= Worker now + 15 s) -> refused, every beat.
      vi.setSystemTime(worker + 400_000);
      for (let i = 0; i < 3; i += 1) expect((await beat(-180)).status, `behind ${i}`).not.toBe(200);
      // Resynchronized: the next beat succeeds (the claim's high-water mark is in the past, the lease dates are valid again).
      expect((await beat(0)).status).toBe(200);
      // PC 120 s ahead: its signed second is admitted as the new high-water mark and its lease is still acceptable, so it works
      // while skewed; after a resync that steps the clock back 120 s, beats are refused until Worker time passes that mark...
      vi.setSystemTime(worker + 500_000);
      expect((await beat(120)).status).toBe(200);
      vi.setSystemTime(worker + 560_000);
      expect((await beat(0)).status).toBe(401);  // V21_SYNC_REPLAY: older than the admitted second
      // ...and succeed again one heartbeat after it (bounded by the skew, itself bounded by the 300 s signature window).
      vi.setSystemTime(worker + 500_000 + 121_000);
      expect((await beat(0)).status).toBe(200);
      // PC 240 s ahead: signature valid, lease refused (it would end 420 s ahead) BEFORE the claim, so the mark does not move
      // and the corrected PC succeeds at once (Astra batch 30).
      vi.setSystemTime(worker + 800_000);
      const mark = relay.storage.values.get("route:admin-claims") as { timestamp: number };
      const far = await beat(240);
      expect(far.status).toBe(400);
      expect(await far.json()).toMatchObject({ ok: false, code: "FREE_RELAY_ROUTE_INVALID" });
      expect(relay.storage.values.get("route:admin-claims")).toEqual(mark);
      expect((await beat(0)).status).toBe(200);
      // A PC more than the 300 s signature window off is refused outright until it is resynchronized.
      expect((await beat(-400)).status).toBe(401);
      expect((await beat(400)).status).toBe(401);
    } finally {
      vi.useRealTimers();
    }
  });

  it("claims nonces monotonically and boundedly", () => {
    const digest = (c: string) => c.repeat(64);
    const first = applyFreeRelayClaim(null, 100, digest("a"));
    expect(first).toEqual({ timestamp: 100, nonces: [digest("a")] });
    expect(applyFreeRelayClaim(first, 101, digest("a"))).toEqual({ timestamp: 101, nonces: [digest("a")] });
    expect(() => applyFreeRelayClaim(first, 99, digest("b"))).toThrow("V21_SYNC_REPLAY");
    expect(() => applyFreeRelayClaim(first, 100, digest("a"))).toThrow("V21_SYNC_REPLAY");
    let state = first;
    const distinct = (i: number) => i.toString(16).padStart(64, "0");
    for (let i = 1; i < 16; i += 1) state = applyFreeRelayClaim(state, 100, distinct(i));
    expect(state.nonces).toHaveLength(16);
    expect(() => applyFreeRelayClaim(state, 100, distinct(99))).toThrow("V21_SYNC_REPLAY");  // at most 16 a second
    for (const [time, nonce] of [[0, digest("a")], [1.5, digest("a")], [100, "z".repeat(64)], [100, "a".repeat(63)]] as const) {
      expect(() => applyFreeRelayClaim(null, time, nonce)).toThrow("FREE_RELAY_CLAIM_INVALID");
    }
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

  it("follows the route's authenticated model only when LOCAL_LLM_MODEL_FROM_ROUTE is on (a profile keeps its settings only)", async () => {
    const relay = relayObject();
    const moved = { ...route("abababababababababababababababab", -1_000), model: "Qwen3.8-27B" } as FreeRelayRouteRecord;
    const pinned = env(relay.object);
    expect(() => parseFreeRelayRoute(JSON.stringify(moved), pinned)).toThrow("FREE_RELAY_ROUTE_INVALID");
    const following = { ...pinned, LOCAL_LLM_MODEL_FROM_ROUTE: "true" };
    expect(parseFreeRelayRoute(JSON.stringify(moved), following).model).toBe("Qwen3.8-27B");
    expect(() => parseFreeRelayRoute(JSON.stringify({ ...moved, model: "bad model!" }), following)).toThrow("FREE_RELAY_ROUTE_INVALID");
    const profiled = { ...following, V213_MODEL_PROFILE_JSON: JSON.stringify({ schema_version: 1, model: "profile-model", enable_thinking: false,
      reasoning_effort: "none", max_output_tokens: 1024, smoke_output_tokens: 128, timeout_ms: 18000 }) };
    expect(parseFreeRelayRoute(JSON.stringify(moved), profiled).model).toBe("Qwen3.8-27B");  // settings only in route mode
    const { LOCAL_LLM_MODEL_FROM_ROUTE: _off, ...profiledPinned } = profiled;
    expect(() => parseFreeRelayRoute(JSON.stringify(moved), profiledPinned)).toThrow("FREE_RELAY_ROUTE_INVALID");  // pinned without it
    await relay.object.fetch(new Request("https://free-relay.internal/update", { method: "POST", body: JSON.stringify(moved) }));
    let sent: RequestInit | undefined;
    vi.stubGlobal("fetch", vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      sent = init;
      return Response.json({ choices: [{ message: { content: "relay answer" } }] });
    }));
    expect((await freeRelayRequestEnv(pinned)).LOCAL_LLM_BASE_URL).toBe("");  // pinned Worker ignores the moved route
    const answer = await generalAnswer(await freeRelayRequestEnv(following), parseQuery("explain photonics"), { tenantId: "synthetic", chatType: "user" });
    expect(answer).toBe("relay answer");
    expect(JSON.parse(String(sent?.body))).toMatchObject({ model: "Qwen3.8-27B" });
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

  it("keeps the KV nonce for every other admin request (the smoke runs rarely)", async () => {
    const relay = relayObject();
    await relay.object.fetch(new Request("https://free-relay.internal/update", { method: "POST", body: JSON.stringify(route("fdfdfdfdfdfdfdfdfdfdfdfdfdfdfdfd", -1_000)) }));
    vi.stubGlobal("fetch", vi.fn(async () => Response.json({ choices: [{ finish_reason: "stop", message: { content: "R75_FREE_RELAY_E2E_OK" } }],
      ii_exact_model_pin: { selected_model: "qwen38-q6", request_model_substitution_allowed: false } })));
    const kv = new MemoryKv();
    const runtime = env(relay.object, kv);
    const request = await signedAdminRequest("/v213/admin/free-relay-smoke", { schema_version: 1 }, "1".repeat(32));
    const replay = request.clone();
    expect((await productionWorker.fetch(request, runtime, context())).status).toBe(200);
    expect([...kv.values.keys()].some(key => key.startsWith("v21:sync-nonce:"))).toBe(true);
    const rejected = await productionWorker.fetch(replay as any, runtime, context());
    expect(await rejected.json()).toMatchObject({ ok: false, code: "V21_SYNC_REPLAY" });
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
