---
source_sha: 4ad2bb97f109
---

# Einen API-Endpunkt hinzufügen { #add-an-api-endpoint }

Dieses Beispiel fügt einen "Notification"-Endpunkt von Anfang bis Ende hinzu und
folgt dabei der Schichtung, die hier jede Domäne verwendet.

!!! important "Routes → Services → Repositories, und nie eine Abkürzung"

    Eine Route validiert, delegiert und gibt zurück. Eine **Route importiert nie
    ein Repository**, und ein Repository enthält nie Geschäftslogik. Siehe
    [Architektur](../architecture.md).

## Schritt für Schritt { #step-by-step }

### 1. Das Schema anlegen (`app/schemas/`) { #1-create-the-schema-appschemas }

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

Ein Schema pro Operation — `*Create`, `*Update` (jedes Feld optional), `*Read`
(mit `id` und Zeitstempeln) und `*List` (`items` plus `total`).
[Schemas und Models](../architecture.md) hat die Regel.

### 2. Das Datenbankmodell anlegen (`app/db/models/`) { #2-create-the-database-model-appdbmodels }

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

`TimestampMixin` liefert `created_at` und `updated_at`, also wird hier keines von
beiden deklariert. `__repr__` ist nicht optional — jedes Modell in dieser
Codebasis hat eines. Importieren Sie das Modell in `app/db/models/__init__.py`,
sonst sieht Alembic es nicht.

### 3. Das Repository anlegen (`app/repositories/`) { #3-create-the-repository-apprepositories }

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

!!! warning "Eine seitenweise Liste braucht eine echte Zählung, nicht `len(items)`"

    Das `total` eines `*List` ist, wie viele Zeilen **passen**, und genau dagegen
    blättert ein Client. `len(items)` ist, wie viele zurückkamen — gleich nur so
    lange, bis die erste Seite voll ist, und danach still falsch in der Richtung,
    die Zeilen verbirgt.

!!! danger "`flush()` + `refresh()`, nie `commit()`"

    Die Session der Anfrage committet einmal, nachdem die Route zurückgekehrt ist
    und *bevor* die Antwort geschrieben wird — und das ist es, was ein 2xx heißen
    lässt, dass der Schreibvorgang lesbar ist
    ([#353](https://github.com/vstorm-co/agenticos/issues/353)). Ein Repository,
    das committet, nimmt diese Reihenfolge der einen Stelle weg, der sie gehört.

Ein Repository ist ein **Modul zustandsloser Funktionen**, keine Klasse: `db`
zuerst, alles danach nur als Schlüsselwort, und die Entität zurückgegeben statt
einer id oder eines Dicts. Re-exportieren Sie es aus
`app/repositories/__init__.py` so, wie es jedes andere auch tut —
`from app.repositories import notification as notification_repo` —, damit
Aufrufer den Alias importieren und nicht den Modulpfad.

### 4. Den Service anlegen (`app/services/`) { #4-create-the-service-appservices }

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

Der Service hält die Session und sonst nichts; Repositories werden als Module
importiert. Er ist außerdem die **einzige** Schicht, die eine Domänen-Exception
wirft, und `details` trägt den Wert statt einer Zeichenkette davon — der Handler
kodiert mit `jsonable_encoder`.

### 5. Die Dependency registrieren (`app/api/deps.py`) { #5-register-the-dependency-appapidepspy }

```python
from app.services.notification import NotificationService


def get_notification_service(db: DBSession) -> NotificationService:
    return NotificationService(db)


NotificationSvc = Annotated[NotificationService, Depends(get_notification_service)]
```

### 6. Die Route anlegen (`app/api/routes/v1/`) { #6-create-the-route-appapiroutesv1 }

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

!!! note "`-> Any`, hier per Konvention"

    `response_model` ist das, was die Antwort serialisiert und validiert, und
    jede Route in dieser Codebasis lässt die Annotation bei `Any`, damit es eine
    Antwort auf "wo ist die Form der Antwort deklariert" gibt statt zweier, die
    sich widersprechen können. Folgen Sie dem aus Konsistenz mit dem umgebenden
    Code — nicht, weil eine Annotation einen zweiten Validierungsdurchlauf kosten
    würde, denn das tut sie nicht.

Alles, was auf eine Organisation begrenzt ist, nimmt eine Permission aus dem
Katalog auf der **Collection**-Route —
`dependencies=[Depends(require(Perm.X))]` —, während eine Route auf einer
einzelnen Ressource die Entscheidung an einen Service übergibt, der
`resolve_access` aufruft. Siehe [Berechtigungen](../permissions.md).

### 7. Den Router registrieren { #7-register-the-router }

In `app/api/routes/v1/__init__.py`:

```python
from app.api.routes.v1 import notifications

v1_router.include_router(
    notifications.router, prefix="/notifications", tags=["notifications"]
)
```

### 8. Die Migration erstellen und anwenden { #8-create-and-apply-the-migration }

```bash
make db-migrate    # message: "Add notifications table"
make db-upgrade
make db-check      # a model change with no migration fails here, and in `make check`
```

### 9. Testen { #9-test-it }

Eine Route wird mit Tests ausgeliefert, nicht nach ihnen: einer dafür, dass ihr
Gate verdrahtet ist (`tests/api/`), einer pro Service-Zweig einschließlich der
Ablehnung, und ein Integrationstest, wenn Sie tatsächlich ein Constraint oder
eine Kaskade geändert haben. Dann `http://localhost:8000/docs`, um es von Hand
auszuprobieren.
