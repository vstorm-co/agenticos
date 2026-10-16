"""The socket's edges: what an offer may contain, and sending a frame (#54)."""

from __future__ import annotations

from fastapi import WebSocket, WebSocketDisconnect

from app.schemas.voice import ServerFrame
from app.services.voice.exceptions import VoiceRefused

MAX_SDP_BYTES = 20_000


def refuse_data_channel(sdp: str) -> None:
    """Refuse an offer that is not one audio stream with no data channel.

    The browser does not need `oai-events` (spike, live result 1), and a data
    channel would let it inject provider events into a session our server
    governs. So an `m=application` section is refused, not ignored.
    """
    if len(sdp.encode()) > MAX_SDP_BYTES:
        raise VoiceRefused("bad_offer", "The call could not be set up.")
    lines = [line.strip().lower() for line in sdp.splitlines()]
    if any(line.startswith("m=application") for line in lines):
        raise VoiceRefused("data_channel", "The call could not be set up.")
    if not any(line.startswith("m=audio") for line in lines):
        raise VoiceRefused("bad_offer", "The call could not be set up.")


async def send_frame(websocket: WebSocket, frame: ServerFrame) -> bool:
    """Send one JSON frame. `False` when the socket is already gone - never an exception.

    Only the fields the frame was built with: an optional one left out is absent
    on the wire, as the call view reads it, rather than `null`.
    """
    try:
        await websocket.send_text(frame.model_dump_json(exclude_unset=True))
    except (WebSocketDisconnect, RuntimeError):
        return False
    return True


async def send_audio_frame(websocket: WebSocket, data: bytes) -> bool:
    """Send one binary frame of the agent's audio (the relay). `False` when the socket is gone."""
    try:
        await websocket.send_bytes(data)
    except (WebSocketDisconnect, RuntimeError):
        return False
    return True
