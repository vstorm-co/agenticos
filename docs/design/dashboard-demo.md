# Dashboard design — stage 1 of #37

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
- **Org steward** (owner, admin) — *Needs attention* first (approvals to
  decide, recent failures), then *Usage &amp; cost* (adoption, outcomes,
  spend, model mix), then *People &amp; quality* — members with a per-role
  split and a "View members" link, beside the answer-quality trend. Members
  is deliberately **not** under Needs attention: a headcount is context, not
  a queue. Workspace last.
- **Operator** — *Needs attention* first and widest: the approvals queue
  beside recent failures, because both are the operator's inbox. Then
  *Health* (outcomes, latency, answer quality), then usage, workspace last.
- **Builder** — *their agents* first: the cards they build and the chats they
  test them in. Then *How your builds behave* — adoption per agent, the model
  mix, recent failures, answer quality — then org usage. A builder holds
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
| Outcomes (completed / failed / budget exceeded) | `runs:view` | `GET /api/v1/stats/usage` | **no — new** |
| Where runs come from (by surface) | `runs:view` | `GET /api/v1/stats/usage` | **no — new** |
| Agents: adopted and forgotten | `runs:view` | `GET /api/v1/stats/usage` | **no — new** |
| Latency (p50 / p95) | `runs:view` | `GET /api/v1/stats/usage` | **no — new** |
| Active people (count, no names) | `runs:view` | `GET /api/v1/stats/usage` | **no — new** |
| Spend, month to date | `runs:view` | `GET /api/v1/spend` | yes |
| Models behind the runs | `runs:view` | `GET /api/v1/stats/usage` | **no — new** |
| Recent failures | `runs:view` | `GET /api/v1/runs?status=failed` | yes |
| Waiting on a decision (approvals) | `approvals:decide` | `GET /api/v1/approvals` | yes |
| Members | `members:manage` | `GET /api/v1/organizations/{id}/members` | yes |
| Answer quality (org) | `runs:view` | `GET /api/v1/ratings/summary` | **no — new** |
| Your agents | `agents:view` | `GET /api/v1/agents` | yes |
| Continue where you left off | `agents:run` | `GET /api/v1/conversations` | yes |
| Your activity | `agents:run` (own rows) | `GET /api/v1/stats/usage?scope=own` | **no — new** |
| Agents you use most | `agents:run` (own rows) | `GET /api/v1/stats/usage?scope=own` | **no — new** |
| Answer quality in your chats | `agents:run` (own rows) | `GET /api/v1/ratings/summary?scope=own` | **no — new** |
| Shared with you | `agents:view` (shared scope) | `GET /api/v1/agents` · `/collections` · `/skills` | yes |
| Quick actions (filter-row buttons) | one action per permission | client-side | — |

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
  either way the page queries `?from=&to=` on `/stats/usage` and `/spend`,
  and every card re-renders against the same slice.
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
stands.

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
  donut. The green/red pair sits in the CVD floor band (deutan ΔE 7.4,
  checked with a palette validator, not by eye), so color is never the only
  channel: segments carry 2px surface gaps, and the legend names each state
  with its count. Values also render as text because green and amber fall
  below 3:1 contrast against the surface.
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
3. **Adoption is a count, not a table of names.** "14 of 23 members ran an
   agent" answers the steward's question without shipping a surveillance
   table. If a per-user table is ever wanted, it is a deliberate later
   decision, not a default.
4. **An org-scoped answer-quality card is proposed but flagged.** Message
   ratings exist and nothing surfaces them below the app-admin level; the
   card needs a new `GET /api/v1/ratings/summary`. In or out is a review
   call — it is the only widget on the page that answers "is it any good".

## Deliberately out of v1

- **A named per-user usage table** — see decision 3.
- **A budgets widget.** `budgets:manage` gates no route today; there is no
  budgets endpoint at all, so this is its own design task, not a dashboard
  line item.
- **An audit strip** (`audit:read`) — the audit log has its own page;
  duplicating it here earns nothing yet.
- **Sandbox capacity / sessions / activity** — issue #129 owns that view and
  its data layer already exists. The zone model absorbs it cleanly later: one
  more section, gated on `connections:manage`.
- **Deployment-wide time series.** `/admin/stats` is point-in-time counts;
  giving the app admin adoption curves would mean cross-tenant aggregation
  with its own questions. The strip stays counts-plus-health for now.
- **Live updates.** Query-layer refetch on focus is enough for a page of
  daily aggregates.

## What stage 2 builds

Backend: `GET /api/v1/stats/usage` (and `GET /api/v1/ratings/summary` if the
review keeps the card), platform-layer coverage at 100%, `docs/architecture.md`
updated per the trigger map.

Frontend: the page as demoed — widgets gated by `can()` / `isAppAdmin`,
loading / empty / error per widget with a test asserting the error state on a
502, `dashboard.integration.test.tsx` covering at least two roles, every
string through `next-intl`, recharts behind `next/dynamic`.

## For the reviewer

The demo is the argument; this note is the map. The calls worth challenging:
the four-audience split and the layout each audience leads with, `scope=own`
for members, the `agents:run` gate that empties the viewer's page down to
what is shared, the aggregate-only adoption card, and which of the **needs
new endpoint** widgets justify their endpoint.
