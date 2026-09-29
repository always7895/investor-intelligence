# Revenue guidance auto-update (ORDERS-V3-AUTOUPDATE-01)

Status: **Part A slice 1 (framework + NVDA + MU) accepted (`e89936f`); B0 shared prerequisites for Part B; shadow
only.** Nothing here is wired into the daily caller, the sealer or the Worker; production still reads only the curated registry and its human approval
(`config/revenue-guidance-v1.json`, `config/revenue-guidance-approval-v1.json`, see
[BOTTLENECK_TOP20_V3](BOTTLENECK_TOP20_V3.md)). The contract is Astra's `astra-contract.result.md` Part 2 in the lane
archive `_archive\lane-orders-v3-autoupdate\`; this page describes what slice 1 implements and what is still open.

Goal (operator 2026-09-29): after each results release the revenue-guidance record renews itself from official
filings without a human step. Anything that cannot be proven from the filings keeps the issuer suspended; numbers are
never guessed and old numbers never return after a newer results event has been seen.

## Components

| File | Role |
| --- | --- |
| `config/revenue-guidance-extraction-profiles-v1.json` | Reviewed per-issuer policy: the enumerated source/event/actuals adapter (only `SEC_8K_202_INLINE_XBRL_V1` is implemented; any other value is refused), enabled symbols, CIK, exhibit naming, guidance grammar, actuals concepts and measure, fiscal-calendar rule and quotes, IR/wire title grammar, the official IR host and page pattern, the wire page pattern. Runtime never edits it; any change needs writer + Astra review. |
| `scripts/revenue_guidance_auto_verify.py` | Pure verifier: captured bytes of one results event + profile + predecessor -> successor record and one decision per input, or a typed WAITING/BLOCKED outcome. No network, no writes, no clock. |
| `scripts/revenue_guidance_overlay.py` | State root: content-addressed captures, immutable generations, pointer; admission by re-derivation (`admit`, shared by readers and the updater); per-issuer resolution at a cutoff; the release-check gate. |
| `scripts/revenue_guidance_autoupdate.py` | Updater: reads the release-check cache, discovers the results filing, captures under hard limits, runs the verifier, publishes generations. CLI with an explicit state root and a hermetic replay mode. |
| `tests/test_revenue_guidance_autoupdate.py` | Replay chains through the real checker, adversarial cases, transport, lock, CLI and state tests. |
| `tests/fixtures/revenue-guidance-autoupdate/` | Public SEC, IR and wire bytes (gzip, named by the SHA-256 of the exact entity bytes), `inventory.json` with the genuine capture instants, `bootstrap-registry.json` (test baseline). Built by `tests/fixtures/make_revenue_guidance_autoupdate_fixtures.py` and `make_revenue_guidance_autoupdate_bootstrap.py` from the writer's capture directory `_workspace\audit-runtime\autoupdate-fixtures`. |

**One reference for the whole active claim set.** `revenue_guidance.guidance_reference(record)` returns the release-
check reference only when every active claim (its own document, or its latest reaffirmation) shares it, plus an
order-independent descriptor of all active claims (period, scope, basis, numeric source digest, reference); distinct
references are a conflict (no reference, so no receipt and no revenue), never the first or the newest claim's. The
release checker, the sealer's model gate and the auto-update admission use this one helper; every curated record is
unchanged by it. An automatic successor must have the single-reference shape (its release), and its ROUTING decision
binds the adapter, the proven report period and the reference descriptor.

The profile file and the state files are validated in code (`validate_profiles`; `validate_generation` for the
envelope, `validate_attempt` for every nested event, capture map, decision and detected document). There are no
separate JSON Schema files: the runtime validators are the one definition (Astra accepted this substitution on the
condition of equivalent strictness and malformed-input coverage).

## Loop

```
release check (existing checker, over the effective records)
  -> updater: admit the chain; material documents ever listed for the effective record's reference, plus recorded
     detections, that the record did not consume
  -> results 8-K (item 2.02) -> detection committed -> capture -> verifier -> VERIFIED | WAITING | BLOCKED
  -> new immutable generation, pointer moved
  -> resolver at a cutoff: admission by re-derivation, then the release-check gate for every usable record
```

1. **Detection.** The existing release checker (`scripts/revenue_guidance_release_check.py`) runs over the *effective*
   record of each issuer (the curated record, or the newest admitted automatic successor, also while the issuer
   waits). A later document is *material* when its disposition is `RESULTS_RELEASE` or `POSSIBLY_RELEVANT` in any
   receipt of that reference up to the cutoff, or was recorded as detected earlier, and the record did not consume it.
   At the start of every run, before anything is fetched for any issuer, the updater adds every material document to
   the issuer's monotonic detection set (`detections` in the generation, at most 256 entries; beyond that the issuer is
   suspended as `DETECTIONS_OVERFLOW`) and commits it. A later feed read that no longer lists an item, the checker's
   receipt retention, a retry or a crash while another issuer is fetched never clears it; only the admitted,
   re-derived producer accounts for an item (below), no older decision does. When a verified successor becomes
   the reference, everything detected against the old reference is carried over: a document leaves only when the
   successor consumed it (typed identity) or when it is dated strictly before the successor's own filing day (that
   later, complete release supersedes it); a same-day or later document stays unresolved. A human
   `REVIEWED_IRRELEVANT` entry of a curated record also accounts for it.
2. **Event.** A material EDGAR `8-K items …2.02…` filing is a results event (oldest first). Before anything is
   fetched the updater commits a generation with a `WAITING`/`EVENT_DETECTED` attempt carrying the complete unresolved
   material set, so a crash, an outage or the later reference change cannot forget any of it. Material documents without a supported results filing (a 10-Q alone, a 6-K, an unrelated same-day
   press release, an unclassified 8-K) make the issuer **WAIT** (`EVENT_UNRESOLVED`).
3. **Capture.** Public HTTPS GET only, bound to the issuer's profile: `data.sec.gov/submissions/CIK##########.json`;
   `www.sec.gov/Archives/edgar/data/<CIK>/<accession>/index.json` and every HTML document of the results filing (the
   release exhibit, the form, commentary exhibits; at most 8); the 10-Q/10-K of each needed quarter end, the newest
   10-K and the newest periodic report; the official IR page listed for that day on the profile's IR host; the Nasdaq
   wire page listed for that day. Bytes are stored content-addressed and never overwritten.
4. **Verification** (all must hold, else a typed outcome); every identity comes from the captured bytes, the event
   passed in is only a lead:
   - form, items, filing date, primary documents and report dates from the captured submissions feed; exhibit and
     package membership from the captured accession index; every capture belongs to the issuer's CIK, was retrieved
     before the decision, and its filing was filed on or before the decision day;
   - no withdrawal, suspension, non-reliance/restatement or revision of earlier guidance anywhere in the results
     package (sentence-local detectors in active, past and passive voice; "Amended and Restated" plans and charters
     excluded; zero false positives on the captured NVDA/MU packages and IR/wire copies);
   - exactly one revenue outlook: NVDA the outlook sentence under its `Outlook` heading, MU the outlook tables whose
     GAAP and non-GAAP columns in both tables state the identical point and band; any competing candidate blocks;
   - the guided quarter is the quarter after the one the release's summary table leads with; the guided point is
     within 0.25x-4x of that quarter's revenue (a unit or scope error otherwise);
   - four trailing quarters, each from the inline XBRL of the periodic filing that EDGAR and its own cover
     (`dei:DocumentType`, `dei:DocumentPeriodEndDate`) say reports that quarter, filed after its end: names compared
     as (namespace URI, local name) against the reviewed US-GAAP, DEI and ISO 4217 namespaces, each resolved in the
     XML scope of the element that carries it: the inline XBRL is read with a namespace-aware XML parser (elements by
     namespace, prefixes case-sensitive and scoped, attribute text never declares anything) after removing only
     EDGAR's one injected watermark/script fragment; a document that is not well-formed XML, declares entities, carries
     the fragment twice, binds a prefix to two namespaces or uses an unbound prefix is an unsupported template (any
     prefix spelling is otherwise accepted); only the supported shapes are read - a simple unit is exactly one direct
     measure, a context has one entity with one identifier and one period that is one start plus one end date, one
     instant or forever, nothing first-matched (a fact on any other context shape blocks); exact start/end, no dimension
     in `segment` or `scenario`, the issuer's CIK, a unit whose measure resolves to ISO 4217 `USD`, a number format
     that resolves in the fact's scope to a reviewed transformation (`num-dot-decimal` or `fixed-zero` of the
     2020-02-12 inline XBRL transformation registry; no format means a plain decimal), a supported scale, and one value across every fact of every reviewed equivalent concept; the fourth fiscal quarter
     as the 10-K year minus the third-quarter 10-Q nine months, each operand under the same complete rule;
   - the release's own revenue for the reported quarter equals the filing's value exactly;
   - the fiscal-calendar rule sentence quoted verbatim from the newest 10-K on EDGAR; each 53-week year touched needs
     the issuer's own statement that its fourth quarter has 14 weeks (otherwise **WAIT** `CALENDAR_ALLOCATION_UNPROVEN`);
   - the official IR page at exactly the listed address, titled for the reported quarter on the filing day, states the
     same outlook passage (whitespace and bullets aside) and no other revenue outlook, else
     `INCOMPLETE_EVENT_COVERAGE` (waiting while it is not listed yet); the wire page is consumed only under the same
     proof, otherwise it stays unaccounted; each consumed page is checked as a whole publication: the same reviewed
     structural extraction must find exactly the verified outlook (any other, malformed or unsupported outlook in a
     recognised template blocks as `SOURCE_DISAGREEMENT`), and a withdrawal, restatement or revision on it blocks;
   - the successor passes the registry's `validate_issuer_record`.
5. **Record.** The successor uses the existing `revenue-guidance-v1` record schema with the exact passage span of the
   canonical release text (`canonical[a:b] rg-canon-1`) and one decision per input (`CLAIM`, `ACTUAL` per quarter and
   for the release row, `CALENDAR`, `ROUTING` with the typed consumed identities `(channel, id, date)`), each naming
   its own capture. Nothing numeric is inherited from the predecessor.
6. **Generations.** Each run that changes anything writes a new immutable generation (per issuer a constant-size
   entry: the head of a hash-linked chain of immutable segments of 32 attempts in `segments/<sha256>.json`, the sealed
   count, up to 32 open attempts - no lifetime limit, nothing deleted - and an index of the newest verified attempts'
   locations (at most 8) and of the events settled since the current producer's filing day; its detection set; parent digest, verifier/normalizer versions, the digest of the installed implementation files
   `revenue_guidance.py`, `revenue_guidance_auto_verify.py`, `revenue_guidance_overlay.py`, and the digests of the
   profile, baseline registry and approval files) and then atomically moves `current.json`. An operating-system lock
   excludes a second updater. When any identity changes, the updater first re-derives each issuer's producer under
   the installed identity from its captures (one per issuer). If it reproduces the stored decision nothing changes;
   otherwise a new decision is taken from the same captures and appended (never rewriting a stored attempt or
   segment): verified, it becomes the producer; otherwise the verified attempt before it becomes the producer,
   re-derived at admission. Publication checks only the segments it writes; older segments are immutable references
   carried on, so missing audit history never stops another issuer.
7. **Resolution** (`overlay.resolve_issuers`) at a cutoff selects the newest generation created at or before it and
   admits its issuers' state (`admit`; every attempt admission reads - open attempts, producer, predecessor, newest -
   must be dated at or before both the cutoff and the generation's creation, else the issuer is `STATE_CORRUPT`; every decision must match the machine decision
   contract: exact operand keys per kind, one CLAIM/CALENDAR/ROUTING and the ACTUALs, typed consumed identities).
   Admission work is bounded per issuer: it validates the open attempts (at most 64), re-derives the producer (the
   newest verified attempt, located by the index) from its stored bytes with its predecessor record (the verified
   attempt before it, or the curated record) as the only input, and reads the newest attempt for the mode - at most
   three sealed segments, independent of history length. A missing or altered segment it needs blocks that issuer. Older attempts are not operative: a
   successor inherits no number, only the predecessor's anchor for ordering, its release channels come from the
   curated baseline record, and unresolved detections are accounted for only by the re-derived producer (its consumed
   identities and items dated strictly before its filing day). A `VERIFIED` attempt counts only when the installed
   verifier re-derives exactly the stored record and decisions from the stored capture bytes, from its hash-linked
   predecessor record, under unchanged identities. `verify_history` is a structural audit off this path (the segment
   chain present, hash-verified and linked, every attempt's shape and time order, the sealed count, the index); it does
   not re-derive sources. With the release-check cache, every usable
   record - curated or automatic, with or without any auto-update state - must pass `receipt_gate`: the newest check
   of its own reference passes the registry's strict `validate_receipt` (issuer, digest, coverage, channel set and
   hosts, anchor, reference, age at most 24 h, recomputed status), and no material document ever listed or detected
   for that reference is left unaccounted. The updater uses the same admission, so unadmitted state never steers a
   capture.

## Outcomes

| Mode | Meaning | Revenue path |
| --- | --- | --- |
| `CURATED` | No automatic attempt yet: the curated record with its human approval. | usable after the gate |
| `AUTO_VERIFIED` | Admitted machine-verified successor. | usable after the gate |
| `WAITING` | Detected event waiting: `EVENT_DETECTED`, `WAITING_PERIODIC_FILING`, `CALENDAR_ALLOCATION_UNPROVEN`, `INCOMPLETE_EVENT_COVERAGE` (IR copy not listed yet), `EVENT_UNRESOLVED`, `NETWORK_UNAVAILABLE`, `CAPTURE_LIMIT`. Retried by later ordinary runs; an unchanged wait writes nothing. | suspended |
| `BLOCKED` | Deterministic refusal: `WITHDRAWAL`, `RESTATEMENT`, `REVISION`, `AMBIGUOUS`, `PERIOD_MISMATCH`, `UNIT_MISMATCH`, `SOURCE_DISAGREEMENT`, `NO_MATCH`, `UNSUPPORTED_TEMPLATE`, `OUT_OF_ORDER`, `CALENDAR_RULE_UNPROVEN`, `ACTUAL_NOT_FOUND`, `RELEASE_ROW_NOT_FOUND`, `INPUT_MISSING`, `INPUT_MALFORMED`, `RECORD_INVALID`, `APPROVAL_BINDING`, `STATE_CORRUPT`, ... Not re-fetched; a later results release can still renew the issuer. | suspended |
| `SUSPENDED` | Usable record whose release check is missing, invalid, stale, incomplete or lists an unaccounted material document (`RECEIPT_*`), or whose detection set overflowed (`DETECTIONS_OVERFLOW`). | suspended |

Invalid, corrupt, foreign or replay state never improves availability: a broken chain, changed capture bytes, a
rehashed record or event identity, a changed implementation/profile/baseline identity (until re-verified) or a
malformed attempt blocks that issuer (`APPROVAL_BINDING` / `STATE_CORRUPT`); a missing or unreadable pointer or
generation blocks every enabled issuer; issuers without attempts keep the curated path (still gated). Captures made by
the hermetic replay transport are marked `REPLAY_*` and admitted only with `allow_replay=True` (tests).

Expected latency: a release is seen by the first release check after it and verified by the same run's updater once
EDGAR lists the 8-K, the exhibit and the quarter's 10-Q/10-K and the issuer's IR site lists the release. NVDA files its
10-Q on the release day; MU files its 10-Q a day later and its 10-K about ten days after the fiscal-fourth-quarter
release, so MU's September release waits (`WAITING_PERIODIC_FILING`) until the 10-K is on EDGAR. No extra seals or
manual steps are added.

## Limits (updater)

Scheduling: after the detection phase, issuers with work are served in a fair order that starts after the issuer
served last; that position (`queue.json`, a scheduling hint, never an admission input) is written before fetching
for an issuer, so a source that crashes or exhausts its own budget cannot starve the others across runs. When the
run's shared budget (wall time, requests, new capture bytes) is spent, the remaining issuers are not attempted and an
issuer that got no service keeps its place at the head of the next run. A plan interrupted by a budget, quota or
network failure keeps the captures it stored referenced by its attempt; EDGAR archive documents captured by any
earlier attempt are reused from the store (re-hashed and re-verified), feeds and IR/wire pages are always read again,
so repeated interruptions still make progress (a superseding wait keeps the captures already referenced). A wire
page that cannot be fetched because of a budget or a transient failure makes the attempt wait for the next run; only a
refused page (for example HTTP 404) leaves the wire copy unconsumed. An issuer whose history cannot be read (for example a missing or
altered segment) is carried forward unchanged as its own fail-closed barrier while the other issuers keep committing.

HTTPS on 443 only; hosts `www.sec.gov`, `data.sec.gov`, the profile's IR host and `www.nasdaq.com`, each with
issuer-bound or reviewed path patterns; no query, userinfo, percent-encoding or traversal; **no redirects are
followed** (a 3xx refuses); every resolved address must be public and the connection is made to that checked address
(TLS name and certificate verified for the host); SEC contact headers are sent only to SEC hosts, other hosts get a
plain public user agent; `Accept-Encoding: identity`, other encodings and unexpected media types refused; bodies
streamed under 8 MiB (submissions), 1 MiB (index), 16 MiB (documents), 4 MiB (IR and wire pages), error bodies read at
most 64 KiB; 30 s timeout; at most 2 attempts for a transient failure, `Retry-After` honoured up to 30 s; 24 requests
per issuer and 120 per run; 10 minute wall budget; 0.5 s pacing; 128 MiB new captures per run; 2 GiB store quota
(reaching it waits, nothing is deleted). Usage comes from a reservation journal, `store_usage.json`: a new object's
bytes are added and named pending before any file is written, and cleared after its raw and metadata commits, so an
interruption in any window only over-counts; each run first settles the pending reservations (at most 16: a written
object stays counted, an unwritten one is released and its incomplete temporary file removed) and enumerates nothing.
If the journal is missing or malformed for a non-empty store, new captures wait (`store_accounting: UNKNOWN` in the
summary; detections still commit) until the maintenance command `--recount-store` rebuilds it from the objects on disk
(temporary leftovers counted too, nothing deleted). Parser: 16 MiB document, 4 MiB canonical text, 1,000-character passages,
reviewed regexes of at most 400 characters. SEC contact headers come from the existing in-memory `sec_contact_headers`
handoff.

## CLI

```
python scripts/revenue_guidance_autoupdate.py --state-root <empty or existing state root>
       [--replay <fixture or capture dir> --as-of YYYY-MM-DDTHH:MM:SSZ]
       [--profiles ...] [--registry ...] [--approval ...] [--receipts ...]
```

`--state-root` is mandatory and must be empty or an existing auto-update root (never an unrelated directory such as
the runtime cache). `--as-of` is accepted only with `--replay`. Exit 0 with a JSON summary (per issuer `NO_EVENT`,
`SETTLED`, `WAITING`, `BLOCKED` or `ATTEMPTED` with its outcome); exit 2 with `SYSTEMIC_FAILURE` for lock, state,
receipt-cache or persistence failures and any unexpected error.

## Proven by slice 1

- Real replay chains from the test baseline (`bootstrap-registry.json`, each issuer as of the release before the
  chain) through the real release checker over complete replayed SEC, wire and IR feeds, the updater and admission:
  NVDA 2026-02-25 -> 2026-05-20 -> 2026-08-26 and MU 2025-12-17 (waiting on its release day, verified after its 10-Q)
  -> 2026-03-18 -> 2026-06-24. Every guidance endpoint, trailing quarter (with Q4 derivation operands) and forward
  interval equals values typed from the filings, and the last links equal the curated production records (US$108.0B
  ±2%, Q3 FY27; US$50.0B ± US$1.0B, FQ4-26).
- MU's FQ4-26 successor passes its own complete next-day release check (the checker alone says `REVIEW_REQUIRED`
  because of the same-day 8-K and wire copy; both are its proven consumed event) and is usable; the curated baseline
  is suspended by the gate as soon as its results filing is listed, before any auto-update state exists.
- NVDA's Q3 FY27 successor stays suspended: its own check lists the unrelated same-day IR release of 2026-08-26 (AWS
  agreement), which nothing accounts for automatically.
- Idempotence, historical cutoffs, detection committed before fetching, crash and outage after detection, no clearing
  by omission or receipt retention (an item first seen during a repeated outage survives eight later checks and the
  successful retry), detections carried across the reference change (a later or same-day item keeps the successor
  suspended, an earlier one is superseded), the detection-overflow barrier, re-verification after an identity change, and tamper, forgery,
  corruption, namespace and transport cases (see the test file; the key defences are mutation-checked).

## Open (later slices and Part B)

- **A2:** CRWV (quarter and full-year guidance in the official IR outlook presentation) and NBIS (6-K EX-99.1 tables
  and EX-99.2 guidance/reaffirmation, 6M-minus-Q2 derivation) with explicit event/source adapters, active-claim
  reference selection for concurrent claims and reaffirmations, and report-period-driven event plans (Astra A1-r2).
  **A3:** LITE, CRDO, BE, AMD, MRVL profiles. Before scaling: a persisted fair queue and demonstrated total
  request/wall/disk budgets with several waiting issuers; bounded attempt-history growth without deleting evidence.
- **Autonomy gap (Astra ruling 2026-09-29):** Part B may add a reviewed, versioned, positive-template classification of
  earnings-date notices (complete official item captured, announcement-only template, issuer, period and a future
  results date proven, whole-item exclusion checks, a distinct machine disposition bound to the bytes and replayed at
  admission). Unrelated same-day press releases and generic 8-Ks stay suspended until a later verified release or a
  human review; keyword absence never clears an item.
- **Part B order (Astra `astra-priority-partb.result.md`):** B0 (this batch: adapter enum, shared reference,
  decision contract, fair queue, history segments), then B1 effective-input loader, B2 daily caller and dirty state,
  B3 sealed evidence and Worker readers, B4 package/end-to-end/rollout plan, all for NVDA/MU; then A2a NBIS and A2b
  CRWV (`astra-contract-a2.result.md`) and A3. In detail: wire the checker over effective records and the updater into `run_daily_data_refresh.ps1`; the shared
  effective-input loader for `order_forecast.py`/`publish_sealed_snapshot.py` with the release-check gate; the
  guidance-input dirty marker and ranking rebuild; the sealed `auto_update` evidence subrecord and Worker readers
  (`「官方財報自動核對（發布 YYYY-MM-DD）」`, typed `AUTO_UPDATE_BLOCKED`/`AUTO_UPDATE_WAITING` reasons); packaging;
  reader-first rollout under its own plan and Astra go/no-go.
