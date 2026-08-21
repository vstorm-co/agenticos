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

from __future__ import annotations

import base64
from typing import Any

import httpx
import pytest

from app.services.portals import PortalUnreachable
from app.services.portals.google import GooglePortalAdapter

pytestmark = pytest.mark.anyio


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def _message(identifier: str, *, subject: str, sender: str, body: str, labels: list[str]):
    return {
        "id": identifier,
        "labelIds": labels,
        "snippet": body[:40],
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [
                {"name": "Subject", "value": subject},
                {"name": "From", "value": sender},
                {"name": "To", "value": "me@acme.test"},
            ],
            "parts": [
                {"mimeType": "text/html", "body": {"data": _b64(f"<p>{body}</p>")}},
                {"mimeType": "text/plain", "body": {"data": _b64(body)}},
            ],
        },
    }


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
        assert read.cursor == {"history_id": "510"}

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
        # The newest, not the oldest: a bounded read should lose the backlog rather
        # than the message that just arrived.
        assert read.events[-1].payload["message_id"] == many[-1]
        assert read.cursor == {"history_id": "600"}

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
        from app.services.portals.google import _body_text

        deep: dict[str, Any] = {"mimeType": "text/plain", "body": {"data": _b64("deep")}}
        for _ in range(12):
            deep = {"mimeType": "multipart/mixed", "parts": [deep]}

        assert _body_text(deep) == ""

    async def test_an_undecodable_body_is_empty_rather_than_an_error(self, monkeypatch):
        from app.services.portals.google import _body_text

        assert _body_text({"mimeType": "text/plain", "body": {"data": "!!!not base64!!!"}}) == ""

    async def test_a_header_the_message_omits_reads_as_empty(self, monkeypatch):
        from app.services.portals.google import _header

        assert _header({"payload": {"headers": []}}, "Subject") == ""
