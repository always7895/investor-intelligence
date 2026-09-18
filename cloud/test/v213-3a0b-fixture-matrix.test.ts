import { describe, it, expect, vi, afterEach } from "vitest";
import { asKv, MemoryKv } from "./fake-kv";
import { sealUnboundReport } from "./sealed-report-migration";
import {
  loadV213FreshTop20Report,
  parseV213Top20Report,
  v213PolicyBindingMatches,
  V213_STALE_RECORDS_MESSAGE,
  V213_NO_CURRENT_ORDERS,
  V213_NO_FUTURE_ORDER_ESTIMATE,
} from "../src/v213/top20-report";
import { INSUFFICIENT_EVIDENCE_MESSAGE } from "../src/v213/bottleneck-report";
import { pinPublicSnapshot } from "../src/v213/public-snapshot";
import { buildV213Top20Messages } from "../src/v213/top20-presentation";
import type { V213Top20Env } from "../src/v213/top20-report";
import type { ParsedQuery } from "../src/core";

const POLICY_ID = "v213-serenity-fresh-independent-evidence-v2";
const POLICY_SHA = "27ce461fae50218bb14e4d50ff283f6ed75b201e4a38d656643a5ed65d59c8d8";
// Legacy no-report (policy-binding rejected) attribution: distinct from seal
// failure (INSUFFICIENT) and from evidence-window staleness (V213_STALE_RECORDS).
const NOT_ACCEPTED_MESSAGE = "七欄 Top20 報告尚未通過驗證；不退回五欄。 / Seven-field Top20 unavailable; no five-field fallback.";
const DISPLAY_COLUMNS = [
  "股票", "長期投資報酬率（近2年年化）", "短期投資報酬率（近6個月）",
  "行業別", "獲利簡述", "公司現在訂單", "未來訂單預估",
];

// Exactly the 26 REQUIRED_RECORD_KEYS the parser accepts (no extras).
function record(index: number, o: { ordersAsOf: string; retrievedAt: string }) {
  return {
    schema_version: 2,
    rank: index + 1,
    ticker: `T${String(index).padStart(2, "0")}`,
    name: `Synthetic ${index}`,
    long_term_return_pct: 50 - index,
    short_term_return_pct: 15 - index / 2,
    industry: "半導體",
    profit_summary: "獲利；營收年增 +20.0%",
    current_orders: V213_NO_CURRENT_ORDERS,
    future_orders_estimate: V213_NO_FUTURE_ORDER_ESTIMATE,
    long_term_window: "2y_cagr",
    short_term_window: "6m_price_return",
    market_source: "yfinance",
    profit_source: "sec_edgar",
    orders_as_of: o.ordersAsOf,
    orders_confidence: "UNAVAILABLE",
    current_order_source_urls: [],
    future_order_source_urls: [],
    numeric_total_order_estimate_prohibited: true,
    retrieved_at: o.retrievedAt,
    orders_state_as_of: o.ordersAsOf,
    evidence_class: "structural_claim",
    freshness_policy_key: "structural_claim_max_age_days",
    test_only_admission: true,
    provider_scope: "public_only",
    owner_watchlist_inherited: false,
  };
}

function validReport(o: { generatedAt?: string; evidenceCaptureAt?: string; ordersAsOf?: string; retrievedAt?: string; policySha?: string } = {}) {
  const generatedAt = o.generatedAt ?? "2026-09-18T00:00:00Z";
  const evidenceCaptureAt = o.evidenceCaptureAt ?? "2026-09-18T00:00:00Z";
  const ordersAsOf = o.ordersAsOf ?? "2026-09-18T00:00:00Z";
  const retrievedAt = o.retrievedAt ?? "2026-09-18T00:00:00Z";
  return {
    schema_version: 2,
    product_version: "2.1.3",
    generated_at: generatedAt,
    freshness_policy: { policy_id: POLICY_ID, policy_sha256: o.policySha ?? POLICY_SHA },
    evidence_capture_at: evidenceCaptureAt,
    display_columns: DISPLAY_COLUMNS,
    long_term_definition: "trailing_2y_adjusted_close_cagr",
    short_term_definition: "trailing_6m_adjusted_close_price_return",
    records: Array.from({ length: 20 }, (_, i) => record(i, { ordersAsOf, retrievedAt })),
    provider_scope: "public_only",
    owner_watchlist_inherited: false,
  };
}

function makeEnv(kv: MemoryKv): V213Top20Env {
  return {
    PUBLIC_CACHE: asKv(kv),
    TENANT_PRIVATE_CACHE: asKv(new MemoryKv()),
    EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()),
    V213_FIELD_LOCALE: "en",
    V21_TOP20_MAX_AGE_SECONDS: "86400",
  } as unknown as V213Top20Env;
}

const rankingQuery: ParsedQuery = {
  intent: "ranking", ticker: null, period: "weekly", referenceId: null, normalized: "Top 20 bottleneck ranking",
};

// Seal a report into a run-bound snapshot. The helper reads the top-level
// v213:top20-report:latest + last_successful_pipeline_timestamp, deletes them,
// and re-packages the SAME bytes under snapshot:<runId>:<key> with a valid seal.
async function sealReport(kv: MemoryKv, report: unknown, stamp: string, runId: string): Promise<void> {
  kv.values.set("v213:top20-report:latest", JSON.stringify(report));
  kv.values.set("last_successful_pipeline_timestamp", stamp);
  await sealUnboundReport(kv, runId);
}

// Legacy (non-sealed) view WITH a run_id pointer: kind="snapshot", integrity="legacy".
// The reader reads objects under snapshot:<runId>:<key>, so the report and the
// pipeline stamp must be stored there (a pointerless view fails closed to
// INSUFFICIENT, and a top-level stamp is not read when a runId is set).
function legacyView(kv: MemoryKv, report: unknown, stamp: string): void {
  const runId = "20260918T000000Z-aaaaaaaaaaaaaaaa";
  kv.values.set("snapshot:current", runId);
  kv.values.set(`snapshot:${runId}:v213:top20-report:latest`, JSON.stringify(report));
  kv.values.set(`snapshot:${runId}:last_successful_pipeline_timestamp`, stamp);
}

afterEach(() => { vi.useRealTimers(); });

describe("TASK0-3A-0B offline fixture matrix (items 1,2,3,5)", () => {
  it("1: valid schema-2 minus a required evidence field -> parser rejects; sealed branch returns insufficient (not freshness window)", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-18T00:00:00Z"));
    const broken = validReport();
    for (const rec of broken.records) delete (rec as Record<string, unknown>).evidence_class;
    expect(parseV213Top20Report(broken)).toBeNull();
    const kv = new MemoryKv();
    // Fresh clock + fresh seal stamp: the ONLY possible failure is the parser,
    // so a freshness-window rejection is ruled out by construction.
    await sealReport(kv, broken, "2026-09-18T00:00:00Z", "20260918T000000Z-aaaaaaaaaaaa");
    const out = await loadV213FreshTop20Report(makeEnv(kv), rankingQuery);
    expect(out).toBe(INSUFFICIENT_EVIDENCE_MESSAGE);
    expect(out).not.toBe(V213_STALE_RECORDS_MESSAGE);
  });

  it("2: schema/policy binding complete but evidence date expired -> parser passes, then fails at evidence window and returns stale", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-18T00:00:00Z"));
    const report = validReport({
      generatedAt: "2026-09-18T00:00:00Z",
      evidenceCaptureAt: "2020-01-01T00:00:00Z",
      ordersAsOf: "2020-01-01T00:00:00Z",
      retrievedAt: "2020-01-01T00:00:00Z",
    });
    expect(parseV213Top20Report(report)).not.toBeNull();
    const kv = new MemoryKv();
    legacyView(kv, report, "2026-09-18T00:00:00Z");
    const out = await loadV213FreshTop20Report(makeEnv(kv), rankingQuery);
    expect(out).toBe(V213_STALE_RECORDS_MESSAGE);
  });

  it("3: all schema, binding, time, and existing admission data valid -> positive control reaches the presentation path", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-18T00:00:00Z"));
    const report = validReport();
    const kv = new MemoryKv();
    legacyView(kv, report, "2026-09-18T00:00:00Z");
    const result = await loadV213FreshTop20Report(makeEnv(kv), rankingQuery);
    expect(typeof result).not.toBe("string");
    expect(result).not.toBeNull();
    const rep = result as { records: unknown[] };
    expect(rep.records).toHaveLength(20);
    const messages = buildV213Top20Messages(result as never);
    expect(Array.isArray(messages)).toBe(true);
    expect(messages.length).toBeGreaterThan(0);
  });

  it("5a: seal/manifest invalid (tampered sealed object) -> integrity invalid and insufficient attribution", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-18T00:00:00Z"));
    const kv = new MemoryKv();
    const runId = "20260918T000000Z-bbbbbbbbbbbb";
    await sealReport(kv, validReport(), "2026-09-18T00:00:00Z", runId);
    // Tamper one sealed object body so the seal manifest no longer matches.
    kv.values.set(`snapshot:${runId}:v213:top20-report:latest`, JSON.stringify({ tampered: true }));
    const view = await pinPublicSnapshot(makeEnv(kv));
    expect(view.integrity).toBe("invalid");
    const out = await loadV213FreshTop20Report(makeEnv(kv), rankingQuery);
    expect(out).toBe(INSUFFICIENT_EVIDENCE_MESSAGE);
  });

  it("5b: policy binding invalid -> attributed separately (not stale, not insufficient)", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-18T00:00:00Z"));
    const report = validReport({ policySha: "f".repeat(64) });
    expect(await v213PolicyBindingMatches(report.freshness_policy)).toBe(false);
    const kv = new MemoryKv();
    legacyView(kv, report, "2026-09-18T00:00:00Z");
    const out = await loadV213FreshTop20Report(makeEnv(kv), rankingQuery);
    expect(out).toBe(NOT_ACCEPTED_MESSAGE);
    expect(out).not.toBe(V213_STALE_RECORDS_MESSAGE);
    expect(out).not.toBe(INSUFFICIENT_EVIDENCE_MESSAGE);
  });
});