"""Real schema and deletion boundaries for personal model connections."""

from dataclasses import replace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.core.secret_kinds import ApiKeySecret
from app.db.models.credential import ModelProfile
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.organization_secret import OrganizationSecret
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.repositories import organization_secret_repo
from app.schemas.model_profile import ModelProfileRead, ModelProfileUpdate
from app.services.model_profile import ModelProfileService
from app.services.organization_secret import OrganizationSecretService

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def _owner(db: AsyncSession) -> tuple[AuthContext, User]:
    owner = User(
        id=uuid4(), email=f"{uuid4().hex}@example.com", hashed_password="x", is_active=True
    )
    db.add(owner)
    await db.flush()
    organization = Organization(
        id=uuid4(),
        name="Personal model tests",
        slug=f"personal-{uuid4().hex}",
        created_by_user_id=owner.id,
    )
    db.add(organization)
    await db.flush()
    return AuthContext(
        user_id=owner.id, organization_id=organization.id, role=OrgRoleName.OWNER
    ), owner


async def _connection(
    db: AsyncSession, ctx: AuthContext, *, personal: bool = True
) -> OrganizationSecret:
    return await OrganizationSecretService(db).create(
        ctx,
        name=f"API {uuid4()}",
        purpose="openai",
        value=ApiKeySecret(api_key="sk-fake-integration-test"),
        visibility=Visibility.PRIVATE,
        usage_scope="personal" if personal else "organization",
    )


async def _model(db: AsyncSession, ctx: AuthContext, secret: OrganizationSecret) -> ModelProfile:
    with patch("app.services.model_profile.models_for", AsyncMock(return_value=([], "unlisted"))):
        return await ModelProfileService(db).create_profile(
            ctx,
            label=f"Model {uuid4()}",
            provider="openai",
            model="gpt-4.1",
            secret_id=secret.id,
        )


@pytest.mark.parametrize(
    ("usage_scope", "visibility", "has_owner"),
    [
        ("personal", "org", True),
        ("personal", "team", True),
        ("personal", "private", False),
        ("invalid", "org", True),
    ],
)
async def test_database_refuses_a_personal_connection_without_private_ownership(
    db: AsyncSession,
    usage_scope: str,
    visibility: str,
    has_owner: bool,
) -> None:
    ctx, _ = await _owner(db)
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(
                OrganizationSecret(
                    id=uuid4(),
                    organization_id=ctx.organization_id,
                    name=f"Invalid {uuid4()}",
                    kind="api_key",
                    purpose="openai",
                    sealed_secret="unused-test-envelope",
                    hint="test",
                    key_version=1,
                    owner_user_id=ctx.user_id if has_owner else None,
                    usage_scope=usage_scope,
                    visibility=visibility,
                )
            )
            await db.flush()


async def test_organization_listing_does_not_discover_personal_keys_even_with_all_visibility(
    db: AsyncSession,
) -> None:
    ctx, _ = await _owner(db)
    personal = await _connection(db, ctx)
    ordinary = await _connection(db, ctx, personal=False)
    other_org, _ = await _owner(db)
    await _connection(db, other_org)
    rows = await organization_secret_repo.list_secrets(
        db, organization_id=ctx.organization_id, see_all=True
    )
    assert {row.id for row in rows} == {ordinary.id}
    rows = await organization_secret_repo.list_secrets(
        db,
        organization_id=ctx.organization_id,
        see_all=True,
        personal_user_id=ctx.user_id,
    )
    assert {row.id for row in rows} == {personal.id, ordinary.id}
    rows = await organization_secret_repo.list_secrets(
        db,
        organization_id=other_org.organization_id,
        see_all=True,
        personal_user_id=ctx.user_id,
    )
    assert rows == []


async def test_disconnect_keeps_model_private_and_unusable_until_its_owner_reconnects(
    db: AsyncSession,
) -> None:
    ctx, _ = await _owner(db)
    secret = await _connection(db, ctx)
    profile = await _model(db, ctx, secret)
    profile_id = profile.id
    assert profile.personal_owner_user_id == ctx.user_id
    assert ModelProfileRead.model_validate(profile).usage_scope == "personal"

    await OrganizationSecretService(db).delete(ctx, secret.id)
    await db.refresh(profile)
    assert profile.secret_id is None
    assert profile.usage_scope == "personal"
    assert ModelProfileRead.model_validate(profile).missing_key
    service = ModelProfileService(db)
    assert await service.list_profiles(ctx) == [profile]
    assert await service.list_profiles(replace(ctx, user_id=uuid4(), is_app_admin=True)) == []
    with pytest.raises(NotFoundError):
        await service.update_profile(
            replace(ctx, user_id=uuid4()), profile.id, ModelProfileUpdate(label="Taken over")
        )
    with pytest.raises(BadRequestError, match="has no key"):
        await service.resolve(ctx, profile_id=profile.id)

    replacement = await _connection(db, ctx)
    reconnected = await service.update_profile(
        ctx, profile.id, ModelProfileUpdate(secret_id=replacement.id)
    )
    assert reconnected.id == profile_id
    assert reconnected.personal_owner_user_id == ctx.user_id
    assert not ModelProfileRead.model_validate(reconnected).missing_key
    assert (
        await service.resolve(ctx, profile_id=profile.id)
    ).credential.personal_owner_user_id == ctx.user_id


async def test_rekey_cannot_change_a_models_usage_scope(db: AsyncSession) -> None:
    ctx, _ = await _owner(db)
    personal_key = await _connection(db, ctx)
    organization_key = await _connection(db, ctx, personal=False)
    personal_profile = await _model(db, ctx, personal_key)
    organization_profile = await _model(db, ctx, organization_key)
    service = ModelProfileService(db)
    for profile, other_key in [
        (personal_profile, organization_key),
        (organization_profile, personal_key),
    ]:
        with pytest.raises(BadRequestError, match="separate model"):
            await service.update_profile(
                ctx, profile.id, ModelProfileUpdate(secret_id=other_key.id)
            )
    assert personal_profile.secret_id == personal_key.id
    assert organization_profile.secret_id == organization_key.id


async def test_deleting_an_account_removes_personal_keys_and_profiles_without_lending_them(
    db: AsyncSession,
) -> None:
    creator_ctx, creator = await _owner(db)
    owner = User(
        id=uuid4(), email=f"{uuid4().hex}@example.com", hashed_password="x", is_active=True
    )
    db.add(owner)
    await db.flush()
    db.add(
        OrganizationMember(
            organization_id=creator_ctx.organization_id,
            user_id=owner.id,
            role=OrgRoleName.OWNER.value,
        )
    )
    await db.flush()
    ctx = replace(creator_ctx, user_id=owner.id)
    personal = await _connection(db, ctx)
    ordinary = await _connection(db, ctx, personal=False)
    personal_profile = await _model(db, ctx, personal)
    ordinary_profile = await _model(db, ctx, ordinary)
    personal_id, profile_id = personal.id, personal_profile.id

    assert (
        await organization_secret_repo.promote_owned_private_to_org(db, owner_user_id=owner.id) == 1
    )
    await db.delete(owner)
    await db.flush()
    assert (
        await db.scalar(
            select(Organization.created_by_user_id).where(Organization.id == ctx.organization_id)
        )
        == creator.id
    )
    assert (
        await db.scalar(select(OrganizationSecret.id).where(OrganizationSecret.id == personal_id))
        is None
    )
    assert await db.scalar(select(ModelProfile.id).where(ModelProfile.id == profile_id)) is None
    await db.refresh(ordinary)
    await db.refresh(ordinary_profile)
    assert ordinary.visibility == "org"
    assert ordinary.usage_scope == "organization"
    assert ordinary.owner_user_id is None
    assert ordinary_profile.secret_id == ordinary.id
    assert ordinary_profile.usage_scope == "organization"
