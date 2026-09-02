# Investor Intelligence v2.1.3 All-in-One

This distribution puts the v2.1.0, v2.1.1, v2.1.2 and v2.1.3 source snapshots inside one outer ZIP. Fully extract the ZIP before running `InvestorIntelligence.exe`.

The `ModelSelect-R43 HealthSchema2` maintenance build can scan the current llama.cpp router catalog, persist an explicit model choice, refresh public data through that selected model, start the selected-model bridge, and—after a separate confirmation—activate the accepted seven-field 08:00 / 21:00 LINE schedule. PowerShell failures surface the diagnostic tail and save complete logs under `%LOCALAPPDATA%\InvestorIntelligence\logs\launcher\`.

## Explicit local-model selection

The launcher reads current IDs from `/v1/models?reload=1`, `/models?reload=1`, or `/v1/models`. The preferred choice is `RVN-Q6_K-multilingual-mtp`, but any model ID actually present in the router catalog can be selected from the drop-down list.

Use the launcher in this order:
1. Select **Scan**.
2. Choose `RVN-Q6_K-multilingual-mtp`, or another intended model ID.
3. Select **Use**.
4. Run **Start selected model + refresh** or formal activation.

The selection is persisted in `%LOCALAPPDATA%\InvestorIntelligence\UserData\config\v213-model-selection.json`. Manual refreshes, scheduled refreshes, bridge startup, and formal activation all consume the same selection. The system no longer silently selects the first catalog entry and no longer silently falls back to Gemma or `qwen3.8-27b`.

Before the bridge is accepted, the selected model must pass a minimal `/v1/chat/completions` routing probe. Both loopback and public gateway `/health` responses must identify the same `selected_model` with `selected_model_available=true`; a mismatch fails closed before any Production deployment.

HealthSchema2 also requires `service=v213-local-llm-gateway` and `health_schema_version=2`. If port 8814 is occupied by a legacy v2.1.2 gateway or another process, the bridge safely stops only its own stale gateway or selects the next free loopback port. Missing legacy health properties now fail closed instead of throwing a PowerShell StrictMode exception.

Model discovery covers common loopback ports and the PowerShell bridge also examines listening llama/localai/kobold processes. If no service is detected, it can try the existing `D:\LocalAI\Start-LocalAI.cmd` or `D:\llama.cpp\Start-LocalAI.cmd`. The shared secret is persisted only through Windows DPAPI. Quick-tunnel DNS propagation has an SNI-safe Cloudflare-DNS plus `curl --resolve` fallback.

## Formal seven-field activation

Formal activation is fail-closed and requires a fresh healthy bridge for the exact selected model. Wrangler JSON stdout is captured separately from spinner/status stderr, so text such as `search...` cannot contaminate deployment JSON parsing. The current single 100% Worker version must be captured and validated before any secret or Worker mutation.

Current Top20/report order must match, the report and pipeline must be fresh, the payload must fit one LINE text message, and a failed deployment or later activation step restores the exact prior Worker version. The production v2.1.3 entrypoint delegates ordinary fetch/Q&A behavior to the accepted v2.1.2 owner Worker, preserving existing research paths.

After successful activation, a stable runtime is copied to `%LOCALAPPDATA%\InvestorIntelligence\V213Runtime`; the local refresh tasks are upgraded to 07:20 and 20:20, ahead of the 08:00 and 21:00 LINE pushes. Later runs keep using the persisted selected model. If its bridge refresh temporarily fails, scheduled report data can still refresh without silently replacing the Worker with a different model route; open-ended generation fails closed until that selected model is healthy again.

Machine field keys stay stable in English for API/KV compatibility. `config/field-labels.zh-en.json` covers the current public Top20, evidence, snapshot/source metadata, public options DTO, v2.1.2 report and v2.1.3 report schemas with both `zh-TW` and `en` labels. CI runs `scripts/audit_v213_bilingual_public_fields.py` and fails if required current-public-schema coverage is incomplete. The v2.1.3 formatter supports `zh-TW`, `en`, and `bilingual` headers; `zh-TW` remains the Production default because it matches the H6B2 accepted format.
