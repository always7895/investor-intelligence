import { hashOpaqueId, timingSafeEqual } from "../security";
import { type StorageEnv } from "../storage";
import { parseV21Top20, type V21Top20Record } from "./top20";

export interface V21AdminEnv extends StorageEnv {
  V21_SYNC_HMAC_SECRET?: string;
  V21_MAX_SYNC_BODY_BYTES?: string;
  V21_MAX_SYNC_AGE_SECONDS?: string;
}

interface SignedSnapshotEnvelope {
  schema_version: 1;
  run_id: string;
  generated_at: string;
  public_data_as_of: string;
  payloads: {
    top20_json: string;
    source_plan_json: string;
    report_text: string;
  };
  sha256: {
    top20_json: string;
    source_plan_json: string;
    report_text: string;
  };
}

const ENCODER = new TextEncoder();
const HEX_64_RE = /^[0-9a-f]{64}$/;
const RUN_ID_RE = /^\d{8}T\d{6}Z-[0-9a-f]{12}$/;
const FORBIDDEN_PUBLIC_KEYS = new Set([
  "account", "account_id", "portfolio", "position", "positions", "holding", "holdings",
  "cost_basis", "pnl", "line_user_id", "raw_user_id", "tenant_id", "conversation",
  "private_message", "brokerage", "ibkr", "secret", "token",
]);
const REQUIRED_REPORT_MARKERS = [
  "<!-- line-public-eligible: true -->",
  "<!-- provider-scope: public_only -->",
  "<!-- owner-watchlist-inherited: false -->",
  "<!-- scoring-version: serenity-first-v2.1.0 -->",
];

function exactKeys(value: Record<string, unknown>, expected: string[]): boolean {
  const keys = Object.keys(value).sort();
  return keys.length === expected.length && keys.every((key, index) => key === [...expected].sort()[index]);
}

function toHex(value: ArrayBuffer): string {
  return Array.from(new Uint8Array(value), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function sha256(value: string): Promise<string> {
  return toHex(await crypto.subtle.digest("SHA-256", ENCODER.encode(value)));
}

async function hmac(secret: string, value: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    ENCODER.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  return toHex(await crypto.subtle.sign("HMAC", key, ENCODER.encode(value)));
}

function rejectPrivateKeys(value: unknown, path = "$"): void {
  if (Array.isArray(value)) {
    value.forEach((entry, index) => rejectPrivateKeys(entry, `${path}[${index}]`));
    return;
  }
  if (!value || typeof value !== "object") return;
  for (const [key, child] of Object.entries(value as Record<string, unknown>)) {
    const normalized = key.toLowerCase();
    const publicCatalogTopic = path === "$.inventory.topic_counts" && normalized === "positions";
    if (FORBIDDEN_PUBLIC_KEYS.has(normalized) && !publicCatalogTopic) {
      throw new Error("V21_PUBLIC_SNAPSHOT_PRIVATE_FIELD");
    }
    rejectPrivateKeys(child, `${path}.${key}`);
  }
}

function parseJsonObject(text: string, label: string): Record<string, unknown> {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    throw new Error(`V21_${label}_JSON_INVALID`);
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`V21_${label}_OBJECT_REQUIRED`);
  }
  rejectPrivateKeys(value);
  return value as Record<string, unknown>;
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
    for (const evidence of item.evidence) {
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

export async function authenticateV21AdminRequest(
  request: Request,
  env: V21AdminEnv,
): Promise<string> {
  const keyMaterial = (env.V21_SYNC_HMAC_SECRET ?? "").trim();
  if (keyMaterial.length < 32) throw new Error("V21_SYNC_KEY_NOT_CONFIGURED");

  const timestamp = request.headers.get("x-ii-v21-timestamp") ?? "";
  const nonce = request.headers.get("x-ii-v21-nonce") ?? "";
  const signature = request.headers.get("x-ii-v21-signature") ?? "";
  if (!/^\d{10}$/.test(timestamp) || !/^[0-9a-f]{32}$/.test(nonce) || !HEX_64_RE.test(signature)) {
    throw new Error("V21_SYNC_AUTH_INVALID");
  }

  const maxAge = Math.max(60, Math.min(900, Number(env.V21_MAX_SYNC_AGE_SECONDS ?? "300") || 300));
  if (Math.abs(Math.floor(Date.now() / 1000) - Number(timestamp)) > maxAge) {
    throw new Error("V21_SYNC_REQUEST_STALE");
  }

  const body = await request.text();
  const maxBody = Math.max(4096, Math.min(5_000_000, Number(env.V21_MAX_SYNC_BODY_BYTES ?? "5000000") || 5_000_000));
  if (ENCODER.encode(body).length > maxBody) throw new Error("V21_SYNC_BODY_TOO_LARGE");

  const expected = await hmac(keyMaterial, `${timestamp}.${nonce}.${body}`);
  if (!timingSafeEqual(expected, signature)) throw new Error("V21_SYNC_SIGNATURE_INVALID");

  const replayKey = `v21:sync-nonce:${await hashOpaqueId(nonce)}`;
  if (await env.EPHEMERAL_SECURITY_CACHE.get(replayKey)) throw new Error("V21_SYNC_REPLAY");
  await env.EPHEMERAL_SECURITY_CACHE.put(replayKey, "used", { expirationTtl: maxAge * 2 });
  return body;
}

export async function ingestV21PublicSnapshot(
  body: string,
  env: V21AdminEnv,
): Promise<{ run_id: string; object_count: number }> {
  let raw: unknown;
  try {
    raw = JSON.parse(body);
  } catch {
    throw new Error("V21_SNAPSHOT_ENVELOPE_JSON_INVALID");
  }
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    throw new Error("V21_SNAPSHOT_ENVELOPE_OBJECT_REQUIRED");
  }
  const envelope = raw as Record<string, unknown>;
  if (!exactKeys(envelope, ["schema_version", "run_id", "generated_at", "public_data_as_of", "payloads", "sha256"])) {
    throw new Error("V21_SNAPSHOT_ENVELOPE_KEYS_INVALID");
  }
  if (
    envelope.schema_version !== 1 ||
    typeof envelope.run_id !== "string" ||
    !RUN_ID_RE.test(envelope.run_id) ||
    typeof envelope.generated_at !== "string" ||
    !Number.isFinite(Date.parse(envelope.generated_at)) ||
    typeof envelope.public_data_as_of !== "string" ||
    !Number.isFinite(Date.parse(envelope.public_data_as_of)) ||
    !envelope.payloads ||
    typeof envelope.payloads !== "object" ||
    Array.isArray(envelope.payloads) ||
    !envelope.sha256 ||
    typeof envelope.sha256 !== "object" ||
    Array.isArray(envelope.sha256)
  ) {
    throw new Error("V21_SNAPSHOT_ENVELOPE_INVALID");
  }

  const generatedAt = Date.parse(envelope.generated_at as string);
  const publicDataAsOf = Date.parse(envelope.public_data_as_of as string);
  const now = Date.now();
  if (generatedAt > now + 300_000 || publicDataAsOf > generatedAt + 300_000) {
    throw new Error("V21_SNAPSHOT_TIMESTAMP_INVALID");
  }

  const payloads = envelope.payloads as Record<string, unknown>;
  const digests = envelope.sha256 as Record<string, unknown>;
  const names = ["top20_json", "source_plan_json", "report_text"];
  if (!exactKeys(payloads, names) || !exactKeys(digests, names)) {
    throw new Error("V21_SNAPSHOT_PAYLOAD_KEYS_INVALID");
  }
  for (const name of names) {
    if (typeof payloads[name] !== "string" || typeof digests[name] !== "string" || !HEX_64_RE.test(String(digests[name]))) {
      throw new Error("V21_SNAPSHOT_PAYLOAD_TYPE_INVALID");
    }
    if (!timingSafeEqual(await sha256(String(payloads[name])), String(digests[name]))) {
      throw new Error(`V21_SNAPSHOT_DIGEST_MISMATCH_${name.toUpperCase()}`);
    }
  }

  let topRaw: unknown;
  try {
    topRaw = JSON.parse(String(payloads.top20_json));
  } catch {
    throw new Error("V21_TOP20_JSON_INVALID");
  }
  rejectPrivateKeys(topRaw);
  const top20 = parseV21Top20(topRaw);
  if (!top20) throw new Error("V21_TOP20_SCHEMA_INVALID");

  const plan = parseJsonObject(String(payloads.source_plan_json), "SOURCE_PLAN");
  const inventory = plan.inventory as Record<string, unknown> | undefined;
  if (
    plan.schema_version !== 1 ||
    plan.catalog_count !== 99 ||
    plan.automatic_activation !== false ||
    plan.owner_watchlist_inherited !== false ||
    plan.provider_scope !== "public_only" ||
    plan.line_public_eligible !== true ||
    !inventory ||
    inventory.runtime_enabled_count !== 0 ||
    inventory.source_count !== 99
  ) {
    throw new Error("V21_SOURCE_PLAN_INVALID");
  }

  const report = String(payloads.report_text);
  if (report.length < 200 || report.length > 200_000 || REQUIRED_REPORT_MARKERS.some((marker) => !report.includes(marker))) {
    throw new Error("V21_REPORT_ATTESTATION_INVALID");
  }

  const prefix = `snapshot:${envelope.run_id}:`;
  const objects: Array<[string, string]> = [
    ["v21:top20:latest", JSON.stringify(top20)],
    ["scores:latest", JSON.stringify(derivedScores(top20))],
    ["source_views:latest", JSON.stringify(derivedSourceViews(top20))],
    ["source_plan:latest", JSON.stringify(plan)],
    ["reports:latest", report],
    ["reports:morning:latest", report],
    ["reports:evening:latest", report],
    ["last_successful_pipeline_timestamp", envelope.public_data_as_of],
  ];
  for (const [key, value] of objects) {
    await env.PUBLIC_CACHE.put(`${prefix}${key}`, value, { expirationTtl: 259200 });
  }
  await env.PUBLIC_CACHE.put(
    "snapshot:current",
    JSON.stringify({
      schema_version: 1,
      run_id: envelope.run_id,
      public_data_as_of: envelope.public_data_as_of,
      promoted_at: new Date().toISOString(),
      provider_scope: "public_only",
      owner_watchlist_inherited: false,
    }),
  );
  return { run_id: envelope.run_id, object_count: objects.length };
}
