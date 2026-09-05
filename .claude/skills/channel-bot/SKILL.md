---
name: channel-bot
description: Work with messaging-channel bots — Telegram, Slack or Mattermost. Register a bot, route inbound messages through an agent, choose webhook vs polling, handle an @slug mention, or add a new channel adapter. Use when wiring chat into a messaging platform or debugging bot delivery, identity linking or "the bot answered as itself".
---

# Channels — Telegram, Slack, Mattermost

**Read `docs/channels.md`.** Code: `app/services/channels/` — a thick service with
per-platform adapters plus a router that funnels inbound messages into the **same**
agent pipeline as the web chat.

| File | Responsibility |
|---|---|
| `base.py` | Shared adapter interface |
| `telegram.py` | Telegram (aiogram v3) |
| `slack.py` | Slack (Events API + Socket Mode) |
| `mattermost.py` | Mattermost |
| `router.py` | Inbound platform message → conversation/session → agent run → reply |
| `mentions.py` | `@slug` resolution, and the identity rules below |

Bots live in the DB (`channel_bots`), with per-user identity (`channel_identity`) and
per-thread session (`channel_session`).

## Tokens go through the vault

Bot tokens are sealed with `app/core/vault.py`, bound to the organization.
**`CHANNEL_ENCRYPTION_KEY` and the deployment-wide Fernet key are gone**, removed
before the chain was squashed into `0001_baseline`.
`channel_bots.secret_key_version` exists because the token is now an envelope
and a staged master-key rotation has to know which key sealed it. See the
`vault-secrets` skill.

## The mention invariants

These are the ones worth testing and the ones easiest to break:

- **A bot serves exactly one agent** - `uq_exposure_bot`, migration `0018`. So
  `answer_default` takes the single active binding without asking what a second row
  would have meant, and `@slug` is an alias for that agent rather than a router
  between several. Binding a second agent is refused by the service *and* by the
  database.
- **`@slug` resolves only inside the bot's organization.** A slug from another org is
  not found, not borrowed.
- **A mention runs as the *sender*, never as the bot.** The bot's own identity would
  carry whatever permissions it was registered with, which is how a channel becomes a
  privilege-escalation path.
- **An unlinked identity is refused, not run with no role.** "No role" is not a safe
  default; it is an unauthenticated run.

`tests/test_channel_mentions.py` and `tests/test_channel_bot_org_scope.py` pin these.

## CLI

```bash
uv run agenticos cmd channel-add-bot \
    --platform telegram --name "Support" --token <token> --mode jwt_linked
uv run agenticos cmd channel-list-bots [--platform telegram]
uv run agenticos cmd channel-test-message --bot-id <uuid> --chat-id <chat> --text ping
uv run agenticos cmd channel-webhook-register --bot-id <uuid>
uv run agenticos cmd channel-webhook-delete --bot-id <uuid>   # back to polling
```

There is no `cmd channel` group — the commands are flat, hyphenated names.

Access modes: `open`, `whitelist`, `jwt_linked`, `group_only`.

## Webhook vs polling

- **Polling (dev)** — the adapter long-polls; no public URL needed.
- **Webhook (prod)** — the platform POSTs to a route under `api/routes/v1/`.
  **Verify the signature or secret before processing anything** (HMAC for Telegram,
  signing secret for Slack).

## Adding an adapter

1. Implement `services/channels/<platform>.py` against `base.py`: parse inbound into
   the normalized message, send outbound.
   Anything per bot the connection needs before it opens - a server address, an
   app token - is registered in `prepare_connection`, the base hook the supervisor
   calls on every adapter; do not add a differently named method for it.
2. Wire it into `router.py` so inbound reaches the agent and replies stream back.
   **Do not fork the agent pipeline** — one runner behind every surface is the whole
   design.
3. Add a signature-verified webhook route and/or a polling entrypoint.
4. Reuse the existing conversation/session model.
5. Respect the per-group/per-thread concurrency controls already in the adapters.

## Where charts come from

Rendering a chart for a channel is the `charts` capability's job
(`app/agents/capabilities/charts/`), not a channel module. There is no
`chart_render.py` in `services/channels/` any more.

## Coverage

`app/services/channels/mentions.py` is in the gated platform layer at 100%. The
adapters are template-inherited and are not. See the `backend-tests` skill.
