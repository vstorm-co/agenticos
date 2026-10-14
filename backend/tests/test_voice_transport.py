from uuid import uuid4

import pytest

from app.services.voice.exceptions import VoiceRefused
from app.services.voice.registry import LiveCalls
from app.services.voice.transport import MAX_SDP_BYTES, refuse_data_channel

_AUDIO_ONLY = "v=0\r\no=- 1 2 IN IP4 127.0.0.1\r\ns=-\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n"


def test_an_audio_only_offer_is_accepted():
    refuse_data_channel(_AUDIO_ONLY)


def test_an_offer_with_a_data_channel_is_refused():
    with pytest.raises(VoiceRefused) as refused:
        refuse_data_channel(_AUDIO_ONLY + "m=application 9 UDP/DTLS/SCTP webrtc-datachannel\r\n")
    assert refused.value.reason == "data_channel"


def test_an_oversized_or_audio_less_offer_is_refused():
    with pytest.raises(VoiceRefused):
        refuse_data_channel("v=0\r\n" + "a" * MAX_SDP_BYTES)
    with pytest.raises(VoiceRefused):
        refuse_data_channel("v=0\r\ns=-\r\n")


@pytest.mark.anyio
async def test_a_reconnect_can_end_the_connection_this_worker_still_holds():
    ended: list[str] = []

    class Call:
        def request_end(self, reason):
            ended.append(reason)

        async def closed(self):
            return None

    calls, call, call_id = LiveCalls(), Call(), uuid4()
    calls.add(call)
    calls.bind(call_id, call)
    assert calls.request_end_for(call_id, "disconnected") is True
    assert calls.request_end_for(uuid4(), "disconnected") is False
    calls.discard(call)
    assert calls.request_end_for(call_id, "disconnected") is False
    assert ended == ["disconnected"]


@pytest.mark.anyio
async def test_shutdown_ends_every_live_call_and_waits_for_it():
    ended: list[str] = []

    class Call:
        def request_end(self, reason):
            ended.append(reason)

        async def closed(self):
            return None

    calls = LiveCalls()
    calls.add(Call())
    assert await calls.end_all() == 1
    assert ended == ["shutdown"]


@pytest.mark.anyio
async def test_a_frame_is_one_json_object_with_its_type():
    from unittest.mock import AsyncMock, MagicMock

    from app.services.voice.transport import send_frame

    websocket = MagicMock(send_text=AsyncMock())

    assert await send_frame(websocket, "state", {"state": "listening", "call_id": uuid4()})
    sent = websocket.send_text.await_args.args[0]
    assert sent.startswith('{"type": "state", "state": "listening"')


@pytest.mark.anyio
async def test_sending_to_a_socket_that_is_gone_is_not_an_error():
    from unittest.mock import AsyncMock, MagicMock

    from fastapi import WebSocketDisconnect

    from app.services.voice.transport import send_frame

    for gone in (WebSocketDisconnect(), RuntimeError("closed")):
        websocket = MagicMock(send_text=AsyncMock(side_effect=gone))
        assert await send_frame(websocket, "state", {}) is False
