# Activity (`/runs`) — stage 1 plan

Companion to `activity-mockup.html`. Written for review before implementation, per #45.

## 1. The Logfire question — overturned, in favour of something stronger

#45 proposed: *our data is the page, Logfire is the drill-down.* The first half stands.
The second half is dropped. **This page does not reference Logfire at all.**

Four findings, in the order that matters:

1. **`logfire_trace_id` has never been written.** It is a parameter of
   `AgentRunner.finish()` (`app/services/agent_runner.py:406`) that no caller passes —
   not the playground, not web chat, not the API, not a channel, not a schedule. The
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
   `MessageRead.tool_calls` (`app/schemas/conversation.py:92`) is already returned by
   `GET /conversations/{id}/messages`.

So the drill-down is a **run detail view built on our own rows**. This is strictly more
available than a Logfire link: it works on a deployment that never set `LOGFIRE_TOKEN`,
and it works for the client agent whose traces we deliberately do not receive.

Logfire keeps doing what it is for — tracing the platform for whoever operates it. It is
not a dependency of an operator-facing page.

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

## 2a. Delegated runs — the page is built on a table that now holds two kinds of row

This section was added after the rest of the plan, reconciling it with #200
(`feat/delegated-run-history`), which lands a second kind of `agent_runs` row and was open
while §1–§9 were being written. Four of the items priced below are already built there.

**A delegation writes its own run row.** `parent_run_id` and `subagent_task_id` join the
run row, and `record_delegated_run` writes a delegated run *finished* — it has a status, a
cost and both ends of its window before any row exists. So run history stops being a list
of one thing, and the two must not be read the same way: **a parent's `cost_usd` already
contains its children's**, which is why `sum_cost_since` counts only
`parent_run_id IS NULL` and why summing a page of rows bills the organization twice for
one request.

### What #200 already ships, so this plan should stop pricing it

| This plan said | #200 |
|---|---|
| The run detail view is the central new deliverable (§1, §3 item 1) | Built: `?run=<id>` and `FocusedRun`, which shows one run plus the delegations it made, links **upwards** to the parent, and tells a 404 apart from a failed request |
| The "Runs" figure renders `runs.length`; fix it to `total` (§3 item 5) | Done, from an unnarrowed `useRuns()`, with a caption saying delegations are counted in their parent |
| The three tabs land as separate components (§9) | `RunTable` is already extracted |
| `ApprovalRead` carries no agent name and no triggering user (§3 item 3) | Adds `subagent_name` and `subagent_agent_id`, rendered by `ApprovalDelegate` with its own integration test. The agent name and triggering user remain this plan's work |

### What this plan has to decide, because #200 does not

**The list is top-level only.** `list_runs` gains `parent_run_id` and
`include_delegations`, defaulting to top-level rows — which is what makes the count and the
cost column agree with the month-to-date figure beside them. So the Run history table draws
top-level runs, and a delegated run is reached by naming it, never by paging to it. The
table says so once rather than leaving a reader to wonder where the fan-out went.

**A delegated run carries no environment.** `record_delegated_run` leaves `environment_id`
NULL deliberately: that column says which environment resolved the version this run
answered with, and a delegate's version comes from a pin. The top-level list is therefore
unaffected — but **every view that deliberately includes delegations loses them the moment
an environment narrows the query**, and there are two on this page:

- the **version strip** (§6), when the agent selected is one that other agents delegate
  to — all of its runs are delegated rows;
- the **per-agent spend tile** (§6), because `cost_breakdown` includes delegations on
  purpose: a delegate's rows are the only record of its own spend.

Both either leave the environment filter out of their query or say that a delegated run has
no environment. Silently dropping the rows is the option this section exists to refuse.

**The version strip has to pick a side of `include_delegations`, and say which.** Runs,
success rate and p50 are per-version questions and want the delegate's own rows; cost per
run summed across both kinds counts a delegation twice, once inside its parent. The strip's
caption names the choice, the way #200's Runs figure names its own.

**The run detail view gains a second half.** A parent's transcript does not contain what its
delegate did, so a run that delegated shows the delegations beneath its own steps, each
linking to its own detail — and a delegated run links up to the run it came from, because
that is where its cost was charged. This is `FocusedRun`'s shape; the detail view here
should be the same component's home rather than a second answer to the same question.

**The approvals queue names the delegate.** A gated tool inside a delegation writes its
approval against the *parent's* run, so two specialists both calling `send_email` produce
two rows with the same tool name and nothing to choose between them. The delegate is the
fact that decides the answer, and it belongs beside the tool name rather than a click away.

## 3. The six items in #45, reassessed against the code

| # | #45 said | Verdict |
|---|---|---|
| 1 | A run does not link to its trace — *smallest change, largest gain* | **Replaced.** It was the largest item, not the smallest (§1). Ships as the run detail view instead — **which #200 has already built** as `?run=` plus `FocusedRun` (§2a). What is left here is the transcript inside it, off `messages.run_id` |
| 2 | Cost rendered without its caveat | **Already shipped** — `runs/page.tsx:219` marks `cost_is_partial`. Remaining work is honesty of presentation: a bare `+` in a `title=` attribute is invisible to a screen reader and easy to miss. Becomes a visible marker with text |
| 3 | An approval has no context | **Half shipped** — `tool_args` is rendered in full (`runs/page.tsx:141`), and #200 adds the **delegate** that asked (§2a). Missing is the agent and the triggering user; `ApprovalRead` carries neither. Backend change, not UI |
| 4 | Filtering is agent-only | **Do it.** `agent_run_repo.list_runs` accepts only `agent_id` |
| 5 | Pagination | **Do it.** The figure it hides is already fixed by #200 (`total`, top-level only, captioned) — what remains is #198, filed: the count reads *all time* while the spend beside it reads one calendar month, so the two invite a comparison that is wrong by however old the organization is. Each figure names its own window, and this work closes #198 |
| 6 | `failed` and `budget_exceeded` look alike | **Already shipped** — different tone and the label "stopped by budget" (`components/agents/status-badge.tsx:41`). No work |

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
not Scope.NONE`, `deps.py:390`). `resolve_access` is what reads a scope, and it reads it
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
  rows also wear a pill in the table. It narrows the top-level list safely; where it must
  **not** be applied is any query that deliberately includes delegations, because a
  delegated run carries no environment at all (§2a). All three came out of #149's review,
  which fixed the dimension vocabulary with this page in the room. An active filter tints its
  button; a **Clear filters** link appears only when something is narrowed. The bar
  renders inside the Run history card in every state — an empty result whose way out
  (Clear) has vanished is a dead end.
- **The surface list is the honest one.** The dead `RunSurface.SCHEDULE` — defined,
  never assigned — is not offered. `embed` and `mattermost` are offered but flagged:
  today an embedded run is stamped `web` (`embed_session.py`) and a Mattermost mention
  falls through to `api` (`channels/mentions.py`), so those two options only return
  truth after the recording widening #149's review settled — priced in §7 and shared
  with #37's stage 2, whichever lands first.
- **The version strip — the builder's feedback loop, where the builder already
  lands.** `?agent=` is the hand-off from the agent page, so when the runs tab is
  narrowed to an agent, a strip of per-version chips renders above the table: runs,
  success rate, p50, cost per run, the current version marked. Clicking a chip filters
  the table to the runs behind the number — the summary and its evidence on one
  screen, which is what "did v4 actually behave better than v3" needs to be
  answerable rather than arguable. Fed by #37's `group_by=version` (§5's one
  exception); absent until an agent is picked, so the default page stays a rows page.
  **Two things it has to settle about delegation** (§2a): it counts a delegate's own
  rows — otherwise an agent used only as a delegate has no strip at all — which means it
  cannot carry the environment filter, and its **cost per run** must exclude delegated
  rows or it counts a delegation twice, once inside the parent it was charged to. The
  caption says which, the way #200's Runs figure does.
- **Approvals** — a **Triggered by** filter and a sort (oldest ↔ newest). Oldest first
  stays the default, because the queue drains from the top. `GET /approvals` today has
  only `skip`/`limit` and a fixed oldest-first order — the filter and the sort are
  priced in §7. Age is a real dimension of this queue, not decoration:
  `ApprovalStatus.EXPIRED` is defined and never assigned (found in #149's review), so
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
- **By provider and By key are blocked on #170, and this tab is where it shows.** Both
  cards are `spend_by_provider` and `spend_by_key` verbatim, and neither carries the
  `parent_run_id IS NULL` filter that `sum_cost_since` has — so on any deployment using
  delegation they render inflated vendor and key totals *next to* a correctly computed
  month-to-date, and the page fails to reconcile against itself. A breakdown totalling
  more than the total above it is exactly the failure that default exists to prevent, so
  this tab either waits for #170 or says on screen that the two cards over-count a
  delegation. Not silently.
- **"By agent" is a tile per agent, telling two truths apart.** Each tile leads with
  what the agent spent in the selected range (with the floor marker when a cost is
  partial), and underneath it a cap meter — the agent against its own
  `AgentSpec.budget.monthly_usd`, amber past 70%, loud past 90%, "no monthly cap"
  said plainly. Two windows on one tile, visibly separate: the number follows the
  range control, the meter is calendar-aligned like the caps themselves, and the
  card's footer names both. This is the per-agent *cause* under the org-level figure
  the month KPI shows — the dashboard's headroom card features the top agents; the
  full set lives here, where the steward investigating spend already is. Priced
  in §7. **This tile is the one place that counts delegated rows on purpose** —
  `cost_breakdown` includes them because a delegate's rows are the only record of its own
  spend, and "the researcher cost $40 this month" is unanswerable without them. Which is
  also why the tile cannot carry the environment filter (§2a), and why its total is
  deliberately not the same question as the org figure above it: the footer already names
  two windows and now names two scopes.
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

The divider is absent for every non-app-admin identity; their Activity is the active
organization, and the sidebar switcher owns that.

## 7. Backend work this implies, so the estimate is honest

**Four rows below shrank when #200 landed its branch** — the run detail view, the `total`
fix, the component split and the delegate on `ApprovalRead` (§2a). They are marked rather
than deleted, so the estimate reads as a corrected one instead of a smaller claim.

| Change | Cost |
|---|---|
| `messages.run_id` — column, FK, write path on every surface | Alembic migration + `agent_runner` and the chat write path |
| `list_runs` — `status` (a **list**: `failed,budget_exceeded` is also #37's Recent-failures query), `surface`, `user_id`, `started_from`, `started_to`, `environment_id`, `exposure_id`, `agent_version_id` | Repository + route + `AgentRunList` unchanged; every column already on the run row. Composes with #200's `parent_run_id` / `include_delegations`, which already default the list to top-level |
| The run detail view, `?run=` and the delegation tree | **Already built** — #200's `FocusedRun`, `useRun`, `useDelegatedRuns`. What is left is the transcript inside it, off `messages.run_id` |
| The "Runs" figure as `total`, top-level only | **Already built** — #200. What is left is #198: the window it counts (§3 item 5) |
| `ApprovalRead` — the delegate that asked | **Already built** — #200's `subagent_name` / `subagent_agent_id` and `ApprovalDelegate`. **Do not rebuild the approval card without it** |
| Surface recording widening — `RunSurface.EMBED` stamped by `embed_session.py`, `mattermost` added to `_SURFACES` in `channels/mentions.py` | Two small service changes. Shared with #37's stage 2 — whichever branch lands first ships it, the other inherits |
| `ApprovalRead` — agent name, triggering user | Schema + approval service join. No migration |
| `/approvals` — `user_id` filter, `sort` (oldest/newest; oldest stays the default) | Repository + route. No migration |
| `/approvals` — the decided view: a `status` param (today the route serves `list_pending` only), and the decider's **name** (`ApprovalRead` already carries `decided_by_user_id` and `decided_at` — a bare UUID, the same class of gap as the missing agent name) | Repository + route; the name rides the same `ApprovalRead` join as the row above. No migration |
| Version strip — per-version runs, success, p50, cost under an agent filter | Nothing new here — the second consumer of #37's `/stats/usage?group_by=version`. It does need `/stats/usage` to expose the `include_delegations` choice §2a describes, or a delegate-only agent has no strip |
| `/spend` — accept `from`/`to` alongside `days`, so the range control is honest | Route + `agent_runner` cost queries |
| `/spend` — a partial-cost run count, so "every total below is a floor" has a number | Aggregate `cost_is_partial` in the existing cost query. No migration |
| `CostByAgent` — agent **name** alongside `agent_id`, **one row per agent** (today `cost_breakdown` splits an agent across its models), plus the agent's **monthly cap** and **month-to-date** so the cap column is honest | Schema + join + grouping; cap from the spec's `budget.monthly_usd`, MTD from the query `/spend` already runs. No migration |
| `AgentRunRead` | Nothing new needed — and #200 adds `parent_run_id` and `subagent_task_id` to it, which is what lets the table and the detail view tell the two kinds of row apart |
| `spend_by_provider` / `spend_by_key` — the `parent_run_id IS NULL` filter they lack | **Not this plan's work: #170.** But the By provider and By key cards are those two queries, so this tab over-counts a delegation until it lands (§6) |
| Budget context on the month figure | Nothing new — `organizations.monthly_budget_usd` is already on `GET /orgs/{org_id}` |
| "All organizations" mode (§6a) — `organization_id`-optional `/runs`, `/approvals`, `/spend`, refused for anyone but an app admin | Route + repository on all three; the one honestly droppable line here |

Everything else is frontend.

## 8. Filed separately, found while writing this

- **`AgentRunRead.logfire_trace_id` is documented as *"Deep-link into the full trace"* and
  is always `null`** (`app/schemas/agent_run.py:29`). The public API promises something it
  never delivers. Independent of this page. **Filed as #206** — and the disposition there
  is *wire it*, not remove it: the deep link was reinstated at sign-off, which makes this
  the first of three pieces rather than a deletion. §1's four findings still hold and are
  the reason that issue is priced the way it is.

A second find — "Spend by agent" listing model labels because `CostByAgent` carries no
name (`runs/page.tsx:285`) — started here, but the mockup shows it fixed and the change
is one join, so it moved into scope: §7 prices it.

## 9. What stage 2 is verified by

- a test that mocks a 502 per tab and asserts the **error** state, not the empty one
- an integration test proving Approve/Reject and the Approvals tab are **absent** without
  `approvals:decide`
- an integration test proving the run count is `total`, not the length of the first page
- the new `list_runs` filters proven against a real database: a staging run absent when
  `environment_id` narrows to production, a `status` list returning both `failed` and
  `budget_exceeded` rows, a version filter returning only the rows that executed it
- **delegation, against a real database** (§2a): the top-level list excludes a delegated
  run while the run it came from is present; a run that delegated shows its delegations in
  the detail view and a delegated run links back to its parent; the version strip of an
  agent used *only* as a delegate is not empty, and its cost-per-run does not count a
  delegation twice; and no environment-narrowed query silently loses a delegated row
- the approvals queue names the delegate — `ApprovalDelegate` still renders and its
  integration test still passes after the tab is rebuilt as three components
- the decided view proven: a decided approval renders its decider and is refused a
  second decision; the pending queue and the decided list never share a row
- the three tabs land as separate components — the 342-line page is already over the
  ~100-line guidance, and #45 counts the split as part of the work, not extra
- `messages.run_id` covered by an integration test against a real database: two runs in
  one conversation, each detail view showing only its own steps
- `bun run type-check && bun run lint && bun run test:run` clean
- `make check` clean
