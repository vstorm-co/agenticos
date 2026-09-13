---
source_sha: 4ad2bb97f109
---

# Dodaj endpoint API { #add-an-api-endpoint }

Ten przykład dodaje endpoint „Notification” od początku do końca, zgodnie z
warstwowaniem, którego używa tu każda domena.

!!! important "Routes → Services → Repositories i żadnej drogi na skróty"

    Route waliduje, deleguje i zwraca. **Route nigdy nie importuje
    repozytorium**, a repozytorium nigdy nie zawiera logiki biznesowej. Zobacz
    [Architekturę](../architecture.md).

## Krok po kroku { #step-by-step }

### 1. Utwórz schemat (`app/schemas/`) { #1-create-the-schema-appschemas }

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

Jeden schemat na operację — `*Create`, `*Update` (każde pole opcjonalne), `*Read`
(z `id` i znacznikami czasu) oraz `*List` (`items` plus `total`).
[Schematy i modele](../architecture.md) opisują tę regułę.

### 2. Utwórz model bazodanowy (`app/db/models/`) { #2-create-the-database-model-appdbmodels }

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

`TimestampMixin` dostarcza `created_at` i `updated_at`, więc żadne z nich nie
jest tu deklarowane. `__repr__` nie jest opcjonalny — każdy model w tej bazie
kodu go ma. Zaimportuj model w `app/db/models/__init__.py`, bo inaczej Alembic go
nie zobaczy.

### 3. Utwórz repozytorium (`app/repositories/`) { #3-create-the-repository-apprepositories }

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

!!! warning "Stronicowana lista potrzebuje prawdziwej liczby, a nie `len(items)`"

    `total` w `*List` to liczba wierszy, które **pasują**, i to względem niej
    klient stronicuje. `len(items)` to liczba tych, które wróciły — równa tamtej
    tylko do chwili, gdy zapełni się pierwsza strona, a potem po cichu błędna w
    kierunku, który ukrywa wiersze.

!!! danger "`flush()` + `refresh()`, nigdy `commit()`"

    Sesja żądania commituje raz, po powrocie z route'a i *przed* zapisaniem
    odpowiedzi — to właśnie sprawia, że 2xx znaczy, iż zapis jest odczytywalny
    ([#353](https://github.com/vstorm-co/agenticos/issues/353)). Repozytorium,
    które commituje, zabiera tę kolejność jedynemu miejscu, do którego ona
    należy.

Repozytorium to **moduł bezstanowych funkcji**, a nie klasa: `db` na początku,
wszystko po nim tylko po nazwie, i zwracana encja, a nie id czy słownik.
Reeksportuj je z `app/repositories/__init__.py` tak jak każde inne —
`from app.repositories import notification as notification_repo` — żeby wołający
importowali alias, a nie ścieżkę modułu.

### 4. Utwórz serwis (`app/services/`) { #4-create-the-service-appservices }

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

Serwis trzyma sesję i nic poza tym; repozytoria importowane są jako moduły. Jest
też **jedyną** warstwą, która rzuca wyjątek domenowy, a `details` niesie wartość,
a nie jej napisową wersję — handler koduje przez `jsonable_encoder`.

### 5. Zarejestruj zależność (`app/api/deps.py`) { #5-register-the-dependency-appapidepspy }

```python
from app.services.notification import NotificationService


def get_notification_service(db: DBSession) -> NotificationService:
    return NotificationService(db)


NotificationSvc = Annotated[NotificationService, Depends(get_notification_service)]
```

### 6. Utwórz route (`app/api/routes/v1/`) { #6-create-the-route-appapiroutesv1 }

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

!!! note "`-> Any`, zgodnie z tutejszą konwencją"

    To `response_model` serializuje i waliduje odpowiedź, a każdy route w tej
    bazie kodu zostawia adnotację na `Any`, żeby na pytanie „gdzie zadeklarowano
    kształt odpowiedzi” była jedna odpowiedź, a nie dwie, które mogą się nie
    zgadzać. Trzymaj się tego dla spójności z otaczającym kodem — a nie dlatego,
    że adnotacja kosztowałaby drugi przebieg walidacji, bo nie kosztuje.

Wszystko, co jest w zakresie organizacji, bierze uprawnienie z katalogu na
route'cie **kolekcji** — `dependencies=[Depends(require(Perm.X))]` — podczas gdy
route per zasób oddaje decyzję serwisowi wołającemu `resolve_access`. Zobacz
[Uprawnienia](../permissions.md).

### 7. Zarejestruj router { #7-register-the-router }

W `app/api/routes/v1/__init__.py`:

```python
from app.api.routes.v1 import notifications

v1_router.include_router(
    notifications.router, prefix="/notifications", tags=["notifications"]
)
```

### 8. Utwórz i zastosuj migrację { #8-create-and-apply-the-migration }

```bash
make db-migrate    # message: "Add notifications table"
make db-upgrade
make db-check      # a model change with no migration fails here, and in `make check`
```

### 9. Przetestuj to { #9-test-it }

Route wychodzi razem z testami, a nie po nich: jeden sprawdzający, że jego bramka
jest podpięta (`tests/api/`), po jednym na każdą gałąź serwisu, łącznie z
odmową, oraz test integracyjny, jeśli tym, co naprawdę zmieniłeś, jest
ograniczenie albo kaskada. A potem `http://localhost:8000/docs`, żeby sprawdzić
to ręcznie.
