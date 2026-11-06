"""The request and read contracts must accept every selected delivery channel."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import BaseModel, ValidationError

from app.schemas.agent_trigger import TriggerCreate, TriggerRead, TriggerUpdate
from app.schemas.watch import WatchCreate, WatchRead, WatchUpdate

CHANNELS = [
    "email",
    "push",
    "slack",
    "telegram",
    "mattermost",
    "teams",
    "sms",
    "imessage",
    "discord",
]
NOW = datetime(2026, 11, 3, tzinfo=UTC)

CASES: list[tuple[type[BaseModel], dict[str, object]]] = [
    (TriggerCreate, {"prompt": "Prepare reports", "interval_seconds": 300}),
    (TriggerUpdate, {}),
    (
        TriggerRead,
        {
            "id": uuid4(),
            "agent_id": uuid4(),
            "created_at": NOW,
            "is_active": True,
            "trigger_type": "schedule",
            "schedule_kind": "interval",
            "interval_seconds": 300,
            "prompt": "Prepare reports",
        },
    ),
    (
        WatchCreate,
        {
            "agent_id": uuid4(),
            "connection_id": uuid4(),
            "title": "Invoices",
            "instructions": "Read pending invoices",
            "interval_minutes": 60,
        },
    ),
    (WatchUpdate, {}),
    (
        WatchRead,
        {
            "id": uuid4(),
            "connection_id": uuid4(),
            "connection_name": "Work",
            "server": "mail",
            "preset_key": None,
            "title": "Invoices",
            "instructions": "Read pending invoices",
            "exclusions": [],
            "urgent": False,
            "interval_minutes": 60,
            "is_active": True,
            "next_run_at": NOW,
            "last_run_at": None,
            "created_at": NOW,
        },
    ),
]


@pytest.mark.parametrize("schema,payload", CASES)
@pytest.mark.parametrize("selected", [CHANNELS, ["sms", "teams", "telegram"], [], None])
def test_all_selected_channels_survive_request_and_read_serialization(
    schema: type[BaseModel], payload: dict[str, object], selected: list[str] | None
) -> None:
    parsed = schema.model_validate({**payload, "notification_channels": selected})
    assert parsed.model_dump(mode="json")["notification_channels"] == selected


@pytest.mark.parametrize("schema,payload", CASES)
def test_channel_selection_is_bounded_and_rejects_unknown_transports(
    schema: type[BaseModel], payload: dict[str, object]
) -> None:
    for invalid in ([*CHANNELS, "sms"], ["not-a-platform"]):
        with pytest.raises(ValidationError):
            schema.model_validate({**payload, "notification_channels": invalid})
