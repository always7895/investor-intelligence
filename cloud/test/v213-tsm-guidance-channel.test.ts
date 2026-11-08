import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { computeReceiptDigest, parseOrderForecastV3 } from "../src/v213/order-forecast";

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

  // The receipt digest is recomputed after each edit, so the edited receipt reaches the coverage and identity checks instead of stopping
  // at the digest check (R/ASTRA-V23-INDEPENDENT-ACCEPT-CLAUDECODE-a43bef58.txt M2); the unchanged-digest tamper is its own case below.
  const withReceipt = (edit: (receipt: any) => void) => {
    const forecast = structuredClone(fixture.forecast);
    edit(forecast.evidence.latest_release_check);
    forecast.evidence.latest_release_check.digest = computeReceiptDigest(forecast.evidence.latest_release_check);
    return forecast;
  };

  it("a recomputed digest of the unchanged receipt is the fixture's digest and still admits the channel (control)", () => {
    expect(computeReceiptDigest(fixture.forecast.evidence.latest_release_check)).toBe(fixture.forecast.evidence.latest_release_check.digest);
    const result = parse(withReceipt(() => {}));
    expect(result.m6.status).toBe("AVAILABLE");
    expect(result.m12.status).toBe("AVAILABLE");
  });

  it("retains incomplete official coverage as unavailable, with a valid receipt digest", () => {
    const bad = withReceipt(receipt => { receipt.channels.find((c: any) => c.kind === "ISSUER_IR").complete = false; });
    const result = parse(bad);
    expect(result.revenueStatus).not.toBe("AVAILABLE");
    expect(result.m6.status).toBe("UNAVAILABLE");
    expect(result.m12.status).toBe("UNAVAILABLE");
  });

  it("refuses an IR channel whose URL is not the reviewed TSMC channel, with a valid receipt digest", () => {
    const bad = withReceipt(receipt => { receipt.channels.find((c: any) => c.kind === "ISSUER_IR").url = "https://example.invalid/news"; });
    expect(parse(bad).m6.status).toBe("UNAVAILABLE");
    expect(parse(bad).m12.status).toBe("UNAVAILABLE");
  });

  it("refuses an edited receipt whose digest was not recomputed (tamper boundary)", () => {
    const bad = structuredClone(fixture.forecast);
    bad.evidence.latest_release_check.channels.find((c: any) => c.kind === "ISSUER_IR").complete = false;
    expect(parse(bad).m6.status).toBe("UNAVAILABLE");
  });
});
