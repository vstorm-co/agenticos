"""Mentions notify only tagged people and open the exact retained message."""

from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest

from app.db.models.notification import NotificationChannel, NotificationEventType
from app.services.notification_catalog import ContentGate, content_gate_for, is_mandatory
from app.services.notifications import NotificationService

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("in_thread", [False, True])
async def test_person_mention_has_scoped_dedupe_and_exact_message_link(monkeypatch, in_thread):
    recipient, actor, org, room, message = (uuid4() for _ in range(5))
    root = uuid4() if in_thread else None
    service = NotificationService(MagicMock())
    write = AsyncMock(return_value=[])
    monkeypatch.setattr(service._center, "write", write)
    await service.room_mentioned(
        recipients=[recipient, actor, recipient],
        organization_id=org,
        conversation_id=room,
        message_id=message,
        thread_root_message_id=root,
        title="Design room",
        sender="Alex",
        actor_user_id=actor,
    )
    values = write.await_args.kwargs
    assert values["recipients"] == [recipient]
    assert values["event_type"] is NotificationEventType.ROOM_MENTION
    assert values["occurrence_id"] == str(message)
    assert values["organization_id"] == org
    assert values["channels"] == {NotificationChannel.IN_APP, NotificationChannel.PUSH}
    assert values["use_savepoint"] is True
    assert "mentioned" in values["summary"]
    assert values["render_context"] == {
        "wording": "room_mention",
        "resource_kind": "conversation",
        "resource_id": str(room),
        "conversation_id": str(room),
        "message_id": str(message),
        "thread_root_message_id": str(root) if root is not None else None,
        "sender": "Alex",
        "title": "Design room",
    }
    link = urlsplit(values["context_url"])
    assert link.path == "/chat"
    query = parse_qs(link.query)
    assert query == {
        "id": [str(room)],
        "message": [str(message)],
        "org": [str(org)],
        **({"thread": [str(root)]} if root is not None else {}),
    }
    assert content_gate_for(NotificationEventType.ROOM_MENTION) is ContentGate.SHARED_CONVERSATION
    assert not is_mandatory(NotificationEventType.ROOM_MENTION)


async def test_self_mentions_do_not_generate_an_inbox_row(monkeypatch):
    actor = uuid4()
    service = NotificationService(MagicMock())
    write = AsyncMock()
    monkeypatch.setattr(service._center, "write", write)
    await service.room_mentioned(
        recipients=[actor],
        organization_id=uuid4(),
        conversation_id=uuid4(),
        message_id=uuid4(),
        thread_root_message_id=None,
        title=None,
        sender="Me",
        actor_user_id=actor,
    )
    write.assert_not_awaited()


async def test_a_thread_reply_notifies_each_follower_once_and_never_the_author(monkeypatch):
    follower, actor, org, room, message, root = (uuid4() for _ in range(6))
    service = NotificationService(MagicMock())
    write = AsyncMock(return_value=[])
    monkeypatch.setattr(service._center, "write", write)
    await service.room_thread_replied(
        recipients=[follower, actor, follower],
        organization_id=org,
        conversation_id=room,
        message_id=message,
        thread_root_message_id=root,
        title=None,
        sender="Alex",
        actor_user_id=actor,
    )
    values = write.await_args.kwargs
    assert values["recipients"] == [follower]
    assert values["event_type"] is NotificationEventType.ROOM_THREAD_REPLY
    assert values["occurrence_id"] == str(message)
    assert values["summary"] == "Alex replied in a thread in 'a conversation'."
    assert values["render_context"]["thread_root_message_id"] == str(root)
    assert values["render_context"]["title"] == "a conversation"
    query = parse_qs(urlsplit(values["context_url"]).query)
    assert query == {
        "id": [str(room)],
        "message": [str(message)],
        "thread": [str(root)],
        "org": [str(org)],
    }


async def test_a_thread_reply_by_its_only_follower_generates_no_inbox_row(monkeypatch):
    actor = uuid4()
    service = NotificationService(MagicMock())
    write = AsyncMock()
    monkeypatch.setattr(service._center, "write", write)
    await service.room_thread_replied(
        recipients=[actor, actor],
        organization_id=uuid4(),
        conversation_id=uuid4(),
        message_id=uuid4(),
        thread_root_message_id=uuid4(),
        title="Design room",
        sender="Me",
        actor_user_id=actor,
    )
    write.assert_not_awaited()
