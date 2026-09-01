# Investor Intelligence v2.1.3 All-in-One

This distribution puts the v2.1.0, v2.1.1, v2.1.2 and v2.1.3 source snapshots inside one outer ZIP. Fully extract the ZIP before running `InvestorIntelligence.exe`.

The bilingual launcher can refresh public data, start the local llama.cpp bridge, and—after a separate confirmation—activate the accepted seven-field 08:00 / 21:00 LINE schedule. PowerShell failures now surface the real diagnostic tail and save a complete log under `%LOCALAPPDATA%\InvestorIntelligence\logs\launcher\`.

Local model discovery probes common loopback ports and listening llama/localai/kobold processes, then reads the first ID from `/v1/models` (fallback: `qwen3.8-27b`). A Cloudflare quick tunnel must pass public `/health` with `llama_reachable=true`; DNS propagation has an SNI-safe Cloudflare-DNS + `curl --resolve` fallback. The shared secret is persisted only through Windows DPAPI.

Formal activation is fail-closed and explicitly requires a fresh healthy local-model bridge. Current Top20/report order must match, the report and pipeline must be fresh, the payload must fit one LINE text message, and a failed deployment/sync restores the exact prior Worker version. The production v2.1.3 entrypoint delegates ordinary fetch/Q&A behavior to the accepted v2.1.2 owner Worker, so existing research paths remain intact.

After successful activation, a stable runtime is copied to `%LOCALAPPDATA%\InvestorIntelligence\V213Runtime`; the local refresh tasks are upgraded to 07:20 and 20:20, ahead of the 08:00 and 21:00 LINE pushes. If a later model tunnel refresh fails, the scheduled report can still be promoted without replacing the active Worker with a model-less route; open-ended generation fails closed until the next healthy bridge refresh.

Machine field keys stay stable in English for API/KV compatibility. `config/field-labels.zh-en.json` now covers the current public Top20, evidence, snapshot/source metadata, public options DTO, v2.1.2 report and v2.1.3 report schemas with both `zh-TW` and `en` labels. CI runs `scripts/audit_v213_bilingual_public_fields.py` and fails if required current-public-schema coverage is incomplete. The v2.1.3 formatter supports `zh-TW`, `en`, and `bilingual` headers; `zh-TW` remains the Production default because it matches the H6B2 accepted format.
