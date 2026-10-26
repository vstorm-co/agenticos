# The console

The console is the web application everything else on this site is configured
through. This page is the map: what each area is for, and which page explains it
properly.

If you are looking for one screen, the fastest route is the **"?"** in a page's
header — it replays that page's walkthrough, and a page whose header carries no
"?" has no walkthrough to replay. Chat has no header: its tips are under the chat
settings, the sliders beside the microphone.

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
| **Usage & cost** | Which agents are used, spend, [voice minutes](#voice-calls), when the work happens, where runs come from, model mix, latency, answer quality, who is using it |

The dashboard opens with **Get started** until each of its steps is done: tell
agents about yourself, start a conversation, connect a service with your own
account, set up a routine and build an agent - that one is a question to the
Architect, which builds it with you. Somebody who builds agents has the
organization's steps after those: publish an agent, give it a knowledge base, add
departments, invite a teammate and - for whoever may - put an agent in a chat app.
Each step is ticked from what exists, wherever it was done, not from a click on the
card; closing the card hides it in that browser.

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

## The inbox { #the-inbox }

**Inbox**, under Chat in the sidebar, is what the platform brought you on its
own: what your [watches](governance.md#proactive-work) found in your connections
and what the nightly look proposed. The number beside it is how many wait. It
reads like a mailbox: one row each, urgent ones first, where it came from and
when, and the answers in the row. Filter by where they came from, or open
**Done** for what you already took or declined, and bring a declined one back.
**What they found** on the Watches card under Routines opens it narrowed to
watches. Shorter rows head your dashboard as **Briefing**, and the empty chat
with the starter agent offers the first of them as a card, with a link to the
rest.

What a watch finds that need not be heard at once waits for your morning: at
the hour your organization's proactivity keeps, one notification and one direct
message from each of its Slack, Teams and Mattermost bots that knows you list
what is new. Each finding is in one briefing only.

## The bell

Next to search, in the sidebar: a running count of what you have not read yet,
and a click opens the list itself. Unlike the widget above, opening it fetches
the page you are looking at, not a five-card preview - **Load more** keeps
paging back through the organization you are currently in, plus anything
addressed to the deployment as a whole, until it reaches what has aged out.

Each row starts with what it is about: the agent's face, with a badge for how
its run went, or an icon for the kind of event - green for a finished run or an
MCP server back up, red for a failure or a spent budget, amber for an approval
or a budget warning.

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

Tell it what an agent should do and it builds one with you, one question at a
time, each with proposed answers: it picks the capabilities, the knowledge base
and the model, says why in a line, drafts the agent, tries it on your own
questions as the unpublished draft, fixes what was wrong, and publishes it when
you approve. It sets up a routine the same way.

Before anything changes it shows you what to approve: an agent draft as the
draft itself - where it is created, its name, what it may do and its
instructions - and anything else as the exact call. It acts with your
permissions, so it finds and does what you could, and no more. Its cost counts
like any agent's.

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
you between conversations, can tell you what your agents cost, and deletes
nothing but an agent draft it made by mistake and a routine you ask it to
remove. Besides approvals and an
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
skill - and `/`; they are gone the moment you click into it. Above it, the cards
are the agent's own **first messages**, set under its instructions in the
Builder; an agent with none offers the chat's own four, two of them to ask what it
can do and to set up a routine.

**Under an answer.** An agent with [Follow-ups](reference/capabilities.md#follow-ups)
offers up to three next steps as buttons under its latest answer, and a click
sends one. A line says what it noted about you, or forgot, with **Manage** for
[the notes themselves](reference/capabilities.md#memory-files) - ask it to forget
something and it does. When a request needs a capability the agent lacks, a card
asks to switch it on, or to ask the agent's owner
([how](reference/capabilities.md)).

**Keeping a request that worked.** Hover your own message: the calendar turns it
into a routine - the same prompt, weekly by default, on the agent that answered -
and the robot asks the Architect to build an agent that does it. Hover the answer
and the bookmark asks the Architect to make a [skill](skills.md) of how it was
done, so any agent can do it the same way next time; it is handed your request
and the answer, and offered to whoever may write skills.

**Links that point.** A console link an agent writes in its answer - "here is the
button that connects your Gmail" - opens that page without reloading the console,
and a `?highlight=` in it points at the control it names, as the Architect's
links do.

**The AgenticOS agent gets to know you.** While your account says nothing about
your role or your work, a greeting starts a short interview: what you do, what
fills your week, which tools you work in - one question at a time, each with
answers to pick. What you say is saved to your profile, so every agent knows it
from then on, and the interview ends with up to three cards to set up - a
routine, a service to connect, an agent of your own - each one click. Skip a
question, or ask for something real, and it does the work instead.

**What it noticed overnight.** Where your organization turned it on, once a day,
early in your morning, the platform looks at your recent conversations in a
background job: a request you keep
repeating becomes a proposed routine, what an agent learnt about your role
becomes a proposed profile, and your empty AgenticOS chat gets first messages
written for your work. Proposals wait as cards in that empty chat, on your
dashboard and in the bell, and **Settings → Assistant** lists them all - bring a
dismissed one back there, or leave yourself out; accept one and it is set up, dismiss it and the same proposal is never
made again. Nothing runs when nothing new happened, and what this may spend is
[capped per person](governance.md#proactive-work). A chat link with
`?agent=<slug>` opens the chat on that agent.

**Working hours** under **Settings → Profile** tell agents when you work, so a
routine they propose lands inside your day. Nothing waits on them: they are
knowledge for the agent, not a schedule.

Reopening a conversation shows its newest messages first. Use **Load earlier messages** above the transcript to read older turns. Live answers and unsaved results stay visible while stored history refreshes.

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
those. Come back while it is still answering - to the conversation, from
another tab, after a reload - and the chat picks the answer up where it is,
with everything it has done so far, and goes on drawing it as it arrives.

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

**Stopping a waiting run.** The composer keeps **Stop** available while the agent waits
for your answer, an approval or an account connection. It also works after you reload a
parked question or approval. Stopping a parked run closes its pending calls without
asking the model to continue and preserves the cost already recorded. You can stop your
own run; approval deciders can also stop a run awaiting approval. If a temporary error
prevents stopping, the card stays available for retry.

### Dictation

The microphone sits beside Send for every agent, and in the `+` menu. It turns
speech into text in the box and never sends it: what you said lands where the
caret was when you pressed the microphone, ready to edit, and goes nowhere until
you press Send. How it transcribes is the agent's choice, made on the Dictation
tab of [its Voice card](#an-agents-voice-card):

- **Transcribe with a provider** on — the browser records, and this deployment
  sends the recording to the agent's provider or the organization's default. It
  works in every browser that can record. See
  [Dictation in chat](ml-services.md#dictation-in-chat) for the endpoint, its
  limits and what is recorded.
- Off, or with no key to send it with — the browser's own speech recognition, so
  the audio goes to the browser vendor (Google, Apple) and costs nothing.
  Firefox has none: its microphone says so when pressed. While it listens, a
  note above the composer says the agent's Dictation is off, and links whoever
  may edit the agent to its Dictation tab.

With a provider, pressing the microphone floats a **recording pill** above the
composer, which does not change: Cancel, the level, a timer and Stop. **Enter**
stops and transcribes, **Escape** cancels, and nothing typed or pressed while a
recording is running or being transcribed is sent. The recording stops by itself
at the organization's longest dictation and is transcribed, and a microphone
unplugged mid-way ends it the same way rather than discarding it. While the
recording uploads, the pill shows how much has gone up, once that takes longer
than a second; after that it says **Transcribing** until the text arrives. The
browser's recognition has a pill of its own, with **Done**.

Everything dictation has to say appears in a strip above the composer, beside
the pill: the permission prompt, a blocked or missing microphone, the last 30
seconds, five seconds without sound, a recording under a second (not sent), a
recording that stopped at the limit, and every failure. How many words were
inserted is announced to a screen reader rather than shown, since the words are
in the box. A recording that failed to transcribe is kept until you press
**Retry** or **Discard**.

The glow around a hosted page's box while you speak follows **Voice glow** under
**Settings → Profile → Appearance**, beside the theme and **Motion**: **Vivid**,
**Subtle** (the default) or **Off**. It is remembered per browser. **Motion**
decides how much the whole console moves: **System** (the default) follows the
operating system's reduced-motion setting, **Reduce** turns motion down without
it, and **Full** keeps it whatever the operating system says. While motion is
reduced there is no glow at all, the strip appears without sliding, and the level
is a five-step indicator.

### The Voice card

On the organization's **Members** page, for somebody holding `org:settings`. It
holds the speech-to-text **default** agents and channel bots inherit, and how
long a dictation may run; whether an agent dictates with a provider, or takes
calls, is switched on in that agent's own Voice card. **Max recording length**
is from 10 seconds to 10 minutes. **Default provider** is the provider and model
from the speech-to-text catalog and a language (auto-detect, or one fixed
language, which is more accurate). It is also what
[channel bots](channels.md#what-every-channel-shares) set to inherit send their
voice messages to; **None** clears it.

**Key**, beside the provider, is the vault key the default is sent with. It
lists the API keys whose purpose is that provider and that the whole
organization can see - the platform spends this key for every member's
dictation and every inheriting bot, so a member's private key is not offered and
is refused if sent. With exactly one such key it is chosen for you, and saved by
name either way; nothing picks a key at run time. A provider with no key is
marked **no key for this provider** and the picker links to the vault to add
one. Where the default cannot run - the model was withdrawn from the catalog, or
the key was deleted or made private - the card says so, and asks to **choose a
key** where that is what is missing.

For somebody who also holds `runs:view`, the card opens with one line on what
the organization transcribed in the last 30 days — "42 min · 118 recordings (30
without a length)" — across dictation, channel voice messages and the API.
**Show breakdown** lists it by agent and by channel bot. The minutes count only
recordings whose length was reported, so the line says how many were not; it is
hidden while nothing has been transcribed. The figures come from
[`GET /ml/calls/summary`](ml-services.md#what-is-recorded).

### An agent's Voice card

An agent's **Build** tab has a **Voice** card after its model settings, with two
tabs: **Voice calls** and **Dictation**.

**Dictation** holds **Transcribe with a provider**. On, the chat microphone
sends the recording to a provider: **This agent's own** (the default) picks a
pair from the catalog and the key to send it with - an API key for that provider
that you can view, since publishing lends it to everybody who can run the agent
- and, until you choose one, the organization's default is used and named.
**Organization's** keeps the organization's provider, model and key. Off, or
with no key to send it with, the browser transcribes instead, which costs
nothing.

The language is chosen on its own: inherit the organization's, or fix one - so a
Polish agent can keep the organization's provider and key. The card is part of
the spec, saved with the draft and live once the agent is published, and it
applies to [dictation](#dictation) into this agent and to voice messages its
channel bots inherit. [The order](ml-services.md#which-engine-a-recording-reaches)
has the rest.

### Voice calls

A [voice call](voice.md) is a spoken conversation with a published agent: you
talk, it answers aloud, and you can interrupt it. Calls are switched on in the
agent; the organization has no call settings.

- **The agent's Voice card**, on its **Voice calls** tab: the call provider and
  model (for Azure, the deployment name and its base model), the key, the voice
  with a **play** button to hear it, the spoken language (or **Follow the
  caller**), the **Longest call** (10 minutes when unset, at most 50) and
  **Instructions for calls**. The card lists what the agent
  [hands to its text model](voice.md#handing-work-off) in calls, says that
  guardrails cannot filter spoken words before they are heard, and that calls
  are recorded as text with no audio kept. It takes effect when the agent is
  published.
- **An embed's Voice calls switch**, in the widget and hosted page forms - see
  [Channels](channels.md#voice-calls-on-a-widget-or-a-hosted-page).

Before offering a call, the console asks whether this agent can take one
(`GET /agents/{id}/voice`), so nobody grants the microphone only to be refused.
The answer names what is missing: no voice set up on the agent, the model no
longer offered, or no key.

The **call button** stands in the chat composer where Send is, for every agent,
while the box is empty; type something and Send comes back. Where this agent cannot take a call it is crossed out, and hovering,
focusing or pressing it says why. Somebody who may edit the agent gets **Open in
the Agent Builder**, which opens its Voice card on the Calls tab; anybody else is
told to ask someone who can.

During a call a **pill** floats above the composer, which stays as it was, a
draft and attachments included: what the call is doing, its time, a waveform of
both voices, push-to-talk, mute and **End**. Only End ends a call; opening
another conversation or a new chat hangs it up. Talking is hands-free by
default; **push-to-talk** (hold the button or Space) is a choice remembered in
your browser. With reduced motion a stepped level meter replaces the waveform.

A call moves through states the pill names: connecting, listening, you
speaking, thinking, the agent speaking, interrupted, working on a tool, waiting
for your approval, an approval you cannot give, almost out of time, and ended -
by you, by a limit, a dropped connection or a failure.

The call happens in the conversation: each turn is drawn as the message it
becomes, growing word by word as it is spoken, a screen reader hears each line
once it is final, and the saved message takes its place without anything
moving, so the call is in your history afterwards and you can carry on typing.
While the agent thinks or runs a tool, the conversation says so where its answer
will appear.

**Approvals** are decided in the call: a card in the conversation shows the
tool, its exact arguments and what you were heard to say, with a 60-second
countdown. Only its buttons decide; saying "yes" does not. Without
`approvals:decide` the card says the tool needs an approval you cannot give by
voice, and offers to end the call and continue in text. **Questions** the agent
asks appear as the chat's question card, read aloud as well: tap an answer, or
just say it. Work the agent [hands to its text model](voice.md#handing-work-off)
shows each step while it runs, and the steps stay on the turn afterwards.
**Limits** are spoken: a minute before the longest call ends you are warned, and
when the time or the budget runs out the agent says one sentence and the call
ends.

A **strip above the composer** points to whatever needs you: the microphone
prompt, an approval waiting (with **Show card**), the last minute, a limit
ending the call, a reconnect, or how push-to-talk works. When the call ends, a
card in the conversation says how long it ran and how many turns were saved, or
which limit ended it, with **Call again**. A call that never started says why
above the composer, with **Try again**.

In **Activity**, a call is one row with a microphone badge, and the kind filter
(**Text** or **Voice calls**) narrows to calls; a call that reconnected is still
one row, with every connection's time and cost summed. The **Voice minutes**
dashboard card, in the Usage band for a holder of `runs:view`, shows the
period's call minutes and calls and the top three agents.

## What each area is for

The sidebar groups them. **Build** holds Agents, Routines, Apps and Activity;
**Knowledge** holds Knowledge bases, Documents, Skills and Context. Two groups
fold to their heading until you open them, because they are set up once and
visited rarely: **Connections** (MCP servers, Channels, Remote agents, Vault, Sandboxes) and
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
| **Channels** | Slack, Teams, Telegram and Mattermost bots, widgets, hosted pages | [Surfaces](channels.md) |
| **Remote agents** | Other vendors' agents, registered by their A2A agent card, that agents delegate to | [Capabilities](reference/capabilities.md#remote-agents) |
| **Vault** | Credentials, sealed per organization | [Secrets](secrets.md) |
| **Organizations** | Members, roles, invitations | [Permissions](permissions.md) |
| **Settings** | Providers, ingestion defaults, notifications, your own profile | [Configuration](configuration.md) |
| **Admin** | The deployment itself: users, tenants, system, background jobs, deployment settings | [The deployment](deployment.md) |

The **Agents** catalog can be filtered by **category** and **tag** — the editable,
organization-local labels shown on each agent's card. Each filter is a menu of the
labels on the agents you can see; tick several to widen it. You maintain an agent's
categories and tags from its detail page, beside the avatar controls, and the
change takes effect at once, without publishing a new version.

## Languages

The console speaks English, Polish and German, all of it except the legal
pages, which stay in English. The walkthrough's first card offers the three, and
the account menu changes the language at any time; the choice is kept on your
account, so the console opens in it on every device you sign in on. You can also
ask an agent - "switch to English" - and the page changes as it answers, without a
reload. Every agent answers in it unless you write in another language. Product
words - agent, skill, run, budget, MCP and the rest of the list in
[translating](howto/translate.md) - stay English in every language.

The same card asks what you do, and **Settings → Profile** keeps the rest of what
agents know about you: your role, what you work on and your time zone. Every agent
reads them at the start of a run, so you never repeat them in a chat; "every Monday
at 9" is your 9. The time zone is taken from your browser the first time you sign
in, until you choose one.

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

- The dashboard is **thirty-eight widgets** you arrange yourself, saved per
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
