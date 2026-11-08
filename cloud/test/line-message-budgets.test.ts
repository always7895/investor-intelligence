import { describe, expect, it } from "vitest";
import { assertLineMessages, type LineOutboundMessage } from "../src/line-messages";
import { packCarousels, shortAltText } from "../src/v213/line-theme";

const bytes = (value: unknown) => new TextEncoder().encode(JSON.stringify(value)).length;
const bubble = (text: string) => ({ type: "bubble", body: { type: "box", layout: "vertical", contents: [{ type: "text", text, wrap: true }] } });
const sizedBubble = (size: number, prefix: string) => {
  const seed = bubble(prefix);
  return bubble(prefix + "x".repeat(size - bytes(seed)));
};
const alt = (index: number, total: number) => `Page ${index + 1}/${total}`;
const flex = (contents: Record<string, unknown>): LineOutboundMessage[] => [{ type: "flex", altText: "Budget boundary", contents }];
const acceptedContents = (contents: Record<string, unknown>) => {
  const messages = flex(contents);
  assertLineMessages(messages);
  return JSON.parse(JSON.stringify(contents));
};

describe("LINE serialized UTF-8 budget boundaries", () => {
  it.each(["漢字", "😀", 'quote" slash\\ newline\n', "\ud800"])("preserves carousel membership at exactly 46KB and one byte over: %j", prefix => {
    const first = sizedBubble(25_000, prefix);
    const secondSize = 46_000 - bytes({ type: "carousel", contents: [first, bubble("")] }) + bytes(bubble(""));
    const second = sizedBubble(secondSize, prefix);
    const exact = packCarousels([first, second], alt);
    expect(exact).toEqual([{ type: "flex", altText: shortAltText("Page 1/1"), contents: { type: "carousel", contents: [first, second] } }]);
    expect(bytes(exact[0]!.type === "flex" ? exact[0]!.contents : null)).toBe(46_000);
    const over = { ...second, body: { ...second.body, contents: [{ ...second.body.contents[0]!, text: second.body.contents[0]!.text + "x" }] } };
    expect(packCarousels([first, over], alt)).toEqual([
      { type: "flex", altText: shortAltText("Page 1/2"), contents: { type: "carousel", contents: [first] } },
      { type: "flex", altText: shortAltText("Page 2/2"), contents: { type: "carousel", contents: [over] } },
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
      { type: "flex", altText: shortAltText("Page 1/1"), contents: { type: "carousel", contents: [bubble("First"), bubble("Array index 1")] } },
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

  it("uses whole-container bytes for hidden required fields and extra keys", () => {
    const visible: any = { a: "x".repeat(48_001 - bytes({ a: "", b: 0 })), b: 0 };
    Object.defineProperties(visible, { type: { value: "carousel" }, contents: { value: [bubble("")] } });
    expect(() => assertLineMessages(flex(visible))).toThrow("LINE_FLEX_CAROUSEL_TOO_LARGE");
    const hidden: any = { a: 0, b: 0 };
    Object.defineProperties(hidden, { type: { value: "carousel" }, contents: { value: [sizedBubble(24_000, ""), sizedBubble(24_000, "")] } });
    expect(acceptedContents(hidden)).toEqual({ a: 0, b: 0 });
    const extra: any = { contents: [bubble("")], extra: "x".repeat(48_000) };
    Object.defineProperty(extra, "type", { value: "carousel" });
    expect(() => assertLineMessages(flex(extra))).toThrow("LINE_FLEX_CAROUSEL_TOO_LARGE");
  });

  it("measures indexed JSON independently of a custom iterator", () => {
    const omitted: any = [sizedBubble(24_000, ""), sizedBubble(24_000, "")];
    omitted[Symbol.iterator] = function* () {};
    expect(() => assertLineMessages(flex({ type: "carousel", contents: omitted }))).toThrow("LINE_FLEX_CAROUSEL_TOO_LARGE");
    const repeated: any = [sizedBubble(24_000, "")];
    repeated[Symbol.iterator] = function* () { yield repeated[0]; yield repeated[0]; };
    expect(acceptedContents({ type: "carousel", contents: repeated }).contents).toEqual([repeated[0]]);
    const replaced: any = [{ type: "not-bubble", payload: "x".repeat(48_000) }];
    replaced[Symbol.iterator] = function* () { yield bubble(""); };
    expect(() => assertLineMessages(flex({ type: "carousel", contents: replaced }))).toThrow("LINE_FLEX_CAROUSEL_TOO_LARGE");
  });

  it("does not call custom array methods or hide holes and root serializers", () => {
    for (const method of ["includes", "every"]) {
      const list: any = [bubble("")];
      list[method] = () => { throw new Error("CUSTOM_METHOD"); };
      expect(acceptedContents({ type: "carousel", contents: list }).contents).toEqual([bubble("")]);
    }
    const noncallable: any = [bubble("")]; noncallable.includes = 0;
    expect(acceptedContents({ type: "carousel", contents: noncallable }).contents).toEqual([bubble("")]);
    const getter: any = [bubble("")];
    Object.defineProperty(getter, "every", { get() { throw new Error("EVERY_GET"); } });
    expect(acceptedContents({ type: "carousel", contents: getter }).contents).toEqual([bubble("")]);
    const hole: any = Array(1); hole.includes = () => false;
    expect(() => assertLineMessages(flex({ type: "carousel", contents: hole }))).toThrow("LINE_FLEX_BUBBLE_INVALID");
    const serializer: any = [{ type: "bubble", toJSON(key: string) { return key === "" ? bubble("") : sizedBubble(48_000, ""); } }];
    serializer.every = () => true;
    expect(() => assertLineMessages(flex({ type: "carousel", contents: serializer }))).toThrow("LINE_FLEX_CAROUSEL_TOO_LARGE");
    const proxy = new Proxy(bubble(""), { has(target, key) { if (key === "toJSON") throw new Error("HAS_TOJSON"); return Reflect.has(target, key); } });
    expect(acceptedContents({ type: "carousel", contents: [proxy] }).contents).toEqual([bubble("")]);
  });

  it("retains original custom-iterator and custom-every pack grouping", () => {
    const custom = () => ({ type: "bubble", toJSON(key: string) { return key === "" ? bubble("") : sizedBubble(23_500, ""); } });
    const iterated: any = [bubble(""), bubble("")];
    iterated[Symbol.iterator] = function* () { yield custom(); yield custom(); };
    expect(packCarousels(iterated, alt).map(m => m.type === "flex" && (m.contents.contents as unknown[]).length)).toEqual([1, 1]);
    const every: any = [custom(), custom()]; every.every = () => true;
    expect(packCarousels(every, alt).map(m => m.type === "flex" && (m.contents.contents as unknown[]).length)).toEqual([1, 1]);
    const throwing: any = [bubble("")]; throwing.every = () => { throw new Error("PACK_EVERY"); };
    expect(packCarousels(throwing, alt)).toEqual([{ type: "flex", altText: shortAltText("Page 1/1"), contents: { type: "carousel", contents: [bubble("")] } }]);
  });

  it.each(["throw", "bigint", "cycle"] as const)("preserves whole-carousel serialization before early type accessor: %s", kind => {
    const first = Object.defineProperty({ payload: "small" }, "type", { get() { throw new Error("EARLY_TYPE"); } });
    const later: any = { type: "bubble" };
    if (kind === "throw") Object.defineProperty(later, "payload", { enumerable: true, get() { throw new Error("LATER_PAYLOAD"); } });
    else if (kind === "bigint") later.payload = 1n;
    else later.payload = later;
    expect(() => assertLineMessages(flex({ type: "carousel", contents: [first, later] })))
      .toThrow(kind === "throw" ? "LATER_PAYLOAD" : kind === "bigint" ? /BigInt/i : /circular/i);
  });

  it("keeps oversized carousel and serializer errors ahead of type and iterator getters", () => {
    const first = Object.defineProperty(sizedBubble(24_000, ""), "type", { enumerable: false, get() { throw new Error("EARLY_TYPE"); } });
    expect(() => assertLineMessages(flex({ type: "carousel", contents: [first, sizedBubble(24_050, "")] }))).toThrow("LINE_FLEX_CAROUSEL_TOO_LARGE");
    const later: any = { type: "bubble", payload: 1n };
    const mutator = Object.defineProperty({ payload: "small" }, "type", { get() { later.payload = "fixed"; return "not-bubble"; } });
    expect(() => assertLineMessages(flex({ type: "carousel", contents: [mutator, later] }))).toThrow(/BigInt/i);
    const list: any = [{ type: "bubble", payload: 1n }];
    Object.defineProperty(list, Symbol.iterator, { get() { throw new Error("ITERATOR_READ"); } });
    expect(() => assertLineMessages(flex({ type: "carousel", contents: list }))).toThrow(/BigInt/i);
  });

  it.each(["bigint", "cycle", "getter"] as const)("calls first altText before serializing a single bubble: %s", kind => {
    const value: any = { type: "bubble" };
    if (kind === "bigint") value.payload = 1n;
    else if (kind === "cycle") value.payload = value;
    else Object.defineProperty(value, "payload", { enumerable: true, get() { throw new Error("PAYLOAD"); } });
    expect(() => packCarousels([value], () => { throw new Error("ALT_FIRST"); })).toThrow("ALT_FIRST");
  });
});
