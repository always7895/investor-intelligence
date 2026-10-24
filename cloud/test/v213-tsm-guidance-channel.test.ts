import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { parseOrderForecastV3 } from "../src/v213/order-forecast";

const fixture = JSON.parse(readFileSync(new URL("../../tests/fixtures/tsm-guidance-channel-v1.json", import.meta.url), "utf8"));
// The fixture is produced by the real Python order_forecast.build_v3 caller.
// Its receipt and approved profile are explicitly synthetic; no live acceptance is represented.
const parse = (forecast: unknown) => parseOrderForecastV3(forecast, fixture.report_day, fixture.issuer, fixture.generated_at);

describe("TSMC reviewed news channel survives Python producer to Worker", () => {
  it("admits the exact TSMC channel and retains the company-guidance numbers", () => {
    const result = parse(fixture.forecast);
    expect(result).toMatchObject({ revenueStatus: "AVAILABLE" });
    expect(result.m6.status).toBe("AVAILABLE");
    expect(result.m12.status).toBe("AVAILABLE");
    expect(result.m6.amount).toBe(fixture.forecast.m6.amount);
    expect(result.m12.amount).toBe(fixture.forecast.m12.amount);
  });

  it("refuses an unknown kind rather than dropping channel provenance", () => {
    const bad = structuredClone(fixture.forecast);
    bad.evidence.release_channels.ir.kind = "UNREVIEWED_NEWS_HTML";
    const result = parse(bad);
    expect(result.revenueStatus).not.toBe("AVAILABLE");
    expect(result.m6.status).toBe("UNAVAILABLE");
    expect(result.m12.status).toBe("UNAVAILABLE");
  });

  it("retains incomplete official coverage as unavailable", () => {
    const bad = structuredClone(fixture.forecast);
    bad.evidence.latest_release_check.channels.find((c: any) => c.kind === "ISSUER_IR").complete = false;
    expect(parse(bad).m6.status).toBe("UNAVAILABLE");
  });
});
