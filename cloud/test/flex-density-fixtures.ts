import type { LineOutboundMessage } from "../src/line-messages";
import { parseQuery } from "../src/core";
import { buildV213Top20Messages } from "../src/v213/top20-presentation";
import { parseV213Top20Report } from "../src/v213/top20-report";
import { buildBottleneckDetail, buildBottleneckTop20Messages, buildIndustryExplosionMessages, parseBottleneckV3 } from "../src/v213/bottleneck-v3";
import { buildCoveredCallMessages, validateCoveredCallCycle } from "../src/v213/covered-call";
import { buildOptionsCycleComparisonFlex, buildOptionsGuidanceFlexBubble, buildPositionSizingFlexBubble, generateOptionsOrderGuidance, generatePositionSizingFramework } from "../src/v213/options-guidance";
import { buildEducationalStrategyFlex } from "../src/v213/educational-options";
import { buildOptionContractFlex, optionsUnavailableReport } from "../src/v213/options-product";
import { validateOptionContractQuote } from "../src/v213/market-product-schema";
import { v213PublicLineAnswer } from "../src/v213/rich-menu";
import { BULLET_DOT_SIZE, LINE_THEME as T } from "../src/v213/line-theme";
import { doc as bottleneckDoc } from "./bottleneck-v3-fixture";
import { admitSyntheticTickers } from "./synthetic-option-admission";
import strategyFixture from "./fixtures/v21-three-strategies.json";
import consensusFixture from "../../tests/fixtures/v11-consensus-sealed.json";

export interface Node {
  type?: string;
  text?: string;
  contents?: Node[];
  action?: { label?: string };
  width?: number | string;
  height?: number | string;
  layout?: string;
  borderWidth?: number | string;
  cornerRadius?: string;
  spacing?: string;
  size?: string;
  weight?: string;
  maxLines?: number;
  [key: string]: unknown;
}
export interface Metrics {
  texts: number;
  chars: number;
  bullets: number;
  sections: number;
  xxs: number;
  buttons: number;
  footerButtons: number;
  longPlain: string[];
  maxLinesUsed: number;
  labels: string[];
  footerDisclosureLines: number;
  disclosureLines: number;
  distinctSizes: number;
  distinctWeights: number;
  longestPlainLine: number;
}

function isNode(value: unknown): value is Node {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export const isBulletRow = (value: unknown): value is Node => {
  if (!isNode(value) || value.type !== "box" || value.layout !== "horizontal" || value.contents?.length !== 2) return false;
  const dot = value.contents[0];
  return isNode(dot) && dot.type === "box" && dot.width === BULLET_DOT_SIZE && dot.height === BULLET_DOT_SIZE;
};

/** Structure metrics for one bubble; body prose excludes its footer disclosure groups. */
export function measure(bubble: Node): Metrics {
  const m: Metrics = { texts: 0, chars: 0, bullets: 0, sections: 0, xxs: 0, buttons: 0, footerButtons: 0,
    longPlain: [], maxLinesUsed: 0, labels: [], footerDisclosureLines: 0, disclosureLines: 0, distinctSizes: 0, distinctWeights: 0, longestPlainLine: 0 };
  const sizes = new Set<string>();
  const weights = new Set<string>();
  const walk = (value: unknown, inBullet: boolean, inFooter: boolean, inHeader: boolean, inBody: boolean): void => {
    if (Array.isArray(value)) {
      for (const child of value as unknown[]) walk(child, inBullet, inFooter, inHeader, inBody);
      return;
    }
    if (!isNode(value)) return;
    if (value.type === "button") { m.buttons += 1; if (inFooter) m.footerButtons += 1; m.labels.push(value.action?.label ?? ""); return; }
    if (value.type === "box" && value.borderWidth && value.cornerRadius === "md" && value.spacing === "none") m.sections += 1;
    const bullet = isBulletRow(value);
    if (bullet) m.bullets += 1;
    if (typeof value.maxLines === "number") m.maxLinesUsed += 1;
    if (value.type === "text") {
      const text = typeof value.text === "string" ? value.text : value.contents?.map(span => typeof span.text === "string" ? span.text : "").join("") ?? "";
      m.texts += 1; m.chars += Array.from(text).length;
      if (value.size === "xxs") m.xxs += 1;
      if (!inHeader && typeof value.size === "string") sizes.add(value.size);
      if (!inHeader && Array.isArray(value.contents)) {
        for (const span of value.contents) if (isNode(span) && typeof span.weight === "string") weights.add(span.weight);
      }
      if (!inHeader && typeof value.weight === "string") weights.add(value.weight);
      const disclosure = value.size === "xxs" && value.color === T.subtle;
      if (disclosure) {
        m.disclosureLines += 1;
        if (inFooter) m.footerDisclosureLines += 1;
      }
      if (inBody && !disclosure) {
        for (const line of text.split(/\r?\n/)) {
          const length = Array.from(line).length;
          m.longestPlainLine = Math.max(m.longestPlainLine, length);
          if (length > 40) m.longPlain.push(line);
        }
      }
    }
    for (const key of Object.keys(value)) {
      if (key !== "type") walk(value[key], inBullet || bullet, inFooter || key === "footer", inHeader || key === "header", inBody || key === "body");
    }
  };
  walk(bubble, false, false, false, false);
  m.distinctSizes = sizes.size;
  m.distinctWeights = weights.size;
  return m;
}
export const bubblesOf = (messages: readonly LineOutboundMessage[]): Node[] =>
  messages.flatMap(message => message.type === "flex" ? (message.contents as unknown as Node).contents ?? [] : []);
export const worst = (list: Metrics[], key: "texts" | "chars" | "bullets" | "sections" | "footerButtons" | "xxs") => Math.max(...list.map(item => item[key]));

// --- realistic-length fixtures shared by V20 and V25 budgets ---
export function top20Report() {
  return {
    schema_version: 2, product_version: "2.1.3", generated_at: "2026-09-01T00:00:00Z",
    freshness_policy: { policy_id: "v213-serenity-fresh-independent-evidence-v2", policy_sha256: "27ce461fae50218bb14e4d50ff283f6ed75b201e4a38d656643a5ed65d59c8d8" },
    evidence_capture_at: "2026-09-15T11:00:00Z",
    display_columns: ["股票", "長期投資報酬率（近2年年化）", "短期投資報酬率（近6個月）", "行業別", "獲利簡述", "公司現在訂單", "未來訂單預估"],
    long_term_definition: "trailing_2y_adjusted_close_cagr", short_term_definition: "trailing_6m_adjusted_close_price_return",
    records: Array.from({ length: 20 }, (_, index) => ({
      schema_version: 2, rank: index + 1, ticker: `T${String(index).padStart(2, "0")}`, name: `Synthetic Semiconductor Holdings ${index}`,
      long_term_return_pct: 50 - index, short_term_return_pct: 15 - index / 2, industry: "半導體設備與先進封裝材料",
      profit_summary: "最新季營收年增 +20.0%，毛利率 52.1%，營業利益率 31.4%；自由現金流為正，稀釋股數年增 1.2%。",
      current_orders: "2027 年前已簽約固定量約 RMB1.73 億，另有三年期供貨協議；公司於 2026-08 季報揭露在手訂單年增 +35%。",
      future_orders_estimate: "能見度偏高但不估總額；管理層指引下一財年新接訂單年增 20%–30%，但未提供金額，系統不推估訂單總額。",
      long_term_window: "2y_cagr", short_term_window: "6m_price_return", market_source: "yfinance", profit_source: "sec_edgar",
      orders_as_of: "2026-09-01T00:00:00Z", orders_confidence: "EVIDENCE_BOUND",
      current_order_source_urls: ["https://www.sec.gov/example/current"], future_order_source_urls: ["https://www.sec.gov/example/future"],
      numeric_total_order_estimate_prohibited: true, retrieved_at: "2026-09-01T00:00:00Z", orders_state_as_of: "2026-09-01T00:00:00Z",
      evidence_class: "structural_claim", freshness_policy_key: "structural_claim_max_age_days", test_only_admission: true,
      provider_scope: "public_only", owner_watchlist_inherited: false,
    })),
    provider_scope: "public_only", owner_watchlist_inherited: false,
  };
}

export const REPORT = Date.parse("2026-09-27T01:00:00Z");
const tierItem = (role: string, strike: number, bid: number, ask: number, delta: number, spot: number, dte: number) => {
  const mid = Number(((bid + ask) / 2).toFixed(4));
  const limit = Number((Math.floor(mid / 0.01 + 1e-9) * 0.01).toFixed(2));
  return { role, strike, bid, ask, mid, limit_price: limit, premium_per_contract: limit * 100, period_yield: limit / spot,
    annualized_yield: limit / spot * 365 / Math.max(dte, 1), upside_to_strike: strike / spot - 1, delta, delta_basis: "QUOTED", iv: 0.4,
    oi: 1200, volume: 350, spread_pct: (ask - bid) / mid };
};
export const coveredCycle = () => ({ ticker: "NVDA", strategy: "COVERED_CALL", expiry: "2026-10-09", dte: 2, spot: 100, currency: "USD", multiplier: 100,
  quote_basis: "delayed", timestamp: "2026-10-07T14:00:00Z", source: "Yahoo Finance option chain (unofficial, delayed)",
  provenance: "https://finance.yahoo.com/quote/NVDA/options", rights_status: "unadmitted_third_party", asof_date: "2026-10-07", weekly_week: "CURRENT",
  suggestions: [tierItem("HIGH_STRIKE", 112, 0.10, 0.12, 0.08, 100, 2), tierItem("BALANCED", 106, 0.60, 0.66, 0.28, 100, 2)],
  middle_suggestion: tierItem("MIDDLE", 108, 0.35, 0.40, 0.20, 100, 2) });

export const v20Surfaces: Record<string, () => Promise<Node[]> | Node[]> = {
  "top20-presentation": () => bubblesOf(buildV213Top20Messages(parseV213Top20Report(top20Report() as never)!)),
  "bottleneck Top20 card": () => bubblesOf(buildBottleneckTop20Messages(parseBottleneckV3(bottleneckDoc(REPORT - 3600_000), REPORT)!, "flex")),
  "bottleneck detail page 1": () => {
    const parsed = parseBottleneckV3(bottleneckDoc(REPORT - 3600_000), REPORT)!;
    return parsed.top.flatMap(entry => {
      const detail = buildBottleneckDetail(parsed, entry.symbol, "flex");
      return typeof detail === "string" ? [] : [bubblesOf(detail)[0]!];
    });
  },
  "bottleneck industry": () => bubblesOf(buildIndustryExplosionMessages(parseBottleneckV3(bottleneckDoc(REPORT - 3600_000), REPORT)!, "flex")),
  "covered-call (3 tiers)": () => {
    admitSyntheticTickers("NVDA");
    return bubblesOf(buildCoveredCallMessages(validateCoveredCallCycle(coveredCycle())!, "每週期權", "flex"));
  },
  "options-guidance order": () => {
    const guidance = generateOptionsOrderGuidance({ ticker: "nvda", strategy: "covered_call", underlyingPrice: 128.4, strike: 135, expiry: "2026-12-18",
      dte: 94, delta: 0.25, bid: 2.1, mid: 2.25, ask: 2.4, openInterest: 1200, volume: 350 });
    return bubblesOf([buildOptionsGuidanceFlexBubble(guidance)]);
  },
  "options-guidance sizing": () => bubblesOf([buildPositionSizingFlexBubble(generatePositionSizingFramework("BOTTLENECK_CHOKEPOINT"), "NVDA")]),
  "educational-options": () => bubblesOf(buildEducationalStrategyFlex()),
  "options-product contract": () => {
    admitSyntheticTickers("NVDA");
    const quote = validateOptionContractQuote({ ticker: "NVDA", expiry: "2026-09-25", dte: 11, strike: 125, type: "call", bid: 4.2, mid: 4.35, ask: 4.5, spread: 0.3,
      delta: 0.52, iv: 0.45, oi: 2500, volume: 480, breakeven: null, maxprofit: null, maxloss: null, annualized_yield: null,
      assignment_risk: "買方持有權利，無被動指派風險", liquidity_warning: "雙邊價差合理，流動性良好", timestamp: "2026-09-14T12:00:00Z",
      quote_basis: "delayed", source: "yfinance_public", provenance: "OP_TEST_SUITE", currency: "USD", multiplier: 100, rights_status: "unadmitted_third_party" } as never,
    { evaluatedAt: "2026-09-14T12:00:00Z" });
    return bubblesOf(buildOptionContractFlex(quote, { evaluatedAt: "2026-09-14T12:00:00Z" }));
  },
  "options-product unavailable": () => bubblesOf(optionsUnavailableReport("NVDA", "weekly",
    "本輪封存資料沒有 NVDA 的每週期權觀察。（已封存之公開觀察）本輪封存資料沒有 NVDA 的每週期權觀察。", false)),
  "rich-menu navigation": async () => bubblesOf(await v213PublicLineAnswer({} as never, parseQuery("選單")) as LineOutboundMessage[]),
};

const v21StrategyCard = () => {
  const cycle = structuredClone(strategyFixture.cases.yahoo_monthly_full);
  admitSyntheticTickers(cycle.ticker);
  const validated = validateCoveredCallCycle(cycle, Date.parse(strategyFixture.stamp) + 60_000, strategyFixture.stamp, "monthly");
  return validated ? bubblesOf(buildCoveredCallMessages(validated, "每月期權", "flex")).slice(0, 1) : [];
};
const optionsCycleComparison = () => {
  const weekly = generateOptionsOrderGuidance({ ticker: "nvda", strategy: "covered_call", underlyingPrice: 128.4, strike: 135, expiry: "2026-10-09",
    dte: 7, delta: 0.25, bid: 2.1, mid: 2.25, ask: 2.4, openInterest: 1200, volume: 350, cycle: "weekly" });
  const monthly = generateOptionsOrderGuidance({ ticker: "nvda", strategy: "covered_call", underlyingPrice: 128.4, strike: 135, expiry: "2026-10-16",
    dte: 30, delta: 0.25, bid: 2.9, mid: 3.0, ask: 3.1, openInterest: 1200, volume: 350, cycle: "monthly" });
  return bubblesOf([buildOptionsCycleComparisonFlex(weekly, monthly)]);
};
const bottleneckDetailAllPages = () => {
  const parsed = parseBottleneckV3(bottleneckDoc(REPORT - 3600_000), REPORT)!;
  const detail = buildBottleneckDetail(parsed, "S1", "flex");
  return typeof detail === "string" ? [] : bubblesOf(detail);
};

export const v25Surfaces = {
  ...v20Surfaces,
  "V21 three strategies": v21StrategyCard,
  "options-guidance cycle comparison": optionsCycleComparison,
  "bottleneck detail (all pages)": bottleneckDetailAllPages,
} satisfies Record<string, () => Promise<Node[]> | Node[]>;
export function v3D1Surfaces(): Record<string, Node[]> {
  const cases = (consensusFixture as any).cases;
  const scenarios = [
    ["bottleneck consensus V3", "bridge_day13", "000660.KS"],
    ["bottleneck company-guidance V3", "guidance_precedence", "NVDA"],
  ] as const;
  return Object.fromEntries(scenarios.map(([name, caseName, symbol]) => {
    const scenario = cases[caseName];
    const generated = Date.parse(scenario.cutoff);
    const raw = bottleneckDoc(generated);
    raw.top[1]!.symbol = symbol;
    raw.top[1]!.outlook = structuredClone(scenario.outlooks[symbol]);
    const parsed = parseBottleneckV3(raw, generated + 3600_000);
    return [name, parsed ? bubblesOf(buildBottleneckTop20Messages(parsed, "flex")) : []];
  }));
}
export async function v25FlexMessages(): Promise<Extract<LineOutboundMessage, { type: "flex" }>[]> {
  admitSyntheticTickers("NVDA");
  const report = parseV213Top20Report(top20Report() as never)!;
  const doc = parseBottleneckV3(bottleneckDoc(REPORT - 3600_000), REPORT)!;
  const detail = buildBottleneckDetail(doc, "S1", "flex");
  const cycle = validateCoveredCallCycle(coveredCycle())!;
  const order = generateOptionsOrderGuidance({ ticker: "nvda", strategy: "covered_call", underlyingPrice: 128.4, strike: 135, expiry: "2026-12-18",
    dte: 94, delta: 0.25, bid: 2.1, mid: 2.25, ask: 2.4, openInterest: 1200, volume: 350 });
  const weekly = generateOptionsOrderGuidance({ ticker: "nvda", strategy: "covered_call", underlyingPrice: 128.4, strike: 135, expiry: "2026-10-09",
    dte: 7, delta: 0.25, bid: 2.1, mid: 2.25, ask: 2.4, openInterest: 1200, volume: 350, cycle: "weekly" });
  const monthly = generateOptionsOrderGuidance({ ticker: "nvda", strategy: "covered_call", underlyingPrice: 128.4, strike: 135, expiry: "2026-10-16",
    dte: 30, delta: 0.25, bid: 2.9, mid: 3.0, ask: 3.1, openInterest: 1200, volume: 350, cycle: "monthly" });
  const quote = validateOptionContractQuote({ ticker: "NVDA", expiry: "2026-09-25", dte: 11, strike: 125, type: "call", bid: 4.2, mid: 4.35, ask: 4.5, spread: 0.3,
    delta: 0.52, iv: 0.45, oi: 2500, volume: 480, breakeven: null, maxprofit: null, maxloss: null, annualized_yield: null,
    assignment_risk: "買方持有權利，無被動指派風險", liquidity_warning: "雙邊價差合理，流動性良好", timestamp: "2026-09-14T12:00:00Z",
    quote_basis: "delayed", source: "yfinance_public", provenance: "OP_TEST_SUITE", currency: "USD", multiplier: 100, rights_status: "unadmitted_third_party" } as never,
    { evaluatedAt: "2026-09-14T12:00:00Z" });
  const navigation = await v213PublicLineAnswer({} as never, parseQuery("選單"));
  const messages: LineOutboundMessage[] = [
    ...buildV213Top20Messages(report),
    ...buildBottleneckTop20Messages(doc, "flex"),
    ...(typeof detail === "string" ? [] : detail),
    ...buildIndustryExplosionMessages(doc, "flex"),
    ...buildCoveredCallMessages(cycle, "每週期權", "flex"),
    buildOptionsGuidanceFlexBubble(order),
    buildPositionSizingFlexBubble(generatePositionSizingFramework("BOTTLENECK_CHOKEPOINT"), "NVDA"),
    ...buildEducationalStrategyFlex(),
    ...buildOptionContractFlex(quote, { evaluatedAt: "2026-09-14T12:00:00Z" }),
    ...optionsUnavailableReport("NVDA", "weekly", "本輪封存資料沒有公開期權觀察。", false),
    ...buildCoveredCallMessages(validateCoveredCallCycle(structuredClone(strategyFixture.cases.yahoo_monthly_full),
      Date.parse(strategyFixture.stamp) + 60_000, strategyFixture.stamp, "monthly")!, "每月期權", "flex").slice(0, 1),
    buildOptionsCycleComparisonFlex(weekly, monthly),
  ];
  if (Array.isArray(navigation)) messages.push(...navigation);
  return messages.filter((message): message is Extract<LineOutboundMessage, { type: "flex" }> => message.type === "flex");
}
