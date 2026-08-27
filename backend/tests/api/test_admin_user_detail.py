"""`GET /admin/users/{id}/detail` - what the drawer asks before a decision.

The user detail drawer showed four facts: the id, the email, the name already in
the table, and a join date. It answered none of the questions an admin opening a
row actually has - where does this person have access, with what authority, when
were they last here, is anything of theirs still signed in (#942).

Assembled server-side because it is three tables: a client doing it makes three
round trips to answer one question, and has to know that "never signed in" and
"no session open now" are different answers.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user, get_db_session, get_user_service
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.main import app
from app.services.user import UserService

pytestmark = pytest.mark.anyio

USER_ID = uuid.uuid4()
ENDPOINT = f"{settings.API_V1_STR}/admin/users/{USER_ID}/detail"
MODULE = "app.services.user"
NOW = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)


class _Caller:
    def __init__(self, *, is_app_admin: bool) -> None:
        self.id = uuid.uuid4()
        self.email = "kacper@example.com"
        self.is_app_admin = is_app_admin
        self.is_active = True
        self.created_at = NOW


def _client(*, is_app_admin: bool = True, service: Any | None = None) -> AsyncClient:
    app.dependency_overrides[get_current_user] = lambda: _Caller(is_app_admin=is_app_admin)
    app.dependency_overrides[get_db_session] = lambda: AsyncMock()
    if service is not None:
        app.dependency_overrides[get_user_service] = lambda: service
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@dataclass
class _Organization:
    """A real object, not a `MagicMock`: `MagicMock(name=...)` names the mock
    rather than setting an attribute, so the row reached pydantic with a mock
    where its name should be."""

    id: uuid.UUID
    name: str
    slug: str
    is_personal: bool


def _organization(name: str, *, personal: bool = False) -> _Organization:
    return _Organization(id=uuid.uuid4(), name=name, slug=name.lower(), is_personal=personal)


def _session(*, last_used: datetime, created: datetime) -> MagicMock:
    return MagicMock(last_used_at=last_used, created_at=created)


@pytest.fixture(autouse=True)
def _clear() -> AsyncGenerator[None, None]:
    yield
    app.dependency_overrides.clear()


async def test_it_names_every_organization_and_the_role_in_each() -> None:
    """The answer the drawer exists to give, and the one entirely absent
    before: an account with no membership anywhere is a different decision from
    one that owns two organizations."""
    service = UserService(AsyncMock())
    with (
        patch.object(service, "get_by_id", new=AsyncMock()),
        patch(
            f"{MODULE}.organization_repo.list_for_user",
            new=AsyncMock(
                return_value=[
                    (_organization("Ada", personal=True), "owner"),
                    (_organization("Acme"), "builder"),
                ]
            ),
        ),
        patch(f"{MODULE}.session_repo.get_user_sessions", new=AsyncMock(return_value=[])),
    ):
        async with _client(service=service) as client:
            response = await client.get(ENDPOINT)

    assert response.status_code == 200
    body = response.json()
    assert [(m["name"], m["role"]) for m in body["memberships"]] == [
        ("Ada", "owner"),
        ("Acme", "builder"),
    ]


async def test_last_seen_is_the_newest_activity_and_the_count_is_what_is_open() -> None:
    service = UserService(AsyncMock())
    sessions = [
        _session(last_used=NOW, created=NOW - timedelta(days=1)),
        _session(last_used=NOW - timedelta(days=3), created=NOW - timedelta(days=30)),
    ]
    with (
        patch.object(service, "get_by_id", new=AsyncMock()),
        patch(f"{MODULE}.organization_repo.list_for_user", new=AsyncMock(return_value=[])),
        patch(f"{MODULE}.session_repo.get_user_sessions", new=AsyncMock(return_value=sessions)),
    ):
        async with _client(service=service) as client:
            body = (await client.get(ENDPOINT)).json()

    assert body["last_seen_at"].startswith("2026-08-20T09:00")
    assert body["active_sessions"] == 2
    # The newest session, not the most recently used one - two different facts
    # about the same list, and the drawer shows both.
    assert body["newest_session_at"].startswith("2026-08-19T09:00")


async def test_an_account_that_has_never_signed_in_says_so_rather_than_nothing() -> None:
    """`null` is not zero. A dormant account and one that was created and never
    used are different decisions, and the drawer has to be able to tell them
    apart."""
    service = UserService(AsyncMock())
    with (
        patch.object(service, "get_by_id", new=AsyncMock()),
        patch(f"{MODULE}.organization_repo.list_for_user", new=AsyncMock(return_value=[])),
        patch(f"{MODULE}.session_repo.get_user_sessions", new=AsyncMock(return_value=[])),
    ):
        async with _client(service=service) as client:
            body = (await client.get(ENDPOINT)).json()

    assert body["last_seen_at"] is None
    assert body["newest_session_at"] is None
    assert body["active_sessions"] == 0


async def test_an_unknown_id_is_a_404_rather_than_an_empty_detail() -> None:
    service = UserService(AsyncMock())
    with patch.object(
        service, "get_by_id", new=AsyncMock(side_effect=NotFoundError(message="User not found"))
    ):
        async with _client(service=service) as client:
            response = await client.get(ENDPOINT)

    assert response.status_code == 404


async def test_a_caller_who_is_not_an_app_admin_is_refused() -> None:
    """Every field here is about somebody else - which organizations they are in
    and when they were last online - so the gate is the reason it may exist."""
    service = AsyncMock()
    async with _client(is_app_admin=False, service=service) as client:
        response = await client.get(ENDPOINT)

    assert response.status_code == 403
    service.admin_detail.assert_not_awaited()
