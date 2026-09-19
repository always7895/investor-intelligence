# Model runtime contract / 模型串接與切換

[Current acceptance](../state/STATUS.md) · [Execution lanes / SKILL audit](RESEARCH_EXECUTION_AUDIT.md)

Historical model, EXE, runner and installed-state observations are not today's acceptance. Full earlier record and failed receipts remain in Git: `git show 4ba2a606c9e459884e15354aa91798ec432df0ba:docs/MODEL_RUNTIME_MIGRATION.md`. No restamping, failed-source fallback or current-session deployment authority is granted here.

## Identity, transport and controls

- Use the existing approved loopback Router, normally `http://127.0.0.1:8080`, and exact operator-selected catalog identity. Do not guess by model family, launch another server/model, change presets or infer capability from a name/HTTP200.
- Explicit/saved endpoint must be a loopback base URL without credentials, paths, queries or fragments. Catalog redirects are disabled; at most `/models` and `/v1/models`, 1MiB response, 4.5s I/O deadline per path and 1024 unique identities/aliases. No `reload=1`, process/port scanning or replacement stack in bridge endpoint resolution.
- Reject alias collisions and conflicting/malformed selection/profile types. Explicit inputs do not depend on an unrelated malformed compatibility file. A returned endpoint/catalog alone is not a completed answer.
- EXE exposes model and manual THINK selectors; `none` disables thinking, other supported profile efforts request it. Save model/mode as unqualified, preserve token/time limits and lock selectors during operations. Manual choice is not automatic best-mode detection or proof the model honors each effort.
- Native candidate tests exercise actual Use/Save handlers, profile bytes and child propagation. They do not qualify an older installed EXE. `--model-catalog-check` is metadata only; Test reply and `--model-route-check` share the actual EXE→PowerShell `-RoutingCheckOnly` caller.
- Routing checks require the validated profile, exact complete marker and existing 64-bit CPython3.12.10 with requests. They never install Python, create a gateway/tunnel, read deployment credentials, register tasks or publish. Invalid mixed mutation/version flags cannot bypass checks. The GUI saves unqualified selection; the CLI does not.

## Profile authority

Schema: [config/v213-model-profile-v1.json](../config/v213-model-profile-v1.json). Shared validation: [Python](../scripts/v213_model_profile.py), [Worker](../cloud/src/v213/model-profile.ts), EXE parser.

Precedence: explicit `V213_MODEL_PROFILE_JSON`, then `%LOCALAPPDATA%\InvestorIntelligence\UserData\config\v213-model-profile-v1.json`, then packaged template. The compatibility selection file/installation receipt is not model or qualification authority.

- Exact closed scalar types; no unknown/duplicate keys, singleton-array coercion, invalid effort or conflicting thinking flags.
- Fixed-order scalar-array SHA256 shared across languages; changed profile invalidates prior qualification.
- Per-file replacements are atomic, **not** a transaction across profile, compatibility selection, child and remote Worker.
- Gateway/Worker must share exact profile identity; health, readiness and completed response must agree. Do not extend the certified caller's deadline to fit long thinking.
- Current installer metadata emits `preferred_model=null`, `model_selection_authority=runtime_model_profile`, `model_profile_qualified=false`. Installing code never chooses/certifies a model.

## Readiness and source-bound evidence

Per-request HttpClient transport is direct, cookie/default-credential/redirect-free, 10s/1MiB bounded and strict UTF-8. HTTP failures remain failures except the explicit409 compatibility result. Keep version/hash/nonce/primitive-type checks and three-consecutive-proof requirements; no global proxy changes.

QA reference selection requires regular HEAD-committed files and identical worktree bytes. Missing/invalid/drifted pointers never fall back. Both callers must still run freshness/profile/runtime verification; selecting a receipt is not qualification. New ZIPs bind the reference path/SHA in HOTFIX-REFS and adjacent Windows/QA/delivery receipts; trusted-source archive verification never imports archive code.

Historical none/low markers, cold/warm cases, extracted installers and earlier successful CI remain tied to their original source and scope. They are not all-THINK-mode, live-data-rights or whole-release acceptance. Preserve all failed/truncated/unsupported responses without reasoning transcripts or raw private exceptions.

## Required future acceptance

1. Probe only the approved exact model serially; retain UNKNOWN for unobservable mode behavior.
2. Complete representative answers within real task/latency budgets. Healthy endpoint, settings, catalog, reasoning-only output or a fixed marker is not research quality.
3. Test EXE→actual child→authenticated gateway→Worker→complete answer, including drift, timeout and incomplete response negatives. Full SKILL research needs its own verifiable source/tool execution, not compact-Q&A attribution text.
4. Validate full installed dependency chain/actions, fresh source-bound Windows proof and independent archive/receipt/install evidence. Source changes invalidate old runtime manifests.
5. Production synchronization, real LINE delivery and schedule changes require explicit current-session authorization. No stale activation replay or paid fallback.

Local settings validation only:

```powershell
& $env:PROJECT_PYTHON scripts/v213_model_profile.py --profile config/v213-model-profile-v1.json
```

It returns settings/fingerprint and `release_qualified=false`, not deployment approval. Package acceptance, automatic THINK selection and installed live acceptance remain separate.
