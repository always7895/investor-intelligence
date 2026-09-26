/**
 * Authoritative Global Identity Catalog & Resolution Contract (v1).
 *
 * Implements strict, deterministic identity resolution without hardcoded tickers
 * or company name whitelists. Supported regions include US, UK, Sweden, Europe,
 * Japan, Korea, China (SSE/SZSE/BSE), Hong Kong, and Taiwan.
 *
 * Closed resolution union:
 *   - RESOLVED: Single unambiguous identity admitted in the catalog.
 *   - NEEDS_MARKET_SELECTION: Ambiguous query matching multiple venue listings or share classes.
 *   - UNAVAILABLE: Valid format but identity lead not present in admitted catalog.
 *   - INVALID_REQUEST: Confusable Unicode, malformed characters, or reserved bot commands.
 */

import { parseResearchProductRequest } from "./research-product-request";

export type SupportedMarket =
  | "US"
  | "UK"
  | "SWEDEN"
  | "EUROPE"
  | "JAPAN"
  | "KOREA"
  | "CHINA_SHANGHAI"
  | "CHINA_SHENZHEN"
  | "CHINA_BEIJING"
  | "HK"
  | "TAIWAN"
  | "UNKNOWN";

export interface GlobalIdentityRecord {
  venue: string;
  market: SupportedMarket;
  country: string;
  symbol: string;
  native_symbol: string;
  security_name: string;
  native_name?: string | null;
  /** Traditional Chinese name from a stated source (exchange, company, Chinese Wikipedia); null when none exists. */
  name_zh?: string | null;
  name_zh_source?: string | null;
  security_class: string;
  currency: string;
  source_feed: string;
  source_url: string;
}

export interface GlobalIdentityCatalog {
  schema_version: 1;
  contract_id: "v213-global-identity-v1";
  generated_at: string;
  collection_receipts_sha256: string;
  records_count: number;
  indexed_symbols_count?: number;
  indexed_names_count?: number;
  conflicts_count?: number;
  records: GlobalIdentityRecord[];
  indexes: {
    by_venue_and_symbol: Record<string, number>;
    by_symbol: Record<string, number[]>;
    by_name: Record<string, number[]>;
  };
  conflicts?: Record<string, unknown[]>;
}

export type GlobalIdentityResolution =
  | { status: "RESOLVED"; record: GlobalIdentityRecord; candidateCount: 1; query: string }
  | { status: "NEEDS_MARKET_SELECTION"; query: string; candidates: GlobalIdentityRecord[] }
  | { status: "UNAVAILABLE"; query: string; reason: string; attemptedMarket?: SupportedMarket }
  | { status: "INVALID_REQUEST"; query: string; reason: string };

export interface SuffixVenueScheme {
  market: SupportedMarket;
  country: string;
  exchangeName: string;
  canonicalVenues: ReadonlySet<string>;
}

// Known market suffix schemes with exact canonical venue/MIC relations
export const MARKET_SUFFIX_SCHEMES: Record<string, SuffixVenueScheme> = {
  ".TW": {
    market: "TAIWAN",
    country: "Taiwan",
    exchangeName: "臺灣證券交易所（TWSE）",
    canonicalVenues: new Set(["TWSE", "TAIWAN STOCK EXCHANGE", "XTAI"]),
  },
  ".TWO": {
    market: "TAIWAN",
    country: "Taiwan",
    exchangeName: "證券櫃檯買賣中心（TPEx）",
    canonicalVenues: new Set(["TPEX", "TAIPEI EXCHANGE", "ROCO", "OTC"]),
  },
  ".T": {
    market: "JAPAN",
    country: "Japan",
    exchangeName: "東京證券交易所（TSE）",
    canonicalVenues: new Set(["TSE", "TOKYO STOCK EXCHANGE", "XTKS"]),
  },
  ".KS": {
    market: "KOREA",
    country: "Korea",
    exchangeName: "韓國交易所（KRX/KOSPI）",
    canonicalVenues: new Set(["KRX", "KOSPI", "XKRX"]),
  },
  ".KQ": {
    market: "KOREA",
    country: "Korea",
    exchangeName: "韓國交易所（KOSDAQ）",
    canonicalVenues: new Set(["KOSDAQ", "XKOS"]),
  },
  ".HK": {
    market: "HK",
    country: "Hong Kong",
    exchangeName: "香港交易所（HKEX）",
    canonicalVenues: new Set(["HKEX", "HONG KONG STOCK EXCHANGE", "XHKG", "SEHK"]),
  },
  ".SS": {
    market: "CHINA_SHANGHAI",
    country: "China",
    exchangeName: "上海證券交易所（SSE）",
    canonicalVenues: new Set(["SSE", "SHANGHAI STOCK EXCHANGE", "XSHG"]),
  },
  ".SH": {
    market: "CHINA_SHANGHAI",
    country: "China",
    exchangeName: "上海證券交易所（SSE）",
    canonicalVenues: new Set(["SSE", "SHANGHAI STOCK EXCHANGE", "XSHG"]),
  },
  ".SZ": {
    market: "CHINA_SHENZHEN",
    country: "China",
    exchangeName: "深圳證券交易所（SZSE）",
    canonicalVenues: new Set(["SZSE", "SHENZHEN STOCK EXCHANGE", "XSHE"]),
  },
  ".BJ": {
    market: "CHINA_BEIJING",
    country: "China",
    exchangeName: "北京證券交易所（BSE）",
    canonicalVenues: new Set(["BSE", "BEIJING STOCK EXCHANGE", "XBSE"]),
  },
  ".L": {
    market: "UK",
    country: "United Kingdom",
    exchangeName: "倫敦證券交易所（LSE）",
    canonicalVenues: new Set(["LSE", "LONDON STOCK EXCHANGE", "XLON"]),
  },
  ".ST": {
    market: "SWEDEN",
    country: "Sweden",
    exchangeName: "斯德哥爾摩證券交易所（Nasdaq Stockholm）",
    canonicalVenues: new Set(["NASDAQ STOCKHOLM", "STOCKHOLM STOCK EXCHANGE", "XSTO", "STOCKHOLM"]),
  },
  ".AS": {
    market: "EUROPE",
    country: "Netherlands",
    exchangeName: "泛歐交易所阿姆斯特丹（Euronext Amsterdam）",
    canonicalVenues: new Set(["EURONEXT AMSTERDAM", "AMSTERDAM", "XAMS"]),
  },
  ".PA": {
    market: "EUROPE",
    country: "France",
    exchangeName: "泛歐交易所巴黎（Euronext Paris）",
    canonicalVenues: new Set(["EURONEXT PARIS", "PARIS", "XPAR"]),
  },
  ".DE": {
    market: "EUROPE",
    country: "Germany",
    exchangeName: "法蘭克福證券交易所（XETRA）",
    canonicalVenues: new Set(["XETRA", "FRANKFURT", "FRANKFURT STOCK EXCHANGE", "XETR", "FRA"]),
  },
  ".SW": {
    market: "EUROPE",
    country: "Switzerland",
    exchangeName: "瑞士證券交易所（SIX Swiss Exchange）",
    canonicalVenues: new Set(["SIX", "SIX SWISS EXCHANGE", "XSWX"]),
  },
  ".BR": {
    market: "EUROPE",
    country: "Belgium",
    exchangeName: "泛歐交易所布魯塞爾（Euronext Brussels）",
    canonicalVenues: new Set(["EURONEXT BRUSSELS", "BRUSSELS", "XBRU"]),
  },
  ".MI": {
    market: "EUROPE",
    country: "Italy",
    exchangeName: "義大利證券交易所（Borsa Italiana）",
    canonicalVenues: new Set(["BORSA ITALIANA", "MILAN", "XMIL"]),
  },
};

// Reserved bot commands that must NEVER be hijacked as equity lookup
export const RESERVED_BOT_COMMANDS = new Set([
  "TOP20", "TOP10", "TOP5", "TOP", "HELP", "STATUS", "HEALTH",
  "MENU", "OPTIONS", "PORTFOLIO", "RANKING", "SOURCES", "SETTINGS",
  "早報", "早报", "晚報", "晚报", "最新報告", "今日報告", "今日报告", "盤前報告", "盘前报告",
  "宏觀", "宏观", "宏觀產業", "宏观产业", "宏觀產業分析", "宏观产业分析", "TOP5產業總覽", "當輪產業分布", "当轮产业分布", "宏觀資料說明", "宏观资料说明",
  "期權", "期权", "選擇權", "选择权", "期權與個股快查", "期权与个股快查", "最新期權", "最新期权", "期權教學", "期权教学", "期權試算說明", "期权试算说明",
  "選單", "菜单", "幫助", "帮助", "說明", "说明", "健康", "狀態", "状态", "功能", "功能導覽",
  "記憶狀態", "记忆状态", "開啟記憶", "开启记忆", "關閉記憶", "关闭记忆", "清除本次對話", "清除本次对话", "清除對話", "清除对话", "刪除我的資料", "删除我的资料",
  "查看結果", "查看结果",
]);

export const AMBIGUOUS_MACRO_TOKENS = new Set([
  "GDP", "CPI", "PPI", "PMI", "FOMC", "FED", "ECB", "BOJ", "BOE",
  "IMF", "OECD", "OPEC", "EIA", "IEA", "DXY", "VIX", "USD", "EUR", "CNY", "TWD",
]);

const DANGEROUS_OBJECT_KEYS = new Set([
  "__proto__", "constructor", "prototype", "toString", "valueOf", "hasOwnProperty", "isPrototypeOf",
]);

/** Normalize company name for exact lowercase index lookup */
export function normalizeCompanyName(name: string): string {
  return name.trim().toLowerCase().replace(/\s+/g, " ");
}

/** Check for full-width confusable Unicode characters (e.g. ＡＡＯＩ) */
function containsConfusableUnicode(text: string): boolean {
  for (let i = 0; i < text.length; i++) {
    const code = text.charCodeAt(i);
    // Full-width ASCII variants U+FF01 to U+FF5E
    if (code >= 0xff01 && code <= 0xff5e) return true;
  }
  return false;
}

export interface ParsedIdentityRequest {
  cleanInput: string;
  isExplicitPrefix: boolean;
  isCompanyQuery: boolean;
  isTickerPrefix: boolean;
  isCompanyPrefix: boolean;
  suffixHint?: {
    rawSuffix: string;
    scheme: SuffixVenueScheme;
    symbolBody: string;
  };
  isBareTickerCandidate: boolean;
  isNumericTicker: boolean;
}

/**
 * Parses raw text query into structured identity request syntax.
 * Rejects confusable Unicode and reserved commands fail-closed.
 */
export function parseIdentityRequest(text: string): { parsed?: ParsedIdentityRequest; error?: string } {
  if (!text || typeof text !== "string") {
    return { error: "INVALID_EMPTY_REQUEST" };
  }
  const raw = text.trim();
  if (!raw) return { error: "INVALID_EMPTY_REQUEST" };
  if (raw.length > 100) return { error: "QUERY_TOO_LONG" };

  if (/<[^>]+>|javascript:|https?:\/\//i.test(raw)) {
    return { error: "INVALID_CHARACTERS" };
  }

  // Reject full-width confusable unicode before any normalization
  if (containsConfusableUnicode(raw)) {
    return { error: "CONFUSABLE_UNICODE_TICKER_REJECTED" };
  }

  const upper = raw.toUpperCase();
  if (
    RESERVED_BOT_COMMANDS.has(upper) ||
    RESERVED_BOT_COMMANDS.has(raw) ||
    /^TOP\s*\d*/i.test(raw)
  ) {
    return { error: "RESERVED_BOT_COMMAND" };
  }
  if (AMBIGUOUS_MACRO_TOKENS.has(upper)) {
    return { error: "AMBIGUOUS_MACRO_TERM" };
  }

  // Result retrieval pattern (查看結果 <id>)
  if (/^(?:查看結果|查看结果|result)\s+[A-Za-z0-9]+/i.test(raw)) {
    return { error: "RESERVED_JOB_RESULT" };
  }

  // Research product requests must not be hijacked as equity lookup
  if (parseResearchProductRequest(raw)) {
    return { error: "RESEARCH_PRODUCT_REQUEST" };
  }

  // Check explicit query prefixes e.g. "股票 AAPL", "個股 2330.TW", "查股價 0700.HK", "公司 台積電"
  const prefixMatch = /^(?:(股票|個股|查股價|查詢股價|stock|ticker)|(公司))\s*[:：]?\s*(.+)$/i.exec(raw);
  const isExplicitPrefix = prefixMatch !== null;
  const isTickerPrefix = Boolean(prefixMatch && prefixMatch[1]);
  const isCompanyPrefix = Boolean(prefixMatch && prefixMatch[2]);
  const cleanInput = (prefixMatch ? prefixMatch[3]!.trim() : raw).trim();
  const cleanUpper = cleanInput.toUpperCase();

  if (!cleanInput) return { error: "INVALID_EMPTY_REQUEST" };
  if (RESERVED_BOT_COMMANDS.has(cleanUpper) || AMBIGUOUS_MACRO_TOKENS.has(cleanUpper)) {
    return { error: "RESERVED_BOT_COMMAND" };
  }

  // Check suffix hints
  let suffixHint: ParsedIdentityRequest["suffixHint"] = undefined;
  for (const [suffix, scheme] of Object.entries(MARKET_SUFFIX_SCHEMES)) {
    if (cleanUpper.endsWith(suffix)) {
      const symbolBody = cleanInput.slice(0, -suffix.length).trim().toUpperCase();
      if (/^[A-Za-z0-9.-]{1,10}$/.test(symbolBody)) {
        suffixHint = { rawSuffix: suffix, scheme, symbolBody };
        break;
      }
    }
  }

  const hasCompanyMarker =
    /(?:\b(?:inc|corp|corporation|ltd|limited|co|company|holdings?|semiconductors?)\b|股份有限公司|有限公司)/i.test(cleanInput) &&
    !/[?？]|(?:為什麼|如何|什麼是|怎么|為何|explain|what|why|how|影響|看法|分析|建議)/i.test(cleanInput);
  const isNumericTicker = /^\d{4,6}$/.test(cleanInput);
  const isBareTickerCandidate = !suffixHint && /^[A-Za-z]{1,6}(?:\.[A-Za-z]{1,2})?$/.test(cleanInput);
  const isCompanyQuery = isCompanyPrefix || hasCompanyMarker || (isExplicitPrefix && !isBareTickerCandidate && !isNumericTicker && !suffixHint);

  return {
    parsed: {
      cleanInput,
      isExplicitPrefix,
      isCompanyQuery,
      isTickerPrefix,
      isCompanyPrefix,
      suffixHint,
      isBareTickerCandidate,
      isNumericTicker,
    },
  };
}

function safeGetRecordsBySymbol(catalog: GlobalIdentityCatalog, sym: string): GlobalIdentityRecord[] {
  if (DANGEROUS_OBJECT_KEYS.has(sym)) return [];
  const bySymbol = catalog.indexes.by_symbol;
  if (!bySymbol || !Object.hasOwn(bySymbol, sym)) return [];
  const entries = bySymbol[sym];
  if (!Array.isArray(entries)) return [];
  const result: GlobalIdentityRecord[] = [];
  for (const item of entries) {
    if (typeof item === "number" && Number.isInteger(item) && item >= 0 && item < catalog.records.length) {
      result.push(catalog.records[item]!);
    }
  }
  return result;
}

function safeGetRecordsByName(catalog: GlobalIdentityCatalog, normName: string): GlobalIdentityRecord[] {
  if (DANGEROUS_OBJECT_KEYS.has(normName)) return [];
  const byName = catalog.indexes.by_name;
  if (!byName || !Object.hasOwn(byName, normName)) return [];
  const entries = byName[normName];
  if (!Array.isArray(entries)) return [];
  const result: GlobalIdentityRecord[] = [];
  for (const item of entries) {
    if (typeof item === "number" && Number.isInteger(item) && item >= 0 && item < catalog.records.length) {
      result.push(catalog.records[item]!);
    }
  }
  return result;
}

/**
 * Strictly resolves identity query against the admitted Global Identity Catalog.
 *
 * Generic resolution algorithm without symbol or company hardcoding.
 * Matches ALL applicable exact candidates across symbol and name channels,
 * deduplicates by canonical identity key, and unions candidate leads.
 */
export function resolveGlobalIdentity(
  catalog: GlobalIdentityCatalog | null,
  rawQuery: string,
): GlobalIdentityResolution {
  const { parsed, error } = parseIdentityRequest(rawQuery);
  if (error || !parsed) {
    return { status: "INVALID_REQUEST", query: rawQuery, reason: error ?? "INVALID_REQUEST" };
  }

  const {
    cleanInput,
    isExplicitPrefix,
    isCompanyQuery,
    isTickerPrefix,
    isCompanyPrefix,
    suffixHint,
    isBareTickerCandidate,
    isNumericTicker,
  } = parsed;

  // Guard dangerous prototype properties directly
  if (DANGEROUS_OBJECT_KEYS.has(cleanInput) || DANGEROUS_OBJECT_KEYS.has(cleanInput.toLowerCase())) {
    return {
      status: "UNAVAILABLE",
      query: rawQuery,
      reason: `IDENTIFIER_UNAVAILABLE: 查詢字串「${cleanInput}」為保留屬性名稱，無已封存證券身分紀錄。`,
    };
  }

  // If no catalog is present (publisher migration deferred), report honest UNAVAILABLE
  if (!catalog) {
    return {
      status: "UNAVAILABLE",
      query: rawQuery,
      reason: "IDENTITY_CATALOG_UNAVAILABLE: 目前公開快照未封存全球身分目錄（publisher migration deferred）。",
      attemptedMarket: suffixHint?.scheme.market,
    };
  }

  // 1. Suffixed Query (e.g. 2330.TW, 7203.T, 0700.HK, SIVE.ST, IQE.L, ASML.AS)
  if (suffixHint) {
    const { symbolBody, scheme } = suffixHint;
    const records = safeGetRecordsBySymbol(catalog, symbolBody);
    // Filter records matching the exact canonical venues of the suffix scheme
    const matchingVenue = records.filter(r =>
      scheme.canonicalVenues.has(r.venue.trim().toUpperCase()),
    );
    if (matchingVenue.length === 1) {
      return { status: "RESOLVED", record: matchingVenue[0]!, candidateCount: 1, query: rawQuery };
    }
    if (matchingVenue.length > 1) {
      return { status: "NEEDS_MARKET_SELECTION", query: rawQuery, candidates: matchingVenue };
    }
    // If not found in catalog for that venue
    return {
      status: "UNAVAILABLE",
      query: rawQuery,
      reason: `SOURCE_UNAVAILABLE: 代號 ${cleanInput} 在指定市場（${scheme.country} / ${scheme.exchangeName}）無已封存之公開證券身分紀錄。`,
      attemptedMarket: scheme.market,
    };
  }

  // 2. Bare or Explicit Operator Query (Symbol vs Name match)
  // Match ALL applicable exact candidates, canonical identity dedup, then 0/1/many union
  let symbolMatches: GlobalIdentityRecord[] = [];
  let nameMatches: GlobalIdentityRecord[] = [];

  const allowSymbol = !isCompanyPrefix;
  const allowName = !isTickerPrefix;

  if (allowSymbol && (isBareTickerCandidate || isNumericTicker || isExplicitPrefix)) {
    symbolMatches = safeGetRecordsBySymbol(catalog, cleanInput.toUpperCase());
  }

  if (allowName) {
    nameMatches = safeGetRecordsByName(catalog, normalizeCompanyName(cleanInput));
  }

  // Combine and deduplicate candidates by unique canonical identity key: `${venue}:${symbol}`
  const candidateMap = new Map<string, GlobalIdentityRecord>();
  const conflictedKeys = new Set<string>();

  for (const c of [...symbolMatches, ...nameMatches]) {
    const key = `${c.venue}:${c.symbol}`;
    const existing = candidateMap.get(key);
    if (existing) {
      if (
        existing.security_name !== c.security_name ||
        existing.security_class !== c.security_class ||
        existing.country !== c.country ||
        existing.currency !== c.currency
      ) {
        conflictedKeys.add(key);
      }
    } else {
      candidateMap.set(key, c);
    }
  }

  for (const key of conflictedKeys) {
    candidateMap.delete(key);
  }

  const allCandidates = Array.from(candidateMap.values());

  if (allCandidates.length === 1) {
    return { status: "RESOLVED", record: allCandidates[0]!, candidateCount: 1, query: rawQuery };
  }
  if (allCandidates.length > 1) {
    return { status: "NEEDS_MARKET_SELECTION", query: rawQuery, candidates: allCandidates };
  }

  // 0 matches -> UNAVAILABLE
  return {
    status: "UNAVAILABLE",
    query: rawQuery,
    reason: isCompanyPrefix || isCompanyQuery
      ? `COMPANY_NAME_UNAVAILABLE: 公司名稱「${cleanInput}」未在已封存公開身分目錄中找到精確符合項目。`
      : `IDENTIFIER_UNAVAILABLE: 代號「${cleanInput.toUpperCase()}」目前未在已封存公開身分目錄中。`,
  };
}
