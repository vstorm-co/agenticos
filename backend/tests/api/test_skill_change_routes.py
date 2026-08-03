"""The skill-changes API, through the app.

`tests/api/test_platform_routes.py` proves each of these is gated on
`skills:edit`. What is left is the shape of what they return - and one property
worth stating: the full body is in the response on purpose. A reviewer deciding
whether an agent's rewrite of a policy becomes the policy has to read it, and a
listing showing only a name would make the decision a coin flip with an audit
trail.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.exceptions import AlreadyExistsError
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app

pytestmark = pytest.mark.anyio

_ORGANIZATION_ID = uuid.uuid4()
_PROPOSAL_ID = uuid.uuid4()


def _row(**overrides: Any) -> MagicMock:
    row = MagicMock()
    row.id = _PROPOSAL_ID
    row.skill_id = uuid.uuid4()
    row.agent_id = uuid.uuid4()
    row.conversation_id = uuid.uuid4()
    row.name = "refunds"
    row.description = "How refunds work now."
    row.content = "Ask for the receipt."
    row.resources = {"reconcile.py": "print(1)"}
    row.status = "pending"
    row.decided_by_user_id = None
    row.decided_at = None
    row.created_at = datetime.now(UTC)
    row.updated_at = None
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


@pytest.fixture
def service() -> MagicMock:
    stub = MagicMock()
    stub.list_proposals = AsyncMock(return_value=[_row()])
    stub.get = AsyncMock(return_value=_row())
    stub.apply = AsyncMock(return_value=_row(status="applied"))
    stub.discard = AsyncMock(return_value=_row(status="discarded"))
    return stub


@pytest.fixture
def client(service: MagicMock, mock_redis: MagicMock) -> Iterator[Any]:
    context = AuthContext(
        user_id=uuid.uuid4(), organization_id=_ORGANIZATION_ID, role=OrgRoleName.OWNER
    )
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_skill_proposal_service] = lambda: service

    @asynccontextmanager
    async def open_client() -> AsyncIterator[AsyncClient]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as opened:
            yield opened

    yield open_client
    app.dependency_overrides.clear()


def _url(tail: str) -> str:
    return f"{settings.API_V1_STR}/skill-changes{tail}"


class TestListing:
    async def test_a_change_arrives_with_the_body_a_reviewer_has_to_read(self, client) -> None:
        async with client() as opened:
            response = await opened.get(_url(""))

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["name"] == "refunds"
        assert body["items"][0]["content"] == "Ask for the receipt."
        assert body["items"][0]["resources"] == {"reconcile.py": "print(1)"}

    async def test_the_filter_is_passed_through(self, client, service) -> None:
        async with client() as opened:
            await opened.get(_url(""), params={"status": "pending"})

        assert service.list_proposals.await_args.kwargs == {"status": "pending"}

    async def test_one_change_can_be_read_on_its_own(self, client) -> None:
        async with client() as opened:
            response = await opened.get(_url(f"/{_PROPOSAL_ID}"))

        assert response.status_code == 200
        assert response.json()["id"] == str(_PROPOSAL_ID)


class TestDeciding:
    async def test_accepting_reports_the_new_state(self, client) -> None:
        async with client() as opened:
            response = await opened.post(_url(f"/{_PROPOSAL_ID}/apply"))

        assert response.status_code == 200
        assert response.json()["status"] == "applied"

    async def test_refusing_reports_the_new_state_too(self, client) -> None:
        async with client() as opened:
            response = await opened.post(_url(f"/{_PROPOSAL_ID}/discard"))

        assert response.status_code == 200
        assert response.json()["status"] == "discarded"

    async def test_a_second_decision_is_a_conflict_rather_than_a_silent_no_op(
        self, client, service
    ) -> None:
        """Applying twice would bump a version against a body already stored."""
        service.apply = AsyncMock(
            side_effect=AlreadyExistsError(message="This change was already applied.")
        )

        async with client() as opened:
            response = await opened.post(_url(f"/{_PROPOSAL_ID}/apply"))

        assert response.status_code == 409
