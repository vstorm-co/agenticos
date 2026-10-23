"""The A2A task endpoint, through the app: which requests count as runs.

`tests/test_a2a_server.py` proves what a request does; what is left is the
route - that only a request which runs the agent is charged against the
caller's run allowance, so a client polling its task does not run out.
"""

import uuid
from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app

pytestmark = pytest.mark.anyio

AGENT = uuid.uuid4()
URL = f"/api/v1/a2a/{AGENT}"


@pytest.fixture
def service(mock_redis: MagicMock) -> Iterator[MagicMock]:
    served = MagicMock(handle=AsyncMock(return_value={"jsonrpc": "2.0", "id": 1, "result": {}}))
    context = AuthContext(
        user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER
    )
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_a2a_server_service] = lambda: served
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    yield served
    app.dependency_overrides.clear()


async def _post(body: object | None = None, *, raw: bytes | None = None) -> dict:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        response = await (
            http.post(URL, content=raw, headers={"Content-Type": "application/json"})
            if raw is not None
            else http.post(URL, json=body)
        )
    return response.json()


@pytest.fixture
def limiter() -> Iterator[AsyncMock]:
    with patch("app.api.routes.v1.a2a.limit_agent_run", AsyncMock()) as limit:
        yield limit


async def test_a_message_that_runs_the_agent_is_counted(
    service: MagicMock, limiter: AsyncMock
) -> None:
    await _post({"jsonrpc": "2.0", "id": 1, "method": "message/send", "params": {}})
    limiter.assert_awaited_once()
    assert service.handle.await_args.args[1] == AGENT


@pytest.mark.parametrize(
    "body",
    [
        {"jsonrpc": "2.0", "id": 1, "method": "tasks/get", "params": {"id": "t"}},
        {"jsonrpc": "2.0", "id": 1, "method": "tasks/cancel", "params": {"id": "t"}},
        {"jsonrpc": "2.0", "id": 1, "method": "message/stream", "params": {}},
        [1, 2],
    ],
    ids=["tasks-get", "tasks-cancel", "refused-method", "not-a-request"],
)
async def test_nothing_that_starts_no_run_is_counted(
    service: MagicMock, limiter: AsyncMock, body: object
) -> None:
    """A probe or a refused request spent the allowance a later message needed."""
    await _post(body)
    limiter.assert_not_awaited()
    service.handle.assert_awaited_once()


async def test_a_body_that_is_not_json_is_a_parse_error(
    service: MagicMock, limiter: AsyncMock
) -> None:
    answer = await _post(raw=b"{not json")
    assert answer["error"]["message"] == "Not JSON"
    limiter.assert_not_awaited()
    service.handle.assert_not_awaited()
