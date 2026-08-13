"""A flow dispatched from a request finds the row that dispatched it.

#417: three services hand a Prefect flow to `spawn` from inside an endpoint,
and the flow's first act is to read by id the row the endpoint has just
written. The task is created immediately and the loop starts it at the next
suspension point - which is well before the request's transaction commits, and
the flow opens a session of its own, so under `READ COMMITTED` it cannot see
the row at all. What follows is an upload answered `{"status": "processing"}`
that stays that way forever.

The ordering is observed rather than sampled. The first two tests drive the same
one-route application over ASGI, differing only in *which* handoff the route
uses, and the flow's first act is to ask a second connection whether the row is
visible to anyone but the request. Under `READ COMMITTED` that answer is a fact
about the ordering, not a bet on timing. The third is the failure path: a
request that raises dispatches nothing at all.

What makes it deterministic in both directions is what the route does after
handing the work over: it awaits whatever tasks the handoff created, and nothing
else. `spawn` creates one, so the flow takes its reading inside the request and
finds an uncommitted database every time. `spawn_after_commit` creates none, so
there is nothing to await, the route returns, the session commits, and only then
does the flow read. One route, two handoffs, opposite answers - and neither of
them a bet on the loop scheduling a task inside a fixed grace, which is what made
this file flake under `make test`'s four workers and coverage (#680).
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

pytestmark = pytest.mark.anyio

# Spelled out per statement rather than interpolated from a constant: ruff reads
# an f-string reaching a cursor as SQL injection (S608), and is right to.
_CREATE = "CREATE TABLE dispatch_ordering_probe (id uuid PRIMARY KEY)"
_DROP = "DROP TABLE IF EXISTS dispatch_ordering_probe"
_INSERT = "INSERT INTO dispatch_ordering_probe (id) VALUES (:id)"
_SELECT = "SELECT 1 FROM dispatch_ordering_probe WHERE id = :id"

# The only clock left in this file, and a passing run never spends it: every
# wait below is on a task or an event that has already been created, so the
# deadline is a guard against hanging rather than a window to fit inside.
_PATIENCE = 5.0

Handoff = Callable[[AsyncSession, Coroutine[Any, Any, None]], None]


@pytest.fixture
async def probe_table(engine: AsyncEngine) -> AsyncGenerator[AsyncEngine, None]:
    """A table to write one row into, and the engine that watches for it.

    Deliberately not one of the product's own tables: this asserts a property of
    dispatch, and must not start failing because a model grew a `NOT NULL`
    column. Outside the metadata means the `engine` fixture's per-test reset
    only empties model tables, so it is dropped here rather than left for the
    reset to find.
    """
    async with engine.begin() as connection:
        await connection.execute(text(_DROP))
        await connection.execute(text(_CREATE))
    yield engine
    async with engine.begin() as connection:
        await connection.execute(text(_DROP))


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


@contextlib.asynccontextmanager
async def _awaiting_whatever_it_starts() -> AsyncGenerator[None, None]:
    """Let the tasks created inside the block run to completion before going on.

    This is the ordering probe itself. Which tasks to wait for is settled by
    diffing the loop's own set across the block rather than by taking the
    handoff's word for it, so a `spawn_after_commit` that began spawning
    immediately is waited for here and caught, instead of being agreed with.

    It replaces a fixed 250ms grace, which was a bet that the loop would
    schedule the task inside it. Under `make test` - four xdist workers and
    coverage instrumentation on one machine - that bet loses often enough to
    turn the ordering property red for reasons that are not the diff (#680).
    """
    before = asyncio.all_tasks()
    yield
    started = asyncio.all_tasks() - before
    if started:
        await asyncio.wait(started, timeout=_PATIENCE)


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
        # Standing in for the several suspension points a real endpoint has
        # left before its commit.
        async with _awaiting_whatever_it_starts():
            handoff(db, flow())
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

    async with _awaiting_whatever_it_starts():
        with caplog.at_level(logging.WARNING, logger="app.core.background"):
            answered = await _drive(_application(dispatch))

    assert answered == status.HTTP_404_NOT_FOUND
    assert not started.is_set(), "a flow ran for a row the database threw away"
    assert not await _committed(probe_table, row_id)
    assert "probe-flow" in caplog.text
