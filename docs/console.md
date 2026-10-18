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

A switch at the top says whose dashboard it is, and offers only the views you
may open. Everybody opens on **Me**:

| View | Answers |
|---|---|
| **Me** | A greeting and your period in one sentence; your runs, how many finished, what is waiting on you and what it cost; then the calls waiting on you, your conversations, your agents and what was shared with you |
| **Organization** | The arrangeable page below |
| **Group** | One [group](departments.md)'s members - their runs, spend, models, when they work and who uses it most. Choose the group beside the switch. A group whose members ran nothing in the period says so once, with a way to the group, rather than showing a page of empty cards |
| **Deployment** | Only for a [deployment admin](permissions.md) — platform totals, health, busiest tenants, ratings |

The organization's view shows the cards that answer with data, grouped into
bands. The rest - integrations, channels, routines, knowledge sync, departments,
members, sandboxes - wait in the catalog, one click away under **Customize**:

| Band | Answers |
|---|---|
| *(untitled, at the top)* | The summary, runs over time and how they ended |
| **Needs attention** | What is waiting: [approvals](governance.md#approvals), recent failures, budget headroom, your most recent [notifications](#the-bell) |
| **Usage & cost** | Which agents are used, spend, when the work happens, where runs come from, model mix, latency, answer quality, who is using it |

Somebody who builds agents also sees **Get started** above the bands until each
of its steps is done: create an agent, publish it, give it a knowledge base, add
departments, invite a teammate and - for whoever may - put an agent in a chat
app. Each step is ticked from what exists, wherever it was done; closing the card
hides it in that browser.

Your own view also shows **Discover AgenticOS**: one tile each for what is easy to
miss - this deployment's own MCP server for Claude Code, Codex or Cursor,
subagents, sandboxes, apps, routines, chat apps, the web browser, knowledge bases
and skills - each leading to where it is switched on, and only those you can use.
Close a tile, or all of them; that too is kept in the browser.

Charts over time pick their own step. The span from the period's first run to now
is drawn in at most 48 points, at the finest step that fits - a minute, five,
fifteen, an hour, three or six hours, a day, a week - so an afternoon's runs read
in minutes and a quarter's in weeks rather than as one spike at the right edge.

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

## The assistant

Every page has the **Architect** in its bottom-right corner: an agent every
organization gets without installing anything, shared with everyone who may run
agents (`agents:run`). It is bound to the
[platform's own MCP server](mcp.md#agenticos-as-an-mcp-server). Ask it which
agents can answer refund questions, why last night's run failed, or what is in a
knowledge base.

Ask it to draft an agent or invite a colleague, and it first shows you what to approve: an
agent draft as the draft itself - where it is created, its name, what it may do
and its instructions - and anything else as the exact call. It acts with your permissions, so it finds
and does what you could, and no more. Its cost counts like any agent's.

A speech bubble above it speaks to what is waiting for you — approvals, an
organization with no agents yet — or to the page you are on, and now and then
offers a tip. Click the bubble to ask it; × silences that page, and the bell in
its window turns the bubbles off. Left unanswered, a bubble fades after a few
seconds. Left alone for under a minute, the button tucks itself into the right
edge of the screen, leaving a sliver to pull it out by - with a dot when
something is waiting - and stays there from page to page until it is opened.

On a phone there is no bubble - it would cover the page it talks about - and the
button carries the dot instead. Approvals it has raised stay raised for the rest
of the browser tab, even when a link reloads the console.

Its window is the console's own chat, not a page inside the page, and opens on
four tiles, so a first message is a click; it keeps its own conversation
history. On a phone it fills the screen.

When it names a page, the link opens in the console behind the window and
points at the control it means — the button that creates an agent, the tab with
the approvals. The camera in its header shows it the page you are on: your
browser asks which tab to share, and one picture is attached to your next
message.

It plans longer jobs as a checklist you can watch, keeps notes about
you between conversations, can tell you what your agents cost, and can undo an
agent draft it made by mistake — never anything else. Besides approvals and an
empty organization, its bubble speaks up when a run of yours has just failed
and when a form has been open, unfinished, for a minute.

Until the organization has a model, it cannot answer. Opening it then types out
a short conversation explaining how to connect one: get an API key from a
provider, open the Architect in the Agent Builder, choose the provider under
**Model** and paste the key, and pick a model. Only somebody who may change the
organization's settings is given the button; anybody else is told who can do it.

The Architect is an agent like any other, so its name, model, knowledge and the
rest of its spec are edited in the Agent Builder - by somebody who may change
the organization's settings, because everyone in the organization runs it. The
organization's page has a card that switches it off for everyone and sets its
greeting. **Settings → Assistant** holds only your own tips.

## Changes made elsewhere

An open page keeps up with changes made somewhere else: a colleague's console,
a script with an [API key](api.md), Claude Code over the
[platform's MCP server](mcp.md#agenticos-as-an-mcp-server), or the Architect.
Each successful write is announced to the organization's open consoles once it
has committed, including the ones only the console makes — sharing, routines,
channel bots, group shares, notification settings — and a list or detail page
with nothing unsaved on it refetches in place. An agent created by a key appears
on the Agents page without a reload, and an agent shared in one tab shows its
new audience in another.

Runs are announced too, as they start, park on an approval or a question, and
finish: a run a schedule fires appears on an open Activity page and changes
status there, with no request from you behind it.

The Builder is the exception, because it saves your draft as you type. When the
agent you are editing changes elsewhere it stops saving and fetches the new
version. With nothing unsaved it simply takes it; with unsaved edits it tells you
who changed it and through what, and waits for you to choose **Reload** (their
version) or **Keep my changes** (yours, saved over theirs).

You only hear about what you could read: a change to an agent, skill, knowledge
base, context file, page, key or MCP server you cannot see never reaches your
console, and a deletion reaches only roles that see every row of its kind. Runs
reach the roles that read run history or decide approvals, channel bots the roles
that manage them, and your notifications only you. When the connection
drops the console works as before and reconnects on its own.

## Chat

Where you talk to a published agent. The picker chooses which agent answers, and
the run behaves exactly as it would in Slack or behind the API — same budget,
same approval gate, same audit trail, because
[every surface goes through one runner](channels.md).

**The list of conversations** says who each thread is with and when it last
moved. One whose run is still at work shows a spinner and how long it has been
going; one with an answer you have not seen since you last had it open carries a
dot, which opening it clears - for you only, since a shared thread is read by each
of its readers separately.

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

**`@` points the agent at something.** Type `@` and a menu offers what the agent
can use, in this order: its MCP servers, the agents it hands work to (with the
delegation capability on), its capabilities - **Sandbox**, **Web research** -
its skills, then its knowledge bases and context files. The pick stays in your
text as `@Name`, marked with its logo, and the agent is told to use it - a
server's tools, a capability's tools, a knowledge base's search, a skill -
without the thing's content being pasted in. Naming an agent hands it the work;
it never changes who answers. Delete the `@Name` and the pick is gone. A link you
paste shows its site's icon above the box and in the sent message. A mention never
widens what the agent may reach: the server checks each one again as you, against
what the agent already has. In the Builder's test panel the menu reads the draft
you are testing. While a conversation is empty, the box cycles through examples
built from what the agent can use - its server, a capability, a delegate, a
skill - and `/`; they are gone the moment you click into it.

**While the agent works**, what you send waits for its answer, as in any chat:
it sits in a queue above the composer and goes out when the run ends. Drag a
queued message, or use its arrows, to change the order. **Send now** puts it into
the running task instead - the agent reads it at its next step and adjusts course
without starting over, and it appears in the conversation where it landed. A
message carrying files always waits for the answer. Slack, Telegram and
Mattermost keep their own behaviour, described in [Channels](channels.md).

**Leaving while it answers.** You do not have to wait for it. Close the tab, quit
the app or open another conversation, and the agent finishes the answer on its
own: it lands in the conversation, and the bell - and an email, if you keep them
for runs that finish or fail - tells you it is there, with a link back to it. A
turn still going after an hour with nobody watching is stopped, and you are told
that instead ([`CHAT_DETACHED_TURN_MINUTES`](configuration.md#a-chat-turn-left-running)).
One that waits on an approval or on your answer to a question tells you through
those.

**On a phone** the chat behaves like a messaging app: the composer stays above
the keyboard and the conversation stays on its last message while it opens,
Enter starts a new line, and attaching a file or dictating sits behind one
**+**. Fields are never small enough for iOS to zoom into them.

**Drawings.** An agent with [Visuals](reference/capabilities.md#visuals) draws
under its message - a diagram, an explainer with sliders, a 3D scene - and you watch
it appear while it is written; its scripts start once it is complete. The panel shows
the whole drawing, sized to the conversation, with buttons to open it full screen,
show its code, download it, copy an SVG as an image, zoom in, and save it as an
[app](artifacts.md#visuals) with a link you can share. When a drawing reports an
error, the agent has already been told; **Fix it** asks again. On a phone a tap opens
it full screen. The dashboard's **Recent visuals** card shows the latest ones drawn for
you, each opening the conversation it was drawn in.

**Watching a browse.** When an agent with the
[web browser](reference/capabilities.md#browser-automation) starts on a page, its
browser draws under the agent's message, live: a window with the address and the page
as the agent sees it, what it is doing now in one line over the page, and its cursor
moving to whatever it clicks or types into. The window keeps a fixed shape and grows
and shrinks with the conversation; several browses at once sit side by side, two to a
row where there is room. The maximise button opens one full screen, and restoring puts
it back under the message. The full list of steps, each with what it was for, is behind
the steps button.

**Taking a browse over.** While a browse runs, **Take over** in the browser's toolbar
pauses the agent after its current step and hands you the page, in the same window:
click, type, scroll, paste. **Hand it back** and the agent carries on from where you
left it. When the agent cannot get past a page alone - a sign-in, a captcha - the browser
says *The agent needs you* and what for. Someone who may view runs but
not edit the agent can watch, not drive. The same window opens on a page of its own
from a channel's link. See [Web browser](reference/capabilities.md#browser-automation).

**Pointing at the page.** The speech-bubble button in the browser's toolbar lets you
click a spot on the page and write a note about it - *this button, not that one*.
**Add to message** puts the page into your message as a picture with the spot ringed,
with your note and the page's address, for you to send or keep writing. It works on a
finished browse too, from its last picture.

**Staying signed in.** When the browse acts for you - your own chat, your direct
message, your own schedule - **Hand it back** offers *Keep me signed in to* the site
you are on. Tick it after signing in, and later browses acting for you start signed
in there: the site's cookies and storage are sealed in the vault for you alone, never
shown, and never used for a widget visitor, a shared room, an API key or an event
trigger. **Settings → Sign-ins** lists the sites you kept, and **Forget** makes the
next browse start signed out. **Sign in to a site** there opens a browser on any site for
you alone, before an agent needs it: sign in, hand it back with the box ticked, and it
is kept the same way. It needs the deployment's sign-in browser
([`BROWSER_SIGN_IN_CDP_URL`](configuration.md)).

## What each area is for

The sidebar groups them. **Build** holds Agents, Routines, Apps and Activity;
**Knowledge** holds Knowledge bases, Documents, Skills and Context. Two groups
fold to their heading until you open them, because they are set up once and
visited rarely: **Connections** (MCP servers, Channels, Vault, Sandboxes) and
**Organization** (Organizations, Groups). A folded group opens by itself on any
page inside it, and stays the way you left it.

| Area | It holds | Read |
|---|---|---|
| **Agents** | The catalog, the Builder, versions, sharing, testing, activity | [Your first agent](first-agent.md) |
| **Chat** | Talking to a published agent | [Surfaces](channels.md) |
| **Knowledge** | Collections, documents, sync sources, ingestion settings | [File processing](file-processing.md) |
| **Skills** | Written procedures an agent loads on demand | [Skills](skills.md) |
| **Context** | Standing knowledge bound to many agents | [Context files](context.md) |
| **Routines** | Schedules and event triggers | [Triggers](triggers.md) |
| **Runs** | What ran, what it cost, what it touched, whether it failed | [Governance](governance.md#audit) |
| **Documents** | Every file agents are keeping for you, what you attached and what they wrote | [The sandbox](sandbox.md#what-the-file-browser-shows-and-what-it-leaves-out) |
| **Sandboxes** | Where agents run code: hosts, live sessions, policy | [The sandbox](sandbox.md) |
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

## Languages

The console speaks English, Polish and German, all of it except the legal
pages, which stay in English. The walkthrough's first card offers the three, and
the account menu changes the language at any time; the choice is remembered in
the browser. Product words - agent, skill, run, budget, MCP and the rest of the
list in [translating](howto/translate.md) - stay English in every language.

## The next step

A page that is empty because nothing exists yet offers the way to make the first
one - an agent, a routine, something shared with a department. Creating a skill,
a context file or a knowledge base ends with a toast offering **Add to an
agent**, for whoever may edit agents, so what was made reaches an agent without a
trip to the Builder.

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
- **Changes made elsewhere arrive on their own** — through the API, MCP or the
  assistant — and the Builder asks before replacing unsaved edits.
- **Slash commands are yours**, built-in ones included, and you can hide the
  ones you do not use.
- A page showing "nothing yet" may be **a failed request**, not an empty
  resource.
