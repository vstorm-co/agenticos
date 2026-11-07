"""Sharing responses preserve edit-only API key authority through the service."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.api import deps
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.db.models.skill import Skill
from app.main import app
from app.services import sharing

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.fixture
def editable_skill(
    mock_db_session: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> tuple[AuthContext, Skill]:
    ctx = AuthContext(
        user_id=uuid4(),
        organization_id=uuid4(),
        role=OrgRoleName.OWNER,
        key_scopes=frozenset({Perm.SKILLS_EDIT}),
    )
    row = Skill(
        id=uuid4(),
        organization_id=ctx.organization_id,
        owner_user_id=ctx.user_id,
        name="editable",
        description="Owned skill",
        content="",
        visibility="private",
    )
    mock_db_session.get.return_value = row
    mock_db_session.add = MagicMock()
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    monkeypatch.setattr(sharing, "record_audit", AsyncMock())
    monkeypatch.setattr(
        sharing.resource_grant_repo, "list_for_resource", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(sharing.member_repo, "get_emails_for_users", AsyncMock(return_value={}))
    monkeypatch.setattr(sharing.group_repo, "get_names", AsyncMock(return_value={}))
    return ctx, row


async def test_edit_only_key_receives_the_updated_sharing_state(
    client: AsyncClient, editable_skill: tuple[AuthContext, Skill]
) -> None:
    _, row = editable_skill
    response = await client.patch(
        f"/api/v1/skills/{row.id}/sharing/visibility", json={"visibility": "org"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["visibility"] == "org"
    assert row.visibility == "org"
    state = await client.get(f"/api/v1/skills/{row.id}/sharing")
    assert state.status_code == 200
    assert state.json()["visibility"] == "org"


@pytest.mark.parametrize("method", ["GET", "PATCH"])
async def test_edit_only_key_cannot_read_or_change_another_tenants_sharing(
    client: AsyncClient,
    editable_skill: tuple[AuthContext, Skill],
    mock_db_session: AsyncMock,
    method: str,
) -> None:
    _, row = editable_skill
    row.organization_id = uuid4()
    path = f"/api/v1/skills/{row.id}/sharing"
    response = await client.request(
        method, path + "/visibility" if method == "PATCH" else path, json={"visibility": "org"}
    )
    assert response.status_code == 404
    assert row.visibility == "private"
    mock_db_session.flush.assert_not_awaited()


async def test_view_only_key_cannot_change_sharing(
    client: AsyncClient, editable_skill: tuple[AuthContext, Skill], mock_db_session: AsyncMock
) -> None:
    ctx, row = editable_skill
    view_only = AuthContext(
        user_id=ctx.user_id,
        organization_id=ctx.organization_id,
        role=ctx.role,
        key_scopes=frozenset({Perm.SKILLS_VIEW}),
    )
    app.dependency_overrides[deps.get_auth_context] = lambda: view_only
    response = await client.patch(
        f"/api/v1/skills/{row.id}/sharing/visibility", json={"visibility": "org"}
    )
    assert response.status_code == 403
    assert row.visibility == "private"
    mock_db_session.flush.assert_not_awaited()
