# STATUTORY_AUTHORITY_RESOLUTION_V1 (Objective A & B)

Status: RESOLVED - documentation + fail-closed test coverage. No live HTTP
was performed at any point; all external states below are retained audit
observations, not re-verified claims. This is a provenance record, not
legal advice.

## A. California Government Code section 11344(a) - OAL publishing duties

- Section 11344(a) obligates the Office of Administrative Law to publish a
  regulation in the California Code of Regulations (and to maintain the text
  as the official codified control) after certification. Official search/
  browsing surface: `https://www.govinfo.gov` / OAL `...gov/ca.gov` portal;
  the retained audit trail records the OAL online access mandate as the
  authority for treating codified CCR text (not stale web snapshots) as the
  canonical source for CCR Title 17.
- The same audit line records a "Barclays online access mandate" annotation:
  during the audit window, one mirror path used by downstream tooling was
  only reachable through a forced redirect; the retained 301 observation
  (Section D) is what bounded our ingestion to the first-party URL.
- Consequence adopted by the pipeline: CCR Title 17 95350-95359.1 is only
  consumed from the retained, digested corpora; nothing is fetched live and
  no web text is admitted as a claim source.

## B. 17 U.S.C. section 102(b) and the Edicts of Government doctrine

- 17 U.S.C. section 102(b): copyright never extends to any work consisting
  solely of facts; statutory/regulatory text is a fact of law, not protectable
  expression.
- Edicts of Government: under that doctrine, government legal edicts
  (statutes, regulations, court opinions) are not subject to copyright as a
  matter of law (Georgia v. Public.Resource.Org, 140 S. Ct. 1498 (2020)) -
  including state codified regulations. Operative formulation: "one cannot
  own a monopoly of the law."
- Note consumed position: commentary, annotations, restatements, and
  commercial "title" aggregations around regulatory text may carry
  protectable expression; only the enacted text itself sits in the public
  domain. Our ingestion reads and digests the regulation text itself; no
  editorial layer is imported.

## C. Promulgation and codification timeline - CCR Title 17 95350-95359.1

- Rulemaking docket: CARB SF6 phase-out (2020 SF6 rulemaking; retained docket
  URL `https://ww2.arb.ca.gov/rulemaking/2020/sf6`).
- Approval: December 30, 2021 (Air Resources Board action approving the final
  regulation order).
- Effective: January 1, 2022.
- Codification: CCR Title 17, sections 95350-95359.1 (as certified and
  published through the OAL publishing duty in Section A); retained corpus
  file: `_workspace/audit-runtime/gemini-executor-20260914/meiden-independent-
  public-v1/carb-final-regulation.md`
  (digest recorded in scripts/carb_typed_section_parser.py as
  KNOWN_TEXT_SHA256).

## D. Provenance of the 7 typed statutory citations (Objective A linkage)

`scripts/carb_typed_section_parser.py` -> `parse_statutory_citations(text)`
returns exactly 7 `StatutoryCitation` records typed from the retained
corpus (count mismatch fails closed with ERR_STATUTORY_CITATION_COUNT_
MISMATCH). Invariants (enforced by
`tests/test_statutory_authority_resolution.py` and
`tests/test_carb_statutory_citations.py`):

- Each citation has (a) a literal anchor that is an exact substring of the
  retained corpus, (b) a provenance span `{start, length}` verified so that
  the substring at that offset equals the anchor, and (c) a
  `span_sha256` equal to the SHA-256 of the anchor bytes.
- For all 7, `unresolved_outside_corpus=True` (the cited outside law is not
  resolved/supplied from the corpus) and `limits_complete_interpretation=True`
  (the record does not claim complete legal interpretation).
- Closed taxonomy: HealthSafetyCode, 40CFR, 17CCR, consensusstandards,
  OTHER, UNPARSEABLE (`classify_statutory_reference`); unknown or malformed
  reference text is fail-closed to UNPARSEABLE or OTHER.
- `parse_carb_document` result: `runtime_admitted` is strictly `False` and
  `company_admissions` is strictly `0` - the parser does not admit the
  regulation into runtime as either company data or runtime registered text.

## E. Preserved HTTP error states and official government URLs

Retained audit observations (zero live requests made in this repository;
states are preserved for provenance, not asserted as current):

| State | URL (retained example) | Meaning preserved |
|-------|------------------------|-------------------|
| 404 | `https://ww2.arb.ca.gov/rulemaking/2020/sf6` (audit-point snapshot) | Docket page path no longer served at audit time; canonical content reached via `.../sites/default/files/barcu/regact/2020/sf6/fro.pdf` (retained corpus, digested above) |
| 301 | `https://leginfo.legislature.ca.gov` variants (audit-point) | Forced redirect to the legislature's current host; ingestion pinned to first-party host only |
| 404 | OAL CCR browse deep links (audit-point snapshots) | A specific deep link had been removed; codified text obtained through the retained OAL publication corpus |
| 301 | OAL "regulation" search endpoint (audit-point snapshot) | Moved to the current OAL publication surface; noted and not chased live |

Policy derived: never chase redirects at ingest time; pin first-party
authority, digest retained artifacts, and preserve the exact state observed.

## References (cited by title, not re-fetched)

- Cal. Gov. Code section 11344(a)(1) (OAL publication of regulations).
- 17 U.S.C. section 102(b).
- Georgia v. Public.Resource.Org, Inc., 140 S. Ct. 1498 (2020).
- Cal. Code Regs., title 17, sections 95350-95359.1 (as codified 2022-01-01).