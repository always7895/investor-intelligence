import { createHash } from "node:crypto";
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

// Operator 2026-10-13 (R/OPERATOR-DECISION-CONSENSUS-AND-OFFHOURS-OPTIONS-20261013.txt A1): the analyst-consensus revenue
// route is on, labelled analyst consensus, not company guidance, unofficial. The sealed outlooks are produced by the real
// chain (tests/fixtures/make_v11_consensus_sealed.py: Yahoo body -> collector cache -> selector -> sealer function); the
// Worker parses them exactly as produced. Synthetic data only: no network, KV or credentials.
type Case = { cutoff: string; outlooks: Record<string, any> };
const fixture = JSON.parse(readFileSync("../tests/fixtures/v11-consensus-sealed.json", "utf-8")) as { cases: Record<string, Case> };
const money = (amount: number, currency: string | null) => `${currency ?? ""} ${amount}`;
const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value));
const KR_LABEL = "分析師共識（非公司財測、非官方）｜Yahoo Finance，37 位分析師，截至 2026-09-28";

function v3Of(name: string, symbol: string): any { return clone(fixture.cases[name]!.outlooks[symbol]!.order_forecast_v3); }
function parse(name: string, symbol: string, mutate?: (v3: any) => void): OrderForecast {
  const outlook = clone(fixture.cases[name]!.outlooks[symbol]!);
  if (mutate) mutate(outlook.order_forecast_v3);
  const cutoff = fixture.cases[name]!.cutoff;
  return parseOrderForecastV3(outlook.order_forecast_v3, cutoff.slice(0, 10), symbol, cutoff, outlook.order_forecast);
}
const surfaces = (f: OrderForecast) => ({
  card: forecastCard(f, money).map(([text]) => text).join("\n"),
  text: forecastText(f, money),
  detail: forecastLines(f, money).join("\n"),
});

/** The sealed Top20 document of one case: each symbol on its own entry (the entry's symbol is the outlook's issuer). */
function rawDoc(name: string, symbols: string[]): any {
  const { cutoff, outlooks } = fixture.cases[name]!;
  const raw = doc(Date.parse(cutoff));
  symbols.forEach((symbol, index) => {
    raw.top[index + 1]!.symbol = symbol;
    (raw.top[index + 1] as any).outlook = clone(outlooks[symbol]);
  });
  return raw;
}
const parsedDoc = (name: string, symbols: string[]) => parseBottleneckV3(rawDoc(name, symbols), Date.parse(fixture.cases[name]!.cutoff) + HOUR)!;

describe("analyst-consensus revenue route: the labelled basis (producer-sealed outlooks, Worker reader)", () => {
  it("renders the labelled consensus basis on the card, the text and the detail, and labels the price scenarios", () => {
    const f = parse("available", "000660.KS");
    expect([f.m6.status, f.m6.basis, f.m12.basis, f.revenueBasis, f.revenueDiagnostic]).toEqual(["AVAILABLE", "CONSENSUS", "CONSENSUS", "CONSENSUS", null]);
    expect(f.m6.basis_label).toBe(KR_LABEL);
    expect(f.m12.basis_label).toBe(KR_LABEL);
    // 0q 100.29T + +1q 113.91T (the producer's own arithmetic, recomputed and equal in the Worker)
    expect(f.m6.amount).toBeCloseTo(100287043740000 + 113906353020000, 0);
    expect(f.m12.amount).toBeCloseTo(100287043740000 + 3 * 113906353020000, 0);
    const s = surfaces(f);
    for (const [name, text] of Object.entries(s)) {
      expect(text, name).toContain(KR_LABEL);
      expect(text, name).toContain("非訂單");
      expect(text, name).toContain(`達成${CONSENSUS_PRICE_LABEL}營收推估 → 股價情境`);
      expect(text, name).not.toContain("公司營收財測＋模型");
      expect(text, name).not.toContain("分析師共識路線本次未啟用");
    }
    // each of the two horizon rows and each of the two price rows carries its label
    expect(s.card.split(KR_LABEL).length - 1).toBe(2);
    expect(s.card.split(`達成${CONSENSUS_PRICE_LABEL}營收推估`).length - 1).toBe(2);
    expect(s.detail).toContain("分析師共識（非官方，0q，至2026-09-30）：37位分析師，截至2026-09-28");
    expect(s.detail).toContain("模型假設：前兩季依分析師共識");
  });

  it("serves a US issuer as well as the Korean ones (every NOT_DISCLOSED record, not only Korean)", () => {
    const f = parse("available", "ACME");
    expect([f.m6.status, f.revenueBasis, f.m6.currency]).toEqual(["AVAILABLE", "CONSENSUS", "USD"]);
    expect(f.m6.basis_label).toBe("分析師共識（非公司財測、非官方）｜Yahoo Finance，11 位分析師，截至 2026-09-28");
    expect(f.m6.amount).toBeCloseTo(1.25e9 + 1.35e9, 0);
    expect(surfaces(f).card).toContain("非官方");
  });

  it("names the smaller analyst count when only the first quarter is a consensus quarter", () => {
    const f = parse("available", "005930.KS");
    expect(f.m6.basis_label).toBe("分析師共識（非公司財測、非官方）｜Yahoo Finance，25 位分析師，截至 2026-09-28");
    expect(surfaces(f).detail).toContain("僅一季共識（次季分析師樣本不足），其後持平模型");
    expect(f.m6.amount).toBeCloseTo(2 * 204646748150000, 0); // the one consensus quarter, flat after it
  });

  it("keeps contracted recognition separate: shown beside the consensus revenue, never added to it", () => {
    const f = parse("with_recognition", "ACME");
    expect(f.revenueBasis).toBe("CONSENSUS");
    expect(f.m12.amount).toBeCloseTo(1.25e9 + 3 * 1.35e9, 0); // consensus + model only
    expect(f.contractedRecognition?.m12?.amount).toBeCloseTo(3.2e8 * 0.39, 0);
    const card = surfaces(f).card;
    expect(card).toContain("另列已簽約預計認列：1年期");
    expect(card).toContain("不相加");
    expect(card).toContain("分析師共識（非公司財測、非官方）");
  });

  it("lets company guidance keep precedence over a capture of the same issuer", () => {
    const f = parse("guidance_precedence", "NVDA");
    expect([f.revenueBasis, f.m6.basis_label]).toEqual(["COMPANY_GUIDANCE", "公司營收財測＋模型（非訂單）"]);
    expect(v3Of("guidance_precedence", "NVDA").evidence.consensus).toBeNull();
    for (const text of Object.values(surfaces(f))) expect(text).not.toContain("分析師共識");
  });

  it("states the unavailable states of the enabled route, each backed by its sealed evidence", () => {
    const cases: [string, string, string, string][] = [
      ["stale_age", "STALE", "分析師共識資料已逾24小時", "stale_age"],
      ["quarter_ended", "STALE", "分析師共識所估財季已結束", "quarter_ended"],
      ["period_mismatch", "PERIOD_MISMATCH", "分析師共識所估財季與已審核財季不一致", "period_mismatch"],
      ["no_capture", "NOT_DISCLOSED", "分析師共識尚無有效資料", "no_capture"],
      ["cache_fault", "INVALID", "分析師共識快取無法讀取", "cache_fault"],
    ];
    for (const [name, reason, words] of cases.map(c => [c[0], c[1], c[2]] as const)) {
      const f = parse(name, "000660.KS");
      expect([f.m6.status, f.m6.reason, f.m12.reason, f.revenueReason, f.revenueBasis, f.revenueDiagnostic], name)
        .toEqual(["UNAVAILABLE", reason, reason, reason, null, null]);
      expect(f.consensusNote, name).toContain(words);
      for (const [surface, text] of Object.entries(surfaces(f))) {
        expect(text, `${name} ${surface}`).toContain(`公司未提供營收財測；${words}`);
        expect(text, `${name} ${surface}`).not.toContain("分析師共識路線本次未啟用");
        expect(text, `${name} ${surface}`).not.toContain("股價情境 +"); // no figure is shown for an unavailable route
      }
    }
  });

  it("states an expired consensus beside a valid contracted recognition without suppressing the recognition", () => {
    const f = parse("recognition_stale", "ACME");
    expect([f.revenueStatus, f.revenueReason, f.revenueBasis ?? null, f.m6.status, f.m6.reason, f.m12.status, f.m12.basis])
      .toEqual(["UNAVAILABLE", "STALE", null, "UNAVAILABLE", "STALE", "AVAILABLE", "RECOGNITION"]);
    expect(f.m12.amount).toBeCloseTo(3.2e8 * 0.39, 0);
    expect(f.consensusNote).toContain("分析師共識所估財季已結束");
    const s = surfaces(f);
    for (const [name, text] of Object.entries(s)) {
      expect(text, name).toContain("內預計認列：");
      expect(text, name).toContain("公司未提供營收財測；分析師共識所估財季已結束");
      expect(text, name).not.toContain(CONSENSUS_PRICE_LABEL);
    }
  });

  it("keeps the gate-off wording unchanged and never routes a capture while the gate is off", () => {
    const f = parse("gate_off", "000660.KS");
    expect([f.revenueDiagnostic, f.revenueBasis, f.consensusNote ?? null]).toEqual(["CONSENSUS_DEFERRED", null, null]);
    for (const text of Object.values(surfaces(f))) expect(text).toContain("公司未提供營收財測；分析師共識路線本次未啟用");
  });
});

describe("analyst-consensus revenue route: an unknown or malformed consensus block fails closed", () => {
  const refused = (f: OrderForecast) => [f.m6.status, f.m6.reason, f.m12.reason, f.revenueBasis ?? null];
  const REFUSED = ["UNAVAILABLE", "INVALID", "INVALID", null];

  it("control: the unmodified sealed outlook parses", () => {
    expect(parse("available", "000660.KS").m6.status).toBe("AVAILABLE");
  });

  it.each<[string, (v3: any) => void]>([
    ["an unknown provider host", v3 => { v3.evidence.consensus.source_url = "https://example.com/v10/finance/quoteSummary/000660.KS"; }],
    ["a look-alike provider host", v3 => { v3.evidence.consensus.source_url = "https://query2.finance.yahoo.com.evil.example/x"; }],
    ["a plain http provider URL", v3 => { v3.evidence.consensus.source_url = "http://query2.finance.yahoo.com/v10/finance/quoteSummary/000660.KS"; }],
    ["a missing source URL", v3 => { delete v3.evidence.consensus.source_url; }],
    ["an unknown block key", v3 => { v3.evidence.consensus.rating = "BUY"; }],
    ["an unknown quarter key", v3 => { v3.evidence.consensus.quarters[0].target_price = 1; }],
    ["a non-object block", v3 => { v3.evidence.consensus = "Yahoo Finance"; }],
    ["a first quarter below three analysts", v3 => { v3.evidence.consensus.quarters[0].analysts = 2; }],
    ["a fractional analyst count", v3 => { v3.evidence.consensus.quarters[0].analysts = 37.5; }],
    ["a negative revenue", v3 => { v3.evidence.consensus.quarters[0].revenue = -1; }],
    ["a wrong currency", v3 => { v3.evidence.consensus.currency = "USD"; }],
    ["another issuer's capture", v3 => { v3.evidence.consensus.symbol = "005930.KS"; }],
    ["a capture dated after the cutoff", v3 => { v3.evidence.consensus.captured_at = "2026-09-28T16:00:00Z"; }],
    ["a capture older than 24 hours beside an available basis", v3 => { v3.evidence.consensus.captured_at = "2026-09-26T12:00:00Z"; }],
    ["a mismatched first quarter beside an available basis", v3 => { v3.evidence.consensus.quarters[0].end = "2026-12-31"; }],
    ["a mismatched second quarter beside an available basis", v3 => { v3.evidence.consensus.quarters[1].end = "2027-03-31"; }],
    ["a mismatched resolved start", v3 => { v3.evidence.consensus.quarters[0].start = "2020-07-01"; }],
    ["a forged amount", v3 => { v3.m6.amount *= 1.01; }],
    ["a forged scenario", v3 => { v3.m12.scenario.change += 0.5; }],
    ["a sealed gate that is off", v3 => { v3.evidence.consensus_enabled = false; }],
    ["a sealed deferred diagnostic", v3 => { v3.revenue_diagnostic = "CONSENSUS_DEFERRED"; }],
  ])("refuses %s", (_name, mutate) => {
    expect(refused(parse("available", "000660.KS", mutate))).toEqual(REFUSED);
  });

  it.each<[string, string, (v3: any) => void]>([
    ["stale_age", "a stale reason beside a fresh capture", v3 => { v3.evidence.consensus.captured_at = "2026-09-28T14:00:00Z"; }],
    ["period_mismatch", "a mismatch beside a matching capture", v3 => {
      v3.evidence.consensus.quarters = [{ period: "0q", end: "2026-09-30", revenue: 1, analysts: 37 }];
    }],
    ["period_mismatch", "a mismatching capture beside another reason", v3 => {
      v3.revenue_reason = "NOT_DISCLOSED"; v3.reason = "NOT_DISCLOSED"; v3.m6.reason = "NOT_DISCLOSED"; v3.m12.reason = "NOT_DISCLOSED";
    }],
    ["no_capture", "a stale reason without any sealed capture", v3 => {
      v3.revenue_reason = "STALE"; v3.reason = "STALE"; v3.m6.reason = "STALE"; v3.m12.reason = "STALE";
    }],
    ["cache_fault", "an unknown cache-fault marker", v3 => { v3.evidence.consensus_fault = "CONSENSUS_CACHE_MISSING"; }],
  ])("refuses an unavailable state backed by nothing: %s (%s)", (name, _what, mutate) => {
    expect(refused(parse(name, "000660.KS", mutate))).toEqual(REFUSED);
  });
});

describe("analyst-consensus revenue route: legacy views plus reviewed MU contract reference", () => {
  // The rendering of every sealed outlook the earlier producers made (the reviewed golden, the real-data proofs and the
  // producer probes) remains byte-identical to the original reader after removing only the explicitly asserted MU
  // contract-reference addition. The aggregate hash still binds every original number, window, label and source.
  const golden = JSON.parse(readFileSync("../tests/fixtures/v213-orders-v3-golden-sealed.json", "utf-8"));
  const proofRpo = JSON.parse(readFileSync("../tests/fixtures/v213-orders-v3-proof-rpo.json", "utf-8"));
  const proofStates = JSON.parse(readFileSync("../tests/fixtures/v213-orders-v3-proof-states.json", "utf-8"));
  const probes = JSON.parse(readFileSync("../tests/fixtures/v213-orders-v3-probes.json", "utf-8"));

  it("preserves the legacy projection and only appends the reviewed MU reference", () => {
    const rendered: string[] = [];
    const take = (label: string, v3: any, v2: any, generatedAt: string, symbol: string) => {
      const f = parseOrderForecastV3(v3, generatedAt.slice(0, 10), symbol, generatedAt, v2);
      expect(f.revenueBasis ?? null, label).not.toBe("CONSENSUS");
      expect(f.consensusNote ?? null, label).toBeNull();
      const view = surfaces(f);
      if (label === "proof-states MU") {
        const headline = "期後訂單消息（不併入 RPO）：已簽策略客戶協議（SCA）RPO 約 US$100B（含 FQ3 後新簽，最低量×最低價）（2026-06-24）";
        expect(f.supplements.map(c => c.id)).toEqual(["MU-SCA-RPO-2026-06-24"]);
        expect(view.card.endsWith(`\n${headline}`)).toBe(true);
        expect(view.text.endsWith(`｜${headline}`)).toBe(true);
        view.card = view.card.slice(0, -headline.length - 1);
        view.text = view.text.slice(0, -headline.length - 1);
        const marker = `\n${headline}\n`;
        const index = view.detail.indexOf(marker);
        expect(index).toBeGreaterThan(0);
        const added = view.detail.slice(index + 1).split("\n");
        expect(added).toHaveLength(3);
        expect(added[0]).toBe(headline);
        expect(added[1]).toBe("　已簽合約；已簽 SCA（含 FQ3 後新簽；公司說明日，非資產負債表日）；截至 2026-06-24");
        expect(added[2]).toBe(`　公司法說會講稿 2026-06-24（p.7, Strategic customer agreements）https://s25.q4cdn.com/621799436/files/doc_financials/2026/q3/Q3-FY26-Prepared-Remarks.pdf；原文：「${[...f.supplements[0]!.passage].slice(0, 160).join("")}」；本次查核 2026-09-27`);
        view.detail = view.detail.slice(0, index);
      }
      rendered.push(label, JSON.stringify(view));
    };
    for (const symbol of Object.keys(golden)) take(`golden ${symbol}`, golden[symbol].order_forecast_v3, golden[symbol].order_forecast, "2026-09-28T15:00:00Z", symbol);
    for (const [name, proof] of [["proof-rpo", proofRpo], ["proof-states", proofStates]] as const) {
      for (const symbol of Object.keys(proof.entries)) {
        take(`${name} ${symbol}`, proof.entries[symbol].order_forecast_v3, proof.entries[symbol].order_forecast, proof.generated_at, symbol);
      }
    }
    for (const name of Object.keys(probes.cases)) {
      take(`probe ${name}`, probes.cases[name].outlook.order_forecast_v3, probes.cases[name].outlook.order_forecast, probes.generated_at, "NVDA");
    }
    expect(rendered.length).toBe(84); // 42 sealed outlooks, each a label and its three surfaces
    expect(createHash("sha256").update(rendered.join("\n")).digest("hex")).toBe(BASELINE_RENDERING_SHA256);
  });
});

// ----- through the real user-facing callers: the Top20 carousel / text, the detail and the Worker's LINE entry ------------

describe("analyst-consensus revenue route through the real LINE callers", () => {
  const CASE = "available";
  const SYMBOLS = ["000660.KS", "005930.KS", "ACME"];
  const RUN = "20260928T150000Z-abcdefabcde1";
  const cutoffMs = Date.parse(fixture.cases[CASE]!.cutoff);

  beforeEach(() => { vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(cutoffMs + 30 * 60_000); });
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

  async function sha(text: string): Promise<string> {
    const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
    return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
  }
  /** A sealed snapshot carrying the case's Top20 v3 as its lazy object (the pattern of v213-line-aliases.test.ts). */
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
  const answer = async (env: unknown, text: string) => JSON.stringify(await v213PublicLineAnswer(env as never, parseQuery(text)));
  /** The reply the Worker's real LINE event entry sends for one user message (fetch captures the LINE reply only). */
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

  it("keeps the compact consensus scenario on Top20 and full detail on existing detail/text routes", () => {
    const parsed = parsedDoc(CASE, SYMBOLS);
    const flex = JSON.stringify(buildBottleneckTop20Messages(parsed, "flex"));
    const text = JSON.stringify(buildBottleneckTop20Messages(parsed, "text"));
    const detailFlex = JSON.stringify(buildBottleneckDetail(parsed, "000660.KS", "flex"));
    const detailText = JSON.stringify(buildBottleneckDetail(parsed, "000660.KS", "text"));
    // V25-D4 merges the duplicate prefix into the remaining clause "情境：營收依上述推估實現，P/S股數不變；以最新已報四季為基準".
    expect(flex).toContain("分析師共識為第三方分析師估計平均，非公司財測、非官方");
    expect(flex).toContain(`若約6個月（2財季）達成${CONSENSUS_PRICE_LABEL}營收推估 → 股價情境`);
    expect(flex).toContain("情境：營收依上述推估實現，P/S股數不變；以最新已報四季為基準");
    expect(flex).toContain("分析師共識情境（非訂單）：無分析師共識可推算。");
    expect(flex).toContain("瓶頸詳情 000660.KS");
    expect(flex).toContain(KR_LABEL);
    expect(text).toContain(KR_LABEL);
    expect(text).toContain("非訂單");
    expect(text).toContain(`達成${CONSENSUS_PRICE_LABEL}營收推估 → 股價情境`);
    expect(text).not.toContain("公司營收財測＋模型");
    expect(detailFlex).toContain(KR_LABEL);
    expect(detailFlex).toContain("完整數據與網址");
    expect(detailText).toContain(KR_LABEL);
    expect(detailText).toContain(`達成${CONSENSUS_PRICE_LABEL}營收推估 → 股價情境`);
    expect(detailText).toContain("分析師共識（非官方，0q，至2026-09-30）");
    expect(detailText).toContain("https://query2.finance.yahoo.com/v10/finance/quoteSummary/000660.KS");
  });

  it("answers the TOP20 command and the company detail through the public LINE route", async () => {
    const env = await sealedEnv(rawDoc(CASE, SYMBOLS), { V213_LINE_PRESENTATION: "text" });
    const top20 = await answer(env, "TOP20");
    expect(top20).toContain("瓶頸爆發 TOP20（v3");
    expect(top20).toContain(KR_LABEL);
    expect(top20).toContain("分析師共識（非公司財測、非官方）｜Yahoo Finance，11 位分析師，截至 2026-09-28");
    const detail = await answer(env, "瓶頸詳情 000660.KS");
    expect(detail).toContain(KR_LABEL);
    expect(detail).toContain(`達成${CONSENSUS_PRICE_LABEL}營收推估 → 股價情境`);
  });

  it("answers the TOP20 command compactly and keeps full company consensus data reachable", async () => {
    const env = await sealedEnv(rawDoc(CASE, SYMBOLS));
    const carousel = await lineReply(env, "TOP20");
    expect(carousel).toContain('"type":"flex"');
    expect(carousel).toContain(KR_LABEL);
    expect(carousel).toContain("分析師共識為第三方分析師估計平均，非公司財測、非官方");
    expect(carousel).toContain("瓶頸詳情 000660.KS");
    const detail = await lineReply(env, "瓶頸詳情 000660.KS");
    expect(detail).toContain(KR_LABEL);
    expect(detail).not.toContain("公司營收財測＋模型");
    const detailText = await lineReply(env, "瓶頸詳情 000660.KS 文字");
    expect(detailText).toContain(KR_LABEL);
    expect(detailText).toContain(`達成${CONSENSUS_PRICE_LABEL}營收推估 → 股價情境`);
  });

  it("shows no consensus figure through the LINE entry when the sealed block is malformed (fail closed)", async () => {
    const raw = rawDoc(CASE, SYMBOLS);
    raw.top[1].outlook.order_forecast_v3.evidence.consensus.source_url = "https://example.com/quote";
    const env = await sealedEnv(raw);
    const detail = await lineReply(env, "瓶頸詳情 000660.KS");
    expect(detail).not.toContain(KR_LABEL);
    expect(detail).not.toContain("分析師共識（非公司財測、非官方）｜");
    expect(detail).toContain("資料未通過驗證");
    const other = await lineReply(env, "瓶頸詳情 005930.KS"); // the other issuers keep their own valid state
    expect(other).toContain("分析師共識（非公司財測、非官方）｜Yahoo Finance，25 位分析師");
  });

  it("states the expired route through the LINE entry (the quarter ended before the company reported)", async () => {
    const name = "quarter_ended";
    const { cutoff } = fixture.cases[name]!;
    vi.setSystemTime(Date.parse(cutoff) + 30 * 60_000);
    const env = await sealedEnv(rawDoc(name, ["000660.KS"]));
    const detail = await lineReply(env, "瓶頸詳情 000660.KS");
    expect(detail).toContain("公司未提供營收財測；分析師共識所估財季已結束");
    expect(detail).not.toContain("股價情境 +");
  });
});

/** sha256 of the rendering of every earlier sealed outlook by the reader at cb48779 (before the consensus route was turned on). */
const BASELINE_RENDERING_SHA256 = "8a4ca1e8f51e2e03edbbf56f95b518aa61c4995af2f054a62d138db9eb97ab6e";
