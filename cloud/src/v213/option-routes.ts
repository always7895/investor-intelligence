/** Which listed options answer an options query (operator 2026-09-27: TSMC and IQE had no options answer).
 * Sealed observations cover US listings and Nasdaq Stockholm (scripts/build_market_quotes_options.py). A listing on another
 * market is answered with its US ADR's options when config/option-adr-map-v1.json maps one (labelled as the ADR with its share
 * ratio), otherwise with an explicit statement that no public listed-option source covers that market. Never a modelled price. */
import adrMap from "../../../config/option-adr-map-v1.json";
import taifex from "../../../config/taifex-stock-option-underlyings-v1.json";
import type { GlobalIdentityRecord } from "./global-identity";

export interface AdrRoute { listing: string; adr: string; ratio: number; name_zh: string }

const LISTINGS = adrMap.listings as Record<string, { adr: string; ratio: number; name_zh: string; aliases: string[] }>;
const COVERED = adrMap.covered_markets as Record<string, string>;
const MARKET_NAMES = adrMap.market_names as Record<string, string>;
const REVIEWED_MARKETS = new Set(["JAPAN", "KOREA", "UK", "EUROPE", "HK"]);

/** The ADR route for a home listing ("2330.TW") or one of its aliases ("TSMC", "台積電", "2330"). */
export function adrRoute(text: string): AdrRoute | null {
  const wanted = text.trim().toUpperCase();
  for (const [listing, row] of Object.entries(LISTINGS)) {
    if (listing === wanted || row.aliases.some(alias => alias.toUpperCase() === wanted)) {
      return { listing, adr: row.adr, ratio: row.ratio, name_zh: row.name_zh };
    }
  }
  return null;
}

export function marketHasOptions(market: string): boolean {
  return Object.hasOwn(COVERED, market);
}

/** The exact command of the global options SOURCE-status page (options-coverage.ts, metadata only). It adds no market support and does
 * not touch covered_markets, which stays the actual covered-call routing scope. */
export const GLOBAL_SOURCE_STATUS_COMMAND = "全球期權來源與缺口";
export function isGlobalSourceStatusCommand(command: string): boolean {
  return /^(?:全球期權來源與缺口|全球期權來源|期權來源與缺口)(?:\s*文字)?$/.test(command.trim());
}

/** The note shown above an ADR's covered-call suggestion. */
export function adrNote(route: AdrRoute): string {
  return `${route.name_zh}（${route.listing}）以其美國 ADR ${route.adr}（1 ADR＝${route.ratio} 股普通股）的掛牌期權顯示；`
    + "台股個股期權沒有本服務可用的公開報價來源。賣出買權被履約時交付的是 ADR，不是台股。";
}

/** Why a resolved listing has no options answer here. */
export function uncoveredReason(record: Pick<GlobalIdentityRecord, "symbol" | "market" | "venue">): string {
  const pointer = `各市場來源與缺口：輸入「${GLOBAL_SOURCE_STATUS_COMMAND}」（僅來源說明，不代表已涵蓋）。`;
  if (record.market === "TAIWAN") {
    const code = record.symbol.toUpperCase().replace(/\.(?:TW|TWO)$/, "");
    if (/^\d{4}$/.test(code)) {
      const listing = Object.hasOwn(taifex.single_stock_options, code)
        ? "期交所列有此股個股選擇權，但本服務尚未提供期交所報價；免費資料僅每日收盤。"
        : "期交所未列有此股個股選擇權。";
      return `截至 ${taifex.effective_date}，${record.symbol}：${listing}${pointer}`;
    }
  }
  const market = MARKET_NAMES[record.market] ?? record.market;
  const reason = REVIEWED_MARKETS.has(record.market)
    ? "本服務尚無可免費自動公開散布的授權個股期權報價來源（該股也可能沒有掛牌期權）。"
    : "本服務尚未採用此市場的個股期權報價來源（該股也可能沒有掛牌期權）。";
  return `${record.symbol} 在${market}（${record.venue}）掛牌；本服務的公開掛牌期權報價只涵蓋${Object.values(COVERED).join("與")}，${reason}${pointer}`;
}
