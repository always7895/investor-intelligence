import { describe, expect, it } from "vitest";
import { doc, HOUR } from "./bottleneck-v3-fixture";
import { parseBottleneckV3, buildBottleneckTop20Messages, buildBottleneckDetail } from "../src/v213/bottleneck-v3";
import { assertLineMessages } from "../src/line-messages";

const SEC = "https://www.sec.gov/Archives/edgar/data/67347/000110465926112870/tm2626618d1_8k.htm";
const distribution = (symbol: string) => ({
  target_market: "US", target_symbol: symbol, kind: "DISTRIBUTION", status: "CLOSED",
  distribution_date: "2026-10-01", related_market: "US", related_symbol: "THRM",
  shares_per_share: 0.44619, source_url: SEC, source_date: "2026-10-01", review_by: null,
});
function specimen() {
  const generated = doc(Date.now() - HOUR) as any;
  generated.top[0].corporate_action = distribution(generated.top[0].symbol);
  return generated;
}

describe("GAP-C distribution note, strict shape and legacy merger compatibility", () => {
  it("renders precisely dated Mandarin notice in text and information banner in UI-R3 Flex", () => {
    const parsed = parseBottleneckV3(specimen());
    expect(parsed).not.toBeNull();
    const text = buildBottleneckTop20Messages(parsed!, "text");
    assertLineMessages(text);
    const payload = text.map((row: any) => row.text).join("\n");
    expect(payload.match(/【注意】分拆已完成/g)?.length).toBe(1);
    const flex = buildBottleneckTop20Messages(parsed!, "flex");
    assertLineMessages(flex);
    const body = JSON.stringify(flex);
    expect(body).toContain("分拆已完成");
    expect(body).toContain("0.44619");
    expect(body).toContain("#EEF3F8"); // info tint, not caution
    expect(body).not.toContain("#FFF7ED");
  });

  it("rejects forbidden distribution shapes without damaging other sealed entries", () => {
    const original = specimen();
    expect(parseBottleneckV3(original)).not.toBeNull();
    for (const [label, change] of [
      ["pending", { status: "PENDING" }], ["invalid_ratio", { shares_per_share: 0 }],
      ["bool_ratio", { shares_per_share: true }], ["missing_date", { distribution_date: null }],
      ["invalid_date", { distribution_date: "2026-02-30" }],
      ["untrusted", { source_url: "https://example.org/Archives/deal" }],
      ["different_issuer", { target_symbol: "WRONG" }],
      ["same_related", { related_symbol: original.top[0].symbol }],
      ["future_source", { source_date: "2026-09-30" }],
      ["extra_field", { acquirer_symbol: "THRM" }],
    ] as const) {
      const malformed = specimen();
      Object.assign(malformed.top[0].corporate_action, change);
      expect(parseBottleneckV3(malformed), label).toBeNull();
    }
    const missing = specimen();
    delete missing.top[0].corporate_action.distribution_date;
    expect(parseBottleneckV3(missing)).toBeNull();
  });

  it("preserves exact LITE/MRVL all-stock note and rejects a new key on it", () => {
    const action = { target_symbol: "LITE", acquirer_symbol: "S1", kind: "ALL_STOCK", status: "PENDING",
      exchange_ratio: 4.5, cash_per_share: null, currency: null,
      expected_close: "first half of calendar year 2028",
      source_url: "https://www.sec.gov/Archives/edgar/data/0001633978/000119312526442758/d163169dex991.htm" };
    const row = specimen();
    row.top[1].corporate_action = action;
    expect(parseBottleneckV3(row)).not.toBeNull();
    row.top[1].corporate_action.source_date = "2026-11-02";
    expect(parseBottleneckV3(row)).toBeNull(); // legacy exact-key contract
  });

  it("does not accept an unsupported distribution-return reason", () => {
    const generated = specimen();
    generated.top[0].market.asof = "2026-11-06";
    generated.top[0].market.ret_6m = null;
    generated.top[0].market.ret_1y = null;
    generated.top[0].market.cagr_2y = null;
    generated.top[0].market.return_reasons = {
      ret_6m: "DISTRIBUTION_IN_WINDOW", ret_1y: "DISTRIBUTION_IN_WINDOW", cagr_2y: "DISTRIBUTION_IN_WINDOW",
    };
    expect(parseBottleneckV3(generated)).not.toBeNull();
    generated.top[0].market.ret_6m = 0.9;
    expect(parseBottleneckV3(generated)).toBeNull();
    generated.top[0].market.ret_6m = null;
    generated.top[0].market.return_reasons = { ret_6m: "RANDOM" };
    expect(parseBottleneckV3(generated)).toBeNull();
  });
});
