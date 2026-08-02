# Testing Guide

## Running Tests

```bash
cd backend

# Run all tests
pytest

# Run with coverage
pytest --cov=app --cov-report=term-missing

# Run specific test file
pytest tests/api/test_health.py -v

# Run specific test
pytest tests/api/test_health.py::test_health_check -v

# Run only unit tests
pytest tests/unit/

# Run only integration tests
pytest tests/integration/

# Run with verbose output
pytest -v

# Stop on first failure
pytest -x
```

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

```bash
cd frontend

# Run unit tests
bun test

# Run with watch mode
bun test --watch

# Run E2E tests
bun test:e2e

# Run E2E in headed mode (see browser)
bun test:e2e --headed
```

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

Tests don't hit a real database. The `client` fixture in `tests/conftest.py` overrides
`get_db_session` with a mocked async session (`AsyncMock`) via FastAPI's
`app.dependency_overrides`, so the suite runs fast and needs no Postgres container:

- `mock_db_session` — an `AsyncMock` standing in for `AsyncSession` (`execute`, `commit`, `rollback`, `close`)
- Overrides are registered before each test and cleared afterwards
- Assert against the mock's calls, or stub `execute(...)` return values for the path under test

For tests that need to exercise real SQL, instantiate your own async engine/session
inside the test rather than relying on a shared fixture.
