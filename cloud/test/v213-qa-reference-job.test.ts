import { afterEach, expect, it, vi } from "vitest";
import { processAuthorizedLineEvent, V211_GENERAL_QA, type V211Env } from "../src/v211/worker";
import { getJob } from "../src/storage";
import { asKv, MemoryKv } from "./fake-kv";
import { compactGeneralAnswer } from "../src/v213/compact-qa";
import { v213RuntimeCompatibleFetch } from "../src/v213/production-worker";
import piProfile from "../../config/v213-pi-inference-v1.json";

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

it("authorized LINE reference job traverses the real public Pi adapter and keeps completion tenant-isolated", async () => {
  vi.useFakeTimers();
  let finish!: (value: Response) => void;
  const inference = new Promise<Response>(resolve => { finish = resolve; });
  const replies: string[] = [];
  const packets: any[] = [];
  const native = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === "https://gateway.example.test/v1/chat/completions") {
      packets.push(JSON.parse(String(init?.body)));
      expect(init?.signal).toBeDefined(); // Preserve certified request cancellation, never extend it silently.
      return inference;
    }
    expect(url).toBe("https://api.line.me/v2/bot/message/reply");
    replies.push(JSON.parse(String(init?.body)).messages[0].text);
    return new Response("{}");
  });
  vi.stubGlobal("fetch", (input: RequestInfo | URL, init?: RequestInit) => v213RuntimeCompatibleFetch(native as typeof fetch, input, init));
  const env = {PUBLIC_CACHE: asKv(new MemoryKv()), TENANT_PRIVATE_CACHE: asKv(new MemoryKv()), EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()),
    TENANT_DATA_ENCRYPTION_KEY: "SYNTHETIC_TENANT_ENCRYPTION_KEY_NOT_REAL", LINE_CHANNEL_ACCESS_TOKEN: "SYNTHETIC_LINE_TOKEN_NOT_REAL", LINE_CHANNEL_SECRET: "SYNTHETIC_LINE_SECRET_NOT_REAL",
    GENERAL_QA_ENABLED: "true", MEMORY_FEATURE_AVAILABLE: "false", CURRENT_PUBLIC_DATA_ENABLED: "false",
    LOCAL_LLM_BASE_URL: "https://gateway.example.test", LOCAL_LLM_ALLOWED_HOSTS: "gateway.example.test", LOCAL_LLM_MODEL: piProfile.model_id,
    LOCAL_LLM_SHARED_SECRET: "SYNTHETIC_GATEWAY_AUTH_NOT_REAL", [V211_GENERAL_QA]: compactGeneralAnswer} as V211Env;
  const work: Promise<unknown>[] = [];
  const ctx = {waitUntil(p: Promise<unknown>) {work.push(p);}, passThroughOnException() {}} as ExecutionContext;
  const processing = processAuthorizedLineEvent(env, ctx, {type: "message", replyToken: "SYNTHETIC_REPLY",
    source: {type: "user", userId: "SYNTHETIC_USER"}, message: {type: "text", text: "Serenity 的瓶頸與價值捕捉有何差異？"}, timestamp: Date.now()}, "pi-synthetic-tenant");
  await vi.waitFor(() => expect(packets, JSON.stringify(replies)).toHaveLength(1));
  expect(packets[0].ii_context_mode).toBe("pi_public_v1");
  expect(packets[0].public_context.kind).toBe("methodology");
  expect(packets[0].public_context.freshness).toBe("UNAVAILABLE");
  await vi.advanceTimersByTimeAsync(7100);
  await processing;
  const reference = replies[0]?.match(/參考編號 ([A-Z0-9]+)/)?.[1];
  expect(reference).toBeTruthy();
  expect((await getJob(env, "pi-synthetic-tenant", reference!))?.status).toBe("pending");
  finish(new Response(JSON.stringify({model: piProfile.model_id,
    choices: [{finish_reason: "stop", message: {role: "assistant", content: "瓶頸不等於公司能捕捉利潤，仍需独立證據。"}}],
    ii_exact_model_pin: {selected_model: piProfile.model_id, canonical_model: piProfile.model_id, request_model_substitution_allowed: false},
    ii_pi: {provider: "llama.cpp", thinking_level: "xhigh", xhigh_payload_validated: true, tools_executed: 0, production_ready: false}})));
  await Promise.all(work);
  expect((await getJob(env, "pi-synthetic-tenant", reference!))?.status).toBe("complete");
  expect(await getJob(env, "other-tenant", reference!)).toBeNull();
  expect(replies).toHaveLength(1); // No second send/push or actual LINE transport.
});
