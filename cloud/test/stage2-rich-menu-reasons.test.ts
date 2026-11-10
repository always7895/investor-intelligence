/** Stage 2 synthetic integration: the real rich-menu branch renders every sealed refusal reason. */
import { afterEach, describe, expect, it, vi } from "vitest";
import { parseQuery } from "../src/core";
import { pinPublicSnapshot } from "../src/v213/public-snapshot";
import { v213PublicLineAnswer } from "../src/v213/rich-menu";

vi.mock("../src/v213/public-snapshot", async importOriginal => {
  const real = await importOriginal<typeof import("../src/v213/public-snapshot")>();
  return { ...real, pinPublicSnapshot: vi.fn(real.pinPublicSnapshot) };
});
const CLOCK = "2026-11-09T12:00:00Z";
const reasons = {
  cc: "買權 Delta 不在限制範圍",
  csp: "賣權雙邊價格缺漏",
  collar: "保護賣權履約價不符",
};
const document = {
  schema: "v213-options-v2", generated_at: CLOCK,
  options: { AAA: { monthly: { unavailable: "三種策略未符合條件", strategy_reasons: reasons } } },
};
afterEach(() => vi.useRealTimers());

describe("Stage 2 rich menu sealed refusal", () => {
  it.each(["text", "flex"] as const)("renders CC, CSP and collar reasons in %s", async mode => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(Date.parse(CLOCK));
    const view = {
      integrity: "sealed",
      text: async () => null,
      json: async () => document,
    };
    vi.mocked(pinPublicSnapshot).mockReturnValue(view as never);
    const reply = await v213PublicLineAnswer(
      { V213_LINE_PRESENTATION: mode } as never,
      parseQuery("AAA 每月期權"),
    );
    const rendered = JSON.stringify(reply);
    for (const label of ["備兌買權：", "現金擔保賣權：", "領口策略："]) {
      expect(rendered).toContain(label);
    }
    for (const reason of Object.values(reasons)) expect(rendered).toContain(reason);
    expect(rendered).not.toContain("資料暫不可用");
  });
});
