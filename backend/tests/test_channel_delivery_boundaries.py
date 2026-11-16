"""Durable inbound work retains current bot authority and routes human choices once."""

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.services.channels.base import IncomingMessage, feedback_value
from app.services.channels.next_steps import next_value
from app.worker.jobs import ChannelDelivery, EmailDelivery
from app.worker.tasks import channel_tasks

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.fixture
def worker(monkeypatch):
    from app.repositories import channel_bot_repo

    org, identifier = uuid4(), uuid4()
    bot = MagicMock(
        id=identifier, organization_id=org, platform="email", is_active=True, webhook_mode=True
    )
    db = AsyncMock()

    @asynccontextmanager
    async def session():
        yield db

    monkeypatch.setattr(channel_tasks, "get_db_context", session)
    monkeypatch.setattr(channel_bot_repo, "get_for_inbound", AsyncMock(return_value=bot))
    monkeypatch.setattr(channel_tasks, "ensure_channel_adapters", lambda: None)
    return bot, db


@pytest.mark.parametrize("change", ["missing", "inactive", "tenant", "platform"])
async def test_email_worker_does_not_process_deliveries_without_current_bot_authority(
    worker, monkeypatch, change
):
    from app.repositories import channel_bot_repo

    bot, _ = worker
    org = bot.organization_id
    if change == "missing":
        channel_bot_repo.get_for_inbound.return_value = None
    elif change == "inactive":
        bot.is_active = False
    elif change == "tenant":
        bot.organization_id = uuid4()
    else:
        bot.platform = "sms"
    routed = AsyncMock()
    monkeypatch.setattr(channel_tasks, "_route_inbound", routed)
    await channel_tasks.process_email_delivery(
        EmailDelivery(organization_id=org, bot_id=bot.id, body="{}")
    )
    routed.assert_not_awaited()


@pytest.mark.parametrize("change", ["invalid", "capacity"])
async def test_durable_email_parse_or_cache_failures_are_explicit(worker, monkeypatch, change):
    from app.services import channel_bot
    from app.services.channels import email

    bot, _ = worker
    monkeypatch.setattr(channel_bot, "unseal_bot_token", lambda _: "bot@example.com")
    monkeypatch.setattr(email, "keep_inbound", AsyncMock(return_value=None))
    payload = (
        {}
        if change == "invalid"
        else {
            "from": "ada@example.com",
            "text": "Hello",
            "sender_authentication": {"dmarc": "pass", "from": "ada@example.com"},
        }
    )
    with pytest.raises(ValueError if change == "invalid" else RuntimeError):
        await channel_tasks.process_email_delivery(
            EmailDelivery(
                organization_id=bot.organization_id, bot_id=bot.id, body=json.dumps(payload)
            )
        )


@pytest.mark.parametrize("change", ["disabled", "platform", "polling_imessage", "ignored"])
async def test_channel_worker_ignores_stale_or_inapplicable_deliveries(worker, monkeypatch, change):
    from app.services import channels

    bot, _ = worker
    bot.platform = "imessage"
    if change == "disabled":
        bot.is_active = False
    elif change == "platform":
        bot.platform = "email"
    elif change == "polling_imessage":
        bot.webhook_mode = False
    monkeypatch.setattr(
        channels, "get_adapter", lambda _: MagicMock(parse_incoming=lambda *_: None)
    )
    routed = AsyncMock()
    monkeypatch.setattr(channel_tasks, "_route_inbound", routed)
    await channel_tasks.process_channel_delivery(
        ChannelDelivery(
            organization_id=bot.organization_id, bot_id=bot.id, platform="imessage", payload={}
        )
    )
    routed.assert_not_awaited()


@pytest.mark.parametrize("kind", ["feedback", "next", "next_unavailable"])
async def test_numbered_channel_choices_reach_their_original_feedback_or_next_step(
    worker, monkeypatch, kind
):
    from app.services.channels import sms_prompts
    from app.services.channels.feedback import ChannelFeedback
    from app.services.channels.next_steps import ChannelNextSteps
    from app.services.channels.router import ChannelMessageRouter

    bot, db = worker
    incoming = IncomingMessage(
        platform="email",
        bot_id=str(bot.id),
        platform_user_id="ada@example.com",
        platform_chat_id="ada@example.com",
        chat_type="private",
        text="1",
        raw={},
    )
    value = (
        feedback_value(str(uuid4()), helpful=True)
        if kind == "feedback"
        else next_value(str(uuid4()), 0)
    )
    monkeypatch.setattr(sms_prompts, "answer", AsyncMock(return_value=value))
    rated, routed = AsyncMock(), AsyncMock()
    monkeypatch.setattr(ChannelFeedback, "rate", rated)
    monkeypatch.setattr(
        ChannelNextSteps,
        "take",
        AsyncMock(return_value=None if kind == "next_unavailable" else incoming),
    )
    monkeypatch.setattr(ChannelMessageRouter, "route", routed)
    await channel_tasks._route_inbound(incoming, db)
    assert rated.await_count == int(kind == "feedback")
    assert routed.await_count == int(kind == "next")


@pytest.mark.parametrize(
    "change", ["none", "missing", "inactive", "tenant", "platform", "generation"]
)
async def test_message_worker_rechecks_frozen_admission_before_routing(worker, monkeypatch, change):
    from app.core.exceptions import BadRequestError
    from app.repositories import channel_bot_repo
    from app.services.channels.steering import current_receipt
    from app.worker.jobs import ChannelMessage

    bot, db = worker
    bot.platform = "mattermost"
    bot.authorization_generation = uuid4()
    job = ChannelMessage(
        receipt_id=uuid4(),
        organization_id=bot.organization_id,
        bot_id=bot.id,
        authorization_generation=bot.authorization_generation,
        platform="mattermost",
        platform_user_id="alice",
        platform_chat_id="room:thread",
        chat_type="group",
        text="Hi",
        message_id="native",
    )
    if change == "missing":
        channel_bot_repo.get_for_inbound.return_value = None
    elif change == "inactive":
        bot.is_active = False
    elif change == "tenant":
        bot.organization_id = uuid4()
    elif change == "platform":
        bot.platform = "slack"
    elif change == "generation":
        bot.authorization_generation = uuid4()

    async def route(incoming, session):
        assert current_receipt() == job.receipt_id
        assert incoming.message_id == "native" and session is db

    routed = AsyncMock(side_effect=route)
    monkeypatch.setattr(channel_tasks, "_route_inbound", routed)
    if change in {"platform", "generation"}:
        with pytest.raises(BadRequestError):
            await channel_tasks.process_channel_message(job)
    else:
        await channel_tasks.process_channel_message(job)
    assert routed.await_count == int(change == "none")
    assert current_receipt() is None


@pytest.mark.parametrize("adapter_ok", [False, True])
async def test_discord_worker_restores_the_encrypted_interaction_reply_scope(
    worker, monkeypatch, adapter_ok
):
    from dataclasses import replace

    from app.services import channels
    from app.services.channels.discord import DiscordAdapter
    from app.services.channels.ingress import normalize

    bot, db = worker
    bot.platform = "discord"
    bot.authorization_generation = uuid4()
    incoming = IncomingMessage(
        platform="discord",
        bot_id=str(bot.id),
        platform_user_id="alice",
        platform_chat_id="room:thread",
        chat_type="group",
        text="/status",
        message_id="interaction",
        discord_interaction=("application", "private-token"),
    )
    adapter = DiscordAdapter() if adapter_ok else MagicMock()
    monkeypatch.setattr(channels, "get_adapter", lambda _: adapter)

    async def route(restored, session):
        assert restored.discord_interaction == ("application", "private-token")
        assert adapter._interactions.get("interaction") == ("application", "private-token")

    monkeypatch.setattr(channel_tasks, "_route_inbound", route)
    if adapter_ok:
        await channel_tasks.process_channel_message(normalize(bot, incoming))
        assert adapter._interactions.get("interaction") is None
        with adapter.restored_interaction(replace(incoming, discord_interaction=None)):
            assert adapter._interactions.get("interaction") is None
    else:
        with pytest.raises(RuntimeError, match="requires the Discord"):
            await channel_tasks.process_channel_message(normalize(bot, incoming))
