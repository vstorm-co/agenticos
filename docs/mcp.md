# MCP — the tools nobody here has to write

[Model Context Protocol](https://modelcontextprotocol.io) servers are this
platform's answer to "you cannot write a connector for everything". An
organization points at a server, its tools appear in the Builder, and no code
changes on our side. Everything in the [capability catalog](reference/capabilities.md)
is code we wrote and hold to 100% coverage; everything here is a URL somebody
pasted.

The two are not alternatives. A capability is the right shape for something the
platform must guarantee — a budget guard, a sandbox, retrieval that cites its
sources. MCP is the right shape for the forty SaaS products a company happens to
use, where the guarantee that matters is only "the tools are the ones the vendor
published".

## A connection

One row pointing at a remote server. The transport — streamable HTTP or
server-sent events — is inferred from the URL, so an SSE-only server like
Atlassian works alongside a streamable-HTTP one with nothing to configure.

| | |
|---|---|
| `name` | Also the tool prefix. See [Name collisions](#name-collisions) |
| `url` | SSRF-validated before we ever request it |
| `auth_token` | Sealed in the [vault](secrets.md), never returned by any endpoint |
| `allowed_tools` | An allowlist, or null for "everything the server offers" |
| `is_enabled` | Off without losing the credential |
| `last_status` | What the last probe found, and when |

### Personal or organization-wide

Two kinds, and the difference is the point.

**Personal** (Settings → Your connections) is scoped to one member and reached
only by their own assistant. Its credential is sealed to the *member*, not to an
organization — a personal connection has none, and its owner may belong to
several, so binding it to whichever was active when they added it would make the
token unreadable the moment they switched.

**Organization** is scoped to the organization, gated on `connections:manage`, and
is the only kind a published agent's spec may name. A published agent that
answered differently depending on whose session ran it could not be reviewed or
reasoned about, which is the whole reason for the restriction.

```
GET  /api/v1/me/mcp-connections     personal
GET  /api/v1/mcp-connections        organization, requires connections:manage
POST /api/v1/mcp-connections/{id}/test   probe it, list its tools, store the status
```

A spec names organization connections by id in `mcp_server_ids`. Deleting a
connection an agent still names loses that server for the agent, not the run.

## Authentication

Three modes, which is the only thing that really varies between servers.

**None.** Public documentation servers, mostly — Cloudflare's docs server needs no
credential at all.

**Token.** A bearer token pasted once and sealed. Each catalog entry carries its
own hint about where to get one, because generic instructions are the main reason
token setup fails. `PATCH` with `auth_token: ""` clears it.

**OAuth 2.1.** Most business servers (Notion, Linear, Atlassian, Asana) return
`401` with a `WWW-Authenticate` header pointing at RFC 9728 protected-resource
metadata, and the flow runs from there:

1. **Discover** — probe the server, resolve its authorization server, fetch RFC
   8414 metadata.
2. **Register** — RFC 7591 dynamic client registration.
3. **Consent** — a PKCE authorization URL with `state` and an RFC 8707 resource
   indicator; the browser goes there.
4. **Exchange** — the callback swaps the code for tokens, then redirects the
   browser back to the MCP servers page, which says whether it worked. That is
   the only place the outcome can be told: the person is looking at a page they
   did not navigate to themselves.
5. **Refresh** — when the access token expires.

Every URL reached in that flow is SSRF-checked, not just the one somebody typed:
discovery means the *remote server* chooses most of the addresses we call, and
those deserve the same policy as a webhook.

A step that fails says **which step gave up and what class of thing raised**,
never what the upstream client wrote. `httpx` puts the failing request in its
message and the two requests here are a client registration and a token grant,
so quoting it would carry a token endpoint — reached with credentials — into the
browser; a pydantic error over an unreadable token response echoes the payload it
rejected, which is the tokens. Both stay in the server log, which is where an
operator already looks.

!!! warning "An organization's OAuth connection is still someone's grant"

    `POST /mcp-connections/oauth/start` produces a connection the organization
    owns, which is what a shared service account is for. But the grant remains the
    consenting person's at the provider: revoking their access there stops the
    organization's server working until it is authorized again. Consent with an
    account the organization controls.

## What happens on a turn

Each server is probed with a short `tools/list` round-trip — 3 seconds — before
the turn starts, and the probes run concurrently.

**An unreachable server is skipped with a warning, not raised.** Pydantic AI
enters every toolset when a run starts, so a dead server would otherwise abort the
whole turn: one expired token on one connection would take down every agent that
names it, including the ones that never needed it.

That is a deliberate trade. A skipped server means the model answers without those
tools rather than not answering, which is right for a chat turn and wrong if you
assumed a tool was always there. The `/test` endpoint and `last_status` are how you
find out; the [audit trail](governance.md#audit) records what actually ran.

### Name collisions

Tools are prefixed with the connection name — `github-work` becomes
`github_work_*` — because two servers exposing the same tool name make Pydantic AI
raise on duplicate names, which aborts the turn.

Two connections whose names reduce to the same prefix are deduplicated, first one
wins, with a warning naming the loser. Deployment-managed servers are ordered
first, so they win over a user connection that happens to pick the same name.

An allowlist filters *before* prefixing, so it compares against the unprefixed
names picked in the UI.

## The catalog

A picker that starts empty and asks for a URL is a picker nobody uses, so the
common servers ship with the metadata needed to connect them: the URL, how it
authenticates, what to tell whoever is pasting a credential.

This is a hand-maintained list, not a mirror of the public registry. Each entry is
a small promise — that somebody looked at the server, that the auth flow works,
that the description is honest — and a mirrored registry cannot make that promise.

`(self-hosted)` below means the entry describes the server but you supply the URL:
either because it runs on your own infrastructure, or because the vendor issues a
per-account endpoint.

### Development

| Server | Auth | URL |
|---|---|---|
| GitHub | token | `https://api.githubcopilot.com/mcp/` |
| Cloudflare docs | none | `https://docs.mcp.cloudflare.com/mcp` |
| GitLab | token | self-hosted |
| Postman | token | self-hosted |
| Vercel | oauth | self-hosted |
| Netlify | oauth | self-hosted |
| Railway | token | self-hosted |
| Replit | oauth | self-hosted |
| Hugging Face | token | self-hosted |

### Project management

| Server | Auth | URL |
|---|---|---|
| Linear | oauth | `https://mcp.linear.app/sse` |
| Jira & Confluence | oauth | `https://mcp.atlassian.com/v1/sse` |
| Asana | oauth | `https://mcp.asana.com/sse` |
| ClickUp | oauth | self-hosted |
| Trello | oauth | self-hosted |
| Todoist | oauth | self-hosted |

### Data and analytics

| Server | Auth | URL |
|---|---|---|
| PostgreSQL | token | self-hosted |
| Supabase | token | self-hosted |
| Elasticsearch | token | self-hosted |
| Airtable | token | self-hosted |
| Snowflake | token | self-hosted |
| Databricks | token | self-hosted |
| Google BigQuery | oauth | self-hosted |
| PostHog | token | self-hosted |
| Mixpanel | token | self-hosted |

### Communication, support, knowledge

| Server | Auth | URL |
|---|---|---|
| Slack | oauth | `https://mcp.slack.com/mcp` |
| Zoom | oauth | self-hosted |
| Intercom | oauth | `https://mcp.intercom.com/sse` |
| Notion | oauth | `https://mcp.notion.com/mcp` |
| GitBook | token | self-hosted |

### Finance, sales, commerce

| Server | Auth | URL |
|---|---|---|
| Stripe | token | `https://mcp.stripe.com` |
| PayPal | oauth | `https://mcp.paypal.com/sse` |
| Xero | oauth | self-hosted |
| HubSpot | oauth | self-hosted |
| Shopify | oauth | self-hosted |

### Observability

| Server | Auth | URL |
|---|---|---|
| Sentry | oauth | `https://mcp.sentry.dev/mcp` |
| Grafana | token | self-hosted |
| PagerDuty | oauth | self-hosted |

### Marketing and design

| Server | Auth | URL |
|---|---|---|
| Mailchimp | oauth | self-hosted |
| Resend | token | self-hosted |
| Webflow | oauth | self-hosted |
| Wix | oauth | self-hosted |
| WordPress.com | oauth | self-hosted |
| Semrush | token | self-hosted |
| Similarweb | token | self-hosted |
| Figma | oauth | self-hosted |
| Miro | oauth | self-hosted |
| Lucid | oauth | self-hosted |
| Excalidraw | none | self-hosted |

### Automation, storage, productivity, media

| Server | Auth | URL |
|---|---|---|
| Zapier | oauth | self-hosted |
| Make | token | self-hosted |
| n8n | token | self-hosted |
| Box | oauth | self-hosted |
| Dropbox | oauth | self-hosted |
| Calendly | oauth | self-hosted |
| Typeform | oauth | self-hosted |
| SurveyMonkey | oauth | self-hosted |
| DeepL | token | self-hosted |
| ElevenLabs | token | self-hosted |

### Anything else

**Custom server** — any MCP server reachable by URL. Its tools are introspected on
connect, and nothing about it needs to be in the catalog first. The catalog saves
somebody a URL lookup; it is not a gate.

To add an entry to the list, see
[Add a server to the MCP catalog](howto/add-mcp-server.md).

## What MCP does not get you

- **A coverage guarantee.** Catalog entries are metadata. The tools are the
  vendor's, and they can change under you between one turn and the next.
- **Approval gates.** Per-tool approval is declared by capabilities in code. An
  MCP server's tools are discovered at run time, so there is nothing to have
  declared them; keep genuinely dangerous servers out of an organization's
  connections rather than assuming a gate.
- **Cost attribution.** What a server does on its own side is not in this
  platform's [budget](governance.md#budgets). Only the model tokens are.
