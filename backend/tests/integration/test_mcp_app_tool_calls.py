"""Finding the stored call an MCP Apps page belongs to, against real rows (#3450).

A page is read through the call it was shown with, so the lookups decide which
connection a page reaches: a `WHERE` that matched a call in another conversation,
or one stored without a page, would hand a page another call's connection.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.db.models.conversation import Conversation, Message, ToolCall
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import conversation as conversation_repo

pytestmark = pytest.mark.anyio

_START = datetime(2026, 11, 26, 9, 0, tzinfo=UTC)


def _record(marker: str) -> dict[str, object]:
    return {
        "resource_uri": f"ui://charts/{marker}.html",
        "tool_input": {},
        "result": {"content": [], "isError": False},
        "connection_id": str(uuid.uuid4()),
        "tool_name": "data_query",
        "allowed_tools": None,
        "approval": "writes",
        "tool_approval": {},
    }


async def _conversation(db) -> Conversation:
    user = User(id=uuid.uuid4(), email=f"{uuid.uuid4().hex}@example.com", hashed_password="x")
    db.add(user)
    await db.flush()
    organization = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=user.id,
    )
    db.add(organization)
    await db.flush()
    conversation = Conversation(id=uuid.uuid4(), user_id=user.id, organization_id=organization.id)
    db.add(conversation)
    await db.flush()
    return conversation


async def _call(
    db, conversation: Conversation, *, at: datetime, mcp_app: dict[str, object] | None
) -> ToolCall:
    message = Message(
        id=uuid.uuid4(),
        conversation_id=conversation.id,
        role="assistant",
        content="",
        created_at=at,
    )
    db.add(message)
    await db.flush()
    return await conversation_repo.create_tool_call(
        db,
        message_id=message.id,
        tool_call_id="toolu_01",
        tool_name="charts_data_query",
        args={},
        started_at=at,
        mcp_app=mcp_app,
    )


async def test_the_newest_call_with_a_page_in_this_conversation_is_found(db) -> None:
    conversation = await _conversation(db)
    other = await _conversation(db)
    await _call(db, conversation, at=_START, mcp_app=_record("older"))
    newest = await _call(
        db, conversation, at=_START + timedelta(minutes=2), mcp_app=_record("newer")
    )
    await _call(db, conversation, at=_START + timedelta(minutes=3), mcp_app=None)
    await _call(db, other, at=_START + timedelta(minutes=4), mcp_app=_record("elsewhere"))

    found = await conversation_repo.get_app_tool_call(
        db, conversation_id=conversation.id, tool_call_id="toolu_01"
    )

    assert found is not None
    assert found.id == newest.id
    assert found.mcp_app == _record("newer") | {"connection_id": newest.mcp_app["connection_id"]}


async def test_a_call_stored_without_a_page_is_not_one_to_read_a_page_through(db) -> None:
    conversation = await _conversation(db)
    plain = await _call(db, conversation, at=_START, mcp_app=None)

    assert (
        await conversation_repo.get_app_tool_call(
            db, conversation_id=conversation.id, tool_call_id="toolu_01"
        )
        is None
    )
    assert await conversation_repo.get_app_tool_call_by_id(db, plain.id) is None


async def test_a_call_with_a_page_is_found_by_its_row(db) -> None:
    conversation = await _conversation(db)
    shown = await _call(db, conversation, at=_START, mcp_app=_record("page"))

    found = await conversation_repo.get_app_tool_call_by_id(db, shown.id)

    assert found is not None and found.id == shown.id
