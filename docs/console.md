# The console

The console is the web application everything else on this site is configured
through. This page is the map: what each area is for, and which page explains it
properly.

If you are looking for one screen, the fastest route is the **"?"** in a page's
header — it replays that page's walkthrough, and a page whose header carries no
"?" has no walkthrough to replay.

## The dashboard

The landing page is an **arrangeable grid of widgets**, and it is the answer to
"what is happening" without opening five pages.

Thirty-six cards exist. You will not see all of them: **a card is gated on the
permission its data needs**, so a widget you may not read is never mounted and
its queries are never issued — except your own notifications, below, which need
only that you are signed in. An empty band disappears with its heading rather
than sitting there empty.

They arrive grouped into bands:

| Band | Answers |
|---|---|
| *(untitled, at the top)* | The summary the rest of the page is the detail of |
| **Deployment** | Only for a [deployment admin](permissions.md) — platform totals, health, busiest tenants, ratings |
| **Attention** | What is waiting: [approvals](governance.md#approvals), recent failures, budget headroom, MCP health, stale knowledge, your most recent [notifications](#the-bell) |
| **Usage** | Runs, outcomes, surfaces, latency, spend, model mix, version comparison |
| **People** | Members, active users, ratings, who is doing what |
| **Sandboxes** | [Capacity, live sessions, policy](sandbox.md) |
| **Workspace** | Yours: your agents, your conversations, your activity, what was shared with you |

### Rearranging it

Drag a card, resize it, hide one. The arrangement is **yours** — scoped to you
and the organization you are in, not to the organization — so changing it changes
nobody else's page.

Save an arrangement as a named **preset** to keep more than one and switch
between them. A duplicate name is refused rather than silently overwriting the
snapshot you meant to keep.

!!! info "The gate runs last, on whatever it is handed"

    A saved arrangement can reorder and hide, but it cannot reveal. Permission
    filtering runs after the layout is resolved, whether the layout came from
    the default or from your own saved one.

## The bell

Next to search, in the sidebar: a running count of what you have not read yet,
and a click opens the list itself. Unlike the widget above, opening it fetches
the page you are looking at, not a five-card preview - **Load more** keeps
paging back through everything that has not aged out yet.

A row with a destination is a link; one without - an admin's own broadcast, most
often - is only ever something to mark read. Marking one read, or everything at
once, updates the count immediately; nothing here waits on a page reload. "Mark
all read" sweeps up to five hundred unread rows at once - past that, the count
lands just short of zero and a further click finishes it, rather than the badge
silently understating what is still unread.

What lands here and what can be turned off is [Governance's](governance.md#alerts)
to explain — this page is only the two places you read it: the bell for what
just happened, the dashboard card for a handful of the most recent, the next
time you open the page.

## Chat

Where you talk to a published agent. The picker chooses which agent answers, and
the run behaves exactly as it would in Slack or behind the API — same budget,
same approval gate, same audit trail, because
[every surface goes through one runner](channels.md).

Three things in the composer worth knowing.

**Your own accounts.** An agent bound to
[each person's own account](mcp.md#whose-account-a-binding-speaks-through) on a
service speaks to it as you. The chat's controls list which of the agent's
services need an account of yours and whether each is ready, with a connect
button that opens the provider's consent in a new tab. Ask before connecting and
the agent says it cannot reach the service - and a card under the answer offers
the same button, so the fix is one click from the refusal.

**Attachments** are parsed and handed to that conversation only; they are not
added to a [knowledge collection](file-processing.md). See
[File processing](file-processing.md#chat-file-uploads).

**Slash commands** expand to a prompt before the message is sent. The built-in
ones ship with the product; you can write your own under
**Settings → Slash commands**, and hide any built-in you never use. They are
yours, not the organization's.

## What each area is for

| Area | It holds | Read |
|---|---|---|
| **Agents** | The catalog, the Builder, versions, sharing, testing, activity | [Your first agent](first-agent.md) |
| **Chat** | Talking to a published agent | [Surfaces](channels.md) |
| **Knowledge** | Collections, documents, sync sources, ingestion settings | [File processing](file-processing.md) |
| **Skills** | Written procedures an agent loads on demand | [Skills](skills.md) |
| **Context** | Standing knowledge bound to many agents | [Context files](context.md) |
| **Routines** | Schedules and event triggers | [Triggers](triggers.md) |
| **Runs** | What ran, what it cost, what it touched, whether it failed | [Governance](governance.md#audit) |
| **Sandboxes / Workspaces** | Isolated file-and-shell sessions an agent worked in | [The sandbox](sandbox.md) |
| **MCP servers** | Connections to external tools, personal and organization-wide | [MCP](mcp.md) |
| **Channels** | Slack, Telegram and Mattermost bots, widgets, hosted pages | [Surfaces](channels.md) |
| **Vault** | Credentials, sealed per organization | [Secrets](secrets.md) |
| **Organizations** | Members, roles, invitations | [Permissions](permissions.md) |
| **Settings** | Providers, ingestion defaults, notifications, your own profile | [Configuration](configuration.md) |
| **Admin** | The deployment itself: users, tenants, system, deployment settings | [The deployment](deployment.md) |

The **Agents** catalog can be filtered by **category** and **tag** — the editable,
organization-local labels shown on each agent's card. You maintain an agent's
categories and tags from its detail page, beside the avatar controls, and the
change takes effect at once, without publishing a new version.

## When a page looks empty

**An empty state and a failed request look the same.** Every page here fans out
to several queries and renders "nothing yet" when one of them fails.

So before concluding a collection is empty or an agent has no runs, check the
network tab. This is the single most common way a real problem gets read as a
quiet one.

## Recap

- The dashboard is **thirty-six widgets** you arrange yourself, saved per
  person and per organization — all but your own notifications gated on the
  permission their data needs.
- A saved arrangement **can hide and reorder but never reveal** — the gate runs
  last.
- **The bell** is a running unread count with the full list one click away,
  independent of whichever page you are on.
- **Chat, Slack and the API are the same runner**, so what you see in the
  console is what a customer gets.
- **Slash commands are yours**, built-in ones included, and you can hide the
  ones you do not use.
- A page showing "nothing yet" may be **a failed request**, not an empty
  resource.
