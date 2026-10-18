/** Synthetic LINE entitlement/API and transactional DO fixtures, never a live review. */
import { createHash } from "node:crypto";
import { vi } from "vitest";
import { V213BroadcastDedupe } from "../src/v213/broadcast-dedupe";
import { localDate } from "../src/v21/line-push-policy";
export const SYNTHETIC_BOT_ID = String.fromCharCode(85) + "f".repeat(32);
export const SYNTHETIC_CHANNEL_HASH = createHash("sha256").update(SYNTHETIC_BOT_ID).digest("hex");
export function syntheticPushPolicy(overrides: Record<string, unknown> = {}): string {
  return JSON.stringify({ schema_version: 1, channel_sha256: SYNTHETIC_CHANNEL_HASH, billing_month: localDate(Date.now()).slice(0, 7),
    billing_timezone: "Asia/Taipei", free_message_limit: 200, reviewed_at: new Date().toISOString(), free_plan_verified: true, paid_expansion_disabled: true, ...overrides });
}
export function withPushPreflight(transport: (...args: any[]) => Promise<Response>, usage = 0, quota = 200) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === "https://api.line.me/v2/bot/info") return Response.json({ userId: SYNTHETIC_BOT_ID });
    if (url === "https://api.line.me/v2/bot/message/quota") return Response.json({ type: "limited", value: quota });
    if (url === "https://api.line.me/v2/bot/message/quota/consumption") return Response.json({ totalUsage: usage });
    return transport(input, init);
  });
}

export function memoryPushNamespace(faults: { failComplete?: boolean; failBudgetCommit?: boolean; loseBudgetAck?: boolean } = {}) {
  const stores = new Map<string, Map<string, unknown>>(); const stubs = new Map<string, unknown>();
  const namespace = { idFromName: (name: string) => name, get: (id: string) => {
    if (stubs.has(id)) return stubs.get(id);
    const values = new Map<string, unknown>(); stores.set(id, values);
    const api = (map: Map<string, unknown>) => ({
      get: async (key: string) => structuredClone(map.get(key)),
      put: async (key: string | Record<string, unknown>, value?: unknown) => {
        if (typeof key === "string") {
          if (faults.failComplete && (value as any)?.status === "sent") { faults.failComplete = false; throw new Error("SYNTHETIC_COMPLETE_FAILED"); }
          map.set(key, structuredClone(value));
        } else for (const [name, item] of Object.entries(key)) map.set(name, structuredClone(item));
      },
      delete: async (key: string) => map.delete(key),
      list: async (options: { prefix: string; limit: number }) => new Map([...map].filter(([key]) => key.startsWith(options.prefix)).slice(0, options.limit)),
    });
    const state = { storage: { ...api(values), transaction: async (callback: (txn: unknown) => Promise<unknown>) => {
      const draft = structuredClone(values); const result = await callback(api(draft));
      if (faults.failBudgetCommit) { faults.failBudgetCommit = false; throw new Error("SYNTHETIC_BUDGET_COMMIT_FAILED"); }
      values.clear(); for (const [key, value] of draft) values.set(key, value);
      return result;
    } } } as unknown as DurableObjectState;
    const instance = new V213BroadcastDedupe(state); let chain = Promise.resolve();
    const stub = { fetch: (input: RequestInfo | URL, init?: RequestInit) => {
      const request = input instanceof Request ? input : new Request(input, init);
      const result = chain.then(async () => {
        const action = (await request.clone().json() as any).action;
        const response = await instance.fetch(request);
        if (faults.loseBudgetAck && action === "reserve_push" && response.ok) { faults.loseBudgetAck = false; throw new Error("SYNTHETIC_BUDGET_ACK_LOST"); }
        return response;
      });
      chain = result.then(() => undefined, () => undefined); return result;
    } };
    stubs.set(id, stub); return stub;
  } } as unknown as DurableObjectNamespace;
  return { namespace, stores, faults };
}
