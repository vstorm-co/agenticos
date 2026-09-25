"""What a notification's destination is, and what an email prints instead.

`notifications.context_url` holds a path, because the console is the reader
that resolves it and a path is what the router navigates as a sub-route rather
than as a whole new document. An email has no origin to resolve one against,
so `absolute_context_url` is the one place `FRONTEND_URL` goes back on - and
the one place that has to keep working for the rows written before the column
changed meaning, which no migration rewrites.
"""

import pytest

from app.core.config import settings
from app.services.notification_center import absolute_context_url


def test_a_path_is_printed_against_the_frontends_own_origin(monkeypatch):
    monkeypatch.setattr(settings, "FRONTEND_URL", "https://console.example")

    assert absolute_context_url("/agents/a1?org=o1") == "https://console.example/agents/a1?org=o1"


def test_a_configured_trailing_slash_does_not_double_the_separator(monkeypatch):
    monkeypatch.setattr(settings, "FRONTEND_URL", "https://console.example/")

    assert absolute_context_url("/vault") == "https://console.example/vault"


def test_a_row_written_before_the_column_changed_meaning_is_left_alone(monkeypatch):
    """The migration this change deliberately does not run. A backfill would
    have to know the origin that was current when each row was written, which
    `FRONTEND_URL` may no longer be - so the legacy shape stays readable
    instead, and ages out with the retention sweep."""
    monkeypatch.setattr(settings, "FRONTEND_URL", "https://console.example")

    assert absolute_context_url("https://old.example/vault") == "https://old.example/vault"


def test_a_protocol_relative_destination_is_not_adopted_as_our_own(monkeypatch):
    """`//evil.example` is a path to a string comparison and another host to a
    browser. Prefixing an origin onto one would mint a link that reads as this
    deployment's and is not."""
    monkeypatch.setattr(settings, "FRONTEND_URL", "https://console.example")

    assert absolute_context_url("//evil.example/vault") == "//evil.example/vault"


@pytest.mark.parametrize("missing", [None, ""])
def test_a_row_with_no_destination_prints_nothing_rather_than_none(missing, monkeypatch):
    """The generic template interpolates this into a button's `href`, where
    `None` prints the word."""
    monkeypatch.setattr(settings, "FRONTEND_URL", "https://console.example")

    assert absolute_context_url(missing) == ""
