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


def _org(**overrides):
    values = {
        "id": uuid4(),
        "voice_conversations_enabled": True,
        "voice_in_chat": True,
        "voice_max_call_seconds": 600,
        "voice_monthly_minutes": 600,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


async def _readiness(org, spec, *, used_seconds=0, surface="web"):
    service = VoiceSettingsService(MagicMock())
    agent = SimpleNamespace(
        id=uuid4(), organization_id=org.id, current_version_id=uuid4(), status="published"
    )
    with (
        patch(
            "app.services.voice.settings.organization_repo.get_by_id",
            new=AsyncMock(return_value=org),
        ),
        patch.object(service, "published_spec", new=AsyncMock(return_value=spec)),
        patch(
            "app.services.voice.settings.voice_call_repo.seconds_since",
            new=AsyncMock(return_value=used_seconds),
        ),
    ):
        return await service.readiness(organization_id=org.id, agent=agent, surface=surface)


_READY = AgentSpec(
    name="a",
    voice=VoiceSpec(provider="openai", model="gpt-realtime", secret_id=_KEY),
    capabilities=[CapabilityBindingSpec(id="sandbox")],
)


async def test_a_configured_agent_is_ready_and_lists_what_a_call_cannot_use():
    readiness = await _readiness(_org(), _READY)
    assert readiness.available and readiness.transport == "webrtc"
    assert readiness.unavailable_capabilities == ["sandbox"]
    assert readiness.cap_seconds == 600 and readiness.minutes_left == 600


@pytest.mark.parametrize(
    ("org", "spec", "used", "reason"),
    [
        (_org(voice_conversations_enabled=False), _READY, 0, "org_off"),
        (_org(voice_in_chat=False), _READY, 0, "not_in_chat"),
        (_org(), AgentSpec(name="a"), 0, "no_voice"),
        (
            _org(),
            AgentSpec(name="a", voice=VoiceSpec(provider="openai", model="gpt-realtime")),
            0,
            "no_key",
        ),
        (_org(), _READY, 600 * 60, "minutes_exhausted"),
    ],
)
async def test_each_reason_a_call_is_not_offered(org, spec, used, reason):
    readiness = await _readiness(org, spec, used_seconds=used)
    assert not readiness.available and readiness.unavailable == reason


async def test_an_embed_ignores_the_chat_switch():
    assert (await _readiness(_org(voice_in_chat=False), _READY, surface="embed")).available


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
    readiness = await _readiness(_org(), spec)
    assert (readiness.available, readiness.unavailable, readiness.transport) == (
        False,
        "not_offered",
        None,
    )


async def test_an_organization_that_is_gone_offers_no_call():
    service = VoiceSettingsService(MagicMock())
    agent = SimpleNamespace(
        id=uuid4(), organization_id=uuid4(), current_version_id=uuid4(), status="published"
    )
    with (
        patch(
            "app.services.voice.settings.organization_repo.get_by_id",
            new=AsyncMock(return_value=None),
        ),
        patch.object(service, "published_spec", new=AsyncMock(return_value=_READY)),
    ):
        readiness = await service.readiness(organization_id=agent.organization_id, agent=agent)
    assert (readiness.unavailable, readiness.cap_seconds, readiness.minutes_left) == (
        "org_off",
        0,
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
    refused = VoiceRefused("org_off", "Voice conversations are off in this organization")
    assert (refused.reason, refused.details, refused.status_code) == (
        "org_off",
        {"reason": "org_off"},
        400,
    )
