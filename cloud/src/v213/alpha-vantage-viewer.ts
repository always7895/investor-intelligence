/** Alpha Vantage values are for the owner only (operator 2026-10-11, R/OPERATOR-DECISION-S1-AND-ALPHAVANTAGE-FRIENDS-20261011.txt, Q2).
 *
 * scripts/build_market_quotes_options.py writes a US spot from Alpha Vantage GLOBAL_QUOTE (source label below, source_url on
 * www.alphavantage.co) when Yahoo cannot quote the underlying. That spot reaches the Worker twice: as the row of the sealed quotes
 * object `v213:quotes:v1` (equity lookup) and, unlabelled, as `spot` and the yields of the cycles of the sealed options object
 * `v213:options:v2` built from it (covered-call card, options guidance). In all_friends mode every viewer that is not the owner
 * (ownerState not "owner"; a failed owner lookup counts as not owner) reads those objects through the view below instead.
 *
 * The rule is applied AFTER the sealed snapshot was digest-verified and only to the parsed copy handed to the reader: the verified
 * bytes (`text()`) are never changed, so digest-bound consumers (options-coverage recomputes a sha256 of the options body and only
 * counts rows, it renders no price) are unaffected. The owner and owner_only mode never get this view (byte-identical to today).
 *
 * Identification is closed, never a substring search: a quote row is Alpha Vantage derived when its `source_url` host is exactly
 * www.alphavantage.co, or its `source` is exactly the producer's label, or its `source_family` / `source_id` is exactly one of the
 * producer's family names. A row with other or unknown provenance stays as today. An options key is Alpha Vantage derived when the
 * quote row of the same key is. */
import type { PublicSnapshotView } from "./public-snapshot";

export const ALPHA_VANTAGE_HOST = "www.alphavantage.co";
/** The exact label scripts/build_market_quotes_options.py writes on the fallback quote row. */
export const ALPHA_VANTAGE_SOURCE_LABEL = "Alpha Vantage GLOBAL_QUOTE（免費金鑰，最近交易日；Yahoo 備援）";
const ALPHA_VANTAGE_FAMILIES: ReadonlySet<string> = new Set(["alpha_vantage_market", "alpha_vantage_adjusted"]);
/** What a non-owner sees where an Alpha Vantage spot would be. Names no provider. */
export const SPOT_UNAVAILABLE_ZH = "現價暫不可用";
const OPTIONS_SPOT_UNAVAILABLE_ZH = `${SPOT_UNAVAILABLE_ZH}，本輪不提供此標的的備兌買權建議。`;

// Same literals as market-observations.ts (QUOTES_KEY / OPTIONS_KEY); copied, not imported, so this module stays a leaf of
// public-snapshot.ts. If they drift, the covered-call and lookup friend tests stop seeing the redaction and fail.
const QUOTES_SCHEMA = "v213-quotes-v1";
const OPTIONS_SCHEMA = "v213-options-v2";
const QUOTES_KEY = "v213:quotes:v1";

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

/** Closed provenance rule for one sealed quote row. */
export function isAlphaVantageProvenance(row: unknown): boolean {
  if (!isRecord(row)) return false;
  if (row.source === ALPHA_VANTAGE_SOURCE_LABEL) return true;
  for (const field of ["source_family", "source_id"] as const) {
    const value = row[field];
    if (typeof value === "string" && ALPHA_VANTAGE_FAMILIES.has(value)) return true;
  }
  if (typeof row.source_url !== "string") return false;
  try {
    return new URL(row.source_url).hostname === ALPHA_VANTAGE_HOST;
  } catch {
    return false;
  }
}

function alphaVantageKeys(quotesDocument: unknown): Set<string> {
  const keys = new Set<string>();
  if (!isRecord(quotesDocument) || !isRecord(quotesDocument.quotes)) return keys;
  for (const [key, row] of Object.entries(quotesDocument.quotes)) if (isAlphaVantageProvenance(row)) keys.add(key);
  return keys;
}

/** The parsed quotes object without its Alpha Vantage rows (a missing row is the reader's existing "no quote" state). */
function redactQuotes(document: Record<string, unknown>): Record<string, unknown> {
  if (!isRecord(document.quotes)) return document;
  const kept = Object.entries(document.quotes).filter(([, row]) => !isAlphaVantageProvenance(row));
  return { ...document, quotes: Object.fromEntries(kept) };
}

/** The parsed options object with every cycle of an Alpha Vantage derived underlying replaced by the reader's existing
 * producer-declared `unavailable` state (same period keys as the original entry). */
function redactOptions(document: Record<string, unknown>, restricted: ReadonlySet<string>): Record<string, unknown> {
  if (restricted.size === 0 || !isRecord(document.options)) return document;
  const options: Record<string, unknown> = {};
  for (const [key, cycles] of Object.entries(document.options)) {
    options[key] = restricted.has(key) && isRecord(cycles)
      ? Object.fromEntries(Object.keys(cycles).map(period => [period, { unavailable: OPTIONS_SPOT_UNAVAILABLE_ZH }]))
      : cycles;
  }
  return { ...document, options };
}

/** The view a non-owner reads: same verified snapshot, same bytes from text(), Alpha Vantage derived values withheld from json(). */
export function withAlphaVantageOwnerOnly(inner: PublicSnapshotView): PublicSnapshotView {
  if (inner.integrity === "invalid") return inner;
  return Object.freeze<PublicSnapshotView>({
    runId: inner.runId,
    kind: inner.kind,
    integrity: inner.integrity,
    ...(typeof inner.hasSealedObject === "function" ? { hasSealedObject: (key: string) => inner.hasSealedObject!(key) } : {}),
    text: logicalKeys => inner.text(logicalKeys),
    async json<T>(logicalKeys: string[]): Promise<T | null> {
      const document = await inner.json<unknown>(logicalKeys);
      if (!isRecord(document)) return document as T | null;
      if (document.schema === QUOTES_SCHEMA) return redactQuotes(document) as T;
      if (document.schema === OPTIONS_SCHEMA) {
        // The quotes object is read from the same verified snapshot; the join key is the options key = the quote symbol.
        const restricted = alphaVantageKeys(await inner.json<unknown>([QUOTES_KEY]));
        return redactOptions(document, restricted) as T;
      }
      return document as T;
    },
  });
}
