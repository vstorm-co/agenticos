"""Personal LLM credentials never change the model or borrow an organization key."""

from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import SecretStr

from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.core.exceptions import AuthorizationError, BadRequestError, ConflictError, NotFoundError
from app.core.permissions import AuthContext
from app.core.secret_kinds import ApiKeySecret, seal_secret
from app.core.vault import VaultScope
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_run import RunSurface
from app.db.models.credential import ModelProfile
from app.db.models.personal_model_key import PersonalModelKey
from app.schemas.personal_model_key import PersonalModelDestination, PersonalModelKeyCreate
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


def key_request(held: ModelProfile, key: str) -> PersonalModelKeyCreate:
    return PersonalModelKeyCreate(
        api_key=SecretStr(key),
        expected_destination=PersonalModelDestination(
            profile_id=held.id, provider=held.provider, endpoint=held.base_url, model=held.model
        ),
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


async def test_delegation_is_allowed_but_separate_step_models_are_refused() -> None:
    chosen = spec().model_copy(update={"capabilities": [CapabilityBindingSpec(id="subagents")]})
    assert personal_model_problems(chosen) == []
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
    with pytest.raises(BadRequestError) as refused:
        require_personal_model_run(chosen, context(), RunSurface.WEB)
    assert refused.value.code == "PERSONAL_MODEL_CONFIGURATION"
    assert "separate capability models" in refused.value.message


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
            await service.save(context(), uuid4(), key_request(profile(), "never-stored"))


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


@pytest.mark.security
@pytest.mark.parametrize("changed", ["profile_id", "provider", "endpoint", "model"])
async def test_connection_refuses_a_destination_changed_after_the_form_was_opened(
    changed: str,
) -> None:
    service, ctx, held = PersonalModelKeyService(AsyncMock()), context(), profile()
    request = key_request(held, "key-for-original-destination")
    if changed == "profile_id":
        held.id = uuid4()
    elif changed == "endpoint":
        held.base_url = "https://replacement.example.com/v1"
    elif changed == "provider":
        held.provider = "openrouter"
    else:
        held.model = "replacement-model"
    with (
        patch.object(service, "_profile", AsyncMock(return_value=held)),
        patch("app.services.personal_model_key.seal_secret") as seal,
        patch("app.services.personal_model_key.key_repo.save", AsyncMock()) as save,
        pytest.raises(ConflictError) as refused,
    ):
        await service.save(ctx, uuid4(), request)
    assert refused.value.code == "PERSONAL_MODEL_DESTINATION_CHANGED"
    seal.assert_not_called()
    save.assert_not_awaited()
    assert "key-for-original" not in str(refused.value)


@pytest.mark.security
@pytest.mark.parametrize("operation", ["list", "status", "save", "delete", "resolve"])
@pytest.mark.parametrize("stage", ["request", "run"])
async def test_impersonation_cannot_reach_personal_model_keys_at_request_or_run_time(
    operation: str,
    stage: str,
) -> None:
    from app.agents.audience import acting_impersonated, run_impersonated
    from app.core.audit import current_impersonator, set_impersonator

    ctx, held, agent_id = context(), profile(), uuid4()
    db = AsyncMock()
    service = PersonalModelKeyService(db)
    previous = current_impersonator()
    with (
        acting_impersonated(stage == "run"),
        patch("app.services.personal_model_key.key_repo.list_for", AsyncMock()) as listed,
        patch("app.services.personal_model_key.key_repo.get", AsyncMock()) as read,
        patch("app.services.personal_model_key.key_repo.save", AsyncMock()) as saved,
        patch("app.services.personal_model_key.key_repo.delete", AsyncMock()) as deleted,
        patch("app.services.personal_model_key.seal_secret") as seal,
        patch("app.services.personal_model_key.unseal_secret") as unseal,
    ):
        set_impersonator(uuid4() if stage == "request" else None)
        try:
            assert run_impersonated() == (stage == "run")
            with pytest.raises(AuthorizationError, match="signed-in web session"):
                if operation == "list":
                    await service.mine(ctx)
                elif operation == "status":
                    await service.status(ctx, agent_id)
                elif operation == "save":
                    await service.save(ctx, agent_id, key_request(held, "private-key"))
                elif operation == "delete":
                    await service.delete(ctx, uuid4())
                else:
                    await service.resolve(ctx, held)
        finally:
            set_impersonator(previous)
    for repository in [listed, read, saved, deleted]:
        repository.assert_not_awaited()
    seal.assert_not_called()
    unseal.assert_not_called()
    assert db.mock_calls == []


@pytest.mark.security
async def test_personal_resolution_records_its_connection_identity_without_secret_metadata() -> (
    None
):
    ctx = context()
    held = profile()
    row = PersonalModelKey(
        id=uuid4(),
        organization_id=ctx.organization_id,
        user_id=ctx.user_id,
        provider=held.provider,
        endpoint=held.base_url,
        sealed_secret="ciphertext",
        key_version=1,
    )
    with (
        patch("app.services.personal_model_key.key_repo.get", AsyncMock(return_value=row)),
        patch(
            "app.services.personal_model_key.unseal_secret",
            return_value=ApiKeySecret(api_key=SecretStr("test-secret")),
        ),
    ):
        resolved = await PersonalModelKeyService(AsyncMock()).resolve(ctx, held)
    assert resolved.credential.credential_id == row.id
    assert resolved.credential.authorization_generation is None
    assert resolved.credential.routing == {"credential_updated_at": None}
    assert resolved.credential.base_url == held.base_url


async def test_reviewed_personal_destination_never_carries_a_credential() -> None:
    service, held = PersonalModelKeyService(AsyncMock()), profile()
    with patch.object(service, "_profile", AsyncMock(return_value=held)):
        destination = await service.destination(context(), uuid4())
    assert destination.model_dump() == {
        "profile_id": held.id,
        "provider": held.provider,
        "endpoint": held.base_url,
        "model": held.model,
    }
    with (
        patch.object(service, "_profile", AsyncMock(return_value=None)),
        pytest.raises(BadRequestError, match="organization"),
    ):
        await service.destination(context(), uuid4())


@pytest.mark.security
async def test_missing_personal_key_cannot_advance_another_connection_generation() -> None:
    service = PersonalModelKeyService(AsyncMock())
    with (
        patch("app.services.personal_model_key.key_repo.get_by_id", AsyncMock(return_value=None)),
        patch("app.services.personal_model_key.key_repo.bump_generation", AsyncMock()) as bump,
    ):
        with pytest.raises(NotFoundError):
            await service.delete(context(), uuid4())
        bump.assert_not_called()


async def test_personal_copilot_rejects_a_stored_custom_endpoint() -> None:
    held = profile()
    held.provider = "github_copilot"
    assert personal_profile_problem(held) == "Copilot requires the fixed GitHub.com gateway"


def test_personal_keys_still_refuse_reviewers() -> None:
    from app.agents.spec import RunReviewerSpec

    chosen = spec().model_copy(update={"reviewers": [RunReviewerSpec(name="reviewer")]})
    assert personal_model_problems(chosen) == ["Personal model keys do not support reviewers yet"]
