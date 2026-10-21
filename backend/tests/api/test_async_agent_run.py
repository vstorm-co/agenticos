"""What an asynchronous run answers, through the mounted app (#2219).

The `202`, its `Location` and `Preference-Applied` are headers the handler sets
on its own response, so only a request through the app sees them; what the
service queues is `tests/integration/test_api_run_requests.py`'s.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.schemas.agent import MAX_RUN_FILES, MAX_RUN_PROMPT_CHARS, RunRequestRead

pytestmark = pytest.mark.anyio

_AGENT_ID = uuid4()
_QUEUED = RunRequestRead(
    id=uuid4(),
    status="queued",
    conversation_id=uuid4(),
    created_at=datetime(2026, 10, 19, tzinfo=UTC),
    finished_at=None,
    error=None,
    result=None,
)


@asynccontextmanager
async def _client(api_runs: MagicMock) -> AsyncIterator[AsyncClient]:
    context = AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OWNER.value)
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.limit_agent_run] = lambda: None
    app.dependency_overrides[deps.get_api_run_service] = lambda: api_runs
    app.dependency_overrides[deps.get_db_session] = lambda: MagicMock()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


async def test_asking_for_async_queues_the_run_and_points_at_it() -> None:
    api_runs = MagicMock(queue=AsyncMock(return_value=_QUEUED))
    async with _client(api_runs) as client:
        response = await client.post(
            f"/api/v1/agents/{_AGENT_ID}/run",
            json={"prompt": "summarise the week"},
            headers={"Prefer": "wait=10, respond-async", "Idempotency-Key": "order-7"},
        )

    assert response.status_code == 202
    assert response.headers["Location"] == f"/api/v1/run-requests/{_QUEUED.id}"
    assert response.headers["Preference-Applied"] == "respond-async"
    assert response.json()["status"] == "queued"
    assert api_runs.queue.await_args.kwargs == {"idempotency_key": "order-7"}


async def test_an_idempotency_key_on_a_synchronous_run_is_refused() -> None:
    api_runs = MagicMock(queue=AsyncMock())
    async with _client(api_runs) as client:
        response = await client.post(
            f"/api/v1/agents/{_AGENT_ID}/run",
            json={"prompt": "summarise the week"},
            headers={"Idempotency-Key": "order-7"},
        )

    assert response.status_code == 400
    assert response.json()["error"]["details"] == {"header": "Idempotency-Key"}
    api_runs.queue.assert_not_awaited()


async def test_the_request_is_read_back_from_its_location() -> None:
    api_runs = MagicMock(get=AsyncMock(return_value=_QUEUED))
    async with _client(api_runs) as client:
        response = await client.get(f"/api/v1/run-requests/{_QUEUED.id}")

    assert response.status_code == 200
    assert response.json()["id"] == str(_QUEUED.id)


@pytest.mark.parametrize(
    ("header", "wants"),
    [
        (None, False),
        ("respond-async", True),
        ("Respond-Async", True),
        ("return=minimal, respond-async", True),
        ("respond-async=1", True),
        ("wait=10", False),
        ("respond-asynchronously", False),
    ],
)
def test_the_prefer_header_is_read_as_rfc_7240_tokens(header: str | None, wants: bool) -> None:
    assert deps.prefers_async(header) is wants


@pytest.mark.parametrize(
    "body",
    [
        {"prompt": "x" * (MAX_RUN_PROMPT_CHARS + 1)},
        {"prompt": "hi", "file_ids": [str(uuid4()) for _ in range(MAX_RUN_FILES + 1)]},
    ],
    ids=["prompt", "files"],
)
async def test_a_request_past_the_caps_is_refused_before_anything_is_queued(
    body: dict[str, object],
) -> None:
    """Codex P1 on #2248: an unbounded prompt went into a queued job's JSONB whole."""
    api_runs = MagicMock(queue=AsyncMock(return_value=_QUEUED))
    async with _client(api_runs) as client:
        response = await client.post(
            f"/api/v1/agents/{_AGENT_ID}/run", json=body, headers={"Prefer": "respond-async"}
        )

    assert response.status_code == 422
    api_runs.queue.assert_not_awaited()
