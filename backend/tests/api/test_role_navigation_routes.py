"""The sidebar policy HTTP contract and refusals, using the real service."""

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.db.models.organization import Organization
from app.main import app
from app.repositories import member_repo, organization_repo
from app.services import role_navigation

pytestmark = pytest.mark.anyio
PATH = f"{settings.API_V1_STR}/roles/navigation"


def _caller(role: str, *, app_admin: bool = False, scoped: bool = False) -> AuthContext:
    ctx = AuthContext(
        user_id=uuid4(),
        organization_id=uuid4(),
        role=role,
        is_app_admin=app_admin,
        key_scopes=frozenset({Perm.AGENTS_VIEW}) if scoped else None,
    )
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    return ctx


@pytest.mark.parametrize("role", list(OrgRoleName))
@pytest.mark.security
async def test_any_member_reads_this_tenant_policy_and_their_own_hidden_entries(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, role: OrgRoleName
) -> None:
    ctx = _caller(role)
    org = Organization(id=ctx.organization_id, role_navigation={"member": ["chat", "groups"]})
    get = AsyncMock(return_value=org)
    monkeypatch.setattr(organization_repo, "get_by_id", get)
    response = await client.get(PATH)
    assert response.status_code == 200
    assert response.json()["hidden_items"]["member"] == ["chat", "groups"]
    assert response.json()["hidden_items"]["owner"] == []
    own = await client.get(f"{settings.API_V1_STR}/me/permissions")
    assert own.status_code == 200
    assert own.json()["hidden_navigation_items"] == (["chat", "groups"] if role == "member" else [])
    assert own.json()["role"] == role
    assert all(call.args[1] == ctx.organization_id for call in get.await_args_list)


@pytest.mark.parametrize("role", ["builder", "operator", "member", "viewer"])
@pytest.mark.security
async def test_a_non_manager_cannot_save_even_an_empty_policy(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, role: str
) -> None:
    _caller(role)
    write = AsyncMock()
    monkeypatch.setattr(organization_repo, "set_role_navigation", write)
    response = await client.patch(f"{PATH}/member", json={"hidden_items": []})
    assert response.status_code == 403
    write.assert_not_awaited()


@pytest.mark.parametrize("app_admin", [False, True])
@pytest.mark.security
async def test_api_key_scopes_still_limit_an_owner_or_platform_admin(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, app_admin: bool
) -> None:
    _caller("owner", app_admin=app_admin, scoped=True)
    write = AsyncMock()
    monkeypatch.setattr(organization_repo, "set_role_navigation", write)
    response = await client.patch(f"{PATH}/member", json={"hidden_items": ["chat"]})
    assert response.status_code == 403
    write.assert_not_awaited()


@pytest.mark.parametrize(
    ("caller", "target"), [("owner", "owner"), ("admin", "admin"), ("admin", "owner")]
)
@pytest.mark.security
async def test_owner_and_peer_policy_writes_are_refused(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, caller: str, target: str
) -> None:
    _caller(caller)
    write = AsyncMock()
    monkeypatch.setattr(organization_repo, "set_role_navigation", write)
    response = await client.patch(f"{PATH}/{target}", json={"hidden_items": ["chat"]})
    assert response.status_code == 403
    write.assert_not_awaited()


@pytest.mark.parametrize("app_admin", [False, True])
@pytest.mark.security
async def test_a_manager_saves_and_resets_only_the_selected_role_in_the_active_org(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, app_admin: bool
) -> None:
    ctx = _caller("" if app_admin else "owner", app_admin=app_admin)
    org = Organization(id=ctx.organization_id, role_navigation={"viewer": ["skills"]})

    async def write(
        _db: object, *, organization_id: UUID, role: str, hidden_items: list[str]
    ) -> Organization:
        assert organization_id == ctx.organization_id
        org.role_navigation = {**(org.role_navigation or {}), role: hidden_items}
        return org

    monkeypatch.setattr(organization_repo, "set_role_navigation", write)
    monkeypatch.setattr(organization_repo, "get_by_id", AsyncMock(return_value=org))
    audit = AsyncMock()
    monkeypatch.setattr(role_navigation, "record_audit", audit)
    saved = await client.patch(f"{PATH}/member", json={"hidden_items": ["groups", "chat"]})
    assert saved.status_code == 200
    assert saved.json()["hidden_items"]["member"] == ["chat", "groups"]
    assert saved.json()["hidden_items"]["viewer"] == ["skills"]
    assert "owner" not in saved.json()["editable_roles"]
    read = await client.get(PATH)
    assert read.json()["hidden_items"] == saved.json()["hidden_items"]
    reset = await client.patch(f"{PATH}/member", json={"hidden_items": []})
    assert reset.status_code == 200
    assert reset.json()["hidden_items"]["member"] == []
    assert reset.json()["hidden_items"]["viewer"] == ["skills"]
    assert audit.await_count == 2


@pytest.mark.parametrize(
    ("target", "payload"),
    [
        ("invented", {"hidden_items": []}),
        ("member", {"hidden_items": ["dashboard"]}),
        ("member", {"hidden_items": ["chat", "chat"]}),
        ("member", {"hidden_items": [], "organization_id": str(uuid4())}),
    ],
)
@pytest.mark.security
async def test_invalid_roles_entries_and_tenant_overrides_are_validation_errors(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, target: str, payload: dict[str, object]
) -> None:
    _caller("owner")
    write = AsyncMock()
    monkeypatch.setattr(organization_repo, "set_role_navigation", write)
    response = await client.patch(f"{PATH}/{target}", json=payload)
    assert response.status_code == 422
    write.assert_not_awaited()


@pytest.mark.parametrize("method", ["get", "patch"])
@pytest.mark.security
async def test_a_nonmember_cannot_select_another_organization_by_header(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, method: str
) -> None:
    user = MagicMock(id=uuid4(), is_app_admin=False)
    app.dependency_overrides[deps.get_current_user] = lambda: user
    monkeypatch.setattr(member_repo, "get_with_organization", AsyncMock(return_value=None))
    write = AsyncMock()
    monkeypatch.setattr(organization_repo, "set_role_navigation", write)
    headers = {"X-Organization-Id": str(uuid4())}
    if method == "get":
        response = await client.get(PATH, headers=headers)
    else:
        response = await client.patch(f"{PATH}/member", headers=headers, json={"hidden_items": []})
    assert response.status_code == 404
    write.assert_not_awaited()
