"""What the two calendar portals share: announcing a meeting once, a set time before it.

A calendar trigger fires *before* something rather than when something
happened, so a poll does not ask "what changed" but "what starts within the
longest lead any trigger watches". Each trigger's lead in minutes is the place
it watches (`trigger_events.polled_place`), so the adapter knows which leads
exist without knowing the triggers: a meeting is announced for a lead the first
tick it is that close or closer, and the announcement is recorded in the
grant's cursor - committed with the fires - so it fires once whatever the
dedupe cache remembers. A meeting booked inside the lead is announced at once;
one moved to another time is a new announcement, because its key includes the
start.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.services.portals.base import PolledEvent

LONGEST_LEAD_MINUTES = 120
_MAX_DESCRIPTION_CHARS = 4000


@dataclass(frozen=True)
class Meeting:
    """One meeting with somebody else on it, as either provider describes it."""

    meeting_id: str
    subject: str
    starts_at: datetime
    ends_at: datetime | None
    organizer: str
    attendees: tuple[str, ...]
    join_url: str
    location: str
    description: str
    url: str


def leads(places: Mapping[str, datetime]) -> list[int]:
    """The lead times the organization's triggers watch, from their place keys."""
    return sorted(
        {int(key) for key in places if key.isdigit() and 0 < int(key) <= LONGEST_LEAD_MINUTES}
    )


def domain_of(address: str) -> str:
    return address.rpartition("@")[2].casefold()


def announce(
    meetings: list[Meeting],
    *,
    watched: list[int],
    announced: Mapping[str, Any],
    account: str,
    now: datetime,
    provider: str,
) -> tuple[list[PolledEvent], dict[str, str]]:
    """The announcements due now, and the record the cursor keeps of them.

    `account` is the calendar owner's address; an attendee at any other domain
    is external. The record drops meetings that have started, so it holds only
    what is still ahead.
    """
    record: dict[str, str] = {
        key: start
        for key, start in announced.items()
        if isinstance(start, str) and start > now.isoformat()
    }
    own = domain_of(account)
    events: list[PolledEvent] = []
    for meeting in meetings:
        until = (meeting.starts_at - now) / timedelta(minutes=1)
        if until <= 0:
            continue
        for lead in watched:
            key = f"{meeting.meeting_id}|{meeting.starts_at.isoformat()}|{lead}"
            if until > lead or key in record:
                continue
            record[key] = meeting.starts_at.isoformat()
            events.append(
                PolledEvent(
                    delivery_id=f"{provider}:{key}",
                    payload={
                        "meeting_id": meeting.meeting_id,
                        "subject": meeting.subject,
                        "starts_at": meeting.starts_at.isoformat(),
                        "ends_at": meeting.ends_at.isoformat() if meeting.ends_at else None,
                        "minutes_until_start": round(until),
                        "lead_minutes": lead,
                        "organizer": meeting.organizer,
                        "attendees": list(meeting.attendees),
                        "external_attendees": [
                            address
                            for address in meeting.attendees
                            if own and domain_of(address) != own
                        ],
                        "join_url": meeting.join_url,
                        "location": meeting.location,
                        "description": meeting.description[:_MAX_DESCRIPTION_CHARS],
                        "url": meeting.url,
                    },
                )
            )
    return events, record
