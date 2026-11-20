"""A room or a shared chat replays visible turns, not another author's private tools."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from pydantic_ai.messages import (
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from app.db.models.conversation import Message, ToolCall
from app.db.models.user import User
from app.repositories import conversation_repo, conversation_share_repo
from app.services.channels.router import ChannelMessageRouter
from app.services.conversation import ConversationService
from tests.test_history_discovery import StoredThread
from tests.test_history_discovery import thread as thread

pytestmark = pytest.mark.anyio


def hidden_exchange() -> list[ModelRequest | ModelResponse]:
    return [
        ModelRequest(parts=[UserPromptPart("Check my calendar")]),
        ModelResponse(
            parts=[ToolCallPart("personal_calendar_list_events", {}, tool_call_id="private-1")]
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    "personal_calendar_list_events",
                    "PRIVATE_EVENT_THERAPY",
                    tool_call_id="private-1",
                )
            ]
        ),
        ModelResponse(parts=[TextPart("You have an appointment.")]),
    ]


@pytest.mark.security
@pytest.mark.parametrize(
    "scope", ["group", "unknown-room", "project", "edit-share", "revoked-share"]
)
async def test_another_author_cannot_replay_hidden_personal_tool_data(
    thread: StoredThread, scope: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, other = uuid4(), uuid4()
    thread.conversation.user_id = owner
    monkeypatch.setattr(conversation_share_repo, "has_edit_share", AsyncMock(return_value=False))
    monkeypatch.setattr(conversation_repo, "has_non_owner_author", AsyncMock(return_value=False))
    await thread.save(hidden_exchange())
    if scope == "project":
        thread.conversation.project_id = uuid4()
    elif scope == "edit-share":
        monkeypatch.setattr(conversation_share_repo, "has_edit_share", AsyncMock(return_value=True))
    elif scope == "revoked-share":
        monkeypatch.setattr(conversation_repo, "has_non_owner_author", AsyncMock(return_value=True))
    elif scope in {"group", "unknown-room"}:
        monkeypatch.setattr(
            conversation_repo, "has_shared_channel_history", AsyncMock(return_value=True)
        )
    started = datetime.now(UTC)
    calls = [
        ToolCall(
            tool_call_id=f"call-{number}",
            tool_name=name,
            status=status,
            started_at=started,
            args={"private_calendar_id": "PRIVATE_ARGUMENT"},
            result="PRIVATE_EVENT_THERAPY",
        )
        for number, (name, status) in enumerate(
            [
                ("query_virtual_table", "completed"),
                ("update_virtual_table_record", "completed"),
                ("update_virtual_table_record", "completed"),
                ("update_virtual_table_record", "awaiting_approval"),
                ("update_virtual_table_record", "failed"),
            ]
        )
    ]
    rows = [
        Message(
            id=uuid4(), ordinal=1, role="user", content="Check my calendar", author_user_id=owner
        ),
        Message(
            id=uuid4(),
            ordinal=2,
            role="assistant",
            content="You have an appointment.",
            parts=[{"type": "tool", "tool_call_id": call.tool_call_id} for call in calls],
            tool_calls=list(reversed(calls)),
        ),
        Message(
            id=uuid4(),
            ordinal=3,
            role="user",
            content="I am another participant",
            author_user_id=other,
        ),
    ]
    monkeypatch.setattr(conversation_repo, "get_recent_messages", AsyncMock(return_value=rows))
    monkeypatch.setattr(conversation_repo, "messages_by_id", AsyncMock(return_value={}))
    authors = {
        owner: User(id=owner, full_name="Mira", email="mira@example.test"),
        other: User(id=other, full_name="Teo", email="teo@example.test"),
    }
    monkeypatch.setattr(conversation_repo, "users_by_id", AsyncMock(return_value=authors))
    if scope in {"group", "unknown-room"}:
        history = await ChannelMessageRouter._load_history(
            thread.service.db, thread.conversation.id, chat_type=scope
        )
    else:
        history = await thread.service.model_history(thread.conversation.id, limit=50)
    encoded = ModelMessagesTypeAdapter.dump_json(history).decode()
    assert "PRIVATE_EVENT_THERAPY" not in encoded
    assert "PRIVATE_ARGUMENT" not in encoded
    assert "personal_calendar_list_events" not in encoded
    note = (
        "query_virtual_table (completed), update_virtual_table_record (2 calls, completed), "
        "update_virtual_table_record (awaiting_approval), update_virtual_table_record (failed)"
    )
    assert note in encoded
    again = await thread.service.model_history(thread.conversation.id, limit=50)
    assert [
        part.content
        for turn in history
        for part in turn.parts
        if isinstance(part, (TextPart, UserPromptPart))
    ] == [
        part.content
        for turn in again
        for part in turn.parts
        if isinstance(part, (TextPart, UserPromptPart))
    ]
    assert "Mira: Check my calendar" in encoded
    assert "You have an appointment." in encoded
    assert "Teo: I am another participant" in encoded
    assert history.revision == 0


@pytest.mark.security
async def test_a_private_direct_message_retains_its_own_tool_evidence(
    thread: StoredThread, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(conversation_share_repo, "has_edit_share", AsyncMock(return_value=False))
    await thread.save(hidden_exchange())
    history = await ChannelMessageRouter._load_history(
        thread.service.db, thread.conversation.id, chat_type="private"
    )
    assert "PRIVATE_EVENT_THERAPY" in ModelMessagesTypeAdapter.dump_json(history).decode()


@pytest.mark.security
async def test_a_room_runner_does_not_checkpoint_private_tool_results() -> None:
    from unittest.mock import MagicMock

    from app.services.agent_runner import AgentRunnerService
    from tests.test_agent_runner import _ctx, _db, _prepared

    service = AgentRunnerService(_db())
    prepared = _prepared(conversation_id=uuid4())
    prepared.shared_history = True
    result = MagicMock(output="You have an appointment.")
    result.all_messages = MagicMock(return_value=hidden_exchange())
    result.new_messages = MagicMock(return_value=hidden_exchange())
    prepared.built.agent.run = AsyncMock(return_value=result)
    with (
        patch.object(service, "prepare", AsyncMock(return_value=prepared)),
        patch("app.services.agent_runner.agent_run_repo.finish_run", AsyncMock()),
        patch.object(service.transcript, "record", AsyncMock()),
        patch("app.services.agent_runner.ConversationService") as conversations,
    ):
        conversations.return_value.history_for_provenance = ConversationService(
            service.db
        ).history_for_provenance
        conversations.return_value.keep_overhead = AsyncMock()
        conversations.return_value.keep_reminder_state = AsyncMock()
        conversations.return_value.keep_plan = AsyncMock()
        conversations.return_value.keep_summary = AsyncMock()
        await service.execute(_ctx(), uuid4(), "Check my calendar")
    conversations.return_value.keep_summary.assert_not_awaited()
