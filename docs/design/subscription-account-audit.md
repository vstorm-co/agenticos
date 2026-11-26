# Subscription account review — 2026-11-22

Scope: model access through the isolated subscription gateway, not the Desktop
runtime's own CLI account. The two paths have different authentication stores and
usage interfaces. OpenBot's native-runtime support is not evidence that every
vendor exposes its billing data through a model gateway.

| Connection | Sign-in | Usage source | Limitations |
|---|---|---|---|
| Claude Code | Browser OAuth and manual callback return | OAuth usage metadata: five hours, weekly, and model-family windows; legacy and scoped response formats | Undocumented provider endpoint; refresh every five minutes and expose read failures |
| ChatGPT (Codex) | Browser OAuth and manual callback return | ChatGPT account usage metadata | Requires the selected account's ChatGPT account ID; disabled zero-duration windows are omitted |
| Google Antigravity | Browser OAuth and manual callback return | Google quota summary grouped by model family | Project discovery must succeed; omitted percentages stay unknown |
| Kimi Code (kimi.com) | Device authorization | Kimi Code weekly summary and rolling windows | Uses the kimi.com issuer and API; not a kimi.com consumer-chat subscription |
| Kimi Code (kimi.ai) | Device authorization | Kimi Code weekly summary and rolling windows | Uses the separate kimi.ai issuer and API; accounts do not move between regions |
| Devin | Browser OAuth and manual callback return | Daily and weekly quota snapshots supplied with the gateway credential | Snapshot freshness is displayed; no synthetic live refresh through a model request |
| Grok (xAI) | Device authorization | Not currently available through this gateway connection | OpenBot reads `_x.ai/billing` through the native Grok ACP connection; this is a separate transport |
| Meta AI | Device authorization | Not currently available through this gateway connection | No verified allowance read contract in this transport; do not infer it from per-response token usage |

Device authorization is selected by the returned flow, not by whether a separate
user code exists. A complete authorization link can work without a code to copy.
All eight gateway identifiers are supported by the pinned CLIProxyAPI v8.0.80
management dispatcher. Kimi's regional identifier was previously mislabeled in
the console. Existing provider IDs remain unchanged.

## Evidence

- [Pinned gateway dispatcher](https://github.com/router-for-me/CLIProxyAPI/blob/v8.0.80/internal/api/handlers/management/auth_files_v8.go)
- [Pinned gateway device flows](https://github.com/router-for-me/CLIProxyAPI/blob/v8.0.80/internal/api/handlers/management/auth_files_provider_oauth.go)
- [Devin reported quota signals](https://github.com/router-for-me/CLIProxyAPI/blob/v8.0.80/internal/auth/devin/record.go)
- [Kimi's own usage implementation](https://github.com/MoonshotAI/kimi-cli/blob/main/src/kimi_cli/ui/shell/usage.py)
- [Kimi's own platform URL](https://github.com/MoonshotAI/kimi-cli/blob/main/src/kimi_cli/auth/platforms.py)
- [OpenBot Claude usage behavior](https://github.com/nightly-labs/openbot/blob/40c0ca2b1b63caa6078658f33706c798a75254b4/src/backend/claude-client.ts)
- [OpenBot Grok usage behavior](https://github.com/nightly-labs/openbot/blob/40c0ca2b1b63caa6078658f33706c798a75254b4/src/backend/grok-client.ts)

OpenBot was inspected as a behavioral reference; its implementation is not copied.
The Claude usage path and OAuth beta identifier were also verified in the installed
Anthropic Claude Code 2.1.330 executable, without reading user credentials.

## Verification boundary

Transport fixtures cover serialization, response validation, missing data, malformed
percentages, private-error redaction, selected regional/account identity and UI
flow behavior. They do not establish that a real account is eligible for a vendor's
plan, that a vendor currently accepts its OAuth client, or that inference succeeds.
Live-account acceptance remains manual; no account is logged in by the tests and
no model requests are used to discover quotas.

An isolated anonymous start-and-cancel probe on 2026-11-22 successfully initiated all eight provider flows and deleted its temporary gateway scope. This verifies initiation only, not provider approval or account eligibility.
