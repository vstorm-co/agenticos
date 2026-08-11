---
description: Testing standards, the four layers, anyio patterns, the 100% platform gate
globs:
  [
    "backend/tests/**/*.py",
    "tests/**/*.py",
    "**/test_*.py",
    "**/conftest.py",
    "frontend/src/**/*.test.ts",
    "frontend/src/**/*.test.tsx",
  ]
---

# Testing

Deeper guidance lives in the `backend-tests` skill and `docs/testing.md`.

## Running — narrowest first

**Run what covers the change, not the suite.** The suite is the check before a push;
after an edit it answers the same question ten to fifty times slower.

| From | Command | About |
|---|---|---|
| `backend/` | `uv run pytest tests/test_sandbox_workspace.py -q` | ~6s, nearly all importing the app |
| `backend/` | `uv run pytest tests/api/test_workspace_routes.py -k bytes -x` | ~6s, same |
| `backend/` | `uv run pytest tests/test_a.py tests/test_b.py -q` | as many files as the change touched |
| `frontend/` | `bunx vitest run src/components/chat/usage-strip.test.tsx` | 2s |
| `frontend/` | `bunx vitest run src/components/chat` | a directory |

Then, once, before the push:

```bash
make lint               # ruff, ruff format, ty, vulture, eslint, prettier, tsc, the guard
                        # scripts, and codespell over every tracked file
make test               # backend + the 100% gate; runs across workers (-n auto,
                        # capped at 4), pytest-cov combines their data
make test-frontend-cov  # frontend + its gate: 100% lines/stmts/funcs, 97.5% branches
make test-integration   # only if the change is near the database; also parallel
make check              # every CI job except e2e - lint, test, db-check,
                        # test-frontend-cov, build-frontend, docs-build, audit.
                        # About five minutes.
```

`make check` is CI, not an approximation of it: `.github/workflows/ci.yml` calls
those targets rather than repeating their commands, and `tests/test_ci_parity.py`
fails if a gating job grows a step `check` does not run - or if `check` grows one
CI does not. It has drifted four times, all four found by #143.

Three things `check` leaves out, on purpose: `e2e` (needs a seeded backend), the
image scan (push to `main` only), and `make test-migrations` - CI cycles the chain
against a throwaway database, and `alembic downgrade base` on a laptop points at
the one with your own work in it. `check` also says at the end when
`tests/integration/` skipped itself for want of a database, because CI's `test`
job always has one.

Traps, each of which has cost a red job here:

- **The order is shuffled every run** (`pytest-randomly`, on by default since #571), so
  a test that passed yesterday and fails today may have been depending on what ran
  before it. The header prints `Using --randomly-seed=<n>`; pass that seed back to
  reproduce the failure, and `-p no:randomly` to pin collection order while bisecting.
  The controller's seed reaches every xdist worker, so `-n auto` collects one order.
- **`bun run test:run` measures no coverage.** The frontend gate is a separate command
  and CI runs it (`bun run test:coverage`); 168 green files still failed the job.
- **Frontend commands run from `frontend/`.** At the repository root vitest finds no
  config, reports about 164 phantom failures, and leaves a stray `node_modules/`.
- **A red `e2e` may not be yours.** `sharing.spec.ts` and `skills.spec.ts` flake
  (#154) - check `gh run list --branch <branch>` for the same spec passing a run later
  before changing anything.
- **A red `e2e` in `[setup]` or `[seed]` ran no product spec at all.** They are project
  dependencies, so Playwright skips what depends on them and the log reads "1 failed,
  7 passed, 17 did not run". `e2e/fixture-reporter.ts` prints a banner saying so - read
  it before touching product code. Creating a row through a dialog goes through
  `submitDialog`, never `click(submit)` then `expect(row).toBeVisible()`: an open Radix
  dialog takes the page out of the accessibility tree, so that shape reports
  `element(s) not found` for a refusal it never looked at (#132). And a **fixture** step
  asserts through the API, never on the row appearing - the refetch after a write is
  sometimes answered with the pre-write list (#230), which is a product bug and must not
  be reported as a broken fixture. It asserts by **polling** that API. The backend half
  of that is fixed - a 2xx now means the write is readable, because the commit lands
  before the response goes out (#353) - but #230 is a browser-side staleness nobody has
  closed, so the polling stays until it is. One step read once instead and took all 87
  specs down three times in a day (#335).
- **Coverage instrumentation slows tests enough to trip a 5s `testTimeout`.** A
  heavy spec that passes under `test:run` can time out under `test:coverage`; re-run
  before believing it.

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

The conftest points `POSTGRES_DB` at `<base>_p<pid>` before `app.core.config` is
imported — a test database, and one per pytest process. Leave both halves: the unit
suite once emptied a developer's database through a populated `.env`, and a constant
name meant two runs on one machine dropping each other's tables mid-test (#189).

`tests/integration/conftest.py` creates that database at the start of the session and
drops it at the end, even when the suite fails, so **two concurrent runs are safe and
nothing has to be passed to make them so**. It still skips when no database is
reachable (a laptop without Docker) and still refuses any database whose name contains
neither `test` nor `ci`, or that is not a plain identifier — it empties every table
unconditionally between tests and drops the database itself afterwards.

A run killed outright (`SIGKILL`) leaks its database; the next run with that pid drops
it before creating its own. Anything else named `agenticos_*` on a shared Postgres was
made by hand and is nobody's to clean up automatically.

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
