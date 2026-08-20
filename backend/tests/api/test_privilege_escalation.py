"""The one global privilege, and the surfaces that must not be able to grant it.

`is_app_admin` reaches every organization on the deployment: `AuthContext`
returns every permission at `Scope.ALL` for whoever holds it. It is granted from
the CLI (`agenticos cmd create-app-admin`) and from `bootstrap`, and by nothing
that speaks HTTP.

That used to be enforced by a guard. `PATCH /users/me` stripped `role` from the
body when the caller was not an admin, because `UserUpdate` carried a privilege
field and a user could otherwise set their own. The column is gone and so is the
guard, and what replaced it is an **absence**: no privilege field on the update
schema at all.

An absence is exactly the kind of protection a later edit undoes by accident -
somebody adds `is_app_admin` to `UserUpdate` so the admin page can toggle it, and
`PATCH /users/me` silently becomes a self-promotion endpoint. Nothing else in the
suite would fail. Hence this file.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.main import app
from app.schemas.user import UserCreate, UserRead, UserUpdate

pytestmark = pytest.mark.anyio

# Every spelling somebody might reach for. `role` is included deliberately: the
# column was dropped in migration 0066, and a schema that started accepting it
# again would be re-growing the layer that removal existed to delete.
PRIVILEGE_FIELDS = ("is_app_admin", "role", "is_superuser", "superuser")


def _stored_user(*, is_app_admin: bool = False) -> MagicMock:
    user = MagicMock()
    user.id = uuid4()
    user.email = "member@example.com"
    user.full_name = "A Member"
    user.is_active = True
    user.is_app_admin = is_app_admin
    user.avatar_url = None
    user.onboarding_completed_at = None
    user.notify_budget_alerts = True
    user.notify_approval_requests = True
    user.notify_usage_reports = True
    user.created_at = "2026-07-31T00:00:00Z"
    user.updated_at = None
    return user


class _RecordingUserService:
    """Stands in for `UserService`, keeping whatever the route handed it.

    The assertion that matters is not the response - a route could return the
    unchanged flag while having asked the repository to set it. What is checked is
    the `UserUpdate` the route actually passed down.
    """

    def __init__(self, stored: MagicMock) -> None:
        self.stored = stored
        self.received: UserUpdate | None = None

    async def update(self, user_id: UUID, user_in: UserUpdate) -> MagicMock:
        self.received = user_in
        return self.stored

    async def admin_update(
        self, user_id: UUID, user_in: UserUpdate, *, acting_admin_id: UUID
    ) -> MagicMock:
        # The admin-by-id route goes through the self-action guard; this test is
        # about which fields reach the update, so it delegates like the real one.
        return await self.update(user_id, user_in)

    async def get_by_id(self, user_id: UUID) -> MagicMock:
        return self.stored


@asynccontextmanager
async def _client(
    *, caller: MagicMock, service: _RecordingUserService
) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[deps.get_current_user] = lambda: caller
    app.dependency_overrides[deps.get_user_service] = lambda: service
    app.dependency_overrides[deps.get_db_session] = lambda: MagicMock()
    app.dependency_overrides[deps.get_redis] = lambda: AsyncMock()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


class TestTheUpdateSchemaCarriesNoPrivilege:
    """Asserted on the schema, so it fails when somebody adds the field.

    A route test only fails once a request exercises it. This fails at import of
    the schema, which is where the mistake would be made.
    """

    def test_user_update_has_no_privilege_field(self) -> None:
        assert set(UserUpdate.model_fields).isdisjoint(PRIVILEGE_FIELDS)

    def test_user_create_has_no_privilege_field(self) -> None:
        """Registration decides `is_app_admin` for the first user only, in the
        service. A field here would let anybody claim it at sign-up."""
        assert set(UserCreate.model_fields).isdisjoint(PRIVILEGE_FIELDS)

    def test_the_flag_is_still_readable(self) -> None:
        """Not a leak, and needed: the frontend hides the /admin surface on it.
        Removing it from the read schema would be a different bug, so the
        assertions above must not be satisfied by deleting the concept."""
        assert "is_app_admin" in UserRead.model_fields


class TestPatchingYourOwnProfile:
    async def test_asking_for_the_flag_does_not_reach_the_service(self) -> None:
        caller = _stored_user()
        service = _RecordingUserService(caller)

        async with _client(caller=caller, service=service) as client:
            response = await client.patch(
                f"{settings.API_V1_STR}/users/me",
                json={"full_name": "Renamed", "is_app_admin": True},
            )

        assert response.status_code == 200
        assert service.received is not None
        # The legitimate half of the request went through...
        assert service.received.full_name == "Renamed"
        # ...and the privilege was not carried down in any form. `exclude_unset`
        # is what the service dumps, so an unset field is the difference between
        # "not asked for" and "asked for and refused".
        assert not hasattr(service.received, "is_app_admin")
        assert "is_app_admin" not in service.received.model_dump(exclude_unset=True)

    async def test_the_response_never_reports_the_caller_as_promoted(self) -> None:
        caller = _stored_user(is_app_admin=False)

        async with _client(caller=caller, service=_RecordingUserService(caller)) as client:
            response = await client.patch(
                f"{settings.API_V1_STR}/users/me", json={"is_app_admin": True}
            )

        assert response.json()["is_app_admin"] is False

    async def test_asking_for_the_dropped_role_column_does_not_reach_the_service(self) -> None:
        """The shape of the original bug, kept as a test after the column was dropped."""
        caller = _stored_user()
        service = _RecordingUserService(caller)

        async with _client(caller=caller, service=service) as client:
            await client.patch(f"{settings.API_V1_STR}/users/me", json={"role": "admin"})

        assert service.received is not None
        assert "role" not in service.received.model_dump(exclude_unset=True)


class TestAnAppAdminPatchingSomebodyElse:
    async def test_even_an_app_admin_cannot_grant_the_flag_over_http(self) -> None:
        """`PATCH /users/{id}` is app-admin gated and can edit any account, which is
        the surface where granting would be most tempting to wire up. The privilege
        is CLI-only on purpose: it is the one thing that reaches every tenant."""
        admin = _stored_user(is_app_admin=True)
        target = _stored_user(is_app_admin=False)
        service = _RecordingUserService(target)

        async with _client(caller=admin, service=service) as client:
            response = await client.patch(
                f"{settings.API_V1_STR}/users/{target.id}",
                json={"full_name": "Promoted?", "is_app_admin": True},
            )

        assert response.status_code == 200
        assert service.received is not None
        assert "is_app_admin" not in service.received.model_dump(exclude_unset=True)
        assert response.json()["is_app_admin"] is False

    async def test_a_caller_without_the_flag_is_refused_outright(self) -> None:
        """Before any of the above matters: the route is gated."""
        ordinary = _stored_user(is_app_admin=False)
        target = _stored_user()

        async with _client(caller=ordinary, service=_RecordingUserService(target)) as client:
            response = await client.patch(
                f"{settings.API_V1_STR}/users/{target.id}", json={"full_name": "x"}
            )

        assert response.status_code == 403
