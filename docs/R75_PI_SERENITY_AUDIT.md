# Pi 原生模型與 Serenity 歸因稽核 / Native Pi and Serenity attribution audit

## Observed baseline / 實際基線

Fetched source: `0ea7a8d5eac3b19937e09bac6e1d2eeda46c1b0f`. This is a new follow-up, not a replacement release acceptance report.

- Takeover workspace `.pi/settings.json` already listed project-local pi-web-access, pi-llama-cpp, pi-mcp-adapter and pi-computer-use. Installed pi-web-access version0.28.0 was read from its package manifest. No package was installed or upgraded in this audit; any future Pi install must log and use `pi install -l ...`.
- Pi itself has a native llama.cpp provider. A real tool-free, session-free Pi invocation selected `llama.cpp/Qwen3.8-27B-UD-Q6_K_XL-844843d973bf`, returned the exact synthetic marker with stop and zero tool calls. This proves the native Pi route, not a migrated LINE Gateway.
- The model's display basename is `Qwen3.8-27B-UD-Q6_K_XL`; the observed API ID includes `-844843d973bf`. Do not guess an API ID by removing that suffix or substitute another quantization.
- Project Pi defaults now select that native provider/full ID. The canonical skill was explicitly added to project settings; Pi's actual ResourceLoader discovered exactly one matching skill. Changes require a new/reloaded Pi resource context; existing sessions are not implicitly re-certified.

## Why the stocks can differ / 為何選股不同

1. `scripts/v21_serenity_top20.py::discover_candidates` uses Yahoo screeners; its preliminary selection includes screen weights, market cap and volume. `config/v21-serenity-policy.json` includes growth/undervalued growth/most-active/day-gainer screens.
2. `scripts/v211_serenity_top20.py` adds generic AI-infrastructure thematic discovery and reserved candidate slots. This is not a verified current @aleabitoreddit watchlist; do not reduce the explanation to broad screeners alone.
3. A skill path recorded in the H6B policy/receipt is not evidence that a Pi research agent actually read the complete method and performed current original-post/claim-level research. The scheduled Python pipeline and developer-facing skill are distinct components.
4. Prior direct-X qualification evidence included an unavailable original candidate. It did not establish a comprehensive, fresh current-view feed. Without original URLs and an as-of cutoff, overlap with her present selections cannot be measured honestly.
5. Research candidates, attributed positive opinions and disclosed positions are different outputs. Twenty LIMITED rows do not establish methodology fidelity, and a real positive social view does not independently validate a company advantage.

## Changes and unfinished migration / 修正與尚未完成

- Skill now separates ATTRIBUTED_SOURCE_VIEWS, SYSTEM_RESEARCH_CANDIDATES and COMPARISON; forbids replacing unavailable current views with generic Top20 or tuning weights to imitate a person.
- No ranking weights, live candidate membership, freshness/publication thresholds, Production Worker, snapshots or schedules changed in this audit. No real LINE test sent; no second model/server started.
- **The live LINE route is still the previously qualified Gateway route.** It is not yet a Pi-mediated research agent. Its existing compact policy, Worker callers, launcher and live qualification still reference the legacy alias. Do not delete the live Router alias first and break those clients.
- Candidate `scripts/v213_pi_inference.mjs` now executes through the real Pi SDK, with `config/v213-pi-inference-v1.json`: exact canonical ID, explicit XHIGH chat-template fields checked in Pi's actual onPayload callback, no tools/default resources/owner credentials/session persistence, bounded output/deadline and process-local backpressure. It is connected to an explicit development-only Gateway backend through scripts/v213_pi_transport.py; Worker/LINE callers are not migrated. Process isolation is not an OS sandbox. It receives no fresh source data and explicitly cannot claim current-source research.
- The observed GGUF template on llama.cpp b10819-6a1a922d2 supports xhigh/medium/low and maps high to xhigh. Native Pi discovery's reasoning=false was insufficient; the candidate explicitly models the supported template controls. A complete real Pi XHIGH public-methodology call passed in9935.3ms with payload validation, zero tools and no LINE transport. This proves requested template controls and a completed answer, not a guarantee about reasoning quality.
- Required next migration: Gateway/Worker caller and public-context integration → global child backpressure and async/deadline tests → Serenity source tools/evidence integration → fresh full source-bound qualification → coordinated live consumer cutover → remove only the old alias. No direct-HTTP fallback disguised as Pi.
- Current local regression:7 Node adapter tests,8 Pi transport tests and the legacy real-process Gateway regression PASS; unchanged Worker22 files/142 tests and typecheck PASS; Python596 tests with1 error/2 skipped, LIVE_SOURCE_MANIFEST_MISMATCH. New source correctly invalidates the old live receipt; it was not rewritten or bypassed. Current main Windows run33993323937 failed on a stale dependency-lock hash; the exact observed Git/CI hash is now pinned with a regression test, CI-repair-only Windows run34011893092 is in progress at this checkpoint. The candidate localhost HTTP Gateway→Pi→Q6 XHIGH path completed in12010.52ms with no direct HTTP inference fallback; this is not real LINE acceptance. Candidate pi_public_v1 currently rejects snapshot context/history rather than silently dropping it; public-context and Worker/reference-job integration remains next.
- LINE must never expose the coding agent's unrestricted filesystem, shell, computer-use, credentials or owner context. Public research tools require a distinct restricted execution profile; installing a web package is not a sandbox or a freshness proof.

## Comparison inputs / 差異核對所需資料

Use2–3 original posts (or public original URLs visible in supplied screenshots) plus the intended date range. Record precise stance, ticker/share class, later revisions and each candidate's inclusion/exclusion stage. Do not fabricate current picks from archives or search snippets. Public reconstruction is not an official/private Serenity formula.
