"""The widget script itself - the one artefact that runs on somebody else's page.

A syntax error here is not a failed request an operator sees in a log; it is a
console error on a customer's marketing site, on every page load, until somebody
tells them. Nothing else in this repository ships code to a third party's
browser, so nothing else has this failure mode.
"""

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from app.services.embed_session import WIDGET_JS

RENDERED = (
    WIDGET_JS.replace("__PUBLIC_KEY__", "test-key")
    .replace("__BASE_URL__", "https://api.example.test")
    .replace("__VOICE_VERSION__", "0123abcd")
)


def test_every_placeholder_is_substituted():
    """A leftover `__TOKEN__` is a widget that talks to a host called `__BASE_URL__`."""
    assert not re.search(r"__[A-Z_]+__", RENDERED)


@pytest.mark.security
def test_it_carries_no_secret():
    """The script is served to anyone who asks for it - that is the point of a
    script tag, and the reason admission happens on the socket instead."""
    lowered = RENDERED.lower()
    for word in ("secret", "api_key", "apikey", "password", "authorization"):
        assert word not in lowered


def test_the_token_is_read_from_the_page_rather_than_baked_in():
    """The customer sets it per visitor, before the script loads."""
    assert "window.AgenticOSToken" in RENDERED


def test_it_speaks_the_documented_frames():
    """`docs/channels.md` promises the widget reads these five; a rename here
    silently breaks every hand-written client built against that page.

    They are the *dashboard's* frame names since #634, when both sockets started
    driving one loop. It used to be `typing` and `message`, which was the second
    dialect that went with the second loop.
    """
    for frame in ("model_request_start", "text_delta", "final_result", "complete", "error"):
        # The quoted name, which is how the script compares one - a bare substring
        # would be satisfied by the comment that explains the choice.
        assert f'"{frame}"' in RENDERED


def test_it_ignores_the_frames_it_does_not_draw():
    """A widget is a bubble in the corner of somebody else's page: an answer
    arriving a word at a time is worth having there, a narration of tool calls is
    not. The page draws those, and `docs/channels.md` says which client reads what -
    so a widget that quietly started rendering them would make that page wrong.
    """
    for frame in ("thinking_delta", "tool_call", "tool_result"):
        assert f'"{frame}"' not in RENDERED


def test_a_refusal_is_not_retried():
    """4003 means the origin is not allowed or the token failed. Reconnecting
    cannot change either, and a widget that retries is a widget hammering a
    deployment from every page view."""
    assert "4003" in RENDERED
    assert "setTimeout" not in RENDERED or "reconnect" not in RENDERED.lower()


def test_a_rate_limit_close_says_to_wait_rather_than_going_silent():
    """4029 means allowed but too fast. Unlike 4003 the client should say to
    wait - `docs/channels.md` promises exactly that - not leave a dead box with
    nothing on screen."""
    assert "4029" in RENDERED


def test_no_close_leaves_the_box_silently_dead():
    """The two named codes were the only ones that said anything, so the close a
    visitor actually meets - a network blip, a deploy restarting the server, the
    1011 a reader too slow to keep up gets - left a dead input box with nothing on
    screen. That is the failure #634 removed for 4029, one code over. Asserted as
    the `else` rather than as a string, because a message added under an `if` for
    some third code would satisfy a copy check and not the visitor.
    """
    assert "The connection dropped." in RENDERED
    assert 'else bubble("assistant", "The connection dropped.' in RENDERED


def test_a_half_written_answer_is_settled_when_the_socket_goes():
    """`pending` is the bubble the deltas were landing in. Left as it was, a
    sentence the agent was cut off mid-way through reads as the answer it gave."""
    close = RENDERED.split("socket.onclose")[1]
    assert "pending.remove()" in close
    assert "pending = null" in close


def test_only_a_refusal_survives_a_reopen():
    """Clearing `socket` is what lets reopening the launcher reconnect, and 4003 is
    the one code that must not: the answer will not change. So the refusal returns
    before the socket is cleared, and the guard in `onsubmit` is `!socket`."""
    close = RENDERED.split("socket.onclose")[1]
    refusal, retryable = close.split("socket = null")
    assert "4003" in refusal
    assert "return;" in refusal
    assert "4029" in retryable


def test_it_is_valid_javascript():
    """Parsed by an actual engine rather than eyeballed.

    Skipped where node is absent so a Python-only checkout still runs the suite;
    CI has it, which is where this has to hold.
    """
    node = shutil.which("node")
    if node is None:  # pragma: no cover - CI has it; a Python-only checkout may not
        pytest.skip("node is not installed")

    with tempfile.TemporaryDirectory() as directory:
        script = Path(directory) / "widget.js"
        script.write_text(RENDERED, encoding="utf-8")
        result = subprocess.run(
            [node, "--check", str(script)], capture_output=True, text=True, timeout=30
        )

    assert result.returncode == 0, result.stderr


def _voice() -> str:
    """The voice section alone, so an assertion about it is not satisfied by the chat."""
    return RENDERED.split("function mountVoice")[1].split("function mount()")[0]


def test_a_recording_goes_to_the_embeds_own_dictation_route():
    """Server dictation posts to the public route, which admits the widget by its
    allow-list exactly as the socket does (#1797)."""
    assert '"/api/v1/embed/" + KEY + "/dictation"' in RENDERED


@pytest.mark.security
def test_the_recording_request_carries_no_custom_header():
    """A custom header is a CORS preflight, which the global policy refuses for
    somebody else's site - so the token travels as a form field, never in the URL
    where access logs keep it."""
    voice = _voice()
    assert "headers:" not in voice
    assert 'body.append("token", token)' in voice
    assert "?token=" not in voice


def test_the_wav_path_resamples_before_it_encodes():
    """The server accepts exactly 16 kHz mono 16-bit PCM, whatever rate the
    microphone delivers, so the widget resamples and mixes down before it
    writes the samples - and its header says exactly that."""
    assert "var WAV_RATE = 16000;" in RENDERED
    assert "createResampler(context.sampleRate)" in RENDERED
    assert "toPcm16(resample(mixToMono(channels)))" in RENDERED
    assert 'config.dictation_format === "wav"' in RENDERED
    header = RENDERED[RENDERED.index("function wavHeader") : RENDERED.index("function wavRecorder")]
    for field in (
        "view.setUint32(16, 16, true);",  # a 16-byte `fmt ` body
        "view.setUint16(20, 1, true);",  # integer PCM
        "view.setUint16(22, 1, true);",  # one channel
        "view.setUint32(24, WAV_RATE, true);",
        "view.setUint32(28, WAV_RATE * 2, true);",
        "view.setUint16(32, 2, true);",
        "view.setUint16(34, 16, true);",
    ):
        assert field in header


def test_the_text_is_put_in_the_box_and_never_sent():
    """The visitor reads and edits a transcript before it becomes a message."""
    assert "socket.send" not in _voice()
    assert "input.value = value + text" in _voice()


def test_every_refusal_the_route_names_has_a_sentence():
    for reason in (
        "requesting",
        "too_short",
        "mic_denied",
        "mic_not_found",
        "mic_busy",
        "mic_insecure",
        "unsupported_type",
        "empty",
        "too_large",
        "provider_error",
        "timeout",
        "rate_limited",
        "offline",
        "unavailable",
    ):
        assert f"    {reason}: " in RENDERED


def test_reduced_motion_holds_the_level_still():
    assert "prefers-reduced-motion: reduce" in RENDERED


def test_browser_mode_is_offered_only_where_the_browser_has_a_recogniser():
    assert 'if (mode === "browser" && !Recognition) return;' in RENDERED


def test_the_call_script_is_fetched_only_for_an_embed_with_calls_on():
    """`voice.js` is its own script so the bubble every visitor downloads stays
    small (#54, Q8): requested when the panel opens, and only when the public
    config offers calls."""
    loader = RENDERED.split("function loadVoice")[1].split("function mount()")[0]
    assert '"/api/v1/embed/" + KEY + "/voice.js?v=0123abcd"' in loader
    assert "if (voiceRequested) return;" in loader
    assert "window.AgenticOSVoice[KEY]" in loader
    opening = RENDERED.split("launcher.onclick")[1].split("form.onsubmit")[0]
    assert "if (open && config.voice_conversation) loadVoice(callParts);" in opening


def test_a_failed_call_script_can_be_fetched_again():
    loader = RENDERED.split("function loadVoice")[1].split("function mount()")[0]
    assert "script.onerror = function () { voiceRequested = false; };" in loader


def test_closing_the_panel_ends_a_call():
    """A call with its End button hidden would go on billing out of sight."""
    opening = RENDERED.split("launcher.onclick")[1].split("form.onsubmit")[0]
    assert "if (!open && voiceCall) voiceCall.end();" in opening
    assert "voiceCall = mountCall(parts, config)" in RENDERED
