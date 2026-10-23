"""Reading Outlook folders on a schedule (#1984).

Graph reports changes a folder at a time, so what is worth holding here is the
ways that shape loses or duplicates work, beyond the ones Gmail's tests cover:

* a **change** to old mail - marked read, flagged - mistaken for an arrival;
* a **folder** that cannot be read stopping the folders that can;
* a **first read** of a place walking the whole folder instead of what is news;
* a **delta link** Graph has expired treated as an error.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app.services.portals import PortalUnreachable, outlook_place
from app.services.portals.outlook import OutlookPortalAdapter

pytestmark = pytest.mark.anyio

_API = "https://graph.microsoft.com/v1.0"
_NOW = datetime.now(UTC)
_CONNECTED = _NOW - timedelta(days=1)


def _stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _item(identifier: str, received: datetime, **extra: Any) -> dict[str, Any]:
    return {"id": identifier, "receivedDateTime": _stamp(received), **extra}


def _message(identifier: str, **overrides: Any) -> dict[str, Any]:
    message: dict[str, Any] = {
        "id": identifier,
        "subject": "Invoice 42",
        "from": {"emailAddress": {"name": "Billing", "address": "billing@acme.test"}},
        "toRecipients": [
            {"emailAddress": {"name": "me@corp.test", "address": "me@corp.test"}},
            {"emailAddress": {}},
        ],
        "receivedDateTime": _stamp(_NOW),
        "hasAttachments": False,
        "importance": "high",
        "categories": ["Finance"],
        "body": {"contentType": "text", "content": "Please pay invoice 42."},
        "bodyPreview": "Please pay",
    }
    message.update(overrides)
    return message


class _Graph:
    """A Microsoft Graph that answers the requests the adapter makes.

    `deltas` maps a folder id to the pages its delta returns, in order; each
    later call to the delta link a page handed out answers the next batch in
    `changes`.
    """

    def __init__(self) -> None:
        self.folders: dict[str, str] = {"me|inbox": "INBOX"}
        self.children: dict[tuple[str, str], str] = {}
        self.top_level: dict[str, str] = {}
        self.unreadable_mailboxes: set[str] = set()
        self.deltas: dict[str, list[list[dict[str, Any]]]] = {}
        self.changes: dict[str, list[dict[str, Any]]] = {}
        self.expired: set[str] = set()
        self.messages: dict[str, dict[str, Any]] = {}
        self.attachments: dict[str, list[dict[str, Any]]] = {}
        self.status: int | None = None
        self.asked: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.asked.append(url)
        assert request.headers["Authorization"] == "Bearer t"
        if self.status is not None:
            return httpx.Response(self.status, json={"error": {"code": "nope"}})
        path = request.url.path.removeprefix("/v1.0")
        query = parse_qs(urlsplit(url).query)
        mailbox = "me"
        if path.startswith("/users/"):
            _, _, rest = path.partition("/users/")
            mailbox, _, path = rest.partition("/")
            path = "/" + path
            if mailbox in self.unreadable_mailboxes:
                return httpx.Response(403, json={"error": {"code": "ErrorAccessDenied"}})
        else:
            path = path.removeprefix("/me")
        if path.endswith("/messages/delta"):
            folder = path.split("/")[2]
            if "$deltatoken" in query:
                token = query["$deltatoken"][0]
                if token in self.expired:
                    return httpx.Response(410, json={"error": {"code": "SyncStateNotFound"}})
                return self._page(folder, self.changes.get(token, []), index=None)
            if "$skiptoken" in query:
                return self._page(folder, *self._skip(folder, int(query["$skiptoken"][0])))
            return self._page(folder, *self._skip(folder, 0))
        if path.endswith("/attachments"):
            return httpx.Response(200, json={"value": self.attachments.get(path.split("/")[2], [])})
        if path.startswith("/messages/"):
            found = self.messages.get(path.split("/")[2])
            if found is None:
                return httpx.Response(404, json={"error": {"code": "ErrorItemNotFound"}})
            return httpx.Response(200, json=found)
        if path.endswith("/childFolders"):
            name = query["$filter"][0].split("'")[1]
            child = self.children.get((path.split("/")[2], name))
            return httpx.Response(200, json={"value": [{"id": child}] if child else []})
        if path == "/mailFolders":
            name = query["$filter"][0].split("'")[1]
            found_id = self.top_level.get(name)
            return httpx.Response(200, json={"value": [{"id": found_id}] if found_id else []})
        well_known = self.folders.get(f"{mailbox}|{path.split('/')[2]}")
        if well_known is None:
            return httpx.Response(404, json={"error": {"code": "ErrorFolderNotFound"}})
        return httpx.Response(200, json={"id": well_known})

    def _skip(self, folder: str, index: int) -> tuple[list[dict[str, Any]], int | None]:
        pages = self.deltas.get(folder, [[]])
        return pages[index], (index + 1 if index + 1 < len(pages) else None)

    def _page(self, folder: str, items: list[dict[str, Any]], index: int | None) -> httpx.Response:
        base = f"{_API}/me/mailFolders/{folder}/messages/delta"
        body: dict[str, Any] = {"value": items}
        if index is None:
            body["@odata.deltaLink"] = f"{base}?$deltatoken={folder}-next"
        else:
            body["@odata.nextLink"] = f"{base}?$skiptoken={index}"
        return httpx.Response(200, json=body)


def _adapter(graph: _Graph, monkeypatch) -> OutlookPortalAdapter:
    original = httpx.AsyncClient.__init__

    def patched(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs["transport"] = httpx.MockTransport(graph.handler)
        original(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched)
    return OutlookPortalAdapter()


def _cursor(places: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"connected_at": _CONNECTED.isoformat(), "places": places or {}}


INBOX = outlook_place(mailbox=None, folder="inbox")


class TestThePlaceKey:
    def test_one_spelling_for_the_same_folder(self):
        assert outlook_place(mailbox="Ops@Corp.test", folder="/Inbox/Invoices/") == (
            "ops@corp.test|inbox/invoices"
        )
        assert outlook_place(mailbox=None, folder="INBOX") == "|inbox"


class TestTheFirstPoll:
    async def test_it_records_the_connection_and_reads_nothing(self, monkeypatch):
        """Connecting a mailbox fires nothing on the mail already in it."""
        graph = _Graph()

        read = await _adapter(graph, monkeypatch).poll(
            access_token="t", cursor=None, places={INBOX: _CONNECTED}
        )

        assert read.events == ()
        assert set(read.cursor) == {"connected_at", "places"}
        assert read.cursor["places"] == {}
        assert graph.asked == []

    async def test_no_places_means_no_requests(self, monkeypatch):
        """A connected mailbox nothing watches costs nothing per tick."""
        graph = _Graph()

        read = await _adapter(graph, monkeypatch).poll(access_token="t", cursor=_cursor())

        assert read.events == ()
        assert graph.asked == []


class TestANewPlace:
    async def test_it_reads_only_what_arrived_since_its_trigger_was_made(self, monkeypatch):
        graph = _Graph()
        made = _NOW - timedelta(minutes=3)
        graph.deltas["INBOX"] = [
            [
                _item("old", made - timedelta(hours=2)),
                _item("m1", made + timedelta(minutes=1)),
            ]
        ]
        graph.messages["m1"] = _message("m1")

        read = await _adapter(graph, monkeypatch).poll(
            access_token="t", cursor=_cursor(), places={INBOX: made}
        )

        [event] = read.events
        assert event.delivery_id == "outlook:m1"
        # The first delta asks Graph for the window, not the whole folder.
        first = next(url for url in graph.asked if "/messages/delta" in url)
        assert f"receivedDateTime ge {_stamp(made)}" in parse_qs(urlsplit(first).query)["$filter"]
        state = read.cursor["places"][INBOX]
        assert state["folder_id"] == "INBOX"
        assert state["link"].endswith("$deltatoken=INBOX-next")

    async def test_the_floor_is_never_before_the_account_was_connected(self, monkeypatch):
        """A trigger older than the grant does not turn the first read into a
        backlog of everything since the trigger was made."""
        graph = _Graph()
        graph.deltas["INBOX"] = [[_item("before", _CONNECTED - timedelta(hours=1))]]

        read = await _adapter(graph, monkeypatch).poll(
            access_token="t", cursor=_cursor(), places={INBOX: _CONNECTED - timedelta(days=9)}
        )

        assert read.events == ()

    async def test_the_message_becomes_the_payload_the_filter_reads(self, monkeypatch):
        graph = _Graph()
        graph.deltas["INBOX"] = [[_item("m1", _NOW)]]
        graph.messages["m1"] = _message(
            "m1", hasAttachments=True, body=None, categories=None, importance=None
        )
        graph.attachments["m1"] = [
            {"name": "invoice.pdf", "contentType": "application/pdf", "size": 1200},
            {"name": "logo.png", "contentType": "image/png", "size": 10, "isInline": True},
            {"name": "notes.txt", "contentType": "text/plain", "size": "big"},
        ]

        read = await _adapter(graph, monkeypatch).poll(
            access_token="t", cursor=_cursor(), places={INBOX: _CONNECTED}
        )

        payload = read.events[0].payload
        assert payload["place"] == INBOX
        assert payload["mailbox"] is None
        assert payload["folder"] == "inbox"
        assert payload["from"] == "Billing <billing@acme.test>"
        assert payload["to"] == "me@corp.test"
        assert payload["subject"] == "Invoice 42"
        assert payload["has_attachments"] is True
        assert payload["importance"] == "normal"
        assert payload["categories"] == []
        assert payload["text"] == ""
        assert payload["attachments"] == [
            {"name": "invoice.pdf", "content_type": "application/pdf", "size": 1200},
            {"name": "notes.txt", "content_type": "text/plain", "size": None},
        ]

    async def test_the_body_is_asked_for_as_text_and_clipped(self, monkeypatch):
        graph = _Graph()
        graph.deltas["INBOX"] = [[_item("m1", _NOW)]]
        graph.messages["m1"] = _message("m1", body={"content": "x" * 30_000})

        read = await _adapter(graph, monkeypatch).poll(
            access_token="t", cursor=_cursor(), places={INBOX: _CONNECTED}
        )

        assert len(read.events[0].payload["text"]) == 20_000


class TestAPlaceAlreadyRead:
    async def test_a_change_to_old_mail_is_not_an_arrival(self, monkeypatch):
        """A delta reports the message somebody marked read last week as readily as
        the one that just landed; only the second is news."""
        graph = _Graph()
        read_at = _NOW - timedelta(minutes=1)
        graph.changes["INBOX-old"] = [
            _item("read-last-week", _NOW - timedelta(days=7)),
            _item("fresh", _NOW),
            {"id": "gone", "@removed": {"reason": "deleted"}},
            _item("draft", _NOW, isDraft=True),
            _item("no-date", _NOW, receivedDateTime=None),
        ]
        graph.messages["fresh"] = _message("fresh")
        state = {
            "folder_id": "INBOX",
            "link": f"{_API}/me/mailFolders/INBOX/messages/delta?$deltatoken=INBOX-old",
            "read_at": read_at.isoformat(),
        }

        read = await _adapter(graph, monkeypatch).poll(
            access_token="t", cursor=_cursor({INBOX: state}), places={INBOX: _CONNECTED}
        )

        assert [event.delivery_id for event in read.events] == ["outlook:fresh"]
        # The folder id was remembered, not looked up again.
        assert not any(url.endswith("/mailFolders/inbox?%24select=id") for url in graph.asked)

    async def test_an_expired_delta_restarts_from_the_last_read(self, monkeypatch):
        """Graph answers 410 for a sync state it dropped. Starting over from the
        last read - not from now, not from the beginning - keeps the folder firing
        without firing its history."""
        graph = _Graph()
        graph.expired.add("INBOX-old")
        read_at = _NOW - timedelta(minutes=30)
        graph.deltas["INBOX"] = [[_item("m1", _NOW)]]
        graph.messages["m1"] = _message("m1")
        state = {
            "folder_id": "INBOX",
            "link": f"{_API}/me/mailFolders/INBOX/messages/delta?$deltatoken=INBOX-old",
            "read_at": read_at.isoformat(),
        }

        read = await _adapter(graph, monkeypatch).poll(
            access_token="t", cursor=_cursor({INBOX: state}), places={INBOX: _CONNECTED}
        )

        assert [event.delivery_id for event in read.events] == ["outlook:m1"]
        restarted = [url for url in graph.asked if "%24filter" in url and "delta" in url]
        assert (
            _stamp(read_at - timedelta(minutes=5))
            in parse_qs(urlsplit(restarted[0]).query)["$filter"][0]
        )

    async def test_a_stored_link_to_another_host_is_never_followed(self, monkeypatch):
        """The link carries the bearer token's destination: only Graph is asked."""
        graph = _Graph()
        state = {
            "folder_id": "INBOX",
            "link": "https://graph.microsoft.com.evil.test/steal",
            "read_at": _NOW.isoformat(),
        }

        await _adapter(graph, monkeypatch).poll(
            access_token="t", cursor=_cursor({INBOX: state}), places={INBOX: _CONNECTED}
        )

        assert all(url.startswith(_API + "/") for url in graph.asked)

    async def test_a_place_nobody_watches_any_more_drops_out(self, monkeypatch):
        graph = _Graph()
        state = {"folder_id": "X", "link": None, "read_at": _NOW.isoformat()}

        read = await _adapter(graph, monkeypatch).poll(
            access_token="t", cursor=_cursor({"|archive": state}), places={}
        )

        assert read.cursor["places"] == {}


class TestFoldersAndMailboxes:
    async def test_a_folder_path_is_walked_by_display_name(self, monkeypatch):
        """`Inbox/Invoices` - where a mail rule files the slice an agent should see."""
        graph = _Graph()
        graph.children[("INBOX", "invoices")] = "INV"
        graph.deltas["INV"] = [[_item("m1", _NOW)]]
        graph.messages["m1"] = _message("m1")
        place = outlook_place(mailbox=None, folder="Inbox/Invoices")

        read = await _adapter(graph, monkeypatch).poll(
            access_token="t", cursor=_cursor(), places={place: _CONNECTED}
        )

        assert [event.delivery_id for event in read.events] == ["outlook:m1"]
        assert read.cursor["places"][place]["folder_id"] == "INV"

    async def test_a_top_level_folder_by_name(self, monkeypatch):
        graph = _Graph()
        graph.top_level["projects"] = "PRJ"
        graph.children[("PRJ", "alpha")] = "ALPHA"
        graph.deltas["ALPHA"] = [[_item("m1", _NOW)]]
        graph.messages["m1"] = _message("m1")
        place = outlook_place(mailbox=None, folder="Projects/Alpha")

        read = await _adapter(graph, monkeypatch).poll(
            access_token="t", cursor=_cursor(), places={place: _CONNECTED}
        )

        assert [event.payload["folder"] for event in read.events] == ["projects/alpha"]
        assert read.cursor["places"][place]["folder_id"] == "ALPHA"

    async def test_a_place_that_cannot_be_read_does_not_stop_the_others(self, monkeypatch):
        """A shared mailbox no longer shared, a folder renamed: named back so its
        triggers can be turned off, while the inbox is read as usual."""
        graph = _Graph()
        graph.unreadable_mailboxes.add("ops@corp.test")
        graph.deltas["INBOX"] = [[_item("m1", _NOW)]]
        graph.messages["m1"] = _message("m1")
        shared = outlook_place(mailbox="ops@corp.test", folder="inbox")
        missing = outlook_place(mailbox=None, folder="nowhere")

        read = await _adapter(graph, monkeypatch).poll(
            access_token="t",
            cursor=_cursor(),
            places={shared: _CONNECTED, missing: _CONNECTED, INBOX: _CONNECTED},
        )

        assert read.unreadable == frozenset({shared, missing})
        assert [event.delivery_id for event in read.events] == ["outlook:m1"]
        assert set(read.cursor["places"]) == {INBOX}

    async def test_a_shared_mailbox_is_read_through_its_own_path(self, monkeypatch):
        graph = _Graph()
        graph.folders["ops@corp.test|inbox"] = "OPS-INBOX"
        graph.deltas["OPS-INBOX"] = [[_item("m1", _NOW)]]
        graph.messages["m1"] = _message("m1")
        shared = outlook_place(mailbox="ops@corp.test", folder="inbox")

        read = await _adapter(graph, monkeypatch).poll(
            access_token="t", cursor=_cursor(), places={shared: _CONNECTED}
        )

        assert read.events[0].payload["mailbox"] == "ops@corp.test"
        assert any("/users/ops@corp.test/messages/m1" in url for url in graph.asked)


class TestTheWaysAPollerLosesWork:
    async def test_a_refused_token_raises_with_its_status(self, monkeypatch):
        """A 401 is the grant's problem, not a folder's: the caller turns it into a
        revoked grant rather than an unreadable place."""
        graph = _Graph()
        graph.status = 401

        with pytest.raises(PortalUnreachable) as raised:
            await _adapter(graph, monkeypatch).poll(
                access_token="t", cursor=_cursor(), places={INBOX: _CONNECTED}
            )

        assert raised.value.details["status"] == 401

    async def test_a_burst_is_bounded_to_the_newest(self, monkeypatch):
        graph = _Graph()
        graph.deltas["INBOX"] = [
            [_item(f"m{index:02}", _NOW + timedelta(seconds=index)) for index in range(30)]
        ]
        graph.messages.update({f"m{index:02}": _message(f"m{index:02}") for index in range(30)})

        read = await _adapter(graph, monkeypatch).poll(
            access_token="t", cursor=_cursor(), places={INBOX: _CONNECTED}
        )

        assert len(read.events) == 25
        assert read.events[0].delivery_id == "outlook:m05"
        assert read.events[-1].delivery_id == "outlook:m29"

    async def test_it_follows_pages_and_keeps_the_next_one_past_the_bound(self, monkeypatch):
        """A folder with more pages than one tick may read carries on next tick
        from where it stopped, rather than starting the window again."""
        graph = _Graph()
        graph.deltas["INBOX"] = [[_item(f"p{index}", _NOW)] for index in range(12)]
        graph.messages.update({f"p{index}": _message(f"p{index}") for index in range(12)})

        read = await _adapter(graph, monkeypatch).poll(
            access_token="t", cursor=_cursor(), places={INBOX: _CONNECTED}
        )

        assert len(read.events) == 10
        assert read.cursor["places"][INBOX]["link"].endswith("$skiptoken=10")

    async def test_a_message_deleted_between_the_reads_is_skipped(self, monkeypatch):
        graph = _Graph()
        graph.deltas["INBOX"] = [[_item("gone", _NOW)]]

        read = await _adapter(graph, monkeypatch).poll(
            access_token="t", cursor=_cursor(), places={INBOX: _CONNECTED}
        )

        assert read.events == ()

    async def test_a_message_read_that_fails_otherwise_raises(self, monkeypatch):
        graph = _Graph()
        graph.deltas["INBOX"] = [[_item("m1", _NOW)]]
        adapter = _adapter(graph, monkeypatch)
        original = graph.handler

        def failing(request: httpx.Request) -> httpx.Response:
            if "/messages/m1" in str(request.url):
                return httpx.Response(500)
            return original(request)

        graph.handler = failing  # type: ignore[method-assign]

        with pytest.raises(PortalUnreachable):
            await adapter.poll(access_token="t", cursor=_cursor(), places={INBOX: _CONNECTED})

    async def test_an_unreachable_graph_or_an_unreadable_answer_is_the_recoverable_failure(
        self, monkeypatch
    ):
        def down(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("down", request=request)

        graph = _Graph()
        graph.handler = down  # type: ignore[method-assign]
        with pytest.raises(PortalUnreachable):
            await _adapter(graph, monkeypatch).poll(
                access_token="t", cursor=_cursor(), places={INBOX: _CONNECTED}
            )

        def html(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html>proxy</html>")

        graph.handler = html  # type: ignore[method-assign]
        with pytest.raises(PortalUnreachable):
            await OutlookPortalAdapter().poll(
                access_token="t", cursor=_cursor(), places={INBOX: _CONNECTED}
            )

    async def test_a_cursor_from_an_older_shape_is_a_first_poll(self, monkeypatch):
        graph = _Graph()

        read = await _adapter(graph, monkeypatch).poll(
            access_token="t", cursor={"connected_at": "not a time"}, places={INBOX: _CONNECTED}
        )

        assert read.events == ()
        assert graph.asked == []


class TestOddAnswers:
    """Shapes Graph documents differently from how it sometimes answers."""

    async def test_an_unreadable_date_or_sender_reads_as_absent(self, monkeypatch):
        graph = _Graph()
        graph.deltas["INBOX"] = [
            [_item("bad", _NOW, receivedDateTime="yesterday"), _item("m1", _NOW)]
        ]
        graph.messages["m1"] = _message("m1", **{"from": None})

        read = await _adapter(graph, monkeypatch).poll(
            access_token="t", cursor=_cursor(), places={INBOX: _CONNECTED}
        )

        assert [event.delivery_id for event in read.events] == ["outlook:m1"]
        assert read.events[0].payload["from"] == ""

    async def test_a_delta_that_fails_for_another_reason_raises(self, monkeypatch):
        """Only 410 means "start over"; anything else leaves the cursor alone."""
        graph = _Graph()
        original = graph.handler

        def failing(request: httpx.Request) -> httpx.Response:
            if "delta" in str(request.url):
                return httpx.Response(503)
            return original(request)

        graph.handler = failing  # type: ignore[method-assign]
        with pytest.raises(PortalUnreachable):
            await _adapter(graph, monkeypatch).poll(
                access_token="t", cursor=_cursor(), places={INBOX: _CONNECTED}
            )

    async def test_an_empty_folder_path_is_the_inbox(self, monkeypatch):
        graph = _Graph()
        place = outlook_place(mailbox=None, folder="/")

        read = await _adapter(graph, monkeypatch).poll(
            access_token="t", cursor=_cursor(), places={place: _CONNECTED}
        )

        assert read.cursor["places"][place]["folder_id"] == "INBOX"

    async def test_a_state_with_no_read_time_resumes_its_link_from_the_floor(self, monkeypatch):
        graph = _Graph()
        graph.changes["INBOX-old"] = [_item("m1", _NOW)]
        graph.messages["m1"] = _message("m1")
        state = {
            "folder_id": "INBOX",
            "link": f"{_API}/me/mailFolders/INBOX/messages/delta?$deltatoken=INBOX-old",
        }

        read = await _adapter(graph, monkeypatch).poll(
            access_token="t", cursor=_cursor({INBOX: state}), places={INBOX: _CONNECTED}
        )

        assert [event.delivery_id for event in read.events] == ["outlook:m1"]
