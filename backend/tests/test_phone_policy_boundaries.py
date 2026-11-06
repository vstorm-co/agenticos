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


@pytest.mark.parametrize(
    "change", ["role", "missing_bot", "wrong_platform", "missing_target", "unconsented_target"]
)
async def test_phone_routing_refuses_unmanageable_accounts_or_transfer_targets(monkeypatch, change):
    from app.core.exceptions import NotFoundError
    from app.schemas.telephony import PhoneEndpointConfig

    contact, _, ctx = contact_and_call()
    ctx = replace(ctx, role="member" if change == "role" else "owner")
    contact.allow_transfers = change != "unconsented_target"
    bot = MagicMock(platform="telegram" if change == "wrong_platform" else "sms")
    monkeypatch.setattr(policy, "hold_subject", AsyncMock())
    monkeypatch.setattr(
        policy.channel_bot_repo,
        "get_for_org",
        AsyncMock(return_value=None if change == "missing_bot" else bot),
    )
    monkeypatch.setattr(policy, "credentials", lambda _bot: None)
    monkeypatch.setattr(
        policy.repo,
        "contact_by_id",
        AsyncMock(return_value=None if change == "missing_target" else contact),
    )
    data = PhoneEndpointConfig(
        enabled=False, price_per_minute_usd="0.10", transfer_contact_ids=[contact.id]
    )
    with pytest.raises((AuthorizationError, NotFoundError, BadRequestError)):
        await policy.PhonePolicyService(AsyncMock()).configure(ctx, uuid4(), data)


async def test_phone_budget_reserves_the_entire_worst_case_before_admission(monkeypatch):
    from decimal import Decimal

    endpoint = MagicMock(
        transfer_contact_ids=[],
        price_per_minute_usd=Decimal("1"),
        max_call_seconds=120,
        calls_per_hour=5,
        calls_per_day=10,
        max_concurrent=2,
        daily_budget_usd=Decimal("2"),
    )
    monkeypatch.setattr(
        policy.repo, "allowance", AsyncMock(return_value=(0, 0, 0, Decimal("0.01")))
    )
    with pytest.raises(RateLimitError, match="worst case"):
        await policy.PhonePolicyService(AsyncMock()).admit_budget(endpoint)


@pytest.mark.parametrize(
    "change", ["missing", "inactive", "private", "wrong_kind", "voice_disabled"]
)
async def test_inbound_voice_requires_an_active_public_voice_exposure(monkeypatch, change):
    _, _, ctx = contact_and_call()
    embed = MagicMock(
        is_active=change != "inactive",
        auth_mode="private" if change == "private" else "public",
        kind="other" if change == "wrong_kind" else "widget",
        config={"voice_conversation": change != "voice_disabled"},
    )
    monkeypatch.setattr(
        policy.agent_embed_repo,
        "get",
        AsyncMock(return_value=None if change == "missing" else embed),
    )
    with pytest.raises(BadRequestError, match="active public"):
        await policy.PhonePolicyService(AsyncMock()).public_embed(ctx, uuid4())


@pytest.mark.parametrize("change", ["missing", "inactive", "wrong_platform", "generation"])
async def test_route_loading_requires_the_current_sms_account(monkeypatch, change):
    from app.core.exceptions import NotFoundError

    generation = uuid4()
    row = MagicMock(
        enabled=True, organization_id=uuid4(), bot_id=uuid4(), bot_generation=generation
    )
    bot = MagicMock(
        is_active=change != "inactive",
        platform="slack" if change == "wrong_platform" else "sms",
        authorization_generation=uuid4() if change == "generation" else generation,
    )
    monkeypatch.setattr(policy.repo, "endpoint", AsyncMock(return_value=row))
    monkeypatch.setattr(
        policy.channel_bot_repo,
        "get_for_org",
        AsyncMock(return_value=None if change == "missing" else bot),
    )
    with pytest.raises((AuthorizationError, NotFoundError)):
        await policy.PhonePolicyService(AsyncMock()).load_endpoint(uuid4())


async def test_settings_hide_retired_endpoints_non_sms_identities_and_removed_people(monkeypatch):
    contact, _, ctx = contact_and_call()
    ctx = replace(ctx, role="owner")
    monkeypatch.setattr(
        policy.channel_identity_repo,
        "list_for_user",
        AsyncMock(return_value=[MagicMock(platform="slack", is_active=True)]),
    )
    monkeypatch.setattr(policy.repo, "contact", AsyncMock(return_value=contact))
    monkeypatch.setattr(policy.channel_identity_repo, "get_by_id", AsyncMock(return_value=None))
    monkeypatch.setattr(
        policy.repo, "endpoints", AsyncMock(return_value=[MagicMock(enabled=False)])
    )
    monkeypatch.setattr(policy.channel_bot_repo, "get_for_org", AsyncMock(return_value=None))
    monkeypatch.setattr(
        policy.channel_bot_repo,
        "list_for_org",
        AsyncMock(return_value=[MagicMock(platform="slack")]),
    )
    monkeypatch.setattr(policy.repo, "public_embeds", AsyncMock(return_value=[]))
    monkeypatch.setattr(policy.repo, "transfer_contacts", AsyncMock(return_value=[contact]))
    monkeypatch.setattr(policy, "acting_member", AsyncMock(return_value=None))
    monkeypatch.setattr(policy.user_repo, "get_by_id", AsyncMock(return_value=None))
    result = await policy.PhonePolicyService(AsyncMock()).settings(ctx)
    assert (
        result.sms_identities == []
        and result.contact is None
        and result.endpoints == []
        and result.transfer_contacts == []
    )
