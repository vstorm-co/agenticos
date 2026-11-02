"""The WhatsApp Graph client: what it posts, and how it fails without leaking (#2076).

Graph is an `httpx.MockTransport` that records every request, so what is asserted
is the call Meta would receive and what a refusal turns into on our side.
"""

import json
import logging
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.services.channels.exceptions import ChannelNotConfigured
from app.services.channels.whatsapp_graph import (
    GRAPH_BASE,
    GRAPH_VERSION,
    MAX_ATTEMPTS,
    TOKEN_REFUSED,
    WhatsAppCredentials,
    WhatsAppGraph,
    WhatsAppGraphError,
    WhatsAppTokenRefused,
)

pytestmark = pytest.mark.anyio

TOKEN = "EAABsecrettoken"
CREDS = WhatsAppCredentials(bot_id="bot-1", access_token=TOKEN, phone_number_id="PNID1")
SLEEP = "app.services.channels.whatsapp_graph.asyncio.sleep"


def _graph(*responses: httpx.Response | Exception) -> tuple[WhatsAppGraph, list[httpx.Request]]:
    seen: list[httpx.Request] = []
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    return WhatsAppGraph(httpx.AsyncClient(transport=httpx.MockTransport(handler))), seen


def _accepted(wamid: str = "wamid.OUT") -> httpx.Response:
    return httpx.Response(200, json={"messaging_product": "whatsapp", "messages": [{"id": wamid}]})


def _refused(code: int, status: int = 400) -> httpx.Response:
    body = {"error": {"message": "Invalid token EAAB... for +4915112345678", "code": code}}
    return httpx.Response(status, json=body)


async def test_send_text_posts_to_the_pinned_version_with_a_bearer_header():
    graph, seen = _graph(_accepted())
    wamid = await graph.send_text(CREDS, recipient="US.111", body="hi")
    assert wamid == "wamid.OUT"
    [request] = seen
    assert request.method == "POST"
    assert str(request.url) == f"{GRAPH_BASE}/{GRAPH_VERSION}/PNID1/messages"
    assert GRAPH_VERSION == "v26.0"
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    assert request.url.query == b""
    assert json.loads(request.content) == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "recipient": "US.111",
        "type": "text",
        "text": {"body": "hi", "preview_url": False},
    }
    await graph.aclose()


async def test_reply_to_adds_the_context():
    graph, seen = _graph(_accepted())
    await graph.send_text(CREDS, recipient="US.111", body="hi", reply_to="wamid.IN")
    assert json.loads(seen[0].content)["context"] == {"message_id": "wamid.IN"}


@pytest.mark.parametrize("typing", [True, False])
async def test_mark_read_with_typing_sends_the_indicator(typing: bool):
    graph, seen = _graph(httpx.Response(200, json={"success": True}))
    assert await graph.mark_read(CREDS, message_id="wamid.IN", typing=typing) is None
    expected: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": "wamid.IN",
    }
    if typing:
        expected["typing_indicator"] = {"type": "text"}
    assert json.loads(seen[0].content) == expected


async def test_code_190_raises_token_refused(caplog: pytest.LogCaptureFixture):
    graph, seen = _graph(_refused(190, status=401))
    with caplog.at_level(logging.WARNING), pytest.raises(WhatsAppTokenRefused) as raised:
        await graph.send_text(CREDS, recipient="US.111", body="hi")
    assert isinstance(raised.value, ChannelNotConfigured)
    assert raised.value.message == TOKEN_REFUSED
    assert raised.value.details == {"code": 190}
    assert len(seen) == 1
    [record] = [r for r in caplog.records if r.message == "whatsapp_graph_refused"]
    assert (record.bot_id, record.code) == ("bot-1", 190)  # type: ignore[attr-defined]


async def test_a_retryable_code_is_retried_then_succeeds():
    graph, seen = _graph(_refused(131056, 429), _refused(4, 400), _accepted("wamid.LATE"))
    with patch(SLEEP, new=AsyncMock()) as sleep:
        assert await graph.send_text(CREDS, recipient="US.111", body="hi") == "wamid.LATE"
    assert len(seen) == MAX_ATTEMPTS == 3
    assert [call.args[0] for call in sleep.await_args_list] == [1, 2]


async def test_a_retryable_code_gives_up_after_the_last_attempt():
    graph, seen = _graph(*[_refused(131056, 429)] * 3)
    with patch(SLEEP, new=AsyncMock()), pytest.raises(WhatsAppGraphError) as raised:
        await graph.send_text(CREDS, recipient="US.111", body="hi")
    assert raised.value.details == {"code": 131056}
    assert len(seen) == 3


async def test_any_other_code_is_not_retried():
    graph, seen = _graph(_refused(131047))
    with patch(SLEEP, new=AsyncMock()) as sleep, pytest.raises(WhatsAppGraphError) as raised:
        await graph.send_text(CREDS, recipient="US.111", body="hi")
    assert raised.value.details == {"code": 131047}
    assert len(seen) == 1
    sleep.assert_not_awaited()


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(502, text="<html>bad gateway</html>"),
        httpx.Response(400, json={"error": "not a mapping"}),
        httpx.Response(400, json={"error": {"code": "190"}}),
        httpx.Response(200, json={"messages": []}),
        httpx.Response(200, json={"messages": [{"id": 5}]}),
        httpx.Response(200, text="not json"),
    ],
)
async def test_a_reply_without_a_usable_code_or_wamid_is_an_error_with_no_code(
    response: httpx.Response,
):
    graph, _ = _graph(response)
    with pytest.raises(WhatsAppGraphError) as raised:
        await graph.send_text(CREDS, recipient="US.111", body="hi")
    assert raised.value.details == {"code": None}


async def test_a_read_timeout_is_never_retried():
    graph, seen = _graph(httpx.ReadTimeout("slow"), _accepted())
    with patch(SLEEP, new=AsyncMock()), pytest.raises(WhatsAppGraphError) as raised:
        await graph.send_text(CREDS, recipient="US.111", body="hi")
    assert raised.value.details == {"code": None}
    assert len(seen) == 1


async def test_a_connect_error_is_retried():
    graph, seen = _graph(httpx.ConnectError("down"), _accepted())
    with patch(SLEEP, new=AsyncMock()) as sleep:
        assert await graph.send_text(CREDS, recipient="US.111", body="hi") == "wamid.OUT"
    assert len(seen) == 2
    sleep.assert_awaited_once_with(1)


async def test_a_connect_error_on_every_attempt_gives_up():
    graph, seen = _graph(*[httpx.ConnectTimeout("down")] * 3)
    with patch(SLEEP, new=AsyncMock()), pytest.raises(WhatsAppGraphError):
        await graph.send_text(CREDS, recipient="US.111", body="hi")
    assert len(seen) == 3


@pytest.mark.security
@pytest.mark.parametrize(
    "response",
    [
        _refused(190, 401),
        _refused(100),
        httpx.ReadTimeout("timed out talking to +4915112345678 with EAABsecrettoken"),
    ],
)
async def test_errors_carry_no_token_phone_or_graph_text(
    response: httpx.Response | Exception, caplog: pytest.LogCaptureFixture
):
    graph, _ = _graph(response)
    with (
        caplog.at_level(logging.DEBUG),
        pytest.raises((WhatsAppGraphError, WhatsAppTokenRefused)) as raised,
    ):
        await graph.send_text(CREDS, recipient="US.111", body="hi")
    exc = raised.value
    assert exc.__cause__ is None and exc.__suppress_context__
    surfaces = [str(exc), exc.message, json.dumps(exc.details), caplog.text]
    surfaces += [str(vars(record)) for record in caplog.records]
    for surface in surfaces:
        for secret in (TOKEN, "EAAB", "4915112345678", "Invalid token", "timed out"):
            assert secret not in surface


@pytest.mark.security
def test_the_access_token_stays_out_of_a_credentials_repr():
    assert CREDS.access_token == TOKEN
    assert TOKEN not in repr(CREDS)
