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
