// V21 (operator 2026-10-19), Worker half: validator for the additive `strategies` object, the three-strategy card, the zero-covered-call rule and
// the block-level degradation. Cycles come from the real Python producer on the synthetic chains of tests/fixtures/v21_put_chains.py
// (regenerate: `python -m tests.fixtures.v21_worker_cases`). Synthetic data only.
import { beforeEach, describe, expect, it, vi } from "vitest";
import fixture from "./fixtures/v21-three-strategies.json";
import type { LineOutboundMessage } from "../src/line-messages";
import { STRATEGY_DEGRADED_TEXT, buildCoveredCallMessages, validateCoveredCallCycle } from "../src/v213/covered-call";
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
    if (record.type === "text") out.push(String(record.text));
    Object.values(record).forEach(child => texts(child, out));
  }
  return out;
};
const joined = (node: unknown) => texts(node).join("\n");
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

  it("a bad block renders as 無資料 in the overview and has no detail bubble; the good ones keep theirs", () => {
    const cycle = clone("yahoo_monthly_full");
    cycle.strategies.csp.suggestions[0].premium_per_contract = 1;
    const list = bubbles(render(cycle));
    expect(list).toHaveLength(3);  // overview, covered call, collar
    expect(joined(list[0])).toContain(`無資料：${STRATEGY_DEGRADED_TEXT}`);
    expect(joined(list[1])).toContain("建議一：高履約價");
    expect(joined(list[2])).toContain("領口策略");
    expect(list.map(joined).join("\n")).not.toContain("需備現金");
  });
});

describe("V21 card", () => {
  const full = () => render(clone("yahoo_monthly_full"));

  it("is one flex message of four bubbles: overview, covered call, cash-secured put, collar; each ordered conservative first", () => {
    const messages = full();
    expect(messages).toHaveLength(1);
    expect(messages[0]!.type).toBe("flex");
    const list = bubbles(messages);
    expect(list).toHaveLength(4);
    const headers = list.map(bubble => texts(bubble.header)[0]!);
    expect(headers[0]).toContain("三種保守期權策略");
    expect(headers[1]).toContain("備兌買權");
    expect(headers[2]).toContain("現金擔保賣權");
    expect(headers[3]).toContain("領口策略");
    // overview: covered call, then the put, then the collar
    const overview = joined(list[0]);
    expect(overview.indexOf("備兌買權（持股賣出買權）")).toBeLessThan(overview.indexOf("現金擔保賣權"));
    expect(overview.indexOf("現金擔保賣權")).toBeLessThan(overview.indexOf("領口策略"));
    // conservative first inside each detail
    const csp = joined(list[2]);
    expect(csp.indexOf("保守型")).toBeLessThan(csp.indexOf("平衡型"));
    const collar = joined(list[3]);
    expect(collar.indexOf("保守型")).toBeLessThan(collar.indexOf("平衡型"));
  });

  it("shows the prices: strikes, limits, premium, cash required, net premium, max loss and max gain", () => {
    const list = bubbles(full());
    const overview = joined(list[0]);
    for (const expected of ["$94.00", "$1.00", "$100.00", "$9400.00", "年化", "$92.00", "$107.00", "$46.00", "$754.00", "$746.00"]) expect(overview, expected).toContain(expected);
    const csp = joined(list[2]);
    for (const expected of ["履約價", "$94.00", "$96.00", "$9400.00", "$9600.00", "損益兩平", "$93.00", "Delta 0.20"]) expect(csp, expected).toContain(expected);
    const collar = joined(list[3]);
    for (const expected of ["保護賣權", "$92.00", "$0.61", "$107.00", "$1.07", "$46.00", "$754.00", "$746.00", "$99.54", "每口淨權利金（收入）"]) expect(collar, expected).toContain(expected);
    expect(joined(list[1])).toContain("$112.00");
  });

  it("every bubble carries the source and rights label, the quote basis and the capture timestamp, in one disclosure line", () => {
    const cycle = clone("yahoo_monthly_full");
    admitSyntheticTickers(cycle.ticker);
    vi.mocked(admission.admitPublicOption).mockImplementation(() => ({ ok: true, provider_id: "synthetic-test-only-not-in-catalog", operator_accepted: true }) as never);
    const list = bubbles(buildCoveredCallMessages(check(cycle) as never, "每月期權", "flex"));
    for (const bubble of list) {
      const footer = texts(bubble.footer).join("\n");
      expect(footer).toContain("來源：Yahoo Finance");
      expect(footer).toContain(STAMP);
      expect(footer).toContain("擷取時間");
      expect(footer).toContain("依營運者決定顯示；本資料未取得再散布授權");
      expect(footer).toContain("非個人化投資建議");
      expect(footer).toContain("本服務不下單");
      expect(texts(bubble.footer).filter(text => text.includes("來源："))).toHaveLength(1);
    }
    const strategyBubbles = list.slice(2).map(bubble => texts(bubble.footer).join("\n"));
    expect(strategyBubbles[0]).toContain("被指派時需以履約價買進正股");
    expect(strategyBubbles[1]).toContain("保護賣權需付權利金");
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
    const list = bubbles(full());
    const metrics = list.map(bubble => {
      let bullets = 0; let textCount = 0; let chars = 0; let maxLines = 0; let xxs = 0;
      const buttons: string[] = [];
      const walk = (node: any) => {
        if (Array.isArray(node)) { node.forEach(walk); return; }
        if (!node || typeof node !== "object") return;
        if (node.type === "button") { buttons.push(node.action.label); return; }
        if (node.type === "box" && node.layout === "horizontal" && node.contents?.length === 2 && node.contents[0]?.width === BULLET_DOT_SIZE) bullets += 1;
        if (node.type === "text") { textCount += 1; chars += Array.from(node.text).length; if (node.maxLines) maxLines += 1; if (node.size === "xxs") xxs += 1; return; }
        Object.values(node).forEach(walk);
      };
      walk(bubble);
      return { bullets, textCount, chars, maxLines, xxs, buttons };
    });
    // overview: three strategies of one hero figure and at most three bullets each, one disclosure line
    expect(metrics[0]!.bullets).toBeLessThanOrEqual(9);
    expect(metrics[0]!.textCount).toBeLessThanOrEqual(34);
    expect(metrics[0]!.chars).toBeLessThanOrEqual(800);
    for (const item of metrics) {
      expect(item.maxLines).toBe(0);
      expect(item.xxs).toBeLessThanOrEqual(1 + 8);  // the single disclosure line plus section/footnote captions
      expect(item.textCount).toBeLessThanOrEqual(56);
      for (const label of item.buttons) {
        expect(Array.from(label).length).toBeLessThanOrEqual(20);
        expect(label).not.toMatch(/^(?:詳情|更多|詳細|查看)$/);
      }
    }
    expect(metrics[0]!.buttons.join("|")).toContain("AAA 完整報價與出處");
    // only the overview carries buttons; the detail bubbles end with their one disclosure line
    expect(metrics.slice(1).every(item => item.buttons.length === 0)).toBe(true);
    for (const bubble of list) expect(texts(bubble.footer).filter(text => text.includes("來源：") && text.includes(STAMP))).toHaveLength(1);
  });

  it("an old cycle without strategies renders the covered call plus two no-data rows with a short reason", () => {
    const old = clone("yahoo_monthly_full"); delete old.strategies;
    const list = bubbles(render(old));
    expect(list).toHaveLength(2);
    const overview = joined(list[0]);
    expect(overview.match(/無資料：此筆為舊版資料，未含此策略報價/g)).toHaveLength(2);
    expect(overview).toContain("備兌買權（持股賣出買權）");
    expect(joined(list[1])).toContain("建議一：高履約價（不易被賣掉）");
  });

  it("a cycle without a covered call shows it as no data with the producer's reason and keeps three bubbles", () => {
    const cycle = withoutCoveredCall();
    const list = bubbles(render(cycle));
    expect(list).toHaveLength(3);  // overview, put, collar
    const overview = joined(list[0]);
    expect(overview).toContain("無資料：");
    expect(overview).toContain("需備現金");
    expect(overview).toContain("最大損失");
  });

  it("the Nordic SEK cycle prices every figure in SEK", () => {
    const list = bubbles(render(clone("nordic_monthly_sek")));
    expect(list).toHaveLength(4);
    expect(joined(list[2])).toContain("9400.00 SEK");
    expect(joined(list[3])).toContain("754.00 SEK");
    expect(joined(list[0])).toContain("Nasdaq Nordic");
  });

  it("the text edition lists all three strategies untruncated, with the standing disclaimers", () => {
    const cycle = clone("yahoo_monthly_full");
    admitSyntheticTickers(cycle.ticker);
    vi.mocked(admission.admitPublicOption).mockImplementation(() => ({ ok: true, provider_id: "synthetic-test-only-not-in-catalog", operator_accepted: true }) as never);
    const messages = buildCoveredCallMessages(check(cycle) as never, "每月期權", "text") as { type: "text"; text: string }[];
    expect(messages).toHaveLength(1);
    const text = messages[0]!.text;
    expect(text.length).toBeLessThan(4900);
    expect(text).toContain("【備兌買權建議｜AAA");
    for (const expected of ["現金擔保賣權", "領口策略", "需備現金 $9400.00", "最大損失 $754.00／口", "最大獲利 $746.00／口", "保護賣權（買進）履約價 $92.00"]) expect(text).toContain(expected);
    expect(text.indexOf("備兌買權")).toBeLessThan(text.indexOf("現金擔保賣權"));
    expect(text.indexOf("現金擔保賣權")).toBeLessThan(text.indexOf("領口策略"));
    expect(text).toContain("本服務不下單。");
    expect(text).toContain(STAMP);
    expect(text).toContain("未取得再散布授權");
  });

  it("no advice or guarantee phrasing, and a denied public admission renders nothing", () => {
    const rendered = JSON.stringify(full());
    for (const forbidden of ["保證獲利", "一定賺", "建議買進", "建議你", "穩賺"]) expect(rendered).not.toContain(forbidden);
    vi.mocked(admission.admitPublicOption).mockImplementation(() => ({ ok: false }) as never);
    expect(() => buildCoveredCallMessages(check(clone("yahoo_monthly_full")) as never, "每月期權", "flex")).toThrow();
  });

  it("the producer's 2% floor wording replaces the 6% note", () => {
    const text = JSON.stringify(full());
    expect(text).toContain("至少 2%");
    expect(text).not.toContain("至少 6%");
  });
});
