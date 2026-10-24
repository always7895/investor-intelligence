import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { assertLineMessages, type LineOutboundMessage } from "../src/line-messages";
import { processAuthorizedLineEvent } from "../src/v211/worker";
import { freeRelayRequestEnv } from "../src/v213/production-worker";
import { pinPublicSnapshot } from "../src/v213/public-snapshot";
import * as macroReaders from "../src/v213/macro-freshness";
import * as reportReaders from "../src/v213/top20-report";
import { memoryFriendGate } from "./line-all-friends-fixture";
import { macroDocument, macroEnv, MACRO_NOW, MACRO_STAMP } from "./macro-freshness-fixture";

const COMMANDS = [
  ["宏觀產業分析", "合成產業 alpha"], ["TOP5產業總覽", "合成產業 alpha"],
  ["宏觀產業 卡片 gamma", "合成產業 gamma"], ["宏觀產業 深度化分析 beta", "合成瓶頸"],
  ["潛力榜", "Synthetic SYNA Corp."], ["潛力報告 SYNA", "合成報告數據"], ["訂單實現榜", "110%"],
] as const;
const FACTS = /合成產業|合成瓶頸|合成報告數據|Synthetic SYNA Corp\.|110%/;
type Viewer = "owner" | "friend";
type Fixture = Awaited<ReturnType<typeof macroEnv>>;

async function reply(fixture: Fixture, viewer: Viewer, command: string): Promise<string> {
  const gate = memoryFriendGate();
  let messages: LineOutboundMessage[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
    expect(url).toBe("https://api.line.me/v2/bot/message/reply");
    messages = JSON.parse(String(init.body)).messages;
    return new Response("{}", { status: 200 });
  }));
  const env = await freeRelayRequestEnv({ ...fixture.env, V213_FRIEND_QA_GATE: gate.namespace });
  await processAuthorizedLineEvent(env, { waitUntil() { throw new Error("MODEL_JOB_FORBIDDEN"); } } as unknown as ExecutionContext,
    { type: "message", replyToken: "SYNTHETIC_REPLY", webhookEventId: crypto.randomUUID(), timestamp: Date.now(),
      message: { id: "SYNTHETIC_MESSAGE", type: "text", text: command } }, "SYNTHETIC_TENANT",
    viewer === "friend" ? { mode: "all_friends", ownerState: "not_owner" } : undefined);
  assertLineMessages(messages);
  expect(gate.calls.every(call => call.action === "admit")).toBe(true);
  expect(gate.calls).toHaveLength(viewer === "friend" ? 1 : 0);
  return JSON.stringify(messages);
}

async function everyEntry(viewer: Viewer, make: () => Promise<Fixture>, admitted: boolean) {
  for (const [command, marker] of COMMANDS) {
    for (const suffix of ["", " 文字"]) {
      const result = await reply(await make(), viewer, command + suffix);
      if (admitted) expect(result, command + suffix).toContain(marker);
      else {
        expect(result, command + suffix).not.toMatch(FACTS);
        if (command === "TOP5產業總覽") expect(result).toContain("不假設為 0");
      }
    }
  }
}

beforeEach(() => { vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(new Date(MACRO_NOW)); });
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe.each<Viewer>(["owner", "friend"])("macro freshness through the %s LINE caller", viewer => {
  it("renders all seven fresh sealed entries in Flex and text, keeping old fiscal dates", async () => {
    await everyEntry(viewer, () => macroEnv(), true);
    const orders = await reply(await macroEnv(), viewer, "潛力榜");
    expect(orders).toContain("2026-06-30");
    expect(orders).toContain("2026-07-29");
  });

  it("rejects old seals even when their digest-bound facts and carrier are otherwise valid", async () => {
    vi.setSystemTime(new Date("2026-09-25T14:00:01Z"));
    await everyEntry(viewer, () => macroEnv(macroDocument("2026-09-25T12:04:00Z")), false);
  });

  it("admits the exact configured seal and carrier liveness boundary", async () => {
    vi.setSystemTime(new Date("2026-09-25T14:00:00Z"));
    await everyEntry(viewer, () => macroEnv(), true);
  });

  it("rejects an old carrier inside a fresh seal", async () => {
    vi.setSystemTime(new Date("2026-09-25T14:00:01Z"));
    await everyEntry(viewer, () => macroEnv(macroDocument(), "2026-09-25T14:00:00Z"), false);
  });

  it("rejects a freshly generated and resealed carrier with a 46-day-old rotation basis", async () => {
    const stamp = "2026-11-10T12:00:00Z";
    vi.setSystemTime(new Date("2026-11-10T12:30:00Z"));
    await everyEntry(viewer, () => macroEnv(macroDocument(stamp), stamp), false);
  });

  it("admits the full 45th Taipei calendar day, even when UTC elapsed age exceeds 45 days", async () => {
    const stamp = "2026-11-09T15:00:00Z";
    vi.setSystemTime(new Date("2026-11-09T15:59:59Z"));
    await everyEntry(viewer, () => macroEnv(macroDocument(stamp), stamp), true);
  });

  it.each([
    ["missing basis", (doc: any) => { delete doc.data_basis; }],
    ["missing basis date", (doc: any) => { delete doc.data_basis.as_of; }],
    ["malformed basis", (doc: any) => { doc.data_basis.as_of = "2026-02-30"; }],
    ["future basis", (doc: any) => { doc.data_basis.as_of = doc.potential_ranking.as_of = "2026-09-26"; }],
    ["conflicting basis", (doc: any) => { doc.potential_ranking.as_of = "2026-09-24"; }],
    ["missing ranking date", (doc: any) => { delete doc.potential_ranking.as_of; }],
    ["malformed ranking date", (doc: any) => { doc.potential_ranking.as_of = "2026-09-31"; }],
    ["missing carrier time", (doc: any) => { delete doc.generated_at; }],
    ["date-only carrier", (doc: any) => { doc.generated_at = "2026-09-25"; }],
    ["normalized impossible carrier", (doc: any) => { doc.generated_at = "2026-02-30T12:00:00Z"; }],
    ["future carrier", (doc: any) => { doc.generated_at = "2026-09-25T12:40:00Z"; }],
    ["carrier later than seal", (doc: any) => { doc.generated_at = "2026-09-25T12:06:00Z"; }],
  ] as const)("fails closed on %s without exposing old facts", async (_label, mutate) => {
    const doc = macroDocument(); mutate(doc);
    await everyEntry(viewer, () => macroEnv(doc), false);
  });

  it("rejects a basis later than carrier creation even if it is not later than today", async () => {
    const stamp = "2026-09-25T15:30:00Z";
    vi.setSystemTime(new Date("2026-09-25T16:10:00Z"));
    await everyEntry(viewer, () => macroEnv(macroDocument(stamp, "2026-09-26"), "2026-09-25T16:00:00Z"), false);
  });

  it("measures seal freshness after an awaited read crosses its exact liveness boundary", async () => {
    await everyEntry(viewer, async () => {
      vi.setSystemTime(new Date("2026-09-25T13:59:59Z"));
      return macroEnv(macroDocument(), MACRO_STAMP, () => vi.setSystemTime(new Date("2026-09-25T14:00:01Z")));
    }, false);
  });

  it("measures basis age after an awaited read crosses Taipei midnight into day 46", async () => {
    const stamp = "2026-11-09T15:30:00Z";
    await everyEntry(viewer, async () => {
      vi.setSystemTime(new Date("2026-11-09T15:59:59Z"));
      return macroEnv(macroDocument(stamp), stamp, () => vi.setSystemTime(new Date("2026-11-09T16:00:01Z")));
    }, false);
  });

  it.each([
    ["seal", MACRO_STAMP, "2026-09-25T13:59:59Z", "2026-09-25T14:00:01Z"],
    ["basis", "2026-11-09T15:30:00Z", "2026-11-09T15:59:59Z", "2026-11-09T16:00:01Z"],
  ])("rechecks partial macro counts and phase metadata after the Top20 fallback crosses the %s boundary", async (_kind, stamp, before, after) => {
    const readReport = reportReaders.loadV213FreshTop20Report;
    vi.spyOn(reportReaders, "loadV213FreshTop20Report").mockImplementation(async (...args) => {
      await Promise.resolve();
      vi.setSystemTime(new Date(after));
      return readReport(...args);
    });
    const doc: any = macroDocument(stamp);
    Object.assign(doc, { qualified_count: 3, shortfall: 2, status: "SHORTFALL_NOT_QUALIFIED",
      industries: doc.industries.slice(0, 3), potential_ranking: null, phase_knowledge_withheld: { affected_industries: 2, signals: 3 } });
    for (const suffix of ["", " 文字"]) {
      vi.setSystemTime(new Date(before));
      const result = await reply(await macroEnv(doc, stamp), viewer, "宏觀產業分析" + suffix);
      expect(result).toContain("不假設為 0");
      expect(result).not.toContain("僅 3 個合格產業");
      expect(result).not.toContain("至少 2 個產業");
    }
  });

  it("requires digest integrity and never rescues an invalid sealed carrier from direct keys", async () => {
    const make = async () => {
      const f = await macroEnv();
      f.kv.values.set("snapshot:20260925T120000Z-0123456789ab:v213:macro-industry:latest", JSON.stringify(macroDocument("2026-09-25T12:01:00Z")));
      f.kv.values.set("v213:macro-industry:latest", JSON.stringify(macroDocument()));
      expect((await pinPublicSnapshot(f.env)).integrity).toBe("invalid");
      return f;
    };
    await everyEntry(viewer, make, false);
  });

  it("preserves an honest sealed empty shortfall with no rotation basis", async () => {
    const doc: any = macroDocument();
    Object.assign(doc, { qualified_count: 0, shortfall: 5, status: "SHORTFALL_NOT_QUALIFIED", industries: [], deep_analyses: {},
      data_basis: null, potential_ranking: null });
    const result = await reply(await macroEnv(doc), viewer, "TOP5產業總覽 文字");
    expect(result).toContain("當輪合格產業候選僅 0 個");
    expect(result).not.toMatch(FACTS);
  });

  it("does not treat non-admitted industry facts as an empty no-basis shortfall", async () => {
    const doc: any = macroDocument();
    Object.assign(doc, { qualified_count: 0, shortfall: 5, status: "SHORTFALL_NOT_QUALIFIED", deep_analyses: {},
      data_basis: null, potential_ranking: null });
    for (const card of doc.industries) { card.rank = null; card.growth = null; }
    const result = await reply(await macroEnv(doc), viewer, "宏觀產業 卡片 gamma 文字");
    expect(result).toContain("MACRO_CARD_UNAVAILABLE");
    expect(result).not.toMatch(FACTS);
  });

  it.each(["2026-09-17", "2026-09-26", "2026-02-30", undefined])("rejects a stale or invalid company calculation date %s", async day => {
    const doc: any = macroDocument(); doc.potential_ranking.reports.SYNA.as_of = day;
    for (const suffix of ["", " 文字"]) {
      const result = await reply(await macroEnv(doc), viewer, "潛力報告 SYNA" + suffix);
      expect(result).toContain("尚未產生或未通過驗證");
      expect(result).not.toContain("合成報告數據");
      const ranking = await reply(await macroEnv(doc), viewer, "潛力榜" + suffix);
      expect(ranking).toContain("SYNA");
      expect(ranking).toContain("訂單計算資料已過期或無法驗證");
      expect(ranking).not.toMatch(/110%|2026-06-30|2026-07-29/);
      const orders = await reply(await macroEnv(doc), viewer, "訂單實現榜" + suffix);
      expect(orders).toContain("訂單計算資料已過期或無法驗證");
      expect(orders).not.toContain("未揭露");
      expect(orders).not.toContain("110%");
    }
  });

  it("withholds orders when the company report is absent or structurally invalid", async () => {
    for (const report of [undefined, { ...macroDocument().potential_ranking.reports.SYNA, sections: [] }]) {
      const doc: any = macroDocument(); doc.potential_ranking.reports.SYNA = report;
      const result = await reply(await macroEnv(doc), viewer, "訂單實現榜 文字");
      expect(result).toContain("訂單計算資料已過期或無法驗證");
      expect(result).not.toContain("110%");
    }
  });

  it("keeps fresh companies in a mixed order ranking while withholding stale report calculations", async () => {
    const doc: any = macroDocument();
    doc.potential_ranking.reports.SYNA.as_of = "2026-09-17";
    doc.potential_ranking.reports.SYNB = { ...doc.potential_ranking.reports.SYNA, ticker: "SYNB", as_of: "2026-09-25" };
    doc.potential_ranking.records.push({ ...doc.potential_ranking.records[0], rank: 2, ticker: "SYNB", name: "Synthetic SYNB Corp.",
      orders: { ...doc.potential_ranking.records[0].orders, coverage_pct: { m6: 220, m12: 220, m24: 220 } } });
    for (const suffix of ["", " 文字"]) {
      const result = await reply(await macroEnv(doc), viewer, "訂單實現榜" + suffix);
      expect(result).toContain("SYNB");
      expect(result).toContain("220%");
      expect(result).toContain("訂單計算資料已過期或無法驗證");
      expect(result).not.toContain("SYNA");
      expect(result).not.toContain("110%");
    }
  });

  it("crossing the eighth Taipei day withholds company calculations while keeping the valid rotation ranking", async () => {
    const stamp = "2026-10-02T15:30:00Z";
    const doc = macroDocument(stamp); doc.potential_ranking.reports.SYNA.as_of = "2026-09-25";
    for (const suffix of ["", " 文字"]) {
      vi.setSystemTime(new Date("2026-10-02T15:59:59Z"));
      const result = await reply(await macroEnv(doc, stamp, () => vi.setSystemTime(new Date("2026-10-02T16:00:01Z"))), viewer, "潛力榜" + suffix);
      expect(result).toContain("SYNA");
      expect(result).toContain("訂單計算資料已過期或無法驗證");
      expect(result).not.toContain("110%");
    }
  });

  it("admits the company report on its seventh Taipei calendar day", async () => {
    const doc = macroDocument(); doc.potential_ranking.reports.SYNA.as_of = "2026-09-18";
    expect(await reply(await macroEnv(doc), viewer, "潛力報告 SYNA 文字")).toContain("合成報告數據");
    expect(await reply(await macroEnv(doc), viewer, "訂單實現榜 文字")).toContain("110%");
  });
  it.each([
    ["exact boundary Flex", "2026-09-25T12:30:00.000Z", true, ""],
    ["exact boundary text", "2026-09-25T12:30:00.000Z", true, " 文字"],
    ["expired during final macro read Flex", "2026-09-25T12:30:00.001Z", false, ""],
    ["expired during final macro read text", "2026-09-25T12:30:00.001Z", false, " 文字"],
  ] as const)("uses the final company-evidence clock at %s", async (_label, after, admitted, suffix) => {
    const readMacro = macroReaders.loadFreshMacroDocument;
    let macroReads = 0;
    vi.spyOn(macroReaders, "loadFreshMacroDocument").mockImplementation(async (...args) => {
      if (++macroReads === 2) { await Promise.resolve(); vi.setSystemTime(new Date(after)); }
      return readMacro(...args);
    });
    const record = { ticker: "SYNTHETIC_FALLBACK", industry: "SYNTHETIC_FALLBACK_INDUSTRY",
      orders_state_as_of: "2026-09-18T12:30:00Z", retrieved_at: "2026-09-25T12:00:00Z", evidence_class: "market_observation" };
    const report = { generated_at: MACRO_STAMP, records: [record] };
    vi.spyOn(reportReaders, "loadV213FreshTop20Report").mockResolvedValue(report as any);
    const observations = [{ freshAsOf: record.orders_state_as_of, retrievedAt: record.retrieved_at,
      evidenceClass: record.evidence_class, sealTime: report.generated_at }];
    const doc: any = macroDocument();
    Object.assign(doc, { qualified_count: 3, shortfall: 2, status: "SHORTFALL_NOT_QUALIFIED",
      industries: doc.industries.slice(0, 3), potential_ranking: null });
    {
      macroReads = 0;
      vi.setSystemTime(new Date("2026-09-25T12:29:59.999Z"));
      expect(await reportReaders.v213EvidenceWithinWindow(observations)).toBe(true);
      const result = await reply(await macroEnv(doc), viewer, "宏觀產業分析" + suffix);
      expect(macroReads).toBe(2);
      expect(await reportReaders.v213EvidenceWithinWindow(observations)).toBe(admitted);
      if (admitted) {
        expect(result).toContain(record.industry);
        expect(result).not.toContain(reportReaders.V213_STALE_RECORDS_MESSAGE);
      } else {
        expect(result).not.toContain(record.industry);
        expect(result).toContain(reportReaders.V213_STALE_RECORDS_MESSAGE);
      }
    }
  });

});
