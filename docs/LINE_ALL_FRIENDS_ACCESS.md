# LINE all-friends access (V213_LINE_ACCESS_MODE)

Status: development only. The merged code is behaviour-neutral: the Production template ships `V213_LINE_ACCESS_MODE = "owner_only"`, so nothing reaches any LINE user until a separate, operator-authorized rollout (see [Rollout](#rollout-not-part-of-the-code-change)). Operator decision of 2026-10-11: every LINE friend in a direct chat may use the public features and the local-model Q&A, with a per-friend limit and a bounded queue so the single shared GPU is not overloaded. Personal holdings, IBKR data, scheduled push, notification settings, pairing and admin routes stay owner-only.

Runtime path: `cloud/src/v213/production-worker.ts` -> `cloud/src/v211/worker.ts`. The policy lives next to the gate it replaces in `cloud/src/v211/line-access.ts`; the friend lane's counters live in the Durable Object `V213FriendQaGate` (`cloud/src/v213/friend-qa-gate.ts`). The separate shared bot (`cloud/src/worker.ts`, `LINE_ACCESS_MODE` = `disabled|allowlist`) is unchanged; the new switch has a different name on purpose.

## The switch

| Value of `V213_LINE_ACCESS_MODE` | Behaviour |
| --- | --- |
| exactly `all_friends` | Direct-chat friends are served as described below. |
| anything else (missing, empty, wrong case, spaces, garbage) | `owner_only`: today's behaviour, fail closed. Non-owners get silence and cause no storage access; the owner path uses the same claim, rate-limit and complete KV writes; zero Durable Object calls. |

Rollback is the same variable set back to `owner_only` plus a config redeploy. The Durable Object class and its data may stay; nothing reads them in `owner_only` mode. `/health` reports `line_access_mode`, `owner_only` (derived from the mode) and `friend_queue_configured`; `/v213/readiness` reports `line_access_mode`. `direct_chat_only` stays `true`: groups and rooms are rejected before any storage in every mode.

## Access policy

Pure functions: `classifyLineRequest` (ordered table), `decideLineAccess(mode, ownerState, sourceType, class)`, `resolveOwnerState`. Owner state is `owner`, `not_owner` or `lookup_failed`; `lookup_failed` is derived only from a thrown KV read, is never the owner, and never causes an unpair, a delete or an epoch rotation. Data commands (`刪除我的資料`, memory commands) answer the service-busy text while the owner lookup fails, while public reads and Q&A proceed as for a friend (a parked job is written only under that tenant's own epoch), so a transient KV error can never delete or rotate the real owner's data.

| Feature | Scope | All friends | Owner |
| --- | --- | --- | --- |
| Follow greeting, help | ALL_FRIENDS | friend text without the notification line, plus the educational sentence | existing text |
| Top 20, bottleneck list and detail, macro, potential ranking, equity lookup, ticker research, reports, option observations, covered-call, manual option arithmetic, `系統狀態` | ALL_FRIENDS | yes (`系統狀態` reduced to the freshness verdict) | yes |
| Portfolio / holdings words | ALL_FRIENDS | static refusal; no path to any data exists for anyone | same |
| Local-model Q&A | PER_FRIEND_OWN_DATA | yes, through the friend lane | yes (counted, never queued) |
| `查看結果 <REF>`, `刪除我的資料`, memory commands | PER_FRIEND_OWN_DATA | own tenant only | own tenant |
| `取消配對`, `通知狀態`, pairing | OWNER_ONLY | one neutral text (identical whether or not an owner exists); a pairing attempt while an owner is paired stays silent and writes nothing | yes |
| Scheduled push, test push, admin routes | OWNER_ONLY | not reachable from LINE | owner / HMAC admin |

Unknown text never maps to an owner-only handler: only the exact `取消配對`, `通知狀態` and pairing patterns do.

Alpha Vantage derived values are owner-only (operator 2026-10-11, `OPERATOR-DECISION-S1-AND-ALPHAVANTAGE-FRIENDS-20261011.txt`, Q2): every viewer whose owner state is not `owner` (a failed owner lookup included) reads the sealed quotes and options objects through `cloud/src/v213/alpha-vantage-viewer.ts`, which withholds the quote row whose `source_url` host is exactly `www.alphavantage.co` (or whose source label or family is the producer's exact Alpha Vantage name) and turns the covered-call cycles built on that spot into the unavailable state 「現價暫不可用」; the rule runs after the snapshot digest check on the parsed copy only, the owner and `owner_only` mode are unchanged, and a row of unknown provenance stays as today.

## Friend lane and limits

All friend counters live in the Durable Object; friend traffic performs no KV writes except the two writes of a parked slow job and the KV writes of the user's own data commands.

| Limit | Value | Where |
| --- | --- | --- |
| Webhook-event dedupe | 24 h by hash of `webhookEventId` | DO |
| Public reads per friend | 20 per minute, 400 per Taipei day | DO |
| Data commands that write KV (`刪除我的資料`, memory) | 5 per friend per Taipei day | DO |
| Model questions per friend | 3 per minute, 30 per Taipei day, 1 in flight + 1 waiting | DO |
| Friend model calls in flight | `V213_FRIEND_QA_GLOBAL_INFLIGHT`, default 1, clamped 1..4 | DO |
| Waiting friends | `V213_FRIEND_QA_QUEUE_MAX`, default 2, clamped 0..8 | DO |
| Bounded wait | `V213_FRIEND_QA_ACQUIRE_WAIT_MS`, default 5000, clamped to `absolute_budget_ms - timeout_ms - 2000` = 6000 | DO |
| Lease TTL | `absolute_budget_ms + 12000` = 40 s | DO |
| Parked-job KV writes | `V213_FRIEND_JOB_WRITES_PER_DAY`, default 150 (two per job); over the cap: busy reply and no parked job | DO |

Day buckets use a fixed +08:00 boundary (Taiwan has no DST), so 「明天再試」 is literally true. The wait is an in-request timed wait inside the acquire, never a durable parked queue; an evicted, unbound, failing or silent Durable Object makes friends see the busy text (every gate call is bounded: 2 s, and the acquire adds its wait plus 1.5 s; the owner's call is bounded at 2 s and its result ignored). The whole friend event runs inside `ctx.waitUntil`: wait (at most 6 s) + `timeout_ms` (20 s) + margin stays inside `absolute_budget_ms` (28 s); a test pins this.

`V213_FRIEND_QA_GLOBAL_INFLIGHT` is coupled to the gateway's `II_GATEWAY_MAX_CONCURRENT_GENERATIONS` (default 1; the gateway answers HTTP 429 above it). Keep it at or below the gateway value, and leave one gateway slot for the owner: the owner is never blocked by the friend lane (it takes a lease at once and counts toward the in-flight cap), but a saturated gateway can still answer the owner with its 429. A gateway 429 or outage reaches the Worker as the `LOCAL_MODEL_OFFLINE` answer and is mapped to the neutral busy text; `qa.ts` and `compact-qa.ts` are not touched.

The refusal of first-person portfolio or account text runs before a slot is taken, so such questions never occupy the GPU lane.

## Texts (zh-TW, reviewed)

- Owner-only command from a friend: 「此功能僅限服務擁有者使用。Top 20、瓶頸榜、期權觀察、個股查詢與 AI 問答都可以直接使用，輸入「說明」查看。」
- Model busy (queue full, wait over, gateway 429 or outage): 「目前 AI 問答暫時無法處理，這則問題沒有被處理，請稍後再試。Top 20、瓶頸榜、期權等公開查詢不受影響。」 No time is promised.
- Gate unavailable: 「服務目前忙碌或暫時無法處理，這則訊息沒有被處理，請稍後再試。」
- Rate limits: 「請求過於頻繁，請稍後再試。」; AI per minute 「AI 問答每分鐘最多 3 次，請稍後再試。」; AI per day 「今日 AI 問答次數已達上限（每日 30 次），請明天（台北時間 00:00 後）再試。」; own question still running 「你前一個 AI 問題還在處理中，請等它回覆後再問。」
- Parked slow answer: 「問題已收到，參考編號 <REF>。請稍後在這個聊天室輸入「查看結果 <REF>」，1 小時內有效；推播僅限擁有者，只有你自己的聊天室能查看這個結果。」
- Portfolio / account refusal: 「本服務只處理公開資料，不接受也不提供個人持倉、帳戶或券商資料。請改問公開的產業、個股或期權觀察。」

## Privacy invariants

- Tenant ids are the existing HMAC ids; the gate stores only a further hash of them, integer counters, bucket expiries, lease records and hashes of webhook event ids. Never message text, replyTokens, raw LINE ids or the owner id (a test dumps every row and request body).
- A friend never sees another friend's data, jobs or answers: parked jobs are AES-GCM encrypted under the friend's own tenant key and epoch, read only by `查看結果` in the same chat; push is owner-only, so there is no other delivery channel.
- Portfolio, holdings and IBKR data never reach LINE, the Worker or public KV for anyone. `delete_data` for a friend removes only the own tenant prefix and its reply never mentions pairing.
- A thrown owner lookup is treated as a friend for that event; it never unpairs or deletes.

## Rollout (not part of the code change)

Enabling `all_friends` in Production needs: a Fable 5.1 GO/NO-GO of a source-bound plan with rollback; a KV write estimate (estimate + reservations + 50 <= 1,000 per UTC day, shared with the hourly publisher; friend traffic adds only parked-job writes, at most `V213_FRIEND_JOB_WRITES_PER_DAY` plus the data commands); the Durable Object migration `v213-friend-qa-gate-v1` deployed first (the class is exported and the binding exists, but is idle in `owner_only`); a LINE reply-quota check (replies use the single-use replyToken, but verify against current LINE terms and the account plan); then current-session operator authorization. See [OPERATOR_RUNBOOK](OPERATOR_RUNBOOK.md) section 8.

A friend event that fails after admission (for example a LINE reply 5xx) is not retried on redelivery: the Durable Object already holds its event id, so the friend may need to ask again. The owner path releases its claim instead. The per-model-call counts (3 a minute, 30 a day) are charged only when a model slot is granted, never for a wait that timed out.
