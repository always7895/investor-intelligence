/// <reference types="node" />
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import policy from "../../config/v213-compact-qa-v1.json";
import {
  ACQUIRE_MARGIN_MS,
  COMPACT_ABSOLUTE_BUDGET_MS,
  COMPACT_TIMEOUT_MS,
  DEFAULT_ACQUIRE_WAIT_MS,
  DEFAULT_JOB_WRITES_PER_DAY,
  DEFAULT_LEASE_MS,
  GATE_CALL_TIMEOUT_MS,
  FRIEND_JOB_WRITES_PER_JOB,
  FRIEND_KV_WRITE_ACTIONS_PER_DAY,
  FRIEND_MODEL_PER_DAY,
  FRIEND_MODEL_PER_MINUTE,
  FRIEND_PUBLIC_PER_DAY,
  FRIEND_PUBLIC_PER_MINUTE,
  MAX_ACQUIRE_WAIT_MS,
  clampFriendQaLimits,
  friendGateConfigured,
  friendQaLimits,
  type FriendQaGateEnv,
  gateAcquire,
  gateAdmit,
  gateRelease,
  gateReserveJobWrites,
  gateTenantKey,
  newAttemptId,
  taipeiDayBucket,
} from "../src/v213/friend-qa-gate";
import { memoryFriendGate } from "./line-all-friends-fixture";

const TENANT_X = "SYNTHETIC_TENANT_X_".padEnd(43, "x");
const TENANT_Y = "SYNTHETIC_TENANT_Y_".padEnd(43, "y");
const TENANT_Z = "SYNTHETIC_TENANT_Z_".padEnd(43, "z");
const START = new Date("2026-10-12T04:00:30+08:00");

function setup(env: Record<string, string> = {}) {
  const gate = memoryFriendGate();
  return { gate, env: { V213_FRIEND_QA_GATE: gate.namespace, ...env } as FriendQaGateEnv };
}
const lane = (gate: ReturnType<typeof memoryFriendGate>) =>
  Object.values(((gate.values.get("lane") as { leases?: Record<string, unknown> } | undefined)?.leases ?? {}));

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(START);
});
afterEach(() => {
  vi.useRealTimers();
});

describe("limits and the model-call timing clamp", () => {
  it("keeps acquire wait + compact timeout + margin inside the absolute budget, whatever the env says", () => {
    expect(COMPACT_TIMEOUT_MS).toBe(policy.timeout_ms);
    expect(COMPACT_ABSOLUTE_BUDGET_MS).toBe(policy.absolute_budget_ms);
    expect(MAX_ACQUIRE_WAIT_MS + COMPACT_TIMEOUT_MS + ACQUIRE_MARGIN_MS).toBeLessThanOrEqual(COMPACT_ABSOLUTE_BUDGET_MS);
    expect(DEFAULT_ACQUIRE_WAIT_MS).toBeLessThanOrEqual(MAX_ACQUIRE_WAIT_MS);
    for (const value of ["999999", "28000", "6001", "Infinity"]) {
      const limits = friendQaLimits({ V213_FRIEND_QA_ACQUIRE_WAIT_MS: value });
      expect(limits.acquireWaitMs + COMPACT_TIMEOUT_MS + ACQUIRE_MARGIN_MS).toBeLessThanOrEqual(COMPACT_ABSOLUTE_BUDGET_MS);
    }
    expect(friendQaLimits({ V213_FRIEND_QA_ACQUIRE_WAIT_MS: "-5" }).acquireWaitMs).toBe(0);
    // The Durable Object re-clamps what a caller sends.
    expect(clampFriendQaLimits({ acquireWaitMs: 10 ** 9, leaseMs: 1, globalInFlight: 99, queueMax: 99 })).toMatchObject({
      acquireWaitMs: MAX_ACQUIRE_WAIT_MS,
      leaseMs: COMPACT_ABSOLUTE_BUDGET_MS + 2000,
      globalInFlight: 4,
      queueMax: 8,
    });
  });

  it("defaults to the gateway's one generation, a lease longer than the budget, and 150 job writes", () => {
    expect(friendQaLimits({})).toEqual({
      globalInFlight: 1,
      queueMax: 2,
      acquireWaitMs: DEFAULT_ACQUIRE_WAIT_MS,
      leaseMs: DEFAULT_LEASE_MS,
      jobWritesPerDay: DEFAULT_JOB_WRITES_PER_DAY,
    });
    expect(DEFAULT_LEASE_MS).toBeGreaterThan(COMPACT_ABSOLUTE_BUDGET_MS);
    expect(DEFAULT_JOB_WRITES_PER_DAY).toBe(150);
    for (const [value, expected] of [["0", 1], ["3", 3], ["9", 4], ["abc", 1], ["", 1]] as const) {
      expect(friendQaLimits({ V213_FRIEND_QA_GLOBAL_INFLIGHT: value }).globalInFlight).toBe(expected);
    }
    expect(friendQaLimits({ V213_FRIEND_QA_QUEUE_MAX: "99" }).queueMax).toBe(8);
    expect(friendQaLimits({ V213_FRIEND_JOB_WRITES_PER_DAY: "abc" }).jobWritesPerDay).toBe(150);
  });

  it("puts the day boundary at 00:00 +08:00 with no time-zone library", () => {
    const before = Date.parse("2026-10-12T23:59:59.999+08:00");
    const after = Date.parse("2026-10-13T00:00:00.000+08:00");
    expect(taipeiDayBucket(after)).toBe(taipeiDayBucket(before) + 1);
    expect(taipeiDayBucket(Date.parse("2026-10-12T00:00:00.000+08:00"))).toBe(taipeiDayBucket(before));
    // 00:00 UTC is 08:00 in Taipei: the same Taipei day as the hours before and after it.
    expect(taipeiDayBucket(Date.parse("2026-10-12T00:00:00Z"))).toBe(taipeiDayBucket(Date.parse("2026-10-12T15:59:00Z")));
  });
});

describe("admit: dedupe and public-read caps", () => {
  it("dedupes an event for 24 hours and then forgets it", async () => {
    const { env } = setup();
    expect(await gateAdmit(env, TENANT_X, "event-1", "public")).toEqual({ ok: true });
    expect(await gateAdmit(env, TENANT_X, "event-1", "public")).toEqual({ ok: false, reason: "duplicate" });
    expect(await gateAdmit(env, TENANT_Y, "event-1", "public")).toEqual({ ok: false, reason: "duplicate" });
    vi.setSystemTime(new Date(START.getTime() + 24 * 3_600_000 + 1000));
    expect(await gateAdmit(env, TENANT_X, "event-1", "public")).toEqual({ ok: true });
  });

  it("does not count a duplicate or a follow against the read caps", async () => {
    const { env } = setup();
    for (let index = 0; index < FRIEND_PUBLIC_PER_MINUTE + 5; index += 1) {
      expect((await gateAdmit(env, TENANT_X, "same-event", "public")).ok).toBe(index === 0);
      expect(await gateAdmit(env, TENANT_X, `follow-${index}`, "follow")).toEqual({ ok: true });
    }
    expect(await gateAdmit(env, TENANT_X, "next", "public")).toEqual({ ok: true });
  });

  it("allows 20 reads a minute and 400 a Taipei day per friend, independently per friend", async () => {
    const { env } = setup();
    for (let index = 0; index < FRIEND_PUBLIC_PER_MINUTE; index += 1) {
      expect(await gateAdmit(env, TENANT_X, `m-${index}`, "public")).toEqual({ ok: true });
    }
    expect(await gateAdmit(env, TENANT_X, "m-over", "public")).toEqual({ ok: false, reason: "rate" });
    expect(await gateAdmit(env, TENANT_Y, "y-1", "public")).toEqual({ ok: true });
    const minutes = FRIEND_PUBLIC_PER_DAY / FRIEND_PUBLIC_PER_MINUTE;
    for (let minute = 1; minute < minutes; minute += 1) {
      vi.setSystemTime(new Date(START.getTime() + minute * 60_000));
      for (let index = 0; index < FRIEND_PUBLIC_PER_MINUTE; index += 1) {
        expect(await gateAdmit(env, TENANT_X, `d-${minute}-${index}`, "public")).toEqual({ ok: true });
      }
    }
    vi.setSystemTime(new Date(START.getTime() + minutes * 60_000));
    expect(await gateAdmit(env, TENANT_X, "day-over", "public")).toEqual({ ok: false, reason: "rate" });
    vi.setSystemTime(new Date("2026-10-13T00:00:05+08:00"));
    expect(await gateAdmit(env, TENANT_X, "next-day", "public")).toEqual({ ok: true });
  });

  it("caps the KV-writing data commands per friend per Taipei day", async () => {
    const { env } = setup();
    for (let index = 0; index < FRIEND_KV_WRITE_ACTIONS_PER_DAY; index += 1) {
      expect(await gateAdmit(env, TENANT_X, `kv-${index}`, "kv_write")).toEqual({ ok: true });
    }
    expect(await gateAdmit(env, TENANT_X, "kv-over", "kv_write")).toEqual({ ok: false, reason: "rate_kv" });
    expect(await gateAdmit(env, TENANT_Y, "kv-y", "kv_write")).toEqual({ ok: true });
    vi.setSystemTime(new Date("2026-10-12T23:59:59+08:00"));
    expect(await gateAdmit(env, TENANT_X, "kv-late", "kv_write")).toEqual({ ok: false, reason: "rate_kv" });
    vi.setSystemTime(new Date("2026-10-13T00:00:01+08:00"));
    expect(await gateAdmit(env, TENANT_X, "kv-tomorrow", "kv_write")).toEqual({ ok: true });
  });
});

describe("acquire: the shared model lane", () => {
  it("grants one slot, makes the same friend wait, and gives up after the bounded wait", async () => {
    const { env, gate } = setup({ V213_FRIEND_QA_ACQUIRE_WAIT_MS: "30" });
    const first = newAttemptId();
    expect(await gateAcquire(env, TENANT_X, first, false)).toEqual({ status: "granted" });
    expect(lane(gate)).toHaveLength(1);
    expect(await gateAcquire(env, TENANT_Y, newAttemptId(), false)).toEqual({ status: "busy", reason: "wait_timeout" });
    expect(lane(gate)).toHaveLength(1);
    await gateRelease(env, first);
    await gateRelease(env, first); // idempotent
    expect(lane(gate)).toHaveLength(0);
    expect(await gateAcquire(env, TENANT_Y, newAttemptId(), false)).toEqual({ status: "granted" });
  });

  it("answers busy at once when the waiting room is full or disabled", async () => {
    const { env } = setup({ V213_FRIEND_QA_QUEUE_MAX: "0", V213_FRIEND_QA_ACQUIRE_WAIT_MS: "5000" });
    const started = performance.now();
    expect(await gateAcquire(env, TENANT_X, newAttemptId(), false)).toEqual({ status: "granted" });
    expect(await gateAcquire(env, TENANT_Y, newAttemptId(), false)).toEqual({ status: "busy", reason: "queue_full" });
    expect(performance.now() - started).toBeLessThan(1000);
    const noWait = setup({ V213_FRIEND_QA_ACQUIRE_WAIT_MS: "0" });
    expect(await gateAcquire(noWait.env, TENANT_X, newAttemptId(), false)).toEqual({ status: "granted" });
    expect(await gateAcquire(noWait.env, TENANT_Y, newAttemptId(), false)).toEqual({ status: "busy", reason: "queue_full" });
  });

  it("serves waiting friends first-come-first-served as slots free, and lets only QUEUE_MAX wait", async () => {
    const { env, gate } = setup({ V213_FRIEND_QA_QUEUE_MAX: "2", V213_FRIEND_QA_ACQUIRE_WAIT_MS: "4000" });
    const a = newAttemptId();
    const b = newAttemptId();
    const c = newAttemptId();
    expect(await gateAcquire(env, TENANT_X, a, false)).toEqual({ status: "granted" });
    const order: string[] = [];
    const second = gateAcquire(env, TENANT_Y, b, false).then((result) => {
      order.push(`B:${result.status}`);
      return result;
    });
    await vi.waitFor(() => expect(gate.calls.filter((call) => call.action === "acquire")).toHaveLength(2));
    await new Promise((resolve) => setTimeout(resolve, 20));
    const third = gateAcquire(env, TENANT_Z, c, false).then((result) => {
      order.push(`C:${result.status}`);
      return result;
    });
    await vi.waitFor(() => expect(gate.calls.filter((call) => call.action === "acquire")).toHaveLength(3));
    await new Promise((resolve) => setTimeout(resolve, 20));
    // Queue is full for a fourth friend.
    expect(await gateAcquire(env, `${TENANT_X}-4`, newAttemptId(), false)).toEqual({ status: "busy", reason: "queue_full" });
    await gateRelease(env, a);
    expect(await second).toEqual({ status: "granted" });
    expect(order).toEqual(["B:granted"]);
    await gateRelease(env, b);
    expect(await third).toEqual({ status: "granted" });
    expect(order).toEqual(["B:granted", "C:granted"]);
    await gateRelease(env, c);
    expect(lane(gate)).toHaveLength(0);
  });

  it("registers a waiting place atomically: concurrent requests never exceed QUEUE_MAX or give one friend two places", async () => {
    const { env } = setup({ V213_FRIEND_QA_QUEUE_MAX: "1", V213_FRIEND_QA_ACQUIRE_WAIT_MS: "120" });
    expect(await gateAcquire(env, TENANT_X, newAttemptId(), false)).toEqual({ status: "granted" });
    const places = await Promise.all([
      gateAcquire(env, TENANT_Y, newAttemptId(), false),
      gateAcquire(env, TENANT_Z, newAttemptId(), false),
    ]);
    expect(places.map((result) => (result.status === "busy" ? result.reason : result.status)).sort()).toEqual(["queue_full", "wait_timeout"]);
    const roomy = setup({ V213_FRIEND_QA_QUEUE_MAX: "4", V213_FRIEND_QA_ACQUIRE_WAIT_MS: "120" });
    expect(await gateAcquire(roomy.env, TENANT_X, newAttemptId(), false)).toEqual({ status: "granted" });
    const same = await Promise.all([
      gateAcquire(roomy.env, TENANT_Y, newAttemptId(), false),
      gateAcquire(roomy.env, TENANT_Y, newAttemptId(), false),
    ]);
    expect(same.map((result) => (result.status === "busy" ? result.reason : result.status)).sort()).toEqual(["tenant_busy", "wait_timeout"]);
  });

  it("frees a timed-out waiting place for the next friend", async () => {
    const { env } = setup({ V213_FRIEND_QA_QUEUE_MAX: "1", V213_FRIEND_QA_ACQUIRE_WAIT_MS: "30" });
    expect(await gateAcquire(env, TENANT_X, newAttemptId(), false)).toEqual({ status: "granted" });
    expect(await gateAcquire(env, TENANT_Y, newAttemptId(), false)).toEqual({ status: "busy", reason: "wait_timeout" });
    expect(await gateAcquire(env, TENANT_Z, newAttemptId(), false)).toEqual({ status: "busy", reason: "wait_timeout" });
  });

  it("allows one in flight and one waiting per friend, never a third", async () => {
    const { env, gate } = setup({ V213_FRIEND_QA_GLOBAL_INFLIGHT: "2", V213_FRIEND_QA_ACQUIRE_WAIT_MS: "4000" });
    const first = newAttemptId();
    expect(await gateAcquire(env, TENANT_X, first, false)).toEqual({ status: "granted" });
    // A free global slot does not let the same friend run two at once: the second waits.
    const second = gateAcquire(env, TENANT_X, newAttemptId(), false);
    await vi.waitFor(() => expect(gate.calls.filter((call) => call.action === "acquire")).toHaveLength(2));
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(await gateAcquire(env, TENANT_X, newAttemptId(), false)).toEqual({ status: "busy", reason: "tenant_busy" });
    // Another friend takes the free slot meanwhile.
    expect(await gateAcquire(env, TENANT_Y, newAttemptId(), false)).toEqual({ status: "granted" });
    await gateRelease(env, first);
    expect(await second).toEqual({ status: "granted" });
  });

  it("does not charge the 3/min and 30/day counts for a wait that timed out", async () => {
    const { env } = setup({ V213_FRIEND_QA_QUEUE_MAX: "1", V213_FRIEND_QA_ACQUIRE_WAIT_MS: "30" });
    const holder = newAttemptId();
    expect(await gateAcquire(env, TENANT_X, holder, false)).toEqual({ status: "granted" });
    for (let index = 0; index < FRIEND_MODEL_PER_MINUTE + 1; index += 1) {
      expect(await gateAcquire(env, TENANT_Y, newAttemptId(), false)).toEqual({ status: "busy", reason: "wait_timeout" });
    }
    await gateRelease(env, holder);
    for (let index = 0; index < FRIEND_MODEL_PER_MINUTE; index += 1) {
      const attempt = newAttemptId();
      expect(await gateAcquire(env, TENANT_Y, attempt, false)).toEqual({ status: "granted" });
      await gateRelease(env, attempt);
    }
    expect(await gateAcquire(env, TENANT_Y, newAttemptId(), false)).toEqual({ status: "busy", reason: "tenant_rate_minute" });
  });

  it("limits each friend to 3 model questions a minute and 30 a Taipei day", async () => {
    const { env } = setup();
    const cycle = async (tenant: string) => {
      const attempt = newAttemptId();
      const result = await gateAcquire(env, tenant, attempt, false);
      if (result.status === "granted") await gateRelease(env, attempt);
      return result;
    };
    for (let index = 0; index < FRIEND_MODEL_PER_MINUTE; index += 1) expect(await cycle(TENANT_X)).toEqual({ status: "granted" });
    expect(await cycle(TENANT_X)).toEqual({ status: "busy", reason: "tenant_rate_minute" });
    expect(await cycle(TENANT_Y)).toEqual({ status: "granted" });
    for (let minute = 1; minute < FRIEND_MODEL_PER_DAY / FRIEND_MODEL_PER_MINUTE; minute += 1) {
      vi.setSystemTime(new Date(START.getTime() + minute * 60_000));
      for (let index = 0; index < FRIEND_MODEL_PER_MINUTE; index += 1) expect(await cycle(TENANT_X)).toEqual({ status: "granted" });
    }
    vi.setSystemTime(new Date("2026-10-12T23:59:50+08:00"));
    expect(await cycle(TENANT_X)).toEqual({ status: "busy", reason: "tenant_rate_day" });
    vi.setSystemTime(new Date("2026-10-13T00:00:10+08:00"));
    expect(await cycle(TENANT_X)).toEqual({ status: "granted" });
  });

  it("expires a lease that was never released, so a crashed Worker cannot leak a slot", async () => {
    const { env, gate } = setup({ V213_FRIEND_QA_ACQUIRE_WAIT_MS: "0" });
    expect(await gateAcquire(env, TENANT_X, newAttemptId(), false)).toEqual({ status: "granted" });
    expect(await gateAcquire(env, TENANT_Y, newAttemptId(), false)).toEqual({ status: "busy", reason: "queue_full" });
    vi.setSystemTime(new Date(START.getTime() + DEFAULT_LEASE_MS - 1000));
    expect(await gateAcquire(env, TENANT_Y, newAttemptId(), false)).toEqual({ status: "busy", reason: "queue_full" });
    vi.setSystemTime(new Date(START.getTime() + DEFAULT_LEASE_MS + 1000));
    expect(await gateAcquire(env, TENANT_Y, newAttemptId(), false)).toEqual({ status: "granted" });
    expect(lane(gate)).toHaveLength(1);
  });

  it("serves the owner at once while friends are saturated, and the owner still counts toward the cap", async () => {
    const { env, gate } = setup({ V213_FRIEND_QA_QUEUE_MAX: "0" });
    const friend = newAttemptId();
    expect(await gateAcquire(env, TENANT_X, friend, false)).toEqual({ status: "granted" });
    expect(await gateAcquire(env, TENANT_Y, newAttemptId(), false)).toEqual({ status: "busy", reason: "queue_full" });
    const owner = newAttemptId();
    expect(await gateAcquire(env, TENANT_Z, owner, true)).toEqual({ status: "granted" });
    expect(lane(gate)).toHaveLength(2);
    await gateRelease(env, friend);
    // One owner lease still occupies the single friend slot.
    expect(await gateAcquire(env, TENANT_Y, newAttemptId(), false)).toEqual({ status: "busy", reason: "queue_full" });
    await gateRelease(env, owner);
    expect(await gateAcquire(env, TENANT_Y, newAttemptId(), false)).toEqual({ status: "granted" });
  });
});

describe("job writes: the daily cap on parked friend jobs", () => {
  it("allows cap/2 parked jobs a Taipei day, then refuses until 00:00 +08:00", async () => {
    const { env } = setup({ V213_FRIEND_JOB_WRITES_PER_DAY: "5" });
    expect(FRIEND_JOB_WRITES_PER_JOB).toBe(2);
    expect(await gateReserveJobWrites(env)).toBe(true);
    expect(await gateReserveJobWrites(env)).toBe(true);
    expect(await gateReserveJobWrites(env)).toBe(false); // 6 > 5
    vi.setSystemTime(new Date("2026-10-12T23:59:59+08:00"));
    expect(await gateReserveJobWrites(env)).toBe(false);
    vi.setSystemTime(new Date("2026-10-13T00:00:01+08:00"));
    expect(await gateReserveJobWrites(env)).toBe(true);
  });

  it("refuses everything when the cap is zero", async () => {
    const { env } = setup({ V213_FRIEND_JOB_WRITES_PER_DAY: "0" });
    expect(await gateReserveJobWrites(env)).toBe(false);
  });
});

describe("storage hygiene and failure handling", () => {
  it("holds only hashes, counters, expiries and leases, and prunes what has expired", async () => {
    const { env, gate } = setup();
    await gateAdmit(env, TENANT_X, "raw-webhook-event-id", "public");
    await gateAdmit(env, TENANT_X, undefined, "kv_write");
    const attempt = newAttemptId();
    await gateAcquire(env, TENANT_X, attempt, false);
    await gateRelease(env, attempt);
    await gateReserveJobWrites(env);
    const dump = JSON.stringify([...gate.values]);
    expect(dump).not.toContain(TENANT_X);
    expect(dump).not.toContain("raw-webhook-event-id");
    expect(dump).toContain(await gateTenantKey(TENANT_X));
    const keys = [...gate.values.keys()];
    expect(keys.every((key) => /^(ev|rm|rd|qm|qd|kd|jw|lane)(:|$)/.test(key))).toBe(true);
    const hashX = await gateTenantKey(TENANT_X);
    // Four days later any call prunes the rows of that day and keeps only the fresh ones.
    vi.setSystemTime(new Date(START.getTime() + 4 * 86_400_000));
    await gateAdmit(env, TENANT_Y, "later-event", "public");
    expect([...gate.values.keys()].some((key) => key.includes(hashX))).toBe(false);
    expect([...gate.values.keys()].filter((key) => key.startsWith("ev:"))).toHaveLength(1);
    expect([...gate.values.keys()].filter((key) => key.startsWith("jw:"))).toHaveLength(0);
  });

  it("fails closed when unbound, throwing or answering garbage; release never throws", async () => {
    expect(friendGateConfigured({})).toBe(false);
    const unbound = {};
    const throwing = { V213_FRIEND_QA_GATE: memoryFriendGate({ failure: "throw" }).namespace };
    const garbage = { V213_FRIEND_QA_GATE: memoryFriendGate({ failure: "malformed" }).namespace };
    for (const env of [unbound, throwing, garbage]) {
      expect(await gateAdmit(env, TENANT_X, "e", "public")).toEqual({ ok: false, reason: "unavailable" });
      expect(await gateAcquire(env, TENANT_X, newAttemptId(), false)).toEqual({ status: "busy", reason: "unavailable" });
      expect(await gateReserveJobWrites(env)).toBe(false);
      await expect(gateRelease(env, newAttemptId())).resolves.toBeUndefined();
    }
  });

  it("treats a bound Durable Object that never answers as unavailable within a bound", async () => {
    const env = { V213_FRIEND_QA_GATE: memoryFriendGate({ failure: "hang" }).namespace, V213_FRIEND_QA_ACQUIRE_WAIT_MS: "0" };
    const realStart = performance.now();
    const results = await Promise.all([
      gateAdmit(env, TENANT_X, "e", "public"),
      gateAcquire(env, TENANT_X, newAttemptId(), false),
      gateAcquire(env, TENANT_X, newAttemptId(), true),
      gateReserveJobWrites(env),
      gateRelease(env, newAttemptId()),
    ]);
    expect(results.slice(0, 4)).toEqual([
      { ok: false, reason: "unavailable" },
      { status: "busy", reason: "unavailable" },
      { status: "busy", reason: "unavailable" },
      false,
    ]);
    expect(performance.now() - realStart).toBeLessThan(GATE_CALL_TIMEOUT_MS + 1500);
  }, 10_000);

  it("rejects malformed requests without touching storage", async () => {
    const { gate } = setup();
    const stub = gate.namespace.get(gate.namespace.idFromName("x"));
    const post = (body: unknown) =>
      stub.fetch("https://friend-qa-gate.internal/action", { method: "POST", body: typeof body === "string" ? body : JSON.stringify(body) });
    expect((await post("not json")).status).toBe(400);
    expect((await post({ action: "nope" })).status).toBe(400);
    expect((await post({ action: "admit", th: "short", kind: "public" })).status).toBe(400);
    expect((await post({ action: "admit", th: "a".repeat(43), kind: "weird" })).status).toBe(400);
    expect((await post({ action: "acquire", th: "a".repeat(43), att: "a".repeat(32), owner: "yes" })).status).toBe(400);
    expect((await post({ action: "job_writes", n: 99, cap: 1 })).status).toBe(400);
    expect((await stub.fetch("https://friend-qa-gate.internal/action", { method: "GET" })).status).toBe(405);
    expect(gate.values.size).toBe(0);
  });
});
