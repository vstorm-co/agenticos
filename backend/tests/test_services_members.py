"""Tests for MemberService and InvitationService."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from app.core.exceptions import (
    AlreadyExistsError,
    AuthorizationError,
    BadRequestError,
    NotFoundError,
)
from app.schemas.organization import OrganizationMemberUpdate
from app.services.invitation import InvitationService
from app.services.member import MemberService


class TestMemberService:
    """Tests for MemberService (PostgreSQL async)."""

    @pytest.fixture
    def mock_db(self):
        db = MagicMock()
        db.execute = AsyncMock()
        db.get = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        db.delete = AsyncMock()
        return db

    @pytest.fixture
    def service(self, mock_db):
        return MemberService(mock_db)

    @pytest.mark.anyio
    async def test_list_for_org_raises_if_not_member(self, service):
        with (
            patch("app.services.member.member_repo.get", new=AsyncMock(return_value=None)),
            pytest.raises(NotFoundError),
        ):
            await service.list_for_org(uuid.uuid4(), uuid.uuid4())

    @pytest.mark.anyio
    async def test_change_role_raises_if_requester_not_admin_or_owner(self, service):
        mock_member = MagicMock()
        mock_member.role = "member"

        with (
            patch("app.services.member.member_repo.get", new=AsyncMock(return_value=mock_member)),
            pytest.raises(AuthorizationError),
        ):
            await service.change_role(
                uuid.uuid4(), uuid.uuid4(), "viewer", requester_id=uuid.uuid4()
            )

    @pytest.mark.anyio
    async def test_change_role_is_gated_on_roles_manage_not_members_manage(
        self, service, monkeypatch
    ):
        """Assigning a role is `roles:manage`; adding and removing people is not.

        The built-in Owner and Admin hold both, so only a synthetic role can
        say which one the check reads - and a custom role (Phase 2) must be
        able to take one entitlement without the other.
        """
        from app.core.permissions import ROLE_PERMS, Perm, Scope

        monkeypatch.setitem(ROLE_PERMS, "test:members-only", {Perm.MEMBERS_MANAGE: Scope.ALL})
        requester = MagicMock()
        requester.role = "test:members-only"

        with (
            patch("app.services.member.member_repo.get", new=AsyncMock(return_value=requester)),
            pytest.raises(AuthorizationError),
        ):
            await service.change_role(
                uuid.uuid4(), uuid.uuid4(), "viewer", requester_id=uuid.uuid4()
            )

    @pytest.mark.anyio
    async def test_change_role_raises_if_target_is_owner(self, service):
        mock_requester = MagicMock()
        mock_requester.role = "owner"
        mock_target = MagicMock()
        mock_target.role = "owner"

        call_count = 0

        async def mock_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return mock_requester if call_count == 1 else mock_target

        with (
            patch("app.services.member.member_repo.get", new=mock_get),
            pytest.raises(BadRequestError),
        ):
            await service.change_role(
                uuid.uuid4(), uuid.uuid4(), "admin", requester_id=uuid.uuid4()
            )

    @pytest.mark.anyio
    async def test_change_role_admin_cannot_assign_admin_role(self, service):
        mock_requester = MagicMock()
        mock_requester.role = "admin"
        mock_target = MagicMock()
        mock_target.role = "member"

        call_count = 0

        async def mock_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return mock_requester if call_count == 1 else mock_target

        with (
            patch("app.services.member.member_repo.get", new=mock_get),
            pytest.raises(AuthorizationError),
        ):
            await service.change_role(
                uuid.uuid4(), uuid.uuid4(), "admin", requester_id=uuid.uuid4()
            )

    @pytest.mark.anyio
    @pytest.mark.parametrize("requester_role", ["owner", "admin"])
    async def test_change_role_cannot_mint_an_owner(self, service, requester_role):
        """Nobody promotes to Owner through this route (#672).

        `transfer_ownership` demotes the outgoing Owner in the same breath, so
        a PATCH that only promotes leaves the organization with two - and an
        audit trail that says `member.role_changed` rather than that ownership
        moved.
        """
        requester = MagicMock(role=requester_role)
        target = MagicMock(role="member")
        update_role = AsyncMock()

        with (
            patch(
                "app.services.member.member_repo.get",
                new=AsyncMock(side_effect=[requester, target]),
            ),
            patch("app.services.member.member_repo.update_role", new=update_role),
            pytest.raises(AuthorizationError),
        ):
            await service.change_role(
                uuid.uuid4(), uuid.uuid4(), "owner", requester_id=uuid.uuid4()
            )

        update_role.assert_not_awaited()

    @pytest.mark.anyio
    async def test_a_custom_role_holding_roles_manage_cannot_mint_an_owner(
        self, service, monkeypatch
    ):
        """The ceiling is what the requester holds, not whether they are `admin`.

        Keyed on the literal role name, the check that stops an Admin promoting
        someone could not see a custom role (Phase 2) at all - and `roles:manage`
        is deliberately written to admit one.
        """
        from app.core.permissions import ROLE_PERMS, Perm, Scope

        monkeypatch.setitem(ROLE_PERMS, "test:role-admin", {Perm.ROLES_MANAGE: Scope.ALL})
        requester = MagicMock(role="test:role-admin")
        target = MagicMock(role="member")
        update_role = AsyncMock()

        with (
            patch(
                "app.services.member.member_repo.get",
                new=AsyncMock(side_effect=[requester, target]),
            ),
            patch("app.services.member.member_repo.update_role", new=update_role),
            pytest.raises(AuthorizationError),
        ):
            await service.change_role(
                uuid.uuid4(), uuid.uuid4(), "owner", requester_id=uuid.uuid4()
            )

        update_role.assert_not_awaited()

    @pytest.mark.anyio
    async def test_an_owner_still_promotes_a_member_to_admin(self, service):
        """The ceiling bounds the assignment; it does not remove it."""
        requester = MagicMock(role="owner")
        target = MagicMock(role="member")
        promoted = MagicMock(role="admin", user_id=uuid.uuid4())

        with (
            patch(
                "app.services.member.member_repo.get",
                new=AsyncMock(side_effect=[requester, target]),
            ),
            patch(
                "app.services.member.member_repo.update_role",
                new=AsyncMock(return_value=promoted),
            ),
            patch("app.services.member.record_audit", new=AsyncMock()),
            patch(
                "app.services.member.user_repo.get_by_id",
                new=AsyncMock(return_value=MagicMock(email="a@example.com", avatar_color=7)),
            ),
        ):
            member, _, _, _, avatar_color = await service.change_role(
                uuid.uuid4(), uuid.uuid4(), "admin", requester_id=uuid.uuid4()
            )

        assert member.role == "admin"
        # The row a listing redraws after a role change carries the member's
        # chosen colour, so their avatar does not flip to the auto one.
        assert avatar_color == 7

    @pytest.mark.anyio
    async def test_remove_raises_if_not_authorized(self, service):
        mock_member = MagicMock()
        mock_member.role = "viewer"

        with (
            patch("app.services.member.member_repo.get", new=AsyncMock(return_value=mock_member)),
            pytest.raises(AuthorizationError),
        ):
            await service.remove(uuid.uuid4(), uuid.uuid4(), requester_id=uuid.uuid4())

    @pytest.mark.anyio
    async def test_remove_admin_cannot_remove_admin(self, service):
        mock_requester = MagicMock()
        mock_requester.role = "admin"
        mock_target = MagicMock()
        mock_target.role = "admin"

        call_count = 0

        async def mock_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return mock_requester if call_count == 1 else mock_target

        with (
            patch("app.services.member.member_repo.get", new=mock_get),
            pytest.raises(AuthorizationError),
        ):
            await service.remove(uuid.uuid4(), uuid.uuid4(), requester_id=uuid.uuid4())

    @pytest.mark.anyio
    async def test_leave_owner_blocked_if_others_exist(self, service):
        mock_membership = MagicMock()
        mock_membership.role = "owner"

        with (
            patch(
                "app.services.member.member_repo.get", new=AsyncMock(return_value=mock_membership)
            ),
            patch("app.services.member.member_repo.count_for_org", new=AsyncMock(return_value=3)),
            pytest.raises(BadRequestError),
        ):
            await service.leave(uuid.uuid4(), requester_id=uuid.uuid4())

    @pytest.mark.anyio
    async def test_transfer_ownership_only_owner_can_call(self, service):
        mock_requester = MagicMock()
        mock_requester.role = "admin"

        with (
            patch(
                "app.services.member.member_repo.get", new=AsyncMock(return_value=mock_requester)
            ),
            pytest.raises(AuthorizationError),
        ):
            await service.transfer_ownership(uuid.uuid4(), uuid.uuid4(), requester_id=uuid.uuid4())

    @pytest.mark.anyio
    async def test_transfer_ownership_to_self_raises(self, service):
        uid = uuid.uuid4()
        mock_requester = MagicMock()
        mock_requester.role = "owner"

        with (
            patch(
                "app.services.member.member_repo.get", new=AsyncMock(return_value=mock_requester)
            ),
            pytest.raises(BadRequestError),
        ):
            await service.transfer_ownership(uuid.uuid4(), uid, requester_id=uid)


class TestRoleAssigned:
    """The request schema refuses a role a role change may not grant (#672).

    The membership half of what `InvitationCreate` holds for invitations - and
    of what `InviteLinkCreate` is still missing on this base, which is #551.
    The service's ceiling depends on who is asking, so the schema is where "no
    owner by PATCH, no made-up roles" holds for every requester alike.
    """

    @pytest.mark.parametrize("role", ["owner", "ceo"])
    def test_an_ungrantable_role_is_refused(self, role):
        with pytest.raises(ValidationError):
            OrganizationMemberUpdate(role=role)

    @pytest.mark.parametrize("role", ["admin", "builder", "operator", "member", "viewer"])
    def test_a_grantable_role_passes(self, role):
        assert OrganizationMemberUpdate(role=role).role == role


class TestInvitationService:
    """Tests for InvitationService (PostgreSQL async)."""

    @pytest.fixture
    def mock_db(self):
        db = MagicMock()
        db.execute = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        return db

    @pytest.fixture
    def service(self, mock_db):
        return InvitationService(mock_db)

    @pytest.mark.anyio
    async def test_invite_raises_if_not_admin_or_owner(self, service):
        mock_member = MagicMock()
        mock_member.role = "member"

        with (
            patch(
                "app.services.invitation.member_repo.get", new=AsyncMock(return_value=mock_member)
            ),
            pytest.raises(AuthorizationError),
        ):
            await service.invite(
                uuid.uuid4(), "user@example.com", "member", requester_id=uuid.uuid4()
            )

    @pytest.mark.anyio
    async def test_invite_admin_cannot_invite_as_admin(self, service):
        mock_requester = MagicMock()
        mock_requester.role = "admin"

        with (
            patch(
                "app.services.invitation.member_repo.get",
                new=AsyncMock(return_value=mock_requester),
            ),
            pytest.raises(AuthorizationError),
        ):
            await service.invite(
                uuid.uuid4(), "user@example.com", "admin", requester_id=uuid.uuid4()
            )

    @pytest.mark.anyio
    async def test_a_custom_role_holding_members_manage_cannot_invite_an_admin(
        self, service, monkeypatch
    ):
        """The ceiling is what the requester holds, not whether they are `admin`.

        Keyed on the literal role name, this let a custom role (Phase 2) composed
        with `members:manage` invite a new Admin unchecked - the invitation half of
        the defect #672 removed from `change_role` (#696). The membership half is
        `test_a_custom_role_holding_roles_manage_cannot_mint_an_owner`.
        """
        from app.core.permissions import ROLE_PERMS, Perm, Scope

        monkeypatch.setitem(ROLE_PERMS, "test:inviter", {Perm.MEMBERS_MANAGE: Scope.ALL})
        requester = MagicMock(role="test:inviter")

        with (
            patch("app.services.invitation.member_repo.get", new=AsyncMock(return_value=requester)),
            pytest.raises(AuthorizationError),
        ):
            await service.invite(
                uuid.uuid4(), "user@example.com", "admin", requester_id=uuid.uuid4()
            )

    @pytest.mark.anyio
    async def test_a_custom_role_holding_members_manage_cannot_link_an_admin(
        self, service, monkeypatch
    ):
        """The same ceiling on the invite-link path, the second call site keyed on
        the literal `admin` (#696)."""
        from app.core.permissions import ROLE_PERMS, Perm, Scope

        monkeypatch.setitem(ROLE_PERMS, "test:inviter", {Perm.MEMBERS_MANAGE: Scope.ALL})
        requester = MagicMock(role="test:inviter")

        with (
            patch("app.services.invitation.member_repo.get", new=AsyncMock(return_value=requester)),
            pytest.raises(AuthorizationError),
        ):
            await service.create_link(uuid.uuid4(), "admin", requester_id=uuid.uuid4())

    @pytest.mark.anyio
    async def test_invite_raises_on_duplicate_pending(self, service):
        mock_requester = MagicMock()
        mock_requester.role = "owner"
        mock_pending = MagicMock()

        with (
            patch(
                "app.services.invitation.member_repo.get",
                new=AsyncMock(return_value=mock_requester),
            ),
            patch(
                "app.services.invitation.user_repo.get_by_email", new=AsyncMock(return_value=None)
            ),
            patch(
                "app.services.invitation.invitation_repo.get_pending_for_org_email",
                new=AsyncMock(return_value=mock_pending),
            ),
            pytest.raises(AlreadyExistsError),
        ):
            await service.invite(
                uuid.uuid4(), "user@example.com", "member", requester_id=uuid.uuid4()
            )

    @pytest.mark.anyio
    async def test_accept_raises_on_missing_token(self, service):
        with (
            patch(
                "app.services.invitation.invitation_repo.get_by_token",
                new=AsyncMock(return_value=None),
            ),
            pytest.raises(NotFoundError),
        ):
            await service.accept("bad-token", accepting_user_id=uuid.uuid4())

    @pytest.mark.anyio
    async def test_accept_raises_on_non_pending_invite(self, service):
        mock_invite = MagicMock()
        mock_invite.status = "accepted"

        with (
            patch(
                "app.services.invitation.invitation_repo.get_by_token",
                new=AsyncMock(return_value=mock_invite),
            ),
            pytest.raises(BadRequestError),
        ):
            await service.accept("some-token", accepting_user_id=uuid.uuid4())

    @pytest.mark.anyio
    async def test_revoke_raises_if_not_pending(self, service):
        mock_invite = MagicMock()
        mock_invite.status = "expired"

        with (
            patch(
                "app.services.invitation.invitation_repo.get_by_token",
                new=AsyncMock(return_value=mock_invite),
            ),
            pytest.raises(BadRequestError),
        ):
            await service.revoke("some-token", requester_id=uuid.uuid4())

    @pytest.mark.anyio
    async def test_the_invitee_can_still_revoke_their_own_by_token(self, service):
        """The reason the token route exists at all.

        An invitee is not a member of the organization and has never seen its
        id - the invitation reached them by email and nothing else did. If this
        stops working, declining an invitation becomes impossible for the only
        person entitled to.
        """
        invite = _pending_invite(email="invitee@example.com")
        invitee = MagicMock(email="Invitee@Example.com")
        revoke = AsyncMock(return_value=invite)

        with (
            patch(
                "app.services.invitation.invitation_repo.get_by_token",
                new=AsyncMock(return_value=invite),
            ),
            # Not a member of the organization: only the matching email admits them.
            patch("app.services.invitation.member_repo.get", new=AsyncMock(return_value=None)),
            patch(
                "app.services.invitation.user_repo.get_by_id", new=AsyncMock(return_value=invitee)
            ),
            patch("app.services.invitation.invitation_repo.revoke", new=revoke),
        ):
            await service.revoke("the-token", requester_id=uuid.uuid4())

        revoke.assert_awaited_once_with(service.db, invite)


class TestRevokingAnInvitationByItsId:
    """The administrator's route, which never handles a token.

    A pending token is a bearer credential: whoever holds it joins the
    organization as the role offered to somebody else's address. Revoking from
    the members list therefore addresses the invitation by id, and these tests
    are mostly about who is refused.
    """

    @pytest.fixture
    def service(self):
        db = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        return InvitationService(db)

    @pytest.mark.anyio
    async def test_an_admin_of_another_organization_is_told_it_does_not_exist(self, service):
        """Not "forbidden" - that would confirm the id names a real invitation.

        The lookup is by id alone, so the organization in the path is the only
        thing tying the row to the caller's tenant.
        """
        invite = _pending_invite(organization_id=uuid.uuid4())
        revoke = AsyncMock()

        with (
            patch(
                "app.services.invitation.invitation_repo.get_by_id",
                new=AsyncMock(return_value=invite),
            ),
            patch("app.services.invitation.invitation_repo.revoke", new=revoke),
            pytest.raises(NotFoundError),
        ):
            await service.revoke_by_id(uuid.uuid4(), invite.id, requester_id=uuid.uuid4())

        revoke.assert_not_awaited()

    @pytest.mark.anyio
    async def test_an_unknown_id_is_not_found(self, service):
        with (
            patch(
                "app.services.invitation.invitation_repo.get_by_id",
                new=AsyncMock(return_value=None),
            ),
            pytest.raises(NotFoundError),
        ):
            await service.revoke_by_id(uuid.uuid4(), uuid.uuid4(), requester_id=uuid.uuid4())

    @pytest.mark.anyio
    async def test_a_member_without_members_manage_is_refused(self, service):
        """Every member can see the organization; withdrawing an offer is not theirs."""
        organization_id = uuid.uuid4()
        invite = _pending_invite(organization_id=organization_id)
        member = MagicMock(role="member")
        revoke = AsyncMock()

        with (
            patch(
                "app.services.invitation.invitation_repo.get_by_id",
                new=AsyncMock(return_value=invite),
            ),
            patch("app.services.invitation.member_repo.get", new=AsyncMock(return_value=member)),
            patch("app.services.invitation.invitation_repo.revoke", new=revoke),
            pytest.raises(AuthorizationError),
        ):
            await service.revoke_by_id(organization_id, invite.id, requester_id=uuid.uuid4())

        revoke.assert_not_awaited()

    @pytest.mark.anyio
    async def test_an_already_accepted_invitation_cannot_be_revoked(self, service):
        """Revoking it would look like removing the member, and would not."""
        organization_id = uuid.uuid4()
        invite = _pending_invite(organization_id=organization_id)
        invite.status = "accepted"
        revoke = AsyncMock()

        with (
            patch(
                "app.services.invitation.invitation_repo.get_by_id",
                new=AsyncMock(return_value=invite),
            ),
            patch(
                "app.services.invitation.member_repo.get",
                new=AsyncMock(return_value=MagicMock(role="owner")),
            ),
            patch("app.services.invitation.invitation_repo.revoke", new=revoke),
            pytest.raises(BadRequestError) as raised,
        ):
            await service.revoke_by_id(organization_id, invite.id, requester_id=uuid.uuid4())

        assert raised.value.details == {"status": "accepted"}
        revoke.assert_not_awaited()

    @pytest.mark.anyio
    async def test_an_admin_revokes_the_pending_invitation_in_their_own_organization(self, service):
        organization_id = uuid.uuid4()
        invite = _pending_invite(organization_id=organization_id)
        revoke = AsyncMock(return_value=invite)

        with (
            patch(
                "app.services.invitation.invitation_repo.get_by_id",
                new=AsyncMock(return_value=invite),
            ),
            patch(
                "app.services.invitation.member_repo.get",
                new=AsyncMock(return_value=MagicMock(role="admin")),
            ),
            patch("app.services.invitation.invitation_repo.revoke", new=revoke),
        ):
            revoked = await service.revoke_by_id(
                organization_id, invite.id, requester_id=uuid.uuid4()
            )

        assert revoked is invite
        revoke.assert_awaited_once_with(service.db, invite)


def _pending_invite(*, organization_id=None, email="invitee@example.com"):
    invite = MagicMock()
    invite.id = uuid.uuid4()
    invite.organization_id = organization_id or uuid.uuid4()
    invite.email = email
    invite.status = "pending"
    return invite
