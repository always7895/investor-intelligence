import { afterEach, expect, it, vi } from "vitest";
import { processAuthorizedLineEvent, V211_GENERAL_QA, type V211Env } from "../src/v211/worker";
import { getJob } from "../src/storage";
import { asKv, MemoryKv } from "./fake-kv";

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });
it("seven-second path returns a reference, then saves completed tenant-isolated result (all LINE calls mocked)", async () => {
  vi.useFakeTimers();
  let finish!: (value: string) => void;
  const inference = new Promise<string>((resolve) => { finish = resolve; });
  const handler = vi.fn(() => inference);
  const replies: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
    expect(String(url)).toBe("https://api.line.me/v2/bot/message/reply");
    replies.push(JSON.parse(String(init.body)).messages[0].text);
    return new Response("{}");
  }));
  const env = { PUBLIC_CACHE: asKv(new MemoryKv()), TENANT_PRIVATE_CACHE: asKv(new MemoryKv()), EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()),
    TENANT_DATA_ENCRYPTION_KEY: "SYNTHETIC_TENANT_ENCRYPTION_KEY_NOT_REAL", LINE_CHANNEL_ACCESS_TOKEN: "SYNTHETIC_LINE_TOKEN_NOT_REAL", LINE_CHANNEL_SECRET: "SYNTHETIC_LINE_SECRET_NOT_REAL",
    GENERAL_QA_ENABLED: "true", MEMORY_FEATURE_AVAILABLE: "false", CURRENT_PUBLIC_DATA_ENABLED: "false", [V211_GENERAL_QA]: handler } as V211Env;
  const work: Promise<unknown>[] = [];
  const ctx = { waitUntil(p: Promise<unknown>) { work.push(p); }, passThroughOnException() {} } as ExecutionContext;
  const processing = processAuthorizedLineEvent(env, ctx, { type: "message", replyToken: "SYNTHETIC_REPLY", source: { type: "user", userId: "SYNTHETIC_USER" },
    message: { type: "text", text: "什麼是自由現金流？" }, timestamp: Date.now() }, "synthetic-tenant");
  await vi.waitFor(() => expect(handler).toHaveBeenCalledOnce());
  await vi.advanceTimersByTimeAsync(6000);
  expect(replies).toHaveLength(0);
  await vi.advanceTimersByTimeAsync(1100);
  await processing;
  expect(replies).toHaveLength(1);
  const reference = replies[0]!.match(/參考編號 ([A-Z0-9]+)/)?.[1];
  expect(reference).toBeTruthy();
  expect((await getJob(env, "synthetic-tenant", reference!))?.status).toBe("pending");
  expect(await getJob(env, "another-tenant", reference!)).toBeNull();
  finish("自由現金流為營運現金流扣除資本支出；淨利則採會計應計基礎。");
  await Promise.all(work);
  expect((await getJob(env, "synthetic-tenant", reference!))?.status).toBe("complete");
  expect(replies).toHaveLength(1); // Completion does NOT push a LINE message.
});
