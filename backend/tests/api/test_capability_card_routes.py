"""The two answers to the card an agent shows for a capability it lacks (#2301).

`tests/test_agent_registry.py` proves what the service decides - publish or
wait in the draft, who may ask. What is left is the handler: it delegates with
the path and the body, answers in the shape the console reads, and refuses a
blank reason at the edge. Neither is part of the public API: a card in the
console's chat is the only caller.
"""

import uuid
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.api.public_api import is_public_route
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.schemas.agent import CapabilityEnabled

pytestmark = pytest.mark.anyio

_CTX = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.MEMBER)


@pytest.fixture
async def service() -> AsyncIterator[MagicMock]:
    registry = MagicMock()
    app.dependency_overrides[deps.get_auth_context] = lambda: _CTX
    app.dependency_overrides[deps.get_agent_registry_service] = lambda: registry
    yield registry
    app.dependency_overrides.clear()


async def _post(path: str, body: dict[str, object] | None = None):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post(f"{settings.API_V1_STR}{path}", json=body)


async def test_switching_on_answers_whether_it_went_live(service: MagicMock):
    agent_id = uuid.uuid4()
    service.enable_capability = AsyncMock(return_value=CapabilityEnabled(published=False))

    response = await _post(f"/agents/{agent_id}/capabilities/web_research/enable")

    assert response.status_code == 200
    assert response.json() == {"published": False}
    service.enable_capability.assert_awaited_once_with(_CTX, agent_id, "web_research")


async def test_asking_the_owner_passes_the_reason_on(service: MagicMock):
    agent_id = uuid.uuid4()
    service.ask_for_capability = AsyncMock(return_value=None)

    response = await _post(
        f"/agents/{agent_id}/capabilities/web_research/request", {"reason": "the news"}
    )

    assert response.status_code == 204
    service.ask_for_capability.assert_awaited_once_with(
        _CTX, agent_id, "web_research", reason="the news"
    )


async def test_an_ask_with_no_reason_is_refused_at_the_edge(service: MagicMock):
    service.ask_for_capability = AsyncMock()

    response = await _post(
        f"/agents/{uuid.uuid4()}/capabilities/web_research/request", {"reason": ""}
    )

    assert response.status_code == 422
    service.ask_for_capability.assert_not_awaited()


@pytest.mark.parametrize("action", ["enable", "request"])
def test_neither_is_part_of_the_public_api(action: str):
    path = f"{settings.API_V1_STR}/agents/{{agent_id}}/capabilities/{{capability_id}}/{action}"

    def routes(entries):
        for entry in entries:
            if hasattr(entry, "effective_route_contexts"):
                for context in entry.effective_route_contexts():
                    yield context.original_route, context.path_format
            else:
                yield entry, getattr(entry, "path_format", None)

    [route] = [route for route, template in routes(app.routes) if template == path]

    assert not is_public_route(route)
