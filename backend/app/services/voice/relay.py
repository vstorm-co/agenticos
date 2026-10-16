"""A call's audio through our own socket, for providers without WebRTC (#54, slice 1).

Gemini Live, xAI and Azure: the browser streams PCM16 at the model's input rate
and plays what we send back at its output rate. **Not verified live** - only
OpenAI was available to test against; this is built from the providers' and the
library's documentation and tested with fakes.

**The agent's audio is forwarded in event order, by the event pump** - from the
`audio_chunk` of each speech delta, not from a separate `stream_audio()`
iterator (a deviation from spec amendment 10). Forwarding from the same task
that sees the parts start and end is what makes three things exact: where an
answer's audio begins in what the browser was sent, which part a barge-in cut
off (its later chunks are dropped here, so nothing generated before the provider
processed the cut plays), and that `clear_playback` reaches the browser after
every chunk sent before it. The library's own playback accounting would also
trust a consumer that buffers ahead - ours does, the browser's queue is ahead of
what it has played - so the position is ours too.

**Playback position.** The browser's `played {bytes}` is a position in the
bytes we forwarded, at the model's output rate, where audio it dropped on
`clear_playback` counts as passed. Barge-in truncates the provider's copy to the
time heard on a model that truncates (Azure; `interrupt(played_ms=...)`),
cancels on one that only cancels (xAI), and on Gemini - which the client cannot
interrupt - only drops the browser's queue.

**Inbound pacing.** A browser captures in real time; audio arriving much faster
is not a microphone, and it would run the provider's bill ahead of the call's
clock. A token bucket at 1.5x the input rate drops the excess, and a sustained
flood ends the call.

Nothing runs as a bare task, and closing the session closes our upstream socket,
which ends the call at the provider.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from pydantic_ai.realtime import RealtimeSession

from app.schemas.voice import ClearPlaybackFrame
from app.services.voice.approvals import SendFrame

MAX_FRAME_BYTES = 32_768
"""About 0.7 s of 24 kHz audio: a browser sends ~85 ms frames, so anything larger is not ours."""

INBOUND_RATE = 1.5
"""How much faster than real time the caller's audio may arrive before it is dropped."""

BURST_SECONDS = 2.0
"""Audio the bucket holds: a browser catching up after a stall sends its backlog at once."""

FLOOD_SECONDS = 5.0
"""Dropped audio, net of real time passing, after which the call is ended as not a microphone."""

SendBytes = Callable[[bytes], Awaitable[bool]]
"""Send one binary frame; `False` when the socket is already gone."""


class AudioRelay:
    """One relay call's audio, both ways, and the playback position barge-in needs."""

    def __init__(
        self,
        *,
        send_bytes: SendBytes,
        send: SendFrame,
        input_sample_rate: int,
        output_sample_rate: int,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._send_bytes = send_bytes
        self._send = send
        self._bytes_per_ms = output_sample_rate * 2 / 1000
        self._input_bytes_per_second = input_sample_rate * 2
        self._now = now
        self._tokens = self._input_bytes_per_second * INBOUND_RATE * BURST_SECONDS
        self._overflow = 0.0
        self._last_inbound = now()
        self._muted = False
        self._forwarded = 0
        self._answer_start = 0
        self._part_start = 0
        self._audio_part: int | None = None
        self._cut_part: int | None = None
        self._socket_open = True
        self.played_bytes = 0

    async def inbound(self, session: RealtimeSession, chunk: bytes) -> bool:
        """Hand one frame of the caller's audio to the provider.

        Returns `False` when audio has been arriving far faster than it can be
        spoken for long enough that this is not a microphone: the call should
        end. A frame that is too large or not whole 16-bit samples is not the
        browser's and is dropped. While muted the provider hears silence of the
        same length rather than nothing, so its turn detection still sees the
        caller stop. Push-to-talk is not gated here: the browser disables its
        track, which captures as silence, and can switch the mode mid-call
        without telling us - the same as over WebRTC, where we never see audio.
        """
        if len(chunk) > MAX_FRAME_BYTES or len(chunk) % 2:
            return True
        now = self._now()
        elapsed, self._last_inbound = now - self._last_inbound, now
        rate = self._input_bytes_per_second * INBOUND_RATE
        self._tokens = min(rate * BURST_SECONDS, self._tokens + elapsed * rate)
        self._overflow = max(0.0, self._overflow - elapsed * self._input_bytes_per_second)
        if len(chunk) > self._tokens:
            self._overflow += len(chunk)
            return self._overflow <= self._input_bytes_per_second * FLOOD_SECONDS
        self._tokens -= len(chunk)
        await session.send_audio(bytes(len(chunk)) if self._muted else chunk)
        return True

    def heard(self, played: int) -> None:
        """A `played {bytes}` report. Reports only move forwards: one sent before a
        `clear_playback` reached the browser may arrive after it."""
        self.played_bytes = max(self.played_bytes, min(played, self._forwarded))

    def mute(self, muted: bool) -> None:
        self._muted = muted

    def answer_started(self) -> None:
        """The agent began a new answer: its audio starts after everything forwarded so far."""
        self._answer_start = self._forwarded

    @property
    def unheard(self) -> bool:
        """Whether the browser still has some of the agent's audio left to play."""
        return self._socket_open and self._forwarded > self.played_bytes

    async def forward(self, index: int, chunk: bytes) -> None:
        """Send one chunk of the agent's speech part `index` to the browser.

        A chunk of the part a barge-in cut off is dropped: generated before the
        provider processed the cut, it is audio the caller already talked over.
        """
        if index == self._cut_part or not self._socket_open:
            return
        if index != self._audio_part:
            self._audio_part = index
            self._part_start = self._forwarded
        if not await self._send_bytes(chunk):
            # The socket is gone, and its reader ends the call.
            self._socket_open = False
            return
        self._forwarded += len(chunk)

    async def barge_in(self, session: RealtimeSession) -> int | None:
        """The caller spoke over the agent: cut the answer off where they stopped hearing it.

        Returns the milliseconds of the current answer that were heard, or
        `None` when the browser had nothing left to play - then nobody was
        talked over and nothing is cut.
        """
        if not self.unheard:
            return None
        played = self.played_bytes
        self._cut_part = self._audio_part
        profile = session.profile
        if profile.get("supports_output_truncation", False):
            await session.interrupt(played_ms=self._ms(played - self._part_start))
        elif profile.get("supports_interruption", False):
            await session.interrupt()
        await self._send(ClearPlaybackFrame(type="clear_playback"))
        # The browser drops everything it was sent so far: from its side all of
        # it is behind the playhead now, and its next report says so too.
        self.played_bytes = self._forwarded
        return self._ms(played - self._answer_start)

    def _ms(self, audio_bytes: int) -> int:
        return int(max(0, audio_bytes) / self._bytes_per_ms)
