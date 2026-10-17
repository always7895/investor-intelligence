// U1-04 (BATCH04 matrix): defensive bounds of the ambiguous identity card, driven through the exported builder with synthetic
// EquityLookupResult objects only: no KV, no handler, no network and no LINE send. assertLineMessages runs inside the builder.
import { describe, expect, it } from "vitest";
import type { LineOutboundMessage } from "../src/line-messages";
import {
  buildGlobalEquityLookupMessages,
  type CandidateQueryRoute,
  type CandidateRouteStatus,
  type EquityLookupResult,
  type GlobalIdentityRecord,
} from "../src/v213/global-equity-lookup";

const LIST_TITLE = "\u53ef\u9078\u5019\u9078\u4ee3\u865f\uff1a";
const SHOWN = "\u5df2\u986f\u793a";  // the omission note's "shown" prefix
const BULLET = "\u2022 ";
const ARROW = "\u2192";
const SAFE_NAVIGATION = ["TOP20", "\u9078\u55ae"];
const TEXT_MAX = 4900;  // the project text bound checked by assertLineMessages (cloud/src/line-messages.ts)

function listing(symbol: string, name: string): GlobalIdentityRecord {
  return {
    venue: "NASDAQ STOCKHOLM", market: "SWEDEN", country: "Sweden", symbol, native_symbol: symbol, security_name: name,
    security_class: "COMMON_STOCK", currency: "SEK", source_feed: "nasdaq-stockholm-main",
    source_url: "https://api.nasdaq.com/api/nordic/screener/shares?category=MAIN_MARKET&tableonly=false&market=STO",
  };
}
/** The handler's candidate display line. */
const display = (r: GlobalIdentityRecord) => `${r.symbol} (${r.venue}, ${r.country}) - ${r.security_name}`;

function ambiguous(candidates: GlobalIdentityRecord[],
  options: { displays?: string[]; routes?: CandidateQueryRoute[]; disclaimer?: string } = {}): EquityLookupResult {
  return {
    identity: {
      rawInput: "U1", normalizedSymbol: "U1", canonicalSymbol: "U1", market: "UNKNOWN", country: "U1", exchange: "U1",
      currency: "UNAVAILABLE", isAmbiguous: true, ambiguityCandidates: options.displays ?? candidates.map(display),
      leadingZeroPreserved: false,
    },
    admittedInSealedSnapshot: true,
    nameUnverified: true,
    quoteStatus: "AMBIGUOUS",
    source: "sealed_snapshot:catalog_multi_match",
    disclaimer: options.disclaimer ?? "U1 synthetic disclaimer",
    resolution: { status: "NEEDS_MARKET_SELECTION", query: "U1", candidates },
    ...(options.routes ? { candidateRoutes: options.routes } : {}),
  };
}
function textsOf(messages: LineOutboundMessage[]): string[] {
  return messages.map(message => {
    if (message.type !== "text") throw new Error("U1_EXPECTED_TEXT");
    return message.text;
  });
}
/** The message text of every Flex button, in footer order. */
function buttons(result: EquityLookupResult): string[] {
  const raw = JSON.stringify(buildGlobalEquityLookupMessages(result, "flex"));
  return [...raw.matchAll(/"action":\{"type":"message","label":"[^"]*","text":"([^"]*)"\}/g)].map(match => match[1] ?? "");
}
const bulletLines = (text: string | undefined) => (text ?? "").split("\n").filter(line => line.startsWith(BULLET));
/** Length of the fixed card (seven head lines and two tail lines) of a one-message ambiguous text card. */
function fixedLength(result: EquityLookupResult): number {
  const [text] = textsOf(buildGlobalEquityLookupMessages(result, "text"));
  const lines = (text ?? "").split("\n");
  if (lines[7] !== LIST_TITLE) throw new Error("U1_LAYOUT");
  return [...lines.slice(0, 7), ...lines.slice(-2)].join("\n").length;
}
/** The same ambiguous result with its disclaimer padded so the fixed card is exactly `target` UTF-16 units. */
function withFixed(candidates: GlobalIdentityRecord[], target: number): EquityLookupResult {
  const rest = fixedLength(ambiguous(candidates, { disclaimer: "D" })) - 1;
  return ambiguous(candidates, { disclaimer: "D".repeat(target - rest) });
}

describe("U1-04 ambiguous card bounds (synthetic results through the exported builder)", () => {
  const pair = [listing("A00", "Orbit Zero"), listing("A01", "Orbit One")];

  it("two-message overflow: a fixed card at the exact bound is sent first, then the bounded candidate block", () => {
    const result = withFixed(pair, TEXT_MAX);
    const messages = buildGlobalEquityLookupMessages(result, "text");
    const [fixed, block] = textsOf(messages);
    expect(messages).toHaveLength(2);
    expect(fixed?.length).toBe(TEXT_MAX);
    expect((block ?? "").split("\n")[0]).toBe(LIST_TITLE);
    expect(bulletLines(block)).toEqual([]);
    expect(block).toContain(`${SHOWN} 0/2 `);
    expect(`${fixed}\n${block}`.length).toBeGreaterThan(TEXT_MAX);
    // Flex shows the same (empty) prefix and omission count, and only the safe navigation.
    const flex = JSON.stringify(buildGlobalEquityLookupMessages(result, "flex"));
    expect(flex).toContain(`${SHOWN} 0/2 `);
    expect(flex).not.toContain("Orbit Zero");
    expect(buttons(result)).toEqual(SAFE_NAVIGATION);
  });

  it("the split boundary is exact: one unit under it stays one message of exactly the bound", () => {
    const blockLength = (textsOf(buildGlobalEquityLookupMessages(withFixed(pair, TEXT_MAX), "text"))[1] ?? "").length;
    expect(blockLength).toBeGreaterThan(0);
    const single = textsOf(buildGlobalEquityLookupMessages(withFixed(pair, TEXT_MAX - 1 - blockLength), "text"));
    expect(single.map(text => text.length)).toEqual([TEXT_MAX]);
    const split = textsOf(buildGlobalEquityLookupMessages(withFixed(pair, TEXT_MAX - blockLength), "text"));
    expect(split.map(text => text.length)).toEqual([TEXT_MAX - blockLength, blockLength]);
  });

  it("a fixed card over the text bound is rejected, never split or cut", () => {
    const result = withFixed(pair, TEXT_MAX + 1);
    expect(() => buildGlobalEquityLookupMessages(result, "text")).toThrow("LINE_TEXT_SIZE_INVALID");
  });

  it("first-line nonfit ends the prefix: a too-long first candidate hides every later candidate", () => {
    // The prefix is measured on the bulleted text line (BULLET + display) against the 3000-unit display bound.
    const later = display(pair[1]!);
    const nonfit = ambiguous(pair, { displays: ["L".repeat(2999), later] });
    const [text] = textsOf(buildGlobalEquityLookupMessages(nonfit, "text"));
    expect(bulletLines(text)).toEqual([]);
    expect(text).toContain(`${SHOWN} 0/2 `);
    expect(text).not.toContain(later);
    expect(buttons(nonfit)).toEqual(SAFE_NAVIGATION);
    // Control: one unit shorter fits exactly; the prefix still stops at the first line that does not fit.
    const fit = ambiguous(pair, { displays: ["L".repeat(2998), later] });
    const [fitText] = textsOf(buildGlobalEquityLookupMessages(fit, "text"));
    expect(bulletLines(fitText)).toEqual([BULLET + "L".repeat(2998)]);
    expect(fitText).toContain(`${SHOWN} 1/2 `);
    expect(fitText).not.toContain(later);
  });

  it("inconsistent internal routes are display-only: no route line and only the safe navigation", () => {
    const three = [...pair, listing("A02", "Orbit Two")];
    const displays = three.map(display);
    const routes: CandidateQueryRoute[] = [
      { display: displays[0]!, status: "CERTIFIED", query: "A00.ST" },
      { display: displays[1]!, status: "NOT_CERTIFIED" },
      { display: displays[2]!, status: "UNCHECKED" },
    ];
    // Control: consistent routes add a route line per candidate and exactly the certified button.
    const control = ambiguous(three, { routes });
    const [controlText] = textsOf(buildGlobalEquityLookupMessages(control, "text"));
    expect(bulletLines(controlText).filter(line => line.includes(ARROW))).toHaveLength(3);
    expect(buttons(control)).toEqual(["A00.ST"]);
    const variants: Record<string, EquityLookupResult> = {
      short: ambiguous(three, { routes: routes.slice(0, 2) }),
      display: ambiguous(three, { routes: [{ ...routes[0]!, display: `${displays[0]} ` }, routes[1]!, routes[2]!] }),
      foreignQuery: ambiguous(three, { routes: [{ ...routes[0]!, query: "A01.ST" }, routes[1]!, routes[2]!] }),
      missingQuery: ambiguous(three, { routes: [{ display: displays[0]!, status: "CERTIFIED" }, routes[1]!, routes[2]!] }),
      queryOnDisplayOnly: ambiguous(three, { routes: [routes[0]!, { ...routes[1]!, query: "A01.ST" }, routes[2]!] }),
      unknownStatus: ambiguous(three, {
        routes: [routes[0]!, { display: displays[1]!, status: "VERIFIED" as unknown as CandidateRouteStatus }, routes[2]!],
      }),
      candidateCount: {
        ...ambiguous(three, { routes }),
        resolution: { status: "NEEDS_MARKET_SELECTION", query: "U1", candidates: [...three, listing("A03", "Orbit Three")] },
      },
    };
    for (const [name, result] of Object.entries(variants)) {
      const [text] = textsOf(buildGlobalEquityLookupMessages(result, "text"));
      expect(text?.includes(ARROW), name).toBe(false);
      expect(text?.includes("A00.ST"), name).toBe(false);
      expect(buttons(result), name).toEqual(SAFE_NAVIGATION);
    }
  });
});
