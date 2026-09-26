import { describe, expect, it, vi } from "vitest";
import { V213BroadcastDedupe, runV213BroadcastOnce } from "../src/v213/broadcast-dedupe";

function harness(initial?: unknown, fault = "") {
  let stored = initial;
  let writes = 0;
  const instance = new V213BroadcastDedupe({ storage: {
    get: async () => stored,
    put: async (_key: string, value: unknown) => { stored = value; writes++; },
    delete: async () => { throw new Error("STATE_MUST_NOT_BE_DELETED"); },
  } } as unknown as DurableObjectState);
  const rpc = async (body: Record<string, unknown>) => instance.fetch(new Request("https://dedupe.internal/action", {
    method: "POST", body: JSON.stringify(body), headers: { "content-type": "application/json" },
  }));
  const namespace = { idFromName: (name: string) => name, get: () => ({ fetch: async (_url: string, init: RequestInit) => {
    const body = JSON.parse(String(init.body));
    if (body.action === "claim" && fault === "malformed_claim") return Response.json({ claimed: false, status: ["duplicate"] });
    if (body.action === "claim" && fault === "unbound_claim") return Response.json({ claimed: true, status: "pending", token: "wrong-token" });
    if (body.action === "uncertain" && fault === "uncertain_write") throw new Error("SYNTHETIC_UNCERTAINTY_WRITE_FAILED");
    if (body.action === "complete" && fault === "malformed_complete") return Response.json({ completed: "true", status: "sent" });
    const result = await rpc(body);
    if (body.action === "complete" && fault === "complete_ack_lost") throw new Error("SYNTHETIC_COMPLETE_ACK_LOST");
    return result;
  } }) } as unknown as DurableObjectNamespace;
  return { rpc, namespace, state: () => stored as any, writes: () => writes };
}

function prior(status: "pending" | "sent" = "pending") {
  return { schema_version: 1, status, token: "old-token", updated_at: new Date(Date.now() - 700_000).toISOString(), expires_at: Date.now() - 1 };
}

describe("LINE delivery uncertainty retention (synthetic DO only)", () => {
  it("does not interpret an expired lease as evidence that no push occurred", async () => {
    const h = harness(prior());
    expect(await (await h.rpc({ action: "claim", token: "new-token" })).json()).toMatchObject({ claimed: false, status: "delivery_unknown" });
    expect(h.state()).toMatchObject({ status: "pending", token: "old-token", delivery_unknown: true });
    expect(h.state().expires_at).toBeGreaterThan(Date.now()); // old readers remain fenced
  });

  it("does not automatically replay a completed snapshot after its old retention timer", async () => {
    const h = harness(prior("sent"));
    expect(await (await h.rpc({ action: "claim", token: "new-token" })).json()).toMatchObject({ claimed: false, status: "duplicate" });
    expect(h.writes()).toBe(0);
  });

  it.each([null, {}, { ...prior(), status: "unexpected" }, { ...prior(), expires_at: "0" }, { ...prior(), delivery_unknown: "true" }])("retains and refuses invalid stored state %j", async state => {
    const h = harness(state);
    expect((await h.rpc({ action: "claim", token: "new-token" })).status).toBe(409);
    expect(h.state()).toBe(state);
    expect(h.writes()).toBe(0);
  });

  it("does not let a legacy release erase possible delivery", async () => {
    const state = prior(); const h = harness(state);
    expect((await h.rpc({ action: "release", token: state.token })).status).toBe(409);
    expect(h.state()).toBe(state);
  });

  it("rejects non-string tokens without changing a claim", async () => {
    const h = harness();
    expect((await h.rpc({ action: "claim", token: true })).status).toBe(400);
    expect(h.writes()).toBe(0);
  });

  it("keeps completed state when the completion acknowledgement is lost", async () => {
    const h = harness(undefined, "complete_ack_lost");
    const send = vi.fn(async () => "provider-accepted");
    await expect(runV213BroadcastOnce(h.namespace, "synthetic-slot", send)).rejects.toThrow("SYNTHETIC_COMPLETE_ACK_LOST");
    expect(h.state().status).toBe("sent");
    expect(await runV213BroadcastOnce(h.namespace, "synthetic-slot", send)).toMatchObject({ status: "duplicate" });
    expect(send).toHaveBeenCalledOnce();
  });

  it.each(["malformed_claim", "unbound_claim"])("refuses %s without calling the transport", async fault => {
    const h = harness(undefined, fault); const send = vi.fn(async () => "must-not-send");
    await expect(runV213BroadcastOnce(h.namespace, "synthetic-slot", send)).rejects.toThrow("V213_BROADCAST_DEDUPE_RESPONSE_INVALID");
    expect(send).not.toHaveBeenCalled(); expect(h.writes()).toBe(0);
  });

  it("does not treat a malformed success acknowledgement as completed", async () => {
    const h = harness(undefined, "malformed_complete"); const send = vi.fn(async () => "provider-accepted");
    await expect(runV213BroadcastOnce(h.namespace, "synthetic-slot", send)).rejects.toThrow("V213_BROADCAST_DEDUPE_RESPONSE_INVALID");
    expect(h.state()).toMatchObject({ status: "pending", delivery_unknown: true });
    expect(await runV213BroadcastOnce(h.namespace, "synthetic-slot", send)).toMatchObject({ status: "delivery_unknown" });
    expect(send).toHaveBeenCalledOnce();
  });

  it("preserves the primary failure and original pending record if uncertainty persistence fails", async () => {
    vi.useFakeTimers(); vi.setSystemTime(new Date("2026-09-10T04:00:00Z"));
    try {
      const h = harness(undefined, "uncertain_write"); const send = vi.fn(async () => { throw new Error("SYNTHETIC_PRIMARY_FAILURE"); });
      await expect(runV213BroadcastOnce(h.namespace, "synthetic-slot", send)).rejects.toThrow("SYNTHETIC_PRIMARY_FAILURE");
      expect(h.state().status).toBe("pending");
      expect(await runV213BroadcastOnce(h.namespace, "synthetic-slot", send)).toMatchObject({ status: "in_progress" });
      for (const delay of [11 * 60_000, 73 * 3600_000]) {
        vi.setSystemTime(new Date(Date.now() + delay));
        expect(await runV213BroadcastOnce(h.namespace, "synthetic-slot", send)).toMatchObject({ status: "delivery_unknown" });
      }
      expect(send).toHaveBeenCalledOnce();
    } finally { vi.useRealTimers(); }
  });
});
