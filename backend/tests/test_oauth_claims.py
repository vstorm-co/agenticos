"""Where a provider actually keeps `email` and its verification claim (#1419).

Authlib parses the ID token into `token["userinfo"]`, and for Google that is the
whole story. An OIDC provider is entitled to keep profile claims at its UserInfo
endpoint instead and put neither in the token - so a callback reading only the
parsed token refuses a compliant provider for supplying nothing, one request
short of a valid, verified identity.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.routes.v1._oauth_claims import claims_for

pytestmark = pytest.mark.anyio

FULL = {"sub": "s-1", "email": "ada@corp.example", "email_verified": True, "name": "Ada"}


def _client(userinfo: dict[str, object] | Exception | None = None) -> MagicMock:
    client = MagicMock()
    client.userinfo = AsyncMock(
        side_effect=userinfo if isinstance(userinfo, Exception) else None,
        return_value=userinfo if not isinstance(userinfo, Exception) else None,
    )
    return client


async def test_an_id_token_that_carries_everything_costs_no_round_trip() -> None:
    """A network request per sign-in, for the providers that do not need one."""
    client = _client()

    assert await claims_for(client, {"userinfo": FULL}) == FULL
    client.userinfo.assert_not_awaited()


async def test_a_provider_that_keeps_its_claims_at_userinfo_is_asked() -> None:
    client = _client(FULL)

    assert await claims_for(client, {"userinfo": {"sub": "s-1"}}) == FULL
    client.userinfo.assert_awaited_once()


async def test_userinfo_wins_where_both_carry_a_claim() -> None:
    """The endpoint the provider directs profile reads at is the current one."""
    client = _client({"email": "new@corp.example"})

    merged = await claims_for(client, {"userinfo": {"sub": "s-1", "email": "old@corp.example"}})

    assert merged["email"] == "new@corp.example"
    assert merged["sub"] == "s-1"


async def test_a_verification_claim_that_says_no_is_an_answer_not_a_gap() -> None:
    """Fetching UserInfo would not change a present `false`, and a round trip per
    refused sign-in is a round trip an attacker can ask for."""
    client = _client(FULL)

    claims = await claims_for(client, {"userinfo": {**FULL, "email_verified": False}})

    assert claims["email_verified"] is False
    client.userinfo.assert_not_awaited()


async def test_a_failed_fetch_leaves_the_token_to_be_judged_on() -> None:
    """Not fatal on its own: the caller refuses on the claims, not on the fetch."""
    client = _client(RuntimeError("userinfo is down"))

    assert await claims_for(client, {"userinfo": {"sub": "s-1"}}) == {"sub": "s-1"}


async def test_neither_source_producing_anything_is_no_claims_at_all() -> None:
    client = _client({})

    assert await claims_for(client, {}) is None
