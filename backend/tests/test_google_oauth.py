"""Google's token exchange: the failures that must stay recoverable.

The happy path is exercised through the connection service's tests; what earns a
file of its own is the shape of a failure. The shared OAuth callback only converts
the translated provider error into its recoverable `ok=false` result, so any
response this module lets raise past `GoogleOAuthError` strands a consent flow on
a 500 the user can do nothing about.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from app.services.portals import google_oauth

pytestmark = pytest.mark.anyio


class _Resp:
    def __init__(self, status_code: int, payload: Any = None, *, unreadable: bool = False) -> None:
        self.status_code = status_code
        self._payload = payload
        self._unreadable = unreadable

    def json(self) -> Any:
        if self._unreadable:
            raise ValueError("not json")
        return self._payload


class _FakeClient:
    def __init__(self, response: _Resp) -> None:
        self._response = response

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    async def post(self, url: str, **kwargs: Any) -> _Resp:
        return self._response


async def _exchange(response: _Resp) -> google_oauth.GoogleToken:
    with patch("httpx.AsyncClient", lambda **_kw: _FakeClient(response)):
        return await google_oauth.exchange_code(
            client_id="cid", client_secret="cs", code="c", redirect_uri="https://app/cb"
        )


async def test_a_200_that_is_not_json_is_a_recoverable_error() -> None:
    """An intermediary's HTML error page raises out of `.json()`; that must arrive
    as the provider error the callback recovers, not a 500."""
    with pytest.raises(google_oauth.GoogleOAuthError):
        await _exchange(_Resp(200, unreadable=True))


async def test_a_200_whose_json_is_not_an_object_is_a_recoverable_error() -> None:
    with pytest.raises(google_oauth.GoogleOAuthError):
        await _exchange(_Resp(200, ["not", "an", "object"]))


async def test_a_well_formed_answer_still_parses() -> None:
    token = await _exchange(
        _Resp(
            200,
            {
                "access_token": "at",
                "refresh_token": "rt",
                "expires_in": 3600,
                "scope": "https://www.googleapis.com/auth/gmail.readonly",
            },
        )
    )
    assert token.access_token == "at"
    assert token.refresh_token == "rt"
    assert token.granted_scopes == ["https://www.googleapis.com/auth/gmail.readonly"]
