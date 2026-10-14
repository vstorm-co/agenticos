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

Thirty-eight cards exist. You will not see all of them: **a card is gated on the
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
| **Usage** | Runs, outcomes, surfaces, latency, spend, [voice minutes](#voice-calls), model mix, version comparison |
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
paging back through the organization you are currently in, plus anything
addressed to the deployment as a whole, until it reaches what has aged out.

Switch organizations and the bell is that one's: a notification from the
organization you left is not gone, it is behind the switcher. A deployment
administrator is the one exception - theirs is not narrowed by the organization
they happen to be acting in, because an "admins" audience reaches them without
a membership to scope by.

A row with a destination is a link; one without - an admin's own broadcast, most
often - is only ever something to mark read. Marking one read, or everything at
once, updates the count immediately; nothing here waits on a page reload. "Mark
all read" sweeps as far as five thousand unread rows, in batches, and then asks
for the count again, so a backlog larger than that leaves the badge showing what
is still unread and a further click finishes it, rather than the badge claiming
an inbox it only partly worked through.

Each click always gets further, even where the whole batch was rows the reader
can no longer see. It never marks those: the check is against *current*
permissions, so somebody demoted for a week and restored would find that week's
security notices already read. Instead a truncated sweep says where it stopped,
and the next click resumes from there.

Both the count and the sweep say when they stopped on that bound rather than on
the end of the inbox -
`approximate` on `GET /notifications/unread-count`, `remaining` on
`POST /notifications/mark-all-read` - because a count of exactly the bound and a
genuine count of exactly the bound are otherwise the same number.

Read is not the same as gone, and both are offered. Hovering a row reveals a
cross that takes it out of the list; **Clear** in the header takes out
everything currently listed, read and unread alike. Clearing something unread
also marks it read, because a row nothing on screen can reach must not go on
counting towards the badge. Like "Mark all read", one clear is bounded - a
thousand rows - and a longer backlog takes a second click.

What a cleared row does *not* do is come back. The notification is kept and
stops being listed rather than being deleted, which is what makes that true:
the inbox recognises a repeat by the fact it describes, so a deleted row is one
the next budget check or the next retry would write again. Dismissing an alert
you have dealt with is therefore final, for that occurrence - a *new* one, about
a new fact, still arrives. Rows also age out on their own: ninety days after
being written if they were read, a year regardless.

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
nothing appears until the agent actually needs the service: then the answer
pauses on a card with that button, and once the account is connected the same
answer carries on with it. **Skip** lets it carry on without.

**Attachments** are parsed and handed to that conversation only; they are not
added to a [knowledge collection](file-processing.md). See
[File processing](file-processing.md#chat-file-uploads).

**Slash commands** expand to a prompt before the message is sent. The built-in
ones ship with the product; you can write your own under
**Settings → Slash commands**, and hide any built-in you never use. They are
yours, not the organization's.

**Watching a browse.** An agent with
[browser automation](reference/capabilities.md#browser-automation-choose) opens a
panel beside the transcript when it starts working through a page: the viewport as
it goes, the page it is on, and each step with the probability the engine chose it
at. That number is the reason the panel exists rather than a spinner - a browse that
acted on a 0.31 pick is one worth looking into. It stays up when the browse ends,
because *blocked by the page* is an answer about the page. Close it and it stays
closed for that browse.

### Dictation

The microphone in the composer turns speech into text in the box, and never
sends it: what you said lands where the caret was when you pressed the
microphone, ready to edit, and goes nowhere until you press Send. How it
transcribes is the organization's choice, made on [the Voice card](#the-voice-card):

- **Off** — no microphone.
- **Browser** — the browser's own speech recognition, so the audio goes to the
  browser vendor (Google, Apple). Firefox has none: its microphone says so
  when pressed.
- **Server** — the browser records, and this deployment sends the recording to
  the organization's speech-to-text provider, or to
  [the agent's own](#an-agents-own-engine) where it names one. It works in every
  browser that can record. See [Dictation in chat](ml-services.md#dictation-in-chat)
  for the endpoint, its limits and what is recorded.

With **Server**, pressing the microphone replaces the controls with a recording
bar: Cancel, the level, a timer and Stop. **Enter** stops and transcribes,
**Escape** cancels, and nothing typed or pressed while a recording is running or
being transcribed is sent. The recording stops by itself at the organization's
longest dictation and is transcribed, and a microphone unplugged mid-way ends it
the same way rather than discarding it. While the recording uploads, the bar
shows how much of it has gone up, once that takes longer than a second; after
that it says **Transcribing** until the text arrives.

Everything dictation has to say appears in a strip attached under the composer:
the permission prompt, a blocked or missing microphone, the last 30 seconds, five
seconds without sound, a recording under a second (not sent), a recording that
stopped at the limit, how many words were inserted, and every failure. The word
count goes away after a few seconds or at your next key. A recording that failed
to transcribe is kept until you press **Retry** or **Discard**.

Where the organization has chosen Server but nothing resolves for
the agent you picked - no provider on the agent or the organization, or no
key chosen for it - or no agent is picked, the microphone is crossed out and
says why; somebody holding `org:settings` is offered a link to the Voice card,
and somebody who can edit agents a link to this agent's own Voice card.

The glow beneath the composer while you speak follows **Voice glow** under
**Settings → Profile → Appearance**, beside the theme and **Motion**: **Vivid**,
**Subtle** (the default) or **Off**. It is remembered per browser. **Motion**
decides how much the whole console moves: **System** (the default) follows the
operating system's reduced-motion setting, **Reduce** turns motion down without
it, and **Full** keeps it whatever the operating system says. While motion is
reduced there is no glow at all, the strip appears without sliding, and the level
is a five-step indicator.

### The Voice card

On the organization's **Members** page, for somebody holding `org:settings`.
**Speech to text** chooses the engine — Off, Browser or Server, each saying where
the audio goes — and, for Server, the longest recording, from 10 seconds to 10
minutes. **Default provider**, below it, is the provider and model from the
speech-to-text catalog and a language (auto-detect, or one fixed language, which
is more accurate). It is shown whatever the engine, because it is also what
[channel bots](channels.md#what-every-channel-shares) set to inherit send their
voice messages to; **None** clears it.

**Key**, beside the provider, is the vault key the default is sent with. It
lists the API keys whose purpose is that provider and that the whole
organization can see - the platform spends this key for every member's
dictation and every inheriting bot, so a member's private key is not offered and
is refused if sent. With exactly one such key it is chosen for you, and saved by
name either way; nothing picks a key at run time. A provider with no key is
marked **no key for this provider** and the picker links to the vault to add
one. Where Server is stored but cannot run — the model was withdrawn from the
catalog, or the key was deleted or made private — the card says so, and asks to
**choose a key** where that is what is missing, because every member then sees
a crossed-out microphone.

Server with no default provider is a setup rather than a fault: the card notes that only agents with their own provider dictate. **Voice conversations**, below it, holds the organization's call settings - see [Voice calls](#voice-calls).

For somebody who also holds `runs:view`, the card opens with one line on what
the organization transcribed in the last 30 days — "42 min · 118 recordings (30
without a length)" — across dictation, channel voice messages and the API.
**Show breakdown** lists it by agent and by channel bot. The minutes count only
recordings whose length was reported, so the line says how many were not; it is
hidden while nothing has been transcribed. The figures come from
[`GET /ml/calls/summary`](ml-services.md#what-is-recorded).

### An agent's own engine

An agent's **Build** tab has a **Voice** card after its model settings, for an
agent that should transcribe differently from its organization. **Inherit**
keeps the organization's provider, model and key and shows which they are;
**Choose** picks a pair from the catalog and the key to send it with - an API key
for that provider that you can view, since publishing lends it to everybody who
can run the agent.

The key is never the organization's: an agent with its own
pair names its own key. The language is chosen on its own: inherit the
organization's, or fix one - so a Polish agent can keep the organization's
provider and key. It is part of the
spec, saved with the draft and live once the agent is published, and it applies
to [dictation](#dictation) into this agent and to voice messages its channel
bots inherit. [The order](ml-services.md#which-engine-a-recording-reaches) has
the rest.

The card says when the override changes less than it looks like: with the
organization's engine on Off or Browser it reaches only channel voice messages,
and with no organization provider it is what dictation to this agent runs on.

### Voice calls

A [voice call](voice.md) is a spoken conversation with a published agent: you
talk, it answers aloud, and you can interrupt it. Three places in the console
set it up.

- **The organization's Voice card**, under **Voice conversations**: **Allow
  voice conversations** (off by default), **Offer calls in chat**, **Longest
  call (minutes)**, from 1 to 50, and **Monthly call minutes**, or no monthly
  limit to rely on budgets alone. The first three need `org:settings`; the
  minutes need `budgets:manage` and are read-only to anybody else. A holder of
  `runs:view` also sees how many of this month's minutes calls have used.
- **The agent's Voice card**, under **Voice conversations**: **Take voice
  calls**, then the call provider and model (for Azure, the deployment name and
  its base model), the key, the voice, the spoken language (or **Follow the
  caller**), the longest call and a voice note. The card lists what the agent
  cannot use in calls, says that guardrails cannot filter spoken words before
  they are heard, and that calls are recorded as text with no audio kept. It
  takes effect when the agent is published.
- **An embed's Voice calls switch**, in the widget and hosted page forms - see
  [Channels](channels.md#voice-calls-on-a-widget-or-a-hosted-page).

Before offering a call, the console asks whether this agent can take one
(`GET /agents/{id}/voice`), so nobody grants the microphone only to be refused.
The answer names what is missing: calls off in the organization or in chat, no
voice set up on the agent, the model no longer offered, no key, or no minutes
left this month.

A call moves through states the console names: connecting, listening, you
speaking, thinking, the agent speaking, interrupted, working on a tool, waiting
for your approval, an approval you cannot give, almost out of time, and ended -
by you, by a limit, a dropped connection or a failure. Captions appear word by
word in a live region a screen reader announces, and each finished turn
replaces its caption with the message saved in the conversation, so the call is
in your history afterwards and you can carry on typing.

**Approvals** are decided in the call: a card shows the tool, its exact
arguments and what you were heard to say, with 60 seconds to decide. Without
`approvals:decide` you are told the tool needs an approval you cannot give by
voice. **Limits** are spoken: a minute before the longest call ends you are
warned, and when the time, the budget or the month's minutes run out the agent
says one sentence and the call ends. Talking is hands-free by default;
**push-to-talk** (hold the button or Space) is a choice remembered in your
browser, beside mute and **End call**.

!!! note "The call view is still being designed"

    Everything above is built except the call view itself and its button in
    the chat composer, whose layout is still being decided. Until it lands, no
    page offers a call.

In **Activity**, a call is one row with a microphone badge, and the kind filter
(**Text** or **Voice calls**) narrows to calls; a call that reconnected is still
one row, with every connection's time and cost summed. The **Voice minutes**
dashboard card, in the Usage band for a holder of `runs:view`, shows the
period's call minutes and calls, the top three agents, and this month's minutes
against the organization's limit.

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
organization-local labels shown on each agent's card. Each filter is a menu of the
labels on the agents you can see; tick several to widen it. You maintain an agent's
categories and tags from its detail page, beside the avatar controls, and the
change takes effect at once, without publishing a new version.

## When a page looks empty

**An empty state and a failed request look the same.** Every page here fans out
to several queries and renders "nothing yet" when one of them fails.

So before concluding a collection is empty or an agent has no runs, check the
network tab. This is the single most common way a real problem gets read as a
quiet one.

## Recap

- The dashboard is **thirty-eight widgets** you arrange yourself, saved per
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
