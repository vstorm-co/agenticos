"""The address a platform is told to send to is one this deployment answers.

`register_webhook` built `/api/v1/channels/{platform}/{bot_id}/webhook` at two
call sites. `/channels` carries the management endpoints; the receivers are
mounted one level up. So `set_webhook` succeeded, the endpoint answered
`{"success": true}`, and Telegram POSTed into a 404 for as long as the bot
existed - a bot that answers nothing, with nothing in any log to say why.

Nothing tied the two together, which is why they could drift. These tests do:
each path is resolved against the application's own routing table rather than
compared to a second string, so moving a receiver fails here instead of in a
deployment.
"""

import uuid
from urllib.parse import urlparse

import pytest
from starlette.routing import Match

from app.commands.channel import channel_add_bot
from app.core.config import settings
from app.main import app
from app.services.channels import INBOUND_PATHS, inbound_webhook_url


def _resolves(url: str) -> bool:
    """Whether the application would route a POST to `url` to a handler."""
    scope = {
        "type": "http",
        "method": "POST",
        "path": urlparse(url).path,
        "path_params": {},
        "root_path": "",
        "headers": [],
    }
    return any(route.matches(scope)[0] is Match.FULL for route in app.routes)


@pytest.mark.parametrize("platform", sorted(INBOUND_PATHS))
def test_the_url_a_platform_is_given_resolves_to_a_handler(platform: str):
    url = inbound_webhook_url(platform, uuid.uuid4())
    assert _resolves(url), url


def test_the_url_that_used_to_be_registered_resolves_to_nothing():
    """The regression itself, stated as what it was: `/channels` in the middle.

    Without this the parametrised test above passes on any path that happens to
    exist, and the bug it is guarding against was precisely a path that did not.
    """
    bot_id = uuid.uuid4()
    stale = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/api/v1/channels/telegram/{bot_id}/webhook"
    assert not _resolves(stale)


def test_slack_is_told_its_events_endpoint_rather_than_a_webhook_one():
    """The paths are not uniform, which is why formatting one was wrong: Slack's
    receiver is its Events API endpoint. A single f-string cannot serve all
    three."""
    url = inbound_webhook_url("slack", uuid.uuid4())
    assert url.endswith("/events")


def test_every_platform_that_can_be_registered_has_an_address():
    """A platform an operator can create a bot for, and cannot be reached on, is
    a bot that is registered and answers nothing.

    Read off the CLI's own choices rather than restated here, so adding a
    platform in one place and not the other fails rather than passing quietly.
    """
    choices = next(p for p in channel_add_bot.params if p.name == "platform").type.choices
    assert set(INBOUND_PATHS) == set(choices)


def test_a_platform_with_no_receiver_is_refused_rather_than_invented():
    """An invented URL is worse than a refusal: it is registered with the
    platform and fails silently from then on."""
    with pytest.raises(KeyError):
        inbound_webhook_url("discord", uuid.uuid4())


def test_the_url_is_built_from_the_one_public_base():
    """The same setting embeds and OAuth callbacks are built from - a second one
    for the same address is how two of them drift apart."""
    url = inbound_webhook_url("telegram", uuid.uuid4())
    assert url.startswith(settings.PUBLIC_BASE_URL.rstrip("/"))


def test_a_trailing_slash_on_the_base_does_not_double_up(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "https://api.example.com/")
    url = inbound_webhook_url("telegram", uuid.uuid4())
    assert url.startswith("https://api.example.com/api/v1/")
