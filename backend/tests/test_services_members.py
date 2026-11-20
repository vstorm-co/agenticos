"""Tests for MemberService and InvitationService."""

import contextlib
import uuid
from datetime import UTC, datetime
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
from app.services.email.providers.base import SendResult
from app.services.invitation import InvitationService
from app.services.member import MemberService, end_membership


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
    async def test_list_flags_which_rows_the_caller_may_change(self, service):
        """An Admin outranks a member but not a peer Admin, so the row-level flag
        is the server's own answer to `change_role` - not a rule the client
        reimplements and gets wrong (#700)."""

        def _row(role: str) -> tuple:
            member = MagicMock()
            member.role = role
            member.user_id = uuid.uuid4()
            return (member, f"{role}@example.com", None, None, None)

        requester = MagicMock()
        requester.role = "admin"
        with (
            patch("app.services.member.member_repo.get", new=AsyncMock(return_value=requester)),
            patch(
                "app.services.member.member_repo.list_for_org",
                new=AsyncMock(return_value=[_row("member"), _row("admin")]),
            ),
            patch("app.services.member.member_repo.count_for_org", new=AsyncMock(return_value=2)),
            patch(
                "app.services.member.audit_log_repo.latest_member_actions",
                new=AsyncMock(return_value={}),
            ),
        ):
            rows, _ = await service.list_for_org(uuid.uuid4(), uuid.uuid4())

        assert {row[0].role: row[-1] for row in rows} == {"member": True, "admin": False}

    @pytest.mark.anyio
    async def test_list_flags_nothing_changeable_for_a_member_without_roles_manage(self, service):
        """A viewer sees roles but may change none - the flag mirrors both of
        `change_role`'s checks, roles:manage and the outrank rule."""

        def _row(role: str) -> tuple:
            member = MagicMock()
            member.role = role
            member.user_id = uuid.uuid4()
            return (member, f"{role}@example.com", None, None, None)

        requester = MagicMock()
        requester.role = "viewer"
        with (
            patch("app.services.member.member_repo.get", new=AsyncMock(return_value=requester)),
            patch(
                "app.services.member.member_repo.list_for_org",
                new=AsyncMock(return_value=[_row("member"), _row("viewer")]),
            ),
            patch("app.services.member.member_repo.count_for_org", new=AsyncMock(return_value=2)),
            patch(
                "app.services.member.audit_log_repo.latest_member_actions",
                new=AsyncMock(return_value={}),
            ),
        ):
            rows, _ = await service.list_for_org(uuid.uuid4(), uuid.uuid4())

        assert all(row[-1] is False for row in rows)

    @pytest.mark.anyio
    async def test_list_projects_only_the_requested_members_activity(self, service):
        organization_id, requester_id, quiet_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        requester = MagicMock(role="owner", user_id=requester_id)
        quiet = MagicMock(role="viewer", user_id=quiet_id)
        at = datetime(2026, 11, 15, tzinfo=UTC)
        with (
            patch("app.services.member.member_repo.get", new=AsyncMock(return_value=requester)),
            patch(
                "app.services.member.member_repo.list_for_org",
                new=AsyncMock(
                    return_value=[
                        (requester, "owner@example.com", None, None, None),
                        (quiet, "quiet@example.com", None, None, None),
                    ]
                ),
            ),
            patch("app.services.member.member_repo.count_for_org", new=AsyncMock(return_value=2)),
            patch(
                "app.services.member.audit_log_repo.latest_member_actions",
                new=AsyncMock(return_value={requester_id: at}),
            ) as activity,
        ):
            rows, total = await service.list_for_org(organization_id, requester_id)
        activity.assert_awaited_once_with(
            service.db, organization_id=organization_id, user_ids=[requester_id, quiet_id]
        )
        assert total == 2
        assert rows[0][-2] == at
        assert rows[1][-2] is None

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
    async def test_a_custom_role_that_does_not_outrank_an_admin_cannot_remove_one(
        self, service, monkeypatch
    ):
        """The hole the literal `admin`-vs-`admin` rule left, that `change_role`
        already closes with the catalog (#700, #1066). A custom role (Phase 2)
        holding `members:manage` whose set does not outrank an Admin's would pass
        the literal - `requester.role == "admin"` is false - and remove the Admin.
        The catalog bounds it by the same ceiling `change_role` uses."""
        from app.core.permissions import ROLE_PERMS, Perm, Scope

        monkeypatch.setitem(ROLE_PERMS, "test:members-only", {Perm.MEMBERS_MANAGE: Scope.ALL})
        mock_requester = MagicMock(role="test:members-only")
        mock_target = MagicMock(role="admin")

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
    async def test_change_role_admin_cannot_demote_admin(self, service):
        """The other half of test_remove_admin_cannot_remove_admin: demoting a
        peer Admin to Viewer strips the same authority `remove` refuses to touch,
        so change_role must refuse it too (#700). The demotion target's role is
        `viewer`, which the assignment ceiling alone would allow."""
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
            await service.change_role(
                uuid.uuid4(), uuid.uuid4(), "viewer", requester_id=uuid.uuid4()
            )

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

    @pytest.mark.anyio
    async def test_transfer_ownership_refuses_a_personal_org(self, service):
        """A personal org is 1:1 with its creator; handing it to another member
        leaves a non-creator owner that account deletion cannot see and would
        orphan (#1136)."""
        requester = MagicMock(role="owner")
        with (
            patch("app.services.member.member_repo.get", new=AsyncMock(return_value=requester)),
            patch(
                "app.services.member.organization_repo.get_by_id",
                new=AsyncMock(return_value=MagicMock(is_personal=True)),
            ),
            pytest.raises(BadRequestError),
        ):
            await service.transfer_ownership(uuid.uuid4(), uuid.uuid4(), requester_id=uuid.uuid4())


class TestAccessChangeAudit:
    """Every path that changes who belongs to an organization leaves one audit entry.

    The removal audit lives in `end_membership` so no caller can forget it, and
    `remove` no longer writes its own - these tests pin both halves: one entry
    per removal, with the action naming the path that took it.
    """

    @pytest.fixture
    def member_service(self):
        return MemberService(MagicMock())

    @staticmethod
    def _ended():
        """Every repository call `end_membership` makes, stubbed."""
        return (
            patch("app.services.member.group_repo.delete_memberships_in_org", new=AsyncMock()),
            patch("app.services.member.oauth_repo.revoke_grants_for_member", new=AsyncMock()),
            patch("app.services.member.api_key_repo.revoke_for_member", new=AsyncMock()),
            patch("app.services.member.coding_account_repo.delete_for_member", new=AsyncMock()),
            patch(
                "app.services.member.mcp_connection_repo.delete_accounts_for_member",
                new=AsyncMock(),
            ),
            patch(
                "app.services.member.agent_trigger_repo.revoke_member_authority", new=AsyncMock()
            ),
            patch("app.services.member.telephony_repo.delete_member_contact", new=AsyncMock()),
            patch(
                "app.services.member.resource_grant_repo.revoke_for_member",
                new=AsyncMock(return_value=0),
            ),
            patch(
                "app.services.member.session_repo.deactivate_all_user_sessions",
                new=AsyncMock(return_value=0),
            ),
            patch(
                "app.services.member.agent_exposure_repo.pause_for_creator",
                new=AsyncMock(return_value=0),
            ),
            patch(
                "app.services.member.agent_embed_repo.pause_for_owner",
                new=AsyncMock(return_value=0),
            ),
            patch(
                "app.services.member.NetworkConnectionService.revoke_member",
                new=AsyncMock(return_value=0),
            ),
            patch("app.services.member.member_repo.delete", new=AsyncMock()),
            patch("app.services.member.resource_grant_repo.lower_edit_data", new=AsyncMock()),
        )

    @staticmethod
    def _membership(role="member"):
        membership = MagicMock()
        membership.organization_id = uuid.uuid4()
        membership.user_id = uuid.uuid4()
        membership.role = role
        return membership

    @pytest.mark.anyio
    async def test_end_membership_writes_one_member_removed_entry(self):
        membership = self._membership()
        with contextlib.ExitStack() as stack:
            for context in self._ended():
                stack.enter_context(context)
            audit = stack.enter_context(patch("app.services.member.record_audit", new=AsyncMock()))
            await end_membership(MagicMock(), membership)

        audit.assert_awaited_once()
        entry = audit.await_args.kwargs
        assert entry["action"] == "member.removed"
        assert entry["actor_user_id"] is None
        assert entry["target_id"] == str(membership.user_id)
        assert entry["details"] == {"role": "member"}

    @pytest.mark.anyio
    async def test_end_membership_closes_the_leavers_sessions_and_pauses_their_surfaces(self):
        """The credential outlives the removal, and the surfaces keep answering
        as the publisher - both stop here, and the audit entry says how many of
        each, so a later reader can tell a quiet departure from a busy one."""
        db = MagicMock()
        membership = self._membership()
        with contextlib.ExitStack() as stack:
            for context in self._ended():
                stack.enter_context(context)
            sessions = stack.enter_context(
                patch(
                    "app.services.member.session_repo.deactivate_all_user_sessions",
                    new=AsyncMock(return_value=2),
                )
            )
            exposures = stack.enter_context(
                patch(
                    "app.services.member.agent_exposure_repo.pause_for_creator",
                    new=AsyncMock(return_value=1),
                )
            )
            embeds = stack.enter_context(
                patch(
                    "app.services.member.agent_embed_repo.pause_for_owner",
                    new=AsyncMock(return_value=3),
                )
            )
            audit = stack.enter_context(patch("app.services.member.record_audit", new=AsyncMock()))
            await end_membership(db, membership)

        sessions.assert_awaited_once_with(db, membership.user_id)
        exposures.assert_awaited_once_with(
            db, organization_id=membership.organization_id, user_id=membership.user_id
        )
        embeds.assert_awaited_once_with(
            db, organization_id=membership.organization_id, user_id=membership.user_id
        )
        assert audit.await_args.kwargs["details"] == {
            "role": "member",
            "sessions_revoked": 2,
            "exposures_paused": 1,
            "embeds_paused": 3,
        }

    @pytest.mark.anyio
    async def test_end_membership_keeps_the_callers_action_and_actor(self):
        membership = self._membership(role="admin")
        actor = uuid.uuid4()
        with contextlib.ExitStack() as stack:
            for context in self._ended():
                stack.enter_context(context)
            audit = stack.enter_context(patch("app.services.member.record_audit", new=AsyncMock()))
            await end_membership(
                MagicMock(),
                membership,
                actor_user_id=actor,
                action="directory.member_removed",
                details={"role": "admin", "provider": "entra"},
            )

        audit.assert_awaited_once()
        entry = audit.await_args.kwargs
        assert (entry["action"], entry["actor_user_id"]) == ("directory.member_removed", actor)
        assert entry["details"] == {"role": "admin", "provider": "entra"}

    @pytest.mark.anyio
    async def test_remove_writes_one_entry_and_none_of_its_own(self, member_service):
        """`remove` used to write `member.removed` itself; the entry now comes
        from `end_membership`, so a removal must still leave exactly one."""
        org_id, target_id, requester_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        requester = MagicMock(role="owner")
        target = self._membership(role="member")
        target.user_id = target_id
        target.organization_id = org_id

        calls = 0

        async def mock_get(*args, **kwargs):
            nonlocal calls
            calls += 1
            return requester if calls == 1 else target

        with contextlib.ExitStack() as stack:
            for context in self._ended():
                stack.enter_context(context)
            stack.enter_context(patch("app.services.member.member_repo.get", new=mock_get))
            audit = stack.enter_context(patch("app.services.member.record_audit", new=AsyncMock()))
            revoked = stack.enter_context(
                patch(
                    "app.services.member.resource_grant_repo.revoke_for_member",
                    new=AsyncMock(return_value=2),
                )
            )
            await member_service.remove(org_id, target_id, requester_id=requester_id)

        audit.assert_awaited_once()
        entry = audit.await_args.kwargs
        assert entry["action"] == "member.removed"
        assert entry["actor_user_id"] == requester_id
        assert entry["target_id"] == str(target_id)
        # Their direct grants go with the membership, so inviting them back
        # wakes none of them.
        revoked.assert_awaited_once_with(
            member_service.db, organization_id=org_id, user_id=target_id
        )

    @pytest.mark.anyio
    async def test_leave_is_audited_as_a_leave_not_a_removal(self, member_service):
        org_id, requester_id = uuid.uuid4(), uuid.uuid4()
        membership = self._membership(role="member")
        membership.organization_id = org_id
        membership.user_id = requester_id
        with contextlib.ExitStack() as stack:
            for context in self._ended():
                stack.enter_context(context)
            stack.enter_context(
                patch(
                    "app.services.member.member_repo.get",
                    new=AsyncMock(return_value=membership),
                )
            )
            audit = stack.enter_context(patch("app.services.member.record_audit", new=AsyncMock()))
            await member_service.leave(org_id, requester_id=requester_id)

        audit.assert_awaited_once()
        entry = audit.await_args.kwargs
        assert entry["action"] == "member.left"
        assert entry["actor_user_id"] == requester_id

    @pytest.mark.anyio
    async def test_transfer_ownership_is_audited(self, member_service):
        org_id, requester_id, new_owner_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        requester = MagicMock(role="owner")
        new_owner = MagicMock(role="member")
        with (
            patch(
                "app.services.member.member_repo.get",
                new=AsyncMock(side_effect=[requester, new_owner]),
            ),
            patch(
                "app.services.member.organization_repo.get_by_id",
                new=AsyncMock(return_value=MagicMock(is_personal=False)),
            ),
            patch("app.services.member.user_repo.get_by_id_for_update", new=AsyncMock()),
            patch(
                "app.services.member.OrganizationService.refuse_past_the_ceiling",
                new=AsyncMock(),
            ),
            patch("app.services.member.member_repo.update_role", new=AsyncMock()),
            patch("app.services.member.record_audit", new=AsyncMock()) as audit,
        ):
            await member_service.transfer_ownership(org_id, new_owner_id, requester_id=requester_id)

        audit.assert_awaited_once()
        entry = audit.await_args.kwargs
        assert entry["action"] == "organization.ownership_transferred"
        assert entry["actor_user_id"] == requester_id
        assert entry["details"] == {"from": str(requester_id), "to": str(new_owner_id)}


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

    def _invited(self, *, send, delivers: bool = True):
        """Every patch `invite` needs to reach the email, with `send` as the outcome.

        The repository, the organization and the requester are all mocked: what
        these four tests are about is the one boolean the caller gets back, which
        nothing was reporting. `delivers` is the provider's own answer to whether
        accepting a message means it leaves the deployment - false for the log
        provider a deployment with no `SMTP_*` falls back to.
        """
        requester = MagicMock()
        requester.role = "owner"
        email_service = MagicMock()
        email_service.send_invitation = send
        email_service.delivers = delivers
        return (
            patch(
                "app.services.invitation.member_repo.get",
                new=AsyncMock(return_value=requester),
            ),
            patch(
                "app.services.invitation.user_repo.get_by_email", new=AsyncMock(return_value=None)
            ),
            patch(
                "app.services.invitation.invitation_repo.get_pending_for_org_email",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.services.invitation.invitation_repo.create",
                new=AsyncMock(return_value=MagicMock(token="tok")),
            ),
            patch(
                "app.services.invitation.organization_repo.get_by_id",
                new=AsyncMock(return_value=MagicMock(name="Acme")),
            ),
            patch(
                "app.services.invitation.user_repo.get_by_id",
                new=AsyncMock(return_value=MagicMock(full_name="Owner", email="o@example.com")),
            ),
            patch(
                "app.services.invitation.DeploymentSettingsService.effective_app_name",
                new=AsyncMock(return_value="AgenticOS"),
            ),
            patch(
                "app.services.invitation.get_email_service",
                new=MagicMock(return_value=email_service),
            ),
        )

    @pytest.mark.anyio
    async def test_a_delivered_invitation_says_it_was_delivered(self, service):
        accepted = AsyncMock(return_value=SendResult(provider_message_id="1", accepted=True))
        with contextlib.ExitStack() as stack:
            for context in self._invited(send=accepted):
                stack.enter_context(context)
            _invite, delivered = await service.invite(
                uuid.uuid4(), "user@example.com", "member", requester_id=uuid.uuid4()
            )

        assert delivered is True

    @pytest.mark.anyio
    async def test_an_invitation_is_audited_when_it_is_created(self, service):
        accepted = AsyncMock(return_value=SendResult(provider_message_id="1", accepted=True))
        requester_id = uuid.uuid4()
        with contextlib.ExitStack() as stack:
            for context in self._invited(send=accepted):
                stack.enter_context(context)
            audit = stack.enter_context(
                patch("app.services.invitation.record_audit", new=AsyncMock())
            )
            await service.invite(
                uuid.uuid4(), "user@example.com", "member", requester_id=requester_id
            )

        audit.assert_awaited_once()
        entry = audit.await_args.kwargs
        assert entry["action"] == "invitation.created"
        assert entry["actor_user_id"] == requester_id
        assert entry["details"] == {"email": "user@example.com", "role": "member"}

    @pytest.mark.anyio
    async def test_a_provider_that_only_logs_has_not_delivered_anything(self, service):
        """`accepted=True` from `LogProvider` means the message was written to the
        application log, which is not a delivery. Reading only `accepted` told a
        developer with no `SMTP_*` that their invitation had been emailed."""
        logged = AsyncMock(return_value=SendResult(provider_message_id="log", accepted=True))
        with contextlib.ExitStack() as stack:
            for context in self._invited(send=logged, delivers=False):
                stack.enter_context(context)
            _invite, delivered = await service.invite(
                uuid.uuid4(), "user@example.com", "member", requester_id=uuid.uuid4()
            )

        assert delivered is False

    @pytest.mark.anyio
    async def test_an_invitation_no_mail_server_accepted_says_so(self, service):
        """The whole point of the pair. The provider answering `accepted=False` -
        which is what a deployment with no `SMTP_*` does - used to be logged and
        discarded, and the inviter was told their invitation had been sent (#1484).
        """
        refused = AsyncMock(
            return_value=SendResult(provider_message_id="", accepted=False, error="no provider")
        )
        with contextlib.ExitStack() as stack:
            for context in self._invited(send=refused):
                stack.enter_context(context)
            invite, delivered = await service.invite(
                uuid.uuid4(), "user@example.com", "member", requester_id=uuid.uuid4()
            )

        assert delivered is False
        # And the invitation itself still exists: it is a row, the row was written,
        # and failing the request would leave a pending invitation nobody was told
        # about.
        assert invite.token == "tok"

    @pytest.mark.anyio
    async def test_an_email_that_raises_is_not_a_delivery_either(self, service):
        """A provider that raises on the way out reaches a different branch from one
        that answers `accepted=False`, and the caller must not be able to tell them
        apart - both mean the link is the only way in."""
        exploded = AsyncMock(side_effect=RuntimeError("connection refused"))
        with contextlib.ExitStack() as stack:
            for context in self._invited(send=exploded):
                stack.enter_context(context)
            invite, delivered = await service.invite(
                uuid.uuid4(), "user@example.com", "member", requester_id=uuid.uuid4()
            )

        assert delivered is False
        assert invite.token == "tok"

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
            patch("app.services.invitation.record_audit", new=AsyncMock()),
        ):
            revoked = await service.revoke_by_id(
                organization_id, invite.id, requester_id=uuid.uuid4()
            )

        assert revoked is invite
        revoke.assert_awaited_once_with(service.db, invite)

    @pytest.mark.anyio
    async def test_revoking_is_audited(self, service):
        organization_id = uuid.uuid4()
        invite = _pending_invite(organization_id=organization_id)
        requester_id = uuid.uuid4()

        with (
            patch(
                "app.services.invitation.invitation_repo.get_by_id",
                new=AsyncMock(return_value=invite),
            ),
            patch(
                "app.services.invitation.member_repo.get",
                new=AsyncMock(return_value=MagicMock(role="admin")),
            ),
            patch("app.services.invitation.invitation_repo.revoke", new=AsyncMock()),
            patch("app.services.invitation.record_audit", new=AsyncMock()) as audit,
        ):
            await service.revoke_by_id(organization_id, invite.id, requester_id=requester_id)

        audit.assert_awaited_once()
        entry = audit.await_args.kwargs
        assert entry["action"] == "invitation.revoked"
        assert entry["actor_user_id"] == requester_id
        assert entry["target_id"] == str(invite.id)


def _pending_invite(*, organization_id=None, email="invitee@example.com"):
    invite = MagicMock()
    invite.id = uuid.uuid4()
    invite.organization_id = organization_id or uuid.uuid4()
    invite.email = email
    invite.status = "pending"
    return invite
