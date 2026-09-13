---
source_sha: dba14340bbd8
---

# Tests { #testing }

Vier Ebenen, ein Runner und ein Coverage-Gate, das den Build unter 100 % auf der
Plattformschicht scheitern lässt.

Die kurze Fassung dessen, was zu laufen hat: beim Schreiben die Tests, die die
Änderung abdecken, und einmal vor dem Push die Suiten.

## Tests ausführen { #running-tests }

!!! tip "Beim Schreiben läuft, was die Änderung abdeckt; die Suite ist das Gate vor dem Push"

    Eine Datei antwortet in etwa einer Sekunde, wo die Suite anderthalb Minuten
    braucht, und sagt dasselbe über die Änderung.

```bash
cd backend

uv run pytest tests/test_capability_registry.py -q         # one file
uv run pytest tests/test_capability_registry.py -k drift   # one behaviour
uv run pytest tests/api/test_workspace_routes.py -x -v     # stop at the first failure
uv run pytest tests/integration -v --no-cov                # the ones needing a database
```

Diese bleiben mit Absicht **seriell**: Worker-Prozesse zu starten, um eine Datei
auszuführen, kostet mehr als die Datei selbst. Die Targets für die ganze Suite —
`make test`, `make test-fast`, `make test-integration`, `make test-cov` — laufen
über Worker verteilt (`pytest -n auto --maxprocesses 4`), was die I/O-gebundene
Integrationssuite ungefähr halbiert; `pytest-cov` führt die Daten je Worker
zusammen, das 100-%-Gate bleibt also unverändert. Die Obergrenze ist vier, weil
die Unit-Suite importgebunden ist — jeder Worker importiert die App einmal — und
darüber hinaus nichts gewinnt, während ein ungedeckeltes `auto` auf einem Laptop
mit vielen Kernen *langsamer* ist als seriell, und zwar komplett durch den Start
der Worker (#520).

!!! warning "Jeder Lauf wird gemischt, und ein Test, der gestern durchlief, hing vielleicht von der Reihenfolge ab"

    `pytest-randomly` gibt den Seed im Kopf aus
    (`Using --randomly-seed=1697040112`). Spielen Sie diesen Seed **seriell**
    nach, um dieselbe Reihenfolge zurückzubekommen — `-n auto` legt nicht fest,
    welcher Worker was ausführt.

Ein reihenfolgeabhängiger Test — einer, der nur durchläuft, weil etwas davor
einen Zustand hinterlassen hat — ist das klassische „grün auf meinem Laptop, rot
in CI“, und eine Suite, die immer in Sammelreihenfolge läuft, stellt die Frage
nie. CI stellt sie in jedem Lauf in einer frischen Reihenfolge.

```bash
uv run pytest tests/ -q --randomly-seed=1697040112   # that order again, serially
uv run pytest tests/ -q -p no:randomly               # collection order, while bisecting
```

Der Seed wird einmal vom Controller gewählt und an jeden xdist-Worker
weitergereicht, `-n auto` sammelt also eine Reihenfolge statt vier. Er legt nicht
fest, welcher Worker was ausführt: `make test` lässt xdist auf seinem Standard
`--dist load`, das jeden Test dem gerade freien Worker gibt. Ein Fehler, der
davon abhing, was sich einen Worker teilte — der `InterfaceError`, den #571 fand,
ist einer —, kommt also zurück, indem man den Seed *seriell* nachspielt, wie
oben, und nicht durch ein erneutes `make test`. Das Plugin seedet außerdem
`random` vor jedem Test identisch, alles, was es für Eindeutigkeit nutzt, ist
also innerhalb eines Tests eindeutig und wiederholt sich über Tests hinweg.

Bis #571 war das Plugin dokumentiert, aber nicht installiert, `-p no:randomly`
war ein stiller No-Op, und nichts hatte die Behauptung je überprüft.

Einmal, vor dem Push — `make check` führt alles davon aus, in dieser Reihenfolge:

```bash
make lint               # ruff, ruff format, ty, vulture, deptry, eslint, prettier, tsc, the guards
make test               # the suite plus the 100% gate on the platform layer
make db-check           # alembic check — a model change with no migration fails here
make test-frontend-cov  # the frontend suite plus its own gate
make build-frontend     # next build — the route tree, which tsc and vitest do not see
make docs-build         # mkdocs --strict — a dead link is a failure
make audit              # the locked dependency set against the advisory database
```

Etwa fünf Minuten seriell, gegen die zwölf von CI parallel — dort ist der
Backend-Job `test` die lange Stange, die #520 kürzt. Die Gleichheit wird gepflegt
statt behauptet: Der Workflow ruft diese Targets auf, statt ihre Befehle zu
wiederholen, und `tests/test_ci_parity.py` scheitert, wenn ein gatender Job einen
Schritt bekommt, den `make check` nicht ausführt. Sie ist viermal auseinander
gedriftet — siehe [Befehle](commands.md#before-a-pull-request) dazu, was `check`
auslässt und warum.

!!! info "CI führt womöglich weniger Jobs aus als `check`, und das ist keine Drift"

    `test`, `test-frontend` und `e2e` werden bei einem Pull Request übersprungen,
    dessen geänderte Pfade sie nicht betreffen können, und ein `skipped` Required
    Check lässt einen Merge trotzdem durch. Lokal gibt es dazu kein Gegenstück:
    `check` führt alles aus.

Eine reine Docs-Änderung führt keinen der drei aus; eine reine Backend-Änderung
führt keine Frontend-Suite aus. Entschieden wird das von
`scripts/ci_changed_scope.py`, es irrt in Richtung Ausführen, und
[Branches](branching.md#a-required-check-may-legitimately-report-skipped) hat die
Regel.

!!! danger "Zwei Wege, etwas zu pushen, das nicht verifiziert wurde"

    `make test-fast` überspringt die Coverage, was es zum falschen letzten Wort
    vor einem Push macht — das Gate ist das meiste, wofür diese Befehle da sind.
    Und `pytest` ohne `uv run` greift sich den Interpreter, der gerade im Pfad
    steht, statt des gepinnten 3.12.

## Aufbau der Tests { #test-structure }

Vier Ebenen, und zu welcher ein Test gehört, entscheidet sich daran, was er
braucht, und nicht daran, worum es in ihm geht.

```
backend/tests/
├── conftest.py          # the shared fixtures, and the test database's name
├── test_*.py            # unit: one module, its dependencies mocked at the repository boundary
├── api/                 # the app driven through `client`, grouped by the question asked
└── integration/
    └── conftest.py      # creates a database of its own, and drops it afterwards
```

`tests/api/` ist danach gruppiert, **was gefragt wird**, und nicht nach
Route-Modul: Manche Dateien nehmen einen Endpunkt
(`test_admin_ratings_window.py`), und `test_platform_routes.py` fegt eine ganze
Familie auf einmal durch, weshalb `agents.py` keine eigene Datei hat. Suchen Sie
nach der Frage, bevor Sie nach dem Pfad suchen.

| Ebene | Wo | Wofür |
|---|---|---|
| Unit | `tests/test_*.py` | Ein Modul. Repositories werden gemockt; der Service, um den es geht, nie |
| API | `tests/api/`, und einige auf oberster Ebene | Die Route: ihr Gate, ihr Statuscode, was den Service erreicht |
| Integration | `tests/integration/` | Was nur eine Datenbank beantwortet — ein `ORDER BY`, eine Kaskade, ein Unique Constraint, eine Abfrage, die wirklich tenant-skopiert ist |
| E2E | `frontend/e2e/` | Wege, die das ganze System überqueren — siehe [Frontend-Tests](#frontend-tests) |

Es gibt kein Verzeichnis `tests/unit/`: Ein Unit-Test ist eine `test_*.py` oben in
`tests/`. Die Ebene ist **das, was ein Test braucht, nicht, wo er liegt**, und die
oberste Ebene hält reichlich, was die App durch einen eigenen `AsyncClient`
treibt — `test_rag_document_listing.py`, `test_oauth_signin_exchange.py`,
`test_security_headers.py`. Wer nur unter `tests/api/` nach bestehender
Route-Abdeckung sucht, übersieht sie.

**Eine Ausnahme, und die liegt auf oberster Ebene statt in `integration/`.**
`tests/test_migrations.py` durchläuft die ganze Alembic-Kette gegen eine echte
Datenbank, die es selbst unter einem eigenen Namen anlegt und wieder löscht —
denn `downgrade base` löscht jede Tabelle, und `POSTGRES_DB` zu erben hat einmal
die Arbeitsdatenbank einer Entwicklerin geleert. Es wird von einem gewöhnlichen
`pytest tests/` eingesammelt. Es liegt nicht in `integration/`, weil es die
`db`-Fixture dieses Pakets überhaupt nicht nutzt: Es führt `alembic` in
Subprozessen aus.

## Async — anyio, nicht pytest-asyncio { #async-anyio-not-pytest-asyncio }

```python
import pytest

pytestmark = pytest.mark.anyio   # at the top of the module
```

oder `@pytest.mark.anyio` am Test, was `tests/api/test_users.py` dort tut, wo nur
ein Teil einer Datei async ist. Beides funktioniert; die Form auf Modulebene ist
hier die Gewohnheit, weil die meisten Dateien durchgängig async sind.

!!! warning "`@pytest.mark.asyncio` funktioniert hier nicht, und es gibt kein `asyncio_mode`, das es täte"

    Die Suite läuft auf **anyio**. Ein unmarkiertes `async def` scheitert beim
    Einsammeln mit einer Meldung über das Framework statt über den Test, es liest
    sich beim Einstieg also wie eine kaputte Umgebung.

Ein unmarkiertes `async def` ist kein stilles Durchlaufen: pytest 9 lässt es beim
Einsammeln scheitern mit *"async def functions are not natively supported"* und
listet die Plugins auf, die es beheben würden. Die Fixture `anyio_backend` pinnt
`asyncio`, weil uvicorn darauf läuft.

## Die wichtigsten Fixtures (`tests/conftest.py`) { #key-fixtures-testsconftestpy }

Fünf. Keine davon ist ein `test_user` oder ein angemeldeter Client, und genau das
ist der Punkt: Eine authentifizierte aufrufende Person ist ein
Dependency-Override, ein Test sagt also, welche Befugnis er ausübt, statt eine zu
erben. `tests/api/test_users.py` baut sich aus genau solchen Overrides einen
eigenen `auth_client` — eine lokale Fixture für die Datei, die eine braucht, und
keine geteilte, die jede Datei erbt.

| Fixture | |
|---|---|
| `anyio_backend` | Pinnt `asyncio`, und nichts nennt sie — anyio fragt danach |
| `client` | `httpx.AsyncClient` über `ASGITransport(app=app)` — **nicht** der `TestClient` von Starlette. Übersteuert `get_db_session` und `get_redis` und leert `app.dependency_overrides` danach |
| `mock_db_session` | Ein `AsyncMock`. Sein `info` ist ein echtes dict, weil `spawn_after_commit` dort Arbeit einreiht |
| `mock_redis` | Ein `MagicMock(spec=RedisClient)` mit gestubbten async-Methoden |
| `api_key_headers` | Der Header für Dienst-zu-Dienst-Aufrufe, für eine Route hinter `ValidAPIKey` |

`tests/integration/conftest.py` ergänzt die, die eine Datenbank berühren. Das
Paket lehnt jede Datenbank ab, deren Name weder `test` noch `ci` enthält, und
leert jede Tabelle zwischen den Tests. **Es überspringt sich selbst nur außerhalb
von CI, wenn keine erreichbar ist**: Mit gesetztem `CI` wirft es stattdessen, weil
ein Skip und ein Postgres-Service, der nicht startete, in der Ausgabe von pytest
identisch aussehen und nur eines von beidem auf einem Runner hinnehmbar ist.

| Fixture | |
|---|---|
| `db` | Eine echte `AsyncSession` — was fast jeder Integrationstest nimmt |
| `engine` | Die `AsyncEngine` dahinter, für einen Test, der eine Session braucht, die `db` nicht sein kann: *mehr als eine* — ein Race, ein nebenläufiger Schreibvorgang, zwei Transaktionen, die sich verschränken müssen, wo eine über beide geteilte `AsyncSession` keine zweite Verbindung, sondern eine kaputte ist — oder eine, die der geprüfte Code sich selbst baut, so wie die RAG-Tests `PgVectorStore` seinen eigenen `async_sessionmaker` geben. Achtzehn Dateien nehmen sie |
| `database_url`, `schema_url` | Session-skopiert und der Grund, warum die beiden darüber sicher sind: Sie benennen die Wegwerfdatenbank und legen ihr Schema einmal an |

## Tests schreiben { #writing-tests }

Benennen Sie das Verhalten und nicht die Funktion, damit ein Fehlschlag sagt, was
kaputt ist: `test_a_grant_widens_access_without_promoting_the_member`, nicht
`test_resolve`.

### Ein Service-Test { #a-service-test }

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

Das Repository wird gemockt und der Service nicht. Ein Test, der das mockt, was er
prüft, läuft auch dann durch, wenn die Implementierung gelöscht wird.

### Ein API-Test { #an-api-test }

Die aufrufende Person ist ein Override, und genau das macht die Ablehnung prüfbar:

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

`tests/api/test_platform_routes.py` tut das fegend statt mit einer Zusicherung je
Route: Das Gate, das eine Route trägt, ist eine Tabelle, und eine Tabelle wird
durchlaufen statt wiederholt. Es durchläuft die **Plattform-Präfixe** —
`/agents`, `/runs`, `/approvals`, `/spend`, `/stats`, `/skills` und den Rest von
`_PLATFORM_PREFIXES` —, weshalb die meisten davon keine eigene Datei haben und
weshalb `/auth`, `/organizations` und `/users` weiterhin eine brauchen: Der Fegezug
geht an ihnen vorbei.

### Ein Integrationstest { #an-integration-test }

Nur für das, was eine gemockte Session nicht beantworten kann, und das ist meist
eine Sortierung, ein Constraint oder eine Kaskade.
`tests/integration/test_message_order.py` ist die Form: Ein Zug schreibt seine
Frage und seine Antwort in einer Transaktion, beide Zeilen tragen also dasselbe
`created_at` auf die Mikrosekunde, und der Gleichstand wird von einer Spalte
aufgelöst statt vom Planer.

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

Der Fehler dort *war* Postgres, und eine gemockte Session wäre gegen das Schema
durchgelaufen, das überhaupt keine Auflösung des Gleichstands hatte.

### Was hier einen Test wert ist { #what-is-worth-a-test-here }

!!! important "Decken Sie die Ablehnung ab"

    Der meiste Wert dieser Plattform liegt in dem, was sie ablehnt, die Ablehnung
    ist also der Fall, den es geben muss:

    - ein Lesevorgang über Tenants hinweg — **auch einer, bei dem die aufrufende
      Person die Zeile besitzt**;
    - ein nicht gewährter Scope;
    - ein Budget, das *vor* der Modellanfrage geprüft und auch dann erfasst wird,
      wenn der Run fehlschlägt;
    - ein Spec, das beim Veröffentlichen abgelehnt wird statt zur Laufzeit;
    - kein Klartext-Secret in irgendeiner Antwort, Logzeile oder einem
      Audit-Eintrag.

`.claude/rules/testing.md` und die Skill `backend-tests` tragen den Rest — die
Fallen, die ausgearbeiteten Beispiele und die Geschichte hinter jeder einzelnen.
Diese Seite ist die Form der Suite; keines von beiden wiederholt das andere.

## Frontend-Tests { #frontend-tests }

Führen Sie diese aus `frontend/` aus. Im Wurzelverzeichnis des Repositorys findet
vitest keine Konfiguration, meldet weit über hundert Phantom-Fehlschläge und
lässt ein verirrtes `node_modules/` zurück.

```bash
cd frontend

bunx vitest run src/components/chat/usage-strip.test.tsx   # one spec, ~2s
bunx vitest run src/components/chat                        # one directory
bun run test                                               # watch mode
bun run test:coverage                                      # the suite plus the gate CI applies
bun run test:e2e                                           # Playwright
bun run test:e2e --headed                                  # ...with a browser to watch
```

**`bun run test:run` misst keine Coverage**, es kann also nicht beantworten, ob
der Job `test-frontend` durchläuft: Das Gate will 100 % Zeilen, Statements und
Funktionen sowie 97,5 % Branches über `src/{app/api,lib,stores,hooks}` und die
meisten von `src/components`.

### Zwei Fristen, beide für eine belastete Maschine bemessen { #two-deadlines-both-sized-for-a-loaded-machine }

Eine renderlastige Spec ist nicht langsam, weil sie schlecht geschrieben ist; sie
ist langsam, weil sich mehrere Tausend davon zehn Kerne mit allem teilen, was
sonst noch läuft. `testTimeout` in `vitest.config.ts` steht auf **15s** und
`asyncUtilTimeout` von Testing Library in `vitest.setup.ts` auf **5s**, beide
angehoben von Voreinstellungen, die nur auf einer unbelasteten Maschine halten.

Die Zahlen stammen daher, dass die ganze Suite auf vier Arten gelaufen ist
([#862](https://github.com/vstorm-co/agenticos/issues/862)):

| Langsamster Einzeltest | Ohne Instrumentierung | Unter `--coverage` |
|---|---|---|
| Zehn Kerne im Leerlauf | 1.7s | 2.9s |
| 32 beschäftigte Schleifen daneben | 5.4s | 6.1s |

Unter dieser Last ließ die alte Voreinstellung von 5s drei Tests je Lauf
scheitern — jedes Mal *andere* drei, weil sich nach Laufzeit entscheidet, welche
Dateien sich einen Worker teilen, und das im nackten Lauf ebenso wie im
instrumentierten. Die Instrumentierung kostet auf einer ruhigen Maschine etwa das
1,6-Fache der gesamten Testzeit und ist der kleinere Faktor; der Rest ist
Scheduling-Latenz. Deshalb hängt keine der beiden Fristen an `--coverage`: Eine
Grenze, über die der schnelle Loop und das Gate uneins sind, ist eine, die das
Gate nicht reproduzieren kann.

`asyncUtilTimeout` bleibt mit Absicht deutlich unter `testTimeout`. Ein Element,
das nie kommt, soll das Rennen verlieren, damit der Fehlschlag *"Unable to find an
element with the text: …"* sagt und es benennt, statt *"Test timed out"* zu sagen
und nichts zu benennen.

Keine der beiden Zahlen ist ein Freibrief für eine Spec, die mehr Arbeit tut, als
ihre Zusicherungen brauchen: vierzig Tabellenzeilen zweimal zu mounten, um eine
Anzahl zu beweisen, kostete in
`rag/[id]/counts.integration.test.tsx` etwa zwei Sekunden, bevor ihr Fixture auf
drei gekürzt wurde.

Playwright startet, was die Suite braucht: das Frontend und einen
OpenAI-kompatiblen **Stub-Modellserver**
(`frontend/e2e/stub-model-server.ts`) standardmäßig auf `127.0.0.1:4010`. Das
Backend und seine Datenbank müssen bereits laufen — die geseedete Owner-Rolle, das
Model Profile und der veröffentlichte Agent kommen aus
`agenticos cmd bootstrap`.

Beide Ports sind konfigurierbar, damit die Suite neben einem anderen Checkout
läuft, der die Voreinstellungen bereits hält — ein `bun run dev`, das auf 3000
offen geblieben ist, oder ein zweites Worktree. `E2E_PORT` verschiebt das
Frontend, `E2E_STUB_MODEL_PORT` den Stub, und `playwright.config.ts` leitet
`baseURL`, beide `webServer.url` und die `PORT`/`E2E_STUB_MODEL_PORT` der Server
daraus ab — nichts wird also zweimal über einen Port informiert.
`make test-e2e` liest alle drei (mit `E2E_BACKEND`) und gibt sie aus, bevor es
startet:

```bash
E2E_PORT=3100 make test-e2e          # frontend on 3100, stub on its default
```

Der Stub ist das, was `journey.spec.ts` einen Agent ohne Provider-Key von Anfang
bis Ende ausführen lässt: Er bedient die Chat-Completions-API, Streaming
eingeschlossen, und ein Model Profile erreicht ihn über das Feld **Endpoint**. Er
gibt das Token zurück, das die Instruktionen des Agents ihm zu sagen auftragen —
und das ist die Zusicherung, denn nichts anderes könnte dieses Token in die
Antwort bringen —, und liefert Usage, damit der Run bepreist wird und die letzte
Zusicherung des Wegs Kosten vorfindet. Er authentifiziert nichts und ruft keine
Tools auf; was er nicht beweist, ist, dass ein echter Provider antwortet.

Der Stub bindet an Loopback, und das Backend wählt ihn über dieses gespeicherte
Profile unter `127.0.0.1:<port>` an — das Backend muss sich das Loopback des Hosts
also teilen. Das ist der Pfad mit uvicorn auf dem Host, den CI fährt; ein Backend
in einem Container erreicht das `127.0.0.1` des Hosts nicht, und den Port zu
verschieben ändert daran nichts.

### Ein rotes `e2e` ist oft das Fixture, nicht das Produkt { #a-red-e2e-is-often-the-fixture-not-the-product }

`setup` und `seed` sind *Project Dependencies* von Playwright, ein Fehlschlag in
einem von beiden hält also die Projekte, die davon abhängen, überhaupt vom Laufen
ab. Die Zusammenfassung liest sich dann `1 failed`, `7 passed` und
`17 did not run`, was auf einem Pull Request genau wie ein kaputtes Feature
aussieht — und es nicht ist: **keine Produkt-Spec ist gelaufen.** Drei Branches
bezahlten dafür an einem Tag je eine Diagnose
([#132](https://github.com/vstorm-co/agenticos/issues/132)), deshalb gibt
`frontend/e2e/fixture-reporter.ts` jetzt ein Banner aus, das das sagt, und unter
CI eine GitHub-Fehlerannotation, die auf der Checks-Seite erscheint, ohne ein Log
zu öffnen.

### Auf eine Zeile zu warten heißt nicht, auf den Schreibvorgang zu warten { #waiting-for-a-row-is-not-waiting-for-the-write }

Eine Spec, die etwas über einen Dialog anlegt, **darf nicht** auf Submit klicken
und dann zusichern, dass die neue Zeile auf dem Bildschirm ist. Diese Form saß an
sechs Stellen und wurde an vieren beim Flackern beobachtet. Zwei Gründe, und der
zweite ist der teure:

- Das Fenster zwischen dem Auflösen der Mutation und dem Rendern der Liste ist
  real, und ein längerer `expect`-Timeout macht ein Race nur langsamer im
  Scheitern.
- **Ein offener Radix-Dialog nimmt den Rest der Seite aus dem
  Accessibility-Baum.** Solange einer auf dem Bildschirm ist, lösen
  `getByRole("main")`, `getByRole("row")` und jeder darauf gebaute Locator auf
  *nichts* auf, die Zusicherung läuft also mit `element(s) not found` in den
  Timeout, ganz gleich ob die Zeile existiert — und benennt damit das eine, was
  nicht die Ursache sein kann. Ein abgelehntes Anlegen sah bei vier einzelnen
  Vorfällen genauso aus wie ein langsames Nachladen.

`submitDialog` in `frontend/e2e/helpers.ts` ist der Weg hindurch: Es wartet auf
die eigene Antwort des Schreibvorgangs und sichert deren Status zu (eine Ablehnung
liest sich also als `409 … already exists`, in Millisekunden) und wartet dann
darauf, dass sich der Dialog schließt — und das ist die App, die sagt, dass sie
alles erledigt hat, was sie rund um den Schreibvorgang tut.

Was es bewusst nicht verspricht, ist, dass die Zeile jetzt gerendert ist, denn das
stimmt derzeit nicht: Das Nachladen der Liste wird manchmal mit der Liste von vor
dem Schreibvorgang beantwortet, obwohl die Zeile committet ist und beide
Serverschichten sie zurückgeben
([#230](https://github.com/vstorm-co/agenticos/issues/230), etwa bei einem von
acht Läufen). Also:

- **Ein Fixture-Schritt fragt die API, und fragt weiter.** Jeder Schritt von
  `seed.setup.ts` sichert über `/api/…` zu, denn seine Aufgabe ist, dass das
  Fixture existiert — und ein Fixture-Schritt, der scheitert, nimmt jede
  Produkt-Spec mit. Nach einem Schreibvorgang fragt er durch Pollen (`nowThere`),
  nie mit einem einzelnen Lesevorgang. Das begann als Behelf: Eine 2xx von diesem
  Backend hieß früher, dass die Anfrage beantwortet war, und nicht, dass der
  Schreibvorgang lesbar war, weil der Commit in einer Dependency lief, die FastAPI
  abwickelt, nachdem die Antwort hinaus ist
  ([#353](https://github.com/vstorm-co/agenticos/issues/353)). **Das ist behoben**
  — der Commit landet jetzt vor der Antwort — und das Pollen bleibt trotzdem, weil
  ein Fixture der falsche Ort ist, um zu entdecken, dass irgendein *anderer*
  Schreibvorgang langsamer ist als seine Bestätigung, und weil `nowThere` die
  Zeilen ausgibt, die es gesehen hat, wo ein einzelner Lesevorgang nichts ausgibt.
  Die Wache `alreadyThere`, mit der jeder Schritt öffnet, ist mit Absicht ein
  einzelner Lesevorgang, da sie vor dem Schreibvorgang läuft. Die eine Prüfung
  *nach* dem Schreibvorgang, die einmal las, kostete an einem Tag dreimal 87
  übersprungene Specs
  ([#335](https://github.com/vstorm-co/agenticos/issues/335)).
- **Eine Produkt-Spec, in der es um das Rendern geht, sagt das** und lädt zuerst
  neu, wenn sie eine Liste braucht, der sie trauen kann. `vault.spec.ts` hat drei
  `page.reload()`-Aufrufe, mit `#230` markiert; wenn dieses Issue schließt,
  kommen sie heraus.

## Die Testdatenbank { #test-database }

Die meisten Tests erreichen keine echte Datenbank. Die Fixture `client` in
`tests/conftest.py` übersteuert `get_db_session` über
`app.dependency_overrides` von FastAPI mit einer gemockten async-Session
(`AsyncMock`), die Suite läuft also schnell und braucht keinen Postgres-Container:

- `mock_db_session` — ein `AsyncMock`, das für eine `AsyncSession` einsteht (`execute`, `commit`, `rollback`, `close`)
- Overrides werden vor jedem Test registriert und danach geleert
- Sichern Sie gegen die Aufrufe des Mocks zu, oder stubben Sie die Rückgaben von `execute(...)` für den geprüften Pfad

Alles unter `tests/integration/` ist die Ausnahme, und es fragt nach der Fixture
`db` aus `tests/integration/conftest.py`, statt sich eine eigene Engine zu bauen —
diese Fixture ist das, was das Schema hinstellt.

**Das Schema wird einmal für den ganzen Prozess gebaut und die Daten zwischen den
Tests zurückgesetzt.**

Die Fixture `schema_url` führt `create_all` ein einziges Mal aus. Die
funktionsskopierte Fixture `engine` gibt dann jedem Test eine leere Datenbank,
indem sie jede Modelltabelle `TRUNCATE`-t — und jede Tabelle löscht, die ein Test
außerhalb der Modelle angelegt hat, ein zur Laufzeit entstandenes
`rag_<collection>` oder eine Sortierprobe —, statt das Schema neu zu bauen.

Früher lief vor *jedem* Test `drop_all` + `create_all`: ~0,4 s DDL, was nahezu die
gesamte Laufzeit einer Suite war, deren Zusicherungen Mikrosekunden an
Postgres-Arbeit sind. Es einmal zu bauen kürzte `tests/integration` von ~125 s auf
~50 s ([#215](https://github.com/vstorm-co/agenticos/issues/215)).

`TRUNCATE` statt eines Transaktions-Rollbacks, weil die Tests der API-Abläufe über
das echte `get_db_session` committen und ihre Zeilen ein Rollback überleben.

**Die Datenbank, die sie nutzt, gehört dem pytest-Prozess, der nach ihr gefragt
hat**: `<POSTGRES_DB>_p<pid>`, angelegt beim Start der Session und gelöscht, wenn
sie endet, Fehlschlag eingeschlossen.

Das ist es, was zwei gleichzeitige Läufe sicher macht — zwei Worktrees, oder ein
Worktree und ein `make test`, gegen den einen Postgres-Container — und es braucht
nichts, was auf der Kommandozeile übergeben wird.

Der Name war konstant bis
[#189](https://github.com/vstorm-co/agenticos/issues/189). Weil jeder Test auf
dieser geteilten Datenbank das Schema löschte und neu anlegte, verbrachten zwei
Läufe ihre Zeit damit, einander die Tabellen zu löschen, und meldeten Fehlschläge,
die zu keinem der beiden Branches gehörten.

!!! danger "Die Suite lehnt jede Datenbank ab, deren Name weder `test` noch `ci` enthält"

    Sie löscht Tabellen bedingungslos, diese Wache ist also das Einzige zwischen
    ihr und einer Entwicklungsdatenbank.

**Die Zugangsinformation wird einmal aufgelöst, in `tests/conftest.py`, und alles
liest sie vom Settings-Objekt zurück.**

Zwei Engines erreichen diese Datenbank — die der Fixture und die der Anwendung,
zur Importzeit in `app/db/session.py` gebaut —, und ein Test, der fragt, ob ein
Schreibvorgang sichtbar ist, braucht beide.

Früher lösten sie das Passwort getrennt auf, die Fixture mit dem Standardwert
`postgres`, wo `app/core/config.py` leer voreinstellt, und niemand konnte das
sehen, solange jeder Test über die Fixture verband.

Der erste Test, der die Engine der Anwendung antrieb, scheiterte auf einem
Checkout ohne `backend/.env` an der Authentifizierung — und das ist **jedes
git-Worktree**, da die Datei nicht versioniert ist. Zwei Fehlschläge gegen ein
volles Grün überall sonst, die sich genau wie eine Regression des Branches lasen
([#485](https://github.com/vstorm-co/agenticos/issues/485)).

Die Suite seedet jetzt `POSTGRES_PASSWORD=postgres`, bevor das Settings-Objekt
gebaut wird, und nur dann, wenn weder die Umgebung noch eine `.env` eines liefert,
ein echtes Passwort wird also nie durch den Standardwert ersetzt.

`app/core/config.py` stellt es weiterhin leer voreinstellt, und das ist es, was
eine fehlende `.env` sich in `alembic check` melden lässt, statt mit einer
Vermutung eine Datenbank zu erreichen.

### Die Migrations-Suite hat eine dritte { #the-migration-suite-has-a-third-one }

`tests/test_migrations.py` wendet die ganze Kette auf eine leere Datenbank an und
rollt sie auf base zurück, es kann also keine der beiden oben nutzen: Die
Integrationsdatenbank hat das Schema schon darin (aus den Modellen gebaut, was
eine andere Frage ist), und `downgrade base` gegen die der Unit-Suite würde sie
mitten im Lauf leeren. Es bekommt `agenticos_migrations_test_p<pid>`, angelegt vor
seinem ersten Test und gelöscht nach seinem letzten, und jedem alembic-Subprozess
wird dieser Name ausdrücklich übergeben, statt dass er `POSTGRES_DB` erbt.

Diese Datenbank musste früher schon existieren, und nichts legte sie je an, jeder
Test in dem Modul übersprang sich also in jedem CI-Lauf, den dieses Projekt hatte
— ein grüner Build über den einzigen Zusicherungen, dass `downgrade()` überhaupt
funktioniert ([#234](https://github.com/vstorm-co/agenticos/issues/234)). Es legt
jetzt eine eigene an, und der verbliebene Skip bedeutet nur, was er sagt: **kein
Postgres hat geantwortet.** In CI, wo ein Service-Container deklariert ist, ist
das stattdessen ein Fehlschlag — ein Container, der nicht startete, ist keine
Umgebung, die nicht antworten kann, und die beiden sind in der Ausgabe von pytest
nicht zu unterscheiden.

`make test-migrations` gibt es weiterhin und ist weiterhin das, was nach einer
Änderung an `alembic/versions/` von Hand zu laufen hat, aber es zeigt auf das, was
`backend/.env` sagt, und das ist auf einem Laptop die Datenbank mit Ihrer eigenen
Arbeit darin. Bevorzugen Sie `uv run pytest tests/test_migrations.py`, das sie
nicht erreichen kann.

## Prefect, und warum kein Test einen Server erreicht { #prefect-and-why-no-test-reaches-a-server }

**Einen `@flow` aufzurufen ist ein Netzwerkaufruf, und die Suite richtet ihn ins
Nirgendwo.** Prefect löst seine eigenen Settings aus `backend/.env` auf — sein
Settings-Modell trägt `env_file=".env"` —, also war
`PREFECT_API_URL=http://localhost:4200/api`, die Zeile, die `make dev` braucht,
auch die Adresse, die der `@flow`-Aufruf eines Tests zu erreichen versuchte. Ohne
laufenden Server ist das `RuntimeError: Failed to reach API at
http://localhost:4200/api/` aus einem Test heraus, der jeden seiner Mitspieler
gemockt hat, und CI sah es nie: Ohne `.env` gibt es keine URL, was ein Laptop
ausführte, war also nie das, was CI ausführte
([#536](https://github.com/vstorm-co/agenticos/issues/536)).

`tests/conftest.py` weist `PREFECT_API_URL` deshalb **leer** zu, bevor Prefect
importiert wird, neben dem Namen und dem Passwort der Datenbank oben und aus
demselben Grund.

Die Variable zu löschen genügte nicht: Eine nicht gesetzte Variable überlässt die
Antwort der dotenv-Quelle, und die dotenv-Quelle ist die, die die URL hält.

Eine leere Zuweisung schlägt sie, weil das Settings-Modell von Prefect
`env_ignore_empty=False` trägt — das ist Prefects Regel und nicht unsere.
`app/core/config.py` setzt es andersherum, dieselbe Zeile gegen eines *unserer*
Settings würde also verworfen und die `.env` antwortete trotzdem.

Prefect liest eine leere URL als keine URL und startet für den Aufruf einen
eigenen temporären Server, und genau das hat CI immer getan. Der Lauf hängt also
in keiner Richtung mehr davon ab, ob gerade ein Prefect-Server läuft.

**Der Zustand dieses Servers ist eine SQLite-Datenbank unter `PREFECT_HOME`, und
die Suite gibt ihm eine eigene.** Sich selbst überlassen ist das `~/.prefect`, ein
Unit-Lauf schriebe seine Flow Runs also in die Prefect-Daten einer Entwicklerin
und, wo Prefect auf dem Host statt in Docker läuft, in die Datei, die ein
laufender `prefect server` geöffnet hat. `tests/conftest.py` richtet es auf
`agenticos-prefect-test` unter dem temporären Verzeichnis des Systems, aus
demselben Grund, aus dem der Postgres-Name oben eine Testdatenbank ist. Ein
Verzeichnis statt eines je Prozess: Was kostet, ist das Anlegen.

Das Anlegen ist eine Migration, und die Suite hebt Prefects Zuteilung von 20
Sekunden für den Start dieses Servers auf 90 — **als Reserve, nicht weil 20 je
gescheitert wäre.** Gegen ein `PREFECT_HOME`, in das noch nichts geschrieben hat,
dauert der ganze Start etwa sechs Sekunden auf einem Laptop und etwa neun auf
einem CI-Container, der in jedem Lauf kalt ist und auf dem Standardwert nie rot
war. Die erhöhte Zuteilung kauft, dass der eine Schritt, dessen Kosten hier
nichts begrenzt — eine Migration auf einer belegten Maschine oder ein
temporäres Verzeichnis, das leergefegt wurde —, wartet, statt eine Suite scheitern
zu lassen, die ein zweiter Lauf bestehen würde.
`tests/test_prefect_test_environment.py` pinnt alle vier Eigenschaften.

## Zusammenfassung { #recap }

- **Vier Ebenen**: Unit, Integration, API, E2E. Wählen Sie danach, was für den
  Test wahr sein muss, nicht danach, worum es in ihm geht.
- Async-Tests nutzen **anyio**. `@pytest.mark.asyncio` tut hier nichts.
- **Decken Sie die Ablehnung ab.** Der meiste Wert dieser Plattform liegt in dem,
  was sie ablehnt.
- Die Plattformschicht steht auf **100 %**, und ein Modul dorthin aufzunehmen
  heißt, zwei Listen in `backend/pyproject.toml` zu bearbeiten.
- Die Reihenfolge wird in jedem Lauf gemischt; spielen Sie einen Fehlschlag mit
  dem ausgegebenen Seed nach, bevor Sie irgendetwas über die Änderung schließen.
