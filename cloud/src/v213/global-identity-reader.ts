/**
 * Sealed Snapshot Global Identity Catalog Reader.
 *
 * Reads and verifies the global identity catalog candidate schema from a sealed
 * PublicSnapshotView. Rejects missing keys, unsealed views, schema violations,
 * invalid indexes, impossible dates, non-HTTPS/credentialed URLs, or byte
 * bounds fail-closed.
 *
 * NOTE: Current stored snapshot seal profile (SNAPSHOT_OBJECT_KEYS) has NO
 * identity slot and no approved identity profile contract. Candidate validation
 * verifies structural schema only; runtime authority is withheld (ADMISSION_DEFER).
 */
import type { PublicSnapshotView } from "./public-snapshot";
import {
  type GlobalIdentityCatalog,
  type GlobalIdentityRecord,
  normalizeCompanyName,
} from "./global-identity";

export const GLOBAL_IDENTITY_CATALOG_KEY = "v213:global-identity:catalog:v1";

export const MAX_CATALOG_BYTES = 10 * 1024 * 1024; // 10 MB bound (measured in UTF-8 bytes)

const ENCODER = new TextEncoder();

const VALID_MARKETS = new Set<string>([
  "US",
  "UK",
  "SWEDEN",
  "EUROPE",
  "JAPAN",
  "KOREA",
  "CHINA_SHANGHAI",
  "CHINA_SHENZHEN",
  "CHINA_BEIJING",
  "HK",
  "TAIWAN",
  "UNKNOWN",
]);

const VALID_CLASSES = new Set<string>([
  "COMMON_STOCK",
  "ETF",
  "PREFERRED_STOCK",
  "WARRANT",
  "UNIT",
  "RIGHTS",
  "ADR",
  "REVIEW_REQUIRED",
]);

const DANGEROUS_KEYS = new Set([
  "__proto__",
  "constructor",
  "prototype",
  "toString",
  "valueOf",
  "hasOwnProperty",
  "isPrototypeOf",
]);

const ALLOWED_ROOT_KEYS = new Set([
  "schema_version",
  "contract_id",
  "generated_at",
  "collection_receipts_sha256",
  "records_count",
  "indexed_symbols_count",
  "indexed_names_count",
  "conflicts_count",
  "records",
  "indexes",
  "conflicts",
]);

const ALLOWED_RECORD_KEYS = new Set([
  "venue",
  "market",
  "country",
  "symbol",
  "native_symbol",
  "security_name",
  "native_name",
  "security_class",
  "currency",
  "source_feed",
  "source_url",
]);

const ALLOWED_INDEX_KEYS = new Set([
  "by_venue_and_symbol",
  "by_symbol",
  "by_name",
]);

function isValidStrictIsoTime(raw: unknown): raw is string {
  if (typeof raw !== "string" || !/^(?!0000)\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{3})?Z$/.test(raw)) {
    return false;
  }
  const n = Date.parse(raw);
  return (
    Number.isFinite(n) &&
    new Date(n).toISOString() === (raw.includes(".") ? raw : raw.replace("Z", ".000Z"))
  );
}

function isValidSourceUrl(raw: unknown): raw is string {
  if (typeof raw !== "string" || !raw.startsWith("https://") || raw.includes("@") || raw.includes("..")) {
    return false;
  }
  try {
    const u = new URL(raw);
    if (u.protocol !== "https:") return false;
    if (u.username || u.password) return false;
    const host = u.hostname.toLowerCase();
    if (
      host === "localhost" ||
      host === "127.0.0.1" ||
      host === "::1" ||
      host === "0.0.0.0" ||
      host.startsWith("10.") ||
      host.startsWith("192.168.") ||
      host.startsWith("172.16.")
    ) {
      return false;
    }
    return true;
  } catch {
    return false;
  }
}

function rebuildCanonicalIndexes(records: GlobalIdentityRecord[]): {
  by_venue_and_symbol: Record<string, number>;
  by_symbol: Record<string, number[]>;
  by_name: Record<string, number[]>;
} {
  const by_venue_and_symbol: Record<string, number> = Object.create(null);
  const by_symbol: Record<string, number[]> = Object.create(null);
  const by_name: Record<string, number[]> = Object.create(null);

  for (let idx = 0; idx < records.length; idx++) {
    const rec = records[idx]!;

    // 1. Primary venue key
    const primaryKey = `${rec.venue}:${rec.symbol}`;
    if (!DANGEROUS_KEYS.has(primaryKey)) {
      by_venue_and_symbol[primaryKey] = idx;
    }

    // 2. Native symbol (uppercase)
    const symKey = rec.native_symbol.toUpperCase();
    if (!DANGEROUS_KEYS.has(symKey)) {
      if (!by_symbol[symKey]) by_symbol[symKey] = [];
      by_symbol[symKey]!.push(idx);
    }
    const symUpper = rec.symbol.toUpperCase();
    if (symUpper !== symKey && !DANGEROUS_KEYS.has(symUpper)) {
      if (!by_symbol[symUpper]) by_symbol[symUpper] = [];
      if (!by_symbol[symUpper]!.includes(idx)) {
        by_symbol[symUpper]!.push(idx);
      }
    }

    // 3. Exact names
    if (rec.security_name) {
      const normName = normalizeCompanyName(rec.security_name);
      if (normName && !DANGEROUS_KEYS.has(normName)) {
        if (!by_name[normName]) by_name[normName] = [];
        if (!by_name[normName]!.includes(idx)) {
          by_name[normName]!.push(idx);
        }
      }
    }

    if (rec.native_name) {
      const normNative = normalizeCompanyName(rec.native_name);
      const normName = rec.security_name ? normalizeCompanyName(rec.security_name) : "";
      if (normNative && normNative !== normName && !DANGEROUS_KEYS.has(normNative)) {
        if (!by_name[normNative]) by_name[normNative] = [];
        if (!by_name[normNative]!.includes(idx)) {
          by_name[normNative]!.push(idx);
        }
      }
    }
  }

  return { by_venue_and_symbol, by_symbol, by_name };
}

/**
 * Validates the candidate schema, bounds, URLs, dates, and index exactness
 * against canonical rebuild from records.
 *
 * NOTE: Returns a structural GlobalIdentityCatalog candidate, NOT runtime authority.
 */
export function validateCatalogCandidate(data: unknown): GlobalIdentityCatalog | null {
  if (!data || typeof data !== "object" || Array.isArray(data)) return null;
  const cat = data as Record<string, unknown>;

  // Closed root keys
  for (const k of Object.keys(cat)) {
    if (!ALLOWED_ROOT_KEYS.has(k)) return null;
  }

  if (cat.schema_version !== 1 || cat.contract_id !== "v213-global-identity-v1") {
    return null;
  }

  if (!isValidStrictIsoTime(cat.generated_at)) {
    return null;
  }

  if (
    typeof cat.collection_receipts_sha256 !== "string" ||
    !/^[0-9a-f]{64}$/i.test(cat.collection_receipts_sha256)
  ) {
    return null;
  }

  if (!Array.isArray(cat.records)) {
    return null;
  }
  if (typeof cat.records_count !== "number" || cat.records_count !== cat.records.length) {
    return null;
  }

  // Validate each record
  for (let i = 0; i < cat.records.length; i++) {
    const r = cat.records[i];
    if (!r || typeof r !== "object" || Array.isArray(r)) return null;
    const rec = r as Record<string, unknown>;

    for (const k of Object.keys(rec)) {
      if (!ALLOWED_RECORD_KEYS.has(k)) return null;
    }

    if (
      typeof rec.venue !== "string" ||
      !rec.venue ||
      typeof rec.market !== "string" ||
      !VALID_MARKETS.has(rec.market) ||
      typeof rec.country !== "string" ||
      !rec.country ||
      typeof rec.symbol !== "string" ||
      !rec.symbol ||
      typeof rec.native_symbol !== "string" ||
      !rec.native_symbol ||
      typeof rec.security_name !== "string" ||
      !rec.security_name ||
      (rec.native_name !== null && rec.native_name !== undefined && typeof rec.native_name !== "string") ||
      typeof rec.security_class !== "string" ||
      !VALID_CLASSES.has(rec.security_class) ||
      typeof rec.currency !== "string" ||
      !rec.currency ||
      typeof rec.source_feed !== "string" ||
      !rec.source_feed ||
      !isValidSourceUrl(rec.source_url)
    ) {
      return null;
    }
  }

  // Validate indexes structure
  if (typeof cat.indexes !== "object" || cat.indexes === null || Array.isArray(cat.indexes)) {
    return null;
  }
  const indexes = cat.indexes as Record<string, unknown>;
  const indexKeys = Object.keys(indexes);
  if (indexKeys.length !== 3 || !indexKeys.every(k => ALLOWED_INDEX_KEYS.has(k))) {
    return null;
  }

  // Rebuild canonical indexes from verified records
  const canonical = rebuildCanonicalIndexes(cat.records as GlobalIdentityRecord[]);

  // 1. by_venue_and_symbol
  if (
    typeof indexes.by_venue_and_symbol !== "object" ||
    indexes.by_venue_and_symbol === null ||
    Array.isArray(indexes.by_venue_and_symbol)
  ) {
    return null;
  }
  const byVenueAndSymbol = indexes.by_venue_and_symbol as Record<string, unknown>;
  const venueKeys = Object.keys(byVenueAndSymbol);
  const canonicalVenueKeys = Object.keys(canonical.by_venue_and_symbol);
  if (venueKeys.length !== canonicalVenueKeys.length) {
    return null;
  }
  for (const [key, ref] of Object.entries(byVenueAndSymbol)) {
    if (DANGEROUS_KEYS.has(key)) return null;
    if (typeof ref !== "number" || !Number.isInteger(ref) || ref < 0 || ref >= cat.records.length) {
      return null;
    }
    if (canonical.by_venue_and_symbol[key] !== ref) {
      return null;
    }
  }

  // 2. by_symbol
  if (
    typeof indexes.by_symbol !== "object" ||
    indexes.by_symbol === null ||
    Array.isArray(indexes.by_symbol)
  ) {
    return null;
  }
  const bySymbol = indexes.by_symbol as Record<string, unknown>;
  const symbolKeys = Object.keys(bySymbol);
  const canonicalSymbolKeys = Object.keys(canonical.by_symbol);
  if (symbolKeys.length !== canonicalSymbolKeys.length) {
    return null;
  }
  for (const [key, val] of Object.entries(bySymbol)) {
    if (DANGEROUS_KEYS.has(key)) return null;
    if (!Array.isArray(val)) return null;
    for (const ref of val) {
      if (typeof ref !== "number" || !Number.isInteger(ref) || ref < 0 || ref >= cat.records.length) {
        return null;
      }
    }
    if (new Set(val).size !== val.length) {
      return null; // Duplicates forbidden
    }
    const exp = canonical.by_symbol[key];
    if (!exp || exp.length !== val.length || !exp.every((id, i) => id === val[i])) {
      return null;
    }
  }

  // 3. by_name
  if (
    typeof indexes.by_name !== "object" ||
    indexes.by_name === null ||
    Array.isArray(indexes.by_name)
  ) {
    return null;
  }
  const byName = indexes.by_name as Record<string, unknown>;
  const nameKeys = Object.keys(byName);
  const canonicalNameKeys = Object.keys(canonical.by_name);
  if (nameKeys.length !== canonicalNameKeys.length) {
    return null;
  }
  for (const [key, val] of Object.entries(byName)) {
    if (DANGEROUS_KEYS.has(key)) return null;
    if (!Array.isArray(val)) return null;
    for (const ref of val) {
      if (typeof ref !== "number" || !Number.isInteger(ref) || ref < 0 || ref >= cat.records.length) {
        return null;
      }
    }
    if (new Set(val).size !== val.length) {
      return null; // Duplicates forbidden
    }
    const exp = canonical.by_name[key];
    if (!exp || exp.length !== val.length || !exp.every((id, i) => id === val[i])) {
      return null;
    }
  }

  return data as GlobalIdentityCatalog;
}

/** Backward compatibility alias for validateCatalogCandidate */
export const validateCatalogIntegrity = validateCatalogCandidate;

export type IdentityAdmissionScope =
  | "ADMITTED_AUTHORITATIVE"
  | "ADMISSION_DEFER"
  | "REJECTED";

export interface IdentityAdmissionAssessment {
  scope: IdentityAdmissionScope;
  isAuthoritative: boolean;
  reason: string;
  catalog: GlobalIdentityCatalog | null;
}

/**
 * Evaluates runtime identity catalog admission from the given sealed snapshot view.
 * If the current view is unsealed or candidate is invalid, reports REJECTED.
 * Because current sealed snapshot profile has NO identity slot and no approved
 * identity producer, runtime authority is withheld (ADMISSION_DEFER) fail-closed.
 */
export function evaluateCatalogAdmission(
  view: PublicSnapshotView,
  candidate: GlobalIdentityCatalog | null,
): IdentityAdmissionAssessment {
  if (view.integrity !== "sealed") {
    return {
      scope: "REJECTED",
      isAuthoritative: false,
      reason: "VIEW_UNSEALED: 快照視圖未封存，拒絕身分准入。",
      catalog: null,
    };
  }

  if (!candidate) {
    return {
      scope: "REJECTED",
      isAuthoritative: false,
      reason: "CANDIDATE_INVALID: 身分目錄候選資料未通過完整性或綱要校驗。",
      catalog: null,
    };
  }

  // Current snapshot seal profile has NO identity slot and no approved contract
  return {
    scope: "ADMISSION_DEFER",
    isAuthoritative: false,
    reason: "ADMISSION_DEFER: 當前封存規格無身分插槽與已核准身分合約，正式身分准入延後（authority withheld）。",
    catalog: candidate,
  };
}

/**
 * Loads and verifies the global identity catalog candidate from the given sealed view.
 * Requires bounded exact raw UTF-8 text (no view.json fallback).
 * If the current view is unsealed, exceeds byte bounds, or fails schema validation,
 * returns null gracefully.
 */
export async function loadGlobalIdentityCatalog(
  view: PublicSnapshotView,
): Promise<GlobalIdentityCatalog | null> {
  if (view.integrity !== "sealed") {
    return null;
  }

  try {
    const rawText = await view.text([GLOBAL_IDENTITY_CATALOG_KEY]);
    if (!rawText || typeof rawText !== "string") {
      return null; // NO view.json fallback
    }

    const utf8Bytes = ENCODER.encode(rawText).byteLength;
    if (utf8Bytes > MAX_CATALOG_BYTES) {
      return null;
    }

    let parsed: unknown;
    try {
      parsed = JSON.parse(rawText);
    } catch {
      return null;
    }
    if (!parsed) return null;
    return validateCatalogCandidate(parsed);
  } catch {
    return null;
  }
}
