/** Read ONE depth-1 member of a producer-compact sealed document without parsing the rest of it.
 *
 * The sealed lazy objects `v213:options:v2` and `v213:quotes:v1` are `json.dumps(..., separators=(",", ":"))` documents of the shape
 * `{"schema":S,"generated_at":G,"<container>":{"<KEY>":<value>,...}}`. The text handed to this module is already digest-verified, so this is a
 * performance read, never an integrity check. One string-aware scan of the container builds a member index (key -> [start, end) span of every
 * DEPTH-1 member, nothing deeper); a lookup then parses only the span of the asked key. The index is refused (undefined, and the caller runs its
 * unchanged full-parse path) for any text that is not exactly that shape: a duplicate depth-1 key, a key with an escape, a missing colon or comma,
 * a bracket of the wrong kind, an unterminated container, anything after the container but the closing brace. A refusal is never "absent".
 * The scan checks the structure of the container and the bracket balance of every value; it does not validate the syntax inside values (that is
 * the JSON.parse of the one span a lookup reads), which is why it is only used on text whose bytes already matched the sealed digest. */
export interface SealedHeader { readonly generated_at: string; readonly bodyStart: number; readonly container: string }
export interface MemberIndex { readonly length: number; readonly spans: ReadonlyMap<string, readonly [number, number]> }

/** Ticker syntax of the producer (and of validateCoveredCallCycle); any other key takes the full path. */
const MEMBER_KEY = /^[A-Z0-9][A-Z0-9.\- ]{0,15}$/;
const MAX_NESTING = 30;

/** Header of `{"schema":"<schema>","generated_at":"<instant>","<container>":{`; undefined when the text does not start exactly so. */
export function sealedHeader(text: string, schema: string, container: string): SealedHeader | undefined {
  const head = `{"schema":"${schema}","generated_at":"`;
  if (!text.startsWith(head)) return undefined;
  const end = text.indexOf('"', head.length);
  if (end < 0 || end - head.length > 40) return undefined;
  const generated = text.slice(head.length, end);
  if (/[\\"]/.test(generated)) return undefined;
  const tail = `","${container}":{`;
  if (!text.startsWith(tail, end)) return undefined;
  return { generated_at: generated, bodyStart: end + tail.length, container };
}

let builds = 0;
/** Test seam: how many container scans this isolate has run. */
export function memberIndexBuilds(): number { return builds; }

/** Index of the depth-1 members of the container that starts at `start` (just after its `{`), or undefined (refused). */
export function scanMembers(text: string, start: number): MemberIndex | undefined {
  builds += 1;
  const n = text.length;
  const spans = new Map<string, readonly [number, number]>();
  let i = start;
  if (text.charCodeAt(i) !== 125) {  // not an empty container
    for (;;) {
      if (text.charCodeAt(i) !== 34) return undefined;  // a depth-1 key is a string
      const keyStart = i + 1;
      i = keyStart;
      for (;;) {
        if (i >= n) return undefined;
        const c = text.charCodeAt(i);
        if (c === 34) break;
        if (c === 92) return undefined;  // an escaped key is never a ticker; the whole index is refused rather than guessed
        i += 1;
      }
      const key = text.slice(keyStart, i);
      i += 1;
      if (text.charCodeAt(i) !== 58) return undefined;
      i += 1;
      const valueStart = i;
      const first = text.charCodeAt(i);
      if (first === 123 || first === 91) {
        let kinds = 0;  // one bit per open bracket: 1 = [, 0 = {
        let depth = 0;
        let inString = false;
        for (; i < n; i += 1) {
          const c = text.charCodeAt(i);
          if (inString) {
            if (c === 92) i += 1;
            else if (c === 34) inString = false;
          } else if (c === 34) inString = true;
          else if (c === 123 || c === 91) {
            if (depth >= MAX_NESTING) return undefined;
            kinds = (kinds << 1) | (c === 91 ? 1 : 0);
            depth += 1;
          } else if (c === 125 || c === 93) {
            if ((kinds & 1) !== (c === 93 ? 1 : 0)) return undefined;  // wrong kind of closing bracket
            kinds >>>= 1;
            depth -= 1;
            if (depth === 0) { i += 1; break; }
          }
        }
        if (depth !== 0) return undefined;  // unterminated value
      } else if (first === 34) {
        i += 1;
        for (;;) {
          if (i >= n) return undefined;
          const c = text.charCodeAt(i);
          if (c === 92) i += 2;
          else { i += 1; if (c === 34) break; }
        }
      } else {
        while (i < n) { const c = text.charCodeAt(i); if (c === 44 || c === 125) break; i += 1; }
        if (i === valueStart) return undefined;  // empty value
      }
      if (spans.has(key)) return undefined;  // duplicate depth-1 key: which one wins is not decided here
      spans.set(key, [valueStart, i]);
      const separator = text.charCodeAt(i);
      if (separator === 44) { i += 1; continue; }
      if (separator === 125) break;
      return undefined;
    }
  }
  // text[i] closes the container; the compact document ends right after it with the closing brace of the document
  if (i !== n - 2 || text.charCodeAt(i) !== 125 || text.charCodeAt(i + 1) !== 125) return undefined;
  return { length: n, spans };
}

// Per-isolate memory of lazy bodies that were ALREADY verified against their sealed sha256. The key is the content address itself, so an entry
// can only ever hold the exact bytes that digest names; the manifest (read and verified for every question) still decides which digest a
// question may use. It saves the KV read, the UTF-8 round trips and the SHA-256 of a 1-2 MB object on every later question of the isolate.
// Kept here (not in public-snapshot.ts, a read-only KV view) because it is plain isolate memory.
const VERIFIED_LAZY = new Map<string, string>();
const VERIFIED_LAZY_MAX_ENTRIES = 4;
const VERIFIED_LAZY_MAX_CHARS = 6_000_000;
/** Test seam: forget every remembered body and member index (the vitest setup file calls it before each test, so no test inherits another test's reads). */
export function clearVerifiedLazyBodies(): void {
  VERIFIED_LAZY.clear();
  clearMemberIndexes();
}
export function rememberVerifiedLazy(sha256: string, body: string): void {
  VERIFIED_LAZY.delete(sha256);
  VERIFIED_LAZY.set(sha256, body);
  let chars = 0;
  for (const value of VERIFIED_LAZY.values()) chars += value.length;
  for (const key of VERIFIED_LAZY.keys()) {
    if (VERIFIED_LAZY.size <= VERIFIED_LAZY_MAX_ENTRIES && chars <= VERIFIED_LAZY_MAX_CHARS) break;
    if (key === sha256) continue;
    chars -= VERIFIED_LAZY.get(key)!.length;
    VERIFIED_LAZY.delete(key);
  }
}

/** A body already verified against `sha256` in this isolate, or undefined. */
export function knownVerifiedLazy(sha256: string): string | undefined {
  return VERIFIED_LAZY.get(sha256);
}

// Per-isolate memory of member indexes, keyed by the body's sealed sha256 (and container): the digest names exact bytes, so an index built from
// those bytes is valid for as long as the isolate lives. Same bounds as the verified lazy bodies of public-snapshot.ts; a refused text is
// remembered too (null), so a document that cannot be indexed is scanned once, not once per question.
const INDEXES = new Map<string, MemberIndex | null>();
const INDEX_LENGTHS = new Map<string, number>();
const INDEX_MAX_ENTRIES = 4;
const INDEX_MAX_CHARS = 6_000_000;
/** Test seam (called by clearVerifiedLazyBodies): forget every remembered index. */
export function clearMemberIndexes(): void {
  INDEXES.clear();
  INDEX_LENGTHS.clear();
}
function rememberIndex(key: string, index: MemberIndex | null, length: number): void {
  INDEXES.delete(key); INDEX_LENGTHS.delete(key);
  INDEXES.set(key, index); INDEX_LENGTHS.set(key, length);
  let chars = 0;
  for (const value of INDEX_LENGTHS.values()) chars += value;
  for (const old of INDEXES.keys()) {
    if (INDEXES.size <= INDEX_MAX_ENTRIES && chars <= INDEX_MAX_CHARS) break;
    if (old === key) continue;
    chars -= INDEX_LENGTHS.get(old)!;
    INDEXES.delete(old); INDEX_LENGTHS.delete(old);
  }
}

/** The member index of `text`, from the isolate memory when the sealed `sha256` of these exact bytes is known (otherwise built, not remembered). */
export function memberIndexFor(text: string, header: SealedHeader, sha256?: string): MemberIndex | undefined {
  const key = sha256 === undefined ? undefined : `${sha256}:${header.container}`;
  if (key !== undefined) {
    const known = INDEXES.get(key);
    if (known === null && INDEX_LENGTHS.get(key) === text.length) return undefined;
    if (known !== undefined && known !== null && known.length === text.length) return known;
  }
  const built = scanMembers(text, header.bodyStart);
  if (key !== undefined) rememberIndex(key, built ?? null, text.length);
  return built;
}

/** The depth-1 member `key` parsed: the value, `null` when the container has no such depth-1 key, `undefined` when this way cannot decide
 * (key syntax, refused index, value that is not an object, value that is not valid JSON): the caller then runs its full-parse path. */
export function parseObjectMember(text: string, header: SealedHeader, key: string, sha256?: string): unknown | null | undefined {
  if (!MEMBER_KEY.test(key)) return undefined;
  const index = memberIndexFor(text, header, sha256);
  if (index === undefined) return undefined;
  const span = index.spans.get(key);
  if (span === undefined) return null;
  if (text.charCodeAt(span[0]) !== 123) return undefined;
  try { return JSON.parse(text.slice(span[0], span[1])); } catch { return undefined; }
}
