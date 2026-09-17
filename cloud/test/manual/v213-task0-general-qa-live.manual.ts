import { afterAll, beforeAll, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { createHmac } from "node:crypto";
import {
  createStrictBoundary,
  finalAnswerCheck,
  startDrain,
  jobIdStrict,
  readProfileJson,
  startLocalGateway,
  type LocalGatewayHandle,
  type StrictBoundary,
} from "../helpers/task0-general-qa-harness";
import { type FreeRelayRouteRecord } from "../../src/v213/free-relay";
import { deriveTenantId } from "../../src/security";
import { storeOwnerPairing } from "../../src/v21/owner-storage";
import { asKv, MemoryKv } from "../fake-kv";

const OPTIN = "authorize-task0-live-phase1f";
const EXL3 = "Qwen3.8-27B-EXL3-SC5-H6-V6";
const EVIDENCE_HOST = "task0-phase1f-live.trycloudflare.com";
const LINE_CHANNEL_SECRET = "EXAMPLE_TASK0_PHASE1F_ONLY_NOT_REAL_0123456789abcdef";
const HMAC_SECRET = "EXAMPLE_TASK0_PHASE1F_HMAC_SECRET_NOT_REAL_0123456789";
const TENANT_SECRET = "EXAMPLE_TASK0_PHASE1F_TENANT_HASH_NOT_REAL_012345";

// Capture the real fetch exactly once at module load (before any stub).
const REAL_FETCH: typeof fetch = globalThis.fetch.bind(globalThis);

let boundary: StrictBoundary | null = null;
let gateway: LocalGatewayHandle | null = null;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let productionWorker: any;
let freeRelayRequestEnv: (env: unknown) => Promise<unknown>;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let minimalModelSmokeExport: any;
let SMOKE_MARKER = "";
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let V213FreeRelayRoute: any;

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
  const object = new V213FreeRelayRoute({ storage } as unknown as DurableObjectState);
  const seed = (rec: FreeRelayRouteRecord) =>
    object.fetch(new Request("https://free-relay.internal/update", { method: "POST", body: JSON.stringify(rec) }));
  const namespace = {
    idFromName: () => ({ toString: () => "task0-phase1f-live" }),
    get: () => ({ fetch: (input: RequestInfo | URL, init?: RequestInit) => object.fetch(new Request(input, init)) }),
  } as unknown as DurableObjectNamespace;
  return { seed, namespace };
}

function fixtureKeyValue(): Array<[string, string]> {
  const objects = JSON.parse(readFileSync(new URL("../fixtures/task0-phase1d/objects.json", import.meta.url), "utf-8")) as Record<string, string>;
  const pointer = readFileSync(new URL("../fixtures/task0-phase1d/pointer.raw.json", import.meta.url), "utf-8").trim();
  return [...Object.entries(objects), ["snapshot:current", pointer]];
}

function workerEnv(namespace: DurableObjectNamespace) {
  const kv = new MemoryKv();
  for (const [k, v] of fixtureKeyValue()) kv.values.set(k, v);
  return {
    PUBLIC_CACHE: asKv(kv),
    TENANT_PRIVATE_CACHE: asKv(new MemoryKv()),
    EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()),
    V21_SYNC_HMAC_SECRET: HMAC_SECRET,
    TENANT_DATA_ENCRYPTION_KEY: "e".repeat(64),
    TENANT_HASH_SECRET: TENANT_SECRET,
    LINE_CHANNEL_SECRET,
    LINE_CHANNEL_ACCESS_TOKEN: "EXAMPLE_TASK0_PHASE1F_ACCESS_NOT_REAL",
    FREE_RELAY_ENABLED: "true",
    FREE_RELAY_MAX_TTL_SECONDS: "300",
    LOCAL_LLM_MODEL: EXL3,
    V213_COMPACT_QA_ENABLED: "true",
    V213_LINE_PRESENTATION: "text",
    V213_MODEL_PROFILE_JSON: readProfileJson(),
    V213_FREE_RELAY_ROUTE: namespace,
  };
}

function textEvent(id: number, token: string, text: string): string {
  return JSON.stringify({
    destination: "owner",
    events: [{
      replyToken: token,
      source: { type: "user", userId: "u_task0_phase1f" },
      timestamp: Date.now(),
      type: "message",
      message: { id, type: "text", text },
    }],
  });
}

async function runWebhook(
  env: unknown,
  rawBody: string,
): Promise<{ status: number; lines: string[]; unhandledRejected: number }> {
  const drain = startDrain(30_000);
  const windowStart = boundary ? boundary.lineReplies.length : 0;
  const ctx = {
    waitUntil(p: Promise<unknown>) { drain.add(p); },
    passThroughOnException() {},
  } as unknown as ExecutionContext;
  const body = new TextEncoder().encode(rawBody);
  const signature = createHmac("sha256", LINE_CHANNEL_SECRET).update(rawBody).digest("base64");
  const req = new Request("https://investor-intelligence-v21-owner-line.example/webhook", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "content-length": String(body.byteLength),
      "x-line-signature": signature,
    },
    body,
  });
  const res = await productionWorker.fetch(req, env, ctx);
  const settled = await drain.settle(); // real-time race; rejections preserved
  const lines = boundary ? boundary.lineReplies.slice(windowStart).flatMap((r) => r.texts) : [];
  return { status: res.status, lines, unhandledRejected: settled.rejected };
}

beforeAll(async () => {
  if (process.env.II_TASK0_LIVE_OPTIN !== OPTIN) {
    // Hard gate (1G): running the live-only runner without opt-in MUST fail
    // (never a silent inert pass); zero spawns / zero model work in that case.
    throw new Error(`TASK0_LIVE_OPTIN_REQUIRED: set II_TASK0_LIVE_OPTIN=${OPTIN} (opt-in is REQUIRED); no gateway spawn or model call was made`);
  }
  gateway = await startLocalGateway({
    model: EXL3,
    llamaBaseUrl: "http://127.0.0.1:5000",
    profileJson: readProfileJson(),
    nativeFetch: REAL_FETCH,
  });
  boundary = createStrictBoundary(EVIDENCE_HOST, gateway, REAL_FETCH);
  globalThis.fetch = boundary.fetch as typeof fetch;
  const workerMod = await import("../../src/v213/production-worker");
  productionWorker = workerMod.default;
  freeRelayRequestEnv = workerMod.freeRelayRequestEnv as unknown as (env: unknown) => Promise<unknown>;
  const compact = await import("../../src/v213/compact-qa");
  minimalModelSmokeExport = compact.minimalModelSmoke;
  SMOKE_MARKER = compact.SMOKE_MARKER;
  const freeRelay = await import("../../src/v213/free-relay");
  V213FreeRelayRoute = freeRelay.V213FreeRelayRoute;
}, 240_000);

afterAll(async () => {
  vi.useRealTimers();
  globalThis.fetch = REAL_FETCH;
  if (gateway) {
    await gateway.stop();
    gateway = null;
  }
  if (boundary) {
    console.error(
      `TASK0_GATEWAY_RELEASED modelCalls=${boundary.modelCalls.length} lineReplies=${boundary.lineReplies.length} violations=${boundary.violations.length}`,
    );
    if (boundary.violations.length > 0) console.error("TASK0_BOUNDARY_VIOLATIONS:", boundary.violations);
  }
});

it("opt-in live: exact smoke marker + ONE Chinese general QA completion via the formal caller and the runtime adapter", async () => {
  if (process.env.II_TASK0_LIVE_OPTIN !== OPTIN) {
    throw new Error("TASK0_LIVE_OPTIN_REQUIRED: this live-only runner must not run without opt-in (opt-in is REQUIRED)");
  }
  expect(process.env.II_TASK0_LIVE_OPTIN).toBe(OPTIN);
  // Align the worker's execution clock to the committed fixture so the
  // sealed snapshot counts as FRESH (Date-only fake; real wall clock stays on
  // the gateway child and all I/O).
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(Date.parse("2026-09-17T09:24:10Z") + 3_600_000));
  const dev = relayDevice();
  const now = Date.now();
  await dev.seed({
    schema_version: 1,
    tunnel_mode: "quick_free_relay",
    model: EXL3,
    public_url: `https://${EVIDENCE_HOST}`,
    connected_at: new Date(now - 60_000).toISOString(),
    expires_at: new Date(now + 300_000).toISOString(),
    health_schema_version: 2,
    route_generation: "ab11cd22ef33ab44cd55ef66ab77cd88",
    consecutive_health_checks: 3,
  } satisfies FreeRelayRouteRecord);
  const env = workerEnv(dev.namespace);
  const tenantId = await deriveTenantId({ type: "user", userId: "u_task0_phase1f" } as never, TENANT_SECRET);
  await storeOwnerPairing(env as never, tenantId, "U" + "a".repeat(32));

  // 1) Smoke through the real gateway + adapter + boundary (transport proof).
  const leaseEnv = await freeRelayRequestEnv(env);
  expect(await minimalModelSmokeExport(leaseEnv)).toBe(true);
  expect(boundary!.modelCalls.length).toBe(1);
  expect(boundary!.modelCalls[0]?.status).toBe(200);
  expect(boundary!.modelCalls[0]?.model).toBe(EXL3);
  expect(boundary!.lineReplies.length).toBe(0);

  // 2) ONE Chinese general QA through the formal webhook caller.
  const res = await runWebhook(env, textEvent(1, "live_qa_token", "请简短解释：股票和债券的主要区别是什么？"));
  expect(res.status).toBe(200);
  expect(res.unhandledRejected).toBe(0);
  const qaCalls = boundary!.modelCalls.length - 1;
  expect(qaCalls).toBeGreaterThanOrEqual(1);
  expect(qaCalls).toBeLessThanOrEqual(3);
  for (const c of boundary!.modelCalls.slice(1)) {
    expect(c.status).toBe(200);
    expect(c.model).toBe(EXL3);
    // Structural completion: the transport MUST prove a usable completion.
    expect(c.finishReason).toBe("stop");
    expect(c.modelReturned).toBe(EXL3);
  }
  let finalText = res.lines.join("\n");
  const jobId = jobIdStrict(finalText);
  if (jobId) {
    // JO (reference issued): the first reply is NOT the answer. Follow ONLY
    // the formal result query path（不读 KV）and assert the final answer.
    const beforeCalls = boundary!.modelCalls.length;
    const res2 = await runWebhook(env, textEvent(2, "live_result_token", `查看結果 ${jobId}`));
    expect(res2.status).toBe(200);
    expect(res2.unhandledRejected).toBe(0);
    expect(boundary!.modelCalls.length).toBe(beforeCalls); // result query re-runs no model
    finalText = res2.lines.join("\n");
  }
  expect(finalText.length).toBeGreaterThan(0);
  expect(finalText).not.toContain(SMOKE_MARKER);
  expect(finalText).not.toContain("本机模型桥接");
  const qaCheck = finalAnswerCheck(finalText, SMOKE_MARKER);
  expect(qaCheck, `QA final rejected: ${qaCheck.reason}`).toEqual({ ok: true, reason: "OK" });

  // 3) Close-out invariants.
  expect(boundary!.violations.length).toBe(0);
  if (boundary!.lineReplies.length > 0) {
    expect(boundary!.lineReplies.every((r) => r.sawBearer && r.textCount > 0)).toBe(true);
  }
}, 600_000);