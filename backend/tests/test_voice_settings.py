"""Whether an agent can take a call, and on what (#54)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.agents.spec import AgentSpec, CapabilityBindingSpec, VoiceSpec
from app.services.voice import VoiceRefused
from app.services.voice.settings import VoiceSettingsService, resolve_voice

pytestmark = pytest.mark.anyio
_KEY = uuid4()


def test_an_azure_section_resolves_to_its_deployment_and_base_model_entry():
    resolved = resolve_voice(
        VoiceSpec(provider="azure", deployment="rt-prod", base_model="gpt-realtime", secret_id=_KEY)
    )
    assert (
        resolved is not None
        and resolved.wire_model == "rt-prod"
        and resolved.entry.id == "gpt-realtime"
    )
    assert resolved.voice == resolved.entry.default_voice


def test_a_section_without_a_key_or_outside_the_catalog_resolves_to_nothing():
    assert resolve_voice(VoiceSpec(provider="openai", model="gpt-realtime")) is None
    assert resolve_voice(VoiceSpec(provider="openai", model="gpt-4o", secret_id=_KEY)) is None
    assert resolve_voice(None) is None


async def _readiness(spec, *, key=True):
    service = VoiceSettingsService(MagicMock())
    agent = SimpleNamespace(
        id=uuid4(), organization_id=uuid4(), current_version_id=uuid4(), status="published"
    )
    with (
        patch.object(service, "published_spec", new=AsyncMock(return_value=spec)),
        patch(
            "app.services.voice.settings.organization_secret_repo.get",
            new=AsyncMock(return_value=SimpleNamespace(id=_KEY) if key else None),
        ),
    ):
        return await service.readiness(organization_id=agent.organization_id, agent=agent)


_READY = AgentSpec(
    name="a",
    voice=VoiceSpec(provider="openai", model="gpt-realtime", secret_id=_KEY),
    capabilities=[CapabilityBindingSpec(id="sandbox")],
)


async def test_an_agent_with_a_voice_section_is_ready_whatever_the_organization():
    """Calls are switched on in the agent; the organization has no call settings."""
    readiness = await _readiness(_READY)
    assert readiness.available and readiness.transport == "webrtc"
    assert readiness.cap_seconds == 600


async def test_the_cap_is_the_agents_own_longest_call():
    spec = _READY.model_copy(
        update={"voice": _READY.voice.model_copy(update={"max_call_seconds": 1200})}
    )
    assert (await _readiness(spec)).cap_seconds == 1200


@pytest.mark.parametrize(
    ("spec", "reason"),
    [
        (AgentSpec(name="a"), "no_voice"),
        (AgentSpec(name="a", voice=VoiceSpec(provider="openai", model="gpt-realtime")), "no_key"),
    ],
)
async def test_each_reason_a_call_is_not_offered(spec, reason):
    readiness = await _readiness(spec)
    assert not readiness.available and readiness.unavailable == reason


async def test_a_published_key_deleted_from_the_vault_since_is_no_key():
    """The spec keeps the deleted key's id, so only the vault's row says it is gone:
    offering the call would ask for the microphone only for the start to refuse it."""
    readiness = await _readiness(_READY, key=False)
    assert not readiness.available and readiness.unavailable == "no_key"


def test_a_provider_without_calls_or_an_azure_section_without_a_deployment_resolves_to_nothing():
    assert resolve_voice(VoiceSpec(provider="anthropic", model="claude", secret_id=_KEY)) is None
    assert (
        resolve_voice(VoiceSpec(provider="azure", base_model="gpt-realtime", secret_id=_KEY))
        is None
    )


def test_the_label_names_the_model_and_the_voice():
    resolved = resolve_voice(
        VoiceSpec(provider="openai", model="gpt-realtime", secret_id=_KEY, voice="cedar")
    )
    assert (
        resolved is not None
        and resolved.label == "GPT Realtime (cedar)"
        and resolved.wire_model == "gpt-realtime"
    )


async def test_a_model_withdrawn_from_the_catalog_is_not_offered():
    spec = AgentSpec(name="a", voice=VoiceSpec(provider="openai", model="gpt-4o", secret_id=_KEY))
    readiness = await _readiness(spec)
    assert (readiness.available, readiness.unavailable, readiness.transport) == (
        False,
        "not_offered",
        None,
    )


@pytest.mark.parametrize("status", ["archived", "unpublished"])
async def test_an_archived_or_unpublished_agent_has_no_spec_to_call(status):
    agent = SimpleNamespace(
        organization_id=uuid4(),
        current_version_id=None if status == "unpublished" else uuid4(),
        status=status,
    )
    assert await VoiceSettingsService(MagicMock()).published_spec(agent) is None


async def test_the_published_spec_is_the_default_versions():
    agent = SimpleNamespace(organization_id=uuid4(), current_version_id=uuid4(), status="published")
    version = SimpleNamespace(spec=_READY.model_dump(mode="json"))
    with patch(
        "app.services.voice.settings.agent_repo.get_version", new=AsyncMock(return_value=version)
    ) as got:
        spec = await VoiceSettingsService(MagicMock()).published_spec(agent)
    assert spec == _READY
    assert got.call_args.kwargs["organization_id"] == agent.organization_id


async def test_a_version_that_is_gone_has_no_spec_to_call():
    agent = SimpleNamespace(organization_id=uuid4(), current_version_id=uuid4(), status="published")
    with patch(
        "app.services.voice.settings.agent_repo.get_version", new=AsyncMock(return_value=None)
    ):
        assert await VoiceSettingsService(MagicMock()).published_spec(agent) is None


def test_a_refusal_carries_its_reason_for_the_client():
    refused = VoiceRefused("no_agent", "Pick an agent to call.")
    assert (refused.reason, refused.details, refused.status_code) == (
        "no_agent",
        {"reason": "no_agent"},
        400,
    )


@pytest.mark.parametrize(
    ("version", "status", "runs"),
    [(uuid4(), "published", True), (None, "published", False), (uuid4(), "archived", False)],
)
def test_one_check_decides_whether_an_agent_can_take_a_call(version, status, runs):
    from app.services.voice.settings import agent_takes_calls

    agent = SimpleNamespace(current_version_id=version, status=status)
    assert agent_takes_calls(agent) is runs
    assert agent_takes_calls(None) is False
