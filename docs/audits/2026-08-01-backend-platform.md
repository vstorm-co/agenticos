# Code audit — AgenticOS, backend platform layer

**Date:** 2026-08-01 · **Commit:** `c13c6ad` · **Scope:** `backend/app/**` (~46k LOC) — the agent runtime, permissions and access resolution, the vault, the catalogs, and the services, routes and repositories built on them. Plus a targeted pass over the frontend's auth proxy and permission gating. · **Focus:** none — full dimension sweep

## Verdict

This is a well-built codebase with a genuinely unusual amount of reasoning written down, and the reasoning is mostly correct. The docstrings are not decoration: `_resolve`'s says "grep for this default when auditing cross-tenant reads", `agent_chat.py`'s explains exactly why it commits, `core/background.py`'s explains exactly what happens if nobody drains. In several cases the module that documents a hazard is the one that then walks into it — which is what makes these findings easy to state and cheap to fix.

The pattern across every dimension is the same: **the mechanism is built and correct; the wiring is missing.** Rate limiting is configured and never applied. Security headers are written and never registered. `background.drain()` is implemented, tested, and called from nowhere. `validate_webhook_url` is thoroughly unit-tested and has no callers. Account linking has a redemption path and nothing that mints a code. The gap is not craft, it is the last connection — and the tests do not catch it because they test the mechanism, not the wiring.

The other theme is the **transaction boundary**. `AgentRunnerService._run` records a run's cost in a `finally` and then lets the session roll it away; that one omission breaks the budget invariant on every surface except web chat, and it is the same root cause as the double-charged approval replay.

The single most important thing: fix the two unscoped conversation routes (AUD-001). It is one line each, it is a live cross-tenant read of full chat transcripts, and this is a multi-tenant product.

**Top three, in order:**

1. [AUD-001](#aud-001) — Any signed-in user can read and write any conversation in the deployment (Critical, S) — #1
2. [AUD-029](#aud-029) — An anonymous caller drives arbitrary GETs against the internal backend through the avatar proxy (High, S) — #13
3. [AUD-002](#aud-002) — A Slack or Mattermost bot missing one config value starves the event loop and the API stops answering (Critical, S) — #2

[AUD-003](#aud-003) (#3) is a close fourth and also a one-line fix — a failed agent run's cost is flushed and then rolled back, so no budget can see it. All four are S.

## Signals

| Check | Result |
|---|---|
| Lint | `ruff check` clean · `ruff format --check` clean (422 files) |
| Types | `ty check` exits 0. 62 diagnostics, all warnings in template-inherited code; the platform layer's `[[tool.ty.overrides]]` promote the same rules to errors and it is clean. 39 suppressions repo-wide, all with a stated reason |
| Tests | Backend: 2080 passed, 5 skipped, 91s, 100% gate on the platform layer enforced in CI. Frontend: 2424 passed across 137 files, `tsc --noEmit` and `eslint --max-warnings 0` both clean. `tests/integration/test_platform_flows.py` is 3.6k lines of named refusal behaviours |
| Dependency audit | Clean — `pip-audit` over the exported lockfile reports no known vulnerabilities |
| TODO / FIXME / HACK | 3 |
| Build / CI | 7 jobs: lint (ruff + ty + backtick check), test (pgvector pinned, migrations cycled up *and* down to base), test-frontend (lint + prettier + type-check + coverage + build), e2e, security (pip-audit), docs (`mkdocs --strict`), docker. Actions pinned by SHA. Fails the build on all of it |

The tooling here is better than most production repos. Every finding below is something the tools structurally cannot see.

## Findings

All 33 are filed as GitHub issues on `vstorm-co/agenticos`, labelled `audit-2026-08-01` plus a `severity:*` label.

| ID | Severity | Dimension | Finding | Effort | Issue |
|---|---|---|---|---|---|
| [AUD-001](#aud-001) | Critical | Tenant isolation | Conversation messages are readable and writable across every tenant | S | #1 |
| [AUD-002](#aud-002) | Critical | Async | A misconfigured Slack/Mattermost bot busy-loops and starves the event loop | S | #2 |
| [AUD-003](#aud-003) | High | Governance | A failed run's cost is flushed and then rolled back — no budget can see it | S | #3 |
| [AUD-004](#aud-004) | High | Security | Telegram webhook fails open when the bot has no secret | S | #4 |
| [AUD-005](#aud-005) | High | Correctness | The cross-org guard in `agent.py` is dead code, and resumed chats lose every user message | S | #5 |
| [AUD-006](#aud-006) | High | Authorization | `spec.skill_ids` is access-checked nowhere — a member can read another's private skill | S | #6 |
| [AUD-007](#aud-007) | High | Security | Rate limiting is configured and never applied to any route | S | #7 |
| [AUD-008](#aud-008) | High | Secrets | The vault master key defaults to a published string outside production, and rotation is impossible | M | #8 |
| [AUD-009](#aud-009) | High | Data | Cascade-vs-CHECK contradictions make deleting a user or an org 500 | M | #9 |
| [AUD-010](#aud-010) | High | Correctness | Channel account linking can never complete, so every channel message is refused | M | #10 |
| [AUD-011](#aud-011) | High | Resources | `drain()` is never called, and shutdown tears down resources in the wrong order | S | #11 |
| [AUD-012](#aud-012) | High | Resources | Three paths hold a pooled DB connection far too long | M | #12 |
| [AUD-029](#aud-029) | High | Security (FE) | Unauthenticated path traversal through the avatar proxy | S | #13 |
| [AUD-031](#aud-031) | High | Security (FE) | OAuth delivers the access and 7-day refresh token in the URL query string | M | #14 |
| [AUD-013](#aud-013) | Medium | Governance | A resumed run double-counts its own prior spend against both caps | S | #15 |
| [AUD-014](#aud-014) | Medium | Governance | Web chat loses every query-time embedding cost | S | #16 |
| [AUD-015](#aud-015) | Medium | Concurrency | Four check-then-act races with no row lock | M | #17 |
| [AUD-016](#aud-016) | Medium | Security | `SecurityHeadersMiddleware` is written, relied on, and never registered | S | #18 |
| [AUD-017](#aud-017) | Medium | Observability | Every 404 and every 403 is logged as an ERROR with a traceback | S | #19 |
| [AUD-018](#aud-018) | Medium | Governance | `record_audit` swallows every failure, and the swallow does not work | S | #20 |
| [AUD-019](#aud-019) | Medium | Secrets | A malformed sealed payload puts the decrypted secret into the log and Logfire | S | #21 |
| [AUD-020](#aud-020) | Medium | Secrets | `channel_bots.webhook_secret` is a credential stored in plaintext | S | #22 |
| [AUD-021](#aud-021) | Medium | Security | An embed token with no `iat` never expires | S | #23 |
| [AUD-022](#aud-022) | Medium | Correctness | Telegram webhooks are registered at a URL that 404s, and Mattermost bots cannot be configured | M | #24 |
| [AUD-023](#aud-023) | Medium | Async | Blocking file I/O on the request event loop | S | #25 |
| [AUD-024](#aud-024) | Medium | Error handling | Background work whose failures nobody observes | S | #26 |
| [AUD-025](#aud-025) | Medium | Data | `GET /rag/documents` has no pagination | S | #27 |
| [AUD-026](#aud-026) | Medium | Structure | Five routes call repositories directly, one of them unseals vault secrets | M | #28 |
| [AUD-027](#aud-027) | Medium | Docs | Three claims in the docs describe behaviour that does not exist | S | #29 |
| [AUD-030](#aud-030) | Medium | Security (FE) | Path traversal in every hand-rolled proxy that interpolates a route param | S | #30 |
| [AUD-032](#aud-032) | Medium | Permissions (FE) | `/rag` renders every write control to a Viewer, then 403s | S | #31 |
| [AUD-033](#aud-033) | Medium | Error handling (FE) | A failed query becomes an empty list, indistinguishable from empty | M | #32 |
| [AUD-028](#aud-028) | Low | — | Nine smaller items, batched | S | #33 |

## Quick wins

Sub-hour fixes with real value. In this order:

- [ ] **AUD-001** (#1) — pass `organization_id=active_org.id` to `list_messages` and `add_message`. Two lines.
- [ ] **AUD-029 / AUD-030** (#13, #30) — `encodeURIComponent` on every interpolated route param in `src/app/api/**`. The repo already does it correctly in three places.
- [ ] **AUD-003** (#3) — move the explicit `await self.db.commit()` from `agent_chat.py:299` into `AgentRunnerService.finish`, then delete the duplicate.
- [ ] **AUD-004** (#4) — change `if bot.webhook_secret and not verify(...)` to `if not bot.webhook_secret or not verify(...)`, matching Mattermost five files away.
- [ ] **AUD-002** (#2) — move `await asyncio.sleep(5)` out of the `except` and onto every iteration of both supervisors.
- [ ] **AUD-005** (#5) — pass `organization_id=organization_id` to the two `conv_service` calls in `agent.py`.
- [ ] **AUD-007** (#7) — `app.add_middleware(SlowAPIMiddleware)` and point the limiter at Redis.
- [ ] **AUD-016** (#18) — `app.add_middleware(SecurityHeadersMiddleware)`.
- [ ] **AUD-017** (#19) — let `AppException` through `_managed_session` without `logger.exception`.

---

## AUD-001 — Scope the conversation message routes to the caller's organization {#aud-001}

**Severity:** Critical · **Dimension:** Tenant isolation · **Effort:** S · **Issue:** #1

**Where:** `backend/app/api/routes/v1/conversations.py:169-189` and `:192-204`; `backend/app/services/conversation.py:297-320` (`_resolve`), `:332-346` (`list_messages`), `:373-388` (`add_message`)

**What's wrong.** `ConversationService._resolve` takes an unscoped branch when `organization_id is None` — a bare `get_conversation_by_id` with no tenant and no owner predicate. Its own docstring says so and warns about it: *"Grep for this default when auditing cross-tenant reads; anything serving an ordinary member must pass the tenant."* Two routes serving ordinary members do not pass the tenant.

**How it fails.** The GET route passes `user_id=current_user.id` — which is used only to enrich messages with ratings at `conversation.py:355`, never for authorization — and no `organization_id`. So:

```
GET /api/v1/conversations/<uuid of a conversation in another org>/messages
→ 200, full transcript including tool calls and their arguments
```

The POST route passes neither, so any authenticated user can append a message — including one with `role: "assistant"` — to any conversation in the deployment. The injected turn is persisted and rendered to its owner. Precondition in both cases is knowing the UUID; AUD-005 supplies one way to obtain that reach, and conversation ids appear in shared links and support tickets.

```python
# conversations.py:181 — current
items, total = await conversation_service.list_messages(
    conversation_id, skip=skip, limit=limit, include_tool_calls=True, user_id=current_user.id,
)
# conversations.py:204 — current
return await conversation_service.add_message(conversation_id, data)
```

The GET route's own docstring says "always scoped to the caller". It is not.

**Fix.**

```python
async def list_messages(conversation_id: UUID, conversation_service: ConversationSvc,
                        current_user: CurrentUser, active_org: ActiveOrg, ...) -> Any:
    items, total = await conversation_service.list_messages(
        conversation_id, skip=skip, limit=limit, include_tool_calls=True,
        organization_id=active_org.id, user_id=current_user.id,
    )
```

Same for `add_message`. Then make `organization_id` a required keyword on both service methods, with the two legitimate unscoped callers (the admin transcript view and the WebSocket session) passing an explicit sentinel — so the omission cannot recur silently.

**Why no test caught it.** `tests/api/test_conversation_scoping.py` asserts `service.list_messages.await_args.kwargs["user_id"] == caller` against a `MagicMock` service. It passes while the real service ignores that argument for authorization — the "no test for a mock" case `.claude/rules/testing.md` names.

**Done when:**
- [ ] Both routes pass the active organization.
- [ ] `organization_id` is required on `list_messages` and `add_message`.
- [ ] Regression test: two orgs, caller in A, conversation in B → `GET .../messages` is 404 and `POST .../messages` is 404 with no `Message` row created. Asserted against a real `ConversationService`, not a mock.

---

## AUD-002 — Give both channel supervisors an unconditional backoff {#aud-002}

**Severity:** Critical · **Dimension:** Async · **Effort:** S · **Issue:** #2

**Where:** `backend/app/services/channels/slack.py:93-124`, `backend/app/services/channels/mattermost.py:125-158`; reached from `backend/app/main.py:51-70`

**What's wrong.** Both supervisors are `while True: await self._run_x(...)` with `asyncio.sleep(5)` only inside the `except Exception` branch. Both inner coroutines have early-return paths that never await:

```python
# slack.py:93 — current
while True:
    try:
        await self._run_socket_mode(bot_id, bot_token)   # can return without ever suspending
    except asyncio.CancelledError:
        break
    except Exception:
        logger.exception(...)
        await asyncio.sleep(5)                            # the only sleep

# slack.py:117 — the early return
app_token = self._app_tokens.get(bot_id)
if not app_token:
    logger.warning("Slack bot %s has no app-level token - Socket Mode not started. ...", bot_id)
    return
```

**How it fails.** Awaiting a coroutine that never suspends does not yield to the event loop. The supervisor spins at 100% CPU and **no other task on the process ever runs again** — not a request, not a health check, not the WebSocket streams. The API is up and answers nothing.

Both trigger states are ordinary rows, not corruption:

- Slack: `slack_app_token_encrypted IS NULL`. The warning text literally instructs the operator to go add it, so it is an expected state, and `main.py:64-68` only calls `remember_app_token` when the unseal returns one.
- Mattermost: `api_base_url IS NULL`, which is `nullable=True` and — per AUD-022 — *cannot currently be set at all*.

`get_active_polling_bots` filters on `is_active` and `webhook_mode` only. Create a Slack bot with polling enabled, don't paste the `xapp-` token, restart the API: the process comes up, lifespan yields, and the deployment goes dark with one WARNING line as the only clue.

**Fix.**

```python
while True:
    try:
        await self._run_socket_mode(bot_id, bot_token)
    except asyncio.CancelledError:
        break
    except _NotConfigured:      # nothing a retry can fix
        return
    except Exception:
        logger.exception(...)
    await asyncio.sleep(5)      # unconditional, and cancellable
```

Better still, raise from the inner coroutine's configuration branches so "could not start" is distinguishable from "the session ended".

**Done when:**
- [ ] Both supervisors sleep on every iteration.
- [ ] A configuration failure stops retrying rather than looping.
- [ ] Regression test, both adapters: with the inner call returning immediately, a concurrent `asyncio.sleep(0)` still completes. This is exactly the test the 100% gate would have forced if these modules were in the platform layer — see the note under AUD-026.

---

## AUD-003 — Commit the run row so a failed run is still accounted {#aud-003}

**Severity:** High · **Dimension:** Governance · **Effort:** S · **Issue:** #3

**Where:** `backend/app/services/agent_runner.py:754-765`; contrast `backend/app/services/agent_chat.py:286-299`; mechanism at `backend/app/db/session.py:34-44`

**What's wrong.** `AgentRunnerService._run` records the run in a `finally` and then re-raises. `finish` flushes; nothing commits; `_managed_session` rolls back on the way out. The run row created at `agent_runner.py:340` goes with it.

`agent_chat.py` — the one surface that gets this right — documents the exact defect:

> Committed here rather than left to the session context: that exit rolls back on any exception, and cancellation never reaches it at all, since `CancelledError` is not an `Exception`. A run that failed, was stopped or ran out of budget still spent money, and a run missing from history is a run nobody is accountable for.

`grep '\.commit()' app/` returns exactly one non-infrastructure caller: that line.

**How it fails.** POST `/api/v1/agents/{id}/run` against an agent whose provider 500s after three model steps. `finish()` flushes `cost_usd = 0.42`; the `RuntimeError` propagates; the session rolls back. There is no run in history, no cost, and `sum_cost_since` — the budget baseline for the *next* run — is unchanged. An agent failing in a retry loop spends unbounded money that no budget can see. This affects the public API, all three channel surfaces (`mentions.py:198,257`), the embed widget (`embed_session.py:160`) and `resume`; web chat alone is safe.

`asyncio.CancelledError` is worse: it is not an `Exception`, so `_run` records `FAILED` rather than `CANCELLED` and then unwinds past the session context entirely.

Verified against the running Postgres — a flushed-but-uncommitted row is gone after the body raises:

```
ROW AFTER ROLLBACK: None
```

`docs/governance.md:41-46` states the opposite: *"Accounting happens in a `finally` block on every surface, and the commit is explicit rather than left to the session context."*

**A second, sharper consequence.** A run parks on an approved `send_invoice`, someone approves, `resume` replays the call — the invoice is sent — and the *next* model request times out. The rollback discards `mark_running` too, so the run is `awaiting_approval` again with its original `paused_state` and an approval still marked `approved`. A second resume produces identical `DeferredToolResults` and **sends the invoice again**. `claim_parked_run`'s `FOR UPDATE` protects against simultaneous resumes; it protects against nothing here, because the state transition it guards is thrown away.

**Fix.** Move the commit into `AgentRunnerService.finish` (or `_run`'s `finally`, after `finish`), give `_run` the `except asyncio.CancelledError: status = RunStatus.CANCELLED; raise` clause `agent_chat.py:268-272` already has, and delete the duplicate from `agent_chat.py`. Consider committing `mark_running` in its own transaction so the "out of the queue before anything is replayed" comment at `agent_runner.py:572-575` becomes true across a crash.

**Done when:**
- [ ] Every surface's failed run appears in history with its cost.
- [ ] A cancelled run records `CANCELLED`.
- [ ] Regression test (integration, real Postgres): run an agent whose model raises, then in a **fresh session** assert the `agent_runs` row exists with `status='failed'` and the recorded cost. The existing `tests/test_agent_runner.py:513` asserts `finish_run` was *called* on an `AsyncMock` and cannot observe the rollback.
- [ ] Regression test: park → approve → resume with a crash after the deferred call → the run is `failed`, and a second resume raises.

---

## AUD-004 — Refuse a Telegram webhook that carries no secret {#aud-004}

**Severity:** High · **Dimension:** Security · **Effort:** S · **Issue:** #4

**Where:** `backend/app/api/routes/v1/telegram_webhook.py:40-41`; contrast `backend/app/api/routes/v1/mattermost_webhook.py:61-67`; secret minted at `backend/app/services/channel_bot.py:110`

**What's wrong.**

```python
# telegram_webhook.py:40 — current
if bot.webhook_secret and not adapter.verify_webhook_signature(headers, bot.webhook_secret):
    raise HTTPException(status_code=403, detail="Invalid webhook signature")
```

When `webhook_secret` is `None` the whole condition is `False` and the payload is processed as a genuine Telegram update. And `webhook_secret` is minted in exactly one place — at create time, only when `webhook_mode=True`, which is not the schema default — and `ChannelBotService.update` accepts `webhook_mode` while never minting one. So any bot created in polling mode, or switched to webhook mode later, has a `NULL` secret and an unauthenticated endpoint.

Mattermost, five files away, gets it right and says why: *"A webhook with no secret is one anybody can post to, so it is refused rather than trusted."* Slack 500s rather than skipping. Telegram is the odd one out, and nothing in `docs/channels.md` presents that as deliberate.

**How it fails.** `channels/router.py:318-342` resolves the sender's identity from `incoming.platform_user_id`, which comes straight out of the unauthenticated body. So a forged update naming a linked user's Telegram id runs an agent **as that user**, against their organization's budget and grants, with the answer delivered to a `chat.id` the attacker also chose. `_check_access`'s `whitelist` mode is satisfied the same way — by putting a whitelisted id in the body.

`grep -rn webhook_secret tests/` returns nothing. No test proves any of these refusals.

**Fix.**

```python
if not bot.webhook_secret or not adapter.verify_webhook_signature(headers, bot.webhook_secret):
    raise HTTPException(status_code=403, detail="Invalid webhook signature")
```

Mint `webhook_secret` whenever a bot enters webhook mode — on create *and* on update — and backfill existing webhook-mode rows.

**Done when:**
- [ ] A bot with no secret is refused, not trusted.
- [ ] Flipping `webhook_mode` on mints a secret.
- [ ] Regression test: an active polling bot, a well-formed update with no `X-Telegram-Bot-Api-Secret-Token` → 403, and `process_channel_event` never scheduled. Mirror it for a wrong token.

---

## AUD-005 — Pass the organization to the two conversation calls in `agent.py` {#aud-005}

**Severity:** High · **Dimension:** Correctness · **Effort:** S · **Issue:** #5

**Where:** `backend/app/services/agent.py:132-134`, `:141-143`, `:164-167`

**What's wrong.** Both calls omit `organization_id`, which is a **required keyword-only** parameter on `ConversationService.get_conversation` and `update_conversation`. Python raises `TypeError` before any check runs, and the broad `except Exception as e: logger.warning("Failed to persist conversation: %s", e)` at line 166 swallows it.

Proven by binding the real signatures:

```
get_conversation: (self, conversation_id, *, organization_id, include_messages=False, user_id=None)
CALLING AS agent.py DOES -> TypeError missing a required keyword-only argument: 'organization_id'
update_conversation: (self, conversation_id, data, *, organization_id, user_id=None)
CALLING AS agent.py DOES -> TypeError missing a required keyword-only argument: 'organization_id'
```

**How it fails.** Three consequences, in order of severity:

1. The `AuthorizationError` at `agent.py:135` — the entire cross-organization guard for a caller-supplied `conversation_id` — is **unreachable dead code**.
2. `current_conversation_id` is set to the caller-supplied value at line 131, *before* the throw, and is returned. `persist_assistant_turn` then writes the model's answer into that conversation through the unscoped `add_message` of AUD-001.
3. Non-security, and the one a user would notice: because the throw happens before `add_message` at line 157, **every user message on a resumed conversation is silently lost.** The frontend sends `conversation_id: conversationId || null` on every frame (`frontend/src/hooks/use-chat.ts:411`), so this is the normal path from the second message onward.

**Fix.** Pass `organization_id=organization_id` to both calls. Then narrow the `except Exception` — swallowing everything is what let a signature error masquerade as a transient persistence failure. At minimum re-raise `TypeError`.

**Done when:**
- [ ] Both calls carry the organization.
- [ ] The `except` no longer swallows programming errors.
- [ ] Regression test: `test_a_resumed_conversation_persists_the_user_message`, which fails today. Build the conversation service as `create_autospec(ConversationService)` rather than a bare `MagicMock` — `tests/test_agent_org_scope.py:124-130` uses the latter, which accepts any signature, and that is why the suite is green.

---

## AUD-006 — Access-check `spec.skill_ids` at publish, like every other reference {#aud-006}

**Severity:** High · **Dimension:** Authorization · **Effort:** S · **Issue:** #6

**Where:** `backend/app/services/agent_registry.py:330-420` (`validate_spec`); `backend/app/services/skills.py:154-168`; `backend/app/agents/capabilities/skills/_capability.py:25-40`

**What's wrong.** `validate_spec` checks every reference in a spec against the publisher's per-row access — collections via `resolve_access(..., COLLECTIONS_VIEW, COLLECTION)`, MCP servers via `get_org_scoped_by_id`, secrets via `resolve_access(..., SECRETS_VIEW, SECRET)`, the model profile via its org-scoped repo. `skill_ids` is checked nowhere: `rg -in skill app/services/agent_registry.py` returns nothing.

At run time `SkillService.resolve_for_agent` fetches with `skill_repo.get_many(..., organization_id=ctx.organization_id)` — organization only, no owner, no visibility, no grant. That shape is fine for collections and secrets *because they are gated at publish*. Skills are gated at neither.

**How it fails.** A Member holds `AGENTS_EDIT: own` and `SKILLS_VIEW: shared`. They create their own agent, put a colleague's **private** skill id in `skill_ids`, publish (accepted), and run it. `load_skill` and `read_skill_resource` hand the model the skill's full body and every attached resource file.

`docs/skills.md:117-120` states that skills are *"governed like agents and collections: visibility plus per-row grants."*

**Fix.** Add the loop, mirroring the collections one verbatim:

```python
for skill_id in spec.skill_ids:
    skill = await skill_repo.get(self.db, skill_id, organization_id=ctx.organization_id)
    reachable = skill is not None and await resolve_access(
        self.db, ctx, skill, Perm.SKILLS_VIEW, resource_type=SKILL
    )
    if not reachable:
        problems.append(f"Skill not found: {skill_id}")
```

Keep the "not found covers both" wording, for the same reason the collections branch gives: a refusal that reads differently maps the organization's private skills one guess at a time.

**Done when:**
- [ ] Publishing an agent bound to an unreachable skill is refused.
- [ ] Regression test: a private skill owned by another member → `BadRequestError` with `Skill not found` in `problems`. Plus the mirror — an explicit `read` grant publishes fine.

---

## AUD-007 — Actually apply the rate limiter {#aud-007}

**Severity:** High · **Dimension:** Security · **Effort:** S (wiring) / M (per-route policy) · **Issue:** #7

**Where:** `backend/app/main.py:249-254`, `backend/app/core/rate_limit.py:32-50`

**What's wrong.** `app.state.limiter` is set and a `RateLimitExceeded` handler registered, but **`SlowAPIMiddleware` is never added** — `main.py` adds only `RequestIDMiddleware`, `CORSMiddleware` and `SessionMiddleware`. In slowapi, `default_limits` are evaluated exclusively inside the middleware; the alternative path, `@limiter.limit(...)` on a handler, has zero call sites. `rate_limit_low` / `_medium` / `_high` are defined and imported nowhere.

Confirmed: `limiter.limit` has three occurrences, all inside `rate_limit.py` itself; `add_middleware` has three, all in `main.py`.

**How it fails.** `RATE_LIMIT_REQUESTS=100` enforces nothing. `POST /api/v1/auth/login`, register, password reset, `GET /api/v1/embed/{key}/config`, `widget.js` and all three webhook receivers are unmetered — brute-force and cost-amplification are free. `docs/governance.md:156` states *"There is deployment-level rate limiting on the API"*; the bundled `nginx/nginx.conf` has no `limit_req` either, so the claim is false at both layers.

The only test is `tests/test_core.py:104` `test_limiter_exists`, which asserts `limiter is not None` — a test that passes whether or not the limiter does anything, which is what happened.

**Fix.** `app.add_middleware(SlowAPIMiddleware)` in `create_app`, and `Limiter(..., storage_uri=settings.REDIS_URL)` — the default `memory://` is per-process, so with N uvicorn workers the effective limit is N× the configured one and resets on every deploy. Then run uvicorn with `--proxy-headers --forwarded-allow-ips=<nginx>`: `key_func=get_remote_address` reads `request.client.host`, so behind the bundled nginx every request currently shares one bucket. Finally, decide which routes need the tighter tiers.

**Done when:**
- [ ] The limiter is on the middleware stack and backed by Redis.
- [ ] `/auth/*` and `/embed/*` carry explicit tighter limits.
- [ ] Regression test: the N+1st request in a window returns 429. Delete `test_limiter_exists`.

---

## AUD-008 — Make the vault master key explicit and rotatable {#aud-008}

**Severity:** High · **Dimension:** Secrets · **Effort:** M · **Issue:** #8

**Where:** `backend/app/core/vault.py:102-121`, `:182-209` (`rewrap`); `backend/app/core/config.py:75-89`, `:101`

Two failures in one mechanism.

**8a. Outside production, the master key is a string published in this repository.**

```python
# vault.py:102 — current
def _master_key() -> str:
    """...production deployments set `VAULT_MASTER_KEY` explicitly, and the config
    validator refuses the default `SECRET_KEY` outside development."""
    configured = getattr(settings, "VAULT_MASTER_KEY", "") or ""
    return configured or settings.SECRET_KEY
```

The validator does not do that. `config.py:84` refuses the default only when `env == "production"`:

```python
if v == "change-me-in-production-use-openssl-rand-hex-32" and env == "production":
```

`ENVIRONMENT` is a `Literal["development", "local", "staging", "production"]`, and `staging` is a first-class deployment here — `main.py:147` lists it in `SHOW_DOCS_ENVIRONMENTS`. So a staging deployment boots happily with `VAULT_MASTER_KEY` unset and `SECRET_KEY` at its default, and **every credential in its vault is sealed under a key printed in `config.py`**. Staging environments routinely hold real provider keys and are often restored from production snapshots. `VAULT_MASTER_KEY` has no validator of its own, unlike `SECRET_KEY` and `API_KEY`; `doctor` catches an unset one but is an opt-in command, not a boot gate.

The `getattr(settings, "VAULT_MASTER_KEY", "")` is also a typing escape on an attribute that certainly exists — it would silently swallow a rename.

**8b. Following the documented rotation procedure destroys every credential.**

`_wrapping_key` derives from `_master_key()` — the single *current* setting — and mixes only `v{key_version}` into the material. So `key_version` records nothing about *which* master key sealed an envelope, contradicting `vault.py:16-18` (*"`key_version` records which master key sealed a given envelope"*).

An operator running on the `SECRET_KEY` fallback reads `docs/secrets.md` ("a production deployment should set it explicitly") and sets `VAULT_MASTER_KEY`. Every envelope in the deployment now fails at `vault.py:174` with `BadRequestError("Failed to decrypt secret - wrong master key or owner")`. `rewrap` cannot repair it — line 204 derives the *from*-version key from the same current master key, so it raises on every row. There is no setting, parameter or code path that supplies a previous master key. `rewrap` has zero production callers (only `tests/test_vault.py`), and there is no `agenticos cmd` for rotation, so the "staged operation" the docs describe has no implementation. `mcp_connection.py:137-139` swallows the failure and marks connections dead, so the damage is partly silent.

`tests/test_vault.py:126-187` passes because the master key never changes across a `rewrap` — it tests version-tag bumping, not rotation.

**Fix.**

```python
# config.py
VAULT_MASTER_KEYS: dict[int, str] = {}    # or VAULT_MASTER_KEY + VAULT_MASTER_KEY_PREVIOUS

# vault.py
def _wrapping_key(scope: VaultScope, key_version: int) -> Fernet:
    master = settings.VAULT_MASTER_KEYS.get(key_version)
    if master is None:
        raise ConfigurationError(f"No master key configured for version {key_version}")
    ...
```

Add a `field_validator` on `VAULT_MASTER_KEY` refusing an empty value outside `local`/`development`, and add `agenticos cmd vault-rotate` walking every sealed column (`organization_secrets`, `channel_bots` ×3, `mcp_connections` ×3, `agent_embeds`). While there, replace `sha256(master|scope|v)` with HKDF-SHA256 using scope+version as `info` — a single SHA-256 over a possibly-passphrase-derived value is not a KDF.

**Related, and it fires the moment 8b is fixed:** `channel_bot.py:212-214` resets `secret_key_version` to `1` when the bot token is rotated, because `seal_bot_token` takes no `key_version` — while the two Slack fields two lines above correctly pass `bot.secret_key_version`. A bot at version 2 whose token is edited ends up with a v1 token envelope and v2 Slack envelopes, and `unseal_slack_signing_secret` then fails. Harmless today because no path produces a version ≠ 1; hard to diagnose the day one does.

**Done when:**
- [ ] The master key resolves per version, and an unknown version raises.
- [ ] `VAULT_MASTER_KEY` is validated at startup outside local/dev.
- [ ] `seal_bot_token` takes a `key_version` and `update` stops rewriting the column.
- [ ] Regression test: seal under key A, retain A as version 1 and make B current, `rewrap(from_version=1, to_version=2)`, assert the plaintext round-trips. Plus `test_rotation_refuses_a_version_with_no_configured_key`.

---

## AUD-009 — Reconcile the delete cascades with the CHECK constraints {#aud-009}

**Severity:** High · **Dimension:** Data · **Effort:** M · **Issue:** #9

**Where:** `backend/app/db/models/organization.py:48-53`, `organization_secret.py:73-78` vs `:105-108`, `knowledge_base.py:72-78` vs `:83-86`

Three delete paths that 500. Verified directly against the live baseline schema:

```
knowledge_bases_organization_id_fkey  | FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE SET NULL
knowledge_bases_ck_..._org_scope_has_org_check | CHECK (scope <> 'org' OR organization_id IS NOT NULL)

organization_secrets_owner_user_id_fkey | FOREIGN KEY (owner_user_id) REFERENCES users(id) ON DELETE SET NULL
organization_secrets_ck_secret_private_needs_owner_check | CHECK (visibility <> 'private' OR owner_user_id IS NOT NULL)
```

In both pairs, the cascade performs precisely the `UPDATE` the check forbids.

**9a. `DELETE /api/v1/users/{id}` fails for every normally-registered user.** `organizations.created_by_user_id` is `ON DELETE RESTRICT`, and `UserService.create` calls `create_personal_org` for every signup — so every user creates at least one organization row. `db.delete(user)` raises `ForeignKeyViolationError`; there is no `IntegrityError` handler in `app/api/exception_handlers.py`, so it becomes a 500. The app-admin delete-user endpoint is non-functional in production, and `delete_non_admins` (used by `seed --clear`) hits the same wall.

Note `tests/integration/test_schema_guarantees.py:163-166` has a `_leaver` fixture whose docstring says it builds *"a member who can actually be deleted — not the organization's creator"*. The suite routes around this rather than covering it.

**9b. Deleting a user who owns a private vault secret** violates the private-needs-owner check. Independent of 9a and survives any fix to it. The column comment says a personal key whose owner leaves *"becomes the organization's problem to clean up"* — the check makes that state unreachable.

**9c. Deleting an org holding an org-scoped collection** violates the org-scope check. `knowledge_base.py:98` sets `scope = ORG` automatically whenever an `organization_id` is passed, so this is the default outcome, not an edge case.

**Fix.** Pick one story per pair and make both halves agree:

- 9a: `UserService.delete` reassigns `created_by_user_id` to another Owner, or deletes/transfers the personal org, before deleting the row.
- 9b: promote the row on owner deletion (`visibility` → `'org'`) in an explicit service step, or drop the check and let a nulled owner mean org-owned.
- 9c: make the FK `ON DELETE CASCADE` — an org-scoped collection has no meaning without its org.

**Also found while verifying, and not fixed by the above:** nothing in `OrganizationService.delete` drops the `rag_<collection>` vector tables. Even with 9c fixed, a deleted tenant's embeddings stay on disk.

**Done when:**
- [ ] All three deletes succeed.
- [ ] Integration tests: a normally-registered user can be deleted; deleting a member who holds a private secret leaves the secret reachable; deleting an org removes its org-scoped collections *and* their vector tables. There is already a sibling test at `test_schema_guarantees.py:108` to model these on.

---

## AUD-010 — Give account linking something that mints a code {#aud-010}

**Severity:** High · **Dimension:** Correctness · **Effort:** M · **Issue:** #10

**Where:** `backend/app/services/channels/router.py:266-302`, `backend/app/repositories/channel_identity.py:32-40`, `:82-95`; refusal at `backend/app/services/channels/mentions.py:277-291`

**What's wrong.** `ChannelIdentity.link_code` is **never written with a value by any code in the repository.** Searching `app/`, `tests/`, `frontend/src` and `docs/` for `link_code` / `linkCode` / `link_to_user` finds only reads (`get_by_link_code`) and clears (`link_code = None`). No endpoint, service, CLI command or UI mints one, and `link_to_user()` has no callers at all.

**How it fails.** `get_by_link_code` filters on `link_code == arg`, which never matches a NULL column, so `/link <code>` always answers *"Invalid or expired link code. Please generate a new one from the web app"* — from a web app that has no such control. Every `ChannelIdentity` therefore keeps `user_id = None`, and `ChannelAgentRouter._context` refuses on exactly that:

```python
# mentions.py:278 — current
if user_id is None:
    raise AuthorizationError(message=_LINK_FIRST, details={"agent": slug})
```

Both `answer` and `answer_default` go through it. So **every** channel message, on any platform, mention or not, is answered with "Link your account before talking to an agent" — permanently. `docs/channels.md:182-184` describes the flow as working.

`tests/test_channel_mentions.py` covers the *refusal* of an unlinked sender thoroughly, and the success path only by injecting a `user_id` directly. That asymmetry is why CI is green.

**Fix.** Add `POST /api/v1/me/channel-link`: create or update the caller's `ChannelIdentity` with a short random `link_code` and an expiry, return it, surface it in the UI. Use the existing `link_to_user` on redemption instead of the two hand-rolled `update` calls at `router.py:281-297`.

**Done when:**
- [ ] A signed-in user can obtain a link code.
- [ ] End-to-end test: mint a code → `/link <code>` → the next mention runs as that user.

---

## AUD-011 — Drain background work before tearing the process down {#aud-011}

**Severity:** High · **Dimension:** Resources · **Effort:** S · **Issue:** #11

**Where:** `backend/app/core/background.py:66-85` (zero non-test callers), `backend/app/main.py:131-144`

**What's wrong.** `drain()`'s own docstring says: *"Called from the application lifespan. Without it, shutting down mid-flight cancels ingestion and sync work that was nearly done, which shows up later as a document stuck in `processing` forever."* It is not called from the lifespan — `rg drain app/ tests/` returns only `tests/test_background.py` and the definition.

And the shutdown order is close to inverted:

```python
# main.py:131 — current
yield state
if "vector_store" in state:
    await state["vector_store"].engine.dispose()   # engine disposed FIRST
for _bid in list(_telegram_adapter._polling_tasks.keys()):
    await _telegram_adapter.stop_polling(_bid)     # intake stopped SECOND
...
await close_db()
```

**How it fails.** Upload a document, `spawn(ingest_document_flow(...))`, deploy. The task is a plain `asyncio.Task` in the API process; uvicorn drains HTTP, runs lifespan shutdown, tears the loop down. `_run_ingestion` never reaches `complete_ingestion`, its `except` never fires, and the `rag_documents` row stays `processing` forever with nothing in the logs — exactly the symptom the docstring predicts. Meanwhile a Telegram message arriving in the window between the engine dispose and the poller stop runs a knowledge search against a disposed engine.

Compounding it, the three webhook routes bypass `spawn` entirely (`slack_webhook.py:71`, `telegram_webhook.py:47`, `mattermost_webhook.py:75`) with bare `asyncio.create_task` into private module sets that `drain()` cannot see — so a Slack message being answered during a deploy is dropped, and if `close_db()` wins the race it dies on a disposed engine.

**Fix.** Stop intake → drain → close resources:

```python
yield state
for _bid in list(_telegram_adapter._polling_tasks): await _telegram_adapter.stop_polling(_bid)
for _sbid in list(_slack_adapter._socket_tasks):     await _slack_adapter.stop_polling(_sbid)
for _mbid in list(_mattermost_adapter._socket_tasks): await _mattermost_adapter.stop_polling(_mbid)
await background.drain()
if "vector_store" in state:
    with suppress(Exception):
        await state["vector_store"].engine.dispose()
if "redis" in state:
    await state["redis"].close()
await close_db()
```

and replace the three `create_task` calls with `spawn(...)`, deleting the local sets.

**Done when:**
- [ ] The lifespan drains, in the right order.
- [ ] The webhook routes use `spawn`.
- [ ] Regression test with `LifespanManager`: a slow task spawned before shutdown completes rather than being cancelled, and `close_db` runs last.

---

## AUD-012 — Stop holding a pooled connection across slow work {#aud-012}

**Severity:** High · **Dimension:** Resources · **Effort:** M · **Issue:** #12

Three separate paths, one consequence: `DB_POOL_SIZE=5` + `DB_MAX_OVERFLOW=10` means fifteen concurrent anything exhausts the pool, and the sixteenth request of *any* kind — a health check, a login — blocks for `DB_POOL_TIMEOUT=30`s and then raises.

**12a. The run's transaction spans the entire LLM call.** `agent_runner.py:340` inserts and flushes the run row; the commit only happens after `agent.iter(...)` completes (`agent_chat.py:299`). For a multi-turn tool-calling run — seconds to minutes — one connection sits `idle in transaction`, holding an uncommitted row lock and blocking `VACUUM` from reclaiming across the window. The fix for AUD-003 makes the commit correct but does not shorten this. Split the boundary: open the run row in its own short session and commit it, run the model with no session held, re-open in `finish`. `PreparedRun` would carry `run_id` rather than a live `AgentRun`.

**12b. The embed widget pins a connection per open browser tab.** `embed.py:113` wraps `while True: await websocket.receive_json()` in `async with get_db_context()`. One connection per visitor, from handshake to close, including all the idle time between questions. Fifteen simultaneous visitors on a marketing page take the whole API down, not just the widget. `AgentSession` (`agent_session.py:202`) does this correctly — a session per turn. Move `get_db_context()` inside the frame loop and give `EmbedSession` a factory rather than a session.

**12c. `PgVectorStore` builds a private engine per instance and ingestion never disposes it.** `vectorstore.py:211-216` calls `create_async_engine` in `__init__`, giving each instance its own `QueuePool` (5 + 10). `rag_tasks.py:53` constructs one per document. `aclose()` exists, is documented (*"Call `await self.aclose()` on shutdown"*), and `main.py:134` is its only caller — so a worker that ingests a few dozen documents leaks a few dozen pools and walks into Postgres `max_connections`. SQLAlchemy async engines do not close asyncpg connections on GC; they warn. Have `PgVectorStore` accept an engine rather than create one.

**Done when:**
- [ ] The run row is committed before the model call and visible from another session mid-run.
- [ ] `EmbedSession` takes a factory; no connection is held between frames.
- [ ] Ingesting two documents creates one engine, not two.

---

## AUD-013 — Exclude a resumed run's own spend from its baseline {#aud-013}

**Severity:** Medium · **Dimension:** Governance · **Effort:** S · **Issue:** #15

**Where:** `agent_runner.py:598` (`ledger.entries.append(_spend_already_booked(run))`), `:361-365`; `repositories/agent_run.py:137-158`; `capabilities/budget/_capability.py:304-309`

An agent with `budget.monthly_usd = 10` spends $6 and parks on an approval; `finish_run` commits `cost_usd = 6.00`. On resume the baseline query sums that same row → $6, and `_spend_already_booked` seeds the ledger with another $6. The first model request evaluates `6 + 6 = 12 ≥ 10` and raises `BudgetExceeded`. **The resumed run is refused at 60% of its budget**, and the alert tells the owner they hit a cap they have $4 under. The org-wide cap double-counts identically.

The seeded entry is right for *accounting* — `finish_run` overwrites rather than adds — and wrong for *enforcement*, because the baseline already contains it. Give `sum_cost_since` / `organization_monthly_spend` an `exclude_run_id` and pass `run.id` from the resume path's two lookup closures.

**Test:** `test_a_resumed_runs_own_prior_spend_is_not_counted_twice` — parked run at `cost_usd=6`, cap `10`, assert the guard sees `6`.

---

## AUD-014 — Meter the web chat surface {#aud-014}

**Severity:** Medium · **Dimension:** Governance · **Effort:** S · **Issue:** #16

**Where:** `agent_chat.py:247`; contrast `agent_runner.py:722-732`

`agent_chat.py:247` opens `async with prepared.built.agent.iter(...)` with **no `metered_by(...)`**. So when a knowledge-enabled agent embeds a query, `record_ambient_usage` finds no active ledger and drops the spend. The run's `cost_usd` under-reports, `cost_is_partial` is *not* set (so the UI shows no `+`), and the org's monthly total never sees it — nor does `ingestion_spend`, which only the worker writes.

`embeddings.py:83-85` says this "used to be dropped on the floor, which made every knowledge search invisible to the monthly budgets". It still is, on the product's primary surface. `rg metered_by app` finds three worker call sites and `agent_runner._run`; `agent_chat.py` is absent.

Wrap the block in `with metered_by(prepared.built.ledger):`. Better: move the meter into `prepare`/`PreparedRun` so a surface cannot forget it — the same reasoning that put budget resolution in the runner.

---

## AUD-015 — Four check-then-act races {#aud-015}

**Severity:** Medium · **Dimension:** Concurrency · **Effort:** M · **Issue:** #17

The codebase already has the right pattern in `claim_parked_run` (`repositories/agent_run.py:91-105`, `.with_for_update()`, with a comment explaining why). Four siblings do not use it.

**15a. `ApprovalService.decide`** (`approvals.py:86-107`, `agent_run.py:263-272`). Two approvers, one rejects and one approves within the same read-committed window; both read `status == 'pending'`, both write. `record_audit` emits two contradictory entries — `approval.rejected` and `approval.approved` — for one decision. The service docstring says deciding twice *"would make the audit trail ambiguous about who authorised the action"*; that is the state produced. Add a `with_for_update` variant of `get_approval`.

**15b. Concurrent runs share one budget baseline** (`budget/_capability.py:289-309`). An org at $99 of a $100 cap; fifty runs arrive together, each opens a row with `cost_usd = 0`, each reads a baseline of $99, all fifty proceed. The cap overshoots by up to N × (cost of one run), while `docs/governance.md:36-39` presents it as a hard stop. Either reserve before the request, or write the ledger total onto the run row periodically so in-flight spend is visible — or state the limit on the governance page. This is a known design class, hence Medium.

**15c. Channel identity get-or-create** (`channels/router.py:318-369`). Both resolvers are check-then-act with no `IntegrityError` handling, against tables that carry unique constraints. The in-process lock is keyed `(bot_id, platform_chat_id)` but the identity is keyed `(platform, platform_user_id)` — so **one Slack user messaging two channels at once takes two different locks**, both create, and the second flush violates `uq_channel_identity_platform_user`. The session rolls back, `process_channel_event` logs, and the user gets **no reply at all**. The lock is per-process anyway, so with two workers the session race and the rate-limit bucket are both wrong. Two adjacent leaks: `_chat_locks` and `_rate_buckets` are module dicts that are never evicted, and Slack folds `thread_ts` into `platform_chat_id`, so a busy workspace accrues one permanent `asyncio.Lock` per thread.

**15d. Invite `used_count` and `seats_limit`** (`invitation.py:201`, `:218-239`). `used_count` is read in Python and incremented with `+= 1`; two accepts of a `max_uses=1` link both pass and both insert a member. Same shape for the seat cap. A link pasted into a team channel is *designed* to be clicked simultaneously. Use `UPDATE ... SET used_count = used_count + 1 WHERE used_count < max_uses` and check `rowcount`.

**Also:** `repositories/agent.py:131-136` computes the next version as `MAX(version) + 1` with no lock, so a double-clicked Publish 500s on `uq_agent_version_number`. No corruption — the constraint does its job — but the user sees a server error where a retry would do. (Low.)

---

## AUD-016 — Register `SecurityHeadersMiddleware` {#aud-016}

**Severity:** Medium · **Dimension:** Security · **Effort:** S · **Issue:** #18

**Where:** `backend/app/core/middleware.py:30-99`, `backend/app/main.py:237`

`main.py` imports only `RequestIDMiddleware`. No API response carries `Content-Security-Policy`, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` or `Permissions-Policy`.

The sharpest evidence it is unintentional: `files.py:69-72` — the one endpoint serving user-uploaded content — reasons about a default that is not there: *"Default `X-Frame-Options: DENY` from SecurityHeadersMiddleware would break that, so opt this endpoint down to SAMEORIGIN."* It believes it is loosening a restriction that was never applied.

Partial mitigation: `nginx/nginx.conf:73-78` sets `X-Frame-Options: SAMEORIGIN`, `nosniff`, `Referrer-Policy` and HSTS. It sets **no CSP**, its `SAMEORIGIN` is weaker than the app's intended `DENY`, and any deployment not fronted by that exact nginx — the self-hosted case this product is built for — gets nothing.

`app.add_middleware(SecurityHeadersMiddleware)` in `create_app()`, then re-verify `files.py`.

---

## AUD-017 — Stop logging expected refusals as application errors {#aud-017}

**Severity:** Medium · **Dimension:** Observability · **Effort:** S · **Issue:** #19

**Where:** `backend/app/db/session.py:38-44`

```python
except Exception:
    logger.exception("DB session error, rolling back")
```

Every exception passing through the session dependency is logged at ERROR with a full traceback — including every domain exception, which are ordinary 4xx outcomes. Verified end to end through the real dependency and the real exception handlers:

```
STATUS: 404
ERRORS: [('app.db.session', 'DB session error, rolling back', True)]   # exc_info=True
```

Every `NotFoundError` (404), every `AuthorizationError` (403), every `AlreadyExistsError` (409) writes a stack trace. On a platform whose stated value is *"mostly in what it refuses"*, the refusals are the loudest errors in the log: any error-rate alert or Logfire error dashboard is dominated by expected outcomes, and a real 500 is buried.

No test catches it because `tests/conftest.py:83` overrides `get_db_session` with a mock — `_managed_session` is not on the tested path at all.

```python
except AppException:
    await session.rollback()      # expected outcome, no traceback
    raise
except Exception:
    logger.exception("DB session error, rolling back")
    ...
```

**Test:** assert a 404 through the real dependency produces no ERROR record, and that an unexpected exception still does.

---

## AUD-018 — Make an audit write failure loud {#aud-018}

**Severity:** Medium · **Dimension:** Governance · **Effort:** S · **Issue:** #20

**Where:** `backend/app/core/audit.py:12-37`

```python
async def record_audit(db, *, actor_user_id: UUID, action: str, ...) -> None:
    """Persist an audit log entry. Failures are logged but do not raise."""
    try:
        ...
        db.add(entry)
        await db.flush()
    except Exception:
        logger.exception("Failed to write audit log for action=%s actor=%s", action, actor_user_id)
```

Three problems. The `db` parameter is **untyped**. The swallow is fail-open on the audit trail, which `docs/governance.md:149` makes load-bearing for the app-admin bypass story — and this is called from the platform-layer services (`organization_secret`, `model_profile`, `agent_embed`, `agent_environment`, `agent_registry`) on ~20 privileged actions.

And the swallow does not achieve what it claims: `flush()` inside the `try` leaves the session needing a rollback, so `_managed_session`'s commit then raises `PendingRollbackError` and the request 500s anyway — with an opaque error that names the session, not the audit. Either outcome is bad, and neither is "the action succeeds quietly".

`app/core/audit.py` is also outside both the coverage gate and the ty overrides, despite every caller being inside them.

Type the parameter, let the exception propagate (or catch narrowly and re-raise as a domain error), and add the module to both lists in `pyproject.toml`.

---

## AUD-019 — Refuse a malformed sealed payload without naming its contents {#aud-019}

**Severity:** Medium · **Dimension:** Secrets · **Effort:** S · **Issue:** #21

**Where:** `backend/app/core/secret_kinds.py:252-270` (line 262)

`unseal_secret`'s docstring promises `BadRequestError` "if the envelope … holds something that is not a secret payload". It does not: `_STORABLE_ADAPTER.validate_json(...)` raises `pydantic_core.ValidationError`, which is not an `AppException`, so it reaches `unhandled_exception_handler` and `logger.exception`. Pydantic embeds the offending input:

```
Input tag 'bogus' found using 'kind' does not match any of the expected tags: …
[type=union_tag_invalid, input_value={'kind': 'bogus', 'api_ke...: 'sk-live-SUPERSECRET'}, ...]
```

The decrypted credential lands in the log line and, under `logfire.instrument_fastapi`, in the exception event on the span — breaking the guarantee `docs/secrets.md` states ("No log line or audit entry contains one"). Reachable from `resolve_for_bindings`, `ModelProfileService` and `_listing_key`. Trigger: any stored payload that no longer validates — a hand-edited row, a rollback to a build whose `SecretKind` enum lacks a kind a newer build wrote, or a future field tightening.

Catch `PydanticValidationError` and re-raise `BadRequestError(message="Stored secret is not a usable payload", details={"recorded": kind.value})` with **`from None`** — `from exc` keeps the plaintext in the traceback.

`tests/api/test_no_secret_escapes.py` sweeps the OpenAPI surface thoroughly and says nothing about log paths.

---

## AUD-020 — Seal `channel_bots.webhook_secret` {#aud-020}

**Severity:** Medium · **Dimension:** Secrets · **Effort:** S · **Issue:** #22

**Where:** `backend/app/db/models/channel_bot.py:44`, `backend/app/services/channel_bot.py:110`

CLAUDE.md: *"Every secret at rest goes through `app/core/vault.py`. **There is no second mechanism.**"* `webhook_secret` is a 32-byte shared secret written straight to a `String(255)` column, in the same row as `token_encrypted`, `slack_signing_secret_encrypted` and `slack_app_token_encrypted` — all sealed. It is the only thing authenticating inbound Telegram and Mattermost webhooks (see AUD-004).

Anyone with read access to the database or a backup — a replica, a support dump, a restored snapshot — recovers it and can drive the agent as any chat user. The bot token immediately beside it is protected against exactly that attacker. `docs/secrets.md` does not mention this column, and `app/core/crypto.py:1-19` carefully documents its one accepted exception (`sync_source`); this is not it.

`webhook_secret_encrypted` sealed via `_seal_at(..., key_version=bot.secret_key_version)`, unsealed in the two webhook routes, one migration re-sealing existing rows. It is never in a response schema, so the change is contained.

---

## AUD-021 — Require a freshness claim on an embed token {#aud-021}

**Severity:** Medium · **Dimension:** Security · **Effort:** S · **Issue:** #23

**Where:** `backend/app/services/agent_embed.py:284-288`

The max-age check is guarded by `if isinstance(issued_at, int | float)`. A token carrying only `sub`, correctly signed, has no `iat` and no `exp` — PyJWT requires neither — so it is accepted forever. A customer's backend minting `{"sub": "user-42"}` produces a token that, scraped once from a browser's network tab, keeps that widget answering on the organization's bill indefinitely. This is the failure the surrounding code twice calls out as the dangerous one (*"a single leaked token becomes the whole widget's budget"*).

`test_a_stale_token_is_refused` passes only because its fixture supplies `iat`. Use `jwt.decode(..., options={"require": ["sub"]})` and refuse when neither `exp` nor a within-window `iat` is present. Say so in `docs/channels.md` — customers minting tokens need to know the claim is mandatory.

---

## AUD-022 — Fix the webhook URL, and let Mattermost bots be configured {#aud-022}

**Severity:** Medium · **Dimension:** Correctness · **Effort:** M · **Issue:** #24

**22a. The registered URL 404s.** `channel_bot.py:270` and `commands/channel.py:112` both build `{base}/api/v1/channels/{platform}/{bot_id}/webhook`. The receivers are mounted at `/telegram`, `/slack`, `/mattermost` (`routes/v1/__init__.py:99-103`); the `/channels` router holds only management endpoints. So `bot.set_webhook()` succeeds, the endpoint returns `{"success": true}`, and Telegram POSTs into a 404 forever. `docs/channels.md:170` documents the *correct* path for Mattermost, which is how the drift is visible. Fix both call sites to `{base}/api/v1/{bot.platform}/{bot_id}/webhook`, and assert the built URL resolves against `app.routes` so they cannot drift again.

**22b. Mattermost bots cannot be configured at all.** `api_base_url` and `webhook_secret` exist on the model and are read by the adapter and the webhook route, but neither is a field on `ChannelBotCreate` or `ChannelBotUpdate`, neither is a parameter of `channel_bot_repo.create`, and neither appears in `frontend/src` or `app/commands`. So the event stream logs *"no server URL; cannot open a stream"* and returns — which is AUD-002's trigger — `send_message` raises, and the outgoing-webhook path can never match because `verify_webhook_signature` compares Mattermost's token against a locally-generated random string the operator cannot overwrite. `docs/channels.md:163-172` instructs the operator to set both fields. Add them to both schemas and to the repo function, validating `api_base_url` through `validate_webhook_url` (see AUD-028).

**Ordering:** do AUD-002 first. Fixing 22b without it turns a dead feature into a live outage.

---

## AUD-023 — Move blocking file work off the event loop {#aud-023}

**Severity:** Medium · **Dimension:** Async · **Effort:** S · **Issue:** #25

**23a.** `file_upload.py:76-117` — `parse_content` is `async def` but every branch is pure blocking CPU. `pymupdf.open(stream=data)` plus `get_text()` over every page of a document up to `MAX_UPLOAD_SIZE` runs without a single suspension point. One user uploading a large PDF freezes every other request and every in-flight agent stream on that worker.

**23b.** `file_storage.py:112-125` — `LocalFileStorage.save` / `load` are declared `async` and call `Path.write_bytes` / `read_bytes` directly, up to 10 MB. `agent_session.py:286-300` loads every attached image sequentially on every turn.

The codebase already knows this pattern — `agents/mcp.py:53` routes DNS through `asyncio.to_thread`, and `rag_document.py:239` switched a file write to anyio with the comment *"writing it synchronously stalls every other request on this worker until it lands."* The sharpest evidence 23b is unintentional: `rag_document.py:218` calls the blocking `storage.save(...)` and then twenty lines later writes the *same bytes* via `anyio.open_file`. One of the two got fixed.

`await asyncio.to_thread(...)` in both. Same shape in `worker/tasks/rag_tasks.py:256,289,302,323` (`rglob` over a tree, `sha256(read_bytes())`) — lower severity, it is the worker, but the same defect.

---

## AUD-024 — Observe the failures of background work {#aud-024}

**Severity:** Medium · **Dimension:** Error handling · **Effort:** S · **Issue:** #26

**24a.** The three webhook routes use bare `asyncio.create_task` with a done-callback that only discards. The strong reference is held, so nothing is GC'd mid-flight, but no exception is observed: anything `process_channel_event` cannot catch vanishes into asyncio's "Task exception was never retrieved" at GC, outside the app's logger and without the bot context. They also bypass `drain()` — see AUD-011. Use `spawn(...)`, which exists for this and whose module docstring is a lecture on the failure mode.

**24b.** `worker/tasks/rag_tasks.py:155-161`:

```python
await asyncio.gather(*tasks, return_exceptions=True)
logger.info("Scheduled sync check: dispatched %d source(s)", len(sources))
```

Every exception, including `CancelledError`, is collected and discarded. A Google Drive source with expired credentials raises on every scheduled run; the flow logs "dispatched 3 source(s)" and reports `Completed()` to Prefect. `_run_source_sync` writes `status="error"` for failures it catches internally, but anything raised in its setup block (`rag_tasks.py:400-437`, before the `try` at 444) escapes into the gather and leaves both the sync log and the source row untouched. Inspect the results and log failures per source id; `asyncio.TaskGroup` is the better shape if a failure should stop the batch.

---

## AUD-025 — Paginate `GET /rag/documents` {#aud-025}

**Severity:** Medium · **Dimension:** Data · **Effort:** S · **Issue:** #27

`repositories/rag_document.py:51-58` (`get_all`) takes no `limit` and no `offset`; `services/rag_document.py:82-86` does `total=len(docs)`; the route (`routes/v1/rag.py:340-357`) exposes no `skip`/`limit`. Every `rag_documents` row across all the caller's readable collections is selected and serialized in one response — a tenant with 50k documents gets a multi-second query and tens of MB held in memory. The sibling `get_for_kb` at `:61-76` pages properly, so the pattern is right there.

Add `skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)` per `.claude/rules/api-conventions.md`, and a `COUNT` for `total`.

**Related, worse, and worth doing together:** `vectorstore.py:412-429` (`get_documents`) runs `SELECT parent_doc_id, metadata FROM rag_<col>` with no `WHERE` and no `LIMIT` and groups in Python — and `ingestion.py` calls it at three sites to answer "is there already a document with this source path". On a 200k-chunk collection that is a full table read into worker memory, once per ingested document. Add a predicate query with a supporting expression index. In the same module, `vectorstore.py:308-324` inserts chunks one round trip at a time; a 500-page PDF is thousands of sequential statements where one `executemany` would do.

---

## AUD-026 — Return the five repository-calling routes to the service layer {#aud-026}

**Severity:** Medium · **Dimension:** Structure · **Effort:** M · **Issue:** #28

**Where:** `org_integrations.py:152`, `knowledge_bases.py:453`, `runs.py:41,52`, `audit.py:32,35`, `model_providers.py:144`

CLAUDE.md and `.claude/rules/architecture.md` both state that routes never import or call repositories. Five handlers do. (`knowledge_bases.py:28` and `skills.py:21` import types only — `CollectionCounts`, `SkillSort` — which is fine.)

**To be fair: all five currently get tenant isolation right.** Each hand-rolls `organization_id=ctx.organization_id` into the repo call. The cost is not a live bug, it is that the rule "tenant isolation lives in a service" now has five exceptions, so the next reader copying `runs.py` gets a template with no service to put the check in — and the isolation is expressed in five places instead of one.

**One of the five is worse than a layering nit.** `model_providers.py:135-156` defines `_listing_key` — a private helper in a **route file** that unseals vault secrets:

```python
async def _listing_key(db: Any, provider: str, *, organization_id: UUID) -> str | None:
    secrets = await organization_secret_repo.list_secrets(db, organization_id=organization_id, purposes=[provider])
    for secret in secrets:
        value = unseal_secret(...)
```

Three problems in one function: decryption in the HTTP layer; `db: Any`, a typing escape the repo's own rules forbid; and `list_secrets` is called with its default `see_all=True`, so it walks **every** secret in the organization regardless of visibility or grants and unseals the first API key it finds. The route is gated only on `AGENTS_VIEW`, which a Viewer holds — so Member A's *private* OpenAI key is unsealed and spent to serve Member B's model picker. The plaintext never leaves the function, so this is unauthorized *use* rather than disclosure: quota, billing and provider-side request logs. It directly contradicts `permissions.py:45-50`, which says gating the whole vault was the defect `SECRETS_VIEW` was introduced to fix.

Move it into `ModelProfileService` or `OrganizationSecretService` and resolve visibility the way the secret listing does — `visible_resource_ids(..., Perm.SECRETS_VIEW)`, `user_id=ctx.subject_id`, `shared_ids`.

**The gate is the reason this matters.** `model_providers.py` is in neither `[tool.coverage.run] include` nor `[[tool.ty.overrides]] include`. Neither are `app/core/audit.py`, `app/core/sanitize.py`, `app/services/agent_embed.py`, `app/services/embed_session.py`, `app/services/channels/slack.py` / `telegram.py` / `mattermost.py` / `router.py` (only `mentions.py` is included). Those modules hold AUD-002, AUD-004, AUD-018, AUD-021 and half of AUD-015 between them. The 100% gate is doing exactly what it was built to do inside its boundary; the boundary just does not include several modules that implement the refusals CLAUDE.md names as must-cover. Adding them means editing both lists in `pyproject.toml` — worth doing incrementally, highest-risk module first.

---

## AUD-027 — Correct three documentation claims {#aud-027}

**Severity:** Medium · **Dimension:** Docs · **Effort:** S · **Issue:** #29

Each of these tells a reader something is enforced when it is not. Fix the code or fix the page, but they cannot both stand.

- **`docs/governance.md:156`** — *"There is deployment-level rate limiting on the API."* Neither the app nor the bundled nginx does any (AUD-007).
- **`docs/channels.md:186`** and **`agent_runner.py:224`** — *"Spending limits per binding, on top of the agent's own and the organization's"* / *"its caps are enforced"*. `AgentExposure` has no cap column; its own docstring says those columns *"arrive with the routes that serve one"*, i.e. later. `_assemble` uses `exposure` for `environment_id` and for stamping `exposure_id` on the run row, and nothing else. An operator reading that page believes a public Slack bot is independently capped. Cheapest correct move: delete both claims until the column exists.
- **`docs/governance.md:41-46`** — *"the commit is explicit rather than left to the session context"* — true only of web chat (AUD-003).

**Separately, and lower stakes:** 65 migrations were collapsed into `0001_baseline.py` (commit `3597cc3`), but roughly twenty places still cite revision numbers that no longer exist in `backend/alembic/versions/` — `CLAUDE.md:70,74,76`, `.claude/rules/exceptions-security.md:70`, five `.claude/skills/*`, `.claude/commands/review.md`, `docs/architecture.md:157`, `docs/permissions.md:17`, `docs/secrets.md:11`, `docs/commands.md:150`, and docstrings in `app/repositories/user.py:64,128`. The `alembic-migration` skill acknowledges it ("revisions the docs cite by number resolve in git history"); nothing else does, so a reader who runs `ls backend/alembic/versions/` concludes the docs are wrong. Add one line to CLAUDE.md's migration section saying the chain was squashed and the numbers are historical.

---

## AUD-028 — Nine smaller items {#aud-028}

**Severity:** Low · **Effort:** S each · **Issue:** #33

- **`spec_version` is write-only.** `rg spec_version app` returns two lines in `spec.py`, neither a read; both migrations key on content shape, not the number. So a client's `spec_version: 3` YAML can be published carrying v7 constructs, and a spec from a newer deployment is accepted silently as long as its fields parse. Stamp it on publish and refuse `> SPEC_VERSION`, or delete the field.
- **`spec.observability.token_secret_id` is not validated at publish**, unlike every other secret reference. A wrong-kind or wrong-tenant id publishes fine and the agent runs **untraced**, with `agent_logfire_token_unavailable` in a log nobody reads. `factory.py:307-322` claims *"publishing is where a missing secret is refused, and a run is far too late."*
- **`hint` is the whole secret for short values.** `ApiKeySecret(api_key='1234').hint` → `'1234'`. `SealedStr` has no `min_length` and `seal()` refuses only the empty string, so a short proxy or test key is published verbatim in `SecretRead.hint` — whose field description reads *"Four characters of the secret — never the secret itself"* — and into the audit entry. `min_length=8` on the sealed fields.
- **`secrets.compare_digest` on non-ASCII `str` raises `TypeError`**, not `False` (`deps.py:595`, `channels/mattermost.py:241`, `channels/slack.py:183`). `{"token": "é"}` to the Mattermost webhook is a 500 with a logged traceback instead of a 403 — a free log-flooding primitive on an unauthenticated endpoint. Compare `.encode()`d bytes.
- **`validate_webhook_url` has no production callers.** A complete, well-tested SSRF guard (link-local, CGNAT, metadata IPs, fail-closed) called from nowhere in `app/`, while `ingestion_config.py:471` cites it as *"the request forgery this platform refuses everywhere else"*. Not exploitable today — MCP has its own `validate_mcp_url` on all four write paths — but the next URL field added will be unguarded by default. Wire it into the channel-bot schemas (needed for AUD-022 anyway).
- **The Slack Socket Mode client is never closed** (`slack.py:126-142`). No `try/finally`; `stop_polling` cancels the task, the aiohttp session, the WSS connection and the registered handler are orphaned. Only bites at shutdown today; becomes a duplicate-processing bug the moment a runtime restart path exists.
- **`McpOAuthPayload` holds `client_secret`, `access_token` and `refresh_token` as plain `str`** (`mcp_oauth.py:100-107`), while `docs/secrets.md` states every secret-bearing field is a `SecretStr` *"so the dataclasses carrying credentials mask themselves in a repr — which is the way a plaintext key usually escapes"*. No leak path today; the guarantee holds by accident of one `except` clause rather than by the mechanism the docs credit.
- **`ModelProfile.allow_byo`** is written by `model_providers.py:90` and read by nothing. A security-relevant toggle with no implementation. Fails safe, but it is dead weight.
- **`get_worker_db_context` duplicates `_managed_session`'s body verbatim** (`db/session.py:84-96` vs `:34-44`) instead of reusing it. Two copies of the commit/rollback/log logic, already at risk of drifting.

---

## AUD-029 — Encode the avatar proxy's path segment {#aud-029}

**Severity:** High · **Dimension:** Security (frontend) · **Effort:** S · **Issue:** #13

**Where:** `frontend/src/app/api/users/avatar/[userId]/route.ts:12`

**What's wrong.** This is the only route handler under `src/app/api/**` that takes a client-controlled path segment, interpolates it **unencoded** into the backend URL, and has **no `access_token` check at all**:

```ts
const response = await fetch(`${BACKEND_URL}/api/v1/users/avatar/${userId}`);
```

The sibling `orgs/[id]/avatar/route.ts:11` does the same job with `encodeURIComponent`, as do `sessions/[id]/route.ts:12` and the MCP OAuth callback. This one was missed.

**How it fails.** Next decodes `%2F` into the param, and `new URL`/`fetch` then normalise `..`, so the segment escapes the intended path. Verified independently against Node's URL parser:

```
"x/../../../openapi.json"  -> /api/v1/openapi.json
"../../../health?probe=1"  -> /api/health?probe=1
```

and reproduced end to end against a running dev server with an instrumented backend, **with no cookie**:

```
GET /api/users/avatar/x%2F..%2F..%2F..%2Fopenapi.json   → backend received GET /api/v1/openapi.json
GET /api/users/avatar/..%2F..%2F..%2Fhealth%3Fprobe%3D1 → backend received GET /api/health?probe=1
```

So an anonymous internet caller drives arbitrary `GET path + query` against the internal FastAPI origin and reads the response body back — the handler returns the buffer with the backend's content-type, and on non-2xx it returns the status with an empty body, which is still a working enumeration oracle. The host is fixed by the `${BACKEND_URL}` prefix (`//evil.com`, `../../../../evil.com` and backslash variants were all checked and do not escape the origin), so this is confined to the backend service — but that service is otherwise not internet-reachable. Everything it serves without an `Authorization` header — health, `/openapi.json` and `/docs` wherever `SHOW_DOCS_ENVIRONMENTS` applies, any public GET — becomes public, unauthenticated and un-rate-limited. AUD-007 means un-throttled, too.

The missing cookie check is itself intentional: `backend/app/api/routes/v1/users.py:64-69` serves avatars publicly. The encoding is the defect.

**Fix.** `encodeURIComponent(userId)`. Better, since the backend signature is `user_id: UUID`, validate it parses as one and 400 otherwise.

**Done when:**
- [ ] The forwarded path for `userId = "../../health"` stays under `/api/v1/users/avatar/`.
- [ ] Regression test in a node environment, plus the repo-wide sweep in AUD-030.

---

## AUD-030 — Encode every interpolated segment in the hand-rolled proxies {#aud-030}

**Severity:** Medium · **Dimension:** Security (frontend) · **Effort:** S · **Issue:** #30

**Where:** ~18 handlers under `frontend/src/app/api/**` interpolate a bare `${param}` into a backend path — `orgs/[id]/route.ts:13,30,48`, `orgs/[id]/members/**`, `orgs/[id]/invitations/**`, `orgs/[id]/integrations/**`, `invitations/[token]/route.ts:13,30`, `files/[id]/route.ts:16`, `me/slash-commands/[id]`, `me/mcp-connections/[id]` and `[id]/test`, `admin/users/[userId]` (×3), `admin/users/[userId]/impersonate`, `admin/conversations/[id]`.

**How it fails.** Same normalisation as AUD-029, reproduced against the running server:

```
GET /api/orgs/x%2F..%2F..%2Fadmin%2Fusers   (with cookie) → backend received GET /api/v1/admin/users
```

The browser reaches any backend route through these mounts carrying its own bearer token — including the `/api/v1/admin/*` surface the BFF deliberately fences behind `requireAdmin` (`lib/admin-auth.ts:5`).

**This is defence-in-depth, not live privilege escalation.** The backend re-gates admin on `CurrentAppAdmin` (`admin_users.py:17,35,46,67,88`, `admin_stats.py:18,27,43`), so nothing is currently reachable that would not be reachable anyway. It is Medium because the BFF's own gate is now decorative, and the day a backend route lands assuming "only reachable via a handler that checks X", it is exposed.

**Fix.** `encodeURIComponent` on every interpolated segment. Then extend `frontend/src/lib/platform-proxy.test.ts` — which already walks every `route.ts` for the org-header omission — with a second sweep that fails any source interpolating a bare `${param}` into a `/api/v1/...` template. A per-route test leaves the next hand-rolled route to repeat it, which is the reasoning that file already gives for its first sweep.

**Not affected:** the shared `platformProxy` (`lib/platform-proxy.ts:90-91`) passes `request.nextUrl.pathname` through verbatim, so `%2f` and `%2e%2e` stay encoded and the backend sees the literal segment. Verified.

---

## AUD-031 — Stop putting tokens in the OAuth redirect URL {#aud-031}

**Severity:** High · **Dimension:** Security (frontend/auth) · **Effort:** M · **Issue:** #14

**Where:** `backend/app/api/routes/v1/oauth.py:44-53`; consumed at `frontend/src/app/[locale]/auth/callback/page.tsx:17-18`

**What's wrong.**

```python
access_token = create_access_token(subject=str(user.id))
refresh_token = create_refresh_token(subject=str(user.id))
params = urlencode({"access_token": access_token, "refresh_token": refresh_token})
return RedirectResponse(url=f"{frontend}/auth/callback?{params}")
```

**How it fails.** A Google sign-in lands the user on `https://app/…/auth/callback?access_token=<jwt>&refresh_token=<jwt>`. Both tokens are therefore written to the Next server's request log and any reverse proxy in front of it; to the browser address bar and session history until `router.replace` runs at line 44; and to the `Referer` of every same-origin request the page then makes — `Referrer-Policy: strict-origin-when-cross-origin` (`frontend/next.config.ts:47-49`) sends the *full* URL same-origin, so the subsequent `POST /api/auth/oauth-callback` carries both tokens in its `Referer`, and that request is logged too.

The refresh token is good for seven days (`REFRESH_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7`). Anyone with read access to an access log has a week of full account access. Nothing in `docs/` records this as a decision — `docs/configuration.md:78-85` documents the OAuth settings and says nothing about token delivery.

**Fix.** Have the backend set the cookies itself on the callback, or redirect with a single-use short-TTL exchange code that `/api/auth/oauth-callback` swaps for the token pair server-to-server. Either way the frontend page never sees a token.

**Related, and worth doing in the same change:** `frontend/src/app/api/auth/oauth-callback/route.ts` accepts an arbitrary token pair from the request body and mints cookies from it — a session-fixation shape. It could not be shown exploitable (a cross-origin JSON POST needs a preflight Next does not answer, and there is no CORS config on the frontend app), so it is not a finding on its own. But it is the route to revisit if this is fixed by any means other than removing the client-supplied tokens.

**Done when:**
- [ ] The redirect `Location` contains no `access_token` or `refresh_token`.
- [ ] Regression tests on both halves: the backend redirect, and the callback page posting a code rather than tokens.

---

## AUD-032 — Gate the `/rag` write controls on `collections:edit` {#aud-032}

**Severity:** Medium · **Dimension:** Permissions (frontend) · **Effort:** S · **Issue:** #31

**Where:** `frontend/src/app/[locale]/(dashboard)/rag/page.tsx` — no `usePermissions` import anywhere in the file; controls at `:285` (create collection), `:516` (Upload files), `:528-544` (Delete collection), `:703-721` (Delete document), `:894` (delete sync source). Offered in the sidebar on `Perm.collectionsView` (`components/layout/app-sidebar.tsx:92`).

**What's wrong.** Viewer, Operator and — outside their own rows — Member hold `collections:view` without `collections:edit` (`backend/app/core/permissions.py:210-236`). The sidebar therefore shows them the page, and the page offers every write control unconditionally. The backend refuses all of them (`routes/v1/rag.py`, `require(Perm.COLLECTIONS_EDIT)` on twelve routes), so clicking produces a 403 toast.

`.claude/rules/frontend.md:44-45`: a control the caller may not use is **not rendered** — not rendered and then 403. The sibling page already does it right: `kb/[id]/page.tsx:86-88` computes `mayEdit = can(Perm.collectionsEdit)` with a comment naming Viewers specifically. `/rag` was never brought along.

**Fix.** `const mayEdit = can(Perm.collectionsEdit)` and gate the five sites, mirroring `kb/[id]/page.tsx`.

**Done when:**
- [ ] A Viewer sees no write control on `/rag`.
- [ ] `rag-page.integration.test.tsx` against a mocked `/me/permissions` returning `collections:view` only. The rule requires an integration test, not Playwright.

**No drift in the permission catalog itself** — this was checked specifically because it was the likeliest headline. `hooks/use-permissions.ts:32` fetches `/me/permissions` from the server rather than deriving anything; `types/permissions.ts:11` deliberately types `Permission` as an open template literal so the UI cannot hardcode the list; and the 21 constants at `:40-62` match `Perm` in `backend/app/core/permissions.py:37-63` exactly. The only role→behaviour mapping left in TS is `ASSIGNABLE_FALLBACK` (`use-permissions.ts:86`), a pre-catalog placeholder replaced as soon as `/roles/catalog` answers.

---

## AUD-033 — Let a failed query render an error, not an empty state {#aud-033}

**Severity:** Medium · **Dimension:** Error handling (frontend) · **Effort:** M · **Issue:** #32

**Where:** `frontend/src/app/[locale]/(dashboard)/rag/page.tsx:171,179,191,203,214,303`; `frontend/src/hooks/use-knowledge-bases.ts:160-170`

**What's wrong.** `.claude/rules/frontend.md:50-54` names this exact defect ("an empty page is ambiguous"). Six call sites swallow a rejection into `[]` with no error state:

- A 502 on `listTrackedDocuments` sets `docs = []` and the page renders **"No documents — Upload PDF, DOCX, TXT, or MD"** (`:636-640`). A user whose documents failed to load is told they have none, next to a button inviting them to upload duplicates.
- A 500 on `listSyncSources` renders **"No sync sources configured"** (`:833-841`); on `listSyncLogs`, "No sync history yet" (`:933`).
- In `use-knowledge-bases.ts`, three `.catch(() => ({ items: [] }))` sit *inside* a `Promise.all` whose outer `catch` (`:178-179`) does set `error` — so the two calls that matter surface a failure and the three connector/sync-source calls silently do not. A failed `/kb/{id}/sync-sources/connectors` reaches `sync-source-wizard.tsx:447-450`, which renders **"No connectors enabled."** The user concludes Google Drive is not available in this deployment.

Unlike the deliberate `.catch`es elsewhere — `use-conversations.ts`, `use-invitations.ts`, `use-organizations.ts`, `use-members.ts` all toast before returning `null` — none of these carries a comment justifying the swallow, and `useKBDetail` already has an `error` state at `:126` that they bypass.

**Fix.** Let the rejection reach an error state and render from `components/states/`. In `useKBDetail`, drop the three inner `.catch`es or record a per-section failure flag.

**Done when:**
- [ ] Each section renders an error component on a 502, not its empty state.
- [ ] Tests mock the fetch as 502 and assert the *error* state — explicitly not the empty state, and not only on chrome.

---

## What's good

Worth keeping, and worth saying — several of these are better than what most production repos manage:

- **`tests/integration/test_platform_flows.py`** is 3.6k lines of named refusal behaviours run against a real Postgres: tenant isolation, grant-widened access, budget accumulation, publish and rollback, renaming a tool on a published agent, "which secrets a member sees", "who still hears about runs". The test names state the behaviour, so a failure says what broke. This file is the reason the findings above are as narrow as they are.
- **The reasoning is written down and it is usually right.** `permissions.py` explains why `Scope` refuses mixed comparisons (a `str` subclass would order `all < none < own` and silently widen access). `access.py` explains why an anonymous context gets `[]` rather than `None`. `mcp.py` explains why `CancelledError` must survive the exception-group unwrapping. These are the subtle cases, and they are handled.
- **`core/background.py`** is textbook: strong-reference set, `cancelled()` checked before `exception()`, `drain` with timeout-then-cancel. Its only defect is that nobody calls it.
- **Money arithmetic.** `Decimal` throughout, `Numeric(12, 6)` in the schema, no `Float` anywhere in `app/db/models/`. `_as_decimal` converts a JSON float via `str`, not `Decimal(float)`. `price_request` retries without the provider hint so a fallback model is priced correctly, and an unpriceable model records `0` with `priced=False` → `cost_is_partial`. A response with no `usage` records nothing rather than a fabricated zero.
- **The vault's owner binding.** Scope kind, subject id and version all enter the derivation, so a ciphertext moved between organizations, between members, or between an org and a user scope with the same UUID all fail to unwrap — with a uniform message. `tests/test_vault.py:61-100` covers each.
- **`tests/api/test_no_secret_escapes.py`** sweeps the generated OpenAPI document for both secret payload models and secret-shaped field names, with an explained allowlist. A far better control than route-by-route assertions, and it currently holds.
- **`tests/api/test_platform_routes.py`** walks the real dependency tree to prove every platform route is either gated or resource-aware, and that every unauthenticated route is deliberate — including WebSockets. The collection-vs-per-resource split is respected throughout.
- **Constraint coverage.** A *partial* unique index for "at most one default environment per agent"; a three-check set enforcing the MCP user/org scope split; uniqueness at the database for `message_ratings`, `skills`, `agents`, `agent_versions`, `organization_members`, `resource_grants`. Every `DateTime` is `timezone=True`. AUD-009 is precisely where this discipline collides with itself.
- **Approval keying.** `approval_required_tools` reads `tool.id` for the decision and `effective_tools(...).name` for the match, so a binding's rename cannot silently drop a gate; `ToolOverrides._describe` runs before `.renamed(...)`; `ApprovalGate` refuses rather than guesses when `capability_id is None`.
- **`agent_session.py`** — one turn at a time, cancel-and-await with `suppress(CancelledError)`, a done-callback distinguishing disconnect from crash, and the route doing `finally: await session.shutdown()`. `_refresh_under_lock` takes a `FOR UPDATE` row lock with a documented consistent lock ordering and re-reads after acquiring. This is the correct check-then-act that AUD-015 asks the four siblings to copy.
- **`build_toolsets_for_agent` awaits in a loop deliberately** — the connections share one `AsyncSession`, which is not concurrency-safe, so a `gather` there would be a worse bug. Correctly left alone.
- **CI.** Actions pinned by SHA, pgvector pinned in every job with a comment explaining why, the migration chain cycled forwards *and* back to base, `mkdocs --strict`, and a `security` job whose comment documents the three ways it previously failed to audit anything.
- **The `except` discipline in the platform layer.** Every swallow is deliberate, logged, and explained; `web_research/_search.py` wraps provider failures in a domain type with `from exc`, and every provider key goes in a header rather than a query string, so no key reaches an `httpx` error message.
- **`platformProxy`** (`frontend/src/lib/platform-proxy.ts`) — cookie-only token, no client-supplied token path, backend status and body passed through unre-serialised, bytes not text, `cache: "no-store"`, and no path traversal. The client-supplied `X-Organization-Id` it forwards is safe because `deps.py:225-248` looks up the membership row and refuses an org the caller does not belong to. Its two repo-wide sweeps in `platform-proxy.test.ts` — every client path has a route, no hand-rolled route drops the org header — are the right shape, and AUD-030 asks for a third in the same style.
- **Frontend cookie and token hygiene.** `httpOnly`, `secure` in production, `sameSite: "lax"`, 15 min / 7 days, consistent across login, refresh, logout, magic-link and oauth-callback; refresh rotates both and clears both on rejection. No token in `localStorage`; `auth-store.ts:69-73` genuinely excludes `accessToken` from `persist`; all eight `NEXT_PUBLIC_` uses are benign; the WebSocket passes the token as a subprotocol rather than a query param. `api-client.ts:96-101` refreshes exactly once, never recurses into the refresh endpoint, and de-duplicates concurrent 401s.

## Not audited

- **Frontend UI depth** (~80k LOC). Only the auth proxy, token handling, permission gating and empty-state handling were in scope; components, stores, i18n and rendering were not. The Playwright E2E suite was not run — it needs the full stack up.
- **Template-inherited RAG internals** — `services/rag/ingestion.py`, `embeddings.py`, the connectors, and the parsers beyond their blocking-I/O and query shapes. Traced for resource ownership only where it crossed a request path.
- **Prefect worker internals** — `worker/prefect_app.py`, `mcp_tasks.py`, `report_tasks.py` unread. Whether a queued task re-checks the tenant it was enqueued for is unverified.
- **`app/agents/mcp_oauth.py`** — deliberately outside the coverage gate as protocol plumbing; audited only for the credential typing in AUD-028.
- **Migration safety is largely moot** — there is one squashed `0001_baseline.py`. Its `downgrade()` drops what `upgrade()` creates, and CI cycles it. There are no incremental migrations to audit for NOT NULL-on-populated-table, long backfills, or JSONB rule narrowing.
- **Churn-based hotspot analysis was not possible** — 38 commits over four days. There is no history yet from which to argue "this module is where the bugs concentrate", which is why there are no refactor proposals in this report. AUD-026 is the closest thing, and it is argued from the stated rule rather than from churn.
- **`pip-audit` would not run locally** (the tool's throwaway venv aborts on this machine's default Python 3.14); I reproduced CI's exact command against a 3.12 interpreter instead, and it reports clean.
- **Whether `wrap_tool_execute` receives the pre- or post-`renamed` tool name** is asserted by the repo's own tests but not verified against the Pydantic AI source. If those tests stub the wrapper, the approval gate's name matching is unverified.
- **`AgentSpec` field history.** `SPEC_VERSION = 7` with `extra="forbid"` and no upgrade branch anywhere in `app/`. If a field was removed or renamed across v1→v7, every spec stored before that change fails `model_validate` and its agent stops running. The squashed history means I could not establish whether any field actually was removed — worth a look from someone who knows.

## Notes

- **AUD-001, AUD-005 and AUD-026 share a root cause worth naming:** an optional `organization_id` parameter that defaults to "unscoped". `_resolve`'s docstring anticipated it and asked future readers to grep for the default. The durable fix is not the two call sites — it is making the tenant a required argument everywhere and giving the two legitimate unscoped callers an explicit, greppable sentinel.
- **AUD-002 and AUD-022b are the same incident waiting to happen.** A Mattermost bot cannot be given a server URL, and a Mattermost bot without a server URL starves the event loop. Fixing 22b without 2 turns a dead feature into a live outage; do 2 first.
- **The frontend has the same shape of gap as the backend**, in miniature: the shared, well-built forwarder (`platformProxy`) is correct and swept by its own tests, while the ~19 hand-rolled handlers beside it each re-implement a piece of it and one of them dropped the encoding. Every one of AUD-029 through AUD-033 passes `tsc`, `eslint --max-warnings 0` and all 2424 vitest tests. The durable fix for AUD-030 is the sweep, not the eighteen edits.
- **Several findings are only invisible because a test mocks the thing that is broken** — `test_conversation_scoping` mocks the service, `test_agent_org_scope` uses a bare `MagicMock` that accepts any signature, `test_limiter_exists` asserts an object is not `None`, `tests/conftest.py` overrides `get_db_session` so `_managed_session` is never exercised. Worth one deliberate pass over the suite asking "would this test still pass if I deleted the implementation?"
