/// <reference types="node" />
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  FRIEND_AI_BUSY_REPLY,
  FRIEND_AI_DAY_LIMIT_REPLY,
  FRIEND_AI_MINUTE_LIMIT_REPLY,
  FRIEND_AI_OWN_BUSY_REPLY,
  FRIEND_EDUCATION_SENTENCE,
  FRIEND_KV_ACTION_LIMIT_REPLY,
  FRIEND_PORTFOLIO_REFUSAL,
  FRIEND_RATE_REPLY,
  FRIEND_SERVICE_BUSY_REPLY,
  OWNER_ONLY_REPLY,
} from "../src/v211/line-access";
import { FRIEND_MODEL_PER_DAY, FRIEND_MODEL_PER_MINUTE } from "../src/v213/friend-qa-gate";
import { getOwnerPushTarget } from "../src/v21/owner-storage";
import { edgeReadiness } from "../src/v213/readiness";
import {
  FRIEND_A,
  FRIEND_B,
  FRIEND_C,
  MODEL_ANSWER,
  OWNER_USER,
  QUESTION,
  lineFixture,
  type FixtureOptions,
} from "./line-all-friends-fixture";

type Fixture = Awaited<ReturnType<typeof lineFixture>>;
const open: Fixture[] = [];
async function fixture(options: FixtureOptions = {}): Promise<Fixture> {
  for (const previous of open.splice(0)) previous.restore();
  const f = await lineFixture(options);
  open.push(f);
  return f;
}
const ALL = { mode: "all_friends" } satisfies FixtureOptions;
const OWNER_ONLY_MODES: Array<string | undefined> = [
  undefined,
  "owner_only",
  "",
  "ALL_FRIENDS",
  " all_friends",
  "all_friends ",
  "all-friends",
  "true",
  "1",
  "allowlist",
];

beforeEach(() => {
  // Fixed clock: Taipei 2026-10-12 04:00:30, a minute and a day boundary away from nothing special.
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-12T04:00:30+08:00"));
});
afterEach(() => {
  for (const f of open.splice(0)) f.restore();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

/** A model that blocks every call until released, so a request can be held in flight. */
function heldModel(f: Fixture) {
  const resolvers: Array<() => void> = [];
  let holding = true;
  const answer = () => new Response(JSON.stringify({ choices: [{ message: { content: MODEL_ANSWER } }] }));
  f.model.handler = () => (holding ? new Promise<Response>((resolve) => resolvers.push(() => resolve(answer()))) : Promise.resolve(answer()));
  return {
    hold: () => {
      holding = true;
    },
    release: () => {
      holding = false;
      for (const resolve of resolvers.splice(0)) resolve();
    },
  };
}

const acquireCalls = (f: Fixture) => f.gate?.calls.filter((call) => call.action === "acquire") ?? [];

describe("rollback switch: anything but exactly all_friends is today's owner-only behaviour", () => {
  it.each(OWNER_ONLY_MODES)("mode %j: friends are silent, the owner path is the unchanged KV path, zero gate calls", async (mode) => {
    const f = await fixture({ mode });
    for (const text of ["說明", "TOP20", QUESTION, "取消配對", "通知狀態"]) {
      await f.deliver(FRIEND_A, text);
    }
    await f.deliver(FRIEND_A, null, { type: "follow" });
    expect(f.replies).toHaveLength(0);
    expect(f.prompts).toHaveLength(0);
    expect(f.writes()).toBe(0);
    expect(f.gate?.calls).toHaveLength(0);

    await f.deliver(OWNER_USER, "說明");
    expect(f.replies).toHaveLength(1);
    expect(f.replies[0]?.text).toContain("配對不代表推送已上線");
    // claimEvent + rateLimit + completeEvent, exactly as before.
    expect(f.spies.securityPut).toHaveBeenCalledTimes(3);
    expect(f.gate?.calls).toHaveLength(0);

    await f.deliver(OWNER_USER, "通知狀態");
    expect(f.replies[1]?.text).toContain("PAIRED（已配對）");
    await f.deliver(OWNER_USER, QUESTION);
    expect(f.replies[2]?.text).toContain(MODEL_ANSWER);
    expect(f.gate?.calls).toHaveLength(0);
    expect(f.urls.some((url) => url.includes("/push"))).toBe(false);
  });

  it("pairing enrolment keeps working for anyone while no owner is paired, in both modes", async () => {
    for (const mode of ["owner_only", "all_friends"]) {
      const f = await fixture({ mode, ownerPaired: false });
      await f.deliver(FRIEND_A, "配對 abcdefgh12");
      expect(f.replies.map((reply) => reply.text)).toEqual(["配對碼無效或已停用。"]);
    }
  });

  it("/health reports the mode instead of a hard-coded owner_only", async () => {
    const closed = await fixture({ gate: false });
    const closedHealth = await closed.health();
    expect(closedHealth).toMatchObject({ owner_only: true, line_access_mode: "owner_only", friend_queue_configured: false, direct_chat_only: true });
    const garbage = await fixture({ mode: "ALL_FRIENDS" });
    expect(await garbage.health()).toMatchObject({ owner_only: true, line_access_mode: "owner_only", friend_queue_configured: true });
    const open_ = await fixture(ALL);
    expect(await open_.health()).toMatchObject({
      ok: true,
      owner_only: false,
      line_access_mode: "all_friends",
      friend_queue_configured: true,
      direct_chat_only: true,
      portfolio_access: false,
      brokerage_connection: false,
      ibkr_bridge: false,
      automatic_trading: false,
    });
    const unbound = await fixture({ ...ALL, gate: false });
    expect(await unbound.health()).toMatchObject({ line_access_mode: "all_friends", friend_queue_configured: false });
  });

  it("readiness reports the access mode without touching storage", async () => {
    const trap = new Proxy({}, { get() { throw new Error("READINESS_MUST_NOT_TOUCH_STORAGE"); } });
    const version = "12345678-1234-1234-1234-123456789abc";
    for (const [mode, expected] of [[undefined, "owner_only"], ["all_friends", "all_friends"], ["x", "owner_only"]] as const) {
      const response = await edgeReadiness(
        new Request(`https://synthetic.workers.dev/v213/readiness?challenge=${"1".repeat(32)}&expected_version=${version}`),
        { CF_VERSION_METADATA: { id: version }, V213_LINE_ACCESS_MODE: mode, PUBLIC_CACHE: trap, V213_FRIEND_QA_GATE: trap } as never,
      );
      expect(response.status).toBe(200);
      expect(await response.json()).toMatchObject({ ready: true, no_write: true, line_access_mode: expected });
    }
  });
});

describe("all_friends: public features for every direct-chat friend", () => {
  it("answers help, TOP20, system status, option arithmetic and the portfolio refusal with zero KV writes", async () => {
    const f = await fixture(ALL);
    await f.deliver(FRIEND_A, "說明");
    await f.deliver(FRIEND_A, "TOP20");
    await f.deliver(FRIEND_A, "系統狀態");
    await f.deliver(FRIEND_A, "期權試算說明");
    await f.deliver(FRIEND_A, "持倉");
    await f.deliver(FRIEND_A, "我持有 100 股 NVDA");
    expect(f.replies).toHaveLength(6);
    const [help, top, status, option, portfolio, holdings] = f.replies.map((reply) => reply.text);
    expect(help).toContain(FRIEND_EDUCATION_SENTENCE);
    expect(help).not.toContain("通知狀態");
    expect(help).not.toContain("配對");
    expect(top).toMatch(/top\s*20/i);
    expect(status).toContain("系統狀態：ONLINE");
    expect(status).toContain("即時資料 Gate");
    expect(status).not.toMatch(/Qwen|租戶記憶|雲端生成|IBKR/);
    expect(option).toContain("不會查詢券商、持倉或帳戶");
    expect(portfolio).toBe(FRIEND_PORTFOLIO_REFUSAL);
    expect(holdings).toBe(FRIEND_PORTFOLIO_REFUSAL);
    expect(f.writes()).toBe(0);
    expect(f.prompts).toHaveLength(0);
    expect(acquireCalls(f)).toHaveLength(0);
  });

  it("greets a new friend with the public text (no notification or pairing line) and not twice for a redelivery", async () => {
    const f = await fixture(ALL);
    await f.deliver(FRIEND_A, null, { type: "follow", eventId: "synthetic-follow-1" });
    await f.deliver(FRIEND_A, null, { type: "follow", eventId: "synthetic-follow-1" });
    expect(f.replies).toHaveLength(1);
    expect(f.replies[0]?.text).toContain(FRIEND_EDUCATION_SENTENCE);
    expect(f.replies[0]?.text).not.toContain("通知狀態");
    expect(f.replies[0]?.text).not.toContain("配對");
    expect(f.writes()).toBe(0);
    await f.deliver(OWNER_USER, null, { type: "follow" });
    expect(f.replies[1]?.text).toContain("通知狀態");
  });

  it("answers an open question from the local model for a friend, with zero KV writes and no identifier in the prompt", async () => {
    const f = await fixture(ALL);
    await f.deliver(FRIEND_A, QUESTION);
    expect(f.replies).toHaveLength(1);
    expect(f.replies[0]?.text).toContain(MODEL_ANSWER);
    expect(f.prompts).toHaveLength(1);
    expect(f.writes()).toBe(0);
    const tenant = await f.tenantOf(FRIEND_A);
    for (const secret of [FRIEND_A, OWNER_USER, tenant, "synthetic-reply-token"]) {
      expect(f.prompts.join("\n")).not.toContain(secret);
    }
    // The lane is free again once the answer is out.
    expect(Object.keys((f.gate?.values.get("lane") as { leases: object } | undefined)?.leases ?? {})).toHaveLength(0);
  });

  it("ignores groups and rooms before any storage in every mode", async () => {
    for (const mode of ["all_friends", "owner_only"]) {
      const f = await fixture({ mode });
      await f.deliver(FRIEND_A, "說明", { sourceType: "group" });
      await f.deliver(FRIEND_A, QUESTION, { sourceType: "room" });
      expect(f.replies).toHaveLength(0);
      expect(f.writes()).toBe(0);
      expect(f.gate?.calls).toHaveLength(0);
    }
  });

  it("never pushes, and the owner stays the only push target", async () => {
    const f = await fixture(ALL);
    await f.deliver(FRIEND_A, QUESTION);
    await f.deliver(FRIEND_B, "刪除我的資料");
    await f.deliver(FRIEND_C, null, { type: "follow" });
    expect(f.urls.some((url) => url.includes("/push"))).toBe(false);
    expect((await getOwnerPushTarget(f.env as never))?.lineUserId).toBe(OWNER_USER);
  });
});

describe("all_friends: owner-only features refuse a friend and leak nothing", () => {
  it.each(["取消配對", "取消配对", "unpair", "通知狀態", "通知状态", "notification status"])("%s gets the neutral owner-only text", async (text) => {
    const f = await fixture(ALL);
    const pairing = [...f.privateKv.values];
    await f.deliver(FRIEND_A, text);
    expect(f.replies.map((reply) => reply.text)).toEqual([OWNER_ONLY_REPLY]);
    expect([...f.privateKv.values]).toEqual(pairing);
    expect(f.spies.privateDelete).not.toHaveBeenCalled();
    expect(f.spies.privatePut).not.toHaveBeenCalled();
    expect(f.spies.securityPut).not.toHaveBeenCalled();
    expect(OWNER_ONLY_REPLY).not.toMatch(/PAIRED|已配對|未配對/);
  });

  it("answers identically whether or not an owner exists", async () => {
    const withOwner = await fixture(ALL);
    await withOwner.deliver(FRIEND_A, "通知狀態");
    await withOwner.deliver(FRIEND_A, "取消配對");
    const seen = withOwner.replies.map((reply) => reply.text);
    const noOwner = await fixture({ ...ALL, ownerPaired: false });
    await noOwner.deliver(FRIEND_A, "通知狀態");
    await noOwner.deliver(FRIEND_A, "取消配對");
    expect(seen).toHaveLength(2);
    expect(noOwner.replies.map((reply) => reply.text)).toEqual(seen);
  });

  it("stays silent and writes nothing for a pairing attempt while an owner is paired", async () => {
    const f = await fixture(ALL);
    await f.deliver(FRIEND_A, "配對 abcdefgh12");
    expect(f.replies).toHaveLength(0);
    expect(f.writes()).toBe(0);
    expect(f.gate?.calls).toHaveLength(0);
  });

  it("keeps the owner's own commands working and counts the owner's model call toward the cap", async () => {
    const f = await fixture(ALL);
    await f.deliver(OWNER_USER, "通知狀態");
    expect(f.replies[0]?.text).toContain("PAIRED（已配對）");
    const model = heldModel(f);
    const owner = await f.deliver(OWNER_USER, QUESTION, { wait: false });
    await vi.waitFor(() => expect(f.prompts).toHaveLength(1));
    const lane = f.gate?.values.get("lane") as { leases: Record<string, { o: boolean }> };
    expect(Object.values(lane.leases).map((lease) => lease.o)).toEqual([true]);
    model.release();
    await owner.settle();
    expect(f.gate?.calls.filter((call) => call.action === "release")).toHaveLength(1);
    expect(Object.keys((f.gate?.values.get("lane") as { leases: object }).leases)).toHaveLength(0);
    await f.deliver(OWNER_USER, "取消配對");
    expect(f.replies.at(-1)?.text).toContain("配對已取消");
    expect(f.privateKv.values.has("v21:owner-line:tenant")).toBe(false);
  });

  it("treats a failed owner lookup as a friend: neutral text, no unpair, no delete, no write", async () => {
    const f = await fixture(ALL);
    const original = f.privateKv.get.bind(f.privateKv);
    const reads = vi.spyOn(f.privateKv, "get").mockImplementation((async (key: string, type?: "text" | "json") => {
      if (key === "v21:owner-line:tenant") throw new Error("SYNTHETIC_KV_READ_FAILURE");
      return original(key, type);
    }) as never);
    const before = [...f.privateKv.values];
    await f.deliver(OWNER_USER, "取消配對");
    await f.deliver(OWNER_USER, "通知狀態");
    await f.deliver(OWNER_USER, "說明");
    await f.deliver(OWNER_USER, "刪除我的資料");
    await f.deliver(OWNER_USER, "開啟記憶");
    reads.mockRestore();
    expect(f.replies.map((reply) => reply.text).slice(0, 2)).toEqual([OWNER_ONLY_REPLY, OWNER_ONLY_REPLY]);
    expect(f.replies[2]?.text).not.toContain("通知狀態");
    expect(f.replies.slice(3).map((reply) => reply.text)).toEqual([FRIEND_SERVICE_BUSY_REPLY, FRIEND_SERVICE_BUSY_REPLY]);
    expect(f.spies.securityPut).not.toHaveBeenCalled();
    expect((await getOwnerPushTarget(f.env as never))?.lineUserId).toBe(OWNER_USER);
    expect(f.spies.privateDelete).not.toHaveBeenCalled();
    expect(f.spies.privatePut).not.toHaveBeenCalled();
    expect([...f.privateKv.values]).toEqual(before);
  });

  it("deletes only the friend's own data and never mentions pairing; the owner's pairing and data stay", async () => {
    const f = await fixture(ALL);
    const model = heldModel(f);
    const friend = await f.deliver(FRIEND_A, QUESTION, { wait: false });
    await vi.waitFor(() => expect(f.replies).toHaveLength(1)); // the parked-job notice
    model.release();
    await friend.settle();
    const ownerKeys = [...f.privateKv.values.keys()].filter((key) => !key.includes(":job:"));
    await f.deliver(FRIEND_A, "刪除我的資料");
    const text = f.replies.at(-1)?.text ?? "";
    expect(text).toMatch(/已刪除（[1-9]\d* 個項目）/);
    expect(text).not.toMatch(/配對|通知/);
    expect([...f.privateKv.values.keys()].filter((key) => !key.includes(":job:"))).toEqual(ownerKeys);
    expect((await getOwnerPushTarget(f.env as never))?.lineUserId).toBe(OWNER_USER);
    expect([...f.privateKv.values.keys()].some((key) => key.includes(":job:"))).toBe(false);
  });

  it("caps the KV-writing data commands per friend per Taipei day", async () => {
    const f = await fixture(ALL);
    for (let index = 0; index < 5; index += 1) await f.deliver(FRIEND_A, "刪除我的資料");
    expect(f.replies.every((reply) => reply.text.includes("已刪除"))).toBe(true);
    await f.deliver(FRIEND_A, "刪除我的資料");
    expect(f.replies.at(-1)?.text).toBe(FRIEND_KV_ACTION_LIMIT_REPLY);
    await f.deliver(FRIEND_B, "刪除我的資料");
    expect(f.replies.at(-1)?.text).toContain("已刪除");
  });
});

describe("all_friends: per-friend rate limits and the shared model lane", () => {
  it("limits public reads per friend per minute and recovers the next minute", async () => {
    const f = await fixture(ALL);
    for (let index = 0; index < 20; index += 1) await f.deliver(FRIEND_A, "說明");
    expect(f.replies).toHaveLength(20);
    await f.deliver(FRIEND_A, "說明");
    expect(f.replies.at(-1)?.text).toBe(FRIEND_RATE_REPLY);
    await f.deliver(FRIEND_B, "說明");
    expect(f.replies.at(-1)?.text).toContain(FRIEND_EDUCATION_SENTENCE);
    vi.setSystemTime(new Date("2026-10-12T04:01:40+08:00"));
    await f.deliver(FRIEND_A, "說明");
    expect(f.replies.at(-1)?.text).toContain(FRIEND_EDUCATION_SENTENCE);
    expect(f.writes()).toBe(0);
  });

  it("drops a webhook redelivery without a second reply or any KV write", async () => {
    const f = await fixture(ALL);
    await f.deliver(FRIEND_A, QUESTION, { eventId: "synthetic-redelivered" });
    await f.deliver(FRIEND_A, QUESTION, { eventId: "synthetic-redelivered" });
    expect(f.replies).toHaveLength(1);
    expect(f.prompts).toHaveLength(1);
    expect(f.writes()).toBe(0);
  });

  it("limits model questions to 3 a minute per friend and 30 a Taipei day, then resets at 00:00 +08:00", async () => {
    const f = await fixture(ALL);
    for (let index = 0; index < FRIEND_MODEL_PER_MINUTE; index += 1) await f.deliver(FRIEND_A, `${QUESTION} ${index}`);
    expect(f.prompts).toHaveLength(FRIEND_MODEL_PER_MINUTE);
    await f.deliver(FRIEND_A, `${QUESTION} extra`);
    expect(f.replies.at(-1)?.text).toBe(FRIEND_AI_MINUTE_LIMIT_REPLY);
    expect(f.prompts).toHaveLength(FRIEND_MODEL_PER_MINUTE);
    expect(FRIEND_AI_MINUTE_LIMIT_REPLY).toContain(String(FRIEND_MODEL_PER_MINUTE));

    for (let minute = 1; minute < FRIEND_MODEL_PER_DAY / FRIEND_MODEL_PER_MINUTE; minute += 1) {
      vi.setSystemTime(new Date(Date.UTC(2026, 9, 11, 20, 0, 30) + minute * 60_000)); // 04:00:30 +08:00 plus minutes
      for (let index = 0; index < FRIEND_MODEL_PER_MINUTE; index += 1) await f.deliver(FRIEND_A, `${QUESTION} ${minute}-${index}`);
    }
    expect(f.prompts).toHaveLength(FRIEND_MODEL_PER_DAY);
    vi.setSystemTime(new Date("2026-10-12T23:59:50+08:00"));
    await f.deliver(FRIEND_A, `${QUESTION} late`);
    expect(f.replies.at(-1)?.text).toBe(FRIEND_AI_DAY_LIMIT_REPLY);
    expect(FRIEND_AI_DAY_LIMIT_REPLY).toContain(String(FRIEND_MODEL_PER_DAY));
    // Another friend is unaffected.
    await f.deliver(FRIEND_B, `${QUESTION} other`);
    expect(f.replies.at(-1)?.text).toContain(MODEL_ANSWER);
    // 00:00 +08:00 is the day boundary the reply promised.
    vi.setSystemTime(new Date("2026-10-13T00:00:10+08:00"));
    await f.deliver(FRIEND_A, `${QUESTION} tomorrow`);
    expect(f.replies.at(-1)?.text).toContain(MODEL_ANSWER);
    expect(f.writes()).toBe(0);
  });

  it("answers busy, without calling the model, when the shared lane is full and the wait is over", async () => {
    const f = await fixture({ ...ALL, env: { V213_FRIEND_QA_ACQUIRE_WAIT_MS: "40" } });
    const model = heldModel(f);
    const first = await f.deliver(FRIEND_A, QUESTION, { wait: false });
    await vi.waitFor(() => expect(f.prompts).toHaveLength(1));
    const busy = await f.deliver(FRIEND_B, `${QUESTION} second`);
    expect(f.replyTo(busy.token)).toBe(FRIEND_AI_BUSY_REPLY);
    expect(f.prompts).toHaveLength(1);
    expect(FRIEND_AI_BUSY_REPLY).not.toMatch(/分鐘後/);
    model.release();
    await first.settle();
  });

  it("answers busy at once when no waiting place is configured", async () => {
    const f = await fixture({ ...ALL, env: { V213_FRIEND_QA_QUEUE_MAX: "0" } });
    const model = heldModel(f);
    const first = await f.deliver(FRIEND_A, QUESTION, { wait: false });
    await vi.waitFor(() => expect(f.prompts).toHaveLength(1));
    const busy = await f.deliver(FRIEND_B, `${QUESTION} second`);
    expect(f.replyTo(busy.token)).toBe(FRIEND_AI_BUSY_REPLY);
    model.release();
    await first.settle();
  });

  it("queues a second friend briefly and serves them once the first answer is done", async () => {
    const f = await fixture({ ...ALL, env: { V213_FRIEND_QA_ACQUIRE_WAIT_MS: "3000" } });
    const model = heldModel(f);
    const first = await f.deliver(FRIEND_A, QUESTION, { wait: false });
    await vi.waitFor(() => expect(f.prompts).toHaveLength(1));
    const second = await f.deliver(FRIEND_B, `${QUESTION} second`, { wait: false });
    await vi.waitFor(() => expect(acquireCalls(f)).toHaveLength(2));
    expect(f.prompts).toHaveLength(1);
    model.release();
    await first.settle();
    await second.settle();
    expect(f.prompts).toHaveLength(2);
    const answers = f.replies.filter((reply) => reply.text.includes(MODEL_ANSWER)).map((reply) => reply.token);
    expect(answers).toContain(second.token);
    expect(Object.keys((f.gate?.values.get("lane") as { leases: object }).leases)).toHaveLength(0);
  });

  it("lets one friend have one question in flight and one waiting, never more", async () => {
    const f = await fixture({ ...ALL, env: { V213_FRIEND_QA_ACQUIRE_WAIT_MS: "3000" } });
    const model = heldModel(f);
    const first = await f.deliver(FRIEND_A, `${QUESTION} 1`, { wait: false });
    await vi.waitFor(() => expect(f.prompts).toHaveLength(1));
    const second = await f.deliver(FRIEND_A, `${QUESTION} 2`, { wait: false });
    await vi.waitFor(() => expect(acquireCalls(f)).toHaveLength(2));
    const third = await f.deliver(FRIEND_A, `${QUESTION} 3`);
    expect(f.replyTo(third.token)).toBe(FRIEND_AI_OWN_BUSY_REPLY);
    model.release();
    await first.settle();
    await second.settle();
    expect(f.prompts).toHaveLength(2);
  });

  it("never lets friend saturation block the owner", async () => {
    const f = await fixture({ ...ALL, env: { V213_FRIEND_QA_QUEUE_MAX: "0" } });
    const model = heldModel(f);
    const first = await f.deliver(FRIEND_A, QUESTION, { wait: false });
    await vi.waitFor(() => expect(f.prompts).toHaveLength(1));
    const busy = await f.deliver(FRIEND_B, `${QUESTION} second`);
    expect(f.replyTo(busy.token)).toBe(FRIEND_AI_BUSY_REPLY);
    const owner = await f.deliver(OWNER_USER, `${QUESTION} owner`, { wait: false });
    await vi.waitFor(() => expect(f.prompts).toHaveLength(2));
    model.release();
    await first.settle();
    await owner.settle();
    expect(f.replyTo(owner.token)).toContain(MODEL_ANSWER);
  });

  it("refuses a portfolio or account question before any model slot is taken", async () => {
    const f = await fixture(ALL);
    await f.deliver(FRIEND_A, "我的投資組合績效如何");
    await f.deliver(FRIEND_A, "my brokerage account has what risk");
    expect(f.replies.map((reply) => reply.text)).toEqual([FRIEND_PORTFOLIO_REFUSAL, FRIEND_PORTFOLIO_REFUSAL]);
    expect(acquireCalls(f)).toHaveLength(0);
    expect(f.prompts).toHaveLength(0);
  });

  it("maps a gateway 429 / outage to the neutral busy text, never to a time promise", async () => {
    const f = await fixture(ALL);
    f.model.handler = async () => new Response("{}", { status: 429, headers: { "retry-after": "5" } });
    await f.deliver(FRIEND_A, QUESTION);
    expect(f.replies.at(-1)?.text).toBe(FRIEND_AI_BUSY_REPLY);
    expect(f.replies.at(-1)?.text).not.toMatch(/offline|離線|分鐘後/);
    expect(f.writes()).toBe(0);
  });
});

describe("all_friends: slow answers are parked per friend and bounded", () => {
  it("parks a slow answer in the friend's own tenant only, with two KV writes and no push", async () => {
    const f = await fixture(ALL);
    const model = heldModel(f);
    const slow = await f.deliver(FRIEND_A, QUESTION, { wait: false });
    await vi.waitFor(() => expect(f.replies).toHaveLength(1));
    const notice = f.replies[0]?.text ?? "";
    const ref = notice.match(/參考編號 ([A-Z0-9]{8})/)?.[1] ?? "";
    expect(ref).toHaveLength(8);
    expect(notice).toContain(`查看結果 ${ref}`);
    expect(notice).toContain("1 小時內有效");
    expect(notice).toMatch(/推播僅限擁有者/);
    model.release();
    await slow.settle();
    expect(f.spies.privatePut).toHaveBeenCalledTimes(2);
    expect(f.spies.securityPut).not.toHaveBeenCalled();

    await f.deliver(FRIEND_A, `查看結果 ${ref}`);
    expect(f.replies.at(-1)?.text).toContain(MODEL_ANSWER);
    await f.deliver(FRIEND_B, `查看結果 ${ref}`);
    expect(f.replies.at(-1)?.text).toContain("找不到該結果");
    expect(f.replies.at(-1)?.text).not.toContain(MODEL_ANSWER);
    await f.deliver(OWNER_USER, `查看結果 ${ref}`);
    expect(f.replies.at(-1)?.text).toContain("找不到該結果");
    expect(f.urls.some((url) => url.includes("/push"))).toBe(false);
  });

  it("stops parking jobs over the daily friend job-write cap and says so, with no KV write", async () => {
    const f = await fixture({ ...ALL, env: { V213_FRIEND_JOB_WRITES_PER_DAY: "2" } });
    const model = heldModel(f);
    const first = await f.deliver(FRIEND_A, QUESTION, { wait: false });
    await vi.waitFor(() => expect(f.replies).toHaveLength(1));
    model.release();
    await first.settle();
    expect(f.spies.privatePut).toHaveBeenCalledTimes(2);

    model.hold();
    const second = await f.deliver(FRIEND_B, `${QUESTION} second`, { wait: false });
    await vi.waitFor(() => expect(f.replies).toHaveLength(2));
    expect(f.replies[1]?.text).toBe(FRIEND_AI_BUSY_REPLY);
    model.release();
    await second.settle();
    expect(f.spies.privatePut).toHaveBeenCalledTimes(2);
    expect(Object.keys((f.gate?.values.get("lane") as { leases: object }).leases)).toHaveLength(0);
  });
});

describe("all_friends: the gate fails closed", () => {
  it.each([
    ["unbound", { gate: false as const }],
    ["throwing", { gate: { failure: "throw" as const } }],
    ["malformed", { gate: { failure: "malformed" as const } }],
  ])("a %s gate gives friends the honest busy text, no model call and no KV write; the owner still works", async (_name, extra) => {
    const f = await fixture({ ...ALL, ...extra });
    await f.deliver(FRIEND_A, "說明");
    await f.deliver(FRIEND_A, QUESTION);
    await f.deliver(FRIEND_A, null, { type: "follow" });
    expect(f.replies.map((reply) => reply.text)).toEqual([FRIEND_SERVICE_BUSY_REPLY, FRIEND_SERVICE_BUSY_REPLY, FRIEND_SERVICE_BUSY_REPLY]);
    expect(f.prompts).toHaveLength(0);
    expect(f.writes()).toBe(0);
    await f.deliver(OWNER_USER, QUESTION);
    expect(f.replies.at(-1)?.text).toContain(MODEL_ANSWER);
    expect(f.prompts).toHaveLength(1);
  });
});

describe("all_friends: a bound gate that never answers", () => {
  it("gives friends the honest busy text after a bounded wait and never blocks the owner", async () => {
    const f = await fixture({ ...ALL, gate: { failure: "hang" }, env: { V213_FRIEND_QA_ACQUIRE_WAIT_MS: "0" } });
    const [friend, owner] = await Promise.all([f.deliver(FRIEND_A, "說明"), f.deliver(OWNER_USER, QUESTION)]);
    expect(f.replyTo(friend.token)).toBe(FRIEND_SERVICE_BUSY_REPLY);
    expect(f.replyTo(owner.token)).toContain(MODEL_ANSWER);
    expect(f.prompts).toHaveLength(1);
  }, 15_000);
});

describe("all_friends: the gate stores no personal data", () => {
  it("holds only hashes, counters, expiries and leases", async () => {
    const f = await fixture(ALL);
    await f.deliver(FRIEND_A, QUESTION);
    await f.deliver(FRIEND_B, "刪除我的資料");
    await f.deliver(FRIEND_B, "取消配對");
    await f.deliver(OWNER_USER, QUESTION);
    await f.deliver(FRIEND_C, null, { type: "follow" });
    const dump = JSON.stringify([[...(f.gate?.values ?? [])], f.gate?.calls]);
    const forbidden = [FRIEND_A, FRIEND_B, FRIEND_C, OWNER_USER, QUESTION, "取消配對", "synthetic-reply-token", "synthetic-event-"];
    for (const user of [FRIEND_A, FRIEND_B, FRIEND_C, OWNER_USER]) forbidden.push(await f.tenantOf(user));
    for (const item of forbidden) expect(dump).not.toContain(item);
    expect(dump).not.toMatch(/replyToken|userId|webhookEventId|"text"/);
  });
});
