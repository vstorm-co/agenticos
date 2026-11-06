"""The Twilio stream as the voice runtime's typed frame transport."""

import base64
import binascii
import json
import time
from collections.abc import Awaitable, Callable, Mapping
from secrets import compare_digest
from typing import Literal

import anyio
from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, ValidationError

from app.schemas.voice import EndedFrame, ReadyFrame
from app.services.telephony.codec import PhoneCodec


class _Format(BaseModel):
    encoding: Literal["audio/x-mulaw"]
    sampleRate: Literal[8000]
    channels: Literal[1]


class _Start(BaseModel):
    accountSid: str = Field(pattern=r"^AC[0-9a-fA-F]{32}$")
    callSid: str = Field(pattern=r"^CA[0-9a-fA-F]{32}$")
    streamSid: str = Field(pattern=r"^MZ[0-9a-fA-F]{32}$")
    mediaFormat: _Format
    customParameters: dict[str, str] = Field(max_length=10)
    tracks: list[str] = Field(max_length=2)


class _StartEvent(BaseModel):
    event: Literal["start"]
    start: _Start
    streamSid: str | None = None


class PhoneStream:
    def __init__(
        self,
        websocket: WebSocket,
        *,
        account_sid: str,
        call_sid: str | None,
        nonce: str,
        ready: Callable[[ReadyFrame], Awaitable[None]],
    ) -> None:
        self.ws = websocket
        self.account = account_sid
        self.call = call_sid
        self.nonce = nonce
        self.ready = ready
        self.sid: str | None = None
        self._codec = PhoneCodec(input_rate=24000, output_rate=24000)
        self.ended_reason: str | None = None
        self._first = True
        self._forwarded = 0
        self._marks: dict[str, int] = {}
        self._mark_sequence = 0
        self._send_lock = anyio.Lock()
        self._window = time.monotonic()
        self._frames = 0

    async def start(self) -> None:
        with anyio.fail_after(10):
            for _ in range(3):
                text = await self.ws.receive_text()
                if len(text) > 16384:
                    raise WebSocketDisconnect(1009)
                try:
                    message = json.loads(text)
                    if isinstance(message, dict) and message.get("event") == "connected":
                        continue
                    frame = _StartEvent.model_validate(message)
                except (ValidationError, ValueError) as exc:
                    raise WebSocketDisconnect(1008) from exc
                start = frame.start
                supplied_nonce = start.customParameters.get("nonce", "")
                if (
                    start.accountSid != self.account
                    or (self.call is not None and start.callSid != self.call)
                    or start.tracks != ["inbound"]
                    or not supplied_nonce.isascii()
                    or not compare_digest(supplied_nonce, self.nonce)
                    or (frame.streamSid is not None and frame.streamSid != start.streamSid)
                ):
                    raise WebSocketDisconnect(1008)
                self.sid = start.streamSid
                self.call = start.callSid
                return
        raise WebSocketDisconnect(1008)

    async def receive(self) -> Mapping[str, object]:
        if self._first:
            self._first = False
            return {"type": "websocket.receive", "text": '{"type":"start"}'}
        text = await self.ws.receive_text()
        if len(text) > 16384:
            raise WebSocketDisconnect(1009)
        now = time.monotonic()
        if now - self._window >= 1:
            self._window, self._frames = now, 0
        self._frames += 1
        if self._frames > 500:
            raise WebSocketDisconnect(1008)
        try:
            message = json.loads(text)
        except ValueError as exc:
            raise WebSocketDisconnect(1008) from exc
        if not isinstance(message, dict) or message.get("streamSid") != self.sid:
            raise WebSocketDisconnect(1008)
        event = message.get("event")
        if event == "stop":
            return {"type": "websocket.disconnect", "code": 1000}
        if event == "media":
            media = message.get("media")
            payload = media.get("payload") if isinstance(media, dict) else None
            if (
                not isinstance(payload, str)
                or not 1 <= len(payload) <= 4096
                or media.get("track") != "inbound"
            ):
                raise WebSocketDisconnect(1008)
            try:
                audio = base64.b64decode(payload, validate=True)
            except binascii.Error as exc:
                raise WebSocketDisconnect(1008) from exc
            return {"type": "websocket.receive", "bytes": self._codec.incoming(audio)}
        if event == "mark":
            mark = message.get("mark")
            name = mark.get("name") if isinstance(mark, dict) else None
            if isinstance(name, str):
                played = self._marks.pop(name, None)
                if played is not None:
                    return {
                        "type": "websocket.receive",
                        "text": json.dumps({"type": "played", "bytes": played}),
                    }
        return {"type": "websocket.receive", "text": "{}"}

    async def send_text(self, data: str) -> None:
        message = json.loads(data)
        if message.get("type") == "ready":
            frame = ReadyFrame.model_validate(message)
            self._codec = PhoneCodec(
                input_rate=frame.input_sample_rate, output_rate=frame.output_sample_rate
            )
            await self.ready(frame)
        elif message.get("type") == "ended":
            self.ended_reason = EndedFrame.model_validate(message).reason
        elif message.get("type") == "clear_playback":
            self._marks.clear()
            self._codec.clear_output()
            async with self._send_lock:
                await self.ws.send_json({"event": "clear", "streamSid": self.sid})

    async def send_bytes(self, data: bytes) -> None:
        chunk = self._codec.outgoing(data)
        self._forwarded += len(data)
        if not chunk:
            return
        self._mark_sequence += 1
        name = str(self._mark_sequence)
        if len(self._marks) >= 500:
            raise WebSocketDisconnect(1008)
        self._marks[name] = self._forwarded
        async with self._send_lock:
            await self.ws.send_json(
                {
                    "event": "media",
                    "streamSid": self.sid,
                    "media": {"payload": base64.b64encode(chunk).decode("ascii")},
                }
            )
            await self.ws.send_json(
                {"event": "mark", "streamSid": self.sid, "mark": {"name": name}}
            )
