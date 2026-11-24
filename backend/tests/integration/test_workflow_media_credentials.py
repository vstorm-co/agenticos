"""Real row locks fence rotation, and refresh a stale credential identity before use."""

from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.secret_kinds import ApiKeySecret
from app.repositories import organization_secret as secret_repo
from app.services.organization_secret import OrganizationSecretService
from tests.integration.test_secret_tenant_isolation import _ctx, _org

pytestmark = [pytest.mark.security, pytest.mark.anyio]


async def seed(engine: AsyncEngine):
    async with AsyncSession(engine, expire_on_commit=False) as db:
        org, user = await _org(db, name="Media credential")
        ctx = _ctx(org, user)
        row = await OrganizationSecretService(db).create(
            ctx,
            name="Media test key",
            purpose="google",
            value=ApiKeySecret(api_key="synthetic-original-media-key"),
        )
        await db.commit()
        return ctx, row.id, row.authorization_generation


async def test_locked_media_read_refreshes_a_cached_generation_after_rotation(
    engine: AsyncEngine,
) -> None:
    ctx, secret_id, generation = await seed(engine)
    async with AsyncSession(engine, expire_on_commit=False) as reader:
        cached = await secret_repo.get(reader, secret_id, organization_id=ctx.organization_id)
        assert cached is not None and cached.authorization_generation == generation
        async with AsyncSession(engine) as writer:
            await OrganizationSecretService(writer).update(
                ctx,
                secret_id,
                value=ApiKeySecret(api_key="synthetic-rotated-media-key"),
            )
            await writer.commit()
        assert cached.authorization_generation == generation
        with (
            patch("app.services.organization_secret.unseal_kind") as unseal,
            pytest.raises(AuthorizationError, match="credential changed"),
        ):
            await OrganizationSecretService(reader).workflow_media_key(
                ctx,
                secret_id,
                provider="google",
                expected_generation=generation,
            )
        assert cached.authorization_generation != generation
        unseal.assert_not_called()


async def test_media_effect_transaction_fences_rotation_until_it_finishes(
    engine: AsyncEngine,
) -> None:
    ctx, secret_id, generation = await seed(engine)
    async with AsyncSession(engine) as reader:
        value = await OrganizationSecretService(reader).workflow_media_key(
            ctx,
            secret_id,
            provider="google",
            expected_generation=generation,
        )
        assert value.api_key.get_secret_value() == "synthetic-original-media-key"
        async with AsyncSession(engine) as writer:
            await writer.execute(text("SET LOCAL lock_timeout = '100ms'"))
            with pytest.raises(DBAPIError) as blocked:
                await OrganizationSecretService(writer).update(
                    ctx,
                    secret_id,
                    value=ApiKeySecret(api_key="synthetic-rotated-media-key"),
                )
            assert getattr(blocked.value.orig, "sqlstate", None) == "55P03"
            await writer.rollback()
        await reader.commit()
    async with AsyncSession(engine) as writer:
        rotated = await OrganizationSecretService(writer).update(
            ctx,
            secret_id,
            value=ApiKeySecret(api_key="synthetic-rotated-media-key"),
        )
        assert rotated.authorization_generation != generation
        await writer.commit()


async def test_foreign_tenant_and_missing_media_keys_never_reach_decryption(
    engine: AsyncEngine,
) -> None:
    _ctx_value, secret_id, generation = await seed(engine)
    async with AsyncSession(engine) as db:
        elsewhere, owner = await _org(db, name="Elsewhere")
        with patch("app.services.organization_secret.unseal_kind") as unseal:
            for identifier in (secret_id, uuid4()):
                with pytest.raises(NotFoundError, match="Secret not found"):
                    await OrganizationSecretService(db).workflow_media_key(
                        _ctx(elsewhere, owner),
                        identifier,
                        provider="google",
                        expected_generation=generation,
                    )
        unseal.assert_not_called()
