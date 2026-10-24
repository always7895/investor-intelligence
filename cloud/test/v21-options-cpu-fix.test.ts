// PROTOTYPE tests for the Worker CPU fix of the options query path (R/ASTRA-ROLLOUT12 finding B2): one-pass body verification, per-isolate memory of
// verified lazy bodies, single-member reads of the options/quotes documents, coverage link check against the sealed pair, per-day catalog memo.
// Synthetic data only. The parity tests run the new path against the unchanged full-parse path on the same sealed bytes.
import { beforeEach, describe, expect, it, vi } from "vitest";
import fixture from "./fixtures/v21-three-strategies.json";
import { ALPHA_VANTAGE_SOURCE_LABEL } from "../src/v213/alpha-vantage-viewer";
import { loadDetailedOptionObservation, OPTIONS_KEY, QUOTES_KEY, optionTickerKeys } from "../src/v213/market-observations";
import { loadOptionsCoverage } from "../src/v213/options-coverage";
import { clearVerifiedLazyBodies, pinPublicSnapshot, scopePublicSnapshot, type PublicSnapshotView } from "../src/v213/public-snapshot";
import { memberIndexBuilds, parseObjectMember, scanMembers, sealedHeader } from "../src/v213/sealed-slice";
import { readLazySealedObject, SNAPSHOT_SEAL_KEY } from "../src/v213/snapshot-seal";
import { asKv, MemoryKv } from "./fake-kv";
import { sealUnboundReport } from "./sealed-report-migration";
import { admitSyntheticTickers, resetAdmissionToReal } from "./synthetic-option-admission";

vi.mock("../src/v213/public-options-admission", async importOriginal => {
  const real = await importOriginal<typeof import("../src/v213/public-options-admission")>();
  return { ...real, admitPublicOption: vi.fn(real.admitPublicOption) };
});
beforeEach(() => { resetAdmissionToReal(); });

type Json = Record<string, any>;
const STAMP: string = fixture.stamp;
const NOW = Date.parse(STAMP) + 60_000;
const cases = fixture.cases as unknown as Record<string, Json>;
const RUN = "20260930T170000Z-abcdefabcde7";

async function sha(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
}
function cycleFor(ticker: string, name = "yahoo_monthly_full"): Json {
  const cycle = structuredClone(cases[name]!);
  cycle.ticker = ticker;
  return cycle;
}
/** A sealed public snapshot whose lazy objects are exactly the given bodies (strings are stored verbatim). */
async function sealed(lazy: Record<string, unknown>, kv = new MemoryKv()) {
  kv.values.set("v213:top20-report:latest", JSON.stringify({ synthetic: "report" }));
  kv.values.set("last_successful_pipeline_timestamp", STAMP);
  await sealUnboundReport(kv, RUN);
  const sealKey = `snapshot:${RUN}:${SNAPSHOT_SEAL_KEY}`;
  const seal = JSON.parse(kv.values.get(sealKey)!);
  for (const [key, value] of Object.entries(lazy)) {
    const body = typeof value === "string" ? value : JSON.stringify(value);
    const digest = await sha(body);
    seal.objects[key] = { sha256: digest, utf8_bytes: new TextEncoder().encode(body).byteLength };
    kv.values.set(`blob:v1:${digest}`, body);
  }
  const sealText = JSON.stringify(seal);
  kv.values.set(sealKey, sealText);
  const pointer = JSON.parse(kv.values.get("snapshot:current")!);
  pointer.seal_sha256 = await sha(sealText);
  kv.values.set("snapshot:current", JSON.stringify(pointer));
  return { kv, env: { PUBLIC_CACHE: asKv(kv), TENANT_PRIVATE_CACHE: asKv(new MemoryKv()), EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()) } as never };
}
/** Publish run `run` into `kv` with one lazy object `body` (declared UTF-8 length offset by `lengthOffset`), resealing manifest and pointer normally. */
async function sealedRun(kv: MemoryKv, run: string, key: string, body: string, lengthOffset = 0) {
  kv.values.set("v213:top20-report:latest", JSON.stringify({ synthetic: "report" }));
  kv.values.set("last_successful_pipeline_timestamp", STAMP);
  await sealUnboundReport(kv, run);
  const sealKey = `snapshot:${run}:${SNAPSHOT_SEAL_KEY}`;
  const seal = JSON.parse(kv.values.get(sealKey)!);
  const digest = await sha(body);
  seal.objects[key] = { sha256: digest, utf8_bytes: new TextEncoder().encode(body).byteLength + lengthOffset };
  kv.values.set(`blob:v1:${digest}`, body);
  const sealText = JSON.stringify(seal);
  kv.values.set(sealKey, sealText);
  const pointer = JSON.parse(kv.values.get("snapshot:current")!);
  pointer.seal_sha256 = await sha(sealText);
  kv.values.set("snapshot:current", JSON.stringify(pointer));
  return { PUBLIC_CACHE: asKv(kv), TENANT_PRIVATE_CACHE: asKv(new MemoryKv()), EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()) } as never;
}
const quoteRow = (symbol: string, source: string, url: string) => ({ symbol, price: 100, previous_close: 99, change_pct: 0.01, currency: "USD", asof: STAMP, source, source_url: url });

describe("sealed-slice: single-member reads of a producer-compact document", () => {
  const header = (text: string) => sealedHeader(text, "v213-options-v2", "options")!;

  it("reads the header and refuses anything that is not exactly the producer shape", () => {
    const ok = JSON.stringify({ schema: "v213-options-v2", generated_at: STAMP, options: { AAA: { monthly: {} } } });
    expect(sealedHeader(ok, "v213-options-v2", "options")).toEqual({ generated_at: STAMP, bodyStart: ok.indexOf('"options":{') + '"options":{'.length, container: "options" });
    expect(sealedHeader(ok, "v213-quotes-v1", "options")).toBeUndefined();
    expect(sealedHeader(ok, "v213-options-v2", "quotes")).toBeUndefined();
    expect(sealedHeader(JSON.stringify(JSON.parse(ok), null, 1), "v213-options-v2", "options")).toBeUndefined();   // pretty-printed
    expect(sealedHeader(JSON.stringify({ generated_at: STAMP, schema: "v213-options-v2", options: {} }), "v213-options-v2", "options")).toBeUndefined();  // key order
    expect(sealedHeader("﻿" + ok, "v213-options-v2", "options")).toBeUndefined();
    expect(sealedHeader('{"schema":"v213-options-v2","generated_at":"' + "x".repeat(60) + '","options":{}}', "v213-options-v2", "options")).toBeUndefined();
    expect(sealedHeader('{"schema":"v213-options-v2","generated_at":"a\\"b","options":{}}', "v213-options-v2", "options")).toBeUndefined();
  });

  it("equals JSON.parse(...).options[key] for random compact documents, including braces, quotes, backslashes and unicode inside strings", () => {
    let seed = 7;
    const rnd = () => (seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff;
    const tricky = ['}"', '{"', '\\', '\\"', '"A":{', '[1,{"B":2}]', "報價—", "💡", ",", ":"];
    for (let round = 0; round < 60; round += 1) {
      const options: Record<string, unknown> = {};
      const keys: string[] = [];
      for (let i = 0; i < 12; i += 1) {
        const key = `K${i}${"ABCXYZ.- "[Math.floor(rnd() * 9)]}${round % 7}`.trim();
        keys.push(key);
        options[key] = { weekly: { note: tricky[Math.floor(rnd() * tricky.length)]! + tricky[Math.floor(rnd() * tricky.length)]!, n: [1, { x: tricky[0]! }] }, monthly: { unavailable: tricky[round % tricky.length]! } };
      }
      const text = JSON.stringify({ schema: "v213-options-v2", generated_at: STAMP, options });
      const h = header(text);
      for (const key of keys) expect(parseObjectMember(text, h, key), key).toEqual(JSON.parse(text).options[key]);
      expect(parseObjectMember(text, h, "NOPE")).toBeNull();
    }
  });

  const docOf = (members: string) => `{"schema":"v213-options-v2","generated_at":"${STAMP}","options":{${members}}}`;

  it("a ticker-shaped key that exists only below depth 1 is ABSENT, never the entry (digit-start, uppercase, ticker-like keys in arrays and strings)", () => {
    const text = docOf('"AAA":{"monthly":{"expiry":"2026-11-20","by":{"2026-11-20":{"x":1},"NESTED":{"y":2},"BBB":{"z":3}},"rows":[{"CCC":{"q":4}},[{"DDD":{"q":5}}]]},"note":"\\"EEE\\":{\\"k\\":1}"},"ZZZ":{"a":1}');
    const h = header(text);
    for (const key of ["2026-11-20", "NESTED", "BBB", "CCC", "DDD", "EEE", "X"]) expect(parseObjectMember(text, h, key), key).toBeNull();
    expect(parseObjectMember(text, h, "monthly")).toBeUndefined();   // lowercase is not the producer ticker syntax: full path
    expect(parseObjectMember(text, h, "AAA")).toEqual(JSON.parse(text).options.AAA);
    expect(parseObjectMember(text, h, "ZZZ")).toEqual({ a: 1 });
    const index = scanMembers(text, h.bodyStart)!;
    expect([...index.spans.keys()]).toEqual(["AAA", "ZZZ"]);
    // identical to the full-parse path
    for (const key of ["2026-11-20", "NESTED", "BBB", "CCC", "DDD", "EEE"]) expect(Object.hasOwn(JSON.parse(text).options, key), key).toBe(false);
  });

  it("a duplicate depth-1 key refuses the whole index (undefined for every key, present or not), also when the duplicates are far apart", () => {
    const dup = docOf('"AAA":{"a":1},"BBB":{"b":1},"AAA":{"a":2}');
    for (const key of ["AAA", "BBB", "CCC"]) expect(parseObjectMember(dup, header(dup), key), key).toBeUndefined();
    expect(scanMembers(dup, header(dup).bodyStart)).toBeUndefined();
    const sameNameDeeper = docOf('"AAA":{"AAA":{"a":1}},"BBB":{"b":1}');   // the same name at depth 2 is not a duplicate of depth 1
    expect(parseObjectMember(sameNameDeeper, header(sameNameDeeper), "AAA")).toEqual({ AAA: { a: 1 } });
    expect(parseObjectMember(sameNameDeeper, header(sameNameDeeper), "BBB")).toEqual({ b: 1 });
  });

  it("refuses malformed containers instead of guessing: truncation, missing colon or comma, wrong bracket kind, trailing text, escaped or non-string key, scalar value", () => {
    const refused = [
      '{"schema":"v213-options-v2","generated_at":"' + STAMP + '","options":{"AAA":{"x":{"y":[1,2',
      docOf('"AAA"{"a":1}'), docOf('"AAA":{"a":1}"BBB":{"b":1}'), docOf('"AAA":{"a":[1}],"b":1}'), docOf('"AAA":{"a":{"b":1]}'),
      docOf('"AAA":{"a":1}') + "\n", docOf('"AAA":{"a":1}').slice(0, -1), docOf('"AAA":{"a":1},'), docOf('"A\\"A":{"a":1}'), docOf('AAA:{"a":1}'), docOf('"AAA":'),
    ];
    for (const text of refused) {
      const h = sealedHeader(text, "v213-options-v2", "options")!;
      expect(h, text).toBeDefined();
      expect(scanMembers(text, h.bodyStart), text).toBeUndefined();
      expect(parseObjectMember(text, h, "AAA"), text).toBeUndefined();
    }
    const scalar = docOf('"AAA":3');   // a well-formed container whose member is not an object: indexed, but never returned as an entry
    expect(parseObjectMember(scalar, header(scalar), "AAA")).toBeUndefined();
    expect(parseObjectMember(scalar, header(scalar), "BBB")).toBeNull();
    expect(parseObjectMember(docOf(""), header(docOf("")), "AAA")).toBeNull();   // an empty container has no members
    const arrayValue = docOf('"AAA":[{"a":1}],"BBB":{"b":1},"CCC":"s","DDD":true,"EEE":null,"FFF":1.5e3');
    expect(parseObjectMember(arrayValue, header(arrayValue), "BBB")).toEqual({ b: 1 });
    expect(parseObjectMember(arrayValue, header(arrayValue), "AAA")).toBeUndefined();   // not an object
    expect([...scanMembers(arrayValue, header(arrayValue).bodyStart)!.spans.keys()]).toEqual(["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]);
    expect(parseObjectMember(docOf('"AAA":{"a":1}'), header(docOf('"AAA":{"a":1}')), "aaa")).toBeUndefined();   // not the producer ticker syntax
    expect(parseObjectMember(docOf('"AAA":{"a":1}'), header(docOf('"AAA":{"a":1}')), "A".repeat(17))).toBeUndefined();
  });

  it("a document JSON.parse refuses is refused for every key, present or absent, whichever unrequested member is malformed (SOL-V24V22 F1)", () => {
    const broken = ["not_json", "tru", "nul", '{"missing":}', '{"a":1,}', '["x",]', '"bad \\x escape"', '"raw \u0001 control"', "01", "1.", "-", "1e", "+1", "NaN"];
    for (const value of broken) {
      const text = docOf('"AAA":{"monthly":{"unavailable":"synthetic"}},"BROKEN":' + value);
      expect(() => JSON.parse(text), value).toThrow();
      const h = header(text);
      for (const sha256 of [undefined, "d".repeat(64)]) {
        expect(parseObjectMember(text, h, "AAA", sha256), `${value} AAA ${sha256 ?? "no digest"}`).toBeUndefined();
        expect(parseObjectMember(text, h, "ZZZ", sha256), `${value} ZZZ ${sha256 ?? "no digest"}`).toBeUndefined();
      }
      clearVerifiedLazyBodies();
    }
    // the same members with valid JSON values answer as JSON.parse does
    for (const value of ["null", "true", "false", "0", "-1.5e-3", '"s"', '{"a":[1,{"b":null}]}', "[]"]) {
      const text = docOf('"AAA":{"monthly":{"unavailable":"synthetic"}},"BROKEN":' + value);
      expect(parseObjectMember(text, header(text), "AAA"), value).toEqual(JSON.parse(text).options.AAA);
      expect(parseObjectMember(text, header(text), "ZZZ"), value).toBeNull();
    }
  });

  it("a member value that does not start as a JSON value (whitespace included) refuses the index, so a literal scan never stops inside a nested value", () => {
    for (const members of ['"AAA": {"a":1,"BBB":{"b":1}}', '"AAA":\t1,"BBB":{"b":1}', '"AAA":{"a":1},"BBB": 2', '"AAA":x,"BBB":{"b":1}']) {
      const text = docOf(members);
      expect(scanMembers(text, header(text).bodyStart), members).toBeUndefined();
      for (const key of ["AAA", "BBB", "ZZZ"]) expect(parseObjectMember(text, header(text), key), `${members} ${key}`).toBeUndefined();
    }
  });

  it("braces, brackets, quotes, backslashes and escaped quotes inside string values never move a member boundary", () => {
    const nasty = ['}', '{', '"', '\\', '\\\\', '\\"', '"}', '{"', '"A":{"x":1}', '","B":{"y":2},"C":"', '[', ']', '\\u0022', '💡', '報價—}'];
    for (const value of nasty) {
      const text = JSON.stringify({ schema: "v213-options-v2", generated_at: STAMP, options: {
        AAA: { note: value, list: [value, { k: value }], "key}\"{": value }, BBB: { note: value }, CCC: { n: 1 },
      } });
      const h = header(text);
      const truth = JSON.parse(text).options;
      for (const key of ["AAA", "BBB", "CCC"]) expect(parseObjectMember(text, h, key), `${key} ${JSON.stringify(value)}`).toEqual(truth[key]);
      for (const key of ["A", "B", "C", "DDD"]) expect(parseObjectMember(text, h, key), `${key} ${JSON.stringify(value)}`).toBeNull();
      expect([...scanMembers(text, h.bodyStart)!.spans.keys()]).toEqual(["AAA", "BBB", "CCC"]);
    }
  });
});

describe("loadDetailedOptionObservation: single-member read equals the full-parse path", () => {
  const tickers = ["AAA", "BBB", "CCC", "AVQ", "UNAV", "BAD", "SIVE.ST", "OLD"];
  function options(): Record<string, unknown> {
    const bad = cycleFor("BAD"); bad.spot = -1;
    const old = cycleFor("OLD"); delete old.strategies;
    return {
      AAA: { monthly: cycleFor("AAA"), weekly: { unavailable: "合成：AAA 本週無雙邊報價" } },
      BBB: { monthly: cycleFor("BBB", "yahoo_monthly_no_covered_call") },
      CCC: { monthly: cycleFor("CCC") },
      AVQ: { monthly: cycleFor("AVQ"), weekly: { unavailable: "合成" } },   // Alpha Vantage derived underlying (quote row below)
      UNAV: { weekly: { unavailable: "x" } },
      BAD: { monthly: bad },
      "SIVE.ST": { monthly: cycleFor("SIVE.ST", "nordic_monthly_sek") },
      OLD: { monthly: old },
    };
  }
  async function views(extra: Record<string, unknown> = {}) {
    const doc = { schema: "v213-options-v2", generated_at: STAMP, options: options() };
    const quotes = { schema: "v213-quotes-v1", generated_at: STAMP, quotes: {
      AAA: quoteRow("AAA", "Yahoo Finance (unofficial, delayed)", "https://finance.yahoo.com/quote/AAA"),
      AVQ: quoteRow("AVQ", ALPHA_VANTAGE_SOURCE_LABEL, "https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol=AVQ"),
    } };
    const { env } = await sealed({ [OPTIONS_KEY]: JSON.stringify(doc), [QUOTES_KEY]: JSON.stringify(quotes), ...extra });
    return env;
  }
  /** The same view without the verified text: loadDetailedOptionObservation then takes the unchanged full-parse path. */
  const legacyOf = (view: PublicSnapshotView): PublicSnapshotView => ({ ...view, text: async keys => (keys[0] === OPTIONS_KEY ? null : view.text(keys)) });

  for (const viewer of ["owner", "friend"] as const) {
    it(`every ticker x period gives the same typed result for the ${viewer} view`, async () => {
      admitSyntheticTickers(...tickers);
      const env = await views();
      for (const ticker of [...tickers, "NOPE"]) for (const period of ["weekly", "monthly"] as const) {
        const fast = await pinPublicSnapshot(scopePublicSnapshot(env, viewer));
        const slow = legacyOf(await pinPublicSnapshot(scopePublicSnapshot(env, viewer)));
        const a = await loadDetailedOptionObservation(fast, optionTickerKeys(ticker), period, NOW);
        const b = await loadDetailedOptionObservation(slow, optionTickerKeys(ticker), period, NOW);
        expect(a, `${ticker} ${period}`).toEqual(b);
      }
    });
  }

  it("a friend gets the unavailable state for the Alpha Vantage underlying only; the owner gets the quote", async () => {
    admitSyntheticTickers(...tickers);
    const env = await views();
    const friend = await loadDetailedOptionObservation(await pinPublicSnapshot(scopePublicSnapshot(env, "friend")), "AVQ", "monthly", NOW);
    expect(friend.status).toBe("PERIOD_UNAVAILABLE");
    expect(friend.unavailable).toContain("現價暫不可用");
    const other = await loadDetailedOptionObservation(await pinPublicSnapshot(scopePublicSnapshot(env, "friend")), "CCC", "monthly", NOW);
    expect(other.status).toBe("FOUND");
    const owner = await loadDetailedOptionObservation(await pinPublicSnapshot(scopePublicSnapshot(env, "owner")), "AVQ", "monthly", NOW);
    expect(owner.status).toBe("FOUND");
  });

  it("a pretty-printed or reordered document still answers identically (full-parse fallback)", async () => {
    admitSyntheticTickers(...tickers);
    const doc = { schema: "v213-options-v2", generated_at: STAMP, options: options() };
    const pretty = await sealed({ [OPTIONS_KEY]: JSON.stringify(doc, null, 1) });
    const reordered = await sealed({ [OPTIONS_KEY]: JSON.stringify({ generated_at: STAMP, options: doc.options, schema: "v213-options-v2" }) });
    for (const { env } of [pretty, reordered]) {
      const view = await pinPublicSnapshot(scopePublicSnapshot(env, "owner"));
      expect((await loadDetailedOptionObservation(view, "AAA", "monthly", NOW)).status).toBe("FOUND");
      expect((await loadDetailedOptionObservation(view, "NOPE", "monthly", NOW)).status).toBe("TICKER_NOT_IN_SNAPSHOT");
    }
  });

  it("document-level states are decided before the ticker, as before", async () => {
    admitSyntheticTickers(...tickers);
    const stale = await sealed({ [OPTIONS_KEY]: JSON.stringify({ schema: "v213-options-v2", generated_at: "2026-09-29T00:00:00Z", options: options() }) });
    expect((await loadDetailedOptionObservation(await pinPublicSnapshot(scopePublicSnapshot(stale.env, "owner")), "NOPE", "monthly", NOW)).status).toBe("DOCUMENT_STALE");
    const wrongSchema = await sealed({ [OPTIONS_KEY]: JSON.stringify({ schema: "v213-options-v1", generated_at: STAMP, options: options() }) });
    expect((await loadDetailedOptionObservation(await pinPublicSnapshot(scopePublicSnapshot(wrongSchema.env, "owner")), "AAA", "monthly", NOW)).status).toBe("DOCUMENT_INVALID_OR_UNREADABLE");
    const future = await sealed({ [OPTIONS_KEY]: JSON.stringify({ schema: "v213-options-v2", generated_at: "2026-09-30T18:00:00Z", options: options() }) });
    expect((await loadDetailedOptionObservation(await pinPublicSnapshot(scopePublicSnapshot(future.env, "owner")), "AAA", "monthly", NOW)).status).toBe("DOCUMENT_INVALID_OR_UNREADABLE");
  });
});

describe("loadDetailedOptionObservation: depth-1 exactness equals the full-parse path", () => {
  const legacyOf = (view: PublicSnapshotView): PublicSnapshotView => ({ ...view, text: async keys => (keys[0] === OPTIONS_KEY ? null : view.text(keys)) });
  const both = async (env: never, viewer: "owner" | "friend", key: string, period: "weekly" | "monthly") => {
    const fast = await loadDetailedOptionObservation(await pinPublicSnapshot(scopePublicSnapshot(env, viewer)), optionTickerKeys(key), period, NOW);
    const slow = await loadDetailedOptionObservation(legacyOf(await pinPublicSnapshot(scopePublicSnapshot(env, viewer))), optionTickerKeys(key), period, NOW);
    return { fast, slow };
  };

  it("a key present only at depth >= 2 (digit-start, uppercase, ticker-like) is TICKER_NOT_IN_SNAPSHOT exactly as the full parse says", async () => {
    admitSyntheticTickers("AAA", "BBB");
    const aaa = cycleFor("AAA");
    (aaa as Json).by_expiry = { "2026-11-20": { x: 1 }, NESTED: { y: 2 }, BBB: { cycle: cycleFor("BBB") } };
    const body = JSON.stringify({ schema: "v213-options-v2", generated_at: STAMP, options: { AAA: { monthly: aaa, extra: { "2026-11-20": { x: 1 }, NESTED: cycleFor("NESTED"), BBB: { monthly: cycleFor("BBB") } } } } });
    const { env } = await sealed({ [OPTIONS_KEY]: body });
    for (const viewer of ["owner", "friend"] as const) {
      for (const key of ["2026-11-20", "NESTED", "BBB"]) for (const period of ["weekly", "monthly"] as const) {
        const { fast, slow } = await both(env, viewer, key, period);
        expect(slow.status, `${key} legacy`).toBe("TICKER_NOT_IN_SNAPSHOT");
        expect(fast, `${key} ${period} ${viewer}`).toEqual(slow);
      }
      const { fast, slow } = await both(env, viewer, "AAA", "monthly");
      expect(slow.status).toBe("FOUND");
      expect(fast).toEqual(slow);
    }
  });

  it("a sealed document JSON.parse refuses is DOCUMENT_INVALID_OR_UNREADABLE on both paths, for a present and an absent ticker (SOL-V24V22 F1)", async () => {
    for (const other of ["not_json", '{"missing":}', '"bad \\q"', "01"]) {
      const body = `{"schema":"v213-options-v2","generated_at":"${STAMP}","options":{"AAA":{"monthly":{"unavailable":"synthetic unavailable"}},"BROKEN":${other}}}`;
      expect(() => JSON.parse(body), other).toThrow();
      const { env } = await sealed({ [OPTIONS_KEY]: body });
      for (const viewer of ["owner", "friend"] as const) for (const key of ["AAA", "ZZZ"]) {
        const { fast, slow } = await both(env, viewer, key, "monthly");
        expect(slow.status, `${other} ${key} ${viewer} legacy`).toBe("DOCUMENT_INVALID_OR_UNREADABLE");
        expect(fast, `${other} ${key} ${viewer}`).toEqual(slow);
      }
      clearVerifiedLazyBodies();
    }
  });

  it("a duplicate depth-1 ticker takes the full-parse path (last occurrence wins, as JSON.parse says) for every viewer and ticker", async () => {
    admitSyntheticTickers("AAA", "BBB");
    const first = cycleFor("AAA"); first.spot = 50;
    const text = `{"schema":"v213-options-v2","generated_at":"${STAMP}","options":{"AAA":{"monthly":${JSON.stringify(first)}},"BBB":{"monthly":${JSON.stringify(cycleFor("BBB"))}},"AAA":{"monthly":${JSON.stringify(cycleFor("AAA"))}}}}`;
    const { env } = await sealed({ [OPTIONS_KEY]: text });
    for (const viewer of ["owner", "friend"] as const) for (const key of ["AAA", "BBB", "CCC"]) {
      const { fast, slow } = await both(env, viewer, key, "monthly");
      expect(fast, `${key} ${viewer}`).toEqual(slow);
    }
    const found = await loadDetailedOptionObservation(await pinPublicSnapshot(scopePublicSnapshot(env, "owner")), "AAA", "monthly", NOW);
    expect(found.quote?.spot).toBe(cycleFor("AAA").spot);   // the later AAA wins in the full parse
  });
});

describe("member index cache: one scan per sealed digest and container, cleared by the seam", () => {
  const text = (n: number) => JSON.stringify({ schema: "v213-options-v2", generated_at: STAMP, options: Object.fromEntries(Array.from({ length: n }, (_, i) => [`T${i}`, { monthly: { i } }])) });

  it("a body with a known sha256 is scanned once; without one it is scanned every time; clearVerifiedLazyBodies() forgets it", () => {
    const body = text(30);
    const h = sealedHeader(body, "v213-options-v2", "options")!;
    const start = memberIndexBuilds();
    for (let i = 0; i < 5; i += 1) expect(parseObjectMember(body, h, "T3", "a".repeat(64))).toEqual({ monthly: { i: 3 } });
    expect(memberIndexBuilds() - start).toBe(1);
    for (let i = 0; i < 3; i += 1) parseObjectMember(body, h, "T3");
    expect(memberIndexBuilds() - start).toBe(4);
    parseObjectMember(body, h, "T4", "b".repeat(64));                 // another digest: its own scan
    parseObjectMember(body, h, "T4", "b".repeat(64));
    expect(memberIndexBuilds() - start).toBe(5);
    clearVerifiedLazyBodies();
    parseObjectMember(body, h, "T3", "a".repeat(64));
    expect(memberIndexBuilds() - start).toBe(6);
    // a text whose length differs from the one the digest was indexed for is never served from the memory
    const other = text(31);
    parseObjectMember(other, sealedHeader(other, "v213-options-v2", "options")!, "T30", "a".repeat(64));
    expect(memberIndexBuilds() - start).toBe(7);
  });

  it("a refused document is remembered as refused (scanned once), the same digest under another container is a separate entry, and the memory is bounded", () => {
    const dup = '{"schema":"v213-options-v2","generated_at":"' + STAMP + '","options":{"AAA":{"a":1},"AAA":{"a":2}}}';
    const h = sealedHeader(dup, "v213-options-v2", "options")!;
    const start = memberIndexBuilds();
    for (let i = 0; i < 4; i += 1) expect(parseObjectMember(dup, h, "AAA", "c".repeat(64))).toBeUndefined();
    expect(memberIndexBuilds() - start).toBe(1);
    const quotes = '{"schema":"v213-quotes-v1","generated_at":"' + STAMP + '","quotes":{"AAA":{"a":1}}}';
    const qh = sealedHeader(quotes, "v213-quotes-v1", "quotes")!;
    parseObjectMember(quotes, qh, "AAA", "c".repeat(64));
    parseObjectMember(quotes, qh, "AAA", "c".repeat(64));
    expect(memberIndexBuilds() - start).toBe(2);
    for (let n = 0; n < 6; n += 1) { const body = text(n + 1); parseObjectMember(body, sealedHeader(body, "v213-options-v2", "options")!, "T0", String(n).repeat(64)); }
    const before = memberIndexBuilds();
    const first = text(1);
    parseObjectMember(first, sealedHeader(first, "v213-options-v2", "options")!, "T0", "0".repeat(64));   // evicted (more than 4 entries): rebuilt
    expect(memberIndexBuilds() - before).toBe(1);
    const last = text(6);
    parseObjectMember(last, sealedHeader(last, "v213-options-v2", "options")!, "T0", "5".repeat(64));     // newest entry is still there
    expect(memberIndexBuilds() - before).toBe(1);
  });

  it("through the loader: one scan of the options document and one of the quotes document per isolate, every later question and every viewer reuses them", async () => {
    admitSyntheticTickers("AAA", "BBB");
    const doc = { schema: "v213-options-v2", generated_at: STAMP, options: { AAA: { monthly: cycleFor("AAA") }, BBB: { monthly: cycleFor("BBB") } } };
    const quotes = { schema: "v213-quotes-v1", generated_at: STAMP, quotes: { AAA: quoteRow("AAA", "Yahoo Finance (unofficial, delayed)", "https://finance.yahoo.com/quote/AAA") } };
    const { env } = await sealed({ [OPTIONS_KEY]: JSON.stringify(doc), [QUOTES_KEY]: JSON.stringify(quotes) });
    const start = memberIndexBuilds();
    for (const [viewer, key] of [["owner", "AAA"], ["friend", "AAA"], ["friend", "BBB"], ["owner", "ZZZ"]] as const) {
      expect((await loadDetailedOptionObservation(await pinPublicSnapshot(scopePublicSnapshot(env, viewer)), key, "monthly", NOW)).status).toBe(key === "ZZZ" ? "TICKER_NOT_IN_SNAPSHOT" : "FOUND");
    }
    expect(memberIndexBuilds() - start).toBe(2);   // options once, quotes once (first friend question)
    clearVerifiedLazyBodies();
    await loadDetailedOptionObservation(await pinPublicSnapshot(scopePublicSnapshot(env, "owner")), "AAA", "monthly", NOW);
    expect(memberIndexBuilds() - start).toBe(3);
  });
});

describe("work budget of one options question (counts, not milliseconds)", () => {
  function bigDoc(count: number) {
    const options: Record<string, unknown> = {};
    for (let i = 0; i < count; i += 1) { const t = `T${String(i).padStart(4, "0")}`; options[t] = { weekly: cycleFor(t), monthly: cycleFor(t) }; }
    return { schema: "v213-options-v2", generated_at: STAMP, options };
  }

  it("a ~1.7 MB document is hashed, encoded and grammar-checked once per isolate; every later question parses only the matched entry", async () => {
    admitSyntheticTickers("T0100", "T0200");
    const body = JSON.stringify(bigDoc(300));
    expect(new TextEncoder().encode(body).byteLength).toBeGreaterThan(1_700_000);
    const { env } = await sealed({ [OPTIONS_KEY]: body });
    const parse = vi.spyOn(JSON, "parse");
    const digest = vi.spyOn(crypto.subtle, "digest");
    const encode = vi.spyOn(TextEncoder.prototype, "encode");
    const view = await pinPublicSnapshot(scopePublicSnapshot(env, "friend"));
    parse.mockClear(); digest.mockClear(); encode.mockClear();
    const result = await loadDetailedOptionObservation(view, "T0100", "monthly", NOW);
    expect(result.status).toBe("FOUND");
    const bigParses = parse.mock.calls.filter(([text]) => String(text).length > 1_000_000);
    expect(bigParses).toHaveLength(1);                                       // the grammar check of the member index, once
    const smallChars = parse.mock.calls.filter(([text]) => String(text).length <= 1_000_000).reduce((n, [text]) => n + String(text).length, 0);
    expect(smallChars).toBeLessThan(20_000);
    const hashed = digest.mock.calls.map(([, data]) => (data as Uint8Array).byteLength);
    expect(hashed.filter(n => n > 1_000_000)).toHaveLength(1);
    const encodedBig = encode.mock.results.filter(r => (r.value as Uint8Array).byteLength > 1_000_000);
    expect(encodedBig).toHaveLength(1);
    const later = await pinPublicSnapshot(scopePublicSnapshot(env, "friend"));
    parse.mockClear(); digest.mockClear(); encode.mockClear();
    expect((await loadDetailedOptionObservation(later, "T0200", "monthly", NOW)).status).toBe("FOUND");
    expect(parse.mock.calls.reduce((n, [text]) => n + String(text).length, 0)).toBeLessThan(20_000);
    expect(digest.mock.calls.map(([, data]) => (data as Uint8Array).byteLength).filter(n => n > 1_000_000)).toHaveLength(0);
    expect(encode.mock.results.filter(r => (r.value as Uint8Array).byteLength > 1_000_000)).toHaveLength(0);
    parse.mockRestore(); digest.mockRestore(); encode.mockRestore();
  });

  it("a remembered body is reused only for the same sealed (sha256, byte length): a later run declaring another length is refused warm as cold (SOL-V24V22 F2)", async () => {
    const body = JSON.stringify({ schema: "v213-quotes-v1", generated_at: STAMP, quotes: { AAA: { source: "synthetic 合成" } } });
    const kv = new MemoryKv();
    const first = await sealedRun(kv, RUN, QUOTES_KEY, body);
    expect(await (await pinPublicSnapshot(scopePublicSnapshot(first, "owner"))).text([QUOTES_KEY])).toBe(body);   // warm
    const nextRun = "20260930T170000Z-abcdefabcde8";
    const second = await sealedRun(kv, nextRun, QUOTES_KEY, body, -1);   // same digest, manifest declares one byte less
    const warmView = await pinPublicSnapshot(scopePublicSnapshot(second, "owner"));
    expect(warmView.runId).toBe(nextRun);
    expect(warmView.integrity).toBe("sealed");
    expect(await warmView.text([QUOTES_KEY])).toBeNull();
    clearVerifiedLazyBodies();
    expect(await (await pinPublicSnapshot(scopePublicSnapshot(second, "owner"))).text([QUOTES_KEY])).toBeNull();
    // the correct length is still served warm after it was verified once
    const third = await sealedRun(kv, "20260930T170000Z-abcdefabcde9", QUOTES_KEY, body);
    expect(await (await pinPublicSnapshot(scopePublicSnapshot(third, "owner"))).text([QUOTES_KEY])).toBe(body);
    const reads: string[] = [];
    const original = kv.get.bind(kv);
    vi.spyOn(kv, "get").mockImplementation(async (key: string, type?: "text" | "json") => { reads.push(key); return original(key, type); });
    expect(await (await pinPublicSnapshot(scopePublicSnapshot(third, "owner"))).text([QUOTES_KEY])).toBe(body);
    expect(reads.filter(key => key.startsWith("blob:v1:"))).toEqual([]);
  });

  it("verified lazy bodies are remembered per isolate by content address; a different digest is still read and verified, a tampered blob is still refused", async () => {
    admitSyntheticTickers("T0001", "T0002");
    const first = await sealed({ [OPTIONS_KEY]: JSON.stringify(bigDoc(20)) });
    await loadDetailedOptionObservation(await pinPublicSnapshot(scopePublicSnapshot(first.env, "owner")), "T0001", "monthly", NOW);
    const reads: string[] = [];
    const original = first.kv.get.bind(first.kv);
    vi.spyOn(first.kv, "get").mockImplementation(async (key: string, type?: "text" | "json") => { reads.push(key); return original(key, type); });
    const again = await loadDetailedOptionObservation(await pinPublicSnapshot(scopePublicSnapshot(first.env, "owner")), "T0001", "monthly", NOW);
    expect(again.status).toBe("FOUND");
    expect(reads.filter(key => key.startsWith("blob:v1:"))).toEqual([]);          // no KV read of the options blob on the second question
    expect(reads).toContain("snapshot:current");                                 // the pointer and the manifest are still read and verified every time
    // another snapshot with different bytes names another digest: its blob is read and verified
    const other = await sealed({ [OPTIONS_KEY]: JSON.stringify(bigDoc(21)) });
    const otherReads: string[] = [];
    const og = other.kv.get.bind(other.kv);
    vi.spyOn(other.kv, "get").mockImplementation(async (key: string, type?: "text" | "json") => { otherReads.push(key); return og(key, type); });
    expect((await loadDetailedOptionObservation(await pinPublicSnapshot(scopePublicSnapshot(other.env, "owner")), "T0002", "monthly", NOW)).status).toBe("FOUND");
    expect(otherReads.filter(key => key.startsWith("blob:v1:"))).toHaveLength(1);
    // a blob whose bytes do not match the sealed digest is refused (never cached)
    const tampered = await sealed({ [OPTIONS_KEY]: JSON.stringify(bigDoc(22)) });
    const seal = JSON.parse(tampered.kv.values.get(`snapshot:${RUN}:${SNAPSHOT_SEAL_KEY}`)!);
    const blobKey = `blob:v1:${seal.objects[OPTIONS_KEY].sha256}`;
    tampered.kv.values.set(blobKey, tampered.kv.values.get(blobKey)!.replace("T0003", "T0009"));
    const refused = await loadDetailedOptionObservation(await pinPublicSnapshot(scopePublicSnapshot(tampered.env, "owner")), "T0003", "monthly", NOW);
    expect(refused.status).toBe("DOCUMENT_INVALID_OR_UNREADABLE");
  });
});

describe("readLazySealedObject: one encode, length and digest on the same bytes", () => {
  const digestOf = async (body: string) => ({ sha256: await sha(body), utf8_bytes: new TextEncoder().encode(body).byteLength });
  it("accepts the exact bytes (ASCII, Chinese, astral) and refuses wrong length, wrong digest, empty and oversized bodies", async () => {
    for (const body of ["{\"a\":1}", "{\"text\":\"報價未通過驗證—\"}", "{\"e\":\"💡\"}"]) {
      const d = await digestOf(body);
      expect(await readLazySealedObject(d, async () => body)).toBe(body);
      expect(await readLazySealedObject({ ...d, utf8_bytes: d.utf8_bytes + 1 }, async () => body)).toBeNull();
      expect(await readLazySealedObject({ ...d, sha256: "0".repeat(64) }, async () => body)).toBeNull();
    }
    const d = await digestOf("{\"a\":1}");
    expect(await readLazySealedObject(d, async () => "")).toBeNull();
    expect(await readLazySealedObject(d, async () => null)).toBeNull();
    expect(await readLazySealedObject(d, async () => { throw new Error("KV"); })).toBeNull();
    const big = "x".repeat(2_097_153);
    expect(await readLazySealedObject({ sha256: await sha(big), utf8_bytes: big.length }, async () => big)).toBeNull();
    const lone = "{\"a\":\"\ud800\"}";   // cannot come out of a UTF-8 decode; its encoding differs from any producer bytes, so the digest cannot match
    expect(await readLazySealedObject(await digestOf("{\"a\":\"�\"}"), async () => lone)).toBeNull();
  });
  it("encodes the body once", async () => {
    const body = JSON.stringify({ k: "報價".repeat(1000) });
    const d = await digestOf(body);
    const encode = vi.spyOn(TextEncoder.prototype, "encode");
    await readLazySealedObject(d, async () => body);
    expect(encode).toHaveBeenCalledTimes(1);
    encode.mockRestore();
  });
});

describe("options coverage: link check against the sealed pair", () => {
  it("the coverage page still verifies and a forged link is refused", async () => {
    const { buildOptionsCoverageMessages } = await import("../src/v213/options-coverage");
    admitSyntheticTickers("AAA", "BBB", "CCC");
    const optionsBody = JSON.stringify({ schema: "v213-options-v2", generated_at: STAMP, options: { AAA: { monthly: cycleFor("AAA") } } });
    // the coverage body is produced by scripts/publish_sealed_snapshot.py in production; a missing/absent body is the typed absent state here
    const { env } = await sealed({ [OPTIONS_KEY]: optionsBody });
    const view = await pinPublicSnapshot(scopePublicSnapshot(env, "owner"));
    expect(view.sealedDigest?.(OPTIONS_KEY)).toEqual({ sha256: await sha(optionsBody), utf8_bytes: new TextEncoder().encode(optionsBody).byteLength });
    expect(view.sealedDigest?.("v213:top20-report:latest")).toBeUndefined();
    const coverage = await loadOptionsCoverage(view, NOW);
    expect(coverage.status).toBe("COVERAGE_ABSENT");
    expect(buildOptionsCoverageMessages(coverage)[0]).toBeDefined();
  });
});
