"""What `GET /runs/{run_id}/transcript` puts on the wire.

The authorization *logic* is proven against the service in
`tests/test_run_transcript.py` and end to end in
`tests/integration/test_run_transcript_access.py`. What belongs here is the
wiring: that the route hands the service the caller and the id, serializes the
run's turns into `RunTranscript`, and surfaces each refusal the service raises as
the status a client will branch on - a missing or cross-tenant run as one 404
shape, a caller without `runs:view` as a 403.

The route carries no `require()` gate on purpose - reading a run is authorized,
not owned, so the decision is the service's - which is why the gate sweep in
`tests/api/test_platform_routes.py` reaches it through the resource-aware runner
service rather than through the permission table.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.db.models.conversation import Message
from app.main import app

pytestmark = pytest.mark.anyio

_ORGANIZATION_ID = uuid4()

# What `transcript_ratings` returns for a turn nobody rated - the three fields
# present and empty, which is how a plain turn serializes identically to a rated
# one until somebody rates it.
_NO_RATING = {"user_rating": None, "rating_count": None, "rating_comment": None}


@asynccontextmanager
async def _client(service: MagicMock) -> AsyncIterator[AsyncClient]:
    context = AuthContext(
        user_id=uuid4(), organization_id=_ORGANIZATION_ID, role=OrgRoleName.OPERATOR.value
    )
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_agent_runner_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def _message(*, run_id, content: str) -> Message:
    """A transient message whose relationships are set, so serializing it needs
    no session - the production route loads them with `selectinload`."""
    message = Message(
        id=uuid4(),
        conversation_id=uuid4(),
        run_id=run_id,
        role="assistant",
        content=content,
        created_at=datetime(2026, 8, 6, 9, 0, tzinfo=UTC),
    )
    message.tool_calls = []
    message.files = []
    return message


async def test_the_transcript_is_served_with_its_run_and_turns() -> None:
    run = MagicMock(id=uuid4(), conversation_id=uuid4())
    message = _message(run_id=run.id, content="two are open")
    service = MagicMock(
        get_run_transcript=AsyncMock(return_value=(run, [message], 1)),
        transcript_ratings=AsyncMock(return_value={message.id: _NO_RATING}),
    )

    async with _client(service) as client:
        response = await client.get(f"/api/v1/runs/{run.id}/transcript")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["run_id"] == str(run.id)
    assert body["conversation_id"] == str(run.conversation_id)
    assert body["total"] == 1
    assert [(item["role"], item["content"]) for item in body["items"]] == [
        ("assistant", "two are open")
    ]
    # The caller and the id reached the service; the route decides nothing itself.
    assert service.get_run_transcript.await_args.args[1] == run.id


async def test_a_down_rated_turn_carries_its_verdict_and_the_words_left_with_it() -> None:
    """The three fields the run-detail feedback panel reads, sourced from the
    service and copied onto the turn: a plain `MessageRead` carries none of them,
    so a turn that shows a comment is the whole reason this route exists (#209)."""
    run = MagicMock(id=uuid4(), conversation_id=uuid4())
    message = _message(run_id=run.id, content="the refund window is 30 days")
    service = MagicMock(
        get_run_transcript=AsyncMock(return_value=(run, [message], 1)),
        transcript_ratings=AsyncMock(
            return_value={
                message.id: {
                    "user_rating": -1,
                    "rating_count": {"likes": 0, "dislikes": 2},
                    "rating_comment": "it invented a policy we do not have",
                }
            }
        ),
    )

    async with _client(service) as client:
        response = await client.get(f"/api/v1/runs/{run.id}/transcript")

    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert item["user_rating"] == -1
    assert item["rating_count"] == {"likes": 0, "dislikes": 2}
    assert item["rating_comment"] == "it invented a policy we do not have"
    # The route asked the service for the ratings of the turns it is about to serve.
    assert service.transcript_ratings.await_args.args[1] == [message.id]


async def test_a_missing_or_cross_tenant_run_is_a_404_naming_only_the_id() -> None:
    """One 404 shape for both, because the service answers a foreign run exactly
    as it answers a fictional one - the response cannot be used to tell them
    apart."""
    run_id = uuid4()
    service = MagicMock(
        get_run_transcript=AsyncMock(
            side_effect=NotFoundError(message="Run not found", details={"run_id": str(run_id)})
        )
    )

    async with _client(service) as client:
        response = await client.get(f"/api/v1/runs/{run_id}/transcript")

    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "NOT_FOUND"
    assert error["message"] == "Run not found"
    assert error["details"] == {"run_id": str(run_id)}


async def test_a_caller_without_runs_view_is_refused() -> None:
    run_id = uuid4()
    service = MagicMock(
        get_run_transcript=AsyncMock(
            side_effect=AuthorizationError(
                message="Insufficient permissions",
                details={"required": [Perm.RUNS_VIEW.value], "run_id": str(run_id)},
            )
        )
    )

    async with _client(service) as client:
        response = await client.get(f"/api/v1/runs/{run_id}/transcript")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "AUTHORIZATION_ERROR"


async def test_a_run_with_no_conversation_says_so_rather_than_an_empty_list() -> None:
    """`conversation_id: null` with no turns is "this run has no transcript" - the
    distinction a client draws from an empty list under a real conversation id,
    which would read as "it did nothing"."""
    run = MagicMock(id=uuid4(), conversation_id=None)
    service = MagicMock(
        get_run_transcript=AsyncMock(return_value=(run, [], 0)),
        transcript_ratings=AsyncMock(return_value={}),
    )

    async with _client(service) as client:
        response = await client.get(f"/api/v1/runs/{run.id}/transcript")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["conversation_id"] is None
    assert body["items"] == []
    assert body["total"] == 0
