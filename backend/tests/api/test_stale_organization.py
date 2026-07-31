"""What the API says when the organization a client is holding is gone.

This is one wire contract with a client behind it. The browser persists the
organization it last switched to and sends it on every request; when that
organization is deleted, or the member is removed from it, the persisted id
outlives the membership and every org-scoped request is refused. The frontend
recovers by clearing the selection and falling back to one the caller actually
belongs to - but only if it can tell "your organization is gone" apart from
"the agent you asked for is missing" and from "the server broke".

`/me/permissions` is what makes that possible: it takes no path parameter and
loads no resource, so the only 404 it can produce is the organization one, and
it carries the refused id in `details.org_id`. Both halves are asserted here,
because the recovery in `use-active-organization.ts` is built on them.
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
from app.main import app

pytestmark = pytest.mark.anyio


@asynccontextmanager
async def _client_for(user_id) -> AsyncIterator[AsyncClient]:
    """A signed-in caller whose organization header is resolved for real."""
    user = MagicMock(id=user_id, is_app_admin=False)
    app.dependency_overrides[deps.get_current_user] = lambda: user
    app.dependency_overrides[deps.get_db_session] = lambda: MagicMock()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


class TestARefusedOrganizationHeader:
    async def test_the_refusal_names_the_organization_it_refused(self) -> None:
        """Without the id, a client cannot know *which* selection to discard.

        A stale header and a switch that raced a removal are the same status
        code; only the echoed id tells the browser the refusal is about the
        organization it is currently holding rather than a previous one.
        """
        stale = uuid4()

        with patch("app.api.deps.member_repo.get", new=AsyncMock(return_value=None)):
            async with _client_for(uuid4()) as client:
                response = await client.get(
                    f"{settings.API_V1_STR}/me/permissions",
                    headers={"X-Organization-Id": str(stale)},
                )

        assert response.status_code == 404
        assert response.json()["error"] == {
            "code": "NOT_FOUND",
            "message": "Organization not found or access denied",
            "details": {"org_id": str(stale)},
        }

    async def test_a_deleted_organization_is_refused_like_a_forbidden_one(self) -> None:
        """Membership rows outlive nothing; the org row can vanish underneath one."""
        deleted = uuid4()

        with (
            patch("app.api.deps.member_repo.get", new=AsyncMock(return_value=MagicMock())),
            patch(
                "app.api.deps.organization_repo.get_by_id",
                new=AsyncMock(return_value=None),
            ),
        ):
            async with _client_for(uuid4()) as client:
                response = await client.get(
                    f"{settings.API_V1_STR}/me/permissions",
                    headers={"X-Organization-Id": str(deleted)},
                )

        assert response.status_code == 404
        assert response.json()["error"]["details"] == {"org_id": str(deleted)}

    def test_the_permissions_route_can_refuse_for_no_other_reason(self) -> None:
        """The frontend reads a 404 here as "your organization is gone".

        That inference is only sound while this route has nothing else to fail
        to find - no path parameter, no resource lookup. A future `{org_id}`
        segment or a row read in the handler would quietly turn a missing
        resource into a signal that reassigns somebody's organization, which is
        the one outcome the recovery must never produce.
        """
        route = next(
            route
            for route in app.routes
            if getattr(route, "path", None) == f"{settings.API_V1_STR}/me/permissions"
        )

        assert route.dependant.path_params == []
        assert route.dependant.query_params == []
