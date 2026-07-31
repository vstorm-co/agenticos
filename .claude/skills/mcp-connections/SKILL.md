---
name: mcp-connections
description: Work with MCP servers — connect one, add an entry to the server catalog, debug "the agent cannot see my MCP tools" or a failing OAuth flow, or change how connections are probed, prefixed or filtered. Use when the ask involves an external SaaS tool (GitHub, Linear, Notion, Slack, Stripe, Postgres…) and before writing a capability that would just be an API client for one.
---

# MCP connections

**Read `docs/mcp.md`** for the model and `docs/howto/add-mcp-server.md` for adding a
catalog entry. Code: `app/agents/mcp.py`, `app/agents/mcp_oauth.py`,
`app/services/mcp_connection.py`, `app/services/mcp_catalog.py`.

## Reach for this before writing a capability

If the ask is "let the agent read our Linear issues", the answer is usually a
connection, not code. A capability is right for something the platform must
*guarantee* — a budget guard, a sandbox, retrieval that cites sources. MCP is right
for the forty SaaS products a company happens to use.

Adding a catalog entry is one object in `app/core/catalog/mcp_servers.json`. No code.
And nothing needs to be in the catalog for a URL to work — the *Custom server* entry
introspects any reachable server.

## Personal vs organization

Two kinds, differing in exactly two places and both are the point:

|  | Personal | Organization |
|---|---|---|
| Reached by | That member's own assistant | Any agent whose spec names it |
| Gate | Owner only | `mcp:manage` |
| Credential sealed to | The **member** | The **organization** |
| A spec may bind it | **No** | Yes, via `mcp_server_ids` |

A published agent that answered differently depending on whose session ran it could
not be reviewed or reasoned about — that is why only org connections are bindable.

A personal connection is sealed to the member rather than an organization because it
has none, and its owner may belong to several: binding it to whichever was active
would make the token unreadable the moment they switched.

## The four behaviours that surprise people

**A dead server is skipped, not raised.** Each server gets a 3-second `tools/list`
probe before the turn; failures log a warning and the turn proceeds without those
tools. Pydantic AI enters every toolset when a run starts, so raising would let one
expired token abort every agent that names the connection. The trade is real: a
skipped server means the model answers *without* the tools. `/test` and `last_status`
are how you find out.

**Tools are prefixed with the connection name.** `github-work` → `github_work_*`.
Two servers exposing the same tool name make Pydantic AI raise on duplicates, which
aborts the turn.

**Two connections reducing to the same prefix are deduplicated**, first one wins, with
a warning naming the loser. Deployment-managed servers are ordered first.

**An allowlist filters before prefixing**, so it compares unprefixed names.

## OAuth

Five steps in `mcp_oauth.py`: discover (RFC 9728 → RFC 8414) → dynamic client
registration (RFC 7591) → consent URL (PKCE + state + RFC 8707 resource indicator) →
exchange → refresh. Split across two HTTP requests because this is a web app, not a
CLI.

**Every URL in that flow is SSRF-checked**, not just the one somebody typed —
discovery means the remote server picks most of the addresses we call. Same policy as
webhooks (`app/core/sanitize.validate_webhook_url`), run in a thread because it
resolves DNS. Do not add a request path that skips it.

An organization's OAuth connection is still the consenting person's grant at the
provider. Revoking their access there breaks the organization's server.

## MCP tools are not gated

`approval_required_tools` iterates `spec.capabilities` only. MCP tools are discovered
at run time, so nothing declared them and nothing approves them. Say so plainly when
reviewing a change that adds a connection to a published agent — do not imply a gate
exists.

Cost is the same story: what a server does on its own side is outside this platform's
budget. Only model tokens are counted.

## Routes

```
GET  /api/v1/me/mcp-connections            personal
GET  /api/v1/mcp-connections               organization  (mcp:manage)
POST /api/v1/mcp-connections/{id}/test     probe, list tools, persist last_status
POST /api/v1/mcp-connections/oauth/start   declared above /{id} — that route parses
                                           its segment as a UUID and would 422
```

`PATCH` with `auth_token: ""` clears a stored credential.

## Test

`frontend/e2e/mcp-servers.spec.ts` covers the UI. For the backend, the interesting
assertions are the refusals: a personal connection is not bindable by a spec, a
connection from another organization is unreachable, and a prefix collision drops the
second server rather than aborting the turn.
