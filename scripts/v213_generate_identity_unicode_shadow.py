"""I2 deterministic Unicode shadow data generator (pure stdlib, one-time).

Derives frozen non-C allowed ranges, a full per-codepoint casefold map and golden
parity vectors from installed Python stdlib unicodedata + accepted I1
normalize_query. Not executable third-party code; no company-name authority.
Rejects an unexpected Unicode version rather than silently regenerating a different ABI.
"""
import hashlib
import json
import pathlib
import sys
import unicodedata

EXPECTED_VERSION = "15.0.0"
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.v213_identity_search_shadow import normalize_query  # noqa: E402

TS_PATH = ROOT / "cloud/src/v213/identity-unicode-shadow-data.ts"
JSON_PATH = ROOT / "cloud/test/fixtures/identity-unicode-shadow.json"

UNICODE_LICENSE_NOTICE = """UNICODE LICENSE V3

COPYRIGHT AND PERMISSION NOTICE

Copyright © 1991-2026 Unicode, Inc.

NOTICE TO USER: Carefully read the following legal agreement. BY
DOWNLOADING, INSTALLING, COPYING OR OTHERWISE USING DATA FILES, AND/OR
SOFTWARE, YOU UNEQUIVOCALLY ACCEPT, AND AGREE TO BE BOUND BY, ALL OF THE
TERMS AND CONDITIONS OF THIS AGREEMENT. IF YOU DO NOT AGREE, DO NOT
DOWNLOAD, INSTALL, COPY, DISTRIBUTE OR USE THE DATA FILES OR SOFTWARE.

Permission is hereby granted, free of charge, to any person obtaining a
copy of data files and any associated documentation (the "Data Files") or
software and any associated documentation (the "Software") to deal in the
Data Files or Software without restriction, including without limitation
the rights to use, copy, modify, merge, publish, distribute, and/or sell
copies of the Data Files or Software, and to permit persons to whom the
Data Files or Software are furnished to do so, provided that either (a)
this copyright and permission notice appear with all copies of the Data
Files or Software, or (b) this copyright and permission notice appear in
associated Documentation.

THE DATA FILES AND SOFTWARE ARE PROVIDED "AS IS", WITHOUT WARRANTY OF ANY
KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT OF
THIRD PARTY RIGHTS.

IN NO EVENT SHALL THE COPYRIGHT HOLDER OR HOLDERS INCLUDED IN THIS NOTICE
BE LIABLE FOR ANY CLAIM, OR ANY SPECIAL INDIRECT OR CONSEQUENTIAL DAMAGES,
OR ANY DAMAGES WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS,
WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION,
ARISING OUT OF OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THE DATA
FILES OR SOFTWARE.

Except as contained in this notice, the name of a copyright holder shall
not be used in advertising or otherwise to promote the sale, use or other
dealings in these Data Files or Software without prior written
authorization of the copyright holder."""


def _json_safe(s):
    return not any(0xD800 <= ord(c) <= 0xDFFF for c in s)


def main():
    if unicodedata.unidata_version != EXPECTED_VERSION:
        raise SystemExit("unexpected unicodedata.unidata_version: " + unicodedata.unidata_version)
    ranges = []
    casefold_map = {}
    single = []
    start = None
    for cp in range(0x110000):
        ch = chr(cp)
        allowed = not unicodedata.category(ch).startswith("C")
        if allowed and start is None:
            start = cp
        elif not allowed and start is not None:
            ranges.append((start, cp - 1))
            start = None
        if not allowed:
            continue
        folded = ch.casefold()
        if folded != ch:
            casefold_map[cp] = folded
        if unicodedata.normalize("NFKC", ch) != ch or folded != ch:
            try:
                single.append({"input": ch, "expected": normalize_query(ch), "status": "OK"})
            except ValueError:
                single.append({"input": ch, "expected": None, "status": "INVALID"})
    if start is not None:
        ranges.append((start, 0x10FFFF))

    multi = []

    def add(name, s):
        try:
            expected = normalize_query(s)
            status = "OK"
        except ValueError:
            expected = None
            status = "INVALID"
        multi.append({
            "name": name,
            "input": s if _json_safe(s) else None,
            "input_codepoints": [ord(c) for c in s],
            "expected": expected,
            "status": status,
        })

    add("composition", "e\u0301")
    add("combining_marks", "a\u0308")
    add("fullwidth", "\uff2e\uff36\uff24\uff21")
    add("strasse", "STRASSE")
    add("eszett", "\u00df")
    add("greek_sigma", "\u03a3")
    add("greek_final_sigma", "\u03c2")
    add("cherokee_casefold", "\u13b3")
    add("whitespace_collapse", "  a\u00a0b  ")
    add("whitespace_only", "   ")
    add("control_rejection", "a\u0000b")
    add("bidi_rejection", "a\u202eb")
    add("surrogate_rejection", "a\ud800b")
    add("ligature_expand", "\ufb01")
    add("length_256", "a" * 256)
    add("length_257", "a" * 257)
    add("unknown_scalar", "\u0378")
    add("private_use", "\ue000")
    add("normalized_cap_expansion", "\ufb03" * 100)
    add("astral256", "\U00010400" * 256)
    add("astral257", "\U00010400" * 257)

    ts = [
        "// Generated by scripts/v213_generate_identity_unicode_shadow.py",
        "// Derived from Python stdlib unicodedata (version %s) + I1 normalize_query." % EXPECTED_VERSION,
        "// Frozen non-C allowed ranges + full per-codepoint casefold map. Not executable",
        "// third-party code; no company-name authority claim.",
        "/*!",
        UNICODE_LICENSE_NOTICE.rstrip("\n"),
        "*/",
        'export const UNICODE_VERSION = "%s";' % EXPECTED_VERSION,
        'export const GENERATOR_PROVENANCE = "python-stdlib-unicodedata-%s + I1 normalize_query";' % EXPECTED_VERSION,
        "export const ALLOWED_RANGES: ReadonlyArray<readonly [number, number]> = [",
    ]
    ts += ["  [%d, %d]," % (a, b) for a, b in ranges]
    ts.append("];")
    ts.append("export const CASEFOLD_MAP: Readonly<Record<string, string>> = {")
    ts += ['  "%04x": %s,' % (cp, json.dumps(casefold_map[cp], ensure_ascii=True)) for cp in sorted(casefold_map)]
    ts.append("};")
    ts_text = "\n".join(ts) + "\n"

    payload = {
        "unidata_version": EXPECTED_VERSION,
        "provenance": "python-stdlib-unicodedata-%s + I1 normalize_query" % EXPECTED_VERSION,
        "unicode_license_notice": UNICODE_LICENSE_NOTICE,
        "single_codepoint": single,
        "multi_codepoint": multi,
    }
    json_text = json.dumps(payload, ensure_ascii=True) + "\n"

    TS_PATH.parent.mkdir(parents=True, exist_ok=True)
    JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    ts_bytes = ts_text.encode("utf-8")
    json_bytes = json_text.encode("utf-8")
    TS_PATH.write_bytes(ts_bytes)
    JSON_PATH.write_bytes(json_bytes)

    print("unidata_version", EXPECTED_VERSION)
    print("ranges_count", len(ranges))
    print("casefold_map_count", len(casefold_map))
    print("single_vectors", len(single))
    print("multi_vectors", len(multi))
    print("ts bytes=%d sha256=%s" % (len(ts_bytes), hashlib.sha256(ts_bytes).hexdigest()))
    print("json bytes=%d sha256=%s" % (len(json_bytes), hashlib.sha256(json_bytes).hexdigest()))


if __name__ == "__main__":
    main()