"""Test configuration and fixtures.

Uses anyio for async testing instead of pytest-asyncio.
This allows using the same async primitives that Starlette uses internally.
See: https://anyio.readthedocs.io/en/stable/testing.html
"""
# ruff: noqa: I001 - Imports structured for Jinja2 template conditionals

import os
import re
import tempfile
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


# Prefect reads `.env` itself - its own settings model carries `env_file=".env"` - so
# `PREFECT_API_URL=http://localhost:4200/api`, which `backend/.env` sets for `make dev`,
# is also the address a `@flow` call in this suite tries to reach. With no server up
# that is `RuntimeError: Failed to reach API at http://localhost:4200/api/` out of a
# test that patched every collaborator it has, which is #536: the failure belongs to the
# environment and reads as the test's. CI never saw it, having no `.env` and therefore no
# URL at all, so what a laptop ran was never what CI ran.
#
# Deleting the variable would not do it: an unset variable leaves the dotenv source to
# answer, and the dotenv source is what holds the URL. An empty *assignment* is what
# outranks it, because Prefect's settings model carries `env_ignore_empty=False` and an
# empty string is therefore an answer rather than a silence. That is Prefect's rule and
# not ours: `app/core/config.py` sets it the other way, so the same line against one of
# *our* settings is discarded and the `.env` answers anyway - which is why the password
# above is checked for rather than emptied. Prefect reads an empty URL as no URL and
# runs the flow against a temporary server of its own, which is what CI has always done.
# Unconditionally, because the point is that the two agree: a developer with `make dev`
# up gets the same run CI gets rather than a different code path.
#
# That server keeps its state in a SQLite database under `PREFECT_HOME`, which is
# `~/.prefect` unless something says otherwise - a developer's own Prefect data, and the
# file a locally run `prefect server` has open. Pointed at a directory of the tests' own
# for the same reason as the database name above: a unit run has no business writing
# there. One directory rather than one per process, because what costs is creating it.
#
# Ephemeral mode is named rather than assumed. It is the default today, but with no URL
# and no ephemeral server a `@flow` call does not fail - it retries for 75 seconds and
# then fails, which is a worse version of the bug this removes.
#
# Creating that database is a migration, and the allowance for it is raised past
# Prefect's own 20 seconds as headroom rather than because 20 has been seen to fail:
# against a `PREFECT_HOME` nothing had written yet the whole start takes about six
# seconds here and about nine on a CI runner, which is cold on every run. What 90 buys
# is that the one step whose cost nothing here bounds - a migration on a contended
# machine, or a temporary directory that has been swept - waits instead of failing a
# suite that a second run would pass.
os.environ["PREFECT_API_URL"] = ""
os.environ["PREFECT_HOME"] = str(Path(tempfile.gettempdir()) / "agenticos-prefect-test")
os.environ["PREFECT_SERVER_EPHEMERAL_ENABLED"] = "true"
os.environ["PREFECT_SERVER_EPHEMERAL_STARTUP_TIMEOUT_SECONDS"] = "90"

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.core.config import settings
from app.api.deps import get_redis
from app.clients.redis import RedisClient
from app.api.deps import get_db_session


@pytest.fixture
def anyio_backend() -> str:
    """Specify the async backend for anyio tests.

    Options: "asyncio" or "trio". We use asyncio since that's what uvicorn uses.
    """
    return "asyncio"


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
async def mock_db_session() -> AsyncGenerator[AsyncMock, None]:
    """Create a mock database session for testing."""
    mock = AsyncMock()
    mock.execute = AsyncMock()
    mock.commit = AsyncMock()
    mock.rollback = AsyncMock()
    mock.close = AsyncMock()
    yield mock


@pytest.fixture
async def client(
    mock_redis: MagicMock,
    mock_db_session,
) -> AsyncGenerator[AsyncClient, None]:
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
