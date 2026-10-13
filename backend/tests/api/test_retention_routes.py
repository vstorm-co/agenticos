"""The two routes an organization's retention settings page calls (#1420).

What the service decides is tested in `tests/test_retention.py`. What is here is
the wiring: the path, the permission the service is asked for, and that a refusal
reaches the caller as a refusal rather than as a 500 - because a settings page
that 500s on a period it is not allowed to set teaches nobody which period it may.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.exceptions import AuthorizationError
from app.main import app
from app.schemas.retention import RetentionRead

pytestmark = pytest.mark.anyio

ORG = uuid4()
PATH = f"{settings.API_V1_STR}/orgs/{ORG}/retention"

_READ = RetentionRead(
    requested={"conversations": 30},
    effective={"conversations": 30, "audit": 2190},
    ceilings={},
    audit_floor_days=2190,
    conflicts=[],
)


@asynccontextmanager
async def _client() -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[deps.get_current_user] = lambda: MagicMock(
        id=uuid4(), is_app_admin=False
    )
    app.dependency_overrides[deps.get_db_session] = lambda: MagicMock()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


async def test_the_page_reads_what_was_asked_what_sweeps_and_what_is_allowed() -> None:
    with patch("app.services.retention.RetentionService.read", new=AsyncMock(return_value=_READ)):
        async with _client() as client:
            response = await client.get(PATH)

    assert response.status_code == 200
    body = response.json()
    assert body["requested"] == {"conversations": 30}
    assert body["effective"]["audit"] == 2190
    assert body["audit_floor_days"] == 2190


async def test_setting_a_period_goes_through_the_service_as_the_caller() -> None:
    updated = AsyncMock(return_value=_READ)
    with patch("app.services.retention.RetentionService.update", new=updated):
        async with _client() as client:
            response = await client.put(PATH, json={"retention_days": {"conversations": 30}})

    assert response.status_code == 200
    # The actor is the signed-in caller, because the change is audited as theirs.
    assert updated.await_args.kwargs["actor_user_id"] is not None


async def test_a_member_without_org_settings_is_refused_rather_than_500() -> None:
    with patch(
        "app.services.retention.RetentionService.read",
        new=AsyncMock(side_effect=AuthorizationError(message="nope")),
    ):
        async with _client() as client:
            response = await client.get(PATH)

    assert response.status_code == 403


async def test_a_period_outside_the_bounds_is_a_422_naming_the_class() -> None:
    async with _client() as client:
        response = await client.put(PATH, json={"retention_days": {"conversations": 0}})

    assert response.status_code == 422
