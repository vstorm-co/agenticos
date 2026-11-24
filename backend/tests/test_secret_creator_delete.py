"""Who may delete an organization API key (#264).

An organization-visible key has no owner, and a Builder's `secrets:edit` reaches
only rows they own - so the Builder who created one saw it in the list and was
told "not found" on delete. The creator is the one extra person allowed to
delete it; nobody else gains anything.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.core.secret_kinds import ApiKeySecret
from app.services.organization_secret import OrganizationSecretService
from tests.test_secrets import _db, _row

pytestmark = pytest.mark.security


def _as(role: OrgRoleName, org_id: uuid.UUID) -> AuthContext:
    return AuthContext(user_id=uuid.uuid4(), organization_id=org_id, role=role)


def _org_key(ctx: AuthContext, *, created_by: uuid.UUID | None, visibility: str = "org"):
    row = _row(ctx, ApiKeySecret(api_key="wx-live-4242"))
    row.usage_scope = "organization"
    row.visibility = visibility
    row.owner_user_id = None if visibility == "org" else uuid.uuid4()
    row.created_by_user_id = created_by
    return row


async def _delete(ctx: AuthContext, row) -> AsyncMock:
    with (
        patch(
            "app.services.organization_secret.organization_secret_repo.get",
            new=AsyncMock(return_value=row),
        ),
        patch(
            "app.services.organization_secret.organization_secret_repo.delete",
            new=AsyncMock(return_value=True),
        ) as delete,
        patch(
            "app.services.access.resource_grant_repo.get_level", new=AsyncMock(return_value=None)
        ),
        patch("app.services.organization_secret.record_audit", new=AsyncMock()),
    ):
        await OrganizationSecretService(_db()).delete(ctx, row.id)
    return delete


@pytest.mark.anyio
async def test_a_builders_new_organization_key_records_its_creator() -> None:
    ctx = _as(OrgRoleName.BUILDER, uuid.uuid4())
    with (
        patch(
            "app.services.organization_secret.organization_secret_repo.create",
            new=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
        ) as create,
        patch("app.services.organization_secret.record_audit", new=AsyncMock()),
    ):
        await OrganizationSecretService(_db()).create(
            ctx, name="Weather API", value=ApiKeySecret(api_key="wx-live-abcd4242")
        )

    assert create.call_args.kwargs["created_by_user_id"] == ctx.user_id
    assert create.call_args.kwargs["owner_user_id"] is None


@pytest.mark.anyio
async def test_a_builder_can_delete_the_organization_key_they_created() -> None:
    ctx = _as(OrgRoleName.BUILDER, uuid.uuid4())
    row = _org_key(ctx, created_by=ctx.user_id)

    delete = await _delete(ctx, row)

    assert delete.await_count == 1


@pytest.mark.anyio
async def test_a_different_builder_is_refused_with_the_missing_permission_named() -> None:
    org_id = uuid.uuid4()
    creator = _as(OrgRoleName.BUILDER, org_id)
    row = _org_key(creator, created_by=creator.user_id)

    with pytest.raises(AuthorizationError) as refused:
        await _delete(_as(OrgRoleName.BUILDER, org_id), row)

    assert refused.value.status_code == 403
    assert "secrets:edit" in refused.value.message


@pytest.mark.anyio
async def test_a_key_with_no_recorded_creator_is_not_claimed_by_anyone() -> None:
    """Old rows are not backfilled, so a null creator must match nobody."""
    ctx = _as(OrgRoleName.BUILDER, uuid.uuid4())
    row = _org_key(ctx, created_by=None)

    with pytest.raises(AuthorizationError):
        await _delete(ctx, row)


@pytest.mark.anyio
async def test_a_key_the_caller_cannot_see_is_still_not_found() -> None:
    org_id = uuid.uuid4()
    creator = _as(OrgRoleName.BUILDER, org_id)
    row = _org_key(creator, created_by=creator.user_id, visibility="private")

    with pytest.raises(NotFoundError):
        await _delete(_as(OrgRoleName.BUILDER, org_id), row)


@pytest.mark.anyio
async def test_an_owner_still_deletes_a_key_somebody_else_created() -> None:
    org_id = uuid.uuid4()
    creator = _as(OrgRoleName.BUILDER, org_id)
    row = _org_key(creator, created_by=creator.user_id)

    delete = await _delete(_as(OrgRoleName.OWNER, org_id), row)

    assert delete.await_count == 1
