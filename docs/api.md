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

A key is issued by a member, in one organization, from **Settings → API**
(or `POST /api/v1/api-keys` from a signed-in session). It carries that member's
authority, narrowed twice:

- **To the permissions it was issued with.** Pick a preset — *Read-only*,
  *Knowledge ingest*, *Full access* — or tick permissions from the
  [catalog](permissions.md). You can only grant what you hold.
- **To what the issuer may do now.** Every request re-reads the issuer's
  membership, so demoting them narrows each of their keys at once. Removing them
  from the organization, or their leaving it, revokes every key they issued and
  every app they connected - for good, so inviting them back wakes none of it. A resource grant
  widens what a *person* may do to one row; it never widens a key past its
  permissions.

The key is shown **once**, in the response that creates it. Only a SHA-256 of it
is stored, and it never appears in a log line, an audit entry or an error body.
Lists show its prefix (`aos_1a2b3c4d`), which is also how an audit entry names
the key that acted — every entry recorded during a key-authenticated request
carries `via_api_key` in its details. A key can have an expiry, and revoking it
(`DELETE /api/v1/api-keys/{id}`) takes effect on its next request.

**A key is not its issuer's person.** A run it starts is owned, budgeted and
audited as the issuer, but it reaches none of their personal state: no
[memory](reference/capabilities.md#whose-notes-and-who-may-hear-them), no search
of their past conversations, no sites they kept signed in for the browser, and
no user-scoped sandbox workspace. Whoever holds the key is a script, not the
person, so the run answers as it would on a public widget.

```bash
curl "$BASE/api/v1/me/permissions" \
  -H "Authorization: Bearer $AGENTICOS_KEY"
```

Two refusals are worth knowing:

- **`403` "API keys are not accepted on this endpoint"** — keys are accepted on
  the public API only: agents, runs and approvals, knowledge bases and RAG, skills,
  context files, projects, apps, the ML services, `/me/permissions`, and an
  organization's members, invitations, groups and settings. The console's own
  routes, your account, leaving or handing over an organization, and key
  management itself stay session-only, so a leaked key cannot mint its successor.
- **`401` "Invalid, expired or revoked API key"** — the same sentence for each
  case, so a wrong key learns nothing about which keys exist.

Each key is also rate limited on its own, `RATE_LIMIT_API_KEY_PER_MINUTE`
requests a minute (600 by default), and a run or an ML call it makes counts
against those limits for the key rather than for its issuer. Both checks run
before the key is looked up, on a request and on a socket handshake: a key is
counted by a digest of the whole token - never by its prefix, which listings show -
and an address that has sent `RATE_LIMIT_AUTH_PER_MINUTE` keys that do not exist is
answered `429` without a lookup until its minute is over.

### Without a browser

A script can get its own key with no console open. Sign in with a form body (the
OAuth2 password grant, so JSON answers `422`), pick the organization, issue the
key with the session token, and revoke it the same way when it is done:

```bash
SESSION=$(curl -s -X POST "$BASE/api/v1/auth/login" \
  -d "username=$EMAIL" --data-urlencode "password=$PASSWORD" | jq -r .access_token)

ORG_ID=$(curl -s "$BASE/api/v1/orgs" -H "Authorization: Bearer $SESSION" \
  | jq -r '[.items[] | select(.is_personal)][0].id')

curl -s -X POST "$BASE/api/v1/api-keys" \
  -H "Authorization: Bearer $SESSION" -H "X-Organization-Id: $ORG_ID" \
  -H "Content-Type: application/json" \
  -d '{"name": "nightly import", "scopes": ["collections:view", "collections:edit"]}'
# -> {"id": "...", "key": "aos_...", "prefix": "aos_1a2b3c4d", ...}

curl -s -X DELETE "$BASE/api/v1/api-keys/$KEY_ID" \
  -H "Authorization: Bearer $SESSION" -H "X-Organization-Id: $ORG_ID"
```

`GET /api/v1/api-keys/scopes` lists what the signed-in member may put on a key,
and the presets over it. A deployment that signs people in only through SSO has
no password to send; there a member issues the key in the console.

[`examples/public-api.sh`](examples/public-api.sh) is the whole round trip as
one script: it issues a read-only key, lists agents and runs with it, shows the
`403` for a route outside the key's permissions, runs an agent and reads the run
back when `AGENT_ID` is set, and revokes the key on exit.

```bash
BASE=http://localhost:8000 EMAIL=you@example.com PASSWORD=... bash docs/examples/public-api.sh
```

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

The response carries the run id, the output, the status, the tokens and the cost.
`environment_id` in the body picks [which environment](environments.md) answers.

**A run continues a conversation.** A call without `conversation_id` opens a new
conversation for the key's issuer and returns its id as `conversation_id`; send
it with the next call and the agent reads what was said before - the recent
turns, or the summary of older ones and what came after. A workspace shared per
conversation, the default, is that conversation's. An unknown id, or somebody
else's, answers `404`; one of the issuer's own conversations from the console or a
channel answers `400` - a key that may run agents was not given the person's chats.
So does a parked run: a key resumes or answers only a run a key started, and
one the person started answers `403`, since continuing it acts as them.
The conversation is filed in the issuer's chat list,
labelled **API** and hidden until they switch such conversations on there.

`GET /api/v1/conversations/{id}/transcript` reads one of the issuer's
conversations turn by turn, with the tools each turn called and what it cost,
for a key holding `runs:view`.

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
## Agents over A2A

An agent its organization serves over A2A answers JSON-RPC at
`POST /api/v1/a2a/{agent_id}`, with the same keys as `/run`; its agent card is at
`GET /api/v1/a2a/{agent_id}/.well-known/agent-card.json` and needs none.
`PUT /api/v1/agents/{id}/a2a` with `{"enabled": true}` turns it on, for a caller
holding `agents:publish` on that agent.

```bash
curl -X POST "$BASE/api/v1/a2a/$AGENT_ID" \
  -H "Authorization: Bearer $AGENTICOS_KEY" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "id": 1, "method": "message/send",
       "params": {"message": {"role": "user", "messageId": "m1",
                              "parts": [{"kind": "text", "text": "Review clause 7"}]}}}'
```

The answer is a `Task` whose id is the run's and whose `contextId` continues the
conversation. `tasks/get` reads one again. [Channels](channels.md#a2a) has the
rest.

Remote agents this organization delegates to are registered at
`/api/v1/external-agents`: `GET` lists them (`agents:view`); `POST` with a
`card_url`, an optional `slug` and an optional API key `secret_id` reads the card
and registers it, and `POST /{id}/refresh` reads it again; `DELETE /{id}` removes
one (`agents:edit` for all three).

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
in `$BASE`. Create the key under **Settings → API** with the permissions the
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
  general assistant. A frame's `conversation_id` continues that conversation;
  `null` starts a new one, and leaving the key out continues the one this socket
  last wrote to. Authenticate with the subprotocol `access_token.<token>`,
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

**A run that started and then failed names itself.** `POST /agents/{id}/run`
answers `502` with `MODEL_CALL_FAILED` when the model provider refused or failed
the request - every model of a fallback chain included - and `500` with
`RUN_FAILED` for any other failure once the run had begun. Both carry
`details.run_id` and `details.status`, and `details.conversation_id` when the run
wrote to one, so a retry continues that thread instead of opening another; and `message` says why
in the platform's words rather than in the provider's raw response. The run is
recorded as failed with what it spent, so `GET /api/v1/runs/{run_id}` reads it;
sending the request again starts a new run.

## Retries, idempotency and revisions

v1 has no `Idempotency-Key` header and no revision preconditions: no `ETag`, no
`If-Match`. A write is applied when it arrives, and the last one wins.

- **`GET`, `PUT` and `DELETE` are safe to repeat.** Reading twice reads twice;
  deleting what is already gone answers `404`, which a retry can treat as done.
- **`PATCH` is safe to repeat with the same body**, and only then: two clients
  patching one field overwrite each other rather than conflicting.
- **`POST` is not.** A repeated `POST /agents/{id}/run` starts a second run and
  is billed as one; a repeated create makes a second row. After a timeout or a
  dropped connection, look before you retry: `GET /api/v1/runs?agent_id=…&surface=api`
  lists the runs newest first, and a list read finds a row the first attempt did
  create.
- **`429` is the one refusal to retry**, after the `Retry-After` it carries. Every
  other `4xx` is final for that request.

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

The console reads the same document as a page: **Settings → API → API reference** lists every endpoint with its parameters, body, responses and a ready `curl` call.

The first rename under that rule is apps (#2071): what were artifacts are served at
`/api/v1/apps` and `/api/v1/public/apps`, and the old `/api/v1/artifacts` and
`/api/v1/public/artifacts` paths answer the same way, marked `deprecated`, until
the 90 days are up. Permission names (`artifacts:view`, `artifacts:edit`), the tool
names and the addresses a published page is served from keep their names.

The console's own routes carry no such promise and change with the console; a key
cannot call them. There is no client library yet.

What the public API does not do yet, so a client is not built on it:

- **Virtual Tables** are not on it; reading and writing a table with a key is
  [#1795](https://github.com/vstorm-co/agenticos/issues/1795).
- **No streaming for a key.** The chat socket takes a person's session only.
- **No idempotency keys and no revisions**, as above.

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
- A script gets its own key **without a browser** — sign in, issue, revoke — and
  `examples/public-api.sh` runs that round trip.
- **Only `429` is worth retrying**; a `POST` is not idempotent, so look before
  repeating one.
- **The public API is in `/api/v1/public/openapi.json`** and changes only
  additively within v1, with 90 days' deprecation; there is no SDK yet.
