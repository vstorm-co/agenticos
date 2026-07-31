---
name: backend-tests
description: Write or extend the backend Python test suite — a unit test for a service, an integration test against a real Postgres, an API test through the FastAPI app, or the test a bug fix needs. Also for "coverage is failing", "make test is red", and deciding which of the four layers a test belongs in. Uses anyio (not pytest-asyncio) and a 100% coverage gate on the platform layer.
---

# Backend tests — four layers and a 100% gate

**Read `docs/testing.md`** and the `## Testing` section of `CLAUDE.md`; both are
current. `.claude/rules/testing.md` has the naming and fixture shapes. This file is
where a test goes and what actually breaks.

```bash
make test-fast          # no coverage — the write-run-write loop
make test               # backend + the 100% gate on the platform layer
make test-integration   # only the tests that need a real database
make test-cov           # HTML at backend/htmlcov/index.html
make coverage-all        # includes template-inherited code (informational)
make test-migrations    # the whole chain forwards and back against Postgres
make check              # what CI runs — before opening a PR
```

## Which layer

| Layer | Path | Use when |
|---|---|---|
| **Unit** | `tests/test_*.py` | One module, deps mocked at the repository boundary. Most tests |
| **Integration** | `tests/integration/` | A `CHECK`, a cascade, a partial unique index, tenant isolation in the schema |
| **API** | `tests/api/` | A route is wired to the right permission and returns the right status |
| **E2E** | `frontend/e2e/` | See the `e2e-tests` skill |

A mock cannot tell you whether a constraint rejects a row. If the assertion is about
the schema, it is an integration test or it is worthless.

## anyio, not pytest-asyncio

```python
import pytest

pytestmark = pytest.mark.anyio   # module top
```

There is no `asyncio_mode` and no `@pytest.mark.asyncio`. The `anyio_backend` fixture
in `tests/conftest.py` pins `asyncio` because that is what uvicorn uses.

## Fixtures worth knowing

`tests/conftest.py`:

- **`client`** — `httpx.AsyncClient` over `ASGITransport(app=app)`. Use this, never
  Starlette's `TestClient`. It overrides `get_db_session` and `get_redis`, and clears
  `app.dependency_overrides` afterwards.
- **`mock_db_session`** — an `AsyncMock`. Mock repositories, **never** the service
  under test.
- **`mock_redis`**, **`api_key_headers`**.

The conftest also sets `POSTGRES_DB=agenticos_test` *before* anything imports
`app.core.config`. Do not move or weaken that: running the unit suite against a
checkout with a populated `.env` used to empty the development database.

`tests/integration/conftest.py` skips the whole module when no database is reachable,
and **refuses to run against a database whose name contains neither `test` nor `ci`**
— it calls `drop_all` unconditionally.

## A test earns its place by failing when the behaviour changes

- **Name the behaviour, not the function.**
  `test_a_failed_run_still_records_its_cost`, not `test_finish`.
- **Assert the consequence.** Not "the repository was called" but "the cost written
  was $2.00".
- **The docstring says why it matters** when the name cannot.
- **Cover the refusal.** Most of this platform's value is in what it refuses: a
  cross-tenant read, an ungranted scope, a second decision on a decided approval.
- **No test for a mock.** If removing the implementation still passes, delete it.

## Invariants to test directly

Tenant isolation (including when the caller owns the row) · permission scopes and
grants · budget checked *before* the model request and recorded even when the run
fails · spec validation refused at publish, never at run time · no plaintext secret
in any response, log or audit entry · channel mentions running as the sender ·
what a parser claims it reads vs what the pipeline routes · narrowing a rule on a
field already stored as JSONB.

The last two have bitten this repository. `CLAUDE.md` explains both.

## Depth

- `references/coverage-gate.md` — what is held to 100%, how the config selects it,
  and the two ways a module drops out silently.
- `references/patterns.md` — worked service, API and integration tests.
