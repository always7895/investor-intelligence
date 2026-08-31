import { describe, expect, it } from "vitest";
import { parseQuery } from "../src/core";
import { ingestV212Top20Report } from "../src/v212/admin";
import {
  formatV212Top20Report,
  parseV212Top20Report,
  v212Top20ReportAnswer,
} from "../src/v212/top20-report";
import { MemoryKv, asKv } from "./fake-kv";

function topRecord(index: number) {
  return {
    ticker: `T${String(index).padStart(2, "0")}`,
    name: `Synthetic Company ${index}`,
    serenity_score: 90 - index,
    serenity_raw_score: 90 - index,
    risk_penalty: 0,
    data_quality: 0.9,
    rating: "A",
    category: "Synthetic Industry",
    serenity_factors: {
      demand_wave: 15,
      chokepoint: 15,
      pricing_power: 15,
      replacement_friction: 10,
      tam_capture: 15,
      valuation_expectations: 10,
      evidence_quality: 10,
    },
    risk_flags: [],
    aschenbrenner_overlay: {
      domain: "C",
      fit_score: 50,
      included_in_serenity_score: false,
      attribution: "system_operationalization_not_aschenbrenner_stock_score",
    },
    evidence: [{
      source_id: "sec_edgar",
      tier: "T0",
      claim_type: "xbrl_fact",
      title: "Synthetic public evidence",
      url: `https://www.sec.gov/example/${index}`,
      as_of: "2026-08-31T00:00:00Z",
    }],
    evidence_count: 1,
    source_count: 2,
    scoring_version: "serenity-first-v2.1.0",
    line_public_eligible: true,
    provider_scope: "public_only",
    owner_watchlist_inherited: false,
    rank: index + 1,
    generated_at: "2026-08-31T00:00:00Z",
    as_of: "2026-08-31T00:00:00Z",
  };
}

function report() {
  return {
    schema_version: 1,
    product_version: "2.1.2",
    generated_at: "2026-08-31T00:00:00Z",
    display_columns: ["股票", "長期投資報酬率", "短期投資報酬率", "行業別", "獲利簡述"],
    long_term_definition: "trailing_2y_adjusted_close_cagr",
    short_term_definition: "trailing_6m_adjusted_close_price_return",
    records: Array.from({ length: 20 }, (_, index) => ({
      schema_version: 1,
      rank: index + 1,
      ticker: `T${String(index).padStart(2, "0")}`,
      long_term_return_pct: 40 - index,
      short_term_return_pct: 10 - index / 2,
      industry: "Synthetic Industry",
      profit_summary: "獲利；營收年增 +20.0%；營益率 15.0%；淨利率 10.0%",
      long_term_window: "2y_cagr",
      short_term_window: "6m_price_return",
      market_source: "yfinance",
      profit_source: "sec_edgar",
      retrieved_at: "2026-08-31T00:00:00Z",
      provider_scope: "public_only",
      owner_watchlist_inherited: false,
    })),
    provider_scope: "public_only",
    owner_watchlist_inherited: false,
  };
}

function env() {
  const publicKv = new MemoryKv();
  return {
    publicKv,
    value: {
      PUBLIC_CACHE: asKv(publicKv),
      TENANT_PRIVATE_CACHE: asKv(new MemoryKv()),
      EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()),
    },
  };
}

describe("v2.1.2 five-field Top 20", () => {
  it("accepts exactly twenty closed-schema rows", () => {
    expect(parseV212Top20Report(report())).not.toBeNull();
    const bad = report() as Record<string, unknown>;
    (bad.records as Array<Record<string, unknown>>)[0]!.serenity_score = 99;
    expect(parseV212Top20Report(bad)).toBeNull();
  });

  it("renders only the requested five display columns", () => {
    const parsed = parseV212Top20Report(report());
    expect(parsed).not.toBeNull();
    const text = formatV212Top20Report(parsed!);
    expect(text.split("\n")[0]).toBe("股票｜長期投資報酬率｜短期投資報酬率｜行業別｜獲利簡述");
    expect(text).not.toContain("Serenity");
    expect(text).not.toContain("品質");
    expect(text).not.toContain("Aschenbrenner");
    expect(text).not.toContain("資料來源");
    expect(text).not.toContain("#1");
    for (const line of text.split("\n")) {
      expect(line.split("｜")).toHaveLength(5);
    }
  });

  it("answers Top 20 with the five-field report and refuses legacy fallback", async () => {
    const { publicKv, value } = env();
    await publicKv.put("snapshot:current", JSON.stringify({ run_id: "run-1" }));
    await publicKv.put("snapshot:run-1:v212:top20-report:latest", JSON.stringify(report()));
    const answer = await v212Top20ReportAnswer(value, parseQuery("Top 20"));
    expect(answer).toContain("股票｜長期投資報酬率｜短期投資報酬率｜行業別｜獲利簡述");

    const missing = env().value;
    const blocked = await v212Top20ReportAnswer(missing, parseQuery("Top 20"));
    expect(blocked).toContain("不會退回舊欄位格式");
  });

  it("ingests only when report order matches the current signed Top 20", async () => {
    const { publicKv, value } = env();
    const runId = "20260831T000000Z-0123456789ab";
    await publicKv.put("snapshot:current", JSON.stringify({ run_id: runId }));
    await publicKv.put(
      `snapshot:${runId}:v21:top20:latest`,
      JSON.stringify(Array.from({ length: 20 }, (_, index) => topRecord(index))),
    );
    const accepted = await ingestV212Top20Report(JSON.stringify(report()), value);
    expect(accepted.report_count).toBe(20);
    expect(publicKv.values.has(`snapshot:${runId}:v212:top20-report:latest`)).toBe(true);

    const reordered = report();
    const first = reordered.records[0]!;
    reordered.records[0] = reordered.records[1]!;
    reordered.records[1] = first;
    await expect(ingestV212Top20Report(JSON.stringify(reordered), value)).rejects.toThrow();
  });
});
