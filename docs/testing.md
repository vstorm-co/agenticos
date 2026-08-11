# Testing Guide

## Running Tests

While writing, run what covers the change — a file answers in about a second where
the suite takes a minute and a half, and says the same thing:

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

**Every run is shuffled**, by `pytest-randomly`, and the header says with what:
`Using --randomly-seed=1697040112`. An order-dependent test — one that passes only
because something before it left state behind — is the classic "green on my laptop,
red in CI", and a suite that always runs in collection order never asks the question.
CI asks it in a fresh order every run.

```bash
uv run pytest tests/ -q --randomly-seed=1697040112   # reproduce a red run exactly
uv run pytest tests/ -q -p no:randomly               # collection order, while bisecting
```

The seed is chosen once by the controller and handed to each xdist worker, so `-n auto`
collects one order rather than four. Until #571 the plugin was documented but not
installed, `-p no:randomly` was a silent no-op, and nothing had ever exercised the
claim.

Once, before pushing — `make check` runs all of it, in this order:

```bash
make lint               # ruff, ruff format, ty, vulture, eslint, prettier, tsc, the guards
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

**CI may run fewer jobs than `check` does, and that is not drift.** `test`,
`test-frontend` and `e2e` are skipped on a pull request whose changed paths cannot
affect them — a docs-only change runs none of the three, a backend-only change runs
no frontend suite. What decides is `scripts/ci_changed_scope.py`, it errs towards
running, and [Branches](branching.md#a-required-check-may-legitimately-report-skipped)
has the rule and why a `skipped` required check still lets a merge through. Locally
there is no equivalent: `check` runs everything.

`make test-fast` skips coverage, which makes it the wrong last word before a push:
the gate is most of what these commands are for. `pytest` without `uv run` picks up
whatever interpreter is on the path rather than the pinned 3.12.

## Test Structure

```
tests/
├── conftest.py          # Shared fixtures
├── api/                 # API endpoint tests
│   ├── test_health.py
│   └── test_auth.py
├── unit/                # Unit tests (services, utils)
│   └── test_services.py
└── integration/         # Integration tests
    └── test_db.py
```

## Key Fixtures (`conftest.py`)

```python
# Database session for tests
@pytest.fixture
async def db_session():
    async with async_session() as session:
        yield session
        await session.rollback()

# Test client
@pytest.fixture
def client():
    return TestClient(app)

# Authenticated client
@pytest.fixture
async def auth_client(client, test_user):
    token = create_access_token(test_user.id)
    client.headers["Authorization"] = f"Bearer {token}"
    return client
```

## Writing Tests

### API Endpoint Test
```python
def test_health_check(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
```

### Service Test
```python
async def test_create_item(db_session):
    service = ItemService(db_session)
    item = await service.create(ItemCreate(name="Test"))
    assert item.name == "Test"
```

### Test with Authentication
```python
def test_protected_endpoint(auth_client):
    response = auth_client.get("/api/v1/users/me")
    assert response.status_code == 200
```

## Frontend Tests

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

## Test Database

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
The `schema_url` fixture runs `create_all` a single time; the function-scoped `engine`
fixture then hands each test an empty database by `TRUNCATE`-ing every model table
(and dropping any table a test created outside the models — a runtime
`rag_<collection>`, an ordering probe) rather than rebuilding the schema. It used to
`drop_all` + `create_all` before *every* test, ~0.4s of DDL that was very nearly the
entire runtime of a suite whose assertions are microseconds of Postgres work; building
it once cut `tests/integration` from ~125s to ~50s
([#215](https://github.com/vstorm-co/agenticos/issues/215)). `TRUNCATE` rather than a
transaction rollback because the API-flow tests commit through the real
`get_db_session`, so their rows outlive a rollback.

**The database it uses belongs to the pytest process that asked for it**:
`<POSTGRES_DB>_p<pid>`, created when the session starts and dropped when it ends,
failure included. That is what makes two runs at once safe — two worktrees, or a
worktree and a `make test`, against the one Postgres container — and it needs nothing
passed on the command line. The name was constant until [#189](https://github.com/vstorm-co/agenticos/issues/189),
and because each test dropped and recreated the schema on that shared database, two
runs spent their time dropping each other's tables and reporting failures that belonged
to neither branch. The suite still refuses any database whose name does not contain
`test` or `ci`: it drops tables unconditionally, so the guard is the only thing between
it and a development database.

**The credential is resolved once, in `tests/conftest.py`, and everything reads it
back off the settings object.** Two engines reach that database — the fixture's, and
the application's, built at import time in `app/db/session.py` — and a test asking
whether a write is visible needs both. They used to resolve the password separately,
the fixture defaulting to `postgres` where `app/core/config.py` defaults to empty, and
nothing could see it while every test connected through the fixture. The first one to
drive the application's engine failed to authenticate on a checkout with no
`backend/.env` — which is **every git worktree**, the file being untracked — two
failures against a full green everywhere else, reading exactly like a branch
regression ([#485](https://github.com/vstorm-co/agenticos/issues/485)). The suite now
seeds `POSTGRES_PASSWORD=postgres` before the settings object is built, and only when
neither the environment nor a `.env` supplies one, so a real password is never
replaced by the default. `app/core/config.py` still defaults it to empty, which is
what makes a missing `.env` announce itself in `alembic check` rather than reaching a
database with a guess.

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
