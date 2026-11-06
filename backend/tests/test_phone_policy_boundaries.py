"""Phone contact and routing choices remain an explicit current human consent."""

from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.exceptions import AuthorizationError, BadRequestError, RateLimitError
from app.db.models.agent_embed import AgentEmbed
from app.db.models.channel_identity import ChannelIdentity
from app.services.telephony import policy
from tests.test_phone_authority import contact_and_call

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.mark.parametrize("change", ["machine", "key", "routine", "fired", "publisher"])
async def test_phone_consent_cannot_be_changed_from_unattended_contexts(change):
    _, _, ctx = contact_and_call()
    changes = {
        "machine": {"user_id": None},
        "key": {"api_key_id": uuid4()},
        "routine": {"routine_id": uuid4()},
        "fired": {"fired_as_creator": "schedule"},
        "publisher": {"subject_is_publisher_fallback": True},
    }
    with pytest.raises(AuthorizationError, match="own console"):
        await policy.PhonePolicyService(AsyncMock()).settings(replace(ctx, **changes[change]))


@pytest.mark.parametrize(
    "change", ["ok", "left", "relinked", "not_opted_in", "quiet", "daily_limit"]
)
async def test_contact_checks_current_membership_number_generation_hours_and_daily_limit(
    monkeypatch, change
):
    contact, _, ctx = contact_and_call()
    contact.allow_reports, contact.calls_per_day = change != "not_opted_in", 2
    identity = ChannelIdentity(
        id=contact.identity_id,
        user_id=ctx.user_id,
        platform="sms",
        platform_user_id="+15551234567",
        is_active=True,
        authorization_generation=uuid4() if change == "relinked" else contact.identity_generation,
        created_at=datetime.now(UTC),
    )
    monkeypatch.setattr(
        policy, "acting_member", AsyncMock(return_value=None if change == "left" else ctx)
    )
    monkeypatch.setattr(policy.channel_identity_repo, "get_by_id", AsyncMock(return_value=identity))
    monkeypatch.setattr(policy, "quiet_now", lambda *args: change == "quiet")
    monkeypatch.setattr(
        policy.repo,
        "contact_calls_today",
        AsyncMock(return_value=2 if change == "daily_limit" else 0),
    )
    if change == "ok":
        assert (
            await policy.PhonePolicyService(AsyncMock()).available_contact(contact, mode="report")
            == identity.platform_user_id
        )
    else:
        with pytest.raises((AuthorizationError, RateLimitError)):
            await policy.PhonePolicyService(AsyncMock()).available_contact(contact, mode="report")


async def test_settings_omit_non_voice_and_inaccessible_exposures_but_preserve_fallback_labels(
    monkeypatch,
):
    contact, _, ctx = contact_and_call()
    ctx = replace(ctx, role="owner")
    denied, allowed = uuid4(), uuid4()
    monkeypatch.setattr(policy.channel_identity_repo, "list_for_user", AsyncMock(return_value=[]))
    monkeypatch.setattr(policy.repo, "contact", AsyncMock(return_value=None))
    monkeypatch.setattr(policy.repo, "endpoints", AsyncMock(return_value=[]))
    monkeypatch.setattr(policy.channel_bot_repo, "list_for_org", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        policy.repo,
        "public_embeds",
        AsyncMock(
            return_value=[
                MagicMock(config={}),
                MagicMock(id=denied, agent_id=denied, config={"voice_conversation": True}),
                AgentEmbed(
                    id=allowed,
                    agent_id=allowed,
                    name="Voice desk",
                    config={"voice_conversation": True},
                ),
            ]
        ),
    )

    async def agent(dbself, actor, identifier, **kwargs):
        if identifier == denied:
            raise AuthorizationError(message="Not shared")
        return MagicMock()

    monkeypatch.setattr(policy.AgentRegistryService, "get", agent)
    monkeypatch.setattr(policy.repo, "transfer_contacts", AsyncMock(return_value=[contact]))
    monkeypatch.setattr(policy, "acting_member", AsyncMock(return_value=ctx))
    monkeypatch.setattr(
        policy.user_repo, "get_by_id", AsyncMock(return_value=MagicMock(full_name=""))
    )
    result = await policy.PhonePolicyService(AsyncMock()).settings(ctx)
    assert [item.id for item in result.public_voice_embeds] == [allowed]
    assert result.transfer_contacts[0].label == "Phone contact"


async def test_public_voice_routing_refuses_a_published_agent_without_live_voice_readiness(
    monkeypatch,
):
    from app.services.voice.settings import VoiceSettingsService

    _, _, ctx = contact_and_call()
    embed = MagicMock(
        is_active=True,
        auth_mode="public",
        kind="widget",
        config={"voice_conversation": True},
        agent_id=uuid4(),
    )
    monkeypatch.setattr(policy.agent_embed_repo, "get", AsyncMock(return_value=embed))
    monkeypatch.setattr(policy.AgentRegistryService, "get", AsyncMock(return_value=MagicMock()))
    monkeypatch.setattr(
        VoiceSettingsService, "readiness", AsyncMock(return_value=MagicMock(available=False))
    )
    with pytest.raises(BadRequestError, match="not ready"):
        await policy.PhonePolicyService(AsyncMock()).public_embed(ctx, uuid4())
