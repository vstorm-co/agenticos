"""The Outlook Calendar portal adapter - meetings about to start, read on a schedule.

See `_calendar` for why a calendar poll looks ahead rather than back. This reads
the account's default calendar through `calendarView`, which expands recurring
meetings into their occurrences, with times asked for in UTC so nothing here
converts a Windows zone name.
"""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.services.portals import _calendar
from app.services.portals._api import TIMEOUT, get_json, nested
from app.services.portals._files import parse_time
from app.services.portals.base import NOWHERE, PolledEvents, PortalAdapter
from app.services.portals.exceptions import PortalUnreachable

_API_BASE = "https://graph.microsoft.com/v1.0"
_FIELDS = (
    "id,iCalUId,subject,start,end,isCancelled,isAllDay,responseStatus,attendees,"
    "organizer,onlineMeeting,location,bodyPreview,webLink"
)


class OutlookCalendarPortalAdapter(PortalAdapter):
    portal_key = "outlook_calendar"

    async def poll(
        self,
        *,
        access_token: str,
        cursor: dict[str, Any] | None,
        places: Mapping[str, datetime] = NOWHERE,
    ) -> PolledEvents:
        """The meetings due an announcement for the leads in `places`.

        With no cursor this records whose calendar it is - its owner's address,
        readable with `Calendars.Read` alone - and announces nothing.
        """
        now = datetime.now(UTC)
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            if not cursor or not isinstance(cursor.get("account"), str):
                calendar = await self._get(
                    client, access_token, f"{_API_BASE}/me/calendar", {"$select": "id,owner"}
                )
                owner = nested(calendar, "owner")
                account = str(owner.get("address") or "").casefold()
                return PolledEvents(events=(), cursor={"account": account, "announced": {}})
            watched = _calendar.leads(places)
            if not watched:
                return PolledEvents(events=(), cursor=cursor)
            params: dict[str, str] | None = {
                "startDateTime": now.isoformat(),
                "endDateTime": (now + timedelta(minutes=max(watched))).isoformat(),
                "$select": _FIELDS,
                "$orderby": "start/dateTime",
                "$top": "1000",
            }
            url = f"{_API_BASE}/me/calendarView"
            meetings: list[_calendar.Meeting] = []
            for _ in range(10):
                listing = await self._get(client, access_token, url, params)
                meetings.extend(
                    meeting
                    for item in listing.get("value") or []
                    if (meeting := _meeting(item, account=cursor["account"])) is not None
                )
                following = listing.get("@odata.nextLink")
                if not isinstance(following, str) or not following:
                    break
                if not following.startswith(_API_BASE + "/"):
                    raise PortalUnreachable(message="Microsoft Graph returned an invalid page URL")
                url, params = following, None
            else:
                raise PortalUnreachable(message="Outlook Calendar pagination limit reached")
        events, announced = _calendar.announce(
            meetings,
            watched=watched,
            announced=cursor.get("announced") or {},
            account=cursor["account"],
            now=now,
            provider="outlookcal",
        )
        return PolledEvents(
            events=tuple(events), cursor={"account": cursor["account"], "announced": announced}
        )

    async def _get(
        self, client: httpx.AsyncClient, access_token: str, url: str, params: dict[str, str] | None
    ) -> dict[str, Any]:
        return await get_json(
            client,
            url,
            access_token=access_token,
            params=params,
            service="Microsoft Graph",
            portal_key=self.portal_key,
            headers={"Prefer": 'outlook.timezone="UTC"'},
        )


def _address(entry: Any) -> str:
    email = entry.get("emailAddress") if isinstance(entry, dict) else None
    address = email.get("address") if isinstance(email, dict) else None
    return address.casefold() if isinstance(address, str) else ""


def _meeting(item: Any, *, account: str) -> _calendar.Meeting | None:
    """A Graph event as a meeting, or `None` for one that is not one to prepare for.

    Not one: cancelled, all day, declined by the account, or with nobody but the
    account and its rooms on it.
    """
    if not isinstance(item, dict) or item.get("isCancelled") or item.get("isAllDay"):
        return None
    response = item.get("responseStatus")
    if isinstance(response, dict) and response.get("response") == "declined":
        return None
    start = nested(item, "start")
    end = nested(item, "end")
    starts_at = parse_time(start.get("dateTime"))
    identifier = item.get("iCalUId") or item.get("id")
    if starts_at is None or not isinstance(identifier, str):
        return None
    others = [
        address
        for attendee in item.get("attendees") or []
        if isinstance(attendee, dict)
        and attendee.get("type") != "resource"
        and (address := _address(attendee))
        and address != account
    ]
    if not others:
        return None
    online = nested(item, "onlineMeeting")
    location = nested(item, "location")
    ends_at = parse_time(end.get("dateTime"))
    return _calendar.Meeting(
        meeting_id=identifier,
        subject=str(item.get("subject") or ""),
        starts_at=starts_at.astimezone(UTC),
        ends_at=ends_at.astimezone(UTC) if ends_at else None,
        organizer=_address(item.get("organizer")),
        attendees=tuple(others),
        join_url=str(online.get("joinUrl") or ""),
        location=str(location.get("displayName") or ""),
        description=str(item.get("bodyPreview") or ""),
        url=str(item.get("webLink") or ""),
    )
