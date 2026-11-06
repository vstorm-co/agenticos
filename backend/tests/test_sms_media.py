"""MMS enters the ordinary attachment path without lending credentials to arbitrary URLs."""

import asyncio
import base64
from collections.abc import AsyncIterator, Callable
from dataclasses import replace
from unittest.mock import patch

import httpx
import pytest

from app.services.channels.base import IncomingAttachment
from app.services.channels.sms import MAX_MEDIA, SmsAdapter

pytestmark = [pytest.mark.anyio, pytest.mark.security]

SID = "AC" + "1" * 32
MESSAGE = "MM" + "2" * 32
MEDIA = "ME" + "3" * 32
TOKEN = f"{SID}:test-secret:+15550001111"
URL = f"https://api.twilio.com/2010-04-01/Accounts/{SID}/Messages/{MESSAGE}/Media/{MEDIA}"


def _payload(**overrides: str) -> dict[str, str]:
    return {
        "From": "+15559998888",
        "Body": "",
        "MessageSid": MESSAGE,
        "NumMedia": "1",
        "MediaUrl0": URL,
        "MediaContentType0": "image/png",
    } | overrides


def _attachment(url: str = URL) -> IncomingAttachment:
    return IncomingAttachment(filename="media-1.png", mime_type="image/png", size=0, handle=url)


async def _adapter(handler: Callable[[httpx.Request], httpx.Response]) -> SmsAdapter:
    adapter = SmsAdapter()
    await adapter._client.aclose()
    adapter._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=True
    )
    return adapter


async def test_a_media_only_message_is_retained_with_a_deferred_handle() -> None:
    adapter = SmsAdapter()
    try:
        incoming = adapter.parse_incoming(_payload(), "bot")
        assert incoming is not None
        assert incoming.text == "" and incoming.platform_user_id == "+15559998888"
        assert incoming.chat_type == "private" and incoming.message_id == MESSAGE
        assert incoming.attachments == [_attachment()]
        assert adapter.parse_incoming(_payload(From=""), "bot") is None
    finally:
        await adapter.aclose()


@pytest.mark.parametrize("count", ["-1", "garbage", "", "\uff19", "9" * 5000])
async def test_malformed_media_counts_do_not_create_unbounded_work(count: str) -> None:
    adapter = SmsAdapter()
    try:
        assert adapter.parse_incoming(_payload(NumMedia=count), "bot") is None
    finally:
        await adapter.aclose()


async def test_a_message_has_at_most_ten_handles_and_unknown_types_remain_untyped() -> None:
    adapter = SmsAdapter()
    try:
        incoming = adapter.parse_incoming(_payload(NumMedia="99", MediaContentType0=""), "bot")
        assert incoming is not None and len(incoming.attachments) == MAX_MEDIA
        assert incoming.attachments[0].mime_type == "application/octet-stream"
        assert incoming.attachments[0].filename == "media-1.bin"
        assert incoming.attachments[1].handle == ""
    finally:
        await adapter.aclose()


async def test_a_handle_cannot_reference_a_different_message() -> None:
    adapter = SmsAdapter()
    try:
        incoming = adapter.parse_incoming(_payload(MessageSid="SM" + "4" * 32), "bot")
        assert incoming is not None and incoming.attachments[0].handle == ""
    finally:
        await adapter.aclose()


async def test_download_authenticates_only_to_the_bots_own_media_resource() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=b"file")

    adapter = await _adapter(respond)
    try:
        assert await adapter.download_attachment(TOKEN, _attachment()) == b"file"
        assert str(requests[0].url) == URL
        authorization = base64.b64encode(f"{SID}:test-secret".encode()).decode()
        assert requests[0].headers["authorization"] == f"Basic {authorization}"
    finally:
        await adapter.aclose()


@pytest.mark.parametrize(
    "url",
    [
        URL.replace(SID, "AC" + "9" * 32),
        URL.replace("api.twilio.com", "localhost"),
        URL.replace("api.twilio.com", "api.twilio.com.attacker.test"),
        URL.replace("https:", "http:"),
        URL.replace("api.twilio.com", "user:secret@api.twilio.com"),
        URL.replace("api.twilio.com", "api.twilio.com:443"),
        URL + "?next=http://localhost",
        URL + "#fragment",
        URL + "/../",
        "",
    ],
)
async def test_invalid_handles_never_make_an_authenticated_request(url: str) -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200)

    adapter = await _adapter(respond)
    try:
        with pytest.raises(ValueError, match="not media for this Twilio account"):
            await adapter.download_attachment(TOKEN, _attachment(url))
        assert requests == []
    finally:
        await adapter.aclose()


@pytest.mark.parametrize("status", [302, 401, 404, 500])
async def test_redirects_and_provider_failures_are_explicit_without_following(status: int) -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status, headers={"location": "https://attacker.test/file"})

    adapter = await _adapter(respond)
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await adapter.download_attachment(TOKEN, _attachment())
        assert len(requests) == 1
    finally:
        await adapter.aclose()


class _MediaStream(httpx.AsyncByteStream):
    def __init__(self) -> None:
        self.yielded = 0
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for _ in range(4):
            self.yielded += 1
            yield b"x" * (512 * 1024)

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.parametrize("claimed_size", [None, "2097152"])
async def test_size_limits_apply_before_download_and_during_unknown_size_streams(
    claimed_size: str | None,
) -> None:
    stream = _MediaStream()
    headers = {} if claimed_size is None else {"content-length": claimed_size}
    adapter = await _adapter(lambda _request: httpx.Response(200, headers=headers, stream=stream))
    try:
        with (
            patch("app.services.channels.sms.settings.CHAT_MAX_UPLOAD_SIZE_MB", 1),
            pytest.raises(ValueError, match="upload size limit"),
        ):
            await adapter.download_attachment(TOKEN, _attachment())
        assert stream.yielded == (3 if claimed_size is None else 0)
        assert stream.closed
    finally:
        await adapter.aclose()


async def test_cancellation_closes_the_media_stream() -> None:
    reading = asyncio.Event()

    class WaitingMedia(_MediaStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            reading.set()
            await asyncio.Future[None]()
            yield b"unreachable"

    stream = WaitingMedia()
    adapter = await _adapter(lambda _request: httpx.Response(200, stream=stream))
    task = asyncio.create_task(adapter.download_attachment(TOKEN, _attachment()))
    try:
        await reading.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert stream.closed
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await adapter.aclose()


async def test_outbound_mms_posts_all_files_and_a_chart_even_without_text() -> None:
    from unittest.mock import AsyncMock, MagicMock
    from urllib.parse import parse_qs

    from app.services.channels.base import OutgoingAttachment, OutgoingMessage

    sent = []

    def accept(request: httpx.Request) -> httpx.Response:
        sent.append(parse_qs(request.content.decode(), keep_blank_values=True))
        return httpx.Response(201, json={"sid": MESSAGE})

    media = MagicMock(
        stage=AsyncMock(side_effect=["https://media.example/chart", "https://media.example/data"])
    )
    context = MagicMock(
        __aenter__=AsyncMock(return_value=media), __aexit__=AsyncMock(return_value=False)
    )
    adapter = await _adapter(accept)
    try:
        with patch("app.services.channels.sms.open_media_store", return_value=context):
            await adapter.send_message(
                TOKEN,
                OutgoingMessage(
                    platform_chat_id="+15559998888",
                    text="",
                    image_png=b"png",
                    attachments=[
                        OutgoingAttachment(
                            filename="data.csv", content=b"x,y\n1,2", mime_type="text/csv"
                        )
                    ],
                ),
            )
        assert sent == [
            {
                "To": ["+15559998888"],
                "From": ["+15550001111"],
                "Body": [""],
                "MediaUrl": ["https://media.example/chart", "https://media.example/data"],
                "ValidityPeriod": ["600"],
            }
        ]
        assert media.stage.await_args_list[0].args[0].content == b"png"
        assert media.stage.await_args_list[1].args[0].filename == "data.csv"
        context.__aexit__.assert_awaited_once()
    finally:
        await adapter.aclose()


@pytest.mark.parametrize("problem", ["type", "count", "combined", "other", "empty"])
async def test_outbound_mms_refuses_unsupported_or_excessive_files_before_staging_or_sending(
    problem: str,
) -> None:
    from unittest.mock import MagicMock

    from app.services.channels.base import OutgoingAttachment, OutgoingMessage

    files = [OutgoingAttachment(filename="file.png", content=b"x", mime_type="image/png")]
    if problem == "type":
        files[0] = replace(files[0], mime_type="application/zip")
    elif problem == "count":
        files *= 11
    elif problem == "combined":
        files[0] = replace(files[0], content=b"x" * 5_000_000)
    elif problem == "other":
        files = [
            OutgoingAttachment(
                filename="file.pdf", content=b"x" * 500_001, mime_type="application/pdf"
            )
        ]
    elif problem == "empty":
        files[0] = replace(files[0], content=b"")

    def never(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Invalid MMS must never reach Twilio")

    adapter = await _adapter(never)
    try:
        with (
            patch("app.services.channels.sms.open_media_store", new=MagicMock()) as store,
            pytest.raises(ValueError),
        ):
            await adapter.send_message(
                TOKEN, OutgoingMessage(platform_chat_id="+1", text="text", attachments=files)
            )
        store.assert_not_called()
    finally:
        await adapter.aclose()
