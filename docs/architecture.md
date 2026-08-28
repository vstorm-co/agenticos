# Architecture Guide

This project follows a **Repository + Service** layered architecture.
Every feature — users, conversations, files, RAG documents, sync sources — uses
the same pattern: **Models → Schemas → Repositories → Services → Endpoints**.

## Request Flow

```
HTTP Request → API Route → Service → Repository → Database
                  ↓
              Response ← Service ← Repository ←
```

Routes never contain direct database calls. All data access goes through
services, which in turn delegate to repositories.

**That is a test rather than a convention.**
`backend/tests/test_route_layering.py` fails if any module under
`app/api/routes/` imports from `app.repositories`, and fails just as loudly if its
allowlist keeps an exemption that no longer applies. The rule had drifted in five
modules before anything read for it — none of them a leak, because each handler
passed the scope it happened to know. That is the cost: a scope a route owns is a
scope no service test can see, and the next reader of the entity has to know to pass
the same thing. The single exemption is a `Literal` of sort orders, imported as a
type rather than as data access.

## Directory Structure (`backend/app/`)

| Directory / File | Purpose |
|-----------|---------|
| `api/routes/v1/` | HTTP endpoints, request validation, auth |
| `api/deps.py` | Dependency injection (db session, current user) |
| **`services/`** | **Business logic, orchestration** |
| ↳ `user.py` | User CRUD, profile updates |
| ↳ `conversation.py` | Conversation & message management |
| ↳ `message_rating.py` | Message rating CRUD, statistics, export |
| ↳ `file_upload.py` | Chat file upload handling |
| ↳ `file_storage.py` | File storage abstraction (local / S3) |
| ↳ `rag_document.py` | RAG document lifecycle |
| ↳ `rag_sync.py` | Remote-source sync orchestration |
| ↳ `sync_source.py` | Sync-source CRUD, and one source's run history |
| ↳ `audit.py` | Reading the audit trail of the caller's own organization |
| **`repositories/`** | **Data access layer, database queries** |
| ↳ `user.py` | User queries |
| ↳ `conversation.py` | Conversation queries |
| ↳ `chat_file.py` | Chat file queries |
| ↳ `message_rating.py` | Message rating queries |
| ↳ `rag_document.py` | RAG document queries |
| ↳ `sync_log.py` | Sync log queries |
| ↳ `sync_source.py` | Sync source queries |
| **`schemas/`** | **Pydantic request/response models** |
| ↳ `user.py` | User schemas |
| ↳ `conversation.py` | Conversation & message schemas |
| ↳ `file.py` | File upload schemas |
| ↳ `message_rating.py` | Message rating schemas |
| ↳ `rag.py` | RAG query/response schemas |
| ↳ `sync_source.py` | Sync source schemas |
| **`db/models/`** | **SQLAlchemy 2.0 models** |
| ↳ `user.py` | User model |
| ↳ `conversation.py` | Conversation & message models |
| ↳ `chat_file.py` | Chat file model |
| ↳ `message_rating.py` | Message rating model |
| ↳ `webhook.py` | Webhook model |
| ↳ `rag_document.py` | RAG document model |
| ↳ `sync_log.py` | Sync log model |
| ↳ `sync_source.py` | Sync source model |
| `core/config.py` | Settings via pydantic-settings |
| `core/security.py` | JWT / API key utilities |
| `agents/` | AI agents and tools |
| `rag/` | RAG module (embeddings, vector store, retrieval) |
| `rag/connectors/` | Sync connectors (Google Drive, S3) |
| `commands/` | Django-style CLI commands |

## Layer Responsibilities

### API Routes (`api/routes/v1/`)
- HTTP request/response handling
- Input validation via Pydantic schemas
- Authentication and authorization checks
- **Never** contains direct DB calls — always delegates to a service
- **Never** parses untrusted input in the route expression. A `ValidationError`
  raised there is a `ValueError` but not a `RequestValidationError`, so no
  handler maps it and the caller is answered 500 with `details: null` — which is
  how every mistake in a hand-edited spec YAML was reported as a crash (#873).
  Parsing is the owning service's job, and so is the refusal: `import_spec` on
  `AgentRegistryService` answers a broken document with a 400 that names the
  field, and never quotes what was submitted back at the caller.

### Services (`services/`)
- Business logic and validation
- Orchestrates one or more repository calls
- Raises domain exceptions (`NotFoundError`, `AlreadyExistsError`, etc.)
- Manages transaction boundaries

### Repositories (`repositories/`)
- Database operations only
- No business logic
- Uses `db.flush()` not `commit()` — the request's session owns the transaction,
  and [commits it before the response is sent](#the-requests-transaction)
- Returns domain models

### Schemas (`schemas/`)
- Separate `Create`, `Update`, and `Response` models per entity
- `Response` schemas use `model_config = ConfigDict(from_attributes=True)` for ORM conversion

### Models (`db/models/`)
- SQLAlchemy 2.0 model definitions
- Relationships, indexes, and column defaults live here

### RAG Connectors (`rag/connectors/`)
- Pluggable sync adapters that implement `BaseSyncConnector`
- Each connector provides `list_files()` and `download_file()`
- Registered in `CONNECTOR_REGISTRY` for discovery at runtime

## The request's transaction

One request, one session, one transaction, committed in one place — and the place
matters as much as the fact.

A route asks for `DBSession` (`app/api/deps.py`), which resolves `get_db_session`
(`app/db/session.py`). Everything below the route shares that one session:
services take it in their constructor, repositories take it as their first
argument, and neither ever calls `commit()` — with one deliberate exception, the
agent run path, described [below](#the-run-paths-two-commits). `flush()` sends
the statements so the row has an id and the constraints have been checked; the
commit happens once, on the way out.

**On the way out means before the response is written.** The alias declares
`Depends(get_db_session, scope="function")`, which registers the session's exit
code on the exit stack FastAPI unwinds between the path operation returning and
`await response(scope, receive, send)`. So the order for a request is:

1. the route returns, and `response_model` serializes what it returned;
2. the transaction commits — or, if anything raised, rolls back;
3. background work the request deferred is started (below);
4. the response is written to the socket;
5. the session is closed.

That ordering is the whole contract, and it is what lets a client act on its own
answer: **a 2xx means the write is readable, not merely accepted.** FastAPI's
default for a dependency with `yield` is `scope="request"`, which puts steps 2
and 4 the other way round — and did here until [#353][353], where an acceptance
answered 204 while the membership row it created stayed invisible to the very
next request for 21.7ms, and an invitation token was spent 34ms before the
transaction that minted it committed.

Three consequences worth knowing before writing a route:

- **A commit that fails is a 500, not a log line.** The response has not been
  written yet, so a deferred constraint or a lost connection reaches the client
  as an error rather than being discovered behind an already-sent 2xx. Step 3
  does not run either: work waiting on a transaction that did not happen is
  dropped, with a warning naming it.
- **Anything that swallows a database error must reset the session.** A statement
  that raised leaves its transaction aborted, and the commit in step 2 raises
  too. The health probes (`app/services/health.py`) are the case in the codebase:
  they refuse to propagate, on purpose, so they roll back before returning.
- **A body produced while the response is being sent needs a different session.**
  A `StreamingResponse` over a generator is iterated during step 3, by which time
  the session is closed. Those endpoints take `StreamingDBSession`, which keeps
  FastAPI's default scope and is therefore read-only: its transaction resolves
  after the client has been answered. Exactly one endpoint uses it — the ratings
  CSV export — and `tests/api/test_db_session_scope.py` refuses a second without
  a decision being made about it.

Work that outlives the request does not use this session at all. WebSocket
handlers and CLI commands open `get_db_context()`, and worker tasks
`get_worker_db_context()`; all three go through the same `_managed_session`, so
they commit on a clean exit of their own `async with` and start their deferred
work in the same place — which has nothing to do with a response.

### The run path's two commits

One path deliberately commits earlier than "on the way out": an agent run. The
runner commits once **before the model is called** and once more in the
terminal `finally` (`AgentRunnerService._run`, and `ChatAgentRunner.run` for
the streaming chat). A model call takes seconds to minutes, and a transaction
left open across it holds a pooled connection `idle in transaction` for the
duration — fifteen concurrent runs used to be the entire pool ([#12][12]).
Committing first also makes the run row readable from every other session for
the whole life of the run, and makes a resumed run's exit from the approval
queue durable before the approved call is replayed, so a crash mid-replay
cannot hand the same approval out twice ([#3][3]). The terminal commit is the
other half: the session context only commits on a clean exit, which a failed,
budget-stopped or cancelled run is not, and a run missing from history is a
run nobody is accountable for. Both boundaries are proved against a real
database in `tests/integration/test_run_commit_boundary.py`.

Visibility cuts both ways: anything that used to reason "an executing run's
row cannot be seen" now reasons about a row that *is* seen. The agent-triggers
scheduler is the one place that did. Its no-overlap guard blocks on every
non-terminal run in the trigger's conversation — which now includes a
concurrent `run_now` or event fire's live run, protection the old
invisibility could not offer — while a worker that dies mid-run leaves a
`running` row nothing in-process will ever finish. What bounds that row is
the hourly stale-run sweep, which ends it `failed` past
`STALE_RUN_REAPED_AFTER_HOURS`; the scheduled fire's own liveness signal
stays its renewed lease (`app/repositories/agent_trigger.py::claim_due`).
[Governance](governance.md#a-run-whose-process-died) has what the sweep
settles and deliberately leaves alone.

### Dispatching background work from a request

**Work that will read a row this request wrote is handed over with
`spawn_after_commit`, never `spawn`** (both in `app/core/background.py`):

```python
from app.core.background import spawn_after_commit

spawn_after_commit(self.db, ingest_document_flow(rag_document_id=str(doc.id)), name=...)
```

`spawn` creates the task immediately, and the loop starts it at the next
suspension point — which is step 1 or 2 above, before the commit. The flow opens
a session of its own, correctly, so under `READ COMMITTED` it cannot see a row
this request has not committed: it looks for the document it was given the id
of, finds nothing, and stops. That is [#417][417], and its visible shape is an
upload answered `{"status": "processing"}` that stays that way forever.

`spawn_after_commit` queues the coroutine on the session instead. Nothing starts
it until step 3, two statements after `commit()` returns, so a flow dispatched
this way reads a row the database has already agreed to. It is how a document
upload, a sync somebody started, a channel connection's stream and a trigger's
manual "run now" are all handed over. The ordering is proved against a real
database in `tests/integration/test_flow_starts_after_commit.py`.

At the other end of the process's life, the application lifespan closes the loop:
after intake stops and serving has drained, it `await`s `background.drain()` for
whatever `spawn` handed off and is still in flight, **before** disposing the
vector store, Redis and the session those tasks read. Without it a shutdown
mid-ingestion cancelled the flow and left the document in `processing` — the same
stuck row as [#417][417], reached from the other end.

The trigger's manual fire is there for a second reason worth naming, because it
is the other half of why a request hands work over at all: `POST
/agents/{id}/triggers/{id}/run` used to *await* the run it started, so an agent
slower than a proxy's read timeout answered 504 while the run carried on and
committed — a failure reported for something that was working, and an invitation
to press the button again and fire the schedule twice ([#658][658]). The route
answers `202` and the fire starts after the commit.

Two things follow from where the queue lives:

- **It belongs to the session, not to the request.** A service dispatching a
  flow does not need to know whether it was called from a route, a WebSocket
  handler, the CLI or a worker — which is why this is not FastAPI's
  `BackgroundTasks`, whose guarantee is about the response and which those other
  three callers do not have.
- **A rolled-back transaction dispatches nothing.** Step 3 is skipped and the
  queued coroutines are closed, because running work whose row was thrown away
  only moves the failure somewhere less explicable.

`spawn` remains right for work that owns everything it needs — the notification
emails in `app/services/notifications.py` carry their own context and touch no
row. Neither is a job queue: anything that must survive a restart is a Prefect
deployment.

[3]: https://github.com/vstorm-co/agenticos/issues/3
[12]: https://github.com/vstorm-co/agenticos/issues/12
[353]: https://github.com/vstorm-co/agenticos/issues/353
[417]: https://github.com/vstorm-co/agenticos/issues/417
[658]: https://github.com/vstorm-co/agenticos/issues/658

## Agent runs: a capability never fetches

The layering above has one more rule inside an agent run, and it is the reason the
runner is as large as it is. **A capability does not touch the database.** Anything
it needs from one — the collection names its spec binds, the skills it may load, the
workspace it writes to, the delegates it may call — is resolved by the service
*before* the run starts and handed over as `resources`, a dict the capability may
read and cannot add to. What the model asks is *what* to search; it never learns
*where*.

Two entries in that dict are seams to other subsystems rather than plain data:

| Resource | Left by the runner | Read by |
|---|---|---|
| `WORKSPACE_BACKEND_RESOURCE` | the opened sandbox session | the `sandbox` capability |
| `SUBAGENT_RUNTIME_RESOURCE` | the resolved delegation tree | the `subagents` capability |

Delegation is the sharpest case for the rule. A delegate is a row; so are its pinned
version, its collections, its skills and its secrets, and every one of them has to
pass `resolve_access` before it is read. So the runner walks the whole tree — the
nesting, the depth bound, the refusal of a delegate already running above it in the
same run — while it still holds a session and an auth context, and leaves behind
closures that build an already-resolved agent plus a recorder that writes one row.
What happens at run time is CPU work and Pydantic AI.

It cannot be the other way round: the request's `AsyncSession` is shared by
everything in the run and is not concurrency-safe, so a tree walked at run time
would be a query from inside a tool call — and a fan-out would be several of them at
once, which corrupts the session the rest of the request is using rather than merely
being slow.

The absence of a resource is never an error. A preview, a unit test or an agent
whose delegates were all removed resolves nothing, and the capability then offers no
delegates rather than raising — exactly as the workspace capability falls back to an
in-memory backend.

### Schema

`0007_delegated_runs` adds two columns to `agent_runs`. `parent_run_id` is a
self-referential foreign key saying which run delegated this one, and it is what
keeps the organization's monthly total honest — see
[Governance](governance.md#what-a-delegated-run-is-recorded-as). It is
`ON DELETE SET NULL` for the same arithmetic: deleting the parent removes the row
that contained this cost, so a delegation row that becomes top-level is one that
*should* start counting, while cascading would delete the record of money that was
spent. `subagent_task_id` is the delegation library's own task id, which is what
joins the row to the handle the parent's model saw in its transcript — and because
a foreign key can only null its own column, that handle outlives the delete and is
withheld by `AgentRunRead` rather than nulled by a trigger on the hottest insert
table in the schema. The index on `parent_run_id` serves
`list_runs(parent_run_id=...)`, which is what `GET /runs?parent_run_id=` asks; see
[Governance](governance.md#what-run-history-shows) for why run history never lists
the two kinds of row together.

## Deleting a member or a tenant

A few foreign keys would, on delete, drive precisely the write a `CHECK`
constraint forbids — so the cascade the schema declares and the invariant it also
declares disagree, and the delete raises inside the database as a 500 rather than
doing anything. Three pairs are reconciled in the service before the row goes,
inside the request's own transaction:

- **A leaver's private secret.** `organization_secrets.owner_user_id` is
  `SET NULL`, but `ck_secret_private_needs_owner` forbids an ownerless private
  secret. `UserService.delete` promotes the leaver's private secrets to org
  visibility first, so the null the cascade writes is legal and the key stays
  reachable by the organization rather than stranded.
- **A creator's organizations.** `organizations.created_by_user_id` is
  `RESTRICT`, and every signup creates a personal org, so a bare `DELETE users`
  never worked for a real account. The personal org is removed with its owner; a
  shared one is handed to another owner, or the delete is refused when there is
  none to hand it to.
- **An org-scoped collection.** `knowledge_bases.organization_id` is `SET NULL`,
  but `ck_knowledge_bases_org_scope_has_org` forbids an org-scoped row with no
  org. `OrganizationService.delete` removes org-scoped collections explicitly —
  vector table and all — before the org row goes; a personal collection that
  merely carries the org's id is left to the `SET NULL`, which its scope permits.
  Because dropping the vector table needs the request-scoped store, the delete
  route wires it in through a dedicated dependency; every other org route uses the
  plain service and builds no store it would never touch.

## What a run handed its model, and why it is a table

`run_manifests` holds one row per run: the instructions as composed and sent,
every tool definition as the provider was handed it, the settings, one entry per
model request, and the last request's message list. It is written by
`AgentRunnerService.finish` on every path out of a run, and read by
`GET /runs/{id}/manifest` — see
[Concepts](concepts.md#a-run-and-what-it-handed-the-model) for what is recorded
and why it cannot be reconstructed from the spec.

Three layering decisions are worth writing down, because each one is a place the
obvious alternative is wrong.

**A table, not a column on `agent_runs`.** That table is the most-listed in the
product — run history, the spend tab, the dashboard figures, the CSV export — and
a JSONB document holding every tool's JSON schema would be read by all of them to
answer a question none of them asks. One row per run, `ON DELETE CASCADE` from
both the run and the organization, read only by the detail view.

**The recording happens in `app/agents/manifest.py`, not in the service.** The
model the agent is built with is wrapped (`RecordingModel`, a `WrapperModel` —
the same shape `MeteredModel` uses to book a sub-agent's spend), so what is
written down is `ModelRequestParameters` as the provider received it: after every
`prepare` hook, after tool search has hidden what it hides, after the output tool
has been added. The service persists what the wrapper collected and decides
nothing about its contents.

**An attachment on the transcript is read through the run, not through its
uploader.** `GET /files/{id}` is scoped to `ChatFile.user_id`, which is the right
scope for the chat composer and the wrong one for a run review: reading a run is
the organization's right rather than its starter's, so the attachment cards on a
colleague's transcript rendered and every preview answered 404.
`GET /runs/{run_id}/files/{file_id}` authorizes as the transcript does -
organization, then `runs:view` - and then admits the file only where its
`message_id` names a turn of the run's own conversation, which is the reach the
transcript already grants and no wider. Both routes serve the bytes through
`_chat_file_bytes.py`, so what a browser may *display* does not depend on which
one authorized the read.

**The write is guarded *and* nested.** It is reached from a `finally` block, so
an exception raised while recording a failed run would replace the failure with
itself. Swallowing it is not enough on its own: a failed flush leaves the session
unusable, so the run's own terminal write would be lost to a record nobody asked
for. It runs inside `begin_nested()` for the same reason
`TranscriptService._attach` does — a SAVEPOINT is what makes "this write may fail
harmlessly" true rather than aspirational.

## A refusal that names a field

Every refusal leaves in one envelope, `{"error": {"code", "message", "details"}}`,
and a refusal about a *field* names it in one shape:

```json
{"details": {"fields": [{"field": "spec.name", "message": "String should have at most 128 characters"}]}}
```

`fieldProblems` in `frontend/src/lib/api-error.ts` reads that and nothing else,
which is what lets a form mark the offending input rather than showing a sentence
the reader has to re-scan the page for. `app/core/field_errors.py` is the only
place it is built, and it has three entry points. Two of them read Pydantic, and
**which caller you are decides what the first element of `loc` means**:

| | For | `loc` starts with |
|---|---|---|
| `request_field_problems` | `validation_exception_handler`, every `RequestValidationError` | where the value came from (`body`, `query`, …), which is dropped |
| `field_problems(…, root=…)` | a service validating a document a route's schema cannot — a per-upload ingestion override, a hand-edited spec YAML, a capability's config blob | a field of that document, reported below `root` |
| `refused_field(field, message, **context)` | a rule a service states in prose rather than in a model — an endpoint carrying a password, a Mattermost bot losing its server, a YAML document that never parsed | — it answers with the `BadRequestError` for the caller to raise |

`refused_field` names the sentence once, because the envelope's `message` and the
field's are the same sentence; a raiser needing another status builds the same
`details` with `field_details`. Eighteen call sites answered
`details={"field": "<name>"}` instead, singular, with the sentence on the
envelope, and no form has ever read it — the same defect in a third shape
([#891](https://github.com/vstorm-co/agenticos/issues/891)). A fourth spelling
was `details={"<field>": <value>}`, where the key was the field name and the
value was what the caller had just sent: `model_profile.py` answered a refused
model id with the id, in a body and in the log line beside it
([#898](https://github.com/vstorm-co/agenticos/issues/898)).

Deciding by the string instead would misread a spec whose forbidden top-level
key is literally called `body`, which is one shape standing in for two — the
mistake the module exists to end.

Two more properties are worth knowing before adding a call site. It reads `loc`
and `msg` only, so the rejected value cannot come back beside the field it broke,
which is why those call sites hand it `exc.errors()` unfiltered. And `root` is
what the caller's form calls the whole document, so every path is relative to it:
that gives a `model_validator(mode="after")` somewhere to land — it reports
`loc: ()`, because the rule it broke is about two fields at once — and it makes
the entry points agree, an override refused at upload naming exactly what the 422
names when the same pair arrives as a collection's own settings.

Handing Pydantic's own `exc.errors()` through instead was
[#882](https://github.com/vstorm-co/agenticos/issues/882) — a second shape,
carrying `input`, `ctx` and `url`, that nothing on the frontend read.

**An aggregated refusal carries both halves.** `validate_spec` reports every
problem in a spec at once and most of them are broken references with no input to
mark, so it answers `details.problems` (a line each, which the Builder lists) and
`details.fields` for the subset that names one. A capability's configuration is
the one part of a spec rendered as a generated form, so its refusals name the
input — `capabilities.knowledge.config.default_top_k`, and
`specialists.researcher.` in front of that for a capability configured inside a
delegate, because the Builder renders one form per specialist. Keeping only the
sentence was the other half of #882: saving a draft does not validate a config
schema at all, so publish validation is the only place a mistyped setting is ever
refused.

**Two kinds of refusal deliberately name no field**, and the line between them
and the rest is what stops the one shape from meaning two things again:

- **A refusal about a value no caller sent.** A remote file's name is chosen by
  whoever can drop a file in the synced folder, and both checks in
  `app/services/rag/remote_names.py` run inside a background sync, where the
  reader is a log rather than a form. Same for a Google Drive source read back
  without its credential: the row is stored, and `CONFIG_SCHEMA` is what refuses
  it at the route.
- **A conflict.** `AlreadyExistsError` reports a fact about a row that already
  exists, not about the shape of what was sent — and which of a form's own
  inputs produced the taken value is a thing only the form knows, since an
  agent's handle is derived from a name nobody typed as a handle. That is
  claimed by `submitFailure`'s `identifiedBy` on the client, so a 409 carries the
  taken value and no field.

## Key Files

- Entry point: `app/main.py`
- Configuration: `app/core/config.py`
- Dependencies: `app/api/deps.py`
- Auth utilities: `app/core/security.py`
- Exception handlers: `app/api/exception_handlers.py`
- Field-level refusals: `app/core/field_errors.py`

## Authentication & Authorization

### Authentication Methods

The project supports two authentication methods, both always available:

1. **JWT (JSON Web Tokens)** -- Used by the frontend and API clients.
   - Login via `POST /api/v1/auth/login` returns `access_token` + `refresh_token`.
   - Access tokens expire after `ACCESS_TOKEN_EXPIRE_MINUTES` (default 30 min).
   - Refresh tokens expire after `REFRESH_TOKEN_EXPIRE_MINUTES` (default 7 days).
   - The frontend stores tokens as HTTP-only cookies.
   - WebSocket auth passes the JWT as a query parameter (`?token=<jwt>`) or cookie.

2. **API Key** -- Used for server-to-server and programmatic access.
   - Passed via the `X-API-Key` header (configurable via `API_KEY_HEADER`).
   - A single shared key set via the `API_KEY` environment variable.
   - Uses constant-time comparison (`secrets.compare_digest`) to prevent timing attacks.

### Where a fresh session lands

Three doors establish a session by three routes - the password form, the OAuth
callback, and a magic link - and exactly one of them decides where the visitor
ends up: `postSignInDestination` in `frontend/src/lib/auth-landing.ts`, which
honours a deep link only when it is a same-origin path and answers the dashboard
otherwise. Three answers in three places is drift, and the drift has been real
twice: on the roles axis, where the landing forked by role, and on the provider
axis, where the OAuth round trip lost `?returnTo=`.

What differs per door is only how the path *travels*:

| Door | How the path reaches the landing |
|---|---|
| Password form | it never left the tab - read straight off `?returnTo=` |
| OAuth callback | `sessionStorage`, which is allowed because the round trip starts and ends in the same tab on this origin |
| Magic link | a signed claim in the token, because the link is followed from an email - another tab, often another application, where `sessionStorage` is empty by construction |

The magic link's path is refused at the **request** rather than filtered at the
landing: `MagicLinkRequest.return_to` accepts a path on this deployment and
nothing with a scheme, a second leading slash, a backslash or a control
character, so a token that could be made to hold an arbitrary string never
exists. The landing judges it again anyway - a check that runs once, on the
server, on a value that then travels through an email, is a check the client
cannot rely on having happened.

`POST /auth/magic-link/verify` therefore answers with `MagicLinkToken` - the
token pair plus `return_to`, unapplied. Its own schema rather than a nullable
field on `Token`, because the other three token responses have no return path to
carry and a field that is always null on most of them is one a client learns to
ignore.

### Authorization

There is no role column on the user and no role-based route dependency. What a
member may do inside an organization is a permission from the catalog in
`app/core/permissions.py`, and which rows they may touch is resolved per row -
see [Permissions](permissions.md) for the whole model.

Two dependencies, and only two:

| Alias | Means |
|---|---|
| `CurrentUser` | any authenticated user |
| `CurrentAppAdmin` | the deployment's superadmin (`users.is_app_admin`), for `/admin/*` and the bulk `/rag` routes |

Everything else goes through one of:

```python
# A permission, on a collection route.
@router.post("/agents", dependencies=[Depends(require(Perm.AGENTS_EDIT))])
async def create_agent(...): ...

# A permission on one row, resolved in the service.
if not await resolve_access(db, ctx, agent, Perm.AGENTS_EDIT, resource_type=AGENT):
    raise AuthorizationError(...)

# A permission decided by a parameter, resolved in the service: scope=org
# demands runs:view, scope=own only a signed-in caller. See Permissions,
# "Where the gates go".
return await service.usage(ctx, scope=scope, ...)
```

!!! note "`require(...)` does not belong on a per-resource route"

    A role gate cannot see the grants on a row, so it would refuse a Viewer
    holding an explicit `edit` grant before `resolve_access` ever widened their
    access. The same shape applies when a *parameter* decides the question -
    `GET /stats/usage?scope=own` must be reachable by a plain member, so its
    gate lives in the service. `tests/api/test_platform_routes.py` enforces
    all of it.

!!! note "A personal preference carries no gate at all"

    A row scoped to `(user_id, organization_id)` that only its owner reads and
    writes is not org data, so no permission gates it and there is no route that
    reaches somebody else's. `GET`/`PUT`/`DELETE /me/dashboard-layout` (the
    saved dashboard arrangement) and its `/presets` shelf underneath (the named
    arrangements a person switches between) are the pattern: `CurrentUser` +
    `ActiveOrg`, every query filtered on **both** ids. The composite key is the
    whole tenant boundary — a layout or preset saved in one organization is
    invisible in another *even to its owner*, which a per-user check alone would
    wave through, so `tests/integration/test_dashboard_layout.py` and
    `tests/integration/test_dashboard_preset.py` cover exactly that. There is no
    *apply-a-preset* route: applying one is the client's `PUT` of the preset's
    entries as the active arrangement, so the dashboard keeps one write path and
    one validation for what it renders.

    A placement may also carry `options` — the card's own window (`period`),
    presentation (`style`), and narrowing (`agent_id`, `user_id`). **A stored
    option is a request, never an authorisation**: it reaches `GET /stats/usage`
    as a query parameter and is refused there if the caller may not read what it
    asks for, the same as if they had typed the URL. Narrowing to a colleague is
    reading somebody else's rows, so it is `scope=org` and behind `runs:view`;
    `scope=own` with a `user_id` is a 422 rather than a silent reinterpretation.
    On write, the style and the window are validated against the closed sets the
    frontend registry declares (`tests/test_dashboard_registry.py` keeps the two
    mirrors equal); on read, options come back verbatim, because an agent that
    has since been deleted must not take a whole arrangement down with it.

`UserRole`, `User.has_role()`, `RoleChecker`, `CurrentAdmin` and
`CurrentSuperuser` were the template's model and are gone, along with the
`users.role` column, which went with the squash into `0001_baseline`. They were a third answer to a question
that already had two.

### IDOR Protection

Two predicates, and they are not interchangeable. **The organization is what
bounds a read; the user is what narrows it further.**

- Conversation endpoints pass `organization_id=active_org.id`. Without it a
  conversation is looked up by primary key alone, and any signed-in caller who
  knows a UUID reads — or appends to — a conversation in another tenant.
- They also pass `user_id=current_user.id`, which restricts a row to its owner
  or somebody it was shared with. The tenant check alone is not enough: without
  this, every member of an organization can read and append to every other
  member's conversation.
- **A share carries the write only at `edit`.** Reading and writing are two
  questions — `_may_read` and `_may_write` — and a share used to answer both
  whatever level it held, so the two levels the sharing dialog offers meant the
  same thing: a conversation shared to *view* could be renamed, archived,
  deleted, or given a `role: "assistant"` turn that everybody reads in `/chat`
  and the model is handed back as its own words. The level is stated to whoever
  grants it, so it is the level that is enforced (#931).
- On `list_messages` that one argument does two jobs — it authorizes, *and* it
  enriches each message with the caller's own rating. That overload is why its
  authorizing half went missing for so long: the route passed it, the argument
  was plainly there in review, and it was doing the other job.
- File downloads verify `chat_file.user_id == current_user.id`, and attaching a
  file to a message carries the same owner in the `WHERE`: a turn naming
  another user's file id — or a file already on a message — is refused, never
  silently applied.

`ConversationService` makes the distinction impossible to omit: `organization_id`
is a **required** `UUID` keyword on every read and write of a conversation. It
used to default to `None`, `None` meant unscoped, and an omission is
indistinguishable from an intention — two routes serving ordinary members simply
left it out, and any signed-in user could read and append to any conversation in
the deployment.

### A favourite belongs to the reader, not to the thread

`conversation_favourites` is a row per `(user_id, conversation_id)` and not a
boolean on `conversations`, because a conversation can be shared and a channel
thread has participants rather than an owner: a column would let one person's
star decide where the thread sits for everybody who can see it.

Four consequences worth knowing:

- **`POST`/`DELETE /conversations/{id}/favourite` are authorized as a *read*.**
  A star says where a thread sits in the starrer's own sidebar and changes
  nothing about the thread, so somebody a conversation was shared with may star
  it exactly as its owner may. `for_write` there would refuse the reader the
  feature exists for. Both routes carry `Auth` for the same reason every other
  read of one does: without a context `_may_read_trigger_log` answers false, and
  a trigger's run-log the caller may open through `runs:view` would be one they
  could not star (#1254).
- **`is_favourite` is the caller's, and it is stamped in `get_conversation`** —
  the one read every reader-scoped one goes through, rather than at each route.
  It reached two responses out of eight while each route had to remember, so a
  `GET` or a PATCH told somebody who had starred a thread that they had not
  (#1254). A read with no reader — the admin listing, the run path resolving a
  thread — asks for nobody's stars and pays no query to say so, and a read that
  only *authorizes* turns it off explicitly with `include_favourite=False`. Those
  are the reads whose result is discarded or is not a conversation:
  `GET /conversations/{id}/messages`, which resolves the thread twice through
  `list_messages` and `conversation_cost`; the three workspace routes; every turn
  of an existing chat, through `agent._resolve_in_org`; and the writes —
  `add_message`, `delete_conversation`, and `set_favourite`, which overwrites the
  flag itself. On by default is what keeps a route that *does* serialize a
  conversation from forgetting; off is a deliberate act at the call site.
- **Starring is idempotent under contention**, because the insert is
  `ON CONFLICT DO NOTHING` rather than a read followed by an insert. Two
  overlapping POSTs for the same pair both saw no row and the second violated
  the primary key; the client also serializes its own pending star per
  conversation, so a double click cannot have the DELETE answered before the
  POST it followed.
- **The band is an `ORDER BY`, not a grouping of the page.** The sidebar is
  paged, so a favourite sorted into page two by recency would sit under fifty
  threads that are not one. Within each band the chosen sort still applies, and
  the archived view is not banded at all: a star survives archiving, but a band
  inside the archive would be a second place to look for what archiving just
  moved.

There is **no way to read a conversation across tenants any more.** The sentinel
that used to spell that out (`UNSCOPED`) had exactly one caller,
`/admin/conversations/{id}`, and both went with the deployment-wide conversation
browser — Activity answers "what happened" with the cost, the model, the trace
and what the model was handed beside it, which is the question that screen was
being used for. What is left of it is `GET /admin/conversations?user_id=`: one
named account's threads, listed for the admin user drawer and never read.

### What the admin user drawer asks for

`GET /admin/users/{id}/detail` is its own route rather than fields on
`GET /admin/users/{id}`, because it is a **view** assembled from three tables -
memberships, sessions, and the user row - and a user is read in a dozen places
that need none of it.

It exists because the drawer answered none of the questions an admin opening a
row actually has: it showed the id, the email already in the table, the display
name and a join date (#942). What it answers now is where this person has
access and with what authority, when they were last here, and whether anything
of theirs is still signed in. `last_seen_at` is **null rather than absent** for
an account that has never signed in, because "created and never used" and
"dormant since March" are different decisions.

The whole route is `CurrentAppAdmin`: every field on it is about somebody else.

For full endpoint-level permissions, see `docs/permissions.md`.

## File Processing in Chat

When a user uploads a file in the chat interface, the following pipeline executes:

```
Upload (POST /files/upload)
  -> Validate (MIME type + size)
  -> Classify (image / pdf / docx / text)
  -> Parse (extract text content)
  -> Store (save to media/{user_id}/)
  -> Record (create ChatFile in DB)
  -> Link (attach to message when sent)
```

### Supported File Types

| Category | Extensions | Processing |
|----------|-----------|------------|
| Images | JPEG, PNG, WebP, GIF | Stored as-is, sent to LLM as binary for vision |
| PDF | .pdf | Text extracted via configured parser |
| Documents | .docx | Text extracted via python-docx |
| Text | .txt, .md | UTF-8 decoded directly |

### Parser Selection
Chat attachments are read with PyMuPDF and are not configurable: an attachment
belongs to no collection, so there is no stored configuration to read a parser
choice from. Parser selection applies to knowledge collections, where it is a
per-collection setting.

### Storage

Files are saved to `media/{user_id}/` via `FileStorageService`. The `ChatFile`
model stores the `storage_path`, `filename`, `mime_type`, `size`, `file_type`,
and `parsed_content` (extracted text). Only the file owner can access their files.

### Size Limits

There are two, because there are two surfaces. `MAX_UPLOAD_SIZE_MB` (default
50MB) is the knowledge-base document cap; `CHAT_MAX_UPLOAD_SIZE_MB` (default
10MB) is what may be attached in chat. They are separate settings rather than
one, because a document is chunked and read back through retrieval while an
attachment to an agent with no workspace is pasted whole into the prompt — the
same size fails differently on each. `GET /api/v1/health` publishes both.

## RAG System

### Architecture Overview

The RAG (Retrieval Augmented Generation) system provides a knowledge base that
the AI agent can search during conversations. It is composed of:

```
Documents -> Parse -> Chunk -> Embed -> Vector Store
                                            |
User Query -> Embed -> Search -> Rerank? -> Results -> Agent Prompt
```

### Key Principle: RAG is Global

**Collections are shared across ALL users.** There is no per-user document
isolation. This means:

- Any authenticated user can **search** any collection.
- Only **admins** can create/delete collections, upload documents, configure sync
  sources, and view sync logs.
- The knowledge base serves as an organization-wide shared resource.

### Components

| Component | File | Purpose |
|-----------|------|---------|
| `DocumentProcessor` | `rag/documents.py` | Parses files into text (PDF, DOCX, TXT, images) |
| `IngestionService` | `rag/ingestion.py` | Orchestrates parse -> chunk -> embed -> store |
| `RetrievalService` | `rag/retrieval.py` | Handles search queries with filtering and scoring |
| `EmbeddingService` | `rag/embeddings.py` | Generates embeddings via configured provider |
| `BaseVectorStore` | `rag/vectorstore.py` | Abstract interface for vector database operations |
| `PgVectorStore` | `rag/vectorstore.py` | pgvector (PostgreSQL) implementation |

### Ingestion Pipeline

Documents can be ingested via:

1. **CLI** -- `uv run agenticos cmd rag-ingest <path>`
2. **API** -- `POST /api/v1/rag/collections/{name}/ingest` (admin only, file upload)
3. **Sync Sources** -- Configured connectors (Google Drive, S3) that pull documents
   on a schedule or on-demand.

Each ingested document gets:
- Parsed into text (parser chosen per collection, overridable per upload)
- Split into chunks (`chunk_size` / `chunk_overlap`, also per collection)
- Embedded via the configured embedding provider
- Stored in the vector database
- Tracked in SQL via `RAGDocument` model with status (`processing`, `done`, `error`)

### Sync Modes

| Mode | Behavior |
|------|----------|
| `full` | Replace all documents (re-ingest everything) |
| `new_only` | Add new files, re-ingest files whose content hash changed, skip unchanged |
| `update_only` | Only re-ingest changed files, skip new files entirely |

### Sync Connectors

Remote document sources use pluggable connectors in
`app/services/rag/connectors/`. Each connector implements `BaseSyncConnector`
with `list_files()` and `_fetch()`, declares a `SECRET_KIND` naming the vault
secret that authenticates it, and declares a `CONFIG_SCHEMA` of
`ConnectorConfigField`s saying how to find the documents. `download_file()` is
concrete and decides where a file may land. See `docs/patterns.md` for how to
add one, and `docs/howto/add-sync-connector.md` for a worked example.
