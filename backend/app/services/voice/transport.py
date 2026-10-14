"""The socket's edges: what an offer may contain, and sending a frame (#54)."""

from __future__ import annotations

import json
from collections.abc import Mapping

from fastapi import WebSocket, WebSocketDisconnect

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


async def send_frame(websocket: WebSocket, kind: str, payload: Mapping[str, object]) -> bool:
    """Send one JSON frame. `False` when the socket is already gone - never an exception."""
    try:
        await websocket.send_text(json.dumps({"type": kind, **payload}, default=str))
    except (WebSocketDisconnect, RuntimeError):
        return False
    return True
