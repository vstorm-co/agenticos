# Mattermost, end to end

Written 2026-08-09. The running ledger for making Mattermost a channel somebody
can actually register and talk to — what already works, what is missing, in
which order, and the two decisions that are not obvious.

The headline: **the adapter is finished and the configuration surface does not
exist.** Nothing about Mattermost is half-written; what is missing is the ability
to give a bot the one thing a self-hosted platform needs, which is the address of
its own server. Every symptom below follows from that one gap.

## What already works, and must not be rewritten

`app/services/channels/mattermost.py` is complete, and covered by
`tests/test_mattermost_channel.py` (16 tests),
`tests/test_channel_supervisor_yields.py::TestMattermost*` and
`tests/test_channel_adapter_attachments.py`:

- **Sending** — one upload call for the chart and the attachments together, then
  a post referencing the file ids. `platform_chat_id` folds `channel_id:root_id`
  so one thread is one conversation without the router knowing about threads.
- **The event stream** — `authentication_challenge`, a 30s keepalive, a
  supervisor that re-raises `CancelledError`, backs off exponentially to 60s, and
  sleeps outside the `except` so a session that returns still yields.
- **The outgoing webhook** — `verify_webhook_signature` is fail-closed and
  compares in constant time; `decode_webhook_body` settles JSON versus form on
  what the body *is* rather than on what the header claimed, because the two
  halves of receiving one disagreed and a mismatched body authenticated and then
  parsed to nothing.
- **Attachments** — `metadata.files` where the socket provides it, an id carried
  as a bare handle where it does not, checked against the bytes after download.

The route (`api/routes/v1/mattermost_webhook.py`) is mounted at
`/api/v1/mattermost/{bot_id}/webhook`, answers 200 before doing the work because
Mattermost retries a slow webhook, and refuses a bot with no secret rather than
trusting it.

## What is missing

### 1. `api_base_url` cannot be set by any path (#24, #41)

The column exists (`db/models/channel_bot.py:43`) and is read by
`main.py:61` and `services/channels/router.py:486`. It is **not** a field on
`ChannelBotCreate`, not on `ChannelBotUpdate`, **not a parameter of
`channel_bot_repo.create`**, and appears nowhere in `app/commands` or
`frontend/src`. There is no way to write it short of `UPDATE`.

So every Mattermost bot has `api_base_url IS NULL`, permanently, and:

- `_run_stream` raises `ChannelNotConfigured`, the supervisor logs
  *"no server URL; cannot open a stream"* and returns — the bot is registered and
  deaf;
- `send_message` raises `ValueError`;
- `download_attachment` refuses, because guessing a Mattermost address is
  guessing whose server to send a bot token to.

`tests/test_mattermost_channel.py:159` asserts that loud failure. It is asserting
the state every bot is permanently in.

### 2. `webhook_secret` is minted, not accepted (#24)

`services/channel_bot.py:110` generates `secrets.token_urlsafe(32)` when
`webhook_mode=True`. For Telegram that is right — we hand the secret *to* the
platform. For Mattermost it is backwards: Mattermost generates the token when the
outgoing webhook is created, and the operator has to paste it in here. There is
no field to paste it into, so `verify_webhook_signature` compares Mattermost's
token against a local random string and the webhook path can never authenticate.

`docs/channels.md:179` already tells the operator to do this. The field it names
does not exist.

### 3. The webhook URL we hand out 404s (#24, 22a)

`services/channel_bot.py:274` and `commands/channel.py:111` both build
`{base}/api/v1/channels/{platform}/{bot_id}/webhook`. The receivers are mounted
at `/api/v1/{platform}/...` (`api/routes/v1/__init__.py:111-115`); `/channels`
holds management endpoints only. For Telegram that means `set_webhook` succeeds
and updates POST into a 404 forever. For Mattermost, `register_webhook` only logs
the URL to paste — so it logs a 404 for an operator to paste into their System
Console.

### 4. `webhook_secret` is stored in the clear (#22)

A `String(255)` column beside `token_encrypted`,
`slack_signing_secret_encrypted` and `slack_app_token_encrypted`, all sealed. It
is the only thing authenticating inbound Telegram and Mattermost webhooks.
CLAUDE.md: *every secret at rest goes through `app/core/vault.py`, and there is
no second mechanism.*

### 5. The webhook route drops its work into a bare task (#26)

`mattermost_webhook.py:60` is `asyncio.create_task` with a module-level set to
hold a reference. It is outside `background.drain()`, so a shutdown mid-message
loses it, and its failures are unobserved.

### 6. A Mattermost run is recorded as `api` (#208)

The surface a run is stamped with does not distinguish a channel from an API
call, so channel traffic is invisible on the dashboard as channel traffic.

## The two decisions

### SSRF validation refuses the documented case

#41's acceptance criteria say to validate `api_base_url` through
`app.core.sanitize.validate_webhook_url`, which today has no callers outside
`agents/mcp.py`. That function **blocks private, reserved, loopback and
link-local addresses, and resolves DNS to prove the host is public**
(`core/sanitize.py:200-206`).

A Mattermost server is somebody's own. `docs/channels.md:174` gives
`https://mattermost.acme.internal` as the example, and calls the event stream
*"the right choice behind a VPN"*. Validating it the way #41 asks would refuse
exactly the deployment the feature is for.

Both halves are real: an unvalidated `api_base_url` is an operator-supplied URL
that this deployment opens a WebSocket to and sends a bot token to, which is an
SSRF primitive if a member with `channels` rights is not trusted. Options:

1. **Scheme and shape only** — reject userinfo, non-http(s) schemes, and
   anything malformed; allow private addresses. Simplest, and matches what the
   feature is for.
2. **Public by default, private behind a setting** — a deployment-level
   `ALLOW_PRIVATE_CHANNEL_HOSTS`, defaulting off. Safe by default, one more knob,
   and every self-hosted operator turns it on immediately.
3. `validate_webhook_url` **as written** — refuses the documented deployment. Not
   viable without changing the documentation to say so.

**Leaning to (1)**, with the reason written into the validator's docstring, and
the refusal tested. `api_base_url` is not a callback we were handed by a stranger;
it is infrastructure an operator with `channels` rights typed about their own
company. The SSRF surface is the same one they already have by registering an MCP
server. Decide before writing the schema — this shapes it.

### Where the sealing of `webhook_secret` belongs

Sealing it (#22) touches the Telegram route as well, and the column is named
`webhook_secret` rather than `webhook_secret_encrypted`. Either do #22 first and
build on a sealed column, or add the field now and seal both in one migration
afterwards. Doing it second means one migration re-sealing rows written in the
meantime; doing it first means #24 lands on a moving column.

**Leaning to sealing first**, in its own commit, because the field being added is
precisely a credential and adding a plaintext write path we intend to remove is
work done twice.

## Order

Each step is its own commit, verified by its own tests.

- [ ] **S0** — decide the two questions above, record the answers here
- [ ] **S1** — seal `webhook_secret` (#22): `webhook_secret_encrypted`, unsealed
      in the two webhook routes, one migration re-sealing existing rows. Never in
      a response schema.
- [ ] **S2** — fix the webhook URL at both call sites (#24, 22a), and assert the
      built URL resolves against `app.routes` so the two cannot drift again
- [ ] **S3** — `api_base_url` and `webhook_secret` on `ChannelBotCreate` and
      `ChannelBotUpdate`, on `channel_bot_repo.create` and on the update path,
      with validation per S0. `ChannelBotRead` gets `api_base_url` (it is an
      address, not a credential) and `has_webhook_secret` (a boolean, never the
      value)
- [ ] **S4** — accept an operator-supplied `webhook_secret` for Mattermost
      instead of minting one; keep minting for Telegram, where we hand it out.
      One place decides, and says which platform is which and why
- [ ] **S5** — the panel: a server-URL field and a webhook-secret field, shown
      for Mattermost the way the Slack credentials are shown for Slack
      (`components/agents/channel-bots-panel.tsx:211`). Copy per `next-intl`
- [ ] **S6** — `app/commands/channel.py`: register a Mattermost bot from the CLI,
      because a deployment behind a VPN has no browser pointed at it
- [ ] **S7** — the webhook route hands its work to `spawn_after_commit` rather
      than `asyncio.create_task` (#26), with the Telegram and Slack routes
- [ ] **S8** — stamp a channel run with its channel surface (#208)
- [ ] **S9** — `docs/channels.md` matches what was built, including whichever
      SSRF answer S0 chose

Out of scope here, filed and left alone: `/link` minting a code (#10), dedupe on
`message_id` (#167), messages recorded for a channel run (#205), approvals
answering in the thread (#152).

## What "done" means

A Mattermost bot registered with a server URL and a webhook secret answers a
signed outgoing-webhook call end to end, and the same bot in event-stream mode
answers a `posted` event, both proven by a test rather than by a screenshot.

`#10` is not a blocker for either: a bot in `open` access mode answers an
unlinked sender. It **is** a blocker for `@slug` mentions, which refuse an
unlinked identity (`services/channels/mentions.py:80`) — so test the plain path,
and expect *"Link your account first"* on the mention path until #10 lands.

The ordering warning in #41 and #24 — *"fix #2 first, or this turns a dead
feature into a live outage"* — is **stale**. Both supervisors now sleep
unconditionally and Mattermost's backs off exponentially
(`mattermost.py:166-194`, covered by `test_channel_supervisor_yields.py`). What
is left of #2 is Slack's flat `asyncio.sleep(5)` (`slack.py:140`), which is not
in the path of this work.
