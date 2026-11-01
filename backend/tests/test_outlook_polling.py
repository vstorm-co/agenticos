"""Reading Outlook folders on a schedule (#1984).

Graph reports changes a folder at a time, so what is worth holding here is the
ways that shape loses or duplicates work, beyond the ones Gmail's tests cover:

* a **change** to old mail - marked read, flagged - mistaken for an arrival;
* a **folder** that cannot be read stopping the folders that can;
* a **first read** of a place walking the whole folder instead of what is news;
* a **delta link** Graph has expired treated as an error;
* a **watched folder** deleted or renamed stopping every folder on the account.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app.services.portals import PortalUnreachable, outlook_place
from app.services.portals.exceptions import AttachmentTooLarge
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


class _Chunks(httpx.AsyncByteStream):
    """A body arriving in chunks, counting how many were pulled off the wire."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks
        self.pulled = 0

    async def __aiter__(self):
        for chunk in self._chunks:
            self.pulled += 1
            yield chunk


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
        self.requests: list[httpx.Request] = []
        self.streams: list[_Chunks] = []
        self.html: dict[str, str] = {}
        self.blobs: dict[tuple[str, str], list[bytes]] = {}
        self.blob_status: int | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.asked.append(url)
        self.requests.append(request)
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
        if path.endswith("/$value"):
            if self.blob_status is not None:
                return httpx.Response(
                    self.blob_status,
                    json={"error": {"code": "ErrorItemNotFound", "message": "Bearer t echoed"}},
                )
            chunks = self.blobs.get((path.split("/")[2], path.split("/")[4]), [])
            stream = _Chunks(chunks)
            self.streams.append(stream)
            return httpx.Response(200, content=stream)
        if path.endswith("/attachments"):
            return httpx.Response(200, json={"value": self.attachments.get(path.split("/")[2], [])})
        if path.startswith("/messages/"):
            found = self.messages.get(path.split("/")[2])
            if found is None:
                return httpx.Response(404, json={"error": {"code": "ErrorItemNotFound"}})
            if "html" in request.headers["Prefer"]:
                content = self.html.get(path.split("/")[2], "")
                return httpx.Response(
                    200, json={"body": {"contentType": "html", "content": content}}
                )
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
    @pytest.mark.parametrize(
        ("mailbox", "folder"),
        [("ops|alerts@corp.test", "inbox"), (None, "Reports|2026"), ("a%7Cb@corp.test", "x%y")],
    )
    def test_a_delimiter_inside_either_half_survives_the_round_trip(self, mailbox, folder):
        """Codex on #2195: `|` is legal in an address's local part, and the key was
        split at the first one - `ops|alerts@corp.test` read as mailbox `ops`."""
        from app.services.portals.outlook import _place

        assert _place(outlook_place(mailbox=mailbox, folder=folder)) == (
            mailbox.casefold() if mailbox else None,
            folder.casefold(),
        )

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
        assert read.cursor["places"] == {}
        # One lookup names the account the cursor belongs to; no mail is read.
        assert read.cursor["account"] == "INBOX"
        assert [urlsplit(url).path for url in graph.asked] == ["/v1.0/me/mailFolders/inbox"]

    async def test_the_account_is_carried_from_poll_to_poll(self, monkeypatch):
        graph = _Graph()

        read = await _adapter(graph, monkeypatch).poll(
            access_token="t", cursor={**_cursor(), "account": "INBOX"}, places={}
        )

        assert read.cursor["account"] == "INBOX"

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
            {"id": "a1", "name": "invoice.pdf", "contentType": "application/pdf", "size": 1200},
            {
                "id": "a2",
                "name": "logo.png",
                "contentType": "image/png",
                "size": 10,
                "isInline": True,
            },
            {"id": "a3", "name": "notes.txt", "contentType": "text/plain", "size": "big"},
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
            {
                "attachment_id": "a1",
                "name": "invoice.pdf",
                "content_type": "application/pdf",
                "size": 1200,
            },
            {
                "attachment_id": "a3",
                "name": "notes.txt",
                "content_type": "text/plain",
                "size": None,
            },
        ]
        assert payload["authenticated"] is False

    @pytest.mark.parametrize(
        ("headers", "vouched"),
        [
            # Exchange's own verdict on mail from outside.
            (
                [
                    {
                        "name": "Authentication-Results",
                        "value": "spf=pass; dmarc=pass header.from=acme.test",
                    }
                ],
                True,
            ),
            # Mail between two of the tenant's mailboxes carries no SPF/DKIM result;
            # Exchange marks it internal and strips that mark from outside mail.
            ([{"name": "X-MS-Exchange-Organization-AuthAs", "value": "Internal"}], True),
            ([{"name": "X-MS-Exchange-Organization-AuthAs", "value": "Anonymous"}], False),
            (
                [
                    {"name": "Authentication-Results", "value": "dmarc=fail header.from=acme.test"},
                    "junk",
                ],
                False,
            ),
        ],
    )
    async def test_exchanges_verdict_on_the_sender_rides_in_the_payload(
        self, monkeypatch, headers, vouched
    ):
        graph = _Graph()
        graph.deltas["INBOX"] = [[_item("m1", _NOW)]]
        graph.messages["m1"] = _message("m1", internetMessageHeaders=headers)

        read = await _adapter(graph, monkeypatch).poll(
            access_token="t", cursor=_cursor(), places={INBOX: _CONNECTED}
        )

        assert read.events[0].payload["authenticated"] is vouched

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

    @pytest.mark.parametrize(
        "error",
        [
            {"code": "invalidRequest", "innerError": {"code": "syncStateNotFound"}},
            {"code": "SyncStateInvalid"},
        ],
        ids=["nested", "top-level"],
    )
    async def test_a_lost_sync_state_restarts_whatever_status_carries_it(self, monkeypatch, error):
        """Microsoft documents an expired Outlook delta token as "a 40X-series error
        with error codes such as syncStateNotFound" - a 410 only sometimes. The
        code, at whichever level Graph puts it, is what restarts the place."""
        graph = _Graph()
        graph.deltas["INBOX"] = [[_item("m1", _NOW)]]
        graph.messages["m1"] = _message("m1")
        original = graph.handler

        def lost(request: httpx.Request) -> httpx.Response:
            if "%24deltatoken=INBOX-old" in str(request.url) or "$deltatoken=INBOX-old" in str(
                request.url
            ):
                return httpx.Response(400, json={"error": error})
            return original(request)

        graph.handler = lost  # type: ignore[method-assign]
        state = {
            "folder_id": "INBOX",
            "link": f"{_API}/me/mailFolders/INBOX/messages/delta?$deltatoken=INBOX-old",
            "read_at": (_NOW - timedelta(minutes=30)).isoformat(),
        }

        read = await _adapter(graph, monkeypatch).poll(
            access_token="t", cursor=_cursor({INBOX: state}), places={INBOX: _CONNECTED}
        )

        assert [event.delivery_id for event in read.events] == ["outlook:m1"]
        assert read.unreadable == frozenset()

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

    async def test_a_folder_made_again_is_found_by_its_path_and_read(self, monkeypatch):
        """The kept folder id no longer opens - the folder was deleted and made
        again under the same name. One lookup by path, and the place reads on."""
        graph = _Graph()
        graph.top_level["invoices"] = "NEW"
        graph.deltas["NEW"] = [[_item("m1", _NOW)]]
        graph.messages["m1"] = _message("m1")
        original = graph.handler

        def gone(request: httpx.Request) -> httpx.Response:
            if "/mailFolders/OLD/" in str(request.url):
                return httpx.Response(404, json={"error": {"code": "ErrorItemNotFound"}})
            return original(request)

        graph.handler = gone  # type: ignore[method-assign]
        invoices = outlook_place(mailbox=None, folder="Invoices")
        state = {
            "folder_id": "OLD",
            "link": f"{_API}/me/mailFolders/OLD/messages/delta?$deltatoken=OLD-1",
            "read_at": (_NOW - timedelta(minutes=10)).isoformat(),
        }

        read = await _adapter(graph, monkeypatch).poll(
            access_token="t", cursor=_cursor({invoices: state}), places={invoices: _CONNECTED}
        )

        assert [event.delivery_id for event in read.events] == ["outlook:m1"]
        assert read.cursor["places"][invoices]["folder_id"] == "NEW"

    async def test_a_folder_deleted_for_good_stops_only_its_own_place(self, monkeypatch):
        """Before, the delta's 404 failed the whole poll on every tick, so one
        deleted folder silenced every trigger on the account."""
        graph = _Graph()
        graph.deltas["INBOX"] = [[_item("m1", _NOW)]]
        graph.messages["m1"] = _message("m1")
        original = graph.handler

        def gone(request: httpx.Request) -> httpx.Response:
            if "/mailFolders/OLD/" in str(request.url):
                return httpx.Response(404, json={"error": {"code": "ErrorItemNotFound"}})
            return original(request)

        graph.handler = gone  # type: ignore[method-assign]
        invoices = outlook_place(mailbox=None, folder="Invoices")
        state = {"folder_id": "OLD", "link": None, "read_at": _NOW.isoformat()}

        read = await _adapter(graph, monkeypatch).poll(
            access_token="t",
            cursor=_cursor({invoices: state}),
            places={invoices: _CONNECTED, INBOX: _CONNECTED},
        )

        assert read.unreadable == frozenset({invoices})
        assert [event.delivery_id for event in read.events] == ["outlook:m1"]

    async def test_a_folder_found_but_not_readable_is_unreadable_at_once(self, monkeypatch):
        """Found just now, so there is nothing to look up again: a shared mailbox
        whose folder list is visible but whose messages are not."""
        graph = _Graph()
        original = graph.handler
        deltas: list[str] = []

        def refused(request: httpx.Request) -> httpx.Response:
            if "/messages/delta" in str(request.url):
                deltas.append(str(request.url))
                return httpx.Response(403, json={"error": {"message": "no code here"}})
            return original(request)

        graph.handler = refused  # type: ignore[method-assign]

        read = await _adapter(graph, monkeypatch).poll(
            access_token="t", cursor=_cursor(), places={INBOX: _CONNECTED}
        )

        assert read.unreadable == frozenset({INBOX})
        assert len(deltas) == 1

    async def test_every_well_known_name_is_addressed_directly(self, monkeypatch):
        """Graph's table of well-known names, which work in any mailbox language -
        `msgfolderroot` is not a display name anybody could look up."""
        graph = _Graph()
        graph.folders["me|msgfolderroot"] = "ROOT"
        root = outlook_place(mailbox=None, folder="msgfolderroot")

        await _adapter(graph, monkeypatch).poll(
            access_token="t", cursor=_cursor(), places={root: _CONNECTED}
        )

        assert any("/mailFolders/msgfolderroot" in url for url in graph.asked)
        assert not any("%24filter=displayName" in url for url in graph.asked)

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

    async def test_a_burst_is_read_over_several_ticks_oldest_first_and_none_is_lost(
        self, monkeypatch
    ):
        graph = _Graph()
        graph.deltas["INBOX"] = [
            [_item(f"m{index:02}", _NOW + timedelta(seconds=index)) for index in range(60)]
        ]
        graph.messages.update({f"m{index:02}": _message(f"m{index:02}") for index in range(60)})
        adapter = _adapter(graph, monkeypatch)

        first = await adapter.poll(access_token="t", cursor=_cursor(), places={INBOX: _CONNECTED})
        second = await adapter.poll(
            access_token="t", cursor=first.cursor, places={INBOX: _CONNECTED}
        )
        third = await adapter.poll(
            access_token="t", cursor=second.cursor, places={INBOX: _CONNECTED}
        )

        read = [event.delivery_id for poll in (first, second, third) for event in poll.events]
        assert read == [f"outlook:m{index:02}" for index in range(60)]
        assert [len(poll.events) for poll in (first, second, third)] == [25, 25, 10]
        assert len(first.cursor["pending"]) == 35 and len(second.cursor["pending"]) == 10
        assert "pending" not in third.cursor

    async def test_the_backlog_of_a_place_nobody_watches_or_an_entry_that_is_malformed_is_dropped(
        self, monkeypatch
    ):
        graph = _Graph()
        stamp = _stamp(_NOW)
        cursor = _cursor()
        cursor["pending"] = [
            [stamp, INBOX, "m1"],
            [stamp, "gone|place", "m2"],
            [stamp, INBOX],
            ["not a time", INBOX, "m3"],
            [stamp, INBOX, 7],
            "junk",
        ]
        graph.messages["m1"] = _message("m1")

        read = await _adapter(graph, monkeypatch).poll(
            access_token="t", cursor=cursor, places={INBOX: _CONNECTED}
        )

        assert [event.delivery_id for event in read.events] == ["outlook:m1"]
        assert "pending" not in read.cursor

    async def test_the_backlog_of_a_place_that_cannot_be_read_is_dropped(self, monkeypatch):
        graph = _Graph()
        graph.unreadable_mailboxes.add("ops@corp.test")
        shared = outlook_place(mailbox="ops@corp.test", folder="inbox")
        cursor = _cursor()
        cursor["pending"] = [[_stamp(_NOW), shared, "m9"]]

        read = await _adapter(graph, monkeypatch).poll(
            access_token="t", cursor=cursor, places={shared: _CONNECTED, INBOX: _CONNECTED}
        )

        assert read.unreadable == frozenset({shared})
        assert read.events == () and "pending" not in read.cursor

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

    async def test_the_rest_of_a_snapshot_keeps_the_floor_it_began_with(self, monkeypatch):
        """Codex on #2195: the next tick carried on with the later read time as its
        floor, so mail received before it - but inside the snapshot being paged -
        was dropped before the round reached its delta link."""
        graph = _Graph()
        older = _NOW - timedelta(hours=2)
        graph.deltas["INBOX"] = [[_item(f"p{index}", _NOW)] for index in range(10)] + [
            [_item("late-page", older)]
        ]
        graph.messages.update({f"p{index}": _message(f"p{index}") for index in range(10)})
        graph.messages["late-page"] = _message("late-page")
        adapter = _adapter(graph, monkeypatch)

        first = await adapter.poll(access_token="t", cursor=_cursor(), places={INBOX: _CONNECTED})
        assert first.cursor["places"][INBOX]["floor"] == _CONNECTED.isoformat()
        second = await adapter.poll(
            access_token="t", cursor=first.cursor, places={INBOX: _CONNECTED}
        )

        assert [event.delivery_id for event in second.events] == ["outlook:late-page"]
        # The round is complete: the next one starts from this read.
        assert "floor" not in second.cursor["places"][INBOX]

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
        # An inbox that answers without an id leaves the account unnamed, not the
        # poll failed.
        graph.folders["me|inbox"] = ""

        read = await _adapter(graph, monkeypatch).poll(
            access_token="t", cursor={"connected_at": "not a time"}, places={INBOX: _CONNECTED}
        )

        assert read.events == ()
        assert "account" not in read.cursor
        assert len(graph.asked) == 1


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
        """A lost sync state means "start over"; an outage leaves the cursor alone."""
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


async def _event(
    graph: _Graph, monkeypatch, place: str = INBOX, *, html_places: tuple[str, ...] = (INBOX,)
) -> dict[str, Any]:
    graph.deltas["INBOX"] = [[_item("m1", _NOW)]]
    read = await _adapter(graph, monkeypatch).poll(
        access_token="t",
        cursor=_cursor(),
        places={place: _CONNECTED},
        html_places=html_places,
    )
    return read.events[0].payload


class TestTheThreadItCarries:
    async def test_the_message_read_selects_the_thread_ids(self, monkeypatch):
        graph = _Graph()
        graph.messages["m1"] = _message("m1")

        await _event(graph, monkeypatch)

        [delta] = [one for one in graph.requests if one.url.path.endswith("/messages/delta")][:1]
        read = next(
            one
            for one in graph.requests
            if one.url.path.endswith("/messages/m1")
            and "internetMessageId" in one.url.query.decode()
        )
        select = read.url.params["$select"]
        assert "internetMessageId" in select
        assert "conversationId" in select
        assert delta.url.params["$select"] == "id,receivedDateTime,isDraft"

    async def test_a_reply_carries_its_thread(self, monkeypatch):
        graph = _Graph()
        graph.messages["m1"] = _message(
            "m1",
            conversationId="conv-9",
            internetMessageId="<c@mail.test>",
            internetMessageHeaders=[
                {"name": "In-Reply-To", "value": "<b@mail.test>"},
                {"name": "References", "value": "<a@mail.test> <b@mail.test> <a@mail.test>"},
                {"name": "Message-ID", "value": "<header@mail.test>"},
            ],
        )

        payload = await _event(graph, monkeypatch)

        assert payload["thread_id"] == "conv-9"
        assert payload["rfc_message_id"] == "<c@mail.test>"
        assert payload["in_reply_to"] == "<b@mail.test>"
        assert payload["references"] == ["<a@mail.test>", "<b@mail.test>"]

    @pytest.mark.parametrize(
        "graph_id", ["no-brackets@mail.test", "", "<" + "x" * 999 + ">", "<a b@mail.test>"]
    )
    async def test_a_graph_id_not_in_rfc_form_gives_way_to_the_header(self, monkeypatch, graph_id):
        graph = _Graph()
        graph.messages["m1"] = _message(
            "m1",
            internetMessageId=graph_id,
            internetMessageHeaders=[{"name": "Message-ID", "value": "<header@mail.test>"}],
        )

        assert (await _event(graph, monkeypatch))["rfc_message_id"] == "<header@mail.test>"

    async def test_a_graph_id_with_whitespace_is_trimmed_to_the_id(self, monkeypatch):
        graph = _Graph()
        graph.messages["m1"] = _message("m1", internetMessageId="  <c@mail.test>\r\n ")

        assert (await _event(graph, monkeypatch))["rfc_message_id"] == "<c@mail.test>"

    async def test_the_message_id_header_stands_in_when_graph_gives_none(self, monkeypatch):
        graph = _Graph()
        graph.messages["m1"] = _message(
            "m1",
            internetMessageId=None,
            internetMessageHeaders=[{"name": "Message-ID", "value": "<header@mail.test>"}],
        )

        payload = await _event(graph, monkeypatch)

        assert payload["rfc_message_id"] == "<header@mail.test>"

    async def test_a_message_without_thread_ids_gets_empty_values(self, monkeypatch):
        graph = _Graph()
        graph.messages["m1"] = _message("m1")

        payload = await _event(graph, monkeypatch)

        assert payload["thread_id"] == ""
        assert payload["rfc_message_id"] == ""
        assert payload["in_reply_to"] == ""
        assert payload["references"] == []


class TestTheHtmlItCarries:
    async def test_the_html_body_is_read_in_a_second_request(self, monkeypatch):
        graph = _Graph()
        graph.messages["m1"] = _message("m1")
        graph.html["m1"] = "<p>Please pay invoice 42.</p>"

        payload = await _event(graph, monkeypatch)

        assert payload["html"] == "<p>Please pay invoice 42.</p>"
        assert payload["text"] == "Please pay invoice 42."
        second = [one for one in graph.requests if "html" in one.headers.get("Prefer", "")]
        [html_read] = second
        assert (
            html_read.headers["Prefer"] == 'outlook.body-content-type="html", IdType="ImmutableId"'
        )
        assert html_read.url.params["$select"] == "body"

    async def test_no_html_is_asked_for_a_place_no_workflow_listens_to(self, monkeypatch):
        graph = _Graph()
        graph.messages["m1"] = _message("m1")
        graph.html["m1"] = "<p>Please pay invoice 42.</p>"

        payload = await _event(graph, monkeypatch, html_places=())

        assert payload["html"] == "" and payload["text"] == "Please pay invoice 42."
        assert not [one for one in graph.requests if "html" in one.headers.get("Prefer", "")]

    async def test_html_is_clipped_like_text(self, monkeypatch):
        graph = _Graph()
        graph.messages["m1"] = _message("m1")
        graph.html["m1"] = "x" * 30_000

        payload = await _event(graph, monkeypatch)

        assert len(payload["html"]) == 20_000

    async def test_a_message_deleted_between_the_two_reads_has_empty_html(self, monkeypatch):
        graph = _Graph()
        graph.messages["m1"] = _message("m1")
        original = graph.handler

        def vanish(request: httpx.Request) -> httpx.Response:
            if "html" in request.headers["Prefer"]:
                return httpx.Response(404, json={"error": {"code": "ErrorItemNotFound"}})
            return original(request)

        graph.handler = vanish  # type: ignore[method-assign]

        payload = await _event(graph, monkeypatch)

        assert payload["html"] == ""
        assert payload["text"] == "Please pay invoice 42."

    @pytest.mark.parametrize("status", [429, 503])
    async def test_a_throttled_or_failing_html_read_has_empty_html(self, monkeypatch, status):
        graph = _Graph()
        graph.messages["m1"] = _message("m1")
        original = graph.handler

        def broken(request: httpx.Request) -> httpx.Response:
            if "html" in request.headers["Prefer"]:
                return httpx.Response(status, json={})
            return original(request)

        graph.handler = broken  # type: ignore[method-assign]

        payload = await _event(graph, monkeypatch)

        assert payload["html"] == ""
        assert payload["text"] == "Please pay invoice 42."

    async def test_a_body_that_is_not_an_object_reads_as_empty_html(self, monkeypatch):
        graph = _Graph()
        graph.messages["m1"] = _message("m1")
        original = graph.handler

        def odd(request: httpx.Request) -> httpx.Response:
            if "html" in request.headers["Prefer"]:
                return httpx.Response(200, json={"body": None})
            return original(request)

        graph.handler = odd  # type: ignore[method-assign]

        assert (await _event(graph, monkeypatch))["html"] == ""


class TestTheAttachmentsItLists:
    async def test_listed_attachments_carry_their_ids_and_only_files_are_listed(self, monkeypatch):
        graph = _Graph()
        graph.messages["m1"] = _message("m1", hasAttachments=True)
        graph.attachments["m1"] = [
            {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "id": "a1",
                "name": "invoice.pdf",
                "contentType": "application/pdf",
                "size": 1200,
            },
            {
                "@odata.type": "#microsoft.graph.itemAttachment",
                "id": "a2",
                "name": "Forwarded mail",
                "contentType": "message/rfc822",
                "size": 40,
            },
            {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "id": "a3",
                "name": "logo.png",
                "isInline": True,
            },
            {"@odata.type": "#microsoft.graph.fileAttachment", "name": "no-id.txt"},
        ]

        payload = await _event(graph, monkeypatch)

        assert payload["attachments"] == [
            {
                "attachment_id": "a1",
                "name": "invoice.pdf",
                "content_type": "application/pdf",
                "size": 1200,
            }
        ]
        listing = next(one for one in graph.requests if one.url.path.endswith("/attachments"))
        assert listing.url.params["$select"] == "id,name,contentType,size,isInline"


async def _read(
    graph: _Graph, monkeypatch, *, mailbox: str | None = None, max_bytes: int = 100
) -> bytes:
    return await _adapter(graph, monkeypatch).attachment(
        access_token="t",
        message_id="m1",
        attachment_id="a1",
        mailbox=mailbox,
        max_bytes=max_bytes,
    )


class TestReadingAnAttachment:
    async def test_an_attachment_is_read_from_the_mailbox_it_came_from(self, monkeypatch):
        graph = _Graph()
        graph.blobs[("m1", "a1")] = [b"\x00PDF", b" bytes"]

        data = await _read(graph, monkeypatch)

        assert data == b"\x00PDF bytes"
        [request] = graph.requests
        assert request.url.raw_path.decode() == "/v1.0/me/messages/m1/attachments/a1/$value"
        assert request.headers["Prefer"] == 'IdType="ImmutableId"'

    async def test_an_attachment_is_read_from_the_shared_mailbox_it_came_from(self, monkeypatch):
        graph = _Graph()
        graph.blobs[("m1", "a1")] = [b"shared"]

        assert await _read(graph, monkeypatch, mailbox="support@x") == b"shared"

        assert (
            graph.requests[0].url.path == "/v1.0/users/support@x/messages/m1/attachments/a1/$value"
        )

    async def test_the_ids_are_quoted_whole(self, monkeypatch):
        graph = _Graph()

        def answer(request: httpx.Request) -> httpx.Response:
            graph.requests.append(request)
            return httpx.Response(200, content=b"ok")

        graph.handler = answer  # type: ignore[method-assign]

        await _adapter(graph, monkeypatch).attachment(
            access_token="t", message_id="m/1", attachment_id="a=1", mailbox=None, max_bytes=9
        )

        assert graph.requests[0].url.raw_path.decode() == (
            "/v1.0/me/messages/m%2F1/attachments/a%3D1/$value"
        )

    async def test_an_attachment_exactly_at_the_limit_is_read(self, monkeypatch):
        graph = _Graph()
        graph.blobs[("m1", "a1")] = [b"x" * 60, b"y" * 40]

        assert len(await _read(graph, monkeypatch, max_bytes=100)) == 100

    async def test_an_attachment_past_the_limit_stops_reading(self, monkeypatch):
        graph = _Graph()
        graph.blobs[("m1", "a1")] = [b"x" * 40, b"y" * 40, b"z" * 40]

        with pytest.raises(AttachmentTooLarge):
            await _read(graph, monkeypatch, max_bytes=60)

        # The third chunk was never pulled off the wire.
        assert graph.streams[0].pulled == 2

    async def test_a_refused_attachment_carries_the_status_and_not_the_text(self, monkeypatch):
        graph = _Graph()
        graph.blob_status = 404

        with pytest.raises(PortalUnreachable) as caught:
            await _read(graph, monkeypatch)

        assert caught.value.details == {
            "portal_key": "microsoft",
            "status": 404,
            "codes": ["erroritemnotfound"],
        }
        assert "echoed" not in caught.value.message

    async def test_a_redirect_is_not_an_attachment(self, monkeypatch):
        graph = _Graph()
        graph.handler = lambda request: httpx.Response(  # type: ignore[method-assign]
            302, headers={"Location": "https://elsewhere.test/"}, content=b"<a>moved</a>"
        )

        with pytest.raises(PortalUnreachable) as caught:
            await _read(graph, monkeypatch)

        assert caught.value.details == {"portal_key": "microsoft", "status": 302}

    async def test_a_refusal_with_no_error_codes_carries_only_the_status(self, monkeypatch):
        graph = _Graph()

        def plain(request: httpx.Request) -> httpx.Response:
            return httpx.Response(502, content=b"Bad gateway Bearer t")

        graph.handler = plain  # type: ignore[method-assign]

        with pytest.raises(PortalUnreachable) as caught:
            await _read(graph, monkeypatch)

        assert caught.value.details == {"portal_key": "microsoft", "status": 502}

    async def test_a_broken_connection_is_unreachable_without_its_text(self, monkeypatch):
        graph = _Graph()

        def refuse(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("Bearer t timed out")

        graph.handler = refuse  # type: ignore[method-assign]

        with pytest.raises(PortalUnreachable) as caught:
            await _read(graph, monkeypatch)

        assert caught.value.details == {"portal_key": "microsoft", "error": "ReadTimeout"}
