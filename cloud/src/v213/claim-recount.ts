/**
 * Worker port of the structural claim recount (publication-mode contract v2).
 *
 * Python references: scripts/source_observation.py compute_independent_lineages and
 * scripts/claim_lineage_qualification.py claim_lineage_structurally_qualified. Both
 * are executed against the SAME vector file
 * (tests/fixtures/v213-r75-publication-mode/claim-recount-vectors.json) by a Python
 * unittest and a Vitest file, so a drift in either implementation fails a test.
 *
 * Fail closed: every missing field or wrong type returns false (the Python code
 * relies on KeyError/TypeError/AttributeError being caught; here those paths
 * throw internally and are caught once at the public entry).
 *
 * Deliberately NOT included: validated_at, valid_until, per-evidence valid_until,
 * clock skew and the guard validity reserve. Expiry is a producer concern; this
 * check runs up to max_bundle_age_seconds after the build.
 */

type Json = unknown;

function isMapping(value: Json): value is Record<string, Json> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

// Python str.isspace() code points: strip() must remove exactly these, not JS trim().
const PY_WHITESPACE = new Set<number>([
  0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x1c, 0x1d, 0x1e, 0x1f, 0x20, 0x85, 0xa0, 0x1680,
  0x2000, 0x2001, 0x2002, 0x2003, 0x2004, 0x2005, 0x2006, 0x2007, 0x2008, 0x2009, 0x200a,
  0x2028, 0x2029, 0x202f, 0x205f, 0x3000,
]);

export function pyStrip(text: string): string {
  const points = Array.from(text);
  let start = 0;
  let end = points.length;
  while (start < end && PY_WHITESPACE.has(points[start]!.codePointAt(0)!)) start += 1;
  while (end > start && PY_WHITESPACE.has(points[end - 1]!.codePointAt(0)!)) end -= 1;
  return points.slice(start, end).join("");
}

/** Python truthiness for JSON values. */
export function pyTruthy(value: Json): boolean {
  if (value === null || value === undefined || value === false || value === 0 || value === "") return false;
  if (Array.isArray(value)) return value.length > 0;
  if (isMapping(value)) return Object.keys(value).length > 0;
  return true;
}

/** Python == for JSON values (True == 1, 1 == 1.0, lists and dicts structurally). */
export function pyEquals(left: Json, right: Json): boolean {
  const a = left === undefined ? null : left;
  const b = right === undefined ? null : right;
  const numeric = (value: Json): number | undefined =>
    typeof value === "boolean" ? (value ? 1 : 0) : typeof value === "number" ? value : undefined;
  const na = numeric(a);
  const nb = numeric(b);
  if (na !== undefined || nb !== undefined) return na !== undefined && nb !== undefined && na === nb;
  if (a === null || b === null) return a === b;
  if (typeof a === "string" || typeof b === "string") return typeof a === "string" && typeof b === "string" && a === b;
  if (Array.isArray(a) || Array.isArray(b)) {
    return Array.isArray(a) && Array.isArray(b) && a.length === b.length && a.every((item, index) => pyEquals(item, b[index]));
  }
  if (isMapping(a) && isMapping(b)) {
    const keys = Object.keys(a);
    return keys.length === Object.keys(b).length && keys.every((key) => Object.prototype.hasOwnProperty.call(b, key) && pyEquals(a[key], b[key]));
  }
  return false;
}

function pyIn(item: Json, list: Json[]): boolean {
  return list.some((entry) => pyEquals(item, entry));
}

function strippedString(value: Json): string {
  return typeof value === "string" ? pyStrip(value) : "";
}

/**
 * Connected components of observations that share a publisher, origin or content
 * hash (transitive). Port of source_observation.compute_independent_lineages:
 * non-string identities are ignored (never coerced), an observation without a
 * usable key is skipped, and a truthy non-mapping `payload` is an error (Python
 * raises AttributeError; the public entry turns it into a refusal).
 */
export function computeIndependentLineages(observations: Json[]): number {
  let components: Array<Set<string>> = [];
  for (const obs of observations) {
    if (!isMapping(obs)) continue;
    const indep = strippedString(obs.independence_group);
    let originRaw: Json = obs.origin_group;
    if (!pyTruthy(originRaw)) {
      const payload: Json = pyTruthy(obs.payload) ? obs.payload : {};
      if (!isMapping(payload)) throw new Error("PAYLOAD_NOT_MAPPING");
      originRaw = payload.origin_group;
    }
    const origin = strippedString(originRaw);
    const sha = strippedString(obs.content_sha256);

    const keys = new Set<string>();
    if (indep) keys.add(`publisher:${indep}`);
    if (origin) keys.add(`origin:${origin}`);
    if (sha) keys.add(`hash:${sha}`);
    if (keys.size === 0) continue;

    const matched = components.filter((component) => [...component].some((key) => keys.has(key)));
    for (const component of matched) component.forEach((key) => keys.add(key));
    components = components.filter((component) => !matched.includes(component));
    components.push(keys);
  }
  return components.length;
}

function claimsQualified(claims: Json[], evidence: Json[], minimum: number): boolean {
  const seen = new Set<string>();
  for (const claim of claims) {
    if (!isMapping(claim)) return false;
    const claimId = claim.claim_id;
    if (typeof claimId !== "string" || !pyStrip(claimId) || seen.has(claimId)) return false;
    if (claim.status !== "SUPPORTED" || claim.high_confidence_eligible !== true || pyTruthy(claim.conflict_set)) return false;
    const evidenceIds = claim.evidence_ids;
    if (!Array.isArray(evidenceIds)) return false;
    seen.add(claimId);
    const bound = evidence.filter((row) =>
      isMapping(row) && row.admitted === true && row.freshness === "CURRENT" &&
      pyIn(row.observation_id, evidenceIds) && Array.isArray(row.claim_ids) && pyIn(claimId, row.claim_ids));
    if (computeIndependentLineages(bound) < minimum) return false;
    for (const row of bound as Array<Record<string, Json>>) {
      // Python: row["value"] / claim["value"] raise KeyError when absent -> refusal.
      if (!Object.prototype.hasOwnProperty.call(row, "value") || !Object.prototype.hasOwnProperty.call(claim, "value")) return false;
      if (!pyEquals(row.value, claim.value)) return false;
    }
  }
  return true;
}

/**
 * Rules 1-6 of contract v2 for ONE EVIDENCE_QUALIFIED source-audit record:
 * recompute from record.claim_evidence_audit. `minimumFamilies` is the contract's
 * min_evidence_claim_families (equal to the producer policy minimum, an int >= 2).
 */
export function claimLineageStructurallyQualified(auditRow: Json, minimumFamilies: number): boolean {
  try {
    if (!Number.isInteger(minimumFamilies) || minimumFamilies < 2) return false;
    if (!isMapping(auditRow)) return false;
    const audit = auditRow.claim_evidence_audit;
    if (!isMapping(audit) || audit.schema_version !== 2) return false;
    const claims = audit.claims;
    const evidence = audit.evidence;
    if (audit.all_material_claims_supported !== true || !Array.isArray(claims) || claims.length === 0 || !Array.isArray(evidence)) {
      return false;
    }
    return claimsQualified(claims, evidence, minimumFamilies);
  } catch {
    return false;
  }
}
