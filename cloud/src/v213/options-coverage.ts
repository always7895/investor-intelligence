/** Global options SOURCE and GAP status (G1A): a PUBLIC, METADATA-ONLY view of what the canonical catalog declares and of what the sealed R75
 * snapshot actually contains. It is NOT a quote product, NOT live, NOT a coverage guarantee and NOT a rights decision.
 *
 * Sealed lazy object `v213:options-coverage:v1`, produced by scripts/publish_sealed_snapshot.py and bound by the same seal. Nothing in the body
 * is authority. The loader (1) rejects a raw body over 200000 UTF-8 bytes BEFORE JSON.parse, (2) validates the strict bounded shape,
 * (3) DERIVES every declared section itself from the SAME canonical catalog and the SAME unchanged ADR routing map this Worker imports
 * (provider rows including name, the jurisdiction -> unique provider-id relation with the literal declared codes only, and the local
 * covered-call routing markets from the covered_markets KEYS) and requires exact equality, and the page prints only that derived projection;
 * (4) rechecks the options link by sha256 and byte length of the sealed options body and recomputes every observed row under the SAME rules
 * as the real public loader (loadDetailedOptionObservation: canonical document clock, at most 5 minutes in the future and 6 hours old,
 * v2 shape, ONLY weekly and monthly, producer-unavailable stays unavailable, validateCoveredCallCycle with its period) plus the canonical
 * admission predicate. A row that cannot be proven is UNKNOWN, never zero and never assumed.
 *
 * The verified result is issued through a module-private WeakMap keyed by the identity of a frozen wrapper that exposes only a status; the
 * deeply frozen projection never leaves the module. A spread, a clone, JSON or a hand-built object has no identity in the map and renders
 * as unavailable, and mutating anything a caller holds changes nothing. At render time the page rechecks the real current clock, the
 * document and counted-cycle freshness windows and the canonical admission of every observed row, without any network, so a projection
 * cannot outlive its own validity. This is not a sandbox against arbitrary privileged code. Catalog counts are catalog counts, never
 * independent confirmations; origin lineage is unknown and there is no corroboration metric; ticker-key counts are distinct sealed
 * option-document keys, not native underlyings, ISINs or chain completeness. The delayed covered-call scope of the public admission gate is NOT
 * broadened to EOD, index or Delta data. No private, raw strike/bid/ask, settlement, Delta or premium field exists in this DTO. */
import adrMap from "../../../config/option-adr-map-v1.json";
import catalog from "../../../config/public-options-provider-candidates.json";
import { assertLineMessages, type LineOutboundMessage } from "../line-messages";
import { isValidUtcIsoInstant, validateCoveredCallCycle } from "./covered-call";
import { OPTIONS_KEY } from "./market-observations";
import { admitPublicOption } from "./public-options-admission";
import type { PublicSnapshotView } from "./public-snapshot";

export const OPTIONS_COVERAGE_KEY = "v213:options-coverage:v1";
const MAX_BODY_BYTES = 200_000;
const MAX_AGE_MS = 6 * 3600_000;
const FUTURE_SKEW_MS = 300_000;
const MAX_PROVIDERS = 32;
const MAX_JURISDICTIONS = 32;
const MAX_LOCAL = 8;
const MAX_OBSERVED = 64;
const OBSERVED_SHOWN = 24;  // rows printed; the rest is counted explicitly
const PAGE_LIMIT = 4400;  // characters per text message, below the LINE text limit
const MAX_PAGES = 5;  // the LINE per-reply message cap
const COVERAGE_NOTES = new Set([
  "CATALOG_COUNT_IS_NOT_INDEPENDENT_CONFIRMATION", "DECLARED_IS_NOT_COLLECTED_OR_LIVE", "EOD_INDEX_AND_DELTA_NOT_ADMITTED_BY_THIS_VIEW",
  "NO_RAW_QUOTES_IN_THIS_OBJECT", "ORIGIN_LINEAGE_UNKNOWN_NO_CORROBORATION_METRIC", "UNCATALOGUED_JURISDICTIONS_ARE_NOT_COVERAGE",
]);
const RIGHTS_STATUSES = new Set(["review_before_enable", "reviewed_public_access", "automated_access_prohibited"]);
const ADAPTER_STATUSES = new Set(["not_implemented", "candidate_implemented", "adapter_reviewed", "not_permitted"]);
const ID_RE = /^[a-z0-9_]{1,64}$/;
const CODE_RE = /^[A-Z0-9_]{1,12}$/;
const ROLE_RE = /^[a-z0-9_]{1,64}$/;
const VENUE_RE = /^[A-Z0-9][A-Z0-9_.-]{0,31}$/;
const MARKET_RE = /^[A-Z]{2,12}$/;
const TICKER_KEY_RE = /^[A-Z0-9.\- ]{1,16}$/;  // the ticker syntax validateCoveredCallCycle enforces
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const HEX_RE = /^[0-9a-f]{64}$/;
// The G1 canonical UTC instant: seconds or exactly three fractional digits (length 20 or 24), a real calendar date, year 1..9999.
const INSTANT_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?Z$/;

export interface CoverageProvider {
  provider_id: string; name: string; authority: string; jurisdictions: string[]; data_roles: string[]; rights_status: string;
  rights_reviewed_at: string | null; adapter_status: string; runtime_enabled: boolean; line_quote_eligible: boolean;
}
export interface CoverageJurisdiction { code: string; provider_ids: string[]; catalog_provider_count: number }
export interface CoverageObserved {
  provider_id: string; jurisdiction: string; venue: string; instrument_kind: string; quote_basis: string; publication_scope: string;
  cycle_count: number; ticker_key_count: number; quote_as_of_max: string;
}
export type ObservedState = "VERIFIED_ADMITTED_ROWS" | "VERIFIED_NO_ADMITTED_ROWS_IN_SEALED_OPTIONS_BODY"
  | "UNKNOWN_NO_OPTIONS_BODY" | "UNKNOWN_LINK_OR_COUNT_MISMATCH";
export type OptionsCoverageStatus = "SNAPSHOT_UNAVAILABLE" | "COVERAGE_ABSENT" | "COVERAGE_SCHEMA_INVALID" | "COVERAGE_STALE" | "OK";
/** The ONLY public shape: a frozen wrapper that carries a status. Verified content lives in a module-private map. */
export interface OptionsCoverageResult { readonly status: OptionsCoverageStatus; readonly generated_at?: string }

interface RenderProjection {
  readonly generated_at: string;
  readonly issued_at: number;
  readonly valid_until: number;
  readonly providers: readonly CoverageProvider[];
  readonly jurisdictions: readonly CoverageJurisdiction[];
  readonly local_markets: readonly string[];
  readonly observed_state: ObservedState;
  readonly observed: readonly CoverageObserved[] | null;
  readonly observed_valid_until: number;
}
const ISSUED = new WeakMap<object, RenderProjection>();

function deepFreeze<T>(value: T): T {
  if (value !== null && typeof value === "object" && !Object.isFrozen(value)) {
    Object.freeze(value);
    for (const child of Object.values(value as Record<string, unknown>)) deepFreeze(child);
  }
  return value;
}
const plain = (status: OptionsCoverageStatus, generated_at?: string): OptionsCoverageResult =>
  Object.freeze(generated_at === undefined ? { status } : { status, generated_at });

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const exactKeys = (value: Record<string, unknown>, keys: readonly string[]): boolean => {
  const actual = Object.keys(value).sort();
  return actual.length === keys.length && [...keys].sort().every((key, index) => key === actual[index]);
};
const boundedText = (value: unknown, max: number): value is string =>
  typeof value === "string" && value.length >= 1 && value.length <= max && !/[\u0000-\u001f]/.test(value);
const stringList = (value: unknown, pattern: RegExp, min: number, max: number): string[] | null =>
  Array.isArray(value) && value.length >= min && value.length <= max && value.every(item => typeof item === "string" && pattern.test(item))
    ? [...value] as string[] : null;
const realDate = (raw: unknown): boolean => {
  if (typeof raw !== "string" || !DATE_RE.test(raw) || raw.startsWith("0000-")) return false;  // Python dates start at year 1
  const ms = Date.parse(`${raw}T00:00:00Z`);
  return Number.isFinite(ms) && new Date(ms).toISOString().slice(0, 10) === raw;
};
const validInstant = (raw: unknown): raw is string => {
  if (typeof raw !== "string" || (raw.length !== 20 && raw.length !== 24) || !INSTANT_RE.test(raw) || raw.startsWith("0000-")) return false;
  const ms = Date.parse(raw);
  if (!Number.isFinite(ms)) return false;
  const iso = new Date(ms).toISOString();  // always three fractional digits: rollover dates such as February 30 cannot round-trip
  return raw.length === 24 ? iso === raw : iso === `${raw.slice(0, 19)}.000Z`;
};
const sameList = (left: readonly unknown[], right: readonly unknown[]): boolean =>
  left.length === right.length && left.every((item, index) => item === right[index]);
const codepointCompare = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0);

interface ValidatedBody {
  generated_at: string;
  link: { key: string; sha256: string; utf8_bytes: number } | null;
  provider_count: number; production_selected: boolean;
  providers: CoverageProvider[]; jurisdictions: CoverageJurisdiction[]; local_markets: string[]; observed: CoverageObserved[];
}

/** Strict bounded shape of the sealed body. Mirrors validate_options_coverage_document in validate_v213_market_products.py. */
export function validateOptionsCoverage(raw: unknown): ValidatedBody | null {
  if (!isRecord(raw) || !exactKeys(raw, ["schema", "generated_at", "purpose", "options_link", "catalog_summary", "providers", "jurisdictions",
    "local_capabilities", "observed", "data_completeness", "notes"])) return null;
  if (raw.schema !== "v213-options-coverage-v1" || raw.purpose !== "SOURCE_COVERAGE_METADATA_ONLY" || raw.data_completeness !== "NOT_REAUDITED"
    || !validInstant(raw.generated_at)) return null;
  let link: ValidatedBody["link"] = null;
  if (raw.options_link !== null) {
    const item = raw.options_link;
    if (!isRecord(item) || !exactKeys(item, ["key", "sha256", "utf8_bytes"]) || item.key !== OPTIONS_KEY || typeof item.sha256 !== "string"
      || !HEX_RE.test(item.sha256) || typeof item.utf8_bytes !== "number" || !Number.isSafeInteger(item.utf8_bytes)
      || item.utf8_bytes < 1 || item.utf8_bytes > 1_900_000) return null;
    link = { key: item.key, sha256: item.sha256, utf8_bytes: item.utf8_bytes };
  }
  const summary = raw.catalog_summary;
  if (!isRecord(summary) || !exactKeys(summary, ["catalog_provider_count", "public_admitted_provider_count", "production_provider_selected"])
    || !Number.isInteger(summary.catalog_provider_count) || (summary.catalog_provider_count as number) < 0 || (summary.catalog_provider_count as number) > MAX_PROVIDERS
    || !Number.isInteger(summary.public_admitted_provider_count) || (summary.public_admitted_provider_count as number) < 0
    || (summary.public_admitted_provider_count as number) > MAX_PROVIDERS || typeof summary.production_provider_selected !== "boolean") return null;
  if (!Array.isArray(raw.notes) || raw.notes.length > 8 || new Set(raw.notes).size !== raw.notes.length
    || !raw.notes.every(note => typeof note === "string" && COVERAGE_NOTES.has(note))) return null;
  if (!Array.isArray(raw.providers) || raw.providers.length > MAX_PROVIDERS || !Array.isArray(raw.jurisdictions)
    || raw.jurisdictions.length > MAX_JURISDICTIONS || !Array.isArray(raw.local_capabilities) || raw.local_capabilities.length > MAX_LOCAL
    || !Array.isArray(raw.observed) || raw.observed.length > MAX_OBSERVED) return null;
  const providers: CoverageProvider[] = [];
  for (const item of raw.providers) {
    if (!isRecord(item) || !exactKeys(item, ["provider_id", "name", "authority", "jurisdictions", "data_roles", "rights_status",
      "rights_reviewed_at", "adapter_status", "runtime_enabled", "line_quote_eligible", "public_admission", "declared"])) return null;
    const jurisdictions = stringList(item.jurisdictions, CODE_RE, 1, 8);
    const roles = stringList(item.data_roles, ROLE_RE, 1, 8);
    if (typeof item.provider_id !== "string" || !ID_RE.test(item.provider_id) || !boundedText(item.name, 120) || !boundedText(item.authority, 120)
      || !jurisdictions || !roles || typeof item.rights_status !== "string" || !RIGHTS_STATUSES.has(item.rights_status)
      || !(item.rights_reviewed_at === null || realDate(item.rights_reviewed_at)) || typeof item.adapter_status !== "string"
      || !ADAPTER_STATUSES.has(item.adapter_status) || typeof item.runtime_enabled !== "boolean" || typeof item.line_quote_eligible !== "boolean"
      || (item.public_admission !== "ADMITTED" && item.public_admission !== "NOT_ADMITTED") || item.declared !== "CATALOG_DECLARED_UNVERIFIED") return null;
    providers.push({ provider_id: item.provider_id, name: item.name, authority: item.authority, jurisdictions, data_roles: roles,
      rights_status: item.rights_status, rights_reviewed_at: item.rights_reviewed_at as string | null, adapter_status: item.adapter_status,
      runtime_enabled: item.runtime_enabled, line_quote_eligible: item.line_quote_eligible });
  }
  if (new Set(providers.map(item => item.provider_id)).size !== providers.length) return null;
  const jurisdictions: CoverageJurisdiction[] = [];
  for (const item of raw.jurisdictions) {
    if (!isRecord(item) || !exactKeys(item, ["code", "provider_ids", "catalog_provider_count"]) || typeof item.code !== "string" || !CODE_RE.test(item.code)) return null;
    const ids = stringList(item.provider_ids, ID_RE, 1, 32);
    if (!ids || new Set(ids).size !== ids.length || item.catalog_provider_count !== ids.length) return null;
    jurisdictions.push({ code: item.code, provider_ids: ids, catalog_provider_count: ids.length });
  }
  const localMarkets: string[] = [];
  for (const item of raw.local_capabilities) {
    if (!isRecord(item) || !exactKeys(item, ["market", "capability", "status"]) || typeof item.market !== "string" || !MARKET_RE.test(item.market)
      || item.capability !== "COVERED_CALL_DELAYED_LOCAL_CANDIDATE" || item.status !== "LOCAL_UNADMITTED_NO_CATALOG_IDENTITY") return null;
    localMarkets.push(item.market);
  }
  const observed: CoverageObserved[] = [];
  for (const item of raw.observed) {
    if (!isRecord(item) || !exactKeys(item, ["provider_id", "jurisdiction", "venue", "instrument_kind", "quote_basis", "publication_scope",
      "cycle_count", "ticker_key_count", "quote_as_of_max"])) return null;
    if (typeof item.provider_id !== "string" || !ID_RE.test(item.provider_id) || typeof item.jurisdiction !== "string" || !CODE_RE.test(item.jurisdiction)
      || typeof item.venue !== "string" || !VENUE_RE.test(item.venue) || item.instrument_kind !== "equity_option" || item.quote_basis !== "delayed"
      || item.publication_scope !== "public_line_quote" || !Number.isInteger(item.cycle_count) || (item.cycle_count as number) < 1
      || (item.cycle_count as number) > 100000 || !Number.isInteger(item.ticker_key_count) || (item.ticker_key_count as number) < 1
      || (item.ticker_key_count as number) > 100000 || !validInstant(item.quote_as_of_max)) return null;
    observed.push({ provider_id: item.provider_id, jurisdiction: item.jurisdiction, venue: item.venue, instrument_kind: item.instrument_kind,
      quote_basis: item.quote_basis, publication_scope: item.publication_scope, cycle_count: item.cycle_count as number,
      ticker_key_count: item.ticker_key_count as number, quote_as_of_max: item.quote_as_of_max });
  }
  return { generated_at: raw.generated_at, link, provider_count: summary.catalog_provider_count as number,
    production_selected: summary.production_provider_selected, providers, jurisdictions, local_markets: localMarkets, observed };
}

interface Derived {
  providers: CoverageProvider[]; jurisdictions: CoverageJurisdiction[]; local_markets: string[]; production_selected: boolean;
}

/** Everything the page may declare, derived ONLY from the canonical catalog JSON and the ADR map keys imported by this Worker. */
function deriveFromCanonical(): Derived | null {
  const root: unknown = catalog;
  if (!isRecord(root) || !Array.isArray(root.providers) || root.providers.length > MAX_PROVIDERS || typeof root.production_quote_provider_selected !== "boolean") return null;
  const providers: CoverageProvider[] = [];
  const byCode = new Map<string, string[]>();
  for (const item of root.providers) {
    if (!isRecord(item)) return null;
    const jurisdictions = stringList(item.jurisdictions, CODE_RE, 1, 8);
    const roles = stringList(item.data_roles, ROLE_RE, 1, 8);
    if (typeof item.id !== "string" || !ID_RE.test(item.id) || !boundedText(item.name, 120) || !boundedText(item.authority, 120) || !jurisdictions || !roles
      || typeof item.rights_status !== "string" || !RIGHTS_STATUSES.has(item.rights_status)
      || !(item.rights_reviewed_at === null || realDate(item.rights_reviewed_at)) || typeof item.adapter_status !== "string"
      || !ADAPTER_STATUSES.has(item.adapter_status) || typeof item.runtime_enabled !== "boolean" || typeof item.line_quote_eligible !== "boolean") return null;
    providers.push({ provider_id: item.id, name: item.name, authority: item.authority, jurisdictions, data_roles: roles,
      rights_status: item.rights_status, rights_reviewed_at: item.rights_reviewed_at as string | null, adapter_status: item.adapter_status,
      runtime_enabled: item.runtime_enabled, line_quote_eligible: item.line_quote_eligible });
    for (const code of new Set(jurisdictions)) byCode.set(code, [...(byCode.get(code) ?? []), item.id]);
  }
  if (new Set(providers.map(item => item.provider_id)).size !== providers.length || byCode.size > MAX_JURISDICTIONS) return null;
  // The literal declared codes only: a GLOBAL role code is its own row and never expands to countries.
  const jurisdictions = [...byCode.entries()].sort((a, b) => codepointCompare(a[0], b[0]))
    .map(([code, ids]) => ({ code, provider_ids: ids, catalog_provider_count: ids.length }));
  const routing = (adrMap as unknown as { covered_markets?: unknown }).covered_markets;
  if (!isRecord(routing)) return null;
  const localMarkets = Object.keys(routing).sort(codepointCompare);
  if (localMarkets.length > MAX_LOCAL || !localMarkets.every(market => MARKET_RE.test(market))) return null;
  return { providers, jurisdictions, local_markets: localMarkets, production_selected: root.production_quote_provider_selected };
}

function sameProvider(a: CoverageProvider, b: CoverageProvider): boolean {
  return a.provider_id === b.provider_id && a.name === b.name && a.authority === b.authority && sameList(a.jurisdictions, b.jurisdictions)
    && sameList(a.data_roles, b.data_roles) && a.rights_status === b.rights_status && a.rights_reviewed_at === b.rights_reviewed_at
    && a.adapter_status === b.adapter_status && a.runtime_enabled === b.runtime_enabled && a.line_quote_eligible === b.line_quote_eligible;
}

/** Every declared section of the body must equal the Worker's own derivation (a forged or skewed body is invalid, never merged). */
function matchesDerived(body: ValidatedBody, derived: Derived): boolean {
  return body.provider_count === derived.providers.length && body.production_selected === derived.production_selected
    && body.providers.length === derived.providers.length && body.providers.every((row, index) => sameProvider(row, derived.providers[index]!))
    && body.jurisdictions.length === derived.jurisdictions.length
    && body.jurisdictions.every((row, index) => {
      const expected = derived.jurisdictions[index]!;
      return row.code === expected.code && sameList(row.provider_ids, expected.provider_ids) && row.catalog_provider_count === expected.catalog_provider_count;
    })
    && sameList(body.local_markets, derived.local_markets);
}

async function sha256Hex(text: string): Promise<{ hex: string; bytes: number }> {
  const encoded = new TextEncoder().encode(text);
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", encoded));
  return { hex: [...digest].map(byte => byte.toString(16).padStart(2, "0")).join(""), bytes: encoded.byteLength };
}

const rowKey = (row: CoverageObserved) => [row.provider_id, row.jurisdiction, row.venue, row.instrument_kind, row.quote_basis, row.publication_scope].join("|");

/** Worker recomputation of the admitted rows under the SAME rules as the real public loader. null = cannot be proven (UNKNOWN). */
async function recomputeObserved(view: PublicSnapshotView, link: NonNullable<ValidatedBody["link"]>, now: number):
Promise<{ rows: CoverageObserved[]; validUntil: number } | null> {
  const text = await view.text([OPTIONS_KEY]);
  if (text === null) return null;
  const measured = await sha256Hex(text);
  if (measured.hex !== link.sha256 || measured.bytes !== link.utf8_bytes) return null;
  let doc: unknown;
  try { doc = JSON.parse(text); } catch { return null; }
  if (!isRecord(doc) || doc.schema !== "v213-options-v2" || !isRecord(doc.options) || !isValidUtcIsoInstant(doc.generated_at)) return null;
  const docTime = Date.parse(doc.generated_at);
  if (docTime - now > FUTURE_SKEW_MS || now - docTime > MAX_AGE_MS) return null;  // a future-invalid or stale document counts nothing
  let validUntil = docTime + MAX_AGE_MS;
  const groups = new Map<string, { row: CoverageObserved; tickers: Set<string>; asOf: number }>();
  for (const [ticker, cycles] of Object.entries(doc.options)) {
    if (!isRecord(cycles)) return null;  // a corrupt ticker entry makes the whole document unprovable
    if (!TICKER_KEY_RE.test(ticker)) continue;
    for (const period of ["weekly", "monthly"] as const) {  // no arbitrary period keys are interpreted
      if (!Object.hasOwn(cycles, period)) continue;
      const entry = cycles[period];
      if (isRecord(entry) && typeof entry.unavailable === "string") continue;  // producer-declared unavailable stays unavailable
      const cycle = validateCoveredCallCycle(entry, now, doc.generated_at, period);
      if (!cycle || !validInstant(cycle.timestamp) || !admitPublicOption(cycle, now).ok) continue;  // format-valid AND admitted by the canonical policy
      const base: CoverageObserved = { provider_id: cycle.provider_id as string, jurisdiction: cycle.jurisdiction as string, venue: cycle.venue as string,
        instrument_kind: cycle.instrument_kind as string, quote_basis: cycle.quote_basis, publication_scope: cycle.publication_scope as string,
        cycle_count: 0, ticker_key_count: 0, quote_as_of_max: cycle.timestamp };
      const key = rowKey(base);
      const stamp = Date.parse(cycle.timestamp);
      const group = groups.get(key) ?? { row: base, tickers: new Set<string>(), asOf: -Infinity };
      group.row.cycle_count += 1;
      group.tickers.add(ticker);
      if (stamp > group.asOf) { group.asOf = stamp; group.row.quote_as_of_max = cycle.timestamp; }
      groups.set(key, group);
      validUntil = Math.min(validUntil, stamp + MAX_AGE_MS);
    }
  }
  const rows = [...groups.values()].map(group => ({ ...group.row, ticker_key_count: group.tickers.size })).sort((a, b) => codepointCompare(rowKey(a), rowKey(b)));
  return { rows, validUntil };
}

function sameObserved(left: readonly CoverageObserved[], right: readonly CoverageObserved[]): boolean {
  const a = [...left].sort((x, y) => codepointCompare(rowKey(x), rowKey(y)));
  const b = [...right].sort((x, y) => codepointCompare(rowKey(x), rowKey(y)));
  return a.length === b.length && a.every((row, index) => rowKey(row) === rowKey(b[index]!) && row.cycle_count === b[index]!.cycle_count
    && row.ticker_key_count === b[index]!.ticker_key_count && row.quote_as_of_max === b[index]!.quote_as_of_max);
}

/** Typed loader over the existing sealed lazy reader. Never reads an unsealed or cached value. */
export async function loadOptionsCoverage(view: PublicSnapshotView, now: number = Date.now()): Promise<OptionsCoverageResult> {
  if (view.integrity !== "sealed") return plain("SNAPSHOT_UNAVAILABLE");
  if (typeof view.hasSealedObject !== "function" || !view.hasSealedObject(OPTIONS_COVERAGE_KEY)) return plain("COVERAGE_ABSENT");
  const text = await view.text([OPTIONS_COVERAGE_KEY]);
  if (text === null) return plain("COVERAGE_ABSENT");
  // The raw sealed text is bounded BEFORE any JSON.parse (UTF-8 bytes are never fewer than UTF-16 code units).
  if (text.length > MAX_BODY_BYTES || new TextEncoder().encode(text).byteLength > MAX_BODY_BYTES) return plain("COVERAGE_SCHEMA_INVALID");
  let raw: unknown;
  try { raw = JSON.parse(text); } catch { return plain("COVERAGE_SCHEMA_INVALID"); }
  const valid = validateOptionsCoverage(raw);
  const derived = deriveFromCanonical();
  if (!valid || !derived || !matchesDerived(valid, derived)) return plain("COVERAGE_SCHEMA_INVALID");
  const generated = Date.parse(valid.generated_at);
  if (generated - now > FUTURE_SKEW_MS) return plain("COVERAGE_SCHEMA_INVALID");
  if (now - generated > MAX_AGE_MS) return plain("COVERAGE_STALE", valid.generated_at);
  let observedState: ObservedState;
  let observed: CoverageObserved[] | null;
  let observedValidUntil = generated + MAX_AGE_MS;
  if (valid.link === null) {
    observedState = "UNKNOWN_NO_OPTIONS_BODY";
    observed = null;
  } else {
    const recomputed = await recomputeObserved(view, valid.link, now);
    if (recomputed === null || !sameObserved(recomputed.rows, valid.observed)) {
      observedState = "UNKNOWN_LINK_OR_COUNT_MISMATCH";
      observed = null;
    } else {
      observed = recomputed.rows;
      observedValidUntil = recomputed.validUntil;
      observedState = recomputed.rows.length === 0 ? "VERIFIED_NO_ADMITTED_ROWS_IN_SEALED_OPTIONS_BODY" : "VERIFIED_ADMITTED_ROWS";
    }
  }
  const wrapper = plain("OK", valid.generated_at);
  ISSUED.set(wrapper, deepFreeze({
    generated_at: valid.generated_at, issued_at: now, valid_until: generated + MAX_AGE_MS,
    providers: derived.providers, jurisdictions: derived.jurisdictions, local_markets: derived.local_markets,
    observed_state: observedState, observed, observed_valid_until: observedValidUntil,
  }));
  return wrapper;
}

const CAVEAT = "宣告 ≠ 已收集 ≠ 已准入 ≠ 即時；非報價、非涵蓋保證；EOD、指數、Delta 不在本視圖；本服務不下單。";
const NAV = ["快捷指令：", "• 期權功能入口：期權", "• 回功能選單：選單"];
const TITLE = "【全球期權來源與缺口】來源狀態說明（非即時報價、非涵蓋保證）";

function toMessages(pages: readonly (readonly string[])[]): LineOutboundMessage[] {
  const total = pages.length;
  const messages: LineOutboundMessage[] = pages.map((page, index) => ({
    type: "text" as const,
    text: [...(total > 1 ? [`（第 ${index + 1}/${total} 頁）`] : []), ...page, "", CAVEAT, ...(index === total - 1 ? ["", ...NAV] : [])].join("\n"),
  }));
  assertLineMessages(messages);
  return messages;
}

/** Complete bounded pages: lines are never cut; a line that cannot fit is replaced by an explicit omission count. Every page carries the caveat. */
function paginate(lines: readonly string[]): string[][] | null {
  const budget = PAGE_LIMIT - CAVEAT.length - NAV.join("\n").length - 40;
  const pages: string[][] = [[]];
  let used = 0;
  for (const line of lines) {
    if (line.length > budget) return null;
    if (used + line.length + 1 > budget && pages[pages.length - 1]!.length > 0) { pages.push([]); used = 0; }
    pages[pages.length - 1]!.push(line);
    used += line.length + 1;
  }
  return pages.length <= MAX_PAGES ? pages : null;
}

function unavailable(status: string, generatedAt?: unknown): LineOutboundMessage[] {
  const known = status === "SNAPSHOT_UNAVAILABLE" || status === "COVERAGE_ABSENT" || status === "COVERAGE_STALE" ? status : "COVERAGE_SCHEMA_INVALID";
  const reason = known === "SNAPSHOT_UNAVAILABLE" ? "目前沒有已封存驗收的公開快照。"
    : known === "COVERAGE_ABSENT" ? "當輪已封存快照不含來源與缺口物件。"
      : known === "COVERAGE_STALE" ? `來源與缺口物件已逾時（產生於 ${validInstant(generatedAt) ? generatedAt : "未知"}，超過 6 小時有效上限）。`
        : "來源與缺口物件未通過驗證、與目錄不符或不是由本模組驗證簽發，已拒絕顯示。";
  return toMessages([[TITLE, `OPTIONS_COVERAGE_UNAVAILABLE（${known}）：${reason}`, "不以舊資料、快取或推測代替；沒有任何報價因此被視為可用。"]]);
}

/** Text presentation (both LINE modes). Only the module-private verified projection is printed, never a caller-held field. */
export function buildOptionsCoverageMessages(result: OptionsCoverageResult, _isText = true): LineOutboundMessage[] {
  if (result === null || typeof result !== "object") return unavailable("COVERAGE_SCHEMA_INVALID");
  const projection = ISSUED.get(result);
  if (!projection) return unavailable(result.status === "OK" ? "COVERAGE_SCHEMA_INVALID" : String(result.status), result.generated_at);
  const now = Date.now();  // the real current clock, never a payload time
  if (now > projection.valid_until || now < projection.issued_at - FUTURE_SKEW_MS) return unavailable("COVERAGE_STALE", projection.generated_at);
  let observed = projection.observed;
  let observedState = projection.observed_state;
  if (observed !== null && observed.length > 0
    && (now > projection.observed_valid_until || observed.some(row => !admitPublicOption(row, now).ok))) {
    observed = null;  // a counted cycle aged out or an admission window changed since loading: no late stale-positive count
    observedState = "UNKNOWN_LINK_OR_COUNT_MISMATCH";
  }
  const lines: string[] = [TITLE, `快照產生時間：${projection.generated_at}`, "以下只是來源與缺口的中繼資料，不含任何價格。"];
  if (observedState === "VERIFIED_ADMITTED_ROWS" && observed && observed.length > 0) {
    lines.push("已驗證的公開准入資料（本 Worker 依自身目錄與封存期權本文重新計算；延遲備兌買權，非 EOD、非指數；標的數為封存期權文件的不同代號鍵，不是原生標的）：");
    for (const row of observed.slice(0, OBSERVED_SHOWN)) {
      lines.push(`• ${row.provider_id}｜${row.jurisdiction}/${row.venue}｜${row.cycle_count} 個週期、${row.ticker_key_count} 個代號鍵｜最新報價時間 ${row.quote_as_of_max}`);
    }
    if (observed.length > OBSERVED_SHOWN) lines.push(`（共 ${observed.length} 列，顯示 ${OBSERVED_SHOWN} 列，另有 ${observed.length - OBSERVED_SHOWN} 列未顯示）`);
  } else if (observedState === "VERIFIED_NO_ADMITTED_ROWS_IN_SEALED_OPTIONS_BODY") {
    lines.push("本快照的封存期權本文中，沒有任何通過目錄准入的週期；這只描述本快照，不代表其他地方沒有收集到資料（尚未重新稽核）。");
  } else {
    lines.push("已准入資料筆數與時間：未知（無法以封存期權本文證明或已過有效期）；不以 0 或推測代替。");
  }
  if (projection.local_markets.length > 0) {
    lines.push(`本機路由宣告（來自備兌買權路由設定，不是觀察到的資料；此本機生產路徑未取得目錄身分，不代表整個國家沒有目錄來源）：${projection.local_markets.join("、")}。`);
  }
  const providerLines = projection.providers.map(row =>
    `• ${row.provider_id}｜${row.authority}｜${row.jurisdictions.join("/")}｜權利:${row.rights_status}｜轉接:${row.adapter_status}｜宣告未驗證`);
  const jurisdictionLines = projection.jurisdictions.map(row => `• ${row.code}：目錄來源 ${row.catalog_provider_count} 筆（宣告，不代表已收集或可用）`);
  const tail = ["未列出的國家或地區：沒有目錄來源或屬未知，未列出不代表涵蓋；ADR 路徑是替代標的，不是本地市場期權。",
    "目錄筆數只是目錄筆數，不是獨立佐證；原始生產者血緣未知，不計佐證。"];
  const full = [...lines, `目錄宣告的來源（共 ${providerLines.length} 筆）：`, ...providerLines, "目錄涵蓋的司法管轄區（依目錄原文代碼，GLOBAL 只是角色代碼，不代表所有國家）：", ...jurisdictionLines, ...tail];
  let pages = paginate(full);
  if (pages === null) {  // compact form, still complete: provider ids on one bounded line each page
    const compact = [...lines, `目錄宣告的來源（共 ${providerLines.length} 筆，僅列代號）：${projection.providers.map(row => row.provider_id).join("、")}`,
      "目錄涵蓋的司法管轄區（依目錄原文代碼）：" + projection.jurisdictions.map(row => `${row.code}(${row.catalog_provider_count})`).join("、"), ...tail];
    pages = paginate(compact);
  }
  return pages === null ? unavailable("COVERAGE_SCHEMA_INVALID") : toMessages(pages);
}
