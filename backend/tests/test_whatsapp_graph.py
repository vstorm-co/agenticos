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
    MEDIA_HOSTS,
    TOKEN_REFUSED,
    WhatsAppCredentials,
    WhatsAppGraph,
    WhatsAppGraphError,
    WhatsAppMediaTooLarge,
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


MEDIA_URL = "https://lookaside.fbsbx.com/whatsapp_business/attachments/?mid=1&ext=2&hash=3"


async def test_media_info_reads_url_type_and_size():
    body = {"url": MEDIA_URL, "mime_type": "image/jpeg", "file_size": 1234, "id": "123"}
    graph, seen = _graph(httpx.Response(200, json=body))
    info = await graph.media_info(CREDS, media_id="123")
    assert (info.url, info.mime_type, info.file_size) == (MEDIA_URL, "image/jpeg", 1234)
    assert seen[0].method == "GET"
    assert str(seen[0].url) == f"{GRAPH_BASE}/{GRAPH_VERSION}/123"


async def test_media_info_without_a_url_is_refused():
    graph, _ = _graph(httpx.Response(200, json={"mime_type": "image/png"}))
    with pytest.raises(WhatsAppGraphError):
        await graph.media_info(CREDS, media_id="123")


async def test_media_info_tolerates_missing_type_and_size():
    graph, _ = _graph(httpx.Response(200, json={"url": MEDIA_URL, "file_size": "twelve"}))
    info = await graph.media_info(CREDS, media_id="123")
    assert (info.mime_type, info.file_size) == (None, None)


async def test_a_digit_string_file_size_is_read_as_an_int():
    graph, _ = _graph(httpx.Response(200, json={"url": MEDIA_URL, "file_size": "1234"}))
    assert (await graph.media_info(CREDS, media_id="123")).file_size == 1234


async def test_the_media_info_url_is_not_in_the_repr():
    graph, _ = _graph(httpx.Response(200, json={"url": MEDIA_URL}))
    info = await graph.media_info(CREDS, media_id="123")
    assert "lookaside" not in repr(info)


async def test_media_requests_ask_for_an_unencoded_body():
    graph, seen = _graph(
        httpx.Response(200, json={"url": MEDIA_URL}), httpx.Response(200, content=b"x")
    )
    await graph.media_info(CREDS, media_id="123")
    await graph.download_media(CREDS, url=MEDIA_URL, limit=10)
    assert [r.headers["Accept-Encoding"] for r in seen] == ["identity", "identity"]


async def test_media_info_is_not_traced():
    graph, _ = _graph(httpx.Response(200, json={"url": MEDIA_URL}))
    with patch("app.services.channels.whatsapp_graph.logfire.suppress_instrumentation") as quiet:
        await graph.media_info(CREDS, media_id="123")
    quiet.assert_called_once_with()


async def test_a_post_never_retries_a_read_timeout():
    graph, seen = _graph(httpx.ReadTimeout("slow"))
    with patch(SLEEP, new=AsyncMock()), pytest.raises(WhatsAppGraphError):
        await graph.send_text(CREDS, recipient="US.111", body="hi")
    assert len(seen) == 1


async def test_media_info_retries_a_read_timeout_and_a_retryable_code():
    graph, seen = _graph(
        httpx.ReadTimeout("slow"),
        _refused(131056, 400),
        httpx.Response(200, json={"url": MEDIA_URL}),
    )
    with patch(SLEEP, new=AsyncMock()):
        info = await graph.media_info(CREDS, media_id="123")
    assert info.url == MEDIA_URL
    assert len(seen) == 3


@pytest.mark.parametrize("media_id", ["../me", "wamid.X", "", "12/3", "\u00b2"])
async def test_a_media_id_that_is_not_digits_is_refused_without_a_request(media_id: str):
    graph, seen = _graph()
    with pytest.raises(WhatsAppGraphError) as caught:
        await graph.media_info(CREDS, media_id=media_id)
    assert caught.value.details == {"code": None}
    assert seen == []


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/x",
        "http://lookaside.fbsbx.com/x",
        "https://lookaside.fbsbx.com.evil.example/x",
    ],
)
async def test_a_foreign_media_host_is_refused(url: str):
    graph, seen = _graph()
    with pytest.raises(WhatsAppGraphError):
        await graph.download_media(CREDS, url=url, limit=1000)
    assert seen == []
    assert "lookaside.fbsbx.com" in MEDIA_HOSTS


async def test_download_returns_the_bytes():
    graph, seen = _graph(httpx.Response(200, content=b"file-bytes"))
    assert await graph.download_media(CREDS, url=MEDIA_URL, limit=1000) == b"file-bytes"
    assert seen[0].headers["Authorization"] == f"Bearer {TOKEN}"


async def test_a_redirect_is_not_followed():
    graph, seen = _graph(
        httpx.Response(302, headers={"Location": "https://evil.example/x"}),
        httpx.Response(200, content=b"nope"),
    )
    with pytest.raises(WhatsAppGraphError):
        await graph.download_media(CREDS, url=MEDIA_URL, limit=1000)
    assert len(seen) == 1


async def test_a_download_refusal_names_no_url_or_token(caplog: pytest.LogCaptureFixture):
    logging_name = "app.services.channels.whatsapp_graph"
    graph, _ = _graph(httpx.Response(404, json={"error": {"code": 100}}))
    with caplog.at_level(logging.DEBUG), pytest.raises(WhatsAppGraphError) as caught:
        await graph.download_media(CREDS, url=MEDIA_URL, limit=1000)
    assert caught.value.details == {"code": None}
    ours = "\n".join(
        r.getMessage() + repr(r.__dict__) for r in caplog.records if r.name == logging_name
    )
    assert TOKEN not in ours
    assert "lookaside" not in ours
    assert "mid=1" not in ours


async def test_a_download_transport_failure_is_a_graph_error():
    graph, _ = _graph(httpx.ConnectError("boom for " + MEDIA_URL))
    with pytest.raises(WhatsAppGraphError) as caught:
        await graph.download_media(CREDS, url=MEDIA_URL, limit=1000)
    assert caught.value.__cause__ is None
    assert MEDIA_URL not in str(caught.value)


async def test_the_download_stops_past_the_limit():
    class Body(httpx.AsyncByteStream):
        def __init__(self) -> None:
            self.sent = 0

        async def __aiter__(self):
            for _ in range(3):
                self.sent += 1
                yield b"x" * 1_000_000

    body = Body()
    graph, _ = _graph(httpx.Response(200, stream=body))
    with pytest.raises(WhatsAppMediaTooLarge) as caught:
        await graph.download_media(CREDS, url=MEDIA_URL, limit=1_000_000 - 1)
    assert caught.value.details == {"code": None}
    assert isinstance(caught.value, WhatsAppGraphError)
    assert body.sent == 1


async def test_the_token_goes_only_in_the_header():
    graph, seen = _graph(
        httpx.Response(200, json={"url": MEDIA_URL}),
        httpx.Response(200, content=b"x"),
        httpx.Response(200, json={"id": "999"}),
    )
    await graph.media_info(CREDS, media_id="123")
    await graph.download_media(CREDS, url=MEDIA_URL, limit=10)
    await graph.upload_media(CREDS, content=b"x", mime_type="image/png", filename="c.png")
    assert len(seen) == 3
    for request in seen:
        assert TOKEN not in str(request.url)
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        assert TOKEN.encode() not in request.content


async def test_upload_sends_multipart_and_returns_the_id():
    graph, seen = _graph(httpx.Response(200, json={"id": "777"}))
    media_id = await graph.upload_media(
        CREDS, content=b"PNGDATA", mime_type="image/png", filename="chart.png"
    )
    assert media_id == "777"
    request = seen[0]
    assert request.method == "POST"
    assert str(request.url) == f"{GRAPH_BASE}/{GRAPH_VERSION}/PNID1/media"
    assert request.headers["Content-Type"].startswith("multipart/form-data")
    body = request.content
    assert b'name="messaging_product"' in body and b"whatsapp" in body
    assert b'name="type"' in body and b"image/png" in body
    assert b'name="file"; filename="chart.png"' in body
    assert b"PNGDATA" in body


async def test_upload_without_an_id_is_refused():
    graph, _ = _graph(httpx.Response(200, json={}))
    with pytest.raises(WhatsAppGraphError):
        await graph.upload_media(CREDS, content=b"x", mime_type="image/png", filename="c.png")


async def test_an_upload_read_timeout_is_not_retried():
    graph, seen = _graph(httpx.ReadTimeout("slow"))
    with patch(SLEEP, new=AsyncMock()), pytest.raises(WhatsAppGraphError):
        await graph.upload_media(CREDS, content=b"x", mime_type="image/png", filename="c.png")
    assert len(seen) == 1


async def test_an_upload_retries_a_connect_error():
    graph, seen = _graph(httpx.ConnectError("x"), httpx.Response(200, json={"id": "5"}))
    with patch(SLEEP, new=AsyncMock()):
        assert (
            await graph.upload_media(CREDS, content=b"x", mime_type="image/png", filename="c.png")
            == "5"
        )
    assert len(seen) == 2


async def test_send_media_puts_the_caption_and_filename_in_the_document():
    graph, seen = _graph(_accepted("wamid.DOC"))
    wamid = await graph.send_media(
        CREDS,
        recipient="US.111",
        kind="document",
        media_id="55",
        caption="Q3",
        filename="q3.pdf",
        reply_to="wamid.IN",
    )
    assert wamid == "wamid.DOC"
    assert json.loads(seen[0].content) == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "recipient": "US.111",
        "type": "document",
        "document": {"id": "55", "caption": "Q3", "filename": "q3.pdf"},
        "context": {"message_id": "wamid.IN"},
    }


async def test_send_media_image_omits_what_is_not_given():
    graph, seen = _graph(_accepted())
    await graph.send_media(
        CREDS,
        recipient="US.111",
        kind="image",
        media_id="55",
        caption=None,
        filename=None,
        reply_to=None,
    )
    sent = json.loads(seen[0].content)
    assert sent["image"] == {"id": "55"}
    assert "context" not in sent


async def test_send_interactive_posts_the_interactive_object():
    interactive = {"type": "button", "body": {"text": "Run?"}, "action": {"buttons": []}}
    graph, seen = _graph(_accepted("wamid.BTN"))
    wamid = await graph.send_interactive(
        CREDS, recipient="US.111", interactive=interactive, reply_to="wamid.IN"
    )
    assert wamid == "wamid.BTN"
    sent = json.loads(seen[0].content)
    assert sent["type"] == "interactive"
    assert sent["interactive"] == interactive
    assert sent["recipient"] == "US.111"
    assert sent["context"] == {"message_id": "wamid.IN"}


async def test_a_send_without_a_message_id_is_refused():
    graph, _ = _graph(httpx.Response(200, json={"messages": []}))
    with pytest.raises(WhatsAppGraphError):
        await graph.send_interactive(CREDS, recipient="US.111", interactive={})
