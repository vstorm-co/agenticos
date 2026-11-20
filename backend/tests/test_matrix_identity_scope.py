"""A homeserver can assert only identities explicitly linked on that endpoint."""

from uuid import uuid4

import pytest

from app.db.models.channel_bot import ChannelBot
from app.repositories.channel_identity import require_identity_scope
from app.services.channels.identity_scope import canonical_matrix_server, identity_scope
from app.services.channels.matrix_protocol import audience_of, room_key, server_fingerprint


@pytest.mark.parametrize(
    "url", ["https://MATRIX.example.org:443/", "https://matrix.example.org///"]
)
def test_cosmetic_server_differences_share_one_authority(url: str) -> None:
    assert canonical_matrix_server(url) == "https://matrix.example.org"


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        "https://[broken",
        "https://host:invalid-port",
        "https://host?",
        "https://host#",
        "ftp://example.org",
        "https:///",
        "https://u:p@host",
        "https://host?secret=yes",
        "https://host/#fragment",
        "https://host/" + "a" * 500,
    ],
)
def test_invalid_or_secret_bearing_servers_are_refused(url: str | None) -> None:
    with pytest.raises(ValueError):
        canonical_matrix_server(url)


def test_paths_and_distinct_servers_have_separate_authorities() -> None:
    urls = ["https://a.example.org", "https://b.example.org", "https://a.example.org/other"]
    assert len({server_fingerprint(url) for url in urls}) == 3
    assert len({room_key("!room:domain", server_url=url) for url in urls}) == 3


def test_scope_comes_from_the_bot_not_the_matrix_user_domain() -> None:
    bot = ChannelBot(id=uuid4(), platform="matrix", api_base_url="https://HS.example.org/")
    assert identity_scope(bot) == {"server_url": "https://hs.example.org"}
    bot.platform = "slack"
    assert identity_scope(bot) == {}


def test_legacy_unscoped_matrix_lookups_fail_closed() -> None:
    with pytest.raises(ValueError, match="homeserver"):
        require_identity_scope("matrix", "")
    require_identity_scope("slack", "")
    require_identity_scope("matrix", "https://hs")


@pytest.mark.parametrize(
    "suffix",
    [
        "s=bad",
        "s=" + "a" * 64 + "|s=" + "b" * 64,
        "x=bad",
        "u=%40ada%3Adomain",
        "s=" + "a" * 64 + "|u=invalid",
        "s=" + "a" * 64 + "|u=%40ada%3Adomain|u=%40eve%3Adomain",
    ],
)
def test_malformed_audience_keys_are_refused(suffix: str) -> None:
    with pytest.raises(ValueError):
        audience_of("!room%3Adomain|" + suffix)


def test_private_keys_require_the_original_server() -> None:
    with pytest.raises(ValueError, match="homeserver"):
        room_key("!room:domain", private_recipient="@ada:domain")
    key = room_key("!room:domain", server_url="https://hs", private_recipient="@ada:domain")
    assert audience_of(key) == (server_fingerprint("https://hs"), "@ada:domain")
    assert audience_of("!room%3Adomain") == (None, None)
