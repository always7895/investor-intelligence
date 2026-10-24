import { describe, expect, it } from "vitest";
import { parseBottleneckV3, buildBottleneckTop20Messages, buildBottleneckDetail, outlookTiles } from "../src/v213/bottleneck-v3";
import { doc, HOUR } from "./bottleneck-v3-fixture";
import actual from "../../tests/fixtures/partial-analyst-outlook.json";
const NOW = Date.parse(actual.generated_at);
function document() {
  const value = doc(NOW);
  (value.top[1] as any).outlook = structuredClone(actual.partial);
  return value;
}
describe("partial analyst actual producer/publisher fields and historical order displays", () => {
  it("renders missing revenue with independently published EPS and target in card/text/detail", () => {
    const parsed = parseBottleneckV3(document(), NOW + HOUR)!;
    expect(parsed).not.toBeNull();
    const detail = buildBottleneckDetail(parsed, parsed.top[1]!.symbol);
    expect(JSON.stringify(detail)).toContain("分析師 EPS 共識（非訂單）");
    expect(JSON.stringify(detail)).toContain("分析師平均目標價（非訂單）");
    expect(JSON.stringify(buildBottleneckTop20Messages(parsed, "flex"))).toContain("+50%");
    expect(JSON.stringify(buildBottleneckTop20Messages(parsed, "text"))).toContain("+25%");
  });
  it("shows the actual per-scenario samples and thin warnings in both detail modes", () => {
    for (const [index, thin] of ["eps", "target"].entries()) {
      const value = document();(value.top[1] as any).outlook = structuredClone(actual.mixed[index]);
      const parsed = parseBottleneckV3(value,NOW+HOUR)!;
      for (const mode of ["flex", "text"] as const) {
        const detail = JSON.stringify(buildBottleneckDetail(parsed,parsed.top[1]!.symbol,mode));
        expect(detail).toContain("僅 1 位分析師，參考性低（樣本不足）");
        expect(detail).toContain(thin === "eps" ? "4 位分析師" : "5 位分析師");
        expect(detail).not.toContain("0 位分析師");
      }
    }
  });
  it("explains all-thin and noncomputable analyst rows in Top20 text", () => {
    for (const [outlook, reason] of [[actual.all_thin,"分析師樣本不足，不列推算"], [actual.no_basis,"無可計算的正值基礎或分析師共識，不列推算"]] as const) {
      const value = document();(value.top[1] as any).outlook = structuredClone(outlook);
      const parsed = parseBottleneckV3(value,NOW+HOUR)!;expect(parsed).not.toBeNull();
      const text = buildBottleneckTop20Messages(parsed,"text").map((m:any)=>m.text??"").join("\n");
      expect(text.split("\n").find(line=>line.startsWith("2. S1 "))).toContain(reason);
    }
  });
  it("renders real publisher official references without inventing recognition horizons", () => {
    for (const [symbol,outlook] of Object.entries(actual.official)) {
      const value = document();value.top[1]!.symbol=symbol;(value.top[1] as any).outlook=structuredClone(outlook);
      const parsed = parseBottleneckV3(value,NOW+HOUR)!;expect(parsed).not.toBeNull();
      for (const output of [buildBottleneckTop20Messages(parsed,"flex"),buildBottleneckTop20Messages(parsed,"text"),buildBottleneckDetail(parsed,symbol,"flex"),buildBottleneckDetail(parsed,symbol,"text")]) {
        const encoded=JSON.stringify(output);
        expect(encoded.includes(symbol === "APLD" ? "初始租期約 US$36B" : "長期投資等級客戶承諾約 US$40B")).toBe(true);
        expect(encoded).not.toContain("\\u");
      }
      for (const horizon of [outlook.order_forecast.m6,outlook.order_forecast.m12]) {
        expect(horizon.status).toBe("UNAVAILABLE");expect("basis" in horizon).toBe(false);
      }
    }
  });
  it("never calculates EPS growth on a negative baseline", () => {
    const value = document();(value.top[1] as any).outlook = structuredClone(actual.loss);
    const parsed = parseBottleneckV3(value, NOW + HOUR)!;
    expect(parsed).not.toBeNull();expect(JSON.stringify(buildBottleneckDetail(parsed, parsed.top[1]!.symbol))).toContain("未具備可比正值，未推算成長");
  });
  it("rejects forged partial fields, counts, source clocks and scenarios", () => {
    const mutations = [
      (o: any) => o.consensus.asof = "2026-10-24", (o: any) => o.consensus.asof = "2026-10-22",
      (o: any) => o.consensus.asof = "2026-02-30", (o: any) => o.consensus.target_analysts = 1.5,
      (o: any) => o.consensus.target_mean = -1, (o: any) => o.consensus.eps_analysts = 0,
      (o: any) => { o.consensus.eps_fy0 = -2; }, (o: any) => o.scenarios[0].change = 999,
      (o: any) => o.consensus.source_url = "https://unreviewed.example/analysis",
    ];
    for (const mutate of mutations) { const value = document();mutate((value.top[1] as any).outlook);expect(parseBottleneckV3(value, NOW + HOUR)).toBeNull(); }
  });
  it("keeps independently sufficient target or EPS samples in compact and text callers", () => {
    for (const [index, thin] of ["eps", "target"].entries()) {
      const value = document();(value.top[1] as any).outlook = structuredClone(actual.mixed[index]);
      const parsed = parseBottleneckV3(value,NOW+HOUR)!;
      const kept = thin === "eps" ? "+25%" : "+50%";
      const detail = JSON.stringify(buildBottleneckDetail(parsed,parsed.top[1]!.symbol));
      expect(detail).toContain("分析師");
      const messages = buildBottleneckTop20Messages(parsed,"flex");
      const focus = messages.flatMap((m: any) => m.contents?.contents ?? []).find((b: any) => JSON.stringify(b.header).includes("S1｜"));
      expect(JSON.stringify(focus)).toContain(kept);
      expect(JSON.stringify(focus)).not.toContain(thin === "eps" ? "EPS實現·本益比不變" : "分析師目標價");
      const line = buildBottleneckTop20Messages(parsed,"text").map((m:any)=>m.text??"").join("\n").split("\n").find(x=>x.startsWith("2. S1 "))!;
      expect(line).toContain(kept);
      expect(line).not.toContain(thin === "eps" ? "EPS實現·本益比不變" : "分析師目標價");
    }
  });
  it("admits actual publisher sanitized order clocks without losing sibling consensus", () => {
    for (const row of actual.order_clocks) {
      const value = document();(value.top[1] as any).outlook = structuredClone(row.outlook);
      const parsed = parseBottleneckV3(value,NOW+HOUR)!;expect(parsed).not.toBeNull();
      expect(parsed.top[1]!.outlook!.consensus!.target_mean).toBe(125);
      expect(!!parsed.top[1]!.outlook!.orders).toBe(["2026-10-23","2021-04-03"].includes(row.input as string));
    }
  });
  it("labels 2021/2023 RPO as historical across card/text/detail instead of current orders", () => {
    for (const asof of ["2021-04-03", "2023-05-31"]) {
      const value = doc(NOW);(value.top[1] as any).outlook.orders.as_of = asof;
      const parsed = parseBottleneckV3(value, NOW + HOUR)!;
      expect(outlookTiles(parsed, parsed.top[1]!)[0]![0]).toBe("歷史披露（已過期）");
      for (const output of [buildBottleneckTop20Messages(parsed, "flex"), buildBottleneckTop20Messages(parsed, "text"), buildBottleneckDetail(parsed, parsed.top[1]!.symbol)]) {
        expect(JSON.stringify(output)).toContain("歷史披露");expect(JSON.stringify(output)).toContain("不作目前訂單／預測");
      }
    }
  });
  it("keeps the existing200day boundary and refuses future or malformed source days", () => {
    for (const age of [200, 201]) {
      const value = doc(NOW);(value.top[1] as any).outlook.orders.as_of = new Date(NOW - age * 86400000).toISOString().slice(0, 10);
      const parsed = parseBottleneckV3(value, NOW + HOUR)!;
      expect(outlookTiles(parsed, parsed.top[1]!)[0]![0]).toBe(age === 200 ? "現有訂單" : "歷史披露（已過期）");
    }
    for (const asof of ["2026-10-24", "2026-02-30", null]) { const value = doc(NOW);(value.top[1] as any).outlook.orders.as_of = asof;expect(parseBottleneckV3(value,NOW+HOUR)).toBeNull(); }
  });
});

// BEGIN ACTUAL OVERFLOW FIXTURE
const overflowCases = [
  {
    "label": "EPS_OVERFLOW",
    "outlook": {
      "orders": null,
      "consensus": {
        "revenue_fy0": null,
        "revenue_fy1": null,
        "revenue_growth": null,
        "revenue_analysts": null,
        "eps_fy0": 1e-308,
        "eps_fy1": 10.0,
        "eps_growth": null,
        "eps_analysts": 5.0,
        "target_mean": 125.0,
        "target_analysts": 4.0,
        "price": 100.0,
        "target_upside": 0.25,
        "source": "Yahoo Finance analyst estimates (unofficial)",
        "source_url": "https://finance.yahoo.com/quote/SYNTH/analysis",
        "asof": "2026-10-23"
      },
      "scenarios": [
        {
          "kind": "ANALYST_TARGET",
          "change": 0.25
        }
      ],
      "consensus_second": null
    }
  },
  {
    "label": "TARGET_OVERFLOW",
    "outlook": {
      "orders": null,
      "consensus": {
        "revenue_fy0": null,
        "revenue_fy1": null,
        "revenue_growth": null,
        "revenue_analysts": null,
        "eps_fy0": 2.0,
        "eps_fy1": 3.0,
        "eps_growth": 0.5,
        "eps_analysts": 5.0,
        "target_mean": 125.0,
        "target_analysts": 4.0,
        "price": 1e-308,
        "target_upside": null,
        "source": "Yahoo Finance analyst estimates (unofficial)",
        "source_url": "https://finance.yahoo.com/quote/SYNTH/analysis",
        "asof": "2026-10-23"
      },
      "scenarios": [
        {
          "kind": "EPS_CONSTANT_PE",
          "change": 0.5
        }
      ],
      "consensus_second": null
    }
  }
];
// END ACTUAL OVERFLOW FIXTURE

describe("actual producer/publisher derived-ratio overflow", () => {
  it.each(overflowCases)("retains the valid sibling in $label across public callers", ({ label, outlook }) => {
    const value = document();
    (value.top[1] as any).outlook = structuredClone(outlook);
    const parsed = parseBottleneckV3(value, NOW + HOUR)!;
    expect(parsed).not.toBeNull();
    const kept = label === "EPS_OVERFLOW" ? "ANALYST_TARGET" : "EPS_CONSTANT_PE";
    const keptLabel = label === "EPS_OVERFLOW" ? "分析師目標價" : "EPS實現·本益比不變";
    const lostLabel = label === "EPS_OVERFLOW" ? "EPS實現·本益比不變" : "分析師目標價";
    const change = label === "EPS_OVERFLOW" ? 0.25 : 0.5;
    const percentage = label === "EPS_OVERFLOW" ? "+25%" : "+50%";
    const entry = parsed.top[1]!;
    expect(entry.outlook!.consensus).toEqual(outlook.consensus);
    expect(entry.outlook!.scenarios).toEqual([{ kind: kept, change }]);
    expect(entry.outlook!.consensus![label === "EPS_OVERFLOW" ? "eps_growth" : "target_upside"]).toBeNull();
    const focus = buildBottleneckTop20Messages(parsed, "flex")
      .flatMap((message: any) => message.contents?.contents ?? [])
      .find((bubble: any) => JSON.stringify(bubble.header).includes("S1｜"));
    expect(focus).toBeDefined();
    const text = buildBottleneckTop20Messages(parsed, "text").map((message: any) => message.text ?? "")
      .join("\n").split("\n").find(line => line.startsWith("2. S1 "));
    expect(text).toBeDefined();
    for (const output of [focus, text, buildBottleneckDetail(parsed, entry.symbol, "flex"), buildBottleneckDetail(parsed, entry.symbol, "text")]) {
      const encoded = JSON.stringify(output);
      expect(encoded).toContain(keptLabel);
      expect(encoded).toContain(percentage);
      expect(encoded).not.toContain(lostLabel);
      expect(encoded).not.toContain("Infinity");
      expect(encoded).not.toContain("NaN");
    }
    for (const mode of ["flex", "text"] as const) {
      const detail = JSON.stringify(buildBottleneckDetail(parsed, entry.symbol, mode));
      expect(detail).toContain("分析師 EPS 共識（非訂單）：下一財年 " + outlook.consensus.eps_fy1);
      expect(detail).toContain("分析師平均目標價（非訂單）：125（4 位）");
    }
  });

  it.each(overflowCases)("still refuses finite mismatches, arbitrary null and transmitted nonfinite values in $label", ({ label, outlook }) => {
    const finiteKey = label === "EPS_OVERFLOW" ? "target_upside" : "eps_growth";
    const overflowKey = label === "EPS_OVERFLOW" ? "eps_growth" : "target_upside";
    const mutations: Array<(outlook: any) => void> = [
      o => o.consensus[finiteKey] = 0.123,
      o => { o.consensus[finiteKey] = null; o.scenarios = []; },
      o => o.consensus[overflowKey] = 0,
      o => o.consensus[overflowKey] = Infinity,
      o => o.consensus[overflowKey] = -Infinity,
      o => o.consensus[overflowKey] = NaN,
      o => o.consensus[finiteKey] = Infinity,
      o => o.consensus.eps_fy0 = Infinity,
      o => o.consensus.eps_fy1 = NaN,
      o => o.consensus.price = Infinity,
      o => o.consensus.target_mean = Infinity,
      o => o.consensus.eps_analysts = 0,
      o => o.consensus.target_analysts = 1.5,
      o => o.consensus.source_url = "https://unreviewed.example/analysis",
      o => o.consensus.asof = "2026-10-24",
      o => o.scenarios.push({ kind: label === "EPS_OVERFLOW" ? "EPS_CONSTANT_PE" : "ANALYST_TARGET", change: 1 }),
    ];
    for (const mutate of mutations) {
      const value = document();
      const bad = structuredClone(outlook);
      mutate(bad);
      (value.top[1] as any).outlook = bad;
      expect(parseBottleneckV3(value, NOW + HOUR)).toBeNull();
    }
  });
});
