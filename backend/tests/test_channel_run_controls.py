"""Only the admitted sender's own root run can be inspected or stopped."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.repositories import agent_run_repo, channel_session_repo, member_repo
from app.services.channels.base import IncomingMessage
from app.services.channels.router import ChannelMessageRouter

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    "command,status", [("status", "running"), ("stop", "running"), ("stop", "completed")]
)
async def test_control_is_scoped_to_the_same_conversation_and_native_identity(
    monkeypatch, command, status
):
    org, identity, conversation = uuid4(), uuid4(), uuid4()
    bot = SimpleNamespace(id=uuid4(), organization_id=org)
    incoming = IncomingMessage(
        platform="mattermost",
        bot_id=str(bot.id),
        platform_user_id="alice",
        platform_chat_id="room:thread",
        chat_type="group",
        text=command,
    )
    run = SimpleNamespace(id=uuid4(), status=status)
    monkeypatch.setattr(
        channel_session_repo,
        "get_by_bot_and_chat",
        AsyncMock(return_value=SimpleNamespace(conversation_id=conversation)),
    )
    latest = AsyncMock(return_value=run)
    stop = AsyncMock()
    monkeypatch.setattr(agent_run_repo, "latest_for_channel_sender", latest)
    monkeypatch.setattr(agent_run_repo, "request_channel_stop", stop)
    db = MagicMock(commit=AsyncMock())
    result = await ChannelMessageRouter()._handle_command(
        command, incoming, bot, db, SimpleNamespace(id=identity, user_id=None), True
    )
    assert result
    assert latest.await_args.kwargs == {
        "organization_id": org,
        "conversation_id": conversation,
        "identity_id": identity,
        "prefer_running": command == "stop",
    }
    assert stop.await_count == int(command == "stop" and status == "running")
    assert db.commit.await_count == stop.await_count


async def test_offboarded_sender_cannot_read_or_stop_their_old_run(monkeypatch):
    router = ChannelMessageRouter()
    monkeypatch.setattr(member_repo, "get_active", AsyncMock(return_value=None))
    invite = AsyncMock(return_value="Link your account")
    monkeypatch.setattr(router, "_invite_to_link", invite)
    latest = AsyncMock()
    monkeypatch.setattr(agent_run_repo, "latest_for_channel_sender", latest)
    assert (
        await router._handle_command(
            "/stop",
            MagicMock(),
            SimpleNamespace(organization_id=uuid4()),
            MagicMock(),
            SimpleNamespace(user_id=uuid4()),
            False,
        )
        == "Link your account"
    )
    latest.assert_not_awaited()


@pytest.mark.parametrize(
    "text,control",
    [
        ("stop", True),
        ("status", True),
        ("/stop@bot", True),
        ("/status@bot", True),
        ("stop and think", False),
        ("/new", False),
        ("hello", False),
    ],
)
def test_native_command_suffixes_keep_the_control_lane(text, control):
    from app.services.channels.base import is_run_control

    assert is_run_control(text) is control


@pytest.mark.parametrize("session", [False, True])
async def test_a_sender_without_a_task_receives_an_explicit_result(monkeypatch, session):
    monkeypatch.setattr(
        channel_session_repo,
        "get_by_bot_and_chat",
        AsyncMock(return_value=SimpleNamespace(conversation_id=uuid4()) if session else None),
    )
    monkeypatch.setattr(agent_run_repo, "latest_for_channel_sender", AsyncMock(return_value=None))
    result = await ChannelMessageRouter()._handle_command(
        "status",
        SimpleNamespace(platform_chat_id="room:thread"),
        SimpleNamespace(id=uuid4(), organization_id=uuid4()),
        MagicMock(),
        SimpleNamespace(id=uuid4(), user_id=None),
        True,
    )
    assert result == "You have no task in this thread."
