import { describe, expect, it } from "vitest";
import { admitPublicOption } from "../src/v213/public-options-admission";
import { rightsZh } from "../src/v213/source-labels";

const now = Date.parse("2026-11-02T14:00:00Z");
const us = { jurisdiction: "US", venue: "US_LISTED_OPTIONS", instrument_kind: "equity_option", quote_basis: "delayed", publication_scope: "public_line_quote" };
const se = { ...us, jurisdiction: "SE", venue: "NASDAQ_STOCKHOLM_OPTIONS" };

describe("V30 catalog admission", () => {
  it("keeps all three operator-accepted routes admitted under the current catalog", () => {
    for (const [provider_id, scope] of [["yahoo_finance_option_chain", us], ["nasdaq_public_option_chain", us], ["nasdaq_nordic_option_chain", se]] as const) {
      expect(admitPublicOption({ ...scope, provider_id }, now)).toEqual({ ok: true, provider_id, operator_accepted: true });
    }
  });

  it("never admits a licence-required source", () => {
    expect(admitPublicOption({ ...us, provider_id: "eurex_public_derivatives" }, now)).toEqual({ ok: false, reason: "OPTION_RIGHTS_NOT_ADMITTED" });
    expect(rightsZh("licence_required")).toBe("需授權");
  });
});
