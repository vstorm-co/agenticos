"""Media spends only the run principal's current, provider-specific organization key."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.core.secret_kinds import ApiKeySecret, seal_secret
from app.core.vault import VaultScope
from app.db.models.organization_secret import OrganizationSecret
from app.services.organization_secret import OrganizationSecretService

pytestmark = [pytest.mark.security, pytest.mark.anyio]


def credential() -> tuple[AuthContext, OrganizationSecret]:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.BUILDER)
    sealed = seal_secret(
        ApiKeySecret(api_key="synthetic-media-key-never-log"),
        scope=VaultScope.organization(ctx.organization_id),
    )
    row = OrganizationSecret(
        id=uuid4(),
        organization_id=ctx.organization_id,
        name="Synthetic media",
        kind="api_key",
        purpose="google",
        usage_scope="organization",
        visibility="private",
        owner_user_id=ctx.user_id,
        created_by_user_id=ctx.user_id,
        authorization_generation=uuid4(),
        sealed_secret=sealed.ciphertext,
        hint=sealed.hint,
        key_version=sealed.key_version,
    )
    return ctx, row


async def test_publication_checks_metadata_without_opening_the_envelope() -> None:
    ctx, row = credential()
    with (
        patch(
            "app.services.organization_secret.organization_secret_repo.get",
            new=AsyncMock(return_value=row),
        ) as get,
        patch(
            "app.services.organization_secret.resolve_access", new=AsyncMock(return_value=True)
        ) as access,
        patch("app.services.organization_secret.unseal_kind") as unseal,
    ):
        assert (
            await OrganizationSecretService(MagicMock()).workflow_media_secret(
                ctx, row.id, provider="google"
            )
            is row
        )
    assert get.await_args.kwargs == {"organization_id": ctx.organization_id}
    assert access.await_args.args[1:3] == (ctx, row)
    unseal.assert_not_called()


async def test_runtime_locks_then_opens_only_the_pinned_generation() -> None:
    ctx, row = credential()
    with (
        patch(
            "app.services.organization_secret.organization_secret_repo.get_locked",
            new=AsyncMock(return_value=row),
        ) as locked,
        patch(
            "app.services.organization_secret.organization_secret_repo.get", new=AsyncMock()
        ) as unlocked,
        patch("app.services.organization_secret.resolve_access", new=AsyncMock(return_value=True)),
    ):
        value = await OrganizationSecretService(MagicMock()).workflow_media_key(
            ctx,
            row.id,
            provider="google",
            expected_generation=row.authorization_generation,
        )
    assert value.api_key.get_secret_value() == "synthetic-media-key-never-log"
    assert "synthetic-media-key-never-log" not in repr(value)
    assert locked.await_args.args[1] == row.id
    assert locked.await_args.kwargs == {"organization_id": ctx.organization_id}
    unlocked.assert_not_called()


@pytest.mark.parametrize(
    "change",
    [
        {"purpose": "openai"},
        {"usage_scope": "personal"},
        {"kind": "aws_credentials"},
    ],
)
async def test_readable_but_incompatible_keys_never_open(change: dict[str, str]) -> None:
    ctx, row = credential()
    for name, value in change.items():
        setattr(row, name, value)
    with (
        patch(
            "app.services.organization_secret.organization_secret_repo.get_locked",
            new=AsyncMock(return_value=row),
        ),
        patch("app.services.organization_secret.resolve_access", new=AsyncMock(return_value=True)),
        patch("app.services.organization_secret.unseal_kind") as unseal,
        pytest.raises(BadRequestError, match="organization API key"),
    ):
        await OrganizationSecretService(MagicMock()).workflow_media_key(
            ctx,
            row.id,
            provider="google",
            expected_generation=row.authorization_generation,
        )
    unseal.assert_not_called()


@pytest.mark.parametrize("missing", [True, False])
async def test_missing_foreign_tenant_or_revoked_keys_are_indistinguishable(missing: bool) -> None:
    ctx, row = credential()
    with (
        patch(
            "app.services.organization_secret.organization_secret_repo.get_locked",
            new=AsyncMock(return_value=None if missing else row),
        ) as get,
        patch(
            "app.services.organization_secret.resolve_access", new=AsyncMock(return_value=False)
        ) as access,
        patch("app.services.organization_secret.unseal_kind") as unseal,
        pytest.raises(NotFoundError, match="Secret not found"),
    ):
        await OrganizationSecretService(MagicMock()).workflow_media_key(
            ctx,
            row.id,
            provider="google",
            expected_generation=row.authorization_generation,
        )
    assert get.await_args.kwargs == {"organization_id": ctx.organization_id}
    assert access.await_count == (0 if missing else 1)
    unseal.assert_not_called()


async def test_rotation_does_not_silently_resume_with_a_different_paid_key() -> None:
    ctx, row = credential()
    with (
        patch(
            "app.services.organization_secret.organization_secret_repo.get_locked",
            new=AsyncMock(return_value=row),
        ),
        patch("app.services.organization_secret.resolve_access", new=AsyncMock(return_value=True)),
        patch("app.services.organization_secret.unseal_kind") as unseal,
        pytest.raises(AuthorizationError, match="credential changed"),
    ):
        await OrganizationSecretService(MagicMock()).workflow_media_key(
            ctx,
            row.id,
            provider="google",
            expected_generation=uuid4(),
        )
    unseal.assert_not_called()
