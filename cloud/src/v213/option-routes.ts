/** Which listed options answer an options query (operator 2026-09-27: TSMC and IQE had no options answer).
 * Sealed observations cover US listings and Nasdaq Stockholm (scripts/build_market_quotes_options.py). A listing on another
 * market is answered with its US ADR's options when config/option-adr-map-v1.json maps one (labelled as the ADR with its share
 * ratio), otherwise with an explicit statement that no public listed-option source covers that market. Never a modelled price. */
import adrMap from "../../../config/option-adr-map-v1.json";
import type { GlobalIdentityRecord } from "./global-identity";

export interface AdrRoute { listing: string; adr: string; ratio: number; name_zh: string }

const LISTINGS = adrMap.listings as Record<string, { adr: string; ratio: number; name_zh: string; aliases: string[] }>;
const COVERED = adrMap.covered_markets as Record<string, string>;
const MARKET_NAMES = adrMap.market_names as Record<string, string>;

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

/** The note shown above an ADR's covered-call suggestion. */
export function adrNote(route: AdrRoute): string {
  return `${route.name_zh}（${route.listing}）以其美國 ADR ${route.adr}（1 ADR＝${route.ratio} 股普通股）的掛牌期權顯示；`
    + "台股個股期權沒有本服務可用的公開報價來源。賣出買權被履約時交付的是 ADR，不是台股。";
}

/** Why a resolved listing has no options answer here. */
export function uncoveredReason(record: Pick<GlobalIdentityRecord, "symbol" | "market" | "venue">): string {
  const market = MARKET_NAMES[record.market] ?? record.market;
  return `${record.symbol} 在${market}（${record.venue}）掛牌；本服務的公開掛牌期權報價只涵蓋${Object.values(COVERED).join("與")}，`
    + "本服務尚未採用此市場的個股期權報價來源（該股也可能沒有掛牌期權）；不以模型推估。";
}
