# Versioned model profile / 版本化模型設定

## Current result / 目前結果

The candidate implements a common profile across the EXE, PowerShell bridge, Python gateway and Worker. With the operator's downgrade authorization, the candidate now requests thinking=false/effort=none. One actual Worker-generated research question completed on the existing Q5 Router in1078ms with prompt caching disabled and656ms with caching enabled; both exact model/profile pins matched. This is scoped development proof, not full live/release qualification, and the Production Worker has not adopted it. Historical xhigh failures remain unchanged.

候選版已接上各端共同設定。依操作者降級授權，改為 thinking=false／effort=none，同一真實研究問題兩次皆完整回覆（1078／656ms），模型及 profile 相符。這不是完整 live／發布驗收；先前 xhigh 失敗紀錄保留，正式 EXE／Worker 尚未替換。

## Authoritative settings / 設定來源

Default template: `config/v213-model-profile-v1.json`.

The new EXE reads the user profile at `%LOCALAPPDATA%\InvestorIntelligence\UserData\config\v213-model-profile-v1.json`, falling back to its packaged template only when no user profile exists. An explicit `V213_MODEL_PROFILE_JSON` process environment value has precedence. EXE model selection updates the user profile atomically, preserves thinking/effort/bounds, records its fingerprint, and passes the same JSON snapshot to child PowerShell processes. The old selection file is compatibility metadata, not the model-profile authority or release approval.

新 EXE 優先使用使用者設定檔；選模型時保留其他推理設定，原子寫入並將同份 JSON 傳給子程序。明確設定的 process environment 可覆蓋檔案。設定更新後需重啟相關程序並同步 Worker binding；不能只更新一端。

Schema v1 fields (unknown keys/versions, duplicate keys, invalid types and contradictory settings fail closed):

| Field | Contract |
|---|---|
| `schema_version` | integer `1` |
| `model` | explicit catalog identity; ASCII ID up to200 characters (same bound as bridge/EXE selection), no family-name guessing |
| `enable_thinking` | strict boolean |
| `reasoning_effort` | `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`; `none` iff thinking disabled |
| `max_output_tokens` | integer1–8192 |
| `smoke_output_tokens` | integer1–max_output_tokens |
| `timeout_ms` | integer1000–20000 |

The 20-second upper bound preserves the certified QA caller's existing timeout. This version does **not** promise unrestricted long-thinking answers. Supporting longer inference requires a separately reviewed asynchronous execution/qualification change, not silently extending or ignoring the caller's abort signal.

20秒上限保留已認證 QA 的既有期限。若高思考需要更長時間，必須另外審查非同步執行與驗收，不能偷偷忽略取消訊號或把截斷回答當成功。

## Validate and distribute / 驗證與同步

Using the approved Python runtime, with no network or Production mutation:

```powershell
& $env:PROJECT_PYTHON scripts/v213_model_profile.py --profile config/v213-model-profile-v1.json
$env:V213_MODEL_PROFILE_JSON = Get-Content config/v213-model-profile-v1.json -Raw -Encoding utf8
& $env:PROJECT_PYTHON scripts/v213_model_profile.py --env
```

The CLI returns normalized settings, `profile_sha256`, and `release_qualified=false`. For an installed EXE, use its user-profile path rather than editing a second template. Worker binding `V213_MODEL_PROFILE_JSON` must contain the same validated JSON; automatic Production deployment/synchronization has **not** been performed by this work. Updating a remote binding still requires an authorized deployment/configuration operation, though changing model/effort values does not require editing source code.

CLI 的 SHA256 可核對各端是否一致；它不是驗收 receipt。已安裝 EXE 的設定請以使用者檔案為準。Worker 必須同步相同 JSON；本輪未自動變更正式環境 binding。

## Protocol / 協定

- All three language implementations pass the same canonical scalar-array SHA256 test vector. Whitespace and key order do not change the profile fingerprint.
- Worker inserts the profile only into its request-scoped public context, never global mutable request state. It emits `ii_model_profile`; the gateway requires exact equality with its configured profile before sending inference.
- Gateway derives the selected model from the profile, not a stale legacy model environment value. It rejects unknown/colliding catalog identities, missing/mismatched profile requests, incomplete answers and wrong response models. Timeout returns bounded `MODEL_PROFILE_TIMEOUT`; no silent effort downgrade or raw exception leakage.
- Gateway health/response pins expose `model_profile_sha256`. Worker smoke verifies it; no-write readiness accepts `expected_model_profile_sha256` and rejects drift.
- PowerShell's actual route probe uses the profile's model, thinking, effort and smoke budget. Gateway reuse/public health also requires its exact profile fingerprint, including when only thinking settings change. Legacy short-answer behavior remains only when no profile is configured.
- Profile/model changes require fresh qualification. EXE selection records explicitly carry `model_profile_qualified=false`; selecting a model is not evidence of a complete answer.

## Revalidation / 重新驗收

- Worker/typecheck:23 files/160 tests PASS, including actual public-QA request construction, two model identities, drift/invalid fields and readiness/smoke checks.
- Python profile tests and actual authenticated gateway tests PASS: strict schema, duplicate rejection, hash parity, model replacement, thinking/effort propagation, mismatch rejection, incomplete response and timeout refusal. PowerShell5.1/7 actual bridge functions and publication contract PASS.
- Development EXE compiled and passed `--model-profile-self-test`, `--model-selection-self-test`, `--self-test`, `--pipe-hold-self-test`. Profile self-test uses isolated configuration, exercises atomic replacement and actual child-process JSON propagation. This is not a packaged/install-qualified release.
- Full Python646/2 skipped retains ONE error: the old live receipt's runtime source manifest no longer matches. It was not restamped or relaxed to make new code pass.
- Actual Worker-generated research request → authenticated development gateway → existing Q5 Router failed closed. Final observed result: HTTP502, `COMPACT_RESPONSE_INCOMPLETE_OR_MODEL_MISMATCH`, `failure_kind=INCOMPLETE`,17797ms. This identifies an incomplete answer rather than model-identity drift. Earlier failures remain preserved locally. No reasoning transcript was logged or retained.
- Requested xhigh/thinking-enabled remains distinct from verified model/template xhigh behavior. Previous simple arithmetic success is not a substitute for complete research/LINE/live qualification.

完整 Python 與真實研究問答仍未全過；新版正式發布仍被阻擋。下一步是解決高思考的完整回答／時限問題，完成 profile-aware live receipt 驗證，再做精確來源 Windows、封裝、安裝與發布驗收。

## Runner evidence / Runner 證據

The supplied runner's275 files matched the official v2.337.0 archive (SHA256 `1150692afa94e71f872017e254ea55b6eece1eece3fe7e3a6d4c93d0a1b85cfc`). Reviewed validation-only run[34303303119](https://github.com/always7895/investor-intelligence/actions/runs/34303303119) succeeded on earlier source `4fade419e02d1b0fd9d7c9a9361ed25de79d8f77`, produced no artifacts, and then deregistered its ephemeral runner. That historical run does not qualify these newer profile changes. The host is not represented as a VM/security sandbox; only reviewed same-owner code may execute.
