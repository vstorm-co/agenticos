"""The Google Calendar portal adapter - meetings about to start, read on a schedule.

See `_calendar` for why a calendar poll looks ahead rather than back. This reads
the account's primary calendar for the next `LONGEST_LEAD_MINUTES`, recurring
meetings expanded into their single occurrences, and keeps the meetings with
somebody else on them that the account has not declined.
"""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.services.portals import _calendar
from app.services.portals._api import TIMEOUT, get_json, nested
from app.services.portals._files import parse_time
from app.services.portals.base import NOWHERE, PolledEvents, PortalAdapter

_API_BASE = "https://www.googleapis.com/calendar/v3"


class GoogleCalendarPortalAdapter(PortalAdapter):
    portal_key = "google_calendar"

    async def poll(
        self,
        *,
        access_token: str,
        cursor: dict[str, Any] | None,
        places: Mapping[str, datetime] = NOWHERE,
    ) -> PolledEvents:
        """The meetings due an announcement for the leads in `places`.

        With no cursor this records whose calendar it is - the primary calendar's
        id is its owner's address - and announces nothing.
        """
        now = datetime.now(UTC)
        async with httpx.AsyncClient(base_url=_API_BASE, timeout=TIMEOUT) as client:
            if not cursor or not isinstance(cursor.get("account"), str):
                primary = await self._get(client, access_token, "/calendars/primary", {})
                account = str(primary.get("id") or "").casefold()
                return PolledEvents(events=(), cursor={"account": account, "announced": {}})
            watched = _calendar.leads(places)
            if not watched:
                return PolledEvents(events=(), cursor=cursor)
            listing = await self._get(
                client,
                access_token,
                "/calendars/primary/events",
                {
                    "timeMin": now.isoformat(),
                    "timeMax": (now + timedelta(minutes=max(watched))).isoformat(),
                    "singleEvents": "true",
                    "orderBy": "startTime",
                    "maxResults": "50",
                },
            )
        meetings = [
            meeting
            for item in listing.get("items") or []
            if (meeting := _meeting(item)) is not None
        ]
        events, announced = _calendar.announce(
            meetings,
            watched=watched,
            announced=cursor.get("announced") or {},
            account=cursor["account"],
            now=now,
            provider="gcal",
        )
        return PolledEvents(
            events=tuple(events), cursor={"account": cursor["account"], "announced": announced}
        )

    async def _get(
        self, client: httpx.AsyncClient, access_token: str, path: str, params: dict[str, str]
    ) -> dict[str, Any]:
        return await get_json(
            client,
            path,
            access_token=access_token,
            params=params,
            service="Google Calendar",
            portal_key=self.portal_key,
        )


def _meeting(item: Any) -> _calendar.Meeting | None:
    """A Google event as a meeting, or `None` for one that is not one to prepare for.

    Not one: cancelled, all day (a `date` rather than a `dateTime`), declined by
    the account, or with nobody but the account and its rooms on it.
    """
    if not isinstance(item, dict) or item.get("status") == "cancelled":
        return None
    start = nested(item, "start")
    end = nested(item, "end")
    starts_at = parse_time(start.get("dateTime"))
    identifier = item.get("iCalUID") or item.get("id")
    if starts_at is None or not isinstance(identifier, str):
        return None
    others: list[str] = []
    for attendee in item.get("attendees") or []:
        if not isinstance(attendee, dict):
            continue
        if attendee.get("self"):
            if attendee.get("responseStatus") == "declined":
                return None
            continue
        email = attendee.get("email")
        if isinstance(email, str) and email and not attendee.get("resource"):
            others.append(email.casefold())
    if not others:
        return None
    organizer = nested(item, "organizer")
    ends_at = parse_time(end.get("dateTime"))
    return _calendar.Meeting(
        meeting_id=identifier,
        subject=str(item.get("summary") or ""),
        starts_at=starts_at.astimezone(UTC),
        ends_at=ends_at.astimezone(UTC) if ends_at else None,
        organizer=str(organizer.get("email") or ""),
        attendees=tuple(others),
        join_url=_join_url(item),
        location=str(item.get("location") or ""),
        description=str(item.get("description") or ""),
        url=str(item.get("htmlLink") or ""),
    )


def _join_url(item: Mapping[str, Any]) -> str:
    """Where to join: Meet's link, else the conference's video entry point."""
    if isinstance(item.get("hangoutLink"), str):
        return item["hangoutLink"]
    conference = item.get("conferenceData")
    entries = conference.get("entryPoints") if isinstance(conference, dict) else None
    for entry in entries or []:
        if isinstance(entry, dict) and entry.get("entryPointType") == "video":
            return str(entry.get("uri") or "")
    return ""
