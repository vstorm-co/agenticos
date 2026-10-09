"""Entra's consent URL, token exchange and refresh, against a fake token endpoint.

What earns a file of its own is what differs from Google's: PKCE on the code,
no `resource` on a refresh, and `AADSTS65001` arriving as the decision it is
rather than as a generic refusal.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app.services.portals import microsoft_oauth

pytestmark = pytest.mark.anyio

TENANT = "contoso.onmicrosoft.com"
CLIENT_ID = "0f9e8d7c-6b5a-4f3e-9d2c-1b0a9f8e7d6c"
SCOPES = ["offline_access", "User.Read"]
TOKEN_URL = microsoft_oauth.token_endpoint(TENANT)

_RealAsyncClient = httpx.AsyncClient


@contextmanager
def _entra(handler: Callable[[httpx.Request], httpx.Response]) -> Iterator[list[httpx.Request]]:
    """Answer every request the module makes with `handler`, recording each."""
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    def client(*, timeout: httpx.Timeout) -> httpx.AsyncClient:
        return _RealAsyncClient(transport=httpx.MockTransport(record), timeout=timeout)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(httpx, "AsyncClient", client)
        yield seen


def _form(request: httpx.Request) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(request.content.decode()).items()}


async def _refresh() -> microsoft_oauth.MicrosoftToken:
    return await microsoft_oauth.refresh_tokens(
        token_endpoint=TOKEN_URL,
        client_id=CLIENT_ID,
        client_secret="app-secret",
        refresh_token="old-refresh",
        scopes=SCOPES,
    )


def test_the_consent_url_is_the_tenants_and_carries_a_pkce_challenge() -> None:
    url = microsoft_oauth.authorization_url(
        tenant_id=TENANT,
        client_id=CLIENT_ID,
        redirect_uri="https://app.example/cb",
        scopes=SCOPES,
        state="state-123",
        code_challenge="challenge-abc",
    )

    parts = urlsplit(url)
    query = {key: values[0] for key, values in parse_qs(parts.query).items()}
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == microsoft_oauth.authorize_endpoint(
        TENANT
    )
    assert query["code_challenge"] == "challenge-abc"
    assert query["code_challenge_method"] == "S256"
    assert query["scope"] == "offline_access User.Read"
    assert query["prompt"] == "select_account"


def test_the_admin_consent_url_asks_for_the_graph_permissions_alone() -> None:
    url = microsoft_oauth.admin_consent_url(
        tenant_id=TENANT, client_id=CLIENT_ID, scopes=SCOPES, redirect_uri="https://app.example/cb"
    )

    parts = urlsplit(url)
    assert parts.path == f"/{TENANT}/v2.0/adminconsent"
    assert parse_qs(parts.query)["scope"] == ["https://graph.microsoft.com/User.Read"]


async def test_a_code_is_exchanged_with_its_verifier() -> None:
    with _entra(
        lambda _: httpx.Response(
            200,
            json={
                "access_token": "at",
                "refresh_token": "rt",
                "expires_in": 3599,
                "scope": "User.Read profile openid email",
            },
        )
    ) as seen:
        token = await microsoft_oauth.exchange_code(
            token_endpoint=TOKEN_URL,
            client_id=CLIENT_ID,
            client_secret="app-secret",
            code="the-code",
            code_verifier="the-verifier",
            redirect_uri="https://app.example/cb",
            scopes=SCOPES,
        )

    assert token == microsoft_oauth.MicrosoftToken(
        access_token="at",
        refresh_token="rt",
        expires_in=3599,
        granted_scopes=["User.Read", "profile", "openid", "email"],
    )
    form = _form(seen[0])
    assert str(seen[0].url) == TOKEN_URL
    assert form["code_verifier"] == "the-verifier"
    assert form["grant_type"] == "authorization_code"


async def test_a_refresh_sends_no_resource_and_takes_the_rotated_token() -> None:
    with _entra(
        lambda _: httpx.Response(200, json={"access_token": "new-at", "refresh_token": "new-rt"})
    ) as seen:
        token = await _refresh()

    form = _form(seen[0])
    assert "resource" not in form
    assert form["scope"] == "offline_access User.Read"
    assert form["refresh_token"] == "old-refresh"
    assert token.refresh_token == "new-rt"
    assert token.expires_in is None


async def test_aadsts65001_is_reported_as_an_administrators_decision() -> None:
    body = {
        "error": "invalid_grant",
        "error_description": "AADSTS65001: The user or administrator has not consented.",
        "error_codes": [65001],
    }
    with (
        _entra(lambda _: httpx.Response(400, json=body)),
        pytest.raises(microsoft_oauth.MicrosoftAdminConsentRequired, match="administrator"),
    ):
        await _refresh()


async def test_another_refusal_does_not_quote_entra() -> None:
    body = {"error": "invalid_grant", "error_description": "AADSTS70008: secret-ish trace"}
    with (
        _entra(lambda _: httpx.Response(400, json=body)),
        pytest.raises(microsoft_oauth.MicrosoftOAuthError) as raised,
    ):
        await _refresh()

    assert not isinstance(raised.value, microsoft_oauth.MicrosoftAdminConsentRequired)
    assert "AADSTS" not in str(raised.value)


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (httpx.Response(200, text="<html>gateway</html>"), "unreadable"),
        (httpx.Response(200, json=["not", "an", "object"]), "unreadable"),
        (httpx.Response(200, json={"token_type": "Bearer"}), "without an access token"),
    ],
)
async def test_an_answer_with_no_token_is_a_recoverable_error(
    response: httpx.Response, expected: str
) -> None:
    with (
        _entra(lambda _: response),
        pytest.raises(microsoft_oauth.MicrosoftOAuthError, match=expected),
    ):
        await _refresh()


async def test_an_unreachable_endpoint_is_a_recoverable_error() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with _entra(refuse), pytest.raises(microsoft_oauth.MicrosoftOAuthError, match="reached"):
        await _refresh()
