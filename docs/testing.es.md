---
source_sha: dba14340bbd8
---

# Pruebas { #testing }

Cuatro capas, un solo runner y una puerta de cobertura que tumba la build por debajo
del 100% en la capa de plataforma.

La versión corta de qué ejecutar: los tests que cubren el cambio mientras escribes, y
las suites una vez antes de hacer push.

## Ejecutar los tests { #running-tests }

!!! tip "Mientras escribes, ejecuta lo que cubre el cambio; la suite es la puerta previa al push"

    Un archivo responde en aproximadamente un segundo donde la suite tarda minuto y
    medio, y dice lo mismo sobre el cambio.

```bash
cd backend

uv run pytest tests/test_capability_registry.py -q         # one file
uv run pytest tests/test_capability_registry.py -k drift   # one behaviour
uv run pytest tests/api/test_workspace_routes.py -x -v     # stop at the first failure
uv run pytest tests/integration -v --no-cov                # the ones needing a database
```

Estos van en **serie** a propósito: lanzar workers para un solo archivo cuesta más que
el archivo. Los objetivos de suite completa —`make test`, `make test-fast`,
`make test-integration`, `make test-cov`— se reparten entre workers
(`pytest -n auto --maxprocesses 4`), lo que casi reduce a la mitad la suite de
integración, limitada por E/S; `pytest-cov` combina los datos de cada worker, así que
la puerta del 100% sigue igual. El tope es cuatro porque la suite unitaria depende de
los imports —cada worker importa la aplicación una vez— y no gana nada más, mientras
un `auto` sin tope en un portátil multinúcleo es *más lento* que en serie, todo ello
arranque de workers (#520).

!!! warning "Cada ejecución se baraja, y un test que pasó ayer puede haber estado dependiendo del orden"

    `pytest-randomly` imprime la semilla en la cabecera
    (`Using --randomly-seed=1697040112`). Repite esa semilla **en serie** para
    recuperar el mismo orden: `-n auto` no fija qué worker ejecuta qué.

Un test que depende del orden —uno que pasa solo porque algo anterior dejó estado
detrás— es el clásico "verde en mi portátil, rojo en CI", y una suite que siempre corre
en orden de recolección nunca hace la pregunta. CI la hace en un orden nuevo cada
ejecución.

```bash
uv run pytest tests/ -q --randomly-seed=1697040112   # that order again, serially
uv run pytest tests/ -q -p no:randomly               # collection order, while bisecting
```

La semilla la elige el controlador una vez y se entrega a cada worker de xdist, así que
`-n auto` recoge un orden y no cuatro. No fija qué worker ejecuta qué: `make test` deja
xdist en su `--dist load` por defecto, que entrega cada test al worker que esté libre.
Un fallo que dependía de lo que compartía worker —el `InterfaceError` que encontró #571
es uno— vuelve repitiendo la semilla *en serie*, como arriba, y no reejecutando
`make test`. El plugin además resiembra `random` igual antes de cada test, así que
cualquier cosa que lo use para unicidad es única dentro de un test y se repite entre
ellos.

Hasta #571 el plugin estaba documentado pero no instalado, `-p no:randomly` no hacía
nada en silencio, y nada había ejercitado nunca esa afirmación.

Una vez, antes del push — `make check` lo ejecuta todo, en este orden:

```bash
make lint               # ruff, ruff format, ty, vulture, deptry, eslint, prettier, tsc, the guards
make test               # the suite plus the 100% gate on the platform layer
make db-check           # alembic check — a model change with no migration fails here
make test-frontend-cov  # the frontend suite plus its own gate
make build-frontend     # next build — the route tree, which tsc and vitest do not see
make docs-build         # mkdocs --strict — a dead link is a failure
make audit              # the locked dependency set against the advisory database
```

Unos cinco minutos en serie, frente a los doce de CI en paralelo — con el job `test`
del backend como el cuello de botella de allí, que es lo que #520 está recortando. La
igualdad se mantiene en vez de afirmarse: el workflow llama a estos objetivos en vez de
repetir sus comandos, y `tests/test_ci_parity.py` falla si un job de los que bloquean
gana un paso que `make check` no ejecuta. Se ha desviado cuatro veces — ver
[Comandos](commands.md#before-a-pull-request) para lo que `check` deja fuera y por qué.

!!! info "CI puede ejecutar menos jobs que `check`, y eso no es una desviación"

    `test`, `test-frontend` y `e2e` se saltan en un pull request cuyas rutas
    modificadas no pueden afectarlos, y un check obligatorio en `skipped` deja pasar
    igualmente un merge. En local no hay equivalente: `check` lo ejecuta todo.

Un cambio solo de documentación no ejecuta ninguno de los tres; uno solo de backend no
ejecuta ninguna suite de frontend. Quien decide es `scripts/ci_changed_scope.py`, yerra
hacia ejecutar, y [Ramas](branching.md#a-required-check-may-legitimately-report-skipped)
tiene la regla.

!!! danger "Dos formas de hacer push de algo que no se ha verificado"

    `make test-fast` se salta la cobertura, lo que lo convierte en la última palabra
    equivocada antes de un push: la puerta es casi todo para lo que existen estos
    comandos. Y `pytest` sin `uv run` coge el intérprete que haya en el path en vez
    del 3.12 fijado.

## Estructura de los tests { #test-structure }

Cuatro capas, y a cuál pertenece un test lo decide lo que necesita, no de qué trata.

```
backend/tests/
├── conftest.py          # the shared fixtures, and the test database's name
├── test_*.py            # unit: one module, its dependencies mocked at the repository boundary
├── api/                 # the app driven through `client`, grouped by the question asked
└── integration/
    └── conftest.py      # creates a database of its own, and drops it afterwards
```

`tests/api/` está agrupado por **qué se está preguntando**, no por módulo de rutas:
algunos archivos toman un solo endpoint (`test_admin_ratings_window.py`), y
`test_platform_routes.py` barre una familia entera de una vez, que es por lo que
`agents.py` no tiene archivo propio. Busca la pregunta antes de buscar la ruta.

| Capa | Dónde | Para qué |
|---|---|---|
| Unitaria | `tests/test_*.py` | Un módulo. Los repositorios se mockean; el servicio bajo prueba nunca |
| API | `tests/api/`, y algunos en el nivel superior | La ruta: su puerta, su código de estado, qué llega al servicio |
| Integración | `tests/integration/` | Lo que solo responde una base de datos: un `ORDER BY`, un borrado en cascada, una restricción de unicidad, una consulta que de verdad está acotada al tenant |
| E2E | `frontend/e2e/` | Recorridos que cruzan todo el sistema — ver [Tests del frontend](#frontend-tests) |

No hay directorio `tests/unit/`: un test unitario es un `test_*.py` en la raíz de
`tests/`. La capa es **lo que un test necesita, no dónde está**, y el nivel superior
tiene bastantes que mueven la aplicación con un `AsyncClient` propio:
`test_rag_document_listing.py`, `test_oauth_signin_exchange.py`,
`test_security_headers.py`. Buscar cobertura de rutas existente solo bajo `tests/api/`
los dejará fuera.

**Una excepción, y está en el nivel superior en vez de en `integration/`.**
`tests/test_migrations.py` recorre la cadena entera de Alembic contra una base de datos
real, que él mismo crea y borra bajo un nombre propio, porque `downgrade base` borra
todas las tablas y heredar `POSTGRES_DB` vació una vez la base de datos de trabajo de
alguien. Lo recoge un `pytest tests/` corriente. No está en `integration/` porque no
usa en absoluto el fixture `db` de ese paquete: ejecuta `alembic` en subprocesos.

## Async: anyio, no pytest-asyncio { #async-anyio-not-pytest-asyncio }

```python
import pytest

pytestmark = pytest.mark.anyio   # at the top of the module
```

o `@pytest.mark.anyio` sobre el test, que es lo que hace `tests/api/test_users.py`
donde solo parte del archivo es asíncrona. Las dos formas valen; la de módulo es la
costumbre aquí porque casi todos los archivos son asíncronos de principio a fin.

!!! warning "`@pytest.mark.asyncio` no funciona aquí, y no hay ningún `asyncio_mode` que lo arregle"

    La suite corre sobre **anyio**. Un `async def` sin marcar falla en la recolección
    con un mensaje sobre el framework y no sobre el test, así que se lee como un
    entorno roto nada más entrar.

Un `async def` sin marcar no es un aprobado silencioso: pytest 9 lo falla en la
recolección con *"async def functions are not natively supported"* y lista los plugins
que lo arreglarían. El fixture `anyio_backend` fija `asyncio`, porque es lo que ejecuta
uvicorn.

## Fixtures clave (`tests/conftest.py`) { #key-fixtures-testsconftestpy }

Cinco. Ninguno es un `test_user` ni un cliente con sesión iniciada, y ese es el punto:
un llamante autenticado es un override de dependencia, así que un test dice qué
autoridad está ejercitando en vez de heredar una. `tests/api/test_users.py` construye un
`auth_client` propio con exactamente esos overrides: un fixture local para el archivo
que lo necesita, no uno compartido que heredan todos.

| Fixture | |
|---|---|
| `anyio_backend` | Fija `asyncio`, y nadie lo nombra: lo pide anyio |
| `client` | `httpx.AsyncClient` sobre `ASGITransport(app=app)` — **no** el `TestClient` de Starlette. Sobrescribe `get_db_session` y `get_redis`, y limpia `app.dependency_overrides` después |
| `mock_db_session` | Un `AsyncMock`. Su `info` es un dict de verdad, porque ahí es donde `spawn_after_commit` encola trabajo |
| `mock_redis` | Un `MagicMock(spec=RedisClient)` con los métodos asíncronos simulados |
| `api_key_headers` | La cabecera de servicio a servicio, para una ruta detrás de `ValidAPIKey` |

`tests/integration/conftest.py` añade los que tocan una base de datos. El paquete
rechaza cualquier base de datos cuyo nombre no contenga ni `test` ni `ci`, y vacía todas
las tablas entre tests. **Solo se salta a sí mismo cuando no hay ninguna alcanzable
fuera de CI**: con `CI` puesto lanza un error, porque un salto y un servicio de Postgres
que no arrancó se leen igual en la salida de pytest y solo uno de los dos es aceptable
en un runner.

| Fixture | |
|---|---|
| `db` | Una `AsyncSession` real: lo que toma casi todo test de integración |
| `engine` | El `AsyncEngine` que hay detrás, para un test que necesita una sesión que `db` no puede ser: *más de una* — una carrera, una escritura concurrente, dos transacciones que tienen que entrelazarse, donde una `AsyncSession` compartida entre ellas no es una segunda conexión sino una corrompida— o una que el código bajo prueba se crea para sí mismo, que es como los tests de RAG le dan a `PgVectorStore` su propio `async_sessionmaker`. Lo toman dieciocho archivos |
| `database_url`, `schema_url` | De alcance de sesión, y la razón por la que los dos de arriba son seguros: nombran la base de datos desechable y crean su esquema una sola vez |

## Escribir tests { #writing-tests }

Nombra el comportamiento, no la función, para que un fallo diga qué se rompió:
`test_a_grant_widens_access_without_promoting_the_member`, no `test_resolve`.

### Un test de servicio { #a-service-test }

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

El repositorio se mockea y el servicio no. Un test que mockea aquello que está probando
pasa cuando la implementación se borra.

### Un test de API { #an-api-test }

El llamante es un override, que es lo que hace que el rechazo se pueda probar:

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

`tests/api/test_platform_routes.py` hace esto barriendo, en vez de con una aserción por
ruta: la puerta que lleva una ruta es una tabla, y una tabla se recorre en vez de
repetirse. Recorre los **prefijos de plataforma** —`/agents`, `/runs`, `/approvals`,
`/spend`, `/stats`, `/skills` y el resto de `_PLATFORM_PREFIXES`—, que es por lo que casi
ninguno de esos tiene archivo propio, y por lo que `/auth`, `/organizations` y `/users`
siguen necesitando el suyo: el barrido pasa de largo sobre ellos.

### Un test de integración { #an-integration-test }

Solo para lo que una sesión mockeada no puede responder, que suele ser una ordenación,
una restricción o un borrado en cascada. `tests/integration/test_message_order.py` es la
forma: un turno escribe su pregunta y su respuesta dentro de una transacción, así que
ambas filas llevan el mismo `created_at` al microsegundo y el empate lo desempata una
columna y no el planificador.

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

Aquel bug *era* de Postgres, y una sesión mockeada habría pasado contra el esquema que
no tenía desempate ninguno.

### Qué merece un test aquí { #what-is-worth-a-test-here }

!!! important "Cubre el rechazo"

    Casi todo el valor de esta plataforma está en lo que rechaza, así que el rechazo
    es el caso que tiene que existir:

    - una lectura entre tenants — **incluida una en la que el llamante es dueño de la
      fila**;
    - un alcance no concedido;
    - un budget comprobado *antes* de la petición al modelo, y registrado incluso
      cuando el run falla;
    - un spec rechazado al publicar y no en tiempo de ejecución;
    - ningún secreto en claro en ninguna respuesta, línea de log o entrada de
      auditoría.

`.claude/rules/testing.md` y el skill `backend-tests` llevan el resto: las trampas, los
ejemplos resueltos y la historia detrás de cada uno. Esta página es la forma de la
suite; ninguna repite a la otra.

## Tests del frontend { #frontend-tests }

Ejecútalos desde `frontend/`. En la raíz del repositorio vitest no encuentra
configuración, informa de bastante más de cien fallos fantasma y deja un `node_modules/`
suelto.

```bash
cd frontend

bunx vitest run src/components/chat/usage-strip.test.tsx   # one spec, ~2s
bunx vitest run src/components/chat                        # one directory
bun run test                                               # watch mode
bun run test:coverage                                      # the suite plus the gate CI applies
bun run test:e2e                                           # Playwright
bun run test:e2e --headed                                  # ...with a browser to watch
```

**`bun run test:run` no mide cobertura**, así que no puede responder si el job
`test-frontend` va a pasar: la puerta quiere el 100% de líneas, sentencias y funciones y
el 97,5% de ramas sobre `src/{app/api,lib,stores,hooks}` y casi todo `src/components`.

### Dos plazos, ambos dimensionados para una máquina cargada { #two-deadlines-both-sized-for-a-loaded-machine }

Un spec con mucho renderizado no es lento por estar mal escrito; es lento porque varios
miles de ellos comparten diez núcleos con lo que sea que esté corriendo. `testTimeout` en
`vitest.config.ts` es de **15 s** y el `asyncUtilTimeout` de Testing Library en
`vitest.setup.ts` es de **5 s**, ambos subidos desde unos valores por defecto que solo
aguantan en una máquina ociosa.

Los números vienen de ejecutar la suite entera de cuatro maneras
([#862](https://github.com/vstorm-co/agenticos/issues/862)):

| Test individual más lento | Desnudo | Con `--coverage` |
|---|---|---|
| Diez núcleos ociosos | 1,7 s | 2,9 s |
| Con 32 bucles ocupados al lado | 5,4 s | 6,1 s |

Con esa carga el viejo valor por defecto de 5 s fallaba tres tests por ejecución — tres
*distintos* cada vez, porque qué archivos comparten worker se decide por tiempos, y
tanto en la ejecución desnuda como en la instrumentada. La instrumentación cuesta
alrededor de 1,6 veces el tiempo total de test en una máquina tranquila y es el
multiplicador menor; el resto es latencia de planificación. Por eso ninguno de los dos
plazos depende de `--coverage`: un límite sobre el que el bucle rápido y la puerta no se
ponen de acuerdo es uno que no puede reproducir la puerta.

`asyncUtilTimeout` se queda bien por debajo de `testTimeout` a propósito. Un elemento que
no va a llegar nunca debería perder la carrera, para que el fallo diga *"Unable to find
an element with the text: …"* y lo nombre, en vez de *"Test timed out"*, que no nombra
nada.

Ninguno de los dos números es licencia para un spec que hace más trabajo del que sus
aserciones leen: montar cuarenta filas de tabla dos veces para demostrar un recuento
costaba unos dos segundos en `rag/[id]/counts.integration.test.tsx` antes de que su
fixture se recortara a tres.

Playwright arranca lo que la suite necesita: el frontend y un **servidor de modelo de
prueba** compatible con OpenAI (`frontend/e2e/stub-model-server.ts`) en
`127.0.0.1:4010` por defecto. El backend y su base de datos tienen que estar ya
levantados — el propietario sembrado, el perfil de modelo y el agent publicado vienen de
`agenticos cmd bootstrap`.

Ambos puertos son configurables, para que la suite corra junto a otro checkout que ya
ocupa los valores por defecto — un `bun run dev` dejado arriba en el 3000, o un segundo
worktree. `E2E_PORT` mueve el frontend, `E2E_STUB_MODEL_PORT` el stub, y
`playwright.config.ts` deriva de ellos el `baseURL`, ambas `webServer.url` y los
`PORT`/`E2E_STUB_MODEL_PORT` de los servidores — así que a nada se le dice un puerto dos
veces. `make test-e2e` lee los tres (con `E2E_BACKEND`) y los imprime antes de empezar:

```bash
E2E_PORT=3100 make test-e2e          # frontend on 3100, stub on its default
```

El stub es lo que permite a `journey.spec.ts` ejecutar un agent de punta a punta sin una
clave de provider: sirve la API de Chat Completions, streaming incluido, y un perfil de
modelo llega a él por el campo **Endpoint**. Devuelve el token que las instrucciones del
agent le dicen que diga —que es la aserción, ya que nada más podría poner ese token en la
respuesta— y devuelve el uso, así que el run se tarifa y la última aserción del recorrido
tiene un coste que encontrar. No autentica nada ni llama a herramientas; lo que no
demuestra es que responda un provider real.

El stub se ata al loopback, y el backend lo marca en `127.0.0.1:<port>` a través de ese
perfil guardado — así que el backend tiene que compartir el loopback de la máquina. Ese
es el camino de uvicorn en el host que ejecuta CI; un backend dentro de un contenedor no
puede alcanzar el `127.0.0.1` del host, y mover el puerto no cambia eso.

### Un `e2e` en rojo suele ser el fixture, no el producto { #a-red-e2e-is-often-the-fixture-not-the-product }

`setup` y `seed` son *dependencias de proyecto* de Playwright, así que un fallo en
cualquiera de los dos impide que lleguen a ejecutarse los proyectos que dependen de él.
El resumen dice entonces `1 failed`, `7 passed` y `17 did not run`, lo que en un pull
request parece exactamente una funcionalidad rota — y no lo es: **no se ejecutó ningún
spec de producto.** Tres ramas pagaron cada una ese diagnóstico en un solo día
([#132](https://github.com/vstorm-co/agenticos/issues/132)), así que
`frontend/e2e/fixture-reporter.ts` imprime ahora un aviso diciéndolo, y bajo CI una
anotación de error de GitHub que se ve en la página de checks sin abrir un log.

### Esperar a una fila no es esperar a la escritura { #waiting-for-a-row-is-not-waiting-for-the-write }

Un spec que crea algo a través de un diálogo **no debe** pulsar enviar y luego afirmar
que la fila nueva está en pantalla. Esa forma estaba en seis sitios y se vio flakear en
cuatro. Dos razones, y la segunda es la cara:

- La ventana entre que la mutación se resuelve y la lista se renderiza es real, y un
  timeout de `expect` más largo solo hace que una carrera tarde más en fallar.
- **Un diálogo de Radix abierto saca del árbol de accesibilidad al resto de la página.**
  Mientras hay uno en pantalla, `getByRole("main")`, `getByRole("row")` y todos los
  locators construidos sobre ellos resuelven a *nada*, así que la aserción expira con
  `element(s) not found` exista la fila o no — nombrando lo único que no puede ser la
  causa. Un create rechazado se veía idéntico a un refetch lento en cuatro ocasiones
  distintas.

`submitDialog`, en `frontend/e2e/helpers.ts`, es la vía: espera a la respuesta de la
propia escritura y afirma su estado (así que un rechazo se lee como
`409 … already exists`, en milisegundos), y después espera a que el diálogo se cierre,
que es la aplicación diciendo que ha terminado todo lo que hace alrededor de la
escritura.

Lo que a propósito no promete es que la fila esté ya renderizada, porque eso hoy no es
cierto: al refetch de la lista se le responde a veces con la lista previa a la escritura
aunque la fila esté confirmada y ambas capas del servidor la devuelvan
([#230](https://github.com/vstorm-co/agenticos/issues/230), en torno a una ejecución de
cada ocho). Así que:

- **Un paso de fixture le pregunta a la API, y sigue preguntando.** Cada paso de
  `seed.setup.ts` afirma a través de `/api/…`, porque su trabajo es que el fixture
  exista — y un paso de fixture que falla se lleva por delante todos los specs de
  producto. Después de una escritura pregunta sondeando (`nowThere`), nunca con una sola
  lectura. Eso empezó como un apaño: un 2xx de este backend significaba antes que la
  petición se había respondido y no que la escritura fuera legible, porque el commit
  corría en una dependencia que FastAPI desenrolla después de que la respuesta haya
  salido ([#353](https://github.com/vstorm-co/agenticos/issues/353)). **Eso está
  arreglado** —el commit aterriza ahora antes que la respuesta— y el sondeo se queda de
  todos modos, porque un fixture es el sitio equivocado para descubrir que *otra*
  escritura es más lenta que su acuse, y porque `nowThere` imprime las filas que sí vio
  donde una sola lectura no imprime nada. La guarda `alreadyThere` con la que abre cada
  paso es una sola lectura a propósito, ya que corre antes de la escritura. La única
  comprobación *posterior a la escritura* que leyó una sola vez costó 87 specs saltados
  tres veces en un día ([#335](https://github.com/vstorm-co/agenticos/issues/335)).
- **Un spec de producto que trata del renderizado lo dice**, y recarga primero si
  necesita una lista de la que fiarse. `vault.spec.ts` tiene tres llamadas a
  `page.reload()` marcadas con `#230`; cuando ese issue se cierre, salen.

## La base de datos de pruebas { #test-database }

Casi ningún test toca una base de datos real. El fixture `client` de
`tests/conftest.py` sobrescribe `get_db_session` con una sesión asíncrona mockeada
(`AsyncMock`) mediante el `app.dependency_overrides` de FastAPI, así que la suite corre
rápido y no necesita un contenedor de Postgres:

- `mock_db_session` — un `AsyncMock` que hace de `AsyncSession` (`execute`, `commit`, `rollback`, `close`)
- Los overrides se registran antes de cada test y se limpian después
- Afirma contra las llamadas del mock, o simula los valores de retorno de `execute(...)` para el camino bajo prueba

Todo lo que hay bajo `tests/integration/` es la excepción, y pide el fixture `db` de
`tests/integration/conftest.py` en vez de construirse un engine propio: ese fixture es
lo que pone el esquema en su sitio.

**El esquema se construye una vez para todo el proceso, y los datos se reinician entre
tests.**

El fixture `schema_url` ejecuta `create_all` una sola vez. El fixture `engine`, de
alcance de función, le entrega después a cada test una base de datos vacía haciendo
`TRUNCATE` de todas las tablas de los modelos —y borrando cualquier tabla que un test
creara fuera de los modelos, una `rag_<collection>` en tiempo de ejecución o una sonda
de ordenación— en vez de reconstruir el esquema.

Antes hacía `drop_all` + `create_all` antes de *cada* test: unos 0,4 s de DDL que eran
casi por completo el tiempo de ejecución de una suite cuyas aserciones son microsegundos
de trabajo de Postgres. Construirlo una vez bajó `tests/integration` de unos 125 s a
unos 50 s ([#215](https://github.com/vstorm-co/agenticos/issues/215)).

`TRUNCATE` en vez de un rollback de transacción, porque los tests de flujo de la API
confirman a través del `get_db_session` real y sus filas sobreviven a un rollback.

**La base de datos que usa pertenece al proceso de pytest que la pidió**:
`<POSTGRES_DB>_p<pid>`, creada cuando la sesión arranca y borrada cuando termina, fallos
incluidos.

Eso es lo que hace seguras dos ejecuciones a la vez —dos worktrees, o un worktree y un
`make test`, contra el único contenedor de Postgres— y no necesita que se pase nada en
la línea de comandos.

El nombre fue constante hasta
[#189](https://github.com/vstorm-co/agenticos/issues/189). Como cada test borraba y
recreaba el esquema en esa base de datos compartida, dos ejecuciones se pasaban el
tiempo borrándose las tablas la una a la otra e informando de fallos que no eran de
ninguna de las dos ramas.

!!! danger "La suite rechaza cualquier base de datos cuyo nombre no contenga `test` o `ci`"

    Borra tablas sin condiciones, así que esa guarda es lo único que hay entre ella y
    una base de datos de desarrollo.

**La credencial se resuelve una vez, en `tests/conftest.py`, y todo lo demás la lee de
vuelta del objeto de settings.**

Dos engines llegan a esa base de datos —el del fixture y el de la aplicación, construido
en tiempo de import en `app/db/session.py`— y un test que pregunta si una escritura es
visible necesita los dos.

Antes resolvían la contraseña por separado, con el fixture por defecto en `postgres`
donde `app/core/config.py` la deja vacía, y nada podía verlo mientras todos los tests se
conectaban a través del fixture.

El primer test que movió el engine de la aplicación no logró autenticarse en un checkout
sin `backend/.env` — es decir, en **cualquier worktree de git**, al no estar el archivo
versionado. Dos fallos contra un verde completo en todo lo demás, que se leían
exactamente como una regresión de rama
([#485](https://github.com/vstorm-co/agenticos/issues/485)).

La suite siembra ahora `POSTGRES_PASSWORD=postgres` antes de que se construya el objeto
de settings, y solo cuando ni el entorno ni un `.env` aportan una, para que una
contraseña real nunca se sustituya por la de por defecto.

`app/core/config.py` la sigue dejando vacía por defecto, que es lo que hace que un
`.env` ausente se anuncie en `alembic check` en vez de llegar a una base de datos con
una suposición.

### La suite de migraciones tiene una tercera { #the-migration-suite-has-a-third-one }

`tests/test_migrations.py` aplica la cadena entera a una base de datos vacía y la
revierte hasta base, así que no puede usar ninguna de las dos anteriores: la de
integración ya tiene el esquema dentro (construido desde los modelos, que es otra
pregunta), y `downgrade base` contra la de la suite unitaria la vaciaría a media
ejecución. Recibe `agenticos_migrations_test_p<pid>`, creada antes de su primer test y
borrada tras el último, y a cada subproceso de alembic se le pasa ese nombre de forma
explícita en vez de heredar `POSTGRES_DB`.

Esa base de datos tenía antes que existir ya, y nada la creaba nunca, así que todos los
tests del módulo se saltaban en cada ejecución de CI que este proyecto ha tenido — una
build verde sobre las únicas aserciones de que `downgrade()` funciona
([#234](https://github.com/vstorm-co/agenticos/issues/234)). Ahora crea la suya, y el
salto que sobrevive significa solo lo que dice: **no respondió ningún Postgres.** En CI,
donde hay un contenedor de servicio declarado, eso es un fallo en su lugar — un
contenedor que no arrancó no es un entorno que no puede responder, y los dos son
indistinguibles en la salida de pytest.

`make test-migrations` sigue existiendo y sigue siendo lo que hay que ejecutar a mano
después de tocar `alembic/versions/`, pero apunta a lo que diga `backend/.env`, que en un
portátil es la base de datos con tu propio trabajo dentro. Prefiere
`uv run pytest tests/test_migrations.py`, que no puede alcanzarla.

## Prefect, y por qué ningún test alcanza un servidor { #prefect-and-why-no-test-reaches-a-server }

**Llamar a un `@flow` es una llamada de red, y la suite la apunta a ninguna parte.**
Prefect resuelve sus propios ajustes desde `backend/.env` —su modelo de settings lleva
`env_file=".env"`— así que `PREFECT_API_URL=http://localhost:4200/api`, la línea que
`make dev` necesita, era también la dirección que intentaba alcanzar la llamada a
`@flow` de un test. Sin un servidor levantado eso es
`RuntimeError: Failed to reach API at http://localhost:4200/api/` saliendo de un test que
mockeaba a todos sus colaboradores, y CI nunca lo vio: sin `.env` no hay URL, así que lo
que ejecutaba un portátil nunca fue lo que ejecutaba CI
([#536](https://github.com/vstorm-co/agenticos/issues/536)).

Por eso `tests/conftest.py` asigna `PREFECT_API_URL` **vacía** antes de que se importe
Prefect, junto al nombre y la contraseña de la base de datos de arriba y por la misma
razón.

Borrar la variable no valdría: una variable sin fijar deja que responda la fuente dotenv,
y la fuente dotenv es la que tiene la URL.

Una asignación vacía le gana porque el modelo de settings de Prefect lleva
`env_ignore_empty=False` — que es la regla de Prefect y no la nuestra.
`app/core/config.py` lo fija al revés, así que la misma línea contra uno de *nuestros*
ajustes se descartaría y el `.env` respondería igualmente.

Prefect lee una URL vacía como ninguna URL y arranca un servidor temporal propio para la
llamada, que es lo que CI ha hecho siempre. Así que la ejecución ya no depende de si hay
un servidor de Prefect levantado, en ninguno de los dos sentidos.

**El estado de ese servidor es una base de datos SQLite bajo `PREFECT_HOME`, y la suite
le da una propia.** Si se deja en paz es `~/.prefect`, así que una ejecución unitaria
escribiría sus flow runs en los datos de Prefect de quien desarrolla y, donde Prefect
corre en el host y no en Docker, en el archivo que un `prefect server` en marcha tiene
abierto. `tests/conftest.py` lo apunta a `agenticos-prefect-test` bajo el directorio
temporal del sistema, por la misma razón por la que el nombre de Postgres de arriba es
una base de datos de pruebas. Un directorio y no uno por proceso: lo que cuesta es
crearlo.

Crearlo es una migración, y la suite sube de 20 a 90 segundos el margen de Prefect para
arrancar ese servidor — **como holgura, no porque 20 haya fallado nunca.** Contra un
`PREFECT_HOME` aún sin escribir, el arranque entero tarda unos seis segundos en un
portátil y unos nueve en un contenedor de CI, frío en cada ejecución y nunca rojo con el
valor por defecto. El margen ampliado compra que el único paso cuyo coste nada acota aquí
—una migración en una máquina disputada, o un directorio temporal ya barrido— espere en
vez de tumbar una suite que una segunda ejecución pasaría.
`tests/test_prefect_test_environment.py` fija las cuatro propiedades.

## Resumen { #recap }

- **Cuatro capas**: unitaria, de integración, de API y E2E. Elige por lo que el test
  necesita que sea cierto, no por de qué trata.
- Los tests asíncronos usan **anyio**. `@pytest.mark.asyncio` no hace nada aquí.
- **Cubre el rechazo.** Casi todo el valor de esta plataforma está en lo que rechaza.
- La capa de plataforma está al **100%**, y añadirle un módulo significa editar dos
  listas en `backend/pyproject.toml`.
- El orden se baraja en cada ejecución; reproduce un fallo con la semilla impresa antes
  de concluir nada sobre el cambio.
