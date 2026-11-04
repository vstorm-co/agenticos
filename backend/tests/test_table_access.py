"""Who may reach a virtual table: the role matrix and grants for the TABLE resource type."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.permissions import AuthContext, OrgRoleName, Perm, Scope
from app.db.models.resource_grant import GrantLevel, Visibility
from app.services.access import TABLE, resolve_access

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def _ctx(role: str) -> AuthContext:
    return AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=role)


def _table(ctx: AuthContext, *, owner: uuid.UUID | None = None):
    table = MagicMock()
    table.id = uuid.uuid4()
    table.organization_id = ctx.organization_id
    table.owner_user_id = owner or uuid.uuid4()
    table.visibility = Visibility.PRIVATE.value
    return table


def _grant(level: GrantLevel | None):
    return patch(
        "app.services.access.resource_grant_repo.get_level", new=AsyncMock(return_value=level)
    )


def test_creating_a_table_is_a_global_permission_and_not_every_role_holds_it():
    creators = {
        role
        for role in OrgRoleName
        if AuthContext(uuid.uuid4(), uuid.uuid4(), role).has(Perm.TABLES_CREATE)
    }
    assert creators == {
        OrgRoleName.OWNER,
        OrgRoleName.ADMIN,
        OrgRoleName.BUILDER,
        OrgRoleName.MEMBER,
    }


def test_a_viewer_and_an_operator_never_edit_a_table_by_role():
    for role in (OrgRoleName.VIEWER, OrgRoleName.OPERATOR):
        assert _ctx(role).scope_for(Perm.TABLES_EDIT) is Scope.NONE


async def test_a_member_edits_their_own_table_but_not_a_colleagues():
    ctx = _ctx(OrgRoleName.MEMBER)
    with _grant(None):
        assert await resolve_access(
            MagicMock(), ctx, _table(ctx, owner=ctx.user_id), Perm.TABLES_EDIT, resource_type=TABLE
        )
        assert not await resolve_access(
            MagicMock(), ctx, _table(ctx), Perm.TABLES_EDIT, resource_type=TABLE
        )


async def test_an_edit_grant_widens_a_viewer_on_one_table_and_a_read_grant_does_not():
    ctx = _ctx(OrgRoleName.VIEWER)
    table = _table(ctx)
    with _grant(GrantLevel.EDIT):
        assert await resolve_access(MagicMock(), ctx, table, Perm.TABLES_EDIT, resource_type=TABLE)
    with _grant(GrantLevel.READ):
        assert await resolve_access(MagicMock(), ctx, table, Perm.TABLES_VIEW, resource_type=TABLE)
        assert not await resolve_access(
            MagicMock(), ctx, table, Perm.TABLES_EDIT, resource_type=TABLE
        )


async def test_another_organizations_table_is_refused_even_to_an_owner():
    ctx = _ctx(OrgRoleName.OWNER)
    table = _table(ctx)
    table.organization_id = uuid.uuid4()
    with _grant(GrantLevel.EDIT):
        assert not await resolve_access(
            MagicMock(), ctx, table, Perm.TABLES_VIEW, resource_type=TABLE
        )
