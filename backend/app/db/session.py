"""Async PostgreSQL database session."""

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.background import discard_deferred, start_deferred
from app.core.config import settings
from app.core.exceptions import AppException

logger = logging.getLogger(__name__)

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DB_ECHO,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,
)

# The vector store's pool, deliberately not the one above. A vector query runs
# *inside* a request whose session already holds a connection from `engine` for
# the whole handler, so putting both on one pool makes saturation a circular
# wait: fifteen concurrent searches each hold one connection and block waiting
# for a second, and nothing progresses until `DB_POOL_TIMEOUT` expires the lot.
# One deliberate second pool for the process's vector work - the lifespan's
# store, the per-request fallback, the knowledge capability - not one per store
# instance, which is the shape #948 removed. Lazy like every engine here: a
# deployment that never searches never connects it.
vector_engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DB_ECHO,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,
)

# The knowledge capability's store, and pool-less on purpose. A pooled asyncpg
# connection belongs to the event loop that opened it, and the capability is the
# one vector caller that runs on a loop nobody here chose: an agent runs inside
# a Prefect worker as well as inside the API, so a second flow run in one worker
# process reaches this from a *different* loop and a pooled connection made on
# the first breaks it (`InterfaceError: attached to a different loop`) (#1079).
# `NullPool` caches nothing, so there is no connection to hand to the wrong
# loop, no second `DB_POOL_SIZE + DB_MAX_OVERFLOW` pool of the kind #948
# removed, and no circular wait against a request that already holds a
# connection (#12) - at the price of one connect per search, which sits beside
# an embedding request that costs an order of magnitude more.
agent_vector_engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DB_ECHO,
    poolclass=NullPool,
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@asynccontextmanager
async def _managed_session(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    """Shared session lifecycle: commit on success, rollback on error.

    Background work registered with `spawn_after_commit` starts here, in the
    two statements after the commit and nowhere else. That is what makes the
    ordering a property of the session rather than of each call site: a flow
    dispatched from a service reads a row the database has already agreed to,
    whether the session belongs to a request, a WebSocket or a worker (#417).

    The `finally` closes anything still queued. A commit that raised, an
    exception thrown in at the `yield`, a cancelled request - each leaves
    coroutines that were created and will now never be awaited, and an
    un-awaited coroutine reports itself as a `RuntimeWarning` from wherever the
    garbage collector happens to be.
    """
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception as exc:
            # A domain refusal (a 4xx AppException) is an ordinary outcome, not an
            # application error, so it rolls back without a traceback - the ERROR
            # line, and its stack, is kept for the unexpected and for 5xx faults (#19).
            if not isinstance(exc, AppException) or exc.status_code >= 500:
                logger.exception("DB session error, rolling back")
            try:
                await session.rollback()
            except Exception:
                logger.exception("DB session rollback failed")
            raise
        else:
            start_deferred(session)
        finally:
            discard_deferred(session)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """The request's session, for FastAPI dependency injection.

    **Depend on it through `app.api.deps.DBSession`, never through a bare
    `Depends(get_db_session)`.** The alias declares `scope="function"`, and that
    is what decides whether a client can act on its own 2xx: the code after the
    `yield` above runs when the exit stack it was registered on unwinds, and
    FastAPI's default for a generator dependency is the stack that unwinds
    *after* `await response(scope, receive, send)` - after the answer has gone
    out. A bare `Depends(get_db_session)` therefore reintroduces #353, in which a
    membership row was invisible to the very next request for 21.7ms and an
    invitation token was spent 34ms before the transaction that minted it
    committed.

    `tests/api/test_db_session_scope.py` walks the mounted routes and refuses
    one that asks for a session any other way.
    """
    async with _managed_session(async_session_maker) as session:
        yield session


_pooled_loop: asyncio.AbstractEventLoop | None = None


def claim_pooled_engines() -> None:
    """Record that this loop owns the process's pooled engines.

    Called once by the API lifespan. A pooled asyncpg connection belongs to the
    loop that opened it, so the two module engines above are usable from exactly
    one loop - and only the loop that starts the application, disposes them at
    shutdown and serves every request between the two has a claim on them. A
    process with no lifespan - a worker, the CLI, the test suite - claims
    nothing, which is the answer `get_db_context` wants below.
    """
    global _pooled_loop
    _pooled_loop = asyncio.get_running_loop()


def release_pooled_engines() -> None:
    """Give the claim up, at shutdown, so a second lifespan can take it.

    A test or a reload runs another lifespan in the same process, on another
    loop; leaving the old loop stamped would tell that one it owns pools whose
    connections were opened on a loop that has gone.
    """
    global _pooled_loop
    _pooled_loop = None


def on_the_pooled_loop() -> bool:
    """Whether the running loop is the one that owns the pooled engines."""
    try:
        return _pooled_loop is asyncio.get_running_loop()
    except RuntimeError:
        return False


@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    """A session for manual management: a WebSocket, a worker task, a command.

    Pooled on the loop that owns the pools, and a `NullPool` engine of its own
    anywhere else. The distinction is not decoration: this is reached from
    Prefect flows (the report, MCP refresh, invitation and approval tasks, the
    channel loops) and from an agent's embedding resolver, each on a loop of its
    own, and a pooled connection made on one loop breaks whoever checks it out
    on the next - `InterfaceError: attached to a different loop`, intermittent,
    and invisible to any test with one loop in it (#1079). Off the owning loop
    it therefore does exactly what `get_worker_db_context` does, at one connect
    per call, which is the price the worker already pays deliberately for its
    ingestion flows (#948).
    """
    if not on_the_pooled_loop():
        async with get_worker_db_context() as session:
            yield session
        return

    async with _managed_session(async_session_maker) as session:
        yield session


@asynccontextmanager
async def get_worker_db_context() -> AsyncGenerator[AsyncSession, None]:
    """Get a short-lived async session for background workers (Celery/ARQ).

    Creates a fresh engine with NullPool on every call so there are no
    cross-fork / cross-event-loop connection issues.  The engine is disposed
    automatically when the context manager exits.

    It is `_managed_session` and not a second copy of it: the copy it used to be
    committed and rolled back identically, but would have been the one session
    lifecycle in the codebase where `spawn_after_commit` queued work that
    nothing ever started - which is worse than not offering it at all.
    """
    worker_engine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        poolclass=NullPool,
    )
    factory = async_sessionmaker(
        worker_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    try:
        async with _managed_session(factory) as session:
            yield session
    finally:
        await worker_engine.dispose()


async def close_db() -> None:
    """Close database connections - both process pools and the agents' engine."""
    await engine.dispose()
    await vector_engine.dispose()
    await agent_vector_engine.dispose()
    release_pooled_engines()
