import { describe, expect, it, vi } from "vitest";
import { parseQuery } from "../src/core";
import { generalAnswer } from "../src/qa";
import { deriveTenantId } from "../src/security";
import { storeOwnerPairing } from "../src/v21/owner-storage";
import {
  FRIEND_AI_BUSY_REPLY,
  FRIEND_PORTFOLIO_REFUSAL,
  OWNER_ONLY_REPLY,
  classifyLineRequest,
  decideLineAccess,
  friendJobReply,
  friendPortfolioDisclosure,
  friendPreModelRefusal,
  lineAccessMode,
  resolveOwnerState,
  type LineAccessMode,
  type LineRequestClass,
  type OwnerState,
} from "../src/v211/line-access";
import { processAuthorizedLineEvent, type V211Env } from "../src/v211/worker";
import type { LineEvent } from "../src/line";
import { asKv, MemoryKv } from "./fake-kv";

describe("lineAccessMode: only the exact value all_friends opens anything", () => {
  it.each([
    ["all_friends", "all_friends"],
    ["owner_only", "owner_only"],
    [undefined, "owner_only"],
    ["", "owner_only"],
    ["ALL_FRIENDS", "owner_only"],
    ["All_Friends", "owner_only"],
    [" all_friends", "owner_only"],
    ["all_friends\n", "owner_only"],
    ["all-friends", "owner_only"],
    ["allowlist", "owner_only"],
    ["disabled", "owner_only"],
    ["true", "owner_only"],
    [1, "owner_only"],
    [null, "owner_only"],
    [{}, "owner_only"],
  ])("%j -> %s", (value, expected) => {
    expect(lineAccessMode({ V213_LINE_ACCESS_MODE: value })).toBe(expected);
  });
  it("is owner_only when the variable is absent", () => {
    expect(lineAccessMode({})).toBe("owner_only");
  });
});

describe("classifyLineRequest: an ordered table where unknown text never reaches an owner-only handler", () => {
  const table: Array<[string, string, string | null, LineRequestClass]> = [
    ["follow", "follow", null, { scope: "ALL_FRIENDS", kind: "follow" }],
    ["unpair zh-TW", "message", "取消配對", { scope: "OWNER_ONLY", kind: "unpair" }],
    ["unpair zh-CN", "message", "取消配对", { scope: "OWNER_ONLY", kind: "unpair" }],
    ["unpair en", "message", "unpair", { scope: "OWNER_ONLY", kind: "unpair" }],
    ["unpair full-width", "message", "　ＵＮＰＡＩＲ ", { scope: "OWNER_ONLY", kind: "unpair" }],
    ["status zh-TW", "message", "通知狀態", { scope: "OWNER_ONLY", kind: "notification_status" }],
    ["status zh-CN", "message", "通知状态", { scope: "OWNER_ONLY", kind: "notification_status" }],
    ["status en", "message", "Notification Status", { scope: "OWNER_ONLY", kind: "notification_status" }],
    ["pairing", "message", "配對 abcdefgh12", { scope: "OWNER_ONLY", kind: "pairing" }],
    ["pairing en postback", "postback", "pair abcdefgh12", { scope: "OWNER_ONLY", kind: "pairing" }],
    ["delete data", "message", "刪除我的資料", { scope: "PER_FRIEND_OWN_DATA", kind: "delete_data" }],
    ["job result", "message", "查看結果 ABCD2345", { scope: "PER_FRIEND_OWN_DATA", kind: "job_result" }],
    ["memory status", "message", "記憶狀態", { scope: "PER_FRIEND_OWN_DATA", kind: "memory" }],
    ["memory enable", "message", "開啟記憶", { scope: "PER_FRIEND_OWN_DATA", kind: "memory" }],
    ["memory clear", "message", "清除本次對話", { scope: "PER_FRIEND_OWN_DATA", kind: "memory" }],
    ["open question", "message", "景氣循環如何影響企業融資？", { scope: "PER_FRIEND_OWN_DATA", kind: "general_qa" }],
    ["portfolio words", "message", "持倉", { scope: "ALL_FRIENDS", kind: "portfolio_refusal" }],
    ["top 20", "message", "TOP20", { scope: "ALL_FRIENDS", kind: "public_read" }],
    ["help", "message", "說明", { scope: "ALL_FRIENDS", kind: "public_read" }],
    ["option arithmetic", "message", "期權試算說明", { scope: "ALL_FRIENDS", kind: "manual_option" }],
    ["non-text message", "message", null, { scope: "ALL_FRIENDS", kind: "public_read" }],
    ["sentence containing unpair", "message", "請告訴我怎麼取消配對", { scope: "PER_FRIEND_OWN_DATA", kind: "general_qa" }],
    ["unpair with extra word", "message", "unpair please", { scope: "PER_FRIEND_OWN_DATA", kind: "general_qa" }],
    ["status with extra word", "message", "通知狀態 如何", { scope: "PER_FRIEND_OWN_DATA", kind: "general_qa" }],
    ["pairing words without a code", "message", "配對失敗怎麼辦", { scope: "PER_FRIEND_OWN_DATA", kind: "general_qa" }],
  ];
  it.each(table)("%s", (_name, type, text, expected) => {
    expect(classifyLineRequest(type, text)).toEqual(expected);
  });
  it("classifies only the three explicit patterns as owner-only, over a sweep of every intent", () => {
    for (const text of ["Top 20", "NVDA 評分", "最新報告", "最新期權", "系統狀態", "serenity", "我持有 NVDA", "SIVE", "2330", "hello", "查看結果 ABCD2345"]) {
      expect(classifyLineRequest("message", text).scope).not.toBe("OWNER_ONLY");
    }
  });
});

describe("decideLineAccess: mode x owner state x scope", () => {
  const cls = (scope: LineRequestClass["scope"], kind: LineRequestClass["kind"]): LineRequestClass => ({ scope, kind });
  const publicRead = cls("ALL_FRIENDS", "public_read");
  const ownData = cls("PER_FRIEND_OWN_DATA", "general_qa");
  const unpair = cls("OWNER_ONLY", "unpair");
  const status = cls("OWNER_ONLY", "notification_status");
  const pairing = cls("OWNER_ONLY", "pairing");

  const cases: Array<[LineAccessMode, OwnerState, LineRequestClass, string]> = [
    // owner_only: today's gate (owner, plus the pairing bypass); everyone else silent.
    ["owner_only", "owner", publicRead, "allow"],
    ["owner_only", "owner", unpair, "allow"],
    ["owner_only", "owner", pairing, "allow"],
    ["owner_only", "not_owner", publicRead, "deny_silent"],
    ["owner_only", "not_owner", ownData, "deny_silent"],
    ["owner_only", "not_owner", unpair, "deny_silent"],
    ["owner_only", "not_owner", status, "deny_silent"],
    ["owner_only", "not_owner", pairing, "allow"],
    ["owner_only", "lookup_failed", publicRead, "deny_silent"],
    ["owner_only", "lookup_failed", pairing, "deny_silent"],
    // all_friends
    ["all_friends", "owner", publicRead, "allow"],
    ["all_friends", "owner", unpair, "allow"],
    ["all_friends", "owner", status, "allow"],
    ["all_friends", "not_owner", publicRead, "allow"],
    ["all_friends", "not_owner", ownData, "allow"],
    ["all_friends", "not_owner", cls("ALL_FRIENDS", "follow"), "allow"],
    ["all_friends", "not_owner", unpair, "owner_only_reply"],
    ["all_friends", "not_owner", status, "owner_only_reply"],
    ["all_friends", "not_owner", pairing, "allow"],
    ["all_friends", "lookup_failed", publicRead, "allow"],
    ["all_friends", "lookup_failed", ownData, "allow"],
    ["all_friends", "lookup_failed", unpair, "owner_only_reply"],
    ["all_friends", "lookup_failed", status, "owner_only_reply"],
    ["all_friends", "lookup_failed", pairing, "deny_silent"],
  ];
  it.each(cases)("%s / %s / %j -> %s", (mode, ownerState, request, expected) => {
    expect(decideLineAccess(mode, ownerState, "user", request)).toBe(expected);
  });
  it.each(["group", "room", "", "bot"])("rejects source type %j before anything else, in every mode and state", (source) => {
    for (const mode of ["owner_only", "all_friends"] as const) {
      for (const ownerState of ["owner", "not_owner", "lookup_failed"] as const) {
        for (const request of [publicRead, ownData, unpair, pairing]) {
          expect(decideLineAccess(mode, ownerState, source, request)).toBe("deny_silent");
        }
      }
    }
  });
  it("makes lookup_failed never the owner", () => {
    for (const mode of ["owner_only", "all_friends"] as const) {
      for (const request of [publicRead, ownData, unpair, status, pairing]) {
        expect(["allow", "owner_only_reply", "deny_silent"]).toContain(decideLineAccess(mode, "lookup_failed", "user", request));
      }
    }
    expect(decideLineAccess("all_friends", "lookup_failed", "user", unpair)).not.toBe("allow");
    expect(decideLineAccess("all_friends", "lookup_failed", "user", status)).not.toBe("allow");
  });
});

describe("resolveOwnerState: a thrown lookup is lookup_failed and writes nothing", () => {
  async function owned() {
    const privateKv = new MemoryKv();
    const env = {
      PUBLIC_CACHE: asKv(new MemoryKv()),
      TENANT_PRIVATE_CACHE: asKv(privateKv),
      EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()),
      TENANT_HASH_SECRET: "SYNTHETIC_ACCESS_TENANT_NOT_REAL",
      TENANT_DATA_ENCRYPTION_KEY: "SYNTHETIC_ACCESS_DATA_NOT_REAL",
    };
    const owner = String.fromCharCode(85) + "1".repeat(32);
    const friend = String.fromCharCode(85) + "a".repeat(32);
    const ownerTenant = await deriveTenantId({ type: "user", userId: owner }, env.TENANT_HASH_SECRET);
    const friendTenant = await deriveTenantId({ type: "user", userId: friend }, env.TENANT_HASH_SECRET);
    await storeOwnerPairing(env as never, ownerTenant, owner);
    return { env, privateKv, ownerTenant, friendTenant };
  }
  it("returns owner, not_owner, and lookup_failed", async () => {
    const { env, privateKv, ownerTenant, friendTenant } = await owned();
    expect(await resolveOwnerState(env as never, ownerTenant)).toBe("owner");
    expect(await resolveOwnerState(env as never, friendTenant)).toBe("not_owner");
    const put = vi.spyOn(privateKv, "put");
    const remove = vi.spyOn(privateKv, "delete");
    vi.spyOn(privateKv, "get").mockRejectedValue(new Error("SYNTHETIC_KV_FAILURE"));
    expect(await resolveOwnerState(env as never, ownerTenant)).toBe("lookup_failed");
    expect(await resolveOwnerState(env as never, friendTenant)).toBe("lookup_failed");
    expect(put).not.toHaveBeenCalled();
    expect(remove).not.toHaveBeenCalled();
  });
});

describe("friend pre-model refusal mirrors the certified first-person disclosure screen", () => {
  const disclosures = [
    "我的投資組合績效如何",
    "我持有 100 股 NVDA",
    "我的持倉要不要加碼",
    "我買了一些台積電",
    "my portfolio is down",
    "I own 100 shares of NVDA",
    "i have 50 shares",
    "my brokerage account has margin",
    "what is my cost basis",
  ];
  it.each(disclosures)("refuses %j before a model slot and agrees with generalAnswer", async (text) => {
    expect(friendPortfolioDisclosure(text)).toBe(true);
    expect(friendPreModelRefusal(text, undefined)).toBe(FRIEND_PORTFOLIO_REFUSAL);
    const answer = await generalAnswer({ GENERAL_QA_ENABLED: "true" } as never, parseQuery(text), { tenantId: "t", chatType: "user" });
    expect(answer).toBe("SENSITIVE_PERSONAL_FINANCIAL_INPUT_NOT_ACCEPTED");
  });
  it.each(["景氣循環如何影響企業融資？", "what is a covered call", "解釋什麼是自由現金流", "How do options work"])("lets %j through", (text) => {
    expect(friendPortfolioDisclosure(text)).toBe(false);
    expect(friendPreModelRefusal(text, undefined)).toBeNull();
  });
  it("applies the same length limit rule as generalAnswer", () => {
    expect(friendPreModelRefusal("字".repeat(3000), undefined)).toBeNull();
    expect(friendPreModelRefusal("字".repeat(3001), undefined)).toBe("問題過長（上限 3000 字）。");
    expect(friendPreModelRefusal("字".repeat(250), "200")).toBe("問題過長（上限 200 字）。");
    expect(friendPreModelRefusal("字".repeat(250), "50")).toBe("問題過長（上限 200 字）。");
  });
});

describe("reviewed zh-TW texts", () => {
  it("pins the texts the operator will see", () => {
    expect(FRIEND_AI_BUSY_REPLY).toBe(
      "目前 AI 問答暫時無法處理，這則問題沒有被處理，請稍後再試。Top 20、瓶頸榜、期權等公開查詢不受影響。",
    );
    expect(FRIEND_PORTFOLIO_REFUSAL).toBe("本服務只處理公開資料，不接受也不提供個人持倉、帳戶或券商資料。請改問公開的產業、個股或期權觀察。");
  });
  it("tells a friend that only their own chat can read a parked answer, and that push is owner-only", () => {
    const text = friendJobReply("ABCD2345");
    expect(text).toContain("查看結果 ABCD2345");
    expect(text).toContain("1 小時內有效");
    expect(text).toContain("推播僅限擁有者");
    expect(text).toContain("只有你自己的聊天室");
  });
  it("keeps the owner-only reply neutral about pairing", () => {
    expect(OWNER_ONLY_REPLY).not.toMatch(/PAIRED|已配對|未配對|擁有者是誰|尚未/);
    expect(OWNER_ONLY_REPLY).toContain("僅限服務擁有者");
  });
});

describe("processAuthorizedLineEvent keeps its exported signature", () => {
  it("accepts the four-argument legacy call (the access context is optional and defaults to the owner path)", () => {
    // Compile-time pin for cloud/src/v21/worker.ts, cloud/src/worker.ts and the callers in cloud/test.
    const legacy: (env: V211Env, ctx: ExecutionContext, event: LineEvent, tenantId: string) => Promise<void> =
      processAuthorizedLineEvent;
    expect(typeof legacy).toBe("function");
    expect(processAuthorizedLineEvent.length).toBe(5);
  });
});
