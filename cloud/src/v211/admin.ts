import { ingestV21PublicSnapshot, type V21AdminEnv } from "../v21/admin";
import { parseV211ResearchUniverse } from "./research";

interface V211Envelope {
  schema_version: 2;
  run_id: string;
  generated_at: string;
  public_data_as_of: string;
  payloads: Record<string, string>;
  sha256: Record<string, string>;
}

const ENCODER = new TextEncoder();
const RUN_ID_RE = /^\d{8}T\d{6}Z-[0-9a-f]{12}$/;
const HEX_64_RE = /^[0-9a-f]{64}$/;
const PAYLOAD_NAMES = [
  "top20_json",
  "research_universe_json",
  "options_json",
  "source_plan_json",
  "report_text",
];
const OPTION_KEYS = new Set([
  "schema_version", "ticker", "provider_symbol", "currency", "current_price",
  "retrieved_at", "status", "quote_source", "quote_delay_status",
  "provider_scope", "line_public_eligible", "ibkr_connected",
  "brokerage_data_included", "account_data_included", "position_data_included",
  "owner_watchlist_inherited", "periods",
]);
const FORBIDDEN_PUBLIC_KEYS = new Set([
  "account", "account_id", "portfolio", "holding", "holdings", "position", "positions",
  "cost_basis", "pnl", "line_user_id", "raw_user_id", "tenant_id", "conversation",
  "private_message", "brokerage", "ibkr", "secret", "token",
]);

function exactKeys(value: Record<string, unknown>, expected: string[]): boolean {
  const keys = Object.keys(value).sort();
  const sorted = [...expected].sort();
  return keys.length === sorted.length && keys.every((key, index) => key === sorted[index]);
}

function exactSet(value: Record<string, unknown>, expected: Set<string>): boolean {
  const keys = Object.keys(value);
  return keys.length === expected.size && keys.every((key) => expected.has(key));
}

function toHex(value: ArrayBuffer): string {
  return Array.from(new Uint8Array(value), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function sha256(value: string): Promise<string> {
  return toHex(await crypto.subtle.digest("SHA-256", ENCODER.encode(value)));
}

function rejectPrivateKeys(value: unknown): void {
  if (Array.isArray(value)) {
    value.forEach(rejectPrivateKeys);
    return;
  }
  if (!value || typeof value !== "object") return;
  for (const [key, child] of Object.entries(value as Record<string, unknown>)) {
    if (FORBIDDEN_PUBLIC_KEYS.has(key.toLowerCase())) throw new Error("V211_PUBLIC_PRIVATE_FIELD");
    rejectPrivateKeys(child);
  }
}

function parseOptions(raw: unknown, universeTickers: string[]): Array<Record<string, unknown>> {
  if (!Array.isArray(raw) || raw.length !== universeTickers.length) {
    throw new Error("V211_OPTIONS_COVERAGE_INVALID");
  }
  const result: Array<Record<string, unknown>> = [];
  for (let index = 0; index < raw.length; index += 1) {
    const value = raw[index];
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      throw new Error("V211_OPTION_RECORD_INVALID");
    }
    const item = value as Record<string, unknown>;
    if (!exactSet(item, OPTION_KEYS)) throw new Error("V211_OPTION_SCHEMA_INVALID");
    const ticker = String(item.ticker ?? "").toUpperCase();
    if (ticker !== universeTickers[index]) throw new Error("V211_OPTION_ORDER_INVALID");
    if (
      item.schema_version !== 1 ||
      item.quote_source !== "yfinance" ||
      item.provider_scope !== "public_only" ||
      item.line_public_eligible !== true ||
      item.ibkr_connected !== false ||
      item.brokerage_data_included !== false ||
      item.account_data_included !== false ||
      item.position_data_included !== false ||
      item.owner_watchlist_inherited !== false ||
      typeof item.status !== "string" ||
      !item.periods || typeof item.periods !== "object" || Array.isArray(item.periods) ||
      !Number.isFinite(Date.parse(String(item.retrieved_at ?? "")))
    ) {
      throw new Error("V211_OPTION_BOUNDARY_INVALID");
    }
    rejectPrivateKeys(item);
    result.push({ ...item, ticker });
  }
  return result;
}

export async function ingestV211PublicSnapshot(
  body: string,
  env: V21AdminEnv,
): Promise<{ run_id: string; object_count: number; research_universe_count: number; options_count: number }> {
  let raw: unknown;
  try {
    raw = JSON.parse(body);
  } catch {
    throw new Error("V211_SNAPSHOT_JSON_INVALID");
  }
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new Error("V211_SNAPSHOT_OBJECT_REQUIRED");
  const envelope = raw as Record<string, unknown>;
  if (!exactKeys(envelope, ["schema_version", "run_id", "generated_at", "public_data_as_of", "payloads", "sha256"])) {
    throw new Error("V211_SNAPSHOT_KEYS_INVALID");
  }
  if (
    envelope.schema_version !== 2 ||
    typeof envelope.run_id !== "string" || !RUN_ID_RE.test(envelope.run_id) ||
    typeof envelope.generated_at !== "string" || !Number.isFinite(Date.parse(envelope.generated_at)) ||
    typeof envelope.public_data_as_of !== "string" || !Number.isFinite(Date.parse(envelope.public_data_as_of)) ||
    !envelope.payloads || typeof envelope.payloads !== "object" || Array.isArray(envelope.payloads) ||
    !envelope.sha256 || typeof envelope.sha256 !== "object" || Array.isArray(envelope.sha256)
  ) throw new Error("V211_SNAPSHOT_ENVELOPE_INVALID");

  const payloads = envelope.payloads as Record<string, unknown>;
  const digests = envelope.sha256 as Record<string, unknown>;
  if (!exactKeys(payloads, PAYLOAD_NAMES) || !exactKeys(digests, PAYLOAD_NAMES)) {
    throw new Error("V211_SNAPSHOT_PAYLOAD_KEYS_INVALID");
  }
  for (const name of PAYLOAD_NAMES) {
    if (typeof payloads[name] !== "string" || typeof digests[name] !== "string" || !HEX_64_RE.test(String(digests[name]))) {
      throw new Error("V211_SNAPSHOT_PAYLOAD_TYPE_INVALID");
    }
    if ((await sha256(String(payloads[name]))) !== String(digests[name])) {
      throw new Error(`V211_SNAPSHOT_DIGEST_MISMATCH_${name.toUpperCase()}`);
    }
  }

  let universeRaw: unknown;
  let optionsRaw: unknown;
  try {
    universeRaw = JSON.parse(String(payloads.research_universe_json));
    optionsRaw = JSON.parse(String(payloads.options_json));
  } catch {
    throw new Error("V211_PUBLIC_PAYLOAD_JSON_INVALID");
  }
  rejectPrivateKeys(universeRaw);
  const universe = parseV211ResearchUniverse(universeRaw);
  if (!universe) throw new Error("V211_RESEARCH_UNIVERSE_INVALID");
  const options = parseOptions(optionsRaw, universe.map((item) => item.ticker));

  // Reuse the already accepted v2.1 validation/promotion path for the original
  // Top20/source-plan/report contract, then add the two v2.1.1 public payloads
  // under the exact same immutable run prefix.
  const legacyEnvelope = {
    schema_version: 1,
    run_id: envelope.run_id,
    generated_at: envelope.generated_at,
    public_data_as_of: envelope.public_data_as_of,
    payloads: {
      top20_json: String(payloads.top20_json),
      source_plan_json: String(payloads.source_plan_json),
      report_text: String(payloads.report_text),
    },
    sha256: {
      top20_json: String(digests.top20_json),
      source_plan_json: String(digests.source_plan_json),
      report_text: String(digests.report_text),
    },
  };
  const accepted = await ingestV21PublicSnapshot(JSON.stringify(legacyEnvelope), env);
  const prefix = `snapshot:${accepted.run_id}:`;
  await env.PUBLIC_CACHE.put(`${prefix}v211:universe:latest`, JSON.stringify(universe), { expirationTtl: 259200 });
  await env.PUBLIC_CACHE.put(`${prefix}options:latest`, JSON.stringify(options), { expirationTtl: 259200 });
  return {
    run_id: accepted.run_id,
    object_count: accepted.object_count + 2,
    research_universe_count: universe.length,
    options_count: options.length,
  };
}
