import { UNICODE_VERSION, ALLOWED_RANGES, CASEFOLD_MAP } from "./identity-unicode-shadow-data";
import { parseIdentityRequest } from "./global-identity";

export const SHADOW_PROFILE_VERSION: string = UNICODE_VERSION;

export class InvalidShadowQueryError extends Error {
  constructor() {
    super("INVALID_SHADOW_QUERY");
    this.name = "InvalidShadowQueryError";
  }
}

function isAllowed(cp: number): boolean {
  let lo = 0;
  let hi = ALLOWED_RANGES.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const range = ALLOWED_RANGES[mid];
    if (range === undefined) {
      return false;
    }
    if (cp < range[0]) {
      hi = mid - 1;
    } else if (cp > range[1]) {
      lo = mid + 1;
    } else {
      return true;
    }
  }
  return false;
}

function assertAllowed(codePoints: readonly number[]): void {
  for (const cp of codePoints) {
    if (!isAllowed(cp)) {
      throw new InvalidShadowQueryError();
    }
  }
}

export function normalizeIdentityShadowQuery(value: unknown): string {
  if (typeof value !== "string") {
    throw new InvalidShadowQueryError();
  }
  const raw = value;
  if (raw.length === 0 || raw.length > 512) {
    throw new InvalidShadowQueryError();
  }
  const rawCps = Array.from(raw, (ch) => ch.codePointAt(0) as number);
  if (rawCps.length === 0 || rawCps.length > 256) {
    throw new InvalidShadowQueryError();
  }
  assertAllowed(rawCps);
  const nfkc = raw.normalize("NFKC");
  let folded = "";
  for (const ch of nfkc) {
    const key = (ch.codePointAt(0) as number).toString(16).padStart(4, "0");
    if (Object.hasOwn(CASEFOLD_MAP, key)) {
      const mapped = CASEFOLD_MAP[key];
      folded += mapped === undefined ? ch : mapped;
    } else {
      folded += ch;
    }
  }
  const collapsed = folded.split(/\s+/u).filter((part) => part.length > 0).join(" ");
  const finalCps = Array.from(collapsed, (ch) => ch.codePointAt(0) as number);
  if (finalCps.length < 1 || finalCps.length > 256) {
    throw new InvalidShadowQueryError();
  }
  assertAllowed(finalCps);
  return collapsed;
}

export interface IdentityRequestShadowResult {
  shadow_only: true;
  production_authorized: false;
  parser_result: ReturnType<typeof parseIdentityRequest>;
}

export function parseIdentityRequestShadow(value: unknown): IdentityRequestShadowResult {
  let normalized: string;
  try {
    normalized = normalizeIdentityShadowQuery(value);
  } catch (err) {
    if (err instanceof InvalidShadowQueryError) {
      return { shadow_only: true, production_authorized: false, parser_result: { error: "INVALID_SHADOW_QUERY" } };
    }
    throw err;
  }
  return { shadow_only: true, production_authorized: false, parser_result: parseIdentityRequest(normalized) };
}