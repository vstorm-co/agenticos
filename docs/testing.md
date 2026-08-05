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

Once, before pushing — `make check` runs all of it, in this order:

```bash
make lint               # ruff, ruff format, ty, eslint, prettier, tsc, and the two guards
make test               # the suite plus the 100% gate on the platform layer
make db-check           # alembic check — a model change with no migration fails here
make test-frontend-cov  # the frontend suite plus its own gate
make build-frontend     # next build — the route tree, which tsc and vitest do not see
make docs-build         # mkdocs --strict — a dead link is a failure
make audit              # the locked dependency set against the advisory database
```

About five minutes serial, against CI's seven in parallel. The equality is
maintained rather than asserted: the workflow calls these targets rather than
repeating their commands, and `tests/test_ci_parity.py` fails if a gating job
grows a step `make check` does not run. It has drifted four times — see
[Commands](commands.md#before-a-pull-request) for what `check` leaves out and why.

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
**stub model server** (`frontend/e2e/stub-model-server.ts`) on `127.0.0.1:4010`.
The backend and its database have to be up already — the seeded owner, model
profile and published agent come from `agenticos cmd bootstrap`.

The stub is what lets `journey.spec.ts` run an agent end to end without a
provider key: it serves the Chat Completions API, streaming included, and a model
profile reaches it through the **Endpoint** field. It echoes back the token the
agent's instructions tell it to say — which is the assertion, since nothing else
could put that token in the reply — and returns usage, so the run is priced and
the journey's last assertion has a cost to find. It authenticates nothing and
calls no tools; what it does not prove is that a real provider answers.

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

**The database it uses belongs to the pytest process that asked for it**:
`<POSTGRES_DB>_p<pid>`, created when the session starts and dropped when it ends,
failure included. That is what makes two runs at once safe — two worktrees, or a
worktree and a `make test`, against the one Postgres container — and it needs nothing
passed on the command line. The name was constant until [#189](https://github.com/vstorm-co/agenticos/issues/189),
and since the fixture rebuilds the schema before every test, two runs spent their time
dropping each other's tables and reporting failures that belonged to neither branch.
The suite still refuses any database whose name does not contain `test` or `ci`: it
drops tables unconditionally, so the guard is the only thing between it and a
development database.
