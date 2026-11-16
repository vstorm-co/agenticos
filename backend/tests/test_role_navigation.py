"""Sidebar preferences stay tenant-scoped and never rewrite resource permissions."""

import importlib.util
import re
from io import StringIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.db.models.organization import Organization
from app.repositories import organization_repo
from app.schemas.permissions import NAVIGATION_ITEM_IDS, RoleNavigationUpdate
from app.services import role_navigation
from app.services.role_navigation import RoleNavigationService

pytestmark = pytest.mark.anyio


def _context(
    role: str = "member", *, is_app_admin: bool = False, key_scopes: frozenset[Perm] | None = None
) -> AuthContext:
    return AuthContext(
        user_id=uuid4(),
        organization_id=uuid4(),
        role=role,
        is_app_admin=is_app_admin,
        key_scopes=key_scopes,
    )


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"hidden_items": ["dashboard"]},
        {"hidden_items": ["organizations"]},
        {"hidden_items": ["adminOverview"]},
        {"hidden_items": ["unknown"]},
        {"hidden_items": ["chat", "chat"]},
        {"hidden_items": ["chat"] * (len(NAVIGATION_ITEM_IDS) + 1)},
        {"hidden_items": None},
        {"hidden_items": [False]},
        {"hidden_items": [], "organization_id": str(uuid4())},
        {"hidden_items": [], "permissions": []},
    ],
)
@pytest.mark.security
def test_invalid_or_protected_preferences_are_rejected(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        RoleNavigationUpdate.model_validate(payload)


def test_a_reset_is_explicit_and_entries_have_stable_catalog_order() -> None:
    assert RoleNavigationUpdate(hidden_items=[]).hidden_items == []
    assert RoleNavigationUpdate(hidden_items=["groups", "chat"]).hidden_items == ["chat", "groups"]


def test_every_sidebar_destination_has_a_policy_entry_or_is_explicitly_protected() -> None:
    source = Path(__file__).resolve().parents[2] / "frontend/src/lib/nav-sections.ts"
    destinations = set(
        re.findall(r'labelKey:\s*"([^"]+)",\s*href:', source.read_text(encoding="utf-8"))
    )
    protected = {"dashboard", "organizations", "adminOverview"}
    assert protected <= destinations
    assert set(NAVIGATION_ITEM_IDS) == destinations - protected


@pytest.mark.parametrize(
    ("role", "app_admin", "editable"),
    [
        ("owner", False, {"admin", "builder", "operator", "member", "viewer"}),
        ("admin", False, {"builder", "operator", "member", "viewer"}),
        ("builder", False, set()),
        ("operator", False, set()),
        ("member", False, set()),
        ("viewer", False, set()),
        ("", True, {"admin", "builder", "operator", "member", "viewer"}),
    ],
)
@pytest.mark.security
async def test_every_member_reads_the_policy_but_only_managers_edit_lower_roles(
    monkeypatch: pytest.MonkeyPatch, role: str, app_admin: bool, editable: set[str]
) -> None:
    ctx = _context(role, is_app_admin=app_admin)
    org = Organization(id=ctx.organization_id, role_navigation=None)
    get = AsyncMock(return_value=org)
    monkeypatch.setattr(organization_repo, "get_by_id", get)
    policy = await RoleNavigationService(AsyncMock()).read(ctx)
    assert policy.hidden_items == {key: [] for key in OrgRoleName}
    assert set(policy.editable_roles) == editable
    assert policy.configurable_items == list(NAVIGATION_ITEM_IDS)
    get.assert_awaited_once_with(get.await_args.args[0], ctx.organization_id)


@pytest.mark.security
async def test_hiding_navigation_does_not_revoke_a_permission_or_change_another_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = _context()
    held = ctx.permissions
    org = Organization(
        id=ctx.organization_id, role_navigation={"member": ["agents"], "viewer": ["skills"]}
    )
    monkeypatch.setattr(organization_repo, "get_by_id", AsyncMock(return_value=org))
    service = RoleNavigationService(AsyncMock())
    assert await service.for_caller(ctx) == ["agents"]
    assert ctx.permissions == held
    assert ctx.has(Perm.AGENTS_VIEW)
    assert (await service.read(ctx)).hidden_items[OrgRoleName.VIEWER] == ["skills"]


@pytest.mark.parametrize(("role", "app_admin"), [("owner", False), ("member", True)])
@pytest.mark.security
async def test_owner_and_platform_admin_cannot_be_hidden_from_navigation(
    monkeypatch: pytest.MonkeyPatch, role: str, app_admin: bool
) -> None:
    get = AsyncMock()
    monkeypatch.setattr(organization_repo, "get_by_id", get)
    assert (
        await RoleNavigationService(AsyncMock()).for_caller(_context(role, is_app_admin=app_admin))
        == []
    )
    get.assert_not_awaited()


@pytest.mark.security
async def test_an_old_owner_preference_never_hides_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = _context("owner")
    org = Organization(id=ctx.organization_id, role_navigation={"owner": ["chat"]})
    monkeypatch.setattr(organization_repo, "get_by_id", AsyncMock(return_value=org))
    assert (await RoleNavigationService(AsyncMock()).read(ctx)).hidden_items[
        OrgRoleName.OWNER
    ] == []


@pytest.mark.parametrize("method", ["read", "for_caller"])
@pytest.mark.security
async def test_anonymous_policy_reads_are_refused(method: str) -> None:
    service = RoleNavigationService(AsyncMock())
    with pytest.raises(AuthorizationError):
        await getattr(service, method)(AuthContext.anonymous(uuid4()))


@pytest.mark.parametrize("method", ["read", "for_caller"])
@pytest.mark.security
async def test_a_missing_organization_has_no_fallback_policy(
    monkeypatch: pytest.MonkeyPatch, method: str
) -> None:
    monkeypatch.setattr(organization_repo, "get_by_id", AsyncMock(return_value=None))
    with pytest.raises(NotFoundError):
        await getattr(RoleNavigationService(AsyncMock()), method)(_context())


@pytest.mark.parametrize(
    ("caller", "target"),
    [
        ("viewer", "member"),
        ("member", "viewer"),
        ("builder", "member"),
        ("operator", "member"),
        ("admin", "admin"),
        ("admin", "owner"),
        ("owner", "owner"),
    ],
)
@pytest.mark.security
async def test_non_managers_and_equal_or_higher_roles_cannot_be_changed(
    monkeypatch: pytest.MonkeyPatch, caller: str, target: str
) -> None:
    write = AsyncMock()
    monkeypatch.setattr(organization_repo, "set_role_navigation", write)
    with pytest.raises(AuthorizationError):
        await RoleNavigationService(AsyncMock()).update(
            _context(caller), OrgRoleName(target), RoleNavigationUpdate(hidden_items=["chat"])
        )
    write.assert_not_awaited()


@pytest.mark.parametrize("app_admin", [False, True])
@pytest.mark.security
async def test_an_owner_key_without_roles_manage_cannot_write(
    monkeypatch: pytest.MonkeyPatch, app_admin: bool
) -> None:
    write = AsyncMock()
    monkeypatch.setattr(organization_repo, "set_role_navigation", write)
    ctx = _context("owner", is_app_admin=app_admin, key_scopes=frozenset({Perm.AGENTS_VIEW}))
    with pytest.raises(AuthorizationError):
        await RoleNavigationService(AsyncMock()).update(
            ctx, OrgRoleName.MEMBER, RoleNavigationUpdate(hidden_items=["agents"])
        )
    write.assert_not_awaited()


@pytest.mark.parametrize(("caller", "target"), [("owner", "admin"), ("admin", "member")])
@pytest.mark.parametrize("hidden", [["chat", "groups"], []])
@pytest.mark.security
async def test_a_write_and_reset_are_scoped_to_the_caller_org_and_audited(
    monkeypatch: pytest.MonkeyPatch, caller: str, target: str, hidden: list[str]
) -> None:
    ctx = _context(caller)
    org = Organization(
        id=ctx.organization_id,
        role_navigation={target: hidden, "viewer": ["skills"]},
    )
    write = AsyncMock(return_value=org)
    audit = AsyncMock()
    monkeypatch.setattr(organization_repo, "set_role_navigation", write)
    monkeypatch.setattr(role_navigation, "record_audit", audit)
    db = AsyncMock()
    policy = await RoleNavigationService(db).update(
        ctx, OrgRoleName(target), RoleNavigationUpdate(hidden_items=hidden)
    )
    write.assert_awaited_once_with(
        db, organization_id=ctx.organization_id, role=target, hidden_items=hidden
    )
    assert policy.hidden_items[OrgRoleName(target)] == hidden
    assert policy.hidden_items[OrgRoleName.VIEWER] == ["skills"]
    assert audit.await_args.kwargs["actor_user_id"] == ctx.user_id
    assert audit.await_args.kwargs["organization_id"] == ctx.organization_id
    assert audit.await_args.kwargs["details"] == {"role": target, "hidden_items": hidden}
    db.commit.assert_not_awaited()


@pytest.mark.security
async def test_a_removed_organization_cannot_be_recreated_by_a_policy_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(organization_repo, "set_role_navigation", AsyncMock(return_value=None))
    audit = AsyncMock()
    monkeypatch.setattr(role_navigation, "record_audit", audit)
    with pytest.raises(NotFoundError):
        await RoleNavigationService(AsyncMock()).update(
            _context("owner"), OrgRoleName.MEMBER, RoleNavigationUpdate(hidden_items=[])
        )
    audit.assert_not_awaited()


@pytest.mark.parametrize("stored", [None, {"viewer": ["skills"]}])
@pytest.mark.security
async def test_the_repository_locks_and_refreshes_the_tenant_before_merging_one_role(
    stored: dict[str, list[str]] | None,
) -> None:
    org = Organization(id=uuid4(), role_navigation=stored)
    result = MagicMock()
    result.scalar_one_or_none.return_value = org
    db = AsyncMock()
    db.execute.return_value = result
    saved = await organization_repo.set_role_navigation(
        db, organization_id=org.id, role="member", hidden_items=["chat"]
    )
    assert saved is org
    assert org.role_navigation == {**(stored or {}), "member": ["chat"]}
    statement = db.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    assert "WHERE organizations.id =" in str(compiled)
    assert "FOR UPDATE" in str(compiled)
    assert compiled.params == {"id_1": org.id}
    assert statement.get_execution_options()["populate_existing"] is True
    db.flush.assert_awaited_once()
    db.refresh.assert_awaited_once_with(org)
    db.commit.assert_not_awaited()


@pytest.mark.security
async def test_the_repository_does_not_write_when_the_tenant_was_deleted() -> None:
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db = AsyncMock()
    db.execute.return_value = result
    assert (
        await organization_repo.set_role_navigation(
            db, organization_id=uuid4(), role="member", hidden_items=[]
        )
        is None
    )
    db.flush.assert_not_awaited()


def test_the_migration_adds_a_nullable_column_and_has_a_matching_downgrade() -> None:
    path = Path(__file__).resolve().parents[1] / "alembic/versions/0330_role_navigation.py"
    spec = importlib.util.spec_from_file_location("role_navigation_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        migration.upgrade()
        migration.downgrade()
    sql = output.getvalue()
    assert "ALTER TABLE organizations ADD COLUMN role_navigation JSONB" in sql
    assert "ALTER TABLE organizations DROP COLUMN role_navigation" in sql
    assert "NOT NULL" not in sql
    assert migration.down_revision == "0329_user_appearance"
