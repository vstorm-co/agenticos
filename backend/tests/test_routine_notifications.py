"""Routine delivery limits never enable a channel or change another recipient's choice."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.db.models.notification import NotificationChannel
from app.services.routine_notifications import allowed_channels, channels

pytestmark = pytest.mark.anyio
MODULE = "app.services.routine_notifications"


@pytest.mark.parametrize(
    ("selection", "expected"),
    [
        (None, None),
        ([], {NotificationChannel.IN_APP}),
        (["email"], {NotificationChannel.IN_APP, NotificationChannel.EMAIL}),
        (
            ["push", "email"],
            {NotificationChannel.IN_APP, NotificationChannel.EMAIL, NotificationChannel.PUSH},
        ),
        (
            ["sms", "slack"],
            {NotificationChannel.IN_APP, NotificationChannel.SMS, NotificationChannel.SLACK},
        ),
    ],
)
def test_channel_selection_only_narrows_inherited_preferences(selection, expected):
    assert channels(selection) == expected


@pytest.mark.parametrize(
    "context",
    [
        None,
        {},
        {"routine_origin_id": None},
        {"routine_origin_id": "invalid", "routine_kind": "watch"},
        {"routine_origin_id": str(uuid4()), "routine_kind": {}},
        {"routine_origin_id": 123, "routine_kind": "trigger"},
    ],
)
async def test_absent_context_inherits_and_malformed_references_cannot_enable_delivery(context):
    result = await allowed_channels(
        MagicMock(), organization_id=uuid4(), recipient_user_id=uuid4(), context=context
    )
    assert result == (None if context is None or context == {} else set())


@pytest.mark.parametrize("kind", ["watch", "trigger"])
@pytest.mark.parametrize(
    "change",
    [
        "inherit",
        "disabled",
        "email",
        "paused",
        "expired",
        "future",
        "gone",
        "tenant",
        "other-recipient",
    ],
)
async def test_live_routine_state_limits_only_its_own_person(kind, change):
    owner, org, identifier = uuid4(), uuid4(), uuid4()
    selected = [] if change == "disabled" else ["email"] if change == "email" else None
    row = MagicMock(
        user_id=owner,
        created_by_user_id=owner,
        organization_id=uuid4() if change == "tenant" else org,
        is_active=change != "paused",
        ends_at=datetime.now(UTC) + timedelta(days=1)
        if change == "future"
        else datetime.now(UTC) - timedelta(days=1)
        if change == "expired"
        else None,
        notification_channels=selected,
    )
    repo = "watch_repo" if kind == "watch" else "agent_trigger_repo"
    with patch(
        f"{MODULE}.{repo}.get_by_id", new=AsyncMock(return_value=None if change == "gone" else row)
    ):
        actual = await allowed_channels(
            MagicMock(),
            organization_id=org,
            recipient_user_id=uuid4() if change == "other-recipient" else owner,
            context={"routine_origin_id": str(identifier), "routine_kind": kind},
        )
    expected = (
        set()
        if change in {"gone", "tenant"}
        else {NotificationChannel.IN_APP}
        if change in {"disabled", "paused", "expired"}
        else {NotificationChannel.IN_APP, NotificationChannel.EMAIL}
        if change == "email"
        else None
    )
    assert actual == expected


@pytest.mark.parametrize("kind", ["watch", "trigger"])
@pytest.mark.parametrize(
    "state", ["current", "resumed", "changed", "expired", "ordinary", "wrong-reason"]
)
async def test_only_the_current_automatic_pause_notice_can_cross_a_paused_routine(
    kind: str, state: str
) -> None:
    stopped = datetime.now(UTC)
    owner, organization, identifier = uuid4(), uuid4(), uuid4()
    row = MagicMock(
        user_id=owner,
        created_by_user_id=owner,
        organization_id=organization,
        is_active=state == "resumed",
        auto_stopped_at=None if state == "resumed" else stopped,
        notification_channels=["telegram"],
        ends_at=stopped - timedelta(seconds=1) if state == "expired" else None,
    )
    context: dict[str, object] = {
        "routine_kind": kind,
        "routine_origin_id": str(identifier),
        "routine_failure_reason": "run",
    }
    if state != "ordinary":
        context["routine_auto_stopped_at"] = (
            stopped - timedelta(seconds=1) if state == "changed" else stopped
        ).isoformat()
    if state == "wrong-reason":
        context["routine_failure_reason"] = "delivery"
    repo = "watch_repo" if kind == "watch" else "agent_trigger_repo"
    with patch(f"{MODULE}.{repo}.get_by_id", new=AsyncMock(return_value=row)):
        result = await allowed_channels(
            MagicMock(), organization_id=organization, recipient_user_id=owner, context=context
        )
    expected = (
        {NotificationChannel.IN_APP, NotificationChannel.TELEGRAM}
        if state == "current"
        else {NotificationChannel.IN_APP}
    )
    assert result == expected
