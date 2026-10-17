import { afterEach, describe, expect, it, vi } from "vitest";
import { pushMessages, pushText } from "../src/v21/line-push";
import { localDate, PUSH_DEADLINE_MS } from "../src/v21/line-push-policy";
import { memoryPushNamespace, SYNTHETIC_BOT_ID, syntheticPushPolicy, withPushPreflight } from "./line-push-fixture";
const TARGET = String.fromCharCode(85) + "0".repeat(32);
const MESSAGE = [{ type: "text" as const, text: "Synthetic public report" }];
function setup(faults = {}) {
  const h = memoryPushNamespace(faults);
  const env = { LINE_CHANNEL_ACCESS_TOKEN: "SYNTHETIC_ACCESS_NOT_REAL", LINE_FREE_PUSH_POLICY: syntheticPushPolicy(), V213_BROADCAST_DEDUPE: h.namespace };
  const post = vi.fn(async () => new Response("{}"));
  const network = withPushPreflight(post); vi.stubGlobal("fetch", network);
  return { h, env, post, network };
}
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers(); });

describe("shared LINE free-only push admission (no real transport)", () => {
  it.each([
    {}, { free_plan_verified: false }, { free_plan_verified: "true" }, { paid_expansion_disabled: false },
    { paid_expansion_disabled: "true" }, { free_message_limit: "200" }, { free_message_limit: true },
    { free_message_limit: 0 }, { free_message_limit: 1.5 }, { billing_month: "2000-01" },
    { billing_timezone: "Not/AZone" }, { reviewed_at: "2099-01-01T00:00:00.000Z" }, { extra: true },
  ])("does not fabricate a free entitlement from invalid review %j", async override => {
    const { env, network } = setup(); env.LINE_FREE_PUSH_POLICY = Object.keys(override).length ? syntheticPushPolicy(override) : "{}";
    Object.defineProperty(env, "LINE_CHANNEL_ACCESS_TOKEN", { get() { throw new Error("CREDENTIAL_MUST_NOT_BE_READ"); } });
    await expect(pushMessages(env, TARGET, MESSAGE)).rejects.toThrow("LINE_FREE_PLAN_REVIEW");
    expect(network).not.toHaveBeenCalled();
  });

  it.each(["literal", "escaped"])("rejects %s duplicate entitlement keys before network", async kind => {
    const { env, network } = setup();
    const key = kind === "literal" ? '"free_plan_verified"' : '"\\u0066ree_plan_verified"';
    env.LINE_FREE_PUSH_POLICY = env.LINE_FREE_PUSH_POLICY.replace("{", `{${key}:false,`);
    await expect(pushMessages(env, TARGET, MESSAGE)).rejects.toThrow("LINE_FREE_PLAN_REVIEW_INVALID_OR_EXPIRED"); expect(network).not.toHaveBeenCalled();
  });

  it("rejects contradictory escaped provider quota keys without reserving or sending", async () => {
    const { env, h } = setup();
    const network = vi.fn(async (url: string) => url.endsWith("/info") ? Response.json({ userId: SYNTHETIC_BOT_ID }) : new Response('{"type":"limited","value":5000,"\\u0076alue":200}', { headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", network);
    await expect(pushMessages(env, TARGET, MESSAGE)).rejects.toThrow("LINE_PUSH_PREFLIGHT_INVALID");
    expect(network).toHaveBeenCalledTimes(2); expect(h.stores.size).toBe(0);
  });

  it.each([{ PAID_FALLBACK_ENABLED: "true" }, { FREE_ONLY_MODE: "false" }, { FREE_ONLY_MODE: "1" }])("has no paid/mode opt-out %j", async flags => {
    const { env, network } = setup(); Object.assign(env, flags);
    await expect(pushMessages(env, TARGET, MESSAGE)).rejects.toThrow("LINE_FREE_ONLY_REQUIRED"); expect(network).not.toHaveBeenCalled();
  });

  it("requires the existing shared budget namespace before credential/network use", async () => {
    const { env, network } = setup(); delete (env as any).V213_BROADCAST_DEDUPE;
    await expect(pushMessages(env, TARGET, MESSAGE)).rejects.toThrow("LINE_PUSH_BUDGET_REQUIRED"); expect(network).not.toHaveBeenCalled();
  });

  it.each([
    [{ type: "none" }, { totalUsage: 0 }], [{ type: "limited", value: 5000 }, { totalUsage: 0 }],
    [{ type: "limited", value: "200" }, { totalUsage: 0 }], [{ type: "limited", value: 200 }, { totalUsage: "0" }],
    [{ type: "limited", value: 200 }, { totalUsage: false }], [{ type: "limited", value: 200 }, { totalUsage: -1 }],
    [{ type: "limited", value: 200 }, { totalUsage: 0.5 }], [{ type: "limited", value: 200 }, { totalUsage: 200 }],
    [{ type: "limited", value: 200 }, { totalUsage: 0, extra: true }],
  ])("refuses unknown/expanded/exhausted provider quota %j", async (quota, usage) => {
    const { env, h, post } = setup();
    vi.stubGlobal("fetch", vi.fn(async (url: string) => Response.json(url.endsWith("/info") ? { userId: SYNTHETIC_BOT_ID } : url.endsWith("/consumption") ? usage : quota)));
    await expect(pushMessages(env, TARGET, MESSAGE)).rejects.toThrow("LINE_FREE_QUOTA"); expect(post).not.toHaveBeenCalled(); expect(h.stores.size).toBe(0);
  });

  it.each(["identity", "redirect", "oversized", "invalid_json", "bad_utf8", "unavailable"])("fails closed for %s preflight without a push", async fault => {
    const { env, h } = setup();
    const network = vi.fn(async () => {
      if (fault === "redirect") return new Response(null, { status: 302, headers: { location: "https://not-line.invalid/" } });
      if (fault === "oversized") return new Response(" ".repeat(4097), { headers: { "content-type": "application/json" } });
      if (fault === "invalid_json") return new Response("{", { headers: { "content-type": "application/json" } });
      if (fault === "bad_utf8") return new Response(new Uint8Array([255]), { headers: { "content-type": "application/json" } });
      if (fault === "unavailable") return Response.json({ error: "SYNTHETIC_PRIVATE_ERROR" }, { status: 503 });
      return Response.json({ userId: TARGET });
    });
    vi.stubGlobal("fetch", network);
    await expect(pushMessages(env, TARGET, MESSAGE)).rejects.toThrow(/LINE_PUSH_(?:CHANNEL|PREFLIGHT)/);
    expect(network).toHaveBeenCalledTimes(1); expect(h.stores.size).toBe(0);
    expect(network.mock.calls[0]).toBeDefined();
  });

  it("counts one recipient, not four message objects, and never stores payloads or identifiers", async () => {
    const { env, h, post, network } = setup();
    const messages = Array.from({ length: 4 }, (_, i) => ({ type: "text" as const, text: `SYNTHETIC_PAYLOAD_${i}` }));
    await pushMessages(env, TARGET, messages);
    expect(post).toHaveBeenCalledTimes(1); expect(network).toHaveBeenCalledTimes(4);
    const values = [...h.stores.values()][0]!; const ledger = values.get("push:ledger") as any;
    expect(ledger).toMatchObject({ reserved_month: 1, reserved_day: 1 });
    const entries = JSON.stringify([...values]);
    for (const forbidden of [TARGET, SYNTHETIC_BOT_ID, env.LINE_CHANNEL_ACCESS_TOKEN, "SYNTHETIC_PAYLOAD"]) expect(entries).not.toContain(forbidden);
    const init = network.mock.calls[3]![1]!;
    const retryKey = new Headers(init.headers).get("X-Line-Retry-Key");
    expect(retryKey).toMatch(/^[a-f0-9-]{36}$/);
    expect(entries).toContain(retryKey);
    for (const [, request] of network.mock.calls) { expect(request!.redirect).toBe("manual"); expect(request!.signal).toBeInstanceOf(AbortSignal); }
  });

  it("captures exact message bytes before asynchronous preflight", async () => {
    const { env } = setup(); const messages = [{ type: "text" as const, text: "original public message" }];
    const post = vi.fn(async (_url, init) => { expect(JSON.parse(init.body).messages[0].text).toBe("original public message"); return new Response("{}"); });
    const allowed = withPushPreflight(post);
    vi.stubGlobal("fetch", vi.fn(async (url, init) => { messages[0]!.text = "mutated after admission"; return allowed(url, init); }));
    await pushMessages(env, TARGET, messages); expect(post).toHaveBeenCalledTimes(1);
  });

  it("refuses a budget acknowledgement arriving on another Taipei day", async () => {
    vi.useFakeTimers(); vi.setSystemTime(new Date("2026-09-10T15:59:59Z"));
    const { env, h, post } = setup();
    const base = h.namespace;
    env.V213_BROADCAST_DEDUPE = { idFromName: (name: string) => base.idFromName(name), get: (id: DurableObjectId) => ({
      fetch: async (input: RequestInfo | URL, init?: RequestInit) => {
        const result = await base.get(id).fetch(input, init); vi.setSystemTime(new Date("2026-09-10T16:00:01Z")); return result;
      },
    }) } as unknown as DurableObjectNamespace;
    await expect(pushMessages(env, TARGET, MESSAGE)).rejects.toThrow("LINE_PUSH_DAY_CHANGED"); expect(post).not.toHaveBeenCalled();
  });

  it("blocks manual retries even after the provider's 24-hour key window", async () => {
    vi.useFakeTimers(); vi.setSystemTime(new Date("2026-09-10T04:00:00Z"));
    const { env, post } = setup(); await pushText(env, TARGET, "Synthetic public report");
    vi.setSystemTime(new Date("2026-09-13T04:00:00Z"));
    await expect(pushMessages(env, TARGET, MESSAGE)).rejects.toThrow("LINE_PUSH_ALREADY_ATTEMPTED"); expect(post).toHaveBeenCalledTimes(1);
  });

  it("prevents changing a scheduled slot's body and shares the two-per-day budget with manual sends", async () => {
    const { env, post } = setup(); const slot = { date: localDate(Date.now()), slot: "morning" as const };
    await pushMessages(env, TARGET, MESSAGE, slot);
    await expect(pushText(env, TARGET, "Changed body", slot)).rejects.toThrow("LINE_PUSH_PAYLOAD_CONFLICT");
    await pushText(env, TARGET, "One manual verification");
    await expect(pushMessages(env, TARGET, MESSAGE, { ...slot, slot: "evening" })).rejects.toThrow("LINE_PUSH_DAILY_LIMIT"); expect(post).toHaveBeenCalledTimes(2);
  });

  it("atomically reserves one budget across concurrent distinct send callers", async () => {
    const { env, post } = setup();
    const results = await Promise.allSettled(["a", "b", "c"].map(text => pushText(env, TARGET, text)));
    expect(results.filter(x => x.status === "fulfilled")).toHaveLength(2);
    expect(results.filter(x => x.status === "rejected")).toHaveLength(1); expect(post).toHaveBeenCalledTimes(2);
  });

  it("never refunds the API high-water mark when a later usage response decreases", async () => {
    const { env, post } = setup(); vi.stubGlobal("fetch", withPushPreflight(post, 199));
    await pushMessages(env, TARGET, MESSAGE);
    vi.stubGlobal("fetch", withPushPreflight(post, 0));
    await expect(pushText(env, TARGET, "different")).rejects.toThrow("LINE_FREE_QUOTA_EXHAUSTED"); expect(post).toHaveBeenCalledTimes(1);
  });

  it("requires a fresh monthly review, retains old attempts and does not reset the Taipei day across a billing boundary", async () => {
    vi.useFakeTimers(); vi.setSystemTime(new Date("2026-09-30T23:30:00Z"));
    const { env, post } = setup();
    env.LINE_FREE_PUSH_POLICY = syntheticPushPolicy({ billing_month: "2026-09", billing_timezone: "UTC" });
    await pushText(env, TARGET, "before boundary");
    vi.setSystemTime(new Date("2026-10-01T00:30:00Z"));
    await expect(pushText(env, TARGET, "after boundary")).rejects.toThrow("LINE_FREE_PLAN_REVIEW_INVALID_OR_EXPIRED");
    env.LINE_FREE_PUSH_POLICY = syntheticPushPolicy({ billing_month: "2026-10", billing_timezone: "UTC" });
    await expect(pushText(env, TARGET, "before boundary")).rejects.toThrow("LINE_PUSH_ALREADY_ATTEMPTED");
    await pushText(env, TARGET, "after boundary");
    await expect(pushText(env, TARGET, "third")).rejects.toThrow("LINE_PUSH_DAILY_LIMIT"); expect(post).toHaveBeenCalledTimes(2);
  });

  it.each(["failBudgetCommit", "loseBudgetAck"])("does not send after %s; atomic failure and committed uncertainty stay distinct", async fault => {
    const { env, h, post } = setup({ [fault]: true });
    await expect(pushMessages(env, TARGET, MESSAGE)).rejects.toThrow("LINE_PUSH_BUDGET_UNAVAILABLE"); expect(post).not.toHaveBeenCalled();
    const store = [...h.stores.values()][0]!;
    if (fault === "failBudgetCommit") { expect(store.size).toBe(0); await pushMessages(env, TARGET, MESSAGE); expect(post).toHaveBeenCalledTimes(1); }
    else { expect(store.has("push:ledger")).toBe(true); await expect(pushMessages(env, TARGET, MESSAGE)).rejects.toThrow("LINE_PUSH_ALREADY_ATTEMPTED"); expect(post).not.toHaveBeenCalled(); }
  });

  it.each(["missing", "malformed", "calendar", "timezone"])("does not reconstruct/reset %s ledger state", async mutation => {
    const { env, h, post } = setup(); await pushMessages(env, TARGET, MESSAGE); const store = [...h.stores.values()][0]!;
    if (mutation === "missing") store.delete("push:ledger");
    else if (mutation === "malformed") store.set("push:ledger", { ...(store.get("push:ledger") as any), reserved_month: false });
    else if (mutation === "calendar") store.set("push:ledger", { ...(store.get("push:ledger") as any), day: "2000-02-31" });
    else env.LINE_FREE_PUSH_POLICY = syntheticPushPolicy({ billing_timezone: "Asia/Tokyo" });
    await expect(pushText(env, TARGET, "different")).rejects.toThrow("LINE_PUSH_LEDGER"); expect(post).toHaveBeenCalledTimes(1);
  });

  it.each(["network", "http", "redirect", "conflict", "quota_rejected"])("retains reservation on %s failure, without exposing provider error content", async fault => {
    const { env, h } = setup();
    const post = vi.fn(async () => {
      if (fault === "network") throw new Error("SYNTHETIC_PRIVATE_TRANSPORT");
      return new Response("SYNTHETIC_PRIVATE_BODY", { status: ({ http: 503, redirect: 307, conflict: 409, quota_rejected: 429 } as Record<string, number>)[fault], headers: { "x-line-request-id": "SYNTHETIC_PRIVATE_HEADER", location: "https://not-line.invalid/" } });
    });
    vi.stubGlobal("fetch", withPushPreflight(post));
    const expected = fault === "network" ? "LINE_PUSH_TRANSPORT_UNCERTAIN" : `V21_LINE_PUSH_${({ http: 503, redirect: 307, conflict: 409, quota_rejected: 429 } as Record<string, number>)[fault]}`;
    await expect(pushMessages(env, TARGET, MESSAGE)).rejects.toMatchObject({ message: expected });
    await expect(pushMessages(env, TARGET, MESSAGE)).rejects.toThrow("LINE_PUSH_ALREADY_ATTEMPTED");
    expect(post).toHaveBeenCalledTimes(1); expect([...h.stores.values()][0]!.has("push:ledger")).toBe(true);
  });

  it("bounds a stalled preflight and does not issue a late POST after it resolves", async () => {
    vi.useFakeTimers(); const { env, h } = setup(); let resolve!: (value: Response) => void;
    const network = vi.fn(() => new Promise<Response>(yes => { resolve = yes; })); vi.stubGlobal("fetch", network);
    const stopped = expect(pushMessages(env, TARGET, MESSAGE)).rejects.toThrow("LINE_PUSH_DEADLINE_EXCEEDED");
    await vi.advanceTimersByTimeAsync(PUSH_DEADLINE_MS + 1); await stopped;
    resolve(Response.json({ userId: SYNTHETIC_BOT_ID })); await vi.advanceTimersByTimeAsync(0);
    expect(network).toHaveBeenCalledTimes(1); expect(h.stores.size).toBe(0);
  });

  it("bounds an ambiguous POST without retrying or refunding its reservation", async () => {
    vi.useFakeTimers(); const { env, h } = setup();
    const post = vi.fn(async () => new Promise<Response>(() => {})); const network = withPushPreflight(post); vi.stubGlobal("fetch", network);
    const stopped = expect(pushMessages(env, TARGET, MESSAGE)).rejects.toThrow("LINE_PUSH_DEADLINE_EXCEEDED");
    await vi.waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    await vi.advanceTimersByTimeAsync(PUSH_DEADLINE_MS + 1); await stopped;
    expect(network.mock.calls[3]![1]!.signal!.aborted).toBe(true);
    expect([...h.stores.values()][0]!.has("push:ledger")).toBe(true);
    await expect(pushMessages(env, TARGET, MESSAGE)).rejects.toThrow("LINE_PUSH_ALREADY_ATTEMPTED"); expect(post).toHaveBeenCalledTimes(1);
  });
});
