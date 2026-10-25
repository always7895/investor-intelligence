import { readFileSync } from "node:fs";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { assertLineMessages } from "../src/line-messages";
import { parseQuery } from "../src/core";
import { processAuthorizedLineEvent } from "../src/v211/worker";
import { BOTTLENECK_V3_KEY, buildBottleneckDetail, buildBottleneckTop20Messages, parseBottleneckV3 } from "../src/v213/bottleneck-v3";
import { CONSENSUS_PRICE_LABEL, forecastCard, forecastLines, forecastText, parseOrderForecastV3, type OrderForecast } from "../src/v213/order-forecast";
import { freeRelayRequestEnv } from "../src/v213/production-worker";
import { v213PublicLineAnswer } from "../src/v213/rich-menu";
import { SNAPSHOT_SEAL_KEY } from "../src/v213/snapshot-seal";
import { doc, HOUR } from "./bottleneck-v3-fixture";
import { asKv, MemoryKv } from "./fake-kv";
import { sealUnboundReport } from "./sealed-report-migration";
import officialRevenueFixture from "../../tests/fixtures/v213-official-quarterly-revenue.json";

// Operator 2026-10-14 (R/OPERATOR-DECISION-CONSENSUS-BRIDGE-AND-NAME-MATCH-20261014.txt): like the company-guidance route, an
// ended first consensus quarter keeps the projection for 70 days with a warning and the unofficial label, but only beside a
// capture taken after that end. The sealed outlooks are produced by the real chain (tests/fixtures/make_v11_consensus_sealed.py);
// the Worker re-derives the warning from the sealed capture and the cutoff. Synthetic data only: no network, KV or credentials.
type Case = { cutoff: string; outlooks: Record<string, any> };
const fixture = JSON.parse(readFileSync("../tests/fixtures/v11-consensus-sealed.json", "utf-8")) as { cases: Record<string, Case> };
const money = (amount: number, currency: string | null) => `${currency ?? ""} ${amount}`;
const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value));
function bubblesFromReply(reply: string): any[] {
  return (JSON.parse(reply) as any[]).flatMap(message => message.type === "flex"
    ? message.contents?.type === "carousel" ? message.contents.contents : [message.contents]
    : []);
}
function visibleText(value: any): string {
  if (Array.isArray(value)) return value.map(visibleText).join(" ");
  if (value === null || typeof value !== "object") return "";
  return Object.entries(value).filter(([key]) => key !== "action")
    .map(([key, child]) => key === "text" && typeof child === "string" ? child : visibleText(child)).join(" ");
}
const noWhitespace = (value: string) => value.replace(/\\n|\s/g, "");
const END = "2026-09-30";
const warningText = (ends: string, capturedAt: string) =>
  `所估季度已於${ends}結束，實際營收尚未公布；截至${capturedAt}分析師共識；仍為分析師共識（非官方），非實績`;
const LABEL_PREFIX = "分析師共識（非公司財測、非官方）｜Yahoo Finance，37 位分析師，截至 ";

/** Parse one case's outlook; mutate may edit the sealed v3 object; the day and instant default to the case's cutoff. */
function parse(name: string, symbol: string, mutate?: (v3: any) => void, generatedAt?: string): OrderForecast {
  const outlook = clone(fixture.cases[name]!.outlooks[symbol]!);
  if (mutate) mutate(outlook.order_forecast_v3);
  const at = generatedAt ?? fixture.cases[name]!.cutoff;
  return parseOrderForecastV3(outlook.order_forecast_v3, at.slice(0, 10), symbol, at, outlook.order_forecast);
}
const surfaces = (f: OrderForecast) => ({
  card: forecastCard(f, money).map(([text]) => text).join("\n"),
  text: forecastText(f, money),
  detail: forecastLines(f, money).join("\n"),
});
/** Set the same warning object in the three places the producer seals it. */
function setWarning(v3: any, warning: any): void { v3.warning = clone(warning); v3.m6.warning = clone(warning); v3.m12.warning = clone(warning); }
const refused = (f: OrderForecast) => [f.m6.status, f.m6.reason, f.m12.reason, f.revenueBasis ?? null];
const REFUSED = ["UNAVAILABLE", "INVALID", "INVALID", null];

describe("consensus post-quarter-end bridge: the Worker re-derives and renders the warning", () => {
  it.each([["bridge_day1", "2026-10-01T02:00:00Z"], ["bridge_day13", "2026-10-13T02:00:00Z"], ["bridge_day70", "2026-12-09T02:00:00Z"]])(
    "keeps the labelled projection with the exact warning at %s", (name, capturedAt) => {
      const f = parse(name, "000660.KS");
      expect([f.m6.status, f.m6.basis, f.revenueBasis]).toEqual(["AVAILABLE", "CONSENSUS", "CONSENSUS"]);
      expect(f.m6.basis_label).toBe(`${LABEL_PREFIX}${capturedAt.slice(0, 10)}`);
      const text = warningText(END, capturedAt);
      expect(f.m6.warning?.text).toBe(text);
      expect(f.m12.warning?.text).toBe(text);
      for (const [surface, body] of Object.entries(surfaces(f))) {
        expect(body, surface).toContain(text);
        expect(body, surface).toContain(`達成${CONSENSUS_PRICE_LABEL}營收推估 → 股價情境`); // Task B's price label, with the warning beside it
        expect(body, surface).toContain(`${LABEL_PREFIX}${capturedAt.slice(0, 10)}`);
        expect(body, surface).not.toContain("財測時效警示"); // the consensus is not a company forecast
        expect(body, surface).not.toContain("公司營收財測＋模型");
      }
      expect(surfaces(f).card).toContain(`共識時效警示：${text}`);
      expect(surfaces(f).detail).toContain(`共識時效警示：${text}`);
      expect(surfaces(f).detail).toContain("推算四個財季（含已結束財季）營收：");
    });

  it("serves a US issuer inside the bridge as well", () => {
    const f = parse("bridge_day13", "ACME");
    expect([f.m6.status, f.revenueBasis, f.m6.currency]).toEqual(["AVAILABLE", "CONSENSUS", "USD"]);
    expect(f.m6.warning?.text).toBe(warningText(END, "2026-10-13T02:00:00Z"));
  });

  it("keeps an expired state when the quarter ended 71 days ago or the capture was taken before the end", () => {
    for (const name of ["bridge_day71", "quarter_ended"]) {
      const f = parse(name, "000660.KS");
      expect([f.m6.status, f.m6.reason, f.revenueBasis ?? null, f.m6.warning ?? null], name).toEqual(["UNAVAILABLE", "STALE", null, null]);
      expect(f.consensusNote, name).toContain("分析師共識所估財季已結束，待公司公布財報並更新審核紀錄後再推估");
      for (const [surface, body] of Object.entries(surfaces(f))) expect(body, `${name} ${surface}`).not.toContain("共識時效警示");
    }
  });

  it("shows no warning for a capture of a quarter that has not ended", () => {
    const f = parse("available", "000660.KS");
    expect(f.m6.warning ?? null).toBeNull();
    for (const body of Object.values(surfaces(f))) expect(body).not.toContain("時效警示");
  });

  it("leaves company guidance with its own wording", () => {
    const f = parse("guidance_precedence", "NVDA");
    expect(f.revenueBasis).toBe("COMPANY_GUIDANCE");
    for (const body of Object.values(surfaces(f))) { expect(body).not.toContain("共識時效警示"); expect(body).not.toContain("分析師共識"); }
  });
});

describe("consensus post-quarter-end bridge: anything the Worker cannot re-derive fails closed", () => {
  const good = () => clone(fixture.cases["bridge_day13"]!.outlooks["000660.KS"].order_forecast_v3.warning);

  it("control: the unmodified bridge object parses", () => {
    expect(parse("bridge_day13", "000660.KS").m6.status).toBe("AVAILABLE");
  });

  it.each<[string, (v3: any) => void]>([
    ["an edited warning text", v3 => { const w = good(); w.text = w.text.replace("非實績", "實績"); setWarning(v3, w); }],
    ["the guidance wording on a consensus basis", v3 => { const w = good(); w.text = `財測季度已於${END}結束，實際營收尚未公布；截至2026-10-13T02:00:00Z查核；仍為財測／模型，非實績`; setWarning(v3, w); }],
    ["a warning edited in one place only", v3 => { v3.m6.warning.text += "。"; }],
    ["a warning missing from one tile", v3 => { delete v3.m12.warning; }],
    ["a missing warning beside an ended quarter", v3 => { v3.warning = null; v3.m6.warning = null; v3.m12.warning = null; }],
    ["a wrong checked_at", v3 => { const w = good(); w.checked_at = "2026-10-13T03:00:00Z"; setWarning(v3, w); }],
    ["an extra affected end", v3 => { const w = good(); w.affected_ends = [END, "2026-12-31"]; setWarning(v3, w); }],
    ["a fiscal-year flag", v3 => { const w = good(); w.is_fy = true; setWarning(v3, w); }],
    ["a wrong quarter index", v3 => { const w = good(); w.quarter_index = 1; setWarning(v3, w); }],
  ])("refuses %s", (_name, mutate) => {
    expect(refused(parse("bridge_day13", "000660.KS", mutate))).toEqual(REFUSED);
  });

  it("refuses a warning beside a capture taken before the quarter ended", () => {
    const f = parse("bridge_day1", "000660.KS", v3 => {
      v3.evidence.consensus.captured_at = "2026-09-30T20:00:00Z";
      const w = good();
      w.checked_at = "2026-09-30T20:00:00Z"; w.text = warningText(END, "2026-09-30T20:00:00Z");
      setWarning(v3, w);
    });
    expect(refused(f)).toEqual(REFUSED);
  });

  it("refuses the bridge at 71 days (a capture and warning re-stamped to the day the quarter is 71 days old)", () => {
    const f = parse("bridge_day70", "000660.KS", v3 => {
      v3.evidence.consensus.captured_at = "2026-12-10T02:00:00Z";
      const w = good();
      w.checked_at = "2026-12-10T02:00:00Z"; w.text = warningText(END, "2026-12-10T02:00:00Z");
      setWarning(v3, w);
    }, "2026-12-10T08:00:00Z");
    expect(refused(f)).toEqual(REFUSED);
    // control: the same object at 70 days is accepted
    expect(parse("bridge_day70", "000660.KS", undefined, "2026-12-09T08:00:00Z").m6.status).toBe("AVAILABLE");
  });

  it("refuses a warning beside a capture of a quarter that has not ended", () => {
    expect(refused(parse("available", "000660.KS", v3 => setWarning(v3, good())))).toEqual(REFUSED);
  });

  it("refuses a consensus warning on a company-guidance basis", () => {
    const f = parse("guidance_precedence", "NVDA", v3 => setWarning(v3, good()));
    expect(f.m6.status).not.toBe("AVAILABLE");
  });

  it("refuses an expired state the bridge would still serve (a STALE seal beside a capture taken after the end)", () => {
    const f = parse("quarter_ended", "000660.KS", v3 => { v3.evidence.consensus.captured_at = "2026-10-01T02:00:00Z"; });
    expect(refused(f)).toEqual(REFUSED);
  });
});

describe("consensus post-quarter-end bridge through the real LINE callers", () => {
  const CASE = "bridge_day13";
  const SYMBOLS = ["000660.KS", "ACME"];
  const RUN = "20261013T080000Z-abcdefabcde2";
  const cutoffMs = Date.parse(fixture.cases[CASE]!.cutoff);
  const TEXT = warningText(END, "2026-10-13T02:00:00Z");

  beforeEach(() => { vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(cutoffMs + 30 * 60_000); });
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

  function rawDoc(mutate?: (v3: any) => void): any {
    const { cutoff, outlooks } = fixture.cases[CASE]!;
    const raw = doc(Date.parse(cutoff));
    SYMBOLS.forEach((symbol, index) => {
      raw.top[index + 1]!.symbol = symbol;
      (raw.top[index + 1] as any).outlook = clone(outlooks[symbol]);
    });
    if (mutate) mutate(raw.top[1]!.outlook.order_forecast_v3);
    return raw;
  }
  async function sha(text: string): Promise<string> {
    const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
    return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
  }
  async function sealedEnv(raw: unknown, extra: Record<string, string> = {}) {
    const kv = new MemoryKv();
    const stamp = new Date(Date.now() - 60_000).toISOString().replace(/\.\d{3}Z$/, "Z");
    kv.values.set("v213:top20-report:latest", JSON.stringify({ synthetic: "report" }));
    kv.values.set("last_successful_pipeline_timestamp", stamp);
    await sealUnboundReport(kv, RUN);
    const sealKey = `snapshot:${RUN}:${SNAPSHOT_SEAL_KEY}`;
    const seal = JSON.parse(kv.values.get(sealKey)!);
    const body = JSON.stringify(raw);
    const digest = await sha(body);
    seal.objects[BOTTLENECK_V3_KEY] = { sha256: digest, utf8_bytes: new TextEncoder().encode(body).byteLength };
    kv.values.set(`blob:v1:${digest}`, body);
    const sealText = JSON.stringify(seal);
    kv.values.set(sealKey, sealText);
    const pointer = JSON.parse(kv.values.get("snapshot:current")!);
    pointer.seal_sha256 = await sha(sealText);
    kv.values.set("snapshot:current", JSON.stringify(pointer));
    class NoPrivateReads extends MemoryKv { override async get<T = string>(): Promise<T | null> { throw new Error("PRIVATE_READ_FORBIDDEN"); } }
    return { PUBLIC_CACHE: asKv(kv), TENANT_PRIVATE_CACHE: asKv(new NoPrivateReads()), EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()),
      V21_TOP20_MAX_AGE_SECONDS: "7200", LINE_CHANNEL_SECRET: "EXAMPLE_NOT_REAL", LINE_CHANNEL_ACCESS_TOKEN: "EXAMPLE_NOT_REAL",
      CURRENT_PUBLIC_DATA_ENABLED: "true", ...extra };
  }
  async function lineReply(env: Record<string, unknown>, text: string): Promise<string> {
    let messages: unknown[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
      if (url !== "https://api.line.me/v2/bot/message/reply") throw new Error(`NETWORK_FORBIDDEN ${url}`);
      messages = JSON.parse(String(init.body)).messages;
      return new Response("{}", { status: 200 });
    }));
    await processAuthorizedLineEvent(await freeRelayRequestEnv(env as never), { waitUntil() { throw new Error("MODEL_JOB_FORBIDDEN"); } } as unknown as ExecutionContext,
      { type: "message", replyToken: "SYNTHETIC_REPLY", timestamp: Date.now(), message: { id: "SYNTHETIC_MESSAGE", type: "text", text } } as never,
      "SYNTHETIC_TENANT");
    assertLineMessages(messages as never);
    expect(fetch).toHaveBeenCalledTimes(1);
    return JSON.stringify(messages);
  }
  const answer = async (env: unknown, text: string) => JSON.stringify(await v213PublicLineAnswer(env as never, parseQuery(text)));

  it("keeps the compact consensus disclosure and the full warning in existing detail/text routes", () => {
    const parsed = parseBottleneckV3(rawDoc(), cutoffMs + HOUR)!;
    const flex = JSON.stringify(buildBottleneckTop20Messages(parsed, "flex"));
    const consensusFlex = visibleText(bubblesFromReply(flex).find(bubble => visibleText(bubble).includes("000660.KS"))).replace(/\s+/g, " ");
    const text = JSON.stringify(buildBottleneckTop20Messages(parsed, "text"));
    const detailFlex = JSON.stringify(buildBottleneckDetail(parsed, "000660.KS", "flex"));
    const detailText = JSON.stringify(buildBottleneckDetail(parsed, "000660.KS", "text"));
    // V25-FIX3: the forecast-bearing Top20 bubble keeps source/date and the exact warning; detail Flex has no consensus figure, while text retains full attribution.
    expect(noWhitespace(consensusFlex)).toContain(noWhitespace(TEXT));
    expect(consensusFlex).toContain("非實績");
    expect(noWhitespace(consensusFlex)).toContain(noWhitespace(`若約6個月（2財季）達成${CONSENSUS_PRICE_LABEL}營收推估 → 股價情境`));
    expect(noWhitespace(consensusFlex)).toContain(noWhitespace("營收推估達成，P/S與股數不變；基準：最新已報四季"));
    expect(noWhitespace(consensusFlex)).toContain(noWhitespace(`${LABEL_PREFIX}2026-10-13`));
    expect(JSON.stringify(bubblesFromReply(flex))).toContain("瓶頸詳情 000660.KS");
    for (const [name, body] of Object.entries({ text, detailFlex, detailText })) expect(noWhitespace(body), name).toContain(noWhitespace(TEXT));
    expect(noWhitespace(text)).toContain(noWhitespace(`達成${CONSENSUS_PRICE_LABEL}營收推估 → 股價情境`));
    expect(detailFlex).toContain("共識時效警示");
    expect(noWhitespace(detailText)).toContain(noWhitespace(`達成${CONSENSUS_PRICE_LABEL}營收推估 → 股價情境`));
    expect(noWhitespace(detailText)).toContain(noWhitespace(`${LABEL_PREFIX}2026-10-13`));
  });
  it("restores financial attribution on the actual detail-page caller bubble", async () => {
    const raw = doc(Date.now());
    const financial = raw.top[2] as any;
    const official = structuredClone((officialRevenueFixture as any).fundamentals);
    official.shares_yoy = 0.02;
    official.shares_basis = "DILUTED_WEIGHTED_AVERAGE";
    official.cross_check = { source_id: "TPEX", source_url: "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O",
      period: "2026-08", revenue_yoy: 0.525, cumulative_yoy: 4.89, currency: "TWD" };
    financial.symbol = "5351.TWO";
    financial.name = "鈺創";
    financial.fundamentals = official;
    financial.market.cross_check = structuredClone((raw.top as any[])[0].market.cross_check);
    const env = await sealedEnv(raw);
    const financePages = bubblesFromReply(await lineReply(env, "瓶頸詳情 5351.TWO"));
    const finance = visibleText(financePages[0]);
    for (const required of ["Yahoo Finance 季度損益表（非官方）", "2026-06-30", "鈺創官方合併季報",
      "稀釋加權平均股數", "正常交易以來年化 +64%（非2年）", "2025-02-21",
      "官方月營收：櫃買中心 2026-08", "交易所收盤交叉比對"]) expect.soft(finance.replace(/\s+/g, " ")).toContain(required);
  });

  it("keeps RPO amount status, revenue-growth calculation, coverage and distinct dates on the actual orders bubble", async () => {
    const env = await sealedEnv(doc(Date.now()));
    const orderPages = bubblesFromReply(await lineReply(env, "瓶頸詳情 S1"));
    const orders = visibleText(orderPages[1]);
    for (const required of ["RPO 2026-07-26 年增+68%", "已簽約營收成長支撐", "分期已簽約認列金額÷目前營收−1",
      "40%", "133%", "股價 2026-09-25", "認列基準 2026-06-30"]) expect.soft(orders).toContain(required);
  });

  it("keeps exact spread legs, assignment risk and unit basis on the actual lesson bubble", async () => {
    const env = await sealedEnv(doc(Date.now()));
    const lesson = bubblesFromReply(await lineReply(env, "期權教學 bull_call_spread"));
    const spread = visibleText(lesson[0]);
    for (const required of ["$100 Call", "$4.00", "$110 Call", "$1.50", "Pin Risk", "100股"]) expect.soft(spread).toContain(required);
  });

  it("preserves the conditional dilution and financing penalty in the actual full-text score route", async () => {
    const env = await sealedEnv(doc(Date.now()));
    const score = await lineReply(env, "瓶頸詳情 S3 文字");
    expect(score).toContain("稀釋／融資扣分 -2");
  });

  it("preserves the industry source quotation and count operands in the actual full-text route", async () => {
    const env = await sealedEnv(doc(Date.now()));
    const industry = await lineReply(env, "產業爆發榜 文字");
    for (const required of ["HBM 與 CoWoS 是近期限制。", "HBM and CoWoS are near-term constraints.", "296", "197", "3.00x"])
      expect.soft(industry).toContain(required);
  });



  it("answers TOP20 compactly and preserves consensus detail through the Worker's LINE event entry", async () => {
    const raw = rawDoc();
    const env = await sealedEnv(raw);
    const carousel = await lineReply(env, "TOP20");
    expect(carousel).toContain('"type":"flex"');
    const consensusBubble = bubblesFromReply(carousel).find(bubble => visibleText(bubble).includes("000660.KS"));
    const consensusText = visibleText(consensusBubble);
    // V25-FIX3: compare the same returned Top20 bubble after line wrapping; every horizon keeps its own window and basis.
    expect(noWhitespace(consensusText)).toContain(noWhitespace(TEXT));
    expect(consensusText).toContain("非實績");
    expect(noWhitespace(consensusText)).toContain(noWhitespace(`${LABEL_PREFIX}2026-10-13`));
    const forecast = parseBottleneckV3(raw, cutoffMs + HOUR)!.top[1]!.forecast!;
    for (const horizon of [forecast.m6, forecast.m12]) {
      expect(horizon.start).toBeTruthy();
      expect(horizon.end).toBeTruthy();
      expect(horizon.basis_label).toBeTruthy();
      expect(noWhitespace(consensusText)).toContain(noWhitespace(horizon.start!));
      expect(noWhitespace(consensusText)).toContain(noWhitespace(horizon.end!));
      expect(noWhitespace(consensusText)).toContain(noWhitespace(horizon.basis_label!));
    }
    for (const token of ["非目標價", "非投資建議", "非今日起", "非保證", "不自動下單"]) {
      const count = consensusText.split(token).length - 1;
      expect(count, token).toBe(1);
    }
    expect(carousel).toContain("瓶頸詳情 000660.KS");
    const detail = await lineReply(env, "瓶頸詳情 000660.KS");
    expect(noWhitespace(visibleText(bubblesFromReply(detail)))).toContain(noWhitespace(TEXT));
    expect(detail).not.toContain("財測時效警示");
    const detailText = await lineReply(env, "瓶頸詳情 000660.KS 文字");
    expect(noWhitespace(detailText)).toContain(noWhitespace(TEXT));
    expect(noWhitespace(detailText)).toContain(noWhitespace(`達成${CONSENSUS_PRICE_LABEL}營收推估 → 股價情境`));
  });
  it("keeps V3 company-guidance caveats single-use and both horizons sourced through the LINE caller", async () => {
    const guidance = fixture.cases["guidance_precedence"]!;
    vi.setSystemTime(Date.parse(guidance.cutoff) + 30 * 60_000);
    const raw = doc(Date.parse(guidance.cutoff));
    raw.top[1]!.symbol = "NVDA";
    (raw.top[1] as any).outlook = clone(guidance.outlooks.NVDA);
    const env = await sealedEnv(raw);
    const reply = await lineReply(env, "TOP20");
    const bubble = bubblesFromReply(reply).find(item => visibleText(item).includes("NVDA"));
    const text = visibleText(bubble);
    // V25-FIX3: required scenario caveats must be present exactly once, not merely free of duplicates.
    for (const token of ["非目標價", "非投資建議", "非今日起", "非保證", "不自動下單"]) {
      const count = text.split(token).length - 1;
      expect.soft(count, token).toBe(1);
    }
    const forecast = parseBottleneckV3(raw, Date.parse(guidance.cutoff) + HOUR)!.top[1]!.forecast!;
    for (const horizon of [forecast.m6, forecast.m12]) {
      if (horizon.start) expect(text).toContain(horizon.start);
      if (horizon.end) expect(text).toContain(horizon.end);
      if (horizon.basis_label) expect(text).toContain(horizon.basis_label);
    }
  });

  it("answers the public LINE route as text for TOP20 and the company detail", async () => {
    const env = await sealedEnv(rawDoc(), { V213_LINE_PRESENTATION: "text" });
    const top20 = await answer(env, "TOP20");
    expect(top20).toContain(TEXT);
    const detail = await answer(env, "瓶頸詳情 000660.KS");
    expect(detail).toContain(TEXT);
    expect(detail).toContain("共識時效警示");
  });

  it("shows no figure and no warning through the LINE entry when the warning is forged", async () => {
    const env = await sealedEnv(rawDoc(v3 => {
      const w = clone(v3.warning); w.text = w.text.replace("非實績", "實績"); setWarning(v3, w);
    }));
    const detail = await lineReply(env, "瓶頸詳情 000660.KS");
    expect(detail).toContain("資料未通過驗證");
    expect(detail).not.toContain("共識時效警示");
    expect(detail).not.toContain(LABEL_PREFIX);
    expect(visibleText(bubblesFromReply(detail)).replace(/\s+/g, " ")).not.toContain(TEXT);
    const other = await lineReply(env, "瓶頸詳情 ACME"); // the other issuer keeps its own valid state
    expect(noWhitespace(visibleText(bubblesFromReply(other)))).toContain(noWhitespace(TEXT));
  });

  it("shows no figure when the warning sits beside a capture taken before the quarter ended", async () => {
    const env = await sealedEnv(rawDoc(v3 => {
      v3.evidence.consensus.captured_at = "2026-09-30T20:00:00Z";
      const w = clone(v3.warning); w.checked_at = "2026-09-30T20:00:00Z"; w.text = warningText(END, "2026-09-30T20:00:00Z"); setWarning(v3, w);
    }));
    const detail = await lineReply(env, "瓶頸詳情 000660.KS");
    expect(detail).toContain("資料未通過驗證");
    expect(detail).not.toContain(LABEL_PREFIX);
  });

  it("shows the expired wording through the LINE entry 71 days after the end", async () => {
    const { cutoff } = fixture.cases["bridge_day71"]!;
    vi.setSystemTime(Date.parse(cutoff) + 30 * 60_000);
    const raw = doc(Date.parse(cutoff));
    raw.top[1]!.symbol = "000660.KS";
    (raw.top[1] as any).outlook = clone(fixture.cases["bridge_day71"]!.outlooks["000660.KS"]);
    const env = await sealedEnv(raw);
    const detail = await lineReply(env, "瓶頸詳情 000660.KS");
    expect(noWhitespace(visibleText(bubblesFromReply(detail)))).toContain(noWhitespace("公司未提供營收財測；分析師共識所估財季已結束，待公司公布財報並更新審核紀錄後再推估"));
    expect(detail).not.toContain("共識時效警示");
    expect(detail).not.toContain("股價情境 +");
  });
});
