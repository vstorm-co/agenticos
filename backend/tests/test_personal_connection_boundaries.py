"""Credential drift is refused before a personal key is opened or a profile is written."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import AuthorizationError, BadRequestError
from app.core.secret_kinds import ApiKeySecret, SecretKind, unseal_secret
from app.core.vault import VaultScope
from app.db.models.resource_grant import Visibility
from app.schemas.model_profile import ModelProfileUpdate
from app.services.access import SECRET
from app.services.model_profile import ModelProfileService
from app.services.organization_secret import OrganizationSecretService, SecretSharingGuard
from app.services.sharing import ShareChange
from tests.test_personal_model_connections import _ctx, _db, _profile, _secret

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def test_an_api_key_profile_view_does_not_query_native_subscription_state() -> None:
    ctx = _ctx()
    profile = _profile(ctx, _secret(ctx))
    with patch.object(ModelProfileService, "_native_connected", new=AsyncMock()) as native:
        view = await ModelProfileService(_db()).profile_view(ctx, profile)

    assert view.id == profile.id
    assert view.provider == "openai"
    native.assert_not_awaited()


@pytest.mark.parametrize("provider,kind", [("openai", "openai_codex"), ("google", "api_key")])
async def test_legacy_personal_key_metadata_cannot_be_lent_to_a_model(
    provider: str, kind: str
) -> None:
    ctx = _ctx()
    row = _secret(ctx, provider=provider)
    row.kind = kind
    with (
        patch(
            "app.services.model_profile.organization_secret_repo.get",
            AsyncMock(return_value=row),
        ),
        patch("app.services.model_profile.unseal_secret") as unseal,
        pytest.raises(BadRequestError, match="personal Anthropic or OpenAI API-key"),
    ):
        await ModelProfileService(_db())._check_key(ctx, row.id, provider=provider)

    unseal.assert_not_called()


async def test_a_personal_gateway_profile_cannot_drop_its_personal_key() -> None:
    ctx = _ctx()
    profile = _profile(ctx, _secret(ctx))
    profile.base_url = "https://gateway.example.test/v1"
    with (
        patch(
            "app.services.model_profile.credential_repo.get_profile",
            AsyncMock(return_value=profile),
        ),
        patch("app.services.model_profile.credential_repo.update_profile", AsyncMock()) as update,
        patch("app.services.model_profile.record_audit", AsyncMock()) as audit,
        pytest.raises(BadRequestError, match="personal API-key connections"),
    ):
        await ModelProfileService(_db()).update_profile(
            ctx, profile.id, ModelProfileUpdate(secret_id=None)
        )

    update.assert_not_awaited()
    audit.assert_not_awaited()
    assert profile.secret_id is not None


async def test_a_personal_profile_rejects_another_owner_even_if_the_access_check_misclassifies_it() -> (
    None
):
    ctx = _ctx()
    profile = _profile(ctx, _secret(ctx))
    foreign = _secret(ctx)
    foreign.owner_user_id = uuid4()
    with (
        patch(
            "app.services.model_profile.credential_repo.get_profile",
            AsyncMock(return_value=profile),
        ),
        patch(
            "app.services.model_profile.organization_secret_repo.get",
            AsyncMock(return_value=foreign),
        ),
        # Fault injection: the final owner boundary must still refuse a key
        # if the lower-level access collaborator returns an inconsistent grant.
        patch("app.services.model_profile.resolve_access", AsyncMock(return_value=True)),
        patch("app.services.model_profile.credential_repo.update_profile", AsyncMock()) as update,
        patch("app.services.model_profile.record_audit", AsyncMock()) as audit,
        patch("app.services.model_profile.unseal_secret") as unseal,
        pytest.raises(BadRequestError, match="your own personal connections"),
    ):
        await ModelProfileService(_db()).update_profile(
            ctx, profile.id, ModelProfileUpdate(secret_id=foreign.id)
        )

    update.assert_not_awaited()
    audit.assert_not_awaited()
    unseal.assert_not_called()


@pytest.mark.parametrize("personal", [False, True])
async def test_a_changed_stored_secret_scope_is_refused_before_unseal(personal: bool) -> None:
    ctx = _ctx()
    row = _secret(ctx, personal=personal)
    profile = _profile(ctx, row)
    row.usage_scope = "organization" if personal else "personal"
    with (
        patch(
            "app.services.model_profile.organization_secret_repo.get",
            AsyncMock(return_value=row),
        ),
        patch("app.services.model_profile.unseal_secret") as unseal,
        pytest.raises(BadRequestError, match="connection scope changed"),
    ):
        await ModelProfileService(_db()).resolve_credential(ctx.organization_id, profile, ctx=ctx)

    unseal.assert_not_called()


async def test_a_changed_stored_secret_owner_is_refused_before_unseal() -> None:
    ctx = _ctx()
    row = _secret(ctx)
    profile = _profile(ctx, row)
    row.owner_user_id = uuid4()
    with (
        patch(
            "app.services.model_profile.organization_secret_repo.get",
            AsyncMock(return_value=row),
        ),
        patch("app.services.model_profile.unseal_secret") as unseal,
        pytest.raises(AuthorizationError, match="sign in as its owner"),
    ):
        await ModelProfileService(_db()).resolve_credential(ctx.organization_id, profile, ctx=ctx)

    unseal.assert_not_called()


async def test_the_owner_can_rotate_a_personal_api_key_without_changing_its_authority() -> None:
    ctx, db = _ctx(), _db()
    row = _secret(ctx)
    generation = row.authorization_generation = uuid4()
    replacement = ApiKeySecret(api_key="sk-rotated-personal-connection-test")

    async def persist(db, *, secret, update_data):
        for name, value in update_data.items():
            setattr(secret, name, value)
        return secret

    with (
        patch(
            "app.services.organization_secret.organization_secret_repo.get",
            AsyncMock(return_value=row),
        ),
        patch(
            "app.services.organization_secret.organization_secret_repo.update",
            AsyncMock(side_effect=persist),
        ) as update,
        patch("app.services.organization_secret.record_audit", AsyncMock()) as audit,
        patch("app.services.organization_secret.NotificationService", autospec=True),
    ):
        rotated = await OrganizationSecretService(db).update(ctx, row.id, value=replacement)

    assert rotated is row
    assert row.usage_scope == "personal"
    assert row.owner_user_id == ctx.user_id
    assert row.visibility == "private"
    assert row.purpose == "openai"
    assert row.authorization_generation != generation
    update.assert_awaited_once()
    opened = unseal_secret(
        row.sealed_secret,
        kind=SecretKind(row.kind),
        key_version=row.key_version,
        scope=VaultScope.organization(ctx.organization_id),
    )
    assert opened == replacement
    assert audit.await_args.kwargs["action"] == "secret.rotated"
    assert replacement.api_key.get_secret_value() not in str(audit.await_args.kwargs)


@pytest.mark.parametrize("personal", [False, True])
async def test_keeping_a_secret_private_needs_no_sharing_grant(personal: bool) -> None:
    ctx, db = _ctx(), _db()
    row = _secret(ctx, personal=personal)
    guard = SecretSharingGuard()

    assert await guard.before_visibility(db, ctx, row, Visibility.PRIVATE) is None
    assert (
        await guard.before_share(db, ctx, row, ShareChange(visibility=Visibility.PRIVATE)) is None
    )

    assert row.visibility == "private"
    assert row.owner_user_id == ctx.user_id
    db.execute.assert_not_awaited()


async def test_an_authorized_organization_secret_adoption_records_its_new_owner() -> None:
    ctx, db = _ctx(), _db()
    row = _secret(ctx, personal=False)
    row.owner_user_id = None
    with patch("app.services.organization_secret.record_audit", AsyncMock()) as audit:
        # SharingService establishes edit authority before invoking this guard.
        await SecretSharingGuard().adopt(db, ctx, row)

    assert row.owner_user_id == ctx.subject_id
    assert row.usage_scope == "organization"
    assert row.visibility == "private"
    audit.assert_awaited_once_with(
        db,
        actor_user_id=ctx.subject_id,
        organization_id=ctx.organization_id,
        action="resource.owner_claimed",
        target_type=SECRET.key,
        target_id=str(row.id),
        details={"owner_user_id": str(ctx.subject_id)},
    )
