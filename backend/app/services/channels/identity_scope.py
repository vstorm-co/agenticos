"""Bind Matrix identities to the configured homeserver that asserts them."""

from typing import TYPE_CHECKING, TypedDict

import httpx

if TYPE_CHECKING:
    from app.db.models.channel_bot import ChannelBot


class IdentityScope(TypedDict, total=False):
    server_url: str


def canonical_matrix_server(api_base_url: str | None) -> str:
    """The exact homeserver authority, without cosmetic URL differences.

    Paths remain significant: two services hosted below one origin must not
    share identities. Credentials, queries and fragments cannot define a scope
    or appear on the account-link confirmation page.
    """
    if not api_base_url:
        raise ValueError("A Matrix identity requires its homeserver URL")
    try:
        url = httpx.URL(api_base_url)
    except httpx.InvalidURL:
        raise ValueError("A Matrix identity requires a valid homeserver URL") from None
    if (
        url.scheme not in {"http", "https"}
        or not url.host
        or any(char in url.host for char in "[]%")
    ):
        raise ValueError("A Matrix identity requires an HTTP or HTTPS homeserver URL")
    if (
        url.username
        or url.password
        or url.query
        or url.fragment
        or "?" in api_base_url
        or "#" in api_base_url
    ):
        raise ValueError("A Matrix homeserver URL cannot contain credentials, query or fragment")
    canonical = str(url).rstrip("/")
    if len(canonical) > 500:
        raise ValueError("A Matrix homeserver URL cannot exceed 500 characters")
    return canonical


def identity_scope(bot: ChannelBot) -> IdentityScope:
    """Repository selectors derived from a trusted bot row, never the sender."""
    if bot.platform != "matrix":
        return {}
    return {"server_url": canonical_matrix_server(bot.api_base_url)}
