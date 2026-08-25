import { afterEach, describe, expect, it, vi } from "vitest";
import worker, { type Env } from "../src/worker";
import { deriveTenantId } from "../src/security";
import { MemoryKv, asKv } from "./fake-kv";

const CHANNEL_SECRET = "EXAMPLE_LINE_CHANNEL_SECRET_NOT_REAL";
const HASH_SECRET = "EXAMPLE_TENANT_HASH_SECRET_NOT_REAL";
const DATA_SECRET = "EXAMPLE_TENANT_DATA_KEY_NOT_REAL";

function base64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (const value of bytes) binary += String.fromCharCode(value);
  return btoa(binary);
}

async function signature(body: string, secret: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  return base64(
    await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(body)),
  );
}

function environment(kv: MemoryKv, overrides: Partial<Env> = {}): Env {
  return {
    PUBLIC_CACHE: asKv(kv),
    TENANT_PRIVATE_CACHE: asKv(new MemoryKv()),
    EPHEMERAL_SECURITY_CACHE: asKv(kv),
    LINE_CHANNEL_SECRET: CHANNEL_SECRET,
    LINE_CHANNEL_ACCESS_TOKEN: "EXAMPLE_LINE_ACCESS_TOKEN_NOT_REAL",
    TENANT_HASH_SECRET: HASH_SECRET,
    TENANT_DATA_ENCRYPTION_KEY: DATA_SECRET,
    MEMORY_FEATURE_AVAILABLE: "false",
    LINE_ACCESS_MODE: "disabled",
    GENERAL_QA_ENABLED: "true",
    CURRENT_PUBLIC_DATA_ENABLED: "false",
    MAX_REQUESTS_PER_MINUTE: "12",
    MAX_WEBHOOK_AGE_SECONDS: "600",
    ...overrides,
  };
}

async function admittedEnvironment(
  kv: MemoryKv,
  userId: string,
  overrides: Partial<Env> = {},
): Promise<Env> {
  const tenant = await deriveTenantId({ type: "user", userId }, HASH_SECRET);
  return environment(kv, {
    LINE_ACCESS_MODE: "allowlist",
    LINE_ALLOWED_TENANT_HASHES: tenant,
    ...overrides,
  });
}

function context() {
  const promises: Promise<unknown>[] = [];
  const value = {
    waitUntil(promise: Promise<unknown>) {
      promises.push(promise);
    },
    passThroughOnException() {},
  } as unknown as ExecutionContext;
  return { value, promises };
}

function messageBody(
  userId: string,
  text: string,
  webhookEventId = "SYNTHETIC-EVENT",
): string {
  return JSON.stringify({
    events: [
      {
        type: "message",
        webhookEventId,
        replyToken: "EXAMPLE_REPLY_TOKEN_NOT_REAL",
        timestamp: Date.now(),
        source: { type: "user", userId },
        message: { id: "synthetic-message-id", type: "text", text },
      },
    ],
  });
}

async function webhookRequest(body: string): Promise<Request> {
  return new Request("https://example.test/webhook", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-line-signature": await signature(body, CHANNEL_SECRET),
    },
    body,
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Worker webhook public-only boundary with split storage", () => {
  it("rejects an invalid LINE signature", async () => {
    const request = new Request("https://example.test/webhook", {
      method: "POST",
      headers: { "x-line-signature": "invalid" },
      body: JSON.stringify({ events: [] }),
    });
    const result = await worker.fetch(request, environment(new MemoryKv()), context().value);
    expect(result.status).toBe(401);
  });

  it("silently fails closed while disabled even when tenant secrets are absent", async () => {
    const fetchMock = vi.fn(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const kv = new MemoryKv();
    const body = messageBody("SYNTHETIC-UNKNOWN-USER", "幫助", "DISABLED-EVENT");
    const execution = context();
    const response = await worker.fetch(
      await webhookRequest(body),
      environment(kv, {
        LINE_ACCESS_MODE: undefined,
        TENANT_HASH_SECRET: undefined,
        TENANT_DATA_ENCRYPTION_KEY: undefined,
      }),
      execution.value,
    );
    expect(response.status).toBe(200);
    await Promise.all(execution.promises);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(kv.values.size).toBe(0);
  });

  it("admits only an HMAC-allowlisted friend and silently denies everyone else", async () => {
    const allowedUser = "SYNTHETIC-ALLOWED-FRIEND";
    const replies: Array<Record<string, unknown>> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
        if (init?.body) replies.push(JSON.parse(String(init.body)) as Record<string, unknown>);
        return new Response("{}", { status: 200 });
      }),
    );
    const kv = new MemoryKv();
    const env = await admittedEnvironment(kv, allowedUser);

    const allowedExecution = context();
    await worker.fetch(
      await webhookRequest(messageBody(allowedUser, "幫助", "ALLOWED-EVENT")),
      env,
      allowedExecution.value,
    );
    await Promise.all(allowedExecution.promises);
    expect(JSON.stringify(replies)).toContain("公開資料模式");
    expect(replies).toHaveLength(1);

    const deniedExecution = context();
    await worker.fetch(
      await webhookRequest(messageBody("SYNTHETIC-OTHER-FRIEND", "幫助", "DENIED-EVENT")),
      env,
      deniedExecution.value,
    );
    await Promise.all(deniedExecution.promises);
    expect(replies).toHaveLength(1);
    expect([...kv.values.keys()].join("\n")).not.toContain("DENIED-EVENT");
  });

  it("silently denies every group even when its HMAC tenant hash is allowlisted", async () => {
    const kv = new MemoryKv();
    const fetchMock = vi.fn(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const groupTenant = await deriveTenantId(
      {
        type: "group",
        userId: "RAW-USER-IDENTIFIER",
        groupId: "RAW-GROUP-IDENTIFIER",
      },
      HASH_SECRET,
    );
    const body = JSON.stringify({
      events: [
        {
          type: "message",
          webhookEventId: "RAW-EVENT-IDENTIFIER",
          replyToken: "EXAMPLE_REPLY_TOKEN_NOT_REAL",
          timestamp: Date.now(),
          source: {
            type: "group",
            userId: "RAW-USER-IDENTIFIER",
            groupId: "RAW-GROUP-IDENTIFIER",
          },
          message: { id: "synthetic-message-id", type: "text", text: "ALPHA 期權" },
        },
      ],
    });
    const execution = context();
    const response = await worker.fetch(
      await webhookRequest(body),
      environment(kv, {
        LINE_ACCESS_MODE: "allowlist",
        LINE_ALLOWED_TENANT_HASHES: groupTenant,
      }),
      execution.value,
    );
    expect(response.status).toBe(200);
    await Promise.all(execution.promises);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(kv.values.size).toBe(0);
  });

  it("treats the former public mode and invalid modes as disabled", async () => {
    const fetchMock = vi.fn(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    for (const mode of ["public", "unexpected"]) {
      const execution = context();
      await worker.fetch(
        await webhookRequest(messageBody("SYNTHETIC-USER", "幫助", `MODE-${mode}`)),
        environment(new MemoryKv(), { LINE_ACCESS_MODE: mode }),
        execution.value,
      );
      await Promise.all(execution.promises);
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("has no private synchronization endpoint", async () => {
    const result = await worker.fetch(
      new Request("https://example.test/internal/private-sync", {
        method: "POST",
        body: "{}",
      }),
      environment(new MemoryKv()),
      context().value,
    );
    expect(result.status).toBe(404);
  });

  it("health declares allowlist-only direct chat and no private bridge", async () => {
    const result = await worker.fetch(
      new Request("https://example.test/health"),
      environment(new MemoryKv(), { LINE_ACCESS_MODE: "public" }),
      context().value,
    );
    const payload = (await result.json()) as Record<string, unknown>;
    expect(payload.line_access_mode).toBe("disabled");
    expect(payload.direct_chat_only).toBe(true);
    expect(payload.options_scope).toBe("public_snapshot_only");
    expect(payload.ibkr_bridge).toBe(false);
    expect(payload.brokerage_connection).toBe(false);
    expect(payload.portfolio_access).toBe(false);
    expect(payload.private_sync).toBe(false);
  });

  it("deduplicates a completed authorized redelivery without a second reply", async () => {
    const kv = new MemoryKv();
    const fetchMock = vi.fn(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const userId = "SYNTHETIC-USER";
    const body = messageBody(userId, "幫助", "REDRIVE-EVENT");
    const headersRequest = await webhookRequest(body);
    const headers = Object.fromEntries(headersRequest.headers.entries());
    const env = await admittedEnvironment(kv, userId);

    const first = context();
    await worker.fetch(
      new Request("https://example.test/webhook", { method: "POST", headers, body }),
      env,
      first.value,
    );
    await Promise.all(first.promises);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    const second = context();
    await worker.fetch(
      new Request("https://example.test/webhook", { method: "POST", headers, body }),
      env,
      second.value,
    );
    await Promise.all(second.promises);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
