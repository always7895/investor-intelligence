// V11 W5: company-name lookup by the leading words of a Latin-script name ("Sivers" -> SIVE), through the real LINE entry.
// Sealed lazy shards with real record shapes (the SIVE, ALAB, MU, 6159, META, MTAW and 2330 rows are copied from a runtime run;
// the other listings are synthetic). Fake KV only, no network.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import fixture from "../../tests/fixtures/identity-batch04-functional.json";
import { parseQuery } from "../src/core";
import { assertLineMessages } from "../src/line-messages";
import { processAuthorizedLineEvent } from "../src/v211/worker";
import { handleGlobalEquityLookup } from "../src/v213/global-equity-lookup";
import { resolveGlobalIdentity } from "../src/v213/global-identity";
import {
  identityNameBucket, identitySymbolBucket, identityTokenBucket, identityTokenKey, leadingTokenQuery, loadIdentityCatalogForQuery, nameTokens,
} from "../src/v213/identity-shards";
import { freeRelayRequestEnv } from "../src/v213/production-worker";
import { clearVerifiedLazyBodies, pinPublicSnapshot } from "../src/v213/public-snapshot";
import { SNAPSHOT_LAZY_KEY_RE, SNAPSHOT_SEAL_KEY } from "../src/v213/snapshot-seal";
import { asKv, MemoryKv } from "./fake-kv";
import { sealUnboundReport } from "./sealed-report-migration";

// VECTORS-BEGIN: [input, words, tokenized name stored in the token shards ("" when the first word is not Latin), bucket]; the table is
// also read by tests/test_v11_name_tokens.py, which asserts it against scripts/build_identity_shards.py.
const VECTORS: [string, string[], string, number | null][] = [
  ["Sivers Semiconductors", ["sivers", "semiconductors"], "sivers semiconductors", 7],
  ["Astera Labs, Inc. - Common Stock", ["astera", "labs", "inc", "common", "stock"], "astera labs inc common stock", 3],
  ["MICRON MACHINERY CO.,LTD.", ["micron", "machinery", "co", "ltd"], "micron machinery co ltd", 7],
  ["Lowe's Companies, Inc.", ["lowe", "s", "companies", "inc"], "lowe s companies inc", 4],
  ["AT&T Inc.", ["at", "t", "inc"], "at t inc", 0],
  ["Soci\u00e9t\u00e9 G\u00e9n\u00e9rale", ["soci\u00e9t\u00e9", "g\u00e9n\u00e9rale"], "soci\u00e9t\u00e9 g\u00e9n\u00e9rale", 1],
  ["\uff33\uff49\uff56\uff45\uff52\uff53\u3000\uff33\uff45\uff4d\uff49", ["sivers", "semi"], "sivers semi", 7],
  ["3M Company", ["3m", "company"], "3m company", 5],
  ["\u53f0\u7063\u7a4d\u9ad4\u96fb\u8def\u88fd\u9020\u80a1\u4efd\u6709\u9650\u516c\u53f8", ["\u53f0\u7063\u7a4d\u9ad4\u96fb\u8def\u88fd\u9020\u80a1\u4efd\u6709\u9650\u516c\u53f8"], "", null],
  ["Hennes & Mauritz AB", ["hennes", "mauritz", "ab"], "hennes mauritz ab", 2],
  ["\u0130stanbul Holding", ["i", "stanbul", "holding"], "i stanbul holding", 4],
  ["e.l.f. Beauty, Inc.", ["e", "l", "f", "beauty", "inc"], "e l f beauty inc", 0],
  ["Volvo B", ["volvo", "b"], "volvo b", 1],
  ["\u00dcn\u00efcode \u00d1ame S.A.", ["\u00fcn\u00efcode", "\u00f1ame", "s", "a"], "\u00fcn\u00efcode \u00f1ame s a", 5],
  ["\u03a3\u03af\u03b3\u03bc\u03b1 Corp", ["\u03c3\u03af\u03b3\u03bc\u03b1", "corp"], "", null],
  ["VOLV-B", ["volv", "b"], "volv b", 4],
  ["a_b c", ["a", "b", "c"], "a b c", 4],
  ["  Spaced   Out  ", ["spaced", "out"], "spaced out", 3],
  ["\ufb01rst Solar", ["first", "solar"], "first solar", 1],
  ["\uc0bc\uc131\uc804\uc790", ["\uc0bc\uc131\uc804\uc790"], "", null],
  ["Nokia Oyj", ["nokia", "oyj"], "nokia oyj", 5]
];
// VECTORS-END

const RUN = "20261013T141233Z-52fae128424c";
const GENERATED = "2026-10-13T04:14:46Z";
const feed = (id: string, url: string, sha256: string) => ({ id, url, retrieved_at: GENERATED, sha256, rows: 1 });
const FEEDS = [
  feed("nasdaq-listed", "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt", "234d5bcd216b19f6bb87a4cdd474e2fc0b4f9afbe3822ad24b6335652dfa5d9d"),
  feed("other-us-listed", "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt", "bf8bc4581835d225f997afcc8d412f07ae3416ee3c94a58c8bb0f1c074984fbc"),
  feed("twse-listed", "https://openapi.twse.com.tw/v1/opendata/t187ap03_L", "8fe3ad48ac759c6c4680d5ee5e909ad2e65bdd6501c93c23678738e01dbc6245"),
  feed("tpex-listed", "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O", "2a88c98473730bb43bb2f109008c2eadf35b0e96df8e8eefd7256fd78eedb5f8"),
  feed("nasdaq-stockholm-main", "https://api.nasdaq.com/api/nordic/screener/shares?category=MAIN_MARKET&tableonly=false&market=STO", "ec474bfb7f9b6085285759d1c2b4d7f98714d1920f68153a124e0e9d37967fe4"),
  feed("nasdaq-stockholm-first-north", "https://api.nasdaq.com/api/nordic/screener/shares?category=FIRST_NORTH&tableonly=false&market=STO", "348a24212496c34e4c5aac8691cad1773d31acd288eb19f8256e492bda7ba435"),
  feed("jpx-listed", "https://www.jpx.co.jp/english/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_e.xlsx", "7b0a3caa9af8255e0591c4eeabad7a0e9054dcfc16ed2922f0c2bef33d6467af"),
];

type Row = readonly unknown[];
const us = (symbol: string, name: string, venue = "NASDAQ", securityClass = "COMMON_STOCK", feedIndex = 0): Row =>
  [symbol, venue, "US", "United States", name, null, securityClass, "USD", feedIndex, null];
const GLOBALS = ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf"].map((word, index) => us(`GLB${"ABCDEFG"[index]}`, `Global ${word} Inc`, "NYSE", "COMMON_STOCK", 1));
const ROWS: readonly Row[] = [
  ["SIVE", "NASDAQ STOCKHOLM", "SWEDEN", "Sweden", "Sivers Semiconductors", null, "COMMON_STOCK", "SEK", 4, null],
  us("ALAB", "Astera Labs, Inc. - Common Stock"),
  us("MU", "Micron Technology, Inc. - Common Stock"),
  ["6159", "TSE", "JAPAN", "Japan", "MICRON MACHINERY CO.,LTD.", null, "COMMON_STOCK", "JPY", 6, null],
  us("META", "Meta Platforms, Inc. - Class A Common Stock"),
  us("MTAW", "Meta AI Lab Ecosystem ETF", "NYSE Arca", "ETF", 1),
  ["2330", "TWSE", "TAIWAN", "Taiwan", "台灣積體電路製造股份有限公司", "台積電", "COMMON_STOCK", "TWD", 2, ["台積電", "TWSE"]],
  ["NVDA", "NASDAQ", "US", "United States", "NVIDIA Corporation - Common Stock", null, "COMMON_STOCK", "USD", 0, ["輝達", "ZHWIKI"]],
  us("ABCH", "Abc Holdings Ltd - Ordinary Shares"),
  us("ACMC", "Acme Corp", "NYSE"), us("ACMH", "Acme Corp Holdings", "NYSE"),
  us("CNFL", "Conflict Corp"), us("CNFL", "Conflict Corporation Ltd"),  // contradictory variants of one listing
  ...GLOBALS,
];

const normalizeName = (name: string) => name.trim().toLowerCase().replace(/\s+/g, " ");
const symbolBucketOf = (row: Row) => identitySymbolBucket(String(row[0]));
type Shards = Record<string, unknown>;

function symbolShards(): Shards {
  const out: Shards = {};
  for (const row of ROWS) {
    const bucket = symbolBucketOf(row);
    const shard = (out[`v213:identity:v2:sym:${bucket}`] ??= { schema: "v213-identity-shard-v2", kind: "symbol", bucket, generated_at: GENERATED, feeds: FEEDS, rows: [] }) as { rows: unknown[] };
    shard.rows.push([...row]);
  }
  return out;
}

/** Today's v2 exact-name shards, built like scripts/build_identity_shards.py (security name, native name, sourced Chinese name). */
function nameShards(): Shards {
  const out: Shards = {};
  for (const row of ROWS) {
    const zh = row[9] as readonly string[] | null;
    for (const name of new Set([row[4], row[5], zh?.[0]].filter(Boolean).map(value => normalizeName(String(value))))) {
      const bucket = identityNameBucket(name);
      const shard = (out[`v213:identity:v2:name:${bucket}`] ??= { schema: "v213-identity-shard-v2", kind: "name", bucket: String(bucket), generated_at: GENERATED, rows: [] }) as { rows: unknown[] };
      if (!shard.rows.some(existing => JSON.stringify(existing) === JSON.stringify([name, symbolBucketOf(row), row[0], row[1]]))) shard.rows.push([name, symbolBucketOf(row), row[0], row[1]]);
    }
  }
  return out;
}

/** The token shards of scripts/build_identity_shards.py (build_token_shards): tokenized security and native names whose first word is Latin. */
function tokenShards(): Shards {
  const out: Shards = {};
  for (const row of ROWS) {
    for (const value of new Set([row[4], row[5]].filter(Boolean).map(String))) {
      const words = nameTokens(value);
      if (words.length === 0 || !/^[\p{Script=Latin}\p{N}]+$/u.test(words[0]!)) continue;
      const bucket = identityTokenBucket(words[0]!);
      const shard = (out[identityTokenKey(bucket)] ??= { schema: "v213-identity-shard-v2", kind: "token", bucket: String(bucket), generated_at: GENERATED, rows: [] }) as { rows: string[][] };
      const entry = [words.join(" "), symbolBucketOf(row), String(row[0]), String(row[1])];
      if (!shard.rows.some(existing => existing.join("|") === entry.join("|"))) shard.rows.push(entry);
    }
  }
  for (const shard of Object.values(out) as { rows: string[][] }[]) shard.rows.sort((a, b) => (a.join("\u0000") < b.join("\u0000") ? -1 : 1));
  return out;
}

async function sha(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
}

interface Sealed { env: Record<string, unknown>; kv: MemoryKv; digests: Map<string, string>; }
interface SealOptions { tokens?: boolean; edit?: (objects: Shards) => void; tamper?: string; dropBlobOf?: string; }

/** A sealed run whose manifest lists the identity shards as lazy objects stored under blob:v1:<sha256>. */
async function sealed(options: SealOptions = {}): Promise<Sealed> {
  clearVerifiedLazyBodies();  // each sealed() call is a new snapshot whose blobs may be dropped or altered under the same digests
  const kv = new MemoryKv();
  const stamp = new Date(Date.now() - 60_000).toISOString().replace(/\.\d{3}Z$/, "Z");
  kv.values.set("v213:top20-report:latest", JSON.stringify({ synthetic: "report" }));
  kv.values.set("last_successful_pipeline_timestamp", stamp);
  await sealUnboundReport(kv, RUN);
  const sealKey = `snapshot:${RUN}:${SNAPSHOT_SEAL_KEY}`;
  const seal = JSON.parse(kv.values.get(sealKey)!);
  const objects: Shards = { ...symbolShards(), ...nameShards(), ...(options.tokens === false ? {} : tokenShards()) };
  options.edit?.(objects);
  const digests = new Map<string, string>();
  for (const [key, value] of Object.entries(objects)) {
    const body = JSON.stringify(value);
    const digest = await sha(body);
    digests.set(key, digest);
    seal.objects[key] = { sha256: digest, utf8_bytes: new TextEncoder().encode(body).byteLength };
    kv.values.set(`blob:v1:${digest}`, key === options.tamper ? body.replace(/sivers/g, "sivars") : body);
  }
  if (options.dropBlobOf) kv.values.delete(`blob:v1:${digests.get(options.dropBlobOf)!}`);
  const sealText = JSON.stringify(seal);
  kv.values.set(sealKey, sealText);
  const pointer = JSON.parse(kv.values.get("snapshot:current")!);
  pointer.seal_sha256 = await sha(sealText);
  kv.values.set("snapshot:current", JSON.stringify(pointer));
  class NoPrivateReads extends MemoryKv {
    override async get<T = string>(): Promise<T | null> { throw new Error("PRIVATE_READ_FORBIDDEN"); }
  }
  return { kv, digests, env: { PUBLIC_CACHE: asKv(kv), TENANT_PRIVATE_CACHE: asKv(new NoPrivateReads()), EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()),
    LINE_CHANNEL_SECRET: "EXAMPLE_NOT_REAL", LINE_CHANNEL_ACCESS_TOKEN: "EXAMPLE_NOT_REAL", MEMORY_FEATURE_AVAILABLE: "false",
    CURRENT_PUBLIC_DATA_ENABLED: "true", PUBLIC_DATA_MAX_AGE_SECONDS: "7200", OPTION_DATA_MAX_AGE_SECONDS: "1800", V21_TOP20_MAX_AGE_SECONDS: "7200",
    V213_FIELD_LOCALE: "bilingual", V213_LINE_ACCESS_MODE: "owner_only", V213_COMPACT_QA_ENABLED: "true", V213_LINE_PRESENTATION: "text" } };
}

function strings(value: unknown): string[] {
  if (!value || typeof value !== "object") return [];
  if (Array.isArray(value)) return value.flatMap(strings);
  const obj = value as Record<string, unknown>;
  return [...(obj.type === "text" && typeof obj.text === "string" ? [obj.text] : []), ...Object.values(obj).flatMap(strings)];
}

/** The reply of the real LINE event entry (the same function the Worker's webhook calls) as one text, plus the raw messages. */
async function line(env: Record<string, unknown>, text: string, extra: Record<string, unknown> = {}): Promise<{ text: string; raw: string }> {
  let messages: unknown[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
    expect(url).toBe("https://api.line.me/v2/bot/message/reply");
    messages = JSON.parse(String(init.body)).messages;
    return new Response("{}", { status: 200 });
  }));
  await processAuthorizedLineEvent(await freeRelayRequestEnv({ ...env, ...extra } as never),
    { waitUntil() { throw new Error("MODEL_JOB_FORBIDDEN"); } } as unknown as ExecutionContext,
    { type: "message", replyToken: "SYNTHETIC_REPLY", timestamp: Date.now(), message: { id: "SYNTHETIC_MESSAGE", type: "text", text } } as never,
    "SYNTHETIC_TENANT");
  assertLineMessages(messages as never);
  expect(messages.length).toBeGreaterThan(0);
  return { text: strings(messages).join("\n"), raw: JSON.stringify(messages) };
}

const UNIQUE_NOTE = "名稱比對：輸入文字是封存名錄中唯一一家公司名稱的開頭字詞";
const MANY_NOTE = "名稱比對：輸入文字是多家公司名稱的開頭字詞";
const SIVERS_ABSENT = "IDENTIFIER_UNAVAILABLE: 代號「SIVERS」目前未在已封存公開身分目錄中";
const bullets = (text: string) => text.split("\n").filter(item => item.startsWith("• "));

afterEach(() => vi.unstubAllGlobals());

describe("V11 W5 name lookup through the real LINE entry", () => {
  it.each(["Sivers", "sivers", "SIVERS", "公司 Sivers", "Sivers Semiconductors"])("answers %s with the Sivers Semiconductors listing", async input => {
    const { env } = await sealed();
    const reply = await line(env, input);
    expect(reply.text).toContain("個股快查 · SIVE");
    expect(reply.text).toContain("已准入證券身分");
    expect(reply.text).toContain("公司名稱（原文）：Sivers Semiconductors");
    expect(reply.text).toContain("NASDAQ STOCKHOLM（Sweden）");
    expect(reply.text).not.toContain("IDENTIFIER_UNAVAILABLE");
    expect(reply.text).not.toContain("身分資料未封存");
    // A leading-word match says so; the exact name "Sivers Semiconductors" is today's path and adds nothing.
    if (input === "Sivers Semiconductors") expect(reply.text).not.toContain("名稱比對");
    else expect(reply.text).toContain(UNIQUE_NOTE);
  });

  it("finds a two-word name that no company marker or ticker shape routes (Astera Labs) and a leading word of a longer name", async () => {
    const { env } = await sealed();
    const alab = await line(env, "Astera Labs");
    expect(alab.text).toContain("個股快查 · ALAB");
    expect(alab.text).toContain("公司名稱（原文）：Astera Labs, Inc. - Common Stock");
    expect(alab.text).toContain(UNIQUE_NOTE);
    const abc = await line(env, "Abc Holdings");
    expect(abc.text).toContain("個股快查 · ABCH");
    expect(abc.text).toContain(UNIQUE_NOTE);
    const mu = await line(env, "Micron Technology");
    expect(mu.text).toContain("個股快查 · MU");
    expect(mu.text).toContain("公司名稱（原文）：Micron Technology, Inc. - Common Stock");
  });

  it("lists the candidates of an ambiguous leading word instead of guessing, with venue and symbol", async () => {
    const { env } = await sealed();
    const reply = await line(env, "Micron");
    expect(reply.text).toContain("多市場代號重疊 · 請確認市場");
    expect(reply.text).toContain(MANY_NOTE);
    expect(bullets(reply.text)).toHaveLength(2);
    expect(reply.text).toContain("MU (NASDAQ, United States) - Micron Technology, Inc. - Common Stock");
    expect(reply.text).toContain("6159 (TSE, Japan) - MICRON MACHINERY CO.,LTD.");
    expect(reply.text).toContain("可查詢「6159.T」");  // the existing safe selection still certifies a suffixed route
    expect(reply.text).not.toContain("已准入證券身分");
    expect(reply.text).not.toContain("已顯示");  // nothing is omitted
    const flex = await line(env, "Micron", { V213_LINE_PRESENTATION: "flex" });
    expect(flex.raw).toContain('"type":"flex"');
    expect(flex.text).toContain("6159 (TSE, Japan)");
  });

  it("shows at most five candidates and states the real number of matching listings", async () => {
    const { env } = await sealed();
    const reply = await line(env, "Global");
    expect(bullets(reply.text)).toHaveLength(5);
    for (const word of ["Alpha", "Bravo", "Charlie", "Delta", "Echo"]) expect(reply.text).toContain(`Global ${word} Inc`);
    for (const word of ["Foxtrot", "Golf"]) expect(reply.text).not.toContain(`Global ${word} Inc`);
    expect(reply.text).toContain("已顯示 5/7 筆候選");
    expect(reply.text).toContain(MANY_NOTE);
    expect(reply.text).toContain("GLBA (NYSE, United States)");
  });

  it("matches whole words only: a part of a word is not a leading word", async () => {
    const { env } = await sealed();
    for (const input of ["Siver", "Micro"]) {
      const reply = await line(env, input);
      expect(reply.text, input).toContain(`IDENTIFIER_UNAVAILABLE: 代號「${input.toUpperCase()}」`);
      expect(reply.text, input).not.toContain("公司名稱（原文）：Sivers");
      expect(reply.text, input).not.toContain("Micron");
    }
    const view = await pinPublicSnapshot(env as never);
    for (const input of ["Sivers S", "Sivers Semi", "Astera Lab", "Sivers Semiconductor"]) {
      expect((await loadIdentityCatalogForQuery(view, input, { leadingToken: true }))?.leading_token, input).toBeUndefined();
    }
  });

  it("refuses a token shorter than four letters", async () => {
    const { env } = await sealed();
    const short = await line(env, "Abc");
    expect(short.text).toContain("IDENTIFIER_UNAVAILABLE: 代號「ABC」");
    expect(short.text).not.toContain("ABCH");
    // The gate counts the letters of the whole input, so a longer input with a short first word still matches.
    expect((await line(env, "Abc Holdings")).text).toContain("ABCH");
  });

  it("keeps a symbol that is also a word: Meta is META, never a list of names that start with meta", async () => {
    const { env } = await sealed();
    for (const input of ["Meta", "META", "meta"]) {
      const reply = await line(env, input);
      expect(reply.text).toContain("個股快查 · META");
      expect(reply.text).toContain("Meta Platforms, Inc.");
      expect(reply.text).not.toContain("名稱比對");
      expect(reply.text).not.toContain("MTAW");
    }
  });

  it("keeps today's exact-name path first: a complete normalized name wins over longer names that start with it", async () => {
    const { env } = await sealed();
    const reply = await line(env, "Acme Corp");
    expect(reply.text).toContain("個股快查 · ACMC");
    expect(reply.text).not.toContain("名稱比對");
    expect(reply.text).not.toContain("ACMH");
    const longer = await line(env, "Acme");
    expect(longer.text).toContain("多市場代號重疊");  // the bare leading word is ambiguous between the two
    expect(longer.text).toContain("ACMC");
    expect(longer.text).toContain("ACMH");
  });

  it("keeps Chinese input on exact names: no prefix matching, today's answers unchanged", async () => {
    const { env } = await sealed();
    expect((await line(env, "台積電")).text).toContain("個股快查 · 2330");
    expect((await line(env, "輝達")).text).toContain("個股快查 · NVDA");
    expect((await line(env, "股票 台積")).text).not.toContain("個股快查 · 2330");  // a prefix of the Chinese name is not a name
    expect((await line(env, "公司 台灣積體")).text).not.toContain("個股快查 · 2330");
    expect((await line(env, "公司 台灣積體")).text).toContain("COMPANY_NAME_UNAVAILABLE");
    expect((await line(env, "2330")).text).toContain("個股快查 · 2330");
    expect((await line(env, "SIVE")).text).toContain("個股快查 · SIVE");
    expect((await line(env, "SIVE.ST")).text).toContain("代號：SIVE（輸入：SIVE.ST）");
  });

  it("does not let a leading word override an explicit ticker request or a suffixed query", async () => {
    const { env } = await sealed();
    const ticker = await line(env, "股票 Sivers");
    expect(ticker.text).not.toContain("Sivers Semiconductors");
    expect(ticker.text).toContain("IDENTIFIER_UNAVAILABLE");
    const suffixed = await line(env, "Sivers.ST");
    expect(suffixed.text).toContain("SOURCE_UNAVAILABLE");
    expect(suffixed.text).not.toContain("公司名稱（原文）：Sivers");
  });

  it("never resolves contradictory variants of a listing found by its leading word", async () => {
    const { env } = await sealed();
    const reply = await line(env, "Conflict");
    expect(reply.text).toContain("IDENTITY_CONFLICT");
    expect(reply.text).toContain("NASDAQ:CNFL");
    expect(reply.text).not.toContain("已准入證券身分");
  });
});

describe("V11 W5 reader compatibility and fail-closed behaviour", () => {
  it("a seal without token shards (made by today's producer) keeps exact-name behaviour only and never errors", async () => {
    const { env } = await sealed({ tokens: false });
    const reply = await line(env, "Sivers");
    expect(reply.text).toContain(SIVERS_ABSENT);
    expect(reply.text).not.toContain("SIVE（");
    expect((await line(env, "Micron")).text).toContain("IDENTIFIER_UNAVAILABLE");
    expect((await line(env, "Sivers Semiconductors")).text).toContain("個股快查 · SIVE");  // exact normalized name, today's path
    expect((await line(env, "SIVE")).text).toContain("個股快查 · SIVE");
    expect((await line(env, "台積電")).text).toContain("個股快查 · 2330");
    expect((await line(env, "Meta")).text).toContain("個股快查 · META");
  });

  const bucket = identityTokenBucket("sivers");
  const key = identityTokenKey(bucket);
  const malformed: [string, (shard: Record<string, unknown>) => unknown][] = [
    ["a different kind", shard => ({ ...shard, kind: "name" })],
    ["a different bucket", shard => ({ ...shard, bucket: String((bucket + 1) % 8) })],
    ["another schema", shard => ({ ...shard, schema: "v213-identity-shard-v3" })],
    ["rows that are not a list", shard => ({ ...shard, rows: { sivers: 1 } })],
    ["a row of three items", shard => ({ ...shard, rows: [["sivers semiconductors", "S", "SIVE"]] })],
    ["a row with another symbol's bucket", shard => ({ ...shard, rows: [["sivers semiconductors", "Q", "SIVE", "NASDAQ STOCKHOLM"]] })],
    ["a row with an empty name", shard => ({ ...shard, rows: [["", "S", "SIVE", "NASDAQ STOCKHOLM"]] })],
    ["a valid row beside a malformed one", shard => ({ ...shard, rows: [...(shard.rows as unknown[]), 7] })],
    ["a non-object body", () => "sivers"],
  ];
  it.each(malformed)("a token shard with %s is treated as absent", async (_label, mutate) => {
    const { env } = await sealed({ edit: objects => { objects[key] = mutate(objects[key] as Record<string, unknown>); } });
    const reply = await line(env, "Sivers");
    expect(reply.text).toContain(SIVERS_ABSENT);
    expect(reply.text).not.toContain("Sivers Semiconductors");
    expect((await line(env, "SIVE")).text).toContain("個股快查 · SIVE");  // every other channel is untouched
  });

  it("a token blob whose bytes do not match the sealed digest is refused", async () => {
    const { env } = await sealed({ tamper: key });
    const reply = await line(env, "Sivers");
    expect(reply.text).toContain(SIVERS_ABSENT);
    expect(reply.text).not.toContain("Sivers Semiconductors");
  });

  it("a token shard that was never written to the blob store is treated as absent", async () => {
    const { env } = await sealed({ dropBlobOf: key });
    expect((await line(env, "Sivers")).text).toContain(SIVERS_ABSENT);
  });

  it("drops the whole step when any matching listing is missing from its symbol shard (never a partial list)", async () => {
    const ghost = await sealed({ edit: objects => {
      const shard = objects[key] as { rows: string[][] };
      objects[key] = { ...shard, rows: [...shard.rows, ["sivers ghost holdings", "G", "GHOST", "NASDAQ"]] };
    } });
    const reply = await line(ghost.env, "Sivers");
    expect(reply.text).toContain(SIVERS_ABSENT);
    expect(reply.text).not.toContain("SIVE（");
    // MU is readable (shard M, which today's symbol channel also reads) but the Tokyo listing's shard is not: no list of one.
    const unreadable = await sealed({ dropBlobOf: `v213:identity:v2:sym:${identitySymbolBucket("6159")}` });
    const micron = await line(unreadable.env, "Micron");
    expect(micron.text).toContain("IDENTIFIER_UNAVAILABLE");
    expect(micron.text).not.toContain("MU (NASDAQ");
    expect(micron.text).not.toContain("個股快查 · MU");
    // When the shard of the typed text itself is unreadable, today's symbol channel already refuses the whole catalog.
    const noM = await sealed({ dropBlobOf: `v213:identity:v2:sym:${identitySymbolBucket("MU")}` });
    const refused = await line(noM.env, "Micron");
    expect(refused.text).toContain("IDENTITY_CATALOG_UNAVAILABLE");
    expect(refused.text).not.toContain("MICRON MACHINERY");
  });

  it("an index entry that the sealed identity row does not support is never shown", async () => {
    const forged = await sealed({ edit: objects => {
      const shard = objects[key] as { rows: string[][] };
      objects[key] = { ...shard, rows: [...shard.rows, ["sivers semiconductors", "N", "NVDA", "NASDAQ"]] };
    } });
    const reply = await line(forged.env, "Sivers");
    expect(reply.text).toContain(SIVERS_ABSENT);
    expect(reply.text).not.toContain("NVIDIA");
    expect(reply.text).not.toContain("Sivers Semiconductors");
  });

  it("reads one token shard per query and the leading step is opt-in (the other callers keep exact names)", async () => {
    const f = await sealed();
    const view = await pinPublicSnapshot(f.env as never);
    expect(view.integrity).toBe("sealed");
    const names = new Map([...f.digests].map(([logical, digest]) => [`blob:v1:${digest}`, logical]));
    const reads: string[] = [];
    const kv = f.kv;
    const original = kv.get.bind(kv);
    kv.get = (async (name: string, type?: "text" | "json") => { if (names.has(name)) reads.push(names.get(name)!); return original(name, type); }) as typeof kv.get;

    const plain = await loadIdentityCatalogForQuery(view, "Sivers");
    expect(plain).not.toBeNull();
    expect(plain!.leading_token).toBeUndefined();
    expect(Object.hasOwn(plain!.indexes.by_name, "sivers")).toBe(false);
    expect(resolveGlobalIdentity(plain, "Sivers").status).toBe("UNAVAILABLE");
    expect(reads.filter(item => item.includes(":tok:"))).toHaveLength(0);

    reads.length = 0;
    const lead = await loadIdentityCatalogForQuery(view, "Sivers", { leadingToken: true });
    expect(lead!.leading_token).toEqual({ total: 1 });
    expect(lead!.indexes.by_name["sivers"]).toEqual([0]);
    const resolution = resolveGlobalIdentity(lead, "Sivers");
    expect(resolution.status === "RESOLVED" && `${resolution.record.venue}:${resolution.record.symbol}`).toBe("NASDAQ STOCKHOLM:SIVE");
    expect(reads.filter(item => item.includes(":tok:"))).toEqual([key]);
    expect(reads.length).toBeLessThanOrEqual(4);  // symbol shard S, the exact-name shard, the token shard (each once per view)
  });

  it("a symbol or an exact name found by today's channels switches the leading step off", async () => {
    const f = await sealed();
    const view = await pinPublicSnapshot(f.env as never);
    for (const input of ["Meta", "SIVE", "Acme Corp", "台積電", "NVDA"]) {
      const catalog = await loadIdentityCatalogForQuery(view, input, { leadingToken: true });
      expect(catalog?.leading_token, input).toBeUndefined();
    }
    for (const input of ["台積", "Sivers 半導體", "2330x", "ab", "Zzzz", "Abc"]) {
      const catalog = await loadIdentityCatalogForQuery(view, input, { leadingToken: true });
      expect(catalog?.leading_token, input).toBeUndefined();
    }
  });
});

describe("V11 W5 word folding parity with the Python producer", () => {
  it("tokenizes, folds and hashes every shared vector like scripts/build_identity_shards.py", () => {
    for (const [input, words, name, bucket] of VECTORS) {
      expect(nameTokens(input), input).toEqual(words);
      const latin = words.length > 0 && /^[\p{Script=Latin}\p{N}]+$/u.test(words[0]!);
      expect(latin ? words.join(" ") : "", input).toBe(name);
      if (latin) expect(identityTokenBucket(words[0]!), input).toBe(bucket);
      else expect(bucket).toBeNull();
    }
    expect(identityTokenBucket("abc")).toBe(440920331 % 8);
  });

  it("accepts only Latin-script input with at least four letters", () => {
    expect(leadingTokenQuery("Sivers")).toEqual({ words: ["sivers"], name: "sivers" });
    expect(leadingTokenQuery("  Astera   LABS,  ")).toEqual({ words: ["astera", "labs"], name: "astera labs" });
    expect(leadingTokenQuery("Société Générale")?.name).toBe("société générale");
    expect(leadingTokenQuery("3M Company")?.name).toBe("3m company");
    for (const refused of ["Abc", "ab", "a b c", "2330", "1234 56", "台積電", "Sivers 半導體", "삼성전자", "Σίγμα", "---", ""]) {
      expect(leadingTokenQuery(refused), refused).toBeNull();
    }
  });

  it("the seal whitelist admits token buckets 0-7 and nothing else", () => {
    for (let index = 0; index < 8; index += 1) expect(SNAPSHOT_LAZY_KEY_RE.test(identityTokenKey(index))).toBe(true);
    for (const bad of ["v213:identity:v2:tok:8", "v213:identity:v2:tok:10", "v213:identity:v2:tok:A", "v213:identity:v2:tok:", "v213:identity:v3:tok:1"]) {
      expect(SNAPSHOT_LAZY_KEY_RE.test(bad), bad).toBe(false);
    }
  });
});

describe("V11 W5 genuine Python builder output through the Worker", () => {
  const SEAL = `snapshot:${fixture.run}:v213:snapshot-seal:v1`;
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-09-15T12:01:00Z"));
  });
  afterEach(() => vi.useRealTimers());

  function environment() {
    const kv = new MemoryKv();
    for (const [name, body] of Object.entries(fixture.values)) kv.values.set(name, body);
    return { PUBLIC_CACHE: asKv(kv), TENANT_PRIVATE_CACHE: asKv(new MemoryKv()), EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()),
      V213_LINE_PRESENTATION: "text", V21_TOP20_MAX_AGE_SECONDS: "7200" };
  }

  it("the sealed run carries the token shards the builder wrote, under whitelisted keys", () => {
    const seal = JSON.parse((fixture.values as Record<string, string>)[SEAL]!) as { objects: Record<string, unknown> };
    const tokenKeys = Object.keys(seal.objects).filter(name => name.includes(":identity:v2:tok:"));
    expect(tokenKeys.length).toBeGreaterThan(0);
    expect(tokenKeys.every(name => SNAPSHOT_LAZY_KEY_RE.test(name))).toBe(true);
    expect(Object.keys(fixture.document.token_shards).sort()).toEqual(tokenKeys.map(name => name.slice(name.lastIndexOf(":") + 1)).sort());
  });

  it("finds a listing by its leading word, resolves the exact name first and still refuses a conflict", async () => {
    const env = environment();
    const reply = async (text: string) => {
      const messages = await handleGlobalEquityLookup(env as never, parseQuery(text));
      expect(Array.isArray(messages)).toBe(true);
      return strings(messages).join("\n");
    };
    const paris = await reply("Paris");
    expect(paris).toContain("個股快查 · PAR");
    expect(paris).toContain("公司名稱（原文）：Paris Orbit");
    expect(paris).toContain("EURONEXT PARIS");
    expect(paris).toContain(UNIQUE_NOTE);
    expect(await reply("London")).toContain("個股快查 · LON");
    expect(await reply("Paris Orbit")).not.toContain("名稱比對");  // the exact name stays on today's path
    const conflict = await reply("Acme");
    expect(conflict).toContain("IDENTITY_CONFLICT");  // the two retained variants of ACME are never resolved
    expect(await reply("Orbit")).toContain("IDENTIFIER_UNAVAILABLE");  // only the FIRST word is indexed, never the middle of a name
    expect(await reply("ACME")).toContain("IDENTITY_CONFLICT");  // today's symbol path is unchanged
  });

  it("answers through the real LINE entry", async () => {
    const reply = await line(environment() as never, "Paris", { LINE_CHANNEL_SECRET: "EXAMPLE_NOT_REAL", LINE_CHANNEL_ACCESS_TOKEN: "EXAMPLE_NOT_REAL" });
    expect(reply.text).toContain("個股快查 · PAR");
    expect(reply.text).toContain(UNIQUE_NOTE);
  });
});
