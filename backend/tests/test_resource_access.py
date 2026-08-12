"""Tests for resource-level access - role scopes combined with explicit grants.

The rule under test is `effective = max(role scope, grant on this resource)`:
a grant widens access for one row, and no scope ever reaches across tenants.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import AuthorizationError
from app.core.permissions import ROLE_PERMS, AuthContext, OrgRoleName, Perm, Scope
from app.db.models.resource_grant import GrantLevel, Visibility
from app.services.access import (
    COLLECTION,
    publisher_context,
    resolve_access,
    visible_resource_ids,
)


def _ctx(role: str, org_id=None, user_id=None) -> AuthContext:
    return AuthContext(
        user_id=user_id or uuid.uuid4(),
        organization_id=org_id or uuid.uuid4(),
        role=role,
    )


def _resource(org_id, owner_user_id=None, visibility=Visibility.PRIVATE):
    resource = MagicMock()
    resource.id = uuid.uuid4()
    resource.organization_id = org_id
    resource.owner_user_id = owner_user_id
    resource.visibility = visibility.value if isinstance(visibility, Visibility) else visibility
    return resource


def _no_grant():
    return patch(
        "app.services.access.resource_grant_repo.get_level",
        new=AsyncMock(return_value=None),
    )


def _grant(level: GrantLevel):
    return patch(
        "app.services.access.resource_grant_repo.get_level",
        new=AsyncMock(return_value=level),
    )


class TestScopeRules:
    @pytest.mark.anyio
    async def test_owner_role_reaches_everything(self):
        ctx = _ctx(OrgRoleName.OWNER)
        resource = _resource(ctx.organization_id, owner_user_id=uuid.uuid4())

        with _no_grant():
            assert await resolve_access(
                MagicMock(), ctx, resource, Perm.COLLECTIONS_EDIT, resource_type=COLLECTION
            )

    @pytest.mark.anyio
    async def test_member_edits_own_resource(self):
        ctx = _ctx(OrgRoleName.MEMBER)
        resource = _resource(ctx.organization_id, owner_user_id=ctx.user_id)

        with _no_grant():
            assert await resolve_access(
                MagicMock(), ctx, resource, Perm.COLLECTIONS_EDIT, resource_type=COLLECTION
            )

    @pytest.mark.anyio
    async def test_member_cannot_edit_someone_elses(self):
        ctx = _ctx(OrgRoleName.MEMBER)
        resource = _resource(ctx.organization_id, owner_user_id=uuid.uuid4())

        with _no_grant():
            assert not await resolve_access(
                MagicMock(), ctx, resource, Perm.COLLECTIONS_EDIT, resource_type=COLLECTION
            )

    @pytest.mark.anyio
    async def test_member_cannot_see_a_private_resource_of_another(self):
        ctx = _ctx(OrgRoleName.MEMBER)
        resource = _resource(ctx.organization_id, owner_user_id=uuid.uuid4())

        with _no_grant():
            assert not await resolve_access(
                MagicMock(), ctx, resource, Perm.COLLECTIONS_VIEW, resource_type=COLLECTION
            )

    @pytest.mark.anyio
    async def test_org_visibility_counts_as_shared_with_everyone(self):
        ctx = _ctx(OrgRoleName.MEMBER)
        resource = _resource(
            ctx.organization_id, owner_user_id=uuid.uuid4(), visibility=Visibility.ORG
        )

        with _no_grant():
            assert await resolve_access(
                MagicMock(), ctx, resource, Perm.COLLECTIONS_VIEW, resource_type=COLLECTION
            )

    @pytest.mark.anyio
    async def test_builder_views_all_but_cannot_edit_a_private_one(self):
        ctx = _ctx(OrgRoleName.BUILDER)
        resource = _resource(ctx.organization_id, owner_user_id=uuid.uuid4())

        with _no_grant():
            assert await resolve_access(
                MagicMock(), ctx, resource, Perm.COLLECTIONS_VIEW, resource_type=COLLECTION
            )
            assert not await resolve_access(
                MagicMock(), ctx, resource, Perm.COLLECTIONS_EDIT, resource_type=COLLECTION
            )


class TestTeamScope:
    """`team` sits between `shared` and `all`: mine, plus what the team can see.

    No built-in role carries it yet - it exists for the custom roles a client
    composes, which may only recombine the scopes defined here. The resolution
    rule has to be right before the first role uses it, because the failure mode
    is silent over-exposure rather than an error.
    """

    def _team_lead(self):
        return patch.dict(ROLE_PERMS, {"team-lead": {Perm.COLLECTIONS_VIEW: Scope.TEAM}})

    @pytest.mark.anyio
    async def test_a_team_scope_reaches_a_resource_its_owner_shared_with_the_team(self):
        ctx = _ctx("team-lead")
        resource = _resource(
            ctx.organization_id, owner_user_id=uuid.uuid4(), visibility=Visibility.TEAM
        )

        with self._team_lead(), _no_grant():
            assert await resolve_access(
                MagicMock(), ctx, resource, Perm.COLLECTIONS_VIEW, resource_type=COLLECTION
            )

    @pytest.mark.anyio
    async def test_a_team_scope_still_does_not_reach_another_members_private_resource(self):
        """Team-wide is not org-wide-with-extra-steps; private stays private."""
        ctx = _ctx("team-lead")
        resource = _resource(ctx.organization_id, owner_user_id=uuid.uuid4())

        with self._team_lead(), _no_grant():
            assert not await resolve_access(
                MagicMock(), ctx, resource, Perm.COLLECTIONS_VIEW, resource_type=COLLECTION
            )


class TestPermissionsGrantsCannotWiden:
    @pytest.mark.anyio
    async def test_sharing_a_resource_cannot_hand_over_an_org_wide_permission(self):
        """`runs:view` is binary and org-wide - there is no single row to widen.

        Without this guard, the grant lookup would run for a permission whose
        grant level is undefined, and the first level that happened to compare
        favourably would turn "you may see this collection" into "you may read
        the organization's entire run history".
        """
        ctx = _ctx(OrgRoleName.MEMBER)
        resource = _resource(ctx.organization_id, owner_user_id=ctx.user_id)

        with _grant(GrantLevel.EDIT) as lookup:
            assert not await resolve_access(
                MagicMock(), ctx, resource, Perm.RUNS_VIEW, resource_type=COLLECTION
            )

        assert lookup.await_count == 0


class TestGrantsWidenAccess:
    @pytest.mark.anyio
    async def test_edit_grant_lets_a_viewer_edit_one_resource(self):
        """The point of sharing: reach beyond the role, for this row only."""
        ctx = _ctx(OrgRoleName.VIEWER)
        resource = _resource(ctx.organization_id, owner_user_id=uuid.uuid4())

        with _grant(GrantLevel.EDIT):
            assert await resolve_access(
                MagicMock(), ctx, resource, Perm.COLLECTIONS_EDIT, resource_type=COLLECTION
            )

    @pytest.mark.anyio
    async def test_read_grant_is_not_enough_to_edit(self):
        ctx = _ctx(OrgRoleName.MEMBER)
        resource = _resource(ctx.organization_id, owner_user_id=uuid.uuid4())

        with _grant(GrantLevel.READ):
            assert not await resolve_access(
                MagicMock(), ctx, resource, Perm.COLLECTIONS_EDIT, resource_type=COLLECTION
            )
            assert await resolve_access(
                MagicMock(), ctx, resource, Perm.COLLECTIONS_VIEW, resource_type=COLLECTION
            )


class TestTenantBoundary:
    @pytest.mark.anyio
    async def test_another_organizations_resource_is_never_reachable(self):
        ctx = _ctx(OrgRoleName.OWNER)
        resource = _resource(uuid.uuid4(), owner_user_id=ctx.user_id)

        with _grant(GrantLevel.EDIT):
            assert not await resolve_access(
                MagicMock(), ctx, resource, Perm.COLLECTIONS_VIEW, resource_type=COLLECTION
            )


class TestListingHelper:
    @pytest.mark.anyio
    async def test_all_scope_skips_the_grant_lookup(self):
        ctx = _ctx(OrgRoleName.BUILDER)
        with patch(
            "app.services.access.resource_grant_repo.list_shared_ids", new=AsyncMock()
        ) as lookup:
            result = await visible_resource_ids(
                MagicMock(), ctx, resource_type=COLLECTION, perm=Perm.COLLECTIONS_VIEW
            )
        assert result is None
        lookup.assert_not_awaited()

    @pytest.mark.anyio
    async def test_narrow_scope_returns_shared_ids(self):
        ctx = _ctx(OrgRoleName.MEMBER)
        shared = [uuid.uuid4()]
        with patch(
            "app.services.access.resource_grant_repo.list_shared_ids",
            new=AsyncMock(return_value=shared),
        ):
            result = await visible_resource_ids(
                MagicMock(), ctx, resource_type=COLLECTION, perm=Perm.COLLECTIONS_VIEW
            )
        assert result == shared


class TestARunWithNobodyBehindIt:
    """A context with no subject must reach nothing, by construction.

    Every run on this platform has a subject: a person with a role in an
    organization. Budgets, resource grants, the audit trail and the approval
    gate all key on it, and `mentions.py` refuses an unlinked Slack identity
    for exactly that reason - a run with no subject is one nobody is
    accountable for.

    A public surface breaks that invariant: its visitors are anonymous. The
    answer is not a fallback user, it is that a subject-less context resolves to
    *no access at all* and the exposure row carries what a person would have
    carried. This class is where that is nailed down, because the alternative is
    a convention every future caller has to remember.

    The two failures it forecloses are different. A subject-less context whose
    `role` string happens to name a real role would sail through the scope
    check and reach everything - nothing structural stops one being built. And a
    grant lookup keyed on a `NULL` subject asks the database a question whose
    answer depends on what rows exist rather than on the invariant.
    """

    @pytest.mark.anyio
    @pytest.mark.parametrize("role", list(OrgRoleName), ids=lambda role: role.value)
    async def test_no_role_string_lets_a_subjectless_context_reach_a_row(self, role):
        """Including `owner`, which is the whole point.

        The refusal cannot be "an anonymous context happens to carry a role with
        no permissions" - that is a property of the string it was built with. It
        has to hold whatever the role says.
        """
        org_id = uuid.uuid4()
        ctx = AuthContext(user_id=None, organization_id=org_id, role=role.value)
        resource = _resource(org_id, owner_user_id=None, visibility=Visibility.ORG)

        with _grant(GrantLevel.EDIT):
            assert not await resolve_access(
                MagicMock(), ctx, resource, Perm.COLLECTIONS_EDIT, resource_type=COLLECTION
            )

    @pytest.mark.anyio
    async def test_a_subjectless_context_never_asks_the_grant_table(self):
        """A query keyed on NULL is a question with no right answer.

        Refusing before the lookup is what makes the guarantee independent of
        what rows exist - a grant with a null subject would otherwise be
        inherited by every anonymous visitor at once.
        """
        org_id = uuid.uuid4()
        ctx = AuthContext(user_id=None, organization_id=org_id, role=OrgRoleName.MEMBER.value)
        resource = _resource(org_id, owner_user_id=None)
        lookup = AsyncMock(return_value=None)

        with patch("app.services.access.resource_grant_repo.get_level", new=lookup):
            await resolve_access(
                MagicMock(), ctx, resource, Perm.COLLECTIONS_VIEW, resource_type=COLLECTION
            )

        lookup.assert_not_called()

    @pytest.mark.anyio
    async def test_a_subjectless_context_owns_nothing_even_when_the_row_does_not_either(self):
        """`owner_user_id IS NULL` must not read as "owned by nobody, so mine".

        Ownership is compared by value, and two absent values are equal. A row
        whose owner was deleted - `ON DELETE SET NULL` leaves plenty - would
        otherwise belong to every anonymous visitor.
        """
        org_id = uuid.uuid4()
        ctx = AuthContext(user_id=None, organization_id=org_id, role=OrgRoleName.MEMBER.value)
        orphaned = _resource(org_id, owner_user_id=None)

        with _no_grant():
            assert not await resolve_access(
                MagicMock(), ctx, orphaned, Perm.COLLECTIONS_EDIT, resource_type=COLLECTION
            )

    @pytest.mark.anyio
    async def test_a_listing_for_a_subjectless_context_is_empty_rather_than_unfiltered(self):
        """`None` means "the role reaches everything" to every caller of this.

        Returning it for a context with no subject would widen a listing to the
        whole organization - the opposite of the intent - so the empty list is
        the only safe answer, and it is reached without a query.
        """
        ctx = AuthContext(user_id=None, organization_id=uuid.uuid4(), role=OrgRoleName.OWNER.value)
        lookup = AsyncMock(return_value=[uuid.uuid4()])

        with patch("app.services.access.resource_grant_repo.list_shared_ids", new=lookup):
            visible = await visible_resource_ids(
                MagicMock(), ctx, resource_type=COLLECTION, perm=Perm.COLLECTIONS_VIEW
            )

        assert visible == []
        lookup.assert_not_called()


class TestTheAnonymousContext:
    """The one way to build a context with no subject, so it is greppable."""

    def test_it_holds_no_permission_at_all(self):
        ctx = AuthContext.anonymous(uuid.uuid4())

        assert not any(ctx.has(perm) for perm in Perm)

    def test_its_role_names_no_real_role(self):
        """Otherwise a future edit to ROLE_PERMS could hand it permissions."""
        assert AuthContext.anonymous(uuid.uuid4()).role not in ROLE_PERMS

    def test_it_says_it_has_no_subject(self):
        """Read by the code that has to behave differently, rather than `is None`."""
        anonymous = AuthContext.anonymous(uuid.uuid4())
        somebody = _ctx(OrgRoleName.MEMBER)

        assert (anonymous.is_anonymous, somebody.is_anonymous) == (True, False)

    def test_it_is_not_an_app_admin(self):
        """`is_app_admin` short-circuits to every permission at Scope.ALL."""
        assert AuthContext.anonymous(uuid.uuid4()).is_app_admin is False


class TestOperationsThatNeedAPerson:
    """`subject_id` - the accessor for work that cannot be done by nobody.

    Most of what a service does keys on a person: an audit entry names an actor,
    an approval names who decided, a listing of "mine plus what was shared with
    me" is meaningless without a me. Those sites read `subject_id` rather than
    `user_id`, which keeps their `UUID` typing honest and - more usefully -
    makes "this needs a person" something the code says out loud.

    It raises rather than returning `None` because the alternatives are worse.
    The audit actor column is `NOT NULL`, so passing the absence through
    surfaces four layers down as an `IntegrityError` naming a constraint, at
    which point the audit entry is lost and the request has already half
    happened. A refusal at the top says what was attempted and by whom.
    """

    def test_it_is_the_user_when_there_is_one(self):
        ctx = _ctx(OrgRoleName.MEMBER)

        assert ctx.subject_id == ctx.user_id

    def test_it_refuses_rather_than_letting_the_absence_travel(self):
        with pytest.raises(AuthorizationError) as refused:
            _ = AuthContext.anonymous(uuid.uuid4()).subject_id

        assert "signed-in subject" in refused.value.message

    def test_the_refusal_names_the_organization_it_happened_in(self):
        """A log line saying only "anonymous" is a log line nobody can trace."""
        org_id = uuid.uuid4()

        with pytest.raises(AuthorizationError) as refused:
            _ = AuthContext.anonymous(org_id).subject_id

        assert refused.value.details == {"org_id": str(org_id)}


class TestWhatAnAnonymousSurfaceRunsAs:
    """The role a turn takes when nobody in front of it can be named.

    A widget on somebody's site, a hosted page behind a link, an agent bound to a
    Slack channel: the person is anonymous, or a chat account with no platform user
    behind it, and a run still needs a subject because the role is what resolves
    what the agent may reach. So it is whoever published the surface.

    It was written twice before #640 - once against `agent_embeds.owner_user_id`
    and once against `agent_exposures.created_by_user_id` - and two copies of an
    authorization decision is one that gets fixed once. The per-surface tests still
    assert it through their own entry points; what this class owns is the rule.
    """

    @pytest.mark.anyio
    async def test_a_publisher_who_is_still_a_member_lends_their_role(self):
        organization, publisher = uuid.uuid4(), uuid.uuid4()

        with patch(
            "app.services.access.member_repo.get",
            new=AsyncMock(return_value=MagicMock(role=OrgRoleName.BUILDER.value)),
        ):
            ctx = await publisher_context(
                MagicMock(), organization_id=organization, publisher_user_id=publisher
            )

        assert (ctx.role, ctx.user_id, ctx.organization_id) == (
            OrgRoleName.BUILDER.value,
            publisher,
            organization,
        )

    @pytest.mark.anyio
    async def test_a_publisher_who_left_drops_the_turn_to_viewer(self):
        """Their departure must not silently *widen* what a public surface reaches.
        A widget on a customer's site outlives the person who pasted it."""
        with patch("app.services.access.member_repo.get", new=AsyncMock(return_value=None)):
            ctx = await publisher_context(
                MagicMock(), organization_id=uuid.uuid4(), publisher_user_id=uuid.uuid4()
            )

        assert ctx.role == OrgRoleName.VIEWER.value

    @pytest.mark.anyio
    async def test_a_surface_with_no_publisher_recorded_drops_too(self):
        """A row old enough to predate the column naming who made it. `viewer` is
        the answer for the same reason, and no membership is read at all."""
        read = AsyncMock()

        with patch("app.services.access.member_repo.get", new=read):
            ctx = await publisher_context(
                MagicMock(), organization_id=uuid.uuid4(), publisher_user_id=None
            )

        assert (ctx.role, ctx.user_id) == (OrgRoleName.VIEWER.value, None)
        read.assert_not_awaited()

    @pytest.mark.anyio
    async def test_who_asked_is_carried_and_is_not_who_published(self):
        """Two different facts. The role comes from the publisher; the chat identity
        records who *spoke*, and merging them would make a channel run claim the
        sender's authority - which an unlinked sender does not have."""
        asker = uuid.uuid4()

        with patch("app.services.access.member_repo.get", new=AsyncMock(return_value=None)):
            ctx = await publisher_context(
                MagicMock(),
                organization_id=uuid.uuid4(),
                publisher_user_id=None,
                channel_identity_id=asker,
            )

        assert ctx.channel_identity_id == asker
        assert ctx.user_id is None
