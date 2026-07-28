"""The widget script itself — the one artefact that runs on somebody else's page.

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


def test_it_carries_no_secret():
    """The script is served to anyone who asks for it — that is the point of a
    script tag, and the reason admission happens on the socket instead."""
    lowered = RENDERED.lower()
    for word in ("secret", "api_key", "apikey", "password", "authorization"):
        assert word not in lowered


def test_the_token_is_read_from_the_page_rather_than_baked_in():
    """The customer sets it per visitor, before the script loads."""
    assert "window.AgenticOSToken" in RENDERED


def test_it_speaks_the_documented_frames():
    """`docs/channels.md` promises these four; a rename here silently breaks
    every hand-written client built against that page."""
    for frame in ("typing", "message", "error", "ready"):
        assert frame in RENDERED


def test_a_refusal_is_not_retried():
    """4003 means the origin is not allowed or the token failed. Reconnecting
    cannot change either, and a widget that retries is a widget hammering a
    deployment from every page view."""
    assert "4003" in RENDERED
    assert "setTimeout" not in RENDERED or "reconnect" not in RENDERED.lower()


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
