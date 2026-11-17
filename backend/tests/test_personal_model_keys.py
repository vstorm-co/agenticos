"""Personal LLM credentials never change the model or borrow an organization key."""

from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import SecretStr

from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext
from app.core.secret_kinds import ApiKeySecret, seal_secret
from app.core.vault import VaultScope
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_run import RunSurface
from app.db.models.credential import ModelProfile
from app.db.models.personal_model_key import PersonalModelKey
from app.services.personal_model_key import PersonalModelKeyService, personal_profile_problem
from app.services.personal_model_policy import (
    personal_model_problems,
    require_organization_model,
    require_personal_model_run,
)
from app.services.personal_model_surfaces import require_organization_agent

pytestmark = pytest.mark.anyio


def context() -> AuthContext:
    return AuthContext(user_id=uuid4(), organization_id=uuid4(), role="member")


def profile() -> ModelProfile:
    return ModelProfile(
        id=uuid4(),
        organization_id=uuid4(),
        label="Approved",
        provider="openai",
        model="gpt-5",
        base_url="https://gateway.example.com/v1",
        params={},
        fallback_profile_ids=[],
        api="chat",
        region=None,
        context_length=128000,
    )


def spec(*, personal: bool = True) -> AgentSpec:
    return AgentSpec(
        name="Shared",
        model_profile_id=uuid4(),
        model_credential_mode="personal" if personal else "organization",
    )


def test_old_specs_keep_organization_keys_and_personal_specs_round_trip() -> None:
    old = AgentSpec.model_validate({"name": "Existing", "instructions": "Help"})
    assert old.model_credential_mode == "organization"
    personal = spec()
    assert AgentSpec.from_yaml(personal.to_yaml()) == personal


@pytest.mark.parametrize("surface", [one for one in RunSurface if one != RunSurface.WEB])
@pytest.mark.security
def test_personal_keys_refuse_every_non_web_surface(surface: RunSurface) -> None:
    with pytest.raises(BadRequestError, match="signed-in web chat"):
        require_personal_model_run(spec(), context(), surface)


@pytest.mark.parametrize("change", ["anonymous", "api", "key_scopes", "publisher", "channel"])
@pytest.mark.security
def test_personal_keys_require_the_actual_signed_in_user(change: str) -> None:
    ctx = context()
    ctx = {
        "anonymous": replace(ctx, user_id=None),
        "api": replace(ctx, api_key_id=uuid4()),
        "key_scopes": replace(ctx, key_scopes=frozenset()),
        "publisher": replace(ctx, subject_is_publisher_fallback=True),
        "channel": replace(ctx, channel_identity_id=uuid4()),
    }[change]
    with pytest.raises(BadRequestError):
        require_personal_model_run(spec(), ctx, RunSurface.WEB)


def test_personal_keys_fix_the_model_and_refuse_voice_or_local_replacement() -> None:
    chosen = spec()
    require_personal_model_run(chosen, context(), RunSurface.WEB, override=chosen.model_profile_id)
    for kwargs in (
        {"override": uuid4()},
        {"local_model": True},
        {"voice": True},
        {"public_origin": True},
    ):
        with pytest.raises(BadRequestError):
            require_personal_model_run(chosen, context(), RunSurface.WEB, **kwargs)
    require_personal_model_run(spec(personal=False), context(), RunSurface.SLACK)
    require_organization_model(spec(personal=False))
    assert personal_model_problems(spec(personal=False)) == []
    with pytest.raises(BadRequestError):
        require_organization_model(chosen)


async def test_delegation_and_separate_step_models_are_refused_before_a_run() -> None:
    chosen = spec().model_copy(update={"capabilities": [CapabilityBindingSpec(id="subagents")]})
    assert "delegation" in personal_model_problems(chosen)[0]
    with pytest.raises(BadRequestError, match="delegation"):
        require_personal_model_run(chosen, context(), RunSurface.WEB)
    chosen = spec().model_copy(
        update={
            "capabilities": [
                CapabilityBindingSpec(
                    id="web_browser", config={"step_model_profile_id": str(uuid4())}
                )
            ]
        }
    )
    assert "separate capability models" in personal_model_problems(chosen)[0]


def test_personal_profile_rejects_non_key_credentials_fallbacks_and_non_chat_models() -> None:
    held = profile()
    assert personal_profile_problem(held) is None
    held.provider = "bedrock"
    assert "API-key" in str(personal_profile_problem(held))
    held.provider = "openai"
    held.fallback_profile_ids = [str(uuid4())]
    assert "fallbacks" in str(personal_profile_problem(held))
    held.fallback_profile_ids = []
    held.base_url = None
    held.model = "text-embedding-3-small"
    assert "chat model" in str(personal_profile_problem(held))


@pytest.mark.security
async def test_resolution_requires_a_personal_key_and_never_reads_the_shared_secret() -> None:
    service, ctx, held = PersonalModelKeyService(AsyncMock()), context(), profile()
    with patch("app.services.personal_model_key.key_repo.get", AsyncMock(return_value=None)) as get:
        with pytest.raises(AuthorizationError) as refused:
            await service.resolve(ctx, held)
        assert refused.value.code == "PERSONAL_MODEL_KEY_REQUIRED"
        assert get.call_args.kwargs == {
            "organization_id": ctx.organization_id,
            "user_id": ctx.user_id,
            "provider": held.provider,
            "endpoint": held.base_url,
        }


@pytest.mark.security
async def test_resolution_unseals_only_the_callers_key_at_the_fixed_destination() -> None:
    ctx, held = context(), profile()
    assert ctx.user_id is not None
    sealed = seal_secret(
        ApiKeySecret(api_key="personal-private"), scope=VaultScope.user(ctx.user_id)
    )
    row = PersonalModelKey(sealed_secret=sealed.ciphertext, key_version=sealed.key_version)
    with patch("app.services.personal_model_key.key_repo.get", AsyncMock(return_value=row)):
        resolved = await PersonalModelKeyService(AsyncMock()).resolve(ctx, held)
    assert isinstance(resolved.credential.secret, ApiKeySecret)
    assert resolved.credential.secret.api_key.get_secret_value() == "personal-private"
    assert resolved.credential.base_url == held.base_url and resolved.model == held.model
    assert resolved.fallbacks == [] and resolved.secret_id is None
    assert "personal-private" not in repr(resolved)
    held.fallback_profile_ids = [str(uuid4())]
    with pytest.raises(BadRequestError, match="fallback"):
        await PersonalModelKeyService(AsyncMock()).resolve(ctx, held)


async def test_connection_access_uses_the_runnable_agent_and_never_the_publishers_key() -> None:
    service, ctx, chosen, held, agent_id = (
        PersonalModelKeyService(AsyncMock()),
        context(),
        spec(),
        profile(),
        uuid4(),
    )
    with (
        patch(
            "app.services.agent_registry.AgentRegistryService.get_runnable_spec",
            AsyncMock(return_value=(MagicMock(), chosen, uuid4())),
        ) as runnable,
        patch(
            "app.services.model_profile.ModelProfileService.profile_for_organization",
            AsyncMock(return_value=held),
        ),
        patch("app.services.personal_model_key.key_repo.get", AsyncMock(return_value=None)),
    ):
        status = await service.status(ctx, agent_id)
        assert status.personal and not status.connected
        runnable.assert_awaited_once_with(ctx, agent_id)
        held.fallback_profile_ids = [str(uuid4())]
        with pytest.raises(BadRequestError, match="fallback"):
            await service.status(ctx, agent_id)


async def test_organization_mode_has_no_personal_connection_and_cannot_accept_a_key() -> None:
    service = PersonalModelKeyService(AsyncMock())
    with patch.object(service, "_profile", AsyncMock(return_value=None)):
        assert not (await service.status(context(), uuid4())).personal
        with pytest.raises(BadRequestError, match="organization"):
            await service.save(context(), uuid4(), SecretStr("never-stored"))


@pytest.mark.security
async def test_personal_key_deletion_is_owner_scoped_and_does_not_acknowledge_missing_keys() -> (
    None
):
    service, ctx, key_id = PersonalModelKeyService(AsyncMock()), context(), uuid4()
    with patch(
        "app.services.personal_model_key.key_repo.delete", AsyncMock(return_value=False)
    ) as delete:
        with pytest.raises(NotFoundError):
            await service.delete(ctx, key_id)
        assert delete.call_args.kwargs["user_id"] == ctx.user_id


@pytest.mark.parametrize(
    ("draft_personal", "published_personal"), [(True, False), (False, True), (False, False)]
)
async def test_surface_admission_checks_both_draft_and_published_configuration(
    draft_personal: bool,
    published_personal: bool,
) -> None:
    ctx, agent_id = context(), uuid4()
    row = Agent(
        id=agent_id,
        current_version_id=uuid4(),
        draft_spec=spec(personal=draft_personal).model_dump(mode="json"),
    )
    with (
        patch(
            "app.services.personal_model_surfaces.AgentRegistryService.get",
            AsyncMock(return_value=row),
        ) as get,
        patch(
            "app.services.personal_model_surfaces.agent_repo.get_version",
            AsyncMock(
                return_value=AgentVersion(
                    agent_id=agent_id,
                    spec=spec(personal=published_personal).model_dump(mode="json"),
                )
            ),
        ),
    ):
        if draft_personal or published_personal:
            with pytest.raises(BadRequestError, match="signed-in web chat"):
                await require_organization_agent(AsyncMock(), ctx, agent_id)
        else:
            await require_organization_agent(AsyncMock(), ctx, agent_id)
        assert get.call_args.kwargs["for_update"] is True


async def test_an_organization_agent_does_not_ask_for_a_personal_connection() -> None:
    with patch(
        "app.services.agent_registry.AgentRegistryService.get_runnable_spec",
        AsyncMock(return_value=(MagicMock(), spec(personal=False), uuid4())),
    ):
        assert not (await PersonalModelKeyService(AsyncMock()).status(context(), uuid4())).personal


@pytest.mark.security
async def test_personal_connections_cannot_be_managed_as_a_publisher_fallback() -> None:
    ctx = replace(context(), subject_is_publisher_fallback=True)
    with pytest.raises(AuthorizationError, match="signed-in web session"):
        await PersonalModelKeyService(AsyncMock()).mine(ctx)


async def test_personal_configuration_refuses_voice_and_background_topics() -> None:
    from app.agents.spec import VoiceSpec

    chosen = spec().model_copy(update={"voice": VoiceSpec(provider="openai")})
    assert "voice" in personal_model_problems(chosen)[0]
    chosen = spec().model_copy(
        update={"capabilities": [CapabilityBindingSpec(id="background_tasks")]}
    )
    assert "background topics" in personal_model_problems(chosen)[0]


async def test_personal_resolution_refuses_an_unexpected_vault_value() -> None:
    from app.core.secret_kinds import NoSecret

    with (
        patch(
            "app.services.personal_model_key.key_repo.get",
            AsyncMock(return_value=PersonalModelKey(sealed_secret="broken", key_version=1)),
        ),
        patch("app.services.personal_model_key.unseal_secret", return_value=NoSecret()),
        pytest.raises(TypeError, match="wrong secret kind"),
    ):
        await PersonalModelKeyService(AsyncMock()).resolve(context(), profile())


@pytest.mark.parametrize(
    "missing", ["environment", "version", "foreign_environment", "foreign_version", "draft"]
)
async def test_surface_admission_refuses_missing_or_foreign_targets_and_checks_pinned_versions(
    missing: str,
) -> None:
    ctx, agent_id = context(), uuid4()
    row = Agent(
        id=agent_id,
        draft_spec=spec(personal=False).model_dump(mode="json"),
        current_version_id=None if missing == "draft" else uuid4(),
    )
    version = AgentVersion(
        agent_id=uuid4() if missing == "foreign_version" else agent_id,
        spec=spec(personal=False).model_dump(mode="json"),
    )
    environment = MagicMock(
        agent_id=uuid4() if missing == "foreign_environment" else agent_id, version_id=uuid4()
    )
    with (
        patch(
            "app.services.personal_model_surfaces.AgentRegistryService.get",
            AsyncMock(return_value=row),
        ),
        patch(
            "app.services.personal_model_surfaces.agent_environment_repo.get",
            AsyncMock(return_value=None if missing == "environment" else environment),
        ),
        patch(
            "app.services.personal_model_surfaces.agent_repo.get_version",
            AsyncMock(return_value=None if missing == "version" else version),
        ),
    ):
        if missing == "draft":
            await require_organization_agent(AsyncMock(), ctx, agent_id)
        else:
            with pytest.raises(NotFoundError):
                await require_organization_agent(AsyncMock(), ctx, agent_id, environment_id=uuid4())


async def test_surface_admission_checks_the_selected_environment_or_explicit_version() -> None:
    ctx, agent_id = context(), uuid4()
    row = Agent(
        id=agent_id,
        draft_spec=spec(personal=False).model_dump(mode="json"),
        current_version_id=uuid4(),
    )
    version = AgentVersion(agent_id=agent_id, spec=spec().model_dump(mode="json"))
    with (
        patch(
            "app.services.personal_model_surfaces.AgentRegistryService.get",
            AsyncMock(return_value=row),
        ),
        patch(
            "app.services.personal_model_surfaces.agent_environment_repo.get",
            AsyncMock(return_value=MagicMock(agent_id=agent_id, version_id=uuid4())),
        ),
        patch(
            "app.services.personal_model_surfaces.agent_repo.get_version",
            AsyncMock(return_value=version),
        ),
    ):
        for environment_id in [None, uuid4()]:
            with pytest.raises(BadRequestError, match="signed-in web chat"):
                await require_organization_agent(
                    AsyncMock(), ctx, agent_id, version_id=uuid4(), environment_id=environment_id
                )
