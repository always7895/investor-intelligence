/**
 * LINE access policy for the Production Worker (pure; no storage except the owner lookup wrapper).
 *
 * Mode switch V213_LINE_ACCESS_MODE. Exactly "all_friends" opens the public features and the local-model Q&A to every
 * direct-chat friend; any other value (missing, empty, wrong case, garbage) is "owner_only", the fail-closed default
 * that keeps today's behaviour byte for byte. The variable is deliberately not named LINE_ACCESS_MODE: the shared bot
 * (cloud/src/worker.ts, security.ts) already uses that name with the values disabled|allowlist.
 *
 * Owner-only for everyone, in every mode: personal holdings / portfolio / IBKR (no such path exists on LINE), scheduled
 * push and notification settings, pairing and unpairing, admin routes. Groups and rooms are rejected before any storage.
 */
import { parseQuery } from "../core";
import { manualOptionQuoteAnswer } from "../manual-options";
import { isOwnerTenant } from "../v21/owner-storage";

export type LineAccessMode = "owner_only" | "all_friends";
export type OwnerState = "owner" | "not_owner" | "lookup_failed";
export type LineAccessScope = "OWNER_ONLY" | "PER_FRIEND_OWN_DATA" | "ALL_FRIENDS";
export type LineRequestKind =
  | "follow"
  | "unpair"
  | "notification_status"
  | "pairing"
  | "delete_data"
  | "job_result"
  | "memory"
  | "general_qa"
  | "manual_option"
  | "portfolio_refusal"
  | "public_read";
export type LineAccessDecision = "allow" | "deny_silent" | "owner_only_reply";

export interface LineRequestClass {
  scope: LineAccessScope;
  kind: LineRequestKind;
}

/** Carried into processAuthorizedLineEvent. Absent = today's owner behaviour. */
export interface LineAccessContext {
  mode: LineAccessMode;
  ownerState: OwnerState;
}

export function lineAccessMode(env: { V213_LINE_ACCESS_MODE?: unknown }): LineAccessMode {
  return env.V213_LINE_ACCESS_MODE === "all_friends" ? "all_friends" : "owner_only";
}

// ----------------------------------------------------------------------- reviewed zh-TW texts

/** Same text whether or not an owner exists, so it reveals nothing about pairing. */
export const OWNER_ONLY_REPLY =
  "此功能僅限服務擁有者使用。Top 20、瓶頸榜、期權觀察、個股查詢與 AI 問答都可以直接使用，輸入「說明」查看。";

/** The mapping of the LOCAL_MODEL_OFFLINE marker (gateway 429 and real outages alike). No time promise. */
export const FRIEND_AI_BUSY_REPLY =
  "目前 AI 問答暫時無法處理，這則問題沒有被處理，請稍後再試。Top 20、瓶頸榜、期權等公開查詢不受影響。";

/** Gate unbound / throwing / full: honest, no model call, nothing stored. */
export const FRIEND_SERVICE_BUSY_REPLY = "服務目前忙碌或暫時無法處理，這則訊息沒有被處理，請稍後再試。";

/** The friend already has one question in flight and one waiting. */
export const FRIEND_AI_OWN_BUSY_REPLY = "你前一個 AI 問題還在處理中，請等它回覆後再問。";

export const FRIEND_RATE_REPLY = "請求過於頻繁，請稍後再試。";
export const FRIEND_KV_ACTION_LIMIT_REPLY =
  "資料管理指令（刪除資料、記憶設定）每日次數有限，今日已達上限，請明天（台北時間 00:00 後）再試。";
export const FRIEND_AI_MINUTE_LIMIT_REPLY = "AI 問答每分鐘最多 3 次，請稍後再試。";
export const FRIEND_AI_DAY_LIMIT_REPLY = "今日 AI 問答次數已達上限（每日 30 次），請明天（台北時間 00:00 後）再試。";

export const FRIEND_EDUCATION_SENTENCE =
  "本服務只提供公開資料的教育性研究與觀察，不提供個人化投資建議，也不接受或處理你的持倉、帳戶或券商資料。";

export const FRIEND_PORTFOLIO_REFUSAL =
  "本服務只處理公開資料，不接受也不提供個人持倉、帳戶或券商資料。請改問公開的產業、個股或期權觀察。";

export function friendDeleteReply(deleted: number): string {
  return `你的 tenant-scoped 對話／工作資料已刪除（${deleted} 個項目）。`;
}

export function friendJobReply(referenceId: string): string {
  return `問題已收到，參考編號 ${referenceId}。請稍後在這個聊天室輸入「查看結果 ${referenceId}」，1 小時內有效；推播僅限擁有者，只有你自己的聊天室能查看這個結果。`;
}

// ----------------------------------------------------------------------- classification

const UNPAIR = /^(?:取消配對|取消配对|unpair)$/i;
const NOTIFICATION_STATUS = /^(?:通知狀態|通知状态|notification status)$/i;
const PAIRING = /^(?:配對|配对|pair)\s+/i;

/**
 * Ordered table. Unknown text never maps to an OWNER_ONLY handler: only the three explicit patterns above do.
 * `text` is null for events without text (follow, unfollow, non-text messages).
 */
export function classifyLineRequest(eventType: string, text: string | null): LineRequestClass {
  if (eventType === "follow") return { scope: "ALL_FRIENDS", kind: "follow" };
  const normalized = (text ?? "").normalize("NFKC").trim();
  if (UNPAIR.test(normalized)) return { scope: "OWNER_ONLY", kind: "unpair" };
  if (NOTIFICATION_STATUS.test(normalized)) return { scope: "OWNER_ONLY", kind: "notification_status" };
  if (PAIRING.test(normalized)) return { scope: "OWNER_ONLY", kind: "pairing" };
  if (text === null) return { scope: "ALL_FRIENDS", kind: "public_read" };
  if (manualOptionQuoteAnswer(text) !== null) return { scope: "ALL_FRIENDS", kind: "manual_option" };
  const { intent } = parseQuery(text);
  if (intent === "delete_data") return { scope: "PER_FRIEND_OWN_DATA", kind: "delete_data" };
  if (intent === "job_result") return { scope: "PER_FRIEND_OWN_DATA", kind: "job_result" };
  if (intent === "memory_status" || intent === "memory_enable" || intent === "memory_disable" || intent === "memory_clear") {
    return { scope: "PER_FRIEND_OWN_DATA", kind: "memory" };
  }
  if (intent === "portfolio") return { scope: "ALL_FRIENDS", kind: "portfolio_refusal" };
  if (intent === "general_qa") return { scope: "PER_FRIEND_OWN_DATA", kind: "general_qa" };
  return { scope: "ALL_FRIENDS", kind: "public_read" };
}

/** Chat types other than a direct user chat are rejected first, in every mode. */
export function decideLineAccess(
  mode: LineAccessMode,
  ownerState: OwnerState,
  sourceType: string,
  cls: LineRequestClass,
): LineAccessDecision {
  if (sourceType !== "user") return "deny_silent";
  if (ownerState === "owner") return "allow";
  if (mode !== "all_friends") {
    // Today's gate: only the owner, plus the pairing bypass so a first owner can enrol.
    return cls.kind === "pairing" && ownerState === "not_owner" ? "allow" : "deny_silent";
  }
  if (cls.scope !== "OWNER_ONLY") return "allow";
  if (cls.kind === "pairing") return ownerState === "not_owner" ? "allow" : "deny_silent";
  return "owner_only_reply";
}

/**
 * A thrown owner lookup is lookup_failed: never the owner, never a reason to remove a pairing, delete or write anything.
 * getOwnerPushTarget / isOwnerTenant / removeOwnerPairing keep their contracts.
 */
export async function resolveOwnerState(env: Parameters<typeof isOwnerTenant>[0], tenantId: string): Promise<OwnerState> {
  try {
    return (await isOwnerTenant(env, tenantId)) ? "owner" : "not_owner";
  } catch {
    return "lookup_failed";
  }
}

// ----------------------------------------------------------------------- friend pre-model checks

// Mirrors the first-person financial disclosure screen inside generalAnswer (cloud/src/qa.ts, certified and not
// patched). Running it here means a friend's portfolio question never occupies a model slot.
const CHINESE_DISCLOSURE =
  /(?:我(?:目前)?(?:持有|持倉|持仓|買了|买了|賣了|卖了)|我的(?:持倉|持仓|部位|投資組合|投资组合|券商|帳戶|账户|成本|均價|均价|股數|股数|損益|损益|保證金|保证金|購買力|购买力))/i;
const ENGLISH_DISCLOSURE =
  /(?:\bmy\s+(?:portfolio|positions?|broker(?:age)?\s+account|account|cost\s+basis|average\s+price|margin|buying\s+power|p&l)\b|\bi\s+(?:own|hold|bought|sold)\b|\bi\s+have\s+\d+(?:\.\d+)?\s+(?:shares?|contracts?)\b)/i;

export function friendPortfolioDisclosure(normalizedQuestion: string): boolean {
  const text = normalizedQuestion.normalize("NFKC");
  return CHINESE_DISCLOSURE.test(text) || ENGLISH_DISCLOSURE.test(text);
}

/** Returns the refusal text, or null when the question may go to the model lane. */
export function friendPreModelRefusal(normalizedQuestion: string, maxChars: unknown): string | null {
  const configured = Number(maxChars ?? "3000");
  const limit = Number.isFinite(configured) ? Math.max(200, configured) : 3000;
  if (normalizedQuestion.length > limit) return `問題過長（上限 ${limit} 字）。`;
  if (friendPortfolioDisclosure(normalizedQuestion)) return FRIEND_PORTFOLIO_REFUSAL;
  return null;
}
