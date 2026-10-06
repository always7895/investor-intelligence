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

/** ICON1 identity fields compared within one exact venue:symbol key. source_feed and source_url are provenance: a difference in
 * them alone is not a conflict and is never treated as independent corroboration. A missing optional field equals null. */
const IDENTITY_VARIANT_FIELDS = ["native_symbol", "market", "country", "security_name", "native_name", "security_class",
  "currency", "name_zh", "name_zh_source"] as const;
/** Conflict diagnostics show at most this many complete keys; the decision always uses the complete relevant set. */
const IDENTITY_CONFLICT_SHOWN_MAX = 5;

function sameIdentityVariant(left: GlobalIdentityRecord, right: GlobalIdentityRecord): boolean {
  return IDENTITY_VARIANT_FIELDS.every(field => (left[field] ?? null) === (right[field] ?? null));
}

/** Spellings under which the existing indexes list a record: the shard loader's symbol spellings ("VOLV B", "VOLV-B", "VOLV.B")
 * and the legacy reader's upper-case symbol and native symbol. */
function indexedSpellings(record: GlobalIdentityRecord): string[] {
  return [record.symbol, record.native_symbol].map(value => value.toUpperCase())
    .flatMap(value => value.includes(" ") ? [value, value.replace(/ /g, "-"), value.replace(/ /g, ".")] : [value]);
}

/** Request-local venue:symbol groups reachable from one by_symbol entry. Each distinct index symbol is read once and each row is
 * grouped once (a Set skips repeated references): linear in the touched index entries. Only rows the index lists under that
 * exact spelling count; an incomplete or malformed index cannot prove that an unobserved conflict is absent. */
function keyGroupReader(catalog: GlobalIdentityCatalog): (indexSymbol: string) => Map<string, GlobalIdentityRecord[]> {
  const cache = new Map<string, Map<string, GlobalIdentityRecord[]>>();
  return indexSymbol => {
    let groups = cache.get(indexSymbol);
    if (!groups) {
      groups = new Map();
      const seen = new Set<GlobalIdentityRecord>();
      for (const record of safeGetRecordsBySymbol(catalog, indexSymbol)) {
        if (seen.has(record) || !indexedSpellings(record).includes(indexSymbol)) continue;
        seen.add(record);
        const key = `${record.venue}:${record.symbol}`;
        const group = groups.get(key);
        if (group) group.push(record);
        else groups.set(key, [record]);
      }
      cache.set(indexSymbol, groups);
    }
    return groups;
  };
}

/** The relevant keys of a query with ALL their known rows: the seed rows (from the query's own channels) grouped by exact key, each
 * key completed ONCE with its complete same-key group from the canonical symbol index. Members = canonical group (index order)
 * plus every observed seed it lacks, de-duplicated by reference, so a native alias or an incomplete canonical index never hides an
 * already observed contradictory row; unobserved rows are not invented. Linear in the seeds plus the touched index entries. */
function relevantKeyGroups(readGroups: (indexSymbol: string) => Map<string, GlobalIdentityRecord[]>,
  seeds: readonly GlobalIdentityRecord[]): Map<string, GlobalIdentityRecord[]> {
  const observed = new Map<string, GlobalIdentityRecord[]>();
  for (const row of seeds) {
    const key = `${row.venue}:${row.symbol}`;
    const rows = observed.get(key);
    if (rows) rows.push(row);
    else observed.set(key, [row]);
  }
  const result = new Map<string, GlobalIdentityRecord[]>();
  for (const [key, rows] of observed) {
    const members: GlobalIdentityRecord[] = [];
    const seen = new Set<GlobalIdentityRecord>();
    for (const row of [...(readGroups(rows[0]!.symbol.toUpperCase()).get(key) ?? []), ...rows]) {
      if (seen.has(row)) continue;
      seen.add(row);
      members.push(row);
    }
    result.set(key, members);
  }
  return result;
}

/** Whether one key's rows contradict each other (equality is transitive, so comparing with the first row suffices). */
function groupConflicts(group: readonly GlobalIdentityRecord[]): boolean {
  return group.some(record => !sameIdentityVariant(group[0]!, record));
}

/** UNAVAILABLE for contradictory identity rows of the relevant keys: the complete key set decides; only the shown list is capped
 * (deterministic O(K log K) sort of the complete keys, exact shown/total). No candidate is chosen. */
function identityConflict(rawQuery: string, keys: Iterable<string>, attemptedMarket?: SupportedMarket): GlobalIdentityResolution {
  const sorted = [...new Set(keys)].sort();
  const shown = sorted.slice(0, IDENTITY_CONFLICT_SHOWN_MAX);
  return {
    status: "UNAVAILABLE",
    query: rawQuery,
    reason: `IDENTITY_CONFLICT: 本快照對 ${sorted.length} 個掛牌有互相矛盾的身分紀錄（顯示 ${shown.length}/${sorted.length}）：${shown.join("、")}；不選擇任何一筆。`,
    ...(attemptedMarket ? { attemptedMarket } : {}),
  };
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
    // ICON1: seeds = rows indexed under this exact spelling on the scheme's canonical venues; each of their keys is completed with
    // its canonical same-key rows (a native alias may index only one variant). Contradictory rows of any relevant key make the
    // query UNAVAILABLE; conflicts of other venues or symbols do not poison it. Equal variants collapse to the first row.
    const readGroups = keyGroupReader(catalog);
    const seeds = [...readGroups(symbolBody).values()].flat()
      .filter(r => scheme.canonicalVenues.has(r.venue.trim().toUpperCase()));
    const conflictKeys: string[] = [];
    const matchingVenue: GlobalIdentityRecord[] = [];
    for (const [key, group] of relevantKeyGroups(readGroups, seeds)) {
      if (groupConflicts(group)) conflictKeys.push(key);
      else matchingVenue.push(group[0]!);
    }
    if (conflictKeys.length > 0) return identityConflict(rawQuery, conflictKeys, scheme.market);
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

  // ICON1: every candidate row of the existing channels is a seed; each relevant key is completed ONCE with its canonical same-key
  // rows (a name may match only ONE variant) and keeps every observed row even if the canonical index lacks it. Any relevant key
  // with contradictory rows makes the query UNAVAILABLE; no remaining candidate is resolved. Equal variants collapse to the first
  // row. The legacy catalog.conflicts metadata is not evidence and is ignored.
  const candidateGroups = relevantKeyGroups(keyGroupReader(catalog), [...symbolMatches, ...nameMatches]);
  const conflictKeys = [...candidateGroups].filter(([, group]) => groupConflicts(group)).map(([key]) => key);
  if (conflictKeys.length > 0) return identityConflict(rawQuery, conflictKeys);

  const allCandidates = [...candidateGroups.values()].map(group => group[0]!);

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

/* -- OPTIONICON R2 (integrated by INTEG1 with the B2 caller; exercised by the bounded HARN1A-1C harnesses; Vitest NOT_RUN) --
 * Pure read-only helper for a later caller patch: do the rows the existing index already lists for THIS
 * quoted spelling contradict each other inside the US market? null means NO_EVIDENCE_OF_CONFLICT only -
 * never a verified identity, an absence claim, or any rights/publication admission. The input is the
 * matched spelling of an already FOUND quote, never a company name and never a raw user query.
 * Every step reuses the existing helpers (parseIdentityRequest, keyGroupReader, relevantKeyGroups,
 * groupConflicts, identityConflict); none of them is changed here. No all-catalog scan, no by_name read,
 * no preference of a first variant, and the legacy catalog.conflicts metadata is never evidence.
 * R1 F1: the declared type is the full existing union; the discriminant is checked at runtime and an
 * impossible wrong status fails explicitly instead of being masked by an unchecked assertion.
 * R1 F5: one closed ASCII quoted-identity spelling gate (the existing shard alphabet and length, no slash
 * alias) on top of the shared parser's invalid/reserved/company/suffix rejection; explicit prefixes and
 * company prefixes are rejected rather than read as symbols. The diagnostic query stays "ticker <spelling>".
 */
const QUOTED_IDENTITY_SPELLING = /^[A-Za-z0-9][A-Za-z0-9 .-]{0,14}$/;

/** R2 correctes only this helper; the resolver and every existing helper above stay byte-for-byte unchanged. */
export function findUsIdentityConflict(
  catalog: GlobalIdentityCatalog | null,
  symbolSpelling: string,
): GlobalIdentityResolution | null {
  if (!catalog) return null;
  const { parsed, error } = parseIdentityRequest(symbolSpelling);
  if (error || !parsed) return null;
  const { cleanInput, isExplicitPrefix, isCompanyQuery, isCompanyPrefix, suffixHint } = parsed;
  if (suffixHint || isExplicitPrefix || isCompanyQuery || isCompanyPrefix) return null;
  if (!QUOTED_IDENTITY_SPELLING.test(cleanInput)) return null;
  if (DANGEROUS_OBJECT_KEYS.has(cleanInput) || DANGEROUS_OBJECT_KEYS.has(cleanInput.toLowerCase())) return null;
  const indexSymbol = cleanInput.toUpperCase();
  const readGroups = keyGroupReader(catalog);
  const seeds = [...readGroups(indexSymbol).values()].flat();
  if (seeds.length === 0) return null;
  // R1 F2/F3: the whole observed key is completed first, US relevance is decided on the completed group and
  // the decision uses that whole group, so a same-key market contradiction is exactly one key (shown 1/1).
  const relevant = [...relevantKeyGroups(readGroups, seeds)]
    .filter(([, group]) => group.some(row => row.market === "US"));
  const conflictKeys = relevant.filter(([, group]) => groupConflicts(group)).map(([key]) => key);
  if (conflictKeys.length === 0) return null;
  const resolution = identityConflict(`ticker ${symbolSpelling}`, conflictKeys, "US");
  if (resolution.status !== "UNAVAILABLE") {
    throw new Error(`OPTIONICON_R2_UNEXPECTED_STATUS:${resolution.status}`);
  }
  return resolution;
}