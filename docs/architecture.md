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
- Each connector provides `list_files()` and `_fetch()`; `download_file()` is
  the base class's, and is what decides where a remote name may be written
- Registered in `CONNECTOR_REGISTRY` for discovery at runtime

## The request's transaction

One request, one session, one transaction, committed in one place — and the place
matters as much as the fact.

A route asks for `DBSession` (`app/api/deps.py`), which resolves `get_db_session`
(`app/db/session.py`). Everything below the route shares that one session:
services take it in their constructor, repositories take it as their first
argument, and neither ever calls `commit()`. `flush()` sends the statements so
the row has an id and the constraints have been checked; the commit happens once,
on the way out.

**On the way out means before the response is written.** The alias declares
`Depends(get_db_session, scope="function")`, which registers the session's exit
code on the exit stack FastAPI unwinds between the path operation returning and
`await response(scope, receive, send)`. So the order for a request is:

1. the route returns, and `response_model` serializes what it returned;
2. the transaction commits — or, if anything raised, rolls back;
3. the response is written to the socket;
4. the session is closed.

That ordering is the whole contract, and it is what lets a client act on its own
answer: **a 2xx means the write is readable, not merely accepted.** FastAPI's
default for a dependency with `yield` is `scope="request"`, which puts steps 2
and 3 the other way round — and did here until [#353][353], where an acceptance
answered 204 while the membership row it created stayed invisible to the very
next request for 21.7ms, and an invitation token was spent 34ms before the
transaction that minted it committed.

Three consequences worth knowing before writing a route:

- **A commit that fails is a 500, not a log line.** The response has not been
  written yet, so a deferred constraint or a lost connection reaches the client
  as an error rather than being discovered behind an already-sent 2xx.
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
`get_worker_db_context()`; both commit on a clean exit of their own `async with`,
which has nothing to do with a response.

[353]: https://github.com/vstorm-co/agenticos/issues/353

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

## Key Files

- Entry point: `app/main.py`
- Configuration: `app/core/config.py`
- Dependencies: `app/api/deps.py`
- Auth utilities: `app/core/security.py`
- Exception handlers: `app/api/exception_handlers.py`

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
```

!!! note "`require(...)` does not belong on a per-resource route"

    A role gate cannot see the grants on a row, so it would refuse a Viewer
    holding an explicit `edit` grant before `resolve_access` ever widened their
    access. `tests/api/test_platform_routes.py` enforces both halves.

`UserRole`, `User.has_role()`, `RoleChecker`, `CurrentAdmin` and
`CurrentSuperuser` were the template's model and are gone, along with the
`users.role` column (migration `0066`). They were a third answer to a question
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
- On `list_messages` that one argument does two jobs — it authorizes, *and* it
  enriches each message with the caller's own rating. That overload is why its
  authorizing half went missing for so long: the route passed it, the argument
  was plainly there in review, and it was doing the other job.
- File downloads verify `chat_file.user_id == current_user.id`.

`ConversationService` makes the distinction impossible to omit: `organization_id`
is a **required** keyword, and a caller that genuinely reads across tenants
passes the `UNSCOPED` sentinel rather than leaving the argument out. There is one
— `/admin/conversations/{id}`, gated on `CurrentAppAdmin` — and `rg UNSCOPED`
finds it. The argument used to default to `None`, `None` meant unscoped, and an
omission is indistinguishable from an intention.

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

Maximum upload size is controlled by `MAX_UPLOAD_SIZE_MB` (default 50MB).

## RAG System

### Architecture Overview

The RAG (Retrieval Augmented Generation) system provides a knowledge base that
the AI agent can search during conversations. It is composed of:

```
Documents -> Parse -> Chunk -> Embed -> Vector Store
                                            |
User Query -> Embed -> Search -> Rerank? -> Results -> Agent Prompt
```

### Key Principle: the collection is the unit of access

**Collections are not global.** Each one is owned by a `knowledge_bases` row, and
that row is the only half of the pair that knows an organization — so every `/rag`
and `/kb` route resolves the name through `app/services/collection_access.py` before
touching a vector, a document or a sync source. Reading takes `collections:view`
reaching that row and writing takes `collections:edit`, either of which an explicit
grant widens on one collection without promoting anybody.

Within a collection there is no per-document isolation: reaching one reaches every
document in it.

[Who may reach a collection](file-processing.md#who-may-reach-a-collection) is the
whole rule, scope by scope and operation by operation. This page does not keep a
second copy of it.

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
2. **API** -- `POST /api/v1/rag/collections/{name}/ingest` (file upload, gated on
   `collections:edit` reaching that collection)
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

Remote document sources use pluggable connectors in `rag/connectors/`. Each
connector implements `BaseSyncConnector` with `list_files()` and `_fetch()`.
`download_file()` stays the base class's: it resolves the remote name against
the sync directory and confirms containment before handing an implementation a
path, so a connector cannot decide where a file lands. See `docs/patterns.md`
for how to add a new connector.
