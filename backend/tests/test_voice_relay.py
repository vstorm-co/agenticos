"""Relaying a call's audio through our socket (#54, slice 1).

Fakes only: Gemini Live, xAI and Azure are not verified live.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.services.voice.relay import FLOOD_SECONDS, MAX_FRAME_BYTES, AudioRelay

pytestmark = pytest.mark.anyio

_SECOND = 48_000
"""One second of 24 kHz 16-bit mono."""

_TRUNCATES = {"supports_interruption": True, "supports_output_truncation": True}
_CANCELS = {"supports_interruption": True, "supports_output_truncation": False}
_NEITHER = {"supports_interruption": False, "supports_output_truncation": False}


class FakeSession:
    def __init__(self, profile=_TRUNCATES):
        self.audio_in: list[bytes] = []
        self.interrupt = AsyncMock(return_value=True)
        self.profile = profile

    async def send_audio(self, data):
        self.audio_in.append(data)


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def _relay(*, socket_open=True, clock=None):
    out: list[bytes] = []
    frames: list[tuple[str, dict]] = []

    async def send_bytes(data):
        if socket_open:
            out.append(data)
        return socket_open

    async def send(kind, payload):
        frames.append((kind, payload))

    relay = AudioRelay(
        send_bytes=send_bytes,
        send=send,
        input_sample_rate=24000,
        output_sample_rate=24000,
        now=clock or Clock(),
    )
    return relay, out, frames


async def test_the_callers_audio_reaches_the_provider():
    relay, _, _ = _relay()
    session = FakeSession()
    assert await relay.inbound(session, b"\x01\x00" * 160)
    assert session.audio_in == [b"\x01\x00" * 160]


async def test_an_oversized_or_odd_frame_is_dropped():
    relay, _, _ = _relay()
    session = FakeSession()
    await relay.inbound(session, b"\x00" * (MAX_FRAME_BYTES + 2))
    await relay.inbound(session, b"\x00" * 3)
    assert session.audio_in == []


async def test_muted_the_provider_hears_silence_of_the_same_length():
    """Silence, not nothing: the provider's turn detection must still hear the caller stop."""
    relay, _, _ = _relay()
    session = FakeSession()
    relay.mute(True)
    await relay.inbound(session, b"\x05\x06" * 4)
    relay.mute(False)
    await relay.inbound(session, b"\x05\x06")
    assert session.audio_in == [b"\x00" * 8, b"\x05\x06"]


async def test_audio_at_the_speed_of_speech_always_gets_through():
    clock = Clock()
    relay, _, _ = _relay(clock=clock)
    session = FakeSession()
    frame = b"\x00" * 4800  # 100 ms at 24 kHz
    for _ in range(600):  # a minute of it
        clock.t += 0.1
        assert await relay.inbound(session, frame)
    assert len(session.audio_in) == 600


async def test_a_backlog_after_a_stall_gets_through():
    relay, _, _ = _relay()
    session = FakeSession()
    for _ in range(20):  # two seconds sent at once
        assert await relay.inbound(session, b"\x00" * 4800)
    assert len(session.audio_in) == 20


async def test_audio_far_faster_than_speech_is_dropped_and_then_ends_the_call():
    """Review 4: a client could otherwise run the provider's bill ahead of the call's clock."""
    clock = Clock()
    relay, _, _ = _relay(clock=clock)
    session = FakeSession()
    frame = b"\x00" * 4800
    results = []
    for _ in range(400):  # 40 s of audio in 4 s of wall clock
        clock.t += 0.01
        results.append(await relay.inbound(session, frame))

    # Sent: the burst allowance plus 1.5x real time; never the whole flood.
    assert len(session.audio_in) * 4800 <= _SECOND * (1.5 * 2 + 1.5 * 4) + 4800
    assert results[-1] is False
    first_refusal = results.index(False)
    # It ended once the excess passed the allowance, not at the first dropped frame.
    assert (first_refusal + 1) * 4800 > _SECOND * FLOOD_SECONDS


async def _forwarded(relay: AudioRelay, *parts: tuple[int, int]) -> None:
    for index, size in parts:
        await relay.forward(index, b"\x00" * size)


async def test_the_agents_audio_reaches_the_browser_in_order():
    relay, out, _ = _relay()
    await relay.forward(1, b"a" * 480)
    await relay.forward(1, b"b" * 480)
    assert out == [b"a" * 480, b"b" * 480]


async def test_barge_in_truncates_to_what_was_played_and_clears_the_browser():
    relay, _, frames = _relay()
    session = FakeSession()
    relay.answer_started()
    await _forwarded(relay, (1, 2 * _SECOND))
    relay.heard(_SECOND)

    played_ms = await relay.barge_in(session)

    session.interrupt.assert_awaited_once_with(played_ms=1000)
    assert played_ms == 1000
    assert frames == [("clear_playback", {})]
    # Everything the browser was sent is behind its playhead once it drops its queue.
    assert relay.played_bytes == 2 * _SECOND
    assert not relay.unheard


async def test_the_time_heard_is_counted_from_the_current_answer_and_part():
    relay, _, _ = _relay()
    session = FakeSession()
    await _forwarded(relay, (1, _SECOND))
    relay.answer_started()
    await _forwarded(relay, (3, _SECOND), (4, 2 * _SECOND))
    relay.heard(_SECOND + _SECOND + _SECOND // 2)

    assert await relay.barge_in(session) == 1500  # of the answer
    session.interrupt.assert_awaited_once_with(played_ms=500)  # of the part being played


async def test_a_model_that_only_cancels_is_cancelled_untruncated():
    """xAI: no output truncation, so the response is cancelled and the browser flushed."""
    relay, _, frames = _relay()
    session = FakeSession(_CANCELS)
    await _forwarded(relay, (1, _SECOND))
    relay.heard(_SECOND // 2)
    assert await relay.barge_in(session) == 500
    session.interrupt.assert_awaited_once_with()
    assert frames == [("clear_playback", {})]


async def test_a_model_that_cannot_be_interrupted_still_has_the_browser_flushed():
    """Gemini: the provider stopped on its own; only the browser's queue is ours to drop."""
    relay, _, frames = _relay()
    session = FakeSession(_NEITHER)
    await _forwarded(relay, (1, _SECOND))
    relay.heard(_SECOND // 2)

    assert await relay.barge_in(session) == 500
    session.interrupt.assert_not_awaited()
    assert frames == [("clear_playback", {})]


async def test_the_cut_parts_late_audio_is_dropped_and_the_next_part_plays():
    relay, out, _ = _relay()
    session = FakeSession()
    await _forwarded(relay, (1, _SECOND))
    await relay.barge_in(session)

    await _forwarded(relay, (1, 960), (2, 480))

    assert [len(chunk) for chunk in out] == [_SECOND, 480]


async def test_speech_after_everything_was_played_cuts_nothing():
    relay, _, frames = _relay()
    session = FakeSession()
    await _forwarded(relay, (1, _SECOND))
    relay.heard(_SECOND)

    assert await relay.barge_in(session) is None
    session.interrupt.assert_not_awaited()
    assert frames == []


async def test_a_report_never_moves_the_playhead_back_or_past_what_was_sent():
    relay, _, _ = _relay()
    await _forwarded(relay, (1, _SECOND))
    relay.heard(_SECOND // 2)
    relay.heard(100)
    assert relay.played_bytes == _SECOND // 2
    relay.heard(10 * _SECOND)
    assert relay.played_bytes == _SECOND


async def test_once_the_socket_is_gone_nothing_is_forwarded_or_cut():
    relay, out, frames = _relay(socket_open=False)
    session = FakeSession()
    await _forwarded(relay, (1, 480), (1, 480))
    assert out == []
    assert await relay.barge_in(session) is None
    assert frames == []
