"""`GET /agents` carries the organization's agent limit and its count (#2488).

The agents page reads it to say **New agent** would be refused before the
dialog is filled in. The service computes it (`tests/test_agent_registry.py`,
`tests/integration/test_deployment_limits.py`); what is left is the response
shape - the pair when a limit is set, null when the deployment sets none.
"""

import uuid
from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.schemas.agent import AgentCeiling

pytestmark = pytest.mark.anyio


@pytest.fixture
def service() -> Iterator[MagicMock]:
    registry = MagicMock()
    registry.list_agents = AsyncMock(return_value=([], 0))
    registry.list_labels = AsyncMock(return_value=([], []))
    registry.ceiling = AsyncMock(return_value=None)
    context = AuthContext(
        user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.BUILDER
    )
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_agent_registry_service] = lambda: registry
    yield registry
    app.dependency_overrides.clear()


async def _list() -> dict[str, object]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"{settings.API_V1_STR}/agents")
    assert response.status_code == 200
    return response.json()


async def test_a_limit_answers_with_the_count_against_it(service: MagicMock) -> None:
    service.ceiling.return_value = AgentCeiling(limit=5, held=5)

    body = await _list()

    assert body["ceiling"] == {"limit": 5, "held": 5}


async def test_an_uncapped_deployment_answers_null(service: MagicMock) -> None:
    body = await _list()

    assert body["ceiling"] is None
