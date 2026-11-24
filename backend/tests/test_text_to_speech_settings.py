"""A default voice never borrows a different level's provider or key."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.core.exceptions import BadRequestError
from app.db.models.organization import Organization
from app.schemas.organization import OrganizationTextToSpeech
from app.services.text_to_speech_settings import TextToSpeechSettingsService

pytestmark = pytest.mark.anyio
MODULE = "app.services.text_to_speech_settings"
ORG = uuid4()
KEY = uuid4()


def defaults(*, enabled: bool = True) -> OrganizationTextToSpeech:
    return OrganizationTextToSpeech(
        enabled=enabled, provider="openai", model="gpt-4o-mini-tts", voice="coral", secret_id=KEY
    )


def inherited() -> CapabilityBindingSpec:
    return CapabilityBindingSpec(
        id="text_to_speech",
        config={
            "use_organization_defaults": True,
            "provider": "elevenlabs",
            "model": "eleven_v3",
            "voice": "old-voice",
        },
        secret_id=uuid4(),
    )


@pytest.mark.parametrize(
    "binding",
    [
        CapabilityBindingSpec(id="clock"),
        CapabilityBindingSpec(
            id="text_to_speech", enabled=False, config={"use_organization_defaults": True}
        ),
        CapabilityBindingSpec(id="text_to_speech", config={"provider": "openai"}),
    ],
)
async def test_unconfigured_disabled_and_explicit_agent_overrides_do_not_read_defaults(
    binding: CapabilityBindingSpec,
) -> None:
    with patch(f"{MODULE}.organization_repo.get_by_id", AsyncMock()) as read:
        resolved = await TextToSpeechSettingsService(MagicMock()).resolve_binding(ORG, binding)
    assert resolved is binding
    read.assert_not_awaited()


@pytest.mark.parametrize("value", [None, defaults(enabled=False)])
async def test_disabled_defaults_do_not_validate_or_spend_a_key(
    value: OrganizationTextToSpeech | None,
) -> None:
    with patch(f"{MODULE}.provider_keys.key_problem", AsyncMock()) as key:
        await TextToSpeechSettingsService(MagicMock()).validate_defaults(ORG, value)
    key.assert_not_awaited()


@pytest.mark.parametrize("value", [None, {}, defaults(enabled=False).model_dump(mode="json")])
async def test_inheritance_refuses_missing_or_disabled_organization_settings(value: object) -> None:
    org = None if value is None else Organization(text_to_speech=None if value == {} else value)
    with (
        patch(f"{MODULE}.organization_repo.get_by_id", AsyncMock(return_value=org)),
        pytest.raises(BadRequestError, match="disabled"),
    ):
        await TextToSpeechSettingsService(MagicMock()).resolve_binding(ORG, inherited())


@pytest.mark.security
async def test_an_inherited_voice_and_key_always_come_from_the_same_scope() -> None:
    binding = inherited()
    org = Organization(text_to_speech=defaults().model_dump(mode="json"))
    with (
        patch(f"{MODULE}.organization_repo.get_by_id", AsyncMock(return_value=org)),
        patch(f"{MODULE}.provider_keys.key_problem", AsyncMock(return_value=None)) as check,
    ):
        resolved, snapshot = await TextToSpeechSettingsService(MagicMock()).resolve_spec(
            ORG, AgentSpec(name="Voice", capabilities=[binding])
        )
    assert snapshot is not None and snapshot.secret_id == KEY
    result = resolved.capabilities[0]
    assert result.config == {
        "use_organization_defaults": False,
        "provider": "openai",
        "model": "gpt-4o-mini-tts",
        "voice": "coral",
    }
    assert result.secret_id == KEY
    assert binding.config["provider"] == "elevenlabs"
    assert binding.secret_id != KEY
    assert check.await_args.kwargs["ctx"] is None
    assert check.await_args.kwargs["organization_id"] == ORG


@pytest.mark.security
async def test_a_private_deleted_or_cross_tenant_key_cannot_be_inherited() -> None:
    with (
        patch(
            f"{MODULE}.provider_keys.key_problem",
            AsyncMock(return_value="Not an organization-visible key"),
        ),
        pytest.raises(BadRequestError, match="organization-visible"),
    ):
        await TextToSpeechSettingsService(MagicMock()).validate_defaults(ORG, defaults())


async def test_an_unavailable_model_is_refused_before_looking_up_a_key() -> None:
    value = defaults().model_copy(update={"model": "retired-model"})
    with (
        patch(f"{MODULE}.provider_keys.key_problem", AsyncMock()) as key,
        pytest.raises(BadRequestError, match="offered speech model"),
    ):
        await TextToSpeechSettingsService(MagicMock()).validate_defaults(ORG, value)
    key.assert_not_awaited()


async def test_a_parked_run_keeps_its_original_destination_when_the_default_changes() -> None:
    from app.db.models.agent_run import AgentRun

    db = MagicMock()
    db.flush = AsyncMock()
    service = TextToSpeechSettingsService(db)
    run = AgentRun(text_to_speech_defaults=None)
    spec = AgentSpec(name="Voice", capabilities=[inherited()])
    org = Organization(text_to_speech=defaults().model_dump(mode="json"))
    with (
        patch(f"{MODULE}.organization_repo.get_by_id", AsyncMock(return_value=org)),
        patch(f"{MODULE}.provider_keys.key_problem", AsyncMock(return_value=None)),
    ):
        original = await service.for_run(ORG, spec, run)
        org.text_to_speech = (
            defaults()
            .model_copy(
                update={
                    "provider": "elevenlabs",
                    "model": "eleven_v3",
                    "voice": "new-voice",
                    "secret_id": uuid4(),
                }
            )
            .model_dump(mode="json")
        )
        resumed = await service.for_run(ORG, spec, run)
    assert original.capabilities[0].config == resumed.capabilities[0].config
    assert resumed.capabilities[0].secret_id == KEY
    assert run.text_to_speech_defaults == defaults().model_dump(mode="json")
    assert db.flush.await_count == 1


async def test_a_delegate_without_inheritance_never_reads_or_pins_a_default() -> None:
    from app.db.models.agent_run import AgentRun

    spec = AgentSpec(name="No voice")
    result = await TextToSpeechSettingsService(MagicMock()).for_run(ORG, spec, AgentRun())
    assert result is spec


@pytest.mark.security
async def test_disabling_the_organization_voice_also_refuses_a_parked_run() -> None:
    from app.db.models.agent_run import AgentRun

    org = Organization(text_to_speech=defaults(enabled=False).model_dump(mode="json"))
    run = AgentRun(text_to_speech_defaults=defaults().model_dump(mode="json"))
    with (
        patch(f"{MODULE}.organization_repo.get_by_id", AsyncMock(return_value=org)),
        pytest.raises(BadRequestError, match="disabled"),
    ):
        await TextToSpeechSettingsService(MagicMock()).for_run(
            ORG, AgentSpec(name="Voice", capabilities=[inherited()]), run
        )


async def test_organization_settings_store_and_clear_the_group_together() -> None:
    from types import SimpleNamespace

    from app.schemas.organization import OrganizationUpdate
    from app.services.organization import OrganizationService

    org = Organization(id=ORG, name="Voice")
    db = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    service = OrganizationService(db)
    with (
        patch.object(
            service, "get_for_user", AsyncMock(return_value=(org, SimpleNamespace(role="owner")))
        ),
        patch(f"{MODULE}.provider_keys.key_problem", AsyncMock(return_value=None)),
    ):
        await service.update(ORG, OrganizationUpdate(text_to_speech=defaults()), uuid4())
        assert org.text_to_speech == defaults().model_dump(mode="json")
        await service.update(ORG, OrganizationUpdate(text_to_speech=None), uuid4())
        assert org.text_to_speech is None


@pytest.mark.security
async def test_a_key_without_organization_settings_authority_cannot_change_the_voice() -> None:
    from types import SimpleNamespace

    from app.core.exceptions import AuthorizationError
    from app.schemas.organization import OrganizationUpdate
    from app.services.organization import OrganizationService

    org = Organization(id=ORG, name="Voice")
    db = MagicMock()
    db.flush = AsyncMock()
    service = OrganizationService(db)
    with (
        patch.object(
            service, "get_for_user", AsyncMock(return_value=(org, SimpleNamespace(role="owner")))
        ),
        pytest.raises(AuthorizationError),
    ):
        await service.update(
            ORG, OrganizationUpdate(text_to_speech=defaults()), uuid4(), key_scopes=frozenset()
        )
    db.flush.assert_not_awaited()
    assert org.text_to_speech is None


@pytest.mark.security
async def test_publish_may_inherit_an_administrator_approved_shared_key_without_vault_read_scope() -> (
    None
):
    from app.core.permissions import AuthContext, OrgRoleName, Perm
    from app.db.models.organization_secret import OrganizationSecret
    from app.services.agent_registry import AgentRegistryService

    context = AuthContext(
        user_id=uuid4(),
        organization_id=ORG,
        role=OrgRoleName.OWNER,
        key_scopes=frozenset({Perm.AGENTS_EDIT}),
    )
    org = Organization(id=ORG, text_to_speech=defaults().model_dump(mode="json"))
    key = OrganizationSecret(
        id=KEY,
        organization_id=ORG,
        name="Shared speech",
        visibility="org",
        kind="api_key",
        purpose="openai",
    )
    with (
        patch(f"{MODULE}.organization_repo.get_by_id", AsyncMock(return_value=org)),
        patch(
            "app.services.provider_keys.organization_secret_repo.get", AsyncMock(return_value=key)
        ),
    ):
        problems = await AgentRegistryService(MagicMock())._binding_problems(context, inherited())
    assert problems.messages == []


async def test_resolving_a_custom_voice_preserves_it_without_a_shared_snapshot() -> None:
    binding = CapabilityBindingSpec(
        id="text_to_speech",
        config={"provider": "openai", "model": "gpt-4o-mini-tts"},
        secret_id=KEY,
    )
    original = AgentSpec(name="Custom voice", capabilities=[binding])
    resolved, snapshot = await TextToSpeechSettingsService(MagicMock()).resolve_spec(ORG, original)
    assert resolved.capabilities[0] is binding
    assert snapshot is None


async def test_inherited_configuration_validates_the_resolved_group_instead_of_old_agent_choices() -> (
    None
):
    from app.agents.capabilities.text_to_speech import TextToSpeechConfig

    pending = TextToSpeechConfig(
        use_organization_defaults=True, provider="retired", model="retired", voice="retired"
    )
    binding = CapabilityBindingSpec(id="text_to_speech", config=pending.model_dump(mode="json"))
    org = Organization(id=ORG, text_to_speech=defaults().model_dump(mode="json"))
    with (
        patch(f"{MODULE}.organization_repo.get_by_id", AsyncMock(return_value=org)),
        patch(f"{MODULE}.provider_keys.key_problem", AsyncMock(return_value=None)),
    ):
        resolved = await TextToSpeechSettingsService(MagicMock()).resolve_binding(ORG, binding)
    effective = TextToSpeechConfig.model_validate(resolved.config)
    assert effective.provider == "openai"
    assert effective.model == "gpt-4o-mini-tts"
    assert effective.voice == "coral"
    assert effective.use_organization_defaults is False
    assert resolved.secret_id == KEY
