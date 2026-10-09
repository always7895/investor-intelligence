import { adrRoute, marketHasOptions } from "./option-routes";
import { assertLineMessages, type LineOutboundMessage } from "../line-messages";
import { LINE_THEME as T, menuAction, menuBox, menuText, headerStyle } from "./line-theme";
import { pinPublicSnapshot, type PublicSnapshotView } from "./public-snapshot";
import type { V213Top20Env } from "./top20-report";
import type { ParsedQuery } from "../core";
import {
  type GlobalIdentityCatalog,
  type GlobalIdentityRecord,
  type GlobalIdentityResolution,
  type SupportedMarket,
  MARKET_SUFFIX_SCHEMES,
  parseIdentityRequest,
  resolveGlobalIdentity,
  RESERVED_BOT_COMMANDS,
  AMBIGUOUS_MACRO_TOKENS,
} from "./global-identity";
import {
  loadGlobalIdentityCatalog,
  evaluateCatalogAdmission,
} from "./global-identity-reader";
import { loadIdentityCatalogForQuery } from "./identity-shards";
import { loadDelayedQuote, loadListingPrice, observationSymbol, PRICE_SOURCE_LABEL } from "./market-observations";
import { sourceZh } from "./source-labels";

export type { SupportedMarket, GlobalIdentityRecord, GlobalIdentityResolution };

export interface ResolvedEquityIdentity {
  rawInput: string;
  normalizedSymbol: string;
  canonicalSymbol: string;
  market: SupportedMarket;
  country: string;
  exchange: string;
  currency: string;
  canonicalNameZh?: string;
  /** Where the Chinese name is stated (TWSE, TPEX, OFFICIAL, ZHWIKI, WIKIDATA_LABEL). */
  nameZhSource?: string;
  canonicalNameEn?: string;
  isAmbiguous: boolean;
  ambiguityCandidates?: string[];
  leadingZeroPreserved: boolean;
  shareClass?: string;
  isCompanyQuery?: boolean;
  suffixHint?: boolean;
}

const ZH_SOURCE_LABEL: Record<string, string> = {
  TWSE: "臺灣證交所", TPEX: "櫃買中心", OFFICIAL: "公司官方", ZHWIKI: "中文維基百科", WIKIDATA_LABEL: "維基數據",
};

/** US identity rows that scripts/build_identity_shards.py builds from the local SEC raw cache when a Nasdaq Trader directory
 * failed. Recognised ONLY from an actual RESOLVED US record whose source_feed is exactly this id (case-sensitive), never from
 * result.source text, a quote, REVIEW_REQUIRED, a name or a feed prefix. It changes display only: not the resolution, the
 * admission, the quotes or the option actions. */
const SEC_CACHE_FALLBACK_FEED = "sec-company-tickers-exchange";
const SEC_FALLBACK_NOTICE = "身分備援：SEC 本機快取僅部分涵蓋 Nasdaq／NYSE；掛牌狀態與證券類別未經交易所名錄核實。檔案時間不等於已驗證取得時間；若顯示期權按鈕，僅供查詢，不代表期權資格或可成交。";
const SEC_FALLBACK_QUOTE_DISCLAIMER = "公開研究資訊，非投資建議；身分採 SEC 公司代號名錄之本機快取備援（部分涵蓋，未經交易所名錄核實），報價為延遲觀察值，不下單。";
const SEC_FALLBACK_NO_QUOTE_DISCLAIMER = "公開研究資訊，非投資建議；身分採 SEC 公司代號名錄之本機快取備援（部分涵蓋，未經交易所名錄核實），本標的暫無延遲報價觀察。";
const SEC_FALLBACK_UNAVAILABLE_SUB = "IDENTITY_FALLBACK_SEC_CACHE：本筆採 SEC 公司代號名錄之本機快取備援；部分涵蓋，非即時交易所核實；暫無已封存延遲報價。";
const SEC_FALLBACK_NAME_ZH = "未有已核對中文名稱（SEC 快取備援，不猜譯）";

function isSecCacheFallback(resolution: GlobalIdentityResolution | undefined): boolean {
  return resolution?.status === "RESOLVED" && resolution.record.market === "US" && resolution.record.source_feed === SEC_CACHE_FALLBACK_FEED;
}

/** ISEL1 (ambiguous identity safe selection). A NEEDS_MARKET_SELECTION card lists its candidates; a candidate becomes a button only
 * when its ONE exact suffixed query (its own symbol plus the first existing MARKET_SUFFIX_SCHEMES suffix whose canonical venues
 * contain its venue) resolved, on the SAME pinned snapshot view through the existing query-specific loader and resolver, to a record
 * whose identity and provenance fields equal the candidate's. Every other candidate is display-only with its reason; nothing is
 * split from a display line or guessed (no US suffix, alias, space, case or zero rewrite), and a button is resolved afresh on the
 * next request's own snapshot (no promise across snapshots; not a quote, option or trading qualification). */
export type CandidateRouteStatus = "CERTIFIED" | "NO_SUFFIX_ROUTE" | "NOT_CERTIFIED" | "UNCHECKED";
export interface CandidateQueryRoute {
  /** The candidate line exactly as shown in identity.ambiguityCandidates. */
  display: string;
  status: CandidateRouteStatus;
  /** The exact suffixed query; present only when CERTIFIED. */
  query?: string;
}

/** Validation calls per ambiguous response (failures included; sequential; no retries). A suffixed query loads no name shard, and
 * each existing loader call reads at most the symbol bucket and the fallback bucket A: at most six symbol-object reads. */
const CANDIDATE_VALIDATION_LIMIT = 3;
/** This module's own 20-character button-label bound (assertLineMessages does not check action labels). */
const CANDIDATE_LABEL_MAX = 20;
/** Display bound of an ambiguous card (a reviewed presentation decision, not a filter or coverage rule): a deterministic prefix of
 * complete candidate lines, at most ten lines and at most 3000 UTF-16 code units joined, fitted to the room left under
 * CANDIDATE_TEXT_MAX. Text and Flex show the same prefix. */
const CANDIDATE_DISPLAY_MAX_LINES = 10;
const CANDIDATE_DISPLAY_MAX_UNITS = 3000;
/** This project's conservative text bound checked by assertLineMessages (cloud/src/line-messages.ts); not an official LINE limit. */
const CANDIDATE_TEXT_MAX = 4900;
const CANDIDATE_LIST_TITLE = "可選候選代號：";
const CANDIDATE_IDENTITY_FIELDS = ["venue", "market", "country", "symbol", "native_symbol", "security_name", "security_class",
  "currency", "source_feed", "source_url"] as const;
const CANDIDATE_OPTIONAL_FIELDS = ["native_name", "name_zh", "name_zh_source"] as const;
const CANDIDATE_ROUTE_REASON: Record<Exclude<CandidateRouteStatus, "CERTIFIED">, string> = {
  NO_SUFFIX_ROUTE: "無可用的市場後綴查詢，僅供辨識",
  NOT_CERTIFIED: "後綴查詢未能確認唯一對應本筆，僅供辨識",
  UNCHECKED: "本次未驗證（每次最多驗證 3 筆），不代表不支援或不存在",
};
const CANDIDATE_ROUTE_FOOTNOTE = "按鈕只送出本次快照驗證過的市場代號；下次查詢依當時快照重新解析，不保證結果相同，也不代表報價、期權資格或可交易。";
const CANDIDATE_DISPLAY_ONLY_NOTE = "候選僅供辨識：未經查詢路徑驗證，不提供候選按鈕。";

/** The candidate's one exact suffixed query, or null: no existing suffix for its venue, or text the parser would not read back
 * as exactly this symbol and suffix. Only the first matching scheme is tried, so aliases (.SS/.SH) never duplicate. */
function candidateSuffixQuery(candidate: GlobalIdentityRecord): string | null {
  const venue = candidate.venue.trim().toUpperCase();
  for (const [suffix, scheme] of Object.entries(MARKET_SUFFIX_SCHEMES)) {
    if (!scheme.canonicalVenues.has(venue)) continue;
    const query = `${candidate.symbol}${suffix}`;
    if (!/^[A-Z0-9.-]+$/.test(query) || `查詢 ${query}`.length > CANDIDATE_LABEL_MAX) return null;
    const { parsed, error } = parseIdentityRequest(query);
    const hint = parsed?.suffixHint;
    return !error && parsed && parsed.cleanInput === query && hint && hint.rawSuffix === suffix && hint.symbolBody === candidate.symbol
      ? query : null;
  }
  return null;
}

/** Same identity and provenance across freshly loaded record objects: every required field strictly equal, and each optional field
 * strictly equal whenever either record defines it (a present null never equals a missing field). */
function sameCandidateIdentity(left: GlobalIdentityRecord, right: GlobalIdentityRecord): boolean {
  if (CANDIDATE_IDENTITY_FIELDS.some(field => left[field] !== right[field])) return false;
  return CANDIDATE_OPTIONAL_FIELDS.every(field => {
    const inLeft = Object.hasOwn(left, field);
    const inRight = Object.hasOwn(right, field);
    return (!inLeft && !inRight) || (inLeft && inRight && left[field] === right[field]);
  });
}

function candidateRouteLine(route: CandidateQueryRoute): string {
  return route.status === "CERTIFIED"
    ? `${route.display} → 可查詢「${route.query}」`
    : `${route.display} → ${CANDIDATE_ROUTE_REASON[route.status]}`;
}

/** The honest omission notice: counts only; omitted candidates are not called absent, unsupported or validated. */
function candidateOmissionNote(shown: number, total: number): string {
  return `已顯示 ${shown}/${total} 筆候選；其餘候選未顯示（不代表不存在、不支援或已驗證），請改用更精確的名稱或含市場後綴的代號查詢。`;
}

/** How many complete lines, from the start, fit in CANDIDATE_DISPLAY_MAX_LINES and `unitBudget` UTF-16 code units joined with "\n";
 * a line is never cut, and the first line that does not fit ends the prefix (zero when even the first line is too long). */
function candidateDisplayPrefix(lines: readonly string[], unitBudget: number): number {
  let count = 0;
  let units = 0;
  for (const line of lines) {
    const next = units + (count > 0 ? 1 : 0) + line.length;
    if (count >= CANDIDATE_DISPLAY_MAX_LINES || next > unitBudget) break;
    units = next;
    count += 1;
  }
  return count;
}

export interface EquityLookupResult {
  identity: ResolvedEquityIdentity;
  admittedInSealedSnapshot: boolean;
  nameUnverified: boolean;
  quoteStatus: "AVAILABLE" | "UNAVAILABLE" | "AMBIGUOUS";
  price?: number;
  changePct?: number;
  asOf?: string;
  /** Where the shown price comes from (Chinese label) and a second, independent observation of the same listing. */
  priceSource?: string;
  crossCheck?: { price: number; source: string; asOf: string; diffPct: number | null };
  source: string;
  disclaimer: string;
  resolution?: GlobalIdentityResolution;
  /** ISEL1: per-candidate query routes, set by the handler for a NEEDS_MARKET_SELECTION result (see trustedCandidateRoutes). */
  candidateRoutes?: readonly CandidateQueryRoute[];
  /** ABS1: internal presentation context, set ONLY by handleGlobalEquityLookup for its UNAVAILABLE result: whether that handler had a
   * runtime-admitted query catalog (CATALOG_PRESENT; not complete coverage) or none (CATALOG_UNAVAILABLE). It is not origin or
   * authentication proof and grants no admission; results without it (direct or legacy callers) are shown unchanged. */
  unavailableIdentityScope?: UnavailableIdentityScope;
}

/** ABS1 (honest absence notice). An identity the real handler could not confirm is never presented as proof that the security does
 * not exist, was delisted or lacks options or trading rights, and no cause is stated for it. */
export type UnavailableIdentityScope = "CATALOG_PRESENT" | "CATALOG_UNAVAILABLE";
const IDENTITY_SCOPE_NOTICE = "範圍提醒：本次查詢未能確認此標的身分；可用的封存資料可能不完整或不可用，原因不明。這不代表該證券不存在、已下市、沒有期權或不具交易權利。";
const CATALOG_UNAVAILABLE_PREFIX = "IDENTITY_CATALOG_UNAVAILABLE:";
const CATALOG_UNAVAILABLE_BODY = "本次查詢未取得可用的封存身分目錄；無法由此判定具體原因。";

/** The shown status line of an UNAVAILABLE resolution. Only a recognized ABS1 context adds the scope notice and, for the exact
 * IDENTITY_CATALOG_UNAVAILABLE prefix, the neutral body instead of the resolver's stated cause; every other reason keeps its text
 * and machine prefix, and the resolution object itself is never changed. */
function unavailableStatusSub(scope: unknown, reason: string): string {
  if (scope !== "CATALOG_PRESENT" && scope !== "CATALOG_UNAVAILABLE") return `QUOTE_UNAVAILABLE：${reason}`;
  const shown = scope === "CATALOG_UNAVAILABLE" && reason.startsWith(CATALOG_UNAVAILABLE_PREFIX)
    ? `${CATALOG_UNAVAILABLE_PREFIX} ${CATALOG_UNAVAILABLE_BODY}` : reason;
  return `QUOTE_UNAVAILABLE：${shown}\n${IDENTITY_SCOPE_NOTICE}`;
}

/** ICON1: the resolver's UNAVAILABLE for contradictory sealed identity rows (reason prefix IDENTITY_CONFLICT:). Only the real
 * handler's result with its catalog context gets this card; the cause is known, so ABS1's cause-unknown notice is not used. */
const IDENTITY_CONFLICT_PREFIX = "IDENTITY_CONFLICT:";
const IDENTITY_CONFLICT_TITLE = "身分資料衝突 · 暫不解析";
const IDENTITY_CONFLICT_NOTICE = "同一掛牌在本快照有互相矛盾的身分紀錄，故不選擇任何一筆；這不代表該證券不存在、已下市、沒有期權或不具交易權利，也不代表哪一筆來源有誤。";

function isIdentityConflictCard(scope: unknown, reason: string): boolean {
  return scope === "CATALOG_PRESENT" && reason.startsWith(IDENTITY_CONFLICT_PREFIX);
}

/** ISEL1 handler step, per candidate in resolver order. One validation call is spent BEFORE each await (failures included), at most
 * CANDIDATE_VALIDATION_LIMIT, sequentially and without retries; a duplicate exact query reuses its in-response outcome. A loader
 * null (no sealed identity shard), a read exception, a non-RESOLVED outcome or a different identity leaves the candidate
 * display-only: there is NO legacy-catalog fallback and the original (possibly name-subset) catalog is never reused. */
async function certifyCandidateRoutes(view: PublicSnapshotView, candidates: readonly GlobalIdentityRecord[],
  displays: readonly string[]): Promise<CandidateQueryRoute[]> {
  const outcomes = new Map<string, GlobalIdentityResolution | null>();
  const routes: CandidateQueryRoute[] = [];
  let attempts = 0;
  for (let index = 0; index < candidates.length; index += 1) {
    const candidate = candidates[index]!;
    const display = displays[index]!;
    const query = candidateSuffixQuery(candidate);
    if (query === null) {
      routes.push({ display, status: "NO_SUFFIX_ROUTE" });
      continue;
    }
    if (!outcomes.has(query)) {
      if (attempts >= CANDIDATE_VALIDATION_LIMIT) {
        routes.push({ display, status: "UNCHECKED" });
        continue;
      }
      attempts += 1;
      let fresh: GlobalIdentityResolution | null = null;
      try {
        const catalog = await loadIdentityCatalogForQuery(view, query);
        fresh = catalog ? resolveGlobalIdentity(catalog, query) : null;
      } catch {
        fresh = null;
      }
      outcomes.set(query, fresh);
    }
    const outcome = outcomes.get(query);
    routes.push(outcome?.status === "RESOLVED" && sameCandidateIdentity(outcome.record, candidate)
      ? { display, status: "CERTIFIED", query }
      : { display, status: "NOT_CERTIFIED" });
  }
  return routes;
}

/** The routes when they are consistent with this result: one route per shown candidate with the same display line, the same count
 * as resolution.candidates, a known status, each CERTIFIED query equal to the candidate's own suffixed query recomputed here and no
 * query on any other status; otherwise null, and the ambiguous result stays display-only. This is an internal SHAPE AND QUERY
 * CONSISTENCY check, not authentication of origin: the real handler produces the routes, and a self-consistent result object built
 * inside the Worker would pass it. */
function trustedCandidateRoutes(result: EquityLookupResult): readonly CandidateQueryRoute[] | null {
  const routes = result.candidateRoutes;
  const shown = result.identity.ambiguityCandidates;
  const resolution = result.resolution;
  if (!routes || !shown || resolution?.status !== "NEEDS_MARKET_SELECTION" || routes.length !== shown.length
    || routes.length !== resolution.candidates.length) return null;
  const candidates = resolution.candidates;
  const consistent = routes.every((route, index) => route.display === shown[index]
    && (route.status === "CERTIFIED"
      ? route.query !== undefined && route.query === candidateSuffixQuery(candidates[index]!)
      : Object.hasOwn(CANDIDATE_ROUTE_REASON, route.status) && route.query === undefined));
  return consistent ? routes : null;
}

type ObservedQuote = { price: number; change_pct: number | null; currency: string | null; asof: string; source: string; source_url: string };

/** The two display labels of the SAME Yahoo Finance provider on the quote paths: the daily-close price shard that serves the
 * Japan and Korea listings (market-observations.PRICE_SOURCE_LABEL["yahoo-daily-close"], returned by loadListingPrice) and the
 * hourly delayed quote (scripts/build_market_quotes_options.py writes "Yahoo Finance (unofficial, delayed)", which sourceZh maps).
 * A CLOSED list of known labels, not a hostname, URL, substring or brand rule. */
const YAHOO_QUOTE_LABELS: ReadonlySet<string> = new Set([PRICE_SOURCE_LABEL["yahoo-daily-close"]!, sourceZh("Yahoo Finance (unofficial, delayed)")]);

/** Operator 2026-09-26 (a lookup showed Yahoo only): the listing's price shard leads (an exchange feed, or for Japan and Korea a
 * Yahoo daily close); a second observation from a DIFFERENT provider is shown beside it, with the difference only when both are in
 * the same currency. Not a second observation: an equal display label, or two known labels of the same Yahoo provider. The
 * comparison is metadata only (labels), not proof of independent retrieval, price discovery or authenticity. */
export function combineQuotes(official: ObservedQuote | null, observed: ObservedQuote | null):
  { primary: ObservedQuote | null; crossCheck?: { price: number; source: string; asOf: string; diffPct: number | null } } {
  const primary = official ?? observed;
  if (!official || !observed) return { primary };
  const officialLabel = sourceZh(official.source);
  const observedLabel = sourceZh(observed.source);
  // One source, not two: an equal display label (as before) or two known labels of the same Yahoo provider.
  if (officialLabel === observedLabel || (YAHOO_QUOTE_LABELS.has(officialLabel) && YAHOO_QUOTE_LABELS.has(observedLabel))) return { primary };
  const sameCurrency = (official.currency ?? "").toUpperCase() === (observed.currency ?? "").toUpperCase() && !!official.currency;
  const diffPct = sameCurrency && official.price > 0 ? observed.price / official.price - 1 : null;
  return { primary, crossCheck: { price: observed.price, source: observed.source, asOf: observed.asof, diffPct } };
}

/**
 * Compatibility helper to parse an equity query into a ResolvedEquityIdentity
 * structure if it meets syntax criteria.
 */
export function parseGlobalEquityQuery(text: string): ResolvedEquityIdentity | null {
  const { parsed, error } = parseIdentityRequest(text);
  if (error || !parsed) return null;

  const { cleanInput, suffixHint, isNumericTicker, isBareTickerCandidate, isCompanyQuery, isExplicitPrefix } = parsed;

  // Compatibility: if no explicit prefix and contains Chinese characters or whitespace, return null
  if (!isExplicitPrefix && (/[\u4e00-\u9fa5]/.test(cleanInput) || /\s/.test(cleanInput))) {
    return null;
  }

  if (suffixHint) {
    const { rawSuffix, scheme, symbolBody } = suffixHint;
    const leadingZero = /^0/.test(symbolBody);
    return {
      rawInput: text,
      normalizedSymbol: cleanInput.toUpperCase(),
      canonicalSymbol: cleanInput.toUpperCase(),
      market: scheme.market,
      country: scheme.country,
      exchange: scheme.exchangeName,
      currency: "UNAVAILABLE",
      isAmbiguous: false,
      leadingZeroPreserved: leadingZero,
      suffixHint: true,
    };
  }

  if (isNumericTicker) {
    const leadingZero = /^0/.test(cleanInput);
    return {
      rawInput: text,
      normalizedSymbol: cleanInput,
      canonicalSymbol: cleanInput,
      market: "UNKNOWN",
      country: "未指定",
      exchange: "未指定市場（需輸入後綴如 .TW、.T、.KS、.HK 等）",
      currency: "UNAVAILABLE",
      isAmbiguous: false,
      leadingZeroPreserved: leadingZero,
    };
  }

  if (isBareTickerCandidate) {
    const upper = cleanInput.toUpperCase();
    const shareClass = upper.includes(".") ? upper.split(".")[1] : undefined;
    return {
      rawInput: text,
      normalizedSymbol: upper,
      canonicalSymbol: upper,
      market: "UNKNOWN",
      country: "未指定",
      exchange: "未指定市場（需輸入後綴或待准入來源確認）",
      currency: "UNAVAILABLE",
      isAmbiguous: false,
      leadingZeroPreserved: false,
      shareClass,
    };
  }

  if (isCompanyQuery || parsed.isExplicitPrefix) {
    return {
      rawInput: text,
      normalizedSymbol: cleanInput,
      canonicalSymbol: cleanInput,
      market: "UNKNOWN",
      country: "未指定",
      exchange: "公司名稱查詢（待公開快照核對）",
      currency: "UNAVAILABLE",
      isAmbiguous: false,
      leadingZeroPreserved: /^0/.test(cleanInput),
      isCompanyQuery: true,
    };
  }

  return null;
}

export function buildGlobalEquityLookupMessages(
  result: EquityLookupResult,
  presentation: "flex" | "text" = "flex",
): LineOutboundMessage[] {
  const { identity, quoteStatus, resolution } = result;
  // A RESOLVED US record from the SEC local-cache fallback gets its own title, notice and disclaimer (display only).
  const secFallback = isSecCacheFallback(resolution);
  const secQuote = secFallback && quoteStatus === "AVAILABLE" && typeof result.price === "number";
  const disclaimerShown = secFallback ? (secQuote ? SEC_FALLBACK_QUOTE_DISCLAIMER : SEC_FALLBACK_NO_QUOTE_DISCLAIMER) : result.disclaimer;
  // ISEL1: the candidate lines of an ambiguous card. Consistent routes add the exact query or an honest display-only reason;
  // without them (a direct or legacy result) the candidates are display-only. Non-ambiguous results never enter this path.
  const shownCandidates = identity.isAmbiguous && identity.ambiguityCandidates && identity.ambiguityCandidates.length > 0
    ? identity.ambiguityCandidates : null;
  const routes = shownCandidates ? trustedCandidateRoutes(result) : null;
  const allCandidateLines = routes ? routes.map(candidateRouteLine) : (shownCandidates ?? []);
  const candidateNote = routes ? CANDIDATE_ROUTE_FOOTNOTE : CANDIDATE_DISPLAY_ONLY_NOTE;

  const headerTitle = `個股快查 · ${identity.canonicalSymbol}${identity.canonicalNameZh && !result.nameUnverified ? ` ${identity.canonicalNameZh}` : ""}`;
  let statusTitle = "個股資料未封存准入 · 報價不可用";
  let statusSub = "QUOTE_UNAVAILABLE：目前快照中無該標的之封存驗收資料；不使用未驗證資料、模型生成或非公開快照猜測。";

  if (resolution) {
    if (resolution.status === "RESOLVED" && result.quoteStatus === "AVAILABLE" && typeof result.price === "number") {
      const change = typeof result.changePct === "number" ? `（${result.changePct >= 0 ? "+" : ""}${(result.changePct * 100).toFixed(2)}%）` : "";
      statusTitle = secFallback ? "備援身分（SEC 快取） · 延遲報價" : "已准入證券身分 · 延遲報價";
      const check = result.crossCheck;
      const cross = check ? `；交叉比對：${sourceZh(check.source)} ${check.price}${check.diffPct === null ? "（幣別或單位不同，不比較）"
        : `（差 ${check.diffPct >= 0 ? "+" : ""}${(check.diffPct * 100).toFixed(2)}%，${check.asOf}；觀察時間不同時有差異屬正常${Math.abs(check.diffPct) > 0.05 ? "；差異超過 5%，請以交易所價格為準並留意資料時間" : ""}）`}` : "";
      statusSub = `價格 ${result.price} ${identity.currency}${change}${result.priceSource ? `，來源 ${result.priceSource}` : ""}，觀察時間 ${result.asOf ?? "未揭露"}${cross}；延遲公開報價，非即時可成交價。`;
    } else if (resolution.status === "RESOLVED") {
      statusTitle = secFallback ? "備援身分（SEC 快取） · 報價未開放" : "已准入證券身分 · 報價未開放";
      statusSub = secFallback ? SEC_FALLBACK_UNAVAILABLE_SUB
        : "IDENTITY_RESOLVED：官方上市證券身分已核對；本標的不在已封存之延遲報價觀察清單。";
    } else if (resolution.status === "NEEDS_MARKET_SELECTION") {
      statusTitle = "多市場代號重疊 · 請確認市場";
      statusSub = "NEEDS_MARKET_SELECTION：本名稱／代號在多個市場掛牌或有多種股類，請使用精確市場代號查詢。";
    } else if (resolution.status === "UNAVAILABLE") {
      const conflict = isIdentityConflictCard(result.unavailableIdentityScope, resolution.reason);
      statusTitle = conflict ? IDENTITY_CONFLICT_TITLE : "身分資料未封存准入 · 報價不可用";
      statusSub = conflict ? `IDENTITY_CONFLICT_UNRESOLVED：${resolution.reason}\n${IDENTITY_CONFLICT_NOTICE}`
        : unavailableStatusSub(result.unavailableIdentityScope, resolution.reason);
    } else if (resolution.status === "INVALID_REQUEST") {
      statusTitle = "查詢格式不合規";
      statusSub = resolution.reason;
    }
  } else if (quoteStatus === "AMBIGUOUS") {
    statusTitle = "多市場代號重疊 · 請確認市場";
    statusSub = "MARKET_AMBIGUOUS：本代號在多個市場掛牌，請使用精確代號後綴查詢。";
  }

  const nameZh = (result.nameUnverified || !identity.canonicalNameZh)
    ? (result.admittedInSealedSnapshot && !identity.isAmbiguous
      ? (secFallback ? SEC_FALLBACK_NAME_ZH : "無公認中文名（交易所、公司官方與中文維基百科皆無，不自行翻譯）")
      : "未完成來源核對（不猜譯）")
    : `${identity.canonicalNameZh}（${ZH_SOURCE_LABEL[identity.nameZhSource ?? ""] ?? "來源已核對"}）`;
  const nameEn = identity.canonicalNameEn || identity.canonicalSymbol;

  const headLines = [
    `【${headerTitle}｜${statusTitle}】`,
    `代號：${identity.canonicalSymbol}（輸入：${identity.rawInput}）`,
    `${secFallback ? "市場／交易所（SEC 標示）" : "市場／交易所"}：${identity.exchange}（${identity.country}）`,
    `公司名稱（原文）：${nameEn}`,
    `中文名稱：${nameZh}`,
    `報價狀態：${statusTitle}`,
    statusSub,
    ...(secFallback ? [SEC_FALLBACK_NOTICE] : []),
  ];
  const tailLines = [
    `資料來源：${sourceZh(result.source)}`,
    `說明：${disclaimerShown}`,
  ];
  // ISEL1 display bound: the same deterministic prefix of complete candidate lines for text and Flex. The unit budget is the room
  // left under CANDIDATE_TEXT_MAX after the actual fixed lines, the list title, a worst-case omission note, the note and their four
  // separators, capped at CANDIDATE_DISPLAY_MAX_UNITS; the prefix is measured on the bulleted text lines (longer than the Flex lines).
  const candidateTotal = allCandidateLines.length;
  const candidateBudget = shownCandidates
    ? Math.min(CANDIDATE_DISPLAY_MAX_UNITS, CANDIDATE_TEXT_MAX - [...headLines, ...tailLines].join("\n").length
      - CANDIDATE_LIST_TITLE.length - candidateOmissionNote(candidateTotal, candidateTotal).length - candidateNote.length - 4)
    : 0;
  const visibleCount = shownCandidates ? candidateDisplayPrefix(allCandidateLines.map(line => `• ${line}`), candidateBudget) : 0;
  const visibleLines = allCandidateLines.slice(0, visibleCount);
  const omissionNote = visibleCount < candidateTotal ? [candidateOmissionNote(visibleCount, candidateTotal)] : [];
  // Buttons come only from CERTIFIED routes inside the visible prefix, then capped at three.
  const certifiedQueries = routes
    ? routes.slice(0, visibleCount).flatMap(route => (route.status === "CERTIFIED" && route.query ? [route.query] : [])).slice(0, 3)
    : [];
  // The candidate block is built once: it sits between the fixed lines in one text message, or forms the second text message.
  const candidateBlock = shownCandidates
    ? [CANDIDATE_LIST_TITLE, ...visibleLines.map(line => `• ${line}`), ...omissionNote, candidateNote]
    : [];
  const lines = [...headLines, ...candidateBlock, ...tailLines];

  if (presentation === "text") {
    // ISEL1: when the combined ambiguous text would exceed CANDIDATE_TEXT_MAX while the fixed card text (head and tail) fits, send
    // TWO text messages: the fixed card first, then the same bounded candidate block (the Flex prefix; never re-expanded, nothing
    // truncated). Every other result, including every non-ambiguous card and a card whose fixed text itself exceeds the bound, keeps
    // the single message and its existing validation.
    const fixedText = [...headLines, ...tailLines].join("\n");
    if (candidateBlock.length > 0 && lines.join("\n").length > CANDIDATE_TEXT_MAX && fixedText.length <= CANDIDATE_TEXT_MAX) {
      const splitMessages: LineOutboundMessage[] = [
        { type: "text", text: fixedText },
        { type: "text", text: candidateBlock.join("\n") },
      ];
      assertLineMessages(splitMessages);
      return splitMessages;
    }
    const textMsg: LineOutboundMessage = { type: "text", text: lines.join("\n") };
    assertLineMessages([textMsg]);
    return [textMsg];
  }

  // Flex Presentation. A Stockholm listing asks for its own options (AZN.ST), never the US listing of the same symbol.
  const optionSymbol = identity.market === "SWEDEN" ? `${identity.canonicalSymbol.replace(/ /g, "-")}.ST` : identity.canonicalSymbol;
  // Option buttons only where an answer exists: US and Stockholm listings, or a home listing with a mapped US ADR (TSMC).
  const hasOptions = marketHasOptions(identity.market) || adrRoute(identity.canonicalSymbol) !== null;
  // ISEL1: any ambiguous card gets only queries the handler certified on this pinned view and that are visible, or the safe
  // navigation buttons; never a symbol split from a display line and never the quote/options buttons.
  const footerActions = identity.isAmbiguous
    ? (certifiedQueries.length > 0
      ? certifiedQueries.map(query => menuAction(`查詢 ${query}`, query))
      : [menuAction("返回 TOP20 榜單", "TOP20"), menuAction("回功能選單", "選單")])
    : result.quoteStatus === "AVAILABLE" && hasOptions
      ? [menuAction("每月期權", `${optionSymbol} 每月期權`), menuAction("每週期權", `${optionSymbol} 每週期權`), menuAction("返回 TOP20 榜單", "TOP20")]
      : [menuAction("返回 TOP20 榜單", "TOP20"), menuAction("回功能選單", "選單")];

  const bubble = {
    type: "bubble" as const,
    size: "mega" as const,
    header: menuBox([
      menuText("韭菜守護者 · 全球個股快查", "xs", T.headerMuted),
      { ...menuText(headerTitle, "xl", T.headerText), weight: "bold" },
      menuText(`${secFallback ? "市場（SEC 標示）" : "市場"}：${identity.exchange}`, "xs", T.headerMuted),
    ], { ...headerStyle }),
    body: menuBox([
      menuBox([
        { ...menuText(statusTitle, "sm", T.ink), weight: "bold" },
        menuText(statusSub, "xs", T.muted),
        ...(secFallback ? [menuText(SEC_FALLBACK_NOTICE, "xs", T.ink)] : []),
      ], { backgroundColor: T.soft, paddingAll: "md", cornerRadius: "md", spacing: "xs" }),
      menuBox([
        menuText(`標的：${identity.canonicalSymbol}`, "sm", T.ink),
        menuText(`原文名稱：${nameEn}`, "xs", T.ink),
        menuText(`中文名稱：${nameZh}`, "xs", T.muted),
        menuText(`計價幣別：${identity.currency}`, "xs", T.muted),
        ...(shownCandidates ? [menuText(["候選市場：", ...visibleLines, ...omissionNote, candidateNote].join("\n"), "xs", T.muted)] : []),
      ], { spacing: "xs", paddingAll: "sm" }),
    ], { paddingAll: "lg", spacing: "md", backgroundColor: T.paper }),
    footer: menuBox([
      menuText(`來源：${sourceZh(result.source)}`, "xxs", T.muted),
      menuText(disclaimerShown, "xxs", T.muted),
      ...footerActions,
    ], { backgroundColor: T.paper, paddingAll: "md", spacing: "xs" }),
  };

  const flexMsg: LineOutboundMessage = {
    type: "flex",
    altText: `${headerTitle}｜${statusTitle}`,
    contents: {
      type: "carousel",
      contents: [bubble],
    },
  };
  assertLineMessages([flexMsg]);
  return [flexMsg];
}

/**
 * Main entry point for Global Equity Lookup within public LINE answering.
 * Uses a single pinned public snapshot view and authoritative catalog reader.
 * Fails closed without falling through to generic QA or issue creation.
 */
export async function handleGlobalEquityLookup(
  env: V213Top20Env & { V213_LINE_PRESENTATION?: string },
  query: ParsedQuery,
): Promise<LineOutboundMessage[] | string | null> {
  const isEquityIntent = query.intent === "global_equity_lookup";
  const { parsed, error } = parseIdentityRequest(query.normalized);

  // If there's an error and not an equity intent, ignore
  if (error && !isEquityIntent) {
    return null;
  }

  const isObviousEquity =
    isEquityIntent ||
    Boolean(
      parsed &&
        (parsed.isCompanyQuery ||
          parsed.isBareTickerCandidate ||
          parsed.suffixHint ||
          parsed.isNumericTicker),
    );

  const isText = env.V213_LINE_PRESENTATION === "text" || /文字\s*$/i.test(query.normalized);

  let view: PublicSnapshotView;
  try {
    view = await pinPublicSnapshot(env);
  } catch {
    if (!isObviousEquity) return null;
    const fallbackResult: EquityLookupResult = {
      identity: {
        rawInput: query.normalized,
        normalizedSymbol: query.normalized.toUpperCase(),
        canonicalSymbol: query.normalized.toUpperCase(),
        market: "UNKNOWN",
        country: "未指定",
        exchange: "快照鎖定失敗",
        currency: "UNAVAILABLE",
        isAmbiguous: false,
        leadingZeroPreserved: false,
      },
      admittedInSealedSnapshot: false,
      nameUnverified: true,
      quoteStatus: "UNAVAILABLE",
      source: "snapshot_pin_failed",
      disclaimer: "公開研究資訊，非投資建議；快照鎖定失敗，資料暫不可用。",
    };
    return buildGlobalEquityLookupMessages(fallbackResult, isText ? "text" : "flex");
  }

  // Sealed identity shards (official listing directories, digest-verified lazily from this pinned view) are the
  // admitted identity authority; the legacy single-catalog slot stays deferred.
  const shardCatalog = await loadIdentityCatalogForQuery(view, query.normalized);
  let effectiveCatalog = shardCatalog;
  if (!effectiveCatalog) {
    const candidateCatalog = await loadGlobalIdentityCatalog(view);
    const admission = evaluateCatalogAdmission(view, candidateCatalog);
    effectiveCatalog = admission.scope === "ADMITTED_AUTHORITATIVE" ? candidateCatalog : null;
  }

  // If not obviously an equity query and no catalog name match, do not hijack normal conversation
  if (!isObviousEquity) {
    if (!effectiveCatalog) return null;
    const norm = query.normalized.trim().toLowerCase().replace(/\s+/g, " ");
    const matches = effectiveCatalog.indexes.by_name[norm];
    if (!matches || matches.length === 0) return null;
  }

  const resolution = resolveGlobalIdentity(effectiveCatalog, query.normalized);

  if (resolution.status === "RESOLVED") {
    const rec = resolution.record;
    // The listing's market price shard leads (exchange feeds; the Japan and Korea shards are Yahoo daily closes); the hourly
    // watch-universe quote is shown as a cross-check only when it comes from a different provider (combineQuotes).
    const { primary: quote, crossCheck } = combineQuotes(await loadListingPrice(view, rec), await loadDelayedQuote(view, observationSymbol(rec)));
    const result: EquityLookupResult = {
      identity: {
        rawInput: query.normalized,
        normalizedSymbol: rec.symbol,
        canonicalSymbol: rec.symbol,
        market: rec.market,
        country: rec.country,
        exchange: `${rec.venue}（${rec.country}）`,
        currency: rec.currency,
        canonicalNameEn: rec.security_name,
        canonicalNameZh: rec.name_zh ?? undefined,
        nameZhSource: rec.name_zh_source ?? undefined,
        isAmbiguous: false,
        leadingZeroPreserved: /^0/.test(rec.native_symbol),
      },
      admittedInSealedSnapshot: true,
      nameUnverified: !rec.name_zh,
      quoteStatus: quote ? "AVAILABLE" : "UNAVAILABLE",
      ...(quote ? { price: quote.price, changePct: quote.change_pct ?? undefined, asOf: quote.asof, priceSource: sourceZh(quote.source) } : {}),
      ...(crossCheck ? { crossCheck } : {}),
      source: quote ? `sealed_snapshot:${rec.source_feed}；報價：${sourceZh(quote.source)} ${quote.source_url}${crossCheck ? `；交叉比對：${sourceZh(crossCheck.source)}` : ""}`
        : `sealed_snapshot:${rec.source_feed}`,
      disclaimer: isSecCacheFallback(resolution) ? (quote ? SEC_FALLBACK_QUOTE_DISCLAIMER : SEC_FALLBACK_NO_QUOTE_DISCLAIMER)
        : quote ? "公開研究資訊，非投資建議；身分來自官方上市目錄，報價為延遲觀察值，不下單。"
        : "公開研究資訊，非投資建議；官方上市身分已核對，本標的暫無延遲報價觀察。",
      resolution,
    };
    return buildGlobalEquityLookupMessages(result, isText ? "text" : "flex");
  }

  if (resolution.status === "NEEDS_MARKET_SELECTION") {
    const candidateStrings = resolution.candidates.map(
      c => `${c.symbol} (${c.venue}, ${c.country}) - ${c.security_name}`,
    );
    // ISEL1: certify each candidate's exact suffixed query on THIS pinned view (at most three validation calls, no retries, no
    // legacy-catalog fallback); every other candidate stays display-only.
    const candidateRoutes = await certifyCandidateRoutes(view, resolution.candidates, candidateStrings);
    const result: EquityLookupResult = {
      identity: {
        rawInput: query.normalized,
        normalizedSymbol: query.normalized.toUpperCase(),
        canonicalSymbol: query.normalized.toUpperCase(),
        market: "UNKNOWN",
        country: "多市場候選",
        exchange: "多個掛牌市場",
        currency: "UNAVAILABLE",
        isAmbiguous: true,
        ambiguityCandidates: candidateStrings,
        leadingZeroPreserved: false,
      },
      admittedInSealedSnapshot: true,
      nameUnverified: true,
      quoteStatus: "AMBIGUOUS",
      source: "sealed_snapshot:catalog_multi_match",
      disclaimer: "公開研究資訊，非投資建議；請選擇精確市場或輸入含後綴代號。",
      resolution,
      candidateRoutes,
    };
    return buildGlobalEquityLookupMessages(result, isText ? "text" : "flex");
  }

  // UNAVAILABLE or INVALID_REQUEST
  const suffixExchange = parsed?.suffixHint ? parsed.suffixHint.scheme.exchangeName : "資料未封存准入";
  const suffixCountry = parsed?.suffixHint ? parsed.suffixHint.scheme.country : "未指定";
  const cleanSym = parsed ? parsed.cleanInput.toUpperCase() : query.normalized.toUpperCase();
  const result: EquityLookupResult = {
    identity: {
      rawInput: query.normalized,
      normalizedSymbol: cleanSym,
      canonicalSymbol: cleanSym,
      market: resolution.status === "UNAVAILABLE" ? (resolution.attemptedMarket ?? "UNKNOWN") : "UNKNOWN",
      country: suffixCountry,
      exchange: suffixExchange,
      currency: "UNAVAILABLE",
      canonicalNameEn: undefined,
      isAmbiguous: false,
      leadingZeroPreserved: false,
    },
    admittedInSealedSnapshot: false,
    nameUnverified: true,
    quoteStatus: "UNAVAILABLE",
    source: view.integrity === "sealed" ? "sealed_snapshot:unadmitted_symbol" : "unsealed_or_missing",
    disclaimer: "公開研究資訊，非投資建議；無合格封存紀錄時維持不可用，絕不使用模型猜測。",
    resolution,
    // ABS1: whether this handler had a runtime-admitted query catalog (effectiveCatalog above; no extra read). INVALID_REQUEST gets
    // no context and is shown unchanged.
    ...(resolution.status === "UNAVAILABLE"
      ? { unavailableIdentityScope: effectiveCatalog ? "CATALOG_PRESENT" as const : "CATALOG_UNAVAILABLE" as const }
      : {}),
  };
  return buildGlobalEquityLookupMessages(result, isText ? "text" : "flex");
}
