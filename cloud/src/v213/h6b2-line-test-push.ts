import { splitLineText } from "../core";
import { publicJson, type StorageEnv } from "../storage";
import { getOwnerPushTarget } from "../v21/owner-storage";
import { pushText, type V21LinePushEnv } from "../v21/line-push";
import { parseV21Top20 } from "../v21/top20";

export interface H6B2LineTestEnv extends StorageEnv, V21LinePushEnv {}

interface H6B2Envelope {
  schema_version: 1;
  stage: "H6B2_REAL_LINE_SEVEN_FIELD_TEST";
  source_sha: string;
  report_sha256: string;
  preview_sha256: string;
  receipt_sha256: string;
  preview_text: string;
}

const ACCEPTED_R15_SOURCE_SHA = "f1d6790de99c8af981a40e26993a12a444b214ba";
const ACCEPTED_R15_REPORT_SHA256 = "cf0ff1a5a1499a8179fb0b68169511ec71c12f548069a3ee3a711955b705c284";
const ACCEPTED_R15_PREVIEW_SHA256 = "b186136c5540cd9d0d50eb74cf2f0417ccba8b1e6ed16ad15de42e62a8b1334f";
const ACCEPTED_R15_RECEIPT_SHA256 = "ffdb272c62ce537dc6537d7a80c9dbd112b064e1b816e3bdc8851f7d044b45d7";
const HEADER = "股票｜長期投資報酬率（近2年年化）｜短期投資報酬率（近6個月）｜行業別｜獲利簡述｜公司現在訂單｜未來訂單預估";
const HEX64 = /^[0-9a-f]{64}$/;
const TICKER = /^[A-Z0-9][A-Z0-9.-]{0,14}$/;
const EXPECTED_KEYS = [
  "schema_version",
  "stage",
  "source_sha",
  "report_sha256",
  "preview_sha256",
  "receipt_sha256",
  "preview_text",
].sort();

function exactKeys(value: Record<string, unknown>): boolean {
  const keys = Object.keys(value).sort();
  return keys.length === EXPECTED_KEYS.length && keys.every((key, index) => key === EXPECTED_KEYS[index]);
}

async function sha256(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export function parseH6B2Preview(text: string): { canonical: string; tickers: string[] } {
  if (!text || text.startsWith("\uFEFF") || text.length > 4900) throw new Error("H6B2_PREVIEW_SIZE_OR_BOM_INVALID");
  const canonical = text.replace(/(?:\r?\n)+$/, "");
  if (!canonical || /\n\n|\r\r/.test(canonical)) throw new Error("H6B2_PREVIEW_LAYOUT_INVALID");
  const lines = canonical.split(/\r?\n/);
  if (lines.length !== 21 || lines[0] !== HEADER) throw new Error("H6B2_PREVIEW_HEADER_OR_ROW_COUNT_INVALID");

  const tickers: string[] = [];
  const seen = new Set<string>();
  for (let index = 1; index < lines.length; index += 1) {
    const columns = lines[index]!.split("｜");
    if (columns.length !== 7 || columns.some((value) => !value.trim())) {
      throw new Error("H6B2_PREVIEW_SEVEN_FIELD_CONTRACT_INVALID");
    }
    const ticker = columns[0]!.trim();
    if (!TICKER.test(ticker) || seen.has(ticker)) throw new Error("H6B2_PREVIEW_TICKER_INVALID");
    seen.add(ticker);
    tickers.push(ticker);
  }

  if (/Serenity|Aschenbrenner|system_operationalization_score|owner_watchlist|IBKR/i.test(canonical)) {
    throw new Error("H6B2_PREVIEW_INTERNAL_OR_PRIVATE_NARRATIVE_FORBIDDEN");
  }
  const chunks = splitLineText(canonical, 4900, 5);
  if (chunks.length !== 1 || chunks[0] !== canonical) throw new Error("H6B2_PREVIEW_MUST_BE_ONE_EXACT_LINE_MESSAGE");
  return { canonical, tickers };
}

function parseEnvelope(body: string): H6B2Envelope {
  let raw: unknown;
  try {
    raw = JSON.parse(body);
  } catch {
    throw new Error("H6B2_ENVELOPE_JSON_INVALID");
  }
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new Error("H6B2_ENVELOPE_OBJECT_REQUIRED");
  const value = raw as Record<string, unknown>;
  if (!exactKeys(value)) throw new Error("H6B2_ENVELOPE_KEYS_INVALID");
  if (
    value.schema_version !== 1 ||
    value.stage !== "H6B2_REAL_LINE_SEVEN_FIELD_TEST" ||
    value.source_sha !== ACCEPTED_R15_SOURCE_SHA ||
    value.report_sha256 !== ACCEPTED_R15_REPORT_SHA256 ||
    value.preview_sha256 !== ACCEPTED_R15_PREVIEW_SHA256 ||
    value.receipt_sha256 !== ACCEPTED_R15_RECEIPT_SHA256 ||
    typeof value.preview_text !== "string" ||
    !HEX64.test(String(value.preview_sha256))
  ) {
    throw new Error("H6B2_ACCEPTED_R15_ATTESTATION_MISMATCH");
  }
  return value as unknown as H6B2Envelope;
}

export async function sendH6B2SevenFieldTestPush(
  env: H6B2LineTestEnv,
  body: string,
): Promise<Record<string, unknown>> {
  const envelope = parseEnvelope(body);
  if ((await sha256(envelope.preview_text)) !== ACCEPTED_R15_PREVIEW_SHA256) {
    throw new Error("H6B2_PREVIEW_CONTENT_SHA_MISMATCH");
  }
  const parsedPreview = parseH6B2Preview(envelope.preview_text);

  const owner = await getOwnerPushTarget(env);
  if (!owner) return { status: "owner_not_paired" };
  const currentTop20 = parseV21Top20(await publicJson<unknown>(env, ["v21:top20:latest"]));
  if (!currentTop20) return { status: "top20_unavailable" };
  if (parsedPreview.tickers.some((ticker, index) => ticker !== currentTop20[index]?.ticker)) {
    return { status: "top20_order_mismatch" };
  }

  await pushText(env, owner.lineUserId, parsedPreview.canonical);
  return {
    status: "sent",
    stage: "H6B2_REAL_LINE_SEVEN_FIELD_TEST",
    count: 20,
    format: "v213_seven_fields",
    message_count: 1,
    source_sha: ACCEPTED_R15_SOURCE_SHA,
    preview_sha256: ACCEPTED_R15_PREVIEW_SHA256,
    public_or_tenant_payload_kv_write_performed: false,
    admin_replay_nonce_write_expected: true,
    scheduled_format_changed: false,
  };
}
