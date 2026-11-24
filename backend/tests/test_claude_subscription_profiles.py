"""Native model profiles stay personal after disconnect and cannot acquire API keys."""

from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.claude_subscription import ClaudeSubscriptionModelClient
from app.agents.model_resolver import ResolvedCredential, build_model
from app.agents.spec import AgentSpec
from app.api.routes.v1.model_providers import list_provider_models
from app.core.claude_subscription import CLAUDE_SUBSCRIPTION_PROVIDER, ClaudeSubscriptionOwner
from app.core.exceptions import (
    AuthorizationError,
    BadRequestError,
    ConflictError,
    ExternalServiceError,
    NotFoundError,
)
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.core.secret_kinds import ApiKeySecret, NoSecret
from app.db.models.credential import ModelProfile
from app.schemas.claude_subscription import ClaudeSubscriptionRead
from app.schemas.model_profile import ModelProfileUpdate
from app.services.agent_registry import AgentRegistryService
from app.services.claude_subscription import ClaudeSubscriptionRuntime, ClaudeSubscriptionService
from app.services.model_profile import ModelProfileService, choosable_for_others, is_sign_in
from app.services.organization_secret import OrganizationSecretService

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def _ctx():
    return AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OWNER)


def _profile(ctx, **overrides):
    return ModelProfile(
        **{
            "id": uuid4(),
            "organization_id": ctx.organization_id,
            "label": "My Claude",
            "provider": CLAUDE_SUBSCRIPTION_PROVIDER,
            "model": "sonnet",
            "secret_id": None,
            "base_url": None,
            "api": None,
            "region": None,
            "params": {},
            "fallback_profile_ids": [],
            "runs_without_key": False,
            "created_at": datetime.now(UTC),
            "personal_owner_user_id": ctx.user_id,
            **overrides,
        }
    )


def _service():
    return ModelProfileService(MagicMock(spec=AsyncSession))


async def test_profile_creation_uses_only_connected_owner_without_api_secret_or_inference():
    ctx, runtime = _ctx(), AsyncMock(spec=ClaudeSubscriptionRuntime)
    runtime.status.return_value = ClaudeSubscriptionRead(
        available=True, connected=True, state="connected"
    )
    profile = _profile(ctx)
    with (
        patch(
            "app.services.model_profile.ClaudeSubscriptionService",
            return_value=ClaudeSubscriptionService(runtime),
        ),
        patch(
            "app.services.model_profile.credential_repo.get_profile_by_label",
            AsyncMock(return_value=None),
        ),
        patch(
            "app.services.model_profile.credential_repo.create_profile",
            AsyncMock(return_value=profile),
        ) as create,
        patch("app.services.model_profile.record_audit", AsyncMock()),
        patch("app.services.model_profile.OrganizationSecretService", autospec=True) as secrets,
        patch(
            "app.services.system_agents.SystemAgentService.adopt_model", new=AsyncMock()
        ) as adopt_model,
    ):
        result = await _service().create_profile(
            ctx,
            label="My Claude",
            provider=CLAUDE_SUBSCRIPTION_PROVIDER,
            model="sonnet",
            secret_id=None,
        )
    assert result is profile
    assert create.await_args.kwargs["personal_owner_user_id"] == ctx.user_id
    assert create.await_args.kwargs["secret_id"] is None
    assert create.await_args.kwargs["runs_without_key"] is False
    adopt_model.assert_awaited_once_with(organization_id=ctx.organization_id)
    runtime.status.assert_awaited_once_with(
        ClaudeSubscriptionOwner(ctx.organization_id, ctx.user_id)
    )
    runtime.infer.assert_not_awaited()
    secrets.assert_not_called()


async def test_disconnected_subscription_cannot_create_a_model():
    runtime = AsyncMock(spec=ClaudeSubscriptionRuntime)
    runtime.status.return_value = ClaudeSubscriptionRead(available=True)
    with (
        patch(
            "app.services.model_profile.ClaudeSubscriptionService",
            return_value=ClaudeSubscriptionService(runtime),
        ),
        patch("app.services.model_profile.credential_repo.create_profile", AsyncMock()) as create,
        pytest.raises(ConflictError),
    ):
        await _service().create_profile(
            _ctx(),
            label="My Claude",
            provider=CLAUDE_SUBSCRIPTION_PROVIDER,
            model="opus",
            secret_id=None,
        )
    create.assert_not_awaited()


@pytest.mark.parametrize(
    "overrides",
    [
        {"secret_id": uuid4()},
        {"base_url": "https://gateway.example/v1"},
        {"api": "chat"},
        {"region": "eu"},
        {"model": "claude-other"},
    ],
)
async def test_native_profile_cannot_be_repurposed_as_an_api_connection(overrides):
    with (
        patch("app.services.model_profile.ClaudeSubscriptionService") as connection,
        pytest.raises(BadRequestError),
    ):
        await _service().create_profile(
            _ctx(),
            **{
                "label": "My Claude",
                "provider": CLAUDE_SUBSCRIPTION_PROVIDER,
                "model": "sonnet",
                "secret_id": None,
                **overrides,
            },
        )
    connection.assert_not_called()


@pytest.mark.parametrize(
    "overrides",
    [
        {"user_id": uuid4()},
        {"user_id": None},
        {"api_key_id": uuid4()},
        {"key_scopes": frozenset()},
        {"key_scopes": frozenset({Perm.AGENTS_RUN})},
        {"subject_is_publisher_fallback": True},
        {"is_impersonated": True},
        {"is_workflow": True},
        {"channel_identity_id": uuid4()},
        {"fired_as_creator": "schedule"},
        {"fired_as_creator": "event"},
        {"routine_id": uuid4()},
        {"routine_source_policy_id": uuid4()},
        {"routine_activation_id": uuid4()},
        {"organization_id": uuid4()},
    ],
)
async def test_resolving_native_model_refuses_nonowners_and_unattended_origins(overrides):
    owner = _ctx()
    with (
        patch("app.services.model_profile.ClaudeSubscriptionService") as connection,
        pytest.raises(AuthorizationError),
    ):
        await _service().resolve_credential(
            owner.organization_id, _profile(owner), ctx=replace(owner, **overrides)
        )
    connection.assert_not_called()


async def test_native_owner_metadata_builds_without_reading_credentials():
    ctx = _ctx()
    with patch("app.services.model_profile.organization_secret_repo.get", AsyncMock()) as secrets:
        credential = await _service().resolve_credential(
            ctx.organization_id, _profile(ctx), ctx=ctx
        )
    assert isinstance(credential.secret, NoSecret)
    assert credential.personal_owner_user_id == ctx.user_id
    assert credential.claude_subscription_owner == ClaudeSubscriptionOwner(
        ctx.organization_id, ctx.user_id
    )
    assert isinstance(build_model(credential, "sonnet"), ClaudeSubscriptionModelClient)
    secrets.assert_not_awaited()


async def test_missing_immutable_owner_is_never_a_shared_subscription_profile():
    ctx = _ctx()
    profile = _profile(ctx, personal_owner_user_id=None)
    with pytest.raises(AuthorizationError):
        await _service().resolve_credential(ctx.organization_id, profile, ctx=ctx)
    with pytest.raises(AuthorizationError):
        await _service().resolve_credential(ctx.organization_id, _profile(ctx))
    assert is_sign_in(profile)
    assert not choosable_for_others(profile, {profile.id: profile})


async def test_disconnected_profiles_remain_private_and_disable_the_saved_picker_option():
    ctx = _ctx()
    own, foreign, malformed = (
        _profile(ctx),
        _profile(replace(ctx, user_id=uuid4())),
        _profile(ctx, personal_owner_user_id=None),
    )
    runtime = AsyncMock(spec=ClaudeSubscriptionRuntime)
    with (
        patch(
            "app.services.model_profile.credential_repo.list_profiles",
            AsyncMock(return_value=[own, foreign, malformed]),
        ),
        patch(
            "app.services.model_profile.ClaudeSubscriptionService",
            return_value=ClaudeSubscriptionService(runtime),
        ),
    ):
        for state, missing in [
            (ClaudeSubscriptionRead(available=True), True),
            (ClaudeSubscriptionRead(available=True, connected=True, state="connected"), False),
        ]:
            runtime.status.return_value = state
            [visible] = await _service().list_profile_views(ctx)
            assert visible.id == own.id
            assert visible.usage_scope == "personal"
            assert visible.missing_key is missing
            assert "native_connected" not in visible.model_dump()
            assert own.personal_owner_user_id == ctx.user_id
    assert runtime.status.await_count == 2
    runtime.infer.assert_not_awaited()


async def test_unavailable_runtime_disables_only_native_profile_views():
    ctx = _ctx()
    with patch("app.services.model_profile.ClaudeSubscriptionService") as connection:
        connection.return_value.status = AsyncMock(side_effect=ExternalServiceError())
        assert (await _service().profile_view(ctx, _profile(ctx))).missing_key
        with pytest.raises(NotFoundError):
            await _service().profile_view(replace(ctx, user_id=uuid4()), _profile(ctx))
        with pytest.raises(NotFoundError):
            await _service().profile_view(replace(ctx, organization_id=uuid4()), _profile(ctx))


async def test_disconnected_native_model_can_be_renamed_without_changing_ownership():
    ctx, service = _ctx(), _service()
    profile = _profile(ctx)
    with (
        patch(
            "app.services.model_profile.credential_repo.get_profile",
            AsyncMock(return_value=profile),
        ),
        patch(
            "app.services.model_profile.credential_repo.get_profile_by_label",
            AsyncMock(return_value=None),
        ),
        patch(
            "app.services.model_profile.credential_repo.update_profile",
            AsyncMock(return_value=profile),
        ) as update,
        patch("app.services.model_profile.record_audit", AsyncMock()),
        patch("app.services.model_profile.ClaudeSubscriptionService") as connection,
    ):
        await service.update_profile(ctx, profile.id, ModelProfileUpdate(label="Renamed Claude"))
        assert update.await_args.kwargs["update_data"] == {"label": "Renamed Claude"}
        with pytest.raises(BadRequestError):
            await service.update_profile(ctx, profile.id, ModelProfileUpdate(secret_id=uuid4()))
        with pytest.raises(NotFoundError):
            await service.update_profile(
                replace(ctx, user_id=uuid4()), profile.id, ModelProfileUpdate(label="Taken")
            )
    assert profile.personal_owner_user_id == ctx.user_id
    connection.assert_not_called()


async def test_subscription_model_choices_do_not_lookup_keys_or_consume_inference():
    secrets = AsyncMock(spec=OrganizationSecretService)
    result = await list_provider_models(CLAUDE_SUBSCRIPTION_PROVIDER, secrets, _ctx())
    assert [model.id for model in result.items] == ["sonnet", "opus", "haiku"]
    assert result.source == "curated"
    assert all(model.chat_capable and model.output_modalities == ["text"] for model in result.items)
    secrets.listing_key.assert_not_awaited()
    with pytest.raises(BadRequestError):
        await list_provider_models(CLAUDE_SUBSCRIPTION_PROVIDER, secrets, _ctx(), secret_id=uuid4())


@pytest.mark.parametrize("change", ["owner", "model", "key", "endpoint"])
def test_model_builder_refuses_forged_native_configuration(change):
    owner = ClaudeSubscriptionOwner(uuid4(), uuid4())
    credential = ResolvedCredential(
        provider=CLAUDE_SUBSCRIPTION_PROVIDER,
        secret=NoSecret(),
        personal_owner_user_id=owner.user_id,
        claude_subscription_owner=owner,
    )
    model = "sonnet"
    if change == "owner":
        credential = replace(credential, personal_owner_user_id=uuid4())
    elif change == "model":
        model = "unsupported"
    elif change == "key":
        credential = replace(credential, secret=ApiKeySecret(api_key="fake-api-key"))
    else:
        credential = replace(credential, base_url="https://gateway.example")
    with pytest.raises(BadRequestError):
        build_model(credential, model)


@pytest.mark.parametrize("authority", ["owner", "other-user", "api-key", "missing-owner"])
async def test_publish_accepts_only_the_native_models_direct_owner(authority):
    owner = _ctx()
    profile = _profile(
        owner, personal_owner_user_id=None if authority == "missing-owner" else owner.user_id
    )
    caller = (
        replace(owner, user_id=uuid4())
        if authority == "other-user"
        else replace(owner, api_key_id=uuid4())
        if authority == "api-key"
        else owner
    )
    registry = AgentRegistryService(MagicMock(spec=AsyncSession))
    with (
        patch(
            "app.services.agent_registry.credential_repo.get_profile",
            AsyncMock(return_value=profile),
        ),
        patch(
            "app.services.agent_registry.credential_repo.get_profiles_by_ids",
            AsyncMock(return_value={profile.id: profile}),
        ),
        patch(
            "app.services.agent_registry.organization_secret_repo.get_many",
            AsyncMock(return_value={}),
        ) as secret_read,
    ):
        profile_problems = await registry.model_profile_problems(caller, profile.id)
        sign_in_problems = await registry._sign_in_problems(
            caller, AgentSpec(name="Contacts", model_profile_id=profile.id)
        )
    assert bool(profile_problems) is (authority != "owner")
    assert bool(sign_in_problems.messages) is (authority != "owner")
    assert secret_read.await_args.args[1] == []
