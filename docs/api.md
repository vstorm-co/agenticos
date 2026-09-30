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
| **JWT** | `Authorization: Bearer <access token>` | A person, or something acting as one. Short-lived, refreshed with a refresh token |
| **API key** | `X-API-Key: <key>` | Service-to-service. No user behind it |
| **Session cookie** | set by the console | The browser only — the token is HttpOnly and never reaches JavaScript |

Keys are compared with `secrets.compare_digest`, never `==`, and a key is
stored the way [every other credential](secrets.md) is.

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

**`X-Organization-Id` travels on every request**, and it is not optional
decoration: it decides which tenant the call acts in.

A caller who belongs to three organizations is a different principal in each,
with a different role and different grants. Omit the header and the request has
no tenant to act in; send the wrong one and you get a refusal that looks exactly
like the resource not existing — deliberately, so ids stay unprobeable.

## Running an agent

```bash
curl -X POST "$BASE/api/v1/agents/$AGENT_ID/run" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-Id: $ORG_ID" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "How do I rotate a provider key?"}'
```

The response carries the run id, the output and the status. Two optional fields
in the body are worth knowing: `conversation_id` continues an existing thread,
and `environment_id` picks [which environment](environments.md) answers. An
agent with an [answer format](concepts.md#spec) answers with an object: it is in
`structured`, already validated against the agent's `output_schema`, and `output`
shows the same object as a JSON block.

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

## Running a workflow

```bash
curl -X POST "$BASE/api/v1/workflow-runs" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-Id: $ORG_ID" \
  -H "Content-Type: application/json" \
  -d '{"workflow_id": "'"$WORKFLOW_ID"'", "input": {"question": "How long do refunds take?"}, "deadline_seconds": 3600}'
```

This starts a run of the workflow's published version and answers `201` at
once; the nodes run in the background. `input` is what the graph's
[`core.input`](reference/workflow-nodes.md#core-input) trigger hands on, at most
`WORKFLOW_RUN_MAX_INPUT_BYTES` as JSON (`413` past it). Only a version that starts
from that trigger, or from none, is started here: any other answers `409
WORKFLOW_TRIGGER_MISMATCH`, because a webhook, a schedule, a chat message or a
table record starts it. `"mode": "test"` runs the current draft instead, from any
trigger, and needs `workflows:edit`.

`deadline_seconds` (up to thirty days) sets
a deadline that is checked each time a node is about to be dispatched: the
first node due after it passes fails the run with `DEADLINE_EXCEEDED`, while a
node already running, or a run parked on an approval, is not interrupted by it. The route is rate-limited per caller like the agent run route,
answering `429` with `Retry-After` past the allowance.

`GET /api/v1/workflow-runs/{id}` returns the run's status, `spent_cost`,
`error` and, once its [`core.output`](reference/workflow-nodes.md#core-output)
node has run, its `output`, and `POST /api/v1/workflow-runs/{id}/cancel` stops it. `GET
/api/v1/workflow-runs/{id}/events?after=<cursor>` returns the run's event stream
oldest first, with a `next_cursor` to pass back as `after`: it stays the same
while nothing newer exists, so polling with it tails a live run. Who may do each
of these is in [Permissions](permissions.md#workflow-runs).

`GET /api/v1/workflow-runs/{id}/nodes` lists every step the run took, loop
iterations included, each with its `scope_path`, status, tries, cost and the typed
error it last failed with, and `GET /api/v1/workflow-runs/{id}/graph` returns the
graph the run executes: its version's, or a test run's draft snapshot.

### Exporting and importing a workflow { #exporting-and-importing-a-workflow }

`GET /api/v1/workflows/{id}/export` (`workflows:view`) returns the draft as a
portable file: `name`, `description`, `tags`, `settings`, `graph` and
`unresolved`, the step and field of every resource pin it left out. It carries no
id of this deployment and no secret value. `POST /api/v1/workflows/import`
(`workflows:create`) takes that file and answers `201` with the new draft
`workflow` and its `unresolved` pins; a graph that does not parse, or names a step
this deployment does not have, is a `400` and makes nothing.

### Following a run over a WebSocket { #following-a-run-over-a-websocket }

`/api/v1/ws/workflow-runs?organization_id=<org>` authenticates like the chat's
socket, with the access token as the `access_token.<token>` subprotocol. Send
`{"type": "start", "workflow_id": ..., "input": {...}}` to start a run, or
`{"type": "attach", "run_id": ..., "after": <cursor>}` to follow one. The server
sends `{"type": "run", "run": {...}}` when it starts following and again when the
run ends, and `{"type": "event", "event": {...}, "cursor": ...}` for every event
between. A refused frame gets `{"type": "error", "code": ..., "message": ...}`,
and a revoked session closes the socket with `4001`. One socket follows one run;
a new frame replaces the run it was following. A `start` frame spends the per-minute
allowance `POST /workflow-runs` does, and past it gets `RATE_LIMIT_EXCEEDED`.

### Webhooks and schedules { #workflow-webhooks-and-schedules }

A workflow whose trigger node is a webhook or a schedule gets its exposure when
that version is published, and the publish response carries it as `exposure`. A
webhook's signing secret is in the publish's `webhook_secret` the first time it is
switched on, and nowhere else. `GET /api/v1/workflows/{id}/exposure` reads it back,
or `null` for a workflow that starts another way. `PATCH
.../exposures/{exposure_id}` with `{"is_active": false}` pauses it, and `POST
.../exposures/{exposure_id}/rotate-secret` replaces a webhook's secret and returns
the new one once. Both need `workflows:edit` and `workflows:run` on the workflow. A
webhook's `webhook_url` is where the sender delivers:

```bash
BODY='{"lead": 42}'
SIGNATURE="sha256=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$SECRET" | cut -d' ' -f2)"
curl -X POST "$WEBHOOK_URL" \
  -H "X-Signature-256: $SIGNATURE" \
  -H "X-Delivery-Id: lead-42" \
  -H "Content-Type: application/json" \
  -d "$BODY"
```

It answers `202` with `{"run_id": ..., "duplicate": false}` as soon as the run is
admitted, never waiting for the run itself. A delivery id already admitted answers
`"duplicate": true` with the first run's id. A signature that does not verify is a
`403`, a delivery with no id or with a body that is not a JSON object a `400`, and
a paused or unknown webhook a `404`.

A graph with a [Respond to webhook](reference/workflow-nodes.md#webhook-respond)
step answers with that step's status, headers and JSON body instead, and a retry
of the delivery gets the same answer. The request waits for it for up to
`WORKFLOW_WEBHOOK_RESPONSE_TIMEOUT_SECONDS`, then answers `202` as above; a run
that fails, is cancelled or runs out of budget before answering is a `500`
`WORKFLOW_WEBHOOK_UNANSWERED` naming the run.

Before publishing, `POST /api/v1/workflows/{id}/webhook-test` (`workflows:edit`)
opens a test URL for the draft, returned as `url` with the `test_token` in it and open
for one call for two minutes. The call needs no signature, is answered
`{"captured": true}` and starts no run. `GET .../webhook-test/{token}` reads back
`state` (`listening`, `caught` or `expired`) and the `delivery` it caught.

## Working with tables { #working-with-tables }

A record's `values` are keyed by column id; `GET /api/v1/tables/{id}` lists the
columns. Every write takes an `Idempotency-Key`: a retry with the same key and body
answers with the first write's result and `Idempotent-Replayed: true` instead of
writing again, and the same key with a different body is `422`.

```bash
curl -X POST "$BASE/api/v1/tables/$TABLE_ID/records" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-Id: $ORG_ID" \
  -H "Idempotency-Key: lead-ada-2026-09-29" \
  -H "Content-Type: application/json" \
  -d '{"external_id": "ada@example.com", "values": {"'"$EMAIL_COLUMN"'": "ada@example.com"}}'
```

`PATCH .../records/{record_id}` changes some cells and needs the
`expected_revision` you last read; a stale one is `409 REVISION_CONFLICT`. `PUT
.../records/by-external-id/{external_id}` creates the record or updates it, with
`expected_revision` required once it exists. `POST .../records/query` filters,
searches and sorts one page at a time, and `POST .../records/count` says how many
records the same filters and search match, up to 100,000.

A workflow whose trigger node is **New table record** runs for every record added
to its table once it is published. `GET .../triggers` lists the workflows that
start from a table, `PATCH .../triggers/{trigger_id}` with `{"is_active": false}`
pauses one, and `GET .../triggers/{trigger_id}/admissions` lists what it decided
about each record. See [Triggers](virtual-tables.md#triggers).

## The ML services

Four of the platform's services answer on their own, with no conversation and no
agent behind them: document analysis, OCR, speech to text and personal data
detection. They are gated on `ml:invoke` rather than `agents:run`, and
[The ML services](ml-services.md) is their reference.

```bash
curl -X POST "$BASE/api/v1/ml/privacy/pii" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-Id: $ORG_ID" \
  -H "Content-Type: application/json" \
  -d '{"text": "write to ada@example.com"}'
```

## Streaming

Two WebSocket endpoints, for two audiences.

- **`/api/v1/ws/agent`** — the authenticated one the console uses. A frame
  carrying `agent_id` runs that published agent; a frame without one gets the
  general assistant.
- **`/api/v1/embed/{public_key}/ws`** — the public one behind an
  [embed](channels.md), for a visitor who has no account.

Both stream tokens as they arrive and both produce an ordinary run, with the
same books as everything else.

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

**There is no published compatibility promise yet, and no client library.** The
API has been public since the first commit and the versioning contract is
[roadmap](https://github.com/vstorm-co/agenticos/blob/main/docs/ROADMAP.md) work
(R10).

In practice the shapes have been stable and the `/api/v1` prefix means a
breaking change would land beside the current one rather than on top of it — but
until that is written down, treat it as what it is: an API you should pin your
integration's tests against.

The one format that *does* carry a promise is the
[agent spec](reference/spec.md), which is versioned and only moves forward.

## Recap

- **`/docs`** on the deployment is the generated reference; it is off in
  production by design.
- Three ways in: **JWT, `X-API-Key`, or the console's cookie**.
- **`X-Organization-Id` decides the tenant** on every request, and the wrong one
  looks like a missing resource.
- Running an agent over HTTP is the **same runner** — budget, approval and audit
  all apply.
- **No compatibility promise or SDK yet** (R10); the agent spec is the one
  versioned format.
