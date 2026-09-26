# Current state / 目前狀態

Updated 2026-09-26 (22:40 Asia/Taipei) by an operator-directed Claude Code session (master and single tracked writer; operator authority 2026-09-25/26). Earlier detail: `git show 3ac39a1:state/STATUS.md` (20:45 seal, full production record), `git show a8c6e58:state/STATUS.md` (17:15), `git show 59049db:state/STATUS.md`, `git show 38860e7:state/STATUS.md`; V12 `git show 0f5358b:state/STATUS.md`. Release identity stays in `README.md`.

## Identity

- Branch `fix/options-provenance-audit`, draft PR #37 to `main`; PR CI reports COMPLETED_SKIPPED (not PASS). DEVELOPMENT_COMPLETE=false; FINAL_RELEASE_COMPLETE=false.

## Production (unchanged since 20:45)

- Worker `25377354-0ff5-4a28-a78b-82ec2457729f` (source `16cb1b3`); runtime LOCAL_SOURCE_CHECKOUT `ff6dc42`, tx `75cc59dc…`; hourly task `InvestorIntelligenceSealedFreshness` (:12); LINE Q&A relay live on ninfer `Qwen3.8-27B` through the watchdog task. Rollback order and secrets: `git show 3ac39a1:state/STATUS.md`.
- Not deployed: `bdd72e5` and every commit below. A Worker deploy plus a runtime reinstall needs the operator's go in the session that does it.

## Commits after 20:45 (tests and gates PASS; not deployed)

| Commit | Change |
| --- | --- |
| `13d7c85` | lane 6: every covered-call high strike needs delta <= 0.20; chains without Greeks (Nasdaq Stockholm, Nasdaq US fallback) use the volatility implied by the strike's own bid/ask (`delta_basis` QUOTE_IMPLIED). Live SIVE: strike 62 implies 157% volatility, delta 0.061 (kept, now labelled). A fixed moneyness cap was rejected (12% OTM is delta ~0.40 at 100% volatility) |
| `b3f5e8d` | lane 3: RPO timing as a word fraction ("one-third", Micron: its card said "not disclosed") or with "during" (Nebius); extractor v4 re-reads cached filings |
| `dee1a05` | lane 4: 排名/前20/前二十/瓶頸排名/TOP20。 reach Top20 v3 (they served the legacy seven-field report), 產業排名 the industry ranking; 瓶頸詳情NVDA, "NVDA 詳情" (Top20 only), SIVE/5351 base symbols; 選擇權 and no-cycle option phrasings; help texts stop naming the dead 最新期權; the v3 renderer no longer throws on a missing `news.ratio` |
| `e8824ae` | Taiwan listings show TWSE/TPEx official monthly revenue beside the Yahoo quarter (`fundamentals.cross_check`, never differenced); `docs/SOURCE_DIVERSITY_AUDIT.md` matrix brought up to date |
| `4bae22f` | Stockholm: SIVE's own interim report from Cision beside the Yahoo quarter ("公司財報公告：Cision 2026-Q2 營收年增 -12%"); one feed read a day, the release page only for a new report; figures + URL cached in `data/cache/cision_interim_revenue.json` |

Gate run 22:10 (final tree): security, documentation boundary/structure, workflow supply-chain PASS; typecheck PASS; vitest 955 passed / 2 skipped; offline suite 2742 OK (`PYTHONUTF8=1`, CPython 3.12.10). The only offline failure before this update was this file missing the `38860e7` pointer that `tests/test_agent_skill_structure.py` requires (dropped at 20:45).

## Operator decisions (2026-09-26)

- ChatGPT review MCP is now `chatgpt-web` (`D:\chatgpt-web-mcp\src\index.js`, dedicated signed-in Chrome profile, zh-TW UI) in the workspace `.mcp.json`, replacing `chatgpt-codex` (`scripts/codex_review_mcp.py`, kept in the repo). Pro first; 極高 only when Pro is locked or spent. On 22:00 the tier slider showed 極高 (4 of 5) and the fifth (Pro) position 「已鎖定」. Its selectors are zh-CN/English: use only `chatgpt_send_message` (`answerTier`, `newChat`, inline prompt) and `chatgpt_route_new_chat`; no uploads or mode/model/thinking options. Rule recorded in the workspace `AGENTS.md`. No pointless questions.
- Local model: ninfer `Qwen3.8-27B` on :8080 (shared GPU, concurrency 1); the System One decider stays retired. Alpha Vantage key as DPAPI ciphertext; the plaintext desktop note is still the operator's to delete. No OpenDART/data.go.kr key; Nasdaq data accepted; Google Finance rejected.

## Open lanes

2. Source diversity: Taiwan (TWSE/TPEx monthly revenue) and Stockholm (SIVE via Cision; GO_WITH_LIMITS from its robots.txt, `%TEMP%\ii-live\gemini-cision-terms.result.md`; MFN RSS disallowed; the Sivers site is bot-blocked) done in code. Korea next: Samsung only via its IR statement PDF (needs a PDF parser outside the hash-locked requirements), SK hynix newsroom terms forbid robots (a curated per-quarter config, as the Hyosung orders); Yahoo matched both exactly for 2Q26 (`%TEMP%\ii-live\gemini-lane2-sweden-korea.result.md`). Japan/Korea price shards stay Yahoo daily closes; consensus outside the US Yahoo-only.
3. Orders: MU fixed. CRWV (24M only) and SNDK (12M only) disclose no other horizon. AXTI ("through the first half of 2029") and NBIS (20-F/6-K, 28%→36% within 24M) have no deep report (only domestic SEC filers get one): DEFERRED_WITH_REASON until foreign-filer deep reports exist. Korea HD Hyundai Electric deck unreadable keylessly.
5. Deferred: report-age gates for carried reports and federation readers (certified `cloud/src/qa.ts` needs recertification); the CI R75 route blocks release qualification.
14. Deploy the commits above (Worker + runtime reinstall + seal + post gate), then refresh company reports so MU's schedule appears. Needs the operator's go.

Closed today: lanes 1, 4, 6, 7, 8, 9, 10, 11, 12, 13.

## Closed components — no reopening without regression evidence

- Top20 single-writer programme T1–T11 (`90563ee` … `f5bfe78`); T1 finite fractional ordering (`5208d64`), T2 nonauthorizing period declarations (`26842de`), T3 forward comparison declaration diagnostic (`689a682` → `a944410`); O1 options venue coverage shadow (`11436e6`), Case9 (`c178127`), R3A (`e45c1d6`), research method quarantine (`c6ce527`); I1/I2/I3 identity shadows, E2A synthetic capacity, hermetic fixtures. Preserved failures and receipts remain immutable (V12 register).

## Boundary flags

NATIVE_ATTEMPT_COUNT=0; NATIVE_EXECUTION_AUTHORIZED=false; CAPACITY_EVIDENCE=UNQUALIFIED; publication_eligible=false for candidates; global P0 NOT_REAUDITED. Serenity primary; Leopold Aschenbrenner CONTEXT_ONLY for company proof, leads the industry ranking since 2026-09-26 (operator).

## Control plane

Claude Code is master and single tracked writer (operator 2026-09-25). Herdr w9 helpers write result files only: p5 `qwen-local` (ninfer Qwen3.8-27B: code analysis and reviews), p7 `gemini-review` (Gemini 3.8 flash: web research and audits). Each task starts with `/new` (send it with `MSYS_NO_PATHCONV=1` from Git Bash, or it arrives as a path). Tonight: Gemini audits (lane 4, Taiwan revenue, RPO passages, Sweden/Korea); Qwen patch proposal (lane 6) and reviews (lanes 6, 4+3, 2). The wB panes belong to another project.

## Workspace fixes (outside the repository, logged)

- Pi `[Extension issues]`: `pi-mcp-adapter` failed because `~\.pi\agent\settings.json` had a UTF-8 BOM written by `Configure-Pi-NInfer.ps1` (Windows PowerShell `Set-Content -Encoding UTF8`). The kit and installed copies now write UTF-8 without BOM and read UTF-8; `models.json` BOM removed; the project `.pi/sol-pi.json` reducer that named the removed `tabby-local` provider is off. Receipt `_archive\extension-issues-fix-20260926T132956Z\RECEIPT.md`.
- `.mcp.json` and workspace `AGENTS.md` preimages: `_archive\chatgpt-web-mcp-switch-20260926T135913Z`.

## Handoff (2026-09-26 22:10)

- Next: lane 14 deploy on the operator's go; lane 2 Korea; the ChatGPT review of `3ac39a1..28b9f94` is queued (`%TEMP%\ii-live\chatgpt-review-queue.sh`, result `chatgpt-review-2210.result.md`) behind another project's ChatGPT operation that has held the browser lock since 22:11.
- Scratch: `%TEMP%\ii-live` (tasks, results, diffs, offline runs).
