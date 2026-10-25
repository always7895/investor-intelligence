import { splitLineText } from "../core";
import { assertLineMessages, type LineOutboundMessage } from "../line-messages";
import { LinePushGateError, localDate, parseFlatPushObject, parseFreePushPolicy, pushDigest, reservePush, validateQuota, PUSH_DEADLINE_MS, type PushSlot } from "./line-push-policy";

export interface V21LinePushEnv {
  LINE_CHANNEL_ACCESS_TOKEN: string;
  LINE_FREE_PUSH_POLICY?: string;
  V213_BROADCAST_DEDUPE?: DurableObjectNamespace;
  FREE_ONLY_MODE?: string;
  PAID_FALLBACK_ENABLED?: string;
}

const API = "https://api.line.me/v2/bot";
const LINE_USER_ID_RE = /^U[0-9a-f]{32}$/i;
const MAX_LINE_TEXT = 4900;
const MAX_LINE_MESSAGES = 5;

export async function pushText(env: V21LinePushEnv, lineUserId: string, text: string, slot?: PushSlot): Promise<void> {
  const chunks = splitLineText(text, MAX_LINE_TEXT, MAX_LINE_MESSAGES);
  await pushMessages(env, lineUserId, chunks.map(chunk => ({ type: "text", text: chunk })), slot);
}

async function boundedJson(response: Response): Promise<Record<string, unknown>> {
  if (response.status !== 200 || !/^application\/json(?:\s*;|$)/i.test(response.headers.get("content-type") ?? "") || !response.body) {
    void response.body?.cancel().catch(() => {});
    throw new LinePushGateError("LINE_PUSH_PREFLIGHT_UNAVAILABLE");
  }
  const reader = response.body.getReader(); const chunks: Uint8Array[] = []; let size = 0;
  try {
    for (;;) {
      const next = await reader.read(); if (next.done) break;
      size += next.value.byteLength;
      if (size > 4096) { void reader.cancel().catch(() => {}); throw new LinePushGateError("LINE_PUSH_PREFLIGHT_INVALID"); }
      chunks.push(next.value);
    }
  } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(size); let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  try {
    return parseFlatPushObject(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  } catch { throw new LinePushGateError("LINE_PUSH_PREFLIGHT_INVALID"); }
}

/** All push callers, including historical/manual/test helpers, use this gate.
 * Success means provider acceptance, never a verified received message.
 * Reservations are not refunded; retries and paid fallbacks are not performed. */
export async function pushMessages(env: V21LinePushEnv, lineUserId: string, messages: readonly LineOutboundMessage[], slot?: PushSlot): Promise<void> {
  if (typeof lineUserId !== "string" || !LINE_USER_ID_RE.test(lineUserId)) throw new LinePushGateError("V21_LINE_PUSH_TARGET_INVALID");
  assertLineMessages(messages);
  const policy = parseFreePushPolicy(env.LINE_FREE_PUSH_POLICY);
  if ((env.FREE_ONLY_MODE !== undefined && env.FREE_ONLY_MODE !== "true") ||
      (env.PAID_FALLBACK_ENABLED !== undefined && env.PAID_FALLBACK_ENABLED !== "false")) throw new LinePushGateError("LINE_FREE_ONLY_REQUIRED");
  const namespace = env.V213_BROADCAST_DEDUPE;
  if (!namespace) throw new LinePushGateError("LINE_PUSH_BUDGET_REQUIRED");
  const credential = env.LINE_CHANNEL_ACCESS_TOKEN;
  if (typeof credential !== "string" || credential.length > 8192 || !/^[\x21-\x7e]+$/.test(credential)) throw new LinePushGateError("LINE_PUSH_CREDENTIAL_UNAVAILABLE");
  // Capture the exact recipient/message bytes before asynchronous admission.
  const body = JSON.stringify({ to: lineUserId, messages, notificationDisabled: false });
  const controller = new AbortController(); let phase = "PREFLIGHT";
  const alive = () => { if (controller.signal.aborted) throw new LinePushGateError("LINE_PUSH_DEADLINE_EXCEEDED"); };
  let timer: ReturnType<typeof setTimeout>;
  const deadline = new Promise<never>((_resolve, reject) => {
    timer = setTimeout(() => { controller.abort(); reject(new LinePushGateError("LINE_PUSH_DEADLINE_EXCEEDED")); }, PUSH_DEADLINE_MS);
  });
  const execute = async () => {
    const headers = { authorization: `Bearer ${credential}` };
    const get = async (path: string) => {
      alive();
      return boundedJson(await fetch(`${API}${path}`, { method: "GET", headers, redirect: "manual", signal: controller.signal }));
    };
    const info = await get("/info");
    if (typeof info.userId !== "string" || !LINE_USER_ID_RE.test(info.userId) || await pushDigest(info.userId) !== policy.channel_sha256) throw new LinePushGateError("LINE_PUSH_CHANNEL_MISMATCH");
    const quota = await get("/message/quota"); const consumption = await get("/message/quota/consumption");
    const usage = validateQuota(quota, consumption, policy);
    alive(); phase = "BUDGET"; const day = localDate(Date.now());
    const retryKey = await reservePush(namespace, policy, usage, await pushDigest(body), slot, controller.signal);
    alive(); parseFreePushPolicy(JSON.stringify(policy));
    if (localDate(Date.now()) !== day) throw new LinePushGateError("LINE_PUSH_DAY_CHANGED");
    phase = "TRANSPORT";
    const response = await fetch(`${API}/message/push`, {
      method: "POST", redirect: "manual", signal: controller.signal,
      headers: { ...headers, "content-type": "application/json", "X-Line-Retry-Key": retryKey }, body,
    });
    // Never retain returned user/message identifiers, quote tokens or request IDs.
    void response.body?.cancel().catch(() => {});
    if (response.status !== 200) throw new LinePushGateError(`V21_LINE_PUSH_${response.status}`);
  };
  try {
    await Promise.race([execute(), deadline]);
  } catch (error) {
    if (error instanceof LinePushGateError) throw error;
    throw new LinePushGateError(phase === "TRANSPORT" ? "LINE_PUSH_TRANSPORT_UNCERTAIN" : `LINE_PUSH_${phase}_UNAVAILABLE`);
  } finally { clearTimeout(timer!); }
}
