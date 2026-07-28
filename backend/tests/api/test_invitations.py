"""What the invitation endpoints put on the wire.

An invitation token is a bearer credential: whoever holds one joins the
organization as the role that was offered to somebody else's email address.
`GET /orgs/{id}/invitations` used to return every pending one, which put the
whole set in an administrator's browser on every visit to the members page, in
any response log, and in anything that cached the reply.

`tests/test_secret_exposure.py` holds the schema side of that statically. These
go through the app, because the schema is only half of it: a token must not turn
up as a *path segment* of an authenticated request either, where it lands in the
server's access log and the admin's history. Revoking as an administrator
therefore addresses the invitation by id, and the token route stays for the
invitee, who has nothing else.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.main import app

pytestmark = pytest.mark.anyio

_ORGANIZATION_ID = uuid4()
_INVITATION_ID = uuid4()
_TOKEN = "a-live-bearer-credential"


def _invitation() -> SimpleNamespace:
    """A pending row as the repository hands it to the route - token included."""
    return SimpleNamespace(
        id=_INVITATION_ID,
        organization_id=_ORGANIZATION_ID,
        email="invitee@example.com",
        role="member",
        status="pending",
        # A row with an address is an email invitation; the link fields are the
        # shape a link takes and an invitation simply does not use.
        max_uses=None,
        used_count=0,
        email_domain=None,
        token=_TOKEN,
        expires_at=datetime.now(UTC) + timedelta(days=7),
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def service() -> MagicMock:
    invitation = _invitation()
    stub = MagicMock()
    stub.invite = AsyncMock(return_value=invitation)
    stub.list_for_org = AsyncMock(return_value=[invitation])
    stub.revoke_by_id = AsyncMock(return_value=invitation)
    stub.revoke = AsyncMock(return_value=invitation)
    return stub


@pytest.fixture
async def client(service: MagicMock) -> AsyncIterator[AsyncClient]:
    """A client whose caller is signed in and whose service is the stub above.

    Who may call these routes is decided in ``InvitationService`` and tested in
    ``tests/test_services_members.py``. What is under test here is the shape of
    the request and of the response.
    """
    app.dependency_overrides[deps.get_current_user] = lambda: SimpleNamespace(id=uuid4())
    app.dependency_overrides[deps.get_invitation_service] = lambda: service
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http
    app.dependency_overrides.clear()


def _org_url(tail: str) -> str:
    return f"{settings.API_V1_STR}/orgs/{_ORGANIZATION_ID}{tail}"


class TestListingDoesNotHandOutTokens:
    async def test_no_listed_invitation_carries_its_token(self, client: AsyncClient) -> None:
        """The bug. The token is on the row the service returns and must not reach the reply."""
        response = await client.get(_org_url("/invitations"))

        assert response.status_code == 200
        assert _TOKEN not in response.text
        assert "token" not in response.json()["items"][0]

    async def test_it_still_returns_what_an_administrator_decides_on(
        self, client: AsyncClient
    ) -> None:
        """Removing a field is easy to overdo - the members page still has to work."""
        item = (await client.get(_org_url("/invitations"))).json()["items"][0]

        assert item["id"] == str(_INVITATION_ID)
        assert item["email"] == "invitee@example.com"
        assert item["role"] == "member"
        assert item["status"] == "pending"
        assert item["expires_at"]


class TestCreatingReturnsTheTokenOnce:
    async def test_the_inviter_gets_the_token_back(self, client: AsyncClient) -> None:
        """Sending the email can fail - the service logs it and carries on - so the
        person who just invited somebody gets the link they can pass on by hand."""
        response = await client.post(
            _org_url("/invitations"), json={"email": "invitee@example.com", "role": "member"}
        )

        assert response.status_code == 201
        assert response.json()["invitation_token"] == _TOKEN


class TestRevokingAsAnAdministrator:
    async def test_it_is_addressed_by_id_under_the_organization(
        self, client: AsyncClient, service: MagicMock
    ) -> None:
        response = await client.delete(_org_url(f"/invitations/{_INVITATION_ID}"))

        assert response.status_code == 204
        assert service.revoke_by_id.await_args.args == (_ORGANIZATION_ID, _INVITATION_ID)

    async def test_a_token_cannot_be_passed_where_the_id_goes(self, client: AsyncClient) -> None:
        """The segment is typed as a UUID, so this route can never carry a credential.

        Which is the point of moving it: an authenticated admin action must not
        put a live token in a URL.
        """
        response = await client.delete(_org_url(f"/invitations/{_TOKEN}"))

        assert response.status_code == 422


class TestRevokingAsTheInvitee:
    async def test_the_token_route_is_still_served(
        self, client: AsyncClient, service: MagicMock
    ) -> None:
        """An invitee knows the token and nothing else - no id, no organization.

        Retiring this route along with the admin one would leave declining an
        invitation impossible for the only person entitled to.
        """
        response = await client.delete(f"{settings.API_V1_STR}/invitations/{_TOKEN}")

        assert response.status_code == 204
        assert service.revoke.await_args.args[0] == _TOKEN
