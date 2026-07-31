"""Tests for the permission catalog and the require() dependency.

The catalog is the single source of truth for authorization, so these tests
guard its invariants rather than restating the role table: a role that drifts
into holding a permission the platform does not define, or a scope attached to
a permission that has no rows to scope, is a bug the tests should catch before
an endpoint does.
"""

import operator
import uuid

import pytest

from app.api.deps import require
from app.core.exceptions import AuthorizationError
from app.core.permissions import (
    RESOURCE_PERMS,
    ROLE_PERMS,
    AuthContext,
    OrgRoleName,
    Perm,
    Scope,
)


def _ctx(role: str, *, is_app_admin: bool = False) -> AuthContext:
    return AuthContext(
        user_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        role=role,
        is_app_admin=is_app_admin,
    )


class TestCatalogInvariants:
    def test_every_role_is_defined(self):
        assert set(ROLE_PERMS) == {role.value for role in OrgRoleName}

    def test_roles_only_use_catalog_permissions(self):
        for role, perms in ROLE_PERMS.items():
            unknown = set(perms) - set(Perm)
            assert not unknown, f"{role} holds permissions outside the catalog: {unknown}"

    def test_no_role_holds_a_permission_at_scope_none(self):
        """Absence means "not held" - an explicit NONE would be a second way to say it."""
        for role, perms in ROLE_PERMS.items():
            empty = [perm for perm, scope in perms.items() if scope is Scope.NONE]
            assert not empty, f"{role} lists {empty} at scope none; drop the entry instead"

    def test_global_permissions_are_never_partially_scoped(self):
        """A global permission is binary - org-wide or not held at all."""
        for role, perms in ROLE_PERMS.items():
            for perm, scope in perms.items():
                if perm not in RESOURCE_PERMS:
                    assert scope is Scope.ALL, f"{role}.{perm} is global but scoped {scope}"

    def test_owner_holds_everything(self):
        assert set(ROLE_PERMS[OrgRoleName.OWNER]) == set(Perm)

    def test_admin_cannot_delete_the_organization(self):
        assert Perm.ORG_DELETE not in ROLE_PERMS[OrgRoleName.ADMIN]

    def test_viewer_cannot_edit_anything(self):
        viewer = ROLE_PERMS[OrgRoleName.VIEWER]
        assert Perm.AGENTS_EDIT not in viewer
        assert Perm.COLLECTIONS_EDIT not in viewer
        assert Perm.SKILLS_EDIT not in viewer


class TestScopeOrdering:
    def test_scopes_are_ordered(self):
        assert Scope.NONE < Scope.OWN < Scope.SHARED < Scope.TEAM < Scope.ALL

    def test_every_comparison_orders_by_reach_rather_than_alphabetically(self):
        """`Scope` is a `str`, and each of the four operators has to override it.

        Left to string comparison these all invert - `"all" < "none" < "own"` -
        so an operator that was forgotten reads as "narrower" for the widest
        scope there is. Each one is checked in the direction where the two
        orderings disagree.
        """
        assert Scope.ALL > Scope.NONE
        assert Scope.ALL >= Scope.TEAM
        assert Scope.NONE < Scope.ALL
        assert Scope.NONE <= Scope.ALL
        assert not Scope.OWN >= Scope.SHARED

    def test_no_comparison_falls_back_to_string_ordering(self):
        """A mixed comparison must raise rather than answer, in every direction.

        `Scope.OWN < "shared"` is `True` as strings and `TypeError` here;
        a silent wrong answer inside an authorization check is the failure this
        exists to prevent.
        """
        for compare in (operator.lt, operator.le, operator.gt, operator.ge):
            with pytest.raises(TypeError, match="only be compared to Scope"):
                compare(Scope.OWN, "shared")


class TestAuthContext:
    def test_member_edits_only_their_own(self):
        ctx = _ctx(OrgRoleName.MEMBER)
        assert ctx.scope_for(Perm.AGENTS_EDIT) is Scope.OWN
        assert ctx.scope_for(Perm.AGENTS_VIEW) is Scope.SHARED

    def test_builder_sees_all_but_edits_shared(self):
        ctx = _ctx(OrgRoleName.BUILDER)
        assert ctx.scope_for(Perm.AGENTS_VIEW) is Scope.ALL
        assert ctx.scope_for(Perm.AGENTS_EDIT) is Scope.SHARED

    def test_operator_runs_but_does_not_build(self):
        ctx = _ctx(OrgRoleName.OPERATOR)
        assert ctx.has(Perm.AGENTS_RUN)
        assert ctx.has(Perm.APPROVALS_DECIDE)
        assert not ctx.has(Perm.AGENTS_EDIT)

    def test_unknown_role_holds_nothing(self):
        ctx = _ctx("not-a-role")
        assert ctx.permissions == {}
        assert not ctx.has(Perm.AGENTS_VIEW)

    def test_app_admin_holds_everything_regardless_of_role(self):
        ctx = _ctx(OrgRoleName.VIEWER, is_app_admin=True)
        assert ctx.has_all(*Perm)

    def test_has_all_requires_every_permission(self):
        ctx = _ctx(OrgRoleName.OPERATOR)
        assert ctx.has_all(Perm.AGENTS_VIEW, Perm.AGENTS_RUN)
        assert not ctx.has_all(Perm.AGENTS_VIEW, Perm.AGENTS_EDIT)


class TestRequireDependency:
    @pytest.mark.anyio
    async def test_passes_when_permission_held(self):
        ctx = _ctx(OrgRoleName.ADMIN)
        dependency = require(Perm.MEMBERS_MANAGE)
        assert await dependency(ctx) is ctx

    @pytest.mark.anyio
    async def test_raises_when_permission_missing(self):
        ctx = _ctx(OrgRoleName.MEMBER)
        dependency = require(Perm.MEMBERS_MANAGE)
        with pytest.raises(AuthorizationError) as exc:
            await dependency(ctx)
        assert exc.value.details is not None
        assert "members:manage" in exc.value.details["required"]

    @pytest.mark.anyio
    async def test_reports_every_missing_permission(self):
        """The error names all of them so a caller fixes the role once, not twice."""
        ctx = _ctx(OrgRoleName.VIEWER)
        dependency = require(Perm.MEMBERS_MANAGE, Perm.BUDGETS_MANAGE)
        with pytest.raises(AuthorizationError) as exc:
            await dependency(ctx)
        assert exc.value.details is not None
        assert set(exc.value.details["required"]) == {"members:manage", "budgets:manage"}
