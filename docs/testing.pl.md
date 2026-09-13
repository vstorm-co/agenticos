---
source_sha: dba14340bbd8
---

# Testowanie { #testing }

Cztery warstwy, jeden runner i bramka pokrycia, która wywala build poniżej 100% na
warstwie platformy.

Krótka wersja tego, co uruchamiać: w trakcie pisania te testy, które pokrywają
zmianę, a całe suity raz, przed pushem.

## Uruchamianie testów { #running-tests }

!!! tip "W trakcie pisania uruchamiaj to, co pokrywa zmianę; suita jest bramką przed pushem"

    Plik odpowiada w jakąś sekundę tam, gdzie suita zajmuje półtorej minuty, i mówi
    o zmianie to samo.

```bash
cd backend

uv run pytest tests/test_capability_registry.py -q         # one file
uv run pytest tests/test_capability_registry.py -k drift   # one behaviour
uv run pytest tests/api/test_workspace_routes.py -x -v     # stop at the first failure
uv run pytest tests/integration -v --no-cov                # the ones needing a database
```

Te zostają **szeregowe** celowo: rozstawianie procesów roboczych, żeby uruchomić
jeden plik, kosztuje więcej niż sam plik. Cele obejmujące całą suitę — `make test`,
`make test-fast`, `make test-integration`, `make test-cov` — działają na wielu
workerach (`pytest -n auto --maxprocesses 4`), co z grubsza połowi suitę
integracyjną, ograniczoną przez I/O; `pytest-cov` scala dane z poszczególnych
workerów, więc bramka 100% pozostaje bez zmian. Limit to cztery, bo suita
jednostkowa jest ograniczona importami — każdy worker importuje aplikację raz — i
powyżej tego nic nie zyskuje, a nieograniczone `auto` na wielordzeniowym laptopie
jest *wolniejsze* niż szeregowo, w całości przez startowanie workerów (#520).

!!! warning "Każdy przebieg jest tasowany, a test, który przeszedł wczoraj, mógł zależeć od kolejności"

    `pytest-randomly` wypisuje seed w nagłówku
    (`Using --randomly-seed=1697040112`). Odtwórz ten seed **szeregowo**, żeby
    odzyskać tę samą kolejność — `-n auto` nie ustala, który worker co uruchamia.

Test zależny od kolejności — taki, który przechodzi tylko dlatego, że coś przed nim
zostawiło stan — to klasyczne „zielone na moim laptopie, czerwone w CI”, a suita,
która zawsze idzie w kolejności zbierania, nigdy tego pytania nie zadaje. CI zadaje
je w świeżej kolejności przy każdym przebiegu.

```bash
uv run pytest tests/ -q --randomly-seed=1697040112   # that order again, serially
uv run pytest tests/ -q -p no:randomly               # collection order, while bisecting
```

Seed jest wybierany raz przez kontroler i przekazywany każdemu workerowi xdist, więc
`-n auto` zbiera jedną kolejność, a nie cztery. Nie ustala, który worker co
uruchamia: `make test` zostawia xdist na domyślnym `--dist load`, który oddaje każdy
test temu workerowi, który jest wolny. Więc awaria, która zależała od tego, co
dzieliło workera — `InterfaceError` znaleziony przez #571 jest jedną z nich —
wraca przez odtworzenie seeda *szeregowo*, jak wyżej, a nie przez ponowne
uruchomienie `make test`. Wtyczka przed każdym testem zasiewa też `random` tak samo,
więc cokolwiek używa go do unikalności, jest unikalne w obrębie testu i powtarza się
między testami.

Do #571 wtyczka była udokumentowana, ale nie zainstalowana, `-p no:randomly` było
cichym no-opem i nic nigdy nie sprawdziło tej obietnicy.

Raz, przed pushem — `make check` uruchamia to wszystko, w tej kolejności:

```bash
make lint               # ruff, ruff format, ty, vulture, deptry, eslint, prettier, tsc, the guards
make test               # the suite plus the 100% gate on the platform layer
make db-check           # alembic check — a model change with no migration fails here
make test-frontend-cov  # the frontend suite plus its own gate
make build-frontend     # next build — the route tree, which tsc and vitest do not see
make docs-build         # mkdocs --strict — a dead link is a failure
make audit              # the locked dependency set against the advisory database
```

Jakieś pięć minut szeregowo, wobec dwunastu w CI równolegle — gdzie zadanie backendu
`test` jest najdłuższym odcinkiem, tym, który skraca #520. Ta równoważność jest
utrzymywana, a nie deklarowana: workflow woła te cele, zamiast powtarzać ich
polecenia, a `tests/test_ci_parity.py` wywala się, jeśli bramkujące zadanie
dorobi krok, którego `make check` nie uruchamia. Rozjechało się już cztery razy —
zobacz [Polecenia](commands.md#before-a-pull-request), co `check` pomija i dlaczego.

!!! info "CI może uruchomić mniej zadań niż `check` i to nie jest rozjazd"

    `test`, `test-frontend` i `e2e` są pomijane na pull requeście, którego zmienione
    ścieżki nie mogą na nie wpłynąć, a wymagane sprawdzenie ze statusem `skipped`
    nadal przepuszcza merge. Lokalnie nie ma odpowiednika: `check` uruchamia
    wszystko.

Zmiana wyłącznie w dokumentacji nie uruchamia żadnego z tych trzech; zmiana wyłącznie
w backendzie nie uruchamia żadnej suity frontendu. Decyduje o tym
`scripts/ci_changed_scope.py`, myli się w stronę uruchamiania, a
[Gałęzie](branching.md#a-required-check-may-legitimately-report-skipped) mają tę
regułę.

!!! danger "Dwa sposoby na wypchnięcie czegoś, co nie zostało zweryfikowane"

    `make test-fast` pomija pokrycie, co czyni go złym ostatnim słowem przed pushem
    — bramka jest większością tego, po co te polecenia w ogóle są. A `pytest` bez
    `uv run` łapie ten interpreter, który akurat jest w ścieżce, zamiast przypiętego
    3.12.

## Struktura testów { #test-structure }

Cztery warstwy, a to, do której należy test, rozstrzyga to, czego test potrzebuje, a
nie to, o czym jest.

```
backend/tests/
├── conftest.py          # the shared fixtures, and the test database's name
├── test_*.py            # unit: one module, its dependencies mocked at the repository boundary
├── api/                 # the app driven through `client`, grouped by the question asked
└── integration/
    └── conftest.py      # creates a database of its own, and drops it afterwards
```

`tests/api/` jest pogrupowane po **tym, o co się pyta**, a nie po module tras:
niektóre pliki biorą jeden endpoint (`test_admin_ratings_window.py`), a
`test_platform_routes.py` zamiata całą rodzinę naraz, dlatego `agents.py` nie ma
własnego pliku. Szukaj pytania, zanim zaczniesz szukać ścieżki.

| Warstwa | Gdzie | Do czego |
|---|---|---|
| Jednostkowa | `tests/test_*.py` | Jeden moduł. Repozytoria są mockowane; testowany serwis nigdy |
| API | `tests/api/`, a część na najwyższym poziomie | Trasa: jej bramka, jej kod statusu, to, co dociera do serwisu |
| Integracyjna | `tests/integration/` | To, na co odpowiada tylko baza danych — `ORDER BY`, kaskada, unikalne ograniczenie, zapytanie naprawdę ograniczone do tenanta |
| E2E | `frontend/e2e/` | Ścieżki przecinające cały system — zobacz [Testy frontendu](#frontend-tests) |

Nie ma katalogu `tests/unit/`: test jednostkowy to `test_*.py` na szczycie `tests/`.
Warstwa to **to, czego test potrzebuje, a nie to, gdzie leży**, a najwyższy poziom
trzyma sporo rzeczy, które prowadzą aplikację przez własnego `AsyncClient` —
`test_rag_document_listing.py`, `test_oauth_signin_exchange.py`,
`test_security_headers.py`. Szukanie istniejącego pokrycia tras wyłącznie pod
`tests/api/` je przeoczy.

**Jeden wyjątek, i leży na najwyższym poziomie, a nie w `integration/`.**
`tests/test_migrations.py` przepuszcza cały łańcuch Alembica przez prawdziwą bazę
danych, którą sam tworzy i usuwa pod własną nazwą — bo `downgrade base` usuwa każdą
tabelę, a odziedziczenie `POSTGRES_DB` raz opróżniło roboczą bazę developera. Jest
zbierany przez zwykłe `pytest tests/`. Nie jest w `integration/`, bo w ogóle nie
używa fikstury `db` tamtego pakietu: uruchamia `alembic` w podprocesach.

## Async — anyio, a nie pytest-asyncio { #async-anyio-not-pytest-asyncio }

```python
import pytest

pytestmark = pytest.mark.anyio   # at the top of the module
```

albo `@pytest.mark.anyio` na teście, co robi `tests/api/test_users.py` tam, gdzie
tylko część pliku jest asynchroniczna. Działa jedno i drugie; forma na poziomie
modułu jest tutaj nawykiem, bo większość plików jest asynchroniczna na wskroś.

!!! warning "`@pytest.mark.asyncio` tutaj nie działa i nie ma `asyncio_mode`, które by to naprawiło"

    Suita działa na **anyio**. Nieoznaczone `async def` wywala się przy zbieraniu z
    komunikatem o frameworku, a nie o teście, więc na wejściu czyta się jak zepsute
    środowisko.

Nieoznaczone `async def` nie jest cichym przejściem: pytest 9 wywala je przy
zbieraniu komunikatem *„async def functions are not natively supported”* i wypisuje
wtyczki, które by to naprawiły. Fikstura `anyio_backend` przypina `asyncio`, bo to
właśnie uruchamia uvicorn.

## Kluczowe fikstury (`tests/conftest.py`) { #key-fixtures-testsconftestpy }

Pięć. Żadna z nich nie jest `test_user` ani zalogowanym klientem i o to właśnie
chodzi: uwierzytelniony wołający jest nadpisaniem zależności, więc test mówi, którą
władzę ćwiczy, zamiast dziedziczyć jakąś. `tests/api/test_users.py` buduje własnego
`auth_client` dokładnie z takich nadpisań — lokalna fikstura dla pliku, który jej
potrzebuje, a nie współdzielona, którą dziedziczy każdy plik.

| Fikstura | |
|---|---|
| `anyio_backend` | Przypina `asyncio` i nic jej nie nazywa — pyta o nią anyio |
| `client` | `httpx.AsyncClient` po `ASGITransport(app=app)` — **nie** `TestClient` ze Starlette. Nadpisuje `get_db_session` i `get_redis`, a potem czyści `app.dependency_overrides` |
| `mock_db_session` | `AsyncMock`. Jego `info` jest prawdziwym słownikiem, bo to tam `spawn_after_commit` kolejkuje pracę |
| `mock_redis` | `MagicMock(spec=RedisClient)` z zaślepionymi metodami asynchronicznymi |
| `api_key_headers` | Nagłówek usługa–usługa, dla trasy za `ValidAPIKey` |

`tests/integration/conftest.py` dokłada te, które dotykają bazy danych. Pakiet
odrzuca każdą bazę danych, której nazwa nie zawiera ani `test`, ani `ci`, i opróżnia
każdą tabelę między testami. **Pomija się sam, gdy żadna nie jest osiągalna, tylko
poza CI**: przy ustawionym `CI` zgłasza zamiast tego błąd, bo pominięcie i usługa
Postgresa, która nie wstała, czytają się w wyjściu pytesta identycznie, a
akceptowalne jest tylko jedno z nich.

| Fikstura | |
|---|---|
| `db` | Prawdziwa `AsyncSession` — to, co bierze niemal każdy test integracyjny |
| `engine` | Stojący za nią `AsyncEngine`, dla testu, który potrzebuje sesji, jaką `db` być nie może: *więcej niż jednej* — wyścig, równoległy zapis, dwie transakcje, które muszą się przepleść, gdzie jedna `AsyncSession` dzielona między nimi nie jest drugim połączeniem, tylko połączeniem uszkodzonym — albo takiej, którą testowany kod tworzy sobie sam, tak jak testy RAG wręczają `PgVectorStore` własny `async_sessionmaker`. Bierze go osiemnaście plików |
| `database_url`, `schema_url` | O zasięgu sesji i powód, dla którego dwie powyższe są bezpieczne: nazywają jednorazową bazę danych i raz tworzą jej schemat |

## Pisanie testów { #writing-tests }

Nazywaj zachowanie, a nie funkcję, żeby awaria mówiła, co się zepsuło:
`test_a_grant_widens_access_without_promoting_the_member`, a nie `test_resolve`.

### Test serwisu { #a-service-test }

```python
import pytest
from unittest.mock import AsyncMock
from uuid import uuid4

from app.core.exceptions import NotFoundError
from app.repositories import user as user_repo
from app.services.user import UserService

pytestmark = pytest.mark.anyio


async def test_an_unknown_user_is_a_refusal_rather_than_a_none(monkeypatch, mock_db_session):
    monkeypatch.setattr(user_repo, "get_by_id", AsyncMock(return_value=None))
    service = UserService(mock_db_session)

    with pytest.raises(NotFoundError):
        await service.get_by_id(uuid4())
```

Repozytorium jest zamockowane, a serwis nie. Test, który mockuje to, co testuje,
przechodzi także wtedy, gdy implementację się skasuje.

### Test API { #an-api-test }

Wołający jest nadpisaniem i to właśnie czyni odmowę testowalną:

```python
import pytest
from httpx import AsyncClient
from uuid import uuid4

from app.api import deps
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app

pytestmark = pytest.mark.anyio


async def test_creating_an_agent_without_agents_edit_is_refused(client: AsyncClient):
    # A role, not a permission list: `AuthContext` reads its own permissions out
    # of `ROLE_PERMS` by name, so the test exercises the catalog rather than a
    # set it invented.
    viewer = AuthContext(
        user_id=uuid4(), organization_id=uuid4(), role=str(OrgRoleName.VIEWER)
    )
    app.dependency_overrides[deps.get_auth_context] = lambda: viewer

    response = await client.post("/api/v1/agents", json={"name": "Support"})

    assert response.status_code == 403
```

`tests/api/test_platform_routes.py` robi to zamiataniem, a nie jedną asercją na
trasę: bramka, którą nosi trasa, jest tabelą, a tabelę się przechodzi, a nie
przepisuje. Przechodzi **prefiksy platformy** — `/agents`, `/runs`, `/approvals`,
`/spend`, `/stats`, `/skills` i resztę `_PLATFORM_PREFIXES` — dlatego większość z
nich nie ma własnego pliku i dlatego `/auth`, `/organizations` i `/users` nadal
potrzebują własnych: zamiatanie je omija.

### Test integracyjny { #an-integration-test }

Tylko na to, na co zamockowana sesja odpowiedzieć nie potrafi, czyli zwykle na
uporządkowanie, ograniczenie albo kaskadę. `tests/integration/test_message_order.py`
jest tego kształtem: tura zapisuje swoje pytanie i swoją odpowiedź w jednej
transakcji, więc oba wiersze niosą to samo `created_at` co do mikrosekundy, a remis
rozstrzyga kolumna, a nie planer.

```python
import pytest

from app.repositories import conversation as conversation_repo
from app.services.transcript import TranscriptService

pytestmark = pytest.mark.anyio


async def test_the_question_precedes_the_answer_it_got(db):
    # `_conversation` and `_run` are the file's own builders - a row per table,
    # added to `db` and flushed. Nothing is mocked; that is the whole point.
    conversation = await _conversation(db)
    run = await _run(db, conversation)

    await TranscriptService(db).record(run, prompt="ask", answer="answer")

    written = await conversation_repo.get_messages_by_conversation(db, conversation.id)
    assert [message.role for message in written] == ["user", "assistant"]
```

Tamten błąd *był* Postgresem, a zamockowana sesja przeszłaby wobec schematu, który
nie miał żadnego rozstrzygnięcia remisu.

### Co jest tutaj warte testu { #what-is-worth-a-test-here }

!!! important "Pokryj odmowę"

    Większość wartości tej platformy jest w tym, co ona odrzuca, więc to odmowa jest
    przypadkiem, który musi istnieć:

    - odczyt w poprzek tenantów — **łącznie z takim, gdzie wołający jest
      właścicielem wiersza**;
    - nieprzyznany zasięg;
    - budżet sprawdzany *przed* żądaniem do modelu i zapisywany nawet wtedy, gdy run
      się nie uda;
    - spec odrzucony przy publikacji, a nie w czasie działania;
    - żadnego jawnego sekretu w jakiejkolwiek odpowiedzi, linii logu czy wpisie
      audytowym.

`.claude/rules/testing.md` i skill `backend-tests` niosą resztę — pułapki,
przerobione przykłady i historię za każdą z nich. Ta strona jest kształtem suity;
żadne z nich nie powtarza drugiego.

## Testy frontendu { #frontend-tests }

Uruchamiaj je z `frontend/`. W katalogu głównym repozytorium vitest nie znajduje
konfiguracji, raportuje grubo ponad sto widmowych awarii i zostawia po sobie zbłąkany
`node_modules/`.

```bash
cd frontend

bunx vitest run src/components/chat/usage-strip.test.tsx   # one spec, ~2s
bunx vitest run src/components/chat                        # one directory
bun run test                                               # watch mode
bun run test:coverage                                      # the suite plus the gate CI applies
bun run test:e2e                                           # Playwright
bun run test:e2e --headed                                  # ...with a browser to watch
```

**`bun run test:run` nie mierzy żadnego pokrycia**, więc nie potrafi odpowiedzieć,
czy zadanie `test-frontend` przejdzie: bramka chce 100% linii, instrukcji i funkcji
oraz 97,5% gałęzi na `src/{app/api,lib,stores,hooks}` i większości `src/components`.

### Dwa terminy, oba wymierzone na obciążoną maszynę { #two-deadlines-both-sized-for-a-loaded-machine }

Spec ciężki od renderowania nie jest wolny dlatego, że jest źle napisany; jest wolny
dlatego, że kilka tysięcy takich dzieli dziesięć rdzeni z czymkolwiek innym, co
akurat działa. `testTimeout` w `vitest.config.ts` to **15 s**, a `asyncUtilTimeout`
Testing Library w `vitest.setup.ts` to **5 s**, oba podniesione z wartości
domyślnych, które trzymają się tylko na bezczynnej maszynie.

Liczby pochodzą z przepuszczenia całej suity na cztery sposoby
([#862](https://github.com/vstorm-co/agenticos/issues/862)):

| Najwolniejszy pojedynczy test | Bez instrumentacji | Pod `--coverage` |
|---|---|---|
| Dziesięć bezczynnych rdzeni | 1,7 s | 2,9 s |
| 32 zajęte pętle obok | 5,4 s | 6,1 s |

Pod takim obciążeniem stare domyślne 5 s wywalało trzy testy na przebieg — *inne*
trzy za każdym razem, bo to, które pliki dzielą workera, rozstrzyga się na
podstawie czasów, i to zarówno w przebiegu bez instrumentacji, jak i w tym z nią.
Instrumentacja kosztuje jakieś 1,6× całkowitego czasu testów na spokojnej maszynie i
jest mniejszym mnożnikiem; resztą jest opóźnienie planisty. Dlatego żaden z tych
terminów nie zależy od `--coverage`: limit, co do którego szybka pętla i bramka są
niezgodne, to limit, który bramki odtworzyć nie potrafi.

`asyncUtilTimeout` zostaje mocno poniżej `testTimeout` celowo. Element, który nigdy
nie nadejdzie, powinien przegrać ten wyścig, żeby awaria mówiła *„Unable to find an
element with the text: …”* i go nazywała, zamiast mówić *„Test timed out”* i nie
nazywać niczego.

Żadna z tych liczb nie jest licencją na spec, który robi więcej pracy, niż potrzebują
jego asercje: montowanie czterdziestu wierszy tabeli dwa razy, żeby udowodnić liczbę,
kosztowało jakieś dwie sekundy w `rag/[id]/counts.integration.test.tsx`, zanim jego
fikstura została przycięta do trzech.

Playwright startuje to, czego potrzebuje suita: frontend oraz zgodny z OpenAI
**zaślepkowy serwer modelu** (`frontend/e2e/stub-model-server.ts`) domyślnie na
`127.0.0.1:4010`. Backend i jego baza danych muszą już stać — zasiany owner, profil
modelu i opublikowany agent pochodzą z `agenticos cmd bootstrap`.

Oba porty są konfigurowalne, więc suita działa obok innego checkoutu, który już
trzyma domyślne — `bun run dev` zostawiony na 3000 albo drugi worktree. `E2E_PORT`
przesuwa frontend, `E2E_STUB_MODEL_PORT` zaślepkę, a `playwright.config.ts`
wyprowadza z nich `baseURL`, oba `webServer.url` oraz `PORT`/`E2E_STUB_MODEL_PORT`
serwerów — więc nic nie jest mówione o porcie dwa razy. `make test-e2e` czyta
wszystkie trzy (razem z `E2E_BACKEND`) i wypisuje je, zanim wystartuje:

```bash
E2E_PORT=3100 make test-e2e          # frontend on 3100, stub on its default
```

Zaślepka jest tym, co pozwala `journey.spec.ts` przepuścić agenta od początku do
końca bez klucza providera: serwuje Chat Completions API, ze strumieniowaniem
włącznie, a profil modelu sięga jej przez pole **Endpoint**. Odbija z powrotem token,
o którym instrukcje agenta każą mu powiedzieć — co jest asercją, bo nic innego nie
mogłoby umieścić tego tokena w odpowiedzi — i zwraca zużycie, więc run jest wyceniany
i ostatnia asercja ścieżki ma koszt do znalezienia. Niczego nie uwierzytelnia i nie
woła żadnych narzędzi; nie dowodzi tego, że prawdziwy provider odpowiada.

Zaślepka przypina się do loopbacku, a backend dzwoni do niej na `127.0.0.1:<port>`
przez ten zapisany profil — więc backend musi dzielić loopback hosta. To ścieżka z
uvicornem na hoście, którą uruchamia CI; backend w kontenerze nie sięgnie
`127.0.0.1` hosta, a przesunięcie portu tego nie zmienia.

### Czerwone `e2e` to często fikstura, a nie produkt { #a-red-e2e-is-often-the-fixture-not-the-product }

`setup` i `seed` to w Playwrighcie *zależności projektów*, więc awaria w
którymkolwiek z nich w ogóle powstrzymuje od uruchomienia projekty, które od niego
zależą. Podsumowanie czyta się wtedy `1 failed`, `7 passed` i `17 did not run`, co na
pull requeście wygląda dokładnie jak zepsuta funkcja — a nią nie jest: **żaden spec
produktowy się nie uruchomił.** Trzy gałęzie zapłaciły za taką diagnozę jednego dnia
([#132](https://github.com/vstorm-co/agenticos/issues/132)), więc
`frontend/e2e/fixture-reporter.ts` wypisuje teraz baner, który to mówi, a pod CI
adnotację błędu GitHuba, którą widać na stronie sprawdzeń bez otwierania logu.

### Czekanie na wiersz to nie czekanie na zapis { #waiting-for-a-row-is-not-waiting-for-the-write }

Spec, który coś tworzy przez dialog, **nie może** kliknąć submit, a potem
zapewniać, że nowy wiersz jest na ekranie. Ten kształt siedział w sześciu miejscach i
w czterech widziano, jak flakuje. Dwa powody, a drugi jest tym kosztownym:

- Okno między rozstrzygnięciem mutacji a wyrenderowaniem listy jest prawdziwe, a
  dłuższy timeout `expect` sprawia tylko, że wyścig wolniej się wywala.
- **Otwarty dialog Radix wyjmuje resztę strony z drzewa dostępności.** Dopóki jeden
  jest na ekranie, `getByRole("main")`, `getByRole("row")` i każdy zbudowany na nich
  lokator rozwiązują się do *niczego*, więc asercja kończy się timeoutem z
  `element(s) not found`, niezależnie od tego, czy wiersz istnieje — nazywając tę
  jedną rzecz, która przyczyną być nie może. Odrzucone tworzenie wyglądało
  identycznie jak wolny refetch, przy czterech osobnych wystąpieniach.

`submitDialog` w `frontend/e2e/helpers.ts` jest drogą przez to: czeka na własną
odpowiedź zapisu i zapewnia o jej statusie (więc odmowa czyta się jako
`409 … already exists`, w milisekundach), a potem czeka, aż dialog się zamknie — co
jest sposobem, w jaki aplikacja mówi, że skończyła wszystko, co robi wokół zapisu.

Czego celowo nie obiecuje, to tego, że wiersz jest już wyrenderowany, bo obecnie to
nieprawda: na refetch listy przychodzi czasem odpowiedź z listą sprzed zapisu, mimo
że wiersz jest zacommitowany i obie warstwy serwera go zwracają
([#230](https://github.com/vstorm-co/agenticos/issues/230), mniej więcej raz na osiem
przebiegów). Zatem:

- **Krok fikstury pyta API i pyta dalej.** Każdy krok `seed.setup.ts` zapewnia przez
  `/api/…`, bo jego zadaniem jest to, żeby fikstura istniała — a krok fikstury,
  który zawiedzie, zabiera ze sobą każdy spec produktowy. Po zapisie pyta przez
  odpytywanie (`nowThere`), nigdy pojedynczym odczytem. Zaczęło się to jako obejście:
  2xx z tego backendu znaczyło kiedyś, że żądanie zostało obsłużone, a nie że zapis
  jest do odczytania, bo commit działał w zależności, którą FastAPI rozwija po tym,
  jak odpowiedź wyszła ([#353](https://github.com/vstorm-co/agenticos/issues/353)).
  **To jest naprawione** — commit ląduje teraz przed odpowiedzią — a odpytywanie i
  tak zostaje, bo fikstura jest złym miejscem na odkrycie, że jakiś *inny* zapis
  jest wolniejszy niż jego potwierdzenie, i dlatego, że `nowThere` wypisuje wiersze,
  które zobaczyło, tam gdzie pojedynczy odczyt nie wypisuje nic. Strażnik
  `alreadyThere`, którym otwiera się każdy krok, jest celowo pojedynczym odczytem, bo
  działa przed zapisem. Ten jeden sprawdzian *po zapisie*, który czytał raz,
  kosztował 87 pominiętych speców trzy razy jednego dnia
  ([#335](https://github.com/vstorm-co/agenticos/issues/335)).
- **Spec produktowy, który jest o renderowaniu, mówi to wprost** i przeładowuje
  stronę najpierw, jeśli potrzebuje listy, której może zaufać. `vault.spec.ts` ma
  trzy wywołania `page.reload()` oznaczone `#230`; kiedy ta sprawa się zamknie,
  znikną.

## Testowa baza danych { #test-database }

Większość testów nie dotyka prawdziwej bazy danych. Fikstura `client` w
`tests/conftest.py` nadpisuje `get_db_session` zamockowaną sesją asynchroniczną
(`AsyncMock`) przez `app.dependency_overrides` FastAPI, więc suita działa szybko i
nie potrzebuje kontenera Postgresa:

- `mock_db_session` — `AsyncMock` stojący za `AsyncSession` (`execute`, `commit`, `rollback`, `close`)
- Nadpisania są rejestrowane przed każdym testem i czyszczone po nim
- Zapewniaj o wywołaniach mocka albo zaślepiaj wartości zwracane przez `execute(...)` dla testowanej ścieżki

Wszystko pod `tests/integration/` jest wyjątkiem i prosi o fiksturę `db` z
`tests/integration/conftest.py`, zamiast budować własny silnik — to właśnie ta
fikstura stawia schemat.

**Schemat jest budowany raz na cały proces, a dane resetowane między testami.**

Fikstura `schema_url` uruchamia `create_all` jeden raz. Fikstura `engine` o zasięgu
funkcji wręcza potem każdemu testowi pustą bazę danych, robiąc `TRUNCATE` na każdej
tabeli modelu — i usuwając każdą tabelę, którą test utworzył poza modelami, runtime'owe
`rag_<collection>` albo sondę porządku — zamiast przebudowywać schemat.

Kiedyś robiło to `drop_all` + `create_all` przed *każdym* testem: ~0,4 s DDL, czyli
prawie cały czas działania suity, której asercje to mikrosekundy pracy Postgresa.
Zbudowanie go raz skróciło `tests/integration` z ~125 s do ~50 s
([#215](https://github.com/vstorm-co/agenticos/issues/215)).

`TRUNCATE`, a nie rollback transakcji, bo testy przepływów API commitują przez
prawdziwe `get_db_session` i ich wiersze przeżywają rollback.

**Baza danych, której używa, należy do tego procesu pytesta, który o nią poprosił**:
`<POSTGRES_DB>_p<pid>`, tworzona przy starcie sesji i usuwana, gdy sesja się kończy,
włącznie z zakończeniem porażką.

To właśnie czyni dwa równoległe przebiegi bezpiecznymi — dwa worktree albo worktree i
`make test`, wobec jednego kontenera Postgresa — i nie potrzebuje niczego podanego w
wierszu poleceń.

Nazwa była stała aż do
[#189](https://github.com/vstorm-co/agenticos/issues/189). Ponieważ każdy test usuwał
i tworzył schemat na tej współdzielonej bazie danych, dwa przebiegi spędzały czas na
usuwaniu sobie nawzajem tabel i raportowaniu awarii, które nie należały do żadnej z
gałęzi.

!!! danger "Suita odrzuca każdą bazę danych, której nazwa nie zawiera `test` ani `ci`"

    Usuwa tabele bezwarunkowo, więc ten strażnik jest jedyną rzeczą między nią a
    developerską bazą danych.

**Poświadczenie jest rozwiązywane raz, w `tests/conftest.py`, a wszystko czyta je z
powrotem z obiektu ustawień.**

Do tej bazy danych sięgają dwa silniki — ten z fikstury i ten aplikacji, budowany w
czasie importu w `app/db/session.py` — a test pytający, czy zapis jest widoczny,
potrzebuje obu.

Kiedyś rozwiązywały hasło osobno, przy czym fikstura domyślnie brała `postgres` tam,
gdzie `app/core/config.py` domyślnie bierze puste, i nic nie mogło tego zobaczyć,
dopóki każdy test łączył się przez fiksturę.

Pierwszy test, który poprowadził silnik aplikacji, nie zdołał się uwierzytelnić na
checkoucie bez `backend/.env` — czyli na **każdym worktree gita**, bo ten plik nie
jest śledzony. Dwie awarie wobec pełnej zieleni wszędzie indziej, czytające się
dokładnie jak regresja gałęzi
([#485](https://github.com/vstorm-co/agenticos/issues/485)).

Suita zasiewa teraz `POSTGRES_PASSWORD=postgres`, zanim zbudowany zostanie obiekt
ustawień, i tylko wtedy, gdy ani środowisko, ani `.env` żadnego nie dostarcza, więc
prawdziwe hasło nigdy nie zostaje zastąpione domyślnym.

`app/core/config.py` nadal ustawia je domyślnie na puste i to właśnie sprawia, że
brakujący `.env` oznajmia się w `alembic check`, zamiast sięgać bazy danych ze
zgadywanką.

### Suita migracji ma trzecią { #the-migration-suite-has-a-third-one }

`tests/test_migrations.py` nakłada cały łańcuch na pustą bazę danych i cofa go do
base, więc nie może użyć żadnej z powyższych: baza integracyjna ma już w sobie schemat
(zbudowany z modeli, co jest innym pytaniem), a `downgrade base` wobec bazy suity
jednostkowej opróżniłby ją w trakcie przebiegu. Dostaje
`agenticos_migrations_test_p<pid>`, tworzoną przed jej pierwszym testem i usuwaną po
ostatnim, a każdemu podprocesowi alembica ta nazwa jest przekazywana jawnie, zamiast
dziedziczyć `POSTGRES_DB`.

Ta baza danych musiała kiedyś istnieć wcześniej i nic jej nigdy nie tworzyło, więc
każdy test w tym module był pomijany przy każdym przebiegu CI, jaki ten projekt miał
— zielony build ponad jedynymi asercjami mówiącymi, że `downgrade()` w ogóle działa
([#234](https://github.com/vstorm-co/agenticos/issues/234)). Teraz tworzy własną, a
pominięcie, które przetrwało, znaczy dokładnie to, co mówi: **żaden Postgres nie
odpowiedział.** W CI, gdzie kontener usługi jest zadeklarowany, jest to zamiast tego
porażka — kontener, który nie wstał, to nie jest środowisko, które nie może
odpowiedzieć, a te dwie rzeczy są w wyjściu pytesta nie do odróżnienia.

`make test-migrations` nadal istnieje i nadal jest tym, co uruchomić ręcznie po
dotknięciu `alembic/versions/`, ale wskazuje na to, co mówi `backend/.env`, czyli na
laptopie na bazę danych z twoją własną pracą. Wybierz raczej
`uv run pytest tests/test_migrations.py`, które sięgnąć jej nie może.

## Prefect i dlaczego żaden test nie sięga serwera { #prefect-and-why-no-test-reaches-a-server }

**Wywołanie `@flow` jest wywołaniem sieciowym, a suita kieruje je donikąd.** Prefect
rozwiązuje własne ustawienia z `backend/.env` — jego model ustawień niesie
`env_file=".env"` — więc `PREFECT_API_URL=http://localhost:4200/api`, linia, której
potrzebuje `make dev`, była też adresem, do którego próbowało sięgnąć wywołanie
`@flow` w teście. Bez stojącego serwera daje to `RuntimeError: Failed to reach API at
http://localhost:4200/api/` z testu, który zamockował każdego współpracownika,
jakiego ma, a CI nigdy tego nie widziało: bez `.env` nie ma URL-a, więc to, co
uruchamiał laptop, nigdy nie było tym, co uruchamiało CI
([#536](https://github.com/vstorm-co/agenticos/issues/536)).

`tests/conftest.py` przypisuje więc `PREFECT_API_URL` **pusty**, zanim Prefect
zostanie zaimportowany, obok nazwy bazy danych i hasła powyżej i z tego samego
powodu.

Skasowanie zmiennej by nie wystarczyło: nieustawiona zmienna zostawia odpowiedź
źródłu dotenv, a to źródło dotenv trzyma ten URL.

Puste przypisanie je przebija, bo model ustawień Prefecta niesie
`env_ignore_empty=False` — co jest regułą Prefecta, a nie naszą. `app/core/config.py`
ustawia to odwrotnie, więc ta sama linia wobec *naszych* ustawień zostałaby odrzucona
i `.env` i tak by odpowiedział.

Prefect czyta pusty URL jako brak URL-a i startuje na potrzeby wywołania własny
tymczasowy serwer, co CI robiło zawsze. Przebieg nie zależy więc już od tego, czy
serwer Prefecta akurat stoi, w żadną ze stron.

**Stan tamtego serwera to baza SQLite pod `PREFECT_HOME`, a suita daje mu własne.**
Zostawione samo sobie jest to `~/.prefect`, więc przebieg jednostkowy pisałby swoje
flow runy do danych Prefecta developera, a tam, gdzie Prefect działa na hoście, a nie
w Dockerze, do pliku, który trzyma otwarty działający `prefect server`.
`tests/conftest.py` kieruje to na `agenticos-prefect-test` w systemowym katalogu
tymczasowym, z tego samego powodu, dla którego nazwa Postgresa powyżej jest bazą
testową. Jeden katalog, a nie jeden na proces: kosztuje jego tworzenie.

Tworzenie go jest migracją, a suita podnosi 20-sekundowy przydział Prefecta na
wystartowanie tego serwera do 90 — **jako zapas, a nie dlatego, że widziano, jak 20
zawodzi.** Wobec `PREFECT_HOME`, do którego nic jeszcze nie pisało, cały start zajmuje
jakieś sześć sekund na laptopie i jakieś dziewięć na kontenerze CI, który jest zimny
przy każdym przebiegu i na wartości domyślnej nigdy nie był czerwony. Podniesiony
przydział kupuje to, że jedyny krok, którego kosztu nic tutaj nie ogranicza —
migracja na obciążonej maszynie albo katalog tymczasowy, który został zamieciony —
czeka, zamiast wywalać suitę, którą drugi przebieg by przepuścił.
`tests/test_prefect_test_environment.py` przypina wszystkie cztery właściwości.

## Podsumowanie { #recap }

- **Cztery warstwy**: jednostkowa, integracyjna, API, E2E. Wybierz po tym, co test
  potrzebuje mieć prawdziwe, a nie po tym, o czym jest.
- Testy asynchroniczne używają **anyio**. `@pytest.mark.asyncio` nic tutaj nie robi.
- **Pokryj odmowę.** Większość wartości tej platformy jest w tym, co ona odrzuca.
- Warstwa platformy jest na **100%**, a dodanie do niej modułu oznacza edycję dwóch
  list w `backend/pyproject.toml`.
- Kolejność jest tasowana przy każdym przebiegu; odtwórz awarię z jej wypisanym
  seedem, zanim wyciągniesz jakikolwiek wniosek o zmianie.
