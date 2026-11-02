import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { parseQuery } from "../src/core";
import { assertLineMessages } from "../src/line-messages";
import type { LineOutboundMessage } from "../src/line-messages";
import { manualOptionQuoteAnswer } from "../src/manual-options";
import { processAuthorizedLineEvent } from "../src/v211/worker";
import { buildCoveredCallMessages, validateCoveredCallCycle } from "../src/v213/covered-call";
import type { CoveredCallCycle } from "../src/v213/covered-call";
import { validateOptionContractQuote } from "../src/v213/market-product-schema";
import { loadDetailedOptionObservation, OPTIONS_KEY } from "../src/v213/market-observations";
import * as rules from "../src/v213/option-recommendation-rules";
import { buildOptionsGuidanceFlexBubble, buildOptionsGuidanceText, generateOptionsOrderGuidance } from "../src/v213/options-guidance";
import { buildOptionContractFlex, buildOptionContractText } from "../src/v213/options-product";
import { freeRelayRequestEnv } from "../src/v213/production-worker";
import type * as PublicOptionsAdmission from "../src/v213/public-options-admission";
import { pinPublicSnapshot } from "../src/v213/public-snapshot";
import { v213PublicLineAnswer } from "../src/v213/rich-menu";
import { SNAPSHOT_SEAL_KEY } from "../src/v213/snapshot-seal";
import { asKv, MemoryKv } from "./fake-kv";
import { sealUnboundReport } from "./sealed-report-migration";
import { admitSyntheticTickers, resetAdmissionToReal } from "./synthetic-option-admission";

// Only quote-specific positive tests opt in. Rights-NONE negatives retain the real catalog predicate.
vi.mock("../src/v213/public-options-admission", async importOriginal => {
  const real = await importOriginal<typeof PublicOptionsAdmission>();
  return { ...real, admitPublicOption: vi.fn(real.admitPublicOption) };
});

const NOW = Date.parse("2026-11-02T12:00:00Z");
const STAMP = "2026-11-02T11:30:00Z";
const RUN = "20261102T120000Z-abcdefabcde9";
const asOf = "2026-11-02";
const day = (dte: number) => new Date(NOW + dte * 86_400_000).toISOString().slice(0, 10);
function cycle(dte = 18): CoveredCallCycle {
  return {
    ticker: "SIVE.ST", strategy: "COVERED_CALL", expiry: day(dte), dte, spot: 30, currency: "SEK", multiplier: 100,
    quote_basis: "delayed", timestamp: STAMP, source: "Synthetic delayed observation", provenance: "https://synthetic.invalid/options",
    rights_status: "unadmitted_third_party", asof_date: asOf,
    suggestions: [{ role: "HIGH_STRIKE", strike: 33, bid: 0.3, ask: 0.32, mid: 0.31, limit_price: 0.31,
      premium_per_contract: 31, period_yield: 0.31 / 30, annualized_yield: 0.31 / 30 * 365 / Math.max(dte, 1),
      upside_to_strike: 0.1, delta: 0.18, delta_basis: "QUOTED", iv: null, oi: 900, volume: 50, spread_pct: 0.02 / 0.31 }],
  };
}
function bareQuote(dte: number) {
  return { ticker: "SIVE.ST", expiry: day(dte), dte, strike: 33, type: "call", bid: 0.3, mid: 0.31, ask: 0.32,
    spread: 0.02, delta: 0.18, iv: null, oi: 900, volume: 50, breakeven: null, maxprofit: null, maxloss: null,
    annualized_yield: null, assignment_risk: "Synthetic", liquidity_warning: "Synthetic", timestamp: STAMP,
    quote_basis: "delayed", source: "Synthetic", provenance: "RECEIPT_SYNTHETIC", currency: "SEK", multiplier: 100,
    rights_status: "unadmitted_third_party", admission_status: "ADMITTED" };
}
async function sha(text: string): Promise<string> {
  return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text))),
    byte => byte.toString(16).padStart(2, "0")).join("");
}
interface MonthlyTestEnv {
  PUBLIC_CACHE: KVNamespace;
  TENANT_PRIVATE_CACHE: KVNamespace;
  EPHEMERAL_SECURITY_CACHE: KVNamespace;
  V21_TOP20_MAX_AGE_SECONDS: string;
  V213_LINE_PRESENTATION: string;
}
async function sealed(monthly: unknown = cycle(), weekly: unknown = { unavailable: "所列到期不在本週或下週策略範圍" }, style = "text"): Promise<MonthlyTestEnv> {
  const kv = new MemoryKv();
  kv.values.set("v213:top20-report:latest", JSON.stringify({ synthetic: "monthly fallback" }));
  kv.values.set("last_successful_pipeline_timestamp", STAMP);
  await sealUnboundReport(kv, RUN);
  const body = JSON.stringify({ schema: "v213-options-v2", generated_at: STAMP, options: { "SIVE.ST": { monthly, weekly } } });
  const digest = await sha(body);
  const sealKey = `snapshot:${RUN}:${SNAPSHOT_SEAL_KEY}`;
  const seal = JSON.parse(kv.values.get(sealKey)!);
  seal.objects[OPTIONS_KEY] = { sha256: digest, utf8_bytes: new TextEncoder().encode(body).byteLength };
  kv.values.set(`blob:v1:${digest}`, body);
  const sealText = JSON.stringify(seal);
  kv.values.set(sealKey, sealText);
  const pointer = JSON.parse(kv.values.get("snapshot:current")!);
  pointer.seal_sha256 = await sha(sealText);
  kv.values.set("snapshot:current", JSON.stringify(pointer));
  return { PUBLIC_CACHE: asKv(kv), TENANT_PRIVATE_CACHE: asKv(new MemoryKv()), EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()),
    V21_TOP20_MAX_AGE_SECONDS: "7200", V213_LINE_PRESENTATION: style };
}
async function answer(env: MonthlyTestEnv, command: string): Promise<LineOutboundMessage[]> {
  const messages = await v213PublicLineAnswer(env as never, parseQuery(command)) as LineOutboundMessage[];
  assertLineMessages(messages);
  return messages;
}
const text = (messages: LineOutboundMessage[]) => JSON.stringify(messages);
function messageActions(value: unknown): string[] {
  if (!value || typeof value !== "object") return [];
  const row = value as Record<string, unknown>;
  const own = row.type === "message" && typeof row.text === "string" ? [row.text] : [];
  return own.concat(Object.values(row).flatMap(messageActions));
}
function hasMonthlyCaution(value: unknown): boolean {
  if (!value || typeof value !== "object") return false;
  if (Array.isArray(value)) return value.some(hasMonthlyCaution);
  const node = value as Record<string, unknown>;
  return (node.type === "box" && node.backgroundColor === "#FDE68A"
    && JSON.stringify(node).includes("超出偏好 21-45 天區間")) || Object.values(node).some(hasMonthlyCaution);
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  resetAdmissionToReal();
  vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("NETWORK_FORBIDDEN"); }));
});
afterEach(() => { resetAdmissionToReal(); vi.useRealTimers(); vi.unstubAllGlobals(); });

describe("V29 monthly fallback: sealed consumer regressions", () => {
  // Existing APIs ONLY: on base these tests reach the loader's missing-fallback assertion, not an import failure.
  it.each([18, 46])("loads SIVE.ST %i DTE and reaches the actual text/Flex card plus detail button", async dte => {
    admitSyntheticTickers("SIVE.ST");
    const env = await sealed(cycle(dte));
    const loaded = await loadDetailedOptionObservation(await pinPublicSnapshot(env as never), "SIVE.ST", "monthly", NOW);
    expect(loaded.status, "selected listed 14-60 DTE monthly fallback must survive the sealed loader").toBe("FOUND");
    expect(loaded.quote?.expiry).toBe(day(dte));
    expect(loaded.quote?.dte).toBe(dte);
    const body = text(await answer(env, "SIVE.ST 每月期權"));
    expect(body).toContain(day(dte));
    expect(body).toContain("33.00 SEK");
    expect(body).toContain(`DTE ${dte}`);
    expect(body).toContain("超出偏好 21-45 天區間");
    expect(body).not.toContain("OPTION_DATA_UNAVAILABLE");
    const flexEnv = await sealed(cycle(dte), undefined, "flex");
    const flex = await answer(flexEnv, "SIVE.ST 每月期權");
    expect(flex[0]?.type).toBe("flex");
    expect(text(flex)).toContain("超出偏好 21-45 天區間");
    expect(hasMonthlyCaution(flex)).toBe(true);
    const detail = messageActions(flex).find(command => command === "SIVE.ST 每月期權 文字");
    expect(detail).toBeDefined();
    const detailBody = text(await answer(flexEnv, detail!));
    expect(detailBody).toContain(day(dte));
    expect(detailBody).toContain("33.00 SEK");
    expect(detailBody).toContain(`DTE ${dte}`);
  });

  it("routes the actual Worker event to the fallback card without invoking a model", async () => {
    admitSyntheticTickers("SIVE.ST");
    const env = await sealed();
    let replies: LineOutboundMessage[] = [];
    const network = vi.fn(async (url: string, init: RequestInit) => {
      if (url !== "https://api.line.me/v2/bot/message/reply") throw new Error("NETWORK_FORBIDDEN");
      replies = JSON.parse(String(init.body)).messages;
      return new Response("{}", { status: 200 });
    });
    vi.stubGlobal("fetch", network);
    await processAuthorizedLineEvent(await freeRelayRequestEnv({ ...env,
      LINE_CHANNEL_SECRET: "SYNTHETIC_NOT_REAL", LINE_CHANNEL_ACCESS_TOKEN: "SYNTHETIC_NOT_REAL", CURRENT_PUBLIC_DATA_ENABLED: "true",
    }), { waitUntil() { throw new Error("MODEL_JOB_FORBIDDEN"); } } as never, {
      type: "message", replyToken: "SYNTHETIC_REPLY", timestamp: NOW,
      message: { id: "SYNTHETIC_MESSAGE", type: "text", text: "SIVE.ST 每月期權" },
    }, "SYNTHETIC_TENANT");
    expect(network).toHaveBeenCalledTimes(1);
    assertLineMessages(replies);
    expect(text(replies)).toContain("2026-11-20");
    expect(text(replies)).toContain("超出偏好 21-45 天區間");
    expect(text(replies)).toContain("33.00 SEK");
  });

  it.each([18, 46])("does not substitute the same-symbol %i DTE monthly row for weekly", async dte => {
    admitSyntheticTickers("SIVE.ST");
    const env = await sealed(cycle(dte), cycle(dte));
    const loaded = await loadDetailedOptionObservation(await pinPublicSnapshot(env as never), "SIVE.ST", "weekly", NOW);
    expect(loaded.status).toBe("QUOTE_INVALID_OR_STALE");
    const body = text(await answer(env, "SIVE.ST 每週期權"));
    expect(body).toContain("OPTION_DATA_UNAVAILABLE");
    expect(body).not.toContain("33.00 SEK");
  });

  it("keeps a real valid current-week quote unchanged and weekly unavailable without substitution", async () => {
    admitSyntheticTickers("SIVE.ST");
    const weekly = { ...cycle(4), weekly_week: "CURRENT" };
    const env = await sealed(cycle(), weekly);
    const body = text(await answer(env, "SIVE.ST 每週期權"));
    expect(body).toContain("2026-11-06");
    expect(body).toContain("本週到期");
    expect(body).toContain("33.00 SEK");
    expect(body).not.toContain("月期權延伸到期");
    const absent = text(await answer(await sealed(), "SIVE.ST 每週期權"));
    expect(absent).toContain("OPTION_DATA_UNAVAILABLE");
    expect(absent).toContain("所列到期不在本週或下週策略範圍");
    expect(absent).not.toContain("33.00 SEK");
  });

  it.each([14, 60])("admits the inclusive monthly %i DTE bound through the sealed card", async dte => {
    admitSyntheticTickers("SIVE.ST");
    const env = await sealed(cycle(dte));
    const loaded = await loadDetailedOptionObservation(await pinPublicSnapshot(env as never), "SIVE.ST", "monthly", NOW);
    expect(loaded.status).toBe("FOUND");
    const body = text(await answer(env, "SIVE.ST 每月期權"));
    expect(body).toContain("33.00 SEK");
    expect(body).toContain(`DTE ${dte}`);
    expect(body).toContain("超出偏好 21-45 天區間");
  });

  it("keeps preferred expiry labels unchanged", async () => {
    admitSyntheticTickers("SIVE.ST");
    for (const dte of [21, 30, 45]) {
      const env = await sealed(cycle(dte));
      const body = text(await answer(env, "SIVE.ST 每月期權"));
      expect(body).toContain("33.00 SEK");
      expect(body).not.toContain("月期權延伸到期");
    }
  });

  it("keeps rights, freshness, quote/numeric, subject and empty-row gates fail-closed", async () => {
    const denied = await sealed();
    expect((await loadDetailedOptionObservation(await pinPublicSnapshot(denied as never), "SIVE.ST", "monthly", NOW)).status).toBe("RIGHTS_NOT_ADMITTED");
    expect(text(await answer(denied, "SIVE.ST 每月期權"))).not.toContain("33.00 SEK");
    admitSyntheticTickers("SIVE.ST");
    const badQuote = cycle(); badQuote.suggestions[0]!.bid = 0;
    const badNumeric = cycle(); badNumeric.suggestions[0]!.annualized_yield = 999;
    const stale = { ...cycle(), timestamp: "2026-11-02T04:00:00Z" };
    const foreign = { ...cycle(), ticker: "FOREIGN.ST" };
    for (const raw of [cycle(13), cycle(61), badQuote, badNumeric, stale, foreign, { ...cycle(), suggestions: [] }, {}]) {
      const env = await sealed(raw);
      expect((await loadDetailedOptionObservation(await pinPublicSnapshot(env as never), "SIVE.ST", "monthly", NOW)).status).toBe("QUOTE_INVALID_OR_STALE");
      expect(text(await answer(env, "SIVE.ST 每月期權"))).not.toContain("33.00 SEK");
    }
    const unavailable = await sealed({ unavailable: "無有效雙邊報價" });
    expect(text(await answer(unavailable, "SIVE.ST 每月期權"))).toContain("無有效雙邊報價");
    expect(text(await answer(unavailable, "SIVE.ST 每月期權"))).not.toContain("33.00 SEK");
  });
});

describe("V29 shared TS monthly selection and guidance", () => {
  it("keeps preferred constants and selects preferred-first, nearest30 with earlier ties", () => {
    expect(rules.selectMonthlyExpiry([day(46), day(18)], asOf)).toBe(day(18));
    expect(rules.selectMonthlyExpiry([day(20), day(45)], asOf)).toBe(day(45));
    expect(rules.selectMonthlyExpiry([day(31), day(29), day(29)], asOf)).toBe(day(29));
    expect(rules.selectMonthlyExpiry([day(46), day(14)], asOf)).toBe(day(14));
    for (const dte of [14, 60]) expect(rules.selectMonthlyExpiry([day(dte)], asOf)).toBe(day(dte));
    for (const expiries of [[], [day(13), day(61)], ["invalid", "2026-02-30"]]) {
      expect(rules.selectMonthlyExpiry(expiries, asOf)).toBeNull();
    }
    expect(rules.selectMonthlyExpiry([day(30)], "invalid")).toBeNull();
  });

  it.each([14, 18, 46, 60])("migrates selected bare-contract validation and guidance notices for %i DTE", dte => {
    admitSyntheticTickers("SIVE.ST");
    const bare = bareQuote(dte);
    const validation = { evaluatedAt: new Date(NOW).toISOString(), period: "monthly" as const };
    const validated = validateOptionContractQuote(bare, validation);
    expect(validated.dte).toBe(dte);
    expect(JSON.stringify(buildOptionContractText(validated, validation))).toContain("超出偏好 21-45 天區間");
    const flex = buildOptionContractFlex(validated, validation);
    expect(JSON.stringify(flex)).toContain("超出偏好 21-45 天區間");
    expect(hasMonthlyCaution(flex)).toBe(true);
    const guidance = generateOptionsOrderGuidance({ ticker: "SIVE.ST", strategy: "covered_call", underlyingPrice: 30,
      strike: 33, expiry: day(dte), dte, delta: 0.18, bid: 0.3, mid: 0.31, ask: 0.32, openInterest: 900, volume: 50, cycle: "monthly" });
    expect(guidance.dte_window).toEqual([21, 45]);
    expect(guidance.dte_window_status).toBe("OUTSIDE_CYCLE_WINDOW");
    expect(buildOptionsGuidanceText(guidance)).toContain(`DTE ${dte}`);
    expect(buildOptionsGuidanceText(guidance)).toContain("超出偏好 21-45 天區間");
    expect(JSON.stringify(buildOptionsGuidanceFlexBubble(guidance))).toContain("超出偏好 21-45 天區間");
    expect(validateCoveredCallCycle(cycle(dte), NOW, STAMP, "monthly")).not.toBeNull();
  });

  it.each([{ dte: 14, period: "weekly" as const }, { dte: 18, period: undefined }, { dte: 14, period: undefined }])(
    "does not infer monthly fallback for a $period individual quote at $dte DTE", ({ dte, period }) => {
      admitSyntheticTickers("SIVE.ST");
      const quote = bareQuote(dte);
      const validation = { evaluatedAt: new Date(NOW).toISOString(), period };
      const validated = validateOptionContractQuote(quote, validation);
      for (const messages of [buildOptionContractText(validated, validation), buildOptionContractFlex(validated, validation)]) {
        assertLineMessages(messages);
        const rendered = JSON.stringify(messages);
        expect(rendered).toContain(day(dte));
        expect(rendered).not.toContain("月期權延伸到期");
        expect(hasMonthlyCaution(messages)).toBe(false);
      }
    });

  it.each(["每週期權", "期權"])("does not label a 14-day %s covered call as monthly", periodLabel => {
    admitSyntheticTickers("SIVE.ST");
    const validated = validateCoveredCallCycle(cycle(14), NOW, STAMP);
    expect(validated).not.toBeNull();
    for (const style of ["text", "flex"] as const) {
      const messages = buildCoveredCallMessages(validated!, periodLabel, style);
      expect(JSON.stringify(messages)).not.toContain("月期權延伸到期");
      expect(hasMonthlyCaution(messages)).toBe(false);
    }
  });

  it.each([18, 46])("keeps manual %i DTE input unverified with an explicit extended-monthly notice", dte => {
    const body = manualOptionQuoteAnswer(`期權試算 ticker=SIVE.ST type=call spot=30 strike=33 bid=0.30 ask=0.32 dte=${dte} currency=SEK`);
    expect(body).toContain("USER_SUPPLIED_NOT_VERIFIED");
    expect(body).toContain("每月延伸觀察區間");
    expect(body).toContain("超出偏好 21-45 天區間");
    expect(body).toContain(`DTE ${dte}`);
    expect(body).not.toContain("已封存");
  });
});
