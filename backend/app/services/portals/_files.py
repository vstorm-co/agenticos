"""What the two file portals share: which changes are news, and how one is described.

**A file being edited is one event, not one a minute.** Google Docs saves as
somebody types and OneDrive's delta reports every save, so a document open for
an hour would change on every tick and fire an agent sixty times. A change is
news when the file is new, or when it was last announced more than
`SETTLE` ago; what the poller announced, and when, rides in the grant's cursor -
committed with the fires, so a crash re-reads rather than forgets it.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.services.portals.base import PolledEvent

SETTLE = timedelta(minutes=30)
# How many changed files one tick turns into events. A folder synced in bulk
# between two ticks must not become hundreds of agent runs; past this the most
# recently changed are taken and the cursor still advances.
MAX_FILES_PER_POLL = 25


@dataclass(frozen=True)
class ChangedFile:
    """One file as the poller saw it, before it is decided whether it is news."""

    provider: str
    file_id: str
    name: str
    mime_type: str
    created_at: datetime
    modified_at: datetime
    url: str
    modified_by: str
    by_account: bool
    location: dict[str, Any]


def parse_time(value: Any) -> datetime | None:
    """An ISO timestamp from a provider, as an aware datetime, or `None`."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def news(
    changed: list[ChangedFile], *, announced: Mapping[str, Any], now: datetime
) -> tuple[list[PolledEvent], dict[str, str]]:
    """The events among `changed`, and what the cursor records as announced.

    A file created within a minute of its last change is `created`; any other is
    `modified`, and is held back while the same file was announced within
    `SETTLE`. The record keeps only what is still inside the window, so it stays
    the size of the recent activity rather than of the drive.
    """
    record: dict[str, str] = {
        file_id: stamp
        for file_id, stamp in announced.items()
        if isinstance(stamp, str)
        and (when := parse_time(stamp)) is not None
        and now - when < SETTLE
    }
    latest: dict[str, ChangedFile] = {}
    for item in changed:
        kept = latest.get(item.file_id)
        if kept is None or item.modified_at > kept.modified_at:
            latest[item.file_id] = item
    events: list[PolledEvent] = []
    for item in sorted(latest.values(), key=lambda one: one.modified_at)[-MAX_FILES_PER_POLL:]:
        created = item.modified_at - item.created_at < timedelta(minutes=1)
        if not created and item.file_id in record:
            continue
        record[item.file_id] = now.isoformat()
        events.append(
            PolledEvent(
                delivery_id=f"{item.provider}:{item.file_id}:{item.modified_at.isoformat()}",
                payload={
                    "file_id": item.file_id,
                    "name": item.name,
                    "mime_type": item.mime_type,
                    "change": "created" if created else "modified",
                    "created_at": item.created_at.isoformat(),
                    "modified_at": item.modified_at.isoformat(),
                    "url": item.url,
                    "modified_by": item.modified_by,
                    "by_account": item.by_account,
                    **item.location,
                },
            )
        )
    return events, record
