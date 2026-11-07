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
