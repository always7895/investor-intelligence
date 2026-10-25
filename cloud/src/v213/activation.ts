import type { V21AdminEnv } from "../v21/admin";
import { parseV21Top20, type V21Evidence, type V21Top20Record } from "../v21/top20";
import { parseV212Top20Report } from "../v212/top20-report";
import { parseV213Top20Report } from "./top20-report";

const ENCODER = new TextEncoder();
const RUN_ID_RE = /^\d{8}T\d{6}Z-[0-9a-f]{12}$/;
const TRANSACTION_ID_RE = /^[0-9a-f]{32}$/;
const HEX_64_RE = /^[0-9a-f]{64}$/;
const SCORING_VERSION = "system-operationalization-v2.1.3-diversified";
const MARKET_DEGRADATION = "INSUFFICIENT_NON_YAHOO_MARKET_COVERAGE";
const MARKET_MISSING = "NON_YAHOO_MARKET_CORROBORATION";
const PAYLOAD_NAMES = [
  "top20_json",
  "source_plan_json",
  "report_text",
  "v212_top20_report_json",
  "v213_top20_report_json",
  "source_federation_json",
  "source_independence_json",
] as const;
const REQUIRED_REPORT_MARKERS = [
  "<!-- line-public-eligible: true -->",
  "<!-- provider-scope: public_only -->",
  "<!-- owner-watchlist-inherited: false -->",
  `<!-- scoring-version: ${SCORING_VERSION} -->`,
  "<!-- official-serenity-formula-claimed: false -->",
];
const FORBIDDEN_PUBLIC_KEYS = new Set([
  "account", "account_id", "portfolio", "position", "positions", "holding", "holdings",
  "cost_basis", "pnl", "line_user_id", "raw_user_id", "tenant_id", "conversation",
  "private_message", "brokerage", "ibkr", "secret", "token",
]);

interface ActivationBundle {
  schema_version: 4;
  product_version: "2.1.3";
  transaction_id: string;
  run_id: string;
  generated_at: string;
  public_data_as_of: string;
  payloads: Record<(typeof PAYLOAD_NAMES)[number], string>;
  sha256: Record<(typeof PAYLOAD_NAMES)[number], string>;
}

interface RollbackState {
  schema_version: 1;
  transaction_id: string;
  run_id: string;
  previous_pointer: string | null;
  previous_run_id: string | null;
  created_at: string;
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

function rejectPrivateKeys(value: unknown, path = "$"): void {
  if (Array.isArray(value)) {
    value.forEach((entry, index) => rejectPrivateKeys(entry, `${path}[${index}]`));
    return;
  }
  if (!value || typeof value !== "object") return;
  for (const [key, child] of Object.entries(value as Record<string, unknown>)) {
    const normalized = key.toLowerCase();
    const catalogTopic = path === "$.inventory.topic_counts" && normalized === "positions";
    if (FORBIDDEN_PUBLIC_KEYS.has(normalized) && !catalogTopic) {
      throw new Error("V213_ACTIVATION_PRIVATE_FIELD");
    }
    rejectPrivateKeys(child, `${path}.${key}`);
  }
}

function parseJson(text: string, code: string): unknown {
  try {
    const value = JSON.parse(text) as unknown;
    rejectPrivateKeys(value);
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

function validateSourcePlan(raw: unknown): Record<string, unknown> {
  const plan = object(raw, "V213_ACTIVATION_SOURCE_PLAN_INVALID");
  const inventory = object(plan.inventory, "V213_ACTIVATION_SOURCE_PLAN_INVALID");
  const federation = object(plan.live_source_federation, "V213_ACTIVATION_SOURCE_PLAN_INVALID");
  const scoring = object(plan.scoring_methodology, "V213_ACTIVATION_SOURCE_PLAN_INVALID");
  if (
    plan.schema_version !== 1 || plan.catalog_count !== 101 ||
    plan.automatic_activation !== false || plan.owner_watchlist_inherited !== false ||
    plan.provider_scope !== "public_only" || plan.line_public_eligible !== true ||
    inventory.source_count !== 101 || inventory.runtime_enabled_count !== 0 ||
    !Array.isArray(federation.successful_families) || federation.successful_families.length < 5 ||
    !Array.isArray(federation.official_successful_families) || federation.official_successful_families.length < 4 ||
    !finite(federation.ticker_coverage_ratio) || federation.ticker_coverage_ratio < 0.8 ||
    federation.unresolved_material_conflict_count !== 0 ||
    federation.yahoo_authoritative !== false ||
    federation.catalog_source_count_is_not_live_use !== true ||
    scoring.scoring_version !== SCORING_VERSION ||
    scoring.official_serenity_formula_claimed !== false
  ) throw new Error("V213_ACTIVATION_SOURCE_PLAN_INVALID");
  return plan;
}

function validateFederation(raw: unknown, order: string[]): Record<string, unknown> {
  const doc = object(raw, "V213_ACTIVATION_FEDERATION_INVALID");
  const gates = object(doc.gates, "V213_ACTIVATION_FEDERATION_INVALID");
  const successful = array(gates.successful_families, "V213_ACTIVATION_FEDERATION_INVALID").map(String);
  const official = array(gates.official_successful_families, "V213_ACTIVATION_FEDERATION_INVALID").map(String);
  const required = ["us_sec", "nasdaq", "world_bank", "us_bls", "ecb"];
  if (
    doc.schema_version !== 1 || doc.product_version !== "2.1.3" ||
    parsedTime(doc.generated_at) === null || gates.pass !== true ||
    successful.length < 5 || official.length < 4 || required.some((family) => !successful.includes(family)) ||
    !finite(gates.ticker_coverage_ratio) || gates.ticker_coverage_ratio < 0.8 ||
    gates.unresolved_material_conflict_count !== 0 || gates.concentration_pass !== true ||
    gates.yahoo_authoritative !== false || gates.catalog_source_count_is_not_live_use !== true
  ) throw new Error("V213_ACTIVATION_FEDERATION_INVALID");
  sameOrder(tickerOrder(array(doc.ticker_sources, "V213_ACTIVATION_FEDERATION_ORDER_INVALID"), "V213_ACTIVATION_FEDERATION_ORDER_INVALID"), order, "V213_ACTIVATION_FEDERATION_ORDER_INVALID");
  return doc;
}

function validateSourceAudit(raw: unknown, order: string[], top20: V21Top20Record[]): Record<string, unknown> {
  const doc = object(raw, "V213_ACTIVATION_SOURCE_AUDIT_INVALID");
  const portfolio = object(doc.portfolio, "V213_ACTIVATION_SOURCE_AUDIT_INVALID");
  const violations = array(doc.violations, "V213_ACTIVATION_SOURCE_AUDIT_INVALID");
  const blockers = array(doc.blocking_violations, "V213_ACTIVATION_SOURCE_AUDIT_INVALID");
  const degradations = array(doc.degradations, "V213_ACTIVATION_SOURCE_AUDIT_INVALID").map(String);
  const records = array(doc.records, "V213_ACTIVATION_SOURCE_AUDIT_INVALID");
  if (
    !finite(doc.schema_version) || doc.schema_version < 3 || doc.product_version !== "2.1.3" ||
    doc.status !== "PASS" || parsedTime(doc.generated_at) === null ||
    violations.length !== 0 || blockers.length !== 0 || records.length !== 20 ||
    !finite(portfolio.claim_primary_coverage_ratio) || portfolio.claim_primary_coverage_ratio < 0.75 ||
    !finite(portfolio.claim_source_families) || portfolio.claim_source_families < 2 ||
    !finite(portfolio.claim_source_domains) || portfolio.claim_source_domains < 2 ||
    !finite(portfolio.maximum_single_family_share) || portfolio.maximum_single_family_share > 0.70 ||
    portfolio.market_conflict_ticker_count !== 0
  ) throw new Error("V213_ACTIVATION_SOURCE_AUDIT_INVALID");
  sameOrder(tickerOrder(records, "V213_ACTIVATION_SOURCE_AUDIT_ORDER_INVALID"), order, "V213_ACTIVATION_SOURCE_AUDIT_ORDER_INVALID");

  const coverage = Number(portfolio.non_yahoo_market_coverage_ratio ?? 0);
  const target = Number(portfolio.non_yahoo_market_coverage_target_ratio ?? 0.75);
  const degraded = coverage < target;
  if (degraded && (
    portfolio.market_corroboration_status !== "DEGRADED" ||
    portfolio.market_corroboration_global_blocker !== false ||
    !degradations.includes(MARKET_DEGRADATION)
  )) throw new Error("V213_ACTIVATION_MARKET_DEGRADATION_INVALID");

  records.forEach((rawRecord, index) => {
    const record = object(rawRecord, "V213_ACTIVATION_SOURCE_AUDIT_RECORD_INVALID");
    const market = object(record.market_corroboration, "V213_ACTIVATION_SOURCE_AUDIT_RECORD_INVALID");
    const logic = object(record.public_logic_state, "V213_ACTIVATION_SOURCE_AUDIT_RECORD_INVALID");
    const missing = array(record.missing_or_review, "V213_ACTIVATION_SOURCE_AUDIT_RECORD_INVALID").map(String);
    const providerCount = Number(market.independent_provider_count ?? 0);
    if (providerCount < 1) {
      if (
        record.eligible_for_high_confidence_model_inference !== false ||
        logic.model_inference_confidence !== "LIMITED" ||
        !missing.includes(MARKET_MISSING) ||
        Number(top20[index]?.serenity_factors.valuation_expectations ?? 99) > 3.75
      ) throw new Error("V213_ACTIVATION_UNCORROBORATED_CONFIDENCE_INVALID");
    }
  });
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

function parseControl(body: string): { transaction_id: string; run_id: string } {
  let raw: unknown;
  try { raw = JSON.parse(body) as unknown; } catch { throw new Error("V213_ACTIVATION_CONTROL_JSON_INVALID"); }
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

export async function ingestV213ActivationBundle(
  body: string,
  env: V21AdminEnv,
): Promise<Record<string, unknown>> {
  let raw: unknown;
  try { raw = JSON.parse(body) as unknown; } catch { throw new Error("V213_ACTIVATION_BUNDLE_JSON_INVALID"); }
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
  const federation = validateFederation(parseJson(String(payloads.source_federation_json), "V213_ACTIVATION_FEDERATION_JSON_INVALID"), order);
  const sourceAudit = validateSourceAudit(parseJson(String(payloads.source_independence_json), "V213_ACTIVATION_SOURCE_AUDIT_JSON_INVALID"), order, top20);

  const previousPointer = await env.PUBLIC_CACHE.get("snapshot:current", "text");
  let previousRunId: string | null = null;
  if (previousPointer) {
    try {
      const parsed = JSON.parse(previousPointer) as { run_id?: unknown; runId?: unknown };
      previousRunId = String(parsed.run_id ?? parsed.runId ?? "") || null;
    } catch {
      previousRunId = previousPointer.trim() || null;
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
  ];
  // Unsealed options/universe from an older run must not inherit this run's
  // freshness. Keep old immutable objects only for exact pointer rollback.
  for (const [key, value] of objects) {
    await env.PUBLIC_CACHE.put(`${prefix}${key}`, value, { expirationTtl: 259200 });
  }
  const state: RollbackState = {
    schema_version: 1,
    transaction_id: transactionId,
    run_id: runId,
    previous_pointer: previousPointer,
    previous_run_id: previousRunId,
    created_at: new Date().toISOString(),
  };
  await env.EPHEMERAL_SECURITY_CACHE.put(rollbackKey(transactionId), JSON.stringify(state), { expirationTtl: 1800 });
  await env.PUBLIC_CACHE.put("snapshot:current", JSON.stringify({
    schema_version: 1,
    run_id: runId,
    public_data_as_of: root.public_data_as_of,
    promoted_at: new Date().toISOString(),
    provider_scope: "public_only",
    owner_watchlist_inherited: false,
  }));
  return {
    status: "accepted",
    product_version: "2.1.3",
    transaction_id: transactionId,
    run_id: runId,
    previous_run_id: previousRunId,
    object_count: objects.length,
    pointer_written_last: true,
    rollback_available: true,
  };
}

export async function rollbackV213Activation(body: string, env: V21AdminEnv): Promise<Record<string, unknown>> {
  const control = parseControl(body);
  const key = rollbackKey(control.transaction_id);
  const stateText = await env.EPHEMERAL_SECURITY_CACHE.get(key, "text");
  const currentText = await env.PUBLIC_CACHE.get("snapshot:current", "text");
  let currentRunId = "";
  if (currentText) {
    try {
      const parsed = JSON.parse(currentText) as { run_id?: unknown; runId?: unknown };
      currentRunId = String(parsed.run_id ?? parsed.runId ?? "");
    } catch { currentRunId = currentText.trim(); }
  }
  if (!stateText) {
    if (currentRunId === control.run_id) throw new Error("V213_ACTIVATION_ROLLBACK_STATE_MISSING");
    return { status: "not_committed", transaction_id: control.transaction_id, run_id: control.run_id };
  }
  const state = JSON.parse(stateText) as RollbackState;
  if (state.transaction_id !== control.transaction_id || state.run_id !== control.run_id) {
    throw new Error("V213_ACTIVATION_ROLLBACK_STATE_INVALID");
  }
  if (currentRunId !== control.run_id) {
    await env.EPHEMERAL_SECURITY_CACHE.delete(key);
    return { status: "not_current", transaction_id: control.transaction_id, run_id: control.run_id, current_run_id: currentRunId || null };
  }
  if (state.previous_pointer === null) await env.PUBLIC_CACHE.delete("snapshot:current");
  else await env.PUBLIC_CACHE.put("snapshot:current", state.previous_pointer);
  await env.EPHEMERAL_SECURITY_CACHE.delete(key);
  return {
    status: "rolled_back",
    transaction_id: control.transaction_id,
    run_id: control.run_id,
    restored_run_id: state.previous_run_id,
  };
}

export async function finalizeV213Activation(body: string, env: V21AdminEnv): Promise<Record<string, unknown>> {
  const control = parseControl(body);
  const key = rollbackKey(control.transaction_id);
  const stateText = await env.EPHEMERAL_SECURITY_CACHE.get(key, "text");
  if (!stateText) throw new Error("V213_ACTIVATION_FINALIZE_STATE_MISSING");
  const currentText = await env.PUBLIC_CACHE.get("snapshot:current", "text");
  let currentRunId = "";
  if (currentText) {
    try {
      const parsed = JSON.parse(currentText) as { run_id?: unknown; runId?: unknown };
      currentRunId = String(parsed.run_id ?? parsed.runId ?? "");
    } catch { currentRunId = currentText.trim(); }
  }
  if (currentRunId !== control.run_id) throw new Error("V213_ACTIVATION_FINALIZE_POINTER_MISMATCH");
  await env.EPHEMERAL_SECURITY_CACHE.delete(key);
  return { status: "finalized", transaction_id: control.transaction_id, run_id: control.run_id };
}
