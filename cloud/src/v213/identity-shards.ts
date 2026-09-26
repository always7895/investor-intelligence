/** Sealed identity shards (contract v213-identity-shard-v2, scripts/build_identity_shards.py).
 *
 * The publisher seals one symbol shard per first character (A-Z, 0-9, _) and 16 name shards (FNV-1a of the
 * normalized name over UTF-16 code units) as lazy content-addressed objects. A lookup reads only the shards its
 * query needs and builds the small catalog the existing resolver works on, so suffix handling, ambiguity and the
 * closed resolution union stay in global-identity.ts. A missing or malformed shard gives no catalog (UNAVAILABLE).
 */
import type { PublicSnapshotView } from "./public-snapshot";
import {
  type GlobalIdentityCatalog,
  type GlobalIdentityRecord,
  type SupportedMarket,
  normalizeCompanyName,
  parseIdentityRequest,
} from "./global-identity";

const SCHEMA = "v213-identity-shard-v2";
const NAME_BUCKETS = 16;
const MARKETS = new Set<SupportedMarket>(["US", "UK", "SWEDEN", "EUROPE", "JAPAN", "KOREA", "CHINA_SHANGHAI",
  "CHINA_SHENZHEN", "CHINA_BEIJING", "HK", "TAIWAN", "UNKNOWN"]);
const CLASSES = new Set(["COMMON_STOCK", "ETF", "PREFERRED_STOCK", "WARRANT", "UNIT", "RIGHTS", "ADR", "REVIEW_REQUIRED"]);
const SYMBOL = /^[A-Z0-9][A-Z0-9 .\-]{0,14}$/;
/** Sources of the tenth column (scripts/build_identity_shards.py): exchange directories or sourced names; never a translation. */
const ZH_SOURCES = new Set(["TWSE", "TPEX", "OFFICIAL", "ZHWIKI", "WIKIDATA_LABEL"]);

interface ShardFeed { readonly id: string; readonly url: string; readonly retrieved_at: string; readonly sha256: string; }
interface SymbolShard { readonly generated_at: string; readonly feeds: readonly ShardFeed[]; readonly rows: readonly GlobalIdentityRecord[]; }

export const identitySymbolKey = (bucket: string) => `v213:identity:v2:sym:${bucket}`;
export const identityNameKey = (bucket: number) => `v213:identity:v2:name:${bucket}`;

/** FNV-1a 32-bit over UTF-16 code units; mirrors build_identity_shards.fnv1a_utf16. */
export function identityNameBucket(normalized: string): number {
  let hash = 0x811c9dc5;
  for (let index = 0; index < normalized.length; index += 1) {
    hash ^= normalized.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash % NAME_BUCKETS;
}

export function identitySymbolBucket(symbol: string): string {
  const first = symbol.charAt(0).toUpperCase();
  return /^[A-Z0-9]$/.test(first) ? first : "_";
}

const text = (value: unknown, max: number): value is string => typeof value === "string" && value.length > 0 && value.length <= max;

function parseFeeds(raw: unknown): ShardFeed[] | null {
  if (!Array.isArray(raw) || raw.length === 0 || raw.length > 16) return null;
  const feeds: ShardFeed[] = [];
  for (const feed of raw) {
    if (!feed || typeof feed !== "object" || !text(feed.id, 64) || !text(feed.url, 300) || !String(feed.url).startsWith("https://")
      || !text(feed.retrieved_at, 30) || !text(feed.sha256, 64) || !/^[0-9a-f]{64}$/.test(feed.sha256)) return null;
    feeds.push({ id: feed.id, url: feed.url, retrieved_at: feed.retrieved_at, sha256: feed.sha256 });
  }
  return feeds;
}

function parseSymbolShard(raw: unknown, bucket: string): SymbolShard | null {
  if (!raw || typeof raw !== "object") return null;
  const shard = raw as Record<string, unknown>;
  if (shard.schema !== SCHEMA || shard.kind !== "symbol" || shard.bucket !== bucket || !text(shard.generated_at, 30)
    || !Array.isArray(shard.rows) || shard.rows.length > 50_000) return null;
  const feeds = parseFeeds(shard.feeds);
  if (!feeds) return null;
  const rows: GlobalIdentityRecord[] = [];
  for (const row of shard.rows) {
    if (!Array.isArray(row) || (row.length !== 9 && row.length !== 10)) return null;
    const [symbol, venue, market, country, name, nativeName, securityClass, currency, feedIndex, zh] = row;
    const zhOk = zh === undefined || zh === null
      || (Array.isArray(zh) && zh.length === 2 && text(zh[0], 40) && ZH_SOURCES.has(String(zh[1])));
    if (!zhOk) return null;
    if (!text(symbol, 15) || !SYMBOL.test(symbol) || identitySymbolBucket(symbol) !== bucket || !text(venue, 40)
      || !MARKETS.has(market as SupportedMarket) || !text(country, 40) || !text(name, 300)
      || !(nativeName === null || text(nativeName, 100)) || !CLASSES.has(String(securityClass)) || !text(currency, 8)
      || !Number.isInteger(feedIndex) || (feedIndex as number) < 0 || (feedIndex as number) >= feeds.length) return null;
    const feed = feeds[feedIndex as number]!;
    rows.push({ symbol, native_symbol: symbol, venue, market: market as SupportedMarket, country, security_name: name,
      native_name: nativeName as string | null, security_class: String(securityClass), currency, source_feed: feed.id, source_url: feed.url,
      name_zh: Array.isArray(zh) ? String(zh[0]) : null, name_zh_source: Array.isArray(zh) ? String(zh[1]) : null });
  }
  return { generated_at: shard.generated_at as string, feeds, rows };
}

function parseNameShard(raw: unknown, bucket: number): [string, string, string, string][] | null {
  if (!raw || typeof raw !== "object") return null;
  const shard = raw as Record<string, unknown>;
  if (shard.schema !== SCHEMA || shard.kind !== "name" || shard.bucket !== String(bucket) || !Array.isArray(shard.rows)) return null;
  const rows: [string, string, string, string][] = [];
  for (const row of shard.rows) {
    if (!Array.isArray(row) || row.length !== 4 || !row.every(item => text(item, 300))) return null;
    rows.push(row as [string, string, string, string]);
  }
  return rows;
}

/** Symbol spellings a user may type for one listed symbol ("VOLV B" is also "VOLV-B" and "VOLV.B"). */
function spellings(symbol: string): string[] {
  return symbol.includes(" ") ? [symbol, symbol.replace(/ /g, "-"), symbol.replace(/ /g, ".")] : [symbol];
}

/** The small catalog this query needs, built from sealed shards; null when no identity shard is sealed. */
export async function loadIdentityCatalogForQuery(view: PublicSnapshotView, rawQuery: string): Promise<GlobalIdentityCatalog | null> {
  if (view.integrity !== "sealed") return null;
  const { parsed } = parseIdentityRequest(rawQuery);
  if (!parsed) return null;
  const shards = new Map<string, SymbolShard | null>();
  const shardFor = async (bucket: string): Promise<SymbolShard | null> => {
    if (!shards.has(bucket)) shards.set(bucket, parseSymbolShard(await view.json<unknown>([identitySymbolKey(bucket)]), bucket));
    return shards.get(bucket)!;
  };
  const selected = new Map<string, GlobalIdentityRecord>();
  let generatedAt: string | null = null;
  let feedDigest: string | null = null;
  const take = (shard: SymbolShard, match: (record: GlobalIdentityRecord) => boolean) => {
    generatedAt ??= shard.generated_at; feedDigest ??= shard.feeds[0]!.sha256;
    for (const record of shard.rows) if (match(record)) selected.set(`${record.venue}:${record.symbol}`, record);
  };
  const body = (parsed.suffixHint ? parsed.suffixHint.symbolBody : parsed.cleanInput).toUpperCase();
  if (!parsed.isCompanyPrefix && SYMBOL.test(body)) {
    const shard = await shardFor(identitySymbolBucket(body));
    if (!shard) return null;
    take(shard, record => spellings(record.symbol).includes(body));
  }
  if (!parsed.isTickerPrefix && !parsed.suffixHint) {
    const normalized = normalizeCompanyName(parsed.cleanInput);
    const bucket = identityNameBucket(normalized);
    // A missing or malformed name shard only removes name matches; symbol matches still resolve.
    const names = parseNameShard(await view.json<unknown>([identityNameKey(bucket)]), bucket) ?? [];
    for (const [name, symbolBucket, symbol, venue] of names) {
      if (name !== normalized) continue;
      const shard = await shardFor(symbolBucket);
      if (shard) take(shard, record => record.symbol === symbol && record.venue === venue);
    }
  }
  // Bare numeric codes are Taiwan-first (4-digit Tokyo codes overlap Taiwan's); `.T` or another suffix selects others.
  if (parsed.isNumericTicker && !parsed.suffixHint && [...selected.values()].some(record => record.market === "TAIWAN")) {
    for (const [key, record] of selected) if (record.market !== "TAIWAN") selected.delete(key);
  }
  if (generatedAt === null) {
    // A sealed but empty result still proves the shards exist: an empty catalog resolves to honest UNAVAILABLE.
    const probe = await shardFor("A");
    if (!probe) return null;
    generatedAt = probe.generated_at; feedDigest = probe.feeds[0]!.sha256;
  }
  const records = [...selected.values()];
  const bySymbol: Record<string, number[]> = Object.create(null);
  const byName: Record<string, number[]> = Object.create(null);
  const byVenue: Record<string, number> = Object.create(null);
  records.forEach((record, index) => {
    byVenue[`${record.venue}:${record.symbol}`] = index;
    for (const spelling of spellings(record.symbol)) (bySymbol[spelling] ??= []).push(index);
    for (const name of new Set([record.security_name, record.native_name ?? "", record.name_zh ?? ""].map(normalizeCompanyName).filter(Boolean))) {
      (byName[name] ??= []).push(index);
    }
  });
  return {
    schema_version: 1, contract_id: "v213-global-identity-v1", generated_at: generatedAt, collection_receipts_sha256: feedDigest!,
    records_count: records.length, records, indexes: { by_venue_and_symbol: byVenue, by_symbol: bySymbol, by_name: byName },
  };
}
