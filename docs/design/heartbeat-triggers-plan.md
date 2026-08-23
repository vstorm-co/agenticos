# Heartbeat & agent triggers — plan first

Design for [#44](https://github.com/vstorm-co/agenticos/issues/44), written plan-first per
the Notion card's *design first, bring a written plan to @DEENUU1 before a line of code* —
**reviewed and approved by @DEENUU1 on 2026-08-10**, then revised to match his answers and
two implementation corrections (recorded in the final section). Implementation follows on
the same branch.

The brief is one sentence: today an agent only runs when somebody writes to it; add other
triggers — **every X minutes**, **when an email arrives**, and so on. The five questions the
issue poses are all answered below.

## 0. What already exists — corrected

The issue's "What already exists" is right in substance and stale in three particulars.
Building against the stale version reinvents or misplaces work, so each is pinned to the
code as it is on `main` (`3c19eae`).

1. **`RunSurface.SCHEDULE` is *not* a value.** The enum
   (`backend/app/db/models/agent_run.py:55`) holds `WEB, EMBED, API, SLACK, TELEGRAM,
   MATTERMOST` and no more. `SCHEDULE` appears only in the docstring
   (`agent_run.py:62`), as the cautionary tale of #207: *"a value nobody writes is a
   filter that answers with nothing on every deployment for ever … `PLAYGROUND` and
   `SCHEDULE` were exactly that."* The rule stated there — **"every member here is
   assigned by something"** — is not an obstacle to this feature; it is its licence. This
   is the change that finally *writes* `SCHEDULE`, so re-adding the member is now correct
   for the exact reason removing it was. **No database migration:** the column is
   `surface: Mapped[str] = mapped_column(String(16), …)` (`agent_run.py:203`), a plain
   string, and `"schedule"` is eight characters. Adding the enum member is a one-line
   code change, not a schema change.

2. **`drain()` is not wired to anything that shuts the API down.** The only caller of
   `app.core.background.drain` (`background.py:144`) is the CLI sync command
   (`app/commands/rag.py:694`); the FastAPI lifespan does not call it, which is #11. The
   consequence the issue names is real — a run spawned in the API process is dropped on
   every deploy — but **the design below sidesteps it** rather than depending on its fix:
   the run executes inside a Prefect worker flow, not an in-process `spawn`. #11 remains a
   dependency only for the best-effort notifications the run path already fires, which are
   no worse off than they are for a chat run today.

3. **`spawn_after_commit` now exists** (`background.py:95`, #417) — the ordering fix for
   "work that reads a row the caller just wrote." It is not load-bearing here, but it is
   the reason a naive "spawn the run when the trigger row is created" would be the wrong
   instinct: the trigger does not run *on creation*, it runs *on a schedule*, and that is
   worker territory.

Two things the issue points at that are exactly right, and that this plan builds on:

- **The heartbeat already exists in another guise.** `check_scheduled_syncs_flow`
  (`app/worker/tasks/rag_tasks.py:244`, the flow the issue meant by `rag_tasks.py:155`)
  runs once a minute — registered as `rag-sync-check` with `IntervalSchedule(interval=60)`
  in `app/worker/prefect_app.py:53` — queries `sync_source_repo.get_due_for_sync(db)` and
  dispatches one flow per due row. A periodic trigger is the same shape aimed at a
  different table. **The precedent to follow — but not to copy line for line: the row-claim
  lock and the submit-and-return are net-new here (§3, §4), because `get_due_for_sync` takes
  no lock and `check_scheduled_syncs_flow` awaits its children.**
- **`AgentRunnerService.execute` is the run path** (`app/services/agent_runner.py:2571`):
  `execute(ctx, agent_id, prompt, *, surface=…, conversation_id=…, exposure=…,
  environment_id=…) -> (answer, AgentRun)`. It is the non-streaming funnel the API and
  channels already use; it calls `prepare` (`:1299`) then runs to completion. A cron
  trigger has no socket and nothing to stream, so `execute` is its entry point unchanged —
  which is what makes budgets, approvals and accounting apply identically for free.

## 1. Question 5 first — is a trigger in the spec, or a row beside it?

Answered first because it fixes the data model everything else hangs off, and because
the issue leans one way and this plan lands the other.

**Decision: a row beside the agent — a new `agent_triggers` table. `SPEC_VERSION` does
not move.**

The issue reasons: *"Given 'an agent is data, not code', the spec is the consistent
answer — and that means `SPEC_VERSION` moves."* The premise is right and the conclusion
does not follow, because the spec says in its own docstring what it refuses to hold
(`app/agents/spec.py:703`):

> Deliberately excluded: anything about *where* the agent runs (surfaces, channels) and
> anything about *who* may use it (owner, sharing). Those are deployment and access
> facts; keeping them out means the same spec can be exported, reviewed and reused across
> organizations.

A trigger is **both** of those excluded things at once. It is *where/when* the agent runs
(a schedule), and it carries *who it runs as* (a subject — see §2, and the whole reason
the issue calls identity the hard question). Put it in the spec and one of two things
breaks:

- If the subject goes in the spec, the spec stops being portable: a `created_by` user
  UUID is meaningless in another organization's exported YAML, and the "reused across
  organizations" property the spec exists to preserve is gone.
- If the subject stays out of the spec, a spec-defined trigger has no subject — and a run
  with no subject cannot pass the run path at all (§2). The spec would describe a trigger
  that can never fire.

So the trigger cannot live wholly in the spec without contradicting either portability or
runnability. The codebase already has the right home for "operational, not part of what
the agent *is*": `AgentExposure` (`app/db/models/agent_exposure.py`), whose docstring is
the template —

> An agent's author decides which surfaces it answers on. That decision is operational,
> not part of what the agent *is*: publishing a new version must not silently change who
> can reach it … Different lifecycle, different table.

A trigger has that same lifecycle: you add, disable and remove one without minting an
agent version, and publishing a new version must not silently change what is scheduled.
It is an exposure-shaped thing — a binding that admits runs and carries caps — and it
belongs in an exposure-shaped table.

### The `agent_triggers` table

Modelled on `agent_exposures` where the questions are the same; two columns — `last_run_id`
and `conversation_id` — are net-new, for guards the exposure never needed.

| Column | Type | Why |
|---|---|---|
| `id` | UUID PK | |
| `organization_id` | UUID FK orgs, CASCADE, indexed | The tenant. There is no ambient tenant in a worker (`background-task` skill), so it is read off this row. |
| `agent_id` | UUID FK agents, CASCADE, indexed | What runs. |
| `created_by_user_id` | UUID FK users, **SET NULL**, nullable | The subject — see §2. SET NULL mirrors the exposure; a null creator means the trigger cannot run and is disabled, never a silent fallback. |
| `is_active` | bool, default true | Turned off without being forgotten — the exposure's exact rationale (`agent_exposure.py:103`). |
| `environment_id` | UUID FK agent_environments, **SET NULL**, nullable | Which version to run, exactly as an exposure pins one (`agent_exposure.py:84`). Null = default environment. |
| `schedule_kind` | str(16) + CHECK `IN ('interval','cron')` | CHECK declared on the model *and* the migration, per the exposure's note that integration tests build the schema from the models. |
| `interval_seconds` | int, nullable | Set when `schedule_kind='interval'`. A CHECK enforces a floor (see §3) and that exactly one of interval/cron is set for the kind. |
| `cron_expression` | str, nullable | Set when `schedule_kind='cron'`. **Deferred — interval ships first** (§3). |
| `prompt` | Text | The input sent on each fire. A scheduled run has no human turn, so the "message" is stored here. |
| `next_fire_at` | timestamptz, indexed | When it is next due. The heartbeat's claim query is `is_active AND created_by_user_id IS NOT NULL AND next_fire_at <= now()`, taken `FOR UPDATE SKIP LOCKED` (§3, §4). |
| `last_fired_at` | timestamptz, nullable | Observability — when it last dispatched. |
| `last_run_id` | UUID FK agent_runs, **SET NULL**, nullable | **What the no-overlap guard reads (§3).** "Skip a trigger whose previous run has not reached a terminal status" has to *find* that run; `last_fired_at` is only a timestamp and nothing on `agent_runs` points back at a trigger. Net-new — the sync precedent keeps status on its own row (`sync_sources.last_sync_status`), and this table needs the same link. |
| `conversation_id` | UUID FK conversations, **SET NULL**, nullable | The **one** run-log conversation this trigger appends to on every fire (§5). Opened once, not per fire — a 60-second trigger would otherwise mint ~1440 conversations a day, for ever. |

Plus `TimestampMixin` and a `__repr__`, per `schemas-models.md`. `*Create`/`*Update`/
`*Read`/`*List` schemas and a `TriggerService` over a `trigger_repo`, per the layering in
`architecture.md`.

**A portable "schedule template" is a later, separate idea, if wanted at all.** One could
imagine the spec carrying a *suggested* cadence that a client's import materialises into a
real trigger with a real subject on their side. That is a feature about onboarding, not
about running, and it does not block anything here. Noted and set aside.

## 2. Question 1 — who does a triggered run run *as*?

The hard one, and the issue is right that "invent a fallback user" is the wrong answer —
`AuthContext.subject_id` (`app/core/permissions.py:315`) raises *loudly and here* when
there is no subject, precisely so the absence cannot travel to the `NOT NULL` audit-actor
column and surface as an `IntegrityError` several layers down (`permissions.py:332`).

**Decision: a triggered run runs as its creator (`created_by_user_id`), with the
membership re-resolved from the database on every fire.** This is not a new pattern; it is
the third instance of one the codebase has already settled twice, for the two other
surfaces with no live human at the keyboard:

- **A channel mention runs as the sender** (`app/services/channels/mentions.py:397`). It
  re-fetches the membership each time and **refuses** an identity with no membership:
  *"running with no role would mean running with none of the checks a role implies"*
  (`mentions.py:413`).
- **An embedded widget runs as its owner** (`app/services/embed_session.py:173`). It
  re-fetches the owner's membership for the *current* role and will not let a departure
  *widen* what the widget can do.

Both resolve to a **real, re-fetched member** — never a synthetic principal. Neither can
run as truly anonymous, because the run path resolves the spec through
`get(ctx, agent_id, perm=Perm.AGENTS_RUN)` (`app/services/agent_registry.py:1438`) and an
anonymous context holds `permissions == {}` (`permissions.py:353`) — it would be refused
`AGENTS_RUN` before any tokens are spent. A trigger is the same situation: unattended, but
attributable to the member who set it up. Concretely, each fire builds:

```python
AuthContext(user_id=trigger.created_by_user_id, organization_id=trigger.organization_id, role=membership.role)
```

re-fetching `membership` with `member_repo.get`, exactly as the mention and embed paths do.

### The creator is gone — auto-disable (resolved in review)

When the creator is no longer a member who may run *this* agent, the trigger
**auto-disables** (`is_active = False`), writes an audit entry saying why, and **notifies an
admin** — @DEENUU1 confirmed all three. A recurring, budget-spending automation with nobody
accountable to it is exactly *"a run nobody could be held to"* that `AuthContext` refuses to
mint. Refusing quietly per-fire would leave it retrying for ever against a wall; disabling
makes the failure visible and stops the noise. The rejected alternatives, for the record:
*keep firing and alert* (it cannot actually run), and *reassign to the agent's owner* (it
silently moves the bill and the authority to someone who did not ask for either, and lets a
low-privilege member escalate by scheduling against a higher-privilege owner).

**"May run *this* agent" is a per-resource question, not a role-level one — and this is
where a happy-path implementation gets it wrong** (Correction C, review). The run path
resolves `get(ctx, agent_id, perm=Perm.AGENTS_RUN)` (`agent_registry.py:1438`), which goes
through `resolve_access` and therefore sees **grants**. A pre-check that only asks "does the
creator's role still hold `AGENTS_RUN`" (`role_has`) is a *different, weaker* decision: a
creator who kept a role with `AGENTS_RUN: SHARED` but had their grant on this one agent
revoked would pass it, then be refused *inside* `execute` — which raises `AuthorizationError`,
which Prefect retries. That is the "silently retried refusal" #44 guards against, arriving
through the authz door instead of the budget one. So the pre-check **must mirror the run
path** — `resolve_access(ctx, agent, Perm.AGENTS_RUN, resource_type=AGENT)`, not `role_has` —
and an authz refusal that still escapes the run is caught and treated exactly like
`BUDGET_EXCEEDED` (§3): the trigger disables, it does not raise into a retry.

### Managing triggers is itself gated

Creating a trigger is asserting "run this agent, repeatedly, as me." The floor is
therefore `Perm.AGENTS_RUN` **on that agent**, resolved per-resource through
`resolve_access` in the service — never a blanket `require()` on the route, per the hard
boundary in `exceptions-security.md` that role gates belong on collection routes only. No
new permission is needed to ship; whether a dedicated `TRIGGERS_MANAGE` or an operator-wide
"see every trigger in the org" view is wanted is a small, separable question (§8).

## 3. Question 2 — what stops a runaway?

A trigger every minute against an agent with no cap is an unbounded bill. Three guards,
two of them free:

1. **A minimum interval.** `interval_seconds` carries a CHECK floor (proposed: `>= 60`).
   A tighter floor buys nothing a heartbeat that ticks once a minute could honour anyway
   (§4), and it bounds the worst case a fat-fingered value can reach.

2. **No self-overlap — the primary guard, and the fix for this feature's slice of #15b.**
   The heartbeat claims a due trigger with `SELECT … FOR UPDATE SKIP LOCKED`, advances its
   `next_fire_at` under that lock before dispatching, and **skips a trigger whose previous
   run — found via `last_run_id` (§1) — has not reached a terminal status.** So a trigger
   never races itself, and #15b — *concurrent runs each reading the same stale budget
   baseline* — cannot be reached *by one trigger against itself*. The cross-trigger and
   cross-surface case (two different triggers, or a trigger and a chat run, reading the same
   baseline at once) is still #15b's, unchanged and unsolved here. **This plan bounds the
   new overlap it would otherwise introduce; it does not claim to fix #15b, and names it as
   a dependency (§7).**

   **The lock is invented here, not inherited** (Correction A, review). `get_due_for_sync`
   (`sync_source.py:40`) is a plain `SELECT … WHERE is_active …` with a Python-side
   `last_sync_at + interval <= now` filter and **no** `FOR UPDATE SKIP LOCKED` — it arguably
   has a latent double-fire precisely because it omits this. The claim-and-advance-under-lock
   protocol is new work, deliberately, and the plan says so rather than pretending the
   precedent hands it over.

3. **The budget, inherited whole.** Because the run goes through `execute → prepare →
   _assemble`, it meets the same two ceilings every other run does: the agent's own cap
   and the organization's, read *inside* `_assemble` (`agent_runner.py:1479-1483`) rather
   than passed by the caller — the module's founding rule, *"a limit each caller has to
   remember is a limit the next surface will not have."* A triggered run over budget ends
   `RunStatus.BUDGET_EXCEEDED` like any other. Two things the flow must get right on top of
   that:
   - **Fail fast.** Re-assert the budget at the top of the flow before assembling, the way
     `_run_ingestion` does with `assert_organization_within_budget`
     (`rag_tasks.py`) — *"the budget can be reached by runs that finished while this file
     waited in the queue."* Same reasoning: the queue between "due" and "run" is time in
     which the budget can be spent elsewhere.
   - **Do not retry a refusal — budget *or* authz.** A `BUDGET_EXCEEDED` outcome is the
     platform working, not a malfunction, and so is an `AuthorizationError` from a creator
     whose grant was revoked (§2). Both are caught and end the flow *normally* — the trigger
     disables or parks — so Prefect's retry policy never fires. A refusal that raises into a
     retry is the "silently retried" failure the issue's test guards against, and it has two
     doors, not one.

## 4. Question — the shape: a heartbeat over rows, not a deployment per trigger

**Decision: one `check_agent_triggers_flow` heartbeat, `IntervalSchedule(interval=60)`,
registered once in `prefect_app.py` — following `check_scheduled_syncs_flow`'s shape, but
diverging from it in the two places it does not cover (the row lock, §3, and the
submit-and-return below).** Each tick opens a worker session, claims due triggers under the
lock (§3), and dispatches one run flow per claimed trigger.

The alternative — **a Prefect deployment per trigger**, each with its own
`CronSchedule`/`IntervalSchedule` — was considered and rejected for user-created triggers.
It would make every trigger CRUD operation an *imperative call to Prefect's deployment
API* from a request handler (create a deployment on POST, delete it on DELETE, patch it on
edit), coupling the app to the scheduler's control plane and leaving a class of bug where
the row and the deployment disagree. Keeping triggers as **plain rows** means create/edit/
delete is ordinary `TriggerService` work — no Prefect call on the request path — which is
what the exposure precedent does and what the issue's word *"heartbeat"* already implies.
The one thing the deployment-per-trigger model would give — Prefect owning the cron
arithmetic — is small for intervals (the flow computes `next_fire_at = now +
interval_seconds`) and is why **cron expressions are deferred**: a cron needs `croniter`
and a timezone decision that `prefect_app.py:78` already notes an interval avoids. Interval
first; cron as a bounded follow-up.

**Dispatch must submit-and-return, and here the precedent is the wrong model to copy.**
`check_scheduled_syncs_flow` does `asyncio.gather(*tasks)` over
`asyncio.create_task(sync_single_source_flow(...))` and **awaits all of them**
(`rag_tasks.py:244`). Copy that literally and one slow agent run holds the whole 60-second
tick open — and the *next* `IntervalSchedule(60)` tick then starts a second concurrent
heartbeat on top of it, which is exactly the double-fire the `SKIP LOCKED` claim (§3) exists
to stop. To genuinely submit-and-return, the heartbeat fires each child through Prefect —
`run_deployment(..., timeout=0)` for `run_scheduled_trigger_flow`, which enqueues a run and
does not await it — so the tick stays short and the lock, not luck, is what keeps two
heartbeats off one trigger. (Accepting a blocking tick is the alternative; rejected, because
it makes the tick's duration a function of the slowest run.)

## 5. Question 3 — where does a triggered run's output go?

A chat run answers into a conversation; a scheduled run answers into nothing, and a run
whose output nobody can see is one this platform's Activity page exists to refuse.

**Decision: one conversation *per trigger*, not per fire — a run-log opened once and
appended to** (resolved in review). The `conversation_id` lives on the trigger row (§1); on
the first fire the flow opens a conversation (`user_id=None`, titled for the trigger, as the
embed widget does at `embed_session.py:144`) and stores its id, and every later fire passes
that same id to `execute`. Per-*fire* was the first draft and is unbounded — a trigger on
the 60-second floor mints ~1440 conversations a day for ever, and the sync precedent
pointedly does not create a row per fire. Per-*trigger* keeps one scrollable log instead of
a firehose.

**Activity loses nothing by this**, which is what makes it safe: an Activity entry is an
`agent_run` row, and **every fire still writes its own run** stamped `RunSurface.SCHEDULE` —
the run-detail drill-down reads the run and its transcript, not the conversation's shape.
Passing no `conversation_id` at all is still not an option: `TranscriptService.record`
writes nothing without one, and the run would be a cost with no visible reason.

Two sinks already work for a triggered run for free, because they hang off the run path:

- **Approvals.** If a triggered run trips an approval gate, `finish` already calls
  `notifications.approval_requested` (`agent_runner.py`), so the approver is paged with no
  new code. A scheduled run that needs a human decision parks in `AWAITING_APPROVAL` like
  any other and waits.
- **Budget alerts.** `notifications.budget_exceeded` already fires on the org ceiling.

What does **not** exist is a *"your scheduled run produced this"* notification —
`app/services/notifications.py` has `budget_exceeded`, `approval_requested`, `usage_report`
and `agent_usage_report`, and no "run completed." **Recommendation: ship the conversation
sink first** (it is the durable record and the Activity entry), and add a completion/
failure notification as the immediate follow-up rather than folding a new
`NotificationService` method and its email template into this issue. Pushing the *answer*
outward — to email, to a channel — is where this meets §6 and is deferred with it.

## 6. Question 4 — email-in is a separate, larger feature

**Decision: scope this issue to time-based (interval) triggers. File email-arrival as its
own issue.** The issue itself flags the asymmetry, and it is stark: a cron trigger is a
row and a heartbeat. Email-in is an inbound address to provision, MIME parsing, spam and
loop protection (an auto-reply to an auto-reply is a bill that grows on its own),
attachment handling, and a reply path — against `app/services/email/`, which is
**send-only today.** None of that shares code with the heartbeat, and bolting it on would
double the surface of this issue while leaving the cron half waiting on the mail half to
be safe. Cron first, cleanly; email-in as its own design, inheriting this issue's identity
and budget answers.

## 7. The run, end to end — and where it runs

```
Prefect (worker):  check_agent_triggers_flow          [IntervalSchedule(interval=60)]
                     └─ claim due triggers: SELECT … FOR UPDATE SKIP LOCKED,
                        advance next_fire_at, skip if last_run_id is non-terminal   §3
                     └─ for each: run_deployment(run_scheduled_trigger_flow, trigger_id),
                        timeout=0 — submit and return, do not await                 §4
                                    │  serializable arg only — an id (background-task skill)
                                    ▼
Prefect (worker):  run_scheduled_trigger_flow
                     └─ open worker session; load trigger (org, agent, subject, prompt, env)
                     └─ re-assert org budget  (assert_organization_within_budget)   §3
                     └─ build AuthContext from re-fetched membership, then
                        resolve_access(ctx, agent, AGENTS_RUN) — grants-aware, not role  §2
                        └─ refused → disable trigger, audit, notify admin, return    §2
                     └─ open or reuse the trigger's run-log conversation            §5
                     └─ answer, run = runner.execute(ctx, agent_id, prompt,
                                        surface=RunSurface.SCHEDULE,                 §0.1
                                        conversation_id=trigger.conversation_id, environment_id=…)
                     └─ set last_fired_at + last_run_id; return normally on
                        BUDGET_EXCEEDED or an authz refusal (never raise into retry) §3
```

The **fire** is durable — a Prefect deployment survives a restart, which is the whole
reason not to schedule in the API process. The **run** executes synchronously *inside* the
flow via `execute`, so the answer and its transcript are written before the flow returns;
nothing about the core result depends on a post-response in-process `spawn`, and therefore
nothing depends on the unfixed #11 drain gap. Any fire-and-forget the run path itself does
(a notification) is best-effort, exactly as it is for a chat run today — no better, no
worse.

## 8. Dependencies, and what stays out of scope

- **#11 (`drain()` unwired).** Sidestepped by running in the worker (§0.2, §7). Named
  because the best-effort notifications inherit its weakness, and because if any future
  part of triggers runs in-process it becomes load-bearing.
- **#15b (concurrent runs, stale budget baseline).** This plan bounds the *new* overlap it
  would introduce (a trigger against itself, §3) and does **not** fix the general race. A
  trigger firing beside a chat run can still both read one baseline. Dependency, not
  deliverable.
- **Cron expressions** (§1, §4) — interval first; cron + timezone as a follow-up.
- **Email-in** (§6) — its own issue.
- **A "run completed" notification** (§5) — immediate follow-up, not this issue.
- **A dedicated `TRIGGERS_MANAGE` permission / operator-wide trigger view** (§2) — ships on
  `AGENTS_RUN` via `resolve_access`; a separate view is separable.

## 9. Testing — the refusals, per `testing.md`

The platform layer is at 100% and most of this is new platform code (`app/services/`,
`app/repositories/`, the model, the flow). The behaviours worth naming because they are the
ones a happy-path implementation would miss:

- `test_a_trigger_against_an_exhausted_budget_is_refused_not_retried` — the issue's own
  line: run ends `BUDGET_EXCEEDED`, flow returns without raising, no second attempt.
- `test_a_trigger_whose_creator_left_the_org_is_disabled_not_run` — no membership →
  `is_active=False`, audit written, admin notified, no run row.
- `test_a_trigger_whose_grant_on_this_agent_was_revoked_is_disabled_not_retried` — creator
  keeps a role with `AGENTS_RUN: SHARED` but the per-resource grant is gone; the
  `resolve_access` pre-check refuses (a `role_has` check would not — Correction C), the
  trigger disables, and the authz refusal never raises into a Prefect retry.
- `test_a_trigger_does_not_overlap_itself` — a fire is skipped while `last_run_id` names a
  non-terminal run.
- `test_two_heartbeats_do_not_double_fire_one_trigger` — the `FOR UPDATE SKIP LOCKED`
  claim (integration, real Postgres — it is a locking claim, which a mock cannot prove).
- `test_a_triggered_run_is_stamped_schedule_and_appears_in_activity` — `RunSurface.SCHEDULE`
  on the run row, transcript appended to the trigger's run-log conversation.
- `test_a_trigger_cannot_be_created_against_an_agent_the_caller_cannot_run` —
  `resolve_access(AGENTS_RUN)` refuses; tenant isolation on every trigger read.

## 10. Documentation owed at implementation (not now)

Per the CLAUDE.md trigger map, the *implementation* — not this plan — will owe
`docs/governance.md` (a triggered run is a new way spend and approvals are incurred) and
`docs/concepts.md` (a new run surface and a new operational object beside the agent). A
design doc under `docs/design/` is engineering material for review, excluded from the site
by `exclude_docs: design/` in `mkdocs.yml`, so it neither needs a `nav` entry nor triggers
the docs-drift stop hook.

## Resolved in review — @DEENUU1, 2026-08-10

All five questions answered; the plan above is revised to match, and this section records
the outcome so the doc stands as the final design rather than a set of proposals.

1. **Creator-gone (§2).** **Auto-disable + audit + notify an admin.** Folded into §2, with
   the per-resource `resolve_access` pre-check that Correction C added.
2. **Spec vs. row (§1).** **Row. `SPEC_VERSION` stays at 8.** Confirmed — "keep it a row"
   was called the strongest argument in the plan; a trigger is not exported in a client's
   YAML, by design.
3. **Heartbeat vs. deployment-per-trigger (§4).** **Single heartbeat.** Confirmed.
4. **Output sink (§5).** **One conversation *per trigger*, not per fire.** Changed from the
   first draft on review — per-fire is an unbounded ~1440-conversations-a-day firehose; the
   run-log adds a `conversation_id` to the §1 schema.
5. **Email-in split (§6).** **Cron-only here; email is its own issue.** Confirmed — I file it
   once this lands, inheriting #44's identity and budget answers, and link it.

Two implementation corrections from the review, both folded in above because they change the
schema and the flow, not just the prose:

- **The no-overlap guard needs a column the table did not have** — `last_run_id` (§1), so
  the guard can find the previous run's status. Net-new, not inherited from the sync row.
- **"Copying `check_scheduled_syncs_flow` exactly" overstated it** — that flow neither locks
  rows nor submits-and-returns (`rag_tasks.py:244`), so the `FOR UPDATE SKIP LOCKED` claim
  (§3) and the `run_deployment` submit-and-return (§4) are new work. The plan now says it is
  inventing them.
