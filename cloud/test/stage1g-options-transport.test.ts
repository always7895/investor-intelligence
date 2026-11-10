/** Stage1G CI: independently consume the exact Python-emitted E1/HV sealed body
 * and compare Worker counts/labels with the Python coverage projection.
 * The fixture is generated with python -m tests.fixtures.stage1g_hv_seal.
 */
import fs from "node:fs";
import { describe, expect, it, vi } from "vitest";
import { decimalModelLimit } from "../src/v213/option-delta-side-model";
import { buildCoveredCallMessages, validateCoveredCallCycle } from "../src/v213/covered-call";
import { loadDetailedOptionObservation } from "../src/v213/market-observations";
import type { PublicSnapshotView } from "../src/v213/public-snapshot";
import * as admission from "../src/v213/public-options-admission";

// Test-only, one-ticker synthetic admission seam. Production rights catalog,
// dates, provider decisions and all other symbols remain unmodified.
vi.mock("../src/v213/public-options-admission", async importOriginal => {
  const real = await importOriginal<typeof import("../src/v213/public-options-admission")>();
  return { ...real, admitPublicOption: vi.fn(real.admitPublicOption) };
});
const realAdmission = await vi.importActual<typeof import("../src/v213/public-options-admission")>(
  "../src/v213/public-options-admission");

const payload = JSON.parse(fs.readFileSync(new URL("./fixtures/stage1g-hv-coverage.json", import.meta.url), "utf8"));
const document = JSON.parse(payload.options_body);
const coverage = JSON.parse(payload.coverage_body);
const time = Date.parse(payload.clock);
const underlying = document.options.AAA;
const historical = underlying._hv;
const original = underlying.monthly;

describe("Stage1G executable decimal tick prices", () => {
  it("snaps after bounds, with no half tick, binary float tail or above-mid buy", () => {
    const cases: Array<[number, number, number, number, number]> = [
      [.01, 1.35, 9, .68, .68],
      [.30, .37, 9, .33, .33],
      [.31, .36, .335, .33, .33],
      [.01, 1.24, 10, .62, .62],
      [.01, 2.50, .0565, .05, .06],
      [.07, 2.50, .2717, .27, .28],
      [.01, .4, 0, .01, .01],
      [.05, .25, .0499999999999996, .05, .05],
      [.05, .25, .0500000000000004, .05, .05],

      [.335, .8, 9, .56, .56],
    ];
    for (const [bid, ask, price, sell, buy] of cases) {
      for (const [direction, expected] of [[false, sell], [true, buy]] as const) {
        const actual = decimalModelLimit(bid, ask, price, direction);
        expect(actual).toBe(expected);
        expect(Math.abs(actual! * 100 - Math.round(actual! * 100))).toBeLessThan(1e-8);
        expect(actual).toBeGreaterThanOrEqual(bid);
        expect(actual!).toBeLessThanOrEqual(Math.floor((bid / 2 + ask / 2) * 100 + 1e-9) / 100);
      }
    }
    expect(decimalModelLimit(.335, .335, .335, false)).toBeNull();
    expect(decimalModelLimit(.335, .335, .335, true)).toBeNull();
  });

  it("matches Python Decimal(str(model)) HALF_EVEN at 12 decimal places", () => {
    expect(decimalModelLimit(.01, 1, .3400000000005, true)).toBe(.34);
    expect(decimalModelLimit(.01, 1, .3400000000015, true)).toBe(.35);
    expect(decimalModelLimit(.01, 1, .3400000000005, false)).toBe(.34);
  });
});

describe("Stage1G sealed E1 historical-volatility and coverage parity", () => {
  it("expands one per-ticker @ history, refuses missing shared evidence, and checks Python coverage", () => {
    expect(document.schema).toBe("v213-options-v2");
    expect(original.historical_volatility).toBe("@");
    expect(historical).toHaveLength(11);
    const accepted = validateCoveredCallCycle(original, time, document.generated_at, "monthly",
      { sharedHistory: historical });
    expect(accepted).not.toBeNull();
    expect(accepted!.historical_volatility?.ticker).toBe("AAA");
    expect(validateCoveredCallCycle(original, time, document.generated_at, "monthly")).toBeNull();
    expect(validateCoveredCallCycle(original, time, document.generated_at, "monthly",
      { sharedHistory: historical.slice(1) })).toBeNull();
    // A different authenticated historical snapshot may stay with its own
    // cycle; no shared marker or previous-session history is invented.
    const retained = structuredClone(original);
    retained.historical_volatility = historical;
    expect(validateCoveredCallCycle(retained, time, document.generated_at, "monthly")).not.toBeNull();
    expect(coverage.options_link.utf8_bytes).toBe(new TextEncoder().encode(payload.options_body).byteLength);
    expect(coverage.observed).toHaveLength(1);
    const result = coverage.observed[0];
    expect(result.cycle_count).toBe(1);
    expect(result.ticker_key_count).toBe(1);
    expect(result.quote_as_of_max).toBe(accepted!.timestamp);
    expect(result.provider_id).toBe(accepted!.provider_id);
    expect(result.venue).toBe(accepted!.venue);
  });

  it("displays a readable HV basis in Flex and Text without an unavailable enum", () => {
    vi.useFakeTimers();
    vi.setSystemTime(time);
    vi.mocked(admission.admitPublicOption).mockImplementation((target: unknown, nowMs?: number) => {
      const ticker = target && typeof target === "object" && "ticker" in target
        ? (target as { ticker: unknown }).ticker : null;
      return ticker === "AAA" ? { ok: true, provider_id: "stage1g-synthetic-only" }
        : realAdmission.admitPublicOption(target, nowMs);
    });
    try {
      const accepted = validateCoveredCallCycle(original, time, document.generated_at, "monthly",
        { sharedHistory: historical });
      expect(accepted).not.toBeNull();
      const renderedFlex = JSON.stringify(buildCoveredCallMessages(accepted!, "每月期權", "flex"));
      const renderedText = JSON.stringify(buildCoveredCallMessages(accepted!, "每月期權", "text"));
      const nextWeek = JSON.stringify(buildCoveredCallMessages(
        { ...accepted!, weekly_week: "NEXT" }, "每週期權", "text"));
      expect(nextWeek).toContain("本週已無剩餘週選，顯示下週最早到期日");
      expect(nextWeek).not.toContain("與每月期權為同一合約");
      for (const rendered of [renderedFlex, renderedText]) {
        expect(rendered).toContain("歷史波動率模型");
        expect(rendered).not.toContain("資料暫不可用");
        expect(rendered).not.toContain("HISTORICAL_VOL");
      }
    } finally {
      vi.mocked(admission.admitPublicOption).mockImplementation(realAdmission.admitPublicOption);
      vi.useRealTimers();
    }
  });

  it("preserves all three independent refusal reasons from the sealed unavailable body", async () => {
    const periods = { monthly: {
      unavailable: "三種策略皆未符合條件",
      strategy_reasons: {
        cc: "買權 Delta 不超過 0.20 的履約價不存在",
        csp: "賣權 Delta 絕對值不在 0.20–0.30",
        collar: "保護賣權未符合 Delta 條件",
      },
    } };
    const stub = {
      integrity: "sealed",
      text: async () => null,
      json: async () => ({ schema: "v213-options-v2", generated_at: payload.clock,
                           options: { AAA: periods } }),
    } as unknown as PublicSnapshotView;
    const detailed = await loadDetailedOptionObservation(stub, ["AAA"], "monthly", time);
    expect(detailed.status).toBe("PERIOD_UNAVAILABLE");
    expect(detailed.strategyReasons?.cc).toContain("買權");
    expect(detailed.strategyReasons?.csp).toContain("賣權");
    expect(detailed.strategyReasons?.collar).toContain("保護賣權");
    expect(detailed.unavailable).toBe("三種策略皆未符合條件");
  });
});
