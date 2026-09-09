# Model runtime contract / 模型串接與切換

## Current acceptance / 目前驗收

See [current status](../state/STATUS.md) for acceptance, not historical PASS headings. The existing Q5 thinking=false/effort=none receipt is historical; current-source verification has reported `LIVE_SOURCE_MANIFEST_MISMATCH`. A model catalog, profile hash or healthy endpoint is not a completed answer or qualified release. No new installed EXE, Worker/model binding, schedule restoration or Production publication is implied.

本輪實查：兩個發布排程仍 Disabled，動作指向預期的 installed refresh 腳本；十個已知鏈路檔案中，六個與候選來源不同、兩個新版模組尚未安裝、兩個相同。這是版本差異，不可只換 EXE 就宣稱整條鏈路已升級。

Historical qualification, failed xhigh responses, runner proof and prior document text remain in Git (`git show dd3cf57:docs/MODEL_RUNTIME_MIGRATION.md`) and original receipts. Do not restamp them.

## EXE candidate / EXE 候選功能

- Selection uses an explicit identity from the selected Router catalog; no model-family guessing. An empty/unavailable catalog cannot authorize saving a guessed model.
- EXE and bridge resolve the explicit/saved loopback endpoint, or `http://127.0.0.1:8080` when absent. Invalid configuration fails closed. Bridge resolution does not probe `/health`, send `reload=1`, scan processes/ports or launch a different model stack. Catalog and completed-marker checks must succeed on the resolved endpoint; returning its URL alone is not health qualification.
- Saved selection root/model/URL types are checked without PowerShell's single-item-array unrolling. Explicit model/endpoint inputs do not depend on an unrelated malformed compatibility selection file.
- Reject credentials, query/fragment and paths in the base URL. Catalog HTTP redirects are disabled. Transfer is bounded by a 1MiB payload limit and 4.5-second I/O deadline per endpoint path; at most `/models` and `/v1/models` are attempted. At most1024 distinct identities/aliases are admitted.
- Catalog deduplication uses a set; preferred-profile lookup happens once per discovery, not once per catalog row. These are bounded operations, not a measured whole-product performance claim.
- EXE has a THINK dropdown: `none` disables thinking; `minimal/low/medium/high/xhigh/max` request thinking with that effort. These are requested settings, not inferred model capabilities. Model and THINK choices are saved together in the common profile; token/time bounds stay unchanged and qualification remains false.
- Scanning/operations lock both selectors. Native UI self-tests display the actual form, click its Save/Use handler across two synthetic models/all effort choices, verify persisted booleans/hash/unqualified state, and check actual PowerShell child snapshots for off/on modes. Invalid effort cannot overwrite a valid profile. No model/network/production buttons are invoked by this test; its logs/config are isolated.
- The existing packager now runs profile and THINK UI self-tests on its compiled EXE. A passing candidate test does not replace a newly qualified ZIP or installed/live acceptance.
- `--model-catalog-check <loopback-base>` checks metadata only. Exit0 means a valid catalog, not inference.
- The candidate's **本機回覆測試 / Test reply** button and `--model-route-check <loopback-base>` share one C# caller and the existing bridge's `-RoutingCheckOnly` branch. That branch requires a profile, exact complete-marker response and existing64-bit CPython3.12.10 with requests (explicit PROJECT_PYTHON or the installed portable-runtime path). It never downloads Python, launches gateway/tunnel, reads deployment credentials, registers tasks or publishes. Mutation switches cannot be combined with it; mixed `--version` cannot bypass a route check.
- The GUI first saves the selected model/mode as unqualified; the CLI does not save selection. Local diagnostic logs may be written. Router inference may load the selected model normally. Successful fixed-marker checks do not certify THINK levels or research-answer quality. These are candidate-build controls, not features verified in the older installed EXE.

## Authoritative profile / 設定來源

Schema: `config/v213-model-profile-v1.json`; validators: Python `scripts/v213_model_profile.py`, Worker `cloud/src/v213/model-profile.ts`, EXE parser.

Precedence: explicit `V213_MODEL_PROFILE_JSON` process environment, then `%LOCALAPPDATA%\InvestorIntelligence\UserData\config\v213-model-profile-v1.json`, then the packaged template. Model selection changes the model; an explicit THINK selection also changes `enable_thinking` and `reasoning_effort`, preserving token/time bounds. Each profile-file replacement is atomic. Profile + compatibility selection + child processes + remote Worker are **not** one atomic transaction. The selection file is not the authority or release approval.

| Field | Contract |
|---|---|
| `schema_version` | integer1 |
| `model` | explicit ASCII catalog identity, up to200 characters |
| `enable_thinking` | boolean |
| `reasoning_effort` | none/minimal/low/medium/high/xhigh/max; none iff thinking disabled |
| `max_output_tokens` | integer1–8192 |
| `smoke_output_tokens` | integer1–max_output_tokens |
| `timeout_ms` | integer1000–20000 |

Unknown/duplicate keys, invalid types and conflicting settings fail closed. The canonical fixed-order scalar-array SHA256 is shared across languages. A changed profile invalidates prior qualification. Do not bypass the certified caller's deadline to accommodate long thinking.

## Auto-think boundary / 自動 think 的未完成部分

Automatic think selection is **not implemented or qualified**. EXE supports manual THINK selection; it does not prove a new model supports or honors those settings. Pi's own thinking setting is separate from this application's local-model profile.

### Bounded real-model observation

`state/model-thinking-observation-20260909.json` records two synthetic local requests through the existing Router to the approved Q5 model, built with the shared request/profile validators. Both returned the complete exact marker within the18s profile budget: none9594ms/no exposed reasoning field; low4703ms/reasoning field present. No reasoning text was retained. No preset was changed or alternate stack started; the existing Router could load its sole configured model normally.

The later `state/exe-local-route-final-20260909.json` records the actual compiled candidate EXE → PowerShell core → real Q5 Router path for none/low, with exact-marker success and no runtime config directory created. It binds compiled-EXE/source-file hashes; startup/IPC time is included. The initial EXE observation is retained separately. No full gateway/Worker/LINE route was exercised, and no installed EXE was replaced.

This observes off/on output behavior and local caller completion, **not** graded-effort semantics, best-mode selection, broad answer quality, a cold-load comparison, installed EXE end-to-end acceptance or release readiness. The initial-model-state field is only a boolean membership check, not a load trace. Dirty-source observation and `release_qualified=false` remain; the release verifier explicitly rejects this receipt. Earlier failures remain intact.

### Readiness transport and isolated Q&A follow-up

The failed authorized run and two diagnostic runs remain in audit-runtime (`r75-live-authorized-*`, `r75-readiness-transport-diagnostic-*`, `r75-readiness-direct-control-*`). PS7 selected a proxy where other clients reported bypass, but subsequent status differences do not prove a single cause for every404/500. Diagnostic observations cannot qualify a failed gate.

The shared readiness transport now uses a per-request HttpClient handler: direct connection, no cookies/default credentials/redirects,10s timeout,1MiB response cap and strict UTF-8. It does not modify global proxy settings. Non200 HTTP responses fail except an explicit409 version mismatch; scalar arrays cannot masquerade as primitive readiness fields. The original parser/version/hash/nonce and three-consecutive-proof rules remain.

A new `r75-live-direct-transport-20260909.json` passed all10 real Q5 none-mode cold/warm cases (maximum2593ms), asynchronous reference completion and negative lease/replay/model/profile checks. The independent verifier accepted its exact runtime manifest/profile; cleanup, unchanged preset/source and no real LINE/Production mutation were confirmed. This is model-Q&A qualification using synthetic public data, not licensed financial-data, all-THINK-mode, installer or whole-release acceptance. Historical receipts are not overwritten. `state/r75-qa-live-current.ref.json` now points by path/SHA to a separately retained receipt. The shared selector requires regular HEAD-committed files and identical worktree bytes; invalid/missing/drifted pointers never fall back. Receipt selection is not qualification: both callers still run the freshness/profile/runtime verifier, and Windows binds the exact selected path/SHA. Git attributes preserve receipt bytes across checkout line-ending settings.

New packages bind that QA reference in HOTFIX-REFS and require the adjacent QA receipt as a delivery artifact. The independent ZIP verifier compares its digest/Windows binding and evaluates its live evidence against the actual archive runtime; it never imports archive code. Synthetic archive tests are not real installation attestations. The packager now refuses existing output directories instead of clearing operator data or previous failures.

The formal release validator reproduced a historical activation baseline failure (retained as `full-release-activation-baseline-red.log`). `activation-v2.ts` is now restored byte-for-byte to the existing certified baseline; production imports only the versioned `activation-v3.ts` implementation, which preserves the no-stale-carry-forward fix and unchanged bundle signatures/schemas. The legacy activation.ts safety diff was separately reviewed. No protected hash was changed. An authenticated synthetic request through the actual Worker route catches stale carry-forward if wired back to v2; rollback originals remain intact. The earlier runtime-manifest QA evidence remains invalid for this migration. Fresh isolated proof on clean e945f60 passed all ten Q5 none cases (max3062ms), reference/negative checks and independent verification; temporary resources were deleted and source/preset unchanged. Its exact bytes are retained separately in `state/r75-qa-live-activation-v3-20260909.json` and selected by the committed reference. Full release/installation and genuine market-data acceptance remain separate requirements.

Required future acceptance:

1. Probe only the explicitly selected model on the approved Router, serially, without starting another model/server or modifying presets.
2. Use declared capabilities and observable complete answers under representative task/latency budgets. Model names and HTTP200 alone do not establish supported or appropriate thinking. Unobservable mode behavior stays UNKNOWN.
3. Preserve each failed/unsupported/timeout trial. An automatic recommendation is not permission to silently downgrade a production request or use a paid fallback.
4. Bind the chosen profile to fresh source/model/runtime evidence; test EXE → actual child → authenticated gateway → Worker → completed answer, plus drift, incomplete-answer and timeout negatives. Require operator confirmation and release gates before Production synchronization.

## Verification and deployment / 驗證與同步

Use the approved Python runtime:

```powershell
& $env:PROJECT_PYTHON scripts/v213_model_profile.py --profile config/v213-model-profile-v1.json
```

This returns validated settings, a fingerprint and `release_qualified=false`, not a deployment receipt. Worker binding must contain the same validated profile as the gateway. Health/response pins and readiness must match; changing only one side is invalid.

The bridge startup now uses the validated profile's exact model instead of rejecting every non-Q6 selection. Unprofiled FreeRelay callers retain the Q6 restriction. PS5.1/7 tests execute the actual startup decision block with synthetic transport, including profile conflict, incomplete response and legacy negatives; they do not certify an installed bridge or live model. The routing smoke disables HTTP redirects.

Archive verification now binds the packaged profile and required runtime modules to matching model/profile hashes in HOTFIX-REFS, Windows and deployment receipts; the delivery receipt must bind that ZIP's SHA. Profile-bearing packages cannot use the legacy Q6-only path, including when only profile-runtime markers remain. Duplicate JSON keys and unqualified thinking profiles reject. Legacy archives without profile markers retain Q6-only admission. Synthetic ZIP/CLI tests establish verifier behavior, not live inference, real PE validity or successful installation.

Gateway requests require exact profile/model agreement and reject incomplete or mismatched responses. Timeout remains bounded `MODEL_PROFILE_TIMEOUT`; no raw exception or reasoning transcript should be retained. Install the complete reviewed dependency chain, validate installed actions separately, then obtain fresh Windows/source-bound/archive/install evidence. No old activation replay and no real LINE test sends.
