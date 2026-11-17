# AgenticOS for Mattermost

Install this server plugin to connect a Mattermost server to **your own AgenticOS
instance**. It creates a local bot, adds it to the chosen team/channel and registers
it with the selected AgenticOS agent. No shared service or AgenticOS Bridge key is
needed. AgenticOS handles conversations through its existing Mattermost event
stream; the plugin does not proxy messages or run models.

## Install and connect

This first bundle targets Linux amd64/arm64 and declares Mattermost 10.11 or later.
A production Mattermost installation has not yet been used for acceptance testing.
Use the AgenticOS version containing PR #2805; the plugin uses its channel and
agent-exposure APIs. Publish the agent before connecting it.

1. Build with Go, Python 3 and Make: `make check bundle` in this
   directory. The build selects the pinned Go 1.26.11 toolchain, downloading it into Go
   caches if needed; it does not replace your system Go. The SDK and dependency
   checksums are pinned in `go.mod` and `go.sum`.
2. Upload `dist/co.vstorm.agenticos-0.1.0.tar.gz` in **System Console → Plugins →
   Plugin Management**, then enable **AgenticOS**. Your server must allow plugin
   uploads, bot account creation and bot access tokens. Keep ordinary users'
   personal access tokens disabled if you do not otherwise need them.
3. In the plugin settings, enter your AgenticOS HTTPS origin, organization UUID
   and published agent UUID. Find IDs in the corresponding AgenticOS resource URLs
   or the API. Both servers need valid TLS certificates. AgenticOS must reach
   Mattermost's HTTPS **Site URL**, including its WebSocket endpoint; Mattermost
   must reach AgenticOS. Private network origins are supported.
4. As a Mattermost **system administrator**, run `/agenticos connect` in the team
   channel where the bot should be available. The private dialog names the target
   instance and organization. Enter a short-lived AgenticOS access token obtained
   through your instance's [authentication API](https://vstorm-co.github.io/agenticos/api/).
   Its user needs `channels:manage` and permission to publish the selected agent.
   Never paste a token into a channel, slash command or plugin setting.
5. Check `/agenticos status`, then the channel's state in **AgenticOS → Channels**.
   Each person links their own Mattermost identity to AgenticOS using the bot's
   link prompt before the agent accepts their messages. A DM reaches the agent
   directly; in a channel, mention `@agenticos` or the published agent's slug.

The dialog credential is a temporary **AgenticOS access token**, not your login
password, bridge key, provider credential or Mattermost bot token. Instances using
SSO can obtain the same short-lived access token through their existing authorized
API session; the plugin does not implement another login flow.

## Commands

All commands are restricted to Mattermost system administrators and reply privately.

| Command | Effect |
| --- | --- |
| `/agenticos connect` | Open the one-time pairing dialog for the configured target |
| `/agenticos status` | Show registration state; this is not a live health probe |
| `/agenticos invite` | Add the connected bot to the current team/channel |
| `/agenticos disconnect` | Ask for fresh AgenticOS authorization, revoke the Mattermost bot token and delete its AgenticOS registration |

One plugin installation connects one agent to one AgenticOS instance. The bot can
join several explicitly selected channels. Use the manual channel setup for
multiple independent bots. Disconnect before changing the instance, organization
or agent. Disconnect targets the **saved original instance**, even after a settings
change. It leaves the local bot user, memberships and existing messages intact.

## Credentials and failure handling

- The AgenticOS access token exists only during the setup request. The plugin
  never writes it to settings, its KV store, logs or URLs. Disable HTTP body
  recording for `/plugins/co.vstorm.agenticos/setup` and the AgenticOS channel APIs
  in any reverse proxy or external request recorder.
- Mattermost creates its own bot access token. The plugin sends it directly to the
  configured AgenticOS instance, whose organization-bound Vault stores it. The
  plugin saves only the token's revocation ID and non-secret connection metadata.
- Only a system administrator can open or submit a setup dialog. Its nonce is
  single-use, expires after five minutes and is bound to the administrator,
  channel, team, action and target configuration. Setup mutations share the SDK's
  cluster mutex. HTTP redirects and proxy-environment forwarding are disabled;
  TLS verification remains enabled. Provider error bodies are never shown.
- Every chat sender still uses their own AgenticOS permissions. Pairing does not
  give other Mattermost users the setup administrator's authority.
- If registration or binding fails, the new bot token is revoked and setup
  metadata remains for explicit cleanup. Use `/agenticos disconnect` before
  retrying. A lost registration response can leave an unusable channel entry in
  AgenticOS; check Channels for `Mattermost plugin <bot-id>` and delete that entry.
  Requests with unknown acceptance are never automatically repeated.
- Disconnect revokes the local token first. If remote cleanup fails, its IDs remain
  available for another disconnect attempt. If a process stops between token
  creation and saving its ID, revoke the token named **AgenticOS plugin connection**
  from the bot's Mattermost account before retrying. This narrow cross-server crash
  window cannot be made transactional by the plugin.
- Disabling/uninstalling a plugin is **not** token revocation. Disconnect before
  uninstalling; in an emergency revoke the bot token in Mattermost and remove the
  channel registration in AgenticOS. The SDK's KV journal must remain intact until
  cleanup finishes. There is no central revocation service.

## Development and verification

`make check` runs formatting checks, Go vet, race-enabled tests and a pinned
`govulncheck` scan against the current Go vulnerability database. Tests cover
pairing/binding, tenant headers, refusal of repeated setup, single-use admission,
configuration changes, expired/forged dialogs, token revocation, retained cleanup
state, redirect refusal, bounded response parsing and credential exclusion from
persisted plugin metadata. They use a local TLS HTTP server and a fake Mattermost
API; they do not prove that a live Mattermost installation delivers messages.

`make bundle` cross-compiles both architectures and validates the archive's
manifest, executable permissions, ELF architecture headers and bundled logo.
CI repeats these checks and publishes a short-lived build artifact for the PR.
The plugin is not submitted to the Mattermost Marketplace and its bundle is not
signed. Install only an artifact built from reviewed source.

See [the channel guide](https://vstorm-co.github.io/agenticos/channels/) for identity
linking, sender permissions, approvals, transport behavior and manual setup.
