# Putting an agent where people already are

An agent that only answers inside this dashboard is a demo. The same published
agent can answer in five places, and every one of them runs the *same frozen
version* through the same budget, the same approval gate and the same tenant
checks — the surface changes, the agent does not.

| Where | What it needs | Who the visitor is |
|---|---|---|
| **Dashboard** | nothing | a signed-in member |
| **Website widget** | a `<script>` tag | anonymous, or a user your backend vouches for |
| **WebSocket** | a widget key | whatever your integration says |
| **Slack** | a bot token | a Slack account, optionally linked to a member |
| **Telegram** | a bot token | a Telegram account, optionally linked |
| **Mattermost** | a bot token and your server URL | a Mattermost account, optionally linked |

Two rules hold everywhere, and both are enforced in the runner rather than per
surface: **a run always belongs to exactly one organization**, and **a spending
limit is checked before each model request, never after**.

Every run records the surface that admitted it — `playground`, `web`, `embed`,
`api`, `slack`, `telegram` or `mattermost` — which is what the dashboard's
by-surface chart aggregates. Two historical wrinkles: widget runs recorded
before the `embed` value existed are stored as `web`, and Mattermost runs from
the same era as `api`. Neither is backfilled — rewriting history would be a
guess — so charts over old periods fold those runs into the surface they were
recorded under.

---

## The website widget

The shortest path. Publish the agent, create an embed, paste two lines.

### 1. Create the embed

In the Builder, open the agent → **Embeds** → *Publish as widget*. You choose:

- **Allowed origins** — the sites this widget may be opened from. **An empty
  list allows nothing.** The key in the script tag is public by construction, so
  the origin list is what actually stops somebody else running your agent on
  your bill.
- **Auth** — `public` (anonymous visitors) or `jwt` (your backend vouches for
  each visitor; see below).
- **Look** — title, greeting, accent colour, which corner.
- **Context** — a note appended to the visitor's first message: *"You are on the
  pricing page"*, *"Answer in German"*. It never replaces the agent's own
  instructions, which belong to the published version.
- **Rate limit** — messages per visitor per minute.

### 2. Paste the snippet

```html
<script src="https://your-api.example.com/api/v1/embed/PUBLIC_KEY/widget.js" async></script>
```

That is the whole integration. The script has no dependencies, no build step and
no framework — it runs on a page that already loads React, jQuery or nothing at
all.

### 3. (Optional) tell it who the visitor is

For a widget inside your own logged-in product, set a token **before** the
script loads. Your backend signs it; we verify it and never see your user
database:

```html
<script>window.AgenticOSToken = "<%= agenticos_token_for(current_user) %>";</script>
<script src="https://your-api.example.com/api/v1/embed/PUBLIC_KEY/widget.js" async></script>
```

Minting one, in any language that can sign a JWT:

```python
import time, jwt   # PyJWT

token = jwt.encode(
    {"sub": str(user.id), "iat": int(time.time())},
    EMBED_SIGNING_SECRET,          # the secret you set on the embed
    algorithm="HS256",
)
```

- `sub` is required. It identifies the visitor for rate limiting, and a token
  without one is refused — otherwise a single leaked token becomes the whole
  widget's budget.
- `iat` is checked: a token older than 12 hours is refused, so one that leaks
  out of a browser does not work forever.
- Mint it per page load, server-side. Never ship the signing secret to a browser.

---

## The raw WebSocket

The widget is a client of a documented protocol, not a black box. If you want
your own UI — a mobile app, a kiosk, a component in your design system — talk to
the same socket:

```
wss://your-api.example.com/api/v1/embed/PUBLIC_KEY/ws[?token=SIGNED_JWT]
```

The handshake must carry an `Origin` on the embed's allow-list; browsers send it
for you. Native clients must set it explicitly.

**Frames you send**

```json
{ "type": "message", "text": "Do you ship to Poland?" }
```

**Frames you receive**

| `type` | Meaning |
|---|---|
| `ready` | Connected. `visitor: true` when a token identified the person. |
| `typing` | The agent is working. Show an indicator. |
| `message` | The answer: `{ "role": "assistant", "text": "…" }` |
| `error` | Something the visitor should see: rate limit, budget reached, failure. |

**Close codes**

| Code | Meaning |
|---|---|
| `4003` | Refused. The origin is not allowed, the token failed, or the widget is paused. Do not retry — the answer will not change. |

The refusal is deliberately one code with one message. A page that is not on the
allow-list learns that it is not allowed and nothing about whether a token would
have helped.

A minimal client:

```js
const socket = new WebSocket(`${BASE}/api/v1/embed/${KEY}/ws`);
socket.onmessage = (event) => {
  const frame = JSON.parse(event.data);
  if (frame.type === "message") render(frame.text);
};
socket.send(JSON.stringify({ type: "message", text: "hello" }));
```

---

## Slack

1. Create a Slack app, add a bot user, install it to the workspace.
2. Register the bot: **Settings → Channels → Add bot**, platform `slack`, paste
   the bot token.
3. Either point Slack's Events API at
   `https://your-api.example.com/api/v1/slack/BOT_ID/events`, or run Socket Mode
   (add the bot's `xapp-` token in its settings) and expose nothing.
4. Bind the agent: Builder → the agent → **Available in** → the bot.

Works in channels and in DMs. A thread gets its own conversation, so two people
asking different things in the same channel do not end up in one thread of
context. `@agent-slug` inside a message routes to *that* agent and runs as the
person who typed it — never as the bot — which is why an unlinked Slack account
is refused rather than run with no role.

## Telegram

1. Create a bot with @BotFather, copy the token.
2. **Settings → Channels → Add bot**, platform `telegram`.
3. Register the webhook from the UI, or run polling in development — no public
   URL needed.

## Mattermost

Mattermost is self-hosted, so a bot carries **your server's URL** as well as its
token. Two ways in; pick by whether your Mattermost can reach this deployment.

**Event stream (nothing exposed).** Create a bot account
(*Integrations → Bot Accounts*), copy its token, register it here with the
server URL — for example `https://mattermost.acme.internal` — and the deployment
opens an authenticated WebSocket to it. This is the right choice behind a VPN.

**Outgoing webhook.** *System Console → Integrations → Outgoing Webhooks*,
pointing at `https://your-api.example.com/api/v1/mattermost/BOT_ID/webhook`.
Copy the token Mattermost generates into the bot's webhook secret here.

Mattermost does not sign webhook bodies the way Slack does — the token in the
payload is the whole check — so **a bot with no webhook secret refuses every
call** rather than trusting it.

## A bot that cannot start stops, rather than retrying

Slack Socket Mode and the Mattermost event stream both run under a supervisor
that reconnects a dropped session. A missing configuration value is not a
dropped session, and the supervisor treats it differently: it logs once and
stops. Nothing it does would change the row — an operator has to add the Slack
`xapp-` token or the Mattermost server URL.

This matters more than it sounds. Retrying a start that fails immediately never
suspends, so the supervisor spins without yielding and every other task on the
process — requests, health checks, chat WebSockets — stops being scheduled. The
API stays up and answers nothing. Both trigger states are ordinary rows somebody
has not filled in yet, so the failure was one restart away at any time.

If a bot is silent, check the log for `not started` before assuming a network
problem.

A dropped session is different: that one is retried, waiting five seconds and
doubling to a minute, so a Mattermost server down for an hour is not hammered
720 times by every bot on it. The line logged before each wait names the delay
it is about to wait.

---

## What every channel shares

- **Access policy per bot** — open, whitelist, or "must be linked to a member".
- **Linking** — a channel user runs `/link` to connect their Slack, Telegram or
  Mattermost account to their account here. After that the agent runs as them,
  with their permissions.
- **Rate limits** per chat.
- **Spending limits** per binding, on top of the agent's own and the
  organization's.
- **Charts render as images** where the platform supports them, and fall back to
  a text table where it does not.
- **What a turn cost**, said or only recorded — see below.
- **Files, both directions** — see below.
- **Who shares a workspace, per surface.** An agent's spec sets the default; each
  binding may override it, because a web chat and a Slack channel are not the same
  sharing question.

### What each surface records

Every surface reaches the same runner, so every run gets its row — its cost, its
status, its tokens, and the budget enforced against it. It also gets its
**transcript**: the question, the answer, and every tool call with the arguments
it was made with and what came back. That matters because a run's drill-down is
read from those rows — what nothing wrote, no page can show.

For everything except web chat the transcript is written by the runner, not by the
surface. It used to be the surface's job, and four of them did not do it: the
widget, a mention, the API and every resumed run recorded nothing at all, so an
organization was billed for an answer with no row saying what was asked. A thing
every surface has to remember is a thing the next surface will not.

Web chat still writes its own, because it has events to attach and a socket to
answer on — and it writes on both endings. **A turn that does not finish is
recorded as far as it got**, from the same text the client was streamed, so what
is stored is what its reader actually saw.

| Surface | What reaches `messages` and `tool_calls` |
|---|---|
| Web chat, run finished | Everything — prompt, reasoning, tool arguments and results, model and version |
| Web chat, run interrupted | The same, as far as it got. A run that failed, hit its budget, was stopped or lost its socket keeps the words already streamed, attributed to the version that produced them, with no cost figure invented for it — the run row is where the accounting lives |
| A channel bot's default agent | Everything except the reasoning, which only a streamed run exposes |
| `@mention` on a channel | The same, with the handle stripped from the recorded prompt |
| Embedded widget | The same. The visitor is anonymous; the run and the turns belong to the widget's owner |
| HTTP API | The same when the call carries a `conversation_id`. Nothing without one — there is no thread to write a turn into, and the run row is still the record that it happened |
| A run resumed after an approval | Its continuation — the answer and the calls it made. No user turn: it picks up at the call it stopped on, and inventing a question would put words in somebody's mouth |

Two things are deliberately not recorded. A channel reply's **delivery notes** — *this
file was too large to send* — stay out of the transcript: they are about what the
reply could not carry, not about what the agent said. And an **attachment folded
into a prompt** contributes only its text; the file itself is a row of its own,
and its `repr` in a message body would be worse than nothing.

### What a turn looks like in web chat

**The work is a narration, not a stack of cards.** Each tool call is one line — *Wrote
test1.md*, *Searched for TODO in app.py*, *Ran pytest -q*, *Linear · Create issue* —
written in the tense it is true in: present while the call runs, past once it has. The
line names the *subject* rather than the function, because `write_file` is not what
anybody wants to read. Every line opens into what the call actually produced, and the
raw arguments and output stay one click further in for whoever is debugging one.

Consecutive calls hang from one rail, and **only the last row stays visible**: earlier
ones fold into "4 earlier steps", which says work happened without pushing the answer off
the screen. A run holding a failure or a call parked for approval is never folded — that
is the one line in the turn that is asking for something. Nothing marks a step that
simply worked, so a marker means what it says.

**What opens itself follows what somebody is watching.** A call that finishes while the
turn is streaming opens on the spot — a chart, code that ran, a file that was written is
the answer, not a footnote to it. A conversation *reopened* shows one line per past call
and keeps open exactly one: the last call of the most recent turn that **used a tool**,
which is the result the reader came back for. The most recent *turn* is the wrong anchor
and was the first way this was written - an agent that writes a file and then answers
about it in prose ends the transcript with text, and the file it had just written was
folded away. Opening every finished call on mount turned a reopened chat into a wall; opening
none of them hid the thing that was asked for.

**A write ends in the file, not in a sentence about it.** `write_file` answers "Wrote 1
lines to /workspace/test1.md"; what the transcript shows is a card naming the file, with
*Open* — the same viewer the Workspaces screen uses — and *Download*. The path is
resolved against the conversation's own listing rather than trusted from the arguments,
because a tool called with `test1.md` reports `/workspace/test1.md` and the workspace may
store either; with no match the card is drawn without controls that would fail.

**An MCP call is named by its server.** Nothing on a tool call records where it came
from — the only trace is the prefix the backend puts on a connection's tools, which is
the connection's name — so the frontend matches that prefix against the servers the
caller can see and shows the server's own logo beside the step. A miss reads as the
humanised tool name, which is what it read as before.

**A delegation is a panel, not a pause.** When the agent hands work to
[a delegate or a specialist](concepts.md#delegate-vs-inline-specialist), that
delegation is a second agent's whole conversation happening inside one turn of the
first — left alone it is a tool call named `task` that goes quiet for thirty seconds.
So it streams into a panel of its own: which specialist is working, its text and its
reasoning as they are generated, its *own* tool calls (which may reach a collection
the parent cannot even see), and on close its status, its tokens and its share of the
turn's cost. Every frame carries the delegation's task id and its depth, because a
fan-out of three is three panels and interleaving three specialists into one
paragraph is worse than not streaming at all — and an opening frame carries the task
id of the delegation it was made *inside*, so a specialist that delegates further
nests under the right panel rather than under whichever one started most recently.
A child's text is never folded into the
parent's answer: that would put words in the parent's mouth its own model never
generated, and the conversation is persisted with them.

A delegate can stop for a person too — a gated tool inside a specialist parks the
whole turn in the approval queue. The panel then closes into a *waiting for a
person* state rather than spinning on "working" for as long as the approver takes,
and the delegation keeps the task id it parked under so its identity survives the
resume rather than a second panel appearing beside the first. The resume itself
runs over HTTP (`POST /runs/{id}/resume`), which carries no delegation frames, so
the waiting panel is moved to the resumed run's own outcome — completed, failed or
cancelled — from that answer; a resume that parks again on a fresh decision leaves
it waiting.

The assistant's answer is **not** in a bubble; only the person's message is. An answer
is prose with headings, code and tables in it, and a rounded fill around that fights
every one of them.

**Every word on any of these screens comes from `frontend/messages/en.json`.** English
is the source language and `pl.json` holds only what has actually been translated -
`src/i18n.ts` merges English underneath every locale, so a missing translation renders
English rather than the key. `make lint` runs `scripts/check_i18n.py`, which fails both
ways: on copy left in a component, and on a key a component reads that the catalog does
not hold.

### A delegation on a surface that cannot show one

Every other surface — Slack, Telegram, Mattermost, the embedded widget, the REST
API — gets no delegation frames at all. The delegation still runs and is still recorded; it is
simply not narrated, the same arrangement `ask_user` has.

That default is load-bearing rather than convenient, and it is the one thing to know
before adding a surface that wants the panels. **Attaching a handler to a delegation
changes the transport, not just the observability**: the library drives each child
through `iter()` and opens a *streamed* request for it. So a delegate whose model or
provider cannot stream works perfectly from the API and stops working the moment
somebody opens the chat window — the same published version, the same agent, failing
on one surface. Which is why a handler is attached only where a sink exists, rather
than unconditionally for the benefit of the one surface that draws them.
`tests/test_subagents_library_contract.py` pins that property of the library, so a
release that starts falling back to a plain request turns red and says so.

### Files

Somebody dropping a spreadsheet on a bot used to have it discarded: `IncomingMessage`
had no attachment field, so no adapter parsed one and the agent answered about a
document it never received. Now a message with a file — with or without a caption —
reaches the agent the same way a web upload does.

**Inbound** is the web upload path reached differently. The bytes come from a
platform instead of a browser and then go through exactly what a web upload gets:
the MIME allowlist, `MAX_UPLOAD_SIZE`, the parser, storage, and a `ChatFile` row.
A bot is the most permissive edge this platform has — anyone in a channel can drop
a file on it — so it must not also be the lenient one. From there the file follows
the routing in [File processing](file-processing.md): pasted inline for an agent
with no workspace, written to `/uploads` with a reference for one that has it.

The size is checked twice on purpose: against what the platform *claims* before
anything is fetched, because downloading a gigabyte to then reject it is the
attack, and against the bytes afterwards, because a claim is not a measurement.

Fetching a file needs a second authenticated request on every platform, which is
why an attachment arrives as a handle rather than as content:

| | |
|---|---|
| Slack | The private URL on the event, fetched with the bot token. Slack answers **200 with a sign-in page** rather than 401 when the token cannot read a file, so the content type is checked — otherwise a login page would be stored as the user's spreadsheet |
| Telegram | `getFile` resolves a `file_id` to a path that expires, then the file API. A photo arrives as several sizes; the largest is the one kept |
| Mattermost | `/files/{id}` on that bot's own server. A bot whose server is not recorded says so rather than guessing which company's server to send a token to |

**Recordings are not supported yet.** Telegram puts each kind of media in its own
field, so a voice note arrives with no text at all — and until this change it parsed
as nothing and vanished with no log line. It is now read, refused, and the refusal
says what is actually true: the recording arrived and nothing here can listen to it
yet. Transcription is [#54](https://github.com/vstorm-co/agenticos/issues/54); when
it lands, audio joins the allowlist and that refusal goes.

A file that is refused — unsupported type, a recording, too large, a download that
failed — is **named in the reply**. One bad file among three does not lose the other two or the
question that came with them, and a bot that silently ignores an attachment looks
exactly like a bot that read it.

**Outbound** is what the agent wrote this turn, compared against a snapshot taken
when the workspace opened. Not a diff of everything: `/uploads` is the user's own
file — posting it back is quoting somebody their own attachment — and `/skills` is
know-how the platform materialised, not the agent's work. A file it *overwrote* is
not sent either: rewriting a script it is iterating on is ordinary, and posting it
every turn would fill the channel with the same attachment.

**If that snapshot could not be taken, nothing is posted.** The comparison is
"everything now, minus everything then", so treating an unreadable workspace as an
empty one would make every file already in it read as this turn's output — and under
`agent` or `channel` scope those files belong to other people. A missing attachment
is the failure worth having; a colleague's spreadsheet in a shared channel is not.

Each file carries the type its name implies rather than a flat
`application/octet-stream`, so a chart an agent wrote arrives as a picture on the
platforms that read the field instead of as a blob somebody has to download to
identify.

Capped at 3 files and 8 MB each, below every platform's own limit so the refusal is
ours and can be explained rather than arriving as an opaque API error. Anything past
the cap is named in the reply and stays in the workspace.

A chart stays separate from all of this. It is a *photo* on these platforms,
rendered inline, which is the whole point of the `charts` capability — folding it
into the attachment list would make every chart arrive as a download.

### Saying what a turn cost

A bot that stops answering because its organization hit its monthly cap looks
broken. The only difference between "broken" and "out of budget" is somebody
having said so beforehand, so a bot can report what a turn spent: tokens, cost,
how much of the month is gone, and how full the workspace behind it is.

In web chat the same two numbers sit under the composer, and they come from
different places because they measure different things. **The cost** is the newest
measured answer *in the conversation on screen* — read from the transcript, so it is
there when a thread is reopened rather than after the next message, and filtered by
conversation id because the store still holds the previous thread's messages for the
moment between the click and the fetch landing. It reported those under the new
conversation until it was. **The fill** is the workspace as it stands now: a live turn
reports it (a container's resident memory can only come from its host), and a reopened
conversation reads it from the workspace listing, which carries the ceiling a stored
workspace fills up against. Without that, "workspace 0% full" appeared only after
somebody sent a message — the one moment nobody needs it.

Per bot, in the channel bots panel:

| Mode | |
|---|---|
| `log only` | Recorded and not said. Unspoken is not unmeasured — "the bot went quiet" is a question somebody asks days later |
| `near a limit` | Said once the budget or the workspace passes a threshold (80% by default). **The default** |
| `every n messages` | Said every n-th turn *of that chat*, not of the bot |
| `every reply` | Said every turn |

`near a limit` is the default rather than `log only`, because defaulting to
silence would leave every already-registered bot in exactly the state this exists
to prevent. And rather than `every reply`, because a footer under every message in
a busy channel is the other way to make a warning useless.

The workspace counts as well as the money. A stored workspace that fills up starts
*refusing writes*, which the agent reports as a tool error in the middle of doing
something — a bot that only watched the budget would go quiet on the other limit
with nothing said.

Measuring costs something for a container: its memory is a round trip to the host
per sandbox. So `log only` never asks, and every other mode asks about one session
rather than listing them all.

In `/chat` there is no noise argument, so the numbers are always sent — the client
draws them under the input and decides what to show. Three things it shows that a
channel footer does not:

- **The agent's own cap first**, and the organization's only past 80%. The
  organization's stops every agent at once and belongs to somebody else; the
  agent's own is the one whoever is looking at it can raise.
- **Input and output separately**, under each answer as well as under the input.
  They are priced an order of magnitude apart, so a total cannot say whether a turn
  was expensive because of a long context or a long answer — and the strip only ever
  describes the *last* turn, which in a long conversation hides which answer cost
  the money. Live turns only: usage is measured when a run finishes and is not
  stored per message, so a reloaded conversation shows none.
- **The files themselves**, in a panel beside the transcript reading
  `GET /conversations/{id}/workspace`. It re-reads when a turn ends rather than on a
  timer, and it is absent entirely — not empty — for an agent that keeps no files,
  which is most of them. It names whose files these are, because under `agent` scope
  one workspace is shared and finding a file you never created reads as a leak until
  something on screen explains it. A file is a tile, and opening one opens the same
  viewer the Workspaces screen uses — a picture, a PDF, markdown as preview or
  source, and always a download — reading `…/workspace/file` for text and
  `…/workspace/raw` for bytes. Through the *conversation* rather than the
  workspace id, deliberately: that is what keeps these files reachable for
  somebody the chat was shared with.

### Overriding who shares the workspace

On Slack, `thread_ts` is folded into the chat id — so a thread *is* a
conversation, and an agent whose spec says `conversation` gets one workspace per
thread. In a busy channel that is fifty containers and a `429` for the fifty-first
person to reply. The binding can say `channel` instead, and every thread in that
channel shares one.

The choices are the same as the spec's (`run`, `conversation`, `channel`, `user`,
`agent`), plus "as the agent says", which is the default and stores nothing. The
control is on the binding in the Builder, and it appears only for an agent that
keeps files at all.

`user` scope is what carries a workspace *across* surfaces: a person who starts in
web chat and continues in Slack is one `ChannelIdentity` linked to one account, so
they find the same files. `conversation` and `channel` deliberately do not — those
name a place, and a place does not follow somebody to another platform.

## Choosing

- Your own site, no accounts → **widget, `public` mode**.
- Inside your product, per-user → **widget, `jwt` mode**.
- Your own interface entirely → **WebSocket**.
- Where the team already talks → **Slack, Telegram or Mattermost**.
- Another system entirely → the REST API (`POST /api/v1/agents/{id}/run`).
