---
source_sha: "4ad2bb97f109"
---

# Añade un endpoint de la API { #add-an-api-endpoint }

Este ejemplo añade un endpoint de "Notification" de principio a fin, siguiendo la
estratificación que usa aquí cada dominio.

!!! important "Rutas → servicios → repositorios, y nunca un atajo"

    Una ruta valida, delega y devuelve. Una **ruta nunca importa un
    repositorio**, y un repositorio nunca contiene lógica de negocio. Consulta
    [Arquitectura](../architecture.md).

## Paso a paso { #step-by-step }

### 1. Crea el schema (`app/schemas/`) { #1-create-the-schema-appschemas }

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

Un schema por operación — `*Create`, `*Update` (con todos los campos
opcionales), `*Read` (con `id` y marcas de tiempo) y `*List` (`items` más
`total`). La regla está en [Schemas y modelos](../architecture.md).

### 2. Crea el modelo de base de datos (`app/db/models/`) { #2-create-the-database-model-appdbmodels }

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

`TimestampMixin` aporta `created_at` y `updated_at`, así que aquí no se declara
ninguno de los dos. `__repr__` no es opcional — todos los modelos de esta base de
código tienen uno. Importa el modelo en `app/db/models/__init__.py` o Alembic no
lo verá.

### 3. Crea el repositorio (`app/repositories/`) { #3-create-the-repository-apprepositories }

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

!!! warning "Una lista paginada necesita un recuento de verdad, no `len(items)`"

    El `total` de un `*List` es cuántas filas **coinciden**, que es contra lo que
    pagina un cliente. `len(items)` es cuántas han vuelto — iguales solo hasta que
    se llena la primera página, y a partir de ahí silenciosamente equivocado en la
    dirección que oculta filas.

!!! danger "`flush()` + `refresh()`, nunca `commit()`"

    La sesión de la petición hace commit una sola vez, después de que la ruta
    devuelva y *antes* de que se escriba la respuesta — que es lo que hace que un
    2xx signifique que lo escrito se puede leer
    ([#353](https://github.com/vstorm-co/agenticos/issues/353)). Un repositorio
    que hace commit le quita ese orden al único sitio al que pertenece.

Un repositorio es un **módulo de funciones sin estado**, no una clase: `db`
primero, todo lo demás solo por palabra clave, y la entidad devuelta en lugar de
un id o un dict. Vuelve a exportarlo desde `app/repositories/__init__.py` igual
que todos los demás —
`from app.repositories import notification as notification_repo` — para que quien
lo llame importe el alias y no la ruta del módulo.

### 4. Crea el servicio (`app/services/`) { #4-create-the-service-appservices }

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

El servicio guarda la sesión y nada más; los repositorios se importan como
módulos. Es además la **única** capa que lanza una excepción de dominio, y
`details` lleva el valor en lugar de una cadena con él — el handler lo codifica
con `jsonable_encoder`.

### 5. Registra la dependencia (`app/api/deps.py`) { #5-register-the-dependency-appapidepspy }

```python
from app.services.notification import NotificationService


def get_notification_service(db: DBSession) -> NotificationService:
    return NotificationService(db)


NotificationSvc = Annotated[NotificationService, Depends(get_notification_service)]
```

### 6. Crea la ruta (`app/api/routes/v1/`) { #6-create-the-route-appapiroutesv1 }

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

!!! note "`-> Any`, por convención aquí"

    `response_model` es lo que serializa y valida la respuesta, y todas las rutas
    de esta base de código dejan la anotación en `Any` para que haya una sola
    respuesta a "dónde se declara la forma de la respuesta" en vez de dos que
    puedan contradecirse. Síguelo por coherencia con el código que lo rodea — no
    porque una anotación fuese a costar una segunda pasada de validación, que no
    lo hace.

Todo lo que está acotado a una organización toma un permiso del catálogo en la
ruta de **colección** — `dependencies=[Depends(require(Perm.X))]` —, mientras que
una ruta por recurso entrega la decisión a un servicio que llama a
`resolve_access`. Consulta [Permisos](../permissions.md).

### 7. Registra el router { #7-register-the-router }

En `app/api/routes/v1/__init__.py`:

```python
from app.api.routes.v1 import notifications

v1_router.include_router(
    notifications.router, prefix="/notifications", tags=["notifications"]
)
```

### 8. Crea y aplica la migración { #8-create-and-apply-the-migration }

```bash
make db-migrate    # message: "Add notifications table"
make db-upgrade
make db-check      # a model change with no migration fails here, and in `make check`
```

### 9. Pruébala { #9-test-it }

Una ruta se entrega con tests, no después de ellos: uno que compruebe que su
puerta está conectada (`tests/api/`), uno por rama del servicio incluido el
rechazo, y un test de integración si lo que has cambiado de verdad es una
restricción o una cascada. Después, `http://localhost:8000/docs` para probarla a
mano.
