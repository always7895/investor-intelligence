/** Bounded outbound messages; never log credentials or recipient identifiers. */
import type { LineEnv } from "./line";
export type LineOutboundMessage =
  | { type: "text"; text: string }
  | { type: "flex"; altText: string; contents: Record<string, unknown> };

export async function replyMessages(env: LineEnv, replyToken: string, messages: readonly LineOutboundMessage[]): Promise<void> {
  assertLineMessages(messages);
  const response = await fetch("https://api.line.me/v2/bot/message/reply", {
    method: "POST",
    headers: { "content-type": "application/json", authorization: `Bearer ${env.LINE_CHANNEL_ACCESS_TOKEN}` },
    body: JSON.stringify({ replyToken, messages }),
  });
  if (!response.ok) {
    const requestId = response.headers.get("x-line-request-id") ?? "unknown";
    throw new Error(`LINE_REPLY_${response.status};request_id=${requestId}`);
  }
}

const bytes = (value: unknown): number => new TextEncoder().encode(JSON.stringify(value)).length;

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
    // Product bounds below LINE's documented 30KB bubble / 50KB carousel.
    if (bytes(container) > 48000) throw new Error("LINE_FLEX_CAROUSEL_TOO_LARGE");
    for (const bubble of container.contents) {
      if (!bubble || bubble.type !== "bubble" || bytes(bubble) > 28000) throw new Error("LINE_FLEX_BUBBLE_INVALID");
    }
  }
}
