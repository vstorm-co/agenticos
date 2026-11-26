"""Real vault envelopes, owner/tenant filters, upserts and membership cascades."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext
from app.core.secret_kinds import ApiKeySecret, SecretKind, unseal_secret
from app.core.vault import VaultScope
from app.db.models.credential import ModelProfile
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import personal_model_key as key_repo
from app.schemas.personal_model_key import PersonalModelDestination, PersonalModelKeyCreate
from app.services.personal_data import PersonalDataService
from app.services.personal_model_key import PersonalModelKeyService

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def setup(db: AsyncSession) -> tuple[AuthContext, AuthContext, ModelProfile]:
    first = User(email=f"{uuid4()}@example.com", hashed_password="x", is_active=True)
    second = User(email=f"{uuid4()}@example.com", hashed_password="x", is_active=True)
    db.add_all([first, second])
    await db.flush()
    org = Organization(name="Models", slug=uuid4().hex, created_by_user_id=first.id)
    db.add(org)
    await db.flush()
    db.add_all(
        [
            OrganizationMember(organization_id=org.id, user_id=user.id, role="member")
            for user in [first, second]
        ]
    )
    held = ModelProfile(
        organization_id=org.id,
        label="Approved",
        provider="openai",
        model="gpt-5",
        base_url="https://gateway.example.com/v1",
        params={},
        fallback_profile_ids=[],
        api="chat",
    )
    db.add(held)
    await db.flush()
    return (
        AuthContext(user_id=first.id, organization_id=org.id, role="member"),
        AuthContext(user_id=second.id, organization_id=org.id, role="member"),
        held,
    )


def key_request(held: ModelProfile, key: str) -> PersonalModelKeyCreate:
    return PersonalModelKeyCreate(
        api_key=SecretStr(key),
        expected_destination=PersonalModelDestination(
            profile_id=held.id, provider=held.provider, endpoint=held.base_url, model=held.model
        ),
    )


async def test_two_members_use_the_same_model_with_isolated_rotatable_keys(
    db: AsyncSession,
) -> None:
    first, second, held = await setup(db)
    service = PersonalModelKeyService(db)
    with patch.object(service, "_profile", AsyncMock(return_value=held)):
        await service.save(first, uuid4(), key_request(held, "first-private-key"))
        await service.save(second, uuid4(), key_request(held, "second-private-key"))
        status = await service.status(first, uuid4())
        assert status.connected
        for ctx, value in [(first, "first-private-key"), (second, "second-private-key")]:
            resolved = await service.resolve(ctx, held)
            assert isinstance(resolved.credential.secret, ApiKeySecret)
            assert resolved.credential.secret.api_key.get_secret_value() == value
            assert resolved.model == held.model and resolved.credential.base_url == held.base_url
        previous_connection = await service.resolve(first, held)
        await service.save(first, uuid4(), key_request(held, "first-replacement"))
        replacement_connection = await service.resolve(first, held)
        assert (
            previous_connection.credential.credential_id
            == replacement_connection.credential.credential_id
        )
        assert previous_connection.credential.routing["credential_updated_at"] is None
        assert replacement_connection.credential.routing["credential_updated_at"] is not None
        assert previous_connection.credential.routing != replacement_connection.credential.routing

        first_keys = await service.mine(first)
        assert len(first_keys) == 1
        second_keys = await service.mine(second)
        assert len(second_keys) == 1
        for ctx, value in [(first, "first-replacement"), (second, "second-private-key")]:
            resolved = await service.resolve(ctx, held)
            assert isinstance(resolved.credential.secret, ApiKeySecret)
            assert resolved.credential.secret.api_key.get_secret_value() == value

    own = (await service.mine(first))[0]
    with pytest.raises(NotFoundError):
        await service.delete(second, own.id)
    await service.delete(first, own.id)
    with pytest.raises(AuthorizationError, match="own model API key"):
        await service.resolve(first, held)
    second_keys = await service.mine(second)
    assert len(second_keys) == 1


async def test_key_envelopes_and_metadata_never_cross_owner_or_tenant(db: AsyncSession) -> None:
    first, second, held = await setup(db)
    assert first.user_id is not None and second.user_id is not None
    service = PersonalModelKeyService(db)
    with patch.object(service, "_profile", AsyncMock(return_value=held)):
        await service.save(first, uuid4(), key_request(held, "vault-personal-private"))
    row = await key_repo.get(
        db,
        organization_id=first.organization_id,
        user_id=first.user_id,
        provider=held.provider,
        endpoint=held.base_url or "",
    )
    assert row is not None
    assert (
        "vault-personal-private" not in repr(row)
        and "vault-personal-private" not in row.sealed_secret
    )
    for scope in [VaultScope.user(second.user_id), VaultScope.organization(first.organization_id)]:
        with pytest.raises(BadRequestError):
            unseal_secret(
                row.sealed_secret, kind=SecretKind.API_KEY, scope=scope, key_version=row.key_version
            )
    removed = await key_repo.get(
        db,
        organization_id=uuid4(),
        user_id=first.user_id,
        provider=held.provider,
        endpoint=held.base_url or "",
    )
    assert removed is None
    metadata = (await service.mine(first))[0].model_dump_json()
    assert "sealed_secret" not in metadata and "vault-personal-private" not in metadata
    exported = await PersonalDataService(db).export(first.user_id, actor_user_id=first.user_id)
    assert len(exported.personal_model_keys) == 1
    assert len(exported.personal_model_generations) == 1
    assert set(exported.personal_model_generations[0].model_dump()) == {
        "organization_id",
        "provider",
        "endpoint",
        "created_at",
        "updated_at",
    }
    assert "vault-personal-private" not in exported.model_dump_json()
    assert "sealed_secret" not in exported.personal_model_keys[0].model_dump()

    held.base_url = "https://different.example.com/v1"
    with pytest.raises(AuthorizationError):
        await service.resolve(first, held)


async def test_membership_is_required_by_the_database_and_removal_deletes_the_key(
    db: AsyncSession,
) -> None:
    from sqlalchemy import delete

    first, _, held = await setup(db)
    assert first.user_id is not None
    service = PersonalModelKeyService(db)
    with patch.object(service, "_profile", AsyncMock(return_value=held)):
        await service.save(first, uuid4(), key_request(held, "revoked-on-leaving"))
    await db.execute(
        delete(OrganizationMember).where(
            OrganizationMember.organization_id == first.organization_id,
            OrganizationMember.user_id == first.user_id,
        )
    )
    await db.flush()
    remaining_keys = await service.mine(first)
    assert remaining_keys == []
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await key_repo.save(
                db,
                organization_id=first.organization_id,
                user_id=first.user_id,
                provider=held.provider,
                endpoint=held.base_url or "",
                sealed_secret="x",
                key_version=1,
            )


async def test_published_credential_mode_metadata_ignores_the_draft(db: AsyncSession) -> None:
    from app.agents.spec import AgentSpec
    from app.db.models.agent import Agent, AgentVersion
    from app.repositories import agent_repo

    ctx, _, _ = await setup(db)
    agent = Agent(
        organization_id=ctx.organization_id,
        owner_user_id=ctx.user_id,
        name="Shared",
        slug=uuid4().hex,
        draft_spec=AgentSpec(name="Draft").model_dump(mode="json"),
    )
    db.add(agent)
    await db.flush()
    version = AgentVersion(
        agent_id=agent.id,
        organization_id=ctx.organization_id,
        version=1,
        spec=AgentSpec(name="Published", model_credential_mode="personal").model_dump(mode="json"),
    )
    db.add(version)
    await db.flush()
    no_versions = await agent_repo.published_personal_model_keys(db, version_ids=[])
    assert no_versions == set()
    personal_versions = await agent_repo.published_personal_model_keys(db, version_ids=[version.id])
    assert personal_versions == {version.id}


async def test_deleting_a_missing_or_foreign_personal_key_cannot_remove_another_members_key(
    db: AsyncSession,
) -> None:
    first, second, held = await setup(db)
    service = PersonalModelKeyService(db)
    with patch.object(service, "_profile", AsyncMock(return_value=held)):
        await service.save(first, uuid4(), key_request(held, "private-test-key"))
        row = await key_repo.get(
            db,
            organization_id=first.organization_id,
            user_id=first.user_id,
            provider=held.provider,
            endpoint=held.base_url or "",
        )
        assert row is not None
        foreign_deleted = await key_repo.delete(
            db,
            organization_id=second.organization_id,
            user_id=second.user_id,
            key_id=row.id,
        )
        assert not foreign_deleted
        missing_deleted = await key_repo.delete(
            db,
            organization_id=first.organization_id,
            user_id=first.user_id,
            key_id=uuid4(),
        )
        assert not missing_deleted
        status = await service.status(first, uuid4())
        assert status.connected
