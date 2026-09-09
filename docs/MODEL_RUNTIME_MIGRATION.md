# Configurable model migration / 可替換模型遷移

## Operator request / 本次要求

The operator now selects Q5 with thinking enabled and requests `xhigh`, with future model replacement through the EXE. This is a **new qualification target**, not permission to rename a Q6 receipt or bypass publication gates.

本次改以 Q5、thinking 開啟、要求 `xhigh` 為新驗收目標；未將舊 Q6 證據改名，也未啟用未驗證的正式發布。

## Observed, not inferred / 實測與界線

- Existing Router only: localhost:8080, max_instances=1; no second server or preset change.
- One Q5 request supplied `reasoning_effort=xhigh` and `chat_template_kwargs.enable_thinking=true`. HTTP200, matching canonical model, finish_reason=stop, correct synthetic arithmetic answer, reasoning present; 43 completion tokens, about14s including possible startup. This is not a latency benchmark or product acceptance.
- llama.cpp b10867 documents `xhigh` as an effort level, but API acceptance does not prove a particular model/template interprets the level. Separate capability/behavior verification is required. No reasoning transcript is retained in the development summary.

既有 Router 上單次 Q5 請求已成功且包含 reasoning，但尚未證明模型模板會依 xhigh 調整強度。不可把 HTTP200、模型可用或單一算術答案當成產品驗收。

## EXE scope / EXE 範圍

The launcher already discovers model IDs and stores user selection outside the installed executable. However, the compact protocol, bridge, Worker readiness and release evidence still contain Q6-specific contracts. **Selecting another model in the UI is not end-to-end support.** No new EXE is qualified by this change.

EXE 已有模型探索／選擇機制，但完整協定尚有 Q6 限制；不能只改下拉選單或常數便宣稱可自由替換。

Required implementation, still pending:

1. One versioned runtime profile for selected canonical ID, requested reasoning mode/effort, token/time bounds and verified backend/template capabilities; no model-name-based capability guessing.
2. EXE, gateway and Worker consume the same profile identity/hash. Unknown IDs, alias collisions and unsupported effort levels fail explicitly; no silent downgrade from xhigh.
3. Separate requested settings from observed support. Preserve publication, source/freshness/privacy and response-completion checks. Longer thinking may require the existing asynchronous answer path; do not merely extend an expired LINE reply deadline.
4. Model/profile changes invalidate the associated live qualification. Re-run exact-source negative tests, actual caller tests and a fresh complete matrix before activating the new profile. Keep historical Q6 receipts unchanged.

以上仍待實作與重新認證，不是已完成的發布宣告。

## Runner scope / Runner 範圍

The supplied Windows runner was compared against all275 files of the official v2.337.0 archive (SHA256 `1150692afa94e71f872017e254ea55b6eece1eece3fe7e3a6d4c93d0a1b85cfc`). Registration uses an ephemeral runner and the distinct `investor-intelligence-reviewed` label, without the old `investor-intelligence` label. This prevents it from accepting the known old queued release workflow. The current workflow additionally restricts the actor to the repository owner.

Actual [Windows run34303303119](https://github.com/always7895/investor-intelligence/actions/runs/34303303119) succeeded on exact source `4fade419e02d1b0fd9d7c9a9361ed25de79d8f77`. All package/upload/release steps were skipped and artifact count was zero. The ephemeral runner then exited and deregistered as intended; it must be re-armed for the next reviewed job. This is not Q5/EXE/product qualification.

實際 Windows 工作已成功完成；未產生發布檔案，單次 runner 已自動退出／解除註冊。下一次受控工作需重新登記，並非持續運行的服務。

The authoritative workflow's `validation_only` input is opt-in and excludes every package/upload/release-qualification step. It proves runner execution and regression only, never Q5 acceptance or Production deployment. The host is not represented as a VM/security sandbox; only reviewed same-owner code may execute. Runner credentials stay in its local credential store, outside Git/artifacts; registration tokens are not printed or passed in command arguments.
