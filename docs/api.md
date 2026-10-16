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

Both stream tokens as they arrive (an agent with an output guardrail streams a step
at a time, see [Guardrails](reference/capabilities.md#guardrails)) and both produce
an ordinary run, with the same books as everything else.

## Voice calls

A [voice call](voice.md) has a socket of its own, because a call is not a turn
loop: **`/api/v1/ws/voice`** for a member, and
**`/api/v1/embed/{public_key}/voice/ws`** for a visitor on a widget or a hosted
page ([admission](channels.md#the-call-socket)). Both speak the same frames,
defined in `backend/app/schemas/voice.py`.

The console socket authenticates as `/ws/agent` does: the token as a
`Sec-WebSocket-Protocol` entry `access_token.<JWT>` (or the same-origin cookie),
never in the query string, and the organization as `?organization_id=`. It
closes with `4001` without a valid session and `4003` when the caller is not a
member. The embed socket closes with `4029` past a rate limit and `4003` for any
refusal about the embed. Every heartbeat re-checks the session, so a call does
not outlive a sign-out.

**The client sends** JSON frames, and over the relay binary audio too:

| Frame | Fields | When |
|---|---|---|
| `start` | `agent_id`, `conversation_id`, `sdp_offer` (WebRTC), `resume_of` and `resume_token` (a reconnect), `context` (an embed's variables) | First, within 10 seconds |
| `approval` | `id`, `decision` (`approve` or `deny`) | Deciding an approval the call is waiting on |
| `mute` | `muted` | The relay: the microphone muted |
| `played` | `bytes` | The relay: how much of the agent's audio has been played |
| `end` | - | Hanging up |
| *binary* | 16-bit PCM at the model's input rate | The relay: the caller's audio |

**The server sends:**

| Frame | Fields | Means |
|---|---|---|
| `answer` | `sdp` | WebRTC: the provider's answer for the browser's peer connection |
| `ready` | `call_id`, `run_id`, `conversation_id`, `transport`, `input_sample_rate`, `output_sample_rate`, `cap_seconds`, `minutes_left`, `resume_token` | The call is set up. `resume_token` is sent only here, to this caller; a reconnect sends it back |
| `state` | `state`: `connecting`, `listening`, `user_speaking`, `thinking`, `agent_speaking`, `interrupted`, `tool_running`, `awaiting_approval` | Who is talking, or what the agent is doing |
| `caption` | `role`, `turn_id`, `part`, and one of `delta` (append), `text` (replace with the screened text so far) or `final` | A live caption |
| `turn_saved` | `message` | A finished turn, as the message it was saved as; it replaces the captions carrying its `turn_id` |
| `tool` | `name`, `status` (`running` or `done`) | A tool the agent is running |
| `approval_required` | `id`, `tool`, `args`, `said`, `timeout_seconds` | An approval for the person on the call: the exact arguments, and what they were heard to say |
| `approval_unavailable` | `tool`, `args` | A tool call this caller cannot approve by voice |
| `approval_settled` | `id`, `outcome` (`approved`, `denied` or `expired`) | How an approval ended |
| `notice` | `kind`, `message` (optional) | Something to say in words: a guardrail hit, a limit being reached |
| `limit` | `seconds_left` | The call's time is nearly up |
| `clear_playback` | - | The relay: drop the agent's queued audio |
| `ended` | `reason`, `message` | The call is over |
| *binary* | 16-bit PCM at the model's output rate | The relay: the agent's audio |

**A visitor on a widget or a hosted page is told less.** `ready` leaves out
`run_id` and sends `minutes_left` as `null`, and its `cap_seconds` is the call's
own limit - the organization's longest call, the agent's, or what is left of a
call being resumed - rather than one that gives away the organization's minutes.
The server still ends the call at the real limit. The tool frames follow the
embed's `show_tool_steps` and `show_tool_results` switches, as a typed reply's
do. Without tool steps no `tool` frame is sent and `tool_running` is sent as
`thinking`. Without tool results, `approval_unavailable` is sent with empty
`args`. A visitor's `turn_saved` carries only the message's `id`, `role`,
`content`, `interrupted` and `turn_id`, whatever the switches: never its run,
agent or version ids, its cost or its tool calls.

**A reconnect proves it holds the call.** A `start` with `resume_of` must also
carry the `resume_token` from that connection's `ready`. Without it, or with a
wrong one, the reconnect is refused as `resume_refused` and the call it names
is not touched. The server keeps only a hash of the token. A call already made
of 20 connections is not resumed again: its next reconnect is refused as
`resume_refused` too.

A socket that sends no `start` within 10 seconds gets `ended` with `no_start`.
A call that will not start answers with `ended` and a stable `reason`:
`voice_off`, `no_agent`, `forbidden`, `not_configured`, `bad_offer`,
`data_channel`, `resume_refused`, `minutes_exhausted`, `call_limit`,
`not_priced`, `budget`, `busy` or `line_busy`, with a `message` safe to show. A
start that fails for any other reason answers `ended` with `error`. A visitor
refused as `not_configured`, `not_priced`, `minutes_exhausted` or `budget` gets
the same reason with the message "Calls are not available right now.", because
the full message is written for the agent's operator. A call into an archived
conversation is refused as `forbidden`, as a typed message into one is refused.

A call that ran ends with `user`, `time_limit`, `budget`, `minutes`,
`disconnected`, `revoked`, `shutdown` or `error`. It ends as `minutes` when the
month's minutes set its limit, and as `time_limit` when a longest call did. A
visitor's call ends as `revoked` when its embed is paused, has its calls
switched off or is pointed at another agent. No frame ever carries a provider
credential.

Four HTTP routes go with it:

| Route | Gate | Answers |
|---|---|---|
| `GET /api/v1/agents/{agent_id}/voice?surface=web` | `agents:run` on that agent, a grant included; `404` otherwise | Whether a call would start, why not, the transport, the longest call and the minutes left. `surface=embed` asks for a widget or a hosted page |
| `GET /api/v1/providers/realtime-models` | `agents:view` | The realtime catalog the Voice section picks from |
| `GET /api/v1/voice/usage?start=…&end=…` | `runs:view` | Call seconds and calls for calls started at or after `start` and before `end`, by agent (a deleted agent's calls as one row with no id or name), and this month's seconds against the organization's monthly minutes. An `end` not after `start` is refused with `422` |
| `GET /api/v1/runs?modality=voice` | `runs:view` | Calls only (`text` for typed runs only); a call that reconnected is one row carrying `voice_chain`, every connection summed |

An approval that belongs to a live call is decided in the call:
`POST /api/v1/approvals/{id}` refuses it with `400`.

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
