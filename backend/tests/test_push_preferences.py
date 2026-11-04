"""Session-scoped push policy, including delivery while the app is closed."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.exceptions import NotFoundError
from app.schemas.push import PushPreferencesUpdate
from app.services.push import PushService
from app.services.web_push import PushMessage, filtered_message

pytestmark = pytest.mark.anyio
NOW = datetime.now(UTC)
CONVERSATION = uuid4()
MESSAGE = PushMessage("Acme", "Private agent answer", f"/chat?id={CONVERSATION}", "notice")


def test_privacy_and_mute_are_applied_before_delivery() -> None:
    assert filtered_message(MESSAGE, None, now=NOW) == MESSAGE
    hidden = filtered_message(MESSAGE, {"hide_previews": True}, now=NOW)
    assert hidden is not None and "Private" not in hidden.body
    assert hidden.url == MESSAGE.url
    assert filtered_message(MESSAGE, {"muted_conversations": [str(CONVERSATION)]}, now=NOW) is None
    assert filtered_message(MESSAGE, {"muted_conversations": [str(uuid4())]}, now=NOW) == MESSAGE
    assert (
        filtered_message(
            PushMessage("Acme", "Test", "/settings/notifications", "test"),
            {"muted_conversations": [str(CONVERSATION)]},
            now=NOW,
        )
        is not None
    )


def test_focus_expires_and_does_not_suppress_another_conversation() -> None:
    focus = {
        "focused_conversation": str(CONVERSATION),
        "focus_until": (NOW + timedelta(seconds=90)).isoformat(),
    }
    assert filtered_message(MESSAGE, focus, now=NOW) is None
    assert filtered_message(MESSAGE, focus, now=NOW + timedelta(seconds=91)) == MESSAGE
    focus["focused_conversation"] = str(uuid4())
    assert filtered_message(MESSAGE, focus, now=NOW) == MESSAGE


def test_invalid_or_unbounded_conversation_preferences_are_rejected() -> None:
    with pytest.raises(ValidationError):
        PushPreferencesUpdate(muted_conversations=[uuid4() for _ in range(501)])
    with pytest.raises(ValidationError):
        PushPreferencesUpdate.model_validate({"muted_conversations": ["wrong"]})


async def test_preferences_belong_to_the_callers_sign_in() -> None:
    user, session = uuid4(), uuid4()
    service = PushService(AsyncMock())
    with patch(
        "app.services.push.session_repo.push_preferences_for",
        new=AsyncMock(return_value={session: {"hide_previews": True}}),
    ) as read:
        assert (await service.preferences(user, session)).hide_previews
        assert read.await_args.kwargs == {"user_id": user, "session_ids": [session]}
    with patch(
        "app.services.push.session_repo.update_push_preferences", new=AsyncMock(return_value=True)
    ) as update:
        await service.set_preferences(user, session, PushPreferencesUpdate(hide_previews=True))
        assert update.await_args.kwargs["user_id"] == user
        assert update.await_args.kwargs["session_id"] == session
        assert "focus_until" not in update.await_args.kwargs["patch"]
        await service.focus(user, session, CONVERSATION)
        assert update.await_args.kwargs["patch"]["focused_conversation"] == str(CONVERSATION)
        await service.focus(user, session, None)
        assert update.await_args.kwargs["patch"]["focus_until"] is None
    with pytest.raises(NotFoundError):
        await service.preferences(user, None)
    with pytest.raises(NotFoundError):
        await service.set_preferences(user, None, PushPreferencesUpdate())
    with patch(
        "app.services.push.session_repo.update_push_preferences", new=AsyncMock(return_value=False)
    ):
        with pytest.raises(NotFoundError):
            await service.focus(user, session, CONVERSATION)
        with pytest.raises(NotFoundError):
            await service.set_preferences(user, session, PushPreferencesUpdate())
