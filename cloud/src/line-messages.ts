/** Bounded outbound messages; never log credentials or recipient identifiers. */
import type { LineEnv } from "./line";
import { localizeLineMessages } from "./v213/status-labels";
export type LineOutboundMessage =
  | { type: "text"; text: string }
  | { type: "flex"; altText: string; contents: Record<string, unknown> };

export async function replyMessages(env: LineEnv, replyToken: string, messages: readonly LineOutboundMessage[]): Promise<void> {
  const localized = localizeLineMessages(messages);
  assertLineMessages(localized);
  const response = await fetch("https://api.line.me/v2/bot/message/reply", {
    method: "POST",
    headers: { "content-type": "application/json", authorization: `Bearer ${env.LINE_CHANNEL_ACCESS_TOKEN}` },
    body: JSON.stringify({ replyToken, messages: localized }),
  });
  if (!response.ok) {
    const requestId = response.headers.get("x-line-request-id") ?? "unknown";
    throw new Error(`LINE_REPLY_${response.status};request_id=${requestId}`);
  }
}

const bytes = (value: unknown): number => new TextEncoder().encode(JSON.stringify(value)).length;

/** Exact ASCII framing; bubble JSON bytes plus inter-bubble commas complete a plain carousel. */
export const LINE_CAROUSEL_FRAME_BYTES = '{"type":"carousel","contents":[]}'.length;

/** Conservative structural proof for additive measurement; unusual objects use the original path. */
export function plainBubbleArray(value: unknown): value is Record<string, unknown>[] {
  try {
    if (!Array.isArray(value) || Object.getPrototypeOf(value) !== Array.prototype
      || Object.getOwnPropertyDescriptor(Array.prototype, "toJSON")
      || Object.getOwnPropertyDescriptor(Object.prototype, "toJSON")) return false;
    const keys = Reflect.ownKeys(value);
    if (keys.length !== value.length + 1 || keys[value.length] !== "length") return false;
    for (let i = 0; i < value.length; i++) {
      if (keys[i] !== String(i)) return false;
      const entry = Object.getOwnPropertyDescriptor(value, String(i));
      if (!entry || !entry.enumerable || !("value" in entry)) return false;
      const bubble = entry.value;
      if (!bubble || typeof bubble !== "object") return false;
      const proto = Object.getPrototypeOf(bubble);
      if ((proto !== Object.prototype && proto !== null) || Object.getOwnPropertyDescriptor(bubble, "toJSON")) return false;
      const type = Object.getOwnPropertyDescriptor(bubble, "type");
      if (!type || !type.enumerable || !("value" in type)) return false;
    }
    return true;
  } catch {
    return false;
  }
}

function plainCarousel(container: Record<string, unknown>): boolean {
  try {
    const proto = Object.getPrototypeOf(container);
    if ((proto !== Object.prototype && proto !== null) || Object.getOwnPropertyDescriptor(Object.prototype, "toJSON")) return false;
    const keys = Reflect.ownKeys(container);
    if (keys.length !== 2 || !((keys[0] === "type" && keys[1] === "contents")
      || (keys[0] === "contents" && keys[1] === "type"))) return false;
    const type = Object.getOwnPropertyDescriptor(container, "type");
    const contents = Object.getOwnPropertyDescriptor(container, "contents");
    return !!type && type.enumerable === true && "value" in type && type.value === "carousel"
      && !!contents && contents.enumerable === true && "value" in contents && plainBubbleArray(contents.value);
  } catch {
    return false;
  }
}

export function assertLineMessages(messages: readonly LineOutboundMessage[]): void {
  if (!Array.isArray(messages) || messages.length < 1 || messages.length > 5) throw new Error("LINE_MESSAGE_COUNT_INVALID");
  for (const message of messages) {
    if (message.type === "text") {
      if (!message.text || message.text.length > 4900) throw new Error("LINE_TEXT_SIZE_INVALID");
      continue;
    }
    if (message.type !== "flex" || !message.altText || message.altText.length > 400) throw new Error("LINE_FLEX_ALT_INVALID");
    const container = message.contents;
    if (container.type !== "carousel" || !Array.isArray(container.contents) || container.contents.length < 1 || container.contents.length > 5) {
      throw new Error("LINE_FLEX_CAROUSEL_INVALID");
    }
    // This equivalence assumes deterministic serialization; stateful nested getters or toJSON
    // have no stable bytes even on the original path, which serializes again when sending.
    if (plainCarousel(container)) {
      let total = LINE_CAROUSEL_FRAME_BYTES + container.contents.length - 1;
      let validBubbles = true;
      for (let i = 0; i < container.contents.length; i++) {
        const bubble = container.contents[i];
        const count = bytes(bubble);
        total += count;
        if (bubble.type !== "bubble" || count > 28000) validBubbles = false;
      }
      // Preserve carousel-before-bubble error precedence and both original safety margins.
      if (total > 48000) throw new Error("LINE_FLEX_CAROUSEL_TOO_LARGE");
      if (!validBubbles) throw new Error("LINE_FLEX_BUBBLE_INVALID");
    } else {
      if (bytes(container) > 48000) throw new Error("LINE_FLEX_CAROUSEL_TOO_LARGE");
      for (const bubble of container.contents) {
        if (!bubble || bubble.type !== "bubble" || bytes(bubble) > 28000) throw new Error("LINE_FLEX_BUBBLE_INVALID");
      }
    }
  }
}
