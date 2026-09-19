/**
 * Typed schemas and strict validators for Macro Industry Products and Options Products.
 * Preserves evidence boundaries: no company-count percentage as market growth,
 * no ungrounded probability scores, no fake live quotes, and strict validation.
 */

export interface MacroGrowthRate {
  readonly rate_pct: number;
  readonly units: string;
  readonly period: string;
  readonly type: "forecast" | "actual";
  readonly publisher: string;
  readonly date: string;
  readonly source_id: string;
  readonly url?: string;
  readonly raw_passage?: string;
}

export interface MacroIndustryCard {
  readonly rank: number | null;
  readonly industry_id: string;
  readonly industry_name: string;
  readonly current_state: string;
  readonly outlook_12_36m: string;
  readonly growth: MacroGrowthRate | null;
  readonly demand_drivers: readonly string[];
  readonly supply_constraint_chokepoint: string;
  readonly pricing: string;
  readonly value_chain_position: string;
  readonly beneficiaries_key_suppliers: readonly string[];
  readonly catalysts: {
    readonly m6: string;
    readonly y1: string;
    readonly y2: string;
  };
  readonly risks_lifecycle: string;
  readonly opportunity_score: number; // 0-100 System Operationalization, not probability
  readonly confidence: {
    readonly data_completeness: number;
    readonly source_independence: number;
    readonly verification_status: string;
  };
  readonly admission_status?: "ADMITTED" | "NOT_PUBLICATION_QUALIFIED";
}

export interface MacroDeepAnalysis {
  readonly industry_id: string;
  readonly industry_name: string;
  readonly demand: string;
  readonly supply: string;
  readonly bottleneck: string;
  readonly pricing: string;
  readonly capex: string;
  readonly competition: string;
  readonly beneficiaries: readonly string[];
  readonly catalysts: {
    readonly m6: string;
    readonly y1: string;
    readonly y2: string;
  };
  readonly risks: readonly string[];
  readonly killers: readonly string[];
  readonly source_references: readonly {
    readonly source: string;
    readonly url: string;
    readonly period?: string;
    readonly passage?: string;
  }[];
}

export interface MacroTop5Overview {
  readonly title: "TOP5產業總覽";
  readonly generated_at: string;
  readonly horizon: string;
  readonly qualified_count: number;
  readonly shortfall: number;
  readonly status: "ADMITTED_TOP5" | "SHORTFALL_NOT_QUALIFIED";
  readonly shortfall_report?: string;
  readonly industries: readonly MacroIndustryCard[];
}

export interface OptionContractQuote {
  readonly ticker: string;
  readonly expiry: string;
  readonly dte: number;
  readonly strike: number;
  readonly type: "call" | "put";
  readonly bid: number;
  readonly mid: number;
  readonly ask: number;
  readonly spread: number;
  readonly delta: number | null;
  readonly iv: number | null;
  readonly oi: number | null;
  readonly volume: number | null;
  readonly breakeven: null;
  readonly maxprofit: null;
  readonly maxloss: null;
  readonly annualized_yield: null;
  readonly assignment_risk: string;
  readonly liquidity_warning: string;
  readonly timestamp: string;
  readonly quote_basis: "realtime" | "delayed" | "asof_close";
  readonly source: string;
  readonly provenance: string;
  readonly currency: "USD";
  readonly multiplier: 100;
  readonly rights_status: "reviewed_public_access" | "candidate_local_review" | "unadmitted_third_party" | "review_before_enable" | "automated_access_prohibited";
  readonly admission_status: "ADMITTED" | "NOT_ADMITTED";
}

export interface OptionEducationalStrategyCard {
  readonly strategy_id: "covered_call" | "cash_secured_put" | "bull_call_spread" | "protective_put";
  readonly strategy_name: string;
  readonly illustrative_ticker: string;
  readonly expiry_dte: string;
  readonly strikes: string;
  readonly debit_credit: string;
  readonly breakeven: string;
  readonly maxprofit: string;
  readonly maxloss: string;
  readonly assignment_exercise_risk: string;
  readonly appropriate_scenarios: string;
  readonly inappropriate_scenarios: string;
  readonly disclaimer: "教學範例，非推薦";
  readonly status: "SYNTHETIC_EDUCATIONAL";
  readonly simulated_as_of: string;
  readonly payoff_reference: {
    readonly underlying_cost_basis: number;
    readonly contract_multiplier: number;
    readonly strike: number;
    readonly premium: number;
    readonly breakeven_price: number;
    readonly max_profit_amount: number | "UNBOUNDED";
    readonly max_loss_amount: number;
    readonly net_credit_debit: number;
  };
  readonly assumptions: {
    readonly quantity_multiplier: string;
    readonly cost_basis: string;
    readonly collateral: string;
    readonly premium_fees: string;
    readonly exercise_assignment_tax: string;
    readonly specific_caveats: string;
  };
}

// Helper: Require strict finite number (rejects string coercion, null, boolean, NaN, Infinity)
export function requireStrictFiniteNumber(val: unknown, field: string): number {
  if (typeof val !== "number" || !Number.isFinite(val)) {
    throw new Error(`STRICT_FINITE_NUMBER_REQUIRED: ${field}`);
  }
  return val;
}

export function requireStrictInteger(val: unknown, field: string): number {
  const n = requireStrictFiniteNumber(val, field);
  if (!Number.isInteger(n)) {
    throw new Error(`STRICT_INTEGER_REQUIRED: ${field}`);
  }
  return n;
}

const STRICT_ISO_INSTANT_RE = /^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d+)?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/;

export function parseStrictIsoInstant(val: unknown, fieldName: string): number {
  if (typeof val !== "string" || !STRICT_ISO_INSTANT_RE.test(val.trim())) {
    throw new Error(`INVALID_${fieldName.toUpperCase()}`);
  }
  const str = val.trim();
  const ts = Date.parse(str);
  if (!Number.isFinite(ts)) {
    throw new Error(`INVALID_${fieldName.toUpperCase()}`);
  }
  return ts;
}

const VALID_PERIOD_RE = /^(?:\d{4}|\d{4}-\d{4}|\d{4}\s*Q[1-4])$/i;
const VALID_DATE_RE = /^\d{4}-(?:0[1-9]|1[0-2])(?:-(?:0[1-9]|[12]\d|3[01]))?$/;

export function validateMacroGrowthRate(
  raw: unknown,
  validationOptions?: { evaluatedAt?: string },
): MacroGrowthRate | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const obj = raw as Record<string, unknown>;

  const rate_pct = requireStrictFiniteNumber(obj.rate_pct, "rate_pct");

  if (typeof obj.units !== "string" || !obj.units.trim()) {
    throw new Error("MISSING_GROWTH_UNITS");
  }
  const units = obj.units.trim();

  if (typeof obj.period !== "string" || !VALID_PERIOD_RE.test(obj.period.trim())) {
    throw new Error("INVALID_GROWTH_PERIOD");
  }
  const period = obj.period.trim();

  if (obj.type !== "forecast" && obj.type !== "actual") {
    throw new Error("INVALID_GROWTH_TYPE");
  }

  if (typeof obj.publisher !== "string" || !obj.publisher.trim()) {
    throw new Error("MISSING_GROWTH_PUBLISHER");
  }
  const publisher = obj.publisher.trim();

  if (typeof obj.date !== "string" || !VALID_DATE_RE.test(obj.date.trim())) {
    throw new Error("INVALID_GROWTH_DATE");
  }
  const date = obj.date.trim();

  // Future growth date check
  const evalDateStr = validationOptions?.evaluatedAt
    ? validationOptions.evaluatedAt.slice(0, 10)
    : new Date().toISOString().slice(0, 10);
  const normalizedDate = date.length === 4 ? `${date}-12-31` : date.length === 7 ? `${date}-28` : date;
  if (normalizedDate > evalDateStr) {
    throw new Error("FUTURE_GROWTH_DATE_REJECTED");
  }

  // Strict check: company count / percentage cannot masquerade as market growth!
  const lowerUnits = units.toLowerCase();
  const lowerPassage = (typeof obj.raw_passage === "string" ? obj.raw_passage : "").toLowerCase();
  if (
    lowerUnits.includes("company") ||
    lowerUnits.includes("companies") ||
    lowerUnits.includes("ticker") ||
    lowerUnits.includes("家數") ||
    lowerUnits.includes("候選家數") ||
    lowerPassage.includes("家數占比") ||
    lowerPassage.includes("candidates percentage")
  ) {
    throw new Error("COMPANY_COUNT_PERCENTAGE_CANNOT_BE_MARKET_GROWTH");
  }

  // Source ID and reference lineage binding required
  const source_id = typeof obj.source_id === "string" ? obj.source_id.trim() : "";
  if (!source_id) {
    throw new Error("UNADMITTED_GROWTH_SOURCE");
  }

  // Require verifiable source binding (valid URL or substantial raw passage)
  const url = typeof obj.url === "string" && /^https?:\/\//i.test(obj.url.trim()) ? obj.url.trim() : undefined;
  const raw_passage = typeof obj.raw_passage === "string" && obj.raw_passage.trim().length >= 10 ? obj.raw_passage.trim() : undefined;

  if (!url && !raw_passage) {
    throw new Error("SOURCE_BINDING_REQUIRED");
  }

  return {
    rate_pct,
    units,
    period,
    type: obj.type,
    publisher,
    date,
    source_id,
    url,
    raw_passage,
  };
}

export function validateMacroIndustryCard(
  raw: unknown,
  validationOptions?: { evaluatedAt?: string },
): MacroIndustryCard {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    throw new Error("INVALID_MACRO_INDUSTRY_CARD");
  }
  const obj = raw as Record<string, unknown>;

  let rank: number | null = null;
  if (obj.rank !== null && obj.rank !== undefined) {
    rank = requireStrictInteger(obj.rank, "rank");
    if (rank < 1) {
      throw new Error("INVALID_INDUSTRY_RANK");
    }
  }

  if (typeof obj.industry_id !== "string" || !obj.industry_id.trim()) {
    throw new Error("INVALID_INDUSTRY_ID");
  }
  if (typeof obj.industry_name !== "string" || !obj.industry_name.trim()) {
    throw new Error("INVALID_INDUSTRY_NAME");
  }
  if (typeof obj.current_state !== "string" || !obj.current_state.trim()) {
    throw new Error("INVALID_CURRENT_STATE");
  }
  if (typeof obj.outlook_12_36m !== "string" || !obj.outlook_12_36m.trim()) {
    throw new Error("INVALID_OUTLOOK_12_36M");
  }

  const growth = obj.growth ? validateMacroGrowthRate(obj.growth, validationOptions) : null;

  if (!Array.isArray(obj.demand_drivers) || obj.demand_drivers.length === 0) {
    throw new Error("INVALID_DEMAND_DRIVERS");
  }
  if (typeof obj.supply_constraint_chokepoint !== "string" || !obj.supply_constraint_chokepoint.trim()) {
    throw new Error("INVALID_SUPPLY_CONSTRAINT");
  }
  if (typeof obj.pricing !== "string" || !obj.pricing.trim()) {
    throw new Error("INVALID_PRICING");
  }
  if (typeof obj.value_chain_position !== "string" || !obj.value_chain_position.trim()) {
    throw new Error("INVALID_VALUE_CHAIN_POSITION");
  }
  if (!Array.isArray(obj.beneficiaries_key_suppliers) || obj.beneficiaries_key_suppliers.length === 0) {
    throw new Error("INVALID_BENEFICIARIES");
  }

  const cat = obj.catalysts as Record<string, unknown> | undefined;
  if (!cat || typeof cat.m6 !== "string" || typeof cat.y1 !== "string" || typeof cat.y2 !== "string") {
    throw new Error("INVALID_CATALYSTS");
  }
  if (typeof obj.risks_lifecycle !== "string" || !obj.risks_lifecycle.trim()) {
    throw new Error("INVALID_RISKS_LIFECYCLE");
  }
  const opportunity_score = requireStrictFiniteNumber(obj.opportunity_score, "opportunity_score");
  if (opportunity_score < 0 || opportunity_score > 100) {
    throw new Error("INVALID_OPPORTUNITY_SCORE");
  }

  const conf = obj.confidence as Record<string, unknown> | undefined;
  if (
    !conf ||
    typeof conf.data_completeness !== "number" ||
    typeof conf.source_independence !== "number" ||
    typeof conf.verification_status !== "string"
  ) {
    throw new Error("INVALID_CONFIDENCE");
  }

  const admission_status = growth !== null && rank !== null ? "ADMITTED" : "NOT_PUBLICATION_QUALIFIED";

  return {
    rank,
    industry_id: obj.industry_id.trim(),
    industry_name: obj.industry_name.trim(),
    current_state: obj.current_state.trim(),
    outlook_12_36m: obj.outlook_12_36m.trim(),
    growth,
    demand_drivers: (obj.demand_drivers as unknown[]).map(s => String(s).trim()),
    supply_constraint_chokepoint: obj.supply_constraint_chokepoint.trim(),
    pricing: obj.pricing.trim(),
    value_chain_position: obj.value_chain_position.trim(),
    beneficiaries_key_suppliers: (obj.beneficiaries_key_suppliers as unknown[]).map(s => String(s).trim()),
    catalysts: {
      m6: cat.m6.trim(),
      y1: cat.y1.trim(),
      y2: cat.y2.trim(),
    },
    risks_lifecycle: obj.risks_lifecycle.trim(),
    opportunity_score,
    confidence: {
      data_completeness: conf.data_completeness,
      source_independence: conf.source_independence,
      verification_status: String(conf.verification_status).trim(),
    },
    admission_status,
  };
}

export function validateMacroTop5Overview(
  raw: unknown,
  validationOptions?: { evaluatedAt?: string },
): MacroTop5Overview {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    throw new Error("INVALID_MACRO_TOP5_OVERVIEW");
  }
  const obj = raw as Record<string, unknown>;
  if (obj.title !== "TOP5產業總覽") {
    throw new Error("INVALID_OVERVIEW_TITLE");
  }
  if (typeof obj.generated_at !== "string" || !obj.generated_at.trim()) {
    throw new Error("INVALID_GENERATED_AT");
  }
  if (typeof obj.horizon !== "string" || !obj.horizon.trim()) {
    throw new Error("INVALID_HORIZON");
  }
  if (!Array.isArray(obj.industries)) {
    throw new Error("INVALID_INDUSTRIES_LIST");
  }

  const validatedIndustries = obj.industries.map(c => validateMacroIndustryCard(c, validationOptions));
  // Count only truly admitted industries (with non-null rank and admitted growth)
  const admittedIndustries = validatedIndustries.filter(ind => ind.admission_status === "ADMITTED" && ind.rank !== null);
  const qualifiedCount = typeof obj.qualified_count === "number" ? obj.qualified_count : admittedIndustries.length;
  const shortfall = Math.max(0, 5 - qualifiedCount);
  const status = shortfall === 0 && qualifiedCount >= 5 ? "ADMITTED_TOP5" : "SHORTFALL_NOT_QUALIFIED";

  return {
    title: "TOP5產業總覽",
    generated_at: obj.generated_at.trim(),
    horizon: obj.horizon.trim(),
    qualified_count: qualifiedCount,
    shortfall,
    status,
    shortfall_report: typeof obj.shortfall_report === "string" ? obj.shortfall_report.trim() : undefined,
    industries: validatedIndustries,
  };
}

export function validateMacroDeepAnalysis(raw: unknown): MacroDeepAnalysis {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    throw new Error("INVALID_MACRO_DEEP_ANALYSIS");
  }
  const obj = raw as Record<string, unknown>;
  if (typeof obj.industry_id !== "string" || !obj.industry_id.trim()) {
    throw new Error("INVALID_DEEP_ANALYSIS_INDUSTRY_ID");
  }
  if (typeof obj.industry_name !== "string" || !obj.industry_name.trim()) {
    throw new Error("INVALID_DEEP_ANALYSIS_INDUSTRY_NAME");
  }
  for (const field of ["demand", "supply", "bottleneck", "pricing", "capex", "competition"] as const) {
    if (typeof obj[field] !== "string" || !(obj[field] as string).trim()) {
      throw new Error(`INVALID_DEEP_ANALYSIS_${field.toUpperCase()}`);
    }
  }
  if (!Array.isArray(obj.beneficiaries) || obj.beneficiaries.length === 0) {
    throw new Error("INVALID_DEEP_ANALYSIS_BENEFICIARIES");
  }
  const cat = obj.catalysts as Record<string, unknown> | undefined;
  if (!cat || typeof cat.m6 !== "string" || typeof cat.y1 !== "string" || typeof cat.y2 !== "string") {
    throw new Error("INVALID_DEEP_ANALYSIS_CATALYSTS");
  }
  if (!Array.isArray(obj.risks) || obj.risks.length === 0) {
    throw new Error("INVALID_DEEP_ANALYSIS_RISKS");
  }
  if (!Array.isArray(obj.killers) || obj.killers.length === 0) {
    throw new Error("INVALID_DEEP_ANALYSIS_KILLERS");
  }
  if (!Array.isArray(obj.source_references)) {
    throw new Error("INVALID_DEEP_ANALYSIS_SOURCES");
  }

  return {
    industry_id: obj.industry_id.trim(),
    industry_name: obj.industry_name.trim(),
    demand: (obj.demand as string).trim(),
    supply: (obj.supply as string).trim(),
    bottleneck: (obj.bottleneck as string).trim(),
    pricing: (obj.pricing as string).trim(),
    capex: (obj.capex as string).trim(),
    competition: (obj.competition as string).trim(),
    beneficiaries: (obj.beneficiaries as unknown[]).map(s => String(s).trim()),
    catalysts: {
      m6: cat.m6.trim(),
      y1: cat.y1.trim(),
      y2: cat.y2.trim(),
    },
    risks: (obj.risks as unknown[]).map(s => String(s).trim()),
    killers: (obj.killers as unknown[]).map(s => String(s).trim()),
    source_references: (obj.source_references as unknown[]).map(ref => {
      const r = ref as Record<string, unknown>;
      return {
        source: String(r.source ?? "").trim(),
        url: String(r.url ?? "").trim(),
        period: typeof r.period === "string" ? r.period.trim() : undefined,
        passage: typeof r.passage === "string" ? r.passage.trim() : undefined,
      };
    }),
  };
}

export function validateOptionContractQuote(
  raw: unknown,
  validationOptions?: {
    evaluatedAt?: string;
    ticker?: string;
    period?: "weekly" | "monthly";
  },
): OptionContractQuote {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    throw new Error("INVALID_OPTION_CONTRACT_QUOTE");
  }
  const obj = raw as Record<string, unknown>;

  // Evaluation clock parsing - strict ISO instant check, never silently skip
  const evalClock = validationOptions?.evaluatedAt
    ? parseStrictIsoInstant(validationOptions.evaluatedAt, "evaluation_clock")
    : Date.now();

  const ticker = String(obj.ticker ?? "").toUpperCase().trim();
  if (!/^[A-Z0-9.-]{1,15}$/.test(ticker)) throw new Error("INVALID_QUOTE_TICKER");
  if (validationOptions?.ticker) {
    const reqTicker = validationOptions.ticker.toUpperCase().trim();
    if (ticker !== reqTicker) {
      throw new Error("QUOTE_TICKER_MISMATCH");
    }
  }

  const expiry = String(obj.expiry ?? "").trim();
  if (!/^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])$/.test(expiry)) {
    throw new Error("INVALID_EXPIRY_FORMAT");
  }
  const expParts = expiry.split("-").map(Number);
  const expYear = expParts[0]!;
  const expMonth = expParts[1]!;
  const expDay = expParts[2]!;
  const testExpDate = new Date(Date.UTC(expYear, expMonth - 1, expDay));
  if (
    testExpDate.getUTCFullYear() !== expYear ||
    testExpDate.getUTCMonth() !== expMonth - 1 ||
    testExpDate.getUTCDate() !== expDay
  ) {
    throw new Error("INVALID_EXPIRY_FORMAT");
  }

  const dte = requireStrictInteger(obj.dte, "dte");
  if (dte < 0 || dte > 1000) throw new Error("INVALID_DTE");

  // Enforce period matching (weekly 3-14 DTE, monthly 21-45 DTE per options policy)
  if (validationOptions?.period) {
    if (validationOptions.period === "weekly" && (dte < 3 || dte > 14)) {
      throw new Error("QUOTE_PERIOD_MISMATCH");
    }
    if (validationOptions.period === "monthly" && (dte < 21 || dte > 45)) {
      throw new Error("QUOTE_PERIOD_MISMATCH");
    }
  }

  // Calendar DTE & expired contract validation against current evaluation clock
  const evalDate = new Date(evalClock);
  const evalDateUtc = Date.UTC(evalDate.getUTCFullYear(), evalDate.getUTCMonth(), evalDate.getUTCDate());
  const expDateUtc = testExpDate.getTime();
  if (expDateUtc < evalDateUtc) {
    throw new Error("EXPIRED_CONTRACT_REJECTED");
  }
  const calendarDte = Math.round((expDateUtc - evalDateUtc) / (86400 * 1000));
  if (calendarDte < 0) {
    throw new Error("EXPIRED_CONTRACT_REJECTED");
  }
  if (Math.abs(dte - calendarDte) > 1) {
    throw new Error("EXPIRY_DTE_INCONSISTENT");
  }

  const strike = requireStrictFiniteNumber(obj.strike, "strike");
  if (strike <= 0) throw new Error("INVALID_STRIKE");

  const type = String(obj.type).toLowerCase();
  if (type !== "call" && type !== "put") throw new Error("INVALID_OPTION_TYPE");

  const bid = requireStrictFiniteNumber(obj.bid, "bid");
  const ask = requireStrictFiniteNumber(obj.ask, "ask");
  if (bid < 0) throw new Error("INVALID_BID");
  if (ask < 0) throw new Error("INVALID_ASK");
  if (ask < bid) throw new Error("CROSSED_MARKET_QUOTE_BID_EXCEEDS_ASK");

  const mid = requireStrictFiniteNumber(obj.mid, "mid");
  if (Math.abs(mid - (bid + ask) / 2) > 0.001) {
    throw new Error("INVALID_MID_QUOTE_MUST_MATCH_BID_ASK_AVERAGE");
  }

  const spread = requireStrictFiniteNumber(obj.spread, "spread");
  if (Math.abs(spread - (ask - bid)) > 0.001) {
    throw new Error("INVALID_SPREAD_MUST_MATCH_ASK_MINUS_BID");
  }

  const delta = obj.delta === null || obj.delta === undefined
    ? null
    : requireStrictFiniteNumber(obj.delta, "delta");
  if (delta !== null && (delta < -1 || delta > 1)) {
    throw new Error("INVALID_DELTA_RANGE");
  }

  const iv = obj.iv === null || obj.iv === undefined
    ? null
    : requireStrictFiniteNumber(obj.iv, "iv");
  if (iv !== null && iv < 0) {
    throw new Error("INVALID_IV");
  }

  const oi = obj.oi === null || obj.oi === undefined
    ? null
    : requireStrictInteger(obj.oi, "oi");
  if (oi !== null && oi < 0) {
    throw new Error("INVALID_OI");
  }

  const volume = obj.volume === null || obj.volume === undefined
    ? null
    : requireStrictInteger(obj.volume, "volume");
  if (volume !== null && volume < 0) {
    throw new Error("INVALID_VOLUME");
  }

  // Finding A: Strict prohibition of caller-supplied payoff metrics on bare option quote
  if (
    (obj.breakeven !== undefined && obj.breakeven !== null) ||
    (obj.maxprofit !== undefined && obj.maxprofit !== null) ||
    (obj.maxloss !== undefined && obj.maxloss !== null) ||
    (obj.annualized_yield !== undefined && obj.annualized_yield !== null)
  ) {
    throw new Error("BARE_QUOTE_STRATEGY_METRICS_PROHIBITED");
  }

  const quote_basis = String(obj.quote_basis ?? "");
  if (quote_basis !== "realtime" && quote_basis !== "delayed" && quote_basis !== "asof_close") {
    throw new Error("INVALID_QUOTE_BASIS");
  }

  // Currency and multiplier binding (Finding C)
  if (obj.currency !== "USD") {
    throw new Error("INVALID_CURRENCY");
  }
  const currency: "USD" = "USD";

  if (obj.multiplier !== 100) {
    throw new Error("INVALID_MULTIPLIER");
  }
  const multiplier: 100 = 100;

  const source = String(obj.source ?? "").trim();
  if (!source) {
    throw new Error("MISSING_QUOTE_SOURCE");
  }

  const provenance = String(obj.provenance ?? "").trim();
  if (!provenance) {
    throw new Error("MISSING_QUOTE_PROVENANCE");
  }

  const validRights = [
    "reviewed_public_access",
    "candidate_local_review",
    "unadmitted_third_party",
    "review_before_enable",
    "automated_access_prohibited",
  ] as const;
  const rights_status = obj.rights_status as typeof validRights[number];
  if (!validRights.includes(rights_status)) {
    throw new Error("INVALID_RIGHTS_STATUS");
  }

  const admission_status = rights_status === "reviewed_public_access" ? "ADMITTED" : "NOT_ADMITTED";

  // Strict ISO Instant timestamp validation
  const timestamp = String(obj.timestamp ?? "");
  const ts = parseStrictIsoInstant(timestamp, "quote_timestamp");
  if (ts > evalClock + 300_000) {
    throw new Error("FUTURE_TIMESTAMP_REJECTED");
  }

  // Freshness age policy relative to evaluation clock (86400s max for active, 345600s for asof_close)
  const ageSeconds = (evalClock - ts) / 1000;
  const maxAgeSeconds = quote_basis === "asof_close" ? 345_600 : 86_400;
  if (ageSeconds > maxAgeSeconds) {
    throw new Error("STALE_TIMESTAMP_REJECTED");
  }

  return {
    ticker,
    expiry,
    dte,
    strike,
    type: type as "call" | "put",
    bid,
    mid,
    ask,
    spread,
    delta,
    iv,
    oi,
    volume,
    breakeven: null,
    maxprofit: null,
    maxloss: null,
    annualized_yield: null,
    assignment_risk: String(obj.assignment_risk ?? "").trim(),
    liquidity_warning: String(obj.liquidity_warning ?? "").trim(),
    timestamp,
    quote_basis,
    source,
    provenance,
    currency,
    multiplier,
    rights_status,
    admission_status,
  };
}

export function validateEducationalStrategyCard(raw: unknown): OptionEducationalStrategyCard {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    throw new Error("INVALID_EDUCATIONAL_STRATEGY_CARD");
  }
  const obj = raw as Record<string, unknown>;
  const validIds = ["covered_call", "cash_secured_put", "bull_call_spread", "protective_put"] as const;
  const strategy_id = obj.strategy_id as typeof validIds[number];
  if (!validIds.includes(strategy_id)) {
    throw new Error("INVALID_STRATEGY_ID");
  }
  if (obj.disclaimer !== "教學範例，非推薦") {
    throw new Error("MANDATORY_EDUCATIONAL_DISCLAIMER_MISSING");
  }
  if (obj.status !== "SYNTHETIC_EDUCATIONAL") {
    throw new Error("MANDATORY_SYNTHETIC_MARKER_MISSING");
  }

  const pref = obj.payoff_reference as Record<string, unknown> | undefined;
  if (!pref || typeof pref !== "object") {
    throw new Error("INVALID_PAYOFF_REFERENCE");
  }
  const underlying_cost_basis = requireStrictFiniteNumber(pref.underlying_cost_basis, "underlying_cost_basis");
  const contract_multiplier = requireStrictInteger(pref.contract_multiplier, "contract_multiplier");
  if (contract_multiplier !== 100) throw new Error("INVALID_CONTRACT_MULTIPLIER");
  const strike = requireStrictFiniteNumber(pref.strike, "strike");
  const premium = requireStrictFiniteNumber(pref.premium, "premium");
  const breakeven_price = requireStrictFiniteNumber(pref.breakeven_price, "breakeven_price");
  let max_profit_amount: number | "UNBOUNDED";
  if (pref.max_profit_amount === "UNBOUNDED") {
    max_profit_amount = "UNBOUNDED";
  } else {
    max_profit_amount = requireStrictFiniteNumber(pref.max_profit_amount, "max_profit_amount");
  }
  const max_loss_amount = requireStrictFiniteNumber(pref.max_loss_amount, "max_loss_amount");
  const net_credit_debit = requireStrictFiniteNumber(pref.net_credit_debit, "net_credit_debit");

  const assumptions = obj.assumptions as Record<string, unknown> | undefined;
  if (
    !assumptions ||
    typeof assumptions.quantity_multiplier !== "string" ||
    typeof assumptions.cost_basis !== "string" ||
    typeof assumptions.collateral !== "string" ||
    typeof assumptions.premium_fees !== "string" ||
    typeof assumptions.exercise_assignment_tax !== "string" ||
    typeof assumptions.specific_caveats !== "string"
  ) {
    throw new Error("INVALID_STRATEGY_ASSUMPTIONS");
  }

  return {
    strategy_id,
    strategy_name: String(obj.strategy_name ?? "").trim(),
    illustrative_ticker: String(obj.illustrative_ticker ?? "").trim(),
    expiry_dte: String(obj.expiry_dte ?? "").trim(),
    strikes: String(obj.strikes ?? "").trim(),
    debit_credit: String(obj.debit_credit ?? "").trim(),
    breakeven: String(obj.breakeven ?? "").trim(),
    maxprofit: String(obj.maxprofit ?? "").trim(),
    maxloss: String(obj.maxloss ?? "").trim(),
    assignment_exercise_risk: String(obj.assignment_exercise_risk ?? "").trim(),
    appropriate_scenarios: String(obj.appropriate_scenarios ?? "").trim(),
    inappropriate_scenarios: String(obj.inappropriate_scenarios ?? "").trim(),
    disclaimer: "教學範例，非推薦",
    status: "SYNTHETIC_EDUCATIONAL",
    simulated_as_of: String(obj.simulated_as_of ?? "").trim(),
    payoff_reference: {
      underlying_cost_basis,
      contract_multiplier,
      strike,
      premium,
      breakeven_price,
      max_profit_amount,
      max_loss_amount,
      net_credit_debit,
    },
    assumptions: {
      quantity_multiplier: String(assumptions.quantity_multiplier).trim(),
      cost_basis: String(assumptions.cost_basis).trim(),
      collateral: String(assumptions.collateral).trim(),
      premium_fees: String(assumptions.premium_fees).trim(),
      exercise_assignment_tax: String(assumptions.exercise_assignment_tax).trim(),
      specific_caveats: String(assumptions.specific_caveats).trim(),
    },
  };
}

// Educational Strategy Arithmetic Verification Helpers
export function calculateCoveredCallPayoff(stockCost: number, callStrike: number, callPremium: number) {
  return {
    breakeven: stockCost - callPremium,
    maxprofit: (callStrike - stockCost) + callPremium,
    maxloss: stockCost - callPremium,
  };
}

export function calculateCspPayoff(putStrike: number, putPremium: number, multiplier = 100) {
  return {
    breakeven: putStrike - putPremium,
    maxprofit: putPremium,
    maxloss: putStrike - putPremium,
    collateral: putStrike * multiplier,
  };
}

export function calculateBullCallSpreadPayoff(kLow: number, kHigh: number, netDebit: number) {
  return {
    netDebit,
    breakeven: kLow + netDebit,
    maxprofit: (kHigh - kLow) - netDebit,
    maxloss: netDebit,
  };
}

export function calculateProtectivePutPayoff(stockCost: number, putStrike: number, putPremium: number) {
  return {
    breakeven: stockCost + putPremium,
    maxprofit: "UNBOUNDED" as const,
    maxloss: (stockCost - putStrike) + putPremium,
  };
}
