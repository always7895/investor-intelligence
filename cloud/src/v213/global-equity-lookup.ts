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
import { loadDelayedQuote, loadListingPrice, observationSymbol } from "./market-observations";
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

export interface EquityLookupResult {
  identity: ResolvedEquityIdentity;
  admittedInSealedSnapshot: boolean;
  nameUnverified: boolean;
  quoteStatus: "AVAILABLE" | "UNAVAILABLE" | "AMBIGUOUS";
  price?: number;
  changePct?: number;
  asOf?: string;
  source: string;
  disclaimer: string;
  resolution?: GlobalIdentityResolution;
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

  const headerTitle = `個股快查 · ${identity.canonicalSymbol}${identity.canonicalNameZh && !result.nameUnverified ? ` ${identity.canonicalNameZh}` : ""}`;
  let statusTitle = "個股資料未封存准入 · 報價不可用";
  let statusSub = "QUOTE_UNAVAILABLE：目前快照中無該標的之封存驗收資料；不使用未驗證資料、模型生成或非公開快照猜測。";

  if (resolution) {
    if (resolution.status === "RESOLVED" && result.quoteStatus === "AVAILABLE" && typeof result.price === "number") {
      const change = typeof result.changePct === "number" ? `（${result.changePct >= 0 ? "+" : ""}${(result.changePct * 100).toFixed(2)}%）` : "";
      statusTitle = "已准入證券身分 · 延遲報價";
      statusSub = `價格 ${result.price} ${identity.currency}${change}，觀察時間 ${result.asOf ?? "未揭露"}；延遲公開報價，非即時可成交價。`;
    } else if (resolution.status === "RESOLVED") {
      statusTitle = "已准入證券身分 · 報價未開放";
      statusSub = "IDENTITY_RESOLVED：官方上市證券身分已核對；本標的不在已封存之延遲報價觀察清單。";
    } else if (resolution.status === "NEEDS_MARKET_SELECTION") {
      statusTitle = "多市場代號重疊 · 請確認市場";
      statusSub = "NEEDS_MARKET_SELECTION：本名稱／代號在多個市場掛牌或有多種股類，請使用精確市場代號查詢。";
    } else if (resolution.status === "UNAVAILABLE") {
      statusTitle = "身分資料未封存准入 · 報價不可用";
      statusSub = `QUOTE_UNAVAILABLE：${resolution.reason}`;
    } else if (resolution.status === "INVALID_REQUEST") {
      statusTitle = "查詢格式不合規";
      statusSub = resolution.reason;
    }
  } else if (quoteStatus === "AMBIGUOUS") {
    statusTitle = "多市場代號重疊 · 請確認市場";
    statusSub = "MARKET_AMBIGUOUS：本代號在多個市場掛牌，請使用精確代號後綴查詢。";
  }

  const nameZh = (result.nameUnverified || !identity.canonicalNameZh)
    ? (result.admittedInSealedSnapshot && !identity.isAmbiguous ? "無公認中文名（交易所、公司官方與中文維基百科皆無，不自行翻譯）" : "未完成來源核對（不猜譯）")
    : `${identity.canonicalNameZh}（${ZH_SOURCE_LABEL[identity.nameZhSource ?? ""] ?? "來源已核對"}）`;
  const nameEn = identity.canonicalNameEn || identity.canonicalSymbol;

  const lines = [
    `【${headerTitle}｜${statusTitle}】`,
    `代號：${identity.canonicalSymbol}（輸入：${identity.rawInput}）`,
    `市場／交易所：${identity.exchange}（${identity.country}）`,
    `公司名稱（原文）：${nameEn}`,
    `中文名稱：${nameZh}`,
    `報價狀態：${statusTitle}`,
    statusSub,
    ...(identity.isAmbiguous && identity.ambiguityCandidates && identity.ambiguityCandidates.length > 0
      ? ["可選候選代號：", ...identity.ambiguityCandidates.map(c => `• ${c}`)]
      : []),
    `資料來源：${sourceZh(result.source)}`,
    `說明：${result.disclaimer}`,
  ];

  if (presentation === "text") {
    const textMsg: LineOutboundMessage = { type: "text", text: lines.join("\n") };
    assertLineMessages([textMsg]);
    return [textMsg];
  }

  // Flex Presentation. A Stockholm listing asks for its own options (AZN.ST), never the US listing of the same symbol.
  const optionSymbol = identity.market === "SWEDEN" ? `${identity.canonicalSymbol.replace(/ /g, "-")}.ST` : identity.canonicalSymbol;
  const footerActions = (identity.isAmbiguous && identity.ambiguityCandidates && identity.ambiguityCandidates.length > 0)
    ? identity.ambiguityCandidates.slice(0, 3).map(c => {
        const sym = c.split(" ")[0]!;
        return menuAction(`查詢 ${sym}`, sym);
      })
    : result.quoteStatus === "AVAILABLE"
      ? [menuAction("每月期權", `${optionSymbol} 每月期權`), menuAction("每週期權", `${optionSymbol} 每週期權`), menuAction("返回 TOP20 榜單", "TOP20")]
      : [menuAction("返回 TOP20 榜單", "TOP20"), menuAction("回功能選單", "選單")];

  const bubble = {
    type: "bubble" as const,
    size: "mega" as const,
    header: menuBox([
      menuText("韭菜守護者 · 全球個股快查", "xs", T.headerMuted),
      { ...menuText(headerTitle, "xl", T.headerText), weight: "bold" },
      menuText(`市場：${identity.exchange}`, "xs", T.headerMuted),
    ], { ...headerStyle }),
    body: menuBox([
      menuBox([
        { ...menuText(statusTitle, "sm", T.ink), weight: "bold" },
        menuText(statusSub, "xs", T.muted),
      ], { backgroundColor: T.soft, paddingAll: "md", cornerRadius: "md", spacing: "xs" }),
      menuBox([
        menuText(`標的：${identity.canonicalSymbol}`, "sm", T.ink),
        menuText(`原文名稱：${nameEn}`, "xs", T.ink),
        menuText(`中文名稱：${nameZh}`, "xs", T.muted),
        menuText(`計價幣別：${identity.currency}`, "xs", T.muted),
        ...(identity.isAmbiguous && identity.ambiguityCandidates && identity.ambiguityCandidates.length > 0
          ? [menuText("請輸入含後綴之代號：\n" + identity.ambiguityCandidates.join("\n"), "xs", T.muted)]
          : []),
      ], { spacing: "xs", paddingAll: "sm" }),
    ], { paddingAll: "lg", spacing: "md", backgroundColor: T.paper }),
    footer: menuBox([
      menuText(`來源：${sourceZh(result.source)}`, "xxs", T.muted),
      menuText(result.disclaimer, "xxs", T.muted),
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
    // Watch-universe quote first (hourly); otherwise the listing's market price shard (official daily feeds).
    const quote = await loadDelayedQuote(view, observationSymbol(rec)) ?? await loadListingPrice(view, rec);
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
      ...(quote ? { price: quote.price, changePct: quote.change_pct ?? undefined, asOf: quote.asof } : {}),
      source: quote ? `sealed_snapshot:${rec.source_feed}；報價：${quote.source} ${quote.source_url}` : `sealed_snapshot:${rec.source_feed}`,
      disclaimer: quote ? "公開研究資訊，非投資建議；身分來自官方上市目錄，報價為延遲觀察值，不下單。"
        : "公開研究資訊，非投資建議；官方上市身分已核對，本標的暫無延遲報價觀察。",
      resolution,
    };
    return buildGlobalEquityLookupMessages(result, isText ? "text" : "flex");
  }

  if (resolution.status === "NEEDS_MARKET_SELECTION") {
    const candidateStrings = resolution.candidates.map(
      c => `${c.symbol} (${c.venue}, ${c.country}) - ${c.security_name}`,
    );
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
  };
  return buildGlobalEquityLookupMessages(result, isText ? "text" : "flex");
}
