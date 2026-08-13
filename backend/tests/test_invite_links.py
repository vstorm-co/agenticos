"""Invite links - one URL that admits whoever holds it.

An email invitation is addressed: the person who can accept it is named in the
row. A link is not, which makes it a bearer credential for *membership of an
organization*. Everything worth testing here is a guard on that:

- an Admin cannot mint a link granting more than an Admin may invite,
- a link stays open for the next person, and stops at its limit,
- a domain restriction is checked against the person arriving, not the link,
- an exhausted or expired link admits nobody.
"""

import uuid
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import AuthenticationError, AuthorizationError, BadRequestError
from app.db.models.organization import InvitationStatus, OrgRole
from app.services.invitation import InvitationService

MODULE = "app.services.invitation"


def _member(role: str = OrgRole.OWNER.value):
    member = MagicMock()
    member.role = role
    return member


def _link(**overrides):
    invite = MagicMock()
    invite.id = uuid.uuid4()
    invite.organization_id = uuid.uuid4()
    invite.email = None
    invite.role = OrgRole.MEMBER.value
    invite.status = InvitationStatus.PENDING.value
    invite.max_uses = None
    invite.used_count = 0
    invite.email_domain = None
    invite.expires_at = datetime.now(UTC) + timedelta(days=7)
    for key, value in overrides.items():
        setattr(invite, key, value)
    return invite


def _user(email: str = "new@acme.test"):
    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = email
    return user


class TestMinting:
    @pytest.mark.anyio
    async def test_an_owner_can_mint_one(self):
        created = _link()
        with (
            patch(f"{MODULE}.member_repo.get", new=AsyncMock(return_value=_member())),
            patch(
                f"{MODULE}.invitation_repo.create", new=AsyncMock(return_value=created)
            ) as create,
        ):
            await InvitationService(MagicMock()).create_link(
                uuid.uuid4(), OrgRole.MEMBER.value, uuid.uuid4(), max_uses=10
            )

        # No address: that is what makes the row a link rather than an invitation.
        assert create.call_args.kwargs["email"] is None
        assert create.call_args.kwargs["max_uses"] == 10

    @pytest.mark.anyio
    async def test_a_member_cannot_mint_one(self):
        with (
            patch(
                f"{MODULE}.member_repo.get",
                new=AsyncMock(return_value=_member(OrgRole.MEMBER.value)),
            ),
            pytest.raises(AuthorizationError),
        ):
            await InvitationService(MagicMock()).create_link(
                uuid.uuid4(), OrgRole.MEMBER.value, uuid.uuid4()
            )

    @pytest.mark.anyio
    async def test_an_admin_cannot_mint_a_link_above_their_own_ceiling(self):
        """Otherwise the link is a way around the ceiling rather than a shortcut
        to it: an Admin who may only invite Members could mint an Owner link."""
        with (
            patch(
                f"{MODULE}.member_repo.get",
                new=AsyncMock(return_value=_member(OrgRole.ADMIN.value)),
            ),
            pytest.raises(AuthorizationError),
        ):
            await InvitationService(MagicMock()).create_link(
                uuid.uuid4(), OrgRole.OWNER.value, uuid.uuid4()
            )

    @pytest.mark.anyio
    async def test_the_domain_is_stored_without_its_at_sign(self):
        """Somebody will type "@acme.com", and a stored "@acme.com" would never
        match an address ending in "@acme.com"."""
        with (
            patch(f"{MODULE}.member_repo.get", new=AsyncMock(return_value=_member())),
            patch(
                f"{MODULE}.invitation_repo.create", new=AsyncMock(return_value=_link())
            ) as create,
        ):
            await InvitationService(MagicMock()).create_link(
                uuid.uuid4(),
                OrgRole.MEMBER.value,
                uuid.uuid4(),
                email_domain="@Acme.COM",
            )

        assert create.call_args.kwargs["email_domain"] == "acme.com"


class TestAccepting:
    async def _accept(self, invite, user):
        """Run one acceptance with every repository call stubbed.

        Returns the three mocks the assertions are about: whether a membership
        was created, whether the link recorded a use, and whether it was marked
        spent - the last being the difference between a link and a one-shot URL.
        """
        with ExitStack() as stack:

            def stub(target: str, mock: AsyncMock) -> AsyncMock:
                return stack.enter_context(patch(f"{MODULE}.{target}", new=mock))

            stub("invitation_repo.get_by_token", AsyncMock(return_value=invite))
            stub("user_repo.get_by_id", AsyncMock(return_value=user))
            stub("member_repo.get", AsyncMock(return_value=None))
            stub("organization_repo.get_by_id", AsyncMock(return_value=None))
            create_member = stub("member_repo.create", AsyncMock())
            record_use = stub("invitation_repo.record_use", AsyncMock())
            mark_accepted = stub("invitation_repo.accept", AsyncMock())

            await InvitationService(MagicMock()).accept("tok", user.id)

        return create_member, record_use, mark_accepted

    @pytest.mark.anyio
    async def test_a_link_admits_anybody_and_stays_open(self):
        """The whole point: it is not spent by the first person through it."""
        create_member, record_use, mark_accepted = await self._accept(_link(), _user())

        create_member.assert_awaited_once()
        record_use.assert_awaited_once()
        # Marking it accepted would turn a link into a one-shot URL that still
        # looked like a link.
        mark_accepted.assert_not_awaited()

    @pytest.mark.anyio
    async def test_an_exhausted_link_admits_nobody(self):
        invite = _link(max_uses=2, used_count=2)
        with (
            patch(f"{MODULE}.invitation_repo.get_by_token", new=AsyncMock(return_value=invite)),
            patch(f"{MODULE}.user_repo.get_by_id", new=AsyncMock(return_value=_user())),
            pytest.raises(BadRequestError, match="used up"),
        ):
            await InvitationService(MagicMock()).accept("tok", uuid.uuid4())

    @pytest.mark.anyio
    async def test_a_domain_restricted_link_refuses_an_outside_address(self):
        invite = _link(email_domain="acme.test")
        with (
            patch(f"{MODULE}.invitation_repo.get_by_token", new=AsyncMock(return_value=invite)),
            patch(
                f"{MODULE}.user_repo.get_by_id",
                new=AsyncMock(return_value=_user("someone@gmail.com")),
            ),
            pytest.raises(AuthenticationError, match=r"acme\.test"),
        ):
            await InvitationService(MagicMock()).accept("tok", uuid.uuid4())

    @pytest.mark.anyio
    async def test_a_domain_restricted_link_admits_a_matching_address(self):
        create_member, _record, _accepted = await self._accept(
            _link(email_domain="acme.test"), _user("new@acme.test")
        )

        create_member.assert_awaited_once()

    @pytest.mark.anyio
    async def test_a_subdomain_lookalike_does_not_match(self):
        """`evil-acme.test` ends with `acme.test`; the check is on the address's
        own domain, so the `@` is part of the comparison."""
        invite = _link(email_domain="acme.test")
        with (
            patch(f"{MODULE}.invitation_repo.get_by_token", new=AsyncMock(return_value=invite)),
            patch(
                f"{MODULE}.user_repo.get_by_id",
                new=AsyncMock(return_value=_user("someone@evil-acme.test")),
            ),
            pytest.raises(AuthenticationError),
        ):
            await InvitationService(MagicMock()).accept("tok", uuid.uuid4())

    @pytest.mark.anyio
    async def test_an_expired_link_admits_nobody(self):
        invite = _link(expires_at=datetime.now(UTC) - timedelta(days=1))
        with (
            patch(f"{MODULE}.invitation_repo.get_by_token", new=AsyncMock(return_value=invite)),
            patch(f"{MODULE}.invitation_repo.expire", new=AsyncMock()),
            pytest.raises(BadRequestError, match="expired"),
        ):
            await InvitationService(MagicMock()).accept("tok", uuid.uuid4())

    @pytest.mark.anyio
    async def test_an_email_invitation_still_checks_the_address(self):
        """The link path must not have loosened the addressed one."""
        invite = _link(email="invited@acme.test")
        with (
            patch(f"{MODULE}.invitation_repo.get_by_token", new=AsyncMock(return_value=invite)),
            patch(
                f"{MODULE}.user_repo.get_by_id",
                new=AsyncMock(return_value=_user("someone-else@acme.test")),
            ),
            pytest.raises(AuthenticationError, match="different email"),
        ):
            await InvitationService(MagicMock()).accept("tok", uuid.uuid4())
