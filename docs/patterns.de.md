---
source_sha: 141e97d23d12
---

# Code-Patterns { #code-patterns }

Die Formen, die sich in dieser Codebasis wiederholen. Wenn eine Änderung, die Sie
schreiben, keiner davon ähnelt, ist das einen zweiten Blick wert, bevor es ein
neues Pattern wert ist.

## Dependency Injection { #dependency-injection }

Alles, was eine Route braucht, kommt als `Annotated`-Alias aus `app/api/deps.py` -
niemals als bloßes `Depends()` in der Signatur:

```python
from app.api.deps import ConversationSvc, CurrentUser


@router.get("", response_model=ConversationList)
async def list_conversations(service: ConversationSvc, user: CurrentUser) -> Any:
    items, total = await service.list(user_id=user.id)
    return ConversationList(items=items, total=total)
```

!!! important "Routen enthalten niemals direkte Datenbankaufrufe"

    Jeder Datenzugriff läuft über einen Service, der seinerseits an ein Repository
    delegiert. Eine Route validiert, delegiert und gibt zurück.

Die Aliase, die man kennen sollte, alle in `app/api/deps.py`:

| Alias | |
|---|---|
| `DBSession` | Die Session der Anfrage. `scope="function"`, und genau das committet, bevor die Antwort geschrieben wird |
| `StreamingDBSession` | Dieselbe Session mit `scope="request"`, für eine Route, die ihren Body streamt |
| `CurrentUser` | Ein authentifizierter Nutzer; ohne einen 401 |
| `CurrentAppAdmin` | Der Superadmin des Deployments |
| `Auth` | Der `AuthContext`: der Aufrufer, die Organisation, die Berechtigungsmenge |
| `Redis` | Der Redis-Client |
| `<Domain>Svc` | Einer pro Service, aus `DBSession` gebaut |

## Service-Layer-Pattern { #service-layer-pattern }

Jedes Feature nutzt dasselbe Pattern: eine Service-Klasse bekommt eine DB-Session
und stellt Methoden auf Fachebene bereit. Services sind die **einzige** Schicht,
die Domain-Exceptions wirft.

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

Die Mandantenprüfung wirft **dieselbe Ablehnung** wie eine fehlende Zeile: "das
dürfen Sie nicht lesen" verrät jemandem in einer anderen Organisation, dass die Id
existiert.

Ein Service hält die Session und sonst nichts - Repositories werden als Module
importiert statt instanziiert, es gibt also keinen Objektgraphen pro Anfrage, den
man konsistent halten müsste. Wo eine Domäne eigene Infrastruktur besitzt
(Clients, Adapter, Parser), wird der Service zu einem Subpaket, das eine Fassade
exportiert: `services/rag/`, `services/channels/`, `services/email/`.

## Repository-Layer-Pattern { #repository-layer-pattern }

Repositories kümmern sich ausschließlich um Datenzugriff. Sie enthalten **keine**
Geschäftslogik und verwenden immer `flush()` statt `commit()`, denn die Session
der Anfrage besitzt die Transaktion und committet sie einmal — nachdem die Route
zurückgekehrt ist und *bevor* die Antwort geschrieben wird, was eine 2xx
bedeuten lässt, dass der Schreibvorgang lesbar ist. Siehe
[die Transaktion der Anfrage](architecture.md#the-requests-transaction).

Ein Repository ist ein **Modul zustandsloser Funktionen**, keine Klasse - `db`
zuerst, alles danach nur als Schlüsselwortargument:

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

Zwei Dinge zu dieser Signatur. `organization_id` hat in diesem Modul nirgends
einen Standardwert, und das mit Absicht: jede Unterhaltung gehört zu einem
Mandanten, und ein Aufrufer, der keinen benennen kann, hat einen Fehler statt
eines Standardwerts. Und ein einschränkendes Argument, das entgegengenommen wird,
muss auch **angewendet** werden — eine Abfrage, die `user_id` nimmt und nur auf
den Mandanten filtert, antwortet mit den Unterhaltungen jedes Mitglieds. (Das
echte Modul weitet das Nutzer-Prädikat über `_reachable_by` auf bestätigte
Kanalteilnehmer aus, über Ids, die der Aufrufer bereits gegen die Plattform
geprüft hat; worauf es hier ankommt, ist, dass das Argument die `WHERE`-Klausel
überhaupt erreicht.)

!!! danger "`flush()`, niemals `commit()`"

    Die Session der Anfrage committet einmal. Die eine erlaubte Ausnahme ist der
    Agent-Run-Pfad, der vor dem Modellaufruf committet und erneut in seinem
    abschließenden `finally`.

## Exception-Handling { #exception-handling }

Verwenden Sie in Services Domain-Exceptions:

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

Exception-Handler wandeln das automatisch in HTTP-Antworten um, und `details` wird
mit `jsonable_encoder` kodiert - demselben Encoder, den auch `response_model`
verwendet -, der Werfende übergibt also den Wert, den er hat, und keine
Zeichenkette davon. Eine `UUID` kommt in ihrer Zeichenkettenform an, ein
`datetime` in ISO 8601, ein `Enum` als sein Wert. Geld ist die Ausnahme, die man
kennen sollte: ein `Decimal` kodiert zu einem Float, Kosten oder eine Obergrenze
werden deshalb von dem Code, der wirft, in eine Zeichenkette verwandelt.

!!! warning "Eine Ablehnung beschreibt die Ablehnung, nicht den Server"

    Alles in `details` wird von demjenigen gelesen, der abgelehnt wurde, es benennt
    also das Feld, die Id oder die Ressource, auf die er einwirken kann - niemals
    einen Dateisystempfad, den Exception-Text eines vorgelagerten Clients oder eine
    Einstellung, die das Deployment beschreibt. Die Diagnose wird nicht gelöscht; sie
    wandert in die Logzeile neben dem Werfen.

`max_mb` und `seats_limit` sind genau das, worauf ein Aufrufer einwirken kann; wo
der Container seine Templates aufbewahrt, ist es nicht. Der Pfad, den der Loader
durchsucht hat, und die Meldung des Anbieter-SDK gehören in die Logzeile neben das
Werfen, wo ein Betreiber sie liest und ein Aufrufer nicht.

```python
except Exception as exc:
    logger.exception("Knowledge base search failed")   # the upstream text stays here
    raise ExternalServiceError(
        message="Knowledge base search failed",
        details={"collections": names, "operation": "retrieve"},
    ) from exc
```

`message` wird an derselben Messlatte gemessen - der Umschlag trägt es und der
Handler loggt es in derselben Zeile, ein Satz, der den Endpunkt benennt, gibt also
preis, wofür das Feld abgelehnt wurde. Eine URL, um die es bei der Ablehnung
*geht*, wird über ihr Feld benannt: `refused_field("base_url", ...)`, niemals der
Endpunkt mit noch enthaltenem Passwort. Dieser Helfer liegt in
`app/core/field_errors.py`, dem einzigen Ort, an dem die `details["fields"]`
gebaut werden, anhand derer ein Formular eine Eingabe markiert - siehe
[Architektur](architecture.md#a-refusal-that-names-a-field) für die drei
Einstiegspunkte und dafür, welche Ablehnungen bewusst überhaupt kein Feld
benennen.

Dasselbe gilt für einen Audit-Eintrag, der `details` mit längerer Lebensdauer ist:
halten Sie fest, *welche* Felder eine Administratorin geändert hat, nicht die
Werte, die sie übermittelt hat.

## Schema-Patterns { #schema-patterns }

Getrennte Schemas für verschiedene Operationen:

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

### Ein Update wird über `writable` geschrieben, nie gedumpt { #an-update-is-written-through-writable-never-dumped }

In einem `*Update` ist jedes Feld `X | None`, weil `None` *nicht angegeben*
bedeutet — und `model_dump(exclude_unset=True)` behält ein Feld, das
**ausdrücklich auf `None` gesetzt** wurde, denn genau das Setzen ist es, wonach
`exclude_unset` fragt. Ein Client, der `{"name": null}` sendet, bringt sein `None`
also durch den Dump, in `setattr` hinein und auf eine `NOT NULL`-Spalte: eine 500,
die eine Datenbank-Constraint benennt, für eine Anfrage, die die Typen der API
selbst als zulässig bezeichnen.

```python
from app.db.updates import writable

changes = writable(data, over=AgentEmbed)      # not data.model_dump(exclude_unset=True)
```

**Die Spalte entscheidet.** `writable` liest die Nullbarkeit am Modell ab, ein
Schema, das ein optionales Feld hinzubekommt, ist also an dem Tag abgedeckt, an
dem es eines bekommt — wo eine von Hand gepflegte Liste von Feldnamen pro Service
ein neuer Absturz ist, sobald jemand das nächste Mal eines hinzufügt.
Vierundzwanzig solcher Paare gab es vor #637 über elf Schemas verteilt.

Ein `null`, das eine Spalte *zulässt*, wird behalten, und genau das unterscheidet
dies von `exclude_none`: eine nullbare Spalte zu leeren ist eine legitime Anfrage,
und jedes Null zu verwerfen würde "entferne die Beschreibung" stillschweigend
wirkungslos machen. Wo ein Feld einen Standardwert hat, zu dem zurückzukehren sich
lohnt, setzt der Service ihn vor dem Aufruf ein — `EmbedUpdate.config` stellt die
Standardwerte der Art wieder her, statt den Schlüssel zu verwerfen.

`tests/test_update_nulls.py` ist das, was das aufrechterhält: jedes
`*Update`-Schema wird gegen die Zeile deklariert, die es schreibt, und kein
Service darf eines selbst dumpen.

## Arbeit in den Hintergrund übergeben { #handing-work-to-the-background }

Zwei Primitive, in `app/core/background.py`, und die Wahl zwischen ihnen hängt
davon ab, was die Arbeit liest, und nicht davon, wie lange sie dauert:

```python
from app.core.background import spawn, spawn_after_commit

# Owns everything it needs - a rendered email, an id it will not look up.
spawn(deliver(key, to, context), name=f"email:{key}:{to}")

# Reads a row this unit of work wrote. Starts when the session commits.
spawn_after_commit(self.db, ingest_document_flow(rag_document_id=str(doc.id)), name=...)
```

Beide halten eine starke Referenz auf den Task und loggen, was immer er wirft, was
ein bloßes `asyncio.create_task` beides nicht tut. `spawn_after_commit` reiht die
Coroutine zusätzlich an der Session ein, sodass nichts startet, bevor die
Transaktion, von der die Arbeit abhängt, gelandet ist — ein Flow, der seine eigene
Zeile per Id liest, liefe sonst gegen eine Datenbank, die sie noch nicht hat
([#417](https://github.com/vstorm-co/agenticos/issues/417)). Keines von beiden
überlebt einen Neustart; Arbeit, die das muss, gehört in ein Prefect-Deployment.

## Connector-Pattern (RAG-Sync) { #connector-pattern-rag-sync }

Entfernte Dokumentquellen (Google Drive, S3 usw.) nutzen ein einsteckbares
Connector-Pattern, definiert in `app/services/rag/connectors/`. Jeder Connector
erbt von `BaseSyncConnector` und wird im Dictionary `CONNECTOR_REGISTRY`
registriert.

### Einen neuen Connector hinzufügen { #adding-a-new-connector }

1. Legen Sie eine Datei in `app/services/rag/connectors/` an (z. B.
   `sharepoint.py`).
2. Leiten Sie von `BaseSyncConnector` ab und implementieren Sie die verlangten
   Methoden.
3. Registrieren Sie den Connector in `CONNECTOR_REGISTRY`.

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

Der `RagSyncService` nutzt `CONNECTOR_REGISTRY`, um den richtigen Connector anhand
seines Typs nachzuschlagen, seine Konfiguration zu validieren, entfernte Dateien
aufzulisten, sie herunterzuladen und sie an die Ingestion-Pipeline zu übergeben.

## Frontend-Patterns { #frontend-patterns }

### Authentifizierung (HTTP-only-Cookies) { #authentication-http-only-cookies }

```typescript
import { useAuth } from '@/hooks/use-auth';

function Component() {
    const { user, isAuthenticated, login, logout } = useAuth();
}
```

### State-Verwaltung (Zustand) { #state-management-zustand }

```typescript
import { useAuthStore } from '@/stores/auth-store';

const { user, setUser, logout } = useAuthStore();
```

### WebSocket-Chat { #websocket-chat }

```typescript
import { useChat } from '@/hooks/use-chat';

function ChatPage() {
    const { messages, sendMessage, isStreaming } = useChat();
}
```
