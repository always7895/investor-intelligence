# LINE GAP LEDGER — v213 Owner-Line (2026-09-16)

Scope: all identified gaps across 8 areas; 31 items. Statuses are as of worker
version `928539bd-e351-4832-9ad7-cebaeae7be37` (Task #26 deploy) and run
`20260916T131939Z-897a86efa733` (seal `c9b19102…`). P0/P1 = blocking LINE QA; P2 = planned/deferred;
DONE = closed with evidence. Sealed-run, freshtask evidence: `data/cache/probe-live-26.json`,
`state/STATUS.md` ledger.

Format per item: ID / AREA / ISSUE / SEVERITY / CURRENT_STATE / EVIDENCE / ACTION / TEST / RESULT.

## 1. Messaging API (5)

G-01 / MESSAGING / Worker deploy lag: live worker lacked Task 025A fixes (seal trim, unadmitted-source distinction, options-guidance). / P0 / DONE (deployed 2026-09-16T13:21Z).
EVIDENCE: `/v213/readiness` echoes `worker_version=928539bd-e351-4832-9ad7-cebaeae7be37`; source tree sha-matched via `npm test` in the deployed build (822/0/1 at commit). / ACTION: `npx wrangler deploy -c wrangler.v213.production.local.toml` (PRODUCTION_AUTHORIZED this session). / TEST: readiness version echo + full probe below. / RESULT: GREEN.

G-02 / MESSAGING / `snapshot:current` seal verification failed on live KV because a transport-level whitespace (LF/CRLF from the local writer) broke the exact-spelling gate; Top20 fell back to stale/fail-closed. / P0 / DONE.
EVIDENCE: repro matrix (Task 025A) — trailing LF/CRLF/space all failed pre-fix; today's sync writes byte-exact `JSON.stringify` shapes (339B pointer, zero transport bytes) and `sync_sealed_snapshot_kv.py` verified 14/14 readback before LAST pointer. / ACTION: `snapshot-seal.ts` `control()` now `raw.trim() === JSON.stringify(value)` (A) + Python `write_bytes` canonicalization (C). / TEST: seal-suite + `sync` readback + live probe. / RESULT: GREEN (pointer active, seal `c9b19102…`).

G-03 / MESSAGING / Production freshness: discovered Top20 `V21_TOP20_MAX_AGE_SECONDS=7200` window could lapse between refresh runs. / P1 / DONE (60-min cycle).
EVIDENCE: task `InvestorIntelligenceSealedFreshness` scheduled every 60 min (SC MINUTE MO 60, Ready); three prior run dirs (103001Z/113001Z/123001Z) proved the cycle; fresh run `131939Z-897a86fa` regenerated + re-pointed during this task. / ACTION: `run_production_sealed_refresh.ps1` + `publish --live-clock` + fail-closed sync (pointer untouched on any failure). / TEST: 60-min window math + fail-closed abort paths in sync script. / RESULT: GREEN (cycle observed ≥3×).

G-04 / MESSAGING / Multi-message >4900B LINE payloads could exceed choking/line limits. / P2 / DONE.
EVIDENCE: `splitLineText(text, 4900, 5)` in `core.ts` (max 5 messages pin); presentation layers route through it. / ACTION: none further (policy verified). / TEST: core split tests. / RESULT: GREEN (in 822).

G-05 / MESSAGING / SIVE/AAOI accepted-symbol surface: pre-025A, an unadmitted ticker under a SEALED view was labeled `unsealed_or_missing` (mis-labeled: understates the seal-state). / P1 / DONE.
EVIDENCE: probe `data/cache/probe-live-26.json` → `sive/aaoi_source_sealed_unadmitted: true`, `*_not_unsealed: true`; 52/52 in `v213-global-equity-lookup.test.ts` incl. the 2 new distinguishing tests. / ACTION: `global-equity-lookup.ts` branch on `view.integrity === "sealed"`. / TEST: live probe + suite. / RESULT: GREEN.

## 2. Rich Menu / UX (3)

G-06 / UX / No Rich Menu is configured for the owner channel (direct-chat-only by design). / P2 / BY DESIGN.
EVIDENCE: `production-worker.ts` allowlist-only direct-chats; `/health` reports `owner_only: true, direct_chat_only: true`; no Rich Menu handler in tree (grep 0). / ACTION: deferred — a Rich Menu requires a LINE channel-menu object + device matrix; not authorized scope. / TEST: n/a (absence pin: public-boundary gate). / RESULT: ACCEPTED-LIMIT — re-evaluate when the supervisor approves Public UI.

G-07 / UX / Seven-field Top20 card labels vs presentation spec misalignment (historical). / P2 / DONE.
EVIDENCE: commit `f031c36` (deterministic option clocks + reader label alignment); `v213-flex-builder.ts` seven-fields pins; `top20_presentation: "seven_fields"`, `top20_field_locale: "bilingual"` live in `/health`. / ACTION: alignment commit. / TEST: flex-builder tests + locale tests. / RESULT: GREEN.

G-08 / UX / Field locale default: production is `bilingual`; en/ja single-locale switching untested end-to-end on device. / P2 / PARTIAL.
EVIDENCE: toml sets `V213_FIELD_LOCALE=bilingual`; tests cover locale mapping (`v213FieldLocale`), device screenshots out of scope. / ACTION: leave as default; test-coverage only. / RESULT: ACCEPTED-LIMIT (test-only locale path is green; device validation pending real fleet).

## 3. Investor Intelligence (6)

G-09 / INT-ELIG / Ranking Top20 surfaces only after sealed publication; raw/unsealed writes must never rank. / P0 / DONE.
EVIDENCE: `98f4a18` (raw writes without pointer → INSUFFICIENT_EVIDENCE); probe: `top20_is_stale_string:false`, records `[{1,GEV},{2,6501}]`, ref `s:20260916T131939Z-897a86efa733`; retired admin route `/v213/admin/top20-report` → 410. / ACTION: sealed pointer contract + loader gate. / TEST: takeover suite 13/13 + live probe. / RESULT: GREEN.

G-10 / INT-ELIG / Rank-qualified pool is only GEV + 6501 (test-only claim tier); 6508/ENR remain uncorroborated. / P1 / OPEN (evidence-blocked).
EVIDENCE: auditor JSON `data/cache/candidate_admission_readiness_audit.json` (V4): GEV/6501 qualified; 6508/ENR uncorroborated (not ranked, by design); `publication_eligible` lane = top20-only (STATUS). / ACTION: ingest licensed 2nd/3rd-family sources before the 180-day windows close (DOE 2026-03-05 is near its limit). / TEST: admission-readiness suite (21/21). / RESULT: OPEN — never fabricates.

G-11 / INT-ELIG / Freshness of the evidence: sources gain age over time; the 60-min RE-PIN re-points the same evidence indefinitely near the limit. / P1 / MONITORED.
EVIDENCE: current live clock 2026-09-16 vs DOE `2026-04-03` (166d) and issuer dates; the 180-day research-fact window is enforced in the claim validator. / ACTION: window-close fail-closed by design; new sources required (tracked in G-10). / TEST: engine freshness parser. / RESULT: ACTIVE-MONITOR.

G-12 / INT-ELIG / Macro/industry analysis must never diverge from frozen ranking (never "re-rank"). / P2 / DONE (by construction).
EVIDENCE: macro/industry consumers read the same sealed view (`pinPublicSnapshot`); the loader suite pins that all records require the store; options-guidance engine consumes `snapshotReference`-bound input. / ACTION: contract documentation + loader pins. / TEST: 13/13 takeover + 20/20 options-guidance suites. / RESULT: GREEN.

G-13 / INT-ELIG / Option-guidance/composer sizing (strike/DTE/delta/yield/probability framework) wired but production smoke against a live contract feed is deferred (no broker feed on lane). / P2 / PARTIAL.
EVIDENCE: `cloud/src/v213/options-guidance.ts` + 20-test suite (included in 822); manual_option_calculator + provider 410 retirement pins. / ACTION: LIVE broker feed integration = external authorization lane. / RESULT: PARTIAL (logic GREEN, live feed deferred).

G-14 / INT-ELIG / Date-range / historical replay requests unsupported (Top20 is a FW9 snapshot only). / P2 / ACCEPTED-LIMIT.
EVIDENCE: `ParsedQuery.period` only ("weekly") + snapshot reference; no range parameter in the loader contract. / ACTION: rejected for v1 (frozen-replay scope creep). / RESULT: DOCUMENTED-LIMIT.

## 4. Production (6)

G-15 / PROD / ERROR worker version in SYNC (26454143 → 928539bd). / P0 / DONE.
EVIDENCE: wrangler deploy output `Current Version ID: 928539bd-e351-4832-9ad7-cebaeae7be37`; readiness echo matches. / ACTION: redeploy under current-session authorization. / TEST: `/health` 200 + readiness version + probe. / RESULT: GREEN.

G-16 / PROD / KV pointer LAST was previously violated (pointer could lead its objects). / P0 / DONE.
EVIDENCE: `sync_sealed_snapshot_kv.py` logs `OBJECTS_UPLOADED 14 → READBACK_VERIFIED 14 → POINTER_LAST 20260916T131939Z…`; abort paths print `SYNC ABORT … pointer untouched`. / ACTION: script rework (Task #23) + 025A byte normalization. / TEST: in-script verification + git history (objects commit precedes pointer). / RESULT: GREEN.

G-17 / PROD / Trigger/jitter between the 7200s freshness cap and 60-min refresh: 2 consecutive failures = still within ONE window if the last run was newer than 50 min. / P1 / MITIGATED.
EVIDENCE: task cadence recorded; ledger note in `state/STATUS.md` (Task #23). / ACTION: 60-min cadence + fail-closed sync; further headroom = optional 45-min cadence (not requested). / RESULT: MITIGATED-ACCEPTED.

G-18 / PROD / Cron LINE push (00:00/13:00 UTC triggers) depends on on-time snapshot: if freshness is capped at push time the push carries the stale notice (fail-closed, not garbled). / P2 / BY DESIGN.
EVIDENCE: toml `crons = ["0 0 * * *", "0 13 * * *"]`; freshness message path tested (top20 staleness takes `V213_STALE_RECORDS_MESSAGE`). / RESULT: DESIGN-FROZEN.

G-19 / PROD / `wrangler.v213.production.local.toml` is ignored (local-only); the committed template lane is split. / P2 / BY DESIGN.
EVIDENCE: `.gitignore` pins `cloud/*.local.toml`; template files (`wrangler.v213.production.template.toml`) are committed; no secrets in tree (security PASS). / RESULT: AS-DESIGNED.

G-20 / PROD / One-live-read audit of `snapshot:current` after each deploy is now mandatory but was pending in the M1 audit. / P1 / DONE.
EVIDENCE: this task: sync readback (14/14) + probe against that exact byte + reader version echo (live verification 3 lines). / ACTION: fold the readback verification into the standard post-deploy checklist (this run). / RESULT: GREEN (recorded in the handoff + ledger).

## 5. Security (4)

G-21 / SEC / Certified blobs (`worker.ts` = `4e0f78af402bcb6103812a3c1e06160cd838bdba` family, `qa.ts`) must never drift in ANY deploy. / P0 / DONE (verified this task).
EVIDENCE: `git diff HEAD --stat cloud/src/worker.ts cloud/src/qa.ts` = 0 across the session; canonical RC gate PASS (marshalling toggle and frozen assets). / ACTION: no workspace edits (task-wide). / TEST: gate + diff. / RESULT: GREEN.

G-22 / SEC / Legacy non-sealed admin write surfaces (`/v21…/admin/public-snapshot`, `/v212/admin/top20-report`, `/v213/admin/top20-report`) are retired to 410 before ANY auth/nonce work. / P0 / DONE.
EVIDENCE: live probe 410 `V213_SEALED_PUBLICATION_REQUIRED` (Task #22 smoke, re-confirmed at #26); route list in `production-worker.ts`. / RESULT: GREEN (retirement frozen).

G-23 / SEC / Public view read challenge is gated (`/v213/readiness` requires the challenge pair; 409 on resistance). / P1 / BY DESIGN.
EVIDENCE: live 409 `V213_READINESS_REQUEST_INVALID` with `no_write: true` echo; hidden-provisioning surface is ENR 410. / RESULT: DESIGN-FROZEN.

G-24 / SEC / Secret handling: Cloudflare credentials are only via logged-in wrangler sessions; never printed; credentials-store extraction from the EXE (`launcher/SecureCredentialStore.cs`) is installed on the local lane. / P1 / DONE.
EVIDENCE: zero `CLOUDFLARE_API_TOKEN` echo across all deploy logs (verified heuristically); `security_check.py` PASS on every gate run; EXE/credentials lane is installed behind the launcher (history `7d2a9f9`). / RESULT: GREEN.

## 6. Reliability (3)

G-25 / REL / Durable-object classes (`V213BroadcastDedupe`, `V213FreeRelayRoute`) are deployed but the broadcast/dedupe behavior is exercised by the generator only (no real-device congestion test). / P2 / PARTIAL.
EVIDENCE: toml migrations `v213-r75-broadcast-dedupe-v1`, `v213-r75-free-relay-route-v1` deployed with the version; dedupe/relay logic tested in-suite (within the 822). / ACTION: real-device congestion testing is a fleet lane. / RESULT: PARTIAL (logic green, device pending).

G-26 / REL / Free-relay local LLM route has a 300s TTL lease; gateway source-probe failures must fail closed rather than fall back (no paid fallback). / P2 / BY DESIGN.
EVIDENCE: `paid_fallback: false` live on `/health`; `FREE_RELAY_MAX_TTL_SECONDS=300` + `LOCAL_LLM_MODEL=qwen38-q6` in tomls. / RESULT: DESIGN-FROZEN.

G-27 / REL / Single-writer discipline: this session's writer is the Qwen lane; M1 audit ran read-only; no branch immediate/merge occurred. / P1 / DONE.
EVIDENCE: STATUS M1 block (`NO PULL/REBASE/BRANCH`, "single writer = Local Qwen"); `git status` clean at each commit point; no remote pushes (local branch). / RESULT: GREEN.

## 7. Tests (3)

G-28 / TEST / Full green baseline: `npm test` 822/1 (61 files), `tsc --noEmit` 0, `pytest` 1511/0/3, security + canonical RC gate PASS. / P0 / DONE (this task).
EVIDENCE: gate run in this task run (recorded in the handoff). / RESULT: GREEN.

G-29 / TEST / Live/production probe is reproducible: `data/cache/probe-live-26.json` captures run/wall/verdicts for Top20 + SIVE + AAOI + ZZZZ routing. / P1 / DONE.
EVIDENCE: JSON fields `top20_is_stale_string:false`, `zzz_intent: general_qa`, `zzz_equity_hijack: false`, reference `s:20260916T131939Z-897a86efa733`. / ACTION: keep probe artifacts as the post-deploy evidence (gitignored). / RESULT: GREEN.

G-30 / TEST / Fail-closed negative pins (tampering seal / size path / pointerless write → no authority; unknown symbol → no hijack) are frozen in-suite. / P0 / DONE.
EVIDENCE: snapshot-seal + v213-top20-report + takeover suites inside the 822; `zzz_equity_hijack:false` on the live probe; 7/7 signature-promotion tampering tests. / RESULT: GREEN.

## 8. Latest Specs (1)

G-31 / SPEC / v213 sealed-publication spec (pointer-last, thaw, run-bound reference, 7-field reader, INSUFFICIENT_EVIDENCE failure family) is fully implemented and deployed. / P0 / DONE.
EVIDENCE: commits `1c3cfa4/1331ff8/5e42584` (run 1) + `4d83c1c/6328d93` (run 2) + Task #26 (run 3 `897a86efa733`); probes + 822 test grid; spec text under `docs/` and AGENTS.md. / RESULT: GREEN — spec ↔ implementation ↔ live state are aligned.

---

Residual OPEN/monitored: G-06 (Rich Menu, by design), G-10 (6508/ENR evidence), G-11 (source elapsed), G-13 (live broker feed), G-25 (device broadcast). All P0s closed with live evidence on worker
`928539bd…` / run `131939Z-897a86efa733`.