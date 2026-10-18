// IDIV2: the US identity SEC-cache fallback card, pinned through the real renderer and through the real lookup caller.
// scripts/build_identity_shards.py writes the feed id `sec-company-tickers-exchange` when a Nasdaq Trader directory failed and the
// local SEC cache replaced both US feeds; the Worker then shows a conservative notice ONLY for an actual RESOLVED US record whose
// source_feed is exactly that id. Display only: no resolution, admission, quote, option button or rights change. Visible text is
// asserted as literals (nothing private is imported). Fake KV, no network, no send.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import fixture from "../../tests/fixtures/identity-batch04-functional.json";
import { parseQuery } from "../src/core";
import { assertLineMessages, type LineOutboundMessage } from "../src/line-messages";
import { buildGlobalEquityLookupMessages, handleGlobalEquityLookup, type EquityLookupResult, type GlobalIdentityRecord } from "../src/v213/global-equity-lookup";
import { asKv, MemoryKv } from "./fake-kv";

const FEED = "sec-company-tickers-exchange";
const SEC_URL = "https://www.sec.gov/files/company_tickers_exchange.json";
const NOTICE = "身分備援：SEC 本機快取僅部分涵蓋 Nasdaq／NYSE；掛牌狀態與證券類別未經交易所名錄核實。檔案時間不等於已驗證取得時間；若顯示期權按鈕，僅供查詢，不代表期權資格或可成交。";
const QUOTE_DISCLAIMER = "公開研究資訊，非投資建議；身分採 SEC 公司代號名錄之本機快取備援（部分涵蓋，未經交易所名錄核實），報價為延遲觀察值，不下單。";
const NO_QUOTE_DISCLAIMER = "公開研究資訊，非投資建議；身分採 SEC 公司代號名錄之本機快取備援（部分涵蓋，未經交易所名錄核實），本標的暫無延遲報價觀察。";
const UNAVAILABLE_SUB = "IDENTITY_FALLBACK_SEC_CACHE：本筆採 SEC 公司代號名錄之本機快取備援；部分涵蓋，非即時交易所核實；暫無已封存延遲報價。";
const NAME_ZH = "未有已核對中文名稱（SEC 快取備援，不猜譯）";
const ORDINARY_QUOTE_DISCLAIMER = "公開研究資訊，非投資建議；身分來自官方上市目錄，報價為延遲觀察值，不下單。";
const ORDINARY_NO_QUOTE_DISCLAIMER = "公開研究資訊，非投資建議；官方上市身分已核對，本標的暫無延遲報價觀察。";
const FALLBACK_PHRASES = ["備援身分（SEC 快取）", "身分備援：SEC 本機快取", "IDENTITY_FALLBACK_SEC_CACHE", "SEC 標示", "SEC 公司代號名錄之本機快取備援", "SEC 快取備援，不猜譯"];

function record(overrides: Partial<GlobalIdentityRecord> = {}): GlobalIdentityRecord {
  return { venue: "NASDAQ", market: "US", country: "United States", symbol: "SECA", native_symbol: "SECA", security_name: "Sec Cache Orbit",
    native_name: null, name_zh: null, name_zh_source: null, security_class: "REVIEW_REQUIRED", currency: "USD", source_feed: FEED, source_url: SEC_URL, ...overrides };
}

function lookup(rec: GlobalIdentityRecord, options: { quote?: boolean; source?: string; resolution?: EquityLookupResult["resolution"] } = {}): EquityLookupResult {
  const quote = options.quote ?? true;
  return {
    identity: { rawInput: rec.symbol, normalizedSymbol: rec.symbol, canonicalSymbol: rec.symbol, market: rec.market, country: rec.country,
      exchange: `${rec.venue}（${rec.country}）`, currency: rec.currency, canonicalNameEn: rec.security_name, isAmbiguous: false, leadingZeroPreserved: false },
    admittedInSealedSnapshot: true, nameUnverified: true, quoteStatus: quote ? "AVAILABLE" : "UNAVAILABLE",
    ...(quote ? { price: 12.34, changePct: 0.0123, asOf: "2026-09-15T11:50:00Z", priceSource: "Nasdaq（延遲）" } : {}),
    source: options.source ?? `sealed_snapshot:${rec.source_feed}`,
    disclaimer: quote ? ORDINARY_QUOTE_DISCLAIMER : ORDINARY_NO_QUOTE_DISCLAIMER,
    resolution: options.resolution ?? { status: "RESOLVED", query: rec.symbol, candidateCount: 1, record: rec },
  };
}

type Out = { text: string; raw: string; messages: LineOutboundMessage[] };
function render(result: EquityLookupResult, style: "text" | "flex"): Out {
  const messages = buildGlobalEquityLookupMessages(result, style);
  assertLineMessages(messages);
  const text = (messages as { type: string; text?: string }[]).map(message => message.text ?? "").join("\n");
  return { messages, text, raw: JSON.stringify(messages) };
}
/** The visible text of a message list, whichever the style (text bodies, Flex JSON including the alt text). */
const visible = (out: Out) => `${out.text}\n${out.raw}`;
function expectNoFallback(out: Out, label: string): void {
  for (const phrase of FALLBACK_PHRASES) expect(visible(out), `${label}: ${phrase}`).not.toContain(phrase);
}

describe("IDIV2 renderer: the SEC-cache fallback card", () => {
  it("a RESOLVED US record from the SEC feed with a quote shows the fallback title, notice, SEC-stated market and disclaimer", () => {
    for (const style of ["text", "flex"] as const) {
      const out = render(lookup(record()), style);
      const all = visible(out);
      expect(all, style).toContain("備援身分（SEC 快取） · 延遲報價");
      expect(all, style).toContain(NOTICE);
      expect(all, style).toContain(QUOTE_DISCLAIMER);
      expect(all, style).toContain(NAME_ZH);
      expect(all, style).toContain("價格 12.34 USD（+1.23%）");
      expect(all, style).not.toContain("已准入證券身分");
      expect(all, style).not.toContain("身分來自官方上市目錄");  // the ordinary verified-identity wording is replaced, not appended
      if (style === "text") {
        expect(out.text).toContain("市場／交易所（SEC 標示）：NASDAQ（United States）");
        expect(out.text).toContain("【個股快查 · SECA｜備援身分（SEC 快取） · 延遲報價】");
      } else {
        expect(out.raw).toContain("市場（SEC 標示）：NASDAQ（United States）");
        expect(out.raw).toContain('"altText":"個股快查 · SECA｜備援身分（SEC 快取） · 延遲報價"');
        expect(out.raw).toContain('"label":"每月期權"');  // the option buttons are unchanged navigation, not an option qualification
        expect(out.raw).toContain('"label":"每週期權"');
      }
    }
  });

  it("a RESOLVED US record from the SEC feed without a quote shows the unavailable-quote fallback card and the no-quote disclaimer", () => {
    for (const style of ["text", "flex"] as const) {
      const out = render(lookup(record(), { quote: false }), style);
      const all = visible(out);
      expect(all, style).toContain("備援身分（SEC 快取） · 報價未開放");
      expect(all, style).toContain(UNAVAILABLE_SUB);
      expect(all, style).toContain(NOTICE);
      expect(all, style).toContain(NO_QUOTE_DISCLAIMER);
      expect(all, style).toContain(NAME_ZH);
      expect(all, style).not.toContain("官方上市證券身分已核對");
      expect(all, style).not.toContain(ORDINARY_NO_QUOTE_DISCLAIMER);  // the ordinary no-quote sentence is replaced (the fallback one differs in its lead)
      expect(all, style).not.toContain("官方上市身分已核對");
      if (style === "flex") expect(out.raw).not.toContain('"label":"每月期權"');
    }
  });

  it("an independently sourced Chinese name keeps its own source label on the fallback card", () => {
    const out = render(lookup(record({ name_zh: "合成軌道", name_zh_source: "ZHWIKI" })), "text");
    const named = lookup(record({ name_zh: "合成軌道", name_zh_source: "ZHWIKI" }));
    named.nameUnverified = false;
    named.identity.canonicalNameZh = "合成軌道";
    named.identity.nameZhSource = "ZHWIKI";
    const text = render(named, "text").text;
    expect(text).toContain("中文名稱：合成軌道（中文維基百科）");
    expect(text).toContain("備援身分（SEC 快取）");
    expect(out.text).toContain(NAME_ZH);  // without the verified-name flag the honest fallback sentence stays
  });

  it("every near-miss is an ordinary card: another US feed, a case variant, a prefix, a suffix, another market, a non-RESOLVED status", () => {
    const ordinaryQuote = (out: Out, label: string) => {
      expectNoFallback(out, label);
      expect(visible(out), label).toContain("已准入證券身分 · 延遲報價");
      expect(visible(out), label).toContain("身分來自官方上市目錄");
    };
    const near: [string, GlobalIdentityRecord][] = [
      ["nasdaq-listed", record({ source_feed: "nasdaq-listed" })],
      ["other-us-listed", record({ source_feed: "other-us-listed" })],
      ["case variant", record({ source_feed: "SEC-company-tickers-exchange" })],
      ["upper case", record({ source_feed: FEED.toUpperCase() })],
      ["prefix", record({ source_feed: `${FEED}-x` })],
      ["suffix padding", record({ source_feed: `x${FEED}` })],
      ["trailing space", record({ source_feed: `${FEED} ` })],
      ["empty feed", record({ source_feed: "" })],
    ];
    for (const [label, rec] of near) for (const style of ["text", "flex"] as const) ordinaryQuote(render(lookup(rec), style), `${label}/${style}`);
    // the exact feed on a non-US market is not the US fallback
    for (const market of ["UK", "SWEDEN", "TAIWAN", "JAPAN", "KOREA", "HK", "EUROPE"] as const) {
      const rec = record({ market, venue: "SYNTH VENUE", country: "Synthland", currency: "USD" });
      for (const style of ["text", "flex"] as const) expectNoFallback(render(lookup(rec), style), `${market}/${style}`);
    }
  });

  it("the same feed id in another place never switches the card: result.source text, NEEDS_MARKET_SELECTION, UNAVAILABLE, INVALID_REQUEST", () => {
    const other = record({ source_feed: "nasdaq-listed" });
    for (const style of ["text", "flex"] as const) {
      expectNoFallback(render(lookup(other, { source: `sealed_snapshot:${FEED}；報價：${FEED}` }), style), `source text/${style}`);
      const sec = record();
      const ambiguous: EquityLookupResult = {
        identity: { rawInput: "SECA", normalizedSymbol: "SECA", canonicalSymbol: "SECA", market: "UNKNOWN", country: "多市場候選", exchange: "多個掛牌市場",
          currency: "UNAVAILABLE", isAmbiguous: true, ambiguityCandidates: ["SECA (NASDAQ, United States) - Sec Cache Orbit", "SECA (LSE, United Kingdom) - Other"], leadingZeroPreserved: false },
        admittedInSealedSnapshot: true, nameUnverified: true, quoteStatus: "AMBIGUOUS", source: `sealed_snapshot:${FEED}`,
        disclaimer: "公開研究資訊，非投資建議；請選擇精確市場或輸入含後綴代號。",
        resolution: { status: "NEEDS_MARKET_SELECTION", query: "SECA", candidates: [sec, record({ market: "UK", venue: "LSE", country: "United Kingdom", source_feed: FEED })] },
      };
      const selection = render(ambiguous, style);
      expectNoFallback(selection, `ambiguous/${style}`);
      expect(visible(selection)).toContain("多市場代號重疊");
      for (const resolution of [
        { status: "UNAVAILABLE" as const, query: "SECA", reason: `IDENTITY_NOT_FOUND ${FEED}` },
        { status: "INVALID_REQUEST" as const, query: "SECA", reason: `INVALID ${FEED}` },
      ]) {
        const unavailable = lookup(sec, { quote: false, resolution });
        unavailable.admittedInSealedSnapshot = false;
        expectNoFallback(render(unavailable, style), `${resolution.status}/${style}`);
      }
    }
  });

  it("a card with no resolution at all (a direct or legacy caller) never shows the fallback", () => {
    const direct = lookup(record());
    delete direct.resolution;
    for (const style of ["text", "flex"] as const) expectNoFallback(render(direct, style), `no resolution/${style}`);
  });
});

// --- the real caller on the BATCH04 sealed fixture ---
const SEAL = `snapshot:${fixture.run}:v213:snapshot-seal:v1`;
const SYM = "v213:identity:v2:sym:";
const sha = async (body: string) => Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(body))),
  n => n.toString(16).padStart(2, "0")).join("");

async function environment(style: "text" | "flex", replacements: Record<string, unknown> = {}) {
  const kv = new MemoryKv();
  for (const [key, body] of Object.entries(fixture.values)) kv.values.set(key, body);
  const seal = JSON.parse(kv.values.get(SEAL)!);
  for (const [logical, value] of Object.entries(replacements)) {
    const body = JSON.stringify(value), digest = await sha(body);
    seal.objects[logical] = { sha256: digest, utf8_bytes: new TextEncoder().encode(body).length };
    kv.values.set("blob:v1:" + digest, body);
  }
  if (Object.keys(replacements).length) {
    const body = JSON.stringify(seal);
    kv.values.set(SEAL, body);
    const pointer = JSON.parse(kv.values.get("snapshot:current")!);
    pointer.seal_sha256 = await sha(body);
    kv.values.set("snapshot:current", JSON.stringify(pointer));
  }
  return { PUBLIC_CACHE: asKv(kv), TENANT_PRIVATE_CACHE: asKv(new MemoryKv()), EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()),
    V213_LINE_PRESENTATION: style, V21_TOP20_MAX_AGE_SECONDS: "7200" };
}

/** The fixture's symbol shard with the feed of its rows renamed to `feedId` (rows, digests and layout untouched). */
function shardWithFeed(bucket: "G" | "S", feedId: string, url: string): Record<string, unknown> {
  const source = JSON.parse(JSON.stringify((fixture.document.symbol_shards as unknown as Record<string, any>)[bucket]));
  for (const row of source.rows) source.feeds[row[8]] = { ...source.feeds[row[8]], id: feedId, url };
  return source;
}

async function ask(style: "text" | "flex", query: string, replacements: Record<string, unknown> = {}): Promise<Out> {
  const env = await environment(style, replacements);
  const messages = await handleGlobalEquityLookup(env as never, parseQuery(query)) as LineOutboundMessage[];
  expect(Array.isArray(messages)).toBe(true);
  assertLineMessages(messages);
  const text = (messages as { type: string; text?: string }[]).map(message => message.text ?? "").join("\n");
  return { messages, text, raw: JSON.stringify(messages) };
}

describe("IDIV2 caller: handleGlobalEquityLookup on sealed bytes", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-09-15T12:01:00Z"));
    vi.stubGlobal("fetch", vi.fn(() => { throw new Error("IDIV2_NETWORK_FORBIDDEN"); }));
  });
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

  it("a single unambiguous US row of a sealed shard whose feed is the SEC cache resolves to the fallback card in text and Flex", async () => {
    const replacement = { [SYM + "G"]: shardWithFeed("G", FEED, SEC_URL) };
    for (const style of ["text", "flex"] as const) {
      const out = await ask(style, "GOOD", replacement);
      const all = visible(out);
      expect(all, style).toContain("Healthy Orbit");
      expect(all, style).toContain("備援身分（SEC 快取） · 報價未開放");  // the fixture seals no price shard or quote for GOOD
      expect(all, style).toContain(UNAVAILABLE_SUB);
      expect(all, style).toContain(NOTICE);
      expect(all, style).toContain(NAME_ZH);
      expect(all, style).toContain(NO_QUOTE_DISCLAIMER);
      expect(all, style).not.toContain("官方上市證券身分已核對");
      expect(all, style).not.toContain("IDENTITY_CONFLICT");
      expect(all, style).not.toContain("原因不明");
      if (style === "text") expect(out.text).toContain("市場／交易所（SEC 標示）：NASDAQ（United States）");
      else expect(out.raw).not.toContain('"label":"每月期權"');  // an unavailable quote has no option buttons, fallback or not
    }
  });

  it("the unchanged fixture (Nasdaq Trader feed) keeps the ordinary verified-identity card for the same symbol", async () => {
    for (const style of ["text", "flex"] as const) {
      const out = await ask(style, "GOOD");
      expect(visible(out), style).toContain("Healthy Orbit");
      expectNoFallback(out, style);
      expect(visible(out), style).toContain("官方上市證券身分已核對");
    }
  });

  it("the exact feed id on a non-US sealed row is not the fallback", async () => {
    const replacement = { [SYM + "S"]: shardWithFeed("S", FEED, SEC_URL) };
    for (const style of ["text", "flex"] as const) {
      const out = await ask(style, "SIVE.ST", replacement);
      expect(visible(out), style).toContain("Synthetic Orbit");
      expectNoFallback(out, style);
    }
  });

  it("a case variant and a prefix of the feed id in sealed bytes are ordinary cards", async () => {
    for (const feedId of ["SEC-company-tickers-exchange", `${FEED}-x`, "nasdaq-listed"]) {
      const out = await ask("text", "GOOD", { [SYM + "G"]: shardWithFeed("G", feedId, SEC_URL) });
      expect(out.text, feedId).toContain("Healthy Orbit");
      expectNoFallback(out, feedId);
    }
  });
});
