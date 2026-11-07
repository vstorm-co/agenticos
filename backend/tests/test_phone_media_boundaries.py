"""Provider media observes receipt, routing and member authority throughout a session."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import WebSocket

from app.core.config import settings
from app.core.exceptions import AuthorizationError
from app.schemas.voice import ReadyFrame
from app.services.telephony import runtime
from tests.test_phone_authority import contact_and_call
from tests.test_telephony import AUTH, SID

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.mark.parametrize(
    "change",
    [
        "ok",
        "missing",
        "account",
        "signature",
        "ended_before_ready",
        "revoked",
        "cleanup",
        "inbound",
        "domain_error",
    ],
)
async def test_media_ready_and_cleanup_keep_the_admitted_call_identity(monkeypatch, change):
    _, row, ctx = contact_and_call()
    row.mode, row.status, row.direction = "conversation", "ringing", "outbound"
    row.endpoint_id, row.endpoint_generation, row.account_sid = uuid4(), uuid4(), AUTH.account
    row.provider_sid, row.stream_claimed_at, row.expires_at = (
        SID,
        None,
        datetime.now(UTC) + timedelta(minutes=1),
    )
    row.agent_id, row.cap_seconds = uuid4(), 60
    if change == "inbound":
        row.direction = "inbound"
    route = MagicMock(generation=row.endpoint_generation)
    db = AsyncMock()

    @asynccontextmanager
    async def sessions():
        yield db

    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "https://phone.example")
    read = AsyncMock(return_value=None if change == "missing" else row)
    monkeypatch.setattr(runtime.repo, "call", read)
    monkeypatch.setattr(runtime.repo, "save", AsyncMock())
    monkeypatch.setattr(
        runtime.PhonePolicyService, "load_endpoint", AsyncMock(return_value=(route, None, AUTH))
    )
    monkeypatch.setattr(runtime, "signature_ok", lambda *args: change != "signature")
    monkeypatch.setattr(runtime, "stream_nonce", lambda *args: "nonce")
    monkeypatch.setattr(
        runtime, "_claim_stream", AsyncMock(return_value=MagicMock(agent_id=row.agent_id))
    )
    monkeypatch.setattr(runtime, "live_contact", AsyncMock(return_value=ctx))
    monkeypatch.setattr(runtime, "still_allowed", AsyncMock(return_value=ctx))
    ended = AsyncMock(
        side_effect=AuthorizationError(message="Cleanup account changed")
        if change == "cleanup"
        else None
    )
    monkeypatch.setattr(runtime, "end_media", ended)
    socket = MagicMock(spec=WebSocket)
    socket.headers, socket.close, socket.accept = {}, AsyncMock(), AsyncMock()
    ready = ReadyFrame(
        type="ready",
        call_id=uuid4(),
        conversation_id=uuid4(),
        transport="relay",
        input_sample_rate=24000,
        output_sample_rate=24000,
        cap_seconds=60,
        resume_token="resume",
    )

    class Stream:
        def __init__(self, websocket, *, account_sid, call_sid, nonce, ready):
            self.ready, self.call, self.ended_reason = ready, call_sid, None

        async def start(self):
            if change == "ended_before_ready":
                row.status = "ending"

    class Session:
        def __init__(self, stream, caller, *, sessions, reauthorize):
            self.stream, self.reauthorize = stream, reauthorize

        async def run(self):
            await self.stream.ready(ready)
            assert (
                row.voice_call_id == ready.call_id and row.conversation_id == ready.conversation_id
            )
            assert row.status == "active"
            if change == "revoked":
                monkeypatch.setattr(
                    runtime,
                    "live_contact",
                    AsyncMock(side_effect=AuthorizationError(message="Revoked")),
                )
            assert (await self.reauthorize(db) is not None) is (change != "revoked")
            if change == "domain_error":
                raise AuthorizationError(message="Session revoked")
            raise TimeoutError

    monkeypatch.setattr(runtime, "PhoneStream", Stream)
    monkeypatch.setattr(runtime, "VoiceCallSession", Session)
    if change == "account":
        row.account_sid = "another-account"
        with pytest.raises(AuthorizationError):
            await runtime.media(socket, row.id, provider=MagicMock(), sessions=sessions)
        socket.accept.assert_not_awaited()
    elif change == "domain_error":
        with pytest.raises(AuthorizationError, match="Session revoked"):
            await runtime.media(socket, row.id, provider=MagicMock(), sessions=sessions)
        assert ended.await_args.kwargs["end_reason"] == "revoked"
        socket.close.assert_awaited_once()
    else:
        await runtime.media(socket, row.id, provider=MagicMock(), sessions=sessions)
        if change in {"missing", "signature"}:
            socket.accept.assert_not_awaited()
            ended.assert_not_awaited()
        else:
            ended.assert_awaited_once()
            assert ended.await_args.kwargs["end_reason"] == "disconnected"
        socket.close.assert_awaited_once()
