# Company Evidence Candidate Text Validation

**Lane:** `COMPANY_EVIDENCE_RESEARCH_V1`

**Script:** `scripts/company_evidence_candidates.py`

**Test Suites:**
- `tests/test_company_evidence_candidates.py`
- `tests/test_company_evidence_candidates_review.py`
- `tests/test_company_evidence_candidates_cli_safety.py`

## 1. Overview & Purpose

The `company_evidence_candidates.py` producer checks candidate passages against provided public-research texts and declared receipt hashes.

It is a candidate consistency checker, **not** independent corroboration, publisher authentication, a ranking engine or publication workflow. Matching hashes and passages do not authenticate caller-provided receipts, establish issuer identity, or grant source rights. Use only an operator-approved public collection; this CLI is not a filesystem sandbox.

### Core Architectural Principles
1. **Passage Verification != Bottleneck Admission:** Matching a passage proves only that the provided text contains it; authenticating the document and determining its speaker or meaning are separate checks. It does **not** grant runtime bottleneck admission, factor score bonuses, or report promotion. Output status is strictly locked to `RESEARCH_CANDIDATE` with `passage_status: PASSAGE_MATCHED` and `economic_validation: TEXT_ANCHOR_ONLY_ECONOMICS_UNVERIFIED`.
2. **Strict Roundtrip Invariant:** Every verified candidate anchor satisfies the invariant `original_text[char_offset : char_offset + char_length] == exact_passage`. Match mode is explicitly recorded as `EXACT`. Normalized fallback offsets that mismatch original text are quarantined.
3. **Context Connection Verification:** Supplied `passage_context` must verifiably enclose the selected `exact_passage` span in the source document. Disconnected or out-of-section contexts are quarantined with `CONTEXT_NOT_CONNECTED_TO_PASSAGE`.
4. **Repeated Passage Disambiguation:** Short quotes occurring multiple times in a document require enclosing context to disambiguate the target occurrence. Without unique context, repeated quotes are quarantined with `AMBIGUOUS_REPEATED_PASSAGE`.
5. **No Unearned Role Promotion:** Document-level role (`document_source_role: ISSUER_PUBLISHED_DOCUMENT`) is taken from declared source metadata, not established as authoritative by this tool. Proposals claiming `INDEPENDENT_THIRD_PARTY_AUDIT` or counterparty validation on issuer documents are overridden to `effective_source_role: ISSUER_PRIMARY`.
6. **No Default Promotion:** Missing semantic metadata defaults to `UNKNOWN` (geography) or `UNREVIEWED` (period_type, proposed_label). Affirmative defaults (`SUPPORTED`, `HISTORICAL_REALIZED`, `GLOBAL`) are strictly prohibited.
7. **Destination Immutability & Anti-Destruction (Review 2):**
   - Output destination paths pointing to existing files, symlinks, or any input file (`--sources`, `--proposals`, or referenced source text files/receipts) are rejected *before* opening.
   - Output writing uses exclusive file creation (`os.open` with `O_CREAT | O_EXCL`) to close TOCTOU race conditions.
   - Complete JSON is serialized before opening the destination, avoiding serialization-failure truncation. A later I/O failure can still leave a partial new file; this is not atomic publication.
8. **Output Privacy & Static Error Codes (Review 2):**
   - Standard output emits strictly counts and static status; raw destination paths and private canary tokens are never printed.
   - All exceptions and CLI errors emit bounded, static code-defined error strings without echoing user input or file arguments.
9. **Strict JSON Parsing & Scalar Typing (Review 2):**
   - Non-finite numbers (`NaN`, `Infinity`, `-Infinity`) and duplicate object keys in JSON inputs are rejected fail-closed.
   - Deep nested structures (>10 levels) are rejected fail-closed.
   - Metric values are restricted to finite scalars (`int`, `float`, or bounded `str`); boolean numeric coercion (`True` / `False`) is strictly rejected (`INVALID_VALUE_TYPE`).
10. **Aggregate Resource Budgeting (Review 2):**
    - Enforces aggregate source byte budgets (<= 50 MB), count caps (<= 50 sources, <= 50 receipts, <= 100 proposals), and manifest `record_count` consistency before deep reading.
11. **Worker Ranking Lane Preserved:**
    - Worker ranking behavior is not tested or changed by this component. Consult STATUS for its current defects. Fallback behavior across Worker is marked `RANKING_WORKER_NOT_EVALUATED`. Runtime admitted claims remain strictly 0.

---

## 2. CLI Contract

```bash
python scripts/company_evidence_candidates.py \
  --sources <path_to_research_sources.json> \
  --proposals <path_to_proposals.json> \
  --output <path_to_output_candidates.json>
```

### CLI Exit Codes and Output Behavior
- `0`: Validation complete; output written exclusively. Output summary on stdout:
  `VALIDATION_COMPLETE: validated_candidates=<N> quarantined_proposals=<M>`
- `1`: Validation error or input missing. Output on stderr:
  `VALIDATION_ERROR: <STATIC_ERROR_CODE>: <Description>`

---

## 3. Security & Validation Gates

| Gate | Check | Action on Violation |
| :--- | :--- | :--- |
| **Output Immutability** | Rejects existing file, symlink, or input-aliased destination | Fails closed with `OUTPUT_FILE_ALREADY_EXISTS` / `OUTPUT_PATH_ALIASED_TO_INPUT` |
| **Exclusive target creation** | Uses `O_CREAT \| O_EXCL` | Prevents replacing an existing target; does not prove all parent-directory races are excluded |
| **Output Privacy** | Omits raw paths and canary strings from stdout/stderr | Emits static codes and numeric counts only |
| **Strict JSON** | Rejects `NaN`, `Infinity`, duplicate keys, deep nesting (>10) | Fails closed with `NON_FINITE_NUMERIC_REJECTED` / `DUPLICATE_KEY_REJECTED` |
| **Scalar Types** | Prevents boolean numeric coercion in metric values | Quarantines proposal with `INVALID_VALUE_TYPE` |
| **Resource Budget** | Caps aggregate bytes (<=50MB), sources (<=50), receipts (<=50) | Fails closed with `EXCEEDED_AGGREGATE_BYTE_LIMIT` / `EXCEEDED_COUNT_LIMIT` |
| **Record Count Consistency** | Verifies `record_count == len(sources)` in manifest | Fails closed with `RECORD_COUNT_MISMATCH` |
| **HTTPS Only** | Rejects `http://` or non-standard schemes | Fails closed with `HTTPS_REQUIRED` |
| **Private/Local IP** | Rejects `localhost`, `127.0.0.1`, RFC1918 private IPs, octal/hex IPs | Fails closed with `PRIVATE_IP_REJECTED` |
| **Path Traversal** | Rejects `..`, `/`, `\` in `text_file` or receipt paths | Fails closed with `PATH_TRAVERSAL_REJECTED` |
| **Symlink files** | Checks `is_symlink()` | Rejects detected links; Windows junction/ancestor-race containment is not established by this check |
| **Cryptographic Hashes** | Verifies on-disk SHA256 matches `text_sha256` and receipt sha256 | Fails closed with `HASH_MISMATCH` |
| **Forbidden Keys** | Detects caller-injected `status: "ADMITTED"`, `bottleneck_score`, `score`, `rank` | Quarantines proposal with `FORBIDDEN_CALLER_STATUS_OR_SCORE` |
| **Roundtrip Invariant** | Asserts `original_text[offset : offset + length] == exact_passage` | Quarantines proposal with `ROUNDTRIP_INVARIANT_FAILED` |
| **Context Connection** | Verifies `passage_context` encloses `exact_passage` in source | Quarantines proposal with `CONTEXT_NOT_CONNECTED_TO_PASSAGE` |
| **Disambiguation** | Requires enclosing context to isolate repeated occurrences | Quarantines proposal with `AMBIGUOUS_REPEATED_PASSAGE` |

---

## 4. Proposal Schema Definition

Illustrative synthetic proposal shape (requires its own matching fixture text and manifest; not market evidence):

```json
{
  "schema_version": 1,
  "lane": "COMPANY_EVIDENCE_RESEARCH_V1",
  "scope": "COMPANY_EVIDENCE_RESEARCH_V1_REVIEW2_PROPOSALS",
  "notice": "Analytical proposals to be validated against verbatim primary source texts via EXACT match mode.",
  "proposals": [
    {
      "claim_id": "SYNTHETIC-REVENUE-001",
      "company_id": "EXAMPLE_ENERGY",
      "legal_entity": "Example Energy — synthetic fixture",
      "segment": "Synthetic equipment segment",
      "product_or_spec": "Power grid systems and transmission equipment",
      "geography": "Global",
      "metric": "revenue",
      "value": 12,
      "unit": "BUSD",
      "denominator": "Synthetic FY2025 period",
      "financial_period": "FY2025",
      "period_type": "HISTORICAL_REALIZED",
      "source_id": "synthetic-report",
      "source_role": "UNREVIEWED",
      "exact_passage": "Example Energy revenue was 12 BUSD in FY2025.",
      "passage_context": "SYNTHETIC FIXTURE. Example Energy revenue was 12 BUSD in FY2025.",
      "page_or_location": "Synthetic fixture paragraph",
      "proposed_label": "UNREVIEWED",
      "premises": ["Synthetic example only"],
      "falsifiers": ["No real-world assertion"],
      "missing_independent_counterparty_proof": ["Not provided"],
      "operating_vs_equity_boundary": "No real equity capture established",
      "effective_substitutes_gap": "High-voltage transmission and transformer equipment market ..."
    }
  ]
}
```

---

## 5. Output Candidate Schema

The output generated by `company_evidence_candidates.py` contains:
- `summary`:
  - `total_proposals`: Integer
  - `validated_candidates`: Integer
  - `quarantined_proposals`: Integer
  - `runtime_admitted_claims`: 0 (strictly zero)
  - `distinct_issuer_lineages`: Integer
  - `lineages`: Array of distinct lineage strings
  - `producer`: Script name and version
- `source_audit`: Full list of audited sources with hashes and rights status
- `candidates`: Array of validated candidate records containing exact text anchors and metadata.
- `quarantine`: Array of quarantined proposals with code-defined failure reasons.
