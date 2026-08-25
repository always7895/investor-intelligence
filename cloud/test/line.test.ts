import { afterEach, describe, expect, it, vi } from "vitest";
import {
  claimEvent,
  completeEvent,
  eventIsFresh,
  rateLimit,
  releaseEvent,
  replyText,
  type LineEnv,
} from "../src/line";
import { MemoryKv, asKv } from "./fake-kv";

function env(kv: MemoryKv, overrides: Partial<LineEnv> = {}): LineEnv {
  return {
    EPHEMERAL_SECURITY_CACHE: asKv(kv),
    LINE_CHANNEL_SECRET: "SYNTHETIC_CHANNEL_SECRET",
    LINE_CHANNEL_ACCESS_TOKEN: "SYNTHETIC_CHANNEL_ACCESS_TOKEN",
    ...overrides,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("LINE reply-only reliability in EPHEMERAL_SECURITY_CACHE", () => {
  it("releases a failed event so LINE redelivery can retry it", async () => {
    const kv = new MemoryKv();
    const runtime = env(kv);

    await expect(claimEvent(runtime, "SYNTHETIC_EVENT_1")).resolves.toBe(true);
    await expect(claimEvent(runtime, "SYNTHETIC_EVENT_1")).resolves.toBe(false);

    await releaseEvent(runtime, "SYNTHETIC_EVENT_1");
    await expect(claimEvent(runtime, "SYNTHETIC_EVENT_1")).resolves.toBe(true);

    await completeEvent(runtime, "SYNTHETIC_EVENT_1");
    await releaseEvent(runtime, "SYNTHETIC_EVENT_1");
    await expect(claimEvent(runtime, "SYNTHETIC_EVENT_1")).resolves.toBe(false);

    const storedKeys = [...kv.values.keys()].join("\n");
    expect(storedKeys).not.toContain("SYNTHETIC_EVENT_1");
  });

  it("applies freshness limits and a bounded redelivery grace period", () => {
    const now = Date.parse("2026-08-24T10:00:00Z");
    vi.spyOn(Date, "now").mockReturnValue(now);
    const runtime = env(new MemoryKv(), { MAX_WEBHOOK_AGE_SECONDS: "600" });

    expect(eventIsFresh({ type: "message", timestamp: now - 599_000 }, runtime)).toBe(true);
    expect(eventIsFresh({ type: "message", timestamp: now - 601_000 }, runtime)).toBe(false);
    expect(
      eventIsFresh(
        {
          type: "message",
          timestamp: now - 60 * 60 * 1000,
          deliveryContext: { isRedelivery: true },
        },
        runtime,
      ),
    ).toBe(true);
    expect(
      eventIsFresh(
        {
          type: "message",
          timestamp: now - 86_401_000,
          deliveryContext: { isRedelivery: true },
        },
        runtime,
      ),
    ).toBe(false);
  });

  it("rate-limits independently by pseudonymous tenant and intent", async () => {
    const kv = new MemoryKv();
    const runtime = env(kv, { MAX_REQUESTS_PER_MINUTE: "2" });
    vi.spyOn(Date, "now").mockReturnValue(Date.parse("2026-08-24T10:00:00Z"));

    await expect(rateLimit(runtime, "TENANT_A_HASH", "options")).resolves.toBe(true);
    await expect(rateLimit(runtime, "TENANT_A_HASH", "options")).resolves.toBe(true);
    await expect(rateLimit(runtime, "TENANT_A_HASH", "options")).resolves.toBe(false);
    await expect(rateLimit(runtime, "TENANT_A_HASH", "ranking")).resolves.toBe(true);
    await expect(rateLimit(runtime, "TENANT_B_HASH", "options")).resolves.toBe(true);
  });

  it("uses only the LINE reply endpoint and never a push endpoint", async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        calls.push({ url: String(input), init });
        return new Response("{}", {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }),
    );

    await replyText(env(new MemoryKv()), "SYNTHETIC_REPLY_TOKEN", "public answer");
    expect(calls).toHaveLength(1);
    expect(calls[0]?.url).toBe("https://api.line.me/v2/bot/message/reply");
    expect(calls[0]?.url).not.toContain("/push");
    expect(calls[0]?.init?.method).toBe("POST");
    expect(calls[0]?.init?.headers).toMatchObject({
      authorization: "Bearer SYNTHETIC_CHANNEL_ACCESS_TOKEN",
    });
    const payload = JSON.parse(String(calls[0]?.init?.body)) as {
      replyToken?: string;
      messages?: Array<{ type?: string; text?: string }>;
    };
    expect(payload.replyToken).toBe("SYNTHETIC_REPLY_TOKEN");
    expect(payload.messages).toEqual([{ type: "text", text: "public answer" }]);
  });

  it("bounds long replies to LINE message limits", async () => {
    let body = "";
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
        body = String(init?.body ?? "");
        return new Response("{}", { status: 200 });
      }),
    );

    await replyText(
      env(new MemoryKv()),
      "SYNTHETIC_REPLY_TOKEN",
      Array.from({ length: 120 }, (_, index) => `section ${index} ${"x".repeat(120)}`).join("\n\n"),
    );
    const payload = JSON.parse(body) as {
      messages: Array<{ type: string; text: string }>;
    };
    expect(payload.messages.length).toBeGreaterThan(0);
    expect(payload.messages.length).toBeLessThanOrEqual(5);
    expect(payload.messages.every((message) => message.type === "text")).toBe(true);
    expect(payload.messages.every((message) => message.text.length <= 4900)).toBe(true);
  });

  it("returns only a bounded request identifier when LINE rejects a reply", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response("PRIVATE_PROVIDER_BODY_MUST_NOT_BE_USED", {
          status: 429,
          headers: { "x-line-request-id": "SYNTHETIC_REQUEST_ID" },
        }),
      ),
    );
    await expect(
      replyText(env(new MemoryKv()), "SYNTHETIC_REPLY_TOKEN", "public answer"),
    ).rejects.toThrow("LINE_REPLY_429;request_id=SYNTHETIC_REQUEST_ID");
  });
});
