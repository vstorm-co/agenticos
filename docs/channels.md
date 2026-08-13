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

### 3. (Optional) tell it about the visitor

A widget can **declare variables** - a name, whether it is required, and a line
saying what it is for - and the page supplies them:

```html
<script>window.AgenticOSContext = { plan: "pro", locale: "pl" };</script>
<script src="https://your-api.example.com/api/v1/embed/PUBLIC_KEY/widget.js" async></script>
```

The snippet the Builder hands you already carries that line, with your own keys
in it, once you have declared any.

They are appended to the agent's instructions as a marked block of data, under a
line saying they are information about the visitor rather than instructions, and
that they cannot be verified. That last part is true of every one of them,
including on a `jwt` widget: the widget reads `window.AgenticOSContext`, and a
token authenticates *who the visitor is* rather than *what the page said about
them*. So nothing here may decide what the agent is allowed to do.

Three rules follow from that:

- **A key nobody declared is dropped.** The page is something a visitor can
  edit; without a declaration, any key they invented would become a line inside
  an agent's instructions.
- **A missing required value omits its line and is logged.** `required` is a
  promise between an integrator and themselves - enforcing it would cost a
  visitor their answer over somebody else's deployment mistake.
- **Sent once per conversation**, ahead of the first question, and read from
  every frame rather than at connect time: a single-page application learns who
  somebody is without reconnecting.

### 4. (Optional) tell it who the visitor is

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
2. Register the bot: **Channels → Add bot**, platform `slack`, paste
   the bot token.
3. Either point Slack's Events API at
   `https://your-api.example.com/api/v1/slack/BOT_ID/events`, or run Socket Mode
   (add the bot's `xapp-` token in its settings) and expose nothing.
4. Bind the agent: Builder → the agent → **Availability** → the bot.

Works in channels and in DMs. A thread gets its own conversation, so two people
asking different things in the same channel do not end up in one thread of
context. A message runs as the person who typed it — never as the bot — which is
why an unlinked Slack account is refused rather than run with no role.

## Telegram

1. Create a bot with @BotFather, copy the token.
2. **Channels → Add bot**, platform `telegram`.
3. Register the webhook from the UI, or run polling in development — no public
   URL needed.

Registering the webhook is what hands Telegram the bot's secret, and **a bot with
no secret refuses every webhook call** rather than trusting it. So a bot switched
from polling to webhook mode has to have its webhook registered before it will
answer anything: the secret is minted when the mode changes, and Telegram only
learns it when the webhook is registered.

## Mattermost

Mattermost is self-hosted, so a bot carries **your server's URL** as well as its
token — there is no api.mattermost.com to fall back to. Registering one without
it is refused rather than accepted and discovered later: a bot that does not know
its server cannot reply, cannot open its event stream and cannot fetch a file
somebody attached.

Two ways in; pick by whether your Mattermost can reach this deployment.

**Event stream (nothing exposed).** The right choice behind a VPN.

1. In Mattermost, *Integrations → Bot Accounts → Add Bot Account*. Copy the
   token it shows once — that is the **bot token**.
2. Register it: **Channels → Add bot**, platform `mattermost`, paste
   the token, and set **Server URL** to your Mattermost, e.g.
   `https://mattermost.acme.internal` or `http://mattermost:8065` inside compose.
   Leave the webhook token empty.
3. Invite the bot to a channel. The deployment opens an authenticated WebSocket
   to your server and every `posted` event arrives on it.

**Outgoing webhook.** For a Mattermost that can reach this API.

1. Create the bot account and register it exactly as above.
2. *System Console → Integrations → Outgoing Webhooks → Add*, with the callback
   URL `https://your-api.example.com/api/v1/mattermost/BOT_ID/webhook` — the bot
   id is on the row once it is registered, and `channel-webhook-register` prints
   the whole URL.
3. Mattermost shows a **token** when the webhook is saved. Paste that into the
   bot's **Webhook token** field here.

The token is the one thing people get wrong twice, so it is worth being exact:
**Mattermost generates it, and you paste it into AgenticOS** — the opposite
direction from Telegram, where this deployment generates the secret and hands it
over when the webhook is registered. Nothing is generated locally for Mattermost,
because a locally generated value is one Mattermost will never send.

Mattermost does not sign webhook bodies the way Slack does — the token in the
payload is the whole check — so **a bot with no webhook token refuses every
call** rather than trusting it. The bot's row says so with a badge.

Either way can be done from the command line, which is the only way on a
deployment with no browser pointed at it:

```bash
uv run agenticos cmd channel-add-bot \
    --platform mattermost --name "Ops" --token <bot-token> \
    --api-base-url https://mattermost.acme.internal \
    --webhook-secret <token-from-mattermost>   # omit for the event stream

uv run agenticos cmd channel-test-message --bot-id <uuid> --chat-id <channel-id>
```

**What a server URL may be.** Scheme and shape are checked — http or https, a
host, no `user:pass@` — and a private or loopback address is deliberately
allowed, because a self-hosted Mattermost behind a VPN is the deployment this
exists for. Instance-metadata addresses are the exception and are refused. The
boundary that actually holds is the permission to manage channel bots, not this
check.

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

- **One bot answers as one agent.** A bot user is a single identity in the chat:
  the same avatar, the same name, whichever agent produced the reply. So a bot
  serves exactly one agent, and binding a second is refused — in the Builder's
  picker, which does not offer a bot somebody else's agent is already on, and in
  the database, which is what makes it true.

    An agent goes the other way freely: one agent can answer on a Slack bot, a
    Telegram bot and two Mattermost servers at once, and each of those bindings
    carries its own instructions, its own channel lookups and its own workspace
    scope.

    This replaced routing several agents behind one bot with `@slug`. It worked
    and it read badly: somebody in a channel had to type a handle to pick
    between agents they could not see, and a message that named none was
    answered with a list of handles instead of an answer. A second bot costs an
    operator two minutes and makes the chat say which agent it is talking to,
    which no amount of routing can. `@slug` still parses — as an alias for the
    agent behind this bot, refused when it names any other.
- **Access policy per bot** — open, whitelist, or "must be linked to a member".
- **Linking, and it comes first** — a channel run belongs to a *person*: the
  budget it spends, what it may read and the audit entry it writes are all
  theirs. So an unlinked chat account is refused, whatever the bot's access
  policy says.

    The refusal carries the way out. Message the bot and it answers with a URL;
    open it, and the dashboard — where you are already signed in — names the chat
    account and asks you to confirm. Nothing is typed and no code is copied. Ask
    again any time by sending the bot `link` (or `/link` where the platform
    delivers a slash; Mattermost does not).

    What is connected, and disconnecting it, is under **Settings → Profile →
    Chat accounts**. Disconnecting clears the owner and keeps the row, so the
    conversations that hang off it survive - the person is still messaging the
    bot from the same account afterwards.

    **Only in a direct message.** The URL is a bearer credential: whoever opens
    it claims that chat account. In a channel the bot says to message it
    directly instead, and mints nothing. A link lasts fifteen minutes, is good
    once, and asking again retires the one before it.
- **A reply you can watch being written.** The bot posts a message the moment
  your question arrives and rewrites it as the answer appears — including what
  it is doing meanwhile ("Searching the web…", "Drawing a chart…"), which is
  when the silence used to be longest, because a tool call produces no text
  while it runs. Edited about once a second: per token would be hundreds of
  writes a second against a server that is often somebody's own. A platform that
  cannot edit a sent message simply gets the finished answer, as before.
- **Every binding carries its own extra instructions**, added to the agent's on
  that surface alone. A new one opens holding what that client actually renders:
  Slack draws no Markdown and writes a link as `<url|text>`, Mattermost renders
  headings and tables, Telegram rejects a message whose `*` is unclosed — plus
  how to give a link there, led with an emoji when it is an action or a
  destination. It is the binding's text from then on: change it, add to it, or
  clear it. It shapes how an answer is delivered and can never replace what the
  agent is for — that belongs to the published version.
- **A bot answers as soon as it is registered.** A polling bot - Telegram
  long-polling, Slack Socket Mode, a Mattermost event stream - is reached over a
  connection the API process holds, and that connection is opened when the row
  is written rather than at the next restart. Pausing, deleting, changing the
  token or the server address, and switching between polling and webhooks all
  take effect immediately, for the same reason: the stream is reopened to match
  whatever the row now says. It is opened *after* the transaction commits, so a
  registration that fails leaves no connection behind.
- **A binding's instructions may name what only the platform knows.**
  `{channel_name}`, `{channel_purpose}`, `{channel_topic}`, `{member_count}`,
  `{member_list}` - filled in when a run starts, from the same calls the channel
  lookups use, so Telegram offers all five even though it offers two of the four
  tools. The Builder lists the ones this platform can answer under the box and
  inserts one at the cursor.

    Resolved per run and never cached: a channel's membership changes, and a
    stale list in a prompt is worse than none because the agent states it as
    fact. Only what the prose asks for is fetched, so a binding that names no
    placeholder costs nothing. A placeholder the platform could not answer
    becomes `(unavailable)` rather than costing somebody their reply.

    A prompt that filled any of them gains a sentence saying the substituted
    values are information rather than orders, and every value has its line
    breaks and braces flattened. A channel's `purpose` is editable by whoever
    can edit the channel, and it is being pasted into an agent's instructions.
- **A redelivered message is answered once.** Every platform delivers
  at-least-once: the webhook routes answer 200 before any work so a slow handler
  never triggers a retry, but a 200 lost on the wire — a proxy drops it, the pod
  restarts — was never received, and the redelivery that follows is a valid,
  signed, brand-new request carrying the same message. The first delivery claims
  the message in Redis (one atomic `SET NX`, keyed on what the platform calls
  the message, inside its chat) at the point every inbound path crosses — the
  three webhook routes and the three polling streams alike — so the retry is
  acknowledged and dropped, whichever API worker receives it. A claim lasts
  fifteen minutes, which outlives every platform's retry window.

    The claim is taken on receipt, so a run that does not finish gives it back:
    a redelivery after a failed or cancelled run is answered rather than
    mistaken for a duplicate. That matters most for the polling streams, which
    re-read a message the process died on.

    The guarantee degrades open, never shut. A message that arrives with no
    platform message id, and a Redis that cannot be reached, are both processed
    rather than refused — a duplicated answer is the rarer, cheaper failure than
    a dropped question — and each writes a warning saying the guarantee was off
    for that delivery. Nothing is refused on a platform's retry header alone:
    Slack's `x-slack-retry-num` says a redelivery is happening, not that the
    first attempt got far enough to do anything, and `reason=http_error` means
    it explicitly did not. The header is logged; the claim decides.
- **Rate limits** per chat, on the bot - who may talk to it and how often is the
  operator's, unlike everything above, which is the agent author's.
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
| Web chat, run finished | Everything — prompt, reasoning, tool arguments and results, model and version, and the order it all happened in |
| Web chat, run interrupted | The same, as far as it got. A run that failed, hit its budget, was stopped or lost its socket keeps the words already streamed, attributed to the version that produced them, with no cost figure invented for it — the run row is where the accounting lives |
| A channel bot's default agent | Everything except the reasoning, which only a streamed run exposes |
| `@mention` on a channel | The same, with the handle stripped from the recorded prompt |
| Embedded widget | The same. The visitor is anonymous; the run and the turns belong to the widget's owner |
| HTTP API | The same when the call carries a `conversation_id`. Nothing without one — there is no thread to write a turn into, and the run row is still the record that it happened |
| A run resumed after an approval | Its continuation — the answer and the calls it made, and the calls even when there is no answer, which is what a continuation that parks again on a second gated call has. No user turn: it picks up at the call it stopped on, and inventing a question would put words in somebody's mouth |

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
the screen. Three kinds of run are never folded — one holding a failure, one holding a
call parked for approval, and one holding a step whose result *is* the answer, which today
means a chart. The first two are the line in the turn that is asking for something; the
third is there because a turn that drew three charts folded two of them away, and three
charts are three answers rather than one with two footnotes. Which tools count as that
kind is `opensOnSight` in `lib/tool-catalog.ts`, the same row the step reads to decide
whether to open itself, so the rail and the step cannot disagree. Nothing marks a step
that simply worked, so a marker means what it says.

**What opens itself follows what somebody is watching, except when the result is the
point.** A call that finishes while the turn is streaming opens on the spot — code that
ran, a file that was written is the answer, not a footnote to it. A conversation *reopened*
shows one line per past call and keeps open exactly one: the last call of the most recent
turn that **used a tool**, which is the result the reader came back for. The most recent
*turn* is the wrong anchor and was the first way this was written - an agent that writes a
file and then answers about it in prose ends the transcript with text, and the file it had
just written was folded away. Opening every finished call on mount turned a reopened chat
into a wall; opening none of them hid the thing that was asked for. A chart is the
exception at both ends: it opens wherever it sits and however the turn is being read,
because a picture nobody can see is not an answer.

### The same turn, watched and reopened

**A turn is one message, and its order is recorded rather than guessed.** Both halves of
that were once false, and together they made the live transcript and the reloaded one two
different documents.

A multi-step turn makes one model request per tool round, and the client used to open a
message on each — so a turn that drew three charts arrived as four bubbles, each with its
own avatar. One turn is one `messages` row, so only one of those bubbles could ever be
matched to what was stored; the rest kept a temporary id, carried no cost and no rating,
and vanished on reload.

And the row said what a turn contained without saying when. `content`, `thinking` and
`tool_calls` are three buckets, so a client had to reconstruct an order and the only one it
could reconstruct was reasoning, then every tool, then the answer. A turn that introduced
the charts, drew them, and then summarised them has two blocks of text and one column to
put them in: the introduction was dropped on save and the summary reappeared above the work
it described.

So `messages.parts` holds the sequence as it was streamed — `{"type": "text"|"thinking",
"text": …}` and `{"type": "tool", "tool_call_id": …}`, in order — and both surfaces render
the same array instead of agreeing by coincidence. A tool's arguments and result stay in
`tool_calls`; the timeline names the call rather than copying it.

It is null on a turn of a single part, where there is no sequence to preserve, and on every
assistant turn written before this existed. Those rows are still readable — the text is in
the columns it always was — but their order was never recorded and cannot be recovered, so
a client that finds null falls back to reconstructing one. That fallback is a guess, and it
is kept only for them.

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

**An approved call is not the end of the turn, and the rest of it is drawn too.**
Approving continues the run over HTTP, so nothing about the continuation arrives on
this conversation's socket: its steps come back in the resume's own answer and are
appended as one more assistant turn — the calls it made, then what it said. Without
them the second half of a turn was invisible, and a run that parked twice was the
worst version of it: approve a command, watch nothing happen, and be asked to
approve a second command with no step on screen accounting for the first. The
newly parked call is drawn in that turn as *waiting for a person*, which is also
the step the next decision is written back onto.

**One run is one turn on screen, however many messages it took.** A run that parks
writes what it had done so far, and each continuation is written as it happens
rather than folded back into the message before it — rewriting a turn somebody has
already read is worse than appending to it. So one run can leave three assistant
rows, and drawing three avatars and three agent names down the page reads as three
agents answering one question. `MessageList` groups *consecutive* assistant
messages carrying the same `run_id` into one turn: the avatar and the name once, at
the top. Consecutive is part of the rule — a person speaking between two segments
means the turn genuinely restarts — and a message with no run recorded never groups,
because absent means "not recorded" rather than "the same run". Live, the run id
arrives on the `tool_approval_required` frame, which is the only frame that names
it and the only turn that needs it; on a reload it comes off the stored message.

**The time and the cost go under the end of the turn**, once, however many messages
it took. A run reports what it has spent when it *parks*, so the figure is recorded
on the first segment — drawn there it sat halfway up the answer, with nothing under
the end of it. The last segment shows the run's total: each figure is cumulative as
at that point, so the later one supersedes the earlier rather than being added to
it, and the continuation takes its numbers from the resume's own answer.

**What the approved call returned is recorded on the step that was approved.** The
row is written open when the run parks — it has not run yet — and the resume that
finally runs it produces the *return* without the call it belongs to, because that
call was made by the previous execution. So it settles the existing row rather than
writing a new step: the alternative is the same command twice in one turn, and the
alternative to *that* was the one call somebody deliberately reviewed being the one
call that opened onto nothing.

**A replayed step never animates.** A tool call is stored as running until
something records its outcome, and not every ending records one: an approval that
expires runs nothing, so the step it parked on was written open and stayed that
way. Read back, it pulsed in the present tense under a conversation that had ended
days earlier, promising a result nothing was going to deliver. So the sweep that
expires an approval now closes the step too — the one ending that never ran the
call — and a replayed call still marked in flight renders as **unfinished**: past
tense, no spinner, no result. Not an error and not a success; the outcome nobody
wrote down.

**And the panel belongs to its conversation, not to the tab.** Opening another
thread takes the approval panel and any pending question off screen, the way it
already takes the delegation panels. Left there the approval was not merely
stale but actionable: *Approve* still decided the call, from under a different
agent's transcript, and the step it settles is in messages that are no longer
loaded — so nothing on screen changed to say it had happened. Clearing it loses
nothing, because the approvals queue holds the same row. The one transition that
is not a switch is a first turn learning its own conversation id mid-stream, and
the panel survives that.

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
English rather than the key. `make lint` runs `frontend/scripts/check-i18n.ts`, which
fails both ways: on copy left in a component, and on a key a component reads that the
catalog does not hold.

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

**A file the turn ran on belongs to that turn.** Its `ChatFile` row is linked to the
user message the run's transcript writes, exactly as a web upload is linked to the
message somebody typed — so a transcript of a channel thread shows the spreadsheet
beside the question it was asked about. It matters more here than it reads:
`chat_files` carries no organization, so a row with no message is scoped by the
sender alone, reachable through `GET /files/{id}` by its owner and by nothing else.
Every channel turn used to leave one that way, because linking was done by the one
surface that writes its own transcript.

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

Chosen **per binding**, in the Builder under *Where this agent is available* -
beside the extra instructions and the channel lookups, because whether a reply
carries a cost footer is part of what this agent says on this surface. It sat on
the bot until a bot served one agent, where it was an operator's setting in a
table of servers and tokens with nothing else about the agent near it.

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

### What the agent may look up about the channel

A bot answering in `~support` knows the words somebody typed and nothing else.
It does not know the channel is called `~support`, who is in it, what it was set
up for, or what was said in it ten minutes ago — so *"who should I ask about
billing?"* and *"summarise what we decided above"* are questions it can only
answer by guessing.

Four tools change that, and each is granted **per binding**, under
*Where this agent is available*:

| Tool | Answers | Slack | Telegram | Mattermost |
|---|---|:-:|:-:|:-:|
| `get_channel_info` | Name, purpose, topic, size | ✅ | ✅ | ✅ |
| `list_channel_members` | Who is here | ✅ | admins only | ✅ |
| `search_channels` | Which other channels exist | ✅ | — | ✅ |
| `read_channel_history` | What was said recently | ✅ | — | ✅ |

Per binding rather than per agent, because an organization can bind one agent to
two Mattermost servers and three Slack workspaces — and *"may it read what was
said in this channel"* has a different answer on the internal one and the
customer one. A switch in the agent's Toolbox would have one answer for all
five, which is why there is no such switch: publishing refuses a spec that
carries `channel_tools`, and the run assembles the binding from the row that
admitted the message, the same way it appends that binding's prompt.

Nothing is granted by default. What a platform cannot answer is not offered:
Telegram gives a bot no directory of chats to search and no way to read messages
it was not sent, and `getChatAdministrators` is the whole of what it may list —
so a Telegram member list is a list of administrators and says so.

Three things worth knowing before granting them:

- **The bot's membership is the whole permission boundary.** Every call goes
  through the bot's own token, so the agent sees exactly what the bot sees. There
  is no allow-list of ours to get out of step with the platform's own.
- **The model never names a channel.** The tools are bound server-side to the
  channel the message arrived in — in a thread, to the channel that holds it.
  An argument for it would turn *"who is in this channel"* into *"read any
  channel this bot is in"*, asked from a conversation somewhere else.
- **`read_channel_history` is the one worth gating.** It is a read, so it does
  not ask by default, but it puts other people's messages into a run transcript
  somebody reads weeks later. A `tool_approval` override on the binding is how
  you make it ask.

This is deliberately *not* the same thing as putting the channel's member list
and purpose into every system prompt. That is a different feature with a
different failure mode — a `purpose` written by whoever can edit the channel,
pasted into the instructions, is a prompt injection with a public edit button.

## Choosing

- Your own site, no accounts → **widget, `public` mode**.
- Inside your product, per-user → **widget, `jwt` mode**.
- Your own interface entirely → **WebSocket**.
- Where the team already talks → **Slack, Telegram or Mattermost**.
- Another system entirely → the REST API (`POST /api/v1/agents/{id}/run`).
