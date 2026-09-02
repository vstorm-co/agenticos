# Testing

Four layers, one runner, and a coverage gate that fails the build below 100% on the
platform layer.

The short version of what to run: the tests that cover the change while you are
writing, and the suites once before you push.

## Running tests

!!! tip "While writing, run what covers the change; the suite is the pre-push gate"

    A file answers in about a second where the suite takes a minute and a half,
    and says the same thing about the change.

```bash
cd backend

uv run pytest tests/test_capability_registry.py -q         # one file
uv run pytest tests/test_capability_registry.py -k drift   # one behaviour
uv run pytest tests/api/test_workspace_routes.py -x -v     # stop at the first failure
uv run pytest tests/integration -v --no-cov                # the ones needing a database
```

These stay **serial** on purpose: spawning worker processes to run one file costs
more than the file does. The whole-suite targets — `make test`, `make test-fast`,
`make test-integration`, `make test-cov` — run across workers (`pytest -n auto --maxprocesses 4`),
which roughly halves the I/O-bound integration suite; `pytest-cov` combines the
per-worker data, so the 100% gate is unchanged. The cap is four because the unit
suite is import-bound — every worker imports the app once — and gains nothing past
that, while an uncapped `auto` on a many-core laptop is *slower* than serial, all of
it worker startup (#520).

!!! warning "Every run is shuffled, and a test that passed yesterday may have been depending on the order"

    `pytest-randomly` prints the seed in the header
    (`Using --randomly-seed=1697040112`). Replay that seed **serially** to get
    the same order back - `-n auto` does not fix which worker runs what.

An order-dependent test — one that passes only
because something before it left state behind — is the classic "green on my laptop,
red in CI", and a suite that always runs in collection order never asks the question.
CI asks it in a fresh order every run.

```bash
uv run pytest tests/ -q --randomly-seed=1697040112   # that order again, serially
uv run pytest tests/ -q -p no:randomly               # collection order, while bisecting
```

The seed is chosen once by the controller and handed to each xdist worker, so `-n auto`
collects one order rather than four. It does not fix which worker runs what: `make test`
leaves xdist on its default `--dist load`, which hands each test to whichever worker is
free. So a failure that depended on what shared a worker — the `InterfaceError` #571
found is one — comes back by replaying the seed *serially*, as above, and not by
re-running `make test`. The plugin also reseeds `random` identically before every test,
so anything using it for uniqueness is unique within a test and repeats across them.

Until #571 the plugin was documented but not installed, `-p no:randomly` was a silent
no-op, and nothing had ever exercised the claim.

Once, before pushing — `make check` runs all of it, in this order:

```bash
make lint               # ruff, ruff format, ty, vulture, deptry, eslint, prettier, tsc, the guards
make test               # the suite plus the 100% gate on the platform layer
make db-check           # alembic check — a model change with no migration fails here
make test-frontend-cov  # the frontend suite plus its own gate
make build-frontend     # next build — the route tree, which tsc and vitest do not see
make docs-build         # mkdocs --strict — a dead link is a failure
make audit              # the locked dependency set against the advisory database
```

About five minutes serial, against CI's twelve in parallel — the backend `test`
job the long pole there, which #520 is cutting. The equality is
maintained rather than asserted: the workflow calls these targets rather than
repeating their commands, and `tests/test_ci_parity.py` fails if a gating job
grows a step `make check` does not run. It has drifted four times — see
[Commands](commands.md#before-a-pull-request) for what `check` leaves out and why.

!!! info "CI may run fewer jobs than `check` does, and that is not drift"

    `test`, `test-frontend` and `e2e` are skipped on a pull request whose changed
    paths cannot affect them, and a `skipped` required check still lets a merge
    through. Locally there is no equivalent: `check` runs everything.

A docs-only change runs none of the three; a backend-only change runs no frontend
suite. What decides is `scripts/ci_changed_scope.py`, it errs towards running, and
[Branches](branching.md#a-required-check-may-legitimately-report-skipped) has the
rule.

!!! danger "Two ways to push something that has not been verified"

    `make test-fast` skips coverage, which makes it the wrong last word before a
    push - the gate is most of what these commands are for. And `pytest` without
    `uv run` picks up whatever interpreter is on the path rather than the pinned
    3.12.

## Test structure

Four layers, and which one a test belongs to is decided by what it needs rather
than by what it is about.

```
backend/tests/
├── conftest.py          # the shared fixtures, and the test database's name
├── test_*.py            # unit: one module, its dependencies mocked at the repository boundary
├── api/                 # the app driven through `client`, grouped by the question asked
└── integration/
    └── conftest.py      # creates a database of its own, and drops it afterwards
```

`tests/api/` is grouped by **what is being asked**, not by route module: some files
take one endpoint (`test_admin_ratings_window.py`), and `test_platform_routes.py`
sweeps a whole family at once, which is why `agents.py` has no file of its own.
Look for the question before looking for the path.

| Layer | Where | For |
|---|---|---|
| Unit | `tests/test_*.py` | One module. Repositories are mocked; the service under test never is |
| API | `tests/api/`, and some at the top level | The route: its gate, its status code, what reaches the service |
| Integration | `tests/integration/` | What only a database answers - an `ORDER BY`, a cascade, a unique constraint, a query that is really tenant-scoped |
| E2E | `frontend/e2e/` | Journeys crossing the whole system - see [Frontend Tests](#frontend-tests) |

There is no `tests/unit/` directory: a unit test is a `test_*.py` at the top of
`tests/`. The layer is **what a test needs, not where it sits**, and the top level
holds plenty that drives the app through an `AsyncClient` of its own -
`test_rag_document_listing.py`, `test_oauth_signin_exchange.py`,
`test_security_headers.py`. Looking only under `tests/api/` for existing route
coverage will miss them.

**One exception, and it is at the top level rather than in `integration/`.**
`tests/test_migrations.py` cycles the whole Alembic chain against a real database,
which it creates and drops itself under a name of its own - because
`downgrade base` drops every table, and inheriting `POSTGRES_DB` once emptied a
developer's working database. It is collected by an ordinary `pytest tests/`. It
is not in `integration/` because it does not use that package's `db` fixture at
all: it runs `alembic` in subprocesses.

## Async - anyio, not pytest-asyncio

```python
import pytest

pytestmark = pytest.mark.anyio   # at the top of the module
```

or `@pytest.mark.anyio` on the test, which `tests/api/test_users.py` does where
only some of a file is async. Either works; the module-level form is the habit
here because most files are async throughout.

!!! warning "`@pytest.mark.asyncio` does not work here, and there is no `asyncio_mode` to make it"

    The suite runs on **anyio**. An unmarked `async def` fails at collection with
    a message about the framework rather than about the test, so it reads as a
    broken environment on the way in.

An unmarked `async def` is not a silent pass: pytest 9 fails it at collection
with *"async def functions are not natively supported"* and lists the plugins
that would fix it. The `anyio_backend` fixture pins `asyncio`, because that is
what uvicorn runs.

## Key fixtures (`tests/conftest.py`)

Five. None of them is a `test_user` or a signed-in client, and that is the
point: an authenticated caller is a dependency override, so a test says which
authority it is exercising rather than inheriting one. `tests/api/test_users.py`
builds an `auth_client` of its own out of exactly those overrides - a local
fixture for the file that needs one, not a shared one every file inherits.

| Fixture | |
|---|---|
| `anyio_backend` | Pins `asyncio`, and nothing names it - anyio asks for it |
| `client` | `httpx.AsyncClient` over `ASGITransport(app=app)` — **not** Starlette's `TestClient`. Overrides `get_db_session` and `get_redis`, and clears `app.dependency_overrides` afterwards |
| `mock_db_session` | An `AsyncMock`. Its `info` is a real dict, because that is where `spawn_after_commit` queues work |
| `mock_redis` | A `MagicMock(spec=RedisClient)` with the async methods stubbed |
| `api_key_headers` | The service-to-service header, for a route behind `ValidAPIKey` |

`tests/integration/conftest.py` adds the ones that touch a database. The package
refuses any database whose name contains neither `test` nor `ci`, and empties
every table between tests. **It skips itself when none is reachable only outside
CI**: with `CI` set it raises instead, because a skip and a Postgres service that
failed to start read identically in pytest's output and only one of them is
acceptable on a runner.

| Fixture | |
|---|---|
| `db` | A real `AsyncSession` - what almost every integration test takes |
| `engine` | The `AsyncEngine` behind it, for a test that needs a session `db` cannot be: *more than one* - a race, a concurrent write, two transactions that have to interleave, where one `AsyncSession` shared across them is not a second connection but a corrupted one - or one the code under test makes for itself, which is how the RAG tests hand `PgVectorStore` its own `async_sessionmaker`. Eighteen files take it |
| `database_url`, `schema_url` | Session-scoped, and the reason the two above are safe: they name the throwaway database and create its schema once |

## Writing tests

Name the behaviour, not the function, so that a failure says what broke:
`test_a_grant_widens_access_without_promoting_the_member`, not `test_resolve`.

### A service test

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

The repository is mocked and the service is not. A test that mocks the thing it
is testing passes when the implementation is deleted.

### An API test

The caller is an override, which is what makes the refusal testable:

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

`tests/api/test_platform_routes.py` does this by sweeping, rather than one
assertion per route: the gate a route carries is a table, and a table is walked
rather than restated. It walks the **platform prefixes** - `/agents`, `/runs`,
`/approvals`, `/spend`, `/stats`, `/skills` and the rest of `_PLATFORM_PREFIXES` -
which is why most of those have no file of their own, and why `/auth`,
`/organizations` and `/users` still need their own: the sweep passes over them.

### An integration test

Only for what a mocked session cannot answer, which is usually an ordering, a
constraint or a cascade. `tests/integration/test_message_order.py` is the shape:
a turn writes its question and its answer inside one transaction, so both rows
carry the same `created_at` to the microsecond and the tie is broken by a column
rather than by the planner.

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

The bug there *was* Postgres, and a mocked session would have passed against the
schema that had no tiebreak at all.

### What is worth a test here

!!! important "Cover the refusal"

    Most of this platform's value is in what it refuses, so the refusal is the
    case that has to exist:

    - a cross-tenant read — **including one where the caller owns the row**;
    - an ungranted scope;
    - a budget checked *before* the model request, and recorded even when the run
      fails;
    - a spec refused at publish rather than at run time;
    - no plaintext secret in any response, log line or audit entry.

`.claude/rules/testing.md` and the `backend-tests` skill carry the rest - the
traps, the worked examples and the history behind each. This page is the shape of
the suite; neither repeats the other.

## Frontend tests

Run these from `frontend/`. At the repository root vitest finds no configuration,
reports well over a hundred phantom failures and leaves a stray `node_modules/`.

```bash
cd frontend

bunx vitest run src/components/chat/usage-strip.test.tsx   # one spec, ~2s
bunx vitest run src/components/chat                        # one directory
bun run test                                               # watch mode
bun run test:coverage                                      # the suite plus the gate CI applies
bun run test:e2e                                           # Playwright
bun run test:e2e --headed                                  # ...with a browser to watch
```

**`bun run test:run` measures no coverage**, so it cannot answer whether the
`test-frontend` job will pass: the gate wants 100% lines, statements and functions and
97.5% branches over `src/{app/api,lib,stores,hooks}` and most of `src/components`.

### Two deadlines, both sized for a loaded machine

A render-heavy spec is not slow because it is badly written; it is slow because
several thousand of them share ten cores with whatever else is running.
`testTimeout` in `vitest.config.ts` is **15s** and Testing Library's
`asyncUtilTimeout` in `vitest.setup.ts` is **5s**, both raised from defaults that
only hold on an idle machine.

The numbers come from running the whole suite four ways
([#862](https://github.com/vstorm-co/agenticos/issues/862)):

| Slowest single test | Bare | Under `--coverage` |
|---|---|---|
| Ten idle cores | 1.7s | 2.9s |
| 32 busy loops beside it | 5.4s | 6.1s |

Under that load the old 5s default failed three tests a run — a *different* three
each time, because which files share a worker is decided on timing, and in the bare
run as well as the instrumented one. Instrumentation costs about 1.6x of total test
time on a quiet machine and is the smaller multiplier; scheduling latency is the
rest. That is why neither deadline is conditional on `--coverage`: a limit the fast
loop and the gate disagree about is one that cannot reproduce the gate.

`asyncUtilTimeout` stays well under `testTimeout` on purpose. An element that is
never coming should lose the race, so the failure says *"Unable to find an element
with the text: …"* and names it, rather than *"Test timed out"* and names nothing.

Neither number is a licence for a spec that does more work than its assertions need:
mounting forty table rows twice to prove a count cost about two seconds in
`rag/[id]/counts.integration.test.tsx` before its fixture was cut to three.

Playwright starts what the suite needs: the frontend, and an OpenAI-compatible
**stub model server** (`frontend/e2e/stub-model-server.ts`) on `127.0.0.1:4010`
by default. The backend and its database have to be up already — the seeded
owner, model profile and published agent come from `agenticos cmd bootstrap`.

Both ports are configurable, so the suite runs beside another checkout that
already holds the defaults — a `bun run dev` left up on 3000, or a second
worktree. `E2E_PORT` moves the frontend, `E2E_STUB_MODEL_PORT` the stub, and
`playwright.config.ts` derives `baseURL`, both `webServer.url`s and the servers'
`PORT`/`E2E_STUB_MODEL_PORT` from them — so nothing is told a port twice.
`make test-e2e` reads all three (with `E2E_BACKEND`) and prints them before it
starts:

```bash
E2E_PORT=3100 make test-e2e          # frontend on 3100, stub on its default
```

The stub is what lets `journey.spec.ts` run an agent end to end without a
provider key: it serves the Chat Completions API, streaming included, and a model
profile reaches it through the **Endpoint** field. It echoes back the token the
agent's instructions tell it to say — which is the assertion, since nothing else
could put that token in the reply — and returns usage, so the run is priced and
the journey's last assertion has a cost to find. It authenticates nothing and
calls no tools; what it does not prove is that a real provider answers.

The stub binds loopback, and the backend dials it at `127.0.0.1:<port>` through
that stored profile — so the backend has to share the host's loopback. That is
the host-uvicorn path CI runs; a backend in a container cannot reach the host's
`127.0.0.1`, and moving the port does not change that.

### A red `e2e` is often the fixture, not the product

`setup` and `seed` are Playwright *project dependencies*, so a failure in either
one stops the projects that depend on it from running at all. The summary then
reads `1 failed`, `7 passed` and `17 did not run`, which on a pull request looks
exactly like a broken feature — and is not: **no product spec ran.** Three
branches each paid a diagnosis for that in one day
([#132](https://github.com/vstorm-co/agenticos/issues/132)), so
`frontend/e2e/fixture-reporter.ts` now prints a banner saying so, and under CI a
GitHub error annotation that shows on the checks page without opening a log.

### Waiting for a row is not waiting for the write

A spec that creates something through a dialog **must not** click submit and then
assert the new row is on screen. That shape sat at six sites and was seen to flake
at four. Two reasons, and the second is the expensive one:

- The window between the mutation resolving and the list rendering is real, and a
  longer `expect` timeout only makes a race slower to fail.
- **An open Radix dialog takes the rest of the page out of the accessibility
  tree.** While one is on screen, `getByRole("main")`, `getByRole("row")` and
  every locator built on them resolve to *nothing*, so the assertion times out
  with `element(s) not found` whether or not the row exists — naming the one
  thing that cannot be the cause. A refused create looked identical to a slow
  refetch for four separate occurrences.

`submitDialog` in `frontend/e2e/helpers.ts` is the way through: it waits for the
write's own response and asserts its status (so a refusal reads
`409 … already exists`, in milliseconds), then waits for the dialog to close —
which is the app saying it has finished everything it does around the write.

What it deliberately does not promise is that the row is now rendered, because
that is not currently true: the list's refetch is sometimes answered with the
pre-write list even though the row is committed and both server layers return it
([#230](https://github.com/vstorm-co/agenticos/issues/230), about one run in
eight). So:

- **A fixture step asks the API, and keeps asking.** Every step of
  `seed.setup.ts` asserts through `/api/…`, because its job is that the fixture
  exists — and a fixture step that fails takes every product spec with it. After
  a write it asks by polling (`nowThere`), never with a single read. That began
  as a workaround: a 2xx from this backend used to mean the request was answered
  and not that the write was readable, because the commit ran in a dependency
  FastAPI unwinds after the response has gone out
  ([#353](https://github.com/vstorm-co/agenticos/issues/353)). **That is fixed**
  — the commit now lands before the answer does — and the polling stays anyway,
  because a fixture is the wrong place to discover that some *other* write is
  slower than its acknowledgement, and because `nowThere` prints the rows it did
  see where a single read prints nothing. The `alreadyThere` guard each step
  opens with is a single read on purpose, since it runs before the write. The one
  *post-write* check that read once cost 87 skipped specs three times in a day
  ([#335](https://github.com/vstorm-co/agenticos/issues/335)).
- **A product spec that is about the rendering says so**, and reloads first if it
  needs a list it can trust. `vault.spec.ts` has three `page.reload()` calls
  marked `#230`; when that issue closes, they come out.

## Test database

Most tests don't hit a real database. The `client` fixture in `tests/conftest.py` overrides
`get_db_session` with a mocked async session (`AsyncMock`) via FastAPI's
`app.dependency_overrides`, so the suite runs fast and needs no Postgres container:

- `mock_db_session` — an `AsyncMock` standing in for `AsyncSession` (`execute`, `commit`, `rollback`, `close`)
- Overrides are registered before each test and cleared afterwards
- Assert against the mock's calls, or stub `execute(...)` return values for the path under test

Everything under `tests/integration/` is the exception, and it asks for the `db`
fixture from `tests/integration/conftest.py` rather than building an engine of its
own — that fixture is what puts the schema in place.

**The schema is built once for the whole process, and the data reset between tests.**

The `schema_url` fixture runs `create_all` a single time. The function-scoped
`engine` fixture then hands each test an empty database by `TRUNCATE`-ing every model
table — and dropping any table a test created outside the models, a runtime
`rag_<collection>` or an ordering probe — rather than rebuilding the schema.

It used to `drop_all` + `create_all` before *every* test: ~0.4s of DDL that was very
nearly the entire runtime of a suite whose assertions are microseconds of Postgres
work. Building it once cut `tests/integration` from ~125s to ~50s
([#215](https://github.com/vstorm-co/agenticos/issues/215)).

`TRUNCATE` rather than a transaction rollback, because the API-flow tests commit
through the real `get_db_session` and their rows outlive a rollback.

**The database it uses belongs to the pytest process that asked for it**:
`<POSTGRES_DB>_p<pid>`, created when the session starts and dropped when it ends,
failure included.

That is what makes two runs at once safe — two worktrees, or a worktree and a
`make test`, against the one Postgres container — and it needs nothing passed on the
command line.

The name was constant until
[#189](https://github.com/vstorm-co/agenticos/issues/189). Because each test dropped
and recreated the schema on that shared database, two runs spent their time dropping
each other's tables and reporting failures that belonged to neither branch.

!!! danger "The suite refuses any database whose name does not contain `test` or `ci`"

    It drops tables unconditionally, so that guard is the only thing between it and a
    development database.

**The credential is resolved once, in `tests/conftest.py`, and everything reads it
back off the settings object.**

Two engines reach that database — the fixture's, and the application's, built at
import time in `app/db/session.py` — and a test asking whether a write is visible
needs both.

They used to resolve the password separately, the fixture defaulting to `postgres`
where `app/core/config.py` defaults to empty, and nothing could see it while every
test connected through the fixture.

The first test to drive the application's engine failed to authenticate on a checkout
with no `backend/.env` — which is **every git worktree**, the file being untracked.
Two failures against a full green everywhere else, reading exactly like a branch
regression ([#485](https://github.com/vstorm-co/agenticos/issues/485)).

The suite now seeds `POSTGRES_PASSWORD=postgres` before the settings object is built,
and only when neither the environment nor a `.env` supplies one, so a real password
is never replaced by the default.

`app/core/config.py` still defaults it to empty, which is what makes a missing `.env`
announce itself in `alembic check` rather than reaching a database with a guess.

### The migration suite has a third one

`tests/test_migrations.py` applies the whole chain to an empty database and rolls it
back to base, so it can use neither of the above: the integration database already
has the schema in it (built from the models, which is a different question), and
`downgrade base` against the unit suite's would empty it mid-run. It gets
`agenticos_migrations_test_p<pid>`, created before its first test and dropped after
its last, and every alembic subprocess is passed that name explicitly rather than
inheriting `POSTGRES_DB`.

That database used to have to exist already, and nothing ever created it, so every
test in the module skipped on every CI run this project had — a green build over the
only assertions that `downgrade()` works at all
([#234](https://github.com/vstorm-co/agenticos/issues/234)). It now creates its own,
and the surviving skip means only what it says: **no Postgres answered.** In CI,
where a service container is declared, that is a failure instead — a container that
did not start is not an environment that cannot answer, and the two are
indistinguishable in pytest's output.

`make test-migrations` still exists and is still the one to run by hand after
touching `alembic/versions/`, but it points at whatever `backend/.env` says, which
on a laptop is the database with your own work in it. Prefer
`uv run pytest tests/test_migrations.py`, which cannot reach it.

## Prefect, and why no test reaches a server

**Calling a `@flow` is a network call, and the suite points it at nowhere.** Prefect
resolves its own settings from `backend/.env` — its settings model carries
`env_file=".env"` — so `PREFECT_API_URL=http://localhost:4200/api`, the line `make dev`
needs, was also the address a test's `@flow` call tried to reach. Without a server up
that is `RuntimeError: Failed to reach API at http://localhost:4200/api/` out of a test
that mocked every collaborator it has, and CI never saw it: with no `.env` there is no
URL, so what a laptop ran was never what CI ran
([#536](https://github.com/vstorm-co/agenticos/issues/536)).

`tests/conftest.py` therefore assigns `PREFECT_API_URL` **empty** before Prefect is
imported, next to the database name and password above and for the same reason.

Deleting the variable would not do: an unset variable leaves the dotenv source to
answer, and the dotenv source is what holds the URL.

An empty assignment outranks it because Prefect's settings model carries
`env_ignore_empty=False` — which is Prefect's rule and not ours. `app/core/config.py`
sets it the other way, so the same line against one of *our* settings would be
discarded and the `.env` would answer anyway.

Prefect reads an empty URL as no URL and starts a temporary server of its own for the
call, which is what CI has always done. So the run no longer depends on whether a
Prefect server happens to be up, in either direction.

**That server's state is a SQLite database under `PREFECT_HOME`, and the suite gives it
one of its own.** Left alone it is `~/.prefect`, so a unit run would write its flow runs
into a developer's Prefect data and, where Prefect runs on the host rather than in
Docker, into the file a running `prefect server` has open. `tests/conftest.py` points it
at `agenticos-prefect-test` under the system temporary directory, for the same reason
the Postgres name above is a test database. One directory rather than one per process:
what costs is creating it.

Creating it is a migration, and the suite raises Prefect's 20-second allowance for
starting that server to 90 — **as headroom, not because 20 has been seen to fail.**
Against a `PREFECT_HOME` nothing has written yet the whole start takes about six seconds
on a laptop and about nine on a CI container, which is cold on every run and has never
been red on the default. What the raised allowance buys is that the one step whose cost
nothing here bounds — a migration on a contended machine, or a temporary directory that
has been swept — waits rather than failing a suite that a second run would pass.
`tests/test_prefect_test_environment.py` pins all four properties.

## Recap

- **Four layers**: unit, integration, API, E2E. Pick by what the test needs to be
  true, not by what it is about.
- Async tests use **anyio**. `@pytest.mark.asyncio` does nothing here.
- **Cover the refusal.** Most of this platform's value is in what it refuses.
- The platform layer is at **100%**, and adding a module to it means editing two
  lists in `backend/pyproject.toml`.
- The order is shuffled every run; replay a failure with its printed seed before
  concluding anything about the change.
