import { describe, expect, it, vi } from "vitest";
import { parseQuery } from "../src/core";
import { assertLineMessages, type LineOutboundMessage } from "../src/line-messages";
import { validateCoveredCallCycle } from "../src/v213/covered-call";
import * as observations from "../src/v213/market-observations";
import { v213PublicLineAnswer } from "../src/v213/rich-menu";
import { admitSyntheticTickers } from "./synthetic-option-admission";
import { bubblesOf, type Node } from "./flex-density-fixtures";
import fixture from "./fixtures/v21-three-strategies.json";

vi.mock("../src/v213/public-options-admission", async original => {
  const real = await original<typeof import("../src/v213/public-options-admission")>();
  return { ...real, admitPublicOption: vi.fn(real.admitPublicOption) };
});
vi.mock("../src/v213/public-snapshot", async original => ({
  ...await original<typeof import("../src/v213/public-snapshot")>(), pinPublicSnapshot: vi.fn(async () => ({ integrity: "sealed" })),
}));
vi.mock("../src/v213/market-observations", async original => ({
  ...await original<typeof import("../src/v213/market-observations")>(), loadDetailedOptionObservation: vi.fn(),
}));
vi.mock("../src/v213/identity-shards", async original => ({
  ...await original<typeof import("../src/v213/identity-shards")>(), loadIdentityCatalogForQuery: vi.fn(async () => null),
}));

function rows(node: Node): number {
  if (node.type === "text") return (node.text ?? (node.contents ?? []).map(span => span.text ?? "").join("")).split("\n").length;
  const children = (node.contents ?? []).map(rows);
  return node.layout === "horizontal" ? Math.max(0, ...children) : children.reduce((sum, count) => sum + count, 0);
}

describe("full public strategy replies", () => {
  it.each(["monthly", "weekly"] as const)("keeps the %s overview compact and every tier's quote scenarios in the actual reply", async period => {
    const cycle: any = structuredClone(fixture.cases.yahoo_monthly_full);
    if (period === "weekly") {
      cycle.dte = 7;
      cycle.expiry = "2026-10-30";  // the fixture run date is Friday 2026-10-23: next week's Friday
      cycle.weekly_week = "NEXT";
      delete cycle.monthly_rule;    // the marker rides monthly rows only
      for (const item of [...cycle.suggestions, cycle.middle_suggestion]) item.annualized_yield = item.period_yield * 365 / 7;
      for (const item of cycle.strategies.csp.suggestions) item.annualized_yield = item.limit_price / item.strike * 365 / 7;
    }
    const valid = validateCoveredCallCycle(cycle, Date.parse(fixture.stamp) + 60_000, fixture.stamp, period);
    expect(valid).not.toBeNull();
    admitSyntheticTickers(cycle.ticker);
    vi.mocked(observations.loadDetailedOptionObservation).mockResolvedValue({ status: "FOUND", ticker: cycle.ticker, matchedKey: cycle.ticker, quote: valid } as never);
    const messages = await v213PublicLineAnswer({} as never, parseQuery(`${cycle.ticker} 每${period === "weekly" ? "週" : "月"}期權`)) as LineOutboundMessage[];
    assertLineMessages(messages);
    const pages = bubblesOf(messages);
    expect(pages).toHaveLength(5);
    expect(JSON.stringify(pages.at(-1)?.header)).toContain("資料來源與說明");
    expect(rows(pages[0]!.body as Node)).toBeLessThanOrEqual(10);
    for (const page of pages.slice(0, -1)) {
      const visible = JSON.stringify(page);
      expect(visible).toContain("非投資建議");
      expect(visible).toContain("不下單");
    }
    const full = JSON.stringify(pages);
    for (const required of ["$94.00", "$96.00", "$9400.00", "$9600.00", "$92.00", "$107.00", "$754.00", "$746.00",
      "Bid $0.98", "Bid $0.59", "Bid $1.05", "以備妥現金計", "LIMIT", "不高於Ask", "不低於Bid", "Call Bid－Put Ask"]) expect(full).toContain(required);
    for (const page of pages.slice(1, -1)) {
      const visible = JSON.stringify(page);
      for (const required of ["LIMIT", "Bid情境", "價差占中價", "未成交"]) expect(visible).toContain(required);
    }
  });
});
