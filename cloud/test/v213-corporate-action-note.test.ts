import { describe, it, expect } from "vitest";
import { doc, HOUR } from "./bottleneck-v3-fixture";
import { parseBottleneckV3, buildBottleneckTop20Messages } from "../src/v213/bottleneck-v3";
import { assertLineMessages } from "../src/line-messages";

const action = (symbol: string) => ({
  target_symbol: "LITE", acquirer_symbol: symbol, kind: "ALL_STOCK", status: "PENDING",
  exchange_ratio: 4.5, cash_per_share: null, currency: null, expected_close: "first half of calendar year 2028",
  source_url: "https://www.sec.gov/Archives/edgar/data/0001633978/000119312526442758/d163169dex991.htm",
});

const AT = Date.parse("2026-11-09T02:15:59Z");
function specimen(symbol: string, note: unknown) {
  const base = doc(AT);
  return { ...base, top: [{ ...base.top[0]!, symbol, corporate_action: note }, ...base.top.slice(1)] };
}

describe("Controlled corporate-action card terms", () => {
  it("renders pending acquirer terms without changing its independent numeric score", () => {
    const generated = specimen("MRVL", action("MRVL"));
    const parsed = parseBottleneckV3(generated, AT);
    expect(parsed).not.toBeNull();
    if (!parsed) throw new Error("VALID_PENDING_ACQUIRER_NOTE_REJECTED");
    expect(parsed.top[0]!.score).toBe(generated.top[0]!.score);
    for (const mode of ["text", "flex"] as const) {
      const messages = buildBottleneckTop20Messages(parsed, mode);
      assertLineMessages(messages);
      const rendered = JSON.stringify(messages);
      expect(rendered).toContain("4.500 股 MRVL");
      expect(rendered).not.toMatch(/\b(?:PENDING|CLOSED)\b/);
      expect(rendered.match(/併購進行中/g)).toHaveLength(1);
    }
  });

  it("rejects a pending target even when its merger terms are structurally valid", () => {
    expect(parseBottleneckV3(specimen("LITE", action("MRVL")), AT)).toBeNull();
  });

  it("rejects unbounded terms, wrong parties and a nonpending status", () => {
    for (const note of [
      { ...action("MRVL"), expected_close: "A".repeat(20000) },
      { ...action("MRVL"), status: "CLOSED" },
      { ...action("MRVL"), acquirer_symbol: "LITE" },
    ]) expect(parseBottleneckV3(specimen("MRVL", note), AT)).toBeNull();
    expect(parseBottleneckV3(specimen("OTHER", action("MRVL")), AT)).toBeNull();
  });

  it("shows both distribution parties without transferring MOD shareholder returns to THRM", () => {
    const note = { kind: "DISTRIBUTION", status: "CLOSED", target_market: "US", target_symbol: "MOD",
      distribution_date: "2026-10-01", related_market: "US", related_symbol: "THRM",
      shares_per_share: 0.44619, source_date: "2026-10-01", review_by: null,
      source_url: "https://www.sec.gov/Archives/edgar/data/67347/000110465926112870/tm2626618d1_8k.htm" };
    const raw = specimen("THRM", note);
    const parsed = parseBottleneckV3(raw, AT);
    expect(parsed).not.toBeNull();
    if (!parsed) throw new Error("VALID_RELATED_PARTY_NOTE_REJECTED");
    expect(parsed.top[0]!.market.ret_6m).toBe(raw.top[0]!.market.ret_6m);
    for (const mode of ["text", "flex"] as const) {
      const rendered = JSON.stringify(buildBottleneckTop20Messages(parsed, mode));
      expect(rendered).toContain("MOD 每股配發 0.44619 股 THRM");
      expect(rendered).not.toMatch(/\b(?:PENDING|CLOSED)\b/);
      expect(rendered.match(/分拆已完成/g)).toHaveLength(1);
      expect(rendered).toContain("未套用 MOD 股東權益報酬");
    }
    expect(parseBottleneckV3(specimen("UNRELATED", note), AT)).toBeNull();
    const forged = specimen("THRM", note);
    Object.assign(forged.top[0]!.market, { distribution_adjustment: {
      status: "REVIEWED_PRIMARY_INPUTS", source_url: note.source_url,
      distribution_date: note.distribution_date, related_symbol: "THRM", shares_per_share: 0.44619,
      evidence_sha256: "1".repeat(64), values: { ret_6m: 0.2 }, method: "SHAREHOLDER_ENTITLEMENT_TOTAL_RETURN",
    } });
    expect(parseBottleneckV3(forged, AT)).toBeNull();
  });
});
