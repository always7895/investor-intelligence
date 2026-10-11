# F05B PDF extraction contract (design only)

Status: **PROPOSED_CONTRACT / NOT_IMPLEMENTED / NOT_QUALIFIED**. BATCH09 at
`a951ec91` specifies a later bounded implementation, not dependency adoption,
parser acceptance, CRWV admission or installation authority. No PDF is parsed by
this change. Existing NBIS PDF refusals stay closed. Current truth remains
[STATUS](../state/STATUS.md); see [guidance](REVENUE_GUIDANCE_AUTOUPDATE.md) and
[dependency locking](DEPENDENCY_LOCKING.md).

## Evidence and current boundaries

Phase-1 audit: `R/batch09-astra-67a3153d/phase1-matrix.json`, SHA256
`C307B28B2E9A6293F6C734778A27A37C730C80C92DA9C55BA2452B24D428E2C0`;
R is the audit-runtime directory named in STATUS, not a distributable source path.
The matrix predates these docs; its raw inventory binds local metadata/source pins.
AMEND1 correction inventory: `R/batch09-r2-astra-0cdf4d5b/phase1-matrix.json`,
SHA256 `55A07FB07402E7CB2A368BE5BE7C61F28E4C4B3A3538F0B93BACCB1829936A9E`.
It rechecks the frozen drafts, A2 section 6 and actual source consumers before edits.
AMEND2 precision matrix: `R/batch09-r3-astra-0cdf4d5b/phase1-matrix.json`,
SHA256 `723B260B405E707BE4C1F57FA027E4310297C1F56DFC658BFB45F4CF3CA6B068`;
R2 input hashes, updater retry policy and further consumers were rechecked.

- `scripts/revenue_guidance_auto_verify.py:375-412` parses HTML and supplies
  canonical **character** offsets, not PDF offsets. Its limits are 16 MiB raw and
  4 * 1024 * 1024 canonical characters; a PDF must not be decoded as this HTML dialect.
- `build_successor` / `_Inputs.raw` at lines 871-917 re-establish source identity
  from captured bytes. NBIS lines 1922 and 1975-1994 refuse PDF links/non-HTML members;
  A1 `package_names:851-854` filters for HTML, not universal PDF inspection/refusal.
- `scripts/revenue_guidance_autoupdate.py` (`PLANNERS`, dispatched in `run`, and the
  `verify.build_successor` calls in `reverify` and `run`) dispatches closed
  planners/builders. Extraction does not add an adapter, issuer, source or fetch.
- CRWV IR-package scope remains a later slice (guidance doc section "Open (later
  slices and Part B)", items A2 and Part B order).
  Neither successful extraction nor this contract supplies original IR bodies,
  dates, units, period/basis, independence, rights or positive qualification.

## Candidate and unresolved artifact inputs

Only candidate selected for **evaluation**, not installed adoption: `pypdf==6.18.1`,
no extras, CPython 3.12.10. Local global site-packages metadata reports
`Requires-Python: >=3.9`, `BSD-3-Clause`, `Root-Is-Purelib: true`, `py3-none-any`.
Its 125 RECORD rows name no `.pyd/.dll/.so/.exe`. These are local packaging facts,
not an upstream authenticity or vulnerability audit. Optional crypto/image/font
extras are outside this contract. No unconditional dependency applies on Python
3.12; `typing_extensions>=4.0` is conditional on Python <3.11. Encrypted inputs
are refused, not a reason to enable crypto or native extras.

| Local metadata evidence | SHA256 |
| --- | --- |
| METADATA (7469 B) | `4D058BDD9D304FEBB158AF874979508BA31ED88BEA21EEF040597D92ED07BE2E` |
| WHEEL (81 B) | `FF23073DA055FACE9F40CC14A28F3735275308CDDCF315D6157461A9A7CDFBB6` |
| RECORD (8840 B) | `3CE1451837E500D65C9C4599C33B1ACF76BB600B6B43C34F8E13EDD58F0BAC4E` |
| licenses/LICENSE (1605 B) | `A97AC230E5F33EF10A5367A850EB01F91F1A0B064E34742C7794D2294557F524` |

**Wheel SHA256: UNKNOWN / X_ARTIFACT_REQUIRED.** No wheel artifact was found in
the checked local wheel-cache location (directory absent); metadata/RECORD hashes
are NOT the wheel hash. Required external input is the complete
`pypdf-6.18.1-py3-none-any.whl`, its independently reviewed origin and actual
SHA256, contained licence and full dependency metadata. No claim about other
caches, no network lookup/download and no parser import occurred. No substitute
parser is approved; another candidate needs its own exact artifact/licence pins.
BSD-3-Clause requires preserving copyright, conditions and disclaimer and forbids
endorsement using the author's name without permission; package licence is not document-use rights.

A LATER dependency GO must review that artifact and transitive closure, add the
exact direct version to `requirements-ci.in` and regenerate the reviewed
`requirements-ci.txt` hash lock without unrelated upgrades. Preserve the pinned
dist-info `licenses/LICENSE` and its package-manifest entry, inspect wheel contents and validate
in a dedicated locked venv with the approved resolver and `pip check`. No sdists,
auto-upgrade, global-import fallback or silently enabled extras. Record separate
source/installed qualification. Missing artifact/provenance stays X, never a
placeholder hash in a real lock. This design changes no requirements or installer.

## Isolation and hard budgets (requirements, not proven capabilities)

One owned extraction child per document, concurrency 1. Parent passes bounded
already-captured bytes through private handles, never an arbitrary URL/path from
the document. Copy once, hash and parse the same immutable input; reject reparse
points and TOCTOU replacement. Pinned interpreter/wheel/wrapper/environment,
`-I -B`, isolated venv, empty inherited search/proxy variables, private TEMP/HOME,
allowlisted inherited handles only. No shell, subprocess descendants, network
(including loopback/DNS), credentials, user profile or installed-payload access.

Create suspended; assign a kill-on-close Windows Job before resume. Require job
and per-process memory limits 512 MiB, active-process limit 1, job user-mode
CPU-time limit 10 s, independent parent wall deadline 30 s (includes parsing,
drainage and validation); CPU-rate ceiling 25% is mandatory. Kernel time is
bounded by the wall deadline, not claimed as job user-mode CPU accounting.
Apply equivalent stricter limits or refuse if a control is unavailable; no silent downgrade. Close/kill
only this owned job on timeout/crash/cancel; reconcile all owned lifetimes and
wait for zero active processes before accepting output. A Job, `-I` and Python
audit hooks are **not an OS network/filesystem sandbox**. A separately reviewed
restricted-token/AppContainer or equivalent deny-network/read-scope design and
native fixture proof are prerequisites; no ACL, firewall, registry or policy
changes of any scope are authorized here. If isolation cannot be demonstrated, backend qualification stays
`BLOCKED_ISOLATION`; this is NOT an output-schema state and no child is launched.

All limits are inclusive ceilings; test equality and one-over. Do not increase
existing event/package/envelope ceilings to fit PDF output.

| Resource | Ceiling / enforcement |
| --- | --- |
| Raw body | 16 MiB, reject before parser allocation |
| Pages | 100 across complete document; no first-N-page success |
| Object/xref entries | 20000 declared or resolved; reject sparse indexes before proportional allocation |
| Object/reference traversal work | 20000 visits including repeats; detect cycles, no repair loop |
| Streams | 10000 counted before decode, including object/font/CMap/Form and image streams |
| Nesting / xref revision chain / filter chain | 64 / 16 / 4 |
| Decoded stream | 8 MiB each, 64 MiB cumulative, including object/font/CMap streams |
| Expansion ratio | decoded <= 100 * max(1, encoded bytes), per stream and total |
| Text | 256 KiB UTF-8/page; 2 MiB total; 20000 spans total |
| IPC/output | 4 MiB framed JSON total; bounded stdout/stderr, no raw body logging |

Charge limits BEFORE allocation/decompression and while producing output, not
only after `extract_text()` returns. Backend allocation/interception and locator
support are **X_IMPLEMENTATION_PROOF**, not capabilities inferred from pypdf
metadata. If the pinned backend cannot enforce these bounds, reject that backend:
qualification stays `BLOCKED_CONTRACT` (outside the output schema), without a child
or purported extraction result. Never claim a post-hoc counter prevents a bomb.

### PDF identity, inert content and rendered-text divergence

Before parsing, require `%PDF-1.0` through `%PDF-1.7` or `%PDF-2.0` at byte offset
0, followed by CR, LF or CRLF; no BOM or leading garbage. The separately
authenticated acquisition receipt must bind this body and a reviewed, normalized
`application/pdf` Content-Type (no unreviewed parameters), plus the exact original
HTTPS URL admitted by the issuer/source allowlist. No sniff-only admission,
redirect inference, guessed CDN URL or source identity from PDF metadata. Failure
is `FAILED/INPUT_NOT_PDF`, `FAILED/CAPTURE_INVALID` or `FAILED/URL_NOT_ALLOWED` as
appropriate. These three reasons are pre-launch refusals with null capture binding
under the exact rule below; they do not require pretending a disallowed URL or
wrong MIME type satisfies the success preimage. Check receipt authentication,
then URL admission, then media type/header, in that order; launch only after all
pass. PDF/HTML masquerades and polyglots refuse as `FAILED/POLYGLOT`:
require the entire body to conform to the admitted PDF grammar, account for every
byte, and reject a second document/container or positively identified HTML body.
An HTML parser accepting arbitrary bytes is NOT proof of HTML identity. The final
`%%EOF` must be the terminal grammar marker; only one optional CR, LF or CRLF may
follow it. Other unaccounted trailing data -> `FAILED/TRAILING_DATA`. Incremental
updates require complete bounded xref/revision accounting; ambiguous revisions
remain `FAILED/MALFORMED_PDF`. No parser repair or permissive fallback.

Classify EVERY reachable stream before decoding using its dictionary type and
its role in the admitted object/resource graph. Text-relevant means page Contents,
Form XObject content, font CMap/ToUnicode and Type3 glyph CharProcs (only if their
font/visibility grammar is independently supported). Structural xref/object
containers are a separate class even when they contain text-related objects.
Ambiguous/conflicting roles or any unclassified stream refuse; no unbounded
"non-text" decoder exception. Closed class/filter/DecodeParms rules:

| Stream class | Decode and outcome |
| --- | --- |
| Text-relevant as defined above | No filter, or a chain of <=4 stages from FlateDecode, ASCIIHexDecode, ASCII85Decode, RunLengthDecode only |
| Cross-reference (`/Type /XRef`) and object (`/Type /ObjStm`) | No filter or ONE FlateDecode stage only; decode under the same stream/total/ratio/object limits BEFORE allocation; reclassify contained objects under this table |
| Metadata (`/Type /Metadata`), ICC profiles, embedded font-program streams (FontFile/FontFile2/FontFile3), other/unknown stream classes | Never decode, regardless of filter or DecodeParms; whole document FAILED/UNSUPPORTED_STREAM_CLASS. No complete-inspection or glyph proof may rely on them in v1 |
| Image XObject / inline image | Never decode, any filter/DecodeParms; whole document FAILED/IMAGE_CONTENT_UNREVIEWED as below |

For BOTH admitted decode classes, each stage's DecodeParms must be absent/null
or an empty dictionary, except Flate may specify ONLY integer `Predictor=1`.
Arrays, alternate keys, aliases/abbreviations and all other predictors refuse
as FAILED/UNSUPPORTED_FILTER. Thus PNG predictors10..15, including a common xref
Predictor12, are explicitly UNSUPPORTED, NOT decoded without bounds. This narrow
v1 does not claim compatibility with those otherwise valid PDFs. For multi-stage
text filters only absent/null DecodeParms is allowed, avoiding ambiguous parameter
alignment. Fonts without embedded programs still need independent mapping and
visibility proof; this table supplies no such proof. A later supported font/ICC/
metadata or predictor grammar requires a separate reviewed contract, not fallback.
All listed resource bounds apply to EVERY decoded stage and cumulative work.
Count rejected streams too; unsupported filter/parameter in an admitted class ->
FAILED/UNSUPPORTED_FILTER, while a refused class takes its class-specific reason
before filter inspection.

Image XObject and inline-image streams are **never decoded**. In this v1 their
presence anywhere in the reachable page/resource graph makes the whole document
`FAILED/IMAGE_CONTENT_UNREVIEWED`, even for a purported decorative logo. Such a
page cannot establish complete adverse-content inspection. There is no admitted
image exception here; a later independent rule/fixture/contract review would be
needed before permitting one. Zero-text pages always give `FAILED/ZERO_TEXT_PAGE`,
including apparently blank pages; v1 has no independently-demonstrated-blank
exception. No OCR, render engine or image-to-text fallback.

Only inert `/Link` annotations with a single `/A` action `/S /URI` are permitted:
URI is an absolute HTTPS string <=2048 UTF-8 bytes without userinfo/controls;
no `/AA`, `/Next`, `/JS`, `/Dest`, appearance stream or alternate action. An
annotation's rectangle/label is not financial evidence. Never fetch, execute,
render or use its URL as capture authority; URI presence alone does not change
source provenance. URI-free ordinary text and this inert link case may succeed;
HTTP/javascript/file links, malformed annotations and all other annotation kinds
refuse as `FAILED/UNSUPPORTED_ANNOTATION`. Document-level actions, scripts,
embedded files, forms/XFA and multimedia give `FAILED/UNSUPPORTED_ACTIVE_CONTENT`.

Require detection across page contents and nested Form XObjects of:

| Condition | Whole-document refusal (no surviving spans) |
| --- | --- |
| Render mode 3 (invisible text) | `FAILED/INVISIBLE_TEXT` |
| Hidden/off optional-content layers, or unresolvable layer state | `FAILED/HIDDEN_OPTIONAL_CONTENT` |
| Text wholly/partly outside CropBox or clipped, or visibility cannot be established | `FAILED/CLIPPED_TEXT` |
| White-on-white, transparent/occluded/overlaid text, unsupported graphics/blend state preventing visibility proof | `FAILED/VISIBILITY_UNPROVEN` |
| ActualText, ToUnicode, Differences or other font mapping changes/suppresses digits, currency or unit glyphs, or their equality cannot be proven | `FAILED/GLYPH_DIVERGENCE` |

Reject uncertain mapping/visibility, not merely known counterexamples. Routine
Unicode mapping is usable only with reviewed font/mapping proof; extracted code
points alone cannot prove what a glyph shows. Geometry may be inspected to REFUSE
invisible/clipped text, never to invent reading order, rows, columns or figures.
These are instrumented-backend proof obligations; metadata is not such proof.

### Reconciliation with A2b CRWV (design precedence, not admission)

[Guidance A2b](REVENUE_GUIDANCE_AUTOUPDATE.md) at lines 720-721 references
`_archive/lane-orders-v3-autoupdate/astra-contract-a2.result.md`, section 6
(SHA256 `DE949739CBCC28B5075E71CA4CE9152A423FEA40E1CF2AFAB816FEDBA3B21AB3`).
This extraction-only design proposes the following refinements for a LATER GO;
it neither edits that historical contract nor qualifies CRWV:

| A2 / initial F05B draft | Reconciled v1 decision and reason |
| --- | --- |
| A2 20000 objects; draft 100000 entries/200000 visits | Restore 20000 entries AND total visits (repeats charged): no unexplained A2 budget expansion |
| A2 10000 streams; draft omitted stream count | Retain 10000, including undecoded image streams: small-stream bombs also cost work |
| A2 16 MiB decoded/stream | Tighten to 8 MiB; retain 64 MiB document total; add per-stage/total 100:1 ratio to bound expansion earlier |
| A2 15 s CPU | Tighten to 10 s user-mode CPU and mandatory 25% rate cap to bound monopolization of the shared host; retain 30 s wall/512 MiB, with job-wide accounting so descendants cannot escape the budget |
| A2 4 MiB canonical text | Tighten to 2 MiB UTF-8 plus 256 KiB/page and 20000 spans to bound per-page buffering and locator/JSON overhead; separate4 MiB IPC is not a larger downstream envelope |
| A2 depth64/cycle detection | Retain depth64; add revision16 and filter-chain4 so many individually small revisions/decoders cannot accumulate unbounded work |
| A2 8192-character match region / 1000-character evidence passage | Retain for future consumer matching/evidence; extraction spans do not enlarge these ceilings |
| A2 page/row/column or bounding-box locators | Use page/raw-byte/operator provenance ONLY because flattened text cannot prove layout or column identity; CRWV quarter/FY table proof stays BLOCKED for a separately reviewed geometry adapter |
| A2 decorative logos potentially allowed | Refuse every image because v1 has no reviewed way to distinguish a logo from rasterized adverse content; no partial inspection |
| A2 unsupported filters/active content/mappings | Close stream/filter/parameter and inert-link lists to eliminate decoder/action loopholes; refuse zero-text/opaque streams and visibility divergence because complete inspection cannot be proven without extra grammar/rendering |

These are conservative design ceilings, not empirically qualified capacity
measurements. The opaque metadata/ICC/font-program and PNG-predictor refusals
narrow compatibility deliberately; they do not establish that those PDFs are
malformed. Missing later proof stays blocked, never an automatic ceiling increase.

Raw16 MiB, pages100, concurrency1, no network/credentials/OCR, bounded native
kill/reap and no partial-success policies remain. Every child's setup, parsing,
waiting, drainage and validation wall time (including failed jobs and admission
replay) is charged to the SAME updater run AND package budget. Its deadline is
the minimum of 30 s and both remaining budgets; no fresh sub-budget, parallel
allowance or excluded time. Distinguish the actual expired limiter:
- `TRUNCATED/DOCUMENT_WALL_LIMIT`: this document reached its own30 s ceiling;
  retain failed evidence, do not retry the same bytes/backend/policy as transport
  failure. A changed, independently reviewed extraction setup needs a new GO.
- `TRUNCATED/RUN_PACKAGE_BUDGET`: the enclosing run or package's remaining budget
  expired first (including no time to launch). A later adapter must map this to
  existing updater `WAITING` / reason `RUN_BUDGET`; that prefix is RETRYABLE in
  `scripts/revenue_guidance_autoupdate.py` (`RETRYABLE`; `Transport.remaining` raises it). Retain the
  attempt/captures and fair-queue place, then wait for a later ordinary invocation
  with genuinely fresh budgets. No in-run restart, refund, partial success or
  retry of a separately recorded deterministic document/resource failure.
If document and enclosing deadlines tie exactly, DOCUMENT_WALL_LIMIT wins so a
known document ceiling cannot be reclassified as a retryable budget pause. A
budget-only pause is not evidence that the document is a bomb or a success.
Existing request/capture/storage/envelope/fair-queue gates are not relaxed.
Both designs' unresolved dependency/native proofs stay open.

## Output and locator domains

Proposed strict JSON schema `f05b-pdf-spans-v1`: exact keys below, all required;
no additional/nested extension keys. Duplicate keys, nonfinite numbers,
bool-as-integer, invalid UTF-8/surrogates, overflow and unknown versions/enums
refuse. Parent validates child output independently. JSON nesting <=16 and framed
output <=4 MiB BEFORE decode. `H` below means exactly 64 lowercase hex SHA256
characters; `I(a,b)` means an integer in the inclusive range. Canonical digest
encoding: sorted-key compact UTF-8 JSON, `ensure_ascii=false`, no floats/BOM;
exclude ONLY `output_sha256` for the envelope digest. All text hashes use exact
UTF-8 bytes without normalization. A body digest proves integrity, not origin.

| Envelope key | Exact type / bound |
| --- | --- |
| `schema` | literal `f05b-pdf-spans-v1` |
| `state` | enum `SUCCESS`, `FAILED`, `TRUNCATED` only |
| `reason_codes` | unique string array: empty for SUCCESS, exactly one code from the closed table otherwise |
| `raw_body_sha256` | H, digest from verified captured bytes |
| `raw_bytes` | I(0,9007199254740991), measured captured length, also matched to the authenticated receipt except on CAPTURE_INVALID; >16 MiB is RAW_LIMIT, never parsed |
| `capture_binding_sha256` | null iff FAILED with the single pre-launch reason CAPTURE_INVALID, URL_NOT_ALLOWED or INPUT_NOT_PDF; H for every other result |
| `extractor` | exact object specified below, never null |
| `pages_total` | I(1,100); null on failure before complete bounded page-tree count (including >100) |
| `pages_examined` | I(0,100), completed pages; <=pages_total when known |
| `page_texts` | ordered array of page objects, <=100; [] on any nonsuccess |
| `spans` | ordered array of span objects, <=20000; [] on any nonsuccess |
| `output_sha256` | H, parent-computed canonical envelope digest |

`extractor` has exactly `name="pypdf"`, `version="6.18.1"`, `wheel_sha256:H`,
`wrapper_sha256:H`, `interpreter_sha256:H`, `limits_policy_sha256:H`. These come
from the independently admitted pinned backend manifest, NOT child claims. Until
that manifest exists (wheel hash still X), backend qualification is blocked and
there is NO conforming output; do not invent zero hashes or run the global reader.

Capture-binding preimage is an exact object: `schema="f05b-capture-binding-v1"`,
`receipt_sha256:H` (exact authenticated acquisition-receipt bytes),
`original_url` (allowlisted absolute HTTPS, 1..2048 UTF-8 bytes, no userinfo or
controls), `retrieved_at` (valid UTC `YYYY-MM-DDTHH:MM:SSZ`, 20 ASCII characters,
years2000..2099, not future at admission), `content_type="application/pdf"`,
`raw_bytes` and `raw_body_sha256` as above. Hash its canonical JSON. Each value
must equal the authenticated receipt; never reconstruct origin from a link,
mtime or caller-supplied digest. This is an ADMITTED capture preimage only.
Before launch, the exact closed refusal set `{CAPTURE_INVALID, URL_NOT_ALLOWED,
INPUT_NOT_PDF}` instead requires capture_binding_sha256=null, state=FAILED,
pages_total=null, pages_examined=0 and empty spans/page_texts. No preimage is
constructed for a disallowed URL, wrong/missing MIME type or failed receipt;
there is no invented application/pdf substitution. Header-only INPUT_NOT_PDF
also uses this null rule even if URL/MIME would otherwise pass. Null with SUCCESS,
TRUNCATED or ANY other failure reason is invalid. Raw body digest and measured
length remain mandatory for these diagnostics; absent body has no result record.

Nested schemas (all listed keys required). Every I(a,b) is an INCLUSIVE integer
value domain. Only each start/end offset PAIR denotes a half-open [start,end)
interval; neither the I endpoints nor array-count bounds are half-open:

| Object | Keys and types |
| --- | --- |
| Page | `page_number:I(1,100)`, `text:string` of 1..262144 UTF-8 bytes, `text_sha256:H` |
| Span | `page_number:I(1,100)`, `text_start:I(0,262143)`, `text_end:I(1,262144)`, `text:string` of 1..262144 UTF-8 bytes, `raw_ranges:array` of 1..64 Range objects |
| Object identity | `object_number:I(1,2147483647)`, `generation:I(0,65535)`; large/sparse identities never license proportional allocation |
| Range | `raw_start:I(0,16777215)`, `raw_end:I(1,16777216)`, `object:Object identity`, `kind:enum RAW_LITERAL or RAW_STREAM_CONTAINER`, `decoded_start` and `decoded_end` as below, `decoder_version` as below, `dependencies:array` of 0..32 Dependency objects |
| Dependency | `role:enum FONT or CMAP`, `object:Object identity`, `raw_start:I(0,16777215)`, `raw_end:I(1,16777216)` |

For every range/dependency, start < end <= raw_bytes; object identity must replay
to those captured bytes. Dependencies are unique by role/object/range; all fonts
and CMaps affecting the text must be included, not optional omissions. A literal
range covers the exact original literal token; only proven direct mapping permits
`RAW_LITERAL`, with `decoded_start=null`, `decoded_end=null`, `decoder_version=null`.
For `RAW_STREAM_CONTAINER`, raw range covers the exact encoded stream data bytes
(excluding stream/endstream delimiters), not a readable substring or the whole
file. `decoded_start:I(0,8388607)` and `decoded_end:I(1,8388608)` select the actual
text operator bytes in that stream after the admitted filter chain, start < end
<=decoded-stream length. `decoder_version` is the literal `pypdf-6.18.1/f05b-v1`;
wheel/wrapper hashes also bind its implementation. Contents arrays/nested Forms
need separate identified ranges; no ambiguous concatenated-stream offset domain.

SUCCESS requires pages1..pages_total in order, pages_examined=pages_total,
nonempty spans ordered by page then text_start, and exact, nonoverlapping,
complete coverage of each page text's UTF-8 bytes. Intervals must end at codepoint
boundaries and page bytes at each interval must equal span text bytes. Sum of
page text bytes <=2 MiB. No x/y-inferred whitespace/order, table cells or quote
normalization; join operator text deterministically in source execution order,
without invented separator bytes. A locator must map EVERY output byte through
the admitted decoder/font chain; pypdf-inserted layout spaces/newlines cannot be
presented as raw text. Unsupported/unmappable output refuses the whole result.
This extraction representation is not a layout or numerical-relationship proof.

Closed reasons and state mapping (no free text, no aliases):

| State | Reason codes and exact trigger class |
| --- | --- |
| SUCCESS | none: all pages/resources/locators validated, clean child exit and reconciled zero children |
| FAILED | `CAPTURE_INVALID` receipt/binding invalid; `URL_NOT_ALLOWED` source allowlist failure; `INPUT_NOT_PDF` header/media-type failure; `POLYGLOT` competing container/HTML identity; `TRAILING_DATA` unaccounted terminal bytes |
| FAILED | `MALFORMED_PDF` structure/xref/cycle/ambiguous revision/repair needed; `ENCRYPTED` any encryption; `EXTERNAL_STREAM` external resource reference; `UNSUPPORTED_FILTER` filter/parameter outside closed list |
| FAILED | `UNSUPPORTED_ACTIVE_CONTENT`, `UNSUPPORTED_ANNOTATION`, `UNSUPPORTED_STREAM_CLASS`, `IMAGE_CONTENT_UNREVIEWED`, `ZERO_TEXT_PAGE` as defined above |
| FAILED | `INVISIBLE_TEXT`, `HIDDEN_OPTIONAL_CONTENT`, `CLIPPED_TEXT`, `VISIBILITY_UNPROVEN`, `GLYPH_DIVERGENCE` as defined above |
| FAILED | `FONT_ENCODING` otherwise unsupported font/encoding; `LOCATOR_UNMAPPED` missing/invalid byte mapping; `INSPECTION_INCOMPLETE` resource/operator coverage not established |
| FAILED | `ISOLATION_LOST` runtime containment loss; `CHILD_CRASH` unexplained abnormal exit; `CANCELLED` explicit owned cancellation; `INVALID_OUTPUT` malformed IPC/schema/digest or unaccounted child lifetime |
| TRUNCATED | `RAW_LIMIT`, `PAGE_LIMIT`, `OBJECT_LIMIT`, `VISIT_LIMIT`, `STREAM_LIMIT`, `DEPTH_LIMIT`, `REVISION_LIMIT`, `FILTER_CHAIN_LIMIT` for the correspondingly named hard ceiling |
| TRUNCATED | `DECODED_STREAM_LIMIT`, `DECODED_TOTAL_LIMIT`, `EXPANSION_LIMIT`, `PAGE_TEXT_LIMIT`, `TOTAL_TEXT_LIMIT`, `SPAN_LIMIT`, `OUTPUT_LIMIT` for those hard ceilings (OUTPUT_LIMIT includes IPC/stdout/stderr flood or schema-array cap) |
| TRUNCATED | `JOB_MEMORY` job/process memory limit; `JOB_CPU` user-mode CPU-time limit; `JOB_PROCESS_LIMIT` attempted descendant; `DOCUMENT_WALL_LIMIT` own30 s expiry; `RUN_PACKAGE_BUDGET` enclosing run/package expiry (distinct retry mapping above) |

Every detected job-limit termination maps to TRUNCATED, never CHILD_CRASH merely
because the child was killed. Rate throttling alone is not termination; its
wall expiry is classified by the actual limiter above. Parent records the first
established terminal reason; for tied notifications priority is JOB_MEMORY,
JOB_CPU, JOB_PROCESS_LIMIT, DOCUMENT_WALL_LIMIT, RUN_PACKAGE_BUDGET, OUTPUT_LIMIT. For remaining tied
reasons use lexical code order; primary reason is diagnostic, never an eligibility
escape. Unknown termination -> FAILED/CHILD_CRASH, not a guessed resource cause.

The parent alone finalizes the envelope, including after child death or empty/
malformed output: use its pinned extractor descriptor and immutable capture,
only validated completed counts (else pages_total=null/pages_examined=0), discard
ALL page_texts/spans, choose the terminal reason above, and recompute output_sha256.
No usable numeric/quote output survives FAILED/TRUNCATED, nor a prior success
merge. If the parent dies, no finalized result exists; incomplete artifacts are
unusable. Backend statuses BLOCKED_ISOLATION/BLOCKED_CONTRACT never enter `state`
or `reason_codes`; the former draft's FAILED_UNSUPPORTED is replaced by FAILED
plus the specific closed unsupported reason, not another state. Zero-text's
former unspecified state is now FAILED/ZERO_TEXT_PAGE. Persist a local result
atomically only after validation and digest readback; public use still needs the
existing sealed, readback, pointer-last publication gate. A file is not success.

## Threats, consumers and later acceptance

Treat PDF text, links and metadata as untrusted data, never instructions. Apply
the closed identity/filter/annotation/visibility rules and state mapping above.
Unsupported content is ignored for execution/extraction, but its detection still
refuses the financial result; ignored does NOT mean irrelevant. Demonstrate
complete bounded page/resource/operator coverage, not only strings a backend
happens to return. Missing fonts, lost text or unexplained mapping refuse.

A future CRWV/F05B adapter may consume only SUCCESS, replayable, raw-bound spans
as **extraction evidence**, with original URL/capture time/event/issuer/period/
currency/accounting-basis provenance. It must compare complete relevant contexts,
handle competing outlooks and independently verify figures. No OCR, inferred
layout/table relationships, automatic guidance/score changes or NBIS bypass.
Existing HTML canonical character offsets require a new versioned adapter,
never relabelling PDF byte offsets. Downstream envelope overflow remains blocked.

Later GO acceptance (all synthetic cases plus separately permitted genuine CRWV
sources; no invented live proof):

1. Golden multi-page text/Unicode, each supported filter and font/CMap locator;
   raw-byte tamper, missing/deleted spans, operator boundaries, geometry-inserted
   whitespace, wrong page/end-boundary/hash/version, nested-key/type/array limits,
   capture preimage mutation and deterministic replay. No lost text passes SUCCESS.
2. Every resource boundary at limit/one-over, including stream count; recursive
   objects, xref loops, revision chains, object/filter/decompression bombs,
   corrupt/truncated trailers. Header offset0 positive; BOM/leading garbage,
   wrong/missing receipt Content-Type, disallowed URL, HTML/PDF polyglot and
   extra bytes after final EOF negatives. Every URL_NOT_ALLOWED and INPUT_NOT_PDF
   diagnostic (including header-only/wrong/missing MIME) must itself pass the
   output schema with null binding and zero page counts; test CAPTURE_INVALID
   likewise. Reject null binding for other reasons and any success, and reject
   forged success-style MIME/URL substitution. Each negative has its exact code.
3. Encrypted, JS/launch actions, forms, embedded files, external streams, unknown
   filters/DecodeParms and font failures; ordinary URI-free and permitted inert
   HTTPS Link positives versus HTTP/javascript/action-chain annotation negatives.
   Never decode image/inline-image streams: image-only, mixed text/image and logo
   fixtures all refuse in v1; blank/zero-text pages refuse too. No partial success.
   Text streams vs XRef/ObjStm: no-filter and Flate Predictor1 bounded positives;
   XRef Predictor12 and all PNG10..15, object-stream predictor/parameter/chain
   negatives; metadata/ICC/font-program/unknown-class fixtures refuse without
   invoking their decoders. Ambiguous role and nested object-container cases
   obey the same class table and memory/ratio limits.
4. Native job memory/CPU/wall/concurrency/descendant limits; crash/cancel, parent
   death, handle reuse, stdout flood and malformed/empty IPC; assert parent-written
   failure envelopes, deterministic tied-cause mapping and zero surviving children.
   No outside-root writes or network; failed native proof stays BLOCKED. Prove
   shared updater run/package wall charge, including failed extraction/replay.
   Own30 s limit vs early run/package expiry, zero remaining launch budget and
   tied deadlines must produce distinct exact codes; only RUN_PACKAGE_BUDGET
   maps to WAITING/RUN_BUDGET and later ordinary retry, with no clock reset.
5. Rendered/extracted divergence fixtures: render mode3, off/unknown optional content, off-page
   and partially clipped text, white-on-white/transparent/occluded text,
   ActualText/ToUnicode/Differences digit/currency/unit substitution and nested
   Form variants. Exact named failure with empty spans/page_texts for EACH case.
6. Real adapter and replay readers reject FAILED/TRUNCATED/stale/rebound spans;
   mirrors stay one lineage; unsupported layouts and competing guidance refuse.
7. Existing NBIS/A1 refusals, package/freshness/rights gates and public defaults
   remain unchanged. Writer and independent reviewer accept the same pinned
   dependency/wrapper/corpus; separate rollout authority is still mandatory.
