"""Phone wire contracts: codec vectors, signed forms, caps and unknown acceptance."""

import base64
import json
import struct
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest
from fastapi import WebSocket, WebSocketDisconnect
from pydantic import SecretStr, ValidationError

from app.core.config import settings
from app.core.exceptions import BadRequestError, ExternalServiceError
from app.db.models.telephony import PhoneCall, PhoneContact
from app.schemas.telephony import PhoneCallCreate, PhoneContactConfig, PhoneEndpointConfig
from app.services.telephony import provider
from app.services.telephony.codec import PhoneCodec, decode_mulaw, encode_mulaw
from app.services.telephony.policy import quiet_now
from app.services.telephony.provider import (
    AcceptanceUnknown,
    PhoneCredentials,
    TwilioPhoneProvider,
    call_twiml,
    signature_ok,
    stream_nonce,
    transfer_twiml,
    url,
)
from app.services.telephony.stream import PhoneStream
from app.services.telephony.webhooks import parse_form, read_body

pytestmark = pytest.mark.anyio
AUTH = PhoneCredentials("AC" + "a" * 32, SecretStr("test-auth-token"), "+15551234567")
SID = "CA" + "b" * 32
STREAM = "MZ" + "c" * 32


@pytest.mark.parametrize(
    ("wire", "pcm"), [(255, 0), (127, 0), (128, 32124), (0, -32124), (213, 716), (85, -716)]
)
async def test_g711_known_decode_vectors(wire: int, pcm: int):
    assert decode_mulaw(wire) == pcm


@pytest.mark.parametrize(
    ("pcm", "wire"), [(0, 255), (32767, 128), (-32768, 0), (716, 213), (-716, 85)]
)
async def test_g711_known_encode_vectors(pcm: int, wire: int):
    assert encode_mulaw(pcm) == wire


@pytest.mark.parametrize("rate", [8000, 16000, 24000, 48000])
async def test_packet_boundaries_preserve_samples(rate: int):
    whole = PhoneCodec(input_rate=rate, output_rate=rate)
    split = PhoneCodec(input_rate=rate, output_rate=rate)
    payload = bytes([255, 128, 0, 213, 85]) * 13
    assert split.incoming(payload[:7]) + split.incoming(payload[7:]) == whole.incoming(payload)
    pcm = struct.pack("<66h", *([1200, -1200] * 33))
    assert split.outgoing(pcm[:14]) + split.outgoing(pcm[14:]) == whole.outgoing(pcm)
    assert len(PhoneCodec(input_rate=rate, output_rate=rate).incoming(payload)) == len(
        payload
    ) * 2 * (rate // 8000)


async def test_resampler_rejects_unsupported_rates_and_partial_samples_and_clears_buffer():
    with pytest.raises(ValueError):
        PhoneCodec(input_rate=44100, output_rate=24000)
    codec = PhoneCodec(input_rate=24000, output_rate=24000)
    with pytest.raises(ValueError):
        codec.outgoing(b"x")
    assert codec.outgoing(struct.pack("<h", 32000)) == b""
    codec.clear_output()
    assert codec.outgoing(struct.pack("<3h", 0, 0, 0)) == b"\xff"


@pytest.mark.parametrize(("hour", "expected"), [(7, True), (8, False), (21, False), (22, True)])
async def test_quiet_hours_use_the_contacts_timezone(hour: int, expected: bool):
    contact = PhoneContact(timezone="Europe/Warsaw", quiet_start_hour=22, quiet_end_hour=8)
    # November in Warsaw is UTC+1.
    assert quiet_now(contact, datetime(2026, 11, 4, (hour - 1) % 24, tzinfo=UTC)) is expected


@pytest.mark.security
async def test_contact_and_call_contracts_refuse_ambiguous_modes_and_budgets():
    with pytest.raises(ValidationError):
        PhoneContactConfig(identity_id=uuid4(), timezone="Not/AZone")
    with pytest.raises(ValidationError):
        PhoneContactConfig(identity_id=uuid4(), quiet_start_hour=8, quiet_end_hour=8)
    with pytest.raises(ValidationError):
        PhoneCallCreate(request_key=uuid4(), endpoint_id=uuid4(), mode="report")
    with pytest.raises(ValidationError):
        PhoneCallCreate(request_key=uuid4(), endpoint_id=uuid4(), mode="conversation")
    with pytest.raises(ValidationError):
        PhoneEndpointConfig(price_per_minute_usd=Decimal("0.0000001"))


async def test_twiml_escapes_report_text_and_transfer_is_bounded(monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "https://phone.example")
    call = PhoneCall(
        id=uuid4(),
        endpoint_generation=uuid4(),
        mode="report",
        report_language="en-US",
        report="<not xml> & private",
    )
    document = call_twiml(AUTH, call)
    assert "&lt;not xml&gt; &amp; private" in document and "Stream" not in document
    call.report_language = "pl-PL"
    assert 'voice="Polly.Ewa"' in call_twiml(AUTH, call)
    call.mode = "conversation"
    document = call_twiml(AUTH, call)
    assert "wss://phone.example" in document and stream_nonce(AUTH, call) in document
    assert 'timeLimit="61"' in transfer_twiml("+15551234568", 61)
    with pytest.raises(BadRequestError):
        transfer_twiml("+15551234568", 0)
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "http://phone.example")
    with pytest.raises(BadRequestError):
        url("/inbound/x")


async def test_forms_are_bounded_unambiguous_and_signed_with_all_fields(monkeypatch):
    from app.services.channels.sms import twilio_signature

    params = parse_form(b"CallSid=x&FutureField=new")
    signature = twilio_signature(
        "https://phone.example/inbound", params, AUTH.token.get_secret_value()
    )
    assert signature_ok(AUTH, "https://phone.example/inbound", params, signature)
    assert not signature_ok(AUTH, "https://other.example/inbound", params, signature)
    with pytest.raises(BadRequestError):
        parse_form(b"CallSid=x&CallSid=y")
    with pytest.raises(BadRequestError):
        parse_form(b"x" * 16385)

    async def chunks():
        yield b"x" * 16000
        yield b"x" * 500
        raise AssertionError("Must stop reading after its limit")

    with pytest.raises(BadRequestError):
        await read_body(chunks())


@pytest.mark.parametrize("outcome", ["accepted", "refused", "server_error", "timeout", "invalid"])
async def test_one_provider_submission_never_retries_ambiguous_acceptance(
    monkeypatch, outcome: str
):
    requests = []

    async def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.host == "api.twilio.com"
        assert b"TimeLimit=61" in request.content
        if outcome == "timeout":
            raise httpx.ReadTimeout("late", request=request)
        if outcome == "refused":
            return httpx.Response(400, json={"message": "refused"})
        if outcome == "server_error":
            return httpx.Response(503)
        return httpx.Response(
            201,
            json={
                "sid": "invalid" if outcome == "invalid" else SID,
                "account_sid": AUTH.account,
                "status": "queued",
            },
        )

    real = httpx.AsyncClient
    monkeypatch.setattr(
        provider.httpx,
        "AsyncClient",
        lambda **kwargs: real(transport=httpx.MockTransport(respond), **kwargs),
    )
    adapter = TwilioPhoneProvider()
    if outcome == "accepted":
        assert (
            await adapter.dial(
                AUTH,
                number="+15551234568",
                twiml="<Response />",
                callback="https://phone.example/status",
                cap_seconds=61,
            )
            == SID
        )
    elif outcome == "refused":
        with pytest.raises(ExternalServiceError) as error:
            await adapter.dial(
                AUTH,
                number="+15551234568",
                twiml="<Response />",
                callback="https://phone.example/status",
                cap_seconds=61,
            )
        assert not isinstance(error.value, AcceptanceUnknown)
    else:
        with pytest.raises(AcceptanceUnknown):
            await adapter.dial(
                AUTH,
                number="+15551234568",
                twiml="<Response />",
                callback="https://phone.example/status",
                cap_seconds=61,
            )
    assert len(requests) == 1


def socket():
    raw = MagicMock(spec=WebSocket)
    raw.receive_text = AsyncMock()
    raw.send_json = AsyncMock()
    ready = AsyncMock()
    stream = PhoneStream(raw, account_sid=AUTH.account, call_sid=SID, nonce="n" * 64, ready=ready)
    return raw, stream


@pytest.mark.parametrize("receipt_known", [True, False])
async def test_media_stream_checks_identity_nonce_format_and_translates_audio(receipt_known):
    raw, stream = socket()
    if not receipt_known:
        stream.call = None
    start = {
        "event": "start",
        "streamSid": STREAM,
        "start": {
            "accountSid": AUTH.account,
            "callSid": SID,
            "streamSid": STREAM,
            "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1},
            "customParameters": {"nonce": "n" * 64},
            "tracks": ["inbound"],
        },
    }
    raw.receive_text.side_effect = [
        json.dumps(start),
        json.dumps(
            {
                "event": "media",
                "streamSid": STREAM,
                "media": {"track": "inbound", "payload": base64.b64encode(b"\xff" * 160).decode()},
            }
        ),
    ]
    await stream.start()
    assert stream.call == SID
    assert (await stream.receive())["text"] == '{"type":"start"}'
    incoming = await stream.receive()
    assert incoming["bytes"] == b"\0" * 960
    await stream.send_bytes(b"\0" * 960)
    assert raw.send_json.call_args_list[0].args[0]["event"] == "media"
    assert raw.send_json.call_args_list[1].args[0]["event"] == "mark"
    await stream.send_text('{"type":"clear_playback"}')
    assert raw.send_json.call_args.args[0]["event"] == "clear" and stream._marks == {}


async def test_media_stream_refuses_another_call_or_invalid_encoding():
    raw, stream = socket()
    raw.receive_text.return_value = json.dumps(
        {
            "event": "start",
            "start": {
                "accountSid": AUTH.account,
                "callSid": "CA" + "d" * 32,
                "streamSid": STREAM,
                "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1},
                "customParameters": {"nonce": "n" * 64},
                "tracks": ["inbound"],
            },
        }
    )
    with pytest.raises(WebSocketDisconnect):
        await stream.start()


@pytest.mark.parametrize(
    "payload",
    [
        "x" * 16385,
        "invalid",
        "[]",
        '{"event":"media","streamSid":"foreign"}',
        json.dumps(
            {"event": "media", "streamSid": STREAM, "media": {"track": "inbound", "payload": "%%%"}}
        ),
        json.dumps({"event": "media", "streamSid": STREAM, "media": None}),
    ],
)
async def test_stream_refuses_invalid_or_unbounded_frames(payload: str) -> None:
    raw, stream = socket()
    stream.sid = STREAM
    await stream.receive()
    raw.receive_text.return_value = payload
    with pytest.raises(WebSocketDisconnect):
        await stream.receive()


async def test_stream_playback_marks_stop_and_unrecognized_events_are_bounded(monkeypatch) -> None:
    raw, stream = socket()
    stream.sid = STREAM
    await stream.receive()
    await stream.send_bytes(b"\0" * 960)
    raw.receive_text.return_value = json.dumps(
        {"event": "mark", "streamSid": STREAM, "mark": {"name": "1"}}
    )
    assert json.loads((await stream.receive())["text"]) == {"type": "played", "bytes": 960}
    assert json.loads((await stream.receive())["text"]) == {}
    raw.receive_text.return_value = json.dumps({"event": "connected", "streamSid": STREAM})
    assert json.loads((await stream.receive())["text"]) == {}
    for mark in [{}, {"name": "unknown"}, "invalid"]:
        raw.receive_text.return_value = json.dumps(
            {"event": "mark", "streamSid": STREAM, "mark": mark}
        )
        assert json.loads((await stream.receive())["text"]) == {}
    raw.receive_text.return_value = json.dumps({"event": "stop", "streamSid": STREAM})
    assert (await stream.receive())["type"] == "websocket.disconnect"
    stream._frames = 500
    with pytest.raises(WebSocketDisconnect):
        await stream.receive()
    monkeypatch.setattr("app.services.telephony.stream.time.monotonic", lambda: stream._window + 2)
    assert (await stream.receive())["type"] == "websocket.disconnect"
    await stream.send_bytes(b"\0\0")
    stream._marks = {str(i): i for i in range(500)}
    with pytest.raises(WebSocketDisconnect):
        await stream.send_bytes(b"\0" * 960)


@pytest.mark.parametrize("payload", ["x" * 16385, "{", '{"event":"connected"}'])
async def test_stream_start_requires_a_valid_handshake_within_three_frames(payload: str) -> None:
    raw, stream = socket()
    raw.receive_text.return_value = payload
    with pytest.raises(WebSocketDisconnect):
        await stream.start()


@pytest.mark.parametrize("body", [b"x" * 16385, b"%ff=bad", b"\xff", b"&".join([b"x=y"] * 101)])
async def test_webhook_parser_refuses_invalid_utf8_size_and_field_floods(body: bytes) -> None:
    with pytest.raises(BadRequestError):
        parse_form(body)


async def test_stream_negotiates_rates_and_retains_the_terminal_reason() -> None:
    raw, stream = socket()
    frame = {
        "type": "ready",
        "call_id": str(uuid4()),
        "conversation_id": str(uuid4()),
        "transport": "relay",
        "input_sample_rate": 16000,
        "output_sample_rate": 16000,
        "cap_seconds": 60,
        "resume_token": "resume",
    }
    await stream.send_text(json.dumps(frame))
    stream.ready.assert_awaited_once()
    await stream.send_text('{"type":"ended","reason":"limit"}')
    assert stream.ended_reason == "limit"
    await stream.send_text('{"type":"state","state":"listening"}')
    raw.send_json.assert_not_awaited()


@pytest.mark.parametrize("response", ["gone", "mismatched", "oversized", "valid"])
async def test_provider_cleanup_is_idempotent_and_checks_receipt_identity(
    monkeypatch, response: str
) -> None:
    real = httpx.AsyncClient
    requests = []

    async def reply(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if response == "gone":
            return httpx.Response(404)
        if response == "oversized":
            return httpx.Response(200, content=b"x" * 65537)
        return httpx.Response(
            200,
            json={
                "sid": SID,
                "account_sid": "AC" + "c" * 32 if response == "mismatched" else AUTH.account,
                "status": "completed",
            },
        )

    monkeypatch.setattr(
        provider.httpx,
        "AsyncClient",
        lambda **kwargs: real(transport=httpx.MockTransport(reply), **kwargs),
    )
    adapter = TwilioPhoneProvider()
    if response in {"gone", "valid"}:
        await adapter.hangup(AUTH, SID)
    else:
        with pytest.raises(AcceptanceUnknown):
            await adapter.hangup(AUTH, SID)
    assert len(requests) == 1
    if response == "valid":
        await adapter.cap(AUTH, SID, 60)
        await adapter.transfer(AUTH, SID, number="+15551234568", seconds=60)
    with pytest.raises(BadRequestError):
        await adapter.hangup(AUTH, "invalid")
    with pytest.raises(BadRequestError):
        await adapter.dial(AUTH, number="not a phone", twiml="", callback="", cap_seconds=60)


@pytest.mark.parametrize("body", [b"\xff", b"x=%FF", b"&".join([b"x=y"] * 101)])
async def test_invalid_phone_forms_are_domain_errors(body: bytes) -> None:
    with pytest.raises(BadRequestError, match="Invalid telephone webhook form"):
        parse_form(body)


async def test_small_chunked_webhook_body_preserves_signed_bytes() -> None:
    async def chunks():
        yield b"CallSid="
        yield SID.encode()

    assert await read_body(chunks()) == ("CallSid=" + SID).encode()


@pytest.mark.parametrize(
    "raw", ["malformed", "ACwrong:token:+15551234567", "AC" + "a" * 32 + ":token:invalid"]
)
async def test_phone_credentials_refuse_incomplete_or_invalid_sms_accounts(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    from app.db.models.channel_bot import ChannelBot

    monkeypatch.setattr(provider, "unseal_bot_token", lambda _bot: raw)
    with pytest.raises(BadRequestError):
        provider.credentials(ChannelBot())
