"""Routine delivery can narrow, but never expand, a person's channel preferences."""

from typing import Literal

from pydantic import TypeAdapter

ExternalNotificationChannel = Literal[
    "email", "push", "slack", "telegram", "mattermost", "teams", "sms", "imessage", "discord"
]
WatchReportMode = Literal["changes", "every_check"]


_CHANNELS = TypeAdapter(list[ExternalNotificationChannel] | None)
_REPORT_MODE = TypeAdapter(WatchReportMode)


def read_channels(value: object) -> list[ExternalNotificationChannel] | None:
    return _CHANNELS.validate_python(value)


def read_report_mode(value: object) -> WatchReportMode:
    return _REPORT_MODE.validate_python(value)
