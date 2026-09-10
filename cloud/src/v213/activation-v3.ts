// Active source-safe implementation; activation-v2 remains byte-frozen for
// historical R75 verification. Bundle schemas/signatures are unchanged.
import type { V21AdminEnv } from "../v21/admin";
import { parseV21Top20, type V21Evidence, type V21Top20Record } from "../v21/top20";
import { parseV212Top20Report } from "../v212/top20-report";
import { parseV213Top20Report } from "./top20-report";
import contract from "../../../config/v213-r75-publication-mode-v1.json";
import { r75PublicationModeContractHash, validateR75PublicationModes } from "./publication-mode";

const ENCODER = new TextEncoder();
const RUN_ID_RE = /^\d{8}T\d{6}Z-[0-9a-f]{12}$/;
const TRANSACTION_ID_RE = /^[0-9a-f]{32}$/;
const HEX_64_RE = /^[0-9a-f]{64}$/;
const SCORING_VERSION = contract.scoring_version;
const MARKET_DEGRADATION = "INSUFFICIENT_NON_YAHOO_MARKET_COVERAGE";
const MARKET_MISSING = "NON_YAHOO_MARKET_CORROBORATION";
const PAYLOAD_NAMES = contract.payload_names;
const REQUIRED_REPORT_MARKERS = contract.report_markers;
const FORBIDDEN_PUBLIC_KEYS = new Set([
  "account", "account_id", "portfolio", "position", "positions", "holding", "holdings",
  "cost_basis", "pnl", "line_user_id", "raw_user_id", "tenant_id", "conversation",
  "private_message", "brokerage", "ibkr", "secret", "token",
]);

interface RollbackState {
  schema_version: 2;
  transaction_id: string;
  run_id: string;
  previous_pointer: string | null;
  previous_run_id: string | null;
  created_at: string;
}

interface RunClaim {
  schema_version: 1;
  transaction_id: string;
  run_id: string;
  payload_digests: Record<string, string>;
  claimed_at: string;
}

function exactKeys(value: Record<string, unknown>, expected: readonly string[]): boolean {
  const left = Object.keys(value).sort();
  const right = [...expected].sort();
  return left.length === right.length && left.every((key, index) => key === right[index]);
}

function finite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function parsedTime(value: unknown): number | null {
  const parsed = typeof value === "string" ? Date.parse(value) : Number.NaN;
  return Number.isFinite(parsed) ? parsed : null;
}

function object(value: unknown, code: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(code);
  return value as Record<string, unknown>;
}

function array(value: unknown, code: string): unknown[] {
  if (!Array.isArray(value)) throw new Error(code);
  return value;
}

function rejectPrivateKeys(
  value: unknown,
  path = "$",
  allowRootSourcePortfolio = false,
): void {
  if (Array.isArray(value)) {
    value.forEach((entry, index) => rejectPrivateKeys(entry, `${path}[${index}]`, false));
    return;
  }
  if (!value || typeof value !== "object") return;
  for (const [key, child] of Object.entries(value as Record<string, unknown>)) {
    const normalized = key.toLowerCase();
    const catalogTopic = path === "$.inventory.topic_counts" && normalized === "positions";
    const publicSourceProfile = allowRootSourcePortfolio && path === "$" && normalized === "portfolio";
    if (FORBIDDEN_PUBLIC_KEYS.has(normalized) && !catalogTopic && !publicSourceProfile) {
      throw new Error("V213_ACTIVATION_PRIVATE_FIELD");
    }
    rejectPrivateKeys(child, `${path}.${key}`, false);
  }
}

function parseJson(
  text: string,
  code: string,
  allowRootSourcePortfolio = false,
): unknown {
  try {
    const value = JSON.parse(text) as unknown;
    rejectPrivateKeys(value, "$", allowRootSourcePortfolio);
    return value;
  } catch (error) {
    if (error instanceof Error && error.message === "V213_ACTIVATION_PRIVATE_FIELD") throw error;
    throw new Error(code);
  }
}

async function sha256(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", ENCODER.encode(value));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function tickerOrder(rows: unknown[], code: string): string[] {
  if (rows.length !== 20) throw new Error(code);
  const seen = new Set<string>();
  return rows.map((raw, index) => {
    const row = object(raw, code);
    const ticker = String(row.ticker ?? "").toUpperCase();
    if (!/^[A-Z0-9][A-Z0-9.-]{0,14}$/.test(ticker) || seen.has(ticker) || row.rank !== index + 1) {
      throw new Error(code);
    }
    seen.add(ticker);
    return ticker;
  });
}

function sameOrder(left: string[], right: string[], code: string): void {
  if (left.length !== right.length || left.some((ticker, index) => ticker !== right[index])) {
    throw new Error(code);
  }
}

function currentRunId(pointer: string | null): string | null {
  if (!pointer) return null;
  try {
    const parsed = JSON.parse(pointer) as { run_id?: unknown; runId?: unknown };
    return String(parsed.run_id ?? parsed.runId ?? "") || null;
  } catch {
    return pointer.trim() || null;
  }
}

function validateSourcePlan(raw: unknown): Record<string, unknown> {
  const plan = object(raw, "V213_ACTIVATION_SOURCE_PLAN_INVALID");
  const inventory = object(plan.inventory, "V213_ACTIVATION_SOURCE_PLAN_INVALID");
  const federation = object(plan.live_source_federation, "V213_ACTIVATION_SOURCE_PLAN_INVALID");
  const scoring = object(plan.scoring_methodology, "V213_ACTIVATION_SOURCE_PLAN_INVALID");
  const successfulFamilies = Array.isArray(federation.successful_families) ? federation.successful_families.map(String) : [];
  const officialFamilies = Array.isArray(federation.official_successful_families) ? federation.official_successful_families.map(String) : [];
  if (
    plan.schema_version !== 1 || plan.catalog_count !== 101 ||
    plan.automatic_activation !== false || plan.owner_watchlist_inherited !== false ||
    plan.provider_scope !== "public_only" || plan.line_public_eligible !== true ||
    inventory.source_count !== 101 || inventory.runtime_enabled_count !== 0 ||
    successfulFamilies.length < contract.thresholds.min_successful_families || contract.required_federation_families.some((family) => !successfulFamilies.includes(family)) ||
    officialFamilies.length < contract.thresholds.min_official_successful_families || contract.required_federation_families.some((family) => !officialFamilies.includes(family)) ||
    !finite(federation.ticker_coverage_ratio) || federation.ticker_coverage_ratio < contract.thresholds.min_ticker_coverage_ratio ||
    federation.unresolved_material_conflict_count !== 0 ||
    federation.yahoo_authoritative !== false ||
    federation.catalog_source_count_is_not_live_use !== true ||
    scoring.scoring_version !== SCORING_VERSION ||
    scoring.official_serenity_formula_claimed !== false ||
    scoring.private_process_reproduction_claimed !== false
  ) throw new Error("V213_ACTIVATION_SOURCE_PLAN_INVALID");
  return plan;
}

function validateFederation(raw: unknown, order: string[]): Record<string, unknown> {
  const doc = object(raw, "V213_ACTIVATION_FEDERATION_INVALID");
  const gates = object(doc.gates, "V213_ACTIVATION_FEDERATION_INVALID");
  const successful = array(gates.successful_families, "V213_ACTIVATION_FEDERATION_INVALID").map(String);
  const official = array(gates.official_successful_families, "V213_ACTIVATION_FEDERATION_INVALID").map(String);
  const required = contract.required_federation_families;
  if (
    doc.schema_version !== 1 || doc.product_version !== "2.1.3" ||
    parsedTime(doc.generated_at) === null || gates.pass !== true ||
    successful.length < contract.thresholds.min_successful_families || official.length < contract.thresholds.min_official_successful_families || required.some((family) => !successful.includes(family) || !official.includes(family)) ||
    !finite(gates.ticker_coverage_ratio) || gates.ticker_coverage_ratio < contract.thresholds.min_ticker_coverage_ratio ||
    gates.unresolved_material_conflict_count !== 0 || gates.concentration_pass !== true ||
    gates.yahoo_authoritative !== false || gates.catalog_source_count_is_not_live_use !== true
  ) throw new Error("V213_ACTIVATION_FEDERATION_INVALID");
  sameOrder(
    tickerOrder(array(doc.ticker_sources, "V213_ACTIVATION_FEDERATION_ORDER_INVALID"), "V213_ACTIVATION_FEDERATION_ORDER_INVALID"),
    order,
    "V213_ACTIVATION_FEDERATION_ORDER_INVALID",
  );
  return doc;
}

function validateSourceAudit(
  raw: unknown,
  order: string[],
  top20: V21Top20Record[],
): Record<string, unknown> {
  const doc = object(raw, "V213_ACTIVATION_SOURCE_AUDIT_INVALID");
  const portfolio = object(doc.portfolio, "V213_ACTIVATION_SOURCE_AUDIT_INVALID");
  const notice = object(doc.methodology_notice, "V213_ACTIVATION_SOURCE_AUDIT_INVALID");
  const violations = array(doc.violations, "V213_ACTIVATION_SOURCE_AUDIT_INVALID");
  const blockers = array(doc.blocking_violations, "V213_ACTIVATION_SOURCE_AUDIT_INVALID");
  const degradations = array(doc.degradations, "V213_ACTIVATION_SOURCE_AUDIT_INVALID").map(String);
  const records = array(doc.records, "V213_ACTIVATION_SOURCE_AUDIT_INVALID");
  const coverage = Number(portfolio.non_yahoo_market_coverage_ratio ?? 0);
  const target = Number(portfolio.non_yahoo_market_coverage_target_ratio ?? 0.75);
  const degraded = coverage < target;
  if (
    !finite(doc.schema_version) || doc.schema_version < 3 || doc.product_version !== "2.1.3" ||
    doc.status !== "PASS" || parsedTime(doc.generated_at) === null ||
    violations.length !== 0 || blockers.length !== 0 || records.length !== contract.thresholds.ticker_count ||
    !finite(portfolio.independent_source_families) || portfolio.independent_source_families < contract.thresholds.min_independent_source_families ||
    !finite(portfolio.independent_domains) || portfolio.independent_domains < contract.thresholds.min_independent_domains ||
    !finite(portfolio.claim_primary_coverage_ratio) || portfolio.claim_primary_coverage_ratio < contract.thresholds.min_claim_primary_coverage_ratio ||
    !finite(portfolio.claim_source_families) || portfolio.claim_source_families < contract.thresholds.min_portfolio_claim_source_families ||
    !finite(portfolio.claim_source_domains) || portfolio.claim_source_domains < contract.thresholds.min_portfolio_claim_source_domains ||
    !finite(portfolio.maximum_single_family_share) || portfolio.maximum_single_family_share > contract.thresholds.max_single_family_share ||
    portfolio.market_conflict_ticker_count !== 0 ||
    !Number.isFinite(coverage) || coverage < 0 || coverage > 1 ||
    !Number.isFinite(target) || target <= 0 || target > 1 ||
    notice.official_serenity_formula !== false ||
    notice.official_serenity_score !== false ||
    notice.private_method_reproduced !== false ||
    notice.single_source_inference_allowed !== false ||
    notice.source_diversity_is_not_truth_by_itself !== true ||
    notice.official_macro_is_not_company_claim_evidence !== true ||
    notice.market_corroboration_unavailable_is_global_blocker !== false ||
    notice.market_corroboration_required_for_high_confidence_model_inference !== true ||
    notice.market_corroboration_required_for_uncapped_valuation_factor !== true ||
    notice.provider_failure_must_be_disclosed !== true ||
    notice.provider_failure_must_not_be_silently_relabelled_as_success !== true ||
    notice.market_data_is_not_averaged_into_published_returns !== true ||
    !finite(notice.uncorroborated_valuation_factor_max) ||
    notice.uncorroborated_valuation_factor_max > contract.thresholds.max_uncorroborated_valuation_factor
  ) throw new Error("V213_ACTIVATION_SOURCE_AUDIT_INVALID");
  sameOrder(
    tickerOrder(records, "V213_ACTIVATION_SOURCE_AUDIT_ORDER_INVALID"),
    order,
    "V213_ACTIVATION_SOURCE_AUDIT_ORDER_INVALID",
  );

  if (degraded) {
    if (
      doc.quality_status !== "PASS_WITH_DEGRADATION" ||
      portfolio.market_corroboration_status !== "DEGRADED" ||
      portfolio.market_corroboration_global_blocker !== false ||
      !degradations.includes(MARKET_DEGRADATION)
    ) throw new Error("V213_ACTIVATION_MARKET_DEGRADATION_INVALID");
  } else if (
    !["PASS", undefined].includes(doc.quality_status as string | undefined) ||
    portfolio.market_corroboration_status !== "CORROBORATED" ||
    degradations.includes(MARKET_DEGRADATION)
  ) {
    throw new Error("V213_ACTIVATION_MARKET_STATUS_INVALID");
  }

  let eligibleCount = 0;
  records.forEach((rawRecord, index) => {
    const record = object(rawRecord, "V213_ACTIVATION_SOURCE_AUDIT_RECORD_INVALID");
    const metrics = object(record.source_metrics, "V213_ACTIVATION_SOURCE_AUDIT_RECORD_INVALID");
    const market = object(record.market_corroboration, "V213_ACTIVATION_SOURCE_AUDIT_RECORD_INVALID");
    const logic = object(record.public_logic_state, "V213_ACTIVATION_SOURCE_AUDIT_RECORD_INVALID");
    const missing = array(record.missing_or_review, "V213_ACTIVATION_SOURCE_AUDIT_RECORD_INVALID").map(String);
    const providerCount = Number(market.independent_provider_count ?? 0);
    const eligible = record.eligible_for_high_confidence_model_inference === true;
    if (eligible) eligibleCount += 1;
    if (providerCount < 1) {
      if (
        eligible || logic.model_inference_confidence !== "LIMITED" ||
        !missing.includes(MARKET_MISSING) ||
        Number(top20[index]?.serenity_factors.valuation_expectations ?? 99) > contract.thresholds.max_uncorroborated_valuation_factor
      ) throw new Error("V213_ACTIVATION_UNCORROBORATED_CONFIDENCE_INVALID");
    } else if (eligible && (
      market.status !== "CORROBORATED" ||
      Number(metrics.claim_relevant_independent_families ?? 0) < 2 ||
      Number(metrics.claim_relevant_independent_domains ?? 0) < 2 ||
      Number(metrics.claim_relevant_primary_sources ?? 0) < 1 ||
      Number(metrics.claim_dated_evidence_ratio ?? 0) < 0.8 ||
      missing.includes("MARKET_SOURCE_CONFLICT_REVIEW")
    )) {
      throw new Error("V213_ACTIVATION_HIGH_CONFIDENCE_INVALID");
    }
  });
  if (eligibleCount !== Number(portfolio.high_confidence_model_inference_eligible_count ?? -1)) {
    throw new Error("V213_ACTIVATION_HIGH_CONFIDENCE_COUNT_INVALID");
  }
  return doc;
}

function derivedScores(top20: V21Top20Record[]): Array<Record<string, unknown>> {
  return top20.map((item) => ({
    rank: item.rank,
    ticker: item.ticker,
    name: item.name,
    total_score: item.serenity_score,
    data_quality: item.data_quality,
    rating: item.rating,
    category: item.category,
    source_count: item.source_count,
    evidence_count: item.evidence_count,
    scoring_version: item.scoring_version,
    line_public_eligible: true,
    provider_scope: "public_only",
    owner_watchlist_inherited: false,
  }));
}

function derivedSourceViews(top20: V21Top20Record[]): Array<Record<string, unknown>> {
  const seen = new Set<string>();
  const result: Array<Record<string, unknown>> = [];
  for (const item of top20) {
    for (const evidence of item.evidence as V21Evidence[]) {
      if (seen.has(evidence.url)) continue;
      seen.add(evidence.url);
      result.push({
        author: evidence.source_id,
        title: evidence.title,
        summary: `Public evidence for ${item.ticker}`,
        url: evidence.url,
        published_at: evidence.as_of,
        source_id: evidence.source_id,
        tier: evidence.tier,
        claim_type: evidence.claim_type,
        line_public_eligible: true,
        provider_scope: "public_only",
        owner_watchlist_inherited: false,
      });
      if (result.length >= 60) return result;
    }
  }
  return result;
}

function rollbackKey(transactionId: string): string {
  return `v213:activation-rollback:${transactionId}`;
}

function claimKey(runId: string): string {
  return `snapshot:${runId}:v213:activation-claim`;
}

function parseControl(body: string): { transaction_id: string; run_id: string } {
  let raw: unknown;
  try { raw = JSON.parse(body) as unknown; }
  catch { throw new Error("V213_ACTIVATION_CONTROL_JSON_INVALID"); }
  const value = object(raw, "V213_ACTIVATION_CONTROL_INVALID");
  if (!exactKeys(value, ["schema_version", "transaction_id", "run_id"]) || value.schema_version !== 1) {
    throw new Error("V213_ACTIVATION_CONTROL_INVALID");
  }
  const transactionId = String(value.transaction_id ?? "");
  const runId = String(value.run_id ?? "");
  if (!TRANSACTION_ID_RE.test(transactionId) || !RUN_ID_RE.test(runId)) {
    throw new Error("V213_ACTIVATION_CONTROL_INVALID");
  }
  return { transaction_id: transactionId, run_id: runId };
}

function parseRollbackState(text: string, transactionId: string, runId: string): RollbackState {
  let raw: unknown;
  try { raw = JSON.parse(text) as unknown; }
  catch { throw new Error("V213_ACTIVATION_ROLLBACK_STATE_INVALID"); }
  const value = object(raw, "V213_ACTIVATION_ROLLBACK_STATE_INVALID");
  if (
    !exactKeys(value, ["schema_version", "transaction_id", "run_id", "previous_pointer", "previous_run_id", "created_at"]) ||
    value.schema_version !== 2 || value.transaction_id !== transactionId || value.run_id !== runId ||
    !(value.previous_pointer === null || typeof value.previous_pointer === "string") ||
    !(value.previous_run_id === null || typeof value.previous_run_id === "string") ||
    parsedTime(value.created_at) === null
  ) throw new Error("V213_ACTIVATION_ROLLBACK_STATE_INVALID");
  return value as unknown as RollbackState;
}

function parseRunClaim(text: string): RunClaim {
  let raw: unknown;
  try { raw = JSON.parse(text) as unknown; }
  catch { throw new Error("V213_ACTIVATION_RUN_CLAIM_INVALID"); }
  const value = object(raw, "V213_ACTIVATION_RUN_CLAIM_INVALID");
  if (
    !exactKeys(value, ["schema_version", "transaction_id", "run_id", "payload_digests", "claimed_at"]) ||
    value.schema_version !== 1 || !TRANSACTION_ID_RE.test(String(value.transaction_id ?? "")) ||
    !RUN_ID_RE.test(String(value.run_id ?? "")) || parsedTime(value.claimed_at) === null
  ) throw new Error("V213_ACTIVATION_RUN_CLAIM_INVALID");
  const digests = object(value.payload_digests, "V213_ACTIVATION_RUN_CLAIM_INVALID");
  if (!exactKeys(digests, PAYLOAD_NAMES) || Object.values(digests).some((item) => typeof item !== "string" || !HEX_64_RE.test(item))) {
    throw new Error("V213_ACTIVATION_RUN_CLAIM_INVALID");
  }
  return value as unknown as RunClaim;
}

function sameDigests(left: Record<string, string>, right: Record<string, unknown>): boolean {
  return PAYLOAD_NAMES.every((name) => left[name] === String(right[name] ?? ""));
}

async function verifySnapshotObjects(
  env: V21AdminEnv,
  prefix: string,
  objects: Array<[string, string]>,
  replay = false,
): Promise<void> {
  for (const [key, expected] of objects) {
    const observed = await env.PUBLIC_CACHE.get(`${prefix}${key}`, "text");
    if (observed !== expected) {
      throw new Error(replay ? "V213_ACTIVATION_REPLAY_CORRUPT" : "V213_ACTIVATION_SNAPSHOT_READBACK_FAILED");
    }
  }
}

export async function ingestV213ActivationBundle(
  body: string,
  env: V21AdminEnv,
): Promise<Record<string, unknown>> {
  let raw: unknown;
  try { raw = JSON.parse(body) as unknown; }
  catch { throw new Error("V213_ACTIVATION_BUNDLE_JSON_INVALID"); }
  const root = object(raw, "V213_ACTIVATION_BUNDLE_INVALID");
  if (!exactKeys(root, ["schema_version", "product_version", "transaction_id", "run_id", "generated_at", "public_data_as_of", "payloads", "sha256"])) {
    throw new Error("V213_ACTIVATION_BUNDLE_KEYS_INVALID");
  }
  const transactionId = String(root.transaction_id ?? "");
  const runId = String(root.run_id ?? "");
  if (
    root.schema_version !== 4 || root.product_version !== "2.1.3" ||
    !TRANSACTION_ID_RE.test(transactionId) || !RUN_ID_RE.test(runId)
  ) throw new Error("V213_ACTIVATION_BUNDLE_INVALID");
  const generatedAt = parsedTime(root.generated_at);
  const publicAsOf = parsedTime(root.public_data_as_of);
  const now = Date.now();
  if (
    generatedAt === null || publicAsOf === null || generatedAt > now + 300_000 ||
    publicAsOf > generatedAt + 300_000 || now - generatedAt > 7_200_000
  ) throw new Error("V213_ACTIVATION_BUNDLE_STALE");

  const payloads = object(root.payloads, "V213_ACTIVATION_PAYLOADS_INVALID");
  const digests = object(root.sha256, "V213_ACTIVATION_DIGESTS_INVALID");
  if (!exactKeys(payloads, PAYLOAD_NAMES) || !exactKeys(digests, PAYLOAD_NAMES)) {
    throw new Error("V213_ACTIVATION_PAYLOAD_KEYS_INVALID");
  }
  for (const name of PAYLOAD_NAMES) {
    if (typeof payloads[name] !== "string" || typeof digests[name] !== "string" || !HEX_64_RE.test(String(digests[name]))) {
      throw new Error("V213_ACTIVATION_PAYLOAD_TYPE_INVALID");
    }
    if ((await sha256(String(payloads[name]))) !== String(digests[name])) {
      throw new Error(`V213_ACTIVATION_DIGEST_MISMATCH_${name.toUpperCase()}`);
    }
  }

  const top20 = parseV21Top20(parseJson(String(payloads.top20_json), "V213_ACTIVATION_TOP20_JSON_INVALID"));
  if (!top20 || top20.some((row) => row.scoring_version !== SCORING_VERSION)) {
    throw new Error("V213_ACTIVATION_TOP20_INVALID");
  }
  const order = top20.map((row) => row.ticker);
  const plan = validateSourcePlan(parseJson(String(payloads.source_plan_json), "V213_ACTIVATION_SOURCE_PLAN_JSON_INVALID"));
  const report = String(payloads.report_text);
  if (report.length < 200 || report.length > 200_000 || REQUIRED_REPORT_MARKERS.some((marker) => !report.includes(marker))) {
    throw new Error("V213_ACTIVATION_REPORT_ATTESTATION_INVALID");
  }
  const v212 = parseV212Top20Report(parseJson(String(payloads.v212_top20_report_json), "V213_ACTIVATION_V212_JSON_INVALID"));
  const v213 = parseV213Top20Report(parseJson(String(payloads.v213_top20_report_json), "V213_ACTIVATION_V213_JSON_INVALID"));
  if (!v212 || !v213) throw new Error("V213_ACTIVATION_REPORT_SCHEMA_INVALID");
  sameOrder(v212.records.map((row) => row.ticker), order, "V213_ACTIVATION_V212_ORDER_INVALID");
  sameOrder(v213.records.map((row) => row.ticker), order, "V213_ACTIVATION_V213_ORDER_INVALID");
  const federation = validateFederation(
    parseJson(String(payloads.source_federation_json), "V213_ACTIVATION_FEDERATION_JSON_INVALID"),
    order,
  );
  const sourceAudit = validateSourceAudit(
    parseJson(String(payloads.source_independence_json), "V213_ACTIVATION_SOURCE_AUDIT_JSON_INVALID", true),
    order,
    top20,
  );
  const publicationMode = validateR75PublicationModes(sourceAudit, top20 as unknown as Array<Record<string, unknown>>);
  const publicationModeContractHash = await r75PublicationModeContractHash();

  const previousPointer = await env.PUBLIC_CACHE.get("snapshot:current", "text");
  const previousRunId = currentRunId(previousPointer);
  const rollbackStateKey = rollbackKey(transactionId);
  const existingStateText = await env.TENANT_PRIVATE_CACHE.get(rollbackStateKey, "text");
  let state: RollbackState;
  let idempotentReplay = false;
  let journalRecovered = false;
  if (existingStateText) {
    state = parseRollbackState(existingStateText, transactionId, runId);
    idempotentReplay = previousRunId === runId;
    journalRecovered = !idempotentReplay;
    if (!idempotentReplay && previousPointer !== state.previous_pointer) {
      throw new Error("V213_ACTIVATION_CONCURRENT_POINTER_CHANGE");
    }
  } else {
    state = {
      schema_version: 2,
      transaction_id: transactionId,
      run_id: runId,
      previous_pointer: previousPointer,
      previous_run_id: previousRunId,
      created_at: new Date().toISOString(),
    };
  }

  await env.TENANT_PRIVATE_CACHE.put(rollbackStateKey, JSON.stringify(state));
  const runClaimKey = claimKey(runId);
  const existingClaimText = await env.PUBLIC_CACHE.get(runClaimKey, "text");
  if (existingClaimText) {
    const claim = parseRunClaim(existingClaimText);
    if (claim.transaction_id !== transactionId || claim.run_id !== runId || !sameDigests(claim.payload_digests, digests)) {
      throw new Error("V213_ACTIVATION_RUN_ID_COLLISION");
    }
  } else {
    const claim: RunClaim = {
      schema_version: 1,
      transaction_id: transactionId,
      run_id: runId,
      payload_digests: Object.fromEntries(PAYLOAD_NAMES.map((name) => [name, String(digests[name])])),
      claimed_at: new Date().toISOString(),
    };
    await env.PUBLIC_CACHE.put(runClaimKey, JSON.stringify(claim));
    const confirmedText = await env.PUBLIC_CACHE.get(runClaimKey, "text");
    if (!confirmedText) throw new Error("V213_ACTIVATION_RUN_CLAIM_WRITE_FAILED");
    const confirmed = parseRunClaim(confirmedText);
    if (confirmed.transaction_id !== transactionId || !sameDigests(confirmed.payload_digests, digests)) {
      throw new Error("V213_ACTIVATION_RUN_ID_COLLISION");
    }
  }

  const prefix = `snapshot:${runId}:`;
  const objects: Array<[string, string]> = [
    ["v21:top20:latest", JSON.stringify(top20)],
    ["scores:latest", JSON.stringify(derivedScores(top20))],
    ["source_views:latest", JSON.stringify(derivedSourceViews(top20))],
    ["source_plan:latest", JSON.stringify(plan)],
    ["reports:latest", report],
    ["reports:morning:latest", report],
    ["reports:evening:latest", report],
    ["last_successful_pipeline_timestamp", String(root.public_data_as_of)],
    ["v212:top20-report:latest", JSON.stringify(v212)],
    ["v213:top20-report:latest", JSON.stringify(v213)],
    ["v213:source-federation:latest", JSON.stringify(federation)],
    ["v213:source-independence:latest", JSON.stringify(sourceAudit)],
    ["v213:activation-claim", existingClaimText ?? await env.PUBLIC_CACHE.get(runClaimKey, "text") ?? ""],
  ];
  // These payloads are not part of this sealed contract. Never rebrand a prior
  // run's options/universe as current. Missing current-run objects fail closed
  // in publicJson; old immutable objects remain available for exact rollback.
  if (idempotentReplay) {
    await verifySnapshotObjects(env, prefix, objects, true);
    return {
      status: "accepted",
      product_version: "2.1.3",
      transaction_id: transactionId,
      run_id: runId,
      previous_run_id: state.previous_run_id,
      object_count: 0,
      objects_read_back: objects.length,
      pointer_written_last: true,
      rollback_available: true,
      recovery_status: "PROMOTED_JOURNAL_RECOVERED",
      idempotent_replay: true,
      publication_mode: publicationMode,
      publication_mode_contract_id: contract.contract_id,
      publication_mode_contract_sha256: publicationModeContractHash,
    };
  }
  for (const [key, value] of objects) {
    await env.PUBLIC_CACHE.put(`${prefix}${key}`, value);
  }
  await verifySnapshotObjects(env, prefix, objects);
  await env.PUBLIC_CACHE.put("snapshot:current", JSON.stringify({
    schema_version: 1,
    run_id: runId,
    public_data_as_of: root.public_data_as_of,
    promoted_at: new Date().toISOString(),
    provider_scope: "public_only",
    owner_watchlist_inherited: false,
  }));
  const confirmedPointer = await env.PUBLIC_CACHE.get("snapshot:current", "text");
  if (currentRunId(confirmedPointer) !== runId) {
    throw new Error("V213_ACTIVATION_POINTER_WRITE_NOT_VERIFIED");
  }
  await verifySnapshotObjects(env, prefix, objects);
  return {
    status: "accepted",
    product_version: "2.1.3",
    transaction_id: transactionId,
    run_id: runId,
    previous_run_id: state.previous_run_id,
    object_count: objects.length,
    objects_read_back: objects.length,
    pointer_written_last: true,
    rollback_available: true,
    recovery_status: journalRecovered ? "PREPARED_JOURNAL_RESUMED" : "JOURNAL_DURABLE",
    idempotent_replay: false,
    publication_mode: publicationMode,
    publication_mode_contract_id: contract.contract_id,
    publication_mode_contract_sha256: publicationModeContractHash,
  };
}

export async function rollbackV213Activation(
  body: string,
  env: V21AdminEnv,
): Promise<Record<string, unknown>> {
  const control = parseControl(body);
  const key = rollbackKey(control.transaction_id);
  const stateText = await env.TENANT_PRIVATE_CACHE.get(key, "text");
  const currentText = await env.PUBLIC_CACHE.get("snapshot:current", "text");
  const observedRunId = currentRunId(currentText);
  if (!stateText) {
    if (observedRunId === control.run_id) throw new Error("V213_ACTIVATION_ROLLBACK_STATE_MISSING");
    return { status: "not_committed", transaction_id: control.transaction_id, run_id: control.run_id };
  }
  const state = parseRollbackState(stateText, control.transaction_id, control.run_id);
  if (observedRunId !== control.run_id) {
    throw new Error("V213_ACTIVATION_ROLLBACK_POINTER_MISMATCH");
  }
  if (state.previous_pointer === null) await env.PUBLIC_CACHE.delete("snapshot:current");
  else await env.PUBLIC_CACHE.put("snapshot:current", state.previous_pointer);
  const restoredText = await env.PUBLIC_CACHE.get("snapshot:current", "text");
  if (restoredText !== state.previous_pointer) {
    throw new Error("V213_ACTIVATION_ROLLBACK_NOT_VERIFIED");
  }
  await env.TENANT_PRIVATE_CACHE.delete(key);
  return {
    status: "rolled_back",
    transaction_id: control.transaction_id,
    run_id: control.run_id,
    restored_run_id: state.previous_run_id,
    exact_pointer_restored: true,
  };
}

export async function finalizeV213Activation(
  body: string,
  env: V21AdminEnv,
): Promise<Record<string, unknown>> {
  const control = parseControl(body);
  const key = rollbackKey(control.transaction_id);
  const stateText = await env.TENANT_PRIVATE_CACHE.get(key, "text");
  if (!stateText) throw new Error("V213_ACTIVATION_FINALIZE_STATE_MISSING");
  parseRollbackState(stateText, control.transaction_id, control.run_id);
  const currentText = await env.PUBLIC_CACHE.get("snapshot:current", "text");
  if (currentRunId(currentText) !== control.run_id) {
    throw new Error("V213_ACTIVATION_FINALIZE_POINTER_MISMATCH");
  }
  await env.TENANT_PRIVATE_CACHE.delete(key);
  return {
    status: "finalized",
    transaction_id: control.transaction_id,
    run_id: control.run_id,
    rollback_handle_deleted: true,
  };
}
