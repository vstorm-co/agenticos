# Dashboard design — stage 1 of #37

**Stage 1 has been reviewed, and two of its calls were reversed.** A named
per-person usage table is *in* (decision 3 below argued the opposite), and a
user-arranged dashboard moves from "out of v1" into stage 2 with the shape
this note had already settled. Both reversals are folded into the sections
they belong to rather than parked in a changelog, so every section reads as
what was decided — the two `Reversed in review` paragraphs mark where the
argument changed. The review also confirmed the org answer-quality card
(#209), kept budget *management* out, and split the live-update question in
two. Issues filed out of it: **#207** (the dead `RunSurface.SCHEDULE`),
**#208** (surface recording), **#209** (answer quality end to end), **#210**
(sort run history by duration).

This is the design artifact for the role-aware dashboard, meant to be reviewed
before any product code is written. Open
[`dashboard-demo.html`](dashboard-demo.html) in a browser — it is
self-contained (no build, no network). The dark bar on top is demo chrome, not
part of the design: it switches the **identity** (all seven the platform
knows), the **data state** (normal / empty / error), and **endpoints &amp;
gates** — hide the annotation layer (endpoint chips, "needs new endpoint"
badges, the gate footers) to see the page as the product would ship it. The
filter row below the page title — period and visible sections on the left,
quick actions on the right, the organization select for an app admin — is
part of the proposed product, not of the demo; see *Filtering*. The demo state lives in the URL hash —
`dashboard-demo.html#identity=member&state=error&period=7d&annotations=off&org=globex`
opens the exact view a review comment means (a custom range travels as
`period=2026-07-05..2026-07-20`).

## The rule that decides everything else

**Widgets are keyed on permissions, never on role names.** Each card declares
the permission that reveals it (printed in its footer) and renders only when
the caller holds it — in the product that is `can()` from
`use-permissions.ts`, plus the `is_app_admin` flag for the deployment strip.

What follows from that one rule:

- **Absence, not greying.** A card the caller may not see does not render —
  no disabled state, no 403 behind a visible control. For a member the
  workspace section *is* the page, and it has to look complete, not stripped.
- **Same page, different answers.** There is one dashboard route. Roles do
  not fork into different landing pages; they resolve to different subsets of
  the same widget registry. The demo computes visibility from a mirror of
  `ROLE_PERMS`, so switching identities exercises the mechanism, not seven
  hand-drawn screens.
- **Custom roles come for free.** When custom roles land (permissions Phase
  2), any recombination of permissions already has a correct dashboard.
- The rule reaches *inside* widgets too: "Your agents" renders for anyone
  with `agents:view`, but the per-agent run counts appear only with
  `runs:view`, the "Open chat" button only with `agents:run`, and the
  "yours" cards only with `agents:edit` — an operator or viewer, who cannot
  create agents, sees only what was shared. A viewer gets a browsable list;
  a builder gets the same list with adoption numbers.
- **It also decides what a card may claim about you.** "Your activity" and
  "Continue where you left off" render only with `agents:run`: a run history
  and a conversation list are made of rows the caller produced by running
  agents, so for a viewer — who cannot run — both cards would be permanently,
  structurally empty. Gating them on `agents:run` (not on the role name)
  means a Phase-2 custom role that grants running gets them back
  automatically.

**One thing the permission rule deliberately does not decide: layout.** Each
audience has its own layout — the order of sections, the width of cards, in a
few places the heading over them. A layout may *feature* or *omit* a
permitted card (a builder's page does not lead with spend), but it can never
*show* an unpermitted one — presence is still each widget's gate, and the
demo applies both layers so switching identities exercises the real
mechanism. A Phase-2 custom role gets the layout of the nearest audience; the
gates keep that honest whatever the layout says.

## Audiences — and the layout each one gets

Seven identities collapse into four audiences. The audience decides what
question the page answers *first* — which is exactly what its layout encodes.

| Audience | Identities | The question the page answers |
|---|---|---|
| Deployment admin | `is_app_admin` flag | Is the platform healthy and growing — and how does my own org look? |
| Org steward | owner, admin | Is my organization adopting this, what does it cost, what needs a decision? |
| Operations | builder, operator | Are the agents working, and what is waiting on me? |
| Everyday user | member, viewer | What can I use, and where did I leave off? |

The layouts, in the order each page reads:

- **Deployment admin** — the deployment strip, then the organization divider
  with its select, then the steward layout for the chosen org. Their own
  workspace sits last: this persona reads before they chat.
- **Org steward** (owner, admin) — *Needs attention* first: approvals to
  decide and recent failures, then a row of three early-warning tiles —
  budget headroom (the *cause* the outcomes donut only shows the symptom
  of), integrations that stopped answering, and knowledge collections that
  stopped syncing. Then *Usage &amp; cost* (adoption, outcomes, spend, model
  mix, and — closing the section, full width — the per-person table under
  the adoption count that summarises it), then *People &amp; quality* —
  members with a per-role split and a "View members" link, beside the
  answer-quality trend. Members is deliberately **not** under Needs
  attention: a headcount is context, not a queue. Then *Where agents run
  code* — the sandbox zone #129 added, gated on `connections:manage`.
  Workspace last.
- **Operator** — *Needs attention* first and widest: the approvals queue
  beside recent failures, because both are the operator's inbox. Then
  *Health* (outcomes, latency, answer quality), then usage, workspace last.
- **Builder** — *their agents* first: the cards they build and the chats they
  test them in. Then *How your builds behave* — a version-to-version
  comparison (did v4 actually behave better than v3, off
  `agent_runs.agent_version_id`), adoption per agent, recent failures,
  answer quality, and the plumbing their agents stand on: MCP server health
  and knowledge-sync freshness, both of which fail quietly and take the
  agent's tools or its knowledge with them. Then org usage, then the sandbox
  zone — a builder is who gives an agent code execution, so the memory
  ceiling it dies on is their question, and they hold `connections:manage`
  where the operator does not. A builder holds
  `runs:view`, so the data is the same; the page just leads with what a
  builder can act on. (This also removes the old sore spot: builder held one
  small governance card and three-quarters of a row of air.)
- **Member** — no section headings at all: their agents,
  continue-where-you-left-off, their own activity — and their own analytics,
  all `scope=own`: which agents *they* use most, and the answer-quality
  trend of *their* conversations. No `runs:view` means no org data, but a
  member's own rows are their own history — the page is a launcher with a
  personal report, not a stripped-down steward view.
- **Viewer** — agents shared with them (browse only — no chat buttons) and
  the shared-with-you counts. Nothing on the page claims activity a viewer
  cannot have.

Within Operations the split is visible and deliberate: operator holds
`approvals:decide` so the approvals queue renders; builder does not, and
instead reads adoption and failures of the agents they can edit.

## Widget map

| Widget | Shown because | Fed by | Exists today |
|---|---|---|---|
| Platform at a glance | `is_app_admin` | `GET /api/v1/admin/stats` | yes |
| Service health | `is_app_admin` | `GET /api/v1/admin/system` | yes |
| Top organizations | `is_app_admin` | `GET /api/v1/admin/organizations` | yes |
| Answer quality, deployment-wide | `is_app_admin` | `GET /api/v1/admin/ratings/summary` | yes |
| Runs over time | `runs:view` | `GET /api/v1/stats/usage` | **no — new** |
| Outcomes (all six `RunStatus` values, five segments) | `runs:view` | `GET /api/v1/stats/usage` | **no — new** |
| Where runs come from (by surface) | `runs:view` | `GET /api/v1/stats/usage` | **no — new, and the recording needs widening (below)** |
| Agents: adopted and forgotten | `runs:view` | `GET /api/v1/stats/usage` | **no — new** |
| Latency (p50 / p95) | `runs:view` | `GET /api/v1/stats/usage` | **no — new** |
| Active people (the count) | `runs:view` | `GET /api/v1/stats/usage` | **no — new** |
| Who is using it (the names under it) | `runs:view` | `GET /api/v1/stats/usage?group_by=user` | **no — new** |
| Spend (period total + this-month line) | `runs:view` | `GET /api/v1/stats/usage` + `GET /api/v1/spend` | **partly — the period total needs `/stats/usage`; the month line exists** |
| Budget headroom | `runs:view` | `GET /api/v1/orgs/{org_id}` + `GET /api/v1/spend` | yes |
| Models behind the runs | `runs:view` | `GET /api/v1/stats/usage` | **no — new** |
| Version to version | `runs:view` | `GET /api/v1/stats/usage?group_by=version` | **no — new** |
| Recent failures | `runs:view` | `GET /api/v1/runs?status=failed,budget_exceeded` | **no — needs a status filter on `/runs`** |
| Waiting on a decision (approvals) | `approvals:decide` | `GET /api/v1/approvals` | yes |
| Integrations (MCP health) | `mcp:manage` | `GET /api/v1/mcp-connections` | yes |
| Knowledge sync | `collections:view` | `GET /api/v1/rag/sync/sources` | yes |
| Members | `members:manage` | `GET /api/v1/orgs/{org_id}/members` | yes |
| Answer quality (org) | `runs:view` | `GET /api/v1/ratings/summary` | **no — new** |
| Your agents | `agents:view` | `GET /api/v1/agents` | yes |
| Continue where you left off | `agents:run` | `GET /api/v1/conversations` | yes |
| Your activity | `agents:run` (own rows) | `GET /api/v1/stats/usage?scope=own` | **no — new** |
| Agents you use most | `agents:run` (own rows) | `GET /api/v1/stats/usage?scope=own` | **no — new** |
| Answer quality in your chats | `agents:run` (own rows) | `GET /api/v1/ratings/summary?scope=own` | **no — new** |
| Shared with you | `agents:view` (shared scope) | `GET /api/v1/agents` · `/kb` · `/skills` | **partly — the lists exist but return own+shared as one page; needs a `shared_with_me` count** |
| Quick actions (filter-row buttons) | one action per permission | client-side | — |

Six rows carry a sentence of fine print:

- **Who is using it** is the one card that names people, so it carries its
  own disclosure: the gate is `runs:view`, which builder and operator hold
  too. It is ordered by runs with cost as a column, and it sits under the
  aggregate rather than replacing it — see decision 3.

- **Outcomes** draws five segments covering all six `RunStatus` values —
  `completed`, `failed`, `budget_exceeded`, `awaiting_approval`, and
  `running`/`cancelled` folded into one neutral segment the legend names.
  The invariant that keeps this card honest: **the segments sum to
  `total_runs`**, and the `awaiting_approval` segment counts the same parked
  runs as the approvals card above it — the two can never disagree.
- **Where runs come from** draws the set the recorder produces *after* a
  stage-2 widening: a `RunSurface.EMBED` stamped by `embed_session.py`
  (today an embedded-widget run is recorded as `web`), and `mattermost`
  added to `_SURFACES` in `channels/mentions.py` (today it falls through to
  `api`). Playground is charted because it is a real surface already; the
  dead `SCHEDULE` value — defined, never assigned — is not.
- **Spend** tells two truths on one card: the period total obeys the filter
  and comes from `/stats/usage`; the month-to-date line is calendar-aligned
  so it reconciles against an invoice, deliberately ignores the filter, and
  says so in its own copy. `/spend` itself stays untouched.
- **Members** is the one row where the permission does layout work rather
  than marking a boundary: the endpoint is open to any member ("Any member
  may call this"), and `active_users` carries `total_members` under
  `runs:view` anyway. The card is *featured* only on steward pages; nothing
  is actually withheld.
- **Budget headroom** reads two stored values against a number `/spend`
  already returns: `organizations.monthly_budget_usd` (on
  `GET /orgs/{org_id}`) and each agent's `budget.monthly_usd` from its spec.
  It exists because the outcomes donut draws `budget_exceeded` — the
  symptom — and nothing else on the page showed the cause.

Every widget has three designed states — the demo's state switcher shows all
of them. "No runs yet" and "the request failed" are different pixels on
purpose: an empty state invites, an error state apologises and offers a
retry, and each card fails alone (live defect #32 on `/rag` is the
counter-example this refuses to repeat).

### The approvals card is an existing feature, not an invention

"Waiting on a decision" renders `ToolApproval` rows
(`app/db/models/agent_run.py`): a side-effecting tool call pauses its run,
stores the tool *and its arguments*, and waits for a human holding
`approvals:decide` — statuses `pending / approved / rejected / expired`,
listed by `GET /api/v1/approvals`. The demo rows mirror that shape: an agent,
the tool it wants to call, whose run is waiting, for how long. Approvals are
tool-call approvals only — a "budget raise" request flow does not exist
today, so the card deliberately does not draw one.

## Filtering

One filter row sits above everything it scopes — never a filter inside a
card. It is product UI, not demo chrome:

- **Period** — a date-range button opening a picker: presets on the left
  (Today, Last 7 / 30 / 90 days, This month, Last month) and a two-month
  calendar for a custom range, future days disabled. Presets are UI sugar —
  either way the page queries `?from=&to=` on `/stats/usage`, and every card
  reading it re-renders against the same slice.

    **`/spend` is not one of them, and cannot be.** It takes `days: int`, a
    rolling window that always ends now, so a range that ended two weeks ago
    is unrepresentable — and its headline is `month_to_date_usd`, which is
    calendar-aligned on purpose so it reconciles against an invoice. Rather
    than widen it, the period total moved to the `cost` block on
    `/stats/usage` and `/spend` stays untouched. The one figure that still
    comes from it is the month-to-date line on the Spend card, which says in
    its own copy that it is a calendar month and deliberately outside the
    filter. A card opting out of the filter bar silently is what this
    arrangement exists to avoid.
- **Sections** — one toggle per titled section of the caller's layout, so
  the page can be narrowed to "just what needs attention" during a review.
  With a single visible section (member, viewer) the control disappears.
- **Quick actions** — the right end of the same row: scoping on the left,
  doing on the right. One button per permission (`New chat` with
  `agents:run`, `Create an agent` with `agents:edit`, `Review approvals`
  with `approvals:decide` and its pending count, `Invite a teammate` with
  `members:manage`); a viewer holds none of these and gets no buttons and no
  teasers. Previously this was a card at the bottom of the page — the one
  place the most actionable control was hardest to reach.
- **Organization** — app admin only, and the one filter that changes tenant.
  It does not sit in the top row: the deployment strip above it is global
  and unaffected, so the select renders at the boundary — a labelled divider
  between the deployment section and the organization sections it actually
  scopes. Everyone else's dashboard is scoped to their active organization,
  which the sidebar switcher already owns; a second org control for them
  would be a fork, not a filter.

The demo's filter row is live: period regenerates the data, the sections
dropdown hides sections, and the org select (as app admin) re-seeds every
number.

## The aggregation decision

**Build one new endpoint in stage 2: `GET /api/v1/stats/usage`.** Today,
apart from `/spend` and the app-admin `/admin/stats`, nothing aggregates —
`/runs` pages through rows with `limit ≤ 100`, and counting one page in the
browser is analytics over the most recent 100 rows, silently. The issue's
central question — *how do people actually use the system* — is unanswerable
from existing aggregates, so "ship only what already aggregates" was
considered and rejected.

Proposed contract:

- `from`, `to`: ISO dates, inclusive; default is the last 30 days. The
  filter bar's presets all reduce to a `from`/`to` pair, so the API has one
  time parameter, not two kinds.
- `scope`: `org` (default) or `own`.
  - `scope=org` requires `runs:view` — it reads everybody's runs.
  - `scope=own` requires only a signed-in membership: it aggregates rows
    where `user_id` is the caller, which is the caller's own history. This
    is what feeds "Your activity" for members and viewers.
- One composed response, so the page's usage section is one query, one
  loading state and one error state:

```json
{
  "from": "2026-07-06",
  "to": "2026-08-04",
  "scope": "org",
  "total_runs": 2003,
  "previous_total_runs": 1622,
  "by_day": [{ "date": "2026-07-05", "runs": 61 }],
  "by_surface": [{ "surface": "webchat", "runs": 821 }],
  "by_agent": [{ "agent_id": "…", "name": "Support triage", "runs": 561 }],
  "by_status": [{ "status": "completed", "runs": 1823 }],
  "by_model": [{ "model_label": "claude-sonnet-5", "runs": 881 }],
  "latency_ms": { "p50": 3200, "p95": 14800 },
  "active_users": { "active": 14, "total_members": 23 }
}
```

Everything above is answerable from `agent_runs` columns that already exist
(`surface`, `status`, `agent_id`, `user_id`, `model_label`, `started_at`,
`ended_at`). `active_users` is deliberately a count — see the decisions below.

- `group_by`: on-demand dimensions beyond the composed default. **The
  vocabulary is fixed now, as the endpoint's contract, so #45 and this page
  agree on one aggregate instead of growing one each:**
  `day | surface | agent | version | user | status | model | exposure | environment`.
  All nine are columns already on the run row — `agent_version_id` (kept even
  if the version is deleted, precisely so this question stays answerable),
  `exposure_id` (which binding admitted the run — *which* Slack workspace or
  Telegram bot, not just "slack"), and `environment_id` (which named
  environment resolved the version, so staging noise can be kept out of
  production numbers). **v1 implements** the composed response plus
  `group_by=version` — the builder's version-to-version card — and
  `group_by=user`, which review added for the per-person table; `exposure`
  and `environment` stay in the contract and land together with #45, whose
  Activity page wants filters over exactly those rows. That the reversal
  cost one dimension rather than an endpoint is the argument for freezing a
  vocabulary before implementing any of it.

With `scope=own` the same shape narrows to the caller's rows, drops
`active_users`, and adds `pending_approvals` — how many of the caller's runs
are parked on somebody's decision (`tool_approvals` where the run is theirs
and status is `pending`). That is what lets "Your activity" answer *why is my
agent stuck* for a member who cannot see, let alone decide, the approval
queue. The same response also feeds the member's personal analytics for
free: `by_day` is their activity chart and `by_agent` is "Agents you use
most" — no extra endpoint, just their own rows.

`GET /api/v1/ratings/summary` takes the same `scope` parameter: `org`
(default, `runs:view`) feeds the organization's answer-quality card;
`scope=own` aggregates ratings given in the caller's conversations and feeds
"Answer quality in your chats". Both return the headline percentage plus a
per-day series, so the card shows how quality *moves*, not just where it
stands. Neither returns rating **comments** — see decision 4: the free text
belongs behind a specific run, not in an organization-wide aggregate.

## Chart library

**recharts `^3.0.0` — already a dependency, zero new install.** It is used in
five files today (`stat-card.tsx`, `stat-card-spark.tsx`,
`chart-message.impl.tsx`, the admin ratings page and its chart).

Measured on this branch (`bun run build`, Next 16.2.12 / Turbopack): the
recharts-bearing client chunk is **301 kB raw / ~90 kB gzipped**. It is
already lazy-loaded via `next/dynamic({ ssr: false })` — `chart-message.tsx`
is the in-repo precedent and explains why — so it never blocks a page's first
paint; the charts hydrate after. The dashboard will use the same pattern:
stat numbers and lists render server-first, chart bodies load on demand.

The hand-rolled SVG in the demo is a mock, not a proposal to hand-roll in
the product.

## Visual language

- **The demo wears the product's own tokens, verbatim.** Its stylesheet
  mirrors `frontend/src/app/globals.css` (light theme) as the same `oklch()`
  values: the hue-259 accent ramp (`--color-brand` = brand-700 for
  selection, links and focus; `--color-chart` = brand-600 for data strokes),
  the neutral surfaces and borders, the status tones
  (`success` / `warning` / `destructive`), `--radius-card` (8px), the card
  shadow, and the type stack — Inter for body, Bricolage Grotesque for the
  page title and section spine, Geist Mono for endpoint chips. One deliberate
  consequence, straight from the product: **the primary action is ink, not
  the accent** — "New chat" and "Review" are near-black buttons, and blue
  keeps the quieter jobs.
- **Icons are lucide, never emoji** — the icon set the product already
  renders everywhere else.
- **One accent hue carries every series.** Charts with a single series (runs
  over time, surfaces, agents, spend) use the brand accent; nothing on the
  page cycles categorical hues.
- **Status colors appear only where color means state** — the outcomes
  donut and the health tiles. The green/red pair sits in the CVD floor band
  (deutan ΔE 7.4, checked with a palette validator, not by eye), so color is
  never the only channel: segments carry 2px surface gaps, and the legend
  names each state with its count. `awaiting_approval` wears the chart
  accent ("waiting on us" is a third story, not a failure) and
  `running`/`cancelled` a neutral grey. Values also render as text because
  green and amber fall below 3:1 contrast against the surface.
- **Text never wears a series color** — identity comes from the mark or a
  legend dot beside it.
- **Line charts carry real axes and a hover crosshair** — labelled y-ticks
  on clean 1/2/5-step values, first / middle / last date on the x-axis, and
  a crosshair with the exact date and value under the cursor. Every chart is
  generated at its card's real width, so type inside a chart is the same
  size as type outside it; axis labels are fixed at 10.5px and the hover
  readout at 12.5px — two settings, deliberately independent. The demo
  hand-rolls this to make the interaction reviewable; the product gets axes
  and tooltips from recharts for free. Bar rows keep native `title` hints.
- **Answer-quality cards plot the trend, not just the score** — a
  percentage alone hides whether last week's change was a blip or a slide;
  the per-day series answers that at a glance.

## Decisions taken in stage 1

1. **App admin sees the deployment strip *and* the org section.** One page,
   more answers — and the deployment admin sees the product the way a
   steward does, instead of a separate console.
2. **A member gets a launcher plus their own analytics; a viewer gets
   neither, on purpose.** No org analytics for either (no `runs:view`), but
   everything `scope=own` can answer from the member's own rows is theirs:
   their activity over time, which agents they use most, the answer-quality
   trend of their own conversations — including when their own runs are
   parked on an approval: the answer to "why is my agent stuck",
   deliberately without a Review control they could not use (deciding stays
   behind `approvals:decide`). A viewer cannot run agents at all, so a run
   history and a conversation list would be built from rows they can never
   produce — those cards gate on `agents:run`, and the viewer's page shows
   what was shared with them instead of permanently empty charts.
3. **Adoption is a count *and* a table of names.** *Reversed in review.* The
   argument here was that "14 of 23 members ran an agent" answers the
   steward's question without shipping a surveillance table. The call went
   the other way, and cheaply: `group_by=user` was already in the frozen
   `/stats/usage` vocabulary, so nothing was ever refused at the endpoint —
   only the rendering. Three things the reversal had to settle, because a
   table of names is not a neutral card:
   - **Whose names, to whom.** The gate is `runs:view`, which builder and
     operator hold as well as owner and admin — a wider audience than the
     person being listed would assume. So the card says so in its own copy,
     and the layouts feature it wherever usage is featured rather than on
     steward pages alone: a disclosure that is true only on some pages is
     not a disclosure.
   - **Runs, with cost as a column.** Ordering by spend turns the same rows
     into a league table nobody asked to join; ordering by runs keeps the
     card answering adoption, and cost rides along as the context the
     steward would otherwise go and cross-reference by hand.
   - **The count stays.** "Active people" is the headline and the table is
     the evidence under it — the same summary-and-its-evidence pattern the
     rest of the page follows. Replacing one with the other loses the
     glanceable answer.
4. **The org-scoped answer-quality card is in.** *Confirmed in review*, and
   filed as **#209** together with the half that makes the number
   actionable: the 👎 on the run row in Activity and the rater's comment in
   the run detail. It is the only widget on the page answering "is it any
   good", and nothing below `admin_ratings.py` surfaces either the score or
   the comment today. One guardrail the card owes its subjects: a rating
   carries free text, and free text shown at `scope=org` is a person's
   written opinion about one conversation reaching an audience its author
   did not pick. **The card is counts and trend only** — the comment stays
   behind the run detail, where the reader has already navigated to a
   specific run.

## Deliberately out of v1

- **Managing budgets from the dashboard.** An earlier draft of this note
  claimed `budgets:manage` gates no route and no cap is stored — both halves
  were wrong (`budgets:manage` gates the `monthly_budget_usd` field on
  `PATCH /orgs/{org_id}`, and the caps live on
  `organizations.monthly_budget_usd` and `AgentSpec.budget.monthly_usd`), so
  *showing* headroom moved into v1 as the Budget headroom card. What stays
  out is managing: raising a cap, a budget-request flow — that is its own
  design task. One thing review added, which is neither: the headroom card
  links to the organization's settings. The outcomes donut draws
  `budget_exceeded` and Activity shows the same symptom, and until now
  neither offered a way out — a link to the page where the cap lives is
  navigation, not a request flow.
- **An audit strip** (`audit:read`) — the audit log has its own page;
  duplicating it here earns nothing yet.
- **Deployment-wide time series.** `/admin/stats` is point-in-time counts;
  giving the app admin adoption curves would mean cross-tenant aggregation
  with its own questions. The strip stays counts-plus-health for now.
- **Live updates, for the aggregates.** Query-layer refetch on focus is
  enough for a page of daily aggregates — a run count does not move
  meaningfully between two glances. *Review split this in two:* the queue is
  the exception. Approvals and `running` runs change in minutes, not days,
  and the approvals count in the quick-actions row is a number somebody acts
  on — a stale one sends them to decide something already decided. Those two
  get a short staleness; everything else keeps the page-wide default.

## What stage 2 builds

Backend:

- `GET /api/v1/stats/usage` — `from`/`to`, `scope`, the composed response,
  and two of the nine dimensions: `group_by=version` for the builder's
  version-to-version card and `group_by=user` for the per-person table
  review added. `GET /api/v1/ratings/summary` with the same `scope`.
- A `status` filter on `GET /runs` — a list, not a single value
  (`failed,budget_exceeded` is the operator's natural query), with the
  matching `where` in the repository.
- The surface-recording widening: `RunSurface.EMBED` stamped by
  `embed_session.py`, `mattermost` added to `_SURFACES` in
  `channels/mentions.py`.
- A `shared_with_me` count (or filter) on the agents / kb / skills list
  endpoints, so "Shared with you" does not count rows client-side over a
  paged list.
- Platform-layer coverage at 100%, `docs/architecture.md` updated per the
  trigger map.

Frontend: the page as demoed — widgets gated by `can()` / `isAppAdmin`,
loading / empty / error per widget with a test asserting the error state on a
502, `dashboard.integration.test.tsx` covering at least two roles, every
string through `next-intl`, recharts behind `next/dynamic`.

### A user-arranged dashboard

*Implemented in #213.* This note settled its whole shape before any code was
written, which is what made it cheap to build; the shape below is what shipped,
not a starting point for a second design round. Where it lives: the pure layer
in `frontend/src/lib/dashboard/preference.ts` (sanitize, resolve, the edit
operations) and the grid vocabulary in `layouts.ts` (span/row classes, the
step and snap helpers a resize calls), the gate in `visibleSections` run last on
whatever it produces, the edit UI in `frontend/src/components/dashboard/`
(`dashboard-editor`, `widget-edit-card`, `add-widget-dialog`, the preset menu
and save dialog) and the store behind `GET`/`PUT`/`DELETE
/api/v1/me/dashboard-layout` with its `presets` shelf underneath.

- **A preference is a third layer over the two the page already has.**
  `effective layout = preference ?? audience default`, then
  `visible = effective ∩ gate()`. The four audience layouts stay the
  default; nobody starts from an empty page.
- **It may only ever reorder or hide — never reveal.** A stored layout
  naming a widget the caller cannot see is dropped at render time. The
  realistic case is a demotion, not an attack, and it has to be survivable
  either way. A preset is the same story: applying one *writes its entries as
  the active arrangement*, so the gate runs on them exactly as it does on a
  hand-arranged layout — a preset can no more reveal a forbidden card than a
  drag can.
- **The "add a widget" catalog passes through `gate()` too**, so the list
  cannot leak what the page hides. This is the half that is easy to forget:
  a catalog is a second surface with the same secrets. The catalog previews
  the real widget with live data on hover, which is the same gate again — it
  can only mount what the caller could already see.
- **Editing is direct manipulation on the real cards.** Edit mode renders the
  live widgets, not placeholders — arranging a page you cannot see the
  contents of is guesswork — behind an overlay that carries the controls: drag
  to reorder, a corner handle (and discrete steppers, for the keyboard) to
  resize in **both** dimensions, and hide. The cards wobble on hover so the
  grid reads as editable.
- **Cards resize in two dimensions, from two closed sets.** Width is the
  `s3`–`s8`-plus-`s12` span set an earlier draft of this note got wrong (its
  own demo pairs `s7`+`s5`, `s8`+`s4`); height is `r2`–`r6` grid rows. Both
  are closed so a stored size the grid cannot express is impossible, and a
  pointer resize snaps to the nearest allowed step. **Height is optional on a
  placement** — the audience defaults auto-size and store no height, so the
  curated pages are pixel-identical to before personalization; a person's own
  arrangement fills in an explicit height so every card has one to grow from.
- **Preferences are stored per user *and* per organization.** The same
  person is a steward in one org and a member in another; one saved layout
  across both is wrong in one of them.
- **Named presets are the versioning layer.** Beyond the single active
  arrangement, a person keeps named ones — "Monday review", "Incident watch" —
  on a shelf next to Customize, and switches between them. A preset is a
  snapshot: applying it copies its entries into the active arrangement, so
  editing afterwards diverges from the preset rather than mutating it, the same
  contract as "save as" everywhere else. Presets share the layout's tenant
  boundary and add a name unique per person per org (so "save as" refuses a
  duplicate rather than silently overwriting) and a per-person cap (so the
  table stays bounded). There is deliberately no *apply* endpoint — applying is
  the client's `PUT` of the entries, keeping one write path and one validation
  for what the dashboard renders.
- Widget ids are stable registry keys, so persisting them is safe; every
  widget declares a "see all" destination pointing at a page that already
  exists, carries catalog metadata (description, permission, default span,
  default height, default audiences) from day one, and the page offers a
  reset-to-default.

Two entries in the list below stop being style advice once this lands, which
is the reason they are worth the paragraph they get.

### The demo's registry, and what must not be ported from it

- **Span and title ride the layout entry, not a widget-id lookup.** A widget
  appears once per page in the mock (`LIVE` is keyed by widget id, the DOM id
  is `w-${id}`). Keep that shape and "runs over time, once org-wide and once
  for me" is a latent collision — one a person arranging their own page
  triggers the first time they add the same card twice.
- **`gate()` takes `(can, isAppAdmin)` rather than closing over module
  state.** The demo's closes over `current`. Injected, a widget is testable
  alone, `dashboard.integration.test.tsx` stays cheap, and the catalog can
  run the same gate over a list it is not rendering.
- **No span→pixels table.** `SPAN_W` hardcodes a 1180px page so 1 SVG unit ≈
  1 CSS px. The product carries no such table at all; recharts'
  `ResponsiveContainer` measures.

### The deep link works in both directions

The demo's cards link out to the pages that hold their rows. The contract
owes the return trip as well: Activity should be able to hand back "see this
on the dashboard", carrying the same `from`/`to` and the same nine `group_by`
dimensions. A filter a user set in one place and has to retype in the other
is two features that merely look related.

## What review settled, and what it did not

The demo is the argument; this note is the map. Review answered the calls
this section used to put up for challenge — the four-audience split, the
`group_by` vocabulary fixed here for #45 to share, the surface-recording
widening, and which **needs new endpoint** widgets justify their endpoint —
and reversed two of them, folded above. What remains genuinely open, and is
worth a second opinion before or during stage 2:

- **The per-person table's disclosure is copy, not a mechanism.** Saying
  "everyone with `runs:view` sees this" is honest and costs nothing, but it
  does not give the person listed any control. If that turns out to be the
  wrong trade, the fix is a permission of its own rather than a narrower
  layout — and that is a permissions-catalog change, not a dashboard one.
- **Whether `scope=own` deserves the same table for one's own row.** A
  member cannot see the org table; whether they should see where they sit
  in it is a question this design does not answer either way.
- **The arrangeable dashboard's persistence.** Settled in #213. The active
  preference is one row per `(user_id, organization_id)` in `dashboard_layouts`;
  named presets are rows in `dashboard_presets` with the same key plus a unique
  name. Both store the arrangement as a JSONB array of `{widget, span, rows?}`
  (`rows` optional — absent means the widget's default height), cascading from
  either side so a removed membership leaves no orphan. It is validated against
  the widget registry **on write** — an unknown id or an out-of-set width or
  height is a 422, not a card that never renders — and trusted on **neither**
  read: a widget id retired since it was saved is dropped at render rather than
  versioned, which is why the row carries no version. `sanitizeEntries` drops
  the unknown id and coerces a stale size, and the gate drops the unpermitted
  one, every render. The registry parity test asserts the backend's
  `WIDGET_IDS`, `SPANS` and `ROWS` mirrors match the frontend registry in both
  directions.

## What stage 2 changed about the visual language

Three calls in this note were superseded by what the product had become by the
time the arrangeable dashboard shipped. Recorded here rather than edited in
above, because each was right when it was written.

- **A card is `Card`, at 16px, with a divider under its heading.** This note
  mirrors `--radius-card` (8px) because that is what the token said; the
  product's `Card` primitive is `rounded-2xl` with `shadow-card`, and by
  0.0.151 every list page and the Activity figures were built on it. A
  dashboard widget drawn at 8px with no elevation was the only surface in the
  product that looked like a different product — on the one page that shows
  all of them at once. `WidgetFrame` is built on `Card` now.
- **A figure is mono numerals under a small upper-case label.** Activity
  settled that shape for its three figures; thirteen widgets had each printed
  their headline as `text-2xl font-semibold`, so the same number changed
  typeface between the dashboard and the page its "see all" points at.
  `Metric` and `DeltaChip` are the one way both are drawn.
- **The quick actions left the filter row.** This note put "period and visible
  sections on the left, quick actions on the right". Four buttons of near-equal
  weight is four decisions asked at once, and they wrapped a button at a time
  below about 1400px. The page's one primary action ("New chat") now sits in
  the header, where every other page in the product puts its primary; the three
  shortcuts stay on the strip as ghost buttons, and the strip wraps as two
  groups rather than one control at a time.

And one thing this note did not anticipate: **a healthy organization opened on
five empty states.** "Needs attention" led the steward layout, and every card
in it is an empty state when nothing is wrong. The `summary` widget — runs,
completed share, spend, active people, all slices of the composed
`/stats/usage` response already in hand — leads the steward, operator and
builder layouts instead, which is also how Activity opens.
