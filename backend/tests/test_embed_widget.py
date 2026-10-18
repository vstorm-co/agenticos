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

RENDERED = WIDGET_JS.replace("__PUBLIC_KEY__", "test-key").replace(
    "__BASE_URL__", "https://api.example.test"
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


def test_it_draws_the_steps_and_the_sources_but_not_the_reasoning():
    """A step reads as a chip - *Searching the knowledge base* - and the documents
    an answer drew on as names under it (#2006). Both arrive only when the server
    sends them: `tool_call` without its arguments unless the operator shows
    results, `sources` only when they switched it on. The reasoning stays out:
    `docs/channels.md` says which client reads what."""
    for frame in ("tool_call", "tool_result", "sources"):
        assert f'"{frame}"' in RENDERED
    assert '"thinking_delta"' not in RENDERED


@pytest.mark.security
def test_an_answer_is_never_parsed_as_html():
    """An answer is model output drawn on a customer's page; a string handed to
    `innerHTML` there is script on their site. The one `innerHTML` is the send
    button's icon, a literal in this file."""
    assignments = re.findall(r"\.innerHTML\s*=\s*([^;]+);", RENDERED)
    assert len(assignments) == 1
    assert assignments[0].lstrip().startswith("'<svg")
    assert "insertAdjacentHTML" not in RENDERED
    assert "document.write" not in RENDERED


@pytest.mark.security
def test_a_link_in_an_answer_is_only_ever_http():
    """`javascript:` in a Markdown link is the classic way out of a chat bubble."""
    assert "if (!/^https?:\\/\\//i.test(href)) return document.createTextNode(label);" in RENDERED
    assert 'a.rel = "noopener noreferrer nofollow";' in RENDERED


def test_every_style_rule_is_its_own():
    """The stylesheet lands on somebody else's page: a rule not scoped to the
    widget's root would restyle their site."""
    css = RENDERED.split("var CSS = [")[1].split("].join")[0]
    selectors = re.findall(r"\"([^\"{}]+)\{", css)
    assert selectors
    for selector in selectors:
        if selector.startswith("@") or selector in ("from", "to") or "%" in selector:
            continue
        for part in selector.split(","):
            assert part.strip().startswith(".aos-"), part


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
    assert 'else botBubble("The connection dropped.' in RENDERED


def test_a_half_written_answer_is_settled_when_the_socket_goes():
    """`turn` is the answer the deltas were landing in. Left as it was - caret and
    all - a sentence the agent was cut off mid-way through reads as one still
    coming; an empty one is removed."""
    close = RENDERED.split("socket.onclose")[1]
    assert close.index("endTurn();") < close.index("4003")
    settle = RENDERED.split("function endTurn()")[1].split("function connect()")[0]
    assert ".remove()" in settle
    assert "draw(turn, false)" in settle
    assert "turn = null" in settle


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
