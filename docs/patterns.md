# Code patterns

## Dependency injection

Everything a route needs arrives as an `Annotated` alias from `app/api/deps.py` -
never a bare `Depends()` in the signature:

```python
from app.api.deps import ConversationSvc, CurrentUser


@router.get("", response_model=ConversationList)
async def list_conversations(service: ConversationSvc, user: CurrentUser) -> Any:
    items, total = await service.list(user_id=user.id)
    return ConversationList(items=items, total=total)
```

!!! important "Routes never contain direct database calls"

    All data access goes through a service, which in turn delegates to a
    repository. A route validates, delegates and returns.

The aliases worth knowing, all in `app/api/deps.py`:

| Alias | |
|---|---|
| `DBSession` | The request's session. `scope="function"`, which is what commits before the response is written |
| `StreamingDBSession` | The same session with `scope="request"`, for a route that streams its body |
| `CurrentUser` | An authenticated user; 401 without one |
| `CurrentAppAdmin` | The deployment's superadmin |
| `Auth` | The `AuthContext`: the caller, the organization, the permission set |
| `Redis` | The Redis client |
| `<Domain>Svc` | One per service, built from `DBSession` |

## Service layer pattern

Every feature uses the same pattern: a service class receives a DB session and
provides business-level methods. Services are the **only** layer that raises
domain exceptions.

```python
from app.repositories import conversation_repo


class ConversationService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: ConversationCreate, ctx: AuthContext) -> Conversation:
        return await conversation_repo.create_conversation(
            self.db,
            organization_id=ctx.organization_id,
            user_id=ctx.user_id,
            title=data.title,
        )

    async def get_conversation(self, conversation_id: UUID, *, organization_id: UUID) -> Conversation:
        conversation = await conversation_repo.get_conversation_by_id(self.db, conversation_id)
        missing = NotFoundError(
            message="Conversation not found",
            details={"conversation_id": conversation_id},
        )
        if not conversation:
            raise missing
        if conversation.organization_id != organization_id:
            raise missing
        return conversation
```

The tenant check raises **the same refusal** as a missing row: "you may not read
this" tells somebody in another organization that the id exists.

A service holds the session and nothing else - repositories are imported as
modules rather than instantiated, so there is no per-request object graph to keep
consistent. Where a domain owns infrastructure of its own (clients, adapters,
parsers) the service becomes a subpackage exporting one facade:
`services/rag/`, `services/channels/`, `services/email/`.

## Repository layer pattern

Repositories handle data access only. They contain **no** business logic and
always use `flush()` instead of `commit()`, because the request's session owns
the transaction and commits it once — after the route returns and *before* the
response is written, which is what makes a 2xx mean the write is readable. See
[the request's transaction](architecture.md#the-requests-transaction).

A repository is a **module of stateless functions**, not a class - `db` first,
everything after it keyword-only:

```python
# app/repositories/conversation.py

async def create_conversation(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID | None = None,
    title: str | None = None,
) -> Conversation:
    conversation = Conversation(
        user_id=user_id, organization_id=organization_id, title=title
    )
    db.add(conversation)
    await db.flush()
    await db.refresh(conversation)
    return conversation


async def get_conversations_by_user(
    db: AsyncSession,
    user_id: UUID | None = None,
    *,
    organization_id: UUID,
    skip: int = 0,
    limit: int = 50,
) -> list[Conversation]:
    query = select(Conversation).where(Conversation.organization_id == organization_id)
    if user_id:
        query = query.where(Conversation.user_id == user_id)
    result = await db.execute(query.offset(skip).limit(limit))
    return list(result.scalars().all())
```

Two things about that signature. `organization_id` has no default anywhere in
that module, on purpose: every conversation belongs to a tenant, and a caller
that cannot name one has a bug rather than a default. And a narrowing argument
that is accepted has to be **applied** — a query that takes `user_id` and filters
only on the tenant answers with every member's conversations. (The real module
widens the user predicate to confirmed channel participants through
`_reachable_by`, over ids the caller has already vetted against the platform;
what matters here is that the argument reaches the `WHERE` clause at all.)

!!! danger "`flush()`, never `commit()`"

    The request's session commits once. The one sanctioned exception is the agent
    run path, which commits before the model call and again in its terminal
    `finally`.

## Exception handling

Use domain exceptions in services:

```python
from app.core.exceptions import NotFoundError, AlreadyExistsError, ValidationError

# In service
if not conversation:
    raise NotFoundError(
        message="Conversation not found",
        details={"id": id}
    )

if await user_repo.get_by_email(self.db, email):
    raise AlreadyExistsError(
        message="User with this email already exists"
    )
```

Exception handlers convert to HTTP responses automatically, and `details` is
encoded with `jsonable_encoder` - the same encoder `response_model` uses - so the
raiser passes the value it has rather than a string of it. A `UUID` arrives as its
string form, a `datetime` in ISO 8601, an `Enum` as its value. Money is the
exception worth knowing: a `Decimal` encodes to a float, so a cost or a cap is
stringified by the code that raises.

!!! warning "A refusal describes the refusal, not the server"

    Everything in `details` is read by whoever was refused, so it names the
    field, the id or the resource they can act on - never a filesystem path, an
    upstream client's exception text, or a setting describing the deployment. The
    diagnosis is not deleted; it moves to the log line beside the raise.

`max_mb` and `seats_limit` are exactly what a caller can act on; where the
container keeps its templates is not. The path the loader searched and the vendor
SDK's message go in the log line beside the raise, where an operator reads them
and a caller does not.

```python
except Exception as exc:
    logger.exception("Knowledge base search failed")   # the upstream text stays here
    raise ExternalServiceError(
        message="Knowledge base search failed",
        details={"collections": names, "operation": "retrieve"},
    ) from exc
```

`message` is held to the same bar - the envelope carries it and the handler logs
it on the same line, so a sentence naming the endpoint leaks whatever the field
was refused for carrying. A URL the refusal is *about* is named by its field:
`refused_field("base_url", ...)`, never the endpoint with the password still in
it. That helper is in `app/core/field_errors.py`, which is the only place the
`details["fields"]` a form marks an input from is built - see
[Architecture](architecture.md#a-refusal-that-names-a-field) for the three entry
points and for which refusals deliberately name no field at all.

The same applies to an audit entry, which is `details` with a longer life: record
*which* fields an administrator changed, not the values they submitted.

## Schema patterns

Separate schemas for different operations:

```python
# Base with shared fields
class UserBase(BaseModel):
    email: str
    full_name: str | None = None

# For creation (input)
class UserCreate(UserBase):
    password: str

# For updates (all optional)
class UserUpdate(BaseModel):
    full_name: str | None = None
    email: str | None = None

# For responses (with DB fields)
class UserResponse(UserBase):
    id: UUID
    created_at: datetime
    updated_at: datetime | None

    model_config = ConfigDict(from_attributes=True)
```

### An update is written through `writable`, never dumped

On a `*Update` every field is `X | None` because `None` means *not provided* — and
`model_dump(exclude_unset=True)` keeps a field that was **explicitly set to
`None`**, because setting it is what `exclude_unset` asks about. So a client
sending `{"name": null}` gets its `None` past the dump, into `setattr`, and onto a
`NOT NULL` column: a 500 naming a database constraint, for a request the API's own
types say is legal.

```python
from app.db.updates import writable

changes = writable(data, over=AgentEmbed)      # not data.model_dump(exclude_unset=True)
```

**The column decides.** `writable` reads nullability off the model, so a schema
that gains an optional field is covered the day it gains one — where a hand-kept
list of field names per service is a new crash the next time somebody adds one.
Twenty-four such pairs existed across eleven schemas before #637.

A `null` a column *allows* is kept, which is what makes this different from
`exclude_none`: clearing a nullable column is a legitimate request, and dropping
every null would make "remove the description" silently do nothing. Where a field
has a default worth returning to, the service substitutes it before calling —
`EmbedUpdate.config` restores the kind's defaults rather than dropping the key.

`tests/test_update_nulls.py` is what keeps this true: every `*Update` schema is
declared against the row it writes, and no service may dump one itself.

## Handing work to the background

Two primitives, in `app/core/background.py`, and the choice between them is
about what the work reads rather than how long it takes:

```python
from app.core.background import spawn, spawn_after_commit

# Owns everything it needs - a rendered email, an id it will not look up.
spawn(deliver(key, to, context), name=f"email:{key}:{to}")

# Reads a row this unit of work wrote. Starts when the session commits.
spawn_after_commit(self.db, ingest_document_flow(rag_document_id=str(doc.id)), name=...)
```

Both hold a strong reference to the task and log whatever it raises, which a
bare `asyncio.create_task` does neither of. `spawn_after_commit` additionally
queues the coroutine on the session, so nothing starts until the transaction the
work depends on has landed — a flow that reads its own row by id would otherwise
run against a database that does not have it yet
([#417](https://github.com/vstorm-co/agenticos/issues/417)). Neither survives a
restart; work that must belongs in a Prefect deployment.

## Connector pattern (RAG sync)

Remote document sources (Google Drive, S3, etc.) use a pluggable connector
pattern defined in `app/services/rag/connectors/`. Each connector inherits from
`BaseSyncConnector` and is registered in the `CONNECTOR_REGISTRY` dictionary.

### Adding a new connector

1. Create a file in `app/services/rag/connectors/` (e.g. `sharepoint.py`).
2. Subclass `BaseSyncConnector` and implement the required methods.
3. Register the connector in `CONNECTOR_REGISTRY`.

```python
from app.core.secret_kinds import SecretKind, StorableSecret
from app.schemas.sync_source import ConnectorConfigField
from app.services.rag.connectors import (
    CONNECTOR_REGISTRY,
    BaseSyncConnector,
    ConnectorConfig,
    RemoteFile,
)

class SharePointConnector(BaseSyncConnector):
    CONNECTOR_TYPE = "sharepoint"
    DISPLAY_NAME = "SharePoint"
    # What authenticates it. The credential is a vault secret the source names,
    # unsealed by the caller - never a field of CONFIG_SCHEMA.
    SECRET_KIND = SecretKind.API_KEY
    CONFIG_SCHEMA = {
        "site_url": ConnectorConfigField(type="string", required=True, label="Site URL"),
    }

    async def list_files(
        self, config: ConnectorConfig, credential: StorableSecret | None
    ) -> list[RemoteFile]:
        # Return metadata for available files
        ...

    async def _fetch(
        self,
        file: RemoteFile,
        dest_path: Path,
        config: ConnectorConfig,
        credential: StorableSecret | None,
    ) -> None:
        # Write the bytes to dest_path. The base class chose it and confirmed
        # it is inside the sync directory - never build a path from file.name.
        ...

# Register so the sync service can discover it
CONNECTOR_REGISTRY["sharepoint"] = SharePointConnector
```

The `RagSyncService` uses `CONNECTOR_REGISTRY` to look up the right connector
by type, validate its config, list remote files, download them, and hand them
off to the ingestion pipeline.

## Frontend patterns

### Authentication (HTTP-only cookies)

```typescript
import { useAuth } from '@/hooks/use-auth';

function Component() {
    const { user, isAuthenticated, login, logout } = useAuth();
}
```

### State management (Zustand)

```typescript
import { useAuthStore } from '@/stores/auth-store';

const { user, setUser, logout } = useAuthStore();
```

### WebSocket chat

```typescript
import { useChat } from '@/hooks/use-chat';

function ChatPage() {
    const { messages, sendMessage, isStreaming } = useChat();
}
```
