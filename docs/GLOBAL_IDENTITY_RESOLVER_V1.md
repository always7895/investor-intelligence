# Authoritative Global Identity Resolver v1 (Specification & Acceptance Revision 2)

## 1. Overview & Architecture

`AUTHORITATIVE_GLOBAL_IDENTITY_RESOLVER_V1` establishes a truly general, source-audited global instrument identity resolver for the Investor Intelligence LINE bot. It replaces ephemeral top-20 matching and hardcoded dictionaries with a verifiable, versioned catalog schema (`v213-global-identity-v1`).

### 1.1 Closed Resolution Union

Every query resolves deterministically into one of four mutually exclusive states:
1. `RESOLVED`: Exactly one authoritative listing record matched. Returns official symbol, venue, jurisdiction, security class, currency, and verified English/native names. Quote remains `WITHHELD` / `UNAVAILABLE`.
2. `NEEDS_MARKET_SELECTION`: Multiple real candidate identities matched across distinct venues or share classes (e.g. dual listings like `ASML` on Euronext Amsterdam vs NASDAQ; `BRK.A` vs `BRK.B`; or ticker vs company name collisions like bare `BOX`). Presents explicit candidate selection choices.
3. `UNAVAILABLE`: Valid syntax and query intent, but the security or company lead is not currently admitted in the pinned sealed snapshot (or the regional feed is deferred). Returns an honest `UNAVAILABLE` card without falling through to generic LLM QA or issue ticket creation.
4. `INVALID_REQUEST`: Malformed query, full-width/confusable Unicode (`ＡＡＯＩ`), overlong strings, or reserved commands.

---

## 2. Acceptance Revision 2 Corrections (Astra Audit)

### 2.1 Complete Removal of Object References in Indexes (Defect 1)
- Removed all object fallback and object compatibility from `by_symbol`, `by_name`, and `by_venue_and_symbol`.
- Indexes strictly map to bounded, finite, non-negative integer record IDs (`0 <= ref < records.length`).
- Rejected `NaN`, `Infinity`, fractional numbers, negatives, booleans, strings, and out-of-bounds references.
- Added full structural validation to `by_venue_and_symbol`.

### 2.2 Canonical Index Derivation & Exact Rebuild Comparison (Defect 2)
- Merely having valid integer IDs is insufficient (e.g. mapping `AAPL` to `MSFT` record index 1).
- `validateCatalogCandidate` rebuilds canonical indexes from the verified `records` array and performs an exact bijective comparison:
  - Exact key count equality.
  - Exact index match for every key.
  - Rejection of wrong, stale, missing, extra, duplicate, or bogus index entries.
  - Complete protection against prototype pollution (`__proto__`, `constructor`, `prototype`, `toString`, `valueOf`, `hasOwnProperty`, `isPrototypeOf`).
  - True identity deduplication (`${venue}:${symbol}`) and conflict quarantine.

### 2.3 Strict ISO 8601 Calendar Validation & Closed Schemas (Defect 3)
- Replaced naive regex matching on `generated_at` with strict ISO 8601 UTC validation (`/^(?!0000)\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{3})?Z$/`) and roundtrip calendar matching (`new Date(n).toISOString() === (raw.includes(".") ? raw : raw.replace("Z", ".000Z"))`).
- Rejects impossible calendar dates (e.g. `2026-02-31`), trailing timezone junk, and naive clocks.
- No invented live freshness from generation time; unknown source publication/rights remain UNKNOWN.
- Closed root keys and closed record schemas reject unauthorized extra attributes.

### 2.4 Credential-Free Public HTTPS Source URLs (Defect 4)
- Enforces strict public HTTPS scheme on `source_url`.
- Rejects HTTP, user credentials (`user:pass@`), path traversal (`/../`), and local/private IP addresses (`127.0.0.1`, `localhost`, `10.*`, `192.168.*`, `172.16.*`).
- Native company names and native symbols preserved without artificial ASCII restrictions.
- Strict distinction between structural `SOURCE_CANDIDATE` and runtime `ADMITTED`.

### 2.5 Strict Raw UTF-8 Byte Bounds & Removal of Unbounded JSON Fallback (Defect 5)
- Reader measures payload size in actual UTF-8 bytes using `TextEncoder().encode(rawText).byteLength` against `MAX_CATALOG_BYTES` (10 MB), properly handling multi-byte CJK text.
- Completely removed `view.json` fallback to ensure unmeasured memory expansion cannot bypass bounded text constraints.
- Actual file size of candidate index measured directly.

### 2.6 Seal Profile Boundary & Admission Deferral (Defect 6 - Most Important)
- Current stored snapshot seal profile (`SNAPSHOT_OBJECT_KEYS`) contains 13 objects and has NO identity slot and no approved identity producer.
- `validateCatalogCandidate` validates candidate syntax only; it CANNOT and DOES NOT grant runtime authority.
- `evaluateCatalogAdmission` reports scope `ADMISSION_DEFER` when snapshot seal lacks an identity profile slot.
- Caller (`handleGlobalEquityLookup`) fails closed with dedicated `UNAVAILABLE` cards ("身分資料未封存准入 · 報價不可用"), guaranteeing no leakage to LLM QA or issue ticket creation.

---

## 3. Retained Projections & Measured Record Counts

- **Retained Projection Fields**:
  - `nasdaq-listed`: `Symbol`, `Security Name`, `Market Category`, `Test Issue`, `ETF`.
  - `other-us-listed`: `ACT Symbol`, `Security Name`, `Exchange`, `Test Issue`, `ETF`.
  - `twse-listed`: `上市日期`, `公司代號`, `公司名稱`, `公司簡稱`, `產業別`.
- **Jurisdiction**: Listing venue country is strictly recorded (US for NASDAQ/NYSE; Taiwan for TWSE), not inferred issuer domicile.
- **Classification**: `ETF=N` does not prove `COMMON_STOCK`; unverified records default to `REVIEW_REQUIRED`.
- **Measured Record Counts**:
  - Global Identity Catalog: 14,276 official records.
  - Legacy Discovery Universe: 8,599 symbols (includes 1,583 `REVIEW_REQUIRED` records).
  - The variance is explained by the global catalog retaining official ETFs (5,677+ ETFs across NASDAQ, Other US, and TWSE).

---

## 4. Test Verification Matrix (Revision 2)

| Lane | Target | Tests | Status | Retries |
|---|---|---|---|---|
| Behavioral RED | `v213-global-identity-integrity.test.ts` (against pre-fix code) | 10 tests, 8 failed assertions | RED_CONFIRMED | 0 |
| Focused Lane | `integrity`, `review`, `identity`, `caller`, `lookup`, `worker-flow` | 98 passed | PASS | 0 |
| Python Lane | `test_global_identity_index.py`, `test_public_symbol_admission.py` | 14 passed | PASS | 0 |
| Affected Suite | Full Cloud Suite (50 test files) + `tsc --noEmit` | 775 passed, 1 skipped | PASS | 0 |
| Catalog CLI | `scripts/global_identity_index.py` | 14,276 records indexed | PASS | 0 |
