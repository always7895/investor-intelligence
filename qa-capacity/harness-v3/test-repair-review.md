# V3 Test-Repair Review: QA_CAPACITY_HARNESS_TEST_ONLY_REPAIR_6922278_V3

## 1. Header & Identity
- **Task**: QA_CAPACITY_HARNESS_TEST_ONLY_REPAIR_6922278_V3
- **V3 Namespace**: `D:/Investor-Intelligence-LINE-Pi/_workspace/audit-runtime/qa-capacity-harness-test-only-repair-6922278-v3-1790010999893`
- **V2 Parent Namespace**: `D:/Investor-Intelligence-LINE-Pi/_workspace/audit-runtime/qa-capacity-harness-usage-test-repair-6922278-1790009963636`
- **Capacity Module**: Pinned unmodified @ FIXUP_SHA `6922278ac865727fdcdded96535f94aaaabeb8b3`
  - File SHA-256: `aa2b4dc0130f7b6d1548717763dbc7c04f5697c252aa970a525749e2a51456cd`
  - Git Blob: `64ab98a1a5ba0f7c7f6959ec8ba15d03d6b0f0ec`

## 2. Scope & Immutability Verification
- **Editable File**: `test_native_inference_runner.py` (Only)
- **Immutable Files** (Byte-identical to V2 parent, verified by SHA-256 pre/post run):
  - `native_inference_runner.py`
  - `request.json`
  - `run-plan.json`
  - `binding-template.json`
  - `implementation-review.md`

### V3 Identities (SHA-256)
| Component | Hash | Status |
| :--- | :--- | :--- |
| HARNESS | `94563cf2e648b73492e75811dfa1cc106d4b436c0c3567979b44b809bfc8e140` | Unchanged from V2 |
| TEST | `7e0823fe342bb13a3e22c9f409f141614cec881c084d95a83cc7bb841ee69243` | V3 |
| REQUEST | `1fa1910c8db0dda712d6997717e7c5519c22de9465222dd302e96456bcc3f7b0` | Unchanged |
| RUN_PLAN | `39d0eb1ab08355ecdc295b8d11f231509cbb0a1c85beb19b9f39a3c0d0492f6f` | Unchanged |
| BINDING_TEMPLATE | `5a453b450056ce69b55358f840d65a9bcd69e1cd64e322b170f193e16b6482ab` | Unchanged |
| REVIEW | `1c75467ec58b8ce723a0ab451826e94c4b27955ef6094cdc25286e2b0fb46a27` | Unchanged |
| REPAIR_DIFF (V2->V3) | `de733d926d9462eb1f6d5502f5944d04b0c7d0e2303d19c34773cb3beaf700d7` | New |
| V3 Core Digest | `1b4a58c8d28bd911f685ac67147e2a724fe10d18978f7fc10f0de726e2eb8bff` | New |
| V2 Parent Core Digest | `def2e7cdd54cbf7c3e49b567dc0fa27828b1fc56fe87c067aa27f5cf66451010` | Reference |

## 3. Repair Facts

### F1: Usage-Override Sentinel
- **Implementation**: Module-level sentinel `_NULL_USAGE = object()` created once in the test module.
- **Constructor**: `UsageConditionedTransport.__init__(self, usage_override=_NULL_USAGE)`.
- **Logic**: In `__call__`, branch is `if self.usage_override is _NULL_USAGE:` (is-identity).
  - **True**: Response usage conditioned on captured request (`include_usage` true -> usage present, otherwise usage null).
  - **False**: `usage = self.usage_override` (explicit override; `usage_override=None` means explicit null usage).
- **Coverage**: All existing subcases retained:
  - Amended-request field assertions.
  - Outbound bytes equal frozen artifact and carry amendment.
  - Conditioned valid response passes with evidence timestamps.
  - Missing/null usage fails `usage_missing` (exactly one call, empty evidence).
  - Valid usage + wrong model fails `model_mismatch` (one call).
  - Token counts `True`/"12" -> `usage_invalid`; `-1`/`0`/`500` -> `token_bound_exceeded` (each with exactly one call).

### F2: Verify Receipt Return Shape
- **Context**: Frozen module's `verify_receipt` returns `computed_summary` (`scripts/v213_qa_capacity.py:1726`), not the receipt.
- **Assertion Update**: 
  ```python
  verified = h.qc.verify_receipt(receipt, binding)
  self.assertEqual(verified, receipt["summary"])
  ```
- **Behavior**: 
  - Real verifier call kept (raises `CapacityError` on any contradiction, including `computed != stored`).
  - Full summary comparison kept.
  - All timing assertions unchanged:
    - Same-clock containment via `check_timeline_containment` with fixture-side callback wrapper.
    - Negative cases: shifted timestamp, reversed ordering, missing times.
    - Receipt-relative ordering in its own coordinate system.

### Unchanged Coverage
- All 27 test names and all subcases retained (including subcases not reached during V2 failing run).

## 4. Pre-Run Checks
- **Syntax**: In-memory syntax inspection `SYNTAX_OK` for both Python files (`py_compile`). No fixture case executed before run.
- **Immutability**: Drift check confirmed all 5 immutable files byte-identical to V2.
- **Scope**: V2->V3 diff = exactly the 4 authorized changes.
- **Request**: 8 fields, `stream_options` `include_usage` true, `stream` false.

## 5. Fixture Execution
- **Command**: `python -B -m unittest test_native_inference_runner -v`
- **Result**: 
  - Ran 27 tests in 7.870s
  - OK
  - Exit code 0
  - 27/27 pass
  - 0 failures
  - 0 errors
  - 0 skips
- **Log**: `fixture-logs/v3-fixture-run1.log`
- **Notes**: Expected fixture-server `ConnectionAbortedError` tracebacks appear in log from cancel/deadline tests (client closes connection; affected tests are ok).
- **Post-Run Hash Check**: Harness and request unchanged; test file carries V3 hash.

## 6. Source Review Hold
- **Status**: Recorded, not resolved by this slice.
- **Harness Request Guard**: Unchanged.
- **Traced Validation Path** (Unresolved `include_usage` integer-vs-boolean question):
  - `load_request_bytes` checks: 
    ```python
    so = data.get("stream_options")
    if not isinstance(so, dict) or so != {"include_usage": True}:
        raise WorkloadError("request_invariant_violated")
    ```
  - **Python Semantics**: `{"include_usage": 1} == {"include_usage": True}` is `True` (`1 == True`). A request artifact carrying `include_usage: 1` would pass this harness invariant.
  - **Server Declaration**: Installed server declares `include_usage` as `Optional[bool]` (`D:/tabbyAPI/endpoints/OAI/types/common.py:46-47`, Pydantic model).
  - **Potential Outcome**: If installed Pydantic rejects an int for a bool field, server answers 422. Callback's status check converts this into an honest non-pass (`http_status_422`). Callback also requires response model/usage criteria.
  - **Defense-in-Depth**: Dispatched bytes are always the frozen artifact itself (fixture-verified: outbound bytes equal artifact bytes). The invariant is a sanity check on the artifact, not the final gate. Final gates are the installed server and callback validation.
- **Conclusion**: Recorded as an open harness-strictness question for the Master's exact-source review. Not claimed exploitable and not claimed closed.

## 7. Provenance
- **Full V2->V3 Diff**: `repair.diff`
- **Parent Identity**: `parent-manifest-reference.json`
- **V3 Core Digest**: `core-manifest.json`
- **V2 Namespace**: Untouched (historical results preserved)
- **Review Packet**: `review-packet.zip` contains relevant permitted material.

## 8. Remaining State
- **Status**: `FIXTURE_PASS`
- **Acceptance**: Exact-source acceptance pending the Master's review of the full inline source delivery.
- **Execution**: No native execution authorized.
- **Claim**: No completion claim.