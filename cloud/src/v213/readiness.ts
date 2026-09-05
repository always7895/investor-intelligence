import { parseV21Top20 } from "../v21/top20";
import { R75_PUBLICATION_MODE_CONTRACT_ID, r75PublicationModeContractHash } from "./publication-mode";
import policy from "../../../config/v213-compact-qa-v1.json";

export const PARSER_SCHEMA = "v213-r75-sec-filing-provenance-v1";
export type VersionEnv = { CF_VERSION_METADATA?: { id: string } };
const VERSION = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
export function servingVersion(env: VersionEnv): string | null {
  const id = env.CF_VERSION_METADATA?.id;
  return typeof id === "string" && VERSION.test(id) ? id : null;
}

function parserCompatibility(): boolean {
  // Fixed synthetic schema probe, not a bundle, account or KV operation.
  const records = Array.from({ length: 20 }, (_, i) => ({
    ticker: `T${String(i).padStart(2, "0")}`, name: "Synthetic readiness", serenity_score: 0, serenity_raw_score: 0,
    risk_penalty: 0, data_quality: 0, rating: "D", category: "Synthetic",
    serenity_factors: { demand_wave: 0, chokepoint: 0, pricing_power: 0, replacement_friction: 0, tam_capture: 0, valuation_expectations: 0, evidence_quality: 0 },
    risk_flags: [], aschenbrenner_overlay: { domain: null, fit_score: 0, included_in_serenity_score: false, attribution: "system_operationalization_not_aschenbrenner_stock_score" },
    evidence: [{ source_id: "sec_edgar", tier: "T0", claim_type: "filing_publication_provenance", title: "Synthetic filing", url: "https://www.sec.gov/Archives/edgar/data/1000000/000100000000000001/",
      as_of: "2000-01-01", publication_date: "2000-01-01", period_end: "1999-12-31", accession_number: "0001000000-00-000001", family: "regulator_filing", primary: true, claim_primary: true,
      provenance_only: true, can_prove_positive_serenity_factor: false, retrieval_timestamp_used_as_publication_date: false },
    { source_id: "nasdaq_symbol_directory", tier: "T2", claim_type: "regulated_listing_identity", title: "Synthetic identity", url: "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt", as_of: "2000-01-01" }],
    evidence_count: 2, source_count: 2, scoring_version: "system-operationalization-v2.1.3-diversified", line_public_eligible: true, provider_scope: "public_only", owner_watchlist_inherited: false,
    rank: i + 1, generated_at: "2000-01-01T00:00:00Z", as_of: "2000-01-01T00:00:00Z",
  }));
  if (!parseV21Top20(records)) return false;
  records[0]!.evidence[0]!.can_prove_positive_serenity_factor = true;
  return parseV21Top20(records) === null;
}

export async function compactPolicyHash(): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(JSON.stringify(policy)));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** PUBLIC and strictly no-write: no HMAC nonce claim, KV, DO, model or LINE call. */
export async function edgeReadiness(request: Request, env: VersionEnv): Promise<Response> {
  const url = new URL(request.url);
  const challenge = url.searchParams.get("challenge") ?? "";
  const expected = url.searchParams.get("expected_version");
  const version = servingVersion(env);
  let code = "";
  if (request.method !== "GET" || url.search.length > 240 || !/^[0-9a-f]{32}$/.test(challenge) || (expected && !VERSION.test(expected)) ||
      [...url.searchParams.keys()].some((key) => !["challenge", "expected_version"].includes(key)) ||
      url.searchParams.getAll("challenge").length !== 1 || url.searchParams.getAll("expected_version").length > 1) code = "V213_READINESS_REQUEST_INVALID";
  else if (!version) code = "V213_READINESS_VERSION_UNAVAILABLE";
  else if (expected && version !== expected) code = "V213_READINESS_VERSION_MISMATCH";
  else if (!parserCompatibility()) code = "V213_READINESS_PARSER_FAILED";
  const result = code ? { ready: false, code, worker_version: version, challenge, no_write: true } : {
    schema_version: 1, ready: true, worker_version: version, challenge, parser_schema: PARSER_SCHEMA,
    publication_contract_id: R75_PUBLICATION_MODE_CONTRACT_ID,
    publication_contract_sha256: await r75PublicationModeContractHash(), compact_policy_sha256: await compactPolicyHash(),
    compatibility: "PASS", no_write: true,
  };
  return new Response(JSON.stringify(result), { status: code ? 409 : 200,
    headers: { "content-type": "application/json", "cache-control": "no-store, max-age=0", "x-content-type-options": "nosniff", "x-ii-serving-version": version ?? "unavailable" } });
}
