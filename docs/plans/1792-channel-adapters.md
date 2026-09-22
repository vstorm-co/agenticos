# #1792 — Workflows: API, WebSocket, chat, webhook and schedule adapters

Design for [#1792](https://github.com/vstorm-co/agenticos/issues/1792), child of
[#56](https://github.com/vstorm-co/agenticos/issues/56). Depends on
[#1786](1786-node-contracts.md) and [#1788](1788-durable-execution.md), both
design-only so far. #1792 is an **admission layer** in front of #1788's
`WorkflowRun`/`DispatchOutbox`/`WorkflowEvent` machinery, not a second
execution path: every adapter's job ends at "one `WorkflowRun` exists,
pinned, its first outbox row inserted"; everything after is #1788's. `FileRef`
is used exactly as #1786 defines it, storage-validation gap included.

## What this issue is

Five ways an external event becomes exactly one `WorkflowRun`: an
authenticated HTTP call, an open WebSocket, the dashboard's `/chat` surface, a
signed webhook, and a cron/interval schedule. `table.record.created` is a
sixth, built by #1785 against the boundary this document draws — see [Reply
destination is frozen](#delivery-reply-and-the-frozen-destination-rule).
Every adapter does the same four things, in order: authenticate/authorize the
caller → map the channel payload onto the graph's entry node's input schema
→ admit (one `WorkflowRun`, pinned to one workflow version and one execution
principal) → deliver, through a contract specific to whether the channel can
hold a connection open.

**`core.input`'s concrete shape is not yet designed** — [shared
contracts](56-shared-contracts.md#resolved-decisions) reserves it for #1789,
deliberately not #1786. This document does not invent #1789's field list; it
designs against what #1786 fixes today, one entry node per graph whose
`input_schema` is a real Pydantic model, so every mapping step produces JSON
validated against *that schema*. When #1789 lands, mapping needs no
redesign, only real field names.

## Precedent reused rather than reinvented

A workflow's principal, outbox and event stream are #1788's, not
`agent_runs`'s — nothing below is copied wholesale, but every decision that
resembles an existing pattern is named as one:

| Problem | Existing answer |
|---|---|
| Reachability kept out of a versioned spec | `AgentExposure` (`app/db/models/agent_exposure.py`) |
| A schedule firing something on its own, attributed to a subject | `AgentTrigger`, `trigger_type=schedule` |
| A signed inbound delivery, verified and deduplicated | `AgentTrigger`'s `event` type + `trigger_events.py`/`trigger_dedupe.py` |
| A long-lived connection, re-checked later | `get_current_user_ws`, re-checked per frame (#1437) |
| A stored file served only to someone still authorized | `_chat_file_bytes.py` / `_stored_bytes.py` |

## The `WorkflowExposure` model

```python
class ExposureAdapter(enum.StrEnum):
    API = "api"; WEBSOCKET = "websocket"; CHAT = "chat"
    WEBHOOK = "webhook"; SCHEDULE = "schedule"
    # lockstep with WorkflowRun.triggered_by (#1788); #1785 adds table_created.

class WorkflowExposure(Base, TimestampMixin):
    id: UUID
    organization_id: UUID                      # FK CASCADE, indexed
    workflow_id: UUID                          # FK CASCADE, indexed
    workflow_version_id: UUID                  # FK workflow_versions.id, NOT NULL, pinned
    adapter: str                               # ExposureAdapter
    execution_principal_user_id: UUID | None   # FK users.id, SET NULL
    config: dict                               # JSONB, adapter-specific
    is_active: bool
    created_by_user_id: UUID | None
```

**`workflow_version_id` is pinned, not floating** — a deliberate departure
from `AgentExposure`, which resolves its version through an optional
`environment_id`, so publishing to the default environment moves a live
Slack bot immediately. `WorkflowRun` carries a frozen version FK instead, and
publishing must never silently change what a live webhook runs, so the
exposure pins the published version at creation; repointing is a separate,
explicit, audited write, the shape `AgentExposureService.update` already
gives rebinding.

**Cardinality differs by adapter.** `api`/`websocket`/`chat` are a
reachability toggle like `AgentExposure` — one row suffices. `webhook`/
`schedule` behave like `AgentTrigger` — many rows per workflow (one secret
per integration, one row per cadence). `config` holds a schedule's cadence
fields (`AgentTrigger`'s own shape, reused verbatim) or a webhook's vault
secret id — never a reply destination, below.

**`execution_principal_user_id` is live for `api`/`websocket`/`chat`** — the
*invoking* member, checked fresh per call — **and stored for `webhook`/
`schedule`**, where no human is present at admission: set on the exposure at
creation, `AgentTrigger.created_by_user_id`'s exact rationale, disabled next
time it is inspected once that member loses access. **Never read from the
caller's payload** — a `run_as` body field is not consulted, closing "forged
execution principal" by construction. `Perm.WORKFLOWS_RUN` joins the three
shared-contracts already named, mirroring `Perm.AGENTS_RUN`; admission is
`resolve_access(db, ctx_for_principal, workflow, Perm.WORKFLOWS_RUN,
resource_type=WORKFLOW)`.

## Per adapter

| Adapter | Caller auth | Admission uniqueness |
|---|---|---|
| API | Org-scoped API key (below) | Each accepted request is one event |
| WebSocket | `get_current_user_ws`, re-checked per frame | Per inbound "start" frame |
| `/chat` | Dashboard session auth (`CurrentUser`) | Per conversation turn |
| Webhook | HMAC-SHA256 over the raw body (`trigger_events.py`) | Durable delivery-id constraint |
| Schedule | N/A — internal clock | A claimed `next_fire_at` tick |

**API auth is assumed, not designed here.** The issue shares it with "the
public API issue." Today's `ValidAPIKey` is one deployment-wide static key
with no `AuthContext` — nothing `resolve_access` can check a principal
against. #1792 depends on the public-API effort rather than inventing a
second scheme; until it lands the API adapter cannot ship for real, the same
kind of open dependency #1788 names for #1790.

**Webhook: durable dedup, not a TTL cache.** `verify_signature`/`delivery_id`
are reused as-is; the departure from `trigger_dedupe` is deliberate. Its
claim is a Redis `SET NX` with a 15-minute TTL, fine there because "a
duplicate is the rarer event." A duplicated `WorkflowRun` is worse — it
double-runs a durable state machine with real budget and side effects, and
the AC is that duplicates never happen. So the delivery id is also recorded
**in the same transaction that inserts the `WorkflowRun` and its first
`DispatchOutbox` row** — `UniqueConstraint(workflow_exposure_id,
delivery_id)` on a `webhook_deliveries` table, whose violation *is* the
"already admitted" signal, checked before commit: #1788's outbox discipline
extended one step earlier, so the claim and the run's existence can never
disagree. Redis stays a cheap pre-filter; the constraint is the source of
truth. The route responds `202`/`{run_id}` the instant that transaction
commits, never waiting on the handler.

**Schedule reuses `AgentTrigger`'s clock, not `DispatchOutbox`'s lease.**
Structurally `run_scheduled_trigger_flow`'s heartbeat: a Prefect deployment
claims exposures whose `next_fire_at <= now()` with the usual `SKIP LOCKED`
claim, advances `next_fire_at` in the same transaction, and calls the shared
admission function every adapter calls, with a default payload from `config`
(a clock has no caller-supplied one) — an internal claimed-tick identity,
where a webhook's is an external delivery id.

**`/chat` is session-bound; WebSocket is the transport under it.** Each
authenticated turn maps through a `ChannelSession`-shaped identity (not the
embed widget's key+origin auth, which stays agent-only); progress/final
events are appended into that conversation, tailed live.

## Re-checking access at invocation *and* at resume

Pinning the principal at admission answers who a run acts as, not whether
that is still true later. #1788 already rechecks the approving member's
current authority before a workflow-owned agent run resumes; #1792 extends
that to two more points a channel can reach a run from. **A WebSocket/chat
reconnect** re-runs the `resolve_access` check `get_current_user_ws` performs
per frame, against the reconnecting identity, before replaying any event
past the cursor. **An approval decided for a webhook- or schedule-admitted
run** also checks the *exposure's* `execution_principal_user_id`, not only
the approving member #1788 already checks — a revoked exposure principal
moves the `NodeRun` to `needs_attention` instead of resuming, #1788's
"stale-authority resume is refused" shape applied to a second identity #1788
does not know about.

## Delivery, reply, and the frozen destination rule

The response goes back to the invoking channel **only if it can hold a
connection open**. API (synchronous default), WebSocket and `/chat` hold the
connection and stream `WorkflowEvent` rows as #1788 appends them — the
`(kind, payload)` vocabulary `run_stream.py` already uses for chat, backed by
the committed table; a synchronous call outliving a bounded wait degrades to
the webhook shape, returning the run id for the caller to poll. Webhook never
holds the connection — `202` plus `{run_id}` the instant admission commits;
the result reaches the caller by polling the cursor endpoint or through an
explicit outbound node in the graph, never a default "call back the source"
(a webhook's source, e.g. GitHub sending an issue payload, is often nothing a
POST can reach). Schedule has no caller: delivery is the event stream, or an
explicit outbound node.

For `api`/`websocket`/`chat`, the reply destination and identity *are* the
connection or session that made the admission call, derived from
authentication, never a payload field. Sending a result anywhere else — a
different user, another socket, an external URL — requires an explicit
outbound node (an HTTP-request or notification node, #1789/#1791 territory)
placed in the graph itself, reviewed and versioned like any other node.

**This is the boundary #1785 must respect.** `table.record.created` has no
connection to hold open — a table write is not a request — but it names a
concrete person, the record's author, making "automatically tell them" look
like an obvious convenience. **It is not one this design permits.** A
table-triggered run follows the same rule as webhook and schedule: the event
stream, or an explicit outbound node. #1785 must not add a "reply to the
author" shortcut — that would special-case exactly the rule every other
adapter here holds, for the adapter where breaking it is least visible.

**Reconnect by cursor** reuses #1788's `GET /workflow-runs/{id}/events?
after=<cursor>` and its `encode_cursor`/`decode_cursor` shape directly — a
disconnected WebSocket/`/chat` client reconnects with `after=<last-seen-seq>`
and resumes exactly where it left off, no second stream or cursor format.
Retrying delivery cannot rerun the workflow: every event was durably
appended before it was sent, the crash-safety property #1788's reconciler
already establishes.

## Attachment import and authorized output references

Import maps into `FileRef{file_id, content_type, byte_size}`. API/WebSocket/
`/chat` accept a pre-uploaded file id, reusing existing upload endpoints
(embed widget's `PublicUpload`, dashboard chat upload) rather than a new one,
and resolve/check organization and principal access before admission — the
pattern #1786 already applies to a `TableIORef` binding. Webhook payloads
naming an already-known platform file id work the same way; a payload naming
an *external* URL cannot become a real `FileRef` yet — decision 1 in shared
contracts is explicit that `FileRef` has no storage backing until #1791, so
importing an external webhook attachment is an honest gap here, the same way
#1788 names its own dependency on #1790. Schedule has no live payload.

A result's `FileRef` output is never handed back as a raw file id or storage
path; it is served through a route shaped like `_chat_file_bytes.py`/
`_stored_bytes.py` — re-checking `WORKFLOWS_RUN`/`VIEW` (or, for a webhook
caller, a scoped token minted at admission and bound to that run id), and
that the `FileRef` is one of *this run's* `ResourceRef` rows (#1788's model),
so a caller cannot fish for another run's output.

## Out of scope: hosted pages and Slack

Both deferred by #56's own scope note, and both slot into `WorkflowExposure`
as a sixth/seventh `ExposureAdapter` value with no redesign above — the
actual argument for deferring them, not a scheduling convenience. A hosted
page needs a login/session model this codebase lacks for anonymous
visitors; Slack is a `ChannelBot`-shaped integration that more naturally
reuses `AgentExposure`'s bot-binding precedent. Neither changes admission,
pinning, dedup or delivery.

## Module layout

```
app/db/models/workflow_exposure.py           # WorkflowExposure, ExposureAdapter, WebhookDelivery
app/repositories, app/schemas/workflow_exposure.py
app/services/workflow_admission/             # facade.admit(), mapping.py, webhook.py, schedule.py
app/api/routes/v1/workflow_exposures.py      # CRUD, mirrors agent_exposures.py
app/api/routes/v1/workflow_invocations.py    # invoke, websocket and webhook routes
app/worker/tasks/workflow_schedule_tasks.py  # heartbeat + fire, mirrors trigger_tasks.py
```

New tables (`workflow_exposures`, `webhook_deliveries`), org-scoped, FK to
`workflow_versions`/`workflow_exposures`. Migration stacks above whatever
#1786/#1788 land as; verify `alembic heads` at implementation time.

## Test plan against the four acceptance criteria

**AC1 — one workflow, five inputs, one contract.** A published workflow with
a `debug.echo`-shaped entry node is invoked once through each adapter with an
equivalent payload; assert every `WorkflowRun` carries the same
`workflow_version_id`, a round-tripped entry-node input, and the same
governance path (permission, budget attribution).

**AC2 — duplicate webhook delivery, one run.** Send one signed delivery
twice with the same delivery id; assert exactly one `WorkflowRun`/
`webhook_deliveries` row, and that the second attempt's constraint violation
becomes the same `202`/`run_id` response as the first.

**AC3 — one final response across approval and reconnect.** Start a run over
WebSocket, disconnect before an approval-gated node resumes, decide the
approval while disconnected, reconnect with the last cursor; assert the
reconnect replays exactly the missed events plus the terminal one, with no
second dispatch of the approved node (`NodeAttempt.attempt_no` stays 1).

**AC4 — unauthorized channel, forged principal, changed recipient rejected.**
No `WORKFLOWS_RUN` grant refuses before any run exists; a `run_as` body field
has no effect on the created run's principal; a synchronous adapter never
delivers to any identity but the one that opened the connection; a webhook
run targeting a caller-configurable address requires an explicit outbound
node, never an inferred one. A revoked-exposure-principal resume test
mirrors #1788's revoked-approver test, for the second identity #1792
introduces.

## Suggested commit order

1. `WorkflowExposure` model + migration + schemas/repository (mirroring
   `AgentExposure`/`AgentTrigger`) + `Perm.WORKFLOWS_RUN` + serialization
   tests, then `workflow_admission/mapping.py` + `facade.py`'s shared
   `admit()`, unit tested against a fake entry node before any transport
   exists.
2. API adapter (route, synchronous delivery + bounded-wait fallback) —
   simplest transport, proves admission end to end first.
3. Webhook adapter: signature verification (reused shapes) + the durable
   delivery-id constraint in the same transaction as admission (AC2).
4. Schedule adapter (`next_fire_at` claim + heartbeat, mirroring
   `trigger_tasks.py`), then WebSocket (`get_current_user_ws` reuse, live
   streaming, reconnect-by-cursor test — AC3).
5. `/chat` adapter, last because it is WebSocket plus session semantics;
   then attachment import (API/WebSocket/chat) + authorized
   output-reference route.
6. `docs/channels.md`/`docs/concepts.md` updates, then the full AC1–AC4
   suite run end to end.
