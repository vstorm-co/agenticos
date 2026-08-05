# Activity (`/runs`) — stage 1 plan

Companion to `activity-mockup.html`. Written for review before implementation, per #45.

## 1. The Logfire question — argued one way, decided the other

#45 proposed: *our data is the page, Logfire is the drill-down.* The first half stands and
is what the rest of this document builds. On the second half this section argued for
dropping the link entirely, and **review decided to keep it** (#206). Both halves are
recorded here rather than the losing argument being deleted: the four findings below are
why the link is expensive, and the decision accepts that cost with its eyes open.

**What that settles.** The run detail view built on our own rows is the drill-down, and it
ships either way — it is what works on a deployment that never set `LOGFIRE_TOKEN`, and for
the client agent whose traces we deliberately do not receive. The Logfire link is an
**addition to it, not a replacement**, and it is #206's work rather than this branch's,
because two of its three pieces are not page changes at all: a project slug becomes a
setting, and a slug on the spec is a `SPEC_VERSION` bump touching every stored spec and
every client's exported YAML.

Four findings, none of which the decision disputes:

1. **`logfire_trace_id` has never been written.** It is a parameter of
   `AgentRunner.finish()` (`app/services/agent_runner.py:603`) that no caller passes —
   not web chat, not the API, not a channel, not the embedded widget. The
   column is always `NULL`. The "link out" had no data behind it.
2. **Nothing stores a Logfire project URL.** `LOGFIRE_TOKEN` is a write credential
   (`app/core/config.py:43`); a deep link needs an organization and project slug, which
   would be a new setting.
3. **A redirected agent needs a *different* URL.** `ObservabilitySpec.token_secret_id`
   (`app/agents/spec.py:311`) exists precisely so a client's agent traces into the
   client's own project. Linking correctly would mean a project slug on the spec — a
   `SPEC_VERSION` bump touching every stored spec and every client's exported YAML.
   Disproportionate for a hyperlink.
4. **We already store, and already serve, what the trace would show.** `messages` carries
   `role`, `content`, `thinking`, `model_name`, `agent_version` and `tokens_used`;
   `tool_calls` carries `tool_name`, `args`, `result`, `status`, `duration_ms`.
   `MessageRead.tool_calls` (`app/schemas/conversation.py:113`) is already returned by
   `GET /conversations/{id}/messages`.

So the drill-down is a **run detail view built on our own rows**, and it is not conditional
on any of the above being fixed. Logfire keeps doing what it is for as well — tracing the
platform for whoever operates it — and #206 makes the link work. What this page refuses is
to *depend* on it: no panel here goes blank because a deployment has no Logfire.

## 2. Linking a run to its transcript

`messages` has no `run_id`, and a conversation holds many runs. Showing "the steps of
*this* run" is therefore not answerable today.

**Decision: add `messages.run_id`** — nullable FK, `ondelete="SET NULL"`, populated on the
write path of every surface. Exact from deployment forward.

Rejected: windowing messages between the run's `started_at` and `ended_at`. It needs no
migration and it is quietly wrong — two concurrent runs in one conversation interleave,
and a run that never set `ended_at` yields an empty window. A drill-down whose errors are
invisible to its reader is worse than one that admits a gap.

Rows written before the migration keep `run_id = NULL`. The detail view says so — *"steps
were not recorded for runs before <date>"* — rather than falling back to a time window.

### The migration is necessary and not sufficient

`run_id` links messages to runs; it does not create messages. Writing the transcript is the
caller's job, and only web chat on its success path does it in full:

| Surface | What a detail view could show today |
|---|---|
| web chat, run succeeded | everything — prompt, reasoning, tool arguments and results |
| web chat, run failed | the prompt only; the exception skips `persist_assistant_turn` (`agent_session.py:226`) |
| a channel bot's default agent | prompt and answer as text — no tool calls, model or version (`channels/router.py:126`, `:136`) |
| embed widget | nothing; a conversation row is created and left empty (`embed_session.py:142`) |
| `@mention` on a channel | nothing (`channels/router.py:176`) |
| API | nothing, even when the caller passes a `conversation_id` (`agents.py:368`) |
| a run resumed after an approval | nothing — `resume` replays through `_run`, which writes no messages (`agent_runner.py:838`) |

`tool_calls` rows are written in exactly one place in the repository — `app/services/agent.py:238`,
inside `persist_assistant_turn` — from a list only the streaming path fills. A non-streaming
surface has no access to them at all.

**Decision: #205 fixes the recording; this page does not.** Five write paths in the chat and
channel subsystems is not an Activity change, and folding it in would roughly double this
branch. So the detail view carries a **third** case beside *we recorded this* and *before the
migration*: **this surface does not record steps**, naming the surface. When #205 lands the
same view fills in with no frontend change.

A panel that is empty and silent is the failure this page exists to remove. A panel that is
empty and says why is the deliverable.

## 2a. Delegation — what #200 has already built, and the two things it breaks here

#200 (`feat/delegated-run-history`, open, based on `main`) adds `parent_run_id` and
`subagent_task_id` to `agent_runs`, and **every delegation writes its own run row**. The rest
of this plan was written without it, which made the estimate look larger than it is:

| #200 already ships | What this plan priced |
|---|---|
| `?run=<id>` and `FocusedRun` — one run, the delegations under it, a link up to the parent, a 404 told apart from a failed request | the run detail view, as the central new deliverable |
| the Runs figure reading the server's `total` from an unnarrowed `useRuns()`, captioned that delegations are counted in their parent | §3 item 5, the same fix |
| `RunTable` extracted to `components/runs/run-table.tsx` with its own test | part of §9's "three tabs as separate components" |
| `ApprovalRead.subagent_name` and `subagent_agent_id`, rendered by `ApprovalDelegate` with an integration test — the name always, the link only with `agents:view` | §7's claim that `ApprovalRead` carries neither |

Two things genuinely bite, and both are this page's to answer:

**The list is top-level only.** `list_runs` gains `parent_run_id` and `include_delegations`,
defaulting to top-level. So every filter in §6 narrows a table that **does not contain
delegated runs**, and a delegation is reached with `?run=` from its parent rather than as a
row of its own. The table says so rather than leaving a reader to infer it from a count that
does not add up.

**`environment_id` is deliberately NULL on a delegated run.** A delegate's version comes from
a pin, not from an environment resolving it, and #200's test asserts the column is never
written. So the Environment filter **silently drops every delegation** the moment somebody
narrows to `production` — the failure mode this page exists to remove, in a filter this page
is adding. The filter states what it does with a run that has no environment, and §9 verifies
it.

**The version strip has to pick a side of `include_delegations`, and say which.**
`sum_cost_since` and `cost_breakdown` carry that switch with opposite correct answers: the
organization's bill *excludes* child rows, because the parent's `cost_usd` already contains
them; one agent's month *includes* them, because a delegate's row is the only record of its
own spend. "Cost per run" per version is the second question sitting inside the first, so it
double-counts unless it chooses.

**The approval card gains a delegate line**, under the tool name, from `subagent_name`.
Without it, building the Approvals tab to this mockup deletes `ApprovalDelegate` and its test,
and the queue approves blind on exactly the rows where the actor is the fact that decides the
answer — two specialists both calling `send_email` produce two rows with the same tool name and
nothing to choose between them. In a delegation what is being approved is often more
consequential than the agent the approver thinks they are talking to.

## 3. The six items in #45, reassessed against the code

| # | #45 said | Verdict |
|---|---|---|
| 1 | A run does not link to its trace — *smallest change, largest gain* | **Split.** It was the largest item, not the smallest (§1), so the two halves ship separately: the drill-down is a run detail view on our own rows, here; the trace link is #206. #200 has already built the detail view — see §2a |
| 2 | Cost rendered without its caveat | **Already shipped** — `runs/page.tsx:214` marks `cost_is_partial`. Remaining work is honesty of presentation: a bare `+` in a `title=` attribute is invisible to a screen reader and easy to miss. Becomes a visible marker with text |
| 3 | An approval has no context | **Half shipped** — `tool_args` is rendered in full (`runs/page.tsx:133`). Missing is the agent and the triggering user, and `ApprovalRead` carries neither. Backend change, not UI |
| 4 | Filtering is agent-only | **Do it.** `agent_run_repo.list_runs` accepts only `agent_id` |
| 5 | Pagination | **Do it.** What it hides — the "Runs" figure rendering `runs.length`, at most 50, as the organization's run count — is **#198**, a filed bug that #200 already fixes with the server's `total`. This design closes #198 rather than re-deriving it |
| 6 | `failed` and `budget_exceeded` look alike | **Already shipped** — different tone and the label "stopped by budget" (`components/agents/status-badge.tsx:53`). No work |

## 4. Who sees this page — all seven identities, answered from `ROLE_PERMS`

The sidebar entry gates on `runs:view`, so presence is decided by the permission
catalog (`app/core/permissions.py`), not per screen:

| Identity | `runs:view` | `approvals:decide` | What they get |
|---|---|---|---|
| app admin | everything — `is_app_admin` holds every permission at `Scope.ALL` | — | the whole page, plus the organization scope (§6a) |
| owner | ✓ | ✓ | the whole page |
| admin | ✓ | ✓ | the whole page |
| operator | ✓ | ✓ | the whole page — this page *is* their job |
| builder | ✓ | ✗ | Runs + Spend; no Approvals tab, no queue figure |
| member | ✗ | ✗ | **nothing — the sidebar entry is absent** |
| viewer | ✗ | ✗ | **nothing — the sidebar entry is absent** |

There is no stripped-down Activity for member and viewer; inventing one would be
inventing a screen the permission model says does not exist.

### The one question this plan asks to be decided: member and viewer

A catalog change, not a page change, so it needs a decision here rather than a silent
default. **The recommendation: yes for a member, at `Scope.OWN`. No for a viewer, ever.**
And it is the same reasoning #37 already ruled on, which is why it should not be
re-litigated per page:

- A **member** holds `agents:run` at `Scope.SHARED`, so a member *produces* runs. They
  can start one, be told it is waiting on an approval, and then see neither the run nor
  the approval. #37's decision 2 gives a member their own `scope=own` analytics for
  exactly this reason — including *"why is my agent stuck"* — so the dashboard already
  shows a member their own activity while Activity denies it. That is the disagreement
  worth closing.
- A **viewer** holds no `agents:run` at all. Their run history would be built from rows
  they can never produce: a permanently, structurally empty page. #37 gates its activity
  cards on `agents:run` for this reason, and the same gate answers here. **A viewer's
  Activity stays absent — not empty, absent.**

**The trap, and why this is not a one-line catalog edit.** `require(...)` passes when a
permission is held at *any* scope above `NONE` (`AuthContext.has` → `scope_for(...) is
not Scope.NONE`, `app/core/permissions.py:354`). `resolve_access` is what reads a scope, and it reads it
**per row**, against an `OwnedResource` — there is no row in a collection request. So
adding `Perm.RUNS_VIEW: Scope.OWN` to member and stopping there does not narrow anything:
the member calls `GET /runs` and receives **the whole organization's runs**, and because
`/spend` is gated on the same permission, the organization's cost breakdown with it. A
scope that nothing enforces is a scope that leaks.

Doing it correctly means the collection routes read the caller's scope and narrow the
query themselves:

- `GET /runs` — when `ctx.scope_for(Perm.RUNS_VIEW)` is `Scope.OWN`, force
  `user_id = ctx.user_id` in the repository call rather than accepting it as a filter.
  The `user_id` parameter §7 already prices is the *filter*; this is the *floor*, and a
  filter a caller can widen is not a floor.
- `GET /spend` — an own-scoped caller gets their own spend or nothing. Returning the
  organization's total to somebody scoped to their own rows is the same leak with a
  dollar sign on it.
- The page a member reaches is the Runs tab alone: no Approvals tab (no
  `approvals:decide`), and the run detail view scoped the same way.

**Cost:** the two route-level scope floors above, plus two refusal tests — a member
seeing exactly their own rows, and a member *not* seeing a colleague's run or the
organization's spend. Small, and worth doing properly or not at all.

**Out of scope for #45 unless DEENUU1 wants it in**, and it is genuinely severable:
everything else in this plan ships unchanged either way.

**The Approvals tab 403s for a Builder today.** `builder` holds `runs:view` but not
`approvals:decide`, and `GET /approvals` is gated on `APPROVALS_DECIDE`. A Builder
lands on Approvals — the default tab — and gets a 403 that the page currently renders
as *"Nothing waiting"*, plus a *"Waiting on a person: 0"* figure. Both are false.

Worse, fixing "empty must not look like failed" without fixing this turns a silent lie
into an error banner on the landing tab. So: **the Approvals tab is absent without
`approvals:decide`, the query is not issued, and the default tab becomes Runs.** Absence,
not a 403 — `.claude/rules/frontend.md:44`.

**Two of the three hooks cannot report a failure.** `useApprovals` and `useSpend` do not
return `error` at all (`hooks/use-runs.ts`). The empty-versus-failed deliverable is a hook
change before it is a component change.

**The page has no i18n.** Zero `useTranslations`, and no namespace for it in `en.json` or
`pl.json` — the existing `agent-filter.integration.test.tsx` already mocks `next-intl` for
a page that never calls it. Both locales get a namespace.

## 5. Does this page consume #37's aggregation endpoint? No

Activity is rows with filters, not analytics. The only aggregate it renders is `/spend`,
which already exists and already answers by-provider, by-key and by-agent. The correct
move is to **extend `/runs` filters**, not to wait on `GET /stats/usage`.

Recorded here so it is not re-decided halfway through stage 2. If #37 later ships
`/stats/usage`, this page has no reason to call it.

The two pages still agree on the **dimensions**, deliberately. The review of #149
fixed `/stats/usage`'s `group_by` vocabulary "with #45 in the room" —
`day | surface | agent | version | user | status | model | exposure | environment` —
and left `exposure` and `environment` to land together with this page. Activity
consumes those dimensions as `/runs` filter parameters over rows, not as aggregates:
same columns, same vocabulary, different endpoint. That is also why the dashboard's
widgets can use Activity as their "see all" destination (§6) — the two pages narrow
by the same things.

**One deliberate exception:** the version strip (§6). When the runs tab is narrowed
to an agent, a per-version summary renders above the table — and it is fed by
`GET /stats/usage?group_by=version`, which #37 builds for the dashboard's
version-to-version card. Consuming it here is the sharing the fixed vocabulary
exists for; growing a second version aggregate on `/runs` would be the exact
failure #149 warned about. Everything else on the page reads rows.

## 6. Filters — owned by the tab whose columns they narrow

A single global row was the first draft, and it lied twice: **status is a runs
column** — the queue and the spend have no status — and neither `/approvals` nor
`/spend` could honour a date range or an agent filter anyway. A bar that visibly sits
above everything but actually scopes one query is a bar somebody trusts and is misled
by. So each tab owns its own filters, in the dashboard demo's (#37) dropdown grammar so
the two pages read as one product:

- **Runs** — a date range (presets: Today / 7 / 30 / 90 days / This month / Last month,
  plus a two-month calendar for a custom range), **Status** and **Surface** as
  multi-select checkbox dropdowns (no selection means *every* value, and the set can
  never be emptied to nothing), **Channel**, **Agent**, **Triggered by** and
  **Environment** as single-selects with an explicit "Any" row, and **Version**, which
  appears once an agent is picked and offers that agent's versions (switching agents
  drops the pick — a v3 under another agent is a different v3). Channel is
  `exposure_id`, not surface: surface says *slack*, the channel says *which* Slack
  workspace, and an org with three bots needs the second. Environment is
  `environment_id`, so staging noise can be kept out of what a steward reads — staging
  rows also wear a pill in the table. All three came out of #149's review, which fixed
  the dimension vocabulary with this page in the room. An active filter tints its
  button; a **Clear filters** link appears only when something is narrowed. The bar
  renders inside the Run history card in every state — an empty result whose way out
  (Clear) has vanished is a dead end.
- **The surface list is the honest one.** Two of the seven `RunSurface` values are dead —
  defined and never assigned — and neither is offered. `SCHEDULE` is the known one.
  `PLAYGROUND` is the second and less obvious: it is only the default of `execute()`'s
  `surface` parameter (`agent_runner.py:710`), and every one of the four call sites passes
  a surface explicitly, so no row is ever stamped with it. A filter option that can only
  ever return nothing is a filter that makes a reader doubt the data, not the filter.
  `embed` and `mattermost` are offered but flagged: today an embedded run is stamped
  `web` (`embed_session.py:164`) and a Mattermost mention falls through to `api`
  (`channels/mentions.py`), so those two only return truth after the recording widening
  #149's review settled — priced in §7 and shared with #37's stage 2, whichever lands
  first (`e76af9d` on that branch already carries it).
- **"Triggered by" is who a run *ran as*, which is not always who asked.**
  `agent_runs.user_id` is `ctx.user_id` (`agent_runner.py:449`), and for an embedded widget
  that is the widget's **owner**: the visitor is anonymous and has no row anywhere. The
  column is right and the bare label would be a lie, so the detail view names whose
  identity it is. It also decides what an own-scoped member would see if §4 is accepted —
  their widget's traffic is their own rows.
- **The version strip — the builder's feedback loop, where the builder already
  lands.** `?agent=` is the hand-off from the agent page, so when the runs tab is
  narrowed to an agent, a strip of per-version chips renders above the table: runs,
  success rate, p50, cost per run, the current version marked. Clicking a chip filters
  the table to the runs behind the number — the summary and its evidence on one
  screen, which is what "did v4 actually behave better than v3" needs to be
  answerable rather than arguable. Fed by #37's `group_by=version` (§5's one
  exception); absent until an agent is picked, so the default page stays a rows page.
- **Approvals** — a **Triggered by** filter and a sort (oldest ↔ newest). Oldest first
  stays the default, because the queue drains from the top. `GET /approvals` today has
  only `skip`/`limit` and a fixed oldest-first order — the filter and the sort are
  priced in §7. Age is a real dimension of this queue, not decoration:
  `ApprovalStatus.EXPIRED` is defined and never assigned (**#178**), so
  nothing ages out and the oldest row can be from months ago. The queue does not
  pretend otherwise — a call waiting past a day wears the loud tone, and the figure up
  top names the oldest wait.
- **Approvals has two views: the queue, and the record.** A **Waiting ↔ Decided**
  toggle. Decided rows show the decision, who made it, and how long the call sat
  first, plus a median time-to-decision line — the operator's inbox becomes the
  steward's accountability trail with one click, and no new page. Deliberately
  **no buttons** on a decided row: a second decision on a decided approval is one of
  the things this platform refuses, and the view says so. `GET /approvals` serves the
  pending queue only today (`list_pending`), and the decider arrives as a bare UUID —
  the `status` param and the decider's name are priced in §7.
- **Spend** — the **same date-range control as Runs, 1:1** (presets + the two-month
  calendar): one component, one muscle memory. `GET /spend` today takes `?days=1..365`,
  so the "last N days" presets map directly; "This month", "Last month" and a custom
  range need a `from`/`to` variant — priced in §7. Month-to-date ignores the range and
  says so where it renders. The tab also says **how much of the figure is a fact**:
  "N of M runs have no metered price — every total below is a floor", aggregated from
  `agent_runs.cost_is_partial` (stored per run today, not yet returned as a count —
  priced in §7). A spend page that renders floors as facts is the `title=`-attribute
  bug from §3 again, one level up.
- **"By agent" is a tile per agent, telling two truths apart.** Each tile leads with
  what the agent spent in the selected range (with the floor marker when a cost is
  partial), and underneath it a cap meter — the agent against its own
  `AgentSpec.budget.monthly_usd`, amber past 70%, loud past 90%, "no monthly cap"
  said plainly. Two windows on one tile, visibly separate: the number follows the
  range control, the meter is calendar-aligned like the caps themselves, and the
  card's footer names both. This is the per-agent *cause* under the org-level figure
  the month KPI shows — the dashboard's headroom card features the top agents; the
  full set lives here, where the steward investigating spend already is. Priced
  in §7.
- The three **figures** stay above the tabs and follow no tab's filters; each names its
  own window in its caption (calendar month · the runs period · right now) and is a
  door — clicking a figure opens its tab. The month figure also carries the **budget**
  it is spending against — "63% of the $500 monthly budget", amber past 70%, loud past
  90% — because the outcomes on this page draw `budget_exceeded` (the symptom) and
  nothing else showed the cause. Nothing new to build:
  `organizations.monthly_budget_usd` is already on `GET /orgs/{org_id}`, and an org
  that never set a cap gets the plain caption.
- Filter state lives in the URL, so a filtered view can be linked and a reload keeps
  it. The URL is also the contract the dashboard deep-links into: #149's review fixed
  the rule that every widget's "see all" points at a page that already exists, and for
  runs and approvals that page is this one — "Recent failures" lands here with
  `status=failed,budget_exceeded` pre-filled, the approvals card lands on the Approvals
  tab. Which is why the `status` parameter takes a **list**, not a single value.

`?agent=` stays the Builder's hand-off and pre-fills the runs agent filter rather than
bypassing it, so the notice and the way out keep working
(`runs/agent-filter.integration.test.tsx` still passes).

The Runs table copies `admin/conversations/page.tsx` — `DataTable`, sortable columns, page
size selector, full i18n. The pattern exists; this page should not invent a second one.

**Considered and left out**, so the boundary is visibly held rather than forgotten:
a **spend-by-person table** (it is the surveillance table #37's decision 3 refuses —
"a count, not a table of names" — and a per-person league table of cost is that table
with dollars on it); **saved filter views** (the URL already carries every filter, and
per-user preferences are out of #37's v1 for the same reason they would be out here);
**CSV export** (real want, own decision — an export endpoint has its own tenancy and
size questions, and folding it in here would bury them).

## 6a. The app admin and the organization scope

`is_app_admin` holds every permission and may set **any** organization active without a
membership (`deps.py:get_auth_context`), so the app admin already reaches any single
organization's Activity through the sidebar switcher. The mockup adds, for the app
admin only, the same **organization divider** the dashboard demo (#37) draws — a
display-font label, a plain select, a one-line note — rather than a highlighted bar of
its own, so the two pages disagree nowhere. The select lists every organization plus
"All organizations":

- **One organization** — the same page everyone else sees, scoped to that org. Feeding
  it is `GET /admin/organizations` for the picker; the data calls are unchanged.
- **All organizations** — the deployment-wide view. Each run row and each parked
  approval carries an *Organization* column, the agent/user pickers widen
  accordingly, and the Spend tab gains a **By organization** breakdown — which tenant
  the deployment's money went to, the one cut only this mode can draw. **This mode
  does not exist in the API**: `/runs`, `/approvals` and `/spend` all scope to
  `ctx.organization_id`. It needs an explicit `organization_id`-optional,
  app-admin-only variant — priced in §7 and honestly droppable from stage 2 if
  DEENUU1 prefers: the per-org picker alone already covers "look at a client's
  Activity without joining their org", and the By organization card drops with it.

**The budget percentage is a member's figure, and the app admin is not one.**
`GET /orgs/{org_id}` calls `get_for_user` (`organization.py:34`), so it 404s for an
organization the admin never joined, and `AdminOrganizationRead` carries no
`monthly_budget_usd`. So in both app-admin modes the month figure renders as an **amount
with no percentage** unless the app-admin response grows the field. Said rather than
faked: a percentage of a cap nobody read is a number somebody would act on.

The divider is absent for every non-app-admin identity; their Activity is the active
organization, and the sidebar switcher owns that.

## 7. Backend work this implies, so the estimate is honest

| Change | Cost |
|---|---|
| `messages.run_id` — column, FK, and the write path where there is one | Alembic migration + the chat write path (`persist_user_turn` / `persist_assistant_turn`). The surfaces that write no messages at all are #205's, not this branch's — §2 |
| `list_runs` — `status` (a **list**: `failed,budget_exceeded` is also #37's Recent-failures query), `surface`, `user_id`, `started_from`, `started_to`, `environment_id`, `exposure_id`, `agent_version_id` | Repository + route + `AgentRunList` unchanged; every column already on the run row |
| Surface recording widening — `RunSurface.EMBED` stamped by `embed_session.py`, `mattermost` added to `_SURFACES` in `channels/mentions.py` | Two small service changes. Shared with #37's stage 2 — whichever branch lands first ships it, the other inherits |
| `ApprovalRead` — agent name and triggering user are the **remaining** gap; the **delegate** is handled by #200 (`subagent_name`, `subagent_agent_id`) | Schema + approval service join. No migration. Do not rebuild the delegate half — §2a |
| `/approvals` — `user_id` filter, `sort` (oldest/newest; oldest stays the default) | Repository + route. No migration |
| `/approvals` — the decided view: a `status` param (today the route serves `list_pending` only), and the decider's **name** (`ApprovalRead` already carries `decided_by_user_id` and `decided_at` — a bare UUID, the same class of gap as the missing agent name) | Repository + route; the name rides the same `ApprovalRead` join as the row above. No migration |
| Version strip — per-version runs, success, p50, cost under an agent filter | Nothing new here — the second consumer of #37's `/stats/usage?group_by=version` |
| `/spend` — accept `from`/`to` alongside `days`, so the range control is honest | Route + `agent_runner` cost queries |
| `/spend` — a partial-cost run count, so "every total below is a floor" has a number | Aggregate `cost_is_partial` in the existing cost query. No migration |
| `CostByAgent` — agent **name** alongside `agent_id`, **one row per agent** (today `cost_breakdown` splits an agent across its models), plus the agent's **monthly cap** and **month-to-date** so the cap column is honest | Schema + join + grouping; cap from the spec's `budget.monthly_usd`, MTD from the query `/spend` already runs. No migration |
| `AgentRunRead` — `conversation_id`, so the detail view has something to open | Schema only; the column is already on the run row. No migration |
| **The detail view's own read** — one run's messages and tool calls, under `RUNS_VIEW` | **A new route, not a reuse.** `GET /conversations/{id}/messages` cannot serve this: it filters `Conversation.user_id == the caller` deliberately (`conversation.py:347` — *"`organization_id` keeps this out of another tenant's transcript; `user_id` keeps it out of a colleague's"*), so an owner opening a colleague's run gets a 404. Embed and channel conversations carry `user_id = NULL` and are unreadable by anyone through it. Run-scoped route + repository read + a cross-tenant refusal test. **Relaxing the conversation endpoint instead is not on the table** — its docstring records that as a bug already fixed once |
| Budget context on the month figure | `GET /orgs/{org_id}` serves it **for a member**. It calls `get_for_user` (`organization.py:34`), so an app admin who never joined the organization gets a 404, and `AdminOrganizationRead` carries no `monthly_budget_usd`. For those organizations the month figure renders as an amount with no percentage, unless the app-admin response grows the field — §6a |
| "All organizations" mode (§6a) — `organization_id`-optional `/runs`, `/approvals`, `/spend`, refused for anyone but an app admin | Route + repository on all three; the one honestly droppable line here |

Everything else is frontend.

## 8. Filed separately, found while writing this

- **#205 — five of seven surfaces record no transcript.** The matrix is in §2. It decides
  what this page can show and what it has to admit, so it is the one item here that
  changes a deliverable rather than sitting beside it. Filed rather than folded in, and
  the detail view is built so that #205 landing fills it in without a frontend change.
- **#206 — `AgentRunRead.logfire_trace_id` is documented as *"Deep-link into the full
  trace"* and is always `null`** (`app/schemas/agent_run.py:29`), and `GET /runs/{run_id}`
  repeats the promise in a docstring the reference docs publish (`runs.py:51`). The public
  API says where to look and hands over nothing to look with. §1 read that as grounds for
  removing the field; review decided to **wire it** instead, so #206 owns the whole chain —
  the trace id at every `finish()` call site, the project slug as a setting, and the slug on
  the spec. Independent of this page either way: nothing here reads the field, and nothing
  here waits on it.
- **`RunSurface.PLAYGROUND` is dead, exactly like `SCHEDULE`** (§6) — a value nothing
  assigns, on a column the API returns and a filter would otherwise offer. It is only the
  default of `execute()`'s `surface` parameter (`agent_runner.py:710`) and all four call
  sites pass one explicitly. #207 covers `SCHEDULE` and #178 covers the third of these,
  `ApprovalStatus.EXPIRED`. **Recommendation: fold `PLAYGROUND` into #207** rather than open
  a fourth issue — same enum, same file, and the decision is the same one either way (assign
  it or delete it).

A second find — "Spend by agent" listing model labels because `CostByAgent` carries no
name (`runs/page.tsx:277`) — started here, but the mockup shows it fixed and the change
is one join, so it moved into scope: §7 prices it.

## 9. What stage 2 is verified by

- a test that mocks a 502 per tab and asserts the **error** state, not the empty one
- an integration test proving Approve/Reject and the Approvals tab are **absent** without
  `approvals:decide`
- an integration test proving the run count is `total`, not the length of the first page
- the new `list_runs` filters proven against a real database: a staging run absent when
  `environment_id` narrows to production, a `status` list returning both `failed` and
  `budget_exceeded` rows, a version filter returning only the rows that executed it
- **a delegated run is not lost when `environment_id` narrows to production** (§2a — the
  column is deliberately never written on one), and the filter says on screen what it does
  with a run that has no environment
- **the version strip does not double-count**: one agent's per-version cost with
  `include_delegations` on, asserted against the same runs summed the organization's way,
  and the chip naming which of the two it is
- the decided view proven: a decided approval renders its decider and is refused a
  second decision; the pending queue and the decided list never share a row
- the three tabs land as separate components — the 335-line page is already over the
  ~100-line guidance, and #45 counts the split as part of the work, not extra
- `messages.run_id` covered by an integration test against a real database: two runs in
  one conversation, each detail view showing only its own steps
- the detail read proven to be authorized rather than owned: an owner opening a
  **colleague's** run gets its steps, the same request for another tenant's run is
  refused, and the conversation endpoint one route over is left exactly as strict as it
  is today
- a run on a surface that records nothing renders the third case of §2, naming the
  surface — asserted by a test, because "empty" and "not recorded" are the same pixels
  and this page exists to stop that
- `bun run type-check && bun run lint && bun run test:run` clean
- `make check` clean
