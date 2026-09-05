# Putting an agent where people already are

An agent that only answers inside this dashboard is a demo. The same published
agent answers in eight places, and every one of them runs the *same frozen
version* through the same budget, the same approval gate and the same tenant
checks — the surface changes, the agent does not.

| Where | What it needs | Who the visitor is |
|---|---|---|
| **Dashboard** | nothing | a signed-in member |
| **Website widget** | a `<script>` tag | anonymous, or a user your backend vouches for |
| **Raw WebSocket** | an embed key | whatever your integration says |
| **A hosted page** | a link | anonymous, and nothing else |
| **The API** | a session | whoever holds the credential |
| **Slack** | a bot token | a Slack account, optionally linked to a member |
| **Telegram** | a bot token | a Telegram account, optionally linked |
| **Mattermost** | a bot token and your server URL | a Mattermost account, optionally linked |

!!! abstract "Three rules hold on every surface, enforced in the runner"

    - **A run always belongs to exactly one organization.**
    - **A spending limit is checked before each model request, never after.**
    - **A run that failed is still in history with what it spent** — the tokens
      were spent before it broke, and a budget that ignores that is not a budget.

!!! info "Three of those eight are one table, and its rows differ by a `kind`"

    A widget, a raw socket and a hosted page are each an *embed* — and a kind is
    fixed at creation, because a tag already pasted, a client already written and
    a link already sent all name the same row.

One public key, one rate bucket, one budget, one pause switch, and one set of
refusals. What differs is what there is to configure and what admits a visitor —
which is why the Builder asks which one you want before it asks anything else,
and why a page has no allowed-origins list rather than an ignored one.

Every run records the surface that admitted it — `web`, `embed`, `api`, `slack`,
`telegram` or `mattermost` — which is what the dashboard's by-surface chart
aggregates. All three embed kinds record `embed`. Two historical wrinkles:
widget runs recorded before the `embed` value existed are stored as `web`, and
Mattermost runs from the same era as `api`. Neither is backfilled — rewriting
history would be a guess — so charts over old periods fold those runs into the
surface they were recorded under.

**What a stranger may do, they may do at a rate.**

The surfaces reachable without a session carry a limit counted in the deployment's
Redis, so it holds across workers:

- the run API, **per caller**;
- the widget's script and its admission, **per address**, on a counter each;
- a hosted page's config, **per page** — that one is fetched by the frontend server
  rather than by the browser, so an address there names a container and would put
  every visitor in the deployment in one bucket.

The script is counted apart from the admission it precedes because a page load
spends both, and one bucket for both made the number an operator sets mean a third
of itself.

`RATE_LIMIT_RUN_PER_MINUTE`, `RATE_LIMIT_EMBED_PER_MINUTE` and
`RATE_LIMIT_HOSTED_PAGE_PER_MINUTE` set them, and
[configuration](configuration.md#rate-limiting) has the one caveat worth reading
before production — behind a proxy, every visitor arrives as the proxy unless you
say otherwise.

What rations *spend* on a hosted page is the socket the page opens, and that is
counted per address like the widget's.

---


!!! tip "Integrating rather than configuring?"

    [The HTTP API](api.md) covers authenticating, the organization header,
    running an agent over HTTP, the two WebSocket endpoints and the error
    envelope.

## The website widget

The shortest path. Publish the agent, create an embed, paste two lines.

### 1. Create the embed

In the Builder, open the agent → **Availability** → *Website widget*. You choose:

- **Allowed origins** — the sites this widget may be opened from. **An empty
  list allows nothing**, so publishing without one is refused rather than
  producing a widget that answers nowhere. The key in the script tag is public by
  construction, so the origin list is what actually stops somebody else running
  your agent on your bill. The same rule holds for a socket, whose handshake is
  checked against the same list.
- **Auth** — `public` (anonymous visitors) or `jwt` (your backend vouches for
  each visitor; see below).
- **Look** — the header and the line under it, the greeting, what the empty box
  says, what the launcher button says, the accent colour and which corner it sits
  in. All seven, and the greeting is drawn by the widget rather than sent to the
  model: a greeting in the model's history is a turn the agent thinks it took.
- **Context** — a note appended to the visitor's first message: *"You are on the
  pricing page"*, *"Answer in German"*. It never replaces the agent's own
  instructions, which belong to the published version.
- **Rate limit** — messages per visitor per minute.

!!! danger "An empty origin list allows nothing, and that is on purpose"

    The key in the script tag is public by construction, so the origin list is
    the only thing stopping somebody else running your agent on your bill.
    Publishing without one is refused rather than producing a widget that
    answers nowhere.

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
- **`iat` is required and must be within the last 12 hours** — it is not checked
  only when present. A token with no `iat`, or a stale one, is refused, so one
  that leaks out of a browser cannot work forever. An `exp` you set is honoured
  too, but only to **shorten** that window (an expired token is rejected); it
  cannot extend a token past the 12-hour ceiling.
- Mint it per page load, server-side.

!!! danger "Never ship the signing secret to a browser"

    It signs *any* visitor. The token it mints is the thing the browser is
    allowed to hold, and only for the twelve hours `iat` gives it.

---

## The raw WebSocket

The widget is a client of a documented protocol, not a black box. If you want
your own UI — a mobile app, a kiosk, a component in your design system — talk to
the same socket:

```
wss://your-api.example.com/api/v1/embed/PUBLIC_KEY/ws[?token=SIGNED_JWT]
```

**You do not have to assemble that yourself.** Publish one from the Builder —
the agent → **Availability** → *Raw WebSocket* — and its row prints the URL,
built from the deployment's own base URL, with a copy button. A **widget** prints
the same thing beside its script tag, because a widget is a client of this
protocol: moving to an interface of your own is a step rather than a rewrite. The `?token=` is not printed
there: in `jwt` mode the token is minted per visitor by your backend, and a real
one on a dashboard screen is a working credential somebody can read over a
shoulder.

!!! bug "The first thing that goes wrong: a missing `Origin`"

    The handshake must carry one on the embed's allow-list. **A browser sends it
    for you; a client of your own sends nothing unless you set it** - a mobile
    app, a kiosk, a server-side relay. What it looks like when it does not is
    `4003` in the table below, not an error message.

```mermaid
sequenceDiagram
    participant C as Your client
    participant E as /embed/{key}/ws
    participant R as run_stream
    C->>E: handshake (Origin, optional ?token=)
    alt origin not allowed, token bad, embed paused
        E-->>C: close 4003 - do not retry
    else admitted
        E-->>C: ready { visitor }
        C->>E: message { text }
        E->>R: the same loop /chat drives
        R-->>C: model_request_start
        R-->>C: text_delta … (a word at a time)
        R-->>C: final_result, then complete
    end
```

**Frames you send**

```json
{ "type": "message", "text": "Do you ship to Poland?" }
```

That is the whole inbound vocabulary, plus `context` (what the page says about the
visitor) and `file_ids` (what they attached, on a page that takes files).

**It deliberately does not include the three fields the dashboard's own frame
carries:** the agent, the model profile and the environment.

A frame that could choose a model is a visitor choosing one on the operator's bill,
and one that could choose an agent is a visitor talking to something nobody
published on this key. All three come off the embed row.

An unknown field is **ignored rather than refused**. A client cached in somebody's
browser may be older than this server, and closing the socket over it would take
the conversation with it.

**Frames you receive**

!!! note "This is the dashboard's own frame vocabulary, not a second one"

    `/chat` and this socket drive one loop (`app/services/run_stream.py`), so an
    answer arrives here a word at a time the same way it does there. A hosted
    page used to show one lump of text after thirty seconds of nothing, and that
    was the loop rather than the transport.

Every frame carries `{ "type": …, "data": { … } }`.

| `type` | `data` | Meaning |
|---|---|---|
| `ready` | `visitor` | Connected. `visitor: true` when a token identified the person. |
| `history` | `messages` | On a hosted page only: what was said in the thread this visitor is resuming. Each entry is `role`, `text` and `at`, so a replayed turn keeps the time under it. |
| `model_request_start` | — | The agent has gone to the model. Show an indicator. |
| `part_start` | `index`, `part_type` | A block of the answer is starting. Sent only for a block this surface will actually carry — a page showing no reasoning does not announce a `ThinkingPart`, since the announcement alone says the agent reasoned. |
| `text_delta` | `index`, `content` | Words of the answer. Append them. |
| `thinking_delta` | `index`, `content` | The model's reasoning. **Only if the operator turned it on.** |
| `call_tools_start` | — | The agent is about to use tools. |
| `tool_call` | `tool_call_id`, `tool_name`, `args` | A step. `args` only when the operator shows results. |
| `tool_call_delta` | `index`, `args_delta` | A call's arguments as they stream. |
| `tool_result` | `tool_call_id`, `content` | What the step returned. |
| `final_result_start` | `tool_name` | The answer is being produced by an output tool. |
| `final_result` | `output` | What the run ended with. Empty on a turn that parked. |
| `complete` | — | The turn is over. It carries **no usage**: what a run cost is the operator's business, not the visitor's. |
| `error` | `message` | Something the visitor should see: rate limit, budget reached, a refusal, a turn that produced nothing. |

Some dashboard frames never reach a public socket, and they are refusals rather
than settings. **`user_prompt_processed`** carries the prompt *as assembled* —
the placement note and the supplied block above what the visitor typed — which is
the operator's text and not the visitor's to read back.

**`ask_user` and `tool_approval_required` have nobody here to answer them, but
they fail differently.** A visitor cannot approve a side effect on somebody
else's organization, so `tool_approval_required` **parks** the run exactly as it
does on a channel, and the turn ends with `error` saying a person has to decide —
unlike a channel, without the `/runs` link, because the reader there is a member
who can open it and here they are a stranger holding a link. `ask_user` does
**not** park: `AgentDeps.ask_user` is `None` on this surface, so the tool
*refuses* when the model calls it (`app/agents/ask_user.py`) and the model carries
on to answer without the input — a degraded answer, not a parked run.

**A client ignores what it does not draw**, and `widget.js` is the worked example:
it reads `model_request_start`, `text_delta`, `final_result`, `complete` and
`error`, and ignores the reasoning and the steps on purpose — an answer arriving
a word at a time is worth having in a bubble in the corner of a page, and a
narration of tool calls is not. The hosted page draws all of them.

**Close codes**

| Code | Meaning |
|---|---|
| `4003` | Refused. The origin is not allowed, the token failed, or the widget is paused. Do not retry — the answer will not change. |
| `4029` | Too many connections from this address in the last minute. Back off and retry. |
| `1011` | This client was not reading. A frame took longer than 30 seconds to reach it, so the server stopped writing rather than hold the turn's database session and the open provider stream once per frame. Reconnect; a hosted page resumes its thread. |

The refusal is deliberately one code with one message. A page that is not on the
allow-list learns that it is not allowed and nothing about whether a token would
have helped.

`4029` is separate from it for the opposite reason: "not allowed" and "allowed
but too fast" ask a client for opposite things — stop for ever, and try again
later — so a client that cannot tell them apart either hammers a refusal or
abandons a limit. How many connections an address gets is
`RATE_LIMIT_EMBED_PER_MINUTE`; how many *messages* a visitor gets once connected
is the widget's own rate limit, set in the Builder.

A minimal client:

```js
const socket = new WebSocket(`${BASE}/api/v1/embed/${KEY}/ws`);
let answer = "";
socket.onmessage = (event) => {
  const { type, data } = JSON.parse(event.data);
  if (type === "text_delta") render((answer += data.content));
  if (type === "final_result" && data.output) render((answer = data.output));
  if (type === "complete") answer = "";
  if (type === "error") render(data.message);
};
socket.send(JSON.stringify({ type: "message", text: "hello" }));
```

`final_result` is assigned rather than appended: it is what the run *ended* with,
and a provider that streamed no deltas leaves it as the only copy of the answer.

---

## A hosted page

The shortest integration there is: **send somebody a link.** No site of your
own, no `<script>` tag, no client to write, no sign-in.

In the Builder, open the agent → **Availability** → *Hosted page*. There is no
site to name and nothing to paste — the form asks for a title, a welcome, an
accent and a logo, all optional, and publishes:

```
https://your-app.example.com/e/PUBLIC_KEY
```

It is **an embed like the other two**: the same kind of key, the same rate limit,
the same budget and the same pause switch. Pausing it stops the page at once, and
every link already sent with it.

### What protects it

Say this part out loud before publishing one, because it is the whole security
model:

> **A hosted link in `public` mode is protected by the key being unguessable,
> plus the embed's rate limit, its budget and its pause switch. Nothing else.**

Whoever has the link can talk to the agent. That is the point of a link, and it
is why the key is 24 random bytes rather than something readable.

There is no allowed-origins list here, deliberately, and the form does not offer
one: an allow-list is a rule about *other people's* sites, and this page is one we
serve. A page is admitted from the deployment's own origin — derived from
`FRONTEND_URL`, never hardcoded — and nowhere else. A `CHECK` constraint refuses
a page that carries a list at all, because a stored one reads as the thing
protecting the link, and it is not.

### Two things a hosted page refuses

Both are refused at publish, with a message, rather than silently falling back to
a widget:

- **A page cannot use `jwt` mode**, and the form does not offer it. The token
  would have to travel in the URL, and so into browser history, `Referer` headers
  and every chat client the link is pasted into — and the fragment trick that
  avoids some of that stops the link being "send it and it works". Use a widget
  or a socket for a per-user integration; `jwt` there is unaffected. A `CHECK`
  constraint holds the same rule in the database.
- **A *required* variable that is not URL-safe cannot be on a page** — see below.

### Variables from the address bar

A hosted page has no page of yours to read `window.AgenticOSContext` from. Its
only source for a declared variable is the visitor's own URL:

```
https://your-app.example.com/e/PUBLIC_KEY?var_plan=pro
```

**A query parameter is visitor-controlled input**, so this is off per variable
and on only where somebody decided it: tick *URL-safe* on the variable in the
Builder. Without it, `?var_user_tier=premium` typed into the address bar is
dropped — which is the point. Anything not declared at all is dropped as it is on
the widget.

That is also why a *required* variable has to be marked: on this surface the URL
is the only way to supply one, so a required-and-not-URL-safe variable is a
promise the page structurally cannot keep.

### Coming back to it

A widget's conversation lasts as long as its socket. A bookmarked link is a
stronger promise, so the page keeps a random visitor key in `localStorage` — one
per public key — and the server maps it to a conversation. Reopening the link
replays the thread and the agent is reminded of the same window the visitor is
reading.

**The key is a bearer credential for that conversation**: whoever holds it
resumes the thread, including what is already in it. It is 128 random bits and
nothing about the person. Clearing site data starts a new thread.

That key is the whole of what the page stores, which is why **a hosted page and a
shared conversation show no cookie prompt** — the two surfaces served to somebody
who is not a member are the two with no optional cookie to consent to. The
product's banner used to appear here, asking permission for analytics this
deployment does not run while sitting over the composer and covering Send (#644).
A consent prompt for one essential key is a prompt whose only effect is the
overlap.

That shape is enforced, not assumed — the socket accepts 32 to 64 lower-case hex
characters as a `visitor` and **drops anything else**, opening a fresh thread
instead. It matters for a client of your own (below): keying continuity on a
customer id, an email or a counter would hand each of your users a conversation
the next person can walk into by guessing. A dropped key costs continuity and
never the conversation, so a stale value in somebody's browser is not a page that
will not load.

### What it offers

Two switches, and both are the operator's rather than the page's — a capability
a page turned on for itself would be one nobody could turn off.

- **A button to start a fresh thread**, on by default. It mints a new continuity
  key, so the old thread is not deleted: it stops being the one that browser
  resumes.
- **A microphone in the composer**, off by default. It dictates into the box
  using the *visitor's own browser*, so no audio reaches this deployment and
  nothing is transcribed here — but a browser that offers speech recognition
  hands the audio to its vendor, which is the half worth reading before turning
  it on for the public. A browser without one is shown no microphone rather than
  a button that does nothing.
- **A way to attach a file**, off by default. See below: it is the only thing on
  this surface that lets a stranger *store* something.

### What a stranger holding the link can write to

Everything else on a public surface reads. This one writes, so it is worth
stating exactly what a visitor can put where.

**They can store a file**, and only if the operator ticked the switch. The bytes
go through the same path a member's upload does — the MIME allowlist,
`CHAT_MAX_UPLOAD_SIZE_MB` (10MB by default — the chat surface's own ceiling,
not the knowledge base's larger `MAX_UPLOAD_SIZE_MB`), the parser, the storage
backend, a `ChatFile` row — with three narrowings in front of it:

| | |
|---|---|
| **A cap of this surface's own** | `EMBED_MAX_UPLOAD_SIZE_MB`, 5MB by default. A member uploading a fifty-megabyte export is somebody the organization employs; the same allowance on a public link is a way to fill a disk from an address nobody knows. It is a ceiling *on top of* `CHAT_MAX_UPLOAD_SIZE_MB`, never a way past it |
| **A limit per address and per visitor** | `RATE_LIMIT_EMBED_UPLOAD_PER_MINUTE`, in the shared Redis, and **both** have to allow it. Counting only the continuity key bounds nothing: the browser mints it and any 32 hex characters is a valid one, so a script varies it per file. Counting only the address lets one browser on a shared one spend everybody's |
| **Three files to a message** | Which bounds how much of one turn's prompt is somebody else's document |

Those three bound what gets *stored*. What bounds what a stranger can make this
deployment *receive* is one layer above all of them, because the multipart body is
parsed before the route runs: a request declaring more than the whole-request
ceiling is answered 413 without being read. See
[configuration](configuration.md#the-size-of-a-request-as-opposed-to-the-size-of-a-file),
including what it does not cover.

**The row belongs to the member who published the page**, because
`chat_files.user_id` is `NOT NULL` and a visitor has no account — the same answer
already given for who a public turn *runs* as. A page whose publisher's account is
gone therefore cannot take files at all, and says "not available" rather than
storing them against nobody.

**Where the file then goes is the runner's decision, not this surface's.** It is
the routing in [File processing](file-processing.md), unchanged: into the agent's
workspace where it has one, folded into the prompt where it does not, and an image
both ways up to the inline ceiling. Nothing about a visitor's file is a special
case.

A frame may only name a file that belongs to this page's owner and does not
already hang off a message, so an id cannot be replayed into a second turn or
into somebody else's thread. That is proportionate rather than complete, and what
makes it enough is the id itself: `uuid4` is 122 random bits, so an id from
another visitor is a value nobody can produce without having been handed it.

**They cannot write anything else.** No knowledge base, no workspace path of their
own, no config, no variable that is not declared and URL-safe. The conversation
row and the turns in it are written *about* them, by the platform.

### What the visitor sees of the work

Three more switches, and they are **filters on what the server sends** rather than
on what the page draws. That distinction is the whole design: reasoning hidden in
CSS is an agent's reasoning sitting in a stranger's devtools, and a page is
exactly where a stranger has one open. A visitor who opens theirs sees what is
ticked here and nothing else.

| Switch | Default | What it lets through |
|---|---|---|
| **What the agent is doing** | on | One line per step — *Searching the documents*, *Ran a query*. On, because a page that goes quiet for thirty seconds reads as broken |
| **What each step returned** | off | The arguments a step was called with and what came back. Written for the model, so this is where something internal turns up: an address, a row from a system, a passage nobody meant to publish |
| **The agent's reasoning** | off | What the model says to itself before answering. Not written for anybody to read, and not an answer an operator can stand behind |

*What each step returned* cannot be turned on alone — there is no step for it to
open, and the server drops both regardless of what the config says.

**A turn looks like a turn in web chat**, down to the chrome around it: the agent's
name above the answer, the avatar in the gutter — the page's logo where there is
one, the agent's initial where there is not — the time under each turn on the side
it is on, and one composer card with the field and its controls inside it.

Three things web chat draws there are deliberately absent, and all three are the
same decision as the panels below: what the turn cost, what the month has cost, and
which agent and model to run.

That last one because a frame that could pick a model is a visitor picking one on
the operator's bill.

**A turn is rendered by web chat's own components**, not by a second set that looks
like them.

`TurnParts` is what the dashboard renders and what the page renders. So the
reasoning is the same disclosure, the answer the same Markdown, and a run of tool
calls the same rail — the icon from `src/lib/tool-catalog.ts`, the wording from
`toolStep`, and the same renderers opening under a step for a knowledge search, a
web search, a chart, code that ran, a skill that was loaded, a file that was
written.

There is deliberately no second table of tool names and no second turn renderer
(#144). What the page does *not* draw is everything about being a member — see
below.

One thing reads differently by necessity: a call that came from an MCP server is
named *Linear · Create issue* in the dashboard and by a humanized name here,
because the mapping is the organization's list of connections and reading it needs a
session.

**A widget and a raw socket carry no switches and get these defaults**, read off
`PageConfig` rather than repeated — a second copy of "off by default" is a copy
that can disagree with the one somebody reads in the Builder. What `widget.js`
then *draws* is narrower still, and says so above.

Neither of them takes files either, and that is the route rather than the client:
the upload endpoint resolves the key through `find_page`, so a widget key reaches
it and is answered "not available". A widget lives on a page the operator already
controls, which is where a file picker of their own belongs.

### What is deliberately member-only

Web chat draws three panels a public surface does not, and each omission is a
decision rather than a gap — recorded here so it is not re-litigated as one.

| Panel | On a public surface | Why |
|---|---|---|
| **The usage strip** | No, and it is not a switch | It reports the turn's tokens, its cost, the month against the organization's cap and how full the workspace is. A visitor is not the one paying, and the operator's remaining budget is a fact about the operator. `complete` carries no usage at all, so there is nothing to hide client-side |
| **The file panel** | No | It lists everything in the agent's *workspace*, which is shared across the conversations of everybody using that agent. A stranger who attached one file would be shown every file the agent has ever been given. Their own attachment is on their own turn, which is what they are owed |
| **The delegation panel** | No | It names the delegates by slug, what each was asked, and what each cost — the shape of the organization's agent graph. A page that showed it would publish an internal org chart to whoever has the link. A delegation still *runs*: it is one `tool_call` step named `task`, under the same switch as any other step |

The pattern behind all three: what a member sees is *about the organization*, and
what a visitor sees is *about their own turn*. A panel that crosses that line is
member-only whatever it would cost to render.

### What it looks like

The answer renders as **Markdown**, the same as web chat: an agent told to answer
in Markdown is answering in it whether or not the page reinterprets the asterisks.
What a *visitor* typed is not reinterpreted — it is not a document.

Four fields, all optional:

| Field | Default |
|---|---|
| **Page title** | the agent's name |
| **Welcome message** | none. **Markdown**, written in the same editor the placement note uses and rendered as Markdown on the page. Shown before the first question and never sent to the model — a greeting in the model's history is a turn the agent thinks it took |
| **Accent colour** | `#4f46e5`. Light and dark still follow the visitor's system |
| **Logo** | the agent's avatar; or the organization's, one you upload, or none. Whichever you pick, the page shows **nothing** rather than a broken image when there is no file behind it — an agent with no avatar is the common case, and a browser cannot tell a 404 from a slow image |

Three of those four are images this platform already holds. The fourth takes a
file — PNG, JPEG, WebP or GIF, up to 2MB — and it can only be added once the page
exists, because an upload needs a row to attach to.

The page fetches it from **its own origin**, not from the API: `img-src` in
`next.config.ts` excludes an API on plain `http`, so a page pointing an `<img>` at
one rendered a broken glyph in dev and on any deployment terminating TLS elsewhere.
`/api/embed/<key>/logo` on the frontend proxies it.

**What it does not take is a URL of your own.** A page we serve fetching an
operator-supplied image is one more thing to make safe. And the stored path is a
*column*, written by the upload route and never by the config you submit: the
path is read back and streamed by a public route, so one accepted from a request
body would be a caller naming any file the process can open.

**Nor does it take your filename, or your word for what the file is.**

Because the page fetches the logo from its own origin, whatever type that response
carries is a type the browser trusts on that origin — and `script-src` there allows
inline script.

An upload is accepted on the `Content-Type` its client *declared*, which is not
evidence about the bytes. So the name on disk is minted from the type instead
(`logo.png`, `logo.jpg`, `logo.webp`, `logo.gif`), and both the API route and the
frontend proxy refuse to answer with anything that is not one of those four image
types.

A stored `.html` or `.svg` — from here, or from an avatar uploaded years ago through
another route — is served as **nothing at all** rather than as a script.

The page is `noindex`. A secret link is not a page to be indexed, and a crawler
that follows one has published it.

---

## The public API

No frontend at all, and no browser. One request, one answer:

```bash
curl -X POST https://your-api.example.com/api/v1/agents/AGENT_ID/run \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-Id: $ORG_ID" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Summarise this week's refunds"}'
```

It goes through the same runner as every other surface, so the run is recorded,
the budget applies and the cost lands in the same dashboard — an API caller
cannot route around governance by not using the UI. Runs are stamped `api`.

The answer carries `run_id`, `output`, `status` and what it cost. A `status` of
`awaiting_approval` with an empty output means a tool call is parked: the run is
in the approvals queue, and it continues when somebody decides.

Limited per caller rather than per address — an office behind one NAT is not one
caller — at `RATE_LIMIT_RUN_PER_MINUTE`.

---

## Slack

1. **api.slack.com/apps → Create New App → From scratch.** Name it and pick the
   workspace.
2. **OAuth & Permissions → Bot Token Scopes → Add an OAuth Scope**, and add the
   thirteen below. *Install to Workspace* stays greyed out until at least one is
   added, which is what a blank app is waiting for.
3. **Install App → Install to Workspace → Allow.** Copy the **Bot User OAuth
   Token** (`xoxb-…`).
4. **Event Subscriptions → Enable Events → Subscribe to bot events**, and add the
   five events below.
5. Register the bot: **Channels → Add bot**, platform `slack`, paste
   the bot token.
6. Pick a transport — Socket Mode needs nothing exposed and is the right choice
   on a laptop:
     - **Socket Mode.** *Basic Information → App-Level Tokens → Generate*, scope
       `connections:write`; paste the `xapp-` token into the bot's settings here.
       No Request URL, no signing secret.
     - **Events API.** Paste the signing secret from *Basic Information → App
       Credentials* into the bot's settings **first**, then set Slack's *Request
       URL* to `https://your-api.example.com/api/v1/slack/BOT_ID/events` — the
       bot id is on its row under **Channels**.
7. **App Home → Messages Tab**: enable it and tick *Allow users to send Slash
   commands and messages from the messages tab*. Without it Slack hides the
   bot's message box and a direct message is impossible.
8. Publish the agent, then bind it: Builder → the agent → **Availability** → the
   bot.
9. Invite the bot to a channel — `/invite @your-bot` — and mention it.

!!! tip "Or paste a manifest and skip steps 2, 4, 6 and 7"

    **App Manifest** in the left nav takes the whole configuration at once —
    scopes, events, Socket Mode and the message tab — which is less error-prone
    than eleven passes through a scope picker. Create the app *from a manifest*,
    or paste this over an existing app's:

    ```yaml
    display_information:
      name: Support Copilot
    features:
      bot_user:
        display_name: Support Copilot
        always_online: true
      app_home:
        messages_tab_enabled: true
        messages_tab_read_only_enabled: false
    oauth_config:
      scopes:
        bot:
          - chat:write
          - files:write
          - files:read
          - app_mentions:read
          - users:read
          - channels:read
          - groups:read
          - channels:history
          - groups:history
          - im:history
          - mpim:history
          - im:read
          - mpim:read
    settings:
      event_subscriptions:
        bot_events:
          - app_mention
          - message.channels
          - message.groups
          - message.im
          - message.mpim
      socket_mode_enabled: true
      token_rotation_enabled: false
    ```

    For the Events API instead, set `socket_mode_enabled: false` and add
    `request_url` under `event_subscriptions` — and read the next warning first,
    because Slack validates that URL the moment the manifest is saved.

!!! danger "The signing secret goes in before the Request URL, not after"

    Slack verifies a new Request URL by posting a signed `url_verification`
    challenge to it, and that challenge takes the same path as every other event.
    A bot with no signing secret answers **500 to all of them**, so Slack reports
    "Your request URL didn't respond with the correct challenge value" — which
    reads like a networking problem and is not one.

!!! warning "Do not opt into token rotation"

    *Advanced token security via token rotation*, at the top of **OAuth &
    Permissions**, makes the `xoxb-` token expire. This deployment stores a
    static bot token in the vault and does not refresh one, so the bot works and
    then stops. Redirect URLs, PKCE, user token scopes, IP ranges and
    Enterprise-Managed Authorization on that page are all unused too — leave them
    alone.

### Scopes and events

Thirteen bot token scopes, each earning its place by a call the adapter makes:

| Scope | What needs it |
|---|---|
| `chat:write` | `chat.postMessage`, and `chat.update` for the reply rewritten as it is written |
| `files:write` | `files.upload` — a chart or a file the agent sends back |
| `files:read` | an attachment somebody posted, fetched from `url_private_download` |
| `app_mentions:read` | being named in a channel |
| `channels:history`, `groups:history`, `im:history`, `mpim:history` | the `message` events, and `conversations.history` for the channel transcript |
| `channels:read`, `groups:read` | `conversations.info`, `.list` and `.members` — the channel lookups an agent may call |
| `im:read`, `mpim:read` | `conversations.members` on a direct message. Easy to leave out and quiet when you do: the membership check fails closed, so a conversation nobody could be confirmed in **disappears from the conversation list** rather than erroring |
| `users:read` | `users.info`, which turns member ids into people |

Five bot events: `app_mention`, `message.channels`, `message.groups`,
`message.im`, `message.mpim`.

`message.channels` and `message.groups` deliver **every** message in every
channel the bot is in, not only the ones naming it — and that is deliberate, so
subscribe to both. What decides whether the bot speaks is the rule below, read
from the event: Slack substitutes `<@U0123>` for a real mention, so the adapter
knows which messages were addressed to it and stays out of the rest. Keeping the
whole conversation arriving is what an agent deciding *for itself* whether a
message deserves an answer will need; a subscription narrowed to `app_mention`
cannot be widened after the fact without every operator editing their Slack app.

| Where | When it answers |
|---|---|
| **A direct message** | Always. There is nobody else in the room, so requiring a mention would be asking somebody to address the only participant |
| **A group direct message** | Only when named. Several people share it, so it is a room rather than a conversation with one person |
| **A channel** | Only when named — `@the-bot`, or `@agent-slug` for the agent behind it |

A mention anywhere in the message counts, not only at the start. A handle typed
without letting Slack resolve it stays plain text and is not a mention — the
platform delivered none — and `@channel`, `@all`, `@here` and `@everyone` address
the room rather than an agent.

**A message with a file attached is a message.** Slack marks one with
`subtype: file_share`, and both the file and the caption sent with it reach the
agent — an image with *"what do you see?"* under it is one turn, not two. What
stays refused is the platform describing the channel rather than somebody
speaking in it: an edit, a deletion, a join, a topic change, and anything the bot
itself posted.

The bot sees what the app was installed with and nothing beyond it. Adding a
scope later means reinstalling the app, which mints a new `xoxb-` token — paste
that one in too, or the bot keeps the access it had.

!!! info "A bot that answers nothing: what is reported, and what is not"

    The connection is. A polling bot whose stream did not open, or keeps
    failing, carries a **Not connected** badge on its row under **Channels**,
    with the reason on it - the supervisor knows, and until #1351 it wrote that
    to the container log and nowhere else.

    The rest is still silent, and this is the order to check it in: no agent
    bound to the bot (the row says so), a missing scope or event subscription,
    then a wrong `BOT_ID` in the Request URL. That last one cannot report
    itself: the events route answers **200 and does nothing** for a bot id it
    cannot find, on purpose, because a prober should learn only that the
    endpoint exists - which the URL already said.

Works in channels and in DMs. A message from a linked account runs as that
person — never as the bot; one from an account nobody has linked runs under the
binding, and only in a channel. A direct message asks for the account first.

A linked account whose member has left the organization, or whose account has
been deactivated, is treated as unlinked: refused in a direct message, run under
the binding in a channel. Offboarding clears neither the membership row nor the
chat account's link, so the role is read only off a membership that can still
sign in.

### One conversation per thread

**The unit is the thread, and that now includes a direct message.** Send the bot
a message and it answers in a thread rooted at yours; that thread is one
conversation and keeps its context for as long as people reply in it. Reply
inside a thread that already exists and it joins that one instead.

So two people asking different things in the same channel get two conversations,
and neither reads the other's context — and one person asking about two
different things in a DM gets two, for the same reason.

!!! warning "Continuing a conversation means replying in its thread"

    A new message typed at the bottom of a chat is a **new** conversation with
    no memory of the last one. That is the trade, and it is deliberate: a chat
    keyed on itself never rolls over, so it walks past the context window in
    days and every turn pays for the whole history behind it. A thread per
    question is a context per topic instead of one long transcript somebody has
    to trim.

    A DM used to key on the chat. Conversations from before are not migrated —
    they stop being reached, and nothing in them is lost.

!!! info "This was wrong until recently"

    A mention at the top of a channel used to be keyed on the channel, while
    the thread the reply opened was keyed on the thread. They were two
    conversations, so the agent answered a question and then, one message later
    in the thread it had just created, had no memory of it — and every
    unrelated mention in that channel piled into one conversation besides.

    Now the thread a reply *will* open is what the first message keys on, so
    both halves agree. Conversations from before the fix are not migrated; they
    simply stop being reached, and nothing in them is lost.

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
3. Add the bot to the **team**, which *Integrations → Bot Accounts* does not do:
   *System Console → User Management → Users*, find it, **Manage Teams**, add the
   team — or `mmctl team users add <team> <bot>`. Until then a channel refuses to
   admit it, saying it "is not a part of this team".
4. Invite the bot to a channel. The deployment opens an authenticated WebSocket
   to your server and every `posted` event arrives on it.

**Every** post, which is the thing to know about this transport: the socket is not
a subscription to messages aimed at the bot, it is the channel. So the rule is the
one a colleague follows — and it belongs to the bot rather than to one way of
reaching it, so the outgoing webhook below obeys the same table:

| Where | When it answers |
|---|---|
| **A direct message** | Always. There is nobody else in the room, so requiring a mention would be asking somebody to address the only participant |
| **A channel** | Only when it is named — `@the-bot`, or `@agent-slug` for one of the agents exposed on it |

*How* it knows it was named is the transport's, because the two payloads say
different things:

| Transport | What it reads |
|---|---|
| **Event stream** | Mattermost's own mention list on each `posted` event, against the account the bot resolves once per session |
| **Outgoing webhook** | The `trigger_word` the integration fired on. The body carries no mention list, so `@the-bot` cannot be read here — set the trigger word to the bot's handle if that is how people should reach it |

An `@agent-slug` needs neither and works on both: it is read out of the text,
because a slug is a name in *this* product and so is never in a mention list.

The stream reads the list rather than matching text for the same reason: `@ada` is
somebody whose display name the bot cannot resolve, and a bot called `bot` should
not answer the word "robot". A handle that turns out to name neither the bot nor
one of its agents is answered in a direct message and passed over in a channel,
because there it was somebody's colleague.

**`@channel`, `@all`, `@here` and `@everyone` address the room, not an agent.**
They have the shape of a slug, and a channel-wide mention puts every member of the
channel — the bot included — in the platform's own mention list, so an announcement
read as a message naming an agent nobody has. Those four handles are never a
mention here, and an agent named after one gets `-agent` on the end of its handle so
it stays reachable.

If the bot's own account cannot be resolved, the stream answers everything, as it
did before this rule existed: going quiet on a server that would not say who we
are is the worse of the two failures. The webhook has no such fallback and does
not need one — an integration with no trigger word is a channel filter, and a
channel filter says nothing about who a post was for.

**Outgoing webhook.** For a Mattermost that can reach this API.

1. Create the bot account and register it exactly as above.
2. *System Console → Integrations → Outgoing Webhooks → Add*, with the callback
   URL `https://your-api.example.com/api/v1/mattermost/BOT_ID/webhook` — the bot
   id is on the row once it is registered, and `channel-webhook-register` prints
   the whole URL. Its **trigger words** are what addresses the bot on this
   transport, per the table above; leave them empty and only an `@agent-slug`
   reaches it in a channel.
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
    --org <organization-id> \
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

- **The model is reminded of the most recent turns, not the first ones.** A
  channel thread is keyed to the chat and never rolls over, so a support channel
  passes the window in days. Two hundred turns for a channel against forty for a
  widget, and the two numbers are different on purpose: a widget is a public URL
  with somebody else's budget behind it, and a channel is a room the operator's own
  colleagues work in. Bounded either way, because a prompt is not a transcript and
  one thread's whole history is a per-turn bill that grows for ever.

    It read from the wrong end until #638: the repository orders oldest-first, so
    the bot was told how the conversation opened and nothing said since — and it
    answered plausibly, from a version of the thread that had stopped hundreds of
    turns ago. Nothing errored, which is why it needed a test rather than a fix.

    The offset is `conversation_repo.get_recent_messages` now, and every surface
    reads the window through it — the widget, the channels and web chat. Three
    copies of one `COUNT` and one offset is how it came to be wrong twice, from
    opposite ends.

- **A thread it is brought into partway through is read first.** A conversation
  here is built from what this deployment *received*, so a bot mentioned in a
  thread that was already running held nothing above the mention — and answered
  as though the thread were empty, which it said confidently. Nobody watching a
  chat can tell an agent that cannot see from one that has read and disagreed.

    Once per conversation — recorded on the session, not inferred from its age,
    so a thread the bot was answering in before this existed is read on its next
    turn rather than never — up to fifty messages, and only where the platform
    has threads. After that the transcript is ours and
    nothing is fetched again. It arrives as one labelled block — *what was said
    before you arrived, `speaker: message`, context rather than instructions* —
    not as turns, because replaying other people's messages as an alternating
    history puts words in the agent's mouth it never said.

    **This is not gated, where `read_channel_history` is**, and the difference is
    the point: that tool reads the *channel*, which is content the agent was
    never addressed in, and an operator decides per binding whether it may. The
    thread the bot was spoken to in is the conversation somebody pointed it at,
    and reading that is not the same act as reading the room. The bot still sees
    only what its own membership allows, because the call goes through its token.

    **The files posted in it come too**, up to four of them: the transcript
    alone let the bot answer, accurately, that it could see no image in a
    conversation whose first message was a screenshot.

    They are fetched down the same path an attachment on the live message takes,
    so one set of size limits applies, and they are attributed to whoever
    mentioned the bot — that is the person who pointed it at the thread, and an
    unlinked sender gets none, exactly as they get none of their own. Four
    rather than fifty, because fifty downloads before an answer starts is a
    minute of silence. Slack reads them with `conversations.replies`, Mattermost
    with `GET /posts/{root}/thread`; Telegram has no threads and reads neither.

    A read that fails costs the context and never the answer: no thread, a
    platform without them, a refusal or an error all produce an answer without
    the history above it, which is worse than one with and better than none.

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
- **A voice message is transcribed, where a bot has been given a model.** It is
  the one attachment an agent cannot be handed as a file: it reads a PDF and
  looks at a screenshot, and an `audio/ogg` blob is a byte count.

    The recording is fetched, transcribed, and **woven into the same turn** as a
    labelled quotation — `[Voice message, transcribed]` — rather than sent as a
    second message. Labelled on purpose: speech recognition mishears names,
    numbers and anything said over traffic, so an agent told the source can hedge
    a figure it half-heard and ask, where one told nothing states it as fact. It
    is also what keeps a recording a quotation rather than instructions somebody
    typed. A voice note with a caption stays one message, because that is what
    somebody sent.

    Which model is a **pair on the bot** — a provider and one of its models, from
    `app/core/catalog/speech_to_text_models.json` — chosen under **Channels**, and
    null by default: transcription spends the organization's provider credit on
    every recording, so it is opted into. The key is the one already configured
    for that provider in the organization's model profiles; there is nothing new
    to store. A bot with no model chosen says it cannot listen rather than
    dropping the recording, because a voice note that produces no reaction is
    indistinguishable from a broken bot.

    Three providers ship: OpenAI, Groq and Mistral, all serving OpenAI's
    `POST /audio/transcriptions`. Adding a model is an entry in that file. Every
    failure — no credential, a recording over the endpoint's limit, a refusal, a
    timeout — is reported on the reply and the turn goes ahead without it.

- **Access policy per bot** — open, whitelist, or "must be linked to a member".
- **A credential can be added or replaced after registration.** The pencil on a
  bot's row opens it: rename it, paste a rotated token, or supply the credential
  that was not in hand when it was registered — which is the ordinary case on
  Slack, whose `xapp-` token is generated on a different screen minutes later.

    Every credential here is sealed at rest and **never read back**, so each
    field starts empty and an empty field means *keep what is stored* rather
    than *clear it*. Only what somebody typed is sent. What the dialog does not
    offer is the platform, because it decides which credentials the row carries
    and how messages reach it, and the transport, because switching to webhook
    mode is only half a move — the webhook still has to be registered with the
    platform, and a bot that reports `webhook` without one answers nothing.
    `channel-webhook-register` does both halves.
- **Linking, and where it is required** — every run belongs to somebody: the
  budget it spends, what it may read and the audit entry it writes are all
  attributed. Where that *somebody* comes from depends on whether the bot is
  being spoken to privately or standing in a room.

    **A direct message asks for an account.** It is a conversation with one
    person, so an unlinked chat account is refused until it names one.

    **A channel answers anybody in it.** Whoever could invite the bot chose the
    audience, so a sender with no linked account is not refused: the turn runs
    under the *binding* that admitted it — the role of whoever bound the agent to
    this bot, dropping to `viewer` if they have since left the organization — and
    the chat account that typed it is recorded on the run. What that widens is
    real and worth saying: anyone who can speak in the channel can spend the
    organization's budget and reach what the binding's creator can reach, which
    is the same trade a public widget makes. The ceilings are the rate limit per
    chat account, the access policy, and the organization's monthly cap. The
    rate limit (`rate_limit_rpm` on the bot's access policy, ten a minute by
    default) is counted in the deployment's shared Redis, so it holds across
    API workers rather than once per worker.

    Set **`require_link`** on the bot's access policy to refuse in channels too,
    which is the old behaviour.

    Linking still matters in a channel, and it is worth doing: a linked sender
    runs as *themselves* rather than under the binding, and linking later makes
    their earlier channel turns attributable to them — the run points at the chat
    account, and the chat account gains a person. Only while that person is a
    member who can sign in: a linked sender who has left, or whose account was
    deactivated, is admitted the way a stranger is — under the binding in a
    channel, refused in a direct message.

    It is also what lets an agent reach *their* tools. A binding to
    [each person's own account](mcp.md#whose-account-a-binding-speaks-through)
    speaks to Notion or Jira as whoever wrote the message, in a channel as much
    as in a direct message — and an unlinked sender has no account to speak
    through, so the agent tells them to `/link` first.

    **A channel thread is one conversation with several people in it**, and it
    appears in the conversation list of everybody whose linked chat account has
    written in it — not only whoever spoke first, and not nobody, which is what a
    thread with no linked speaker used to reach. Each turn records the account
    that wrote it, so a room reads as a room rather than as one person talking to
    themselves. Linking afterwards is what puts the earlier thread in front of
    somebody, with no backfill: the turn points at the chat account and the
    account gains a person.

    **Speaking is a claim; the platform decides whether it still holds.** The
    turn record says who *spoke*, and before [#641][641] that was the whole
    check — somebody removed from the channel kept reading the thread,
    including everything said after they left. Now every participation claim is
    confirmed against the platform's current membership (`getChatMember` on
    Telegram, `conversations.members` on Slack, the per-user member lookup on
    Mattermost) before the listing shows the thread and before it opens, behind
    a shared Redis cache of about a minute. The check **fails closed**: a
    platform that cannot answer, a bot that is gone, and a thread whose channel
    nothing names any more — `/new` re-points the session at a fresh
    conversation — all refuse participation rather than trust the claim. The
    thread's owner and anybody it was explicitly shared with keep their access
    regardless; the membership check gates participation and nothing else.

    **And it opens a thread rather than owning one.** Speaking in a room admits
    you to reading it; renaming it, archiving it, deleting it or appending a turn
    to it stays with the thread's owner and anybody it was explicitly shared with.
    Otherwise one person who said "thanks" in a channel could delete the room's
    whole transcript, or write a turn as the agent that everybody reads and the
    model is handed back as its own words on the next turn.

    A thread whose first speaker never linked an account has no owner, and there
    the participants *are* who may change it — the same set that may open it.
    There is nobody the write would be taken from, and the alternative was the
    whole organization: any member could delete a transcript whose list entry
    they had never seen ([#701][701]). The write leans on the same confirmed
    participation as the read: a claim the platform no longer backs carries
    neither ([#641][641]).

[701]: https://github.com/vstorm-co/agenticos/issues/701

[641]: https://github.com/vstorm-co/agenticos/issues/641

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

**What is recorded is what the person wrote, not the prompt assembled around it.**

Every surface builds something larger before the model sees it: `AttachmentRouter`
appends a briefing about each file, and an embedded widget prepends the operator's
placement note.

Recording that put the platform's own briefing in the transcript as somebody's
words. A file posted in Mattermost read back as `co tu widzisz` followed by
`--- Attached file: … (/uploads/…, 43 KB, image)`, and the opening turn of every
widget conversation read as a visitor reciting the page they were on.

**The file itself is a row on that turn**, which is what the dashboard renders as a
card — the same as an upload made there.

One thing is deliberately not recorded: a channel reply's **delivery notes** — *this
file was too large to send* — stay out of the transcript, because they are about what
the reply could not carry rather than about what the agent said.

### What a turn looks like in web chat

**The work is a narration, not a stack of cards.** Each tool call is one line — *Wrote
test1.md*, *Searched for TODO in app.py*, *Ran pytest -q*, *Linear · Create issue* —
written in the tense it is true in: present while the call runs, past once it has. The
line names the *subject* rather than the function, because `write_file` is not what
anybody wants to read. Every line opens into what the call actually produced, and the
raw arguments and output stay one click further in for whoever is debugging one.

Consecutive calls hang from one rail, and **only the last row stays visible**.
Earlier ones fold into "4 earlier steps", which says work happened without pushing
the answer off the screen.

Three kinds of run are never folded: one holding a failure, one holding a call
parked for approval, and one holding a step whose result *is* the answer — which
today means a chart.

The first two are the line in the turn that is asking for something. The third is
there because a turn that drew three charts folded two of them away, and three
charts are three answers rather than one with two footnotes.

Which tools count as that kind is `opensOnSight` in `lib/tool-catalog.ts`, the same
row the step reads to decide whether to open itself, so the rail and the step cannot
disagree. Nothing marks a step that simply worked, so a marker means what it says.

**What opens itself follows what somebody is watching, except when the result is the
point.**

A call that finishes while the turn is streaming opens on the spot — code that ran,
or a file that was written, is the answer rather than a footnote to it.

A conversation *reopened* shows one line per past call and keeps open exactly one:
the last call of the most recent turn that **used a tool**, which is the result the
reader came back for.

The most recent *turn* is the wrong anchor, and was the first way this was written:
an agent that writes a file and then answers about it in prose ends the transcript
with text, and the file it had just written was folded away. Opening every finished
call on mount turned a reopened chat into a wall; opening none of them hid the thing
that was asked for.

A chart is the exception at both ends. It opens wherever it sits and however the
turn is being read, because a picture nobody can see is not an answer.

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

**A delegation is a panel, not a pause.**

When the agent hands work to
[a delegate or a specialist](concepts.md#delegate-vs-inline-specialist), that
delegation is a second agent's whole conversation happening inside one turn of the
first. Left alone it is a tool call named `task` that goes quiet for thirty seconds.

So it streams into a panel of its own: which specialist is working, its text and its
reasoning as they are generated, its *own* tool calls — which may reach a collection
the parent cannot even see — and on close its status, its tokens and its share of the
turn's cost.

Every frame carries the delegation's task id and its depth. A fan-out of three is
three panels, and interleaving three specialists into one paragraph is worse than
not streaming at all. An opening frame also carries the task id of the delegation it
was made *inside*, so a specialist that delegates further nests under the right
panel rather than under whichever one started most recently.

A child's text is **never** folded into the parent's answer. That would put words in
the parent's mouth its own model never generated, and the conversation is persisted
with them.

**An approved call is not the end of the turn, and the rest of it is drawn too.**

Approving continues the run over HTTP, so nothing about the continuation arrives on
this conversation's socket. Its steps come back in the resume's own answer and are
appended as one more assistant turn: the calls it made, then what it said.

Without them the second half of a turn was invisible, and a run that parked twice
was the worst version of it — approve a command, watch nothing happen, and be asked
to approve a second command with no step on screen accounting for the first.

The newly parked call is drawn in that turn as *waiting for a person*, which is also
the step the next decision is written back onto.

**One run is one turn on screen, however many messages it took.**

A run that parks writes what it had done so far, and each continuation is written as
it happens rather than folded back into the message before it — rewriting a turn
somebody has already read is worse than appending to it.

So one run can leave three assistant rows, and drawing three avatars and three agent
names down the page reads as three agents answering one question.

`MessageList` groups *consecutive* assistant messages carrying the same `run_id`
into one turn: the avatar and the name once, at the top. Consecutive is part of the
rule — a person speaking between two segments means the turn genuinely restarts —
and a message with no run recorded never groups, because absent means "not recorded"
rather than "the same run".

Live, the run id arrives on the `tool_approval_required` frame, which is the only
frame that names it and the only turn that needs it. On a reload it comes off the
stored message.

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

**A replayed step never animates.**

A tool call is stored as running until something records its outcome, and not every
ending records one: an approval that expires runs nothing, so the step it parked on
was written open and stayed that way.

Read back, it pulsed in the present tense under a conversation that had ended days
earlier, promising a result nothing was going to deliver.

So the sweep that expires an approval now closes the step too — the one ending that
never ran the call — and a replayed call still marked in flight renders as
**unfinished**: past tense, no spinner, no result.

Not an error and not a success. The outcome nobody wrote down.

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
whole turn in the approval queue.

The panel then closes into a *waiting for a person* state rather than spinning on
"working" for as long as the approver takes, and the delegation keeps the task id it
parked under, so its identity survives the resume rather than a second panel
appearing beside the first.

The resume itself runs over HTTP (`POST /runs/{id}/resume`), which carries no
delegation frames. So the waiting panel is moved to the resumed run's own outcome —
completed, failed or cancelled — from that answer. A resume that parks again on a
fresh decision leaves it waiting.

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
before adding a surface that wants the panels.

!!! danger "Attaching a handler to a delegation changes the transport, not just the observability"

    The library drives each child through `iter()` and opens a **streamed** request
    for it.

    So a delegate whose model or provider cannot stream works perfectly from the API
    and stops working the moment somebody opens the chat window — the same published
    version, the same agent, failing on one surface.

Which is why a handler is attached only where a sink exists, rather than
unconditionally for the benefit of the one surface that draws them.
`tests/test_subagents_library_contract.py` pins that property of the library, so a
release that starts falling back to a plain request turns red and says so.

### Files

Somebody dropping a spreadsheet on a bot used to have it discarded. `IncomingMessage`
had no attachment field, so no adapter parsed one and the agent answered about a
document it never received.

Now a message with a file — with or without a caption — reaches the agent the same
way a web upload does, and is **read back the same way**: the file is a row on the
turn it arrived with, so the thread in `/chat` shows a card rather than the briefing
the model was given about it.

A caption-less upload is still a turn, and its message names what arrived —
`Attached image: photo.jpg` — rather than sitting blank above the card, because a
blank user message reads as somebody sending nothing.

**On every transport, because each adapter has exactly one parser.**

Each platform has two ways in — a webhook and a stream, or long-polling — and the
second one used to build its own normalised message. Telegram's polling loop read
text and nothing else; the Mattermost outgoing webhook read no `file_ids` at all.

Both now put their update back into the shape the platform sends and hand it to the
same `parse_incoming`, so what counts as a message is decided **once**. It had been
decided twice, and the copies disagreed about files — which mattered most on the
paths a self-hosted deployment actually runs.

What each transport is *handed* still differs, and that is the platform's doing
rather than ours: Telegram's polling loop subscribes to new messages only, so an
edit reaches the webhook receiver and never the poller.

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

What the link widens is the *metadata*, not the bytes. A channel's conversation is
owned by whoever spoke in it first, so in a shared channel a colleague's file now
appears in a transcript other members can read — as a name, a type and a size.
Downloading it still answers only its owner, which is the right half to keep
private and the half a reader has to be told about: the chip is there, the bytes
are not theirs.

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

**A turn refused before it runs gives its files back.**

The bytes are fetched and stored before the agent is resolved, so a refusal raised
in the run's place — no agent exposed on this bot, a sender whose chat account is
nobody's — used to leave the rows and the files behind with no message that would
ever link them. `chat_files` carries no organization, so an unlinked row is scoped
by `user_id` alone and nothing collects it.

Both are now deleted before the refusal is sent, and the refusal is sent whether or
not that succeeded
([#661](https://github.com/vstorm-co/agenticos/issues/661)).

A turn that actually ran keeps its files — they fed it, and the run is in the
transcript.

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
different places because they measure different things.

**The cost** is the newest measured answer *in the conversation on screen*. It is
read from the transcript, so it is there when a thread is reopened rather than after
the next message — and filtered by conversation id, because the store still holds
the previous thread's messages for the moment between the click and the fetch
landing. It reported those under the new conversation until it was.

**The fill** is the workspace as it stands now. A live turn reports it — a
container's resident memory can only come from its host — and a reopened
conversation reads it from the workspace listing, which carries the ceiling a stored
workspace fills up against. Without that, "workspace 0% full" appeared only after
somebody sent a message, the one moment nobody needs it.

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
| `read_channel_history` | What was said recently, **in the thread it is answering in** | ✅ | — | ✅ |

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
- **The model never names a channel, or a thread.** The tools are bound
  server-side to the channel the message arrived in, and `read_channel_history`
  to the thread as well: a thread and its channel are two transcripts, and the
  one the agent was spoken to in is the thread. Bound to the channel alone,
  *"summarise what we decided above"* summarised whatever else the room had been
  saying. An argument for either would turn *"who is in this channel"* into
  *"read any channel this bot is in"*, asked from a conversation somewhere else.
- **`read_channel_history` is the one worth gating.** It is a read, so it does
  not ask by default, but it puts other people's messages into a run transcript
  somebody reads weeks later. A `tool_approval` override on the binding is how
  you make it ask.

This is deliberately *not* the same thing as putting the channel's member list
and purpose into every system prompt. That is a different feature with a
different failure mode — a `purpose` written by whoever can edit the channel,
pasted into the instructions, is a prompt injection with a public edit button.

## Choosing

```mermaid
flowchart TD
    A{a site of your own?} -->|no| L{a link will do?}
    L -->|yes| H[a hosted page]
    L -->|no| T[Slack, Telegram or Mattermost]
    A -->|yes| U{your own interface?}
    U -->|yes| WS[the raw WebSocket]
    U -->|no| P{visitors signed in to your product?}
    P -->|yes| J["the widget, <code>jwt</code> mode"]
    P -->|no| PB["the widget, <code>public</code> mode"]
    A -->|another system entirely| API["the REST API"]
```

- Your own site, no accounts → **widget, `public` mode**.
- Inside your product, per-user → **widget, `jwt` mode**.
- Your own interface entirely → **WebSocket**.
- No site of your own, and a link will do → **a hosted page**.
- Where the team already talks → **Slack, Telegram or Mattermost**.
- Another system entirely → the REST API (`POST /api/v1/agents/{id}/run`).

!!! success "The first four are one object"

    A widget, a socket client and a hosted page are three ways of reaching the
    same embed, with one set of refusals between them — so "who may talk to this
    agent" has exactly one answer whichever of the three somebody arrives
    through.

## Recap

- **One runner behind every surface.** Web chat, a hosted page, a widget, the API,
  Slack, Telegram and Mattermost all reach the same code, so governance is not
  something a caller can route around.
- A bot answers as **one agent**, and a mention runs as **the sender** — never as
  the bot.
- What a **stranger** may do, they may do at a rate: the public surfaces carry
  per-caller and per-address limits counted in Redis.
- What is recorded is **what the person wrote**, not the prompt assembled around it.
- A **delegation is a panel**, not a pause — and attaching a handler to one changes
  the transport, so it is attached only where a sink exists.
