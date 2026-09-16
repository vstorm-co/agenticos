"""The two export routes, and the two things that gate them.

An export is everything this deployment holds about one person in a single
document, which is the shape of a breach when the caller is not who they claim
to be. Two controls say so: the hourly limit, which has to be on *both* routes
because the threat it exists for - a stolen privileged session walking the
deployment's people - uses the administrator's one; and the reason, which is the
only thing that makes an entry in the trail reviewable and so has to say
something (#1421).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import (
    get_current_user,
    get_db_session,
    get_personal_data_service,
    limit_personal_data_export,
)
from app.api.routes.v1 import admin_users, me_personal_data
from app.core.config import settings
from app.main import app
from app.schemas.personal_data import PersonalDataExport

pytestmark = pytest.mark.anyio

USER_ID = uuid.uuid4()
ADMIN_EXPORT = f"{settings.API_V1_STR}/admin/users/{USER_ID}/export"


class _Caller:
    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.email = "admin@example.com"
        self.is_app_admin = True
        self.is_active = True


def _client(*, service: Any) -> AsyncClient:
    app.dependency_overrides[get_current_user] = lambda: _Caller()
    app.dependency_overrides[get_db_session] = lambda: AsyncMock()
    app.dependency_overrides[get_personal_data_service] = lambda: service
    # The limiter resolves the caller's active organization, which needs a real
    # database. That it is installed at all is what matters here, and the test
    # above asserts it structurally rather than by exhausting it.
    app.dependency_overrides[limit_personal_data_export] = lambda: None
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _export() -> PersonalDataExport:
    """An empty but valid document, so the route's own answer is what is tested."""
    return PersonalDataExport(
        exported_at=datetime.now(UTC),
        profile={"id": str(USER_ID)},
        conversations=[],
        messages=[],
        tool_calls=[],
        memberships=[],
        ratings=[],
        sessions=[],
        runs=[],
        memory=[],
        channel_identities=[],
        slash_commands=[],
        dashboard_layouts=[],
    )


@pytest.fixture(autouse=True)
def _clear() -> AsyncGenerator[None, None]:
    yield
    app.dependency_overrides.clear()


def _gates(router: Any, path: str) -> set[Any]:
    route = next(
        candidate
        for candidate in router.routes
        if candidate.path == path and "GET" in candidate.methods
    )
    return {dependency.dependency for dependency in route.dependencies}


@pytest.mark.security
def test_both_export_routes_consume_the_same_hourly_limit() -> None:
    """The documented threat is a stolen app-admin session, and that session
    uses the administrator's route rather than `/me/data/export`."""
    assert limit_personal_data_export in _gates(me_personal_data.router, "/export")
    assert limit_personal_data_export in _gates(admin_users.router, "/{user_id}/export")


@pytest.mark.security
async def test_a_reason_of_only_whitespace_is_refused() -> None:
    """Three spaces satisfied `min_length=3` and were recorded verbatim, so the
    trail held an entry saying somebody read a colleague's entire history for no
    stated reason."""
    service = AsyncMock()

    async with _client(service=service) as client:
        response = await client.get(ADMIN_EXPORT, params={"reason": "   "})

    assert response.status_code == 422
    service.export.assert_not_called()


async def test_a_reason_reaches_the_service_stripped() -> None:
    service = AsyncMock(return_value=None)
    service.export = AsyncMock(return_value=_export())

    async with _client(service=service) as client:
        response = await client.get(ADMIN_EXPORT, params={"reason": "  DPO request 41  "})

    assert response.status_code == 200
    assert service.export.await_args.kwargs["reason"] == "DPO request 41"
