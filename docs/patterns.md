# Code Patterns

## Dependency Injection

Use FastAPI's `Depends()` for injecting dependencies:

```python
from app.api.deps import get_db, get_current_user

@router.get("/conversations")
async def list_conversations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ConversationService(db)
    return await service.get_by_user(current_user.id)
```

> **Important:** Routes never contain direct database calls. All data access
> goes through a service, which in turn delegates to a repository.

Available dependencies in `app/api/deps.py`:
- `get_db` - Database session
- `get_current_user` - Authenticated user (raises 401 if not authenticated)
- `get_current_user_optional` - User or None
- `get_redis` - Redis connection

## Service Layer Pattern

Every feature uses the same pattern: a service class receives a DB session,
instantiates its repository, and provides business-level methods. Services
are the **only** layer that raises domain exceptions.

```python
class ConversationService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ConversationRepository()

    async def create(self, data: ConversationCreate, user_id: UUID) -> Conversation:
        # Business validation
        return await self.repo.create(self.db, user_id=user_id, **data.model_dump())

    async def get_or_raise(self, id: UUID) -> Conversation:
        conv = await self.repo.get_by_id(self.db, id)
        if not conv:
            raise NotFoundError(message="Conversation not found", details={"id": id})
        return conv
```

All current services follow this pattern: `UserService`, `ConversationService`,
`FileUploadService`, `FileStorageService`, `RagDocumentService`, `RagSyncService`, `SyncSourceService`.

## Repository Layer Pattern

Repositories handle data access only. They contain **no** business logic and
always use `flush()` instead of `commit()`, because the request's session owns
the transaction and commits it once — after the route returns and *before* the
response is written, which is what makes a 2xx mean the write is readable. See
[the request's transaction](architecture.md#the-requests-transaction).

```python
class ConversationRepository:
    async def get_by_id(self, db: AsyncSession, id: UUID) -> Conversation | None:
        return await db.get(Conversation, id)

    async def create(self, db: AsyncSession, **kwargs) -> Conversation:
        conv = Conversation(**kwargs)
        db.add(conv)
        await db.flush()  # Not commit! Let dependency manage transaction
        await db.refresh(conv)
        return conv

    async def get_by_user(
        self, db: AsyncSession, user_id: UUID, skip: int = 0, limit: int = 100
    ) -> list[Conversation]:
        result = await db.execute(
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .offset(skip).limit(limit)
        )
        return list(result.scalars().all())
```

## Exception Handling

Use domain exceptions in services:

```python
from app.core.exceptions import NotFoundError, AlreadyExistsError, ValidationError

# In service
if not conversation:
    raise NotFoundError(
        message="Conversation not found",
        details={"id": id}
    )

if await self.repo.exists_by_email(self.db, email):
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

**A refusal describes the refusal, not the server.** Everything in `details` is
read by whoever was refused, so it names the field, the id or the resource they
can act on - never a filesystem path, an upstream client's exception text, or a
setting whose value describes the deployment rather than a limit the caller is
being held to (`max_mb` and `seats_limit` are exactly what a caller can act on;
where the container keeps its templates is not). The diagnosis is not deleted, it
moves: the path the loader searched and the vendor SDK's message go in the log
line beside the raise, where an operator reads them and a caller does not.

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
`{"field": "base_url"}`, never the endpoint with the password still in it.

The same applies to an audit entry, which is `details` with a longer life: record
*which* fields an administrator changed, not the values they submitted.

## Schema Patterns

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

## Connector Pattern (RAG Sync)

Remote document sources (Google Drive, S3, etc.) use a pluggable connector
pattern defined in `app/services/rag/connectors/`. Each connector inherits from
`BaseSyncConnector` and is registered in the `CONNECTOR_REGISTRY` dictionary.

### Adding a new connector

1. Create a file in `app/services/rag/connectors/` (e.g. `sharepoint.py`).
2. Subclass `BaseSyncConnector` and implement the required methods.
3. Register the connector in `CONNECTOR_REGISTRY`.

```python
from app.services.rag.connectors import BaseSyncConnector, RemoteFile, CONNECTOR_REGISTRY

class SharePointConnector(BaseSyncConnector):
    CONNECTOR_TYPE = "sharepoint"
    DISPLAY_NAME = "SharePoint"
    CONFIG_SCHEMA = {
        "site_url": {"label": "Site URL", "required": True},
        "client_id": {"label": "Client ID", "required": True},
    }

    async def list_files(self, config: dict) -> list[RemoteFile]:
        # Return metadata for available files
        ...

    async def _fetch(self, file: RemoteFile, dest_path: Path, config: dict) -> None:
        # Write the bytes to dest_path. The base class chose it and confirmed
        # it is inside the sync directory - never build a path from file.name.
        ...

# Register so the sync service can discover it
CONNECTOR_REGISTRY["sharepoint"] = SharePointConnector
```

The `RagSyncService` uses `CONNECTOR_REGISTRY` to look up the right connector
by type, validate its config, list remote files, download them, and hand them
off to the ingestion pipeline.

## Frontend Patterns

### Authentication (HTTP-only cookies)

```typescript
import { useAuth } from '@/hooks/use-auth';

function Component() {
    const { user, isAuthenticated, login, logout } = useAuth();
}
```

### State Management (Zustand)

```typescript
import { useAuthStore } from '@/stores/auth-store';

const { user, setUser, logout } = useAuthStore();
```

### WebSocket Chat

```typescript
import { useChat } from '@/hooks/use-chat';

function ChatPage() {
    const { messages, sendMessage, isStreaming } = useChat();
}
```
