# Model runtime contract / 模型串接與切換

## Current acceptance / 目前驗收

See [current status](../state/STATUS.md) for acceptance, not historical PASS headings. The existing Q5 thinking=false/effort=none receipt is historical; current-source verification has reported `LIVE_SOURCE_MANIFEST_MISMATCH`. A model catalog, profile hash or healthy endpoint is not a completed answer or qualified release. No new installed EXE, Worker/model binding, schedule restoration or Production publication is implied.

本輪實查：兩個發布排程仍 Disabled，動作指向預期的 installed refresh 腳本；十個已知鏈路檔案中，六個與候選來源不同、兩個新版模組尚未安裝、兩個相同。這是版本差異，不可只換 EXE 就宣稱整條鏈路已升級。

Historical qualification, failed xhigh responses, runner proof and prior document text remain in Git (`git show dd3cf57:docs/MODEL_RUNTIME_MIGRATION.md`) and original receipts. Do not restamp them.

## EXE candidate / EXE 候選功能

- Selection uses an explicit identity from the selected Router catalog; no model-family guessing. An empty/unavailable catalog cannot authorize saving a guessed model.
- Discovery stays on the configured loopback endpoint, or `http://127.0.0.1:8080` when none is configured. Invalid configured URLs fail; a failed selected endpoint does not trigger scans of unrelated ports.
- Reject credentials, query/fragment and paths in the base URL. Catalog HTTP redirects are disabled. Transfer is bounded by a 1MiB payload limit and 4.5-second I/O deadline per endpoint path; at most `/models` and `/v1/models` are attempted. At most1024 distinct identities/aliases are admitted.
- Catalog deduplication uses a set; preferred-profile lookup happens once per discovery, not once per catalog row. These are bounded operations, not a measured whole-product performance claim.
- Scanning locks other GUI operations and preserves the user's pending choice when it remains available. Saved selection text explicitly says unqualified. Native catalog/profile tests do not replace interactive GUI/extracted-install acceptance.
- `--model-catalog-check <loopback-base>` is a read-only native transport check. It does not start a model, send inference, change presets or save selection. Exit0 means a valid catalog only.

## Authoritative profile / 設定來源

Schema: `config/v213-model-profile-v1.json`; validators: Python `scripts/v213_model_profile.py`, Worker `cloud/src/v213/model-profile.ts`, EXE parser.

Precedence: explicit `V213_MODEL_PROFILE_JSON` process environment, then `%LOCALAPPDATA%\InvestorIntelligence\UserData\config\v213-model-profile-v1.json`, then the packaged template. Model selection changes the model and preserves the other profile fields; each profile-file replacement is atomic. Profile + compatibility selection + child processes + remote Worker are **not** one atomic transaction. The selection file is not the authority or release approval.

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

Automatic think selection is **not implemented or qualified**. Current EXE selection preserves settings; it does not prove a new model supports them. Pi's own thinking setting is separate from this application's local-model profile.

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
