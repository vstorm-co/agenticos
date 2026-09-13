---
source_sha: 141e97d23d12
---

# Wzorce w kodzie { #code-patterns }

Kształty, które powtarzają się w tym kodzie. Jeśli zmiana, którą piszesz, nie
wygląda jak żaden z nich, warto przyjrzeć się jej drugi raz, zanim uznasz, że
zasługuje na nowy wzorzec.

## Wstrzykiwanie zależności { #dependency-injection }

Wszystko, czego potrzebuje route, przychodzi jako alias `Annotated` z
`app/api/deps.py` - nigdy jako gołe `Depends()` w sygnaturze:

```python
from app.api.deps import ConversationSvc, CurrentUser


@router.get("", response_model=ConversationList)
async def list_conversations(service: ConversationSvc, user: CurrentUser) -> Any:
    items, total = await service.list(user_id=user.id)
    return ConversationList(items=items, total=total)
```

!!! important "Route nigdy nie zawiera bezpośrednich wywołań bazy danych"

    Cały dostęp do danych idzie przez serwis, który z kolei deleguje do
    repozytorium. Route waliduje, deleguje i zwraca.

Aliasy, które warto znać — wszystkie w `app/api/deps.py`:

| Alias | |
|---|---|
| `DBSession` | Sesja żądania. `scope="function"`, czyli to, co commituje przed zapisaniem odpowiedzi |
| `StreamingDBSession` | Ta sama sesja ze `scope="request"`, dla route'u, który streamuje swoje body |
| `CurrentUser` | Uwierzytelniony użytkownik; 401 bez niego |
| `CurrentAppAdmin` | Superadmin deploymentu |
| `Auth` | `AuthContext`: wywołujący, organizacja, zbiór uprawnień |
| `Redis` | Klient Redis |
| `<Domain>Svc` | Po jednym na serwis, budowany z `DBSession` |

## Wzorzec warstwy serwisowej { #service-layer-pattern }

Każda funkcjonalność korzysta z tego samego wzorca: klasa serwisu dostaje sesję
DB i udostępnia metody na poziomie biznesowym. Serwisy są **jedyną** warstwą,
która rzuca wyjątki domenowe.

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

Sprawdzenie tenanta rzuca **tę samą odmowę** co brakujący wiersz: „nie możesz
tego przeczytać” mówi komuś z innej organizacji, że dane id istnieje.

Serwis trzyma sesję i nic poza tym - repozytoria są importowane jako moduły, a
nie tworzone jako obiekty, więc nie ma grafu obiektów per żądanie, który trzeba
by utrzymywać spójnym. Tam, gdzie domena ma własną infrastrukturę (klienty,
adaptery, parsery), serwis staje się podpakietem eksportującym jedną fasadę:
`services/rag/`, `services/channels/`, `services/email/`.

## Wzorzec warstwy repozytoriów { #repository-layer-pattern }

Repozytoria zajmują się wyłącznie dostępem do danych. **Nie** zawierają logiki
biznesowej i zawsze używają `flush()` zamiast `commit()`, ponieważ sesja żądania
jest właścicielem transakcji i commituje ją raz — po zwróceniu przez route i
*przed* zapisaniem odpowiedzi, co sprawia, że 2xx oznacza, iż zapis jest do
odczytania. Zobacz
[transakcję żądania](architecture.md#the-requests-transaction).

Repozytorium to **moduł bezstanowych funkcji**, nie klasa - `db` pierwsze, a
wszystko po nim tylko jako argumenty nazwane:

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

Dwie rzeczy o tej sygnaturze. `organization_id` nigdzie w tym module nie ma
wartości domyślnej, i to celowo: każda konwersacja należy do tenanta, a
wywołujący, który nie potrafi go wskazać, ma błąd, a nie wartość domyślną. Oraz:
argument zawężający, który jest przyjmowany, musi zostać **zastosowany** —
zapytanie, które przyjmuje `user_id`, a filtruje tylko po tenancie, odpowiada
konwersacjami wszystkich członków. (Prawdziwy moduł rozszerza predykat
użytkownika na potwierdzonych uczestników kanału przez `_reachable_by`, po id,
które wywołujący już zweryfikował wobec platformy; tutaj liczy się to, że
argument w ogóle dociera do klauzuli `WHERE`.)

!!! danger "`flush()`, nigdy `commit()`"

    Sesja żądania commituje raz. Jedynym usankcjonowanym wyjątkiem jest ścieżka
    runa agenta, która commituje przed wywołaniem modelu i jeszcze raz w swoim
    końcowym `finally`.

## Obsługa wyjątków { #exception-handling }

W serwisach używaj wyjątków domenowych:

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

Handlery wyjątków zamieniają je na odpowiedzi HTTP automatycznie, a `details`
jest kodowane przez `jsonable_encoder` - ten sam encoder, którego używa
`response_model` - więc rzucający przekazuje wartość, którą ma, a nie jej postać
tekstową. `UUID` dociera w swojej formie tekstowej, `datetime` w ISO 8601, `Enum`
jako swoja wartość. Pieniądze to wyjątek, o którym warto wiedzieć: `Decimal`
koduje się do float, więc koszt albo limit jest zamieniany na tekst przez kod,
który rzuca.

!!! warning "Odmowa opisuje odmowę, a nie serwer"

    Wszystko w `details` czyta ten, komu odmówiono, więc nazywa pole, id albo
    zasób, na który może on zadziałać - nigdy ścieżkę w systemie plików, tekst
    wyjątku z klienta zewnętrznego ani ustawienie opisujące deployment.
    Diagnostyka nie znika; przenosi się do linii logu obok rzucenia.

`max_mb` i `seats_limit` to dokładnie to, na co wywołujący może zadziałać; to,
gdzie kontener trzyma swoje szablony, już nie. Ścieżka, którą przeszukał loader,
i komunikat z SDK dostawcy trafiają do linii logu obok rzucenia, gdzie czyta je
operator, a wywołujący nie.

```python
except Exception as exc:
    logger.exception("Knowledge base search failed")   # the upstream text stays here
    raise ExternalServiceError(
        message="Knowledge base search failed",
        details={"collections": names, "operation": "retrieve"},
    ) from exc
```

`message` trzymany jest przy tej samej poprzeczce - koperta go niesie, a handler
loguje go w tej samej linii, więc zdanie nazywające endpoint wycieka to, za co
pole zostało odrzucone. URL, którego odmowa *dotyczy*, nazywany jest przez swoje
pole: `refused_field("base_url", ...)`, nigdy endpoint z hasłem wciąż w środku.
Ten helper jest w `app/core/field_errors.py`, który jest jedynym miejscem, gdzie
budowane jest `details["fields"]` — to po nim formularz oznacza input. Zobacz
[Architekturę](architecture.md#a-refusal-that-names-a-field), gdzie są trzy
punkty wejścia oraz to, które odmowy celowo nie nazywają żadnego pola.

To samo dotyczy wpisu audytowego, który jest `details` o dłuższym życiu: zapisuj
*które* pola administrator zmienił, a nie wartości, które przesłał.

## Wzorce schematów { #schema-patterns }

Osobne schematy dla różnych operacji:

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

### Aktualizacja zapisywana jest przez `writable`, nigdy przez dump { #an-update-is-written-through-writable-never-dumped }

W `*Update` każde pole jest `X | None`, bo `None` znaczy *nie podano* — a
`model_dump(exclude_unset=True)` zachowuje pole **jawnie ustawione na `None`**,
bo właśnie o to pyta `exclude_unset`. Więc klient wysyłający `{"name": null}`
przepycha swoje `None` przez dump, do `setattr` i na kolumnę `NOT NULL`: 500
nazywające ograniczenie bazy danych, dla żądania, które według własnych typów API
jest legalne.

```python
from app.db.updates import writable

changes = writable(data, over=AgentEmbed)      # not data.model_dump(exclude_unset=True)
```

**Decyduje kolumna.** `writable` odczytuje nullowalność z modelu, więc schemat,
który zyskuje opcjonalne pole, jest pokryty tego samego dnia — podczas gdy ręcznie
utrzymywana lista nazw pól per serwis to nowa awaria przy następnym dodaniu pola.
Przed #637 istniały dwadzieścia cztery takie pary w jedenastu schematach.

`null`, na które kolumna *pozwala*, jest zachowywane, i to odróżnia to od
`exclude_none`: wyczyszczenie nullowalnej kolumny to uprawnione żądanie, a
odrzucanie każdego nulla sprawiłoby, że „usuń opis” po cichu nie robiłoby nic.
Tam, gdzie pole ma wartość domyślną wartą przywrócenia, serwis podstawia ją przed
wywołaniem — `EmbedUpdate.config` przywraca domyślne wartości danego rodzaju,
zamiast usuwać klucz.

`tests/test_update_nulls.py` jest tym, co utrzymuje to w mocy: każdy schemat
`*Update` jest zadeklarowany wobec wiersza, który zapisuje, i żaden serwis nie
może sam go zdumpować.

## Przekazywanie pracy w tło { #handing-work-to-the-background }

Dwa prymitywy, w `app/core/background.py`, a wybór między nimi dotyczy tego, co
ta praca czyta, a nie tego, jak długo trwa:

```python
from app.core.background import spawn, spawn_after_commit

# Owns everything it needs - a rendered email, an id it will not look up.
spawn(deliver(key, to, context), name=f"email:{key}:{to}")

# Reads a row this unit of work wrote. Starts when the session commits.
spawn_after_commit(self.db, ingest_document_flow(rag_document_id=str(doc.id)), name=...)
```

Oba trzymają silną referencję do zadania i logują wszystko, co ono rzuci, czego
gołe `asyncio.create_task` nie robi ani razu. `spawn_after_commit` dodatkowo
kolejkuje korutynę na sesji, więc nic się nie zaczyna, dopóki transakcja, od
której ta praca zależy, nie wyląduje — flow czytający własny wiersz po id inaczej
uruchomiłby się na bazie, która go jeszcze nie ma
([#417](https://github.com/vstorm-co/agenticos/issues/417)). Żaden z nich nie
przeżywa restartu; praca, która musi, należy do deploymentu Prefect.

## Wzorzec konektora (synchronizacja RAG) { #connector-pattern-rag-sync }

Zdalne źródła dokumentów (Google Drive, S3 itd.) korzystają z wtyczkowego wzorca
konektora zdefiniowanego w `app/services/rag/connectors/`. Każdy konektor
dziedziczy po `BaseSyncConnector` i jest rejestrowany w słowniku
`CONNECTOR_REGISTRY`.

### Dodawanie nowego konektora { #adding-a-new-connector }

1. Utwórz plik w `app/services/rag/connectors/` (np. `sharepoint.py`).
2. Odziedzicz po `BaseSyncConnector` i zaimplementuj wymagane metody.
3. Zarejestruj konektor w `CONNECTOR_REGISTRY`.

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

`RagSyncService` używa `CONNECTOR_REGISTRY`, żeby odnaleźć właściwy konektor po
typie, zwalidować jego konfigurację, wylistować zdalne pliki, pobrać je i
przekazać do pipeline'u ingestii.

## Wzorce frontendowe { #frontend-patterns }

### Uwierzytelnianie (ciasteczka HTTP-only) { #authentication-http-only-cookies }

```typescript
import { useAuth } from '@/hooks/use-auth';

function Component() {
    const { user, isAuthenticated, login, logout } = useAuth();
}
```

### Zarządzanie stanem (Zustand) { #state-management-zustand }

```typescript
import { useAuthStore } from '@/stores/auth-store';

const { user, setUser, logout } = useAuthStore();
```

### Czat po WebSocket { #websocket-chat }

```typescript
import { useChat } from '@/hooks/use-chat';

function ChatPage() {
    const { messages, sendMessage, isStreaming } = useChat();
}
```
