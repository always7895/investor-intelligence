# Investor Intelligence v2.1.3 All-in-One

This distribution puts the v2.1.0, v2.1.1, v2.1.2 and v2.1.3 source snapshots inside one outer ZIP.

Run `InvestorIntelligence.exe` for the bilingual launcher. It can start the local llama.cpp bridge, refresh public data, and—after a separate confirmation—activate the accepted seven-field 08:00 / 21:00 LINE schedule.

Machine field keys stay stable in English. Traditional Chinese and English labels are defined in `config/field-labels.zh-en.json`. The v2.1.3 formatter supports `zh-TW`, `en`, and `bilingual` headers; `zh-TW` remains the safe default because it matches the H6B2 accepted payload.

Formal activation is fail-closed: current Top20/report order must match, the report and pipeline must be fresh, the payload must fit one LINE text message, and a failed deployment/sync restores the exact prior Worker version.

The production v2.1.3 entrypoint delegates ordinary fetch/Q&A behavior to the accepted v2.1.2 owner Worker, so the existing research and local-model QA paths are preserved.

Local model selection is automatic from the first ID returned by `/v1/models` (fallback: `qwen3.8-27b`). The bridge can also start the existing local launcher if no healthy loopback llama.cpp endpoint is found.
