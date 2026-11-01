"""Reading a mailbox on a schedule, and firing what arrived.

The delivery mechanism a Gmail trigger has instead of a webhook. What is worth
holding here is not that a message can be read - it is the four ways a poller
silently loses or duplicates work:

* a **first** poll that fires the agent once per message already in the mailbox;
* a **cursor** advanced before the fires are dispatched, so a crash between the
  two says the messages were handled when nothing handled them;
* an **expired** cursor - Google keeps about a week - treated as an error, which
  parks a mailbox that went unread over a holiday for ever;
* a **burst** read in full, turning one mailing-list dump into four hundred agent
  runs.
"""

import base64
from typing import Any

import httpx
import pytest

from app.services.portals import PortalUnreachable
from app.services.portals.exceptions import AttachmentTooLarge
from app.services.portals.google import GooglePortalAdapter

pytestmark = pytest.mark.anyio


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def _message(
    identifier: str,
    *,
    subject: str,
    sender: str,
    body: str,
    labels: list[str],
    thread_id: str | None = None,
    extra_headers: list[tuple[str, str]] | None = None,
    parts: list[dict[str, Any]] | None = None,
    internal_date: str | None = None,
):
    message: dict[str, Any] = {
        "id": identifier,
        "labelIds": labels,
        "snippet": body[:40],
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [
                {"name": "Subject", "value": subject},
                {"name": "From", "value": sender},
                {"name": "To", "value": "me@acme.test"},
                *({"name": name, "value": value} for name, value in extra_headers or []),
            ],
            "parts": parts
            if parts is not None
            else [
                {"mimeType": "text/html", "body": {"data": _b64(f"<p>{body}</p>")}},
                {"mimeType": "text/plain", "body": {"data": _b64(body)}},
            ],
        },
    }
    if thread_id is not None:
        message["threadId"] = thread_id
    if internal_date is not None:
        message["internalDate"] = internal_date
    return message


class _Gmail:
    """A Gmail that answers the three endpoints the adapter uses."""

    def __init__(
        self,
        *,
        history_id: str = "500",
        added: list[str] | None = None,
        messages: dict[str, dict[str, Any]] | None = None,
        history_status: int = 200,
        pages: int = 1,
    ) -> None:
        self.history_id = history_id
        self.added = added or []
        self.messages = messages or {}
        self.history_status = history_status
        self.pages = pages
        self.asked: list[str] = []
        self.raw: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.asked.append(str(request.url.path))
        if request.url.path.endswith("/profile"):
            return httpx.Response(200, json={"historyId": self.history_id})
        if request.url.path.endswith("/history"):
            if self.history_status != 200:
                return httpx.Response(self.history_status, json={"error": "gone"})
            page = request.url.params.get("pageToken")
            index = 0 if page is None else int(page)
            body: dict[str, Any] = {
                "historyId": self.history_id,
                "history": [
                    {"messagesAdded": [{"message": {"id": one}} for one in self.added[index::]]}
                ],
            }
            if index + 1 < self.pages:
                body["nextPageToken"] = str(index + 1)
            return httpx.Response(200, json=body)
        identifier = request.url.path.rsplit("/", 1)[-1]
        found = self.messages.get(identifier)
        if found is None:
            return httpx.Response(404, json={"error": "not found"})
        return httpx.Response(200, json=found)


def _adapter(gmail: _Gmail, monkeypatch) -> GooglePortalAdapter:
    """The adapter with its transport swapped for `gmail`, and nothing else."""
    original = httpx.AsyncClient.__init__

    def patched(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs["transport"] = httpx.MockTransport(gmail.handler)
        original(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched)
    return GooglePortalAdapter()


class TestTheFirstPoll:
    async def test_it_establishes_the_position_and_fires_nothing(self, monkeypatch):
        """Otherwise connecting a mailbox fires the agent once per message already
        in it - which is not what connecting means."""
        gmail = _Gmail(history_id="900", added=["m1", "m2"])

        read = await _adapter(gmail, monkeypatch).poll(access_token="t", cursor=None)

        assert read.events == ()
        assert read.cursor == {"history_id": "900"}
        # And it did not read the history at all: there is no "since" to ask about.
        assert not any(path.endswith("/history") for path in gmail.asked)

    async def test_a_cursor_with_no_history_id_is_treated_as_a_first_poll(self, monkeypatch):
        gmail = _Gmail(history_id="901")

        read = await _adapter(gmail, monkeypatch).poll(access_token="t", cursor={})

        assert read.events == ()
        assert read.cursor == {"history_id": "901"}


class TestReadingWhatArrived:
    async def test_a_message_becomes_the_payload_the_filters_already_match(self, monkeypatch):
        """The keys are `trigger_events`' own, so a polled event and a posted one
        are the same shape by the time a trigger is chosen."""
        gmail = _Gmail(
            history_id="510",
            added=["m1"],
            messages={
                "m1": _message(
                    "m1",
                    subject="Invoice 42",
                    sender="Billing <billing@acme.test>",
                    body="Please pay this.",
                    labels=["INBOX", "IMPORTANT"],
                )
            },
        )

        read = await _adapter(gmail, monkeypatch).poll(
            access_token="t", cursor={"history_id": "500"}
        )

        [event] = read.events
        assert event.payload["subject"] == "Invoice 42"
        assert event.payload["from"] == "Billing <billing@acme.test>"
        assert event.payload["labels"] == ["INBOX", "IMPORTANT"]
        # The plain-text part, not the HTML one: what reaches the agent should be
        # what a person would read rather than markup it has to strip.
        assert event.payload["text"] == "Please pay this."
        # No verdict from Gmail, so nothing vouches for the sender.
        assert event.payload["authenticated"] is False
        assert read.cursor == {"history_id": "510"}

    async def test_gmails_own_verdict_on_the_sender_rides_in_the_payload(self, monkeypatch):
        """A sender filter fires only on mail the sender's domain signed; the
        adapter reads Gmail's topmost `Authentication-Results` to say so."""
        message = _message(
            "m1", subject="s", sender="Billing <billing@acme.test>", body="b", labels=["INBOX"]
        )
        message["payload"]["headers"].insert(
            0,
            {
                "name": "Authentication-Results",
                "value": "mx.google.com; dmarc=pass header.from=acme.test",
            },
        )
        gmail = _Gmail(history_id="510", added=["m1"], messages={"m1": message})

        read = await _adapter(gmail, monkeypatch).poll(
            access_token="t", cursor={"history_id": "500"}
        )

        assert read.events[0].payload["authenticated"] is True

    async def test_the_delivery_id_is_gmails_own_so_a_reread_dedups(self, monkeypatch):
        """A crash after dispatch and before the cursor advances re-reads the same
        messages - which is the safe direction only because this key is stable."""
        gmail = _Gmail(
            history_id="510",
            added=["m1"],
            messages={"m1": _message("m1", subject="s", sender="f", body="b", labels=[])},
        )
        adapter = _adapter(gmail, monkeypatch)

        first = await adapter.poll(access_token="t", cursor={"history_id": "500"})
        again = await adapter.poll(access_token="t", cursor={"history_id": "500"})

        assert first.events[0].delivery_id == again.events[0].delivery_id == "gmail:m1"

    async def test_a_message_deleted_between_the_two_reads_is_skipped(self, monkeypatch):
        """The history says it arrived and `messages.get` says it is gone. One
        missing message must not cost the rest of the batch their fire."""
        gmail = _Gmail(
            history_id="510",
            added=["gone", "m2"],
            messages={"m2": _message("m2", subject="s", sender="f", body="b", labels=[])},
        )

        read = await _adapter(gmail, monkeypatch).poll(
            access_token="t", cursor={"history_id": "500"}
        )

        assert [event.payload["message_id"] for event in read.events] == ["m2"]

    async def test_nothing_added_advances_the_cursor_and_reads_no_message(self, monkeypatch):
        gmail = _Gmail(history_id="512", added=[])

        read = await _adapter(gmail, monkeypatch).poll(
            access_token="t", cursor={"history_id": "500"}
        )

        assert read.events == ()
        assert read.cursor == {"history_id": "512"}
        assert not any("/messages/" in path for path in gmail.asked)


class TestTheWaysAPollerLosesWork:
    async def test_an_expired_cursor_resynchronises_instead_of_failing(self, monkeypatch):
        """Google keeps about a week of history. Treating a 404 as an error parks a
        mailbox nobody looked at over a holiday for ever."""
        gmail = _Gmail(history_id="999", history_status=404)

        read = await _adapter(gmail, monkeypatch).poll(access_token="t", cursor={"history_id": "1"})

        assert read.events == ()
        assert read.cursor == {"history_id": "999"}

    async def test_a_provider_that_refuses_raises_so_the_cursor_is_left_alone(self, monkeypatch):
        """A 401 is a revoked grant and a 500 is Google's day. Either way the tick
        must not advance the cursor over messages it never read."""
        gmail = _Gmail(history_status=500)

        with pytest.raises(PortalUnreachable):
            await _adapter(gmail, monkeypatch).poll(access_token="t", cursor={"history_id": "500"})

    async def test_a_200_that_is_not_json_is_the_recoverable_poll_failure(self, monkeypatch):
        """An intermediary's HTML error page raises out of `.json()`. Raw, that
        aborted the whole polling tick and rolled back every other mailbox's
        cursor; translated, `poll_grant` marks this one grant and moves on."""

        def html(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"<html>proxy error</html>")

        gmail = _Gmail()
        gmail.handler = html  # type: ignore[method-assign]

        with pytest.raises(PortalUnreachable):
            await _adapter(gmail, monkeypatch).poll(access_token="t", cursor={"history_id": "500"})

    async def test_a_burst_is_bounded_and_the_cursor_still_advances(self, monkeypatch):
        """One mailing-list dump must not become four hundred agent runs - and must
        not be re-read for ever either, which is why the cursor moves anyway."""
        from app.services.portals.google import _MAX_MESSAGES_PER_POLL

        many = [f"m{n}" for n in range(_MAX_MESSAGES_PER_POLL + 10)]
        gmail = _Gmail(
            history_id="600",
            added=many,
            messages={
                one: _message(one, subject="s", sender="f", body="b", labels=[]) for one in many
            },
        )

        read = await _adapter(gmail, monkeypatch).poll(
            access_token="t", cursor={"history_id": "500"}
        )

        assert len(read.events) == _MAX_MESSAGES_PER_POLL
        # The unread tail stays durable in the cursor for the next tick.
        assert read.events[-1].payload["message_id"] == many[24]
        assert read.cursor["pending_message_ids"] == many[25:]
        assert read.cursor["history_id"] == "600"

    async def test_it_follows_the_history_pages(self, monkeypatch):
        gmail = _Gmail(
            history_id="600",
            added=["m1", "m2"],
            pages=2,
            messages={
                "m1": _message("m1", subject="s", sender="f", body="b", labels=[]),
                "m2": _message("m2", subject="s", sender="f", body="b", labels=[]),
            },
        )

        read = await _adapter(gmail, monkeypatch).poll(
            access_token="t", cursor={"history_id": "500"}
        )

        assert len(gmail.asked) >= 3
        assert len(read.events) >= 1


class TestTheBodyItReads:
    async def test_html_is_the_fallback_when_there_is_no_plain_part(self, monkeypatch):
        gmail = _Gmail(
            history_id="510",
            added=["m1"],
            messages={
                "m1": {
                    "id": "m1",
                    "labelIds": [],
                    "payload": {
                        "mimeType": "multipart/alternative",
                        "headers": [{"name": "Subject", "value": "s"}],
                        "parts": [{"mimeType": "text/html", "body": {"data": _b64("<p>hi</p>")}}],
                    },
                }
            },
        )

        read = await _adapter(gmail, monkeypatch).poll(
            access_token="t", cursor={"history_id": "500"}
        )

        assert read.events[0].payload["text"] == "<p>hi</p>"

    async def test_a_body_is_clipped_rather_than_filling_the_prompt(self, monkeypatch):
        from app.services.portals.google import _MAX_BODY_CHARS

        gmail = _Gmail(
            history_id="510",
            added=["m1"],
            messages={"m1": _message("m1", subject="s", sender="f", body="x" * 60_000, labels=[])},
        )

        read = await _adapter(gmail, monkeypatch).poll(
            access_token="t", cursor={"history_id": "500"}
        )

        assert len(read.events[0].payload["text"]) == _MAX_BODY_CHARS

    async def test_a_mime_tree_deeper_than_the_bound_answers_empty(self, monkeypatch):
        """A MIME tree is attacker-shaped input - anybody who can email this mailbox
        chooses it - so a deeply nested one is a stack, not a message."""
        deep: dict[str, Any] = {"mimeType": "text/plain", "body": {"data": _b64("deep")}}
        for _ in range(12):
            deep = {"mimeType": "multipart/mixed", "parts": [deep]}

        async with httpx.AsyncClient() as client:
            assert await GooglePortalAdapter()._body(client, "t", "m", deep) == ""

    async def test_an_undecodable_body_is_empty_rather_than_an_error(self, monkeypatch):
        from app.services.portals.google import _body_text

        assert _body_text({"mimeType": "text/plain", "body": {"data": "!!!not base64!!!"}}) == ""

    async def test_a_header_the_message_omits_reads_as_empty(self, monkeypatch):
        from app.services.portals.google import _header

        assert _header({"payload": {"headers": []}}, "Subject") == ""

    async def test_an_explicit_null_where_an_object_is_documented_reads_as_absent(self):
        """`.get(key, {})` is not the same as "or an empty one".

        A default applies when the key is *absent*, and JSON says `"body": null` as
        readily as it omits the field - so the chained `.get` on the answer used to
        be an `AttributeError` on `None`. Which matters more than it reads: a raise
        out of a poll aborted the whole tick, for every tenant, every minute.
        """
        from app.services.portals.google import _body_text, _header

        assert _header({"payload": None}, "Subject") == ""
        assert _body_text({"mimeType": "text/plain", "body": None}) == ""
        # And a part list whose entries are the wrong shape does not raise either.
        assert _body_text({"mimeType": "multipart/mixed", "parts": [{"body": None}]}) == ""


class TestMailboxReviewRegressions:
    async def test_body_bytes_referenced_by_attachment_id_are_read(self, monkeypatch) -> None:
        gmail = _Gmail(
            history_id="600",
            added=["m1"],
            messages={
                "m1": {
                    "labelIds": ["INBOX"],
                    "payload": {"mimeType": "text/plain", "body": {"attachmentId": "body"}},
                }
            },
        )
        original = gmail.handler

        def answer(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/attachments/body"):
                return httpx.Response(200, json={"data": _b64("The full body")})
            return original(request)

        gmail.handler = answer
        read = await _adapter(gmail, monkeypatch).poll(
            access_token="t", cursor={"history_id": "500"}
        )
        assert read.events[0].payload["text"] == "The full body"

    async def test_an_overflow_is_retained_and_read_on_the_next_tick(self, monkeypatch) -> None:
        many = [f"m{n}" for n in range(30)]
        gmail = _Gmail(
            history_id="600",
            added=many,
            messages={
                one: _message(one, subject="s", sender="f", body="b", labels=["INBOX"])
                for one in many
            },
        )
        adapter = _adapter(gmail, monkeypatch)
        first = await adapter.poll(access_token="t", cursor={"history_id": "500"})
        gmail.added = []
        second = await adapter.poll(access_token="t", cursor=first.cursor)
        assert {event.payload["message_id"] for event in (*first.events, *second.events)} == set(
            many
        )


async def test_a_bounded_history_read_resumes_after_the_last_consumed_record(monkeypatch) -> None:
    gmail = _Gmail()

    def answer(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("pageToken", "0"))
        return httpx.Response(
            200,
            json={
                "historyId": "9000",
                "history": [
                    {"id": str(501 + page), "messagesAdded": [{"message": {"id": f"m{page}"}}]}
                ],
                "nextPageToken": str(page + 1),
            },
        )

    gmail.handler = answer
    adapter = _adapter(gmail, monkeypatch)
    async with httpx.AsyncClient(base_url="https://gmail.googleapis.com") as client:
        added, resume = await adapter._added_since(client, "t", "500")
    assert added == [f"m{page}" for page in range(10)]
    assert resume == "510"


async def test_the_async_body_reader_ignores_attachments_and_malformed_parts() -> None:
    adapter = GooglePortalAdapter()
    deep: dict[str, Any] = {"mimeType": "text/plain", "body": {"data": _b64("too deep")}}
    for _ in range(10):
        deep = {"mimeType": "multipart/mixed", "parts": [deep]}
    async with httpx.AsyncClient() as client:
        text = await adapter._body(
            client,
            "t",
            "m",
            {
                "parts": [
                    None,
                    {
                        "filename": "attachment.txt",
                        "mimeType": "text/plain",
                        "body": {"data": _b64("attachment")},
                    },
                    deep,
                    {"mimeType": "text/plain", "body": {"data": _b64("body")}},
                ]
            },
        )
    assert text == "body"


async def test_a_message_read_failure_keeps_the_batch_retryable(monkeypatch) -> None:
    gmail = _Gmail(history_id="600", added=["m1"])
    original = gmail.handler

    def answer(request: httpx.Request) -> httpx.Response:
        if "/messages/" in request.url.path:
            return httpx.Response(503, json={})
        return original(request)

    gmail.handler = answer
    with pytest.raises(PortalUnreachable):
        await _adapter(gmail, monkeypatch).poll(access_token="t", cursor={"history_id": "500"})


async def test_a_gmail_transport_failure_is_a_provider_error(monkeypatch) -> None:
    gmail = _Gmail()

    def answer(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unreachable", request=request)

    gmail.handler = answer
    with pytest.raises(PortalUnreachable):
        await _adapter(gmail, monkeypatch).poll(access_token="t", cursor=None)


async def test_history_records_without_a_message_identifier_are_ignored(monkeypatch) -> None:
    gmail = _Gmail()
    gmail.handler = lambda request: httpx.Response(
        200,
        json={"historyId": "600", "history": [{"id": "599", "messagesAdded": [{"message": {}}]}]},
    )
    read = await _adapter(gmail, monkeypatch).poll(access_token="t", cursor={"history_id": "500"})
    assert read.events == ()
    assert read.cursor["history_id"] == "600"


def _polled(gmail: _Gmail, monkeypatch):
    return _adapter(gmail, monkeypatch).poll(access_token="t", cursor={"history_id": "500"})


def _one(message_id: str = "m1", **fields: Any) -> _Gmail:
    fields.setdefault("subject", "s")
    fields.setdefault("sender", "a@acme.test")
    fields.setdefault("body", "hello")
    fields.setdefault("labels", ["INBOX"])
    return _Gmail(added=[message_id], messages={message_id: _message(message_id, **fields)})


class TestTheThreadItCarries:
    async def test_a_reply_carries_its_thread(self, monkeypatch):
        gmail = _one(
            thread_id="t-77",
            extra_headers=[
                ("Message-ID", "<c@mail.test>"),
                ("In-Reply-To", "<b@mail.test>"),
                ("References", "<a@mail.test>\r\n <b@mail.test>"),
            ],
        )

        [event] = (await _polled(gmail, monkeypatch)).events

        assert event.payload["thread_id"] == "t-77"
        assert event.payload["rfc_message_id"] == "<c@mail.test>"
        assert event.payload["in_reply_to"] == "<b@mail.test>"
        assert event.payload["references"] == ["<a@mail.test>", "<b@mail.test>"]

    async def test_a_message_without_thread_headers_gets_empty_values(self, monkeypatch):
        [event] = (await _polled(_one(), monkeypatch)).events

        assert event.payload["thread_id"] == ""
        assert event.payload["rfc_message_id"] == ""
        assert event.payload["in_reply_to"] == ""
        assert event.payload["references"] == []
        assert event.payload["received_at"] == ""

    async def test_the_receipt_time_comes_from_internal_date(self, monkeypatch):
        # 2026-10-26T09:31:00Z in epoch milliseconds.
        [event] = (await _polled(_one(internal_date="1793007060000"), monkeypatch)).events

        assert event.payload["received_at"] == "2026-10-26T09:31:00+00:00"

    @pytest.mark.parametrize("raw", ["soon", "-9" * 30, "99999999999999999999999"])
    async def test_an_unreadable_internal_date_is_empty(self, monkeypatch, raw):
        [event] = (await _polled(_one(internal_date=raw), monkeypatch)).events

        assert event.payload["received_at"] == ""


class TestTheHtmlItCarries:
    async def test_the_html_part_is_carried_beside_the_text(self, monkeypatch):
        [event] = (await _polled(_one(body="hello"), monkeypatch)).events

        assert event.payload["html"] == "<p>hello</p>"
        assert event.payload["text"] == "hello"

    async def test_a_message_with_no_html_part_has_empty_html(self, monkeypatch):
        parts = [{"mimeType": "text/plain", "body": {"data": _b64("plain")}}]

        [event] = (await _polled(_one(parts=parts), monkeypatch)).events

        assert event.payload["html"] == ""

    async def test_an_html_part_stored_apart_is_fetched(self, monkeypatch):
        parts = [{"mimeType": "text/html", "body": {"attachmentId": "big"}}]
        gmail = _one(parts=parts)
        original = gmail.handler

        def answer(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/attachments/big"):
                return httpx.Response(200, json={"data": _b64("<b>stored apart</b>")})
            return original(request)

        gmail.handler = answer

        [event] = (await _polled(gmail, monkeypatch)).events

        assert event.payload["html"] == "<b>stored apart</b>"

    async def test_a_part_stored_apart_is_fetched_once_for_text_and_html(self, monkeypatch):
        parts = [{"mimeType": "text/html", "body": {"attachmentId": "big"}}]
        gmail = _one(parts=parts)
        original = gmail.handler

        def answer(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/attachments/big"):
                gmail.asked.append(request.url.path)
                return httpx.Response(200, json={"data": _b64("<b>once</b>")})
            return original(request)

        gmail.handler = answer

        [event] = (await _polled(gmail, monkeypatch)).events

        assert event.payload["html"] == "<b>once</b>"
        assert event.payload["text"] == "<b>once</b>"
        assert [one for one in gmail.asked if one.endswith("/attachments/big")] == [
            "/gmail/v1/users/me/messages/m1/attachments/big"
        ]

    async def test_html_is_clipped_like_text(self, monkeypatch):
        parts = [{"mimeType": "text/html", "body": {"data": _b64("x" * 30_000)}}]

        [event] = (await _polled(_one(parts=parts), monkeypatch)).events

        assert len(event.payload["html"]) == 20_000

    async def test_the_html_walk_stops_at_the_depth_bound_and_skips_attached_files(
        self, monkeypatch
    ):
        deep: dict[str, Any] = {"mimeType": "text/html", "body": {"data": _b64("deep")}}
        for _ in range(10):
            deep = {"mimeType": "multipart/mixed", "parts": [deep]}
        attached = {
            "mimeType": "text/html",
            "filename": "page.html",
            "body": {"data": _b64("<i>an attachment</i>")},
        }

        [event] = (await _polled(_one(parts=[deep, attached, "junk"]), monkeypatch)).events

        assert event.payload["html"] == ""


def _file(name: str, attachment_id: str, mime: str = "application/pdf", **extra: Any):
    return {
        "mimeType": mime,
        "filename": name,
        "body": {"attachmentId": attachment_id, "size": 1200},
        **extra,
    }


class TestTheAttachmentsItLists:
    async def test_attachments_are_listed_with_their_ids_and_inline_parts_are_not(
        self, monkeypatch
    ):
        parts = [
            {"mimeType": "text/plain", "body": {"data": _b64("hi")}},
            _file("invoice.pdf", "att-1"),
            _file(
                "logo.png",
                "att-2",
                "image/png",
                headers=[{"name": "Content-ID", "value": "<logo@x>"}],
            ),
            _file(
                "photo.jpg",
                "att-3",
                "image/jpeg",
                headers=[{"name": "Content-Disposition", "value": "inline; filename=photo.jpg"}],
            ),
            _file(
                "tagged.pdf",
                "att-6",
                headers=[
                    {"name": "Content-ID", "value": "<t@x>"},
                    {"name": "Content-Disposition", "value": "attachment; filename=tagged.pdf"},
                ],
            ),
            _file(
                "both.png",
                "att-7",
                "image/png",
                headers=[
                    {"name": "Content-ID", "value": "<b@x>"},
                    {"name": "Content-Disposition", "value": "inline"},
                ],
            ),
            {"mimeType": "application/pdf", "filename": "", "body": {"attachmentId": "att-4"}},
            {"mimeType": "application/pdf", "filename": "inlined.pdf", "body": {"data": "x"}},
            {
                "mimeType": "application/zip",
                "filename": "odd.zip",
                "body": {"attachmentId": "att-5", "size": "big"},
                "headers": [
                    {"name": "Content-Type", "value": "application/zip"},
                    {"name": "Content-Disposition", "value": "attachment"},
                    "junk",
                ],
            },
        ]

        [event] = (await _polled(_one(parts=parts), monkeypatch)).events

        assert event.payload["attachments"] == [
            {
                "attachment_id": "att-1",
                "name": "invoice.pdf",
                "content_type": "application/pdf",
                "size": 1200,
            },
            {
                "attachment_id": "att-6",
                "name": "tagged.pdf",
                "content_type": "application/pdf",
                "size": 1200,
            },
            {
                "attachment_id": "att-5",
                "name": "odd.zip",
                "content_type": "application/zip",
                "size": None,
            },
        ]

    async def test_a_message_without_files_lists_none(self, monkeypatch):
        [event] = (await _polled(_one(), monkeypatch)).events

        assert event.payload["attachments"] == []

    async def test_attachments_nested_in_a_multipart_are_found(self, monkeypatch):
        parts = [{"mimeType": "multipart/mixed", "parts": [_file("a.pdf", "att-1"), "junk"]}]

        [event] = (await _polled(_one(parts=parts), monkeypatch)).events

        assert [one["attachment_id"] for one in event.payload["attachments"]] == ["att-1"]

    async def test_at_most_twenty_attachments_are_listed(self, monkeypatch):
        parts = [_file(f"f{index}.pdf", f"att-{index}") for index in range(25)]

        [event] = (await _polled(_one(parts=parts), monkeypatch)).events

        assert [one["attachment_id"] for one in event.payload["attachments"]] == [
            f"att-{index}" for index in range(20)
        ]

    async def test_a_part_tree_deeper_than_the_bound_lists_nothing_past_it(self, monkeypatch):
        deep = _file("deep.pdf", "att-1")
        for _ in range(10):
            deep = {"mimeType": "multipart/mixed", "parts": [deep]}

        [event] = (await _polled(_one(parts=[deep]), monkeypatch)).events

        assert event.payload["attachments"] == []


def _attachment_gmail(
    monkeypatch, *, data: bytes = b"", size: int | None = None, status: int = 200
) -> tuple[_Gmail, GooglePortalAdapter]:
    gmail = _Gmail()

    def answer(request: httpx.Request) -> httpx.Response:
        gmail.raw.append(request.url.raw_path.decode())
        if status != 200:
            return httpx.Response(status, json={"error": {"message": "secret-echo Bearer t"}})
        encoded = base64.urlsafe_b64encode(data).decode().rstrip("=")
        return httpx.Response(
            200, json={"size": len(data) if size is None else size, "data": encoded}
        )

    gmail.handler = answer
    return gmail, _adapter(gmail, monkeypatch)


async def _read(adapter: GooglePortalAdapter, max_bytes: int = 100) -> bytes:
    return await adapter.attachment(
        access_token="t",
        message_id="m/1",
        attachment_id="a+b/c",
        mailbox=None,
        max_bytes=max_bytes,
    )


class TestReadingAnAttachment:
    async def test_an_attachment_is_read_by_its_id(self, monkeypatch):
        gmail, adapter = _attachment_gmail(monkeypatch, data=b"\x00PDF bytes\xff")

        assert await _read(adapter) == b"\x00PDF bytes\xff"
        # Both ids are quoted whole, a slash included.
        assert gmail.raw == ["/gmail/v1/users/me/messages/m%2F1/attachments/a%2Bb%2Fc"]

    async def test_an_attachment_exactly_at_the_limit_is_read(self, monkeypatch):
        _, adapter = _attachment_gmail(monkeypatch, data=b"x" * 100)

        assert await _read(adapter, 100) == b"x" * 100

    async def test_an_attachment_declared_over_the_limit_is_not_decoded(self, monkeypatch):
        _, adapter = _attachment_gmail(monkeypatch, data=b"tiny", size=10_000)

        def forbidden(*_args: Any, **_kwargs: Any) -> bytes:
            raise AssertionError("decoded an attachment declared over the limit")

        monkeypatch.setattr(base64, "urlsafe_b64decode", forbidden)

        with pytest.raises(AttachmentTooLarge):
            await _read(adapter)

    async def test_an_attachment_decoding_over_the_limit_is_refused(self, monkeypatch):
        # Declares nothing over the limit, but the bytes are.
        _, adapter = _attachment_gmail(monkeypatch, data=b"x" * 101, size=5)

        with pytest.raises(AttachmentTooLarge):
            await _read(adapter)

    async def test_an_answer_far_past_the_limit_is_not_read_to_the_end(self, monkeypatch):
        consumed = 0

        class _Endless(httpx.AsyncByteStream):
            async def __aiter__(self):
                nonlocal consumed
                for _ in range(10_000):
                    consumed += 1
                    yield b"x" * 1024

        gmail = _Gmail()
        gmail.handler = lambda request: httpx.Response(200, stream=_Endless())
        adapter = _adapter(gmail, monkeypatch)

        with pytest.raises(AttachmentTooLarge):
            await _read(adapter)

        assert consumed < 10

    async def test_a_redirect_is_not_an_attachment(self, monkeypatch):
        gmail = _Gmail()
        gmail.handler = lambda request: httpx.Response(302, headers={"Location": "https://x.test/"})

        with pytest.raises(PortalUnreachable) as caught:
            await _read(_adapter(gmail, monkeypatch))

        assert caught.value.details == {"portal_key": "google", "status": 302}

    async def test_a_gone_attachment_is_unreachable_with_its_status(self, monkeypatch):
        _, adapter = _attachment_gmail(monkeypatch, status=404)

        with pytest.raises(PortalUnreachable) as caught:
            await _read(adapter)

        assert caught.value.details["status"] == 404
        assert "secret-echo" not in str(caught.value.message) + str(caught.value.details)

    async def test_a_broken_connection_is_unreachable_without_its_text(self, monkeypatch):
        gmail = _Gmail()

        def refuse(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Bearer t leaked")

        gmail.handler = refuse

        with pytest.raises(PortalUnreachable) as caught:
            await _read(_adapter(gmail, monkeypatch))

        assert caught.value.details == {"portal_key": "google", "error": "ConnectError"}

    async def test_an_answer_that_is_not_json_is_unreachable(self, monkeypatch):
        gmail = _Gmail()
        gmail.handler = lambda request: httpx.Response(200, content=b"<html>proxy</html>")

        with pytest.raises(PortalUnreachable):
            await _read(_adapter(gmail, monkeypatch))

    async def test_an_answer_with_no_data_is_an_empty_attachment(self, monkeypatch):
        gmail = _Gmail()
        gmail.handler = lambda request: httpx.Response(200, json=["not", "an", "object"])

        assert await _read(_adapter(gmail, monkeypatch)) == b""

    async def test_an_attachment_with_a_broken_encoding_is_unreachable(self, monkeypatch):
        gmail = _Gmail()
        gmail.handler = lambda request: httpx.Response(200, json={"data": "a"})

        with pytest.raises(PortalUnreachable):
            await _read(_adapter(gmail, monkeypatch))
