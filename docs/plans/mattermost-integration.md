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

## The two decisions — settled 2026-08-09

**Both answered before any code was written, which is what S0 was for.** The
reasoning is kept below rather than replaced by the answer, because the next
person to widen `api_base_url` validation needs to know what was weighed.

1. **`api_base_url` is validated on scheme and shape only** — option (1). Reject
   userinfo, anything that is not `http`/`https`, and anything malformed; private
   and loopback addresses pass. `validate_webhook_url` is **not** used on this
   field, and the validator says why in its docstring so nobody "fixes" it back.
2. **`webhook_secret` is sealed first** (S1), in its own commit, before any field
   that writes one exists.

Two more, decided at the same time and recorded here because they change the
shape of the branch rather than of one step:

3. **This is one branch and one pull request**, covering S1–S9 plus #10, #157,
   #205, #167 and #152. Each step is a commit that stands on its own, so the
   branch can still be cut in half if it outgrows a single review.
4. **Testing is against a real Mattermost server the author already runs.**
   Nothing is added to `docker-compose.dev.yml`; what `docs/channels.md` owes
   instead is an exact account of which token comes from where and what is pasted
   where. Automated verification is the unit and API layers — the integration and
   Playwright layers are deliberately not extended here.

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

**Chosen: (1)**, with the reason written into the validator's docstring, and the
refusal tested. `api_base_url` is not a callback we were handed by a stranger; it
is infrastructure an operator with `channels` rights typed about their own
company. The SSRF surface is the same one they already have by registering an MCP
server. The cost is stated plainly: a member who may manage channel bots can
point one at an internal address, and the bot token goes with it. That is a
consequence of the permission, not of this field.

### Where the sealing of `webhook_secret` belongs

Sealing it (#22) touches the Telegram route as well, and the column is named
`webhook_secret` rather than `webhook_secret_encrypted`. Either do #22 first and
build on a sealed column, or add the field now and seal both in one migration
afterwards. Doing it second means one migration re-sealing rows written in the
meantime; doing it first means #24 lands on a moving column.

**Chosen: sealing first**, in its own commit, because the field being added is
precisely a credential and adding a plaintext write path we intend to remove is
work done twice.

## Order

Each step is its own commit, verified by its own tests. Two phases: the first
makes Mattermost configurable at all, the second closes the gaps that every
channel shares and that "all the features" means.

### Phase 1 — Mattermost becomes usable

- [x] **S0** — decide the two questions above, record the answers here
- [x] **S1** — seal `webhook_secret` (#22): `webhook_secret_encrypted`, unsealed
      in the two webhook routes, one migration re-sealing existing rows. Never in
      a response schema.
- [x] **S1b** — refuse a Telegram webhook that carries no secret (#4). Not in the
      original list: the guard was `if secret and not verify(...)`, on a line S1
      was rewriting anyway, and leaving a known auth bypass in a line being
      edited is worse than the scope it adds. `update` mints one when a bot
      enters webhook mode, which is the half that made null the normal state
- [x] **S2** — fix the webhook URL at both call sites (#24, 22a), and assert the
      built URL resolves against `app.routes` so the two cannot drift again
- [x] **S3** — `api_base_url` and `webhook_secret` on `ChannelBotCreate` and
      `ChannelBotUpdate`, on `channel_bot_repo.create` and on the update path,
      with validation per S0. `ChannelBotRead` gets `api_base_url` (it is an
      address, not a credential) and `has_webhook_secret` (a boolean, never the
      value)
- [x] **S4** — accept an operator-supplied `webhook_secret` for Mattermost
      instead of minting one; keep minting for Telegram, where we hand it out.
      One place decides, and says which platform is which and why
- [x] **S5** — the panel: a server-URL field and a webhook-secret field, shown
      for Mattermost the way the Slack credentials are shown for Slack
      (`components/agents/channel-bots-panel.tsx:211`). Copy per `next-intl`
- [x] **S6** — `app/commands/channel.py`: register a Mattermost bot from the CLI,
      because a deployment behind a VPN has no browser pointed at it
- [x] **S7** — the three webhook routes hand their work to `spawn` rather than
      `asyncio.create_task` (#26). `spawn`, not `spawn_after_commit`: they read a
      bot and write nothing, so there is no transaction for the work to outrun
- [x] **S8** — **already done, and the issue is stale.** `RunSurface.MATTERMOST`
      and `RunSurface.EMBED` both exist and are assigned, `_SURFACES` in
      `mentions.py` covers all three platforms, and
      `tests/test_run_surface.py` asserts the recorded value per entry point.
      Fixed by `cd965175` (#202); #207 and #208 were never closed
- [x] **S9** — `docs/channels.md` matches what was built: the SSRF answer S0
      chose, and an exact account of which token comes from where and what is
      pasted where, because that is what manual verification runs off

### Phase 2 — the gaps every channel shares

Each one is Mattermost-visible and none is Mattermost-only: Slack and Telegram
get the same fix, and each needs its own tests on all three.

- [ ] **S10** — `/link` mints a code (#10). Nothing writes `link_code`; it is only
      read (`repositories/channel_identity.py:32`) and cleared (`:90`), so
      `/link <code>` cannot succeed and `@slug` refuses every sender
      (`services/channels/mentions.py:80`). **Taken first in this phase**, because
      until it lands half of what manual testing tries comes back as *"Link your
      account first"* and reads like a broken Mattermost
- [x] **S11** — dedupe on `message_id` (#167). A retried delivery is a second run
      with a second bill. Mattermost retries a slow webhook and our route answers
      200 before doing the work, so this surfaces here sooner than elsewhere
- [ ] **S12** — a channel run records its messages (#205). Today it has a cost and
      no content, so Activity cannot show what the bot actually said
- [ ] **S13** — charts on a channel (#157). Three docstrings promise a PNG that
      nothing renders. The Mattermost adapter already uploads `image_png`
      correctly; what is missing is whatever was meant to produce it
- [ ] **S14** — a tool approval answers in the thread (#152). Today the bot says
      *"check the approvals queue"* and the thread never hears back. The largest
      of the five and the last, because it builds on S12's message recording

## What "done" means

Phase 1: a Mattermost bot registered with a server URL and a webhook secret
answers a signed outgoing-webhook call end to end, and the same bot in
event-stream mode answers a `posted` event.

Phase 2: `/link` completes from a Mattermost DM, `@slug` runs as the person who
typed it, a retried webhook produces one run rather than two, that run has its
messages in Activity, a chart arrives as an image, and an approval is answered in
the thread that asked for it.

Proven by tests at the unit and API layers, and by the author against a real
Mattermost server. Neither `tests/integration/` nor the Playwright suite is
extended for this — deliberately, and said out loud so a later reader does not
mistake the gap for an oversight. What that leaves unproven is anything only a
real server shows: whether Mattermost's actual `posted` frame matches the shape
`_from_socket` expects, and whether the outgoing-webhook body arrives in the
encoding we assume. Those are exactly what the manual pass is for.

The ordering warning in #41 and #24 — *"fix #2 first, or this turns a dead
feature into a live outage"* — is **stale**. Both supervisors now sleep
unconditionally and Mattermost's backs off exponentially
(`mattermost.py:166-194`, covered by `test_channel_supervisor_yields.py`). What
is left of #2 is Slack's flat `asyncio.sleep(5)` (`slack.py:140`), which is not
in the path of this work.
