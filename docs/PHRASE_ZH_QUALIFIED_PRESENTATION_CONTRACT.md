# phrase_zh qualified presentation contract (design only)

Status: **PROPOSED_CONTRACT / NOT_IMPLEMENTED / QUALIFICATION_OPEN** at
`a951ec91`. No translator/model activation, publication-schema change or qualified
Chinese phrase is authorized. BATCH02A D6 remains unchanged; current public
behaviour is English-only fresh evidence or explicit refusal. [STATUS](../state/STATUS.md)
and [company claims](COMPANY_CLAIM_ADMISSION_BRIDGE.md) retain all admission and
rollout boundaries. Qualification here means a reviewed translation, never a
new company fact, independent source or trading recommendation.

Phase-1 matrix: `R/batch09-astra-67a3153d/phase1-matrix.json`, SHA256
`C307B28B2E9A6293F6C734778A27A37C730C80C92DA9C55BA2452B24D428E2C0`.
R is the audit-runtime location in STATUS, not packaged evidence. Matrix entries
bind the source file hashes and the current caller locations before these docs.
AMEND1 correction matrix: `R/batch09-r2-astra-0cdf4d5b/phase1-matrix.json`,
SHA256 `55A07FB07402E7CB2A368BE5BE7C61F28E4C4B3A3538F0B93BACCB1829936A9E`;
actual producer/reader fan-out and M4/M5 dependencies were rechecked before edits.
AMEND2 matrix: `R/batch09-r3-astra-0cdf4d5b/phase1-matrix.json`, SHA256
`723B260B405E707BE4C1F57FA027E4310297C1F56DFC658BFB45F4CF3CA6B068`;
route context, carry/captured variants and policy migration were rechecked.

## Current paths this design constrains

- `scripts/company_business_profile.py:397-487`: `_phrase_binding` is mutable-cache
  consistency, not authentication. `resolve_business_profile` re-fetches source
  bytes, may reuse a candidate, and explicitly emits FORMAT_CHECKS_ONLY,
  model UNKNOWN, review NONE and UNVERIFIED translation. A digest cannot promote it.
- Lines 504-525: `_banned_phrases` returns an empty tuple on policy-read failure;
  `validate_phrase` checks format, selected wording and digit-set membership, not
  semantic equivalence. Neither behaviour is a qualification predicate.
- Lines 526-698: `local_translator` identity binding is distinct from generation
  provenance. Reply model ID/`translate.model` is not a weights hash or an attestation.
- `scripts/company_deep_report.py:515-538,619-629,792-840`: public business section
  accepts fresh English source only, refuses oversized text (>700 UTF-16 units),
  and `main()` sets `translate=None`. Test the `build_reports`/main wiring, not
  just `business_section_text` in isolation.
- `scripts/build_v212_top20_report.py:382,474-495,555,707`: no translator; English
  industry detail and audit candidate sidecar are separate. Top20 stays unchanged.
- `scripts/company_deep_report.py:747-767` (`load_reports`) compacts the supplied
  report input: normally the shared cache, or captured bytes on the protected
  v3 path below. Carry-forward bypasses it. Line763 rewrites newlines with spaces
  and slices section text with `[:700]` (Python codepoints, NOT UTF-16 units).
  This is a constrained qualification boundary, not a harmless formatter.
- `scripts/publish_sealed_snapshot.py:248,307-331,350` embeds those sections in
  `deep_reports`, serialized into both `v213:top20-report:latest` and
  `v213:bottleneck-report:latest`. `cloud/src/v213/top20-presentation.ts:148-152`
  reads those aliases from the same sealed snapshot, through
  `deep-analysis.ts:46-51,91-105` and its text/Flex report renderers.
- Carry-forward is a separate producer: `scripts/publish_sealed_snapshot.py:316-338`
  reseals prior `carry.bundle.payloads` without calling load_reports;
  `scripts/top20_carry_forward.py:40-44` CARRIED_OBJECTS includes the v213 Top20
  key. The same carried v213 bytes also feed the bottleneck alias at publisher:350.
- V3 has pathname AND captured-byte callers. `scripts/publish_sealed_snapshot.py:659-683`
  delegates to `captured_bottleneck_v3_body`; `CapturedPublicationInputs:435-455`
  holds immutable operands. `scripts/revenue_guidance_host.py:720-722` passes
  `captured.catalog()`. Publisher:794-814 loads `operand("deep")` when supplied,
  with `today=generated.date()` rather than today's wall clock, then serializes
  `v213-bottleneck-top20-v3-sealed.deep_reports` under `v213:bottleneck-top20:v3`.
- `cloud/src/v213/rich-menu.ts:215-216,229-241` pins the view/loads v3 for both
  bottleneck-detail routes. `bottleneck-v3.ts:445-457` reads BOTTLENECK_V3_KEY
  from that sealed view; :898-904 passes the selected report to the shared
  validator/text/Flex renderers. Admission cannot be checked only at rendering.
- `scripts/build_v213_macro_industry_research.py:350-365,392` builds
  `potential_ranking.reports` from `load_reports`; the macro object is serialized
  by `scripts/publish_sealed_snapshot.py:356-359` under MACRO_KEY
  (`v213:macro-industry:latest`). `cloud/src/v213/rich-menu.ts:486-504` is the
  route-level reader: pinPublicSnapshot -> view.json([MACRO_PRODUCT_KEY]) ->
  validatePotentialRanking -> buildPotentialReport. Only there are the actual
  selected object/view run ID known. `potential-ranking.ts:227-232` receives
  ranking/ticker/display time, NOT an authenticated run ID or object key.
- `cloud/src/v213/deep-analysis.ts:42-79,270,335` is the shared section validator
  (700 UTF-16 units) and text/Flex renderer, NOT three independent admission
  gates. No directly named `phrase_zh` consumer was found under `cloud/src`, but
  generic section strings already flow through ALL the above paths. That absence
  cannot establish containment. Each producer/reader pair needs explicit binding.
- `config/v213-sourced-wording-policy.json` is shared with order wording. Do not
  retrofit phrase qualification by silently changing that policy or its consumers.

## Common encoding, trust and strict load

All proposed `*-v1` records below use closed schemas: required keys, exact types,
known enums, finite bounded integers (not booleans), no duplicate keys/NaN/Infinity,
no lone surrogates, UTF-8 without BOM. Unknown keys/versions and unsupported
algorithms refuse. Canonical digest encoding is sorted-key JSON, compact separators,
UTF-8, `ensure_ascii=false`, no floats; exclude only the record's own digest field.
Hash exact phrase/evidence strings; do not normalize or repair them after review.
All SHA256 values are 64 lowercase hex characters. Strictly bound input sizes
before decoding; validate recursively before canonicalization. Error output is
fixed reason codes, not raw documents, identifiers or model responses.

An attacker can rewrite a cache and all its hashes. Consequently the approved
policy, generation manifest and review receipt must be anchored to a separately
trusted, digest-pinned release/evidence manifest and reviewed author roster, not
a digest supplied alongside the candidate. No new credential/signing scheme is
introduced here. The precise integration with the existing sealed publication
trust root is **BLOCKED_IMPLEMENTATION_TRUST_ROOT** until independently accepted.
Reject mutable sidecars and self-declared signatures as approval evidence.

## Digest-bound phrase wording policy

Proposed separate file `config/phrase-zh-wording-policy-v1.json` (not created by
this design), schema `phrase-zh-policy-v1`, max65536 UTF-8 bytes and depth16.
Exact policy keys below are all required; no nulls, booleans-as-integers, unknown
keys or implicit defaults. Every policy integer is finite. Array uniqueness is
by exact value. EVERY sorted string array in this contract (including bans,
allowed_surfaces, semantic_rules, approved_surfaces and admission ticker order)
uses ascending lexicographic Unicode CODE-POINT/scalar-value order, comparing
first differing scalar numerically, shorter prefix first. No locale collation,
casefold/normalization or UTF-16-code-unit comparison. Integer arrays use ascending
numeric order. Equality/digest checks always retain the exact original strings.

| Key | Exact type / enum / inclusive bound |
| --- | --- |
| `schema` | string literal `phrase-zh-policy-v1` |
| `policy_id` | ASCII string matching `[A-Za-z0-9][A-Za-z0-9._-]{0,63}` |
| `revision` | ASCII string matching `[A-Za-z0-9][A-Za-z0-9._-]{0,31}` |
| `effective_from`, `expires_at` | valid UTC `YYYY-MM-DDTHH:MM:SSZ`, exactly20 ASCII characters, years2000..2099, no leap-second/offset/fraction alternative |
| `locale` | string literal `zh-TW` |
| `allowed_surfaces` | sorted unique string array, 1..3 entries from SurfaceId below; v1 additionally permits ONLY the singleton `POTENTIAL_REPORT_BUSINESS` |
| `min_phrase_codepoints` | integer literal4, applies to candidate phrase_zh, NOT ban entries |
| `max_phrase_codepoints` | integer literal40 |
| `max_phrase_utf16_units` | integer literal80 |
| `banned_phrases_zh`, `banned_phrases_en` | each a sorted unique string array of 1..256 entries; each entry 1..100 Unicode scalar values (<=400 UTF-8 bytes), not blank, no forbidden codepoint; internal single U+0020 allowed under the whitespace rule below |
| `forbidden_controls` | sorted unique integer array exactly equal to the codepoint set below; no configurable omissions/additions in v1 |
| `semantic_rules` | sorted unique string array exactly equal to all seven rule IDs below |
| `required_provenance_schema` | string literal `phrase-zh-generation-v1` |
| `required_review_schema` | string literal `phrase-zh-review-v1` |
| `policy_sha256` | 64 lowercase hex string, canonical digest excluding this field only |

`forbidden_controls` is precisely U+0000..U+001F, U+007C (column separator),
U+007F..U+009F, U+200B..U+200F, U+2028..U+202E, U+2060..U+206F, U+FEFF
and U+FF5C (fullwidth column separator, alongside U+007C),
expanded to their integer scalar values, ascending order. This includes CR/LF,
TAB, bidi overrides/isolation and invisible format controls. Every candidate
phrase and full presentation section is checked against it; no normalization
that removes controls and then grants eligibility. No lone surrogate is valid.

Closed `semantic_rules`: `ENTITY_SCOPE`, `EXACT_QUANTITIES_UNITS`,
`NEGATION_MODALITY`, `NO_MATERIAL_OMISSION`, `NO_UNSUPPORTED_CLAIMS`,
`PERIOD_BASIS`, `TRADITIONAL_CHINESE`. All seven are mandatory, not a selection.
They require source-bound issuer/scope, quantities/units, negation/modality,
period/basis and no unsupported superiority, market size, causality or forecast.

Require effective_from <= decision_time < expires_at and effective_from < expires_at.
Policy IDs/revisions are not authority. Candidate phrase length is 4..40 Unicode
scalar values AND <=80 UTF-16 units; ban-entry minimum is independently1. Existing
two-codepoint bans such as `大量` and `強勁` therefore remain valid. A future
migration must preserve the existing shared bans, not drop them to satisfy a
misapplied phrase minimum. Ban strings may contain internal U+0020 only, with no
leading/trailing/consecutive whitespace. All other Unicode whitespace is refused:
U+0009..U+000D, U+0085, U+00A0, U+1680, U+2000..U+200A, U+2028..U+2029,
U+202F, U+205F and U+3000 (plus the forbidden_controls set). Thus all10 current
English bans in `config/v213-sourced-wording-policy.json`, including
`strong visibility`, `substantially all`, `nearly all`, `multi-year backlog` and
`robust demand`, migrate byte-identically; only their array order may change. Exact zh substring checks and ASCII-casefolded
en substring checks are format refusals only, never positive semantic approval.

The trusted pin source is the **independently admitted immutable release manifest**
entry for the exact relative path above, with its file-byte SHA256; no self-pin
inside the policy, environment override, runtime download or cache sidecar.
Integrating this entry with the publication trust root remains
BLOCKED_IMPLEMENTATION_TRUST_ROOT. Offline fixtures instead inject an explicit
immutable `(policy_path, expected_file_sha256)` test dependency and known bytes;
that injected test pin is never deployable authority. No real pin file is created
or changed here. Production must not silently use the test injection interface.

Check that trusted pin on exact held file bytes BEFORE parsing, then independently
check the internal canonical digest. Same bytes feed validation and evidence.
Missing/unreadable/oversized/malformed/expired/unknown or mismatched policy ->
`POLICY_UNAVAILABLE`, never an empty/default ban set or a previously eligible
result. Revalidate at read and publish time. Existing shared order policy stays
unchanged; migration is a separately reviewed GO.

## Generation record (candidate, not approval)

Schema `phrase-zh-generation-v1`, max 65536 bytes:

| Field group | Required binding |
| --- | --- |
| Identity | generation_id, subject/issuer, accession, original URL, filing form/date |
| Source | raw document/index SHA256, authenticated acquisition receipt digest, source-evidence SHA256, exact sentence and sentence SHA256, extractor version/code SHA256 |
| Locations | ordered source spans with raw/canonical domain tags, offsets, context digests, transformation map and mapped sentence intervals |
| Policy | exact policy-file and canonical policy digests |
| Model/runtime | exact model ID, weights manifest SHA256 (all shards), tokenizer SHA256, runtime build/binary and config digests, binding digest, request/response model identity |
| Prompt | system/user/template SHA256, complete effective prompt bundle digest, template/version and generation parameters (temperature/seed/token/time ceilings) |
| Result | exact phrase_zh and SHA256, response digest, finish_reason=stop, generated_at, generation record SHA256 |

All groups mandatory. UNKNOWN/null model/runtime hashes or missing input evidence
mean UNVERIFIED, not eligible. Model ID alone, a provider name or a running health
endpoint never substitutes. Specifically, model, all weight shards, tokenizer,
runtime binary/build/config and binding hashes count only when bound to the
**admitted owned-instance receipt** in [M4/M5](MODEL_RUNTIME_MIGRATION.md), with
that exact enrolled instance and generation valid for this generation request.
Do not upgrade DECLARED endpoint metadata or a hash computed from unrelated local
files into measured runtime proof. Match request/response identity to the held
instance, source/prompt bindings and receipt; revalidate drift/revocation before
publication. Shared desktop Strata ownership cannot be inferred from a port.

Explicit dependency: `BLOCKED_OWNED_INSTANCE_RECEIPT / X_NATIVE_RUNTIME_PROOF`.
Additional `BLOCKED_RECEIPT_SCHEMA_EXTENSION / X_TOKENIZER_WEIGHT_SHARDS`: the
M4 transition-receipt list in `docs/MODEL_RUNTIME_MIGRATION.md:146` names
executable/model/config/profile/binding hashes but does NOT yet specify tokenizer
or individual weight shards. A later reviewed M4/M5 schema must bind a complete
per-shard manifest (each shard identity, byte length and SHA256, plus manifest
SHA256) and a complete tokenizer-artifact manifest/digest to the actual owned
loaded instance/generation. A top-level model hash alone is not that inventory;
missing/extra/replaced shards or tokenizer bytes refuse. No M4 document/schema
is changed here. Until that extension and the actual admitted proof exist, the
new fields cannot count as bound hashes. Until M4/M5 controller/ownership/native proof and that admitted receipt exist,
generation stays UNVERIFIED even if every hash string is populated. M5 remains
BLOCKED_EXCLUSIVITY_AND_NATIVE_ADMISSION; this design authorizes no GPU probe,
reservation, lifecycle/weight replacement, translator or model activation.

Prompts are evidence, not secrets; retain approved
prompt/template bytes in controlled audit storage, never chain-of-thought,
credentials or unrelated messages. Source text is data, never an instruction.
No translator is invoked by this design. Generation budget/identity failures do
not license model switching, a new GPU server or paid/cloud fallback.

Current English business sentences may be selected, clipped or transformed,
not verbatim raw substrings. A later extractor must provide an honest multi-span
transformation/context map; do not fabricate raw offsets by finding the derived
sentence in HTML. Absent/unreplayable mapping prevents semantic qualification.
Source re-fetch is still not proof of authenticated acquisition by itself.

## Source-bound semantic review

State machine: `UNVERIFIED -> PENDING_REVIEW -> APPROVED | REJECTED | NEEDS_EVIDENCE`;
any changed binding/expired source/policy/revocation gives `STALE` or `REVOKED`.
Only APPROVED with all live trusted bindings is eligible. Unknown/missing state
refuses. Format checks, an LLM confidence score or a second phrasing are not review.

Schema `phrase-zh-review-v1`, max 65536 bytes: review_id, generation/source/policy/
phrase digests, reviewer pseudonymous ID and role, reviewed_at/expires_at,
verdict, source-span/context references, clause-by-clause semantic decisions,
limitations, approved surface set, review digest and trusted-manifest reference.
`approved_surfaces` is a sorted unique nonempty array from the closed SurfaceId
enum below, a subset of the admitted policy and its v1 permission rule. For each
approved surface, review also binds the exact final `section_title`,
`section_text` and their UTF-8 SHA256 values, presentation-template digest,
envelope logical key/schema and source/issuer binding. `section_title` is 1..20
UTF-16 units; `section_text` is 1..700 UTF-16 units, with no forbidden controls.
The reviewed text includes ALL labels, phrase, English excerpt and citation;
reviewing the phrase alone cannot authorize a newly assembled section.
No personal identifiers/credentials enter public output. Until a separate reviewer
trust mechanism is accepted, no record is eligible merely because it says APPROVED.

Roles: generator/writer produces the candidate; an independent bilingual semantic
reviewer (not that generator identity) reads the pinned source/context; publisher
validator deterministically rechecks every binding and authority. Independent
reviewer identity must be enrolled through the approved roster. Disagreement,
source conflict or unclear omitted context -> NEEDS_EVIDENCE, not majority vote.
A model may advise review but cannot authorize itself or replace the independent
reviewer's accountable verdict.

Review every translated clause for issuer/subsidiary, actual vs conditional/future,
negation, products, period, quantities/units, comparative strength and material
omissions. The existing digit-set check cannot establish numerical equality.
A phrase may summarize supported activity, not invent estimates, dominance,
causality or order visibility. Keep evidence per clause; absence of a banned word
is not positive semantic proof. Review validity ends no later than the source and
policy limits; stale evidence cannot be made fresh by reviewing it again.

## Publication surfaces, refusal and cache rules

**Today: no surface may show a qualified phrase.** Closed `SurfaceId` enum for
both policy `allowed_surfaces` and review `approved_surfaces`:

| SurfaceId | Producer / sealed object / Worker reader pair | Future v1 permission, NOT current activation |
| --- | --- | --- |
| `TOP20_DEEP_BUSINESS` | publish_sealed_snapshot:248,331,350 / v213:top20-report:latest or v213:bottleneck-report:latest deep_reports / top20-presentation:148-152 -> deep-analysis:46-51,91-105 | DENIED; English/gap only on BOTH aliases and both text/Flex styles |
| `BOTTLENECK_V3_DETAIL_BUSINESS` | pathname/captured_bottleneck_v3_body -> publish_sealed_snapshot:794-814 / v213:bottleneck-top20:v3 deep_reports / rich-menu:215-241 -> bottleneck-v3:445-457,898-904 -> shared validator/renderers | DENIED; English/gap only, Top20 unchanged |
| `POTENTIAL_REPORT_BUSINESS` | macro builder:350-365,392 + publish_sealed_snapshot:356-359 / v213:macro-industry:latest potential_ranking.reports / rich-menu:486-504 -> potential-ranking:227-232 -> shared validator/renderers | Sole candidate for a later qualified BUSINESS section, after a separate versioned publication GO |

Paths in this table expand to the exact files in Current paths. Unknown surface,
object key/schema or producer/reader pairing refuses. The two Top20 aliases are
explicitly enumerated; they are not a wildcard to copy a permitted envelope.
No qualified phrase enters the shared unqualified `load_reports` payload merely
because it came from build_reports. Retain the English/gap representation there;
a later surface-specific admission stage may produce a reviewed replacement
only for the permitted pair. No generic "company deep-report" exemption covers
all three paths. Top20 ranking/industry/detail, all order/forecast fields,
raw-cache output and legacy/unversioned readers remain not permitted.

Admission granularity is **ONE top-level `phrase_admission` per sealed object**,
with per-ticker entries, never nested sibling admissions. For the permitted macro
object, entries refer exactly to `potential_ranking.reports[ticker]` (business
section only). The admission binds the actual envelope logical key/schema,
snapshot run ID, common candidate payload SHA256 and an entries array of 1..100
unique tickers (also bounded by the existing reports-map size; no map limit is
increased), sorted by the string comparator above. Each entry binds SurfaceId,
issuer/ticker, exact report path, report SHA256, section title/text SHA256,
policy-file/canonical digests, generation/review digests. Independently pinned
review binds that surface/key/schema and the complete section. Require a bijection
between entries and sections explicitly marked qualified by the later versioned
presentation schema: no missing/orphan/duplicate entries or blanket approval of
unlisted siblings. Ordinary English/gap entries need no qualified admission.
Language detection is not a substitute for the versioned presentation type.

Non-circular digest order: first construct all final report strings with NO
admission fields; hash each complete report's canonical JSON. Hash the whole
candidate envelope excluding the ENTIRE top-level phrase_admission member (and
no other member). Then construct the admission with those report/common digests,
and finally seal the envelope INCLUDING admission and all reports. Nested
phrase_admission members are prohibited, not recursively stripped. Thus two
qualified tickers share the same payload digest without hashing each other's
admission. Changing even an English sibling changes the common payload digest;
recompute and revalidate the envelope admission, never copy the old one.

Actual route admission checkpoints for a later implementation:
- Potential report: `rich-menu.ts:491-503`, on the SAME pinned view and original
  macro envelope BEFORE validatePotentialRanking projects data. Compare entry
  ticker, SurfaceId, actual MACRO_PRODUCT_KEY, view.runId, schema, sealed digest
  and all per-entry/common bindings. Only admitted context may reach
  buildPotentialReport/shared rendering; calling a formatter directly or supplying
  overview.generated_at as a run ID cannot qualify it.
- V3 detail: `loadBottleneckV3:445-457` with the pinned view retained by
  `rich-menu:215-241`, BEFORE losing key/run context during parsing; the v1 surface
  is DENIED on both detail routes regardless of a copied potential approval.
- Legacy Top20: `top20-presentation:148-152`, BEFORE companyDataReportFromSealed.
  A future reader must retain which of the two alias keys was actually selected
  and its sealed digest, not guess from the candidate-key list. Missing selection
  context refuses; both aliases remain DENIED. Every checkpoint preserves the
  existing snapshot/freshness/integrity gates and passes checked context onward.
A valid seal alone is not qualification. Context/key/run/surface mismatches or
missing/expired bindings refuse, never infer authority from section metadata.

Carry/captured rule: an exact copied admission can be retained ONLY if the actual
selected route, envelope key/schema, run ID, all bytes/digests and fresh trust
chain still match. A CARRIED_FORWARD reseal into a NEW run cannot retain the prior
run's qualification even when payload bytes are identical; a reseal is not a
review and cannot refresh generation/review clocks. Refuse the qualified section
(or the whole carried object if an independently valid English/gap projection
cannot be built); never strip the approval marker but keep its Chinese phrase.
The captured v3 path likewise revalidates the immutable deep operand and original
clocks at admission, never treats generated.date() or captured-byte identity as
semantic approval. Both Top20 families remain denied in all these variants.
Any future re-admission requires separately allowed surface and new exact bindings;
no silent rebinding, reopening a live cache or repairing captured bytes. Versioned
schema integration/trust-root implementation remains BLOCKED.

For the sole future permitted pair, use the exact reviewed phrase, SEC
form/date/source reference and explicit label
`繁中業務摘要（來源核對；非原文引述）`. Never imply SEC authored the translation.
The source English excerpt keeps its existing honest extraction label. The WHOLE
reviewed section, including labels/citation/English, must fit 700 UTF-16 units.
Otherwise choose independently valid fresh English or explicit gap text, not a
shortened translation. Fallbacks are marked unqualified and carry no approval.

`company_deep_report.load_reports:763` is specifically constrained: future
qualified text must be **byte-identical after UTF-8 decoding/encoding** from the
review record through the sealer to the sealed section and Worker. JSON escaping
may differ, but decoded string bytes/digests must not. The sealer independently
checks no CR/LF/forbidden controls, scalar validity, <=700 UTF-16 units, exact
reviewed title/text digests and full binding; it REFUSES a qualified replacement
rather than `.replace`, `.strip`, normalize or `[:700]` slice it. Formatter checks
are not a substitute. A post-seal digest mismatch refuses that envelope, never
rewrites text inside it. Tests must bypass formatter validation to exercise this
sealer boundary; neither function nor schema is changed by this design.

Research sidecars may retain UNVERIFIED candidates with audit-only labels but
never as qualified public text. Cross-surface copying requires a new review and
admission AND a permission-changing contract; a new review alone cannot enable
a denied pair. Preserve snapshot/readback/freshness/rights gates in every reader.
Real LINE sends need separate current-session authority. No scores, Top20
behaviour, admission or lineage counts change.

On policy, source, acquisition, sentence/map, model/weights/runtime, prompt/template,
phrase, review, schema or permitted-surface change: invalidate eligibility, keep
immutable prior evidence, re-extract/regenerate/review as applicable under a new
GO. A cache hit revalidates the whole chain at the actual decision clock; it does
not refresh acquisition/generation/review timestamps. Cache-only source or missing
original bytes -> refusal, not stale success. No overwriting a digest binding to
"repair" a previous approval. A new identical-byte fetch retains its true clock
and receipt; semantic reuse still needs a new explicitly bound review attestation,
never copying the old status. Failures cannot be blended with a last-known-good
phrase; fresh English source may remain usable independently.

## Later implementation acceptance (NOT_RUN here)

1. Strict policy negatives: absent/read-error/duplicate keys/unknown fields,
   nonfinite/overflow/wrong types/empty bans/expired/mismatched digest; every table
   field/enum/bound at equality and one-over, omitted control/semantic rule,
   invalid surface and swapped path/pin source. Phrase3/4/40/41-codepoint cases
   separate from ban1/2/100/101 cases; two-character Chinese bans remain active.
   No fail-open fallback; preserve shared order-policy behaviour/defaults.
   All10 existing English bans survive unchanged; leading/trailing/doubled spaces,
   NBSP/TAB and other whitespace refuse. Test BOTH U+007C and U+FF5C, and string
   sort with astral versus U+E000/fullwidth values (code-point, not UTF-16 order).
2. Tamper each binding coordinate independently; forged cache+recomputed digests,
   untrusted reviewer/self-review, UNKNOWN weights/runtime, wrong issuer/filing/
   sentence/source, reordered spans and post-validation mutation all refuse.
   Populated hashes without an admitted M4/M5 owned-instance receipt, foreign or
   revoked instance/generation, and request/response mismatch remain UNVERIFIED;
   mock positives never qualify the native runtime or authorize model activation.
   Missing tokenizer/per-shard receipt-schema extension, incomplete/changed shard
   inventory or tokenizer artifact refuses even with a top-level model hash.
3. Controlled translation corpus: negation, subsidiary attribution, modality,
   units/number reordering using identical digit sets, omitted caveats, unsupported
   superlatives, simplified Chinese, source prompt-injection and malformed UTF-8.
   Record human source-bound decisions; model agreement is not a test oracle.
4. Cache/rebinding/revocation/clock limits, restart, concurrent policy update and
   missing source bytes; no timestamp laundering or automatic regeneration.
5. Real `resolve_business_profile -> build_reports -> load_reports` and EVERY
   producer/reader pair in the surface table: both Top20 alias envelopes,
   bottleneck-v3 envelope and macro potential-report envelope, text AND Flex.
   Only the permitted pair may have a future mocked qualified positive; every
   denied pair renders English/gap even with a valid review for the permitted
   one. Surface/key/schema/snapshot/issuer swap, copied admission, missing or
   unversioned binding, stale cache, invalid label/template and post-seal digest
   mismatch negatives at each pair. Both Top20 build/main paths stay nonactivated.
   At the REAL sealer (bypassing formatter checks): 700-unit equality, 701 units,
   astral character ending exactly at the boundary versus crossing it, embedded
   newline, CR/control and a valid-length changed string all refuse unless exact
   reviewed bytes and bindings pass. Assert no newline rewrite, codepoint slice
   or Unicode normalization and independent English/gap fallback, not a clipped
   qualified phrase. Test actual route checkpoints with missing/forged view.runId,
   selected key/digest and direct formatter calls; both v3 detail routes. Exercise
   CARRIED_FORWARD aliases/new-run reseals and captured-deep v3 bytes/clocks;
   old admission cannot be laundered into a new snapshot. Multi-ticker macro
   fixtures include two qualified reports, an English sibling, missing/duplicate/
   swapped entries, nested admissions and changed sibling bytes; verify the common
   payload/per-report hash order has no cycle. No helper-only/formatter acceptance.
6. Frozen clocks, raw evidence before assertions, killing mutants for every
   admission-negative predicate, writer and independent same-snapshot acceptance.
   No translator activation, public admission or rollout inferred from doc tests.
