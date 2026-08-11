"""A 2xx from this API means the write is readable, not merely accepted.

#353: `get_db_session` commits in the exit code of a dependency with `yield`,
and FastAPI's default is to unwind that stack *after* `await response(scope,
receive, send)`. So the answer went out first and the transaction committed
afterwards - measured at 21.7ms on a real backend, with a membership row
invisible to the very next request and an invitation token spent 34ms before
the transaction that minted it committed.

The tests here do not sample that race, they observe the ordering directly: the
app is driven as a bare ASGI application, and the moment `http.response.start`
is handed to the transport, a *second* connection is asked whether the row is
there. Under `READ COMMITTED` that connection can only see committed work, so
the answer is a fact about the ordering rather than a bet on timing. Against the
ordering this file was written to fix, it is `False` every single time.

The application under test is built here rather than imported: it is one route,
so what failed is unambiguous, and it takes the same `DBSession` alias every
real route takes - which is the thing being checked - through the same
`BaseHTTPMiddleware` the real app puts in front of them.
"""

from collections.abc import AsyncGenerator
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api.deps import DBSession
from app.api.exception_handlers import register_exception_handlers
from app.core.exceptions import NotFoundError
from app.core.middleware import RequestIDMiddleware

pytestmark = pytest.mark.anyio

# Spelled out in each statement rather than interpolated from a constant: ruff
# reads an f-string reaching a cursor as SQL injection (S608) and is right to,
# even where the value is a literal three lines up.
_CREATE = "CREATE TABLE commit_ordering_probe (id uuid PRIMARY KEY)"
_DROP = "DROP TABLE IF EXISTS commit_ordering_probe"
_INSERT = "INSERT INTO commit_ordering_probe (id) VALUES (:id)"
_SELECT = "SELECT 1 FROM commit_ordering_probe WHERE id = :id"


@pytest.fixture
async def probe_table(engine: AsyncEngine) -> AsyncGenerator[AsyncEngine, None]:
    """A table to write one row into, and the engine that watches for it.

    Not one of the product's own tables on purpose: this asserts a property of
    the request lifecycle, and it should not start failing because a model grew
    a `NOT NULL` column. The cost of being outside the metadata is that the
    `engine` fixture's per-test reset only empties model tables, so it is
    dropped here rather than left for the reset to find.
    """
    async with engine.begin() as connection:
        await connection.execute(text(_DROP))
        await connection.execute(text(_CREATE))
    yield engine
    async with engine.begin() as connection:
        await connection.execute(text(_DROP))


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)

    @app.post("/write", status_code=status.HTTP_204_NO_CONTENT)
    async def write(row_id: UUID, db: DBSession) -> Response:
        await db.execute(text(_INSERT), {"id": row_id})
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post("/write-then-fail", status_code=status.HTTP_204_NO_CONTENT)
    async def write_then_fail(row_id: UUID, db: DBSession) -> Response:
        await db.execute(text(_INSERT), {"id": row_id})
        raise NotFoundError(message="decided after the write", details={"row_id": row_id})

    return app


async def _committed(engine: AsyncEngine, row_id: UUID) -> bool:
    """Is the row visible to a connection that is not the request's?"""
    async with engine.connect() as connection:
        found = await connection.execute(text(_SELECT), {"id": row_id})
        return found.scalar_one_or_none() is not None


async def _post(path: str, row_id: UUID, engine: AsyncEngine) -> tuple[int, bool]:
    """Drive the app over ASGI, reading the row the instant the answer goes out.

    Answers the response's status and whether the row was visible to `engine` at
    the moment `http.response.start` was handed to the transport.

    `httpx`'s `ASGITransport` would do the driving, but it hands back a finished
    response - by which time the ordering being asserted has already happened one
    way or the other. The read below happens inside `send`, with the request
    suspended at exactly the point the client is being answered.
    """
    app = _app()
    answered: tuple[int, bool] | None = None

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        nonlocal answered
        if message["type"] == "http.response.start":
            answered = (message["status"], await _committed(engine, row_id))

    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": f"row_id={row_id}".encode(),
            "root_path": "",
            "headers": [(b"host", b"testserver")],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "state": {},
        },
        receive,
        send,
    )
    assert answered is not None, "the app never started a response"
    return answered


async def test_a_write_is_readable_by_the_time_its_answer_goes_out(
    probe_table: AsyncEngine,
) -> None:
    """The whole of #353, in one assertion."""
    row_id = uuid4()

    status_code, visible = await _post("/write", row_id, probe_table)

    assert status_code == status.HTTP_204_NO_CONTENT
    assert visible, (
        "the client was answered 204 while the row was still uncommitted, so a "
        "client acting on that 204 can be answered from a database the write has "
        "not reached (#353)"
    )


async def test_a_failed_write_is_rolled_back_by_the_time_its_refusal_goes_out(
    probe_table: AsyncEngine,
) -> None:
    """The other half: an error response must not outrun its own rollback.

    A refusal a caller can act on is worth as much as an acknowledgement it can
    act on. If the rollback landed after the 404, a caller retrying on that 404
    could collide with a row that was about to disappear.

    This half passed before #353 too - an exception unwinds both of FastAPI's
    exit stacks before its handler builds a response - and is here because
    nothing said so, and because `scope="function"` is exactly the sort of change
    that could have quietly moved it.
    """
    row_id = uuid4()

    status_code, visible = await _post("/write-then-fail", row_id, probe_table)

    assert status_code == status.HTTP_404_NOT_FOUND
    assert not visible
    assert not await _committed(probe_table, row_id), "the rolled-back row arrived later"
