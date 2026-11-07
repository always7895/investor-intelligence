import { describe, it, expect } from "vitest";
import { doc, HOUR } from "./bottleneck-v3-fixture";
import { parseBottleneckV3, buildBottleneckTop20Messages } from "../src/v213/bottleneck-v3";
import { assertLineMessages } from "../src/line-messages";

const action = (symbol: string) => ({
  target_symbol: "LITE", acquirer_symbol: symbol, kind: "ALL_STOCK",
  exchange_ratio: 4.5, cash_per_share: null, currency: null, expected_close: "first half of calendar year 2028",
  source_url: "https://www.sec.gov/Archives/edgar/data/0001633978/000119312526442758/d163169dex991.htm",
});

describe("Gap-A pending deal LINE note", () => {
  it("shows capture-transfer notice from a sealed acquirer record without leaking a target ranking", () => {
    const generated = doc(Date.now() - HOUR) as any;
    generated.top[0].corporate_action = action(generated.top[0].symbol);
    const parsed = parseBottleneckV3(generated);
    expect(parsed).not.toBeNull();
    const texts = buildBottleneckTop20Messages(parsed!, "text");
    assertLineMessages(texts);
    expect(texts.map((x: any) => x.text).join("\n")).toContain("併購進行中：每股換 4.500 股");
    expect(texts.map((x: any) => x.text).join("\n")).toContain("2028 年上半年");
  });

  it("rejects malicious/unbounded deal text but does not throw for a valid note", () => {
    const value = doc(Date.now() - HOUR) as any;
    value.top[0].corporate_action = { ...action(value.top[0].symbol), expected_close: "A".repeat(20000) };
    expect(parseBottleneckV3(value)).toBeNull();
    value.top[0].corporate_action = action(value.top[0].symbol);
    const parsed = parseBottleneckV3(value)!;
    expect(() => assertLineMessages(buildBottleneckTop20Messages(parsed, "flex"))).not.toThrow();
  });
});
