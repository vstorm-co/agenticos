---
description: Testing standards, the four layers, anyio patterns, the 100% platform gate
globs: ["backend/tests/**/*.py", "tests/**/*.py", "**/test_*.py", "**/conftest.py"]
---

# Testing

Deeper guidance lives in the `backend-tests` skill and `docs/testing.md`.

## Running

```bash
make test-fast          # no coverage — the write-run-write loop
make test               # backend + the 100% gate on the platform layer
make test-integration   # only the tests that need a real database
make test-cov           # HTML at backend/htmlcov/index.html
make check              # what CI runs
```

Single test, from `backend/`:
`uv run pytest tests/test_capability_registry.py -k drift -v`.

## The four layers

| Layer | Path | For |
|---|---|---|
| Unit | `tests/test_*.py` | One module, deps mocked at the repository boundary |
| Integration | `tests/integration/` | A real database — constraints, cascades, tenant isolation |
| API | `tests/api/` | A route is wired to the right permission and status |
| E2E | `frontend/e2e/` | Journeys crossing the whole system |

## Async — anyio, not pytest-asyncio

```python
import pytest

pytestmark = pytest.mark.anyio   # module top
```

`@pytest.mark.asyncio` does not work here; there is no `asyncio_mode`. The
`anyio_backend` fixture pins `asyncio` because that is what uvicorn uses.

## Fixtures (`tests/conftest.py`)

- `client` — `httpx.AsyncClient` over `ASGITransport(app=app)`. **Not** Starlette's
  `TestClient`. Overrides `get_db_session` and `get_redis`, and clears
  `app.dependency_overrides` afterwards.
- `mock_db_session` — an `AsyncMock`. Mock repositories, never the service under test.
- `mock_redis`, `api_key_headers`.

The conftest pins `POSTGRES_DB=agenticos_test` before `app.core.config` is imported.
Leave it: the unit suite once emptied a developer's database through a populated `.env`.

`tests/integration/conftest.py` skips when no database is reachable and refuses any
database whose name contains neither `test` nor `ci` — it calls `drop_all`
unconditionally.

## Naming

```python
# test_<behaviour>, stated so a failure says what broke
def test_a_failed_run_still_records_its_cost
def test_a_grant_widens_access_without_promoting_the_member
def test_a_ciphertext_from_another_organization_fails_to_unwrap
```

Name the behaviour, not the function. `test_finish` says nothing.

## Service test

```python
async def test_get_user_not_found_raises(monkeypatch, mock_db_session):
    service = UserService(mock_db_session)
    monkeypatch.setattr(user_repo, "get_by_id", AsyncMock(return_value=None))
    with pytest.raises(NotFoundError):
        await service.get_by_id(uuid4())
```

## API test

```python
async def test_creating_an_agent_without_agents_edit_is_refused(client: AsyncClient):
    app.dependency_overrides[deps.get_auth_context] = lambda: caller_without(Perm.AGENTS_EDIT)
    resp = await client.post("/api/v1/agents", json={...})
    assert resp.status_code == 403
```

## Rules

- **Assert the consequence**, not that a mock was called.
- **Cover the refusal.** Most of this platform's value is in what it refuses.
- **No test for a mock** — if removing the implementation still passes, delete it.
- Each test independent; plain `assert`; factory fixtures, not raw dicts.
- A docstring when the name cannot carry why it matters.
- `app/agents/**` and the rest of the platform layer are at **100%, enforced in CI**.
