---
source_sha: 141e97d23d12
---

# Patrones de código { #code-patterns }

Las formas que se repiten en este código. Si un cambio que estás escribiendo no
se parece a ninguna de ellas, eso merece una segunda mirada antes que un patrón
nuevo.

## Inyección de dependencias { #dependency-injection }

Todo lo que necesita una ruta llega como un alias `Annotated` desde
`app/api/deps.py` - nunca un `Depends()` pelado en la firma:

```python
from app.api.deps import ConversationSvc, CurrentUser


@router.get("", response_model=ConversationList)
async def list_conversations(service: ConversationSvc, user: CurrentUser) -> Any:
    items, total = await service.list(user_id=user.id)
    return ConversationList(items=items, total=total)
```

!!! important "Las rutas nunca contienen llamadas directas a la base de datos"

    Todo el acceso a datos pasa por un servicio, que a su vez delega en un
    repositorio. Una ruta valida, delega y devuelve.

Los alias que conviene conocer, todos en `app/api/deps.py`:

| Alias | |
|---|---|
| `DBSession` | La sesión de la petición. `scope="function"`, que es lo que hace el commit antes de que se escriba la respuesta |
| `StreamingDBSession` | La misma sesión con `scope="request"`, para una ruta que transmite su cuerpo en streaming |
| `CurrentUser` | Un usuario autenticado; 401 si no lo hay |
| `CurrentAppAdmin` | El superadmin del despliegue |
| `Auth` | El `AuthContext`: quien llama, la organización, el conjunto de permisos |
| `Redis` | El cliente de Redis |
| `<Domain>Svc` | Uno por servicio, construido a partir de `DBSession` |

## El patrón de la capa de servicios { #service-layer-pattern }

Cada funcionalidad usa el mismo patrón: una clase de servicio recibe una sesión
de base de datos y ofrece métodos de nivel de negocio. Los servicios son la
**única** capa que lanza excepciones de dominio.

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

La comprobación de inquilino lanza **el mismo rechazo** que una fila que no
existe: «no puedes leer esto» le dice a alguien de otra organización que el id
existe.

Un servicio guarda la sesión y nada más - los repositorios se importan como
módulos en vez de instanciarse, así que no hay un grafo de objetos por petición
que mantener coherente. Donde un dominio es dueño de infraestructura propia
(clientes, adaptadores, parsers) el servicio pasa a ser un subpaquete que exporta
una única fachada: `services/rag/`, `services/channels/`, `services/email/`.

## El patrón de la capa de repositorios { #repository-layer-pattern }

Los repositorios se ocupan solo del acceso a datos. **No** contienen lógica de
negocio y siempre usan `flush()` en vez de `commit()`, porque la transacción es
de la sesión de la petición y esta hace el commit una sola vez — después de que
la ruta devuelva y *antes* de que se escriba la respuesta, que es lo que hace que
un 2xx signifique que la escritura es legible. Ver
[la transacción de la petición](architecture.md#the-requests-transaction).

Un repositorio es un **módulo de funciones sin estado**, no una clase - `db`
primero, y todo lo que va detrás solo por nombre:

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

Dos cosas sobre esa firma. `organization_id` no tiene valor por defecto en ese
módulo, a propósito: cada conversación pertenece a un inquilino, y quien llama
sin poder nombrar uno tiene un bug, no un valor por defecto. Y un argumento que
estrecha y que se acepta tiene que **aplicarse** — una consulta que toma
`user_id` y filtra solo por el inquilino responde con las conversaciones de todos
los miembros. (El módulo real amplía el predicado de usuario a los participantes
confirmados del canal a través de `_reachable_by`, sobre ids que quien llama ya
ha contrastado con la plataforma; lo que importa aquí es que el argumento llegue
a la cláusula `WHERE`.)

!!! danger "`flush()`, nunca `commit()`"

    La sesión de la petición hace el commit una vez. La única excepción
    autorizada es el camino de ejecución del agent, que hace commit antes de la
    llamada al modelo y otra vez en su `finally` terminal.

## Manejo de excepciones { #exception-handling }

Usa excepciones de dominio en los servicios:

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

Los manejadores de excepciones las convierten en respuestas HTTP
automáticamente, y `details` se codifica con `jsonable_encoder` - el mismo
codificador que usa `response_model` - así que quien lanza pasa el valor que
tiene y no una cadena de él. Un `UUID` llega en su forma de cadena, un `datetime`
en ISO 8601, un `Enum` como su valor. El dinero es la excepción que conviene
conocer: un `Decimal` se codifica como float, así que un coste o un tope los
convierte a cadena el código que lanza.

!!! warning "Un rechazo describe el rechazo, no el servidor"

    Todo lo que hay en `details` lo lee quien ha sido rechazado, así que nombra
    el campo, el id o el recurso sobre el que puede actuar - nunca una ruta del
    sistema de archivos, el texto de excepción de un cliente externo, ni un
    ajuste que describa el despliegue. El diagnóstico no se borra: se mueve a la
    línea de log que hay junto al raise.

`max_mb` y `seats_limit` son exactamente aquello sobre lo que quien llama puede
actuar; dónde guarda el contenedor sus plantillas no lo es. La ruta que buscó el
cargador y el mensaje del SDK del proveedor van en la línea de log junto al
raise, donde los lee un operador y no quien llama.

```python
except Exception as exc:
    logger.exception("Knowledge base search failed")   # the upstream text stays here
    raise ExternalServiceError(
        message="Knowledge base search failed",
        details={"collections": names, "operation": "retrieve"},
    ) from exc
```

`message` se somete al mismo listón - el sobre lo lleva y el manejador lo
registra en la misma línea, así que una frase que nombre el endpoint filtra justo
aquello por lo que se rechazó el campo. Una URL *sobre la que* va el rechazo se
nombra por su campo: `refused_field("base_url", ...)`, nunca el endpoint con la
contraseña todavía dentro. Ese ayudante está en `app/core/field_errors.py`, que
es el único sitio donde se construye el `details["fields"]` con el que un
formulario marca un input - ver
[Arquitectura](architecture.md#a-refusal-that-names-a-field) para los tres puntos
de entrada y para qué rechazos deliberadamente no nombran ningún campo.

Lo mismo vale para una entrada de auditoría, que es `details` con una vida más
larga: registra *qué* campos cambió un administrador, no los valores que envió.

## Patrones de esquemas { #schema-patterns }

Esquemas separados para operaciones distintas:

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

### Una actualización se escribe con `writable`, nunca se vuelca { #an-update-is-written-through-writable-never-dumped }

En un `*Update` cada campo es `X | None` porque `None` significa *no
proporcionado* — y `model_dump(exclude_unset=True)` conserva un campo que se puso
**explícitamente a `None`**, porque ponerlo es justo lo que `exclude_unset`
pregunta. Así que un cliente que envía `{"name": null}` cuela su `None` a través
del volcado, hasta `setattr`, y hasta una columna `NOT NULL`: un 500 que nombra
una restricción de la base de datos, para una petición que los propios tipos de
la API dicen que es legal.

```python
from app.db.updates import writable

changes = writable(data, over=AgentEmbed)      # not data.model_dump(exclude_unset=True)
```

**Decide la columna.** `writable` lee del modelo si admite nulos, así que un
esquema que gana un campo opcional queda cubierto el mismo día que lo gana —
mientras que una lista de nombres de campo mantenida a mano por servicio es un
fallo nuevo la próxima vez que alguien añada uno. Antes de #637 había
veinticuatro parejas así repartidas por once esquemas.

Un `null` que una columna *permite* se conserva, que es lo que diferencia esto de
`exclude_none`: vaciar una columna que admite nulos es una petición legítima, y
descartar todos los nulos haría que «quita la descripción» no hiciera nada en
silencio. Donde un campo tiene un valor por defecto al que merece la pena volver,
el servicio lo sustituye antes de llamar — `EmbedUpdate.config` restaura los
valores por defecto del kind en vez de descartar la clave.

`tests/test_update_nulls.py` es lo que mantiene esto cierto: cada esquema
`*Update` se declara contra la fila que escribe, y ningún servicio puede volcar
uno por su cuenta.

## Pasar trabajo al segundo plano { #handing-work-to-the-background }

Dos primitivas, en `app/core/background.py`, y la elección entre ellas va de lo
que lee el trabajo y no de lo que tarda:

```python
from app.core.background import spawn, spawn_after_commit

# Owns everything it needs - a rendered email, an id it will not look up.
spawn(deliver(key, to, context), name=f"email:{key}:{to}")

# Reads a row this unit of work wrote. Starts when the session commits.
spawn_after_commit(self.db, ingest_document_flow(rag_document_id=str(doc.id)), name=...)
```

Las dos mantienen una referencia fuerte a la tarea y registran lo que esta lance,
cosa que un `asyncio.create_task` pelado no hace en ninguno de los dos casos.
`spawn_after_commit` además encola la corrutina en la sesión, así que no empieza
nada hasta que haya aterrizado la transacción de la que depende el trabajo — un
flow que lee su propia fila por id se ejecutaría si no contra una base de datos
que todavía no la tiene
([#417](https://github.com/vstorm-co/agenticos/issues/417)). Ninguna de las dos
sobrevive a un reinicio; el trabajo que deba hacerlo pertenece a un deployment de
Prefect.

## El patrón de conector (sincronización RAG) { #connector-pattern-rag-sync }

Las fuentes remotas de documentos (Google Drive, S3, etc.) usan un patrón de
conector enchufable definido en `app/services/rag/connectors/`. Cada conector
hereda de `BaseSyncConnector` y se registra en el diccionario
`CONNECTOR_REGISTRY`.

### Añadir un conector nuevo { #adding-a-new-connector }

1. Crea un archivo en `app/services/rag/connectors/` (por ejemplo,
   `sharepoint.py`).
2. Hereda de `BaseSyncConnector` e implementa los métodos requeridos.
3. Registra el conector en `CONNECTOR_REGISTRY`.

```python
from pathlib import Path

from pydantic import BaseModel, Field

from app.core.secret_kinds import SecretKind, StorableSecret
from app.services.rag.connectors import (
    CONNECTOR_REGISTRY,
    BaseSyncConnector,
    ConnectorConfig,
    RemoteFile,
)

class SharePointConfig(BaseModel):
    # No default, so the one required field; the wizard draws it from the
    # model's JSON Schema and a refusal names its title.
    site_url: str = Field(title="Site URL")

class SharePointConnector(BaseSyncConnector):
    CONNECTOR_TYPE = "sharepoint"
    DISPLAY_NAME = "SharePoint"
    # What authenticates it. The credential is a vault secret the source names,
    # unsealed by the caller - never a field of CONFIG_MODEL.
    SECRET_KIND = SecretKind.API_KEY
    CONFIG_MODEL = SharePointConfig

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

El `RagSyncService` usa `CONNECTOR_REGISTRY` para buscar el conector adecuado por
tipo, validar su configuración, listar los archivos remotos, descargarlos y
entregárselos a la pipeline de ingesta.

## Patrones del frontend { #frontend-patterns }

### Autenticación (cookies HTTP-only) { #authentication-http-only-cookies }

```typescript
import { useAuth } from '@/hooks/use-auth';

function Component() {
    const { user, isAuthenticated, login, logout } = useAuth();
}
```

### Gestión del estado (Zustand) { #state-management-zustand }

```typescript
import { useAuthStore } from '@/stores/auth-store';

const { user, setUser, logout } = useAuthStore();
```

### Chat por WebSocket { #websocket-chat }

```typescript
import { useChat } from '@/hooks/use-chat';

function ChatPage() {
    const { messages, sendMessage, isStreaming } = useChat();
}
```
