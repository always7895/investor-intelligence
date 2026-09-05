import { splitLineText } from "../core";
import { assertLineMessages, type LineOutboundMessage } from "../line-messages";

export interface V21LinePushEnv {
  LINE_CHANNEL_ACCESS_TOKEN: string;
}

const PUSH_URL = "https://api.line.me/v2/bot/message/push";
const LINE_USER_ID_RE = /^U[0-9a-f]{32}$/i;
const MAX_LINE_TEXT = 4900;
const MAX_LINE_MESSAGES = 5;

export async function pushText(
  env: V21LinePushEnv,
  lineUserId: string,
  text: string,
): Promise<void> {
  const chunks = splitLineText(text, MAX_LINE_TEXT, MAX_LINE_MESSAGES);
  await pushMessages(env, lineUserId, chunks.map(chunk => ({ type: "text", text: chunk })));
}

export async function pushMessages(env: V21LinePushEnv, lineUserId: string, messages: readonly LineOutboundMessage[]): Promise<void> {
  if (!LINE_USER_ID_RE.test(lineUserId)) throw new Error("V21_LINE_PUSH_TARGET_INVALID");
  assertLineMessages(messages);
  const response = await fetch(PUSH_URL, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      authorization: `Bearer ${env.LINE_CHANNEL_ACCESS_TOKEN}`,
    },
    body: JSON.stringify({
      to: lineUserId,
      messages,
      notificationDisabled: false,
    }),
  });
  if (!response.ok) {
    const requestId = response.headers.get("x-line-request-id") ?? "unknown";
    throw new Error(`V21_LINE_PUSH_${response.status};request_id=${requestId}`);
  }
}
