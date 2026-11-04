"""Who may reach a workflow: the role matrix and grants for the WORKFLOW resource type.

Mirrors `test_table_access.py` - workflows are a shareable resource shaped
the same way tables are, plus the fourth permission, `WORKFLOWS_RUN`, which
`AGENTS_RUN` is the precedent for: "may edit" and "may cause it to run" are
different authorities.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.permissions import AuthContext, OrgRoleName, Perm, Scope
from app.db.models.resource_grant import GrantLevel, Visibility
from app.services.access import WORKFLOW, resolve_access

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def _ctx(role: str) -> AuthContext:
    return AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=role)


def _workflow(ctx: AuthContext, *, owner: uuid.UUID | None = None):
    workflow = MagicMock()
    workflow.id = uuid.uuid4()
    workflow.organization_id = ctx.organization_id
    workflow.owner_user_id = owner or uuid.uuid4()
    workflow.visibility = Visibility.PRIVATE.value
    return workflow


def _grant(level: GrantLevel | None):
    return patch(
        "app.services.access.resource_grant_repo.get_level", new=AsyncMock(return_value=level)
    )


def test_creating_a_workflow_is_a_global_permission_and_not_every_role_holds_it():
    creators = {
        role
        for role in OrgRoleName
        if AuthContext(uuid.uuid4(), uuid.uuid4(), role).has(Perm.WORKFLOWS_CREATE)
    }
    assert creators == {
        OrgRoleName.OWNER,
        OrgRoleName.ADMIN,
        OrgRoleName.BUILDER,
        OrgRoleName.MEMBER,
    }


def test_a_viewer_and_an_operator_never_edit_a_workflow_by_role():
    for role in (OrgRoleName.VIEWER, OrgRoleName.OPERATOR):
        assert _ctx(role).scope_for(Perm.WORKFLOWS_EDIT) is Scope.NONE


def test_running_a_workflow_is_a_distinct_authority_from_editing_it():
    """The precedent is `AGENTS_RUN`: an operator may cause a workflow to run
    without ever being able to change its graph."""
    ctx = _ctx(OrgRoleName.OPERATOR)
    assert ctx.has(Perm.WORKFLOWS_RUN)
    assert not ctx.has(Perm.WORKFLOWS_EDIT)


async def test_a_member_edits_their_own_workflow_but_not_a_colleagues():
    ctx = _ctx(OrgRoleName.MEMBER)
    with _grant(None):
        assert await resolve_access(
            MagicMock(),
            ctx,
            _workflow(ctx, owner=ctx.user_id),
            Perm.WORKFLOWS_EDIT,
            resource_type=WORKFLOW,
        )
        assert not await resolve_access(
            MagicMock(), ctx, _workflow(ctx), Perm.WORKFLOWS_EDIT, resource_type=WORKFLOW
        )


async def test_an_edit_grant_widens_a_viewer_on_one_workflow_and_a_read_grant_does_not():
    ctx = _ctx(OrgRoleName.VIEWER)
    workflow = _workflow(ctx)
    with _grant(GrantLevel.EDIT):
        assert await resolve_access(
            MagicMock(), ctx, workflow, Perm.WORKFLOWS_EDIT, resource_type=WORKFLOW
        )
    with _grant(GrantLevel.READ):
        assert await resolve_access(
            MagicMock(), ctx, workflow, Perm.WORKFLOWS_VIEW, resource_type=WORKFLOW
        )
        assert not await resolve_access(
            MagicMock(), ctx, workflow, Perm.WORKFLOWS_EDIT, resource_type=WORKFLOW
        )


async def test_a_use_grant_widens_a_viewer_to_run_one_workflow_but_not_to_edit_it():
    """The grant precedent `_PERM_MIN_GRANT[Perm.WORKFLOWS_RUN] = GrantLevel.USE`
    exists to satisfy: without it, a resource grant could never reach a
    `WORKFLOWS_RUN` check, only a role's own scope could."""
    ctx = _ctx(OrgRoleName.VIEWER)
    workflow = _workflow(ctx)
    with _grant(GrantLevel.USE):
        assert await resolve_access(
            MagicMock(), ctx, workflow, Perm.WORKFLOWS_RUN, resource_type=WORKFLOW
        )
        assert not await resolve_access(
            MagicMock(), ctx, workflow, Perm.WORKFLOWS_EDIT, resource_type=WORKFLOW
        )
    with _grant(GrantLevel.READ):
        assert not await resolve_access(
            MagicMock(), ctx, workflow, Perm.WORKFLOWS_RUN, resource_type=WORKFLOW
        )


async def test_another_organizations_workflow_is_refused_even_to_an_owner():
    ctx = _ctx(OrgRoleName.OWNER)
    workflow = _workflow(ctx)
    workflow.organization_id = uuid.uuid4()
    with _grant(GrantLevel.EDIT):
        assert not await resolve_access(
            MagicMock(), ctx, workflow, Perm.WORKFLOWS_VIEW, resource_type=WORKFLOW
        )
