import { splitLineText } from "./core";
import {
  hashOpaqueId,
  verifyLineSignature,
  type LineSourceIdentity,
  type SecurityEnv,
} from "./security";

export interface LineEnv extends SecurityEnv {
  EPHEMERAL_SECURITY_CACHE: KVNamespace;
  LINE_CHANNEL_SECRET: string;
  LINE_CHANNEL_ACCESS_TOKEN: string;
  MAX_REQUESTS_PER_MINUTE?: string;
  MAX_WEBHOOK_AGE_SECONDS?: string;
}

export interface LineTextMessage {
  id: string;
  type: "text";
  text: string;
}

export interface LineEvent {
  type: string;
  webhookEventId?: string;
  replyToken?: string;
  timestamp?: number;
  source?: LineSourceIdentity;
  message?: LineTextMessage | Record<string, unknown>;
  postback?: { data?: string };
  deliveryContext?: { isRedelivery?: boolean };
}

const REPLY_URL = "https://api.line.me/v2/bot/message/reply";
const EVENT_DONE_TTL_SECONDS = 24 * 60 * 60;
const EVENT_PROCESSING_TTL_SECONDS = 120;
const MAX_LINE_TEXT = 4900;
const MAX_LINE_MESSAGES = 5;

export { verifyLineSignature };

export function eventIsFresh(event: LineEvent, env: LineEnv): boolean {
  if (!event.timestamp) return true;
  const configured = Number(env.MAX_WEBHOOK_AGE_SECONDS ?? "600");
  const maxAge = Number.isFinite(configured) ? Math.max(60, configured) : 600;
  const ageSeconds = Math.max(0, Date.now() - event.timestamp) / 1000;
  if (event.deliveryContext?.isRedelivery) return ageSeconds <= Math.max(maxAge, 86400);
  return ageSeconds <= maxAge;
}

async function eventKey(eventId: string): Promise<string> {
  // webhookEventId is an external identifier and must never appear raw in KV.
  return `line:event:${await hashOpaqueId(eventId)}`;
}

export async function claimEvent(env: LineEnv, eventId: string | undefined): Promise<boolean> {
  if (!eventId) return true;
  const key = await eventKey(eventId);
  if (await env.EPHEMERAL_SECURITY_CACHE.get(key)) return false;
  // KV is eventually consistent, so this is a retry-safe best-effort gate rather
  // than a strict distributed lock. Phase 8 may move exact-once claims to D1/DO.
  await env.EPHEMERAL_SECURITY_CACHE.put(key, "processing", {
    expirationTtl: EVENT_PROCESSING_TTL_SECONDS,
  });
  return true;
}

export async function completeEvent(env: LineEnv, eventId: string | undefined): Promise<void> {
  if (!eventId) return;
  await env.EPHEMERAL_SECURITY_CACHE.put(await eventKey(eventId), "done", {
    expirationTtl: EVENT_DONE_TTL_SECONDS,
  });
}

export async function releaseEvent(env: LineEnv, eventId: string | undefined): Promise<void> {
  if (!eventId) return;
  const key = await eventKey(eventId);
  const value = await env.EPHEMERAL_SECURITY_CACHE.get(key);
  if (value === "processing") await env.EPHEMERAL_SECURITY_CACHE.delete(key);
}

export async function rateLimit(
  env: LineEnv,
  tenantId: string,
  intent: string,
): Promise<boolean> {
  const configured = Number(env.MAX_REQUESTS_PER_MINUTE ?? "12");
  const limit = Number.isFinite(configured) ? Math.max(1, configured) : 12;
  const bucket = Math.floor(Date.now() / 60000);
  const key = `rate:${tenantId}:${intent}:${bucket}`;
  const current = Number((await env.EPHEMERAL_SECURITY_CACHE.get(key)) ?? "0");
  if (Number.isFinite(current) && current >= limit) return false;
  await env.EPHEMERAL_SECURITY_CACHE.put(
    key,
    String((Number.isFinite(current) ? current : 0) + 1),
    { expirationTtl: 120 },
  );
  return true;
}

export async function replyText(env: LineEnv, replyToken: string, text: string): Promise<void> {
  const chunks = splitLineText(text, MAX_LINE_TEXT, MAX_LINE_MESSAGES);
  const response = await fetch(REPLY_URL, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      authorization: `Bearer ${env.LINE_CHANNEL_ACCESS_TOKEN}`,
    },
    body: JSON.stringify({
      replyToken,
      messages: chunks.map((chunk) => ({ type: "text", text: chunk })),
    }),
  });
  if (!response.ok) {
    const requestId = response.headers.get("x-line-request-id") ?? "unknown";
    throw new Error(`LINE_REPLY_${response.status};request_id=${requestId}`);
  }
}
