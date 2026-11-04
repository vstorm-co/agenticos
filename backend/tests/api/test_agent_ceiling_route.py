"""`GET /agents/ceiling`: the organization's agent limit, read before a create (#2488).

The agents page reads it to say **New agent** would be refused before the
dialog is filled in. The service computes it (`tests/test_agent_registry.py`,
`tests/integration/test_deployment_limits.py`); what is left is the route - its
gate, its shape, and that the paged list no longer recomputes it on every page.
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


def _context(role: str) -> AuthContext:
    return AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=role)


@pytest.fixture
def service() -> Iterator[MagicMock]:
    registry = MagicMock()
    registry.list_agents = AsyncMock(return_value=([], 0))
    registry.list_labels = AsyncMock(return_value=([], []))
    registry.ceiling = AsyncMock(return_value=AgentCeiling(limit=None, held=None, at_limit=False))
    app.dependency_overrides[deps.get_auth_context] = lambda: _context(OrgRoleName.BUILDER)
    app.dependency_overrides[deps.get_agent_registry_service] = lambda: registry
    yield registry
    app.dependency_overrides.clear()


async def _get(path: str) -> tuple[int, dict[str, object]]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"{settings.API_V1_STR}{path}")
    return response.status_code, response.json()


async def test_a_limit_answers_with_the_count_against_it(service: MagicMock) -> None:
    service.ceiling.return_value = AgentCeiling(limit=5, held=5, at_limit=True)

    status, body = await _get("/agents/ceiling")

    assert status == 200
    assert body == {"limit": 5, "held": 5, "at_limit": True}


async def test_a_scoped_caller_gets_no_count(service: MagicMock) -> None:
    service.ceiling.return_value = AgentCeiling(limit=5, held=None, at_limit=False)

    _status, body = await _get("/agents/ceiling")

    assert body == {"limit": 5, "held": None, "at_limit": False}


async def test_an_uncapped_deployment_answers_no_limit(service: MagicMock) -> None:
    _status, body = await _get("/agents/ceiling")

    assert body == {"limit": None, "held": None, "at_limit": False}


async def test_a_caller_who_cannot_create_is_refused(service: MagicMock) -> None:
    """A Viewer has no create to forecast, and the count is not theirs to read."""
    app.dependency_overrides[deps.get_auth_context] = lambda: _context(OrgRoleName.VIEWER)

    status, _body = await _get("/agents/ceiling")

    assert status == 403
    service.ceiling.assert_not_awaited()


async def test_the_list_does_not_count_the_ceiling(service: MagicMock) -> None:
    """Paging through `/agents` must not recount the organization on every page."""
    status, body = await _get("/agents?skip=50")

    assert status == 200
    assert "ceiling" not in body
    service.ceiling.assert_not_awaited()
