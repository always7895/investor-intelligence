import { describe, expect, it } from "vitest";
import { assertLineMessages, type LineOutboundMessage } from "../src/line-messages";
import { packCarousels } from "../src/v213/line-theme";

const bytes = (value: unknown) => new TextEncoder().encode(JSON.stringify(value)).length;
const bubble = (text: string) => ({ type: "bubble", body: { type: "box", layout: "vertical", contents: [{ type: "text", text, wrap: true }] } });
const sizedBubble = (size: number, prefix: string) => {
  const seed = bubble(prefix);
  return bubble(prefix + "x".repeat(size - bytes(seed)));
};
const alt = (index: number, total: number) => `Page ${index + 1}/${total}`;
const flex = (contents: Record<string, unknown>): LineOutboundMessage[] => [{ type: "flex", altText: "Budget boundary", contents }];

describe("LINE serialized UTF-8 budget boundaries", () => {
  it.each(["漢字", "😀", 'quote" slash\\ newline\n', "\ud800"])("preserves carousel membership at exactly 46KB and one byte over: %j", prefix => {
    const first = sizedBubble(25_000, prefix);
    const secondSize = 46_000 - bytes({ type: "carousel", contents: [first, bubble("")] }) + bytes(bubble(""));
    const second = sizedBubble(secondSize, prefix);
    const exact = packCarousels([first, second], alt);
    expect(exact).toEqual([{ type: "flex", altText: "Page 1/1", contents: { type: "carousel", contents: [first, second] } }]);
    expect(bytes(exact[0]!.type === "flex" ? exact[0]!.contents : null)).toBe(46_000);
    const over = { ...second, body: { ...second.body, contents: [{ ...second.body.contents[0]!, text: second.body.contents[0]!.text + "x" }] } };
    expect(packCarousels([first, over], alt)).toEqual([
      { type: "flex", altText: "Page 1/2", contents: { type: "carousel", contents: [first] } },
      { type: "flex", altText: "Page 2/2", contents: { type: "carousel", contents: [over] } },
    ]);
  });

  it("keeps carousel-size failure ahead of an invalid or oversized bubble", () => {
    expect(() => assertLineMessages(flex({ type: "carousel", contents: [sizedBubble(48_001, "漢")] }))).toThrow("LINE_FLEX_CAROUSEL_TOO_LARGE");
    expect(() => assertLineMessages(flex({ type: "carousel", contents: [{ ...sizedBubble(48_001, "😀"), type: "box" }] }))).toThrow("LINE_FLEX_CAROUSEL_TOO_LARGE");
    expect(() => assertLineMessages(flex({ type: "carousel", contents: [sizedBubble(28_001, "漢")] }))).toThrow("LINE_FLEX_BUBBLE_INVALID");
  });

  it("includes additional carousel properties in the 48KB limit", () => {
    const contents = { type: "carousel", contents: [bubble("Small")], extra: "x".repeat(48_000) };
    expect(() => assertLineMessages(flex(contents))).toThrow("LINE_FLEX_CAROUSEL_TOO_LARGE");
  });

  it("retains custom toJSON array-index semantics", () => {
    const custom = { type: "bubble", toJSON(key: string) { return bubble(`Array index ${key}`); } };
    const messages = packCarousels([bubble("First"), custom], alt);
    expect(JSON.parse(JSON.stringify(messages))).toEqual([
      { type: "flex", altText: "Page 1/1", contents: { type: "carousel", contents: [bubble("First"), bubble("Array index 1")] } },
    ]);
  });

  it("re-measures mutable input rather than retaining stale byte counts", () => {
    const value = bubble("Small");
    const first = packCarousels([value], alt);
    expect(first[0]!.type).toBe("flex");
    value.body.contents[0]!.text = "x".repeat(28_001);
    expect(() => packCarousels([value], alt)).toThrow("LINE_FLEX_BUBBLE_INVALID");
    expect(() => assertLineMessages(first)).toThrow("LINE_FLEX_BUBBLE_INVALID");
  });
});
