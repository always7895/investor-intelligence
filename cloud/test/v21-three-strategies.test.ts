// V21 (operator 2026-10-19), Worker half: validator for the additive `strategies` object, the three-strategy card, the zero-covered-call rule and
// the block-level degradation. Cycles come from the real Python producer on the synthetic chains of tests/fixtures/v21_put_chains.py
// (regenerate: `python -m tests.fixtures.v21_worker_cases`). Synthetic data only.
import { beforeEach, describe, expect, it, vi } from "vitest";
import fixture from "./fixtures/v21-three-strategies.json";
import { assertLineMessages, type LineOutboundMessage } from "../src/line-messages";
import { STRATEGY_DEGRADED_TEXT, buildCoveredCallMessages, validateCoveredCallCycle,
  type CoveredCallCycle, type CoveredCallSuggestion, type CspItem, type BuyStrategyLeg, type SellStrategyLeg, type CollarItem } from "../src/v213/covered-call";
import { BULLET_DOT_SIZE } from "../src/v213/line-theme";
import * as admission from "../src/v213/public-options-admission";
import { admitSyntheticTickers, resetAdmissionToReal } from "./synthetic-option-admission";

vi.mock("../src/v213/public-options-admission", async importOriginal => {
  const real = await importOriginal<typeof import("../src/v213/public-options-admission")>();
  return { ...real, admitPublicOption: vi.fn(real.admitPublicOption) };
});
beforeEach(() => { resetAdmissionToReal(); });

type Json = Record<string, any>;
const STAMP: string = fixture.stamp;
const NOW = Date.parse(STAMP) + 60_000;
const cases = fixture.cases as unknown as Record<string, Json>;
const clone = (name: string): Json => structuredClone(cases[name]!);
const check = (raw: unknown) => validateCoveredCallCycle(raw, NOW, STAMP, "monthly") as Json | null;
const render = (cycle: Json, style: "flex" | "text" = "flex") => {
  admitSyntheticTickers(cycle.ticker);
  return buildCoveredCallMessages(check(cycle) as never, "每月期權", style);
};
const bubbles = (messages: LineOutboundMessage[]): Json[] => messages.flatMap(message => message.type === "flex" ? (message.contents as Json).contents as Json[] : []);
const size = (value: unknown) => new TextEncoder().encode(JSON.stringify(value)).length;
const texts = (node: unknown, out: string[] = []): string[] => {
  if (Array.isArray(node)) node.forEach(child => texts(child, out));
  else if (node && typeof node === "object") {
    const record = node as Json;
    if (record.type === "text") {
      if (typeof record.text === "string") out.push(record.text);
      else if (Array.isArray(record.contents)) out.push((record.contents as Json[]).map(span => String(span.text ?? "")).join(""));
      return out;
    }
    Object.values(record).forEach(child => texts(child, out));
  }
  return out;
};
const joined = (node: unknown) => texts(node).join("\n").replace(/\s+/g, " ");
const unavailable = { unavailable: STRATEGY_DEGRADED_TEXT };
/** The full cycle with its covered call removed (the shape the producer emits when only the put side qualifies). */
const withoutCoveredCall = (): Json => {
  const cycle = clone("yahoo_monthly_full");
  cycle.suggestions = []; delete cycle.middle_suggestion;
  cycle.strategies = { cc: { unavailable: "本次回應有效買權不足，不提供備兌買權建議" }, ...cycle.strategies };
  return cycle;
};

describe("V21 validator: positives from the Python producer", () => {
  it("accepts the full Yahoo cycle, the covered-call-less cycle and the Nordic SEK cycle", () => {
    for (const name of Object.keys(cases)) {
      const cycle = check(clone(name));
      expect(cycle, name).not.toBeNull();
      expect(Object.keys(cycle!.strategies).sort(), name).toEqual(name === "yahoo_monthly_no_covered_call" ? ["cc", "collar", "csp"] : ["collar", "csp"]);
    }
    expect(check(clone("nordic_monthly_sek"))!.currency).toBe("SEK");
  });

  it("zero covered-call suggestions are allowed only beside a real csp or collar block and a cc unavailable block", () => {
    const cycle = withoutCoveredCall();
    expect(cycle.suggestions).toEqual([]);
    expect(check(cycle)).not.toBeNull();
    const cspOnly = withoutCoveredCall(); cspOnly.strategies.collar = { unavailable: "x" };
    expect(check(cspOnly)).not.toBeNull();
    const collarOnly = withoutCoveredCall(); collarOnly.strategies.csp = { unavailable: "x" };
    expect(check(collarOnly)).not.toBeNull();
    const nothingReal = withoutCoveredCall(); nothingReal.strategies.csp = { unavailable: "x" }; nothingReal.strategies.collar = { unavailable: "x" };
    expect(check(nothingReal)).toBeNull();
    const noCcBlock = withoutCoveredCall(); delete noCcBlock.strategies.cc;
    expect(check(noCcBlock)).toBeNull();
    const noStrategies = withoutCoveredCall(); delete noStrategies.strategies;
    expect(check(noStrategies)).toBeNull();
    const everyRealBlockBad = withoutCoveredCall(); everyRealBlockBad.strategies.csp.suggestions[0].premium_per_contract = 1;
    everyRealBlockBad.strategies.collar.put.strike = 120;  // the bad blocks degrade, nothing real is left: the cycle is invalid
    expect(check(everyRealBlockBad)).toBeNull();
    const ccBeside = clone("yahoo_monthly_full"); ccBeside.strategies.cc = { unavailable: "x" };
    expect(check(ccBeside)).toBeNull();  // a cc block beside real covered-call tiers is a contradiction
  });

  it("an old cycle without strategies is unchanged, and a malformed strategies value or unknown name never reaches the card", () => {
    const old = clone("yahoo_monthly_full"); delete old.strategies;
    expect(check(old)).toEqual(old);
    const wrongType = clone("yahoo_monthly_full"); wrongType.strategies = "x";
    const stripped = check(wrongType)!;
    expect(stripped).not.toBeNull();
    expect("strategies" in stripped).toBe(false);
    const unknown = clone("yahoo_monthly_full"); unknown.strategies.straddle = { suggestions: [] };
    expect(Object.keys(check(unknown)!.strategies).sort()).toEqual(["collar", "csp"]);
  });
});

describe("V21 validator: a bad block degrades alone", () => {
  const mutants: [string, (cycle: Json) => void, "csp" | "collar"][] = [
    ["csp strike above the spot", c => { c.strategies.csp.suggestions[0].strike = 101; }, "csp"],
    ["csp premium not limit x 100", c => { c.strategies.csp.suggestions[0].premium_per_contract += 5; }, "csp"],
    ["csp cash not strike x 100", c => { c.strategies.csp.suggestions[0].cash_required = 1; }, "csp"],
    ["csp annualized wrong", c => { c.strategies.csp.suggestions[0].annualized_yield = 0.9; }, "csp"],
    ["csp limit above the mid", c => { c.strategies.csp.suggestions[0].limit_price = 1.02; }, "csp"],
    ["csp delta below the band", c => { c.strategies.csp.suggestions[0].delta = 0.1; }, "csp"],
    ["csp delta above the band", c => { c.strategies.csp.suggestions[0].delta = 0.35; }, "csp"],
    ["csp unknown delta basis", c => { c.strategies.csp.suggestions[0].delta_basis = "GUESSED"; }, "csp"],
    ["csp extra key", c => { c.strategies.csp.suggestions[0].extra = 1; }, "csp"],
    ["csp missing key", c => { delete c.strategies.csp.suggestions[0].breakeven; }, "csp"],
    ["csp balanced strike not higher", c => { c.strategies.csp.suggestions[1].strike = 90; c.strategies.csp.suggestions[1].cash_required = 9000; }, "csp"],
    ["csp wrong roles", c => { c.strategies.csp.suggestions[0].role = "BALANCED"; }, "csp"],
    ["csp label mismatch", c => { c.strategies.csp.timestamp = "2026-09-30T16:00:00Z"; }, "csp"],
    ["csp label key missing", c => { delete c.strategies.csp.provider_id; }, "csp"],
    ["csp NaN-like string", c => { c.strategies.csp.suggestions[0].bid = "0.98"; }, "csp"],
    ["csp three items", c => { c.strategies.csp.suggestions.push(structuredClone(c.strategies.csp.suggestions[1])); }, "csp"],
    ["collar put above the spot", c => { c.strategies.collar.put.strike = 101; }, "collar"],
    ["collar put buy limit below the mid", c => { c.strategies.collar.put.limit_price = 0.59; }, "collar"],
    ["collar put delta outside the window", c => { c.strategies.collar.put.delta = 0.4; }, "collar"],
    ["collar call below the spot", c => { c.strategies.collar.items[0].call.strike = 99; }, "collar"],
    ["collar net wrong", c => { c.strategies.collar.items[0].net_premium_per_share = 5; }, "collar"],
    ["collar max loss wrong", c => { c.strategies.collar.items[0].max_loss_per_share = 1; }, "collar"],
    ["collar max gain wrong", c => { c.strategies.collar.items[0].max_gain_per_share = 99; }, "collar"],
    ["collar break-even wrong", c => { c.strategies.collar.items[0].break_even = 50; }, "collar"],
    ["collar worst case wrong", c => { c.strategies.collar.items[0].worst_case_net_per_share = 9; }, "collar"],
    ["collar balanced call not lower", c => { c.strategies.collar.items[1].call = structuredClone(c.strategies.collar.items[0].call); }, "collar"],
    ["collar put leg extra key", c => { c.strategies.collar.put.iv = 0.3; }, "collar"],
    ["collar label mismatch", c => { c.strategies.collar.rights_status = "reviewed_public_access"; }, "collar"],
    ["collar block that is an array", c => { c.strategies.collar = []; }, "collar"],
    ["unavailable plus data", c => { c.strategies.collar.unavailable = "x"; }, "collar"],
  ];
  for (const [name, mutate, which] of mutants) {
    it(`${name}: only that strategy becomes no data; the covered call and the other strategy survive`, () => {
      const original = clone("yahoo_monthly_full");
      const cycle = clone("yahoo_monthly_full");
      mutate(cycle);
      const out = check(cycle);
      expect(out, name).not.toBeNull();
      const other = which === "csp" ? "collar" : "csp";
      expect(out!.strategies[which]).toEqual(unavailable);
      expect(out!.strategies[other]).toEqual(original.strategies[other]);
      expect(out!.suggestions).toEqual(original.suggestions);
    });
  }

  it("a bad block renders a compact no-data overview and keeps the exact reason on Flex and text", () => {
    const cycle = clone("yahoo_monthly_full");
    cycle.strategies.csp.suggestions[0].premium_per_contract = 1;
    const list = bubbles(render(cycle));
    expect(list).toHaveLength(4);  // overview, covered call, collar, disclosure
    expect(joined(list[0])).toContain("無資料");
    expect(joined(list.at(-1))).toContain(STRATEGY_DEGRADED_TEXT);
    expect(joined(list[1])).toContain("建議一：高履約價");
    expect(joined(list[2])).toContain("領口策略");
    // V25-FIX3 inspects the actual joined reply, so a leaked CSP cash requirement cannot pass through an empty traversal.
    const visible = list.map(joined).join("\n");
    expect(visible).not.toMatch(/現金 \$[\d,.]+/);
    expect(joined(render(cycle, "text"))).toContain(`無資料：${STRATEGY_DEGRADED_TEXT}`);
  });
});

describe("V21 card", () => {
  const full = () => render(clone("yahoo_monthly_full"));

  it("is one flex message of five bubbles: overview, three strategies and shared disclosure", () => {
    const messages = full();
    expect(messages).toHaveLength(1);
    expect(messages[0]!.type).toBe("flex");
    const list = bubbles(messages);
    expect(list).toHaveLength(5);
    const headers = list.map(bubble => texts(bubble.header)[0]!);
    expect(headers[0]).toContain("三種保守期權策略");
    expect(headers[1]).toContain("備兌買權");
    expect(headers[2]).toContain("現金擔保賣權");
    expect(headers[3]).toContain("領口策略");
    expect(joined(list[4]!.header)).toContain("資料來源與說明");
    // overview: covered call, then the put, then the collar
    const overview = joined(list[0]);
    expect(overview.indexOf("備兌買權")).toBeLessThan(overview.indexOf("現金擔保賣權"));
    expect(overview.indexOf("現金擔保賣權")).toBeLessThan(overview.indexOf("領口策略"));
    expect(overview).toContain("可用策略");
    // conservative first inside each detail
    const csp = joined(list[2]);
    expect(csp.indexOf("保守型")).toBeLessThan(csp.indexOf("平衡型"));
    const collar = joined(list[3]);
    expect(collar.indexOf("保守型")).toBeLessThan(collar.indexOf("平衡型"));
  });

  it("keeps compact strategy figures and preserves complete same-reply qualifications", () => {
    const list = bubbles(full());
    const overview = joined(list[0]);
    const detail = joined(list);
    for (const expected of ["$94.00", "年化", "$107.00", "+$46.00", "以備妥現金計"]) expect(overview).toContain(expected);
    for (const expected of ["$1.00", "$100.00", "$9400.00", "$9600.00", "$92.00", "$107.00",
      "Bid $0.36", "中價 $0.38", "Ask $0.40", "Bid $0.98", "中價 $1.00", "Ask $1.02",
      "Bid $0.59", "中價 $0.61", "Ask $0.63", "Bid $1.05", "中價 $1.07", "Ask $1.09",
      "年化 13.9%（以備妥現金計）", "損益兩平 $93.00", "Delta 0.20", "Bid $0.98",
      "Bid $0.59", "Bid $1.05", "$754.00", "$746.00", "$99.54", "模型值，依報價隱含波動率"]) {
      expect(detail, expected).toContain(expected);
    }
    expect(JSON.stringify(list[0])).toContain("AAA 每月期權 文字");
    expect(overview).not.toContain("後續頁面");
    expect(joined(list[2])).toContain("以備妥現金計");
    expect(joined(list[3])).toContain("買賣相抵");
    const cc = joined(list[1]);
    expect(cc).toContain("Bid $0.36");
    expect(joined(list[4])).toContain("年化收益＝期間收益×365÷DTE");
    expect(joined(list)).toContain("模型值，依報價隱含波動率 30%");
    const text = joined(render(clone("yahoo_monthly_full"), "text"));
    for (const expected of ["$94.00", "$96.00", "$9400.00", "$9600.00", "損益兩平 $93.00", "$92.00", "$107.00",
      "每口淨權利金（收入）$46.00", "最大損失 $754.00／口", "最大獲利 $746.00／口", "保護賣權（買進）履約價 $92.00"]) {
      expect(text, expected).toContain(expected);
    }
  });

  it("keeps immediate warnings on each strategy and complete qualifications in the shared disclosure", () => {
    const cycle = clone("yahoo_monthly_full");
    admitSyntheticTickers(cycle.ticker);
    vi.mocked(admission.admitPublicOption).mockImplementation(() => ({ ok: true, provider_id: "synthetic-test-only-not-in-catalog", operator_accepted: true }) as never);
    const list = bubbles(buildCoveredCallMessages(check(cycle) as never, "每月期權", "flex"));
    const byEyebrow = (eyebrow: string) => {
      const found = list.filter(bubble => joined(bubble.header).includes(`${eyebrow} · `));
      expect(found, eyebrow).toHaveLength(1);
      return joined(found[0]);
    };
    expect(byEyebrow("備兌買權")).toContain("正股仍有下跌風險");
    expect(byEyebrow("現金擔保賣權")).toContain("損失可超過權利金");
    const collar = byEyebrow("領口策略");
    for (const required of ["每組100股＋買1口Put＋賣1口Call", "下跌有界、上漲封頂", "最大損失"])
      expect(collar).toContain(required);
    const disclosure = joined(list[list.length - 1]);
    for (const required of ["正股仍有下跌風險", "損失可大於權利金", "最大盈虧為到期估算"])
      expect(disclosure).toContain(required);
  });

  it("shares source, rights, capture time and quote rules in one final disclosure", () => {
    const cycle = clone("yahoo_monthly_full");
    admitSyntheticTickers(cycle.ticker);
    vi.mocked(admission.admitPublicOption).mockImplementation(() => ({ ok: true, provider_id: "synthetic-test-only-not-in-catalog", operator_accepted: true }) as never);
    const list = bubbles(buildCoveredCallMessages(check(cycle) as never, "每月期權", "flex"));
    const disclosure = joined(list[list.length - 1]);
    for (const required of ["資料來源與說明", "Yahoo Finance 期權鏈（非官方，延遲）", "10-24 01:00（台北）", "擷取時間",
      "依營運者決定顯示；本資料未取得再散布授權", "非投資建議", "不下單"])
      expect(disclosure).toContain(required);
    expect(list.filter(bubble => joined(bubble.header).includes("資料來源與說明"))).toHaveLength(1);
    for (const bubble of list.slice(0, -1)) {
      const footer = joined(bubble.footer);
      expect(footer).toContain("非投資建議");
      expect(footer).toContain("不下單");
      expect(footer).not.toContain(STAMP);
    }
    const text = joined(render(cycle, "text"));
    expect(text).toContain("被指派時需以履約價買進正股");
    expect(text).toContain("保護賣權需付權利金");
  });

  it("stays under the 46 KB packing size and the LINE altText limits", () => {
    const messages = full();
    expect(size(messages[0]!.type === "flex" ? (messages[0] as Json).contents : null)).toBeLessThan(46_000);
    const alt = (messages[0] as Json).altText as string;
    expect(Array.from(alt).length).toBeLessThanOrEqual(120);
    expect(alt.split("｜").length).toBeGreaterThanOrEqual(3);
    expect(alt).toContain("AAA");
    for (const bubble of bubbles(messages)) expect(size(bubble)).toBeLessThan(14_000);
  });

  it("density budget: bulleted, one disclosure line, no maxLines, specific button labels", () => {
    const list = bubbles(full()).slice(0, -1);
    const metrics = list.map(bubble => {
      let bullets = 0; let textCount = 0; let chars = 0; let maxLines = 0; let xxs = 0;
      const buttons: string[] = []; const commands: string[] = [];
      const walk = (node: any) => {
        if (Array.isArray(node)) { node.forEach(walk); return; }
        if (!node || typeof node !== "object") return;
        if (node.type === "button") { buttons.push(node.action.label); commands.push(node.action.text); return; }
        if (node.type === "box" && node.layout === "horizontal" && node.contents?.length === 2 && node.contents[0]?.width === BULLET_DOT_SIZE) bullets += 1;
        if (node.type === "text") {
          const text = typeof node.text === "string" ? node.text
            : Array.isArray(node.contents) ? node.contents.map((span: any) => String(span.text ?? "")).join("") : "";
          textCount += 1; chars += Array.from(text).length; if (node.maxLines) maxLines += 1; if (node.size === "xxs") xxs += 1; return;
        }
        Object.values(node).forEach(walk);
      };
      walk(bubble);
      return { bullets, textCount, chars, maxLines, xxs, buttons, commands };
    });
    // overview: three strategies of one hero figure and at most three bullets each, no more than three labelled disclosures
    expect(metrics[0]!.bullets).toBeLessThanOrEqual(9);
    expect(metrics[0]!.textCount).toBeLessThanOrEqual(36);
    expect(metrics[0]!.chars).toBeLessThanOrEqual(800);
    for (const item of metrics) {
      expect(item.maxLines).toBe(0);
      expect(item.xxs).toBeLessThanOrEqual(3 + 8);  // up to three disclosure labels plus section/footnote captions
      expect(item.textCount).toBeLessThanOrEqual(56);
      for (const label of item.buttons) {
        expect(Array.from(label).length).toBeLessThanOrEqual(20);
        expect(label).not.toMatch(/^(?:詳情|更多|詳細|查看)$/);
      }
    }
    expect(metrics[0]!.commands.join("|")).toContain("AAA 每月期權 文字");
    expect(metrics.slice(1).every(item => item.buttons.length >= 2)).toBe(true);
  });

  it("an old cycle keeps the covered call summary and exposes no-data reasons in text", () => {
    const old = clone("yahoo_monthly_full"); delete old.strategies;
    const list = bubbles(render(old));
    expect(list).toHaveLength(3);
    const overview = joined(list[0]);
    expect(overview.match(/無資料/g)).toHaveLength(2);
    const disclosure = joined(list.at(-1));
    expect(disclosure).toContain("無法判定賣權鏈或報價是否可用");
    expect(disclosure).not.toContain("未包含可核驗賣權鏈");
    expect(overview).toContain("備兌買權");
    expect(joined(list[1])).toContain("建議一：高履約價（不易被賣掉）");
    const text = joined(render(old, "text"));
    expect(text).toContain("無法判定賣權鏈或報價是否可用");
    expect(text).not.toContain("未包含可核驗賣權鏈");
    expect(text).toContain("備兌買權（持股賣出買權）");
  });

  it("a cycle without a covered call keeps the no-data label, with details reachable in the text edition", () => {
    const cycle = withoutCoveredCall();
    const list = bubbles(render(cycle));
    expect(list).toHaveLength(4);  // overview, put, collar, disclosure
    const overview = joined(list[0]);
    expect(overview).toContain("備兌買權");
    expect(overview).toContain("無資料");
    expect(joined(list.at(-1))).toContain("備兌買權】無資料：本次回應有效買權不足");
    expect(joined(list[1])).toContain("需備現金 $");
    expect(joined(list[2])).toContain("最大損失");
    expect(joined(render(cycle, "text"))).toContain("無資料：本次回應有效買權不足");
  });

  it("the Nordic SEK cycle prices every figure in SEK", () => {
    const list = bubbles(render(clone("nordic_monthly_sek")));
    expect(list).toHaveLength(5);
    expect(joined(list[2])).toContain("9400.00 SEK");
    expect(joined(list[3])).toContain("754.00 SEK");
    expect(joined(list[4])).toContain("Nasdaq Nordic");
  });

  it("the text edition lists all three strategies untruncated, with the standing disclaimers", () => {
    const cycle = clone("yahoo_monthly_full");
    admitSyntheticTickers(cycle.ticker);
    vi.mocked(admission.admitPublicOption).mockImplementation(() => ({ ok: true, provider_id: "synthetic-test-only-not-in-catalog", operator_accepted: true }) as never);
    const messages = buildCoveredCallMessages(check(cycle) as never, "每月期權", "text") as { type: "text"; text: string }[];
    expect(messages.length).toBeLessThanOrEqual(5);
    for (const message of messages) expect(message.text.length).toBeLessThanOrEqual(4900);
    const text = messages.map(message => message.text).join("");
    expect(text).toContain("【備兌買權建議｜AAA");
    for (const expected of ["現金擔保賣權", "領口策略", "需備現金 $9400.00", "最大損失 $754.00／口", "最大獲利 $746.00／口", "保護賣權（買進）履約價 $92.00"]) expect(text).toContain(expected);
    expect(text.indexOf("備兌買權")).toBeLessThan(text.indexOf("現金擔保賣權"));
    expect(text.indexOf("現金擔保賣權")).toBeLessThan(text.indexOf("領口策略"));
    expect(text).toContain("本服務不下單。");
    expect(text).toContain("10-24 01:00（台北）");
    expect(text).toContain("未取得再散布授權");
  });

  it("no advice or guarantee phrasing, and a denied public admission renders nothing", () => {
    const rendered = JSON.stringify(full());
    for (const forbidden of ["保證獲利", "一定賺", "建議買進", "建議你", "穩賺"]) expect(rendered).not.toContain(forbidden);
    vi.mocked(admission.admitPublicOption).mockImplementation(() => ({ ok: false }) as never);
    expect(() => buildCoveredCallMessages(check(clone("yahoo_monthly_full")) as never, "每月期權", "flex")).toThrow();
  });

  it("no card claims an annualized-yield floor (the 6% and then 2% floors were removed on 2026-11-03)", () => {
    const text = JSON.stringify(full());
    expect(text).toContain("不設年化收益下限");
    for (const stale of ["至少 2%", "至少 6%", "年化權利金至少"]) expect(text).not.toContain(stale);
  });
});

describe("Stage 1C producer bridge and observation boundaries", () => {
  // Parent regenerates the bridge: names describe input chains, not guaranteed observation-only outcomes.
  const observationFixture = fixture as unknown as { observations: Record<string, Json> };
  const observed = (name: string): Json => structuredClone(observationFixture.observations[name]!);
  const observationOnly = (): Json => {
    const raw = clone("yahoo_monthly_full");
    const call = raw.suggestions[0];
    raw.quote_observation = { kind: "TWO_SIDED", strike: call.strike, bid: call.bid, ask: call.ask,
      last: null, annualized_yield: call.bid / raw.spot * 365 / Math.max(raw.dte, 1), oi: call.oi, volume: call.volume };
    raw.suggestions = [];
    delete raw.middle_suggestion;
    raw.strategies = { cc: { unavailable: "買權 Delta 超出保守範圍" },
      csp: { unavailable: "無該到期的賣權報價" }, collar: { unavailable: "無該到期的賣權報價" } };
    return raw;
  };

  it.each(["wide_all", "wide_calls", "no_two_sided_put", "absent_puts", "unknown_puts", "delta_call", "collar_only"])(
    "%s renders every independently available strategy and preserves remaining reasons", name => {
      const raw = observed(name);
      const valid = check(raw);
      expect(valid).not.toBeNull();
      expect(valid!.strategies).toEqual(raw.strategies);
      for (const style of ["text", "flex"] as const) {
        const visible = joined(render(raw, style));
        expect(visible).toContain(raw.expiry);
        for (const strategy of ["cc", "csp", "collar"]) {
          const reason = raw.strategies?.[strategy]?.unavailable;
          if (reason) expect(visible).toContain(reason);
        }
        expect(visible).not.toContain("買賣價差大於中價");
        if (raw.suggestions.length) {
          expect(visible).toContain("LIMIT");
          expect(visible).toContain("Bid情境");
        }
      }
    });

  it("wide quotes no longer force observation-only, and a missing put Bid degrades only the selling strategy", () => {
    const wide = check(observed("wide_all"))!;
    expect(wide.suggestions.length).toBeGreaterThan(0);
    expect(wide.strategies.csp.suggestions.length).toBeGreaterThan(0);
    expect(wide.strategies.collar.items.length).toBeGreaterThan(0);
    const oneSided = check(observed("no_two_sided_put"))!;
    expect(oneSided.strategies.csp.unavailable).toContain("Bid");
    expect(oneSided.strategies.collar.put.bid).toBeNull();
    expect(oneSided.strategies.collar.put.ask).toBeGreaterThan(0);
  });

  it("routes a qualified put beside a call observation through the shared recommendation cards", () => {
    const mixed = observed("delta_call");
    expect(mixed.quote_observation).toBeDefined();
    expect(mixed.suggestions).toEqual([]);
    const cards = bubbles(render(mixed, "flex"));
    expect(joined(cards[0])).toContain("可用策略");
    expect(joined(cards.at(-1))).toContain("資料來源與說明");
    const visible = joined(cards);
    expect(visible).toContain(mixed.strategies.cc.unavailable);
    expect(visible).toContain("現金擔保賣權");
    expect(visible).toContain("建議賣出限價");
    expect(visible).toContain("Bid情境");
    expect(joined(render(mixed, "text"))).toContain("建議賣出限價");
    const observationCards = bubbles(render(observationOnly(), "flex"));
    expect(joined(observationCards[0])).toContain("報價觀察");
    expect(joined(observationCards)).not.toContain("建議賣出限價");
  });

  it("does not infer put-chain absence from omitted metadata or an omitted strategy block", () => {
    const raw = observationOnly();
    delete raw.strategies;
    for (const style of ["text", "flex"] as const) {
      const visible = joined(render(raw, style));
      expect(visible).toContain("無法判定賣權鏈或報價是否可用");
      expect(visible).not.toContain("未包含可核驗賣權鏈");
    }
  });

  it("keeps monthly observation validation, freshness and precise independent reasons", () => {
    const raw = observationOnly();
    expect(check(raw)).not.toBeNull();
    for (const style of ["text", "flex"] as const) {
      const visible = joined(render(raw, style));
      for (const name of ["cc", "csp", "collar"]) expect(visible).toContain(raw.strategies[name].unavailable);
    }
    for (const mutate of [
      (row: Json) => { delete row.quote_observation; },
      (row: Json) => { row.quote_observation.annualized_yield = 99; },
      (row: Json) => { delete row.strategies.cc; },
      (row: Json) => { row.strategies.cc.unavailable = ""; },
      (row: Json) => { row.strategies.cc.unavailable = "x".repeat(201); },
    ]) {
      const bad = observationOnly(); mutate(bad);
      expect(check(bad)).toBeNull();
    }
    expect(validateCoveredCallCycle(raw, NOW, STAMP, "weekly")).toBeNull();
    expect(validateCoveredCallCycle(raw, NOW + 7 * 3600_000, STAMP, "monthly")).toBeNull();
    raw.strategies.csp = { unavailable: "x", suggestions: [] };
    const kept = check(raw)!;
    expect(kept.strategies.csp).toEqual(unavailable);
    expect(kept.strategies.cc).toEqual(raw.strategies.cc);
    expect(kept.strategies.collar).toEqual(raw.strategies.collar);
  });
});

/** Independent, real-shaped wide quotes; no generated fixture or producer algorithm is used here. */
function wideRecommendation(currency: "USD" | "SEK" = "SEK") {
  const cycle = validateCoveredCallCycle(clone("yahoo_monthly_full"), NOW, STAMP, "monthly")!;
  cycle.currency = currency;
  cycle.spot = 16.2;
  const days = Math.max(cycle.dte, 1);
  const cc = (role: CoveredCallSuggestion["role"], strike: number, delta: number): CoveredCallSuggestion => ({
    role, strike, bid: 0.5, ask: 2.5, mid: 1.5, limit_price: 1.5, premium_per_contract: 150,
    period_yield: 1.5 / cycle.spot, annualized_yield: 1.5 / cycle.spot * 365 / days,
    upside_to_strike: strike / cycle.spot - 1, delta, delta_basis: "QUOTED", iv: null,
    oi: null, volume: null, spread_pct: 0, // a finite but false supplied percentage must never drive the display
  });
  cycle.suggestions = [cc("HIGH_STRIKE", 18, 0.2), cc("BALANCED", 16.4, 0.3)];
  cycle.middle_suggestion = cc("MIDDLE", 17, 0.25);
  delete cycle.quote_observation;
  const cspItem = (role: CspItem["role"], strike: number): CspItem => ({
    role, strike, bid: 0.4, ask: 2.4, limit_price: 1.4, delta: 0.25, delta_basis: "QUOTED",
    premium_per_contract: 140, cash_required: strike * 100, annualized_yield: 1.4 / strike * 365 / days,
    breakeven: strike - 1.4, downside_buffer: 1 - strike / cycle.spot,
  });
  const put: BuyStrategyLeg = { strike: 14, bid: 0.1, ask: 1.1, limit_price: 0.6, delta: 0.15, delta_basis: "QUOTED" };
  const collarItem = (role: CollarItem["role"], strike: number): CollarItem => {
    const call: SellStrategyLeg = { strike, bid: 0.5, ask: 2.5, limit_price: 1.5, delta: 0.25, delta_basis: "QUOTED" };
    return { role, call, net_premium_per_share: 0.9, max_loss_per_share: cycle.spot - put.strike - 0.9,
      max_gain_per_share: strike - cycle.spot + 0.9, break_even: cycle.spot - 0.9, worst_case_net_per_share: -0.6 };
  };
  const label = { rights_status: cycle.rights_status, provider_id: cycle.provider_id!, quote_basis: cycle.quote_basis, timestamp: cycle.timestamp };
  const csp = { ...label, suggestions: [cspItem("CONSERVATIVE", 15), cspItem("BALANCED", 16)] };
  const collar = { ...label, put, items: [collarItem("CONSERVATIVE", 18), collarItem("BALANCED", 17)] };
  cycle.strategies = { csp, collar };
  return { cycle, csp, collar };
}

function repriceRecommendation(cycle: CoveredCallCycle) {
  const days = Math.max(cycle.dte, 1);
  for (const item of [...cycle.suggestions, ...(cycle.middle_suggestion ? [cycle.middle_suggestion] : [])]) {
    item.premium_per_contract = item.limit_price * 100;
    item.period_yield = item.limit_price / cycle.spot;
    item.annualized_yield = item.period_yield * 365 / days;
  }
  const csp = cycle.strategies?.csp;
  if (csp && "suggestions" in csp) for (const item of csp.suggestions) {
    item.premium_per_contract = item.limit_price * 100;
    item.annualized_yield = item.limit_price / item.strike * 365 / days;
    item.breakeven = item.strike - item.limit_price;
  }
  const collar = cycle.strategies?.collar;
  if (collar && "items" in collar) for (const item of collar.items) {
    const net = item.call.limit_price - collar.put.limit_price;
    item.net_premium_per_share = net;
    item.max_loss_per_share = cycle.spot - collar.put.strike - net;
    item.max_gain_per_share = item.call.strike - cycle.spot + net;
    item.break_even = cycle.spot - net;
    item.worst_case_net_per_share = item.call.bid - collar.put.ask;
  }
}

describe("Stage 1C nullable executable sides and visible LIMIT scenarios", () => {
  it.each([
    { currency: "USD", period: "monthly" }, { currency: "SEK", period: "monthly" },
    { currency: "USD", period: "weekly" }, { currency: "SEK", period: "weekly" },
  ] as const)("$currency $period shares every tier's rule, real spread and numeric economics in Text and Flex", ({ currency, period }) => {
    const { cycle, csp, collar } = wideRecommendation(currency);
    if (period === "weekly") {
      cycle.dte = 7; cycle.expiry = "2026-10-30"; cycle.weekly_week = "NEXT";
      delete cycle.monthly_rule;
      repriceRecommendation(cycle);
    }
    const valid = validateCoveredCallCycle(cycle, NOW, STAMP, period)!;
    expect(valid).not.toBeNull();
    admitSyntheticTickers(cycle.ticker);
    const label = period === "weekly" ? "每週期權" : "每月期權";
    const flex = buildCoveredCallMessages(valid, label, "flex");
    const text = buildCoveredCallMessages(valid, label, "text");
    for (const messages of [flex, text]) assertLineMessages(messages);
    const pages = bubbles(flex);
    expect(pages).toHaveLength(5);
    const money = (value: number) => currency === "USD" ? `$${value.toFixed(2)}` : `${value.toFixed(2)} SEK`;
    const rate = (value: number) => `${(value * 365 / Math.max(cycle.dte, 1) * 100).toFixed(1)}%`;
    const visibleText = joined(text);
    for (const [index, count] of [[1, 3], [2, 2], [3, 2]]) {
      const visibleFlex = joined(pages[index!]);
      expect(visibleFlex.match(/Bid情境/g)).toHaveLength(count!);
      expect(visibleFlex.match(/未成交每次降0\.01/g)).toHaveLength(count!);
      for (const line of texts(pages[index!]!.body).flatMap(value => value.split("\n"))) {
        if (line.includes("Bid情境") || line.includes("LIMIT") || line.includes("價差占中價"))
          expect(visibleText).toContain(line);
      }
      expect(visibleFlex).toContain("流動性警示");
      expect(visibleFlex).toContain("不低於Bid");
    }
    for (const visible of [joined(flex), visibleText]) {
      for (const expected of ["價差占中價 133%", "價差占中價 143%", "價差占中價 167%",
        `LIMIT每口權利金 ${money(150)}`, `Bid情境：每口權利金 ${money(50)}`,
        `年化 ${rate(1.5 / cycle.spot)}`, `年化 ${rate(0.5 / cycle.spot)}`,
        `LIMIT每口權利金 ${money(140)}`, `Bid情境：每口權利金 ${money(40)}`,
        `年化 ${rate(1.4 / csp.suggestions[0]!.strike)}`, `年化 ${rate(0.4 / csp.suggestions[0]!.strike)}`,
        `LIMIT每口淨權利金（收入）${money(90)}`, `每口淨權利金 -${money(60)}`,
        `淨權利金年化 ${rate(0.9 / cycle.spot)}`, `淨權利金年化 ${rate(-0.6 / cycle.spot)}`,
        "Call Bid－Put Ask", "不高於Ask", "非保證", "非投資建議", "不下單"]) expect(visible).toContain(expected);
      expect(visible).not.toContain("四分之一");
      expect(visible).not.toContain("價差占中價 0%");
    }
    expect(collar.put.ask).not.toBe(collar.put.bid);
    expect(size(flex[0]!.type === "flex" ? flex[0]!.contents : null)).toBeLessThan(46_000);
    for (const page of pages) expect(size(page)).toBeLessThan(14_000);
  });

  it("accepts missing opposite sides at the real executable reference without inventing mid, spread or Greeks", () => {
    const { cycle, csp, collar } = wideRecommendation();
    for (const item of [...cycle.suggestions, cycle.middle_suggestion!]) {
      item.ask = null; item.mid = null; item.spread_pct = null; item.limit_price = item.bid;
    }
    for (const item of csp.suggestions) { item.ask = null; item.limit_price = item.bid; }
    collar.put.bid = null; collar.put.limit_price = collar.put.ask;
    for (const item of collar.items) { item.call.ask = null; item.call.limit_price = item.call.bid; }
    repriceRecommendation(cycle);
    const valid = validateCoveredCallCycle(cycle, NOW, STAMP, "monthly")!;
    expect(valid).toEqual(cycle);
    admitSyntheticTickers(cycle.ticker);
    for (const style of ["text", "flex"] as const) {
      const visible = joined(buildCoveredCallMessages(valid, "每月期權", style));
      for (const expected of ["Ask 未提供", "Bid 未提供", "中價 未提供", "中價／價差無法計算", "Delta 0.20", "Call Bid－Put Ask"])
        expect(visible).toContain(expected);
      expect(visible).not.toMatch(/NaN|Infinity|價差占中價 0%|由買賣報價反推/);
    }
    const high = cycle.suggestions[0]!;
    high.delta_basis = "QUOTE_IMPLIED";
    expect(validateCoveredCallCycle(cycle)).toBeNull();
    high.delta_basis = "QUOTED";
    csp.suggestions[0]!.delta_basis = "QUOTE_IMPLIED";
    expect(validateCoveredCallCycle(cycle)!.strategies!.csp).toEqual(unavailable);
    expect(validateCoveredCallCycle(cycle)!.strategies!.collar).toEqual(collar);
  });

  it.each([null, undefined, 0, -1, NaN, Infinity, "1", true])("rejects unusable required sides (%s) and preserves independent valid legs", bad => {
    const { cycle, csp, collar } = wideRecommendation();
    const cc = structuredClone(cycle);
    Object.assign(cc.suggestions[0]!, { bid: bad });
    expect(validateCoveredCallCycle(cc)).toBeNull();
    Object.assign(csp.suggestions[0]!, { bid: bad });
    let valid = validateCoveredCallCycle(cycle)!;
    expect(valid.strategies!.csp).toEqual(unavailable);
    expect(valid.strategies!.collar).toEqual(collar);
    const badCall = wideRecommendation();
    Object.assign(badCall.collar.items[0]!.call, { bid: bad });
    expect(validateCoveredCallCycle(badCall.cycle)!.strategies!.collar).toEqual(unavailable);
    expect(validateCoveredCallCycle(badCall.cycle)!.strategies!.csp).toEqual(badCall.csp);
    Object.assign(collar.put, { ask: bad });
    valid = validateCoveredCallCycle(cycle)!;
    expect(valid.strategies!.collar).toEqual(unavailable);
    expect(valid.suggestions).toEqual(cycle.suggestions);
  });

  it.each([undefined, 0, -1, NaN, Infinity, "1", true])("rejects malformed opposite sides (%s), not just the required side", bad => {
    const { cycle, csp, collar } = wideRecommendation();
    const cc = structuredClone(cycle);
    Object.assign(cc.suggestions[0]!, { ask: bad });
    expect(validateCoveredCallCycle(cc)).toBeNull();
    Object.assign(csp.suggestions[0]!, { ask: bad });
    Object.assign(collar.put, { bid: bad });
    const valid = validateCoveredCallCycle(cycle)!;
    expect(valid.strategies!.csp).toEqual(unavailable);
    expect(valid.strategies!.collar).toEqual(unavailable);
  });

  it("keeps strict quote bounds, arithmetic, cent-exact strikes, delta and OTM on very wide quotes", () => {
    for (const mutate of [
      (row: CoveredCallCycle) => { row.suggestions[0]!.ask = 0.4; },
      (row: CoveredCallCycle) => { row.suggestions[0]!.mid = null; },
      (row: CoveredCallCycle) => { row.suggestions[0]!.delta = 0.2001; },
      (row: CoveredCallCycle) => { row.suggestions[0]!.delta = null; },
      (row: CoveredCallCycle) => { row.suggestions[0]!.strike = 16.2; },
      (row: CoveredCallCycle) => { row.suggestions[0]!.strike = 18.001; },
      (row: CoveredCallCycle) => { row.suggestions[0]!.annualized_yield += 0.1; },
      (row: CoveredCallCycle) => { row.suggestions[0]!.limit_price = 0.4999999999; repriceRecommendation(row); },
      (row: CoveredCallCycle) => { row.suggestions[0]!.limit_price = 1.51; repriceRecommendation(row); },
    ]) {
      const { cycle } = wideRecommendation(); mutate(cycle);
      expect(validateCoveredCallCycle(cycle)).toBeNull();
    }
    const { cycle, csp, collar } = wideRecommendation();
    csp.suggestions[0]!.strike = 15.001;
    collar.put.limit_price = collar.put.ask + 1e-10;
    repriceRecommendation(cycle);
    const valid = validateCoveredCallCycle(cycle)!;
    expect(valid.strategies!.csp).toEqual(unavailable);
    expect(valid.strategies!.collar).toEqual(unavailable);
  });

  it("accepts bounded midpoint rounding and off-tick edge clamps but never an outside-quote limit", () => {
    for (const [bid, ask, sell, buy] of [[0.5, 2.51, 1.5, 1.51], [0.505, 0.506, 0.505, 0.506], [0.5, 0.5, 0.5, 0.5]]) {
      const { cycle, csp, collar } = wideRecommendation();
      Object.assign(cycle.suggestions[0]!, { bid, ask, mid: (bid! + ask!) / 2, limit_price: sell });
      Object.assign(csp.suggestions[0]!, { bid, ask, limit_price: sell });
      Object.assign(collar.put, { bid, ask, limit_price: buy });
      repriceRecommendation(cycle);
      expect(validateCoveredCallCycle(cycle)).not.toBeNull();
      Object.assign(cycle.suggestions[0]!, { limit_price: ask! + 1e-10 });
      repriceRecommendation(cycle);
      expect(validateCoveredCallCycle(cycle)).toBeNull();
    }
  });

  it("does not round visible subcent quotes or limits outside their actual executable boundaries", () => {
    const { cycle, csp, collar } = wideRecommendation("USD");
    const bid = 0.005049, ask = 0.00505;
    for (const item of [...cycle.suggestions, cycle.middle_suggestion!])
      Object.assign(item, { bid, ask, mid: (bid + ask) / 2, limit_price: bid });
    for (const item of csp.suggestions) Object.assign(item, { bid, ask, limit_price: bid });
    for (const item of collar.items) Object.assign(item.call, { bid, ask, limit_price: bid });
    Object.assign(collar.put, { bid, ask, limit_price: ask });
    repriceRecommendation(cycle);
    const valid = validateCoveredCallCycle(cycle, NOW, STAMP, "monthly")!;
    expect(valid).not.toBeNull();
    admitSyntheticTickers(cycle.ticker);
    for (const style of ["text", "flex"] as const) {
      const messages = buildCoveredCallMessages(valid, "每月期權", style);
      assertLineMessages(messages);
      const visible = joined(messages);
      for (const expected of ["Bid $0.005049", "Ask $0.00505", "中價 $0.0050495",
        "建議賣出限價 $0.005049", "建議買入限價 $0.00505"]) expect(visible).toContain(expected);
      expect(visible).not.toContain("建議賣出限價 $0.01");
      expect(visible).not.toContain("建議買入限價 $0.01");
    }
  });

  it("one-sided quotes refuse invented midpoint/spread and prices above their executable reference", () => {
    for (const patch of [{ mid: 0.5 }, { spread_pct: 0 }, { limit_price: 0.51 }, { delta_basis: null }]) {
      const { cycle } = wideRecommendation();
      Object.assign(cycle.suggestions[0]!, { ask: null, mid: null, spread_pct: null, limit_price: 0.5 }, patch);
      repriceRecommendation(cycle);
      expect(validateCoveredCallCycle(cycle)).toBeNull();
    }
  });

  it("validates cent-rounded contract premiums at an off-tick Bid clamp without loosening other arithmetic", () => {
    const { cycle, csp } = wideRecommendation();
    Object.assign(cycle.suggestions[0]!, { bid: 0.005049, ask: 0.00505, mid: 0.0050495, limit_price: 0.005049 });
    Object.assign(csp.suggestions[0]!, { bid: 0.005049, ask: 0.00505, limit_price: 0.005049 });
    repriceRecommendation(cycle);
    cycle.suggestions[0]!.premium_per_contract = 0.5;
    csp.suggestions[0]!.premium_per_contract = 0.5;
    const valid = validateCoveredCallCycle(cycle)!;
    expect(valid).not.toBeNull();
    expect(valid.strategies!.csp).toEqual(csp);
    cycle.suggestions[0]!.premium_per_contract = 0.49;
    expect(validateCoveredCallCycle(cycle)).toBeNull();
    cycle.suggestions[0]!.premium_per_contract = 0.5;
    csp.suggestions[0]!.annualized_yield += 0.001;
    expect(validateCoveredCallCycle(cycle)!.strategies!.csp).toEqual(unavailable);
  });

  it.each(["put", "call"] as const)("refuses a one-sided collar %s claiming midpoint-implied Greeks without discarding CSP", side => {
    const { cycle, csp, collar } = wideRecommendation();
    if (side === "put") Object.assign(collar.put, { bid: null, limit_price: collar.put.ask, delta_basis: "QUOTE_IMPLIED" });
    else Object.assign(collar.items[0]!.call, { ask: null, limit_price: collar.items[0]!.call.bid, delta_basis: "QUOTE_IMPLIED" });
    repriceRecommendation(cycle);
    const valid = validateCoveredCallCycle(cycle)!;
    expect(valid.strategies!.collar).toEqual(unavailable);
    expect(valid.strategies!.csp).toEqual(csp);
  });

  it("never admits a one-sided live recommendation as a two-sided previous-session capture", () => {
    for (const side of ["cc", "middle", "csp", "put", "call"] as const) {
      const { cycle, csp, collar } = wideRecommendation("USD");
      cycle.quote_basis = "previous_session_last";
      cycle.asof_date = STAMP.slice(0, 10);
      csp.quote_basis = cycle.quote_basis; collar.quote_basis = cycle.quote_basis;
      const options = { allowPreviousSession: true };
      expect(validateCoveredCallCycle(cycle, NOW, STAMP, "monthly", options)).not.toBeNull();
      if (side === "cc") Object.assign(cycle.suggestions[0]!, { ask: null, mid: null, spread_pct: null, limit_price: 0.5 });
      if (side === "middle") Object.assign(cycle.middle_suggestion!, { ask: null, mid: null, spread_pct: null, limit_price: 0.5 });
      if (side === "csp") Object.assign(csp.suggestions[0]!, { ask: null, limit_price: 0.4 });
      if (side === "put") Object.assign(collar.put, { bid: null, limit_price: 1.1 });
      if (side === "call") Object.assign(collar.items[0]!.call, { ask: null, limit_price: 0.5 });
      repriceRecommendation(cycle);
      expect(validateCoveredCallCycle(cycle, NOW, STAMP, "monthly", options)).toBeNull();
      cycle.quote_basis = "delayed"; csp.quote_basis = "delayed"; collar.quote_basis = "delayed";
      expect(validateCoveredCallCycle(cycle, NOW, STAMP, "monthly")).not.toBeNull();
    }
  });
});
