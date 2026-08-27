# How to: Add a New API Endpoint

This example adds a "Notification" endpoint end to end, following the layering
every domain here uses.

!!! important "Routes → Services → Repositories, and never a shortcut"

    A route validates, delegates and returns. A **route never imports a
    repository**, and a repository never contains business logic. See
    [Architecture](../architecture.md).

## Step-by-Step

### 1. Create the schema (`app/schemas/`)

```python
# app/schemas/notification.py
from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema


class NotificationCreate(BaseSchema):
    title: str = Field(max_length=255)
    body: str
    channel: str = "email"


class NotificationRead(BaseSchema):
    id: UUID
    title: str
    body: str
    channel: str
    is_read: bool
    created_at: datetime


class NotificationList(BaseSchema):
    items: list[NotificationRead]
    total: int
```

One schema per operation — `*Create`, `*Update` (every field optional), `*Read`
(with `id` and timestamps) and `*List` (`items` plus `total`).
[Schemas and models](../architecture.md) has the rule.

### 2. Create the database model (`app/db/models/`)

```python
# app/db/models/notification.py
import uuid

from sqlalchemy import Boolean, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Notification(Base, TimestampMixin):
    """One notification sent to somebody, and whether they have read it."""

    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(String, nullable=False)
    channel: Mapped[str] = mapped_column(String(50), default="email", nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    def __repr__(self) -> str:
        return f"<Notification(id={self.id}, title={self.title})>"
```

`TimestampMixin` supplies `created_at` and `updated_at`, so neither is declared
here. `__repr__` is not optional — every model in this codebase has one. Import
the model in `app/db/models/__init__.py` or Alembic will not see it.

### 3. Create the repository (`app/repositories/`)

```python
# app/repositories/notification.py
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.notification import Notification


async def get_by_id(db: AsyncSession, notification_id: UUID) -> Notification | None:
    return await db.get(Notification, notification_id)


async def create(db: AsyncSession, *, title: str, body: str, channel: str) -> Notification:
    notification = Notification(title=title, body=body, channel=channel)
    db.add(notification)
    await db.flush()
    await db.refresh(notification)
    return notification


async def list_unread(db: AsyncSession, limit: int = 50) -> list[Notification]:
    result = await db.execute(
        select(Notification)
        .where(Notification.is_read.is_(False))
        .order_by(Notification.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def count_unread(db: AsyncSession) -> int:
    result = await db.execute(
        select(func.count()).select_from(Notification).where(Notification.is_read.is_(False))
    )
    return result.scalar_one()
```

!!! warning "A paged list needs a real count, not `len(items)`"

    `*List`'s `total` is how many rows **match**, which is what a client pages
    against. `len(items)` is how many came back — equal only until the first page
    fills up, and then quietly wrong in the direction that hides rows.

!!! danger "`flush()` + `refresh()`, never `commit()`"

    The request's session commits once, after the route returns and *before* the
    response is written — which is what makes a 2xx mean the write is readable
    ([#353](https://github.com/vstorm-co/agenticos/issues/353)). A repository
    that commits takes that ordering away from the one place that owns it.

A repository is a **module of stateless functions**, not a class: `db` first,
everything after it keyword-only, and the entity returned rather than an id or a
dict. Re-export it from `app/repositories/__init__.py` the way every other one is
— `from app.repositories import notification as notification_repo` — so callers
import the alias rather than the module path.

### 4. Create the service (`app/services/`)

```python
# app/services/notification.py
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.models.notification import Notification
from app.repositories import notification_repo
from app.schemas.notification import NotificationCreate


class NotificationService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: NotificationCreate) -> Notification:
        return await notification_repo.create(
            self.db, title=data.title, body=data.body, channel=data.channel
        )

    async def get_or_raise(self, notification_id: UUID) -> Notification:
        notification = await notification_repo.get_by_id(self.db, notification_id)
        if not notification:
            raise NotFoundError(
                message="Notification not found",
                details={"notification_id": notification_id},
            )
        return notification

    async def list_unread(self) -> tuple[list[Notification], int]:
        items = await notification_repo.list_unread(self.db)
        return items, await notification_repo.count_unread(self.db)
```

The service holds the session and nothing else; repositories are imported as
modules. It is also the **only** layer that raises a domain exception, and
`details` carries the value rather than a string of it — the handler encodes with
`jsonable_encoder`.

### 5. Register the dependency (`app/api/deps.py`)

```python
from app.services.notification import NotificationService


def get_notification_service(db: DBSession) -> NotificationService:
    return NotificationService(db)


NotificationSvc = Annotated[NotificationService, Depends(get_notification_service)]
```

### 6. Create the route (`app/api/routes/v1/`)

```python
# app/api/routes/v1/notifications.py
from typing import Any

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, NotificationSvc
from app.schemas.notification import NotificationCreate, NotificationList, NotificationRead

router = APIRouter()


@router.post("", response_model=NotificationRead, status_code=status.HTTP_201_CREATED)
async def create_notification(
    data: NotificationCreate, service: NotificationSvc, user: CurrentUser
) -> Any:
    return await service.create(data)


@router.get("", response_model=NotificationList)
async def list_unread(service: NotificationSvc, user: CurrentUser) -> Any:
    items, total = await service.list_unread()
    return NotificationList(items=items, total=total)
```

!!! note "`-> Any`, on purpose"

    `response_model` does the serialization. Annotating the real return type
    makes Pydantic validate the same object twice.

Anything org-scoped takes a permission from the catalog on the **collection**
route — `dependencies=[Depends(require(Perm.X))]` — while a per-resource route
hands the decision to a service calling `resolve_access`. See
[Permissions](../permissions.md).

### 7. Register the router

In `app/api/routes/v1/__init__.py`:

```python
from app.api.routes.v1 import notifications

v1_router.include_router(
    notifications.router, prefix="/notifications", tags=["notifications"]
)
```

### 8. Create and apply the migration

```bash
make db-migrate    # message: "Add notifications table"
make db-upgrade
make db-check      # a model change with no migration fails here, and in `make check`
```

### 9. Test it

A route ships with tests, not after them: one that its gate is wired
(`tests/api/`), one per service branch including the refusal, and an integration
test if a constraint or a cascade is what you actually changed. Then
`http://localhost:8000/docs` to try it by hand.
