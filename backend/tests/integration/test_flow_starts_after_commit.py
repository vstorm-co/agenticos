"""A flow dispatched from a request finds the row that dispatched it.

#417: three services hand a Prefect flow to `spawn` from inside an endpoint,
and the flow's first act is to read by id the row the endpoint has just
written. The task is created immediately and the loop starts it at the next
suspension point - which is well before the request's transaction commits, and
the flow opens a session of its own, so under `READ COMMITTED` it cannot see
the row at all. What follows is an upload answered `{"status": "processing"}`
that stays that way forever.

The ordering is observed rather than sampled. Both tests below drive the same
one-route application over ASGI, differing only in *which* handoff the route
uses, and the flow's first act is to ask a second connection whether the row is
visible to anyone but the request. Under `READ COMMITTED` that answer is a fact
about the ordering, not a bet on timing.

What makes it deterministic in both directions is the wait in the route: after
handing the work over, the route pauses for a moment for the flow to take its
reading. `spawn` fills that pause - the task exists, so the loop runs it, and it
reads an uncommitted database every time. `spawn_after_commit` leaves it empty:
there is no task to run until the commit, so the wait times out, the route
returns, the session commits, and only then does the flow read. One route, two
handoffs, opposite answers.
"""

import asyncio
import contextlib
import logging
from collections.abc import AsyncGenerator, Callable, Coroutine
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.api.deps import DBSession
from app.api.exception_handlers import register_exception_handlers
from app.core.background import spawn, spawn_after_commit
from app.core.exceptions import NotFoundError
from app.core.middleware import RequestIDMiddleware
from app.db.session import engine as app_engine

pytestmark = pytest.mark.anyio

# Spelled out per statement rather than interpolated from a constant: ruff reads
# an f-string reaching a cursor as SQL injection (S608), and is right to.
_CREATE = "CREATE TABLE dispatch_ordering_probe (id uuid PRIMARY KEY)"
_DROP = "DROP TABLE IF EXISTS dispatch_ordering_probe"
_INSERT = "INSERT INTO dispatch_ordering_probe (id) VALUES (:id)"
_SELECT = "SELECT 1 FROM dispatch_ordering_probe WHERE id = :id"

# How long the route holds after handing the work over, and how long the test
# waits afterwards for a flow that has not run yet. The first is paid once by
# the deferred case, where nothing fills it; the second is only ever reached by
# a failure.
_GRACE = 0.25
_PATIENCE = 5.0

Handoff = Callable[[AsyncSession, Coroutine[Any, Any, None]], None]


@pytest.fixture
async def probe_table(engine: AsyncEngine) -> AsyncGenerator[AsyncEngine, None]:
    """A table to write one row into, and the engine that watches for it.

    Deliberately not one of the product's own tables: this asserts a property of
    dispatch, and must not start failing because a model grew a `NOT NULL`
    column. Outside the metadata means the `engine` fixture's `drop_all` does
    not reach it, so it is dropped here.
    """
    async with engine.begin() as connection:
        await connection.execute(text(_DROP))
        await connection.execute(text(_CREATE))
    yield engine
    async with engine.begin() as connection:
        await connection.execute(text(_DROP))
    # The route below goes through the real `get_db_session` and its pool. anyio
    # gives each test its own event loop, so a connection left in that pool is
    # one the next test finds attached to a loop that no longer exists.
    await app_engine.dispose()


async def _committed(engine: AsyncEngine, row_id: UUID) -> bool:
    """Is the row visible to a connection that is not the request's?"""
    async with engine.connect() as connection:
        found = await connection.execute(text(_SELECT), {"id": row_id})
        return found.scalar_one_or_none() is not None


def _spawn_now(session: AsyncSession, coro: Coroutine[Any, Any, None]) -> None:
    """The handoff #417 is about. It is handed the session and ignores it."""
    spawn(coro, name="probe-flow")


def _spawn_deferred(session: AsyncSession, coro: Coroutine[Any, Any, None]) -> None:
    """The handoff this file exists to pin."""
    spawn_after_commit(session, coro, name="probe-flow")


async def _drive(app: FastAPI) -> int:
    """POST /dispatch as a bare ASGI application, and answer with the status."""
    answered: list[int] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            answered.append(message["status"])

    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/dispatch",
            "raw_path": b"/dispatch",
            "query_string": b"",
            "root_path": "",
            "headers": [(b"host", b"testserver")],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "state": {},
        },
        receive,
        send,
    )
    assert len(answered) == 1, "the route did not answer"
    return answered[0]


def _application(route: Callable[..., Any]) -> FastAPI:
    """One route, through the middleware and handlers the real app puts around it."""
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)
    app.post("/dispatch", status_code=status.HTTP_204_NO_CONTENT)(route)
    return app


async def _dispatch(handoff: Handoff, engine: AsyncEngine) -> bool:
    """Write a row, hand a flow over with `handoff`, and report what it read.

    Answers whether the row was committed at the instant the flow first looked
    for it - which is the only thing the flow can act on, because it has a
    session of its own and can see nothing the database has not agreed to.
    """
    row_id = uuid4()
    read = asyncio.Event()
    seen: list[bool] = []

    async def flow() -> None:
        seen.append(await _committed(engine, row_id))
        read.set()

    async def dispatch(db: DBSession) -> Response:
        await db.execute(text(_INSERT), {"id": row_id})
        handoff(db, flow())
        # Standing in for the several suspension points a real endpoint has
        # left before its commit, and bounded so the correct handoff - which
        # cannot fill it - does not hang here.
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(read.wait(), _GRACE)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    answered = await _drive(_application(dispatch))

    assert answered == status.HTTP_204_NO_CONTENT
    await asyncio.wait_for(read.wait(), _PATIENCE)
    return seen[0]


async def test_a_dispatched_flow_can_read_the_row_that_dispatched_it(
    probe_table: AsyncEngine,
) -> None:
    """The whole of #417, in one assertion."""
    assert await _dispatch(_spawn_deferred, probe_table), (
        "the flow started before the request's transaction committed, so it "
        "looked for its own row and found nothing - the work is lost and the "
        "document stays in `processing` forever (#417)"
    )


async def test_spawning_inside_the_request_starts_before_the_row_exists(
    probe_table: AsyncEngine,
) -> None:
    """Why the deferred handoff exists, pinned rather than described.

    `spawn` is not being deprecated - it is right for work that owns everything
    it needs, which is what `app/services/notifications.py` hands it. This is
    the case it is wrong for, and it fails the same way every time rather than
    occasionally, which is why #417 went unnoticed.
    """
    assert not await _dispatch(_spawn_now, probe_table), (
        "spawning inside the request no longer outruns the commit - if that is "
        "deliberate, this file and `spawn_after_commit` are both redundant"
    )


async def test_a_request_that_fails_dispatches_nothing(probe_table: AsyncEngine, caplog) -> None:
    """The other half: work waiting on a transaction that never happened.

    The row is rolled back, so the flow would open a session, look for a
    document that does not exist and report that as an ingestion failure -
    against an id nobody can look up. It is dropped instead, with a line saying
    so, which is the only place that fact is recorded.
    """
    row_id = uuid4()
    started = asyncio.Event()

    async def flow() -> None:
        started.set()

    async def dispatch(db: DBSession) -> Response:
        await db.execute(text(_INSERT), {"id": row_id})
        spawn_after_commit(db, flow(), name="probe-flow")
        raise NotFoundError(message="decided after the write", details={"row_id": row_id})

    with caplog.at_level(logging.WARNING, logger="app.core.background"):
        answered = await _drive(_application(dispatch))
    await asyncio.sleep(_GRACE)

    assert answered == status.HTTP_404_NOT_FOUND
    assert not started.is_set(), "a flow ran for a row the database threw away"
    assert not await _committed(probe_table, row_id)
    assert "probe-flow" in caplog.text
