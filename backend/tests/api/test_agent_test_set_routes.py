"""The agent test set routes, through the app.

`tests/integration/test_agent_test_set.py` proves what the service does and
refuses; here, that each route reaches it with what was sent and answers its shape.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.exceptions import AuthorizationError
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.schemas.agent_test_set import (
    AgentTestSetBootstrap,
    AgentTestSetCounts,
    AgentTestSetEstimate,
    AgentTestSetJudge,
)

pytestmark = pytest.mark.anyio

_AGENT = uuid.uuid4()
_BUILT = AgentTestSetBootstrap(
    dataset_id=uuid.uuid4(),
    version=1,
    created=True,
    counts=AgentTestSetCounts(
        rated_good=2, rated_bad=1, skipped=0, from_others=1, generated_requested=2
    ),
    generation_id=uuid.uuid4(),
    judge=AgentTestSetJudge(agent_id=uuid.uuid4(), independent=True),
    gradable=3,
    too_few=False,
)


@pytest.fixture
def service() -> MagicMock:
    stub = MagicMock()
    stub.bootstrap_for_agent = AsyncMock(return_value=_BUILT)
    stub.estimate_bootstrap = AsyncMock(
        return_value=AgentTestSetEstimate(cost_usd=Decimal("0.01"), priced=True, generate=5)
    )
    return stub


@pytest.fixture
async def http(mock_redis: MagicMock, service: MagicMock) -> AsyncIterator[AsyncClient]:
    context = AuthContext(
        user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER
    )
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_agent_test_set_service] = lambda: service
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


def _url(path: str) -> str:
    return f"{settings.API_V1_STR}{path}"


async def test_building_a_test_set_passes_the_window_and_the_count(
    http: AsyncClient, service: MagicMock
) -> None:
    since = datetime(2026, 10, 1, tzinfo=UTC)

    response = await http.post(
        _url(f"/agents/{_AGENT}/test-set"), json={"since": since.isoformat(), "more": 5}
    )

    assert response.status_code == 200
    assert response.json()["counts"]["rated_bad"] == 1
    _, agent_id = service.bootstrap_for_agent.await_args.args
    assert agent_id == _AGENT
    assert service.bootstrap_for_agent.await_args.kwargs == {"since": since, "more": 5}


async def test_an_estimate_writes_nothing_and_says_how_many(
    http: AsyncClient, service: MagicMock
) -> None:
    response = await http.post(_url(f"/agents/{_AGENT}/test-set/estimate"), json={})

    assert response.status_code == 200
    assert response.json() == {"cost_usd": "0.01", "priced": True, "generate": 5}
    assert service.estimate_bootstrap.await_args.kwargs == {"more": None}
    service.bootstrap_for_agent.assert_not_awaited()


async def test_a_refusal_and_an_out_of_range_count_answer_as_errors(
    http: AsyncClient, service: MagicMock
) -> None:
    service.bootstrap_for_agent.side_effect = AuthorizationError(message="Not allowed")

    refused = await http.post(_url(f"/agents/{_AGENT}/test-set"), json={})
    too_many = await http.post(_url(f"/agents/{_AGENT}/test-set"), json={"more": 51})

    assert (refused.status_code, too_many.status_code) == (403, 422)
