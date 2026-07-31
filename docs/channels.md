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

## Choosing

- Your own site, no accounts → **widget, `public` mode**.
- Inside your product, per-user → **widget, `jwt` mode**.
- Your own interface entirely → **WebSocket**.
- Where the team already talks → **Slack, Telegram or Mattermost**.
- Another system entirely → the REST API (`POST /api/v1/agents/{id}/run`).
