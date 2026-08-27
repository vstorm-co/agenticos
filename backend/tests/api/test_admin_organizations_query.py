"""`GET /admin/organizations` - what a deployment admin may narrow it by.

The page is the only surface that answers "what tenants exist", and until #921
it answered fifty rows in one order with no way to reach the rest. Narrowing
and ordering are the route's job rather than the page's, because a sort applied
to a page after it arrives claims a whole-collection order fifty rows cannot
deliver.

What is pinned here is the wiring: which arguments reach the service, that a
column outside the set is refused rather than guessed at, and that the whole
route is app-admin only. Whether the ordering is really applied before
`OFFSET`/`LIMIT` is SQL - see `tests/integration/test_admin_org_owner.py`.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_admin_service, get_current_user, get_db_session
from app.core.config import settings
from app.main import app

pytestmark = pytest.mark.anyio

ENDPOINT = f"{settings.API_V1_STR}/admin/organizations"


class _User:
    def __init__(self, *, is_app_admin: bool) -> None:
        self.id = uuid4()
        self.email = "kacper@example.com"
        self.is_app_admin = is_app_admin
        self.is_active = True
        self.created_at = datetime.now(UTC)


def _client(*, is_app_admin: bool, service: Any) -> AsyncClient:
    app.dependency_overrides[get_current_user] = lambda: _User(is_app_admin=is_app_admin)
    app.dependency_overrides[get_db_session] = lambda: AsyncMock()
    app.dependency_overrides[get_admin_service] = lambda: service
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture
async def service() -> AsyncGenerator[AsyncMock, None]:
    yield AsyncMock(list_organizations=AsyncMock(return_value={"items": [], "total": 0}))
    app.dependency_overrides.clear()


async def test_the_defaults_are_the_page_the_admin_lands_on(service: AsyncMock) -> None:
    async with _client(is_app_admin=True, service=service) as client:
        response = await client.get(ENDPOINT)

    assert response.status_code == 200
    assert service.list_organizations.await_args.kwargs == {
        "skip": 0,
        "limit": 50,
        "search": None,
        "sort_by": "created_at",
        "sort_dir": "desc",
        "kind": "all",
    }


async def test_every_narrowing_reaches_the_service(service: AsyncMock) -> None:
    async with _client(is_app_admin=True, service=service) as client:
        response = await client.get(
            ENDPOINT,
            params={
                "skip": 50,
                "limit": 25,
                "search": "acme",
                "sort_by": "members",
                "sort_dir": "asc",
                "kind": "team",
            },
        )

    assert response.status_code == 200
    assert service.list_organizations.await_args.kwargs == {
        "skip": 50,
        "limit": 25,
        "search": "acme",
        "sort_by": "members",
        "sort_dir": "asc",
        "kind": "team",
    }


@pytest.mark.parametrize(
    "params",
    [
        {"sort_by": "owner_email"},
        {"sort_by": "monthly_budget"},
        {"sort_dir": "sideways"},
        {"kind": "personal-ish"},
        {"limit": 500},
        {"skip": -1},
    ],
)
async def test_a_value_outside_its_type_is_refused_rather_than_guessed_at(
    service: AsyncMock, params: dict[str, object]
) -> None:
    """A 422, not a silent fallback. An `ORDER BY` assembled from a query string
    is an injection surface, and a `kind` nothing matches would answer with an
    empty page - which reads as a deployment with no tenants."""
    async with _client(is_app_admin=True, service=service) as client:
        response = await client.get(ENDPOINT, params=params)

    assert response.status_code == 422
    service.list_organizations.assert_not_awaited()


async def test_a_caller_who_is_not_an_app_admin_is_refused(service: AsyncMock) -> None:
    """Cross-tenant by construction: this route names every organization on the
    deployment, so the gate is the whole reason it may exist."""
    async with _client(is_app_admin=False, service=service) as client:
        response = await client.get(ENDPOINT, params={"search": "acme"})

    assert response.status_code == 403
    service.list_organizations.assert_not_awaited()
