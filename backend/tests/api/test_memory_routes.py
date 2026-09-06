"""The memory routes, through the app.

Two routes, both deletions. `tests/api/test_platform_routes.py` proves neither
carries a role gate and why; `tests/test_memory_service.py` proves the service
refuses where the database is. What is left here is the wiring: the method and
path a client actually calls, and the shape of the answer.

The answer shape is the part worth a route test. Both routes answer with counts
rather than 204, because half of "forgotten" happens in somebody else's service
and a caller has to be able to see which halves actually happened.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.exceptions import AuthorizationError
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.services.memory.facade import MemoryService

pytestmark = pytest.mark.anyio

_ORGANIZATION_ID = uuid.uuid4()
_USER_ID = uuid.uuid4()
_AGENT_ID = uuid.uuid4()

OpenClient = Callable[[], AbstractAsyncContextManager[AsyncClient]]

FACADE = "app.services.memory.facade"
REPO = "app.repositories.memory"


@pytest.fixture
def client(mock_redis: MagicMock) -> Iterator[OpenClient]:
    context = AuthContext(
        user_id=_USER_ID, organization_id=_ORGANIZATION_ID, role=OrgRoleName.OWNER
    )
    db = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = []
    result = MagicMock()
    result.scalars.return_value = scalars
    db.execute = AsyncMock(return_value=result)

    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_memory_service] = lambda: MemoryService(db)

    @asynccontextmanager
    async def open_client() -> AsyncIterator[AsyncClient]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as opened:
            yield opened

    yield open_client
    app.dependency_overrides.clear()


def _url(suffix: str = "") -> str:
    return f"{settings.API_V1_STR}/memory{suffix}"


class TestForgettingAPerson:
    async def test_it_answers_with_what_each_half_removed(self, client: OpenClient):
        """Not 204: the mem0 half is somebody else's service, and "forgotten" that
        cannot say which parts happened is a claim rather than a report."""
        with (
            patch(f"{REPO}.delete_for_person", new=AsyncMock(return_value=4)),
            patch(f"{FACADE}.record_audit", new=AsyncMock()),
        ):
            async with client() as http:
                response = await http.delete(_url(f"/person/{_USER_ID}"))

        assert response.status_code == 200
        assert response.json() == {"notes_deleted": 4, "mem0_agents_cleared": 0}

    async def test_the_services_refusal_reaches_the_caller_as_a_403(self, client: OpenClient):
        with patch(
            f"{FACADE}.MemoryService.forget_person",
            new=AsyncMock(side_effect=AuthorizationError(message="no")),
        ):
            async with client() as http:
                response = await http.delete(_url(f"/person/{uuid.uuid4()}"))

        assert response.status_code == 403

    async def test_a_user_id_that_is_not_one_never_reaches_the_service(self, client: OpenClient):
        with patch(f"{FACADE}.MemoryService.forget_person", new=AsyncMock()) as forget:
            async with client() as http:
                response = await http.delete(_url("/person/nobody"))

        assert response.status_code == 422
        assert not forget.await_count


class TestClearingAnAgent:
    async def test_it_answers_with_the_notes_it_removed(self, client: OpenClient):
        with (
            patch(f"{FACADE}.agent_repo.get", new=AsyncMock(return_value=MagicMock(id=_AGENT_ID))),
            patch(f"{FACADE}.resolve_access", new=AsyncMock(return_value=True)),
            patch(f"{REPO}.delete_all_for_agent", new=AsyncMock(return_value=9)),
            patch(f"{FACADE}.record_audit", new=AsyncMock()),
        ):
            async with client() as http:
                response = await http.delete(_url(f"?agent_id={_AGENT_ID}"))

        assert response.status_code == 200
        assert response.json()["notes_deleted"] == 9

    async def test_the_agent_is_required_rather_than_defaulted(self, client: OpenClient):
        """A clear with no agent named would have to mean "every agent", which is
        not a thing anybody should be able to ask for by omission."""
        async with client() as http:
            response = await http.delete(_url())

        assert response.status_code == 422

    async def test_an_agent_the_caller_may_not_edit_is_a_404(self, client: OpenClient):
        with (
            patch(f"{FACADE}.agent_repo.get", new=AsyncMock(return_value=MagicMock(id=_AGENT_ID))),
            patch(f"{FACADE}.resolve_access", new=AsyncMock(return_value=False)),
        ):
            async with client() as http:
                response = await http.delete(_url(f"?agent_id={_AGENT_ID}"))

        assert response.status_code == 404
