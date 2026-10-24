"""Test configuration and fixtures.

Uses anyio for async testing instead of pytest-asyncio.
This allows using the same async primitives that Starlette uses internally.
See: https://anyio.readthedocs.io/en/stable/testing.html
"""
# ruff: noqa: I001 - Imports structured for Jinja2 template conditionals

import os
import re
from pathlib import Path

# Before anything imports `app.core.config`, and therefore before anything can
# open a connection: point every database name in this process at a test
# database *of its own*. An environment variable outranks the `.env` file
# pydantic-settings reads, so this holds even where a developer's `.env` names
# their working database.
#
# It is here rather than in the integration conftest because the damage was not
# there: running the *unit* suite against a checkout with a populated `.env`
# emptied the development database, and no test in it means to touch a database
# at all. A default that can only ever hit a test database costs nothing and
# removes the whole class of accident.
#
# The process id is appended because the name used to be constant while
# `tests/integration/conftest.py` calls `drop_all` unconditionally: two runs on
# one machine - two worktrees, or one worktree and a `make test` - dropped and
# recreated each other's tables mid-test, and reported failures belonging to
# neither branch (#189). One database per pytest process removes the sharing
# rather than scheduling around it; `tests/integration/conftest.py` creates it
# and drops it again. A pid also separates `pytest-xdist` workers, which are
# processes of their own.
#
# Deriving from whatever is already set, rather than defaulting, keeps two
# properties: CI (which sets `POSTGRES_DB=test_db`) runs the same create-and-drop
# path a laptop does, and a name that is not obviously a test database is still
# refused by the guard in the integration conftest instead of being made to look
# like one.
os.environ["POSTGRES_DB"] = f"{os.environ.get('POSTGRES_DB', 'agenticos_test')}_p{os.getpid()}"


def _a_password_is_already_configured() -> bool:
    """Would `app.core.config` resolve a Postgres password from somewhere?

    The `.env` search mirrors `find_env_file`, which cannot be imported here:
    importing `app.core.config` is precisely what this block has to precede.
    An empty assignment does not count, because `env_ignore_empty` discards it.
    """
    if os.environ.get("POSTGRES_PASSWORD"):
        return True
    for directory in (Path.cwd(), Path.cwd().parent):
        env_file = directory / ".env"
        if env_file.exists():
            return any(
                re.match(r"\s*POSTGRES_PASSWORD\s*=\s*\S", line)
                for line in env_file.read_text().splitlines()
            )
    return False


# The credential those same two engines authenticate with, resolved here for the
# same reason as the name above: `app/db/session.py` builds its engine at import
# time, so anything the settings object must hold has to be in the environment
# before it is constructed.
#
# `tests/integration/conftest.py` used to default this to "postgres" while
# `app/core/config.py` defaults it to empty, and no test could tell, because
# every one of them connected through the fixture's engine. The first test to
# drive the *application's* engine found the disagreement: on a checkout with no
# `backend/.env` - which is every git worktree, the file being untracked - it
# failed to authenticate while the rest of the suite passed, which reads exactly
# like a regression of whatever branch it turned up on (#485).
#
# The empty default in `app/core/config.py` stays, and this is deliberately not a
# second copy of it. `make install` is built around that empty default: with no
# `.env`, `alembic check` is refused with `fe_sendauth: no password supplied`,
# which is a missing file announcing itself rather than a guessed credential
# reaching a database. What is defaulted here is what the test suite connects
# with, in one place, and `tests/integration/conftest.py` reads it back off the
# settings object rather than defaulting it again.
#
# Seeded only when nothing else supplies one - unlike the database name above,
# where overriding a developer's `.env` is the entire point. Here it would swap a
# real password for a guess, so a `.env` that names one keeps it, and the
# integration fixture now honours it too instead of ignoring it.
if not _a_password_is_already_configured():
    os.environ["POSTGRES_PASSWORD"] = "postgres"


from collections.abc import AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.core.config import settings
from app.api.deps import get_redis
from app.clients.redis import RedisClient
from app.api.deps import get_db_session


@pytest.fixture(autouse=True)
def _no_steps_written_after(monkeypatch: pytest.MonkeyPatch) -> None:
    """No follow-ups model wrote next steps after any run here (#2301).

    Most runner tests stub the build with a `MagicMock`, whose deps answer
    `next_steps` with steps no JSON encoder can write - across the runner's,
    the surfaces' and the delegation suites. The helper is covered on its own by
    `test_agent_runner.py::TestNextStepsWrittenAfterTheAnswer`, which calls it
    directly.
    """
    monkeypatch.setattr("app.services.agent_runner._written_next_steps", lambda _deps: [])


@pytest.fixture
def anyio_backend() -> str:
    """Specify the async backend for anyio tests.

    Options: "asyncio" or "trio". We use asyncio since that's what uvicorn uses.
    """
    return "asyncio"


@pytest.fixture(autouse=True)
def _reset_channel_intake() -> Generator[None]:
    """Reset the channel supervisor's shutdown flag after every test.

    `_shutting_down` is a process global, and a test that runs the real lifespan
    (`test_lifespan_drain.py`) sets it on the way down. Under the randomized
    parallel suite that leaks into a later test that opens an inbound stream,
    which the flag would then decline - a red run that passes on re-run (#1119).
    """
    yield
    from app.services.channels.supervisor import allow_intake

    allow_intake()


@pytest.fixture(autouse=True)
def _forget_mcp_answers() -> Generator[None]:
    """Clear which MCP servers answered a probe recently.

    A process global, like the flag above: a server one test probed as up would
    otherwise skip the next test's probe of the same URL, and a test stubbing that
    probe to fail would find the server attached anyway.
    """
    yield
    from app.agents.mcp import _answered

    _answered.clear()


@pytest.fixture(autouse=True)
def _fresh_rate_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give every test its own per-process rate floor.

    `consume_floored` counts in a process global whenever no limiter is
    configured, which is every unit test. Calls made under one test's caller
    address would otherwise fill the window another test on the same worker
    opens, and refuse it with a 4029 it never earned.
    """
    from app.services import rate_limit

    monkeypatch.setattr(rate_limit, "_floor", rate_limit.LocalWindows())


@pytest.fixture
def sole_source_run() -> Generator[None]:
    """Grant `_run_source_sync` its per-source lock without a database.

    The lock is a Postgres advisory lock on a session of its own (#987), and the
    unit tests of the sync flow replace every session with a mock. They are about
    what one run does, so they are handed the lock; what happens when it is held
    elsewhere is `test_connector_sync_state.py`'s, and the lock itself is proved
    against a real database in `tests/integration/test_sync_source_removal.py`.
    """
    from contextlib import asynccontextmanager

    from app.worker.tasks import rag_tasks

    @asynccontextmanager
    async def held(_source_id: str) -> AsyncGenerator[bool]:
        yield True

    with patch.object(rag_tasks, "_exclusive_source_run", new=held):
        yield


@pytest.fixture
def _generated_media_store(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[dict[str, object]], dict[object, dict[str, object]]]:
    """Generated media's rows and quota claims, held in memory instead of a database.

    The organization's advisory lock is an `anyio.Lock` held until the fake
    session ends, as a transaction-scoped lock is held until the commit, so
    concurrent admissions serialize here as they do on Postgres.
    """
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from uuid import uuid4

    import anyio

    from app.services import generated_media

    rows: list[dict[str, object]] = []
    reservations: dict[object, dict[str, object]] = {}
    locks: dict[object, anyio.Lock] = {}

    @asynccontextmanager
    async def session() -> AsyncGenerator[SimpleNamespace]:
        db = SimpleNamespace(held=[])
        try:
            yield db
        finally:
            for lock in db.held:
                lock.release()

    async def hold_subject(db: SimpleNamespace, _scope: object, subject: object) -> None:
        lock = locks.setdefault(subject, anyio.Lock())
        await lock.acquire()
        db.held.append(lock)

    async def create(_db: object, **row: object) -> SimpleNamespace:
        rows.append(row)
        return SimpleNamespace(**row)

    async def bytes_used(_db: object, *, organization_id: object) -> int:
        return sum(
            int(str(row["size_bytes"])) for row in rows if row["organization_id"] == organization_id
        )

    async def bytes_reserved(_db: object, *, organization_id: object, since: object) -> int:
        return sum(
            int(str(claim["size_bytes"]))
            for claim in reservations.values()
            if claim["organization_id"] == organization_id
        )

    async def reserve(_db: object, *, organization_id: object, size_bytes: int) -> object:
        reservation_id = uuid4()
        reservations[reservation_id] = {
            "organization_id": organization_id,
            "size_bytes": size_bytes,
        }
        return reservation_id

    async def release(_db: object, *, organization_id: object, reservation_id: object) -> None:
        if reservations.get(reservation_id, {}).get("organization_id") == organization_id:
            del reservations[reservation_id]

    monkeypatch.setattr(generated_media, "get_db_context", session)
    monkeypatch.setattr(generated_media, "hold_subject", hold_subject)
    repo = generated_media.generated_media_repo
    monkeypatch.setattr(repo, "create", create)
    monkeypatch.setattr(repo, "bytes_used", bytes_used)
    monkeypatch.setattr(repo, "bytes_reserved", bytes_reserved)
    monkeypatch.setattr(repo, "reserve", reserve)
    monkeypatch.setattr(repo, "release", release)
    return rows, reservations


@pytest.fixture
def generated_media_ledger(
    _generated_media_store: tuple[list[dict[str, object]], dict[object, dict[str, object]]],
) -> list[dict[str, object]]:
    """Record generated media in a list rather than a database; the list is returned.

    Every file an agent's tool stores is recorded in `generated_media` through a
    session of its own (#2310), and the quota is summed from those rows and the
    claims of calls in flight (`generated_media_reservations`). The unit tests
    of the tools are about what a tool does with a file, so they are handed
    this; the rows themselves are proved against a real database in
    `tests/integration/test_generated_media.py`.
    """
    return _generated_media_store[0]


@pytest.fixture
def generated_media_reservations(
    _generated_media_store: tuple[list[dict[str, object]], dict[object, dict[str, object]]],
) -> dict[object, dict[str, object]]:
    """The quota claims of generation calls in flight, by id, beside `generated_media_ledger`."""
    return _generated_media_store[1]


@pytest.fixture
def mock_redis() -> MagicMock:
    """Create a mock Redis client for testing."""
    mock = MagicMock(spec=RedisClient)
    mock.ping = AsyncMock(return_value=True)
    mock.get = AsyncMock(return_value=None)
    mock.set = AsyncMock(return_value=True)
    mock.delete = AsyncMock(return_value=1)
    mock.exists = AsyncMock(return_value=0)
    mock.incr = AsyncMock(return_value=1)
    mock.expire = AsyncMock(return_value=True)
    return mock


@pytest.fixture
async def mock_db_session() -> AsyncGenerator[AsyncMock]:
    """Create a mock database session for testing."""
    mock = AsyncMock()
    mock.execute = AsyncMock()
    mock.commit = AsyncMock()
    mock.rollback = AsyncMock()
    mock.close = AsyncMock()
    # A real session's `info` is a plain dict, and it is where `spawn_after_commit`
    # queues work for after the commit. Left as an `AsyncMock`, `setdefault` answers
    # a coroutine and any service deferring work raises inside the mock rather than
    # in the code being tested.
    mock.info = {}
    yield mock


@pytest.fixture
async def client(
    mock_redis: MagicMock,
    mock_db_session,
) -> AsyncGenerator[AsyncClient]:
    """Async HTTP client for testing.

    Uses HTTPX AsyncClient with ASGITransport instead of Starlette's TestClient.
    This allows proper async testing without thread pool overhead.
    """
    # Override dependencies for testing
    app.dependency_overrides[get_redis] = lambda: mock_redis
    app.dependency_overrides[get_db_session] = lambda: mock_db_session

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    # Clear overrides after test
    app.dependency_overrides.clear()


@pytest.fixture
def api_key_headers() -> dict[str, str]:
    """Headers with valid API key."""
    return {settings.API_KEY_HEADER: settings.API_KEY}


# Note: For integration tests requiring authenticated users,
# use dependency overrides with mock users instead of test_user fixture.
# See tests/api/test_auth.py and tests/api/test_users.py for examples.
