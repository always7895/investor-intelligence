/** The ONE Worker public-option rights predicate (L-RIGHTS). Authority is the SAME canonical catalog the Python gate audits
 * (config/public-options-provider-candidates.json), imported at build time: an immutable projection of one authority, not a
 * second editable list. Nothing here trusts a payload: a rights label, a currency, free-form provenance, an `admission_status`
 * string or a caller-supplied flag can never admit a row. A row only carries the identity it CLAIMS (provider_id, jurisdiction,
 * venue, instrument_kind, quote_basis, publication_scope); admission needs the catalog itself to enable that exact provider
 * and list that exact scope.
 *
 * The WHOLE imported catalog must satisfy every catalog-local rule of `audit_public_options_providers` and `_scope_findings`
 * (public_options_provider_gate.py) BEFORE any requested entry is considered: one malformed provider, even an inactive or
 * unrelated one, makes the policy unusable, exactly as in Python. The field names, vocabularies and pinned provider ids below
 * are safety-invariant constants mirrored from Python, not a second approval catalog; nothing here admits a provider. The Python
 * audit also reads repository context a deployed Worker cannot see (cloud/wrangler.toml, the development-provider file,
 * runtime-policy.json, the builder source); those are gate-context checks, not catalog facts, and are NOT run here. Known
 * unproven source differences (URL parsing, Python's lenient str() coercion that is stricter here, UTC day boundary) are left
 * for final verification. Admission is judged against the real current time; format validators stay reusable for local data
 * and every PUBLIC call site must call this independently. Packaging of the catalog and same-source identity are verified by
 * later gates (NOT_RUN here). */
import catalog from "../../../config/public-options-provider-candidates.json";

export const OPTION_RIGHTS_NOT_ADMITTED = "OPTION_RIGHTS_NOT_ADMITTED";
export const OPTION_RIGHTS_NOT_ADMITTED_ZH = "期權報價未取得公開散布權利准入（OPTION_RIGHTS_NOT_ADMITTED）；僅限本機研究，不公開顯示。";

/** The dedicated typed renderer failure: the ONLY error a public caller may turn into an unavailable report. */
export class OptionRightsNotAdmittedError extends Error {
  readonly code = OPTION_RIGHTS_NOT_ADMITTED;
  constructor() {
    super(OPTION_RIGHTS_NOT_ADMITTED);
    this.name = "OptionRightsNotAdmittedError";
  }
}

export type PublicOptionAdmission =
  | { readonly ok: true; readonly provider_id: string }
  | { readonly ok: false; readonly reason: typeof OPTION_RIGHTS_NOT_ADMITTED };

const DENIED: PublicOptionAdmission = { ok: false, reason: OPTION_RIGHTS_NOT_ADMITTED };
const DAY_MS = 86_400_000;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const VENUE_RE = /^[A-Z0-9][A-Z0-9_.-]{0,31}$/;
const TOP_FIELDS = new Set(["schema_version", "purpose", "automatic_activation", "owner_watchlist_inheritance",
  "ibkr_or_broker_account_fallback", "paid_fallback", "production_quote_provider_selected", "providers"]);
const ROOT_FALSE_FLAGS = ["automatic_activation", "owner_watchlist_inheritance", "ibkr_or_broker_account_fallback", "paid_fallback"];
const REQUIRED_FIELDS = ["id", "name", "authority", "jurisdictions", "data_roles", "official_url", "rights_evidence_url",
  "rights_status", "automated_access_allowed", "rights_reviewed_at", "review_notes", "adapter_status", "runtime_enabled",
  "line_quote_eligible"];
const ALL_FIELDS = new Set([...REQUIRED_FIELDS, "admitted_scopes", "review_valid_through"]);
const RIGHTS_STATUSES = new Set(["review_before_enable", "reviewed_public_access", "automated_access_prohibited"]);
const ADAPTER_STATUSES = new Set(["not_implemented", "candidate_implemented", "adapter_reviewed", "not_permitted"]);
const PROHIBITED_IDS = ["cboe_public_options_market_data", "marketdata_app_free_forever", "occ_public_market_data",
  "tradier_broker_market_data_api"];
// Reviewed scope vocabulary (mirrors the Python gate): only real delayed equity-option quotes for public LINE display.
// EOD, theoretical and settlement observations are not upgraded and have no value here.
const INSTRUMENT_KINDS = new Set(["equity_option"]);
const QUOTE_BASES = new Set(["delayed"]);
const PUBLICATION_SCOPES = new Set(["public_line_quote"]);
const SCOPE_KEYS = ["instrument_kind", "jurisdiction", "publication_scope", "quote_basis", "venue"];

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const has = (record: Record<string, unknown>, key: string): boolean => Object.prototype.hasOwnProperty.call(record, key);

/** UTC midnight (ms) of a real YYYY-MM-DD calendar date, or null. */
function dayStart(raw: unknown): number | null {
  if (typeof raw !== "string" || !DATE_RE.test(raw)) return null;
  // Year 0000 is a valid ECMAScript extended-ISO year but not a Python date (1..9999): refuse it BEFORE Date.parse so the Worker and the
  // Python catalog audit agree. Nothing else about eligibility changes.
  if (raw.startsWith("0000-")) return null;
  const ms = Date.parse(`${raw}T00:00:00Z`);
  return Number.isFinite(ms) && new Date(ms).toISOString().slice(0, 10) === raw ? ms : null;
}

function safeHttps(raw: unknown): boolean {
  if (typeof raw !== "string") return false;
  try {
    const url = new URL(raw);
    return url.protocol === "https:" && url.hostname !== "" && url.username === "" && url.password === ""
      && (url.port === "" || url.port === "443");
  } catch {
    return false;
  }
}

const rightsReviewed = (provider: Record<string, unknown>): boolean =>
  provider.rights_status === "reviewed_public_access" && provider.automated_access_allowed === true
  && provider.adapter_status === "adapter_reviewed";

/** Mirror of _scope_findings: true when the optional review_valid_through / admitted_scopes fields are valid for this provider. */
function scopeFieldsOk(provider: Record<string, unknown>, enabled: boolean, today: number): boolean {
  if (enabled && (!has(provider, "admitted_scopes") || !has(provider, "review_valid_through"))) return false;
  if (has(provider, "review_valid_through")) {
    const through = dayStart(provider.review_valid_through);
    const reviewed = dayStart(provider.rights_reviewed_at);
    if (through === null) return false;
    if (reviewed === null || through < reviewed) return false;
    if (enabled && through < today) return false;
  }
  if (has(provider, "admitted_scopes")) {
    const scopes = provider.admitted_scopes;
    const jurisdictions = provider.jurisdictions;
    if (!Array.isArray(scopes) || scopes.length === 0) return false;
    for (const entry of scopes) {
      if (!isRecord(entry)) return false;
      const keys = Object.keys(entry).sort();
      if (keys.length !== SCOPE_KEYS.length || keys.some((key, index) => key !== SCOPE_KEYS[index])) return false;
      const { instrument_kind, jurisdiction, publication_scope, quote_basis, venue } = entry;
      if (typeof instrument_kind !== "string" || typeof jurisdiction !== "string" || typeof publication_scope !== "string"
        || typeof quote_basis !== "string" || typeof venue !== "string") return false;
      if (!Array.isArray(jurisdictions) || !jurisdictions.includes(jurisdiction)) return false;
      if (!VENUE_RE.test(venue) || !INSTRUMENT_KINDS.has(instrument_kind) || !QUOTE_BASES.has(quote_basis)
        || !PUBLICATION_SCOPES.has(publication_scope)) return false;
    }
  }
  return true;
}

interface ProviderFacts {
  readonly id: string;
  readonly authority: string;
  readonly jurisdictions: string[];
  readonly roles: string[];
  readonly fullyEligible: boolean;
}

/** Mirror of the per-provider rules of audit_public_options_providers; null means the provider (hence the catalog) is invalid. */
function checkProvider(provider: Record<string, unknown>, today: number): ProviderFacts | null {
  if (Object.keys(provider).some(key => !ALL_FIELDS.has(key)) || REQUIRED_FIELDS.some(key => !has(provider, key))) return null;
  const id = provider.id;
  // A padded id is refused, never normalized: Python trims ids before its duplicate and pinned-id checks, so an untrimmed id here could
  // hide a trimmed duplicate or a pinned-id mismatch. Canonical catalog ids carry no padding; the typed-string rule is stricter than Python.
  if (typeof id !== "string" || id.trim() === "" || id !== id.trim()) return null;
  const authority = typeof provider.authority === "string" ? provider.authority.trim() : "";
  const jurisdictions = provider.jurisdictions;
  const roles = provider.data_roles;
  if (!Array.isArray(jurisdictions) || jurisdictions.length === 0 || !Array.isArray(roles) || roles.length === 0) return null;
  if (!safeHttps(provider.official_url) || !safeHttps(provider.rights_evidence_url)) return null;
  if (typeof provider.review_notes !== "string" || provider.review_notes.trim() === "") return null;
  const status = provider.rights_status;
  const adapter = provider.adapter_status;
  const automation = provider.automated_access_allowed;
  const reviewedAt = provider.rights_reviewed_at;
  if (typeof status !== "string" || !RIGHTS_STATUSES.has(status) || typeof adapter !== "string" || !ADAPTER_STATUSES.has(adapter)) return null;
  if (automation !== null && typeof automation !== "boolean") return null;
  const reviewedDay = dayStart(reviewedAt);
  if (status === "review_before_enable") {
    if (automation !== null || reviewedAt !== null || adapter === "not_permitted") return null;
  } else if (status === "automated_access_prohibited") {
    if (automation !== false || reviewedDay === null || reviewedDay > today || adapter !== "not_permitted") return null;
  } else if (automation !== true || reviewedDay === null || reviewedDay > today || adapter === "not_permitted") {
    return null;  // reviewed_public_access
  }
  if (PROHIBITED_IDS.includes(id) && (status !== "automated_access_prohibited" || automation !== false || adapter !== "not_permitted")) return null;
  if (typeof provider.runtime_enabled !== "boolean" || typeof provider.line_quote_eligible !== "boolean") return null;
  const enabled = provider.runtime_enabled;
  const lineEligible = provider.line_quote_eligible;
  if ((enabled || lineEligible) && (status !== "reviewed_public_access" || automation !== true || adapter !== "adapter_reviewed")) return null;
  if (enabled !== lineEligible) return null;  // atomic pairing
  if (!scopeFieldsOk(provider, enabled || lineEligible, today)) return null;
  return {
    id, authority,
    jurisdictions: jurisdictions.map(item => String(item).trim()).filter(item => item !== ""),
    roles: roles.map(item => String(item).trim()).filter(item => item !== ""),
    fullyEligible: enabled && lineEligible && rightsReviewed(provider),
  };
}

/** Whole-catalog validation (catalog-local mirror of audit_public_options_providers). The providers, or null when ANY rule fails. */
function validCatalogProviders(root: unknown, today: number): Record<string, unknown>[] | null {
  if (!isRecord(root) || Object.keys(root).some(key => !TOP_FIELDS.has(key)) || root.schema_version !== 2) return null;
  if (ROOT_FALSE_FLAGS.some(flag => root[flag] !== false)) return null;
  const providers = root.providers;
  if (!Array.isArray(providers) || providers.length < 8) return null;
  const ids = new Set<string>();
  const authorities = new Set<string>();
  const jurisdictions = new Set<string>();
  const roles = new Set<string>();
  let fullyEligible = 0;
  const rows: Record<string, unknown>[] = [];
  for (const item of providers) {
    if (!isRecord(item)) return null;
    const facts = checkProvider(item, today);
    if (facts === null || ids.has(facts.id)) return null;
    ids.add(facts.id);
    if (facts.authority !== "") authorities.add(facts.authority);
    facts.jurisdictions.forEach(value => jurisdictions.add(value));
    facts.roles.forEach(value => roles.add(value));
    if (facts.fullyEligible) fullyEligible += 1;
    rows.push(item);
  }
  if (PROHIBITED_IDS.some(id => !ids.has(id))) return null;  // pinned decisions cannot be removed
  if (jurisdictions.size < 6 || authorities.size < 8) return null;
  if (![...roles].some(role => role.includes("quote")) || ![...roles].some(role => role.includes("open_interest"))) return null;
  const selected = root.production_quote_provider_selected;
  // Root selection truth table (same as the Python audit): a strict boolean that equals whether any provider is fully eligible.
  // false+none = valid and admits nothing (the current catalog); true+none and false+some are invalid; true+some can admit only after
  // every check above and the exact identity join below. A non-boolean value is invalid.
  if (typeof selected !== "boolean" || selected !== (fullyEligible > 0)) return null;
  return rows;
}

/** Public admission of one row (a covered-call cycle or an option contract quote) against the canonical catalog at `nowMs`.
 * Fail closed on every uncertainty, including an unexpected exception. */
export function admitPublicOption(subject: unknown, nowMs: number = Date.now()): PublicOptionAdmission {
  try {
    if (!isRecord(subject) || !Number.isFinite(nowMs)) return DENIED;
    const today = Math.floor(nowMs / DAY_MS) * DAY_MS;
    const providers = validCatalogProviders(catalog as unknown, today);  // the WHOLE catalog first, before any requested entry
    if (providers === null) return DENIED;
    const claimed: Record<string, string> = {};
    for (const field of ["provider_id", "jurisdiction", "venue", "instrument_kind", "quote_basis", "publication_scope"]) {
      const value = subject[field];
      if (typeof value !== "string" || value === "") return DENIED;
      claimed[field] = value;
    }
    const matches = providers.filter(item => item.id === claimed.provider_id);
    if (matches.length !== 1) return DENIED;  // unknown identity (duplicates were already refused)
    const provider = matches[0] as Record<string, unknown>;
    if (provider.runtime_enabled !== true || provider.line_quote_eligible !== true || !rightsReviewed(provider)) return DENIED;
    const reviewed = dayStart(provider.rights_reviewed_at);
    const validThrough = dayStart(provider.review_valid_through);  // review freshness window, not a license expiry
    if (reviewed === null || validThrough === null || reviewed > today || validThrough < today || validThrough < reviewed) return DENIED;
    const scopes = provider.admitted_scopes;
    if (!Array.isArray(scopes)) return DENIED;
    const matched = scopes.some(entry => isRecord(entry) && entry.instrument_kind === claimed.instrument_kind
      && entry.jurisdiction === claimed.jurisdiction && entry.publication_scope === claimed.publication_scope
      && entry.quote_basis === claimed.quote_basis && entry.venue === claimed.venue);
    return matched ? { ok: true, provider_id: claimed.provider_id as string } : DENIED;
  } catch {
    return DENIED;
  }
}
