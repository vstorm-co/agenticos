# The HTTP API

Everything the console does, it does through this API. There is no private
surface: the same endpoints are available to you.

The interactive reference is generated from the code and served by the
deployment itself at **`/docs`**, with the schema at
`/api/v1/openapi.json`. Both are on in development and off in production —
`ENVIRONMENT` decides, so a production deployment does not publish its own
route list.

## Authenticating

Three ways in, for three different callers.

| | Header | For |
|---|---|---|
| **Organization API key** | `Authorization: Bearer aos_…` | A script, an HTTP client such as Postman, or an MCP client. Acts as the member who issued it, narrowed to the permissions it was issued with |
| **JWT** | `Authorization: Bearer <access token>` | A person, or something acting as one. Short-lived, refreshed with a refresh token |
| **Session cookie** | set by the console | The browser only — the token is HttpOnly and never reaches JavaScript |

### Organization API keys

A key is issued by a member, in one organization, from **Settings → API keys**
(or `POST /api/v1/api-keys` from a signed-in session). It carries that member's
authority, narrowed twice:

- **To the permissions it was issued with.** Pick a preset — *Read-only*,
  *Knowledge ingest*, *Full access* — or tick permissions from the
  [catalog](permissions.md). You can only grant what you hold.
- **To what the issuer may do now.** Every request re-reads the issuer's
  membership, so demoting them narrows each of their keys at once, and removing
  them from the organization stops every key they issued. A resource grant
  widens what a *person* may do to one row; it never widens a key past its
  permissions.

The key is shown **once**, in the response that creates it. Only a SHA-256 of it
is stored, and it never appears in a log line, an audit entry or an error body.
Lists show its prefix (`aos_1a2b3c4d`), which is also how an audit entry names
the key that acted — every entry recorded during a key-authenticated request
carries `via_api_key` in its details. A key can have an expiry, and revoking it
(`DELETE /api/v1/api-keys/{id}`) takes effect on its next request.

```bash
curl "$BASE/api/v1/me/permissions" \
  -H "Authorization: Bearer $AGENTICOS_KEY"
```

Two refusals are worth knowing:

- **`403` "API keys are not accepted on this endpoint"** — keys are accepted on
  the public API only: agents, runs and approvals, knowledge bases and RAG, skills,
  context files, artifacts, the ML services, `/me/permissions`, and an
  organization's members, invitations, groups and settings. The console's own
  routes, your account, leaving or handing over an organization, and key
  management itself stay session-only, so a leaked key cannot mint its successor.
- **`401` "Invalid, expired or revoked API key"** — the same sentence for each
  case, so a wrong key learns nothing about which keys exist.

Each key is also rate limited on its own, `RATE_LIMIT_API_KEY_PER_MINUTE`
requests a minute (600 by default), and a run or an ML call it makes counts
against those limits for the key rather than for its issuer.

### Sessions and revocation

A JWT access token is bound to the session its sign-in opened — the session's id
travels inside the token. Signing out everywhere (`DELETE /sessions`) deactivates
those sessions, and a bound token is then refused on its next use rather than
living out its few remaining minutes. That reaches an open chat WebSocket too: the
next frame on a revoked session closes the socket, not only the next HTTP request.

Refreshing does not start a new session — the refresh token rotates in place and
the access token keeps naming the same one — so a long-lived connection is not cut
off by a routine refresh.

## The organization header

**An API key acts in its own organization**, and needs no header. Sending
`X-Organization-Id` with a key is allowed only when it names that same
organization; naming another one answers `400` with
`details.header = "X-Organization-Id"` rather than switching tenant.

**A session token takes the tenant from `X-Organization-Id`.** A caller who
belongs to three organizations is a different principal in each, with a
different role and different grants, so send the header on every request. When
it is absent the request falls back to the caller's **personal organization** —
a script that forgets it acts there, with whatever agents, grants and budget
that organization has, and gets no error. Send the wrong one and you get a
refusal that looks exactly like the resource not existing — deliberately, so ids
stay unprobeable.

## Running an agent

```bash
curl -X POST "$BASE/api/v1/agents/$AGENT_ID/run" \
  -H "Authorization: Bearer $AGENTICOS_KEY" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "How do I rotate a provider key?"}'
```

The response carries the run id, the output and the status. Two optional fields
in the body are worth knowing: `conversation_id` continues an existing thread,
and `environment_id` picks [which environment](environments.md) answers.

!!! info "An API caller cannot route around governance"

    This endpoint goes through the same runner as the console, Slack and the
    widget. The run is recorded, the budget is checked before the model request,
    the approval gate applies, and the cost lands in the same dashboard.

    That is the point of one runner, and it is why there is no "fast path" that
    skips it.

The route carries a **rate limit rather than a permission gate**. Permission is
decided inside the service, against that specific agent's grants — a role gate
on a per-resource route [cannot see them](permissions.md).

`PATCH /api/v1/agents/{id}/metadata` sets an agent's **categories** and **tags**
with a body like `{"categories": [...], "tags": [...]}`, where an empty list
clears that facet. Values are normalized — trimmed, whitespace-collapsed,
case-folded and de-duplicated — and bounded: at most 10 categories and 20 tags,
each at most 32 characters, a longer item answering `422`. Like the run route it
carries no role gate; the grant-aware `agents:edit` check inside the service
decides, so a viewer holding an edit grant on one agent may retag it.

`GET /api/v1/agents` filters that catalog through repeatable `category` and `tag`
query parameters: values **OR within a facet** and **AND across facets**, matched
case-insensitively (a query value folds the way a stored one does, and a blank
value is ignored). The filter only narrows what you could already see — it never
crosses a tenant or a grant boundary.

The response also carries `categories` and `tags`: every distinct label on the
agents you could list, whatever the filter and the page — the choices a filter
menu offers. A private agent you cannot see adds none.
## The ML services

Four of the platform's services answer on their own, with no conversation and no
agent behind them: document analysis, OCR, speech to text and personal data
detection. They are gated on `ml:invoke` rather than `agents:run`, and
[The ML services](ml-services.md) is their reference.

```bash
curl -X POST "$BASE/api/v1/ml/privacy/pii" \
  -H "Authorization: Bearer $AGENTICOS_KEY" \
  -H "Content-Type: application/json" \
  -d '{"text": "write to ada@example.com"}'
```

## Worked examples

Each one runs with an organization key in `$AGENTICOS_KEY` and the API's origin
in `$BASE`. Create the key under **Settings → API keys** with the permissions the
example names; the console shows the key once.

**Put a document into a knowledge base and search it** — a key with
`collections:view` and `collections:edit` (the *Knowledge ingest* preset).
Ingestion runs in the background, so a search right after the upload may not find
the document yet; `GET /api/v1/kb/$KB_ID/documents` shows its status.

```bash
# Find the knowledge base, upload a file into it, and search it.
curl "$BASE/api/v1/kb" -H "Authorization: Bearer $AGENTICOS_KEY"

curl -X POST "$BASE/api/v1/kb/$KB_ID/documents" \
  -H "Authorization: Bearer $AGENTICOS_KEY" \
  -F "file=@policy.pdf"

curl -X POST "$BASE/api/v1/rag/search" \
  -H "Authorization: Bearer $AGENTICOS_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"collection_name\": \"$COLLECTION_NAME\", \"query\": \"refund window\"}"
```

**Run an agent and read what it cost** — `agents:run` and `runs:view`. The run
read carries its status, its tokens and its cost.

```bash
RUN_ID=$(curl -s -X POST "$BASE/api/v1/agents/$AGENT_ID/run" \
  -H "Authorization: Bearer $AGENTICOS_KEY" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Summarise this week'"'"'s tickets"}' | jq -r .run_id)

curl "$BASE/api/v1/runs/$RUN_ID" -H "Authorization: Bearer $AGENTICOS_KEY"
```

**Invite a member** — `members:manage`. The invitation is emailed; the response
carries its token once, for an inviter whose mail may not arrive.

```bash
curl -X POST "$BASE/api/v1/orgs/$ORG_ID/invitations" \
  -H "Authorization: Bearer $AGENTICOS_KEY" \
  -H "Content-Type: application/json" \
  -d '{"email": "new.hire@example.com", "role": "member"}'
```

**Retry what was rate limited, and nothing else.** A `429` carries
`Retry-After`; every other refusal is final for that request, and a `401` means
the key is gone — revoked, expired, or its issuer removed — so retrying it only
spends the limit.

```python
import time

import httpx


def call(client: httpx.Client, method: str, path: str, **kwargs) -> httpx.Response:
    for _ in range(5):
        response = client.request(method, path, **kwargs)
        if response.status_code != 429:
            response.raise_for_status()
            return response
        time.sleep(int(response.headers.get("Retry-After", "60")))
    response.raise_for_status()
    return response


client = httpx.Client(
    base_url="https://agenticos.example.com/api/v1",
    headers={"Authorization": f"Bearer {KEY}"},
)
print(call(client, "GET", "/me/permissions").json())
```

## Streaming

Two WebSocket endpoints, for two audiences.

- **`/api/v1/ws/agent`** — the authenticated one the console uses. A frame
  carrying `agent_id` runs that published agent; a frame without one gets the
  general assistant. Authenticate with the subprotocol `access_token.<token>`,
  where the token is a session JWT. An organization API key is refused here: a
  turn on this socket is a person at the keyboard, with their personal
  connections. Integrations run agents with `POST /api/v1/agents/{id}/run`.
- **`/api/v1/embed/{public_key}/ws`** — the public one behind an
  [embed](channels.md), for a visitor who has no account.

Both stream tokens as they arrive (an agent with an output guardrail streams a step
at a time, see [Guardrails](reference/capabilities.md#guardrails)) and both produce
an ordinary run, with the same books as everything else.

A third, **`/api/v1/ws/events`**, only listens. It is how an open console
[keeps up with changes made elsewhere](console.md#changes-made-elsewhere):
authenticated the same way, with the organization in `?organization_id=`, it
sends one JSON frame per successful public write in that organization —
`resource`, `id`, `action` (`created`, `updated` or `deleted`), `surface`
(`console`, `api_key`, `mcp` or `assistant`) and who made it — and only for rows
the caller may read.

## Errors

One envelope, everywhere:

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Agent not found",
    "details": { "agent_id": "..." }
  }
}
```

`details` carries values rather than rows, so it names the field that explains a
refusal and never a database record. When a refusal is about something the
caller submitted, `details.fields` is a list of `{field, message}` — which is
what lets a form mark the input instead of showing a sentence somebody has to
re-scan the page for.

A `401` carries `WWW-Authenticate: Bearer`. A cross-tenant read answers `404`,
not `403`, for the reason above.

## Conventions

| | |
|---|---|
| Prefix | `/api/v1` |
| Create | `POST`, `201` |
| Partial update | `PATCH` |
| Delete | `DELETE`, `204`, no body |
| Pagination | `skip` (≥ 0) and `limit` (1–100) query parameters; list responses carry `items` and `total` |
| Paths | kebab-case |

## Stability, honestly

**The public API has a written compatibility promise; the rest of `/api/v1` does
not.** The routes an API key may call are listed in their own OpenAPI document at
**`/api/v1/public/openapi.json`**, served in every environment. Within v1 a change
to one of them is additive — a new route, a new optional field, a new response
field or enum value — and a client must ignore response fields it does not know.
Removing or renaming something there happens only after it has been marked
`deprecated` in that document for at least 90 days and listed in the
[release notes](release-notes.md); a change that cannot be made that way goes into
`/api/v2`, beside v1.

The console's own routes carry no such promise and change with the console; a key
cannot call them. There is no client library yet.

The [agent spec](reference/spec.md) carries its own promise: it is versioned and
only moves forward.

## Recap

- **`/docs`** on the deployment is the generated reference; it is off in
  production by design.
- Three ways in: **an organization API key, a JWT, or the console's cookie**.
- A key carries its issuer's authority **narrowed to its permissions and to the
  issuer's current role**, is shown once, and works on the public API only.
- **A key acts in its own organization; a session reads `X-Organization-Id`**
  and falls back to the personal organization without it. The wrong one looks
  like a missing resource.
- Running an agent over HTTP is the **same runner** — budget, approval and audit
  all apply.
- **The public API is in `/api/v1/public/openapi.json`** and changes only
  additively within v1, with 90 days' deprecation; there is no SDK yet.
