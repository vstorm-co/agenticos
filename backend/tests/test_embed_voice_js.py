"""The widget's call UI, a separate script loaded only when it is needed (#54, Q8).

Like `widget.js`, this runs on somebody else's page, so a syntax error is a
console error on a customer's site; and unlike it, a resource it forgets to
close is a provider call still billing. Asserted as strings and parsed by node,
the way `test_embed_widget.py` checks the widget.
"""

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from app.services.embed_voice_js import VOICE_JS

HARNESS = Path(__file__).parent / "fixtures" / "voice_widget_harness.js"

RENDERED = VOICE_JS.replace("__PUBLIC_KEY__", "test-key").replace(
    "__BASE_URL__", "https://agents.example.test"
)


def _function(name: str) -> str:
    """One function's body, up to the next top-level-looking declaration."""
    return RENDERED.split(f"function {name}(")[1].split("\n    function ")[0]


def test_it_is_valid_javascript():
    node = shutil.which("node")
    if node is None:  # pragma: no cover - CI has it; a Python-only checkout may not
        pytest.skip("node is not installed")
    with tempfile.TemporaryDirectory() as directory:
        script = Path(directory) / "voice.js"
        script.write_text(RENDERED, encoding="utf-8")
        result = subprocess.run(
            [node, "--check", str(script)], capture_output=True, text=True, timeout=30
        )
    assert result.returncode == 0, result.stderr


def test_every_placeholder_is_substituted():
    assert not re.search(r"__[A-Z_]+__", RENDERED)


@pytest.mark.security
def test_it_carries_no_secret():
    """Served to anyone who asks, like `widget.js`."""
    lowered = RENDERED.lower()
    for word in ("secret", "api_key", "apikey", "password", "authorization"):
        assert word not in lowered


def test_it_calls_the_embeds_own_voice_socket_with_the_pages_token():
    assert '"/api/v1/embed/" + KEY + "/voice/ws"' in RENDERED
    assert "window.AgenticOSToken" in RENDERED
    assert '"?token=" + encodeURIComponent(token)' in RENDERED


def test_it_registers_under_its_own_key():
    """Two widgets on one page each mount their own call, with their own key baked in."""
    assert "window.AgenticOSVoice[KEY] = mount;" in RENDERED


@pytest.mark.security
def test_it_never_opens_a_data_channel():
    """`oai-events` would let the page inject provider events into a call the
    server governs; the offer is checked before it is sent, as the server checks it."""
    assert "createDataChannel" not in RENDERED
    assert "/^m=application/im.test(sdp)" in _function("offer")


@pytest.mark.security
def test_ending_closes_everything_that_could_keep_a_call_billing():
    """A peer connection left open is an OpenAI call still billing."""
    finish = _function("finish")
    assert "closeMedia(c)" in finish
    assert "tracks[i].stop()" in finish
    assert "c.context.close()" in finish
    assert "socket.close()" in finish
    close_media = _function("closeMedia")
    assert "c.pc.close()" in close_media
    assert "c.relay.player.clear()" in close_media


@pytest.mark.security
def test_leaving_the_page_or_losing_the_socket_ends_the_call():
    assert (
        'window.addEventListener("pagehide", function () { if (call) hangUp(call, false); });'
        in RENDERED
    )
    onclose = RENDERED.split("socket.onclose")[1]
    assert "closeMedia(c)" in onclose


def test_end_tells_the_server_before_closing():
    assert 'send(c, { type: "end" });' in _function("hangUp")


def test_the_start_frame_carries_the_offer_the_resume_and_the_pages_variables():
    onopen = RENDERED.split("socket.onopen")[1].split("socket.onmessage")[0]
    for field in (
        "start.sdp_offer = sdp",
        "start.resume_of = resumeOf",
        "start.resume_token = c.resumeToken",
        "start.context = context",
    ):
        assert field in onopen


def test_only_flat_page_variables_are_sent():
    """The server validates the start frame whole: one nested value on the page
    would refuse the call as `no_start`."""
    context = _function("pageContext")
    assert '"string"' in context and '"boolean"' in context and '"number"' in context
    assert "count >= 64" in context


def test_a_relay_streams_pcm_and_reports_playback_for_barge_in():
    assert 'socket.binaryType = "arraybuffer"' in RENDERED
    assert "socket.send(toPcm16(pcm))" in RENDERED
    assert 'send(c, { type: "played", bytes: bytes })' in RENDERED
    assert '"clear_playback"' in RENDERED and "c.relay.player.clear()" in RENDERED
    assert "createResampler(context.sampleRate, frame.input_sample_rate)" in RENDERED


def test_a_drop_is_retried_once_as_the_call_it_continues():
    onclose = RENDERED.split("socket.onclose")[1]
    assert "c.retried = true" in onclose
    assert "schedule(c, c.callId)" in onclose
    assert "RESUME_WINDOW_MS" in onclose


def test_refusals_are_said_and_not_retried():
    onclose = RENDERED.split("socket.onclose")[1]
    refused, rest = onclose.split("c.retried = true")
    assert "event.code === 4003" in refused and "COPY.refused" in refused
    assert "event.code === 4029" in refused and "COPY.too_many" in refused


def test_every_reason_a_visitor_can_meet_has_a_sentence():
    for reason in (
        "user",
        "time_limit",
        "call_limit",
        "budget",
        "unavailable",
        "line_busy",
        "revoked",
        "guardrail",
        "shutdown",
        "disconnected",
        "resume_refused",
    ):
        assert f"    {reason}: " in RENDERED
    assert "ENDED_FALLBACK" in RENDERED


def test_captions_land_in_the_message_list_and_the_saved_turn_replaces_them():
    assert "parts.bubble(" in RENDERED
    assert "message.turn_id" in _function("saved")
    assert "message.interrupted" in _function("saved")


def test_the_call_bar_has_mute_end_a_timer_and_a_level():
    assert '"End call"' in RENDERED
    assert '"Mute microphone"' in RENDERED and '"Unmute microphone"' in RENDERED
    assert 'send(c, { type: "mute", muted: c.muted })' in RENDERED
    assert "clock((c.endsAt - c.startedAt) / 1000)" in RENDERED
    assert "prefers-reduced-motion: reduce" in RENDERED


@pytest.mark.security
def test_there_is_no_approval_card():
    """A visitor's calls carry no tool that needs an approval (decisions, Q7 refined)."""
    assert '"approval"' not in RENDERED


def _run(scenario: str, transport: str = "webrtc") -> dict[str, object]:
    """One scenario of `fixtures/voice_widget_harness.js`, against the real script.

    The harness fakes the DOM, the microphone, Web Audio, the peer connection and
    the socket, and reports what the script did with them.
    """
    node = shutil.which("node")
    if node is None:  # pragma: no cover - CI has it; a Python-only checkout may not
        pytest.skip("node is not installed")
    with tempfile.TemporaryDirectory() as directory:
        script = Path(directory) / "voice.js"
        script.write_text(RENDERED, encoding="utf-8")
        result = subprocess.run(
            [node, str(HARNESS), str(script), scenario, transport],
            capture_output=True,
            text=True,
            timeout=30,
        )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _released(result: dict[str, object]) -> None:
    """Nothing left that could carry audio or keep a provider call billing."""
    assert result["micStopped"] is True
    assert result["contextClosed"] is True
    assert result["peersClosed"] is True
    assert result["barShown"] is False
    assert result["inputShown"] is True


class TestACallInThePage:
    @pytest.mark.parametrize("transport", ["webrtc", "relay"])
    def test_captions_are_replaced_by_the_saved_turns_and_end_gives_the_input_row_back(
        self, transport
    ):
        result = _run("call", transport)

        assert ("sdp_offer" in result["start"]) is (transport == "webrtc")
        assert result["live"] == ["user: What is the time"]
        assert result["label"] == "Speaking"
        assert result["saved"] == [
            "user: What is the time?",
            "assistant: It is noon, [Interrupted]",
        ]
        assert result["endSent"] is True
        assert result["notice"] == "Call ended."
        _released(result)
        # Open after End only for the turns saved on the way out; closed by `ended`.
        assert result["closedOnEnded"] is True

    def test_a_drop_is_resumed_exactly_once_and_keeps_the_mute(self):
        result = _run("drop")

        assert result["label"] == "Reconnecting…"
        assert result["starts"] == [None, "c1"]
        # The resume proves it is this visitor's call with the secret `ready` gave them.
        assert result["startSecrets"] == [None, "secret-of-c1"]
        assert {"type": "mute", "muted": True} in result["resumedFrames"]
        # Muted reads as a crossed-out microphone, one icon, not a red one.
        assert "m2 2 20 20" in result["muteIcon"]
        assert len([d for d in result["muteIcon"] if d == "M12 19v3"]) == 1
        # The resumed connection dropped too: no second retry.
        assert result["sockets"] == 2
        assert result["pendingTimers"] == 0
        assert result["notice"].startswith("The call dropped.")
        _released(result)

    @pytest.mark.parametrize(
        ("scenario", "notice"),
        [
            ("refused", "Calls aren't available on this page."),
            ("too_many", "Too many calls just now - wait a moment and try again."),
            ("line_busy", "All lines are busy. Try again in a few minutes, or type your message."),
        ],
    )
    def test_a_refusal_is_said_and_never_retried(self, scenario, notice):
        result = _run(scenario)

        assert result["notice"] == notice
        assert result["sockets"] == 1
        assert result["pendingTimers"] == 0
        _released(result)


@pytest.mark.security
class TestNothingIsLeftBilling:
    """A peer connection left open is an OpenAI call still billing."""

    def test_leaving_the_page_hangs_up_at_once(self):
        result = _run("pagehide")

        assert result["endSent"] is True
        assert result["socketsClosed"] is True
        _released(result)

    def test_closing_the_panel_ends_the_call(self):
        result = _run("panel_closed")

        assert result["endSent"] is True
        assert result["lingered"] is True
        assert result["socketsClosed"] is True
        _released(result)

    def test_a_media_path_that_fails_hangs_up_rather_than_showing_listening(self):
        result = _run("media_failed")

        assert result["endSent"] is True
        assert result["notice"] == "The call couldn't connect. Please try again."
        assert result["socketsClosed"] is True
        _released(result)

    def test_a_setup_that_throws_still_releases_the_microphone(self):
        result = _run("setup_threw")

        assert result["notice"] == "The call couldn't connect. Please try again."
        _released(result)


def test_a_name_the_server_sends_is_never_read_off_the_object_prototype():
    result = _run("odd_names")

    assert result["afterNotice"] == ""
    assert result["notice"] == "The call ended unexpectedly. Please try again."


def test_a_call_during_dictation_says_why_it_did_not_start():
    result = _run("dictating")

    assert result["sockets"] == 0
    assert result["notice"] == "Finish the dictation first, then start the call."
    assert result["micStopped"] is False
