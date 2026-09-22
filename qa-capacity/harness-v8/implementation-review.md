# V8 Implementation Review (QA_CAPACITY_HARNESS_RUNTIME_REPAIR_6922278_V8)

Task: QA_CAPACITY_HARNESS_RUNTIME_REPAIR_6922278_V8
Namespace: D:/Investor-Intelligence-LINE-Pi/_workspace/audit-runtime/qa-capacity-harness-runtime-repair-6922278-v8-1790073020041
Parent: QA_CAPACITY_HARNESS_RUNTIME_REPAIR_6922278_V7 (review SHA d98aa796c8648bbb454d185f70c28adcbbf7d28b, verdict REWORK, 17/17 files verified)
Capacity module (pinned, unmodified): D:/Investor-Intelligence-LINE-Pi/_workspace/source/scripts/v213_qa_capacity.py @ FIXUP_SHA 6922278ac865727fdcdded96535f94aaaabeb8b3

## Master V7 verdict (authoritative)

VERDICT=REWORK; SHA_VERIFIED=true; VERIFIED_FILES=17/17. CLOSED: R1; F1/F2; R2-B; R3; R4; R5 canonical-key/argv; R5-L; R6. ONLY REMAINING RUNTIME DEFECT: R2-A HIGH — the authority window is checked at callback entry and before transport(...), but the default transport performs conn.connect() -> cancel/deadline checks -> conn.request("POST", ...); a grant can expire during conn.connect() and still issue the POST.

## V8 repair (exactly three runner hunks; verified by diff vs V7 baseline 459cd777d6d61e04)

1. `make_transport(..., grant_check=None)` — one trailing keyword parameter; default `None` keeps every non-live call site behavior-identical.
2. Inside the default live transport, after successful `conn.connect()`, after the existing cancel check, after the existing deadline check, and IMMEDIATELY BEFORE `conn.request("POST", ...)`:
   `if grant_check is not None: grant_check()`
3. In `run_live`, the default transport is bound to a closure over the already-validated unchanged auth record:
   `def grant_check(): _check_window_current(auth)` / `transport = make_transport(grant_check=grant_check)`

Properties: no grant extension or restamping (the guard re-reads the unchanged records against the current finite wall clock via the existing `_check_window_current`); an expired authority raises `authority_stale` and a non-finite clock raises `clock_invalid`, both BEFORE the POST; the connection still closes through the existing `finally: conn.close()` cleanup; every existing authority/cancel/deadline/cleanup check is preserved (the runner diff is exactly 3 hunks and nothing else). The guard is NOT a duplicate of the pre-transport check: it executes strictly between `conn.connect()` and `conn.request("POST", ...)`, closing the exact window the master identified.

## Revalidation stages (four, now named precisely in run-plan rules)

1. **admission** — `run_live` before process attestation/collector/Git/binding.
2. **work-callback entry** — `work_factory`'s `work()` after the native PRE phase, before the transport call.
3. **pre-transport** — immediately before HTTP dispatch inside `inference_callback` (directly before `transport(request_bytes, cancel_event)`).
4. **post-connect/pre-POST** — NEW in V8: inside the default live transport, after successful `conn.connect()` and after the existing cancel/deadline checks, immediately before `conn.request("POST", ...)`.

## Test changes (3 new deterministic tests; all 67 V7 tests byte-for-byte unchanged)

The new tests exercise `make_transport` ITSELF using an in-memory `http.client.HTTPConnection` substitute (`_V8FakeConn` + `_V8FakeSock`, module level; patched via `unittest.mock.patch.object(h.http.client, "HTTPConnection", ...)`), with the wall clock controlled via `unittest.mock.patch.object(h.time, "time", ...)` and `grant_check = lambda: h._check_window_current(auth)` (the harness's own unchanged guard):

1. `test_make_transport_expiry_during_connect_zero_post` — grant valid before connect; expires while `connect()` executes (controlled clock advanced past `valid_until` inside the fake connect); the post-connect/pre-POST guard raises `authority_stale`; ZERO POST requests; no success tuple returned (empty success evidence); connection closed.
2. `test_make_transport_valid_window_single_post` — grant remains valid after connect; exactly one POST (method/body verified); normal successful path preserved (200, body 'ok'); connection closed.
3. `test_make_transport_invalid_clock_at_dispatch_zero_post` — post-connect guard sees a non-finite clock (controlled clock set to `inf` inside the fake connect); raises `clock_invalid`; ZERO POST; no success evidence; connection closed.

## Evidence corrections applied in V8 (per master V7 directive)

- The four revalidation stages are distinguished by name (admission / work-callback entry / pre-transport / post-connect-pre-POST) in `run-plan.json` (`window_contract.rule`, `authority.rule`) and this review.
- Windows documentation corrected: `PureWindowsPath("/x").is_absolute()` is **FALSE** (the V7 explanation claimed True; the implementation was correct and no runtime repair was needed — documentation correction only).
- The delayed-PRE receipt test (`test_expiry_after_native_pre_fails_closed`) is a **SYNTHETIC fixture** (module-contract fake of `run_native_window`), NOT native replay evidence; it is labeled as such in `runtime-repair-review.md`.
- This artifact manifest uses the actual relative paths `fixture-logs/v8-fixture-run1.log` and `fixture-logs/v8-fixture-run2.log` (the V7 manifest listed the log without its `fixture-logs/` directory prefix).
- Raw JEV output is preserved in `jev-result.json`; the JEV decision grade (2.4) is an **ORDINAL SCORE** on the legend scale, not a probability.
- The V7 packet (namespace) and V7 branch (`qa-capacity-harness-v7` @ d98aa796) are preserved byte-for-byte; no V7 evidence was rewritten.

## Budget and dispatch record

- Bounded Qwen implementation dispatch: TabbyAPI `http://127.0.0.1:5000/v1/chat/completions`, model `Qwen3.8-27B-EXL3-5.5bpw-v2`, temperature 0, n 1, stream false, max_tokens 16384, enable_thinking false, 180s cap, no retries; status 200, finish stop, 8975 chars; raw persisted (`qwen-v8-response.json`, `qwen-v8-completion.txt` in the namespace).
- One pre-run static placement correction (no execution): `_V8FakeConn`/`_V8FakeSock` placed at module level (a class-attribute reference inside test methods would NameError); test logic otherwise as Qwen-specified.
- Fixture budget: 1 full run (67/70; 3 test-side API errors) + 1 narrowly diagnosed test-only repair + 1 retry run (70/70 OK). No third run. No mis-targeted executions beyond the two documented runs.