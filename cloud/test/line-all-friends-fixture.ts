/** Synthetic fixtures for the all-friends LINE access tests: real Worker caller, fake KV, fake LINE, fake model, fake gate DO. */
/// <reference types="node" />
import { createHmac } from "node:crypto";
import { vi } from "vitest";
import approvedProfile from "../../config/v213-model-profile-v1.json";
import productionWorker from "../src/v213/production-worker";
import { V213FriendQaGate } from "../src/v213/friend-qa-gate";
import { deriveTenantId } from "../src/security";
import { storeOwnerPairing } from "../src/v21/owner-storage";
import { asKv, MemoryKv } from "./fake-kv";

export const lineUser = (fill: string): string => String.fromCharCode(85) + fill.repeat(32);
export const OWNER_USER = lineUser("1");
export const FRIEND_A = lineUser("a");
export const FRIEND_B = lineUser("b");
export const FRIEND_C = lineUser("c");
export const MODEL_ANSWER = "SYNTHETIC_FRIEND_ANSWER_NOT_LIVE";
export const QUESTION = "景氣循環如何影響企業融資？";

export interface GateOptions {
  /** "throw": every call rejects. "malformed": every call answers garbage. "hang": no call ever answers. */
  failure?: "throw" | "malformed" | "hang";
}

/** Durable Object fixture with the storage API the gate uses. Transactions are serialised; fetches are not (a waiting acquire must not block a release). */
export function memoryFriendGate(options: GateOptions = {}) {
  const values = new Map<string, unknown>();
  const calls: Array<{ action: string; body: Record<string, unknown> }> = [];
  let lock: Promise<unknown> = Promise.resolve();
  const view = (map: Map<string, unknown>) => ({
    get: async (key: string) => structuredClone(map.get(key)),
    put: async (key: string, value: unknown) => {
      map.set(key, structuredClone(value));
    },
    delete: async (key: string) => map.delete(key),
    list: async (query: { prefix: string; limit: number }) =>
      new Map(
        [...map]
          .filter(([key]) => key.startsWith(query.prefix))
          .slice(0, query.limit)
          .map(([key, value]) => [key, structuredClone(value)] as const),
      ),
  });
  const state = {
    storage: {
      ...view(values),
      transaction: (callback: (txn: unknown) => Promise<unknown>) => {
        const run = lock.then(async () => {
          const draft = new Map([...values].map(([key, value]) => [key, structuredClone(value)] as const));
          const result = await callback(view(draft));
          values.clear();
          for (const [key, value] of draft) values.set(key, value);
          return result;
        });
        lock = run.then(
          () => undefined,
          () => undefined,
        );
        return run;
      },
    },
  } as unknown as DurableObjectState;
  const instance = new V213FriendQaGate(state);
  const stub = {
    fetch: async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = input instanceof Request ? input : new Request(input, init);
      const parsed = await request
        .clone()
        .json()
        .then((value) => value as Record<string, unknown>)
        .catch(() => ({}) as Record<string, unknown>);
      calls.push({ action: String(parsed.action), body: parsed });
      if (options.failure === "throw") throw new Error("SYNTHETIC_GATE_DOWN");
      if (options.failure === "hang") return new Promise<Response>(() => undefined);
      if (options.failure === "malformed") return new Response("not json at all", { status: 200 });
      return instance.fetch(request);
    },
  };
  const namespace = { idFromName: (name: string) => name, get: () => stub } as unknown as DurableObjectNamespace;
  return { namespace, values, calls, instance };
}

export interface FixtureOptions {
  mode?: string | undefined;
  /** false: no gate binding at all. */
  gate?: false | GateOptions;
  ownerPaired?: boolean;
  env?: Record<string, string>;
}

export async function lineFixture(options: FixtureOptions = {}) {
  if (vi.isMockFunction(globalThis.fetch) || vi.isMockFunction(globalThis.setTimeout)) throw new Error("SYNTHETIC_FIXTURE_ALREADY_OPEN");
  const publicKv = new MemoryKv();
  const privateKv = new MemoryKv();
  const securityKv = new MemoryKv();
  const gate = options.gate === false ? null : memoryFriendGate(options.gate ?? {});
  const env: Record<string, unknown> = {
    PUBLIC_CACHE: asKv(publicKv),
    TENANT_PRIVATE_CACHE: asKv(privateKv),
    EPHEMERAL_SECURITY_CACHE: asKv(securityKv),
    LINE_CHANNEL_SECRET: "SYNTHETIC_FRIEND_SIGNATURE_NOT_REAL",
    LINE_CHANNEL_ACCESS_TOKEN: "SYNTHETIC_FRIEND_REPLY_NOT_REAL",
    TENANT_HASH_SECRET: "SYNTHETIC_FRIEND_TENANT_NOT_REAL",
    TENANT_DATA_ENCRYPTION_KEY: "SYNTHETIC_FRIEND_DATA_NOT_REAL",
    MEMORY_FEATURE_AVAILABLE: "false",
    CURRENT_PUBLIC_DATA_ENABLED: "true",
    GENERAL_QA_ENABLED: "true",
    V213_COMPACT_QA_ENABLED: "true",
    LOCAL_LLM_BASE_URL: "https://synthetic-friend-model.example.test",
    LOCAL_LLM_ALLOWED_HOSTS: "synthetic-friend-model.example.test",
    LOCAL_LLM_SHARED_SECRET: "SYNTHETIC_FRIEND_MODEL_NOT_REAL",
    LOCAL_LLM_MODEL: approvedProfile.model,
    V213_MODEL_PROFILE_JSON: JSON.stringify(approvedProfile),
    ...(options.mode === undefined ? {} : { V213_LINE_ACCESS_MODE: options.mode }),
    ...(gate ? { V213_FRIEND_QA_GATE: gate.namespace } : {}),
    ...(options.env ?? {}),
  };
  const hashSecret = String(env.TENANT_HASH_SECRET);
  const tenantOf = (userId: string) => deriveTenantId({ type: "user", userId }, hashSecret);
  if (options.ownerPaired !== false) {
    await storeOwnerPairing(env as never, await tenantOf(OWNER_USER), OWNER_USER);
  }

  const prompts: string[] = [];
  const replies: Array<{ token: string; text: string }> = [];
  const urls: string[] = [];
  const model: { handler: () => Promise<Response> } = {
    handler: async () => new Response(JSON.stringify({ choices: [{ message: { content: MODEL_ANSWER } }] })),
  };
  const network = vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(input instanceof Request ? input.url : String(input));
    urls.push(url.origin + url.pathname);
    const body = JSON.parse(String(init?.body ?? "{}"));
    if (url.origin === "https://synthetic-friend-model.example.test" && url.pathname === "/v1/chat/completions") {
      prompts.push(JSON.stringify(body.messages));
      return model.handler();
    }
    if (url.origin === "https://api.line.me" && url.pathname === "/v2/bot/message/reply") {
      replies.push({ token: String(body.replyToken), text: (body.messages as Array<{ text: string }>).map((m) => m.text).join("\n") });
      return new Response("{}");
    }
    throw new Error("UNEXPECTED_SYNTHETIC_FRIEND_TRANSPORT");
  });

  // The 7 s "answer quickly or park a job" race becomes 250 ms; every other timer is untouched.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const realSetTimeout = globalThis.setTimeout.bind(globalThis) as (...args: any[]) => unknown;
  const timers = vi
    .spyOn(globalThis, "setTimeout")
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    .mockImplementation(((handler: any, ms?: number, ...args: any[]) => realSetTimeout(handler, ms === 7000 ? 250 : ms, ...args)) as never);

  let sequence = 0;
  /** Delivers one signed webhook event and (unless `wait` is false) waits for all of its background work. */
  async function deliver(
    userId: string,
    text: string | null,
    extra: { type?: string; sourceType?: string; wait?: boolean; eventId?: string } = {},
  ): Promise<{ token: string; tasks: Promise<unknown>[]; settle: () => Promise<void> }> {
    const replyToken = `synthetic-reply-token-${++sequence}`;
    const type = extra.type ?? "message";
    const source = extra.sourceType && extra.sourceType !== "user"
      ? { type: extra.sourceType, [`${extra.sourceType}Id`]: "C" + "9".repeat(32), userId }
      : { type: "user", userId };
    const event: Record<string, unknown> = {
      type,
      timestamp: Date.now(),
      webhookEventId: extra.eventId ?? `synthetic-event-${sequence}`,
      replyToken,
      source,
    };
    if (type === "message") event.message = { type: "text", id: String(sequence), text };
    const body = JSON.stringify({ events: [event] });
    const signature = createHmac("sha256", String(env.LINE_CHANNEL_SECRET)).update(body).digest("base64");
    const tasks: Promise<unknown>[] = [];
    const ctx = { waitUntil: (task: Promise<unknown>) => { tasks.push(task); }, passThroughOnException() {} } as unknown as ExecutionContext;
    const response = await productionWorker.fetch(
      new Request("https://synthetic-worker.example.test/webhook", { method: "POST", headers: { "x-line-signature": signature }, body }),
      env as never,
      ctx,
    );
    if (response.status !== 200) throw new Error(`SYNTHETIC_WEBHOOK_STATUS_${response.status}`);
    const settle = async () => {
      // Tasks can enqueue more tasks (the parked-job completion), so drain until stable.
      for (let seen = 0; seen < tasks.length; ) {
        seen = tasks.length;
        await Promise.all(tasks);
      }
    };
    if (extra.wait !== false) await settle();
    return { token: replyToken, tasks, settle };
  }

  async function health(): Promise<Record<string, unknown>> {
    const response = await productionWorker.fetch(new Request("https://synthetic-worker.example.test/health"), env as never, {
      waitUntil() {},
      passThroughOnException() {},
    } as unknown as ExecutionContext);
    return (await response.json()) as Record<string, unknown>;
  }

  const spies = {
    securityPut: vi.spyOn(securityKv, "put"),
    privatePut: vi.spyOn(privateKv, "put"),
    publicPut: vi.spyOn(publicKv, "put"),
    privateDelete: vi.spyOn(privateKv, "delete"),
    securityDelete: vi.spyOn(securityKv, "delete"),
  };
  const writes = () =>
    spies.securityPut.mock.calls.length + spies.privatePut.mock.calls.length + spies.publicPut.mock.calls.length +
    spies.privateDelete.mock.calls.length + spies.securityDelete.mock.calls.length;

  return {
    env, gate, replyTo: (id: string) => replies.find((reply) => id === reply.token)?.text, publicKv, privateKv, securityKv, prompts, replies, urls, model, deliver, health, tenantOf, spies, writes,
    restore: () => {
      network.mockRestore();
      timers.mockRestore();
    },
  };
}
