import { describe, expect, it } from "vitest";
import fixture from "./fixtures/identity-unicode-shadow.json";
import {
  normalizeIdentityShadowQuery,
  parseIdentityRequestShadow,
  InvalidShadowQueryError,
  SHADOW_PROFILE_VERSION,
} from "../src/v213/identity-request-shadow";
import { parseIdentityRequest } from "../src/v213/global-identity";

type Vec = { input: string | null; input_codepoints?: number[]; expected: string | null; status: string };

function vecInput(v: Vec): string {
  if (typeof v.input === "string") return v.input;
  return String.fromCodePoint(...(v.input_codepoints ?? []));
}

const VECTORS: Vec[] = [...(fixture.single_codepoint as Vec[]), ...(fixture.multi_codepoint as Vec[])];

describe("I2 unicode shadow normalizer parity vs I1 oracle", () => {
  it("profile version is the frozen Python Unicode version", () => {
    expect(SHADOW_PROFILE_VERSION).toBe("15.0.0");
  });

  it("records exact corpus counts and permitted statuses before the parity loop", () => {
    expect(fixture.single_codepoint).toHaveLength(6340);
    expect(fixture.multi_codepoint).toHaveLength(21);
    expect(VECTORS.length).toBe(6361);
    for (const v of VECTORS) {
      expect(typeof v.status).toBe("string");
      expect(v.status.length).toBeGreaterThan(0);
      expect(["OK", "INVALID"]).toContain(v.status);
    }
  });

  it("matches the I1 oracle for every generated single/multi vector", () => {
    for (const v of VECTORS) {
      const input = vecInput(v);
      if (v.status === "OK") {
        expect(normalizeIdentityShadowQuery(input), JSON.stringify(input)).toBe(v.expected);
      } else {
        expect(() => normalizeIdentityShadowQuery(input), JSON.stringify(input)).toThrow(InvalidShadowQueryError);
      }
    }
  });

  it("rejects non-string types with the fixed error", () => {
    for (const bad of [123, null, undefined, {}, [], true, 1.5]) {
      expect(() => normalizeIdentityShadowQuery(bad)).toThrow(InvalidShadowQueryError);
    }
  });

  it("rejects empty input", () => {
    expect(() => normalizeIdentityShadowQuery("")).toThrow(InvalidShadowQueryError);
  });

  it("rejects control, bidi, private-use and unknown scalars", () => {
    for (const bad of ["a\u0000b", "a\u202eb", "\ue000", "\u0378"]) {
      expect(() => normalizeIdentityShadowQuery(bad)).toThrow(InvalidShadowQueryError);
    }
  });

  it("enforces codepoint and UTF-16 caps including real astral", () => {
    const astral = String.fromCodePoint(0x10400);
    expect(() => normalizeIdentityShadowQuery("a".repeat(257))).toThrow(InvalidShadowQueryError);
    expect(Array.from(normalizeIdentityShadowQuery(astral.repeat(256))).length).toBe(256);
    expect(() => normalizeIdentityShadowQuery(astral.repeat(257))).toThrow(InvalidShadowQueryError);
  });

  it("rejects raw-normalized length expansion beyond 256", () => {
    expect(() => normalizeIdentityShadowQuery("\ufb03".repeat(90))).toThrow(InvalidShadowQueryError);
  });
});

describe("I2 parser shadow wrapper closed shape", () => {
  it("always exposes only shadow_only/production_authorized/parser_result with false authority", () => {
    for (const input of ["NVDA", "TOP20", "", "a\u0000b", 123 as unknown]) {
      const r = parseIdentityRequestShadow(input);
      expect(Object.keys(r).sort()).toEqual(["parser_result", "production_authorized", "shadow_only"]);
      expect(r.shadow_only).toBe(true);
      expect(r.production_authorized).toBe(false);
    }
  });

  it("returns INVALID_SHADOW_QUERY on normalization refusal without a parsed member", () => {
    for (const input of ["", "a\u0000b", "\ue000", 123 as unknown]) {
      const r = parseIdentityRequestShadow(input);
      expect(r.parser_result).toEqual({ error: "INVALID_SHADOW_QUERY" });
      expect("parsed" in r.parser_result).toBe(false);
    }
  });

  it("prototype-key inputs delegate to the actual parser with closed shape and no prototype mutation", () => {
    const before = Object.getOwnPropertyNames(Object.prototype).sort();
    for (const key of ["__proto__", "constructor", "toString"]) {
      const r = parseIdentityRequestShadow(key);
      expect(Object.keys(r).sort()).toEqual(["parser_result", "production_authorized", "shadow_only"]);
      expect(r.production_authorized).toBe(false);
      expect(r.parser_result).toEqual(parseIdentityRequest(normalizeIdentityShadowQuery(key)));
    }
    expect(Object.getOwnPropertyNames(Object.prototype).sort()).toEqual(before);
  });
});

describe("I2 actual parser through shadow (normalization only, parser unchanged)", () => {
  it("normalizes NVDA/NvIdIa/NVIDIA/fullwidth to valid parses", () => {
    for (const input of ["NVDA", "NvIdIa", "NVIDIA", "\uff2e\uff36\uff24\uff21"]) {
      const want = input === "NvIdIa" || input === "NVIDIA" ? "nvidia" : "nvda";
      expect(parseIdentityRequestShadow(input).parser_result.parsed?.cleanInput).toBe(want);
    }
  });

  it("accepts company prefix with fullwidth ticker via normalization", () => {
    const r = parseIdentityRequestShadow("公司 \uff2e\uff36\uff24\uff21");
    expect(r.parser_result.parsed?.isCompanyPrefix).toBe(true);
    expect(r.parser_result.parsed?.cleanInput).toBe("nvda");
  });

  it("preserves suffix and leading zero", () => {
    expect(parseIdentityRequestShadow("02330.TW").parser_result.parsed?.suffixHint?.symbolBody).toBe("02330");
    expect(parseIdentityRequestShadow("0700.HK").parser_result.parsed?.suffixHint?.symbolBody).toBe("0700");
  });

  it("preserves BRK.A vs BRK-A punctuation", () => {
    expect(parseIdentityRequestShadow("BRK.A").parser_result.parsed?.cleanInput).toBe("brk.a");
    expect(parseIdentityRequestShadow("BRK-A").parser_result.parsed?.cleanInput).toBe("brk-a");
  });

  it("keeps reserved TOP20 and macro term refusals", () => {
    expect(parseIdentityRequestShadow("TOP20").parser_result).toEqual({ error: "RESERVED_BOT_COMMAND" });
    expect(parseIdentityRequestShadow("GDP").parser_result).toEqual({ error: "AMBIGUOUS_MACRO_TERM" });
  });

  it("keeps research product request refusal", () => {
    expect(parseIdentityRequestShadow("股票 數據詳報").parser_result).toEqual({ error: "RESEARCH_PRODUCT_REQUEST" });
  });

  it("retains the parser 100-character limit", () => {
    expect(parseIdentityRequestShadow("a".repeat(101)).parser_result).toEqual({ error: "QUERY_TOO_LONG" });
  });

  it("baseline raw fullwidth still CONFUSABLE-rejected; shadow accepts normalized NVDA", () => {
    const full = "\uff2e\uff36\uff24\uff21";
    expect(parseIdentityRequest(full)).toEqual({ error: "CONFUSABLE_UNICODE_TICKER_REJECTED" });
    expect(parseIdentityRequestShadow(full).parser_result.parsed?.cleanInput).toBe("nvda");
  });
});