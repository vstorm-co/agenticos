"""Microsoft's consent and token exchange for the Outlook portal (#1984).

The failures that must stay recoverable, as for Google: the shared callback only
converts the translated provider error into its `ok=false` result, so anything
this module lets raise past `MicrosoftOAuthError` strands a consent on a 500.
"""

from typing import Any
from unittest.mock import patch

import httpx
import pytest

from app.services.portals import microsoft_oauth

pytestmark = pytest.mark.anyio

_TOKEN = microsoft_oauth.token_endpoint_for("contoso.onmicrosoft.com")


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
    def __init__(self, response: _Resp | Exception) -> None:
        self._response = response
        self.posted: dict[str, Any] = {}

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    async def post(self, url: str, **kwargs: Any) -> _Resp:
        self.posted = {"url": url, **kwargs}
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


async def _exchange(
    response: _Resp | Exception,
) -> tuple[microsoft_oauth.MicrosoftToken, _FakeClient]:
    client = _FakeClient(response)
    with patch("httpx.AsyncClient", lambda **_kw: client):
        token = await microsoft_oauth.exchange_code(
            token_endpoint=_TOKEN,
            client_id="cid",
            client_secret="cs",
            code="c",
            redirect_uri="https://app/cb",
            scopes=["https://graph.microsoft.com/Mail.Read", "offline_access"],
        )
    return token, client


def test_the_endpoints_are_the_tenants() -> None:
    assert microsoft_oauth.authorize_endpoint_for("contoso.onmicrosoft.com") == (
        "https://login.microsoftonline.com/contoso.onmicrosoft.com/oauth2/v2.0/authorize"
    )
    assert _TOKEN.endswith("/contoso.onmicrosoft.com/oauth2/v2.0/token")


def test_the_consent_url_asks_the_person_which_account() -> None:
    """Often signed in to Microsoft as somebody else; a silent consent would
    connect whichever mailbox the browser held."""
    url = microsoft_oauth.authorization_url(
        tenant_id="organizations",
        client_id="cid",
        redirect_uri="https://app/cb",
        scopes=["offline_access"],
        state="s",
    )
    params = httpx.URL(url).params
    assert url.startswith("https://login.microsoftonline.com/organizations/oauth2/v2.0/authorize?")
    assert params["prompt"] == "select_account"
    assert params["response_type"] == "code"
    assert params["scope"] == "offline_access"


async def test_a_well_formed_answer_parses_and_repeats_the_scopes() -> None:
    token, client = await _exchange(
        _Resp(
            200,
            {
                "access_token": "at",
                "refresh_token": "rt",
                "expires_in": 3599,
                "scope": "https://graph.microsoft.com/Mail.Read",
            },
        )
    )
    assert (token.access_token, token.refresh_token, token.expires_in) == ("at", "rt", 3599)
    assert token.granted_scopes == ["https://graph.microsoft.com/Mail.Read"]
    assert client.posted["url"] == _TOKEN
    assert client.posted["data"]["scope"] == "https://graph.microsoft.com/Mail.Read offline_access"


async def test_an_answer_without_a_refresh_token_or_expiry_records_none() -> None:
    token, _ = await _exchange(_Resp(200, {"access_token": "at", "expires_in": "soon"}))
    assert (token.refresh_token, token.expires_in, token.granted_scopes) == (None, None, [])


@pytest.mark.parametrize(
    "response",
    [
        httpx.ConnectError("down"),
        _Resp(400, {"error": "invalid_grant"}),
        _Resp(200, unreadable=True),
        _Resp(200, ["not", "an", "object"]),
        _Resp(200, {"token_type": "Bearer"}),
    ],
    ids=["unreachable", "refused", "not-json", "not-an-object", "no-token"],
)
async def test_every_failure_is_the_recoverable_error(response: _Resp | Exception) -> None:
    with pytest.raises(microsoft_oauth.MicrosoftOAuthError):
        await _exchange(response)
