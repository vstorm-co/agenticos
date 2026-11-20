"""A deleted connection cannot be resurrected by a device authorization started earlier."""

from typing import TypedDict
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.organization import OrganizationMember
from app.db.models.personal_model_generation import PersonalModelGeneration
from app.repositories import personal_model_key as repo
from app.services.personal_model_key import PersonalModelKeyService
from tests.integration.test_personal_model_keys import key_request, setup

pytestmark = [pytest.mark.anyio, pytest.mark.security]


class _Connection(TypedDict):
    organization_id: UUID
    user_id: UUID
    provider: str
    endpoint: str


async def test_create_delete_cycle_invalidates_a_sign_in_started_without_a_connection(
    db: AsyncSession,
) -> None:
    owner, _, profile = await setup(db)
    assert owner.user_id is not None
    before = await repo.bump_generation(
        db,
        organization_id=owner.organization_id,
        user_id=owner.user_id,
        provider=profile.provider,
        endpoint=profile.base_url or "",
    )
    service = PersonalModelKeyService(db)
    with patch.object(service, "_profile", AsyncMock(return_value=profile)):
        await service.save(owner, uuid4(), key_request(profile, "private-model-key"))
        row = (await service.mine(owner))[0]
        await service.delete(owner, row.id)
    assert await service.mine(owner) == []
    assert not await repo.claim_generation(
        db,
        organization_id=owner.organization_id,
        user_id=owner.user_id,
        provider=profile.provider,
        endpoint=profile.base_url or "",
        expected=before,
    )
    assert (
        await repo.get_by_id(
            db, organization_id=owner.organization_id, user_id=owner.user_id, key_id=row.id
        )
        is None
    )


async def test_newer_sign_in_consumes_one_owner_endpoint_revision(db: AsyncSession) -> None:
    owner, other, _ = await setup(db)
    assert owner.user_id is not None and other.user_id is not None
    args: _Connection = {
        "organization_id": owner.organization_id,
        "user_id": owner.user_id,
        "provider": "github_copilot",
        "endpoint": "",
    }
    first = await repo.bump_generation(db, **args)
    second = await repo.bump_generation(db, **args)
    assert not await repo.claim_generation(db, **args, expected=first)
    assert not await repo.claim_generation(
        db,
        organization_id=owner.organization_id,
        user_id=other.user_id,
        provider="github_copilot",
        endpoint="",
        expected=second,
    )
    assert not await repo.claim_generation(
        db,
        organization_id=uuid4(),
        user_id=owner.user_id,
        provider="github_copilot",
        endpoint="",
        expected=second,
    )
    assert not await repo.claim_generation(
        db,
        organization_id=owner.organization_id,
        user_id=owner.user_id,
        provider="github_copilot",
        endpoint="https://elsewhere.example",
        expected=second,
    )
    assert await repo.claim_generation(db, **args, expected=second)
    assert not await repo.claim_generation(db, **args, expected=second)


async def test_generation_metadata_is_removed_with_membership(db: AsyncSession) -> None:
    owner, _, _ = await setup(db)
    assert owner.user_id is not None
    generation = await repo.bump_generation(
        db,
        organization_id=owner.organization_id,
        user_id=owner.user_id,
        provider="github_copilot",
        endpoint="",
    )
    row = await db.scalar(
        select(PersonalModelGeneration).where(PersonalModelGeneration.user_id == owner.user_id)
    )
    assert row is not None and "github_copilot" in repr(row)
    await db.execute(
        delete(OrganizationMember).where(
            OrganizationMember.organization_id == owner.organization_id,
            OrganizationMember.user_id == owner.user_id,
        )
    )
    await db.flush()
    assert (
        await db.scalar(
            select(PersonalModelGeneration).where(PersonalModelGeneration.user_id == owner.user_id)
        )
        is None
    )
    assert not await repo.claim_generation(
        db,
        organization_id=owner.organization_id,
        user_id=owner.user_id,
        provider="github_copilot",
        endpoint="",
        expected=generation,
    )


async def test_resolved_copilot_model_cannot_reuse_a_disconnected_personal_token(
    db: AsyncSession,
) -> None:
    from collections.abc import AsyncGenerator
    from contextlib import asynccontextmanager

    from app.core.exceptions import AuthorizationError
    from app.services import personal_copilot

    owner, _, profile = await setup(db)
    profile.provider, profile.model, profile.base_url, profile.api = (
        "github_copilot",
        "plan-model",
        None,
        None,
    )
    service = PersonalModelKeyService(db)

    @asynccontextmanager
    async def same_transaction() -> AsyncGenerator[AsyncSession]:
        yield db

    with (
        patch.object(service, "_profile", AsyncMock(return_value=profile)),
        patch.object(personal_copilot, "get_db_context", same_transaction),
    ):
        await service.save(owner, uuid4(), key_request(profile, "copilot-owner-token"))
        resolved = await service.resolve(owner, profile)
        assert resolved.credential.token_source is not None
        assert await resolved.credential.token_source() == "copilot-owner-token"
        await service.delete(owner, (await service.mine(owner))[0].id)
        with pytest.raises(AuthorizationError, match="disconnected"):
            await resolved.credential.token_source()
