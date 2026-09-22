# Implementation Review — QA Capacity Harness Usage Test Repair (V2)

Task: QA_CAPACITY_HARNESS_USAGE_TEST_REPAIR_6922278_V2
Child namespace: D:/Investor-Intelligence-LINE-Pi/_workspace/audit-runtime/qa-capacity-harness-usage-test-repair-6922278-1790009963636
Parent namespace: D:/Investor-Intelligence-LINE-Pi/_workspace/audit-runtime/qa-capacity-inference-harness-prep-6922278-1790007724960
Capacity module (pinned, unmodified): D:/Investor-Intelligence-LINE-Pi/_workspace/source/scripts/v213_qa_capacity.py @ FIXUP_SHA 6922278ac865727fdcdded96535f94aaaabeb8b3

## Design summary

- `native_inference_runner.py` (harness): constructs the full narrow binding and supplies the single-inference callback to the UNMODIFIED `run_native_window(binding, work, interval_s=2, max_gap_s=5, timeout_s=15, ttl_s=30)` module API. It never copies, replaces, monkey-patches, or weakens native capacity logic.
- Import performs no network, native attempt, lease mutation, process launch, or settings mutation (module level: docstring, imports, constants, defs only).
- The future native entrypoint (`run_live`/`main`) refuses live execution without run-authority.json + operator-handoff.json matching the expected task id and fixup SHA; no bypass flags exist; the entrypoint uses the pinned default transport only (no DI at the entrypoint).
- Binding construction (`build_binding`): the signature exposes no parameter for extra allowed_clients, no parameter for alternate qwen_worker_names, no model override. allowed_clients is exactly the dedicated lease-owning runner's own freshly-attested (pid, birth) captured before lease acquisition and PRE; qwen_worker_names is fixed to ["qwen-writer"] (not narrowable). The raw service must carry the 7 identity keys plus optional listener_port (strict int 5000 when present — the real collector emits it); the binding service is emitted as the 7 keys (listener_port excluded), matching the module's `_validate_binding`.
- `freeze_binding`: runs the module's canonical `_validate_binding`, persists the complete expected binding exactly once (expected-binding.json; no post-freeze overwrite), returns (deep copy, sha256). Independent replay receives the separately preserved expected binding.
- Transport (`make_transport`): stdlib http.client to the literal pinned destination (default http://127.0.0.1:5000/v1/chat/completions); no environment proxy (http.client does not consult HTTP(S)_PROXY; no urllib.request/ProxyHandler); no redirect following (3xx returned as a plain status, never re-issued); absolute monotonic deadline (total 10s from transport call start; connect 2s) that cannot be extended by slow headers or trickled body; interruptible reads (0.25s socket timeout, cancel-checked before deadline classification); body cap 65536 bytes; every failure path closes the connection and leaves no local threads or sockets.
- Callback (`inference_callback`): exactly one request, zero retries; cancels before dispatch without any request; validates HTTP 200, bounded JSON, exactly one choice, finish_reason "stop" (None -> finish_reason_missing; "length" -> truncated), non-empty assistant content, matching model identity, and credible completion-token accounting (usage.completion_tokens strict int within [1, 384]); records request start / response completion / callback boundaries on one consistent monotonic clock in the workload evidence; every failure raises WorkloadError (never success-shaped).
- `work_factory`: exceptions propagate unchanged into the native API (work_raised -> non-pass).
- `test_native_inference_runner.py`: 27 fixture tests; deterministic fakes + bounded ephemeral loopback servers (127.0.0.1 port 0, daemon threads, stopped in finally); tmpdir lease roots; no contact with ports 5000/8000, the real model service, real hardware probes, or the canonical lease root.

## Installed-source references (request and cancellation behavior)

Installed TabbyAPI: D:/tabbyAPI/ (service: "C:\Users\moon9\AppData\Local\Programs\Python\Python312\python.exe" D:\tabbyAPI\main.py, pid 6432)

1. Endpoint and non-streaming path: D:/tabbyAPI/endpoints/OAI/router.py:110-170 — POST /v1/chat/completions; `if data.model: await load_inline_model(data.model, request)`; stream=false -> `generate_chat_completion(...)` -> ChatCompletionResponse; cancellation -> HTTPException 422 "request cancelled by user".
2. Model dispatch (no load/unload/switch/fallback for the bound model): D:/tabbyAPI/endpoints/OAI/utils/common_.py:106-111 — `load_inline_model`: `if _is_loaded_model(model_name): return` (early return when the requested model name is already loaded). A request naming the bound model therefore selects the already-bound model without any load, unload, switch, or fallback.
3. Request fields: D:/tabbyAPI/endpoints/OAI/types/chat_completion.py:79-160 — ChatCompletionRequest: messages, model, enable_thinking (request-local; "forwarded to the chat template as the enable_thinking variable"; flat top-level takes precedence over template_vars/reasoning), tools optional (not sent by the frozen request); D:/tabbyAPI/endpoints/OAI/types/common.py:54-110 — CommonCompletionRequest: stream (default False), n (ge=1); D:/tabbyAPI/common/sampling.py:39-60 — BaseSamplerRequest: max_tokens (ge=0), temperature.
4. Response shape and token accounting: D:/tabbyAPI/endpoints/OAI/types/chat_completion.py:162-170 — ChatCompletionResponse {choices, model, usage}; D:/tabbyAPI/endpoints/OAI/types/common.py:27-45 — UsageStats {prompt_tokens, completion_tokens, total_tokens, ...}; D:/tabbyAPI/endpoints/OAI/types/chat_completion.py:45-58 — ChatCompletionRespChoice {finish_reason, message}.
5. Cancellation/disconnect semantics: D:/tabbyAPI/common/networking.py:81-140 — DisconnectHandler: a background task owns the ASGI receive channel and flags the handler on http.disconnect; poll() is a plain flag check that raises asyncio.CancelledError; the endpoint catches CancelledError/InvalidStateError -> 422. Client-side disconnect is detectable server-side, but client-side evidence alone cannot prove server-side generation stopped (the harness records only client-side outcomes).
6. CONCRETE INCOMPATIBILITY (for Master ruling): D:/tabbyAPI/endpoints/OAI/utils/chat_completion.py:932 — `return_usage = data.stream_options and data.stream_options.include_usage` and :977 — `response = _compose_response(..., return_usage)`; :167 — `usage=(aggregate_usage_stats(usl) if return_usage and usl else None)`. The non-streaming response includes usage ONLY when the request carries stream_options.include_usage=true. The Master-frozen request body does NOT include stream_options, so a live attempt with the exact frozen request will receive usage=null; the harness completion criterion "credible completion token accounting" (usage.completion_tokens within [1,384]) therefore cannot be satisfied and the attempt would be an honest non-pass (usage_missing). The supported per-request control exists (D:/tabbyAPI/endpoints/OAI/types/common.py:46-47 — ChatCompletionStreamOptions.include_usage, default False); amending the frozen request to add `stream_options: {"include_usage": true}` is a Master decision (the frozen body was specified exactly and was not changed by this slice).

## Evidence of unmodified native contract

- Capacity module file SHA-256 aa2b4dc0130f7b6d1548717763dbc7c04f5697c252aa970a525749e2a51456cd (unchanged at FIXUP_SHA; verified in this slice).
- The harness imports the module read-only (sys.path insert); no monkey-patching (the AST import test verifies no top-level side effects; no setattr on module objects anywhere in the harness).
- Native-level fixtures drive the module's own `run_window`/`CapacityLease`/`verify_receipt` with injected probe/transport only at the seam the module itself exposes (probe parameter of run_window; work callable); the module entrypoint `run_native_window` is called unmodified by `run_live`.

## V2 Changes

### Request Amendment
- Master-approved on HARNESS_PREP_HANDOFF: exactly `stream_options: {"include_usage": true}` added to request.json.
- stream remains false; all other fields unchanged.
- Amended request has 8 fields.
- CHILD_REQUEST_BYTES_SHA256: 1fa1910c8db0dda712d6997717e7c5519c22de9465222dd302e96456bcc3f7b0.
- Original incompatible request preserved unchanged in the parent namespace.
- Directly dependent harness check: `load_request_bytes` now requires stream_options to be exactly `{"include_usage": True}` (dict equality; no extra keys) or raises `request_invariant_violated`.
- Usage semantics unchanged: missing/null usage remains a failure; no estimation, substitution, relaxation, streaming, added requests, or timeout extension.
- No other harness change (transport, deadline, cancel, binding, qualification, response validation, dispatch cardinality all unchanged).
- Full parent->child diff in repair.diff; REPAIR_DIFF_SHA256: 886e69da34593082944c42ba204eb1766fc077ef25bcc60ca06e99c066afd692.

### Test Changes
1. **Error-event assertion**: Now uses the actual event key 'kind' (`kind=='error'` and `code=='work_raised'`). The test additionally asserts the callback was attempted exactly once (`transport.calls == 1`) and produced no successful workload result (`evidence == {}`). 'type' is not accepted as an alternate key; unrelated error events cannot satisfy the test.
2. **Timeline test**: Replaced with a same-clock containment design. A fixture-side wrapper captures callback entry/exit with `time.monotonic()` (the same clock as the workload evidence). `check_timeline_containment(evidence, cb_start, cb_end)` requires all three evidence timestamps to be valid numbers within the callback interval and in order, raising AssertionError on missing/invalid values, reversed ordering, or out-of-interval timestamps. Negative cases included (shifted timestamp outside interval rejected; reversed ordering rejected; missing times rejected). Receipt-relative work ordering verified separately in its own coordinate system (`work_start_s <= work_end_s`, both not None) plus module `verify_receipt` recomputation equality.
3. **New test_request_amendment_usage_conditions**: Captured outbound bytes equal the frozen artifact and carry `include_usage=true` + `stream=false`; all other frozen fields unchanged. A source-faithful fake conditions the response usage on the captured request (`include_usage true -> usage present`, otherwise `usage null`) mirroring the installed server. Missing/null usage fails without a second request. Valid int `completion_tokens` in [1,384] passes only when all other response criteria pass (valid usage + wrong model still fails). Bool/string/negative/zero/over-limit token counts fail with the specific codes.
4. **Binding non-regression**: Listener_port boundary cases (`str '5000'` rejected; `5001` rejected; unexpected extra field rejected; all `service_identity_invalid`) and normalization check (binding service is exactly the 7 identity keys, no listener_port). `build_binding` logic itself unchanged.

### Installed Version Identification
- Installed TabbyAPI at D:/tabbyAPI/ is a git checkout at HEAD 53da7919d4e45c63f4acbcbbc00cbe0f60a1ce65 (commit date 2026-09-14 00:43:10 +0200).
- pyproject.toml name tabbyAPI version 0.0.1 (local dev marker).
- Inspected file fingerprints (SHA-256):
  - D:/tabbyAPI/endpoints/OAI/types/common.py: f3d9f90342888a571bd4a6db03f3e00cba33678457ce6b25df7379bd3844bb43
  - D:/tabbyAPI/endpoints/OAI/utils/chat_completion.py: 20f73001b342b9f318c85fad995f6d2344bf61b3790afeb425b6bbda130072ec
  - D:/tabbyAPI/endpoints/OAI/router.py: bfabc219a1287fa107b76e4f8d16045b1fdab2ac0ef38898897bd5f6eda20679
  - D:/tabbyAPI/endpoints/OAI/utils/common_.py: 90d1d2d99cb990d0cb271acbd4345b260ac48b5bbd0989971fee23950e1ea5a4
  - D:/tabbyAPI/common/networking.py: fce8899ecde52ad4ad0babbd8bc6b5b7c79b47b5ea1684475f5e3587a419e3d7

### Installed Usage Path Evidence
- **Schema acceptance**: types/common.py:46-47 `ChatCompletionStreamOptions {include_usage: Optional[bool] = False}` accepted on ChatCompletionRequest via CommonCompletionRequest.stream_options.
- **Consumption**: utils/chat_completion.py:932 (non-streaming generate_chat_completion) `return_usage = data.stream_options and data.stream_options.include_usage`.
- **Propagation**: :977 `response = _compose_response(request.state.id, generations, model_path.name, return_usage)`; :167 `usage=(aggregate_usage_stats(usl) if return_usage and usl else None)`.
- No backend component was imported or started by this slice (read-only inspection only).

## Known candidate state (honest V2)

- **Fixture suite**: The one budgeted full focused fixture suite run (`python -B -m unittest test_native_inference_runner -v`): Ran 27 tests in 7.873s — FAILED (failures=1, errors=1); 25/27 pass; zero skips; raw log fixture-logs/child-fixture-run1.log.
- **Diagnosed test-design bugs** (the harness is correct in both):
  1. `test_request_amendment_usage_conditions`: `UsageConditionedTransport` uses `usage_override=None` as its no-override default, so the null-forcing sub-case (written with `usage_override=None`) fell into the conditioned branch and, because the amended request carries `include_usage=true`, received a valid usage response and raised nothing. Precise fix: module-level sentinel `_NULL_USAGE = object()`; `__init__(self, usage_override=_NULL_USAGE)`; in `__call__` branch on `is _NULL_USAGE` (conditioned) vs the explicit override value (so `usage_override=None` forces null).
  2. `test_workload_evidence_timeline_consistency`: The frozen module's `verify_receipt` returns `computed_summary` (scripts/v213_qa_capacity.py:1726), not the receipt, so `verified['summary']` raised KeyError. Precise fix: `assertEqual(verified, receipt['summary'])`.
- **STOP condition applied**: First completed failing fixture run; no post-failure repair or re-run performed in this slice.
- **Provenance**: Full parent->child diff in repair.diff; parent identity in parent-manifest-reference.json (parent core digest d1d1d189b146850d3fe9e84f1837dbf72ccaef89585a00861e2f015c1d2c6a03 verified by recomputation); child core digest in core-manifest.json; parent namespace untouched (its historical failed results preserved).
- **Remaining uncertainty**: The two precisely-stated test fixes are pending a Master ruling (authorize an additional repair batch + one fixture run, or rework); JEV/Mapika were NOT run because the directive conditions JEV on the child fixture passing; no completion claim.