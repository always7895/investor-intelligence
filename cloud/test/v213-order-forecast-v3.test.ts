import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  CONDITION_TEXT_V3,
  computeReceiptDigest,
  forecastCard,
  forecastLines,
  forecastText,
  parseOrderForecast,
  parseOrderForecastV3,
  type ForecastHorizon,
  type OrderForecast,
} from "../src/v213/order-forecast";
import {
  buildBottleneckDetail,
  buildBottleneckTop20Messages,
  outlookForecast,
  parseBottleneckV3,
} from "../src/v213/bottleneck-v3";
import { assertLineMessages } from "../src/line-messages";
import { doc, HOUR } from "./bottleneck-v3-fixture";
import v2Fixture from "../../tests/fixtures/v213-order-forecast-v2.json";

const GENERATED = "2026-09-28T12:00:00Z";
// The golden build clock sits after the writer's 14:45Z CRWV IR review (verify/ir-live-2026-09-28.txt), so the
// reviewed item is admissible; the strict reviewed_at <= cutoff rule is unchanged (the sealer's fixed cutoff,
// see tests/fixtures/make_orders_v3_golden.py).
const GOLDEN_GENERATED = "2026-09-28T15:00:00Z";
// The nine issuers with a reviewed official IR channel in the writer's registry (verify/ir-channels.json); the
// five blocked issuers (SNDK AVGO MTSI AAOI ALAB) carry no IR channel, so their company-guidance path suspends.
const IR_ISSUERS = new Set(["NVDA", "MU", "LITE", "MRVL", "AMD", "CRDO", "BE", "NBIS", "CRWV"]);
const REPORT_DAY = "2026-09-28";
const REPORT_MS = Date.parse(GENERATED);
const money = (val: number, cur: string | null) => `${cur ?? "USD"} ${val >= 1e9 ? `${(val / 1e9).toFixed(1)}B` : val}`;

/** The synthetic record's reviewed official IR feed (Astra W1 ruling, astra-ir-coverage). */
const irChannelUrl = (issuer: string) =>
  `https://investor.${issuer.toLowerCase().replace(/[^a-z0-9]/g, "")}.com/feed/PressRelease.svc/GetPressReleaseList`;

function makeReceipt(issuer = "NVDA", anchorEnd = "2026-06-30", guidanceDoc = "DOC-GUIDANCE", guidancePub = "2026-08-20", chk = "2026-09-28T10:00:00Z", receiptStatus = "OK", withIr = true): any {
  const r: any = {
    issuer,
    checked_at: chk,
    status: receiptStatus,
    guidance_document_id: guidanceDoc,
    guidance_published_date: guidancePub,
    anchor_end: anchorEnd,
    coverage: withIr ? "SEC_WIRE_IR" : "SEC_AND_WIRE",
    channels: [
      { kind: "SEC_SUBMISSIONS", url: "https://data.sec.gov/submissions/CIK0000000000.json", status: "OK", checked_through: "2026-09-28", complete: true },
      { kind: "WIRE_PRESS_RELEASES", url: `https://api.nasdaq.com/api/news/topic/press_release?q=symbol:${issuer}`, status: "OK", checked_through: "2026-09-28", complete: true },
      ...(withIr ? [{ kind: "ISSUER_IR", url: irChannelUrl(issuer), status: "OK", checked_through: "2026-09-28", complete: true }] : []),
    ],
    later_documents: [],
  };
  r.digest = computeReceiptDigest(r);
  return r;
}

function makeSyntheticV3(overrides: Record<string, any> = {}): any {
  const iss = overrides.issuer ?? "NVDA";
  const anchorDate = overrides.anchor_date ?? "2026-06-30";
  const fw = overrides.forward_quarters ?? [
    { quarter_index: 1, fiscal_label: "Q1", start: "2026-07-01", end: "2026-09-30", amount: 120.0, revenue: 120.0, derivation: "公司財測" },
    { quarter_index: 2, fiscal_label: "Q2", start: "2026-10-01", end: "2026-12-31", amount: 120.0, revenue: 120.0, derivation: "模型：之後各季持平於公司財測" },
    { quarter_index: 3, fiscal_label: "Q3", start: "2027-01-01", end: "2027-03-31", amount: 120.0, revenue: 120.0, derivation: "模型：之後各季持平於公司財測" },
    { quarter_index: 4, fiscal_label: "Q4", start: "2027-04-01", end: "2027-06-30", amount: 120.0, revenue: 120.0, derivation: "模型：之後各季持平於公司財測" },
  ];
  const actuals = overrides.reported_quarters ?? [
    { fiscal_label: "Q1 FY25", start: "2025-07-01", end: "2025-09-30", revenue: 80.0, currency: "USD", scope: "COMPANY", accounting_basis: "GAAP", document_id: "DOC-10K", locator: "p.1" },
    { fiscal_label: "Q2 FY25", start: "2025-10-01", end: "2025-12-31", revenue: 90.0, currency: "USD", scope: "COMPANY", accounting_basis: "GAAP", document_id: "DOC-10K", locator: "p.2" },
    { fiscal_label: "Q3 FY25", start: "2026-01-01", end: "2026-03-31", revenue: 100.0, currency: "USD", scope: "COMPANY", accounting_basis: "GAAP", document_id: "DOC-10K", locator: "p.3" },
    { fiscal_label: "Q4 FY25", start: "2026-04-01", end: "2026-06-30", revenue: 110.0, currency: "USD", scope: "COMPANY", accounting_basis: "GAAP", document_id: "DOC-10K", locator: "p.4" },
  ];
  const intervals = overrides.forward_intervals ?? fw.map((f: any) => ({ fiscal_label: f.fiscal_label, start: f.start, end: f.end,
    // The forward intervals are bound to the fiscal calendar document (Astra r5 item 10: calendar links on every branch).
    calendar_document_id: "DOC-10K", calendar_locator: "p.10" }));
  const defaultDocs = [
    {
      id: "DOC-GUIDANCE",
      issuer: iss,
      publisher: "Issuer Corporation",
      title: "Earnings Release with Guidance",
      source_kind: "ISSUER_EARNINGS_RELEASE",
      url: `https://investor.${iss.toLowerCase().replace(/[^a-z0-9]/g, "")}.com/release.pdf`,
      published_date: "2026-08-20",
      retrieved_at: "2026-08-20T12:00:00Z",
      sha256: "0".repeat(64),
      byte_size: 1000,
      lineage_id: "L1",
    },
    {
      id: "DOC-10K",
      issuer: iss,
      publisher: "Issuer Corporation",
      title: "Form 10-K",
      source_kind: "OFFICIAL_FISCAL_CALENDAR",
      url: `https://investor.${iss.toLowerCase().replace(/[^a-z0-9]/g, "")}.com/10k.pdf`,
      published_date: "2026-08-20",
      retrieved_at: "2026-08-20T12:00:00Z",
      sha256: "1".repeat(64),
      byte_size: 2000,
      lineage_id: "L2",
    },
  ];
  const defaultClaims = [
    {
      id: "CLAIM-1",
      document_id: "DOC-GUIDANCE",
      locator: "p.1",
      passage: "Revenue is expected to be $120.0",
      metric: "REVENUE",
      assertion_kind: "COMPANY_GUIDANCE",
      currency: "USD",
      unit_multiplier: 1,
      stated_point: 120.0,
      scope: "COMPANY",
      accounting_basis: "GAAP",
      fiscal_label: "Q1",
      period_kind: "QUARTER",
      period_start: fw[0].start,
      period_end: fw[0].end,
    },
  ];
  const base: any = {
    version: 3,
    issuer: iss,
    formula: "ORDERS-V3-01",
    horizon_convention: "FISCAL_2Q_4Q",
    status: "AVAILABLE",
    revenue_status: "AVAILABLE",
    revenue_basis: "COMPANY_GUIDANCE",
    anchor_date: anchorDate,
    cutoff: GENERATED,
    m6: {
      status: "AVAILABLE",
      basis: "COMPANY_GUIDANCE",
      basis_label: "公司營收財測＋模型（非訂單）",
      amount: 240.0,
      currency: "USD",
      start: fw[0].start,
      end: fw[1].end,
      horizon_label: "約6個月（2財季）",
      qualifier: `自${fw[0].start}起，非今日起`,
      ttm_revenue: 450.0,
      scenario: { status: "AVAILABLE", change: 70.0 / 380.0 },
    },
    m12: {
      status: "AVAILABLE",
      basis: "COMPANY_GUIDANCE",
      basis_label: "公司營收財測＋模型（非訂單）",
      amount: 480.0,
      currency: "USD",
      start: fw[0].start,
      end: fw[3].end,
      horizon_label: "約1年（4財季）",
      qualifier: `自${fw[0].start}起，非今日起`,
      ttm_revenue: 480.0,
      scenario: { status: "AVAILABLE", change: 100.0 / 380.0 },
    },
    reported_quarters: actuals,
    baseline_b: 380.0,
    forward_quarters: fw,
    references: [],
    ...overrides,
  };
  // The sealer always seals the order view beside a v3 (item 7); complete the synthetic records with the
  // unavailable no-order view (a sibling v2 with orders supplies its own order_view through the outer record).
  base.order_view = base.order_view ?? {
    status: "UNAVAILABLE",
    reason: "NOT_DISCLOSED_HORIZON",
    m6: { status: "UNAVAILABLE", reason: "NOT_DISCLOSED_HORIZON", scenario: { status: "NO_BASIS", reason: "NO_REVENUE_BASIS" } },
    m12: { status: "UNAVAILABLE", reason: "NOT_DISCLOSED_HORIZON", scenario: { status: "NO_BASIS", reason: "NO_REVENUE_BASIS" } },
  };
  base.evidence = {
    revenue_registry_status: "OK",
    revenue_registry_sha256: "0".repeat(64),
    cutoff: base.cutoff ?? GENERATED,
    formula: "ORDERS-V3-01",
    url_prefixes: [`https://investor.${iss.toLowerCase().replace(/[^a-z0-9]/g, "")}.com/`],
    documents: defaultDocs,
    claims: defaultClaims,
    reported_quarters: actuals,
    forward_intervals: intervals,
    // The record's reviewed official IR channel (Astra W1 ruling, astra-ir-coverage): the company-guidance path
    // requires the SEC_WIRE_IR coverage with the IR channel on this host, so the synthetic record carries it.
    release_channels: {
      wire_symbol: iss,
      ir: { kind: "Q4_PRESS_RELEASES", url: irChannelUrl(iss) },
      ir_guidance_release_title: "Issuer Reports Financial Results",
    },
    latest_release_check: makeReceipt(iss, anchorDate, "DOC-GUIDANCE", "2026-08-20"),
    // A3/A6 (acceptance r7): the registry's explicit consensus gate seals with the evidence; off by default
    // (the first rollout defers the consensus route), overridden per-test where the route is exercised.
    consensus_enabled: false,
    // A1 (acceptance r7): the enforced reviewed profile seals beside the record - the approval file's sha256, its
    // approved_at and the record's review decisions covering the sealed inputs (claim, actuals, calendar, routing).
    approval_sha256: "0".repeat(63) + "1",
    approval_approved_at: "2026-09-28T11:00:00Z",
    approval_decisions: [
      { kind: "CLAIM", ref: "CLAIM-1", decision: "VERBATIM_IN_SOURCE", reviewed_at: "2026-09-28T11:00:00Z" },
      ...actuals.map((q: any) => ({ kind: "ACTUAL", ref: q.end, decision: "VALUE_IN_SOURCE", reviewed_at: "2026-09-28T11:00:00Z" })),
      { kind: "CALENDAR", ref: "calendar", decision: "RULE_QUOTED", reviewed_at: "2026-09-28T11:00:00Z" },
      { kind: "ROUTING", ref: "routing", decision: "RULE_QUOTED", reviewed_at: "2026-09-28T11:00:00Z" },
    ],
    ...(overrides.evidence ?? {}),
  };
  // The v3 schema requires original_representation (and fiscal_label) on every sealed claim; complete the synthetic
  // claims so they satisfy the strict validator (a missing field is a fixture gap, not a relaxation).
  if (Array.isArray(base.evidence.claims)) {
    for (const c of base.evidence.claims) {
      if (c && typeof c === "object") {
        if (typeof c.original_representation !== "string") {
          c.original_representation = c.stated_point !== undefined && c.stated_point !== null
            ? `${c.stated_point}`
            : (c.low !== undefined && c.high !== undefined ? `${c.low}–${c.high}` : "unquantified guidance");
        }
        if (typeof c.fiscal_label !== "string") c.fiscal_label = c.period_kind === "FISCAL_YEAR" ? "FY" : "Q";
      }
    }
  }
  return base;
}

describe("version-3 order & revenue forecast", () => {
  it("implements Section 8.1 synthetic Oracles 1-7 exactly", () => {
    // Oracle 1: quarter guidance G=120, actuals=[80, 90, 100, 110]
    const o1 = parseOrderForecast(makeSyntheticV3(), REPORT_DAY, "NVDA", GENERATED);
    expect(o1.version).toBe(3);
    expect(o1.m6.status).toBe("AVAILABLE");
    expect(o1.m6.amount).toBe(240.0);
    expect(o1.m12.amount).toBe(480.0);
    expect(o1.m6.scenario.change).toBeCloseTo(70.0 / 380.0, 9);
    expect(o1.m12.scenario.change).toBeCloseTo(100.0 / 380.0, 9);

    // Oracle 2: FY guidance FY=500, YTD=210, n=2, forward=[145, 145, 145, 145]
    const fw2 = [
      { quarter_index: 1, fiscal_label: "Q3", start: "2026-07-01", end: "2026-09-30", amount: 145.0, revenue: 145.0, derivation: "模型：全年財測扣已報營收，剩餘各季均分" },
      { quarter_index: 2, fiscal_label: "Q4", start: "2026-10-01", end: "2026-12-31", amount: 145.0, revenue: 145.0, derivation: "模型：全年財測扣已報營收，剩餘各季均分" },
      { quarter_index: 3, fiscal_label: "Q1", start: "2027-01-01", end: "2027-03-31", amount: 145.0, revenue: 145.0, derivation: "模型：後續各季持平於財測推算末季" },
      { quarter_index: 4, fiscal_label: "Q2", start: "2027-04-01", end: "2027-06-30", amount: 145.0, revenue: 145.0, derivation: "模型：後續各季持平於財測推算末季" },
    ];
    const claims2 = [
      {
        id: "CLAIM-FY",
        document_id: "DOC-GUIDANCE",
        locator: "p.1",
        passage: "FY revenue 500",
        metric: "REVENUE",
        assertion_kind: "COMPANY_GUIDANCE",
        currency: "USD",
        unit_multiplier: 1,
        stated_point: 500.0,
        scope: "COMPANY",
        accounting_basis: "GAAP",
        fiscal_label: "FY26",
        period_kind: "FISCAL_YEAR",
        period_start: "2026-01-01",
        period_end: "2026-12-31",
      },
    ];
    const o2 = parseOrderForecast(
      makeSyntheticV3({
        forward_quarters: fw2,
        m6: { status: "AVAILABLE", basis: "COMPANY_GUIDANCE", amount: 290.0, currency: "USD", start: "2026-07-01", end: "2026-12-31", ttm_revenue: 500.0, scenario: { status: "AVAILABLE", change: 120.0 / 380.0 } },
        m12: { status: "AVAILABLE", basis: "COMPANY_GUIDANCE", amount: 580.0, currency: "USD", start: "2026-07-01", end: "2027-06-30", ttm_revenue: 580.0, scenario: { status: "AVAILABLE", change: 200.0 / 380.0 } },
        evidence: {
          claims: claims2,
          fy_reconciliation: {
            fy_claim_id: "CLAIM-FY",
            ytd_start: "2026-01-01",
            ytd_end: "2026-06-30",
            ytd_revenue: 210.0,
            ytd_quarter_ends: ["2026-03-31", "2026-06-30"],
          },
        },
      }),
      REPORT_DAY,
      "NVDA",
      GENERATED
    );
    expect(o2.m6.amount).toBe(290.0);
    expect(o2.m12.amount).toBe(580.0);
    expect(o2.m6.scenario.change).toBeCloseTo(120.0 / 380.0, 9);
    expect(o2.m12.scenario.change).toBeCloseTo(200.0 / 380.0, 9);

    // Oracle 3: concurrent quarter G=130 + FY=500, YTD=210 -> forward=[130, 160, 160, 160]
    const fw3 = [
      { quarter_index: 1, fiscal_label: "Q3", start: "2026-07-01", end: "2026-09-30", amount: 130.0, revenue: 130.0, derivation: "公司財測" },
      { quarter_index: 2, fiscal_label: "Q4", start: "2026-10-01", end: "2026-12-31", amount: 160.0, revenue: 160.0, derivation: "模型：全年財測扣已報營收及下季財測，剩餘各季均分" },
      { quarter_index: 3, fiscal_label: "Q1", start: "2027-01-01", end: "2027-03-31", amount: 160.0, revenue: 160.0, derivation: "模型：後續各季持平於財測推算末季" },
      { quarter_index: 4, fiscal_label: "Q2", start: "2027-04-01", end: "2027-06-30", amount: 160.0, revenue: 160.0, derivation: "模型：後續各季持平於財測推算末季" },
    ];
    const claims3 = [
      {
        id: "CLAIM-Q",
        document_id: "DOC-GUIDANCE",
        locator: "p.1",
        passage: "Q revenue 130",
        metric: "REVENUE",
        assertion_kind: "COMPANY_GUIDANCE",
        currency: "USD",
        unit_multiplier: 1,
        stated_point: 130.0,
        scope: "COMPANY",
        accounting_basis: "GAAP",
        fiscal_label: "Q1",
        period_kind: "QUARTER",
        period_start: "2026-07-01",
        period_end: "2026-09-30",
      },
      {
        id: "CLAIM-FY",
        document_id: "DOC-GUIDANCE",
        locator: "p.2",
        passage: "FY revenue 500",
        metric: "REVENUE",
        assertion_kind: "COMPANY_GUIDANCE",
        currency: "USD",
        unit_multiplier: 1,
        stated_point: 500.0,
        scope: "COMPANY",
        accounting_basis: "GAAP",
        fiscal_label: "FY26",
        period_kind: "FISCAL_YEAR",
        period_start: "2026-01-01",
        period_end: "2026-12-31",
      },
    ];
    const o3 = parseOrderForecast(
      makeSyntheticV3({
        forward_quarters: fw3,
        m6: { status: "AVAILABLE", basis: "COMPANY_GUIDANCE", amount: 290.0, currency: "USD", start: "2026-07-01", end: "2026-12-31", ttm_revenue: 500.0, scenario: { status: "AVAILABLE", change: 120.0 / 380.0 } },
        m12: { status: "AVAILABLE", basis: "COMPANY_GUIDANCE", amount: 610.0, currency: "USD", start: "2026-07-01", end: "2027-06-30", ttm_revenue: 610.0, scenario: { status: "AVAILABLE", change: 230.0 / 380.0 } },
        evidence: {
          claims: claims3,
          fy_reconciliation: {
            fy_claim_id: "CLAIM-FY",
            ytd_start: "2026-01-01",
            ytd_end: "2026-06-30",
            ytd_revenue: 210.0,
            ytd_quarter_ends: ["2026-03-31", "2026-06-30"],
          },
        },
      }),
      REPORT_DAY,
      "NVDA",
      GENERATED
    );
    expect(o3.m6.amount).toBe(290.0);
    expect(o3.m12.amount).toBe(610.0);
    expect(o3.m6.scenario.change).toBeCloseTo(120.0 / 380.0, 9);
    expect(o3.m12.scenario.change).toBeCloseTo(230.0 / 380.0, 9);

    // Oracle 4: consensus C1=120, C2=130 -> forward=[120, 130, 130, 130]
    const fw4 = [
      { quarter_index: 1, fiscal_label: "Q1", start: "2026-07-01", end: "2026-09-30", amount: 120.0, revenue: 120.0, derivation: "分析師共識" },
      { quarter_index: 2, fiscal_label: "Q2", start: "2026-10-01", end: "2026-12-31", amount: 130.0, revenue: 130.0, derivation: "分析師共識" },
      { quarter_index: 3, fiscal_label: "Q3", start: "2027-01-01", end: "2027-03-31", amount: 130.0, revenue: 130.0, derivation: "模型：持平於次季分析師共識" },
      { quarter_index: 4, fiscal_label: "Q4", start: "2027-04-01", end: "2027-06-30", amount: 130.0, revenue: 130.0, derivation: "模型：持平於次季分析師共識" },
    ];
    const o4 = parseOrderForecast(
      makeSyntheticV3({
        revenue_basis: "CONSENSUS",
        forward_quarters: fw4,
        m6: { status: "AVAILABLE", basis: "CONSENSUS", amount: 250.0, currency: "USD", start: "2026-07-01", end: "2026-12-31", ttm_revenue: 460.0, scenario: { status: "AVAILABLE", change: 80.0 / 380.0 } },
        m12: { status: "AVAILABLE", basis: "CONSENSUS", amount: 510.0, currency: "USD", start: "2026-07-01", end: "2027-06-30", ttm_revenue: 510.0, scenario: { status: "AVAILABLE", change: 130.0 / 380.0 } },
        evidence: {
          // A3/A6: this oracle exercises the consensus route, so the registry gate is explicitly on.
          consensus_enabled: true,
          consensus: {
            symbol: "NVDA",
            captured_at: "2026-09-28T10:00:00Z",
            currency: "USD",
            quarters: [
              { period: "0q", end: "2026-09-30", revenue: 120.0, analysts: 10 },
              { period: "+1q", end: "2026-12-31", revenue: 130.0, analysts: 10 },
            ],
          },
        },
      }),
      REPORT_DAY,
      "NVDA",
      GENERATED
    );
    expect(o4.m6.amount).toBe(250.0);
    expect(o4.m12.amount).toBe(510.0);
    expect(o4.m6.scenario.change).toBeCloseTo(80.0 / 380.0, 9);
    expect(o4.m12.scenario.change).toBeCloseTo(130.0 / 380.0, 9);

    // Oracle 5: flat equality
    const flatActuals = [
      { fiscal_label: "Q1", start: "2025-07-01", end: "2025-09-30", revenue: 100.0, currency: "USD", scope: "COMPANY", accounting_basis: "GAAP", document_id: "DOC-10K", locator: "p.1" },
      { fiscal_label: "Q2", start: "2025-10-01", end: "2025-12-31", revenue: 100.0, currency: "USD", scope: "COMPANY", accounting_basis: "GAAP", document_id: "DOC-10K", locator: "p.2" },
      { fiscal_label: "Q3", start: "2026-01-01", end: "2026-03-31", revenue: 100.0, currency: "USD", scope: "COMPANY", accounting_basis: "GAAP", document_id: "DOC-10K", locator: "p.3" },
      { fiscal_label: "Q4", start: "2026-04-01", end: "2026-06-30", revenue: 100.0, currency: "USD", scope: "COMPANY", accounting_basis: "GAAP", document_id: "DOC-10K", locator: "p.4" },
    ];
    const fw5 = [
      { quarter_index: 1, fiscal_label: "Q1", start: "2026-07-01", end: "2026-09-30", amount: 100.0, revenue: 100.0, derivation: "公司財測" },
      { quarter_index: 2, fiscal_label: "Q2", start: "2026-10-01", end: "2026-12-31", amount: 100.0, revenue: 100.0, derivation: "模型：之後各季持平於公司財測" },
      { quarter_index: 3, fiscal_label: "Q3", start: "2027-01-01", end: "2027-03-31", amount: 100.0, revenue: 100.0, derivation: "模型：之後各季持平於公司財測" },
      { quarter_index: 4, fiscal_label: "Q4", start: "2027-04-01", end: "2027-06-30", amount: 100.0, revenue: 100.0, derivation: "模型：之後各季持平於公司財測" },
    ];
    const claims5 = [
      {
        id: "CLAIM-1",
        document_id: "DOC-GUIDANCE",
        locator: "p.1",
        passage: "Revenue is expected to be $100.0",
        metric: "REVENUE",
        assertion_kind: "COMPANY_GUIDANCE",
        currency: "USD",
        unit_multiplier: 1,
        stated_point: 100.0,
        scope: "COMPANY",
        accounting_basis: "GAAP",
        fiscal_label: "Q1",
        period_kind: "QUARTER",
        period_start: "2026-07-01",
        period_end: "2026-09-30",
      },
    ];
    const o5 = parseOrderForecast(
      makeSyntheticV3({
        reported_quarters: flatActuals,
        baseline_b: 400.0,
        forward_quarters: fw5,
        m6: { status: "AVAILABLE", basis: "COMPANY_GUIDANCE", amount: 200.0, currency: "USD", start: "2026-07-01", end: "2026-12-31", ttm_revenue: 400.0, scenario: { status: "AVAILABLE", change: 0.0 } },
        m12: { status: "AVAILABLE", basis: "COMPANY_GUIDANCE", amount: 400.0, currency: "USD", start: "2026-07-01", end: "2027-06-30", ttm_revenue: 400.0, scenario: { status: "AVAILABLE", change: 0.0 } },
        evidence: {
          claims: claims5,
          reported_quarters: flatActuals,
        },
      }),
      REPORT_DAY,
      "NVDA",
      GENERATED
    );
    expect(o5.m6.scenario.change).toBeCloseTo(0.0, 9);
    expect(o5.m12.scenario.change).toBeCloseTo(0.0, 9);

    // Oracle 6: negative returns
    const fw6 = [
      { quarter_index: 1, fiscal_label: "Q1", start: "2026-07-01", end: "2026-09-30", amount: 80.0, revenue: 80.0, derivation: "公司財測" },
      { quarter_index: 2, fiscal_label: "Q2", start: "2026-10-01", end: "2026-12-31", amount: 80.0, revenue: 80.0, derivation: "模型：之後各季持平於公司財測" },
      { quarter_index: 3, fiscal_label: "Q3", start: "2027-01-01", end: "2027-03-31", amount: 80.0, revenue: 80.0, derivation: "模型：之後各季持平於公司財測" },
      { quarter_index: 4, fiscal_label: "Q4", start: "2027-04-01", end: "2027-06-30", amount: 80.0, revenue: 80.0, derivation: "模型：之後各季持平於公司財測" },
    ];
    const claims6 = [
      {
        id: "CLAIM-1",
        document_id: "DOC-GUIDANCE",
        locator: "p.1",
        passage: "Revenue is expected to be $80.0",
        metric: "REVENUE",
        assertion_kind: "COMPANY_GUIDANCE",
        currency: "USD",
        unit_multiplier: 1,
        stated_point: 80.0,
        scope: "COMPANY",
        accounting_basis: "GAAP",
        fiscal_label: "Q1",
        period_kind: "QUARTER",
        period_start: "2026-07-01",
        period_end: "2026-09-30",
      },
    ];
    const o6 = parseOrderForecast(
      makeSyntheticV3({
        reported_quarters: flatActuals,
        baseline_b: 400.0,
        forward_quarters: fw6,
        m6: { status: "AVAILABLE", basis: "COMPANY_GUIDANCE", amount: 160.0, currency: "USD", start: "2026-07-01", end: "2026-12-31", ttm_revenue: 360.0, scenario: { status: "AVAILABLE", change: -0.10 } },
        m12: { status: "AVAILABLE", basis: "COMPANY_GUIDANCE", amount: 320.0, currency: "USD", start: "2026-07-01", end: "2027-06-30", ttm_revenue: 320.0, scenario: { status: "AVAILABLE", change: -0.20 } },
        evidence: {
          claims: claims6,
          reported_quarters: flatActuals,
        },
      }),
      REPORT_DAY,
      "NVDA",
      GENERATED
    );
    expect(o6.m6.scenario.change).toBeCloseTo(-0.10, 9);
    expect(o6.m12.scenario.change).toBeCloseTo(-0.20, 9);

    // Oracle 7: missing history
    const twoActuals = flatActuals.slice(2, 4);
    const o7 = parseOrderForecast(
      makeSyntheticV3({
        reported_quarters: twoActuals,
        baseline_b: null,
        m6: { status: "AVAILABLE", basis: "COMPANY_GUIDANCE", amount: 240.0, currency: "USD", start: "2026-07-01", end: "2026-12-31", scenario: { status: "NO_BASIS", reason: "NO_REVENUE_HISTORY" } },
        m12: { status: "AVAILABLE", basis: "COMPANY_GUIDANCE", amount: 480.0, currency: "USD", start: "2026-07-01", end: "2027-06-30", scenario: { status: "NO_BASIS", reason: "NO_REVENUE_HISTORY" } },
        evidence: {
          reported_quarters: twoActuals,
        },
      }),
      REPORT_DAY,
      "NVDA",
      GENERATED
    );
    expect(o7.m6.status).toBe("AVAILABLE");
    expect(o7.m6.amount).toBe(240.0);
    expect(o7.m6.scenario.status).toBe("NO_BASIS");
    expect(o7.m6.scenario.reason).toBe("NO_REVENUE_HISTORY");
  });

  it("handles the Astra staleness amendment and post-quarter-end bridge (+70d cap)", () => {
    // Forward Q1 ended on 2026-08-20 (39 days before report day 2026-09-28 <= 70d)
    const fwBridged = [
      { quarter_index: 1, fiscal_label: "Q1", start: "2026-05-21", end: "2026-08-20", amount: 120.0, revenue: 120.0, derivation: "公司財測" },
      { quarter_index: 2, fiscal_label: "Q2", start: "2026-08-21", end: "2026-11-20", amount: 120.0, revenue: 120.0, derivation: "模型：之後各季持平於公司財測" },
      { quarter_index: 3, fiscal_label: "Q3", start: "2026-11-21", end: "2027-02-20", amount: 120.0, revenue: 120.0, derivation: "模型：之後各季持平於公司財測" },
      { quarter_index: 4, fiscal_label: "Q4", start: "2027-02-21", end: "2027-05-20", amount: 120.0, revenue: 120.0, derivation: "模型：之後各季持平於公司財測" },
    ];
    const actualsBridged = [
      { fiscal_label: "Q1", start: "2025-05-21", end: "2025-08-20", revenue: 80.0, currency: "USD", scope: "COMPANY", accounting_basis: "GAAP", document_id: "DOC-10K", locator: "p.1" },
      { fiscal_label: "Q2", start: "2025-08-21", end: "2025-11-20", revenue: 90.0, currency: "USD", scope: "COMPANY", accounting_basis: "GAAP", document_id: "DOC-10K", locator: "p.2" },
      { fiscal_label: "Q3", start: "2025-11-21", end: "2026-02-20", revenue: 100.0, currency: "USD", scope: "COMPANY", accounting_basis: "GAAP", document_id: "DOC-10K", locator: "p.3" },
      { fiscal_label: "Q4", start: "2026-02-21", end: "2026-05-20", revenue: 110.0, currency: "USD", scope: "COMPANY", accounting_basis: "GAAP", document_id: "DOC-10K", locator: "p.4" },
    ];
    const claimsBridged = [
      {
        id: "CLAIM-1",
        document_id: "DOC-GUIDANCE",
        locator: "p.1",
        passage: "Revenue is expected to be $120.0",
        metric: "REVENUE",
        assertion_kind: "COMPANY_GUIDANCE",
        currency: "USD",
        unit_multiplier: 1,
        stated_point: 120.0,
        scope: "COMPANY",
        accounting_basis: "GAAP",
        fiscal_label: "Q1",
        period_kind: "QUARTER",
        period_start: "2026-05-21",
        period_end: "2026-08-20",
      },
    ];
    const warningObj = {
      quarter_index: 0,
      quarter_end: "2026-08-20",
      checked_at: "2026-09-28T10:00:00Z",
      text: "財測季度已於2026-08-20結束，實際營收尚未公布；截至2026-09-28T10:00:00Z查核；仍為財測／模型，非實績",
      is_fy: false,
      affected_ends: ["2026-08-20"],
    };
    const validBridged = parseOrderForecast(
      makeSyntheticV3({
        anchor_date: "2026-05-20",
        reported_quarters: actualsBridged,
        forward_quarters: fwBridged,
        m6: {
          status: "AVAILABLE",
          basis: "COMPANY_GUIDANCE",
          amount: 240.0,
          currency: "USD",
          start: "2026-05-21",
          end: "2026-11-20",
          ttm_revenue: 450.0,
          scenario: { status: "AVAILABLE", change: 70.0 / 380.0 },
          warning: warningObj,
        },
        m12: {
          status: "AVAILABLE",
          basis: "COMPANY_GUIDANCE",
          amount: 480.0,
          currency: "USD",
          start: "2026-05-21",
          end: "2027-05-20",
          ttm_revenue: 480.0,
          scenario: { status: "AVAILABLE", change: 100.0 / 380.0 },
          warning: warningObj,
        },
        warning: warningObj,
        evidence: {
          reported_quarters: actualsBridged,
          claims: claimsBridged,
          forward_intervals: fwBridged.map(f => ({ fiscal_label: f.fiscal_label, start: f.start, end: f.end,
            calendar_document_id: "DOC-10K", calendar_locator: "p.10" })),
          latest_release_check: makeReceipt("NVDA", "2026-05-20", "DOC-GUIDANCE", "2026-08-20", "2026-09-28T10:00:00Z"),
        },
      }),
      REPORT_DAY,
      "NVDA",
      GENERATED
    );
    expect(validBridged.m6.status).toBe("AVAILABLE");
    expect(validBridged.m6.warning?.text).toContain("已於2026-08-20結束，實際營收尚未公布");

    // Overdue by 71 days: quarter ended on 2026-07-19 (71 days before 2026-09-28) -> fails closed
    const fwOverdue = [
      { quarter_index: 1, fiscal_label: "Q1", start: "2026-04-19", end: "2026-07-19", amount: 120.0, revenue: 120.0 },
      { quarter_index: 2, fiscal_label: "Q2", start: "2026-07-20", end: "2026-10-20", amount: 120.0, revenue: 120.0 },
      { quarter_index: 3, fiscal_label: "Q3", start: "2026-10-21", end: "2027-01-20", amount: 120.0, revenue: 120.0 },
      { quarter_index: 4, fiscal_label: "Q4", start: "2027-01-21", end: "2027-04-20", amount: 120.0, revenue: 120.0 },
    ];
    const overdueRes = parseOrderForecast(
      makeSyntheticV3({
        anchor_date: "2026-04-18",
        forward_quarters: fwOverdue,
        m6: { status: "AVAILABLE", basis: "COMPANY_GUIDANCE", amount: 240.0, currency: "USD", start: "2026-04-19", end: "2026-10-20" },
        m12: { status: "AVAILABLE", basis: "COMPANY_GUIDANCE", amount: 480.0, currency: "USD", start: "2026-04-19", end: "2027-04-20" },
        evidence: {
          forward_intervals: fwOverdue.map(f => ({ fiscal_label: f.fiscal_label, start: f.start, end: f.end,
            calendar_document_id: "DOC-10K", calendar_locator: "p.10" })),
          latest_release_check: makeReceipt("NVDA", "2026-04-18", "DOC-GUIDANCE", "2026-08-20", "2026-09-28T10:00:00Z"),
        },
      }),
      REPORT_DAY,
      "NVDA",
      GENERATED
    );
    expect(overdueRes.m6.status).toBe("UNAVAILABLE");
    expect(overdueRes.m6.reason).toBe("INVALID");
  });

  it("verifies dual-reader compatibility cells", () => {
    // Cell 1: old reader + v2-only
    const v2Payload = {
      version: 2,
      issuer: "S1",
      status: "UNAVAILABLE",
      // An empty registry with no stock orders recomputes as NO_ORDERS (decideV2), never NOT_DISCLOSED.
      reason: "NO_ORDERS",
      m6: { status: "UNAVAILABLE", reason: "NO_ORDERS", scenario: { status: "NO_BASIS", reason: "NO_ORDER_BASIS" } },
      m12: { status: "UNAVAILABLE", reason: "NO_ORDERS", scenario: { status: "NO_BASIS", reason: "NO_ORDER_BASIS" } },
      references: [],
      stock_sensitivity: null,
      evidence: {
        registry_status: "EMPTY",
        registry_sha256: "0".repeat(64),
        cutoff: GENERATED,
        url_prefixes: [],
        documents: [],
        claims: [],
        // The sealed selection must be what selectClaims recomputes for an empty registry (never null).
        selection: { status: "OK", active: [], current_stock: null, schedule: null, filing: null, excluded: [] },
        periodic: null,
        stock_orders: null,
      },
    };
    const oldReadV2 = parseOrderForecast(v2Payload, REPORT_DAY, "S1", GENERATED);
    expect(oldReadV2.version).toBe(2);

    // Cell 2: old reader ignores v3 in dual-field structure
    const dualOutlook = {
      orders: null,
      consensus: null,
      scenarios: [],
      order_forecast: v2Payload,
      order_forecast_v3: makeSyntheticV3({ issuer: "S1" }),
    };
    const oldReaderCell2 = parseOrderForecast(dualOutlook.order_forecast, REPORT_DAY, "S1", GENERATED);
    expect(oldReaderCell2.version).toBe(2);
    expect(oldReaderCell2.m12.status).toBe("UNAVAILABLE");

    // Cell 3: new reader parses v2-only when v3 is absent
    const rawDocV2Only = doc(REPORT_MS);
    (rawDocV2Only.top as any)[1].outlook = {
      orders: null,
      consensus: null,
      scenarios: [],
      order_forecast: v2Payload,
    };
    const parsedV2Only = parseBottleneckV3(rawDocV2Only, REPORT_MS + HOUR);
    expect(parsedV2Only).not.toBeNull();
    expect(parsedV2Only!.top[1]!.forecast?.version).toBe(2);

    // Cell 4: new reader parses v3 from dual-field input
    const dualV3 = makeSyntheticV3({ issuer: "S1" });
    // A v3 beside a sibling v2 carries the sibling's sealed order evidence (order_evidence) and, when the sibling is a
    // recognition record, the bound contracted recognition.
    dualV3.evidence.order_evidence = { ...v2Payload.evidence };
    // The sealed order view mirrors the sibling v2's own tiles (item 7: the duplicated fields must be equal).
    dualV3.order_view = {
      status: "UNAVAILABLE",
      reason: "NO_ORDERS",
      m6: v2Payload.m6,
      m12: v2Payload.m12,
    };
    const rawDocDual = doc(REPORT_MS);
    (rawDocDual.top as any)[1].outlook = { orders: null, consensus: null, scenarios: [], order_forecast: v2Payload, order_forecast_v3: dualV3 };
    const parsedDual = parseBottleneckV3(rawDocDual, REPORT_MS + HOUR);
    expect(parsedDual).not.toBeNull();
    expect(parsedDual!.top[1]!.forecast?.version).toBe(3);
    expect(parsedDual!.top[1]!.forecast?.m6.amount).toBe(240.0);

    // Cell 5: new reader + present-invalid v3 + valid v2 MUST NOT DOWNGRADE to v2!
    const rawDocTamperedV3 = doc(REPORT_MS);
    (rawDocTamperedV3.top as any)[1].outlook = {
      orders: null,
      consensus: null,
      scenarios: [],
      order_forecast: v2Payload,
      order_forecast_v3: { version: 3, issuer: "S1", formula: "TAMPERED_WRONG_FORMULA" },
    };
    const parsedTampered = parseBottleneckV3(rawDocTamperedV3, REPORT_MS + HOUR);
    expect(parsedTampered).not.toBeNull();
    // Must NOT downgrade: forecast is invalid refuse object, reason is INVALID, not v2's NOT_DISCLOSED
    expect(parsedTampered!.top[1]!.forecast?.m12.reason).toBe("INVALID");
  });

  it("rejects a present but malformed v3 slot without downgrading to v2 (item 3 matrix)", () => {
    // The sibling v2 is valid and available; a present v3 of any other shape must read as v3 INVALID.
    const v2Payload = {
      version: 2, issuer: "S1", status: "UNAVAILABLE", reason: "NO_ORDERS",
      m6: { status: "UNAVAILABLE", reason: "NO_ORDERS", scenario: { status: "NO_BASIS", reason: "NO_ORDER_BASIS" } },
      m12: { status: "UNAVAILABLE", reason: "NO_ORDERS", scenario: { status: "NO_BASIS", reason: "NO_ORDER_BASIS" } },
      references: [], stock_sensitivity: null,
      evidence: { registry_status: "EMPTY", registry_sha256: "0".repeat(64), cutoff: GENERATED, url_prefixes: [],
        documents: [], claims: [],
        selection: { status: "OK", active: [], current_stock: null, schedule: null, filing: null, excluded: [] },
        periodic: null, stock_orders: null },
    };
    const badV3Slots: unknown[] = [null, false, 0, "", [], { version: 9, issuer: "S1" },
      { version: 1, issuer: "S1", m6: { status: "UNAVAILABLE", reason: "LEGACY", scenario: {} }, m12: { status: "UNAVAILABLE", reason: "LEGACY", scenario: {} }, references: [] },
      { ...v2Payload }];
    for (const slot of badV3Slots) {
      const rawDoc = doc(REPORT_MS);
      (rawDoc.top as any)[1].outlook = { orders: null, consensus: null, scenarios: [],
        order_forecast: v2Payload, order_forecast_v3: slot };
      const parsed = parseBottleneckV3(rawDoc, REPORT_MS + HOUR);
      expect(parsed, JSON.stringify(slot)).not.toBeNull();
      expect(parsed!.top[1]!.forecast?.version, JSON.stringify(slot)).toBe(3);
      expect(parsed!.top[1]!.forecast?.m12.reason, JSON.stringify(slot)).toBe("INVALID");
      expect(parsed!.top[1]!.forecast?.m12.status).toBe("UNAVAILABLE");
    }
  });

  it("never asserts contracted recognition without the sealed order evidence (item 2)", () => {
    const forged = parseOrderForecast(
      makeSyntheticV3({
        contracted_recognition: {
          m6: { amount: 1.2e9, currency: "USD", start: "2026-07-01", end: "2027-01-01" },
          m12: { amount: 1.2e9, currency: "USD", start: "2026-07-01", end: "2027-06-30" },
        },
      }),
      REPORT_DAY, "NVDA", GENERATED
    );
    expect(forged.m6.status).toBe("UNAVAILABLE");
    expect(forged.m6.reason).toBe("INVALID");
  });

  it("rejects a fabricated unavailable revenue reason (item 14)", () => {
    const fabricated = parseOrderForecast(
      makeSyntheticV3({ status: "UNAVAILABLE", revenue_status: "UNAVAILABLE", revenue_reason: "MADE_UP_REASON",
        m6: { status: "UNAVAILABLE", reason: "MADE_UP_REASON", scenario: { status: "NO_BASIS" } },
        m12: { status: "UNAVAILABLE", reason: "MADE_UP_REASON", scenario: { status: "NO_BASIS" } } }),
      REPORT_DAY, "NVDA", GENERATED
    );
    expect(fabricated.m6.reason).toBe("INVALID");
  });

  it("rejects mixed currencies between guidance claims and reported actuals (item 5)", () => {
    const mismatched = parseOrderForecast(
      makeSyntheticV3({
        revenue_basis: "COMPANY_GUIDANCE",
        evidence: {
          revenue_registry_status: "OK", revenue_registry_sha256: "0".repeat(64), cutoff: GENERATED,
          latest_release_check: { checked_at: "2026-09-28T10:00:00Z" },
          url_prefixes: ["https://investor.nvidia.com/"],
          documents: [{ id: "D1", issuer: "NVDA", publisher: "NVIDIA", title: "Q3 press release",
            source_kind: "ISSUER_EARNINGS_RELEASE", url: "https://investor.nvidia.com/q3.pdf",
            published_date: "2026-08-20", retrieved_at: "2026-08-20T12:00:00Z", sha256: "0".repeat(64), byte_size: 1000 }],
          claims: [{ id: "C1", document_id: "D1", locator: "p.1", passage: "Revenue is expected to be 120 million",
            metric: "REVENUE", assertion_kind: "COMPANY_GUIDANCE", currency: "KRW", unit_multiplier: 1,
            stated_point: 120, scope: "COMPANY", period_kind: "QUARTER", period_start: "2026-07-01", period_end: "2026-09-30" }],
        },
      }),
      REPORT_DAY, "NVDA", GENERATED
    );
    // The sealed USD actuals (80/90/100/110) contradict the KRW guidance currency: the record is invalid, not mixed.
    expect(mismatched.m6.reason).toBe("INVALID");
  });

  it("shows contracted recognition beside a revenue projection as 另列, never 其中 (item 15)", () => {
    // A parsed v3 with revenue AVAILABLE plus a bound contracted recognition renders the recognition as a
    // separate line (另列, 不相加); a coincident window never turns it into 其中 (a subset of the projection).
    const recView = {
      version: 3, issuer: "NVDA",
      m6: { status: "AVAILABLE", basis: "COMPANY_GUIDANCE", amount: 240.0, currency: "USD", start: "2026-07-01", end: "2026-12-31",
            ttm_revenue: 450.0, scenario: { status: "AVAILABLE", change: 70.0 / 380.0 }, warning: null },
      m12: { status: "AVAILABLE", basis: "COMPANY_GUIDANCE", amount: 480.0, currency: "USD", start: "2026-07-01", end: "2027-06-30",
            ttm_revenue: 480.0, scenario: { status: "AVAILABLE", change: 100.0 / 380.0 }, warning: null },
      revenueBasis: "COMPANY_GUIDANCE",
      contractedRecognition: { m6: { amount: 1.2e9, currency: "USD", start: "2026-07-01", end: "2026-12-31" } },
    } as unknown as OrderForecast;
    const card = forecastCard(recView, (v, c) => `${c ?? "USD"} ${v}`);
    const recLine = card.find((line) => String(line[0]).includes("已簽約預計認列"));
    expect(recLine).toBeDefined();
    expect(String(recLine![0]!)).toContain("另列已簽約預計認列");
    expect(String(recLine![0]!)).toContain("不相加");
    for (const line of card) expect(String(line[0])).not.toContain("其中已簽約");
  });

  it("parses the identical v2 subtree byte-for-byte in v2-only and dual-field documents (item 20)", () => {
    // A real, parseable v2 forecast from the shared fixture, rebound to the entry's symbol and build instant.
    const v2For = (symbol: string) => {
      const rebound = JSON.parse(JSON.stringify((v2Fixture as any).cases.S17.forecast).replaceAll("S17", symbol));
      rebound.evidence = { ...rebound.evidence, cutoff: GENERATED };
      return rebound;
    };
    const onlyV2 = doc(REPORT_MS);
    (onlyV2.top as any)[1].outlook = { orders: null, consensus: null, scenarios: [], order_forecast: v2For("S1") };
    const parsedOnly = parseBottleneckV3(onlyV2, REPORT_MS + HOUR)!;
    expect(parsedOnly.top[1]!.forecast?.version).toBe(2);
    expect(parsedOnly.top[1]!.forecast?.m6.status).toBe("AVAILABLE");

    const dual = doc(REPORT_MS);
    const dualSibling = v2For("S1");
    const dualV3 = makeSyntheticV3({ issuer: "S1" });
    // A v3 beside a sibling v2 carries the sibling's sealed order evidence; the S17 sibling is a recognition record, so
    // the v3 also carries the bound contracted recognition recomputed from the validated sibling.
    dualV3.evidence.order_evidence = { ...(dualSibling as any).evidence };
    const validatedSibling = parseOrderForecast(dualSibling, REPORT_DAY, "S1", GENERATED);
    const recTile = (h: any) => ({ amount: h.amount, currency: h.currency, start: h.start, end: h.end,
      ...(h.share_pct !== undefined ? { share_pct: h.share_pct } : {}),
      ...(h.rpo !== undefined ? { rpo: h.rpo } : {}),
      ...(h.as_of !== undefined ? { as_of: h.as_of } : {}) });
    dualV3.contracted_recognition = { m6: recTile(validatedSibling.m6), m12: recTile(validatedSibling.m12) };
    // The sealer binds the recognition into the tiles as well as the top level (item 7: duplicated fields equal).
    dualV3.m6.contracted_recognition = dualV3.contracted_recognition.m6;
    dualV3.m12.contracted_recognition = dualV3.contracted_recognition.m12;
    // The sealed order view is the sibling's own v2 tiles (item 7: order view mandatory beside a v2 sibling).
    dualV3.order_view = {
      status: "AVAILABLE",
      reason: null,
      m6: (dualSibling as any).m6,
      m12: (dualSibling as any).m12,
    };
    (dual.top as any)[1].outlook = { orders: null, consensus: null, scenarios: [], order_forecast: dualSibling,
      order_forecast_v3: dualV3 };
    const parsedDual = parseBottleneckV3(dual, REPORT_MS + HOUR)!;
    expect(parsedDual.top[1]!.forecast?.version).toBe(3);
    expect(parsedDual.top[1]!.forecast?.m6.amount).toBe(240.0);
    // The sealed v2 subtree is byte-identical in both documents: the v3 field never rewrites the v2 content.
    expect(JSON.stringify((onlyV2.top as any)[1].outlook.order_forecast)).toBe(JSON.stringify((dual.top as any)[1].outlook.order_forecast));

    // And a v2-only entry elsewhere in the dual document still reads as v2 with its own outcome.
    (dual.top as any)[2].outlook = { orders: null, consensus: null, scenarios: [], order_forecast: v2For("S2") };
    const parsedDual2 = parseBottleneckV3(dual, REPORT_MS + HOUR)!;
    expect(parsedDual2.top[2]!.forecast?.version).toBe(2);
    expect(parsedDual2.top[2]!.forecast?.m6.status).toBe("AVAILABLE");
  });

  it("verifies rendering and LINE payload limits on all 20 entries with real handlers", () => {
    const raw = doc(REPORT_MS);
    for (let i = 0; i < 20; i++) {
      const sym = i === 0 ? "SIVE.ST" : `S${i}`;
      (raw.top as any)[i].outlook = {
        orders: null,
        consensus: null,
        scenarios: [],
        order_forecast_v3: makeSyntheticV3({ issuer: sym }),
      };
    }
    const parsed = parseBottleneckV3(raw, REPORT_MS + HOUR)!;
    expect(parsed).not.toBeNull();
    expect(parsed.top.length).toBe(20);

    // Verify all 20 have version 3 forecast
    for (const entry of parsed.top) {
      expect(entry.forecast?.version).toBe(3);
      const cardLines = outlookForecast(parsed, entry);
      expect(cardLines[0]![0]).toBe("訂單認列／營收推估");
      // The model assumption and the bounded revenue-source detail lines (Astra r5 item 19) precede the scenario
      // header; their count is content-dependent, so locate them by content.
      const texts = cardLines.map(l => String(l[0]));
      const assumptionIdx = texts.findIndex(t => t.startsWith("模型假設："));
      expect(assumptionIdx).toBeGreaterThan(2);
      const scenarioIdx = texts.findIndex(t => t === "營收實現後股價情境");
      expect(scenarioIdx).toBeGreaterThan(assumptionIdx);
      expect(texts.slice(assumptionIdx + 1, scenarioIdx).every(t => t.startsWith("分析師共識：") || t.startsWith("營收財測來源："))).toBe(true);
    }

    // Verify LINE outbound messages pass assertLineMessages
    const flexMessages = buildBottleneckTop20Messages(parsed, "flex");
    expect(() => assertLineMessages(flexMessages)).not.toThrow();

    const textMessages = buildBottleneckTop20Messages(parsed, "text");
    expect(() => assertLineMessages(textMessages)).not.toThrow();

    // Verify all 20 detail cards obey LINE limits
    for (const entry of parsed.top) {
      const flexDetail = buildBottleneckDetail(parsed, entry.symbol, "flex");
      if (Array.isArray(flexDetail)) {
        expect(() => assertLineMessages(flexDetail)).not.toThrow();
      }

      const textDetail = buildBottleneckDetail(parsed, entry.symbol, "text");
      if (Array.isArray(textDetail)) {
        expect(() => assertLineMessages(textDetail)).not.toThrow();
      } else {
        expect(typeof textDetail).toBe("string");
      }
    }
  });

  it("parses all 16 sealed writer records with the r6 IR-coverage semantics (item 21)", () => {
    const sealedData = JSON.parse(readFileSync("../tests/fixtures/v213-orders-v3-golden-sealed.json", "utf-8"));
    const symbols = Object.keys(sealedData);
    expect(symbols.length).toBe(16);

    for (const sym of symbols) {
      const entryOutlook = sealedData[sym];
      const parsed = parseOrderForecastV3(entryOutlook.order_forecast_v3, REPORT_DAY, sym, GOLDEN_GENERATED, entryOutlook.order_forecast);
      expect(parsed.version, sym).toBe(3);

      if (sym === "000660.KS" || sym === "005930.KS") {
        // A3/A6 (acceptance r7): the registry gate is off in the first rollout, so the Korean consensus route is
        // deferred: the genuine nondisclosure stands with the distinct CONSENSUS_DEFERRED diagnostic, and the
        // sealed capture (if any) is never routed.
        expect(parsed.revenueStatus, sym).toBe("UNAVAILABLE");
        expect(parsed.revenueReason, sym).toBe("NOT_DISCLOSED");
        expect(parsed.revenueDiagnostic, sym).toBe("CONSENSUS_DEFERRED");
        expect(parsed.revenueBasis, sym).toBeNull();
        expect(parsed.m6.status, sym).toBe("UNAVAILABLE");
        expect(parsed.m6.reason, sym).toBe("NOT_DISCLOSED");
      } else if (IR_ISSUERS.has(sym)) {
        // The nine issuers with a reviewed official IR channel keep the company-guidance path AVAILABLE
        // (SEC_WIRE_IR coverage with the IR channel on the reviewed host).
        expect(parsed.m6.status, sym).toBe("AVAILABLE");
        expect(parsed.m12.status, sym).toBe("AVAILABLE");
        expect(parsed.m6.amount, sym).toBeGreaterThan(0);
        expect(parsed.m12.amount, sym).toBeGreaterThan(0);
        expect(parsed.revenueBasis, sym).toBe("COMPANY_GUIDANCE");
        expect(parsed.m6.currency, sym).toBe("USD");
        expect(parsed.revenueDiagnostic ?? null, sym).toBeNull();

        if (sym === "MU" || sym === "LITE" || sym === "AMD") {
          expect(parsed.warning, sym).not.toBeNull();
          expect(parsed.warning?.text, sym).toContain("結束，實際營收尚未公布");
        } else {
          expect(parsed.warning, sym).toBeNull();
        }
      } else {
        // The five blocked issuers (no reviewed official IR channel): the company-guidance path suspends with the
        // distinct IR_COVERAGE_MISSING diagnostic (never NOT_DISCLOSED, zero or consensus); the order tiles carry
        // the independent order-recognition state (no order evidence here -> NOT_DISCLOSED_HORIZON).
        expect(parsed.revenueStatus, sym).toBe("UNAVAILABLE");
        expect(parsed.revenueReason, sym).toBe("FRESHNESS_UNVERIFIED");
        expect(parsed.revenueDiagnostic, sym).toBe("IR_COVERAGE_MISSING");
        expect(parsed.revenueBasis, sym).toBeNull();
        expect(parsed.m6.status, sym).toBe("UNAVAILABLE");
        expect(parsed.m12.status, sym).toBe("UNAVAILABLE");
      }

      if (sym === "BE") {
        expect(parsed.forwardQuarters?.[0].amount).toBeCloseTo(parsed.forwardQuarters?.[1].amount, 5);
      }
      if (sym === "CRWV") {
        expect(parsed.forwardQuarters?.[0].amount).toBeCloseTo(3.525e9, 0);
        expect(parsed.forwardQuarters?.[1].amount).toBeCloseTo(4.622e9, 0);
      }
    }
  });

  it("reproduces and rejects all counterexample mutations (items 1-20)", () => {
    const sealedData = JSON.parse(readFileSync("../tests/fixtures/v213-orders-v3-golden-sealed.json", "utf-8"));
    const nvdaOutlook = sealedData["NVDA"];

    // 1. Coordinated forward amounts / totals tamper without evidence change
    const tamperedAmts = JSON.parse(JSON.stringify(nvdaOutlook.order_forecast_v3));
    tamperedAmts.m6.amount = 300.0;
    tamperedAmts.forward_quarters[0].amount = 150.0;
    const r1 = parseOrderForecastV3(tamperedAmts, REPORT_DAY, "NVDA", GOLDEN_GENERATED, nvdaOutlook.order_forecast);
    expect(r1.m6.status).toBe("UNAVAILABLE");
    expect(r1.m6.reason).toBe("INVALID");

    // 2. Removal of documents & claims
    const noDocs = JSON.parse(JSON.stringify(nvdaOutlook.order_forecast_v3));
    noDocs.evidence.documents = [];
    noDocs.evidence.claims = [];
    const r2 = parseOrderForecastV3(noDocs, REPORT_DAY, "NVDA", GOLDEN_GENERATED, nvdaOutlook.order_forecast);
    expect(r2.m6.status).toBe("UNAVAILABLE");
    expect(r2.m6.reason).toBe("INVALID");

    // 3. Forged recognition tiles without order evidence
    const forgedRec = JSON.parse(JSON.stringify(nvdaOutlook.order_forecast_v3));
    forgedRec.revenue_status = "UNAVAILABLE";
    forgedRec.status = "AVAILABLE";
    forgedRec.m6 = { status: "AVAILABLE", basis: "RECOGNITION", amount: 999, scenario: { status: "NO_BASIS", reason: "NO_REVENUE_BASIS" } };
    forgedRec.evidence.order_evidence = null;
    const r3 = parseOrderForecastV3(forgedRec, REPORT_DAY, "NVDA", GOLDEN_GENERATED);
    expect(r3.m6.status).toBe("UNAVAILABLE");
    expect(r3.m6.reason).toBe("INVALID");

    // 4. Anchor date mutation
    const tamperedAnchor = JSON.parse(JSON.stringify(nvdaOutlook.order_forecast_v3));
    tamperedAnchor.anchor_date = "2026-05-31";
    const r4 = parseOrderForecastV3(tamperedAnchor, REPORT_DAY, "NVDA", GOLDEN_GENERATED, nvdaOutlook.order_forecast);
    expect(r4.m6.status).toBe("UNAVAILABLE");
    expect(r4.m6.reason).toBe("INVALID");

    // 5. Change only m12 currency to KRW
    const currencyMix = JSON.parse(JSON.stringify(nvdaOutlook.order_forecast_v3));
    currencyMix.m12.currency = "KRW";
    const r5 = parseOrderForecastV3(currencyMix, REPORT_DAY, "NVDA", GOLDEN_GENERATED, nvdaOutlook.order_forecast);
    expect(r5.m6.status).toBe("UNAVAILABLE");
    expect(r5.m6.reason).toBe("INVALID");

    // 6. Set company guidance tile basis to RECOGNITION
    const basisMix = JSON.parse(JSON.stringify(nvdaOutlook.order_forecast_v3));
    basisMix.m6.basis = "RECOGNITION";
    const r6 = parseOrderForecastV3(basisMix, REPORT_DAY, "NVDA", GOLDEN_GENERATED, nvdaOutlook.order_forecast);
    expect(r6.m6.status).toBe("UNAVAILABLE");
    expect(r6.m6.reason).toBe("INVALID");

    // 7. Rehashed receipt with fake channel
    const fakeChannel = JSON.parse(JSON.stringify(nvdaOutlook.order_forecast_v3));
    fakeChannel.evidence.latest_release_check.channels = [{ kind: "FAKE", url: "https://bad.url", status: "OK", complete: true, checked_through: "2099-01-01" }];
    fakeChannel.evidence.latest_release_check.digest = computeReceiptDigest(fakeChannel.evidence.latest_release_check);
    const r7 = parseOrderForecastV3(fakeChannel, REPORT_DAY, "NVDA", GOLDEN_GENERATED, nvdaOutlook.order_forecast);
    expect(r7.m6.status).toBe("UNAVAILABLE");
    expect(r7.m6.reason).toBe("INVALID");

    // 8. A3/A6 (acceptance r7): a sealed CONSENSUS basis while the sealed gate is off is refused - the first
    // rollout defers the consensus route, so a forged basis beside consensus_enabled: false is invalid.
    const gateOff = JSON.parse(JSON.stringify(sealedData["000660.KS"].order_forecast_v3));
    gateOff.revenue_basis = "CONSENSUS";
    gateOff.evidence.consensus = {
      symbol: "000660.KS", captured_at: "2026-09-28T08:00:00Z", currency: "KRW",
      quarters: [{ period: "0q", end: "2026-09-30", revenue: 15e12, analysts: 25 }],
    };
    const r8 = parseOrderForecastV3(gateOff, REPORT_DAY, "000660.KS", GOLDEN_GENERATED);
    expect(r8.m6.status).toBe("UNAVAILABLE");
    expect(r8.m6.reason).toBe("INVALID");

    // 9. Consensus shape still fails closed with the gate on: an explicit string second quarter is malformed.
    const strQ2 = JSON.parse(JSON.stringify(sealedData["000660.KS"].order_forecast_v3));
    strQ2.evidence.consensus_enabled = true;
    strQ2.evidence.consensus = {
      symbol: "000660.KS", captured_at: "2026-09-28T08:00:00Z", currency: "KRW",
      quarters: [{ period: "0q", end: "2026-09-30", revenue: 15e12, analysts: 25 }, "malformed string second quarter"],
    };
    const r9 = parseOrderForecastV3(strQ2, REPORT_DAY, "000660.KS", GOLDEN_GENERATED);
    expect(r9.m6.status).toBe("UNAVAILABLE");
    expect(r9.m6.reason).toBe("INVALID");
  });

  it("enforces counterexample regression tests (compact executed counterexample receipt table)", () => {
    const sealedData = JSON.parse(readFileSync("../tests/fixtures/v213-orders-v3-golden-sealed.json", "utf-8"));
    const nvdaOutlook = sealedData["NVDA"];
    const krwOutlook = sealedData["000660.KS"];
    const beOutlook = sealedData["BE"];
    const muOutlook = sealedData["MU"];

    // Row 1: Worker: missing actual-source document / nonexistent actual document ID -> Fail closed
    {
      const mut = JSON.parse(JSON.stringify(nvdaOutlook.order_forecast_v3));
      mut.evidence.reported_quarters[0].document_id = "DOES-NOT-EXIST";
      const res = parseOrderForecastV3(mut, REPORT_DAY, "NVDA", GOLDEN_GENERATED, nvdaOutlook.order_forecast);
      expect(res.m6.status).toBe("UNAVAILABLE");
      expect(res.m6.reason).toBe("INVALID");
    }

    // Row 2: Worker: future actual source retrieval / future claim review -> Fail closed
    {
      const mut = JSON.parse(JSON.stringify(nvdaOutlook.order_forecast_v3));
      mut.evidence.documents[0].retrieved_at = "2099-01-01T00:00:00Z";
      const res = parseOrderForecastV3(mut, REPORT_DAY, "NVDA", GOLDEN_GENERATED, nvdaOutlook.order_forecast);
      expect(res.m6.status).toBe("UNAVAILABLE");
      expect(res.m6.reason).toBe("INVALID");
    }

    // Row 3: Worker: GAAP guidance + NON_GAAP actual -> Fail closed
    {
      const mut = JSON.parse(JSON.stringify(nvdaOutlook.order_forecast_v3));
      mut.evidence.reported_quarters[0].accounting_basis = "NON_GAAP";
      const res = parseOrderForecastV3(mut, REPORT_DAY, "NVDA", GOLDEN_GENERATED, nvdaOutlook.order_forecast);
      expect(res.m6.status).toBe("UNAVAILABLE");
      expect(res.m6.reason).toBe("INVALID");
    }

    // Row 4: Worker: missing claim quote and locator -> Fail closed
    {
      const mut = JSON.parse(JSON.stringify(nvdaOutlook.order_forecast_v3));
      delete mut.evidence.claims[0].passage;
      delete mut.evidence.claims[0].locator;
      const res = parseOrderForecastV3(mut, REPORT_DAY, "NVDA", GOLDEN_GENERATED, nvdaOutlook.order_forecast);
      expect(res.m6.status).toBe("UNAVAILABLE");
      expect(res.m6.reason).toBe("INVALID");
    }

    // Row 5: Python + Worker: unknown revision enum and orphan target -> Fail closed
    {
      const mut = JSON.parse(JSON.stringify(nvdaOutlook.order_forecast_v3));
      mut.evidence.claims[0].revision = { kind: "BOGUS", targets: ["ABSENT"] };
      const res = parseOrderForecastV3(mut, REPORT_DAY, "NVDA", GOLDEN_GENERATED, nvdaOutlook.order_forecast);
      expect(res.m6.status).toBe("UNAVAILABLE");
      expect(res.m6.reason).toBe("INVALID");
    }

    // Row 6: Worker: registry INVALID + malformed hash; wrong evidence formula -> Fail closed
    {
      const mut = JSON.parse(JSON.stringify(nvdaOutlook.order_forecast_v3));
      mut.evidence.revenue_registry_status = "INVALID";
      mut.evidence.revenue_registry_sha256 = "garbage";
      const res1 = parseOrderForecastV3(mut, REPORT_DAY, "NVDA", GOLDEN_GENERATED, nvdaOutlook.order_forecast);
      expect(res1.m6.status).toBe("UNAVAILABLE");
      expect(res1.m6.reason).toBe("INVALID");

      const mut2 = JSON.parse(JSON.stringify(nvdaOutlook.order_forecast_v3));
      mut2.evidence.formula = "WRONG";
      const res2 = parseOrderForecastV3(mut2, REPORT_DAY, "NVDA", GOLDEN_GENERATED, nvdaOutlook.order_forecast);
      expect(res2.m6.status).toBe("UNAVAILABLE");
      expect(res2.m6.reason).toBe("INVALID");
    }

    // Row 7: Worker: m6 UNAVAILABLE; scenario NO_BASIS; inconsistent top actual copy -> Fail closed
    {
      const mut = JSON.parse(JSON.stringify(nvdaOutlook.order_forecast_v3));
      mut.m6.status = "UNAVAILABLE";
      const res1 = parseOrderForecastV3(mut, REPORT_DAY, "NVDA", GOLDEN_GENERATED, nvdaOutlook.order_forecast);
      expect(res1.m6.status).toBe("UNAVAILABLE");
      expect(res1.m6.reason).toBe("INVALID");

      const mut2 = JSON.parse(JSON.stringify(nvdaOutlook.order_forecast_v3));
      mut2.m6.scenario = { status: "NO_BASIS", reason: "TAMPERED" };
      const res2 = parseOrderForecastV3(mut2, REPORT_DAY, "NVDA", GOLDEN_GENERATED, nvdaOutlook.order_forecast);
      expect(res2.m6.status).toBe("UNAVAILABLE");
      expect(res2.m6.reason).toBe("INVALID");

      const mut3 = JSON.parse(JSON.stringify(nvdaOutlook.order_forecast_v3));
      mut3.reported_quarters[0].revenue = 999999;
      const res3 = parseOrderForecastV3(mut3, REPORT_DAY, "NVDA", GOLDEN_GENERATED, nvdaOutlook.order_forecast);
      expect(res3.m6.status).toBe("UNAVAILABLE");
      expect(res3.m6.reason).toBe("INVALID");
    }

    // Row 8: Worker: remove order evidence despite sibling / overwrite duplicate order_view -> Fail closed
    {
      const mut = JSON.parse(JSON.stringify(nvdaOutlook.order_forecast_v3));
      delete mut.evidence.order_evidence;
      const res1 = parseOrderForecastV3(mut, REPORT_DAY, "NVDA", GOLDEN_GENERATED, nvdaOutlook.order_forecast);
      expect(res1.m6.status).toBe("UNAVAILABLE");
      expect(res1.m6.reason).toBe("INVALID");

      const mut2 = JSON.parse(JSON.stringify(nvdaOutlook.order_forecast_v3));
      mut2.order_view = { status: "AVAILABLE", m6: { amount: 999 } };
      const res2 = parseOrderForecastV3(mut2, REPORT_DAY, "NVDA", GOLDEN_GENERATED, nvdaOutlook.order_forecast);
      expect(res2.m6.status).toBe("UNAVAILABLE");
      expect(res2.m6.reason).toBe("INVALID");
    }

    // Row 9: Real-proof Worker: recognition m12 is string; forged share/RPO/as-of/extra key -> Fail closed
    {
      const siblingV2WithRec = JSON.parse(JSON.stringify(nvdaOutlook.order_forecast));
      siblingV2WithRec.m12 = { status: "AVAILABLE", basis: "RECOGNITION", amount: 100, currency: "USD", start: "2026-07-01", end: "2027-06-30" };
      siblingV2WithRec.status = "AVAILABLE";

      const mut1 = JSON.parse(JSON.stringify(nvdaOutlook.order_forecast_v3));
      mut1.contracted_recognition = { m12: "forged" };
      const res1 = parseOrderForecastV3(mut1, REPORT_DAY, "NVDA", GOLDEN_GENERATED, siblingV2WithRec);
      expect(res1.m6.status).toBe("UNAVAILABLE");
      expect(res1.m6.reason).toBe("INVALID");

      const mut2 = JSON.parse(JSON.stringify(nvdaOutlook.order_forecast_v3));
      mut2.contracted_recognition = { m12: { amount: 100, currency: "USD", start: "2026-07-01", end: "2027-06-30", share_pct: 999 } };
      const res2 = parseOrderForecastV3(mut2, REPORT_DAY, "NVDA", GOLDEN_GENERATED, siblingV2WithRec);
      expect(res2.m6.status).toBe("UNAVAILABLE");
      expect(res2.m6.reason).toBe("INVALID");
    }

    // Row 10: Real-proof Worker: delete valid recognition; force allowed unavailable state -> Fail closed
    {
      const siblingV2WithRec = JSON.parse(JSON.stringify(nvdaOutlook.order_forecast));
      siblingV2WithRec.m12 = { status: "AVAILABLE", basis: "RECOGNITION", amount: 100, currency: "USD", start: "2026-07-01", end: "2027-06-30" };
      siblingV2WithRec.status = "AVAILABLE";

      const mut = JSON.parse(JSON.stringify(nvdaOutlook.order_forecast_v3));
      delete mut.contracted_recognition;
      const res1 = parseOrderForecastV3(mut, REPORT_DAY, "NVDA", GOLDEN_GENERATED, siblingV2WithRec);
      expect(res1.m6.status).toBe("UNAVAILABLE");
      expect(res1.m6.reason).toBe("INVALID");
    }

    // Row 11: Worker: boolean low, one-sided representation, negative ±percent -> Fail closed
    {
      const mut1 = JSON.parse(JSON.stringify(nvdaOutlook.order_forecast_v3));
      mut1.evidence.claims[0].low = true;
      const res1 = parseOrderForecastV3(mut1, REPORT_DAY, "NVDA", GOLDEN_GENERATED, nvdaOutlook.order_forecast);
      expect(res1.m6.status).toBe("UNAVAILABLE");
      expect(res1.m6.reason).toBe("INVALID");

      const mut2 = JSON.parse(JSON.stringify(nvdaOutlook.order_forecast_v3));
      mut2.evidence.claims[0].original_representation = "GREATER_THAN";
      const res2 = parseOrderForecastV3(mut2, REPORT_DAY, "NVDA", GOLDEN_GENERATED, nvdaOutlook.order_forecast);
      expect(res2.m6.status).toBe("UNAVAILABLE");
      expect(res2.m6.reason).toBe("INVALID");

      const mut3 = JSON.parse(JSON.stringify(nvdaOutlook.order_forecast_v3));
      mut3.evidence.claims[0].plus_minus_percent = -2.0;
      const res3 = parseOrderForecastV3(mut3, REPORT_DAY, "NVDA", GOLDEN_GENERATED, nvdaOutlook.order_forecast);
      expect(res3.m6.status).toBe("UNAVAILABLE");
      expect(res3.m6.reason).toBe("INVALID");
    }

    // Row 12: Python + Worker: fresh receipt but checked-through only guidance day -> Fail closed
    {
      const mut = JSON.parse(JSON.stringify(nvdaOutlook.order_forecast_v3));
      const r = mut.evidence.latest_release_check;
      r.channels[0].checked_through = r.guidance_published_date;
      r.channels[1].checked_through = r.guidance_published_date;
      r.digest = computeReceiptDigest(r);
      const res = parseOrderForecastV3(mut, REPORT_DAY, "NVDA", GOLDEN_GENERATED, nvdaOutlook.order_forecast);
      expect(res.m6.status).toBe("UNAVAILABLE");
      expect(res.m6.reason).toBe("INVALID");
    }

    // Row 13: Python + Worker: REVIEWED_IRRELEVANT later item with no linked review -> Fail closed
    {
      const mut = JSON.parse(JSON.stringify(nvdaOutlook.order_forecast_v3));
      const r = mut.evidence.latest_release_check;
      r.later_documents.push({
        channel: "SEC_SUBMISSIONS",
        date: "2026-09-01",
        id: "FORGED_UNLINKED_ID",
        label: "8-K items 8.01",
        disposition: "REVIEWED_IRRELEVANT",
      });
      r.digest = computeReceiptDigest(r);
      const res = parseOrderForecastV3(mut, REPORT_DAY, "NVDA", GOLDEN_GENERATED, nvdaOutlook.order_forecast);
      expect(res.m6.status).toBe("UNAVAILABLE");
      expect(res.m6.reason).toBe("INVALID");
    }

    // Row 14: Worker: same-day review after cutoff -> Fail closed
    {
      const mut = JSON.parse(JSON.stringify(nvdaOutlook.order_forecast_v3));
      const r = mut.evidence.latest_release_check;
      r.later_documents.push({
        channel: "SEC_SUBMISSIONS",
        date: "2026-09-28",
        id: "LATER_ITEM_SAME_DAY",
        label: "8-K items 8.01",
        disposition: "REVIEWED_IRRELEVANT",
      });
      r.digest = computeReceiptDigest(r);
      mut.evidence.reviewed_later_documents = [
        { id: "LATER_ITEM_SAME_DAY", disposition: "REVIEWED_IRRELEVANT", reviewed_at: "2026-09-28T23:59:59Z" },
      ];
      const res = parseOrderForecastV3(mut, REPORT_DAY, "NVDA", GOLDEN_GENERATED, nvdaOutlook.order_forecast);
      expect(res.m6.status).toBe("UNAVAILABLE");
      expect(res.m6.reason).toBe("INVALID");
    }

    // Row 15: Worker: fabricated NOT_DISCLOSED with malformed revenue evidence -> Fail closed
    {
      const mut = JSON.parse(JSON.stringify(nvdaOutlook.order_forecast_v3));
      mut.status = "UNAVAILABLE";
      mut.reason = "NOT_DISCLOSED";
      mut.revenue_status = "UNAVAILABLE";
      mut.revenue_reason = "NOT_DISCLOSED";
      mut.evidence.documents = "malformed string not array";
      const res = parseOrderForecastV3(mut, REPORT_DAY, "NVDA", GOLDEN_GENERATED, nvdaOutlook.order_forecast);
      expect(res.m6.status).toBe("UNAVAILABLE");
      expect(res.m6.reason).toBe("INVALID");
    }

    // Row 16: Worker: Korean documents removed; a sealed consensus capture with the wrong currency -> Fail closed.
    // (A3/A6 r7: the gate is off in the golden, so the consensus capture is injected with the gate on for the
    // currency-mix check.)
    {
      const mut1 = JSON.parse(JSON.stringify(krwOutlook.order_forecast_v3));
      mut1.evidence.documents = [];
      const res1 = parseOrderForecastV3(mut1, REPORT_DAY, "000660.KS", GOLDEN_GENERATED);
      expect(res1.m6.status).toBe("UNAVAILABLE");
      expect(res1.m6.reason).toBe("INVALID");

      const mut2 = JSON.parse(JSON.stringify(krwOutlook.order_forecast_v3));
      mut2.evidence.consensus_enabled = true;
      mut2.evidence.consensus = {
        symbol: "000660.KS", captured_at: "2026-09-28T08:00:00Z", currency: "KRW",
        quarters: [{ period: "0q", end: "2026-09-30", currency: "USD", revenue: 15e12, analysts: 25 }],
      };
      const res2 = parseOrderForecastV3(mut2, REPORT_DAY, "000660.KS", GOLDEN_GENERATED);
      expect(res2.m6.status).toBe("UNAVAILABLE");
      expect(res2.m6.reason).toBe("INVALID");
    }

    // Row 21: Worker: wrong FY/YTD starts -> Fail closed
    {
      const mut = JSON.parse(JSON.stringify(beOutlook.order_forecast_v3));
      mut.evidence.claims[0].period_start = "2020-01-01";
      const res = parseOrderForecastV3(mut, REPORT_DAY, "BE", GOLDEN_GENERATED, beOutlook.order_forecast);
      expect(res.m6.status).toBe("UNAVAILABLE");
      expect(res.m6.reason).toBe("INVALID");
    }

    // Row 22: Worker: MU m12 warning removed; arbitrary assumptions key -> Fail closed
    {
      const mut1 = JSON.parse(JSON.stringify(muOutlook.order_forecast_v3));
      delete mut1.m12.warning;
      const res1 = parseOrderForecastV3(mut1, REPORT_DAY, "MU", GOLDEN_GENERATED, muOutlook.order_forecast);
      expect(res1.m6.status).toBe("UNAVAILABLE");
      expect(res1.m6.reason).toBe("INVALID");

      const mut2 = JSON.parse(JSON.stringify(muOutlook.order_forecast_v3));
      mut2.assumptions = { arbitrary_key: "forged" };
      const res2 = parseOrderForecastV3(mut2, REPORT_DAY, "MU", GOLDEN_GENERATED, muOutlook.order_forecast);
      expect(res2.m6.status).toBe("UNAVAILABLE");
      expect(res2.m6.reason).toBe("INVALID");
    }

    // Row 27: The shared typed receipt domain (Astra r5 item 3): out-of-domain scalars (any number, e.g. 1e-7 whose
    // canonical spellings differ across languages, or integral 1e21 / 1e+21) are refused before hashing, in both
    // languages; a string-domain receipt hashes identically in the Worker and in Python.
    {
      expect(() => computeReceiptDigest({ x: 1.0 })).toThrow("RECEIPT_OUT_OF_DOMAIN_SCALAR");
      expect(() => computeReceiptDigest({ x: 1e21 })).toThrow("RECEIPT_OUT_OF_DOMAIN_SCALAR");
      expect(() => computeReceiptDigest({ x: { y: 2 } })).toThrow("RECEIPT_OUT_OF_DOMAIN_SCALAR");
      expect(computeReceiptDigest({ x: "1" })).toBe("013bdcb2b4d38b7d26f13f2a48631e9a5ae45530c3ef0e5946668d4f1892baa1");
    }
  });

  it("enforces the Astra r5 counterexamples (scoped limit, field allowlists, the unavailable state machine, duplicated fields)", () => {
    const base = makeSyntheticV3();
    const parseV3 = (v3: any) => parseOrderForecastV3(v3, REPORT_DAY, "NVDA", GENERATED);
    const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v));

    // Item 20: oversized evidence yields the small, consistent EVIDENCE_LIMIT object - never the whole-document INVALID,
    // and the oversized originals never travel sealed. (17 documents / 9 claims / 9 actuals)
    for (const oversized of [
      { ...clone(base), evidence: { ...base.evidence, documents: Array.from({ length: 17 }, (_, i) => ({ ...base.evidence.documents[0], id: `DOC-G${i}`, lineage_id: `L${i}` })) } },
      { ...clone(base), evidence: { ...base.evidence, claims: Array.from({ length: 9 }, (_, i) => ({ ...base.evidence.claims[0], id: `CLAIM-${i}` })) } },
      { ...clone(base), evidence: { ...base.evidence, reported_quarters: Array.from({ length: 9 }, (_, i) => ({ ...base.evidence.reported_quarters[0], id: `A${i}` })) } },
    ]) {
      const res = parseV3(oversized);
      expect(res.m6.status).toBe("UNAVAILABLE");
      expect(res.m6.reason).toBe("EVIDENCE_LIMIT");
      expect(res.revenueReason).toBe("EVIDENCE_LIMIT");
      // The scoped result carries no oversized originals.
      expect((res as any).reportedQuarters ?? []).toHaveLength(0);
    }

    // Item 20: unknown fields are refused by the allowlists, at the top level and inside the evidence - a forged
    // multi-megabyte field is never passed through into the outer Top20 object.
    {
      const forged = clone(base);
      forged.forged_multimegabyte = "x".repeat(1_000_000);
      const res = parseV3(forged);
      expect(res.m6.reason).toBe("INVALID");
      const forgedEv = clone(base);
      forgedEv.evidence.forged = { big: true };
      const resEv = parseV3(forgedEv);
      expect(resEv.m6.reason).toBe("INVALID");
    }

    // Item 10: a forward interval without its fiscal calendar link fails validation on the guidance branch too.
    {
      const mut = clone(base);
      for (const intv of mut.evidence.forward_intervals) { delete intv.calendar_document_id; delete intv.calendar_locator; }
      const res = parseV3(mut);
      expect(res.m6.reason).toBe("INVALID");
    }

    // Item 15: an explicit null consensus quarter is malformed evidence, never an absence. (The gate is on here
    // so the check under test is the quarter shape, not the A3/A6 gate-off rejection.)
    {
      const mut = clone(base);
      mut.revenue_basis = "CONSENSUS";
      mut.evidence.consensus_enabled = true;
      mut.evidence.consensus = {
        symbol: "NVDA", captured_at: "2026-09-28T10:00:00Z", currency: "USD",
        quarters: [{ period: "0q", end: "2026-09-30", revenue: 120.0, analysts: 10 }, null],
      };
      const res = parseV3(mut);
      expect(res.m6.reason).toBe("INVALID");
    }

    // Item 6: a WITHDRAWN revenue_reason beside available revenue is contradictory.
    {
      const mut = clone(base);
      mut.revenue_reason = "WITHDRAWN";
      const res = parseV3(mut);
      expect(res.m6.reason).toBe("INVALID");
    }

    // Item 8: a valid contracted recognition is never suppressed by the revenue state - an overall-UNAVAILABLE
    // record that carries a valid recognition must fail closed, and the sealed reason must be backed by the inputs.
    {
      const mut = clone(base);
      mut.status = "UNAVAILABLE";
      mut.reason = "NOT_DISCLOSED";
      mut.revenue_status = "UNAVAILABLE";
      mut.revenue_reason = "NOT_DISCLOSED";
      mut.m6 = { status: "UNAVAILABLE", reason: "NOT_DISCLOSED", scenario: { status: "NO_BASIS", reason: "NO_REVENUE_BASIS" } };
      mut.m12 = { status: "UNAVAILABLE", reason: "NOT_DISCLOSED", scenario: { status: "NO_BASIS", reason: "NO_REVENUE_BASIS" } };
      // No order_evidence and no recognition: the sealed NOT_DISCLOSED is backed (no active guidance claims in the
      // base synthetic? there is one) - replace the active claim with a withdrawn one so the state machine derives it.
      mut.evidence.claims = [{ ...base.evidence.claims[0], revision: { kind: "WITHDRAWN" } }];
      mut.revenue_reason = "WITHDRAWN";
      mut.reason = "WITHDRAWN";
      mut.m6 = { status: "UNAVAILABLE", reason: "WITHDRAWN", scenario: { status: "NO_BASIS", reason: "NO_REVENUE_BASIS" } };
      mut.m12 = { status: "UNAVAILABLE", reason: "WITHDRAWN", scenario: { status: "NO_BASIS", reason: "NO_REVENUE_BASIS" } };
      const res = parseV3(mut);
      expect(res.m6.status).toBe("UNAVAILABLE");
      expect(res.m6.reason).toBe("WITHDRAWN");
      // And the same sealed reason beside an active claim is unbacked -> INVALID.
      mut.evidence.claims = clone(base.evidence.claims);
      const resUnbacked = parseV3(mut);
      expect(resUnbacked.m6.reason).toBe("INVALID");
    }

    // Item 7: a partial contracted-recognition tile (amount only) is a contract break - beside a real recognition
    // sibling the sealed rec must carry all seven fields.
    {
      const sibling = JSON.parse(JSON.stringify((v2Fixture as any).cases.S17.forecast).replaceAll("S17", "NVDA"));
      sibling.evidence = { ...sibling.evidence, cutoff: GENERATED };
      const mut = clone(base);
      mut.evidence.order_evidence = { ...(sibling as any).evidence };
      mut.order_view = { status: "AVAILABLE", reason: null, m6: (sibling as any).m6, m12: (sibling as any).m12 };
      mut.contracted_recognition = { m6: { amount: 999 }, m12: { amount: 999 } };
      const res = parseV3(mut);
      expect(res.m6.reason).toBe("INVALID");
    }

    // Item 1: a numeric receipt field is out of the typed receipt domain -> INVALID, never a digest mismatch.
    {
      const mut = clone(base);
      mut.evidence.latest_release_check.numeric_probe = 1.5;
      const res = parseV3(mut);
      expect(res.m6.reason).toBe("INVALID");
    }
  });
});

describe("version-3 forecast on real sealed data with a 12-month-only RPO schedule (writer proof, ORDERS-V3-01)", () => {
  // Outlooks sealed by the real sealer from the production v3 document (tests/fixtures/v213-orders-v3-proof-rpo.json):
  // the filings state only a 12-month RPO share, so the v2 order view has m12 AVAILABLE and m6 NOT_DISCLOSED_HORIZON.
  const proof = JSON.parse(readFileSync("../tests/fixtures/v213-orders-v3-proof-rpo.json", "utf-8"));
  const day = proof.generated_at.slice(0, 10);
  const parse = (sym: string, v3: any) => parseOrderForecastV3(v3, day, sym, proof.generated_at, proof.entries[sym].order_forecast);
  const copy = (sym: string) => JSON.parse(JSON.stringify(proof.entries[sym].order_forecast_v3));

  it("accepts the revenue path beside a 12-month-only recognition and keeps the recognition separate", () => {
    // Re-sealed from the genuine rebuild with the reviewed profile (approval fields sealed) after the A1 rule.
    for (const sym of ["NVDA", "AMD"]) {
      const parsed = parse(sym, proof.entries[sym].order_forecast_v3);
      expect(parsed.m6.status, sym).toBe("AVAILABLE");
      expect(parsed.m12.status, sym).toBe("AVAILABLE");
      expect(parsed.revenueBasis, sym).toBe("COMPANY_GUIDANCE");
      expect(parsed.contractedRecognition?.m12?.amount, sym).toBeGreaterThan(0);
      expect(parsed.contractedRecognition?.m6 ?? null, sym).toBeNull();
    }
    expect(parse("NVDA", proof.entries.NVDA.order_forecast_v3).m6.amount).toBeCloseTo(216e9, 0);
    const v2nvda = parseOrderForecast(proof.entries.NVDA.order_forecast, day, "NVDA", proof.generated_at);
    expect(v2nvda.m12.basis).toBe("RECOGNITION");
    expect(v2nvda.m12.amount).toBeCloseTo(1.248e9, 0);
  });

  it("refuses the re-sealed revenue path once its approval binding is removed", () => {
    const unbound = copy("NVDA");
    unbound.evidence.approval_sha256 = null;
    expect(parse("NVDA", unbound).m6.reason).toBe("INVALID");
  });

  it("refuses an AVAILABLE revenue path once the reviewed official-IR channel is stripped from the sealed evidence", () => {
    const stripped = copy("NVDA");
    stripped.evidence.release_channels = { ...stripped.evidence.release_channels, ir: undefined, ir_guidance_release_title: undefined };
    delete stripped.evidence.release_channels.ir;
    delete stripped.evidence.release_channels.ir_guidance_release_title;
    expect(parse("NVDA", stripped).m6.reason).toBe("INVALID");
  });

  it("refuses an order view that invents a 6-month amount, changes the 12-month amount or the 6-month reason", () => {
    const invented = copy("NVDA");
    invented.order_view.m6 = { ...invented.order_view.m6, amount: 1e9 };
    expect(parse("NVDA", invented).m6.reason).toBe("INVALID");
    const changed = copy("NVDA");
    changed.order_view.m12.amount = changed.order_view.m12.amount * 2;
    expect(parse("NVDA", changed).m6.reason).toBe("INVALID");
    const reason = copy("AMD");
    reason.order_view.m6.reason = "NOT_DISCLOSED";
    expect(parse("AMD", reason).m6.reason).toBe("INVALID");
    const status = copy("AMD");
    status.order_view.m6 = { ...status.order_view.m12 };
    expect(parse("AMD", status).m6.reason).toBe("INVALID");
  });
});

describe("version-3 forecast under the official-IR third release-check channel (Astra W1 ruling, astra-ir-coverage)", () => {
  const parseV3 = (v3: any) => parseOrderForecastV3(v3, REPORT_DAY, "NVDA", GENERATED);
  const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v));

  /** The sealed unavailable shape beside the IR-coverage suspension (the sealer's own tiles for this state). */
  const toIrCoverageSuspended = (v3: any): any => {
    v3.status = "UNAVAILABLE";
    v3.reason = "FRESHNESS_UNVERIFIED";
    v3.revenue_status = "UNAVAILABLE";
    v3.revenue_reason = "FRESHNESS_UNVERIFIED";
    v3.revenue_diagnostic = "IR_COVERAGE_MISSING";
    v3.m6 = { status: "UNAVAILABLE", reason: "FRESHNESS_UNVERIFIED", scenario: { status: "NO_BASIS", reason: "NO_REVENUE_BASIS" } };
    v3.m12 = { status: "UNAVAILABLE", reason: "FRESHNESS_UNVERIFIED", scenario: { status: "NO_BASIS", reason: "NO_REVENUE_BASIS" } };
    v3.order_view = {
      status: "UNAVAILABLE",
      reason: "NOT_DISCLOSED_HORIZON",
      m6: { status: "UNAVAILABLE", reason: "NOT_DISCLOSED_HORIZON", scenario: { status: "NO_BASIS", reason: "NO_REVENUE_BASIS" } },
      m12: { status: "UNAVAILABLE", reason: "NOT_DISCLOSED_HORIZON", scenario: { status: "NO_BASIS", reason: "NO_REVENUE_BASIS" } },
    };
    return v3;
  };

  it("keeps the company-guidance path AVAILABLE with the complete SEC_WIRE_IR receipt", () => {
    const parsed = parseV3(makeSyntheticV3());
    expect(parsed.m6.status).toBe("AVAILABLE");
    expect(parsed.m12.status).toBe("AVAILABLE");
    expect(parsed.revenueDiagnostic ?? null).toBeNull();
    expect(parsed.latestReleaseCheck?.coverage).toBe("SEC_WIRE_IR");
    // The detail line lists the channels actually checked, derived from the receipt's coverage.
    expect(forecastLines(parsed, money)).toContainEqual(
      expect.stringContaining("查核管道：SEC_WIRE_IR（SEC 申報、通訊社新聞稿與官方IR）"));
  });

  it("suspends with IR_COVERAGE_MISSING when the record has no reviewed IR channel (through the real caller)", () => {
    const v3 = toIrCoverageSuspended(clone(makeSyntheticV3()));
    delete v3.evidence.release_channels.ir;
    delete v3.evidence.release_channels.ir_guidance_release_title;
    const r = v3.evidence.latest_release_check;
    r.coverage = "SEC_AND_WIRE";
    r.channels = r.channels.filter((c: any) => c.kind !== "ISSUER_IR");
    r.digest = computeReceiptDigest(r);
    const parsed = parseV3(v3);
    expect(parsed.m6.status).toBe("UNAVAILABLE");
    expect(parsed.m6.reason).toBe("FRESHNESS_UNVERIFIED");
    expect(parsed.revenueStatus).toBe("UNAVAILABLE");
    expect(parsed.revenueReason).toBe("FRESHNESS_UNVERIFIED");
    expect(parsed.revenueDiagnostic).toBe("IR_COVERAGE_MISSING");
    // Rendered on every surface as the fixed wording; never NOT_DISCLOSED, zero or consensus.
    expect(forecastText(parsed, money)).toContain("官方IR查核未完成，暫停營收推估");
    expect(forecastCard(parsed, money).map(l => l[0]).join("｜")).toContain("官方IR查核未完成，暫停營收推估");
    expect(forecastLines(parsed, money).join("\n")).toContain("官方IR查核未完成，暫停營收推估");
  });

  it("suspends with IR_COVERAGE_MISSING when the reviewed IR channel lacks the SEC_WIRE_IR coverage", () => {
    const v3 = toIrCoverageSuspended(clone(makeSyntheticV3()));
    const r = v3.evidence.latest_release_check;
    r.coverage = "SEC_AND_WIRE"; // the reviewed wiring was not upgraded; the IR channel stays bound
    r.digest = computeReceiptDigest(r);
    const parsed = parseV3(v3);
    expect(parsed.revenueStatus).toBe("UNAVAILABLE");
    expect(parsed.revenueReason).toBe("FRESHNESS_UNVERIFIED");
    expect(parsed.revenueDiagnostic).toBe("IR_COVERAGE_MISSING");
  });

  it("refuses a forged IR label on a record without a reviewed IR wiring (invalid, not a suspension)", () => {
    const v3 = clone(makeSyntheticV3());
    delete v3.evidence.release_channels.ir;
    delete v3.evidence.release_channels.ir_guidance_release_title;
    // The receipt keeps the SEC_WIRE_IR label and its IR channel: the host is unreviewed -> invalid evidence.
    const parsed = parseV3(v3);
    expect(parsed.m6.reason).toBe("INVALID");
  });

  it("refuses an IR channel bound to a host the registry did not review", () => {
    const v3 = clone(makeSyntheticV3());
    const r = v3.evidence.latest_release_check;
    const ir = r.channels.find((c: any) => c.kind === "ISSUER_IR");
    ir.url = "https://feeds.mirror.example/rss";
    r.digest = computeReceiptDigest(r);
    const parsed = parseV3(v3);
    expect(parsed.m6.reason).toBe("INVALID");
  });

  it("never falls back to consensus or NOT_DISCLOSED while the IR coverage is missing", () => {
    // A consensus capture beside a missing IR channel does not revive the revenue path (Astra W1: never consensus).
    const v3 = clone(makeSyntheticV3());
    v3.evidence.consensus = {
      symbol: "NVDA", captured_at: "2026-09-28T10:00:00Z", currency: "USD",
      quarters: [{ period: "0q", end: "2026-09-30", revenue: 120.0, analysts: 10 }],
    };
    v3.evidence.latest_release_check = null; // no receipt at all: the suspension, not a consensus rescue
    const parsed = parseV3(toIrCoverageSuspended(v3));
    expect(parsed.revenueStatus).toBe("UNAVAILABLE");
    expect(parsed.revenueReason).toBe("FRESHNESS_UNVERIFIED");
    expect(parsed.revenueDiagnostic).toBe("IR_COVERAGE_MISSING");
    expect(parsed.revenueBasis).toBeNull();
  });

  it("keeps independent order recognition beside a suspended revenue path", () => {
    // The recognition-only outcome (item 8) is independent of the revenue state: a suspended revenue path (IR
    // coverage missing) never suppresses a valid contracted recognition, and the order tiles keep the
    // recognition state. The full recognition wiring is exercised by the writer-proof tests above; here the
    // synthetic suspension keeps its own order state (no order evidence -> NOT_DISCLOSED_HORIZON, independent of
    // the revenue reason on the tiles).
    const v3 = toIrCoverageSuspended(clone(makeSyntheticV3()));
    delete v3.evidence.release_channels.ir;
    delete v3.evidence.release_channels.ir_guidance_release_title;
    const r = v3.evidence.latest_release_check;
    r.coverage = "SEC_AND_WIRE";
    r.channels = r.channels.filter((c: any) => c.kind !== "ISSUER_IR");
    r.digest = computeReceiptDigest(r);
    const parsed = parseV3(v3);
    expect(parsed.revenueDiagnostic).toBe("IR_COVERAGE_MISSING");
    expect(parsed.m6.reason).toBe("FRESHNESS_UNVERIFIED");
    expect(parsed.m12.reason).toBe("FRESHNESS_UNVERIFIED");
    // The order tiles keep the normalized order state (no order evidence -> NO_ORDER_BASIS), independent of the
    // revenue suspension wording on the tiles.
    expect(parsed.m6.scenario?.reason).toBe("NO_ORDER_BASIS");
  });
});

describe("version-3 acceptance r7: the enforced reviewed profile, the deferred consensus gate and the scoped limit (A1/A3/A4)", () => {
  const parseV3 = (v3: any) => parseOrderForecastV3(v3, REPORT_DAY, "NVDA", GENERATED);
  const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v));
  const money = (amount: number, currency: string | null) => `${currency ?? ""} ${amount}`;

  it("refuses a record whose inputs seal without the reviewed profile (UNREVIEWED_INPUTS)", () => {
    // A1 (acceptance r7): the record's inputs are sealed but the approval fields are absent - the Worker fails
    // the record closed with the distinct UNREVIEWED_INPUTS diagnostic (never AVAILABLE), and the independent
    // order recognition is never affected by the revenue suspension.
    const v3 = clone(makeSyntheticV3());
    v3.status = "UNAVAILABLE";
    v3.reason = "INVALID";
    v3.revenue_status = "UNAVAILABLE";
    v3.revenue_reason = "INVALID";
    v3.revenue_diagnostic = "UNREVIEWED_INPUTS";
    v3.m6 = { status: "UNAVAILABLE", reason: "INVALID", scenario: { status: "NO_BASIS", reason: "NO_REVENUE_BASIS" } };
    v3.m12 = { status: "UNAVAILABLE", reason: "INVALID", scenario: { status: "NO_BASIS", reason: "NO_REVENUE_BASIS" } };
    v3.evidence.approval_sha256 = null;
    v3.evidence.approval_approved_at = null;
    v3.evidence.approval_decisions = null;
    const parsed = parseV3(v3);
    expect(parsed.revenueStatus).toBe("UNAVAILABLE");
    expect(parsed.revenueReason).toBe("INVALID");
    expect(parsed.revenueDiagnostic).toBe("UNREVIEWED_INPUTS");
    expect(parsed.m6.status).toBe("UNAVAILABLE");
    expect(parsed.m6.reason).toBe("INVALID");
    // The surfaces state the unreviewed-inputs suspension (rendered 營收輸入未經審核，暫停營收推估).
    expect(forecastLines(parsed, money)).toContainEqual(expect.stringContaining("營收輸入未經審核，暫停營收推估"));
  });

  it("refuses a forged sealed state: approval fields present beside an unreviewed record", () => {
    // The approval fields are sealed exactly when the profile admitted the record; a forged UNREVIEWED_INPUTS
    // state beside a sealed approval is a contract break.
    const v3 = clone(makeSyntheticV3());
    v3.status = "UNAVAILABLE";
    v3.reason = "INVALID";
    v3.revenue_status = "UNAVAILABLE";
    v3.revenue_reason = "INVALID";
    v3.revenue_diagnostic = "UNREVIEWED_INPUTS";
    v3.m6 = { status: "UNAVAILABLE", reason: "INVALID", scenario: { status: "NO_BASIS", reason: "NO_REVENUE_BASIS" } };
    v3.m12 = { status: "UNAVAILABLE", reason: "INVALID", scenario: { status: "NO_BASIS", reason: "NO_REVENUE_BASIS" } };
    // The synthetic base seals the approval fields (the profile admits the record) - the diagnostic must not stand.
    expect(parseV3(v3).m6.reason).toBe("INVALID");
  });

  it("refuses a sealed CONSENSUS basis while the sealed gate is off, and the deferred diagnostic beside a gate on", () => {
    // A3/A6 (acceptance r7): the registry gate travels sealed. Off: a CONSENSUS basis is invalid (the route is
    // deferred for this rollout). On: the CONSENSUS_DEFERRED diagnostic cannot appear (the route is live).
    const off = clone(makeSyntheticV3());
    off.revenue_basis = "CONSENSUS";
    off.evidence.consensus = {
      symbol: "NVDA", captured_at: "2026-09-28T10:00:00Z", currency: "USD",
      quarters: [{ period: "0q", end: "2026-09-30", revenue: 120.0, analysts: 10 }],
    };
    expect(parseV3(off).m6.reason).toBe("INVALID"); // V3_CONSENSUS_BASIS_GATE_OFF

    const deferred = clone(makeSyntheticV3());
    deferred.evidence.consensus_enabled = true;
    deferred.evidence.consensus = null;
    deferred.revenue_diagnostic = "CONSENSUS_DEFERRED";
    expect(parseV3(deferred).m6.reason).toBe("INVALID"); // V3_DEFERRED_GATE_ON
  });

  it("parses the scoped EVIDENCE_LIMIT envelope and keeps the preserved m12 recognition (A4)", () => {
    // A4 (acceptance r7): the oversized revenue originals were cleared by the sealer; the bounded v2 order view
    // stays sealed, so the independently validated sibling recognition re-derives as exactly that scoped state -
    // never INVALID and never a wiped entry.
    const v3 = clone(makeSyntheticV3());
    // The sealed order view mirrors the sibling v2's own tiles (the recognition on m12 only).
    const sibling = JSON.parse(JSON.stringify((v2Fixture as any).cases.S17.forecast).replaceAll("S17", "NVDA"));
    v3.evidence.order_evidence = { ...sibling.evidence, cutoff: GENERATED };
    v3.order_view = { status: "AVAILABLE", reason: null, m6: sibling.m6, m12: sibling.m12 };
    v3.references = sibling.references;  // the sealed v2 subtree's references travel with the v3 document
    // The sealed contracted-recognition copy must mirror the validated tile's full field set (amount, currency,
    // dates, rpo, share, as-of) - a partial copy is a contract break.
    v3.contracted_recognition = {
      m6: null,
      m12: {
        amount: sibling.m12.amount, currency: sibling.m12.currency, start: sibling.m12.start, end: sibling.m12.end,
        ...(sibling.m12.rpo !== undefined ? { rpo: sibling.m12.rpo } : {}),
        ...(sibling.m12.share_pct !== undefined ? { share_pct: sibling.m12.share_pct } : {}),
        ...(sibling.m12.as_of !== undefined ? { as_of: sibling.m12.as_of } : {}),
      },
    };
    v3.status = "AVAILABLE";
    v3.reason = null;
    v3.revenue_status = "UNAVAILABLE";
    v3.revenue_reason = "EVIDENCE_LIMIT";
    v3.revenue_basis = null;
    // The preserved recognition tiles mirror the validated order view (both horizons in the S17 case).
    const recTile = (t: any) => ({
      status: "AVAILABLE", basis: "RECOGNITION", basis_label: "已簽約預計認列",
      amount: t.amount, currency: t.currency, start: t.start, end: t.end,
      horizon_label: "1年", qualifier: `自${t.start}起，非今日起`,
      ...(t.rpo !== undefined ? { rpo: t.rpo } : {}),
      ...(t.share_pct !== undefined ? { share_pct: t.share_pct } : {}),
      scenario: { status: "NO_BASIS", reason: "NO_REVENUE_BASIS" }, warning: null,
    });
    v3.m6 = { ...recTile(sibling.m6), horizon_label: "半年" };
    v3.m12 = recTile(sibling.m12);
    v3.contracted_recognition = {
      m6: {
        amount: sibling.m6.amount, currency: sibling.m6.currency, start: sibling.m6.start, end: sibling.m6.end,
        as_of: sibling.m6.as_of, share_pct: sibling.m6.share_pct, rpo: sibling.m6.rpo,
      },
      m12: {
        amount: sibling.m12.amount, currency: sibling.m12.currency, start: sibling.m12.start, end: sibling.m12.end,
        as_of: sibling.m12.as_of, share_pct: sibling.m12.share_pct, rpo: sibling.m12.rpo,
      },
    };
    // The scoped envelope: the revenue originals are cleared, the bounded order view stays.
    v3.reported_quarters = [];
    v3.forward_quarters = [];
    v3.baseline_b = null;
    v3.warning = null;
    v3.evidence.documents = [];
    v3.evidence.claims = [];
    v3.evidence.reported_quarters = [];
    v3.evidence.forward_intervals = [];
    v3.evidence.consensus = null;
    v3.evidence.latest_release_check = null;
    v3.evidence.fy_reconciliation = null;
    v3.evidence.release_channels = null;
    v3.evidence.reviewed_later_documents = null;
    v3.evidence.approval_sha256 = null;
    v3.evidence.approval_approved_at = null;
    v3.evidence.approval_decisions = null;
    const parsed = parseV3(v3);
    expect(parsed.m12.status, "the scoped state stays available through the preserved recognition").toBe("AVAILABLE");
    expect(parsed.m12.basis).toBe("RECOGNITION");
    expect(parsed.m12.amount).toBeCloseTo(22e9);
    expect(parsed.m6.status).toBe("AVAILABLE");
    expect(parsed.m6.basis).toBe("RECOGNITION");
    expect(parsed.revenueReason).toBe("EVIDENCE_LIMIT");
    expect(parsed.revenueStatus).toBe("UNAVAILABLE");
  });
});

describe("version-3 forecast states on a genuinely rebuilt real document (writer, ORDERS-V3-01)", () => {
  // tests/fixtures/v213-orders-v3-proof-states.json: outlooks sealed by the real sealer from a v3 document rebuilt with
  // live receipts and the reviewed registry; each entry is one state the Worker must accept as sealed.
  const proof = JSON.parse(readFileSync("../tests/fixtures/v213-orders-v3-proof-states.json", "utf-8"));
  const day = proof.generated_at.slice(0, 10);
  const parse = (sym: string) => parseOrderForecastV3(proof.entries[sym].order_forecast_v3, day, sym, proof.generated_at, proof.entries[sym].order_forecast);

  it("keeps a 12-month RPO recognition beside an official-IR suspension, and suspends without orders", () => {
    const sndk = parse("SNDK");
    expect(sndk.revenueDiagnostic).toBe("IR_COVERAGE_MISSING");
    expect([sndk.m6.status, sndk.m12.status, sndk.m12.basis]).toEqual(["UNAVAILABLE", "AVAILABLE", "RECOGNITION"]);
    expect(sndk.m12.amount).toBeCloseTo(11.362e9, 0);
    const aaoi = parse("AAOI");
    expect([aaoi.m6.status, aaoi.m6.reason, aaoi.m12.status]).toEqual(["UNAVAILABLE", "FRESHNESS_UNVERIFIED", "UNAVAILABLE"]);
    expect(aaoi.revenueDiagnostic).toBe("IR_COVERAGE_MISSING");
  });

  it("accepts the empty envelope of an issuer without a reviewed record as INPUTS_MISSING, not INVALID", () => {
    const f = parse("POET");
    expect([f.m6.status, f.m6.reason, f.m12.reason]).toEqual(["UNAVAILABLE", "INPUTS_MISSING", "INPUTS_MISSING"]);
    // a partial record (one sealed document but no intervals) is not the empty envelope
    const partial = JSON.parse(JSON.stringify(proof.entries.POET.order_forecast_v3));
    partial.evidence.url_prefixes = ["https://www.sec.gov/"];
    partial.evidence.documents = [{ ...proof.entries.MU.order_forecast_v3.evidence.documents[0], issuer: "POET" }];
    expect(parseOrderForecastV3(partial, day, "POET", proof.generated_at, proof.entries.POET.order_forecast).m6.reason).toBe("INVALID");
  });

  it("accepts the ended-quarter bridge and the deferred consensus state as sealed", () => {
    const mu = parse("MU");
    expect(mu.m6.status).toBe("AVAILABLE");
    expect(mu.warning?.text).toContain("財測季度已於2026-09-03結束，實際營收尚未公布");
    const hynix = parse("000660.KS");
    expect([hynix.m6.status, hynix.m6.reason]).toEqual(["UNAVAILABLE", "NOT_DISCLOSED"]);
    expect(hynix.revenueDiagnostic).toBe("CONSENSUS_DEFERRED");
  });

  it("refuses a nested recognition copy on the recognition tile of a suspended revenue path", () => {
    const forged = JSON.parse(JSON.stringify(proof.entries.SNDK.order_forecast_v3));
    forged.m12.contracted_recognition = forged.contracted_recognition.m12;
    expect(parseOrderForecastV3(forged, day, "SNDK", proof.generated_at, proof.entries.SNDK.order_forecast).m6.reason).toBe("INVALID");
  });
});

describe("version-3 rendering of real states: suspension reason and source attribution (writer, ORDERS-V3-01)", () => {
  // A1 (acceptance r7): the pre-r7 proof documents no longer carry the approved profile, so the rendering
  // surfaces move to the regenerated golden (sealed with the approval fields) plus synthetic variants.
  const golden = JSON.parse(readFileSync("../tests/fixtures/v213-orders-v3-golden-sealed.json", "utf-8"));
  const money = (amount: number, currency: string | null) => `${currency ?? ""} ${amount}`;
  const parseGolden = (sym: string) => parseOrderForecastV3(golden[sym].order_forecast_v3, "2026-09-28", sym, "2026-09-28T15:00:00Z",
    golden[sym].order_forecast);
  const surfaces = (f: any) => ({
    card: forecastCard(f, money).map(([text]) => text).join("\n"),
    text: forecastText(f, money),
    detail: forecastLines(f, money).join("\n"),
  });

  it("states the official-IR suspension on every surface (golden, the five blocked issuers)", () => {
    for (const sym of ["SNDK", "AAOI"]) {
      const s = surfaces(parseGolden(sym));
      for (const [name, text] of Object.entries(s)) expect(text, `${sym} ${name}`).toContain("官方IR查核未完成，暫停營收推估");
    }
  });

  it("states the deferred consensus route on every surface (golden 000660.KS, gate off)", () => {
    const s = surfaces(parseGolden("000660.KS"));
    for (const [name, text] of Object.entries(s)) expect(text, name).toContain("公司未提供營收財測；分析師共識路線本次未啟用");
  });

  it("attributes every selected operational claim in the detail: CRWV quarter + FY, quote, locator, URL, the calendar separately", () => {
    const s = surfaces(parseGolden("CRWV"));
    // Both operative selected claims, each with its representation (the stated figure), the operative quote, the
    // locator and the URL; the fiscal calendar is attributed separately.
    expect(s.detail).toContain("公司財測 $3.45 – 3.60 billion");
    expect(s.detail).toContain("公司財測 $12.4 – 13.2 billion");
    expect(s.detail).toContain("原文：「");
    expect(s.detail).toContain("財季日曆來源：");
    expect(s.card).toContain("營收財測來源：");
    expect(s.card).not.toContain("原文：「"); // the compact card keeps the stated figure, the quote stays in the detail
  });

  it("shows the reaffirmation, the actual provenance with derivation operands and the YTD block (NBIS/CRWV)", () => {
    const nbis = surfaces(parseGolden("NBIS"));
    expect(nbis.detail).toContain("財測重申：");
    expect(nbis.detail).toContain("YTD營收（至2026-06-30）");
    const crwv = surfaces(parseGolden("CRWV"));
    expect(crwv.detail).toContain("實際營收來源（至2025-12-31）");
    expect(crwv.detail).toContain("YTD差額"); // the Q4 = FY − 9M derivation operands, shown with the used actual
  });

  it("keeps the 20-entry LINE budget without truncating the required claim detail", () => {
    // All 20 entries carry synthetic outlooks; the text rendering paginates into at most five messages and the
    // detail of each entry keeps its full bounded provenance list (no required line is cut away).
    const rawDoc = doc(REPORT_MS);
    for (let i = 0; i < 20; i++) {
      const sym = i === 0 ? "SIVE.ST" : `S${i}`;
      (rawDoc.top as any)[i].outlook = { orders: null, consensus: null, scenarios: [],
        order_forecast_v3: makeSyntheticV3({ issuer: sym }) };
    }
    const parsed = parseBottleneckV3(rawDoc, REPORT_MS + HOUR)!;
    expect(parsed.top.length).toBe(20);
    const textMessages = buildBottleneckTop20Messages(parsed, "text");
    expect(() => assertLineMessages(textMessages)).not.toThrow();
    expect(textMessages.length).toBeLessThanOrEqual(5);
    // Every entry's detail keeps its bounded guidance line (representation + quote + URL), untruncated.
    for (const entry of parsed.top) {
      const detail = JSON.stringify(buildBottleneckDetail(parsed, entry.symbol, "text"));
      expect(detail).toContain("營收財測來源：");
      expect(detail).toContain("公司財測 120");
      expect(detail).toContain("財季日曆來源：");
    }
  });

  it("names a missing reviewed record precisely (the sealed empty envelope)", () => {
    // The sealed no-record envelope (build_v3 INPUTS_MISSING): empty revenue evidence, explicit null approval
    // fields, and the tiles naming the state precisely.
    const empty = {
      version: 3, issuer: "NVDA", formula: "ORDERS-V3-01", horizon_convention: "FISCAL_2Q_4Q",
      status: "UNAVAILABLE", reason: "INPUTS_MISSING",
      m6: { status: "UNAVAILABLE", reason: "INPUTS_MISSING", scenario: { status: "NO_BASIS", reason: "NO_REVENUE_BASIS" } },
      m12: { status: "UNAVAILABLE", reason: "INPUTS_MISSING", scenario: { status: "NO_BASIS", reason: "NO_REVENUE_BASIS" } },
      revenue_status: "UNAVAILABLE", revenue_reason: "INPUTS_MISSING", revenue_basis: null,
      anchor_date: null, baseline_b: null, reported_quarters: [], forward_quarters: [],
      cutoff: GENERATED,
      evidence: {
        revenue_registry_status: "OK", revenue_registry_sha256: "0".repeat(64),
        cutoff: GENERATED, formula: "ORDERS-V3-01",
        url_prefixes: [], documents: [], claims: [], reported_quarters: [], forward_intervals: [],
        release_channels: null, latest_release_check: null, consensus: null, fy_reconciliation: null,
        reviewed_later_documents: null, order_evidence: null,
        consensus_enabled: false, approval_sha256: null, approval_approved_at: null, approval_decisions: null,
      },
    };
    const s = surfaces(parseOrderForecastV3(empty, REPORT_DAY, "NVDA", GENERATED));
    expect(s.detail).toContain("未收錄經審核的營收財測");
  });
});

describe("producer-to-reader regressions of Astra's r7 acceptance (A1, A2, A4; writer)", () => {
  // tests/fixtures/v213-orders-v3-probes.json: outlooks produced by the real collector, loaders and sealer function from
  // frozen real NVDA inputs (tests/fixtures/make_orders_v3_probes.py); the Worker parses them exactly as produced.
  const probes = JSON.parse(readFileSync("../tests/fixtures/v213-orders-v3-probes.json", "utf-8"));
  const day = probes.generated_at.slice(0, 10);
  const parse = (name: string) => parseOrderForecastV3(probes.cases[name].outlook.order_forecast_v3, day, "NVDA", probes.generated_at,
    probes.cases[name].outlook.order_forecast);
  const keepsRecognition = (f: any) => {
    expect(f.m12.status).toBe("AVAILABLE");
    expect(f.m12.basis).toBe("RECOGNITION");
    expect(f.m12.amount).toBeCloseTo(1.248e9, 0);
  };

  it("control: the approved record with quiet channels is AVAILABLE", () => {
    const f = parse("control");
    expect([f.m6.status, f.m6.amount, f.m12.amount]).toEqual(["AVAILABLE", 216e9, 432e9]);
  });

  it("A1: an unreviewed record change suspends the revenue path with its diagnostic and keeps the recognition", () => {
    const f = parse("unreviewed_extra_field");
    expect(f.m6.status).toBe("UNAVAILABLE");
    expect(f.revenueDiagnostic).toBe("UNREVIEWED_INPUTS");
    keepsRecognition(f);
    expect(forecastLines(f, (a: number, c: string | null) => `${c} ${a}`).join("\n")).toContain("營收輸入未經審核，暫停營收推估");
  });

  it("A1: without any order inputs the unreviewed suspension is the whole state, with its diagnostic", () => {
    const f = parse("unreviewed_without_orders");
    expect([f.m6.status, f.m6.reason, f.m12.status, f.m12.reason]).toEqual(["UNAVAILABLE", "INVALID", "UNAVAILABLE", "INVALID"]);
    expect(f.revenueDiagnostic).toBe("UNREVIEWED_INPUTS");
  });

  it("A4: the produced evidence-limit envelope parses as that scoped state and keeps the recognition", () => {
    const f = parse("evidence_limit_fiscal_label");
    expect([f.m6.status, f.m6.reason]).toEqual(["UNAVAILABLE", "EVIDENCE_LIMIT"]);
    keepsRecognition(f);
  });

  it("A2: compound material IR titles suspend the path; scheduling-only notices stay current", () => {
    for (const [name, c] of Object.entries<any>(probes.cases)) {
      if (!name.startsWith("title_")) continue;
      const f = parse(name);
      if (c.material) {
        expect(c.receipt_status, c.title).toBe("REVIEW_REQUIRED");
        expect([f.m6.status, f.m6.reason], c.title).toEqual(["UNAVAILABLE", "STALE"]);
        keepsRecognition(f);
      } else {
        expect(c.receipt_status, c.title).toBe("OK");
        expect(f.m6.status, c.title).toBe("AVAILABLE");
      }
    }
  });
});

describe("G4c MT7: the sealed zero-YTD degenerate guard on the HUMAN quarter-claim-only path", () => {
  // The default makeSyntheticV3 record is the AVAILABLE quarter-claim carrier of Oracle 1. Its derivation never reads
  // fy_reconciliation, so the sealed shape check V3_FY_ZERO_YTD_DEGENERATE is the only denier here; a machine envelope
  // cannot isolate it (the NBIS machine validator denies first). Synthetic HUMAN record only.
  const withYtd = (ytdStart: string, ytdEnd: string, ytdRevenue: number) => parseOrderForecast(makeSyntheticV3({
    evidence: { fy_reconciliation: { fy_claim_id: "CLAIM-1", ytd_start: ytdStart, ytd_end: ytdEnd, ytd_revenue: ytdRevenue,
      ytd_quarter_ends: [] } },
  }), REPORT_DAY, "NVDA", GENERATED);

  it("control: the exact zero-day span with zero revenue stays AVAILABLE with the Oracle 1 figures", () => {
    const f = withYtd("2026-07-01", "2026-07-01", 0);
    expect([f.m6.status, f.m6.amount, f.m12.amount]).toEqual(["AVAILABLE", 240.0, 480.0]);
  });

  it("an empty quarter-end list with a non-degenerate span or non-zero revenue is INVALID", () => {
    // Every row keeps start <= end and a finite non-negative revenue, so only the degenerate rule can refuse it.
    for (const [start, end, revenue] of [["2026-07-01", "2026-07-02", 0], ["2026-07-01", "2026-07-01", 1],
      ["2026-07-01", "2026-07-01", 0.5], ["2026-07-01", "2026-09-30", 120]] as const) {
      const f = withYtd(start, end, revenue);
      expect([f.m6.status, f.m6.reason, f.m12.status, f.m12.reason], `${start} ${end} ${revenue}`)
        .toEqual(["UNAVAILABLE", "INVALID", "UNAVAILABLE", "INVALID"]);
    }
  });
});
