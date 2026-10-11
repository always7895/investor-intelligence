/** F03 machine semantic admission DATA context. Source-only / IMPLEMENTED_UNVERIFIED.
 * Trusted publisher + independently sealed selection is the upstream boundary;
 * public hashes/this context are NOT native qualification or human approval.
 */
import { createHash } from "node:crypto";

export const GUIDANCE_BINDING_KEY = "v213:revenue-guidance-binding:v1";
export const MACHINE_SCHEMA = "v213-order-forecast-machine-v1";
const BINDING_SCHEMA = "revenue-guidance-public-binding-v1";
const SHA = /^[0-9a-f]{64}$/;
const GENERATION = /^\d{8}T\d{6}Z-[0-9a-f]{12}$/;
const INSTANT = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;
const DAY = /^\d{4}-\d{2}-\d{2}$/;
const IDENTITY = ["verifier_version", "normalizer_version", "implementation_sha256", "profiles_sha256",
  "baseline_registry_sha256", "baseline_approval_sha256"];
const ISSUER_KEYS = ["symbol", "disposition", "reason", "admission_kind", "identity", "attempt_sha256", "record_sha256", "receipt_digest"];
const AUTO_KEYS = ["version", "issuer", "disposition", "reason", "admission_kind", "generation_id", "identity", "producer",
  "decisions", "consumed", "detections", "overflow", "receipt", "cutoff", "input_digest", "generation_sha256"];
const MATERIAL = new Set(["RESULTS_RELEASE", "POSSIBLY_RELEVANT"]);
const CHANNELS = new Set(["SEC_SUBMISSIONS", "ISSUER_IR", "WIRE_PRESS_RELEASES"]);
const object = (v: any): v is Record<string, any> => v !== null && typeof v === "object" && !Array.isArray(v);
/** Fail-closed runtime check; an assertion signature so TypeScript narrows exactly what the check proves. */
function need(condition: unknown): asserts condition { if (!condition) throw new Error("MACHINE_INPUTS_UNAVAILABLE"); }
const keys = (v: any, names: readonly string[]) => object(v) && Object.keys(v).length === names.length && names.every(k => Object.hasOwn(v, k));
const instant = (v: any): v is string => typeof v === "string" && INSTANT.test(v) && Number.isFinite(Date.parse(v));
const hash = (v: string) => createHash("sha256").update(v).digest("hex");
const utf8 = (v: string) => new TextEncoder().encode(v).byteLength;
function canonical(v: any): string {
  if (v === null || typeof v !== "object") return JSON.stringify(v);
  if (Array.isArray(v)) return `[${v.map(canonical).join(",")}]`;
  return `{${Object.keys(v).sort().map(k => `${JSON.stringify(k)}:${canonical(v[k])}`).join(",")}}`;
}
const equal = (a: any, b: any) => canonical(a) === canonical(b);
function finite(v: any): void {
  const stack: [any, number][] = [[v, 0]]; let count = 0;
  while (stack.length) {
    const [value, depth] = stack.pop()!;
    need(depth <= 32 && ++count <= 200000);
    if (typeof value === "number") need(Number.isFinite(value));
    else if (Array.isArray(value)) value.forEach(x => stack.push([x, depth + 1]));
    else if (object(value)) Object.values(value).forEach(x => stack.push([x, depth + 1]));
    else need(value === null || typeof value === "string" || typeof value === "boolean");
  }
}
function parsed(text: any): any { need(typeof text === "string"); const value = JSON.parse(text); finite(value); return value; }
function identity(v: any, curated = false): boolean {
  return curated ? object(v) && Object.keys(v).length === 0 : keys(v, IDENTITY) && IDENTITY.every(k =>
    v[k] === null || (typeof v[k] === "string" && (k.endsWith("sha256") ? SHA.test(v[k]) : v[k].length > 0 && v[k].length <= 100)));
}
export interface MachineIssuerBinding {
  symbol: string; disposition: "CURATED" | "AUTO_VERIFIED" | "WAITING" | "BLOCKED" | "SUSPENDED";
  reason: string | null; admission_kind: "HUMAN_PROFILE" | "MACHINE_REPLAY" | null;
  identity: Readonly<Record<string, string | null>>;
  attempt_sha256: string | null; record_sha256: string | null; receipt_digest: string | null;
}
export interface MachineBindings {
  schema: "revenue-guidance-public-binding-v1"; report_sha256: string; cutoff: string; revision: string;
  input_digest: string; generation_id: string | null; generation_sha256: string | null;
  source_manifest_sha256: string; issuers: Readonly<Record<string, MachineIssuerBinding>>;
}
/** Actual loader supplies TWO texts from ONE immutable digest-verifying view.
 * No expected values are taken from an envelope; no options override this result.
 */
export function resolveSealedMachineBindings(reportText: string, bindingText: string): MachineBindings | null {
  try {
    need(utf8(reportText) <= 1900000 && utf8(bindingText) <= 64000);
    const report = parsed(reportText), b = parsed(bindingText);
    need(keys(b, ["schema", "report_sha256", "cutoff", "revision", "input_digest", "generation_id", "generation_sha256", "source_manifest_sha256", "issuers"]));
    need(b.schema === BINDING_SCHEMA && b.report_sha256 === hash(reportText) && instant(b.cutoff)
      && b.cutoff === report.generated_at && /^gir1:[0-9a-f]{64}$/.test(b.revision)
      && SHA.test(b.input_digest) && SHA.test(b.source_manifest_sha256));
    need(report.schema === "v213-bottleneck-top20-v3-sealed" && Array.isArray(report.top) && report.top.length >= 10 && report.top.length <= 20);
    const symbols = report.top.map((row: any) => row.symbol);
    need(new Set(symbols).size === symbols.length && object(b.issuers) && equal(Object.keys(b.issuers).sort(), [...symbols].sort()));
    need((b.generation_id === null) === (b.generation_sha256 === null));
    if (b.generation_id !== null) need(typeof b.generation_id === "string" && GENERATION.test(b.generation_id) && SHA.test(b.generation_sha256));
    for (const symbol of symbols) {
      need(typeof symbol === "string" && /^[A-Z0-9][A-Z0-9.\-]{0,23}$/.test(symbol));
      const p = b.issuers[symbol];
      need(keys(p, ISSUER_KEYS) && p.symbol === symbol && (p.reason === null || typeof p.reason === "string" && p.reason.length <= 200));
      for (const value of [p.attempt_sha256, p.record_sha256, p.receipt_digest]) need(value === null || typeof value === "string" && SHA.test(value));
      if (p.disposition === "CURATED") {
        need(identity(p.identity, true) && p.attempt_sha256 === null && p.receipt_digest === null
          && p.admission_kind === (p.record_sha256 === null ? null : "HUMAN_PROFILE"));
      } else if (p.disposition === "AUTO_VERIFIED") {
        need(identity(p.identity) && p.admission_kind === "MACHINE_REPLAY" && SHA.test(p.attempt_sha256)
          && SHA.test(p.record_sha256) && SHA.test(p.receipt_digest) && b.generation_id !== null);
      } else {
        need(["WAITING", "BLOCKED", "SUSPENDED"].includes(p.disposition) && identity(p.identity)
          && p.admission_kind === null && p.attempt_sha256 === null && p.record_sha256 === null);
      }
      Object.freeze(p.identity); Object.freeze(p);
    }
    Object.freeze(b.issuers); return Object.freeze(b) as MachineBindings;
  } catch { return null; }
}
export interface MachineCallbacks {
  digest(text: string): string;
  receiptDigest(receipt: any): string;
  /** ORIGINAL strict receipt classifier; record supplies own issuer/reference/
   * anchor/channel/freshness operands, including real guidance published date. */
  receiptStatus(receipt: any, record: any, cutoff: string): string;
}
export interface MachineAdmissionContext {
  readonly kind: "AUTO" | "BARRIER";
  readonly scoped: boolean;
  readonly barrierReason: "STALE" | "FRESHNESS_UNVERIFIED" | "INVALID" | null;
  readonly receiptDigest: string | null;
  readonly rawReceiptStatus: string | null;
  readonly consumed: ReadonlySet<string>;
}
const contexts = new WeakSet<object>();
export const machineContextIsValid = (ctx: unknown): ctx is MachineAdmissionContext => object(ctx) && contexts.has(ctx);
function triple(v: any): string {
  need(object(v) && CHANNELS.has(v.channel) && typeof v.id === "string" && v.id.length > 0 && v.id.length <= 400
    && typeof v.date === "string" && DAY.test(v.date) && Number.isFinite(Date.parse(v.date))
    && new Date(v.date).toISOString().slice(0,10) === v.date);
  return JSON.stringify([v.channel, v.id, v.date]);
}
function triples(rows: any[]): Set<string> {
  const set = new Set<string>(); for (const row of rows) set.add(triple(row)); return set;
}
const sameSet = (a: ReadonlySet<string>, b: ReadonlySet<string>) => a.size === b.size && [...a].every(x => b.has(x));
export function machineBarrierReason(disposition: string, reason: string | null): "STALE" | "FRESHNESS_UNVERIFIED" | "INVALID" {
  if (disposition === "WAITING") return "STALE";
  if (disposition === "SUSPENDED") {
    if (["RECEIPT_RESULTS_PUBLISHED", "RECEIPT_REVIEW_REQUIRED", "RECEIPT_RECEIPT_AGE_EXCEEDED", "DETECTIONS_"].some(p => (reason ?? "").startsWith(p))) return "STALE";
    if (["RECEIPT_MISSING", "RECEIPTS_", "RECEIPT_CHECKED_AT", "RECEIPT_IR_COVERAGE", "RECEIPT_CHANNELS"].some(p => (reason ?? "").startsWith(p))) return "FRESHNESS_UNVERIFIED";
  }
  return "INVALID";
}
function remember(ctx: MachineAdmissionContext): MachineAdmissionContext { contexts.add(ctx); return Object.freeze(ctx); }
function projection(source: any, sealed: any): void {
  need(object(source) && object(sealed));
  for (const key of Object.keys(sealed)) need(equal(sealed[key], Object.hasOwn(source, key) ? source[key] : null));
}
function scopedProjection(payload: any): boolean {
  const e = payload.evidence;
  return payload.revenue_status === "UNAVAILABLE" && payload.revenue_reason === "EVIDENCE_LIMIT"
    && [e.documents, e.claims, e.reported_quarters, e.forward_intervals, payload.reported_quarters, payload.forward_quarters]
      .every(a => Array.isArray(a) && a.length === 0)
    && [e.latest_release_check, e.consensus, e.fy_reconciliation, e.release_channels, e.reviewed_later_documents,
      e.approval_sha256, e.approval_approved_at, e.approval_decisions, payload.baseline_b, payload.warning].every(x => x === null)
    && object(e.order_evidence) && object(payload.order_view);
}
const REFERENCE_CLAIM_KEYS = ["id", "period_kind", "period_start", "period_end", "scope", "accounting_basis",
  "document_id", "source_sha256", "reference_document_id"];
const referenceId = (v: any): v is string => typeof v === "string"
  && /^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$/.test(v) && !/[\r\n]/.test(v);
const referenceDay = (v: any): v is string => typeof v === "string" && DAY.test(v) && !v.startsWith("0000-")
  && Number.isFinite(Date.parse(v)) && new Date(v).toISOString().slice(0,10) === v;
const referenceInstant = (v: any): v is string => instant(v)
  && !v.startsWith("0000-") && new Date(v).toISOString().replace(".000Z", "Z") === v;
interface ReferenceClaimDescriptor {
  id: string; period_kind: "QUARTER" | "FISCAL_YEAR"; period_start: string; period_end: string;
  scope: "COMPANY" | "CONSOLIDATED"; accounting_basis: string; document_id: string;
  source_sha256: string; reference_document_id: string;
}
interface ActiveGuidanceReference { document_id: string; claims: ReferenceClaimDescriptor[]; }
function referenceDocument(id: any, docs: ReadonlyMap<string, any>, issuer: string, cutoff: string): any {
  need(referenceId(id) && docs.has(id));
  const doc = docs.get(id);
  need(object(doc) && doc.id === id && doc.issuer === issuer && typeof doc.sha256 === "string"
    && doc.sha256.length === 64 && SHA.test(doc.sha256) && referenceDay(doc.published_date)
    && referenceInstant(doc.retrieved_at) && doc.retrieved_at <= cutoff
    && doc.published_date <= doc.retrieved_at.slice(0,10));
  if (doc.published_at !== undefined && doc.published_at !== null) {
    need(referenceInstant(doc.published_at) && doc.published_at.slice(0,10) === doc.published_date
      && doc.published_at <= doc.retrieved_at && doc.published_at <= cutoff);
  } else need(doc.published_date < cutoff.slice(0,10)); // SAME original date-only end-of-day rule
  return doc; // caller already bound this actual record document to a canonical-source capture
}
function referencePeriod(c: any, canonicalKey: string, alias: string): string {
  need((c[canonicalKey] === undefined || c[canonicalKey] === null || typeof c[canonicalKey] === "string")
    && (c[alias] === undefined || c[alias] === null || typeof c[alias] === "string"));
  const value = c[canonicalKey] || c[alias]; // Python's period_start or start / period_end or end, NOT nullish preference
  need(referenceDay(value)); return value;
}
/** Private semantic mirror of guidance_reference/select_active_guidance_claims.
 * Derive from the already hash-bound FULL record, never from a routing/pin descriptor.
 * This is source/reference binding, not a second fiscal/numerical admission parser.
 */
function deriveActiveGuidanceReference(record: any, docs: ReadonlyMap<string, any>, issuer: string,
  cutoff: string): ActiveGuidanceReference {
  need(referenceInstant(cutoff) && Array.isArray(record.claims) && record.claims.length > 0 && record.claims.length <= 8);
  const claims = new Map<string, any>();
  for (const c of record.claims) {
    need(object(c) && referenceId(c.id) && !claims.has(c.id) && referenceId(c.document_id)
      && ["QUARTER", "FISCAL_YEAR"].includes(c.period_kind) && ["COMPANY", "CONSOLIDATED", "SEGMENT"].includes(c.scope)
      && ["GAAP", "NON_GAAP", "IFRS", "K-IFRS"].includes(c.accounting_basis));
    referenceDocument(c.document_id, docs, issuer, cutoff);
    need(referencePeriod(c, "period_start", "start") <= referencePeriod(c, "period_end", "end"));
    claims.set(c.id, c);
  }
  const superseded = new Set<string>();
  // ALL claims contribute revision targets, including non-company/history rows,
  // BEFORE active selection; do not filter them by age/scope first to erase a target.
  for (const c of claims.values()) {
    const rev = c.revision;
    if (rev === undefined || rev === null) continue;
    need(object(rev) && Object.keys(rev).every(k => ["kind", "targets", "supersedes", "reason"].includes(k))
      && ["SUPERSEDED", "WITHDRAWN", "WITHDRAWAL", "CORRECTION", "REAFFIRMATION"].includes(rev.kind));
    if (["SUPERSEDED", "WITHDRAWN", "WITHDRAWAL"].includes(rev.kind)) superseded.add(c.id);
    const targets = rev.targets === undefined || rev.targets === null ? [] : rev.targets;
    need(Array.isArray(targets));
    const operands = [...targets];
    if (rev.supersedes !== undefined && rev.supersedes !== null) {
      need(referenceId(rev.supersedes)); operands.push(rev.supersedes);
    }
    for (const target of operands) {
      need(referenceId(target) && target !== c.id && claims.has(target));
      need(docs.get(claims.get(target).document_id).published_date <= docs.get(c.document_id).published_date);
      superseded.add(target);
    }
  }
  const descriptors: ReferenceClaimDescriptor[] = [], references = new Set<string>();
  for (const c of claims.values()) {
    // Preserve validation of retained reaffirmation operands, not just the winning row.
    const reaffirmations = c.reaffirmed_by === undefined || c.reaffirmed_by === null ? [] : c.reaffirmed_by;
    need(Array.isArray(reaffirmations));
    let best = c.document_id, bestDay = docs.get(best).published_date;
    for (const item of reaffirmations) {
      need(object(item) && referenceId(item.document_id) && typeof item.locator === "string"
        && item.locator.trim().length > 0 && item.locator.length <= 160 && typeof item.passage === "string"
        && item.passage.trim().length > 0 && item.passage.length <= 1000);
      const doc = referenceDocument(item.document_id, docs, issuer, cutoff);
      if (doc.published_date > bestDay) { best = item.document_id; bestDay = doc.published_date; }
      // Strictly later ONLY: own document wins a tie; then the prior winning
      // reaffirmation wins a tie in the ORIGINAL reaffirmed_by order.
    }
    if (superseded.has(c.id) || !["COMPANY", "CONSOLIDATED"].includes(c.scope)) continue;
    references.add(best);
    descriptors.push({id: c.id, period_kind: c.period_kind, period_start: referencePeriod(c, "period_start", "start"),
      period_end: referencePeriod(c, "period_end", "end"), scope: c.scope, accounting_basis: c.accounting_basis,
      document_id: c.document_id, source_sha256: docs.get(c.document_id).sha256, reference_document_id: best});
  }
  need(descriptors.length > 0 && references.size === 1); // distinct active refs CONFLICT, never newest/first fallback
  const compare = (a: string, b: string): number => a < b ? -1 : a > b ? 1 : 0;
  // All keys are validated ASCII strings; this is Python tuple/codepoint order,
  // NOT object .sort() coercion or locale-dependent ordering.
  descriptors.sort((a, b) => compare(a.period_kind, b.period_kind) || compare(a.period_start, b.period_start) || compare(a.id, b.id));
  const first = descriptors[0];
  need(first !== undefined); // length is checked above; explicit fail-closed narrowing, no non-null assertion
  return {document_id: first.reference_document_id, claims: descriptors};
}
function checkActiveGuidanceReference(actual: any, derived: ActiveGuidanceReference): void {
  need(keys(actual, ["document_id", "claims"]) && actual.document_id === derived.document_id
    && Array.isArray(actual.claims) && actual.claims.length === derived.claims.length);
  const seen = new Set<string>();
  actual.claims.forEach((d: any, i: number) => {
    need(keys(d, REFERENCE_CLAIM_KEYS) && referenceId(d.id) && !seen.has(d.id) && equal(d, derived.claims[i]));
    seen.add(d.id); // complete exact ordered descriptors: no extra keys, omission, duplicates, coercion or null fillers
  });
}
/** Verify canonical FULL objects, original capture roles and consumed/retained
 * receipt accounting; construct only a distinct machine context, never approval.
 */
const NBIS_MODE = "NBIS_6K_TABLE_REAFFIRMATION_V1";
const NBIS_PACKAGE_KEYS = ["accession", "filed", "index", "form", "statement", "letter", "members"];
const NBIS_FACT_KEYS = ["capture", "document_id", "raw_sha256", "source_sha256", "locator", "headers", "shown",
  "start", "end", "value", "currency", "unit_multiplier", "scope", "accounting_basis", "precision"];
const NBIS_DECISION_FIELDS: Record<string, [string, string[]]> = {
  MEMBERSHIP: ["PACKAGE_PROVEN", ["accession", "filed", "form", "members", "report_period", "basis", "comparative_notes", "guidance_state", "link_accounts"]],
  ACTUAL: ["TABLE_DIRECT_OR_RECONCILED", ["operand", "derivation", "tagged"]],
  CALENDAR: ["TABLE_CALENDAR_PROVEN", ["rule", "proofs", "intervals", "full_year", "tagged_proofs"]],
  CLAIM: ["FY_RANGE_IN_SOURCE", ["offsets", "low", "high", "fiscal_year", "scope_context"]],
  REAFFIRMATION: ["ALL_METRICS_SAME_FY", ["claim_id", "original_capture", "reference_capture", "original", "current"]],
  FY_RECONCILIATION: ["REPORTED_YTD_PROVEN", ["fy_claim_id", "start", "end", "value", "quarters", "operand"]],
  ROUTING: ["EVENT_CONSUMED", ["adapter", "accession", "form", "filed", "packages", "channel_history", "channel_links", "ir_item", "wire_item", "consumed", "report_period", "reference"]],
};
function nbisSpan(v: any): void {
  need(Array.isArray(v) && v.length === 2 && v.every(n => Number.isInteger(n) && n >= 0 && n <= 4194304) && v[0] < v[1]);
}
function nbisText(v: any, max = 1000): void { need(typeof v === "string" && v.length > 0 && v.length <= max); }
function nbisQuote(v: any): void { need(keys(v, ["offsets", "quote"])); nbisSpan(v.offsets); nbisText(v.quote); }
function nbisDecimal(v: any): number {
  need(typeof v === "string" && v.length <= 40 && /^[0-9]+(?:\.[0-9]+)?$/.test(v));
  const n = Number(v); need(Number.isFinite(n) && n >= 0 && n <= Number.MAX_SAFE_INTEGER); return n;
}
function nbisDecimalCompareInteger(v: any, fence: number): number {
  nbisDecimal(v); need(Number.isSafeInteger(fence) && fence >= 0);
  const [whole, fraction = ""] = (v as string).split("."); const n = Number(whole);
  need(Number.isSafeInteger(n));
  return n < fence ? -1 : n > fence ? 1 : /[1-9]/.test(fraction) ? 1 : 0;
}
function nbisShown(v: string): number {
  need(typeof v === "string" && /^[0-9]{1,12}(?:,[0-9]{3})*\.[0-9]$/.test(v));
  // Exact decimal shift; binary fraction multiplication can reject legitimate
  // 0.1M disclosures. Safe-integer bound is consumer admission, not rounding.
  const [whole, tenth] = v.replaceAll(",", "").split(".");
  need(whole !== undefined && tenth !== undefined); // the grammar above guarantees exactly one "."
  const n = Number(whole + tenth + "00000"); need(Number.isSafeInteger(n)); return n;
}
function nbisHeaders(headers: string[], start: string, end: string): void {
  need(Array.isArray(headers) && headers.length > 0 && headers.length <= 512 && headers.every(h => typeof h === "string" && h.length <= 8192));
  const joined = headers.join(" "); need(joined.length <= 8192 && !/\bChange\b|%/i.test(joined));
  const years = headers.filter(h => /^20[0-9]{2}$/.test(h));
  const periods = [...joined.matchAll(/\b(Three|Six|Nine|Twelve) months ended (March|June|September|December) ([0-9]{1,2})\b/gi)];
  need(years.length === 1 && periods.length === 1);
  const months: Record<string, number> = {march: 3, june: 6, september: 9, december: 12};
  const durations: Record<string, number> = {three: 3, six: 6, nine: 9, twelve: 12};
  // Mandatory captures of the single matched period phrase; any absence fails closed.
  const [, durationWord, monthWord, dayText] = periods[0] ?? [];
  need(durationWord !== undefined && monthWord !== undefined && dayText !== undefined);
  const month = months[monthWord.toLowerCase()], n = durations[durationWord.toLowerCase()], year = Number(years[0]);
  need(month !== undefined && n !== undefined && n <= month && Number(dayText) === (month === 3 || month === 12 ? 31 : 30)
    && start === new Date(Date.UTC(year, month - n, 1)).toISOString().slice(0,10)
    && end === new Date(Date.UTC(year, month, 0)).toISOString().slice(0,10));
}
const NBIS_FY_RANGE = String.raw`On track to achieve \$(?<low>[0-9]{1,6}(?:\.[0-9]{1,6})?)B–\$(?<high>[0-9]{1,6}(?:\.[0-9]{1,6})?)B revenue in (?<year>20[0-9]{2}) and \$[0-9]{1,6}(?:\.[0-9]{1,6})?B–\$[0-9]{1,6}(?:\.[0-9]{1,6})?B ARR`;
const NBIS_SCOPE_SENTENCE = String.raw`Nebius Group(?: N\.V\.)?(?:'s)? consolidated revenue guidance (?:is|has been) (?:prepared|presented) (?:in accordance with|on the basis of) U\.S\. GAAP\.`;
function nbisBillion(v: string): number {
  need(/^[0-9]{1,6}(?:\.[0-9]{1,6})?$/.test(v)); const [whole, fraction = ""] = v.split(".");
  const value = Number(whole + fraction.padEnd(9, "0")); need(Number.isSafeInteger(value)); return value;
}
function nbisScope(v: any): {year: number; low: number; high: number; range: string} {
  need(keys(v, ["offsets", "quote", "scope_offsets", "range_offsets", "heading", "rule", "grammar"])
    && v.rule === "EXPLICIT_GROUP_GAAP" && v.grammar === "NBIS_POSITIVE_FY_BLOCK_V2");
  nbisSpan(v.offsets); nbisSpan(v.scope_offsets); nbisSpan(v.range_offsets); nbisText(v.quote); nbisQuote(v.heading);
  need(v.offsets[1] - v.offsets[0] === v.quote.length);
  const heading = String.raw`(?:(?<heading>20[0-9]{2} Guidance update) )?`;
  const bodies = [String.raw`(?<range>${NBIS_FY_RANGE})\.? (?<scope>${NBIS_SCOPE_SENTENCE})`,
    String.raw`(?<scope>${NBIS_SCOPE_SENTENCE}) (?<range>${NBIS_FY_RANGE})\.?`];
  for (const body of bodies) {
    const m = new RegExp("^" + heading + body + "$").exec(v.quote);
    if (m === null || m[0] !== v.quote) continue; // FULL coverage, not a positive substring/blacklist
    // year/low/high/range/scope are mandatory named groups of this full-coverage match; only heading is optional.
    const g = m.groups;
    need(g !== undefined);
    const {year: yearText, low: lowText, high: highText, range, scope, heading: headingGroup} = g;
    need(yearText !== undefined && lowText !== undefined && highText !== undefined && range !== undefined && scope !== undefined);
    const year = Number(yearText), low = nbisBillion(lowText), high = nbisBillion(highText);
    need(low > 0 && low <= high && v.heading.quote === `${year} Guidance update`
      && (headingGroup === undefined || headingGroup === v.heading.quote));
    const start = v.offsets[0], rangeStart = v.quote.indexOf(range), scopeStart = v.quote.indexOf(scope);
    need(equal(v.range_offsets, [start + rangeStart, start + rangeStart + range.length])
      && equal(v.scope_offsets, [start + scopeStart, start + scopeStart + scope.length])
      && equal(v.heading.offsets, headingGroup === undefined ? [start - v.heading.quote.length - 1, start - 1] : [start, start + headingGroup.length]));
    return {year, low, high, range};
  }
  throw new Error("MACHINE_INPUTS_UNAVAILABLE");
}
function nbisLetterActual(v: any): {start: string; end: string; value: number} {
  nbisText(v);
  const m = /^Consolidated revenues? for the (first|second|third|fourth) quarter (?:of )?(20[0-9]{2}) (?:was|were) \$([0-9]{1,12}\.[0-9]) million\.?$/i.exec(v);
  need(m !== null && m[0] === v);
  const [, ordinalWord, yearText, shown] = m; // mandatory captures; absence fails closed below
  need(ordinalWord !== undefined && yearText !== undefined && shown !== undefined);
  const ordinals: Record<string, number> = {first: 1, second: 2, third: 3, fourth: 4};
  const quarter = ordinals[ordinalWord.toLowerCase()];
  need(quarter !== undefined);
  return {...nbisQuarter(Number(yearText), quarter), value: nbisShown(shown)};
}
/** Form-body period proof: the same sentence grammar and quarter as the Python builder, not arbitrary quote text. */
function nbisReportBody(v: any, end: string): void {
  nbisQuote(v);
  const m = /^financial results for (?:the )?(first|second|third|fourth) quarter (?:of )?(20[0-9]{2})$/i.exec(v.quote);
  need(m !== null && m[0] === v.quote);
  const [, ordinalWord, yearText] = m; // mandatory captures; absence fails closed below
  need(ordinalWord !== undefined && yearText !== undefined);
  const ordinals: Record<string, number> = {first: 1, second: 2, third: 3, fourth: 4};
  const quarter = ordinals[ordinalWord.toLowerCase()];
  need(quarter !== undefined && nbisQuarter(Number(yearText), quarter).end === end);
}
function nbisDecimalIdentity(v: any): string {
  nbisDecimal(v); const [whole, fraction = ""] = (v as string).split(".");
  need(whole !== undefined); // split always yields a first element; explicit narrowing
  const integer = whole.replace(/^0+(?=[0-9])/, ""), tail = fraction.replace(/0+$/, "");
  return tail ? integer + "." + tail : integer;
}
function nbisTagged(tagged: any, operand: any): void {
  need(object(tagged) && typeof tagged.present === "boolean");
  if (!tagged.present) { need(keys(tagged, ["present", "policy"]) && tagged.policy === "FOREIGN_TABLE_TAGGED_ABSENCE_V1"); return; }
  const value = nbisDecimal(operand.value);
  need(keys(tagged, ["present", "policy", "value", "lower_inclusive", "upper_exclusive", "facts"])
    && tagged.policy === "HALF_UP_HALF_OPEN" && nbisDecimalCompareInteger(tagged.lower_inclusive, value - 50000) === 0
    && nbisDecimalCompareInteger(tagged.upper_exclusive, value + 50000) === 0
    && nbisDecimalCompareInteger(tagged.value, value - 50000) >= 0 && nbisDecimalCompareInteger(tagged.value, value + 50000) < 0
    && Array.isArray(tagged.facts) && tagged.facts.length > 0 && tagged.facts.length <= 64);
  const seen = new Set<string>();
  for (const f of tagged.facts) {
    need(keys(f, ["concept", "namespace", "context", "entity", "unit", "measure", "measure_namespace", "start", "end", "scope", "accounting_basis", "value"])
      && Object.values(f).every(v => typeof v === "string" && v.length > 0 && v.length <= 240)
      && /^[A-Za-z_][A-Za-z0-9_.-]*:(?:Revenues|RevenueFromContractWithCustomerExcludingAssessedTax)$/.test(f.concept)
      && /^http:\/\/fasb\.org\/us-gaap\/20[0-9]{2}$/.test(f.namespace) && /^[0-9]{1,10}$/.test(f.entity) && Number(f.entity) === 1513845
      && /^[A-Za-z_][A-Za-z0-9_.-]*:USD$/.test(f.measure) && f.measure_namespace === "http://www.xbrl.org/2003/iso4217"
      && f.start === operand.start && f.end === operand.end && f.scope === operand.scope && f.accounting_basis === operand.accounting_basis
      && nbisDecimalIdentity(f.value) === nbisDecimalIdentity(tagged.value));
    const id = canonical(f); need(!seen.has(id)); seen.add(id);
  }
}
function nbisQuarter(year: number, q: number): {start: string; end: string} {
  need(Number.isInteger(year) && year >= 2000 && year <= 2099 && Number.isInteger(q) && q >= 1 && q <= 4);
  return {start: new Date(Date.UTC(year, (q - 1) * 3, 1)).toISOString().slice(0,10),
    end: new Date(Date.UTC(year, q * 3, 0)).toISOString().slice(0,10)};
}
function nbisFact(v: any, captures: ReadonlyMap<string, any>, docs: ReadonlyMap<string, any>): number {
  need(keys(v, NBIS_FACT_KEYS) && captures.has(v.capture) && docs.has(v.document_id)
    && referenceDay(v.start) && referenceDay(v.end) && v.start <= v.end && SHA.test(v.raw_sha256) && SHA.test(v.source_sha256)
    && v.currency === "USD" && v.unit_multiplier === 1000000 && v.scope === "COMPANY" && v.accounting_basis === "GAAP"
    && v.precision === "0.1" && typeof v.locator === "string" && /^grid\[[0-9]{1,3}\]\.r\[[0-9]{1,3}\]\.c\[[0-9]{1,2}\]$/.test(v.locator)
    && Array.isArray(v.headers) && v.headers.length > 0 && v.headers.length <= 512
    && v.headers.every((h: any) => typeof h === "string" && h.length <= 8192)
    && typeof v.shown === "string" && /^[0-9]{1,12}(?:,[0-9]{3})*\.[0-9]$/.test(v.shown));
  nbisHeaders(v.headers, v.start, v.end);
  const cap = captures.get(v.capture), doc = docs.get(v.document_id), value = nbisDecimal(v.value);
  need(value > 0 && Number.isSafeInteger(value) && nbisShown(v.shown) === value
    && cap.raw_sha256 === v.raw_sha256 && cap.sha256 === v.source_sha256 && doc.sha256 === v.source_sha256
    && cap.url === doc.url && cap.retrieved_at === doc.retrieved_at && doc.source_kind === "SEC_6K_EXHIBIT"
    && cap.role === "NBIS_ACTUALS_STATEMENT" && v.end < doc.published_date);
  return value;
}
function validateNbisSourceDecisions(record: any, attempt: any, decisions: any[], route: any,
  captures: ReadonlyMap<string, any>, docs: ReadonlyMap<string, any>): void {
  need(record.symbol === "NBIS" && route.adapter === NBIS_MODE && route.form === "6-K"
    && keys(attempt.event, ["adapter", "accession", "filed", "packages", "channel_history", "ir_item", "wire_item", "later_documents"])
    && attempt.event.adapter === NBIS_MODE && route.accession === attempt.event.accession && route.filed === attempt.event.filed
    && equal(route.packages, attempt.event.packages) && equal(route.channel_history, attempt.event.channel_history)
    && equal(route.wire_item, attempt.event.wire_item)
    && referenceDay(route.filed) && route.filed <= attempt.attempted_at.slice(0,10)
    && Array.isArray(route.packages) && route.packages.length > 0 && route.packages.length <= 8
    && keys(route.report_period, ["quarter", "fiscal_year", "start", "end"])
    && equal({start: route.report_period.start, end: route.report_period.end}, nbisQuarter(route.report_period.fiscal_year, route.report_period.quarter))
    && record.reported_quarters.length === 4 && record.claims.length === 1 && record.forward_intervals.length === 4);
  need(captures.size <= 32 && [...captures.keys()].every(k => /^(?:submissions|ir_copy|wire_copy|nbis:[0-9]{10}-[0-9]{2}-[0-9]{6}:(?:index|form|statement|letter|ir_copy|wire_copy|member:[A-Za-z0-9._-]{1,100}))$/.test(k)));
  const counts = new Map<string, number>();
  for (const d of decisions) {
    const domain = NBIS_DECISION_FIELDS[d.kind];
    need(domain !== undefined && d.decision === domain[0] && keys(d.operands, domain[1]));
    counts.set(d.kind, (counts.get(d.kind) ?? 0) + 1);
  }
  need(counts.get("MEMBERSHIP") === route.packages.length && counts.get("ACTUAL") === 4 && counts.get("CLAIM") === 1
    && counts.get("CALENDAR") === 1 && counts.get("FY_RECONCILIATION") === 1 && counts.get("ROUTING") === 1
    && (counts.get("REAFFIRMATION") ?? 0) <= 1);
  const packageIds = new Set<string>(), sourceUrls = new Set<string>();
  const operandRefs = new Map<string, any>();
  const boundFact = (v: any): number => { const value = nbisFact(v, captures, docs); operandRefs.set(canonical(v), v); return value; };
  const linkTargets = new Map<string, string>();
  for (const p of route.packages) for (const [name, key] of Object.entries(p.members))
    linkTargets.set(key as string, `https://www.sec.gov/Archives/edgar/data/1513845/${p.accession.replaceAll("-", "")}/${name}`);
  const boundLinks = (rows: any): Set<string> => {
    need(Array.isArray(rows) && rows.length <= 256); const urls: string[] = [], targets = new Set<string>();
    for (const row of rows) {
      need(keys(row, ["url", "capture"]) && linkTargets.has(row.capture) && row.url === linkTargets.get(row.capture));
      const cap = captures.get(row.capture); need(cap && cap.url === row.url && sourceUrls.has(row.url));
      urls.push(row.url); targets.add(row.capture);
    }
    need(equal(urls, [...new Set(urls)].sort())); return targets;
  };
  for (const p of route.packages) {
    need(keys(p, NBIS_PACKAGE_KEYS) && typeof p.accession === "string" && /^\d{10}-\d{2}-\d{6}$/.test(p.accession)
      && !packageIds.has(p.accession) && referenceDay(p.filed) && p.filed <= route.filed && object(p.members)
      && Object.keys(p.members).length > 0 && Object.keys(p.members).length <= 8
      && new Set(Object.values(p.members)).size === Object.keys(p.members).length);
    packageIds.add(p.accession);
    const base = `https://www.sec.gov/Archives/edgar/data/1513845/${p.accession.replaceAll("-", "")}/`;
    const index = captures.get(p.index);
    need(index && index.role === "SEC_INDEX" && index.url === base + "index.json");
    for (const [name, key] of Object.entries(p.members)) {
      need(/^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$/.test(name) && /\.html?$/i.test(name) && typeof key === "string");
      const cap = captures.get(key as string);
      need(cap && cap.url === base + name && cap.retrieved_at.slice(0,10) >= p.filed
        && cap.role === (key === p.form ? "NBIS_RESULTS_FORM" : key === p.statement ? "NBIS_ACTUALS_STATEMENT" : key === p.letter ? "NBIS_SHAREHOLDER_LETTER" : "NBIS_RESULTS_PACKAGE"));
      const doc = docs.get(`NBIS-${p.accession}-${name}`);
      need(doc && doc.url === cap.url && doc.sha256 === cap.sha256 && doc.published_date === p.filed);
      sourceUrls.add(cap.url);
    }
    need([p.form, p.statement, p.letter].every(k => Object.values(p.members).includes(k)) && new Set([p.form, p.statement, p.letter]).size === 3);
    const ds = decisions.filter(d => d.kind === "MEMBERSHIP" && d.ref === p.accession);
    need(ds.length === 1 && ds[0].capture === p.index);
    const op = ds[0].operands;
    need(op.accession === p.accession && op.filed === p.filed && op.form === p.form && equal(op.members, p.members)
      && keys(op.report_period, ["end", "body"]) && referenceDay(op.report_period.end)
      && Array.isArray(op.report_period.body) && op.report_period.body.length > 0 && op.report_period.body.length <= 16);
    for (const v of op.report_period.body) nbisReportBody(v, op.report_period.end);
    const basis = op.basis;
    need(keys(basis, ["gaap", "continuing_revenue", "company", "corroboration"]) && basis.company === "Nebius Group N.V.");
    for (const k of ["gaap", "continuing_revenue"]) {
      need(Array.isArray(basis[k]) && basis[k].length > 0 && basis[k].length <= 16); basis[k].forEach(nbisQuote);
      for (const v of basis[k]) {
        const pattern = k === "gaap" ? /^(?:These|The) unaudited condensed consolidated financial statements (?:have been|are) prepared in accordance with (?:U\.S\. GAAP|accounting principles generally accepted in the United States)\.?$/i
          : /^Revenues (?:in|presented in) (?:the|these) unaudited condensed consolidated statements of operations (?:are|represent) revenues from continuing operations for all periods presented\.?$/i;
        const match = pattern.exec(v.quote); need(match !== null && match[0] === v.quote);
      }
    }
    need(Array.isArray(basis.corroboration) && basis.corroboration.length > 0 && basis.corroboration.length <= 32);
    for (const v of basis.corroboration) {
      need(v.kind === "HIGHLIGHTS" || v.kind === "LETTER");
      need(keys(v, v.kind === "HIGHLIGHTS" ? ["kind", "locator", "start", "end", "value", "shown", "headers"] : ["kind", "capture", "offsets", "quote", "start", "end", "value"])
        && referenceDay(v.start) && referenceDay(v.end) && v.start <= v.end);
      const amount = nbisDecimal(v.value), cal = decisions.find(d => d.kind === "CALENDAR");
      need(cal && cal.operands.proofs.some((f: any) => f.capture === p.statement && f.start === v.start && f.end === v.end && nbisDecimal(f.value) === amount));
      if (v.kind === "LETTER") {
        nbisSpan(v.offsets); const actual = nbisLetterActual(v.quote);
        need(v.capture === p.letter && captures.has(v.capture) && v.offsets[1] - v.offsets[0] === v.quote.length
          && actual.start === v.start && actual.end === v.end && actual.value === amount);
      }
      else { nbisText(v.locator, 120); nbisText(v.shown, 40); nbisHeaders(v.headers, v.start, v.end); need(nbisShown(v.shown) === amount); }
    }
    need(Array.isArray(op.comparative_notes) && op.comparative_notes.length <= 32);
    for (const note of op.comparative_notes) {
      need(keys(note, ["capture", "offsets", "quote", "periods", "classification"]) && captures.has(note.capture)
        && note.classification === "PRIOR_COMPARATIVE_ONLY" && Array.isArray(note.periods) && note.periods.length > 0 && note.periods.length <= 16);
      nbisSpan(note.offsets); nbisText(note.quote);
      for (const period of note.periods) need(keys(period, ["start", "end"]) && referenceDay(period.start) && referenceDay(period.end)
        && period.start <= period.end && period.end < record.reported_quarters[0].start);
    }
    need(route.consumed.some((v: any) => v.channel === "SEC_SUBMISSIONS" && v.id === p.accession && v.date === p.filed));
  }
  const current = route.packages.filter((p: any) => p.accession === route.accession && p.filed === route.filed);
  need(current.length === 1 && [...docs.values()].every(doc => sourceUrls.has(doc.url)));
  // All package URLs/documents are established before checking cross-package links.
  for (const p of route.packages) {
    const accounts = decisions.find(d => d.kind === "MEMBERSHIP" && d.ref === p.accession).operands.link_accounts;
    need(object(accounts) && sameSet(new Set(Object.keys(accounts)), new Set(Object.values(p.members) as string[])));
    for (const rows of Object.values(accounts)) boundLinks(rows);
    const formLinks = boundLinks(accounts[p.form]); need(formLinks.has(p.statement) && formLinks.has(p.letter));
  }
  const channelPackages = new Map<string, any>();
  for (const [slot, key, channel, role] of [["ir_item", "ir_copy", "ISSUER_IR", "IR_RELEASE_PAGE"], ["wire_item", "wire_copy", "WIRE_PRESS_RELEASES", "WIRE_RELEASE_PAGE"]] as const) {
    const item = route[slot];
    if (item === null) { need(slot === "wire_item"); continue; }
    need(keys(item, ["id", "title", "date"]) && item.date === route.filed); nbisText(item.title, 200); nbisText(item.id, 400);
    const cap = captures.get(key);
    need(cap && cap.url === item.id && cap.role === role && route.consumed.some((v: any) => v.channel === channel && v.id === item.id && v.date === item.date));
    channelPackages.set(key, current[0]);
  }
  need(Array.isArray(route.channel_history) && route.channel_history.length <= 16);
  const historyTriples = new Set<string>();
  for (const h of route.channel_history) {
    need(keys(h, ["accession", "channel", "item", "capture"]) && packageIds.has(h.accession) && h.accession !== route.accession
      && ["ISSUER_IR", "WIRE_PRESS_RELEASES"].includes(h.channel) && keys(h.item, ["id", "title", "date"]));
    const packageRow = route.packages.find((p: any) => p.accession === h.accession);
    need(h.item.date === packageRow.filed && h.capture === `nbis:${h.accession}:${h.channel === "ISSUER_IR" ? "ir_copy" : "wire_copy"}`);
    const cap = captures.get(h.capture), value = triple({channel: h.channel, id: h.item.id, date: h.item.date}); nbisText(h.item.title, 200);
    need(cap && cap.url === h.item.id && cap.role === (h.channel === "ISSUER_IR" ? "IR_RELEASE_PAGE" : "WIRE_RELEASE_PAGE")
      && !historyTriples.has(value) && route.consumed.some((v: any) => triple(v) === value)); historyTriples.add(value);
    channelPackages.set(h.capture, packageRow);
  }
  need(object(route.channel_links) && sameSet(new Set(Object.keys(route.channel_links)), new Set(channelPackages.keys())));
  for (const [key, p] of channelPackages) {
    const links = boundLinks(route.channel_links[key]); need(links.has(p.statement) && links.has(p.letter));
  }
  const consumed = triples(route.consumed);
  const proven = new Set<string>([...route.packages.map((p: any) => triple({channel: "SEC_SUBMISSIONS", id: p.accession, date: p.filed})), ...historyTriples]);
  for (const [slot, channel] of [["ir_item", "ISSUER_IR"], ["wire_item", "WIRE_PRESS_RELEASES"]] as const) if (route[slot] !== null)
    proven.add(triple({channel, id: route[slot].id, date: route[slot].date}));
  need(sameSet(consumed, proven));
  need(consumed.size === route.consumed.length && Array.isArray(attempt.event.later_documents) && attempt.event.later_documents.length <= 256);
  for (const item of attempt.event.later_documents) {
    need(keys(item, ["channel", "date", "id", "label", "disposition"]) && MATERIAL.has(item.disposition));
    triple(item); nbisText(item.label, 200);
  }
  for (const q of record.reported_quarters) {
    const ds = decisions.filter(d => d.kind === "ACTUAL" && d.ref === q.end); need(ds.length === 1);
    const d = ds[0], op = d.operands, value = boundFact(op.operand);
    need(d.capture === op.operand.capture && q.start === op.operand.start && q.end === op.operand.end
      && q.revenue === value && q.document_id === op.operand.document_id && q.locator === op.operand.locator);
    const dv = op.derivation;
    if (dv === null) need(q.derivation === undefined || q.derivation === null);
    else {
      need(keys(dv, ["operation", "longer", "shorter", "direct", "output"]) && equal(dv.direct, op.operand));
      const l = boundFact(dv.longer), s = boundFact(dv.shorter); boundFact(dv.direct);
      const year = Number(q.end.slice(0,4));
      if (dv.operation === "SIX_MONTHS_MINUS_FINAL_QUARTER") need(dv.longer.start === `${year}-01-01` && dv.longer.end === `${year}-06-30`
        && dv.shorter.start === `${year}-04-01` && dv.shorter.end === dv.longer.end && q.start === dv.longer.start && q.end === `${year}-03-31`);
      else need(dv.operation === "FULL_YEAR_MINUS_INITIAL_NINE_MONTHS" && dv.longer.start === `${year}-01-01` && dv.longer.end === `${year}-12-31`
        && dv.shorter.start === dv.longer.start && dv.shorter.end === `${year}-09-30` && q.start === `${year}-10-01` && q.end === dv.longer.end);
      need(l - s === value && value > 0 && keys(dv.output, ["start", "end", "value", "currency", "unit_multiplier", "scope", "accounting_basis", "precision"])
        && dv.output.start === q.start && dv.output.end === q.end && nbisDecimal(dv.output.value) === value && dv.output.currency === "USD"
        && dv.output.unit_multiplier === 1000000 && dv.output.scope === "COMPANY" && dv.output.accounting_basis === "GAAP" && dv.output.precision === "0.1"
        && object(q.derivation) && q.derivation.kind === "YTD_DIFFERENCE" && q.derivation.longer_document_id === dv.longer.document_id
        && q.derivation.shorter_document_id === dv.shorter.document_id && q.derivation.longer_value === l && q.derivation.shorter_value === s
        && q.derivation.longer_start === dv.longer.start && q.derivation.shorter_end === dv.shorter.end);
    }
    nbisTagged(op.tagged, op.operand);
  }
  const claim = record.claims[0], cd = decisions.filter(d => d.kind === "CLAIM" && d.ref === claim.id);
  need(cd.length === 1 && claim.period_kind === "FISCAL_YEAR" && claim.original_representation === "RANGE" && claim.stated_point === null
    && claim.amount === null && claim.unit_multiplier === 1 && claim.currency === "USD" && claim.scope === "COMPANY" && claim.accounting_basis === "GAAP");
  const cop = cd[0].operands; nbisSpan(cop.offsets); const positive = nbisScope(cop.scope_context);
  need(equal(cop.offsets, cop.scope_context.range_offsets) && cop.fiscal_year === positive.year && claim.passage === positive.range
    && nbisDecimalCompareInteger(cop.low, positive.low) === 0 && nbisDecimalCompareInteger(cop.high, positive.high) === 0);
  need(Number.isInteger(cop.fiscal_year) && claim.period_start === `${cop.fiscal_year}-01-01` && claim.period_end === `${cop.fiscal_year}-12-31`
    && nbisDecimal(cop.low) === claim.low && nbisDecimal(cop.high) === claim.high && claim.low > 0 && claim.low <= claim.high);
  const source = docs.get(claim.document_id), sourceCapture = captures.get(cd[0].capture);
  need(source && sourceCapture && sourceCapture.role === "NBIS_SHAREHOLDER_LETTER" && sourceCapture.url === source.url && sourceCapture.sha256 === source.sha256);
  for (const pkg of route.packages) {
    const state = decisions.find(d => d.kind === "MEMBERSHIP" && d.ref === pkg.accession).operands.guidance_state;
    if (pkg.filed < source.published_date) { need(state === null); continue; }
    need(object(state) && state.year === cop.fiscal_year); nbisSpan(state.offsets); nbisText(state.passage);
    if (pkg.letter === cd[0].capture) need(keys(state, ["kind", "year", "low", "high", "offsets", "passage", "scope_context"])
      && state.kind === "ORIGINAL_RANGE" && state.low === cop.low && state.high === cop.high && equal(state.offsets, cop.offsets)
      && equal(state.scope_context, cop.scope_context) && state.passage === claim.passage);
    else need(pkg.filed > source.published_date && keys(state, ["kind", "year", "offsets", "passage"]) && state.kind === "REAFFIRMATION"
      && state.passage === `We are reaffirming our full-year ${cop.fiscal_year} guidance across all metrics.`);
  }
  const reaffirm = decisions.filter(d => d.kind === "REAFFIRMATION");
  if (reaffirm.length === 0) need((claim.reaffirmed_by ?? []).length === 0 && source.published_date === route.filed);
  else {
    const r = reaffirm[0], op = r.operands;
    need(r.ref === claim.id && op.claim_id === claim.id && op.original_capture === cd[0].capture && op.reference_capture === r.capture
      && r.capture === current[0].letter && keys(op.original, ["year", "low", "high", "offsets", "passage", "scope_context"])
      && keys(op.current, ["year", "offsets", "passage"]) && op.original.year === cop.fiscal_year && op.current.year === cop.fiscal_year
      && op.original.low === cop.low && op.original.high === cop.high && equal(op.original.offsets, cop.offsets)
      && equal(op.original.scope_context, cop.scope_context) && op.original.passage === claim.passage);
    nbisSpan(op.current.offsets); nbisScope(op.original.scope_context);
    need(op.current.passage === `We are reaffirming our full-year ${cop.fiscal_year} guidance across all metrics.`
      && Array.isArray(claim.reaffirmed_by) && claim.reaffirmed_by.length === 1 && claim.reaffirmed_by[0].passage === op.current.passage);
    const ref = docs.get(claim.reaffirmed_by[0].document_id), cap = captures.get(r.capture);
    need(ref && cap && cap.role === "NBIS_SHAREHOLDER_LETTER" && ref.url === cap.url && ref.sha256 === cap.sha256
      && ref.published_date === route.filed && source.published_date < ref.published_date);
  }
  for (const item of attempt.event.later_documents) if (item.date >= source.published_date) need(consumed.has(triple(item)));
  const cal = decisions.find(d => d.kind === "CALENDAR"); need(cal && cal.ref === "calendar");
  const co = cal.operands;
  need(co.rule === "CALENDAR_YEAR_TABLE_V1" && Array.isArray(co.proofs) && co.proofs.length > 0 && co.proofs.length <= 64
    && Array.isArray(co.full_year) && co.full_year.length > 0 && Array.isArray(co.intervals) && co.intervals.length === 4);
  for (const proof of co.proofs) {
    boundFact(proof); const year = Number(proof.end.slice(0,4)), q = Number(proof.end.slice(5,7)) / 3;
    const period = nbisQuarter(year, q); need(proof.end === period.end && (proof.start === period.start || proof.start === `${year}-01-01`));
  }
  need(equal(co.full_year, co.proofs.filter((v: any) => v.start === v.end.slice(0,4) + "-01-01" && v.end.endsWith("-12-31")))
    && cal.capture === co.full_year[0].capture);
  let year = route.report_period.fiscal_year, q = route.report_period.quarter;
  for (let i = 0; i < 4; i++) {
    q++; if (q === 5) { q = 1; year++; }
    const interval = nbisQuarter(year, q);
    need(keys(co.intervals[i], ["start", "end"]) && equal(co.intervals[i], interval)
      && record.forward_intervals[i].start === interval.start && record.forward_intervals[i].end === interval.end
      && record.forward_intervals[i].calendar_document_id === co.full_year[0].document_id
      && record.forward_intervals[i].calendar_locator === co.full_year[0].locator);
  }
  const fd = decisions.find(d => d.kind === "FY_RECONCILIATION"), fy = record.fy_reconciliation;
  need(fd && fd.ref === claim.id && object(fy) && fd.operands.fy_claim_id === fy.fy_claim_id && fy.fy_claim_id === claim.id
    && fd.operands.start === fy.ytd_start && fd.operands.end === fy.ytd_end && nbisDecimal(fd.operands.value) === fy.ytd_revenue
    && equal(fd.operands.quarters, fy.ytd_quarter_ends) && fy.ytd_start === claim.period_start);
  const ytd = record.reported_quarters.filter((v: any) => v.start >= fy.ytd_start);
  need(equal(fy.ytd_quarter_ends, ytd.map((v: any) => v.end)) && ytd.reduce((n: number, v: any) => n + v.revenue, 0) === fy.ytd_revenue);
  if (ytd.length === 0) need(fd.operands.operand === null && fy.ytd_start === fy.ytd_end && fy.ytd_revenue === 0
    && Date.parse(fy.ytd_start) - Date.parse(route.report_period.end) === 86400000);
  else need(boundFact(fd.operands.operand) === fy.ytd_revenue && fd.operands.operand.start === fy.ytd_start
    && fd.operands.operand.end === route.report_period.end && fy.ytd_end === route.report_period.end);
  const expectedOperands = [...new Set<string>(co.proofs.map((v: any) => canonical(v)))];
  need(sameSet(new Set(operandRefs.keys()), new Set(expectedOperands)) && Array.isArray(co.tagged_proofs)
    && co.tagged_proofs.length === expectedOperands.length && co.tagged_proofs.length > 0 && co.tagged_proofs.length <= 64);
  const tagged = new Map<string, any>();
  for (const proof of co.tagged_proofs) {
    need(keys(proof, ["operand", "tagged"])); const id = canonical(proof.operand);
    need(operandRefs.has(id) && !tagged.has(id)); boundFact(proof.operand); nbisTagged(proof.tagged, proof.operand);
    tagged.set(id, proof.tagged);
  }
  need(equal([...tagged.keys()], expectedOperands));
  for (const d of decisions.filter(d => d.kind === "ACTUAL")) need(equal(d.operands.tagged, tagged.get(canonical(d.operands.operand))));
}

export function validateMachineEnvelope(envelope: any, expected: MachineBindings | undefined,
  issuer: string, cutoff: string | undefined, callbacks: MachineCallbacks): MachineAdmissionContext | null {
  try {
    finite(envelope); need(utf8(JSON.stringify(envelope)) <= 256000);
    need(keys(envelope, ["schema", "admission_mode", "payload", "machine"]) && envelope.schema === MACHINE_SCHEMA
      && envelope.admission_mode === "B1_MACHINE_V1" && expected !== undefined && expected.schema === BINDING_SCHEMA && cutoff === expected.cutoff);
    const pin = expected!.issuers[issuer], m = envelope.machine, p = envelope.payload, e = p.evidence, auto = e.auto_update;
    need(pin !== undefined); // a missing sealed issuer pin stays denied; no default pin
    need(keys(pin, ISSUER_KEYS) && pin.symbol === issuer && pin.disposition !== "CURATED");
    need(keys(m, ["schema", "issuer", "cutoff", "input_digest", "generation_id", "generation_sha256", "identity",
      "record_canonical_json", "producer_canonical_json", "decisions_canonical_json", "receipt_history"]));
    need(m.schema === "revenue-guidance-machine-evidence-v1" && m.issuer === issuer && p.issuer === issuer && p.version === 3
      && m.cutoff === cutoff && p.cutoff === cutoff && e.cutoff === cutoff && m.input_digest === expected!.input_digest
      && m.generation_id === expected!.generation_id && m.generation_sha256 === expected!.generation_sha256 && equal(m.identity, pin.identity));
    need(keys(auto, AUTO_KEYS) && auto.version === "auto-admission-evidence-v1" && auto.issuer === issuer && auto.cutoff === cutoff
      && auto.input_digest === m.input_digest && auto.generation_id === m.generation_id && auto.generation_sha256 === m.generation_sha256
      && ["disposition", "reason", "admission_kind", "identity"].every(k => equal(auto[k], (pin as any)[k])));
    need(e.approval_sha256 === null && e.approval_approved_at === null && e.approval_decisions === null);
    need(Array.isArray(auto.detections) && typeof auto.overflow === "boolean" && Array.isArray(m.receipt_history));
    const summary = auto.receipt;
    need((summary === null ? null : summary.receipt_digest) === pin.receipt_digest);
    const reference = summary === null ? null : summary.reference;
    if (reference === null) need(m.receipt_history.length === 0); // unavailable absence, never clean freshness
    else {
      need(typeof reference === "string" && reference.length > 0);
      for (const row of m.receipt_history) need(object(row) && row.issuer === issuer && row.guidance_document_id === reference
        && instant(row.checked_at) && row.checked_at <= cutoff! && SHA.test(row.digest) && callbacks.receiptDigest(row) === row.digest);
      need(equal(summary.rows, m.receipt_history.map((r: any) => ({checked_at: r.checked_at, digest: r.digest, status: r.status}))));
    }
    const scoped = p.revenue_status === "UNAVAILABLE" && p.revenue_reason === "EVIDENCE_LIMIT";
    if (scoped) need(scopedProjection(p)); // before any available-revenue path; attachment never restores originals
    if (pin.disposition !== "AUTO_VERIFIED") {
      need(["WAITING", "BLOCKED", "SUSPENDED"].includes(pin.disposition) && pin.admission_kind === null
        && pin.attempt_sha256 === null && pin.record_sha256 === null && auto.producer === null
        && m.record_canonical_json === null && m.producer_canonical_json === null && m.decisions_canonical_json === null
        && Array.isArray(auto.decisions) && auto.decisions.length === 0 && Array.isArray(auto.consumed) && auto.consumed.length === 0);
      const reason = machineBarrierReason(pin.disposition, pin.reason);
      if (!scoped) need(p.revenue_status === "UNAVAILABLE" && p.revenue_reason === reason);
      return remember({kind: "BARRIER", scoped, barrierReason: reason, receiptDigest: pin.receipt_digest,
        rawReceiptStatus: summary?.receipt_status ?? null, consumed: new Set()});
    }
    need(["NVDA", "MU", "NBIS"].includes(issuer) && (scoped || p.revenue_basis !== "CONSENSUS"));
    need(pin.admission_kind === "MACHINE_REPLAY" && SHA.test(pin.record_sha256!) && SHA.test(pin.attempt_sha256!)
      && SHA.test(pin.receipt_digest!) && m.generation_id !== null && SHA.test(m.generation_sha256) && summary !== null && reference !== null
      && auto.overflow === false && summary.decision === null);
    const producerPin = auto.producer;
    need(object(producerPin) && producerPin.attempt_sha256 === pin.attempt_sha256 && producerPin.record_sha256 === pin.record_sha256);
    // Hash EXACT UTF-8 canonical strings, not JS-reserialized number spellings.
    need(callbacks.digest(m.record_canonical_json) === pin.record_sha256 && callbacks.digest(m.producer_canonical_json) === pin.attempt_sha256
      && callbacks.digest(m.decisions_canonical_json) === producerPin.decisions_sha256);
    const record = parsed(m.record_canonical_json), attempt = parsed(m.producer_canonical_json), decisions = parsed(m.decisions_canonical_json);
    need(record.symbol === issuer && record.status === "GUIDANCE" && keys(attempt, ["event_key", "attempted_at", "predecessor_sha256",
      "event", "captures", "outcome", "reason", "detail", "record_sha256", "record", "decisions"])
      && attempt.outcome === "VERIFIED" && attempt.reason === null && equal(attempt.record, record)
      && attempt.record_sha256 === pin.record_sha256 && equal(attempt.decisions, decisions) && Array.isArray(decisions) && decisions.length > 0);
    need(instant(attempt.attempted_at) && attempt.attempted_at <= cutoff! && producerPin.attempted_at === attempt.attempted_at
      && producerPin.event_key === attempt.event_key && producerPin.predecessor_sha256 === attempt.predecessor_sha256
      && SHA.test(attempt.predecessor_sha256) && callbacks.digest(canonical(attempt.event)) === producerPin.event_sha256);
    // Select the reviewed dialect from the ORIGINAL hash-bound producing event
    // plus separately pinned profile/code identity, never a payload permission.
    const nbis = issuer === "NBIS" && attempt.event?.adapter === NBIS_MODE;
    need(issuer !== "NBIS" || nbis);
    need(Array.isArray(auto.decisions) && equal(auto.decisions, decisions.map((d: any) => {
      need(keys(d, ["kind", "ref", "decision", "capture", "operands", "reviewed_at"])
        && (nbis ? Object.hasOwn(NBIS_DECISION_FIELDS, d.kind) && d.decision === NBIS_DECISION_FIELDS[d.kind]?.[0]
          : ["CLAIM", "ACTUAL", "CALENDAR", "ROUTING"].includes(d.kind)
            && ["VERBATIM_IN_SOURCE", "XBRL_FACT", "XBRL_YTD_DIFFERENCE", "RELEASE_ROW_EQUALS_FILING", "RULE_QUOTED", "EVENT_CONSUMED"].includes(d.decision))
        && typeof d.ref === "string" && d.ref.length > 0 && d.ref.length <= 80 && instant(d.reviewed_at)
        && d.reviewed_at <= cutoff! && d.reviewed_at === attempt.attempted_at && object(d.operands));
      return {kind: d.kind, ref: d.ref, decision: d.decision, capture: d.capture, operands: d.operands};
    })));
    need(object(attempt.captures) && Array.isArray(producerPin.captures)
      && equal(Object.keys(attempt.captures).sort(), producerPin.captures.map((c: any) => c.key).sort()));
    const captures = new Map<string, any>();
    for (const cap of producerPin.captures) {
      need(keys(cap, ["key", "raw_sha256", "sha256", "meta_sha256", "url", "role", "accession", "retrieved_at"])
        && !captures.has(cap.key) && cap.raw_sha256 === attempt.captures[cap.key]
        && [cap.raw_sha256, cap.sha256, cap.meta_sha256].every((s: any) => typeof s === "string" && SHA.test(s))
        && typeof cap.url === "string" && cap.url.startsWith("https://") && typeof cap.role === "string"
        && instant(cap.retrieved_at) && cap.retrieved_at <= attempt.attempted_at);
      captures.set(cap.key, cap); // raw hash and canonical source hash remain DISTINCT
    }
    for (const d of decisions) need(captures.has(d.capture));
    const routing = decisions.filter((d: any) => d.kind === "ROUTING" && d.decision === "EVENT_CONSUMED");
    need(routing.length === 1);
    const route = routing[0].operands;
    need(route.filed === producerPin.filed && equal(route.report_period, producerPin.report_period)
      && equal(route.reference, producerPin.reference) && route.reference.document_id === reference
      && route.accession === attempt.event.accession && DAY.test(route.filed)
      && object(route.report_period) && DAY.test(route.report_period.start) && DAY.test(route.report_period.end));
    need(keys(attempt.event, nbis ? ["adapter", "accession", "filed", "packages", "channel_history", "ir_item", "wire_item", "later_documents"]
      : ["accession", "filed", "periodic", "calendar", "allocation_sources", "ir_item", "wire_item", "later_documents"])
      && route.filed === attempt.event.filed && captures.get(routing[0].capture).role === "SEC_SUBMISSIONS"
      && equal(route.ir_item, attempt.event.ir_item) && route.reference.document_id === reference
      && typeof route.accession === "string" && /^\d{10}-\d{2}-\d{6}$/.test(route.accession));
    need(Array.isArray(route.consumed) && Array.isArray(auto.consumed));
    const consumed = triples(route.consumed);
    const publicConsumed = triples(auto.consumed.map((t: any) => { need(Array.isArray(t) && t.length === 3); return {channel: t[0], id: t[1], date: t[2]}; }));
    need(sameSet(consumed, publicConsumed));
    need(Array.isArray(record.documents) && record.documents.length > 0 && record.documents.length <= 16
      && Array.isArray(record.claims) && Array.isArray(record.reported_quarters)
      && Array.isArray(record.forward_intervals) && record.reviewed_later_documents.length === 0);
    const docs = new Map<string, any>();
    for (const doc of record.documents) {
      need(object(doc) && referenceId(doc.id) && doc.issuer === issuer && !docs.has(doc.id)); docs.set(doc.id, doc);
      need([...captures.values()].some(c => c.url === doc.url && c.sha256 === doc.sha256 && c.retrieved_at === doc.retrieved_at));
    }
    const derivedReference = deriveActiveGuidanceReference(record, docs, issuer, cutoff!);
    checkActiveGuidanceReference(route.reference, derivedReference);
    checkActiveGuidanceReference(producerPin.reference, derivedReference); // existing route/pin equality ALSO remains above
    need(derivedReference.document_id === reference);
    const referenceDoc = referenceDocument(derivedReference.document_id, docs, issuer, cutoff!);
    need(referenceDoc.published_date === route.filed);
    if (nbis) validateNbisSourceDecisions(record, attempt, decisions, route, captures, docs);
    else {
    for (const c of record.claims) {
      const ds = decisions.filter((d: any) => d.kind === "CLAIM" && d.ref === c.id && d.decision === "VERBATIM_IN_SOURCE");
      need(ds.length === 1);
      const numericSource = docs.get(c.document_id), capture = captures.get(ds[0].capture);
      // Numeric source is NOT necessarily the latest reaffirmation reference:
      // bind the actual decision capture to the original numeric document, never discard it.
      need(numericSource && capture && capture.url === numericSource.url && capture.sha256 === numericSource.sha256
        && capture.retrieved_at === numericSource.retrieved_at && Number(ds[0].operands.point) === c.stated_point
        && Number(ds[0].operands.low) === c.low && Number(ds[0].operands.high) === c.high);
    }
    need(record.reported_quarters.length > 0 && record.reported_quarters.at(-1).end === route.report_period.end);
    for (const q of record.reported_quarters) {
      const ds = decisions.filter((d: any) => d.kind === "ACTUAL" && d.ref === q.end);
      need(ds.length === 1 && docs.has(q.document_id));
      const op = ds[0].operands;
      if (ds[0].decision === "XBRL_FACT") need(op.start === q.start && op.end === q.end && Number(op.value) === q.revenue);
      else {
        need(ds[0].decision === "XBRL_YTD_DIFFERENCE" && Array.isArray(op.longer) && Array.isArray(op.shorter)
          && Number(op.longer[2]) - Number(op.shorter[2]) === q.revenue && object(q.derivation)
          && Number(op.longer[2]) === q.derivation.longer_value && Number(op.shorter[2]) === q.derivation.shorter_value
          && captures.has(op.shorter_capture));
      }
    }
    const release = decisions.filter((d: any) => d.kind === "ACTUAL" && d.ref === `release:${route.report_period.end}`);
    need(release.length === 1 && release[0].decision === "RELEASE_ROW_EQUALS_FILING"
      && Number(release[0].operands.value) === record.reported_quarters.at(-1).revenue && release[0].capture === "exhibit");
    const cal = decisions.filter((d: any) => d.kind === "CALENDAR" && d.decision === "RULE_QUOTED");
    need(cal.length === 1 && cal[0].ref === "calendar" && cal[0].capture === attempt.event.calendar
      && typeof cal[0].operands.rule === "string" && Array.isArray(cal[0].operands.offsets)
      && cal[0].operands.offsets.length === 2 && cal[0].operands.offsets.every((n: any) => Number.isInteger(n) && n >= 0));
    for (const interval of record.forward_intervals) need(docs.has(interval.calendar_document_id)
      && interval.calendar_locator.length > 0 && interval.start <= interval.end);
    }
    if (!scoped) {
      for (const [source, projected] of [[record.documents, e.documents], [record.claims, e.claims],
        [record.reported_quarters, e.reported_quarters], [record.forward_intervals, e.forward_intervals]]) {
        need(Array.isArray(projected) && source.length === projected.length);
        source.forEach((row: any, i: number) => projection(row, projected[i]));
      }
      projection(record.release_channels, e.release_channels);
      need(equal(record.fy_reconciliation, e.fy_reconciliation) && Array.isArray(e.reviewed_later_documents) && e.reviewed_later_documents.length === 0);
    }
    const history = m.receipt_history;
    need(history.length > 0);
    let newest = history[0];
    for (const row of history) {
      need(row.guidance_published_date === referenceDoc.published_date && row.anchor_end === record.reported_quarters.at(-1).end);
      need(callbacks.receiptStatus(row, record, row.checked_at) === row.status); // historical structural checks, no current-age rewrite
      if (row.checked_at > newest.checked_at) newest = row; // FIRST tie retained like B1 max()
    }
    need(newest.digest === pin.receipt_digest && summary.receipt_digest === newest.digest
      && summary.receipt_status === newest.status && summary.checked_at === newest.checked_at && summary.anchor === newest.anchor_end);
    if (!scoped) need(equal(e.latest_release_check, newest));
    need((Date.parse(cutoff!) - Date.parse(newest.checked_at)) / 3600000 <= 24);
    const rawStatus = callbacks.receiptStatus(newest, record, cutoff!);
    need(rawStatus === newest.status && ["OK", "RESULTS_PUBLISHED", "REVIEW_REQUIRED"].includes(rawStatus));
    const material = new Map<string, any>();
    for (const row of [...history, {later_documents: auto.detections}]) {
      need(Array.isArray(row.later_documents));
      for (const item of row.later_documents) if (MATERIAL.has(item.disposition)) {
        const key = triple(item); if (!material.has(key)) material.set(key, item);
      }
    }
    const remainder = [...material].filter(([key]) => !consumed.has(key)).map(([, d]) =>
      ({channel: d.channel, id: d.id, date: d.date, disposition: d.disposition}));
    need(equal(remainder, summary.unaccounted) && remainder.length === 0 && summary.decision === null);
    return remember({kind: "AUTO", scoped, barrierReason: null, receiptDigest: newest.digest,
      rawReceiptStatus: newest.status, consumed});
  } catch { return null; }
}
/** BOTH financial receipt call sites use this separate effective status ONLY
 * after original strict recompute matches the unchanged raw receipt + complete
 * producer/own-history accounting. Raw status/digest are never rewritten.
 */
export function machineEffectiveReceipt(ctx: MachineAdmissionContext | undefined, receipt: any, raw: string | null): string | null {
  if (!ctx) return raw;
  need(machineContextIsValid(ctx) && ctx.kind === "AUTO" && receipt.digest === ctx.receiptDigest
    && receipt.status === ctx.rawReceiptStatus && raw === receipt.status);
  return ["OK", "RESULTS_PUBLISHED", "REVIEW_REQUIRED"].includes(raw!) ? "OK" : raw;
}
