"""Files and calendars as polled portals (#2195).

What is worth holding here is how each could fire wrongly:

* a **file being edited** firing an agent on every tick, or an agent's own edit
  firing itself;
* a **first read** walking a drive's whole history instead of starting now;
* a **meeting** announced twice for one lead, or never because it was booked
  inside the lead;
* a **library** the account cannot read stopping the ones it can.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, get_args
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app.db.models.agent_trigger import EventSource
from app.schemas.agent_trigger import EventSourceName
from app.services import trigger_events
from app.services.portals import PortalUnreachable, _calendar, _files, files_place, get_adapter
from app.services.portals._api import get_json, nested
from app.services.portals.google_calendar import GoogleCalendarPortalAdapter
from app.services.portals.google_drive import GoogleDrivePortalAdapter
from app.services.portals.microsoft_files import MicrosoftFilesPortalAdapter
from app.services.portals.outlook_calendar import OutlookCalendarPortalAdapter

pytestmark = pytest.mark.anyio

_NOW = datetime.now(UTC)
_GRAPH = "https://graph.microsoft.com/v1.0"
Route = Callable[[httpx.Request], httpx.Response]


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


class _Api:
    """A provider that answers by path, recording what it was asked."""

    def __init__(self, routes: dict[str, Route | dict[str, Any]]) -> None:
        self.routes = routes
        self.asked: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer t"
        self.asked.append(request)
        route = self.routes.get(request.url.path)
        if route is None:
            return httpx.Response(404, json={"error": {"code": "itemNotFound"}})
        if callable(route):
            return route(request)
        return httpx.Response(200, json=route)


def _install(api: _Api, monkeypatch) -> None:
    original = httpx.AsyncClient.__init__

    def patched(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs["transport"] = httpx.MockTransport(api.handler)
        original(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched)


def _changed(
    file_id: str, *, created: datetime, modified: datetime, **extra: Any
) -> _files.ChangedFile:
    fields: dict[str, Any] = {
        "provider": "test",
        "file_id": file_id,
        "name": f"{file_id}.pdf",
        "mime_type": "application/pdf",
        "created_at": created,
        "modified_at": modified,
        "url": f"https://files.test/{file_id}",
        "modified_by": "ann@acme.test",
        "by_account": False,
        "location": {},
    }
    fields.update(extra)
    return _files.ChangedFile(**fields)


class TestWhichFileChangesAreNews:
    def test_a_new_file_is_created_and_an_edit_is_modified(self):
        old = _NOW - timedelta(days=3)
        events, record = _files.news(
            [
                _changed("new", created=_NOW - timedelta(seconds=20), modified=_NOW, is_new=True),
                _changed("old", created=old, modified=_NOW),
            ],
            announced={},
            now=_NOW,
        )
        assert [(event.payload["file_id"], event.payload["change"]) for event in events] == [
            ("new", "created"),
            ("old", "modified"),
        ]
        assert set(record) == {"new", "old"}
        assert events[0].delivery_id == f"test:new:{_NOW.isoformat()}"

    def test_a_file_kept_being_edited_fires_once_in_the_settle_window(self):
        """A document open for an hour saves every minute; one run, not sixty."""
        old = _NOW - timedelta(days=3)
        just_now = {"doc": (_NOW - timedelta(minutes=5)).isoformat()}
        held, _ = _files.news(
            [_changed("doc", created=old, modified=_NOW)], announced=just_now, now=_NOW
        )
        assert held == []
        long_ago = {"doc": (_NOW - timedelta(minutes=31)).isoformat(), "junk": 7, "bad": "x"}
        again, record = _files.news(
            [_changed("doc", created=old, modified=_NOW)], announced=long_ago, now=_NOW
        )
        assert len(again) == 1
        # The record keeps only what is inside the window.
        assert set(record) == {"doc"}

    def test_two_reports_of_one_file_are_one_event_at_its_latest_change(self):
        old = _NOW - timedelta(days=3)
        earlier = _changed("doc", created=old, modified=_NOW - timedelta(minutes=2))
        later = _changed("doc", created=old, modified=_NOW)
        events, _ = _files.news([later, earlier], announced={}, now=_NOW)
        assert [event.payload["modified_at"] for event in events] == [_NOW.isoformat()]

    def test_a_bulk_sync_is_bounded_to_the_most_recent(self):
        changed = [
            _changed(
                f"f{index}",
                created=_NOW - timedelta(days=1),
                modified=_NOW - timedelta(seconds=index),
            )
            for index in range(_files.MAX_FILES_PER_POLL + 5)
        ]
        events, _ = _files.news(changed, announced={}, now=_NOW)
        assert len(events) == _files.MAX_FILES_PER_POLL
        assert "f0" in {event.payload["file_id"] for event in events}

    @pytest.mark.parametrize("value", [None, "", "yesterday", 5])
    def test_an_unreadable_time_is_none(self, value):
        assert _files.parse_time(value) is None

    def test_a_naive_time_is_read_as_utc(self):
        assert _files.parse_time("2027-01-01T09:00:00") == datetime(2027, 1, 1, 9, tzinfo=UTC)


def _meeting(meeting_id: str = "m1", *, starts_in: float = 10, attendees=("bob@client.test",)):
    return _calendar.Meeting(
        meeting_id=meeting_id,
        subject="Quarterly review",
        starts_at=_NOW + timedelta(minutes=starts_in),
        ends_at=None,
        organizer="ann@acme.test",
        attendees=tuple(attendees),
        join_url="https://meet.test/x",
        location="Room 1",
        description="Agenda",
        url="https://calendar.test/m1",
    )


class TestAnnouncingAMeeting:
    def _announce(self, meetings, *, watched=(15,), announced=None):
        return _calendar.announce(
            meetings,
            watched=list(watched),
            announced=announced or {},
            account="ann@acme.test",
            now=_NOW,
            provider="cal",
        )

    def test_a_meeting_inside_a_lead_is_announced_once_for_that_lead(self):
        meeting = _meeting(starts_in=10)
        events, record = self._announce([meeting], watched=(15, 60))
        assert sorted(event.payload["lead_minutes"] for event in events) == [15, 60]
        assert events[0].payload["external_attendees"] == ["bob@client.test"]
        assert events[0].payload["minutes_until_start"] == 10
        again, _ = self._announce([meeting], watched=(15, 60), announced=record)
        assert again == []

    def test_a_meeting_beyond_the_lead_or_already_started_waits_or_is_skipped(self):
        assert self._announce([_meeting(starts_in=40)])[0] == []
        assert self._announce([_meeting(starts_in=-1)])[0] == []

    def test_a_moved_meeting_is_announced_again(self):
        _, record = self._announce([_meeting(starts_in=10)])
        moved, _ = self._announce([_meeting(starts_in=12)], announced=record)
        assert len(moved) == 1

    def test_the_record_forgets_meetings_that_have_started(self):
        stale = {"gone|x|15": (_NOW - timedelta(minutes=1)).isoformat(), "junk": 3}
        _, record = self._announce([], announced=stale)
        assert record == {}

    def test_colleagues_are_not_external(self):
        events, _ = self._announce([_meeting(attendees=("carl@acme.test", "dee@client.test"))])
        assert events[0].payload["external_attendees"] == ["dee@client.test"]

    def test_leads_come_from_the_watched_places(self):
        assert _calendar.leads({"60": _NOW, "15": _NOW, "0": _NOW, "500": _NOW, "x": _NOW}) == [
            15,
            60,
        ]


class TestTheSharedRequest:
    async def test_a_refusal_carries_the_status_and_codes_and_nothing_else(self):
        def refuse(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                404, json={"error": {"code": 404, "status": "NOT_FOUND", "message": "token=secret"}}
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(refuse)) as client:
            with pytest.raises(PortalUnreachable) as raised:
                await get_json(
                    client,
                    "https://api.test/x",
                    access_token="t",
                    params=None,
                    service="X",
                    portal_key="p",
                )
        assert raised.value.details == {"portal_key": "p", "status": 404, "codes": ["not_found"]}

    async def test_an_unreachable_or_unreadable_provider_is_the_recoverable_failure(self):
        def drop(_request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("down")

        def html(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html>")

        def plain_error(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="oops")

        def a_list(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[1])

        for handler in (drop, html, plain_error):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                with pytest.raises(PortalUnreachable):
                    await get_json(
                        client,
                        "https://api.test/x",
                        access_token="t",
                        params=None,
                        service="X",
                        portal_key="p",
                    )
        async with httpx.AsyncClient(transport=httpx.MockTransport(a_list)) as client:
            assert (
                await get_json(
                    client,
                    "https://api.test/x",
                    access_token="t",
                    params=None,
                    service="X",
                    portal_key="p",
                )
                == {}
            )

    def test_a_null_or_missing_object_reads_as_empty(self):
        assert nested({"owner": None}, "owner") == {}
        assert nested(None, "owner") == {}
        assert nested({"owner": {"id": "1"}}, "owner") == {"id": "1"}


def _drive_change(file_id: str, *, modified: datetime, **file: Any) -> dict[str, Any]:
    return {
        "changeType": "file",
        "file": {
            "id": file_id,
            "name": f"{file_id}.docx",
            "mimeType": "application/vnd.google-apps.document",
            "createdTime": _iso(_NOW - timedelta(days=2)),
            "modifiedTime": _iso(modified),
            "parents": ["FOLDER"],
            "webViewLink": f"https://docs.test/{file_id}",
            "lastModifyingUser": {"emailAddress": "bob@acme.test", "me": False},
            **file,
        },
    }


class TestGoogleDrive:
    async def test_a_first_poll_takes_the_position_and_the_account_and_fires_nothing(
        self, monkeypatch
    ):
        api = _Api(
            {
                "/drive/v3/about": {"user": {"emailAddress": "Ann@Acme.test"}},
                "/drive/v3/changes/startPageToken": {"startPageToken": "100"},
            }
        )
        _install(api, monkeypatch)
        read = await GoogleDrivePortalAdapter().poll(access_token="t", cursor=None)
        assert read.events == ()
        assert read.cursor["page_token"] == "100"
        assert read.cursor["account"] == "ann@acme.test"
        assert _files.parse_time(read.cursor["created_since"]) is not None

    async def test_changes_become_events_and_what_is_not_a_file_is_skipped(self, monkeypatch):
        pages = {
            "100": {
                "nextPageToken": "101",
                "changes": [
                    _drive_change("a", modified=_NOW),
                    {"changeType": "drive"},
                    {"changeType": "file", "removed": True},
                    _drive_change(
                        "folder", modified=_NOW, mimeType="application/vnd.google-apps.folder"
                    ),
                    _drive_change("binned", modified=_NOW, trashed=True),
                    _drive_change("broken", modified=_NOW, createdTime=None),
                    "noise",
                ],
            },
            "101": {"newStartPageToken": "102", "changes": [_drive_change("b", modified=_NOW)]},
        }

        def changes(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=pages[request.url.params["pageToken"]])

        _install(_Api({"/drive/v3/changes": changes}), monkeypatch)
        read = await GoogleDrivePortalAdapter().poll(
            access_token="t", cursor={"page_token": "100", "account": "ann@acme.test"}
        )
        assert [event.payload["file_id"] for event in read.events] == ["a", "b"]
        assert read.events[0].payload["parents"] == ["FOLDER"]
        assert read.cursor["page_token"] == "102"
        assert read.cursor["account"] == "ann@acme.test"
        assert read.cursor["seen_files"] == {}

    async def test_a_long_feed_is_read_over_several_ticks(self, monkeypatch):
        def endless(request: httpx.Request) -> httpx.Response:
            following = str(int(request.url.params["pageToken"]) + 1)
            return httpx.Response(200, json={"nextPageToken": following, "changes": []})

        _install(_Api({"/drive/v3/changes": endless}), monkeypatch)
        read = await GoogleDrivePortalAdapter().poll(access_token="t", cursor={"page_token": "1"})
        assert read.cursor["page_token"] == "11"

    async def test_a_token_drive_no_longer_accepts_starts_again_from_now(self, monkeypatch):
        def gone(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"error": {"code": 404}})

        api = _Api(
            {
                "/drive/v3/changes": gone,
                "/drive/v3/changes/startPageToken": {"startPageToken": "900"},
            }
        )
        _install(api, monkeypatch)
        read = await GoogleDrivePortalAdapter().poll(access_token="t", cursor={"page_token": "1"})
        assert read.events == ()
        assert read.cursor["page_token"] == "900"

    async def test_any_other_refusal_raises_so_the_token_is_kept(self, monkeypatch):
        def refuse(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={})

        _install(_Api({"/drive/v3/changes": refuse}), monkeypatch)
        with pytest.raises(PortalUnreachable):
            await GoogleDrivePortalAdapter().poll(access_token="t", cursor={"page_token": "1"})

    async def test_an_account_drive_does_not_name_is_left_out(self, monkeypatch):
        api = _Api(
            {"/drive/v3/about": {}, "/drive/v3/changes/startPageToken": {"startPageToken": "1"}}
        )
        _install(api, monkeypatch)
        read = await GoogleDrivePortalAdapter().poll(access_token="t", cursor={})
        assert read.cursor["page_token"] == "1"
        assert "account" not in read.cursor


def _gcal_event(**overrides: Any) -> dict[str, Any]:
    event: dict[str, Any] = {
        "id": "e1",
        "iCalUID": "uid-1@google.com",
        "status": "confirmed",
        "summary": "Kickoff",
        "start": {"dateTime": _iso(_NOW + timedelta(minutes=10))},
        "end": {"dateTime": _iso(_NOW + timedelta(minutes=40))},
        "attendees": [
            {"email": "ann@acme.test", "self": True, "responseStatus": "accepted"},
            {"email": "Bob@Client.test"},
            {"email": "room@resource.test", "resource": True},
            "noise",
        ],
        "organizer": {"email": "ann@acme.test"},
        "hangoutLink": "https://meet.google.com/abc",
        "htmlLink": "https://calendar.google.com/e1",
    }
    event.update(overrides)
    return event


class TestGoogleCalendar:
    async def test_a_first_poll_records_whose_calendar_it_is(self, monkeypatch):
        _install(_Api({"/calendar/v3/calendars/primary": {"id": "Ann@Acme.test"}}), monkeypatch)
        read = await GoogleCalendarPortalAdapter().poll(access_token="t", cursor=None)
        assert read.cursor == {"account": "ann@acme.test", "announced": {}}

    async def test_no_watched_lead_asks_nothing(self, monkeypatch):
        api = _Api({})
        _install(api, monkeypatch)
        cursor = {"account": "ann@acme.test", "announced": {}}
        read = await GoogleCalendarPortalAdapter().poll(access_token="t", cursor=cursor, places={})
        assert read.cursor == cursor
        assert api.asked == []

    async def test_meetings_to_prepare_for_are_announced_and_the_rest_skipped(self, monkeypatch):
        items = [
            _gcal_event(),
            _gcal_event(id="cancelled", iCalUID="c", status="cancelled"),
            _gcal_event(id="allday", iCalUID="d", start={"date": "2027-01-01"}),
            _gcal_event(
                id="declined",
                iCalUID="x",
                attendees=[
                    {"email": "ann@acme.test", "self": True, "responseStatus": "declined"},
                    {"email": "b@c.test"},
                ],
            ),
            _gcal_event(
                id="alone", iCalUID="y", attendees=[{"email": "ann@acme.test", "self": True}]
            ),
            _gcal_event(id=None, iCalUID=None),
            _gcal_event(
                id="zoom",
                iCalUID="z",
                hangoutLink=None,
                end={},
                conferenceData={
                    "entryPoints": [
                        {"entryPointType": "phone"},
                        {"entryPointType": "video", "uri": "https://zoom.test/1"},
                    ]
                },
            ),
            _gcal_event(id="nolink", iCalUID="n", hangoutLink=None, conferenceData=None),
            "noise",
        ]
        api = _Api({"/calendar/v3/calendars/primary/events": {"items": items}})
        _install(api, monkeypatch)
        read = await GoogleCalendarPortalAdapter().poll(
            access_token="t", cursor={"account": "ann@acme.test"}, places={"15": _NOW}
        )
        by_id = {event.payload["meeting_id"]: event.payload for event in read.events}
        assert set(by_id) == {"uid-1@google.com", "z", "n"}
        assert by_id["uid-1@google.com"]["attendees"] == ["bob@client.test"]
        assert by_id["uid-1@google.com"]["join_url"] == "https://meet.google.com/abc"
        assert by_id["z"]["join_url"] == "https://zoom.test/1"
        assert by_id["z"]["ends_at"] is None
        assert by_id["n"]["join_url"] == ""
        assert api.asked[0].url.params["singleEvents"] == "true"
        assert read.cursor["account"] == "ann@acme.test"
        assert len(read.cursor["announced"]) == 3


def _graph_event(**overrides: Any) -> dict[str, Any]:
    event: dict[str, Any] = {
        "id": "AAMk1",
        "iCalUId": "uid-1",
        "subject": "Contract call",
        "start": {
            "dateTime": (_NOW + timedelta(minutes=10)).replace(tzinfo=None).isoformat() + "0",
            "timeZone": "UTC",
        },
        "end": {
            "dateTime": (_NOW + timedelta(minutes=40)).replace(tzinfo=None).isoformat(),
            "timeZone": "UTC",
        },
        "isCancelled": False,
        "isAllDay": False,
        "responseStatus": {"response": "accepted"},
        "attendees": [
            {"type": "required", "emailAddress": {"address": "ann@acme.test"}},
            {"type": "required", "emailAddress": {"address": "Bob@Client.test"}},
            {"type": "resource", "emailAddress": {"address": "room@acme.test"}},
            {"type": "optional", "emailAddress": None},
            "noise",
        ],
        "organizer": {"emailAddress": {"address": "Ann@Acme.test"}},
        "onlineMeeting": {"joinUrl": "https://teams.test/join"},
        "location": {"displayName": "Room 1"},
        "bodyPreview": "Agenda: terms",
        "webLink": "https://outlook.test/e1",
    }
    event.update(overrides)
    return event


class TestOutlookCalendar:
    async def test_a_first_poll_records_whose_calendar_it_is(self, monkeypatch):
        api = _Api({"/v1.0/me/calendar": {"id": "cal", "owner": {"address": "Ann@Acme.test"}}})
        _install(api, monkeypatch)
        read = await OutlookCalendarPortalAdapter().poll(access_token="t", cursor=None)
        assert read.cursor == {"account": "ann@acme.test", "announced": {}}

    async def test_no_watched_lead_asks_nothing(self, monkeypatch):
        api = _Api({})
        _install(api, monkeypatch)
        cursor = {"account": "ann@acme.test"}
        assert (
            await OutlookCalendarPortalAdapter().poll(access_token="t", cursor=cursor)
        ).cursor == cursor
        assert api.asked == []

    async def test_meetings_to_prepare_for_are_announced_in_utc(self, monkeypatch):
        items = [
            _graph_event(),
            _graph_event(id="c", iCalUId="c", isCancelled=True),
            _graph_event(id="d", iCalUId="d", isAllDay=True),
            _graph_event(id="x", iCalUId="x", responseStatus={"response": "declined"}),
            _graph_event(
                id="y", iCalUId="y", attendees=[{"emailAddress": {"address": "ann@acme.test"}}]
            ),
            _graph_event(id=None, iCalUId=None),
            _graph_event(id="bare", iCalUId="bare", end=None, onlineMeeting=None, location=None),
            "noise",
        ]
        api = _Api({"/v1.0/me/calendarView": {"value": items}})
        _install(api, monkeypatch)
        read = await OutlookCalendarPortalAdapter().poll(
            access_token="t", cursor={"account": "ann@acme.test"}, places={"15": _NOW, "60": _NOW}
        )
        uid = [event.payload for event in read.events if event.payload["meeting_id"] == "uid-1"]
        assert sorted(payload["lead_minutes"] for payload in uid) == [15, 60]
        assert uid[0]["attendees"] == ["bob@client.test"]
        assert uid[0]["organizer"] == "ann@acme.test"
        assert uid[0]["join_url"] == "https://teams.test/join"
        assert {event.payload["meeting_id"] for event in read.events} == {"uid-1", "bare"}
        assert api.asked[0].headers["Prefer"] == 'outlook.timezone="UTC"'
        window = api.asked[0].url.params
        assert datetime.fromisoformat(window["endDateTime"]) - datetime.fromisoformat(
            window["startDateTime"]
        ) == timedelta(minutes=60)


def _drive_item(item_id: str, **overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": item_id,
        "name": f"{item_id}.xlsx",
        "file": {"mimeType": "application/vnd.ms-excel"},
        "createdDateTime": _iso(_NOW - timedelta(days=1)),
        "lastModifiedDateTime": _iso(_NOW),
        "webUrl": f"https://acme.sharepoint.com/{item_id}",
        "lastModifiedBy": {"user": {"id": "user-bob", "displayName": "Bob"}},
        "parentReference": {"path": "/drives/D1/root:/Invoices/2026"},
    }
    item.update(overrides)
    return item


class _Drives:
    """Graph's drive endpoints: the own drive, sites, and a delta per drive."""

    def __init__(self) -> None:
        self.sites = {"/v1.0/sites/acme.sharepoint.com:/sites/finance:/drive": {"id": "D1"}}
        self.pages: dict[str, list[dict[str, Any]]] = {}
        self.expired: set[str] = set()
        self.refused: set[str] = set()

    def routes(self) -> dict[str, Route | dict[str, Any]]:
        routes: dict[str, Route | dict[str, Any]] = {
            "/v1.0/me": {"id": "user-ann"},
            "/v1.0/drives/D1/items/nopath": _drive_item("nopath"),
            "/v1.0/me/drive": {"id": "OWN", "owner": {"user": {"id": "user-ann"}}},
            **self.sites,
        }
        for drive in ("OWN", "D1", "D2"):
            routes[f"/v1.0/drives/{drive}/root/delta"] = self._delta(drive)
        return routes

    def _delta(self, drive: str) -> Route:
        def answer(request: httpx.Request) -> httpx.Response:
            if drive in self.refused:
                return httpx.Response(403, json={"error": {"code": "accessDenied"}})
            query = parse_qs(urlsplit(str(request.url)).query)
            token = query.get("token", [""])[0]
            if token in self.expired:
                self.expired.discard(token)
                return httpx.Response(410, json={"error": {"code": "resyncRequired"}})
            base = f"{_GRAPH}/drives/{drive}/root/delta"
            if token == "latest" or "T" in token:
                return httpx.Response(
                    200, json={"value": [], "@odata.deltaLink": f"{base}?token={drive}-0"}
                )
            pages = self.pages.get(token, [])
            index = int(query.get("page", ["0"])[0])
            body: dict[str, Any] = {"value": pages[index] if pages else []}
            if index + 1 < len(pages):
                body["@odata.nextLink"] = f"{base}?token={token}&page={index + 1}"
            else:
                body["@odata.deltaLink"] = f"{base}?token={drive}-next"
            return httpx.Response(200, json=body)

        return answer


_SITE = files_place("https://acme.sharepoint.com/sites/Finance/")


class TestMicrosoftFiles:
    def _cursor(self, places: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"account": "OWN", "user_id": "user-ann", "places": places or {}}

    async def test_a_first_poll_records_the_account_and_fires_nothing(self, monkeypatch):
        _install(_Api(_Drives().routes()), monkeypatch)
        read = await MicrosoftFilesPortalAdapter().poll(access_token="t", cursor=None)
        assert read.cursor == {"account": "user-ann", "places": {}, "user_id": "user-ann"}

    async def test_an_owner_graph_names_no_user_for_is_recorded_without_one(self, monkeypatch):
        routes = _Drives().routes()
        routes["/v1.0/me"] = {"id": "user-ann"}
        _install(_Api(routes), monkeypatch)
        read = await MicrosoftFilesPortalAdapter().poll(access_token="t", cursor=None)
        assert read.cursor["account"] == "user-ann"

    async def test_a_long_delta_is_read_over_several_ticks(self, monkeypatch):
        drives = _Drives()
        drives.pages["OWN-0"] = [[_drive_item(f"f{index}")] for index in range(12)]
        _install(_Api(drives.routes()), monkeypatch)
        state = {"": {"drive_id": "OWN", "link": f"{_GRAPH}/drives/OWN/root/delta?token=OWN-0"}}
        read = await MicrosoftFilesPortalAdapter().poll(
            access_token="t", cursor=self._cursor(state), places={"": _NOW}
        )
        assert len(read.events) == 10
        assert read.cursor["places"][""]["link"].endswith("token=OWN-0&page=10")

    async def test_a_new_place_starts_from_now_rather_than_the_librarys_history(self, monkeypatch):
        drives = _Drives()
        api = _Api(drives.routes())
        _install(api, monkeypatch)
        read = await MicrosoftFilesPortalAdapter().poll(
            access_token="t", cursor=self._cursor(), places={"": _NOW, _SITE: _NOW}
        )
        assert read.events == ()
        assert read.cursor["places"][""]["drive_id"] == "OWN"
        assert read.cursor["places"][_SITE]["drive_id"] == "D1"
        assert read.cursor["places"][_SITE]["link"].endswith("token=D1-0")

    async def test_changes_in_a_library_become_events_with_where_they_are(self, monkeypatch):
        drives = _Drives()
        drives.pages["D1-0"] = [
            [_drive_item("a"), {"id": "gone", "deleted": {}}, {"id": "dir", "folder": {}}, "noise"],
            [
                _drive_item(
                    "mine", lastModifiedBy={"user": {"id": "user-ann", "email": "ann@acme.test"}}
                ),
                _drive_item("broken", createdDateTime=None),
                _drive_item("rootfile", parentReference={"path": "/drives/D1/root:"}),
                _drive_item("nopath", parentReference=None),
            ],
        ]
        _install(_Api(drives.routes()), monkeypatch)
        state = {_SITE: {"drive_id": "D1", "link": f"{_GRAPH}/drives/D1/root/delta?token=D1-0"}}
        read = await MicrosoftFilesPortalAdapter().poll(
            access_token="t", cursor=self._cursor(state), places={_SITE: _NOW}
        )
        payloads = {event.payload["file_id"]: event.payload for event in read.events}
        assert set(payloads) == {"a", "mine", "rootfile", "nopath"}
        assert payloads["a"]["folder"] == "Invoices/2026"
        assert payloads["a"]["site_url"] == _SITE
        assert payloads["a"]["by_account"] is False
        assert payloads["mine"]["by_account"] is True
        assert payloads["mine"]["modified_by"] == "ann@acme.test"
        assert payloads["rootfile"]["folder"] == ""
        assert (
            read.cursor["places"][_SITE]["link"] == f"{_GRAPH}/drives/D1/root/delta?token=D1-next"
        )

    async def test_a_dropped_link_starts_again_from_now(self, monkeypatch):
        drives = _Drives()
        drives.expired.add("D1-0")
        _install(_Api(drives.routes()), monkeypatch)
        state = {_SITE: {"drive_id": "D1", "link": f"{_GRAPH}/drives/D1/root/delta?token=D1-0"}}
        read = await MicrosoftFilesPortalAdapter().poll(
            access_token="t", cursor=self._cursor(state), places={_SITE: _NOW}
        )
        assert read.events == ()
        assert read.cursor["places"][_SITE]["link"].endswith("token=D1-0")

    async def test_a_link_to_another_host_is_never_followed(self, monkeypatch):
        drives = _Drives()
        api = _Api(drives.routes())
        _install(api, monkeypatch)
        state = {"": {"drive_id": "OWN", "link": "https://attacker.test/steal"}}
        await MicrosoftFilesPortalAdapter().poll(
            access_token="t", cursor=self._cursor(state), places={"": _NOW}
        )
        assert all(request.url.host == "graph.microsoft.com" for request in api.asked)

    async def test_a_site_that_cannot_be_read_stops_only_its_own_place(self, monkeypatch):
        drives = _Drives()
        drives.refused.add("D2")
        _install(_Api(drives.routes()), monkeypatch)
        missing = files_place("https://acme.sharepoint.com/sites/Gone")
        refused = "https://acme.sharepoint.com/sites/locked"
        state = {refused: {"drive_id": "D2", "link": f"{_GRAPH}/drives/D2/root/delta?token=x"}}
        read = await MicrosoftFilesPortalAdapter().poll(
            access_token="t",
            cursor=self._cursor(state),
            places={missing: _NOW, refused: _NOW, "": _NOW},
        )
        assert read.unreadable == frozenset({missing, refused})
        assert set(read.cursor["places"]) == {""}

    async def test_a_drive_answer_with_no_id_is_unreadable(self, monkeypatch):
        drives = _Drives()
        drives.sites["/v1.0/sites/acme.sharepoint.com/drive"] = {}
        _install(_Api(drives.routes()), monkeypatch)
        root = files_place("https://acme.sharepoint.com")
        read = await MicrosoftFilesPortalAdapter().poll(
            access_token="t", cursor=self._cursor(), places={root: _NOW}
        )
        assert read.unreadable == frozenset({root})

    async def test_any_other_refusal_raises(self, monkeypatch):
        def broken(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={})

        routes = _Drives().routes()
        routes["/v1.0/drives/OWN/root/delta"] = broken
        _install(_Api(routes), monkeypatch)
        with pytest.raises(PortalUnreachable):
            await MicrosoftFilesPortalAdapter().poll(
                access_token="t", cursor=self._cursor(), places={"": _NOW}
            )

    async def test_a_site_lookup_that_fails_otherwise_raises(self, monkeypatch):
        def broken(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={})

        routes = _Drives().routes()
        routes["/v1.0/sites/acme.sharepoint.com:/sites/finance:/drive"] = broken
        _install(_Api(routes), monkeypatch)
        with pytest.raises(PortalUnreachable):
            await MicrosoftFilesPortalAdapter().poll(
                access_token="t", cursor=self._cursor(), places={_SITE: _NOW}
            )


class TestTheVocabulary:
    def test_the_api_offers_every_source_the_table_accepts(self):
        """The schema's names are written out for the OpenAPI document; one the
        enum gained without them would be a source no request could name."""
        assert set(get_args(EventSourceName)) == {source.value for source in EventSource}


class TestTheAdaptersAreRegistered:
    @pytest.mark.parametrize(
        "key", ["google_drive", "google_calendar", "microsoft_files", "outlook_calendar"]
    )
    def test_each_portal_resolves_to_its_adapter(self, key):
        adapter = get_adapter(key)
        assert adapter is not None and adapter.portal_key == key


def _matches(source: str, payload: dict[str, Any], config: dict[str, Any]) -> bool:
    return trigger_events.event_matches(source, headers={}, payload=payload, config=config)


class TestMatchingFiles:
    drive_file = {
        "change": "modified",
        "name": "Invoice 42.pdf",
        "parents": ["F1"],
        "by_account": False,
    }

    def test_a_drive_file_narrows_by_folder_name_and_change(self):
        assert _matches("google_drive", self.drive_file, {})
        assert _matches(
            "google_drive",
            self.drive_file,
            {"folder_id": "https://drive.google.com/drive/folders/F1"},
        )
        assert not _matches("google_drive", self.drive_file, {"folder_id": "F2"})
        assert _matches("google_drive", self.drive_file, {"name_contains": "INVOICE"})
        assert not _matches("google_drive", self.drive_file, {"name_contains": "receipt"})
        assert not _matches("google_drive", self.drive_file, {"change": "created"})

    def test_the_accounts_own_edit_fires_nothing_unless_asked(self):
        """An agent writing through the same grant would otherwise set itself off."""
        own = {**self.drive_file, "by_account": True}
        assert not _matches("google_drive", own, {})
        assert _matches("google_drive", own, {"include_own_changes": True})

    def test_a_sharepoint_file_fires_only_the_triggers_on_its_library_and_folder(self):
        site = "https://acme.sharepoint.com/sites/Finance"
        payload = {**self.drive_file, "place": files_place(site), "folder": "Invoices/2026/Q1"}
        assert _matches("microsoft_files", payload, {"site_url": site})
        assert not _matches("microsoft_files", payload, {})
        assert _matches(
            "microsoft_files", payload, {"site_url": site, "folder_path": "/invoices/2026/"}
        )
        assert _matches(
            "microsoft_files", payload, {"site_url": site, "folder_path": "Invoices/2026/Q1"}
        )
        assert not _matches(
            "microsoft_files", payload, {"site_url": site, "folder_path": "Invoices/20"}
        )

    def test_a_site_url_must_be_a_sharepoint_address(self):
        with pytest.raises(ValueError):
            trigger_events.polled_place(
                "microsoft_files", {"site_url": "https://evil.test/sites/x"}
            )

    def test_the_place_a_files_trigger_reads(self):
        assert trigger_events.polled_place("microsoft_files", {}) == ""
        assert trigger_events.polled_place("google_drive", {}) is None


class TestMatchingMeetings:
    meeting = {
        "lead_minutes": 15,
        "subject": "Renewal with Client",
        "attendees": ["bob@client.test", "carl@acme.test"],
        "external_attendees": ["bob@client.test"],
    }

    @pytest.mark.parametrize("source", ["google_calendar", "outlook_calendar"])
    def test_a_trigger_takes_the_announcement_for_its_own_lead(self, source):
        assert _matches(source, self.meeting, {})
        assert not _matches(source, self.meeting, {"minutes_before": 60})
        assert trigger_events.polled_place(source, {"minutes_before": 60}) == "60"

    def test_external_subject_and_attendee_filters(self):
        internal = {**self.meeting, "external_attendees": []}
        assert _matches("outlook_calendar", self.meeting, {"external_only": True})
        assert not _matches("outlook_calendar", internal, {"external_only": True})
        assert _matches("outlook_calendar", self.meeting, {"subject_contains": "renewal"})
        assert not _matches("outlook_calendar", self.meeting, {"subject_contains": "hiring"})
        assert _matches("outlook_calendar", self.meeting, {"attendee_contains": "@CLIENT.test"})
        assert not _matches("outlook_calendar", self.meeting, {"attendee_contains": "@other.test"})

    def test_a_lead_outside_five_to_a_hundred_and_twenty_minutes_is_refused(self):
        for lead in (4, 121):
            with pytest.raises(ValueError):
                trigger_events.polled_place("google_calendar", {"minutes_before": lead})


class TestContext:
    def test_a_file_is_described_with_where_it_is(self):
        rendered = trigger_events.render_context(
            "microsoft_files",
            payload={
                "change": "created",
                "name": "Q1.xlsx",
                "mime_type": "x",
                "modified_by": "Bob",
                "url": "https://u",
                "folder": "Reports",
                "site_url": "https://acme.sharepoint.com/sites/finance",
            },
        )
        assert rendered.startswith("A file was added in OneDrive/SharePoint.\nName: Q1.xlsx")
        assert "Folder: Reports" in rendered and "Site: https://acme.sharepoint.com" in rendered
        plain = trigger_events.render_context(
            "google_drive", payload={"change": "modified", "name": "a"}
        )
        assert plain.startswith("A file was changed in Google Drive.")
        assert "Folder:" not in plain

    def test_a_meeting_is_described_with_who_is_coming(self):
        rendered = trigger_events.render_context(
            "google_calendar",
            payload={
                "minutes_until_start": 15,
                "subject": "Kickoff",
                "starts_at": "2027-01-01T09:00:00+00:00",
                "attendees": ["bob@client.test"],
                "external_attendees": ["bob@client.test"],
                "join_url": "https://meet",
                "description": "Agenda",
            },
        )
        assert rendered.startswith("A meeting in Google Calendar starts in 15 minutes.")
        assert "From outside the organization: bob@client.test" in rendered
        assert "Join: https://meet" in rendered and "Location:" not in rendered
        assert rendered.endswith("Agenda")
        bare = trigger_events.render_context("outlook_calendar", payload={})
        assert "From outside" not in bare


class TestProviderContractRegressions:
    def test_creation_is_identified_after_an_edit_before_the_first_read(self) -> None:
        created = _NOW - timedelta(minutes=3)
        changed, seen = _files.classify(
            [_changed("new", created=created, modified=_NOW)],
            since=_NOW - timedelta(minutes=5),
            seen={},
            now=_NOW,
            complete=False,
        )
        events, _ = _files.news(changed, announced={}, now=_NOW)
        assert events[0].payload["change"] == "created"
        changed, _ = _files.classify(
            [_changed("new", created=created, modified=_NOW)],
            since=_NOW - timedelta(minutes=5),
            seen=seen,
            now=_NOW,
            complete=True,
        )
        events, _ = _files.news(changed, announced={}, now=_NOW)
        assert events[0].payload["change"] == "modified"

    async def test_sharepoint_delta_resolves_the_folder_outside_the_delta_feed(
        self, monkeypatch
    ) -> None:
        drives = _Drives()
        drives.pages["D1-0"] = [
            [_drive_item("doc", parentReference={"id": "folder", "driveId": "D1"})]
        ]
        routes = drives.routes()
        routes["/v1.0/drives/D1/items/doc"] = _drive_item("doc")
        _install(_Api(routes), monkeypatch)
        read = await MicrosoftFilesPortalAdapter().poll(
            access_token="t",
            cursor={
                "account": "ann",
                "places": {
                    _SITE: {"drive_id": "D1", "link": f"{_GRAPH}/drives/D1/root/delta?token=D1-0"}
                },
            },
            places={_SITE: _NOW},
        )
        assert read.events[0].payload["folder"] == "Invoices/2026"
        assert _matches(
            "microsoft_files",
            read.events[0].payload,
            {"site_url": _SITE, "folder_path": "Invoices"},
        )

    async def test_sharepoint_identity_does_not_require_a_personal_drive(self, monkeypatch) -> None:
        api = _Api({"/v1.0/me": {"id": "guest"}})
        _install(api, monkeypatch)
        read = await MicrosoftFilesPortalAdapter().poll(access_token="t", cursor=None)
        assert read.cursor["account"] == "guest"
        assert [request.url.path for request in api.asked] == ["/v1.0/me"]

    async def test_a_new_sharepoint_watch_uses_its_creation_time(self, monkeypatch) -> None:
        api = _Api(_Drives().routes())
        _install(api, monkeypatch)
        await MicrosoftFilesPortalAdapter().poll(
            access_token="t", cursor={"account": "ann", "places": {}}, places={_SITE: _NOW}
        )
        request = next(request for request in api.asked if request.url.path.endswith("/delta"))
        assert request.url.params["token"] == _NOW.isoformat()

    @pytest.mark.parametrize("provider", ["google", "outlook"])
    async def test_calendar_reads_the_next_page(self, provider: str, monkeypatch) -> None:
        def page(request: httpx.Request) -> httpx.Response:
            if "pageToken" in request.url.params or "$skip" in request.url.params:
                return httpx.Response(
                    200, json={"items": [_gcal_event()], "value": [_graph_event()]}
                )
            return httpx.Response(
                200,
                json={
                    "items": [],
                    "value": [],
                    "nextPageToken": "2",
                    "@odata.nextLink": f"{_GRAPH}/me/calendarView?$skip=1",
                },
            )

        route = (
            "/calendar/v3/calendars/primary/events"
            if provider == "google"
            else "/v1.0/me/calendarView"
        )
        api = _Api({route: page})
        _install(api, monkeypatch)
        adapter = (
            GoogleCalendarPortalAdapter()
            if provider == "google"
            else OutlookCalendarPortalAdapter()
        )
        read = await adapter.poll(
            access_token="t", cursor={"account": "ann@acme.test"}, places={"15": _NOW}
        )
        assert len(api.asked) == 2
        assert len(read.events) == 1


@pytest.mark.parametrize("provider", ["google", "outlook"])
async def test_a_calendar_pagination_overflow_is_an_observable_failure(
    provider: str, monkeypatch
) -> None:
    api = _Api(
        {
            "/calendar/v3/calendars/primary/events": {"items": [], "nextPageToken": "next"},
            "/v1.0/me/calendarView": {
                "value": [],
                "@odata.nextLink": f"{_GRAPH}/me/calendarView?$skip=1",
            },
        }
    )
    _install(api, monkeypatch)
    adapter = (
        GoogleCalendarPortalAdapter() if provider == "google" else OutlookCalendarPortalAdapter()
    )
    with pytest.raises(PortalUnreachable):
        await adapter.poll(
            access_token="t", cursor={"account": "ann@acme.test"}, places={"15": _NOW}
        )
    assert len(api.asked) == 10


async def test_calendar_pagination_never_sends_the_token_to_another_host(monkeypatch) -> None:
    api = _Api(
        {"/v1.0/me/calendarView": {"value": [], "@odata.nextLink": "https://other.test/steal"}}
    )
    _install(api, monkeypatch)
    with pytest.raises(PortalUnreachable):
        await OutlookCalendarPortalAdapter().poll(
            access_token="t", cursor={"account": "ann@acme.test"}, places={"15": _NOW}
        )
    assert len(api.asked) == 1


@pytest.mark.parametrize("status", [404, 503])
async def test_a_file_removed_between_delta_and_metadata_does_not_break_the_cursor(
    status: int, monkeypatch
) -> None:
    drives = _Drives()
    drives.pages["D1-0"] = [[_drive_item("gone", parentReference={"id": "folder"})]]
    routes = drives.routes()
    routes["/v1.0/drives/D1/items/gone"] = lambda request: httpx.Response(status, json={})
    _install(_Api(routes), monkeypatch)
    operation = MicrosoftFilesPortalAdapter().poll(
        access_token="t",
        cursor={
            "account": "ann",
            "places": {
                _SITE: {"drive_id": "D1", "link": f"{_GRAPH}/drives/D1/root/delta?token=D1-0"}
            },
        },
        places={_SITE: _NOW},
    )
    if status == 503:
        with pytest.raises(PortalUnreachable):
            await operation
    else:
        assert (await operation).events == ()


async def test_repeated_lost_sync_never_advances_the_drive_cursor(monkeypatch) -> None:
    api = _Api({"/v1.0/drives/D1/root/delta": lambda request: httpx.Response(410, json={})})
    _install(api, monkeypatch)
    with pytest.raises(PortalUnreachable):
        await MicrosoftFilesPortalAdapter().poll(
            access_token="t",
            cursor={"account": "ann", "places": {_SITE: {"drive_id": "D1"}}},
            places={_SITE: _NOW},
        )
    assert len(api.asked) == 10
