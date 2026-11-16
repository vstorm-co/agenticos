"""Native account broker: pinned TLS, fixed consent destinations and safe failures."""

from collections.abc import Callable
from unittest.mock import AsyncMock
from urllib.parse import urlencode

import httpx2
import pytest
from pydantic import SecretStr

from app.agents.mcp_oauth import OAuthError, OAuthGrantRevoked
from app.core.config import settings
from app.core.pinned_http import PinnedAsyncClient
from app.services.integrations import bridge
from tests.test_connected_accounts import _payload

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def wire(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx2.Request], httpx2.Response]
) -> None:
    monkeypatch.setattr(settings, "OAUTH_BRIDGE_URL", "https://93.184.216.34")
    monkeypatch.setattr(
        bridge,
        "PinnedAsyncClient",
        lambda **kwargs: PinnedAsyncClient(transport=httpx2.MockTransport(handler), **kwargs),
    )


async def test_transport_and_metadata_status(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert str(request.url).startswith("https://93.184.216.34/v1/providers?origin=")
        return httpx2.Response(
            200,
            json=[
                {
                    "provider": "google",
                    "configured": True,
                    "deployment_allowed": True,
                    "client_id": "app",
                }
            ],
        )

    wire(monkeypatch, handler)
    assert await bridge.status("google") == "ready"
    assert await bridge.status("slack") == "unconfigured"
    monkeypatch.setattr(settings, "OAUTH_BRIDGE_URL", "")
    assert await bridge.status("google") == "disabled"
    with pytest.raises(OAuthError):
        await bridge._request("/v1/providers")


@pytest.mark.parametrize(
    "response",
    [
        httpx2.Response(302, headers={"location": "http://127.0.0.1"}),
        httpx2.Response(500, content=b"SECRET"),
        httpx2.Response(400, json={"error": "not_ready"}),
        httpx2.Response(200, content=b"x" * 70000),
        httpx2.Response(200, json={"wrong": "SECRET"}),
    ],
)
async def test_status_refuses_redirects_large_or_invalid_bodies(monkeypatch, response) -> None:
    wire(monkeypatch, lambda request: response)
    assert await bridge.status("google") == "unavailable"


async def test_private_address_and_network_failure_are_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("SECRET internal detail")

    wire(monkeypatch, unavailable)
    with pytest.raises(OAuthError, match="unavailable") as refused:
        await bridge._request("/v1/providers")
    assert "SECRET" not in str(refused.value)
    monkeypatch.setattr(settings, "OAUTH_BRIDGE_URL", "https://127.0.0.1")
    with pytest.raises(OAuthError, match="unavailable"):
        await bridge._request("/v1/providers")


@pytest.mark.parametrize("failure", ["invalid_ticket", "invalid_proof", "provider_grant_revoked"])
async def test_revoked_receipts_require_reconnect(monkeypatch, failure) -> None:
    wire(monkeypatch, lambda request: httpx2.Response(400, json={"error": failure}))
    with pytest.raises(OAuthGrantRevoked):
        await bridge._request("/v1/oauth/refresh", {"refresh_token": "secret"})


@pytest.mark.parametrize("alter", ["none", "host", "client", "callback", "malformed"])
async def test_consent_destination_is_pinned_to_the_requested_provider(monkeypatch, alter) -> None:
    monkeypatch.setattr(settings, "OAUTH_BRIDGE_URL", "https://bridge.example")
    params = {
        "response_type": "code",
        "state": "encrypted-state",
        "scope": "openid",
        "code_challenge": "c" * 43,
        "code_challenge_method": "S256",
        "client_id": "wrong" if alter == "client" else "app",
        "redirect_uri": "https://evil.example"
        if alter == "callback"
        else "https://bridge.example/v1/oauth/callback/google",
    }
    url = (
        (
            "https://evil.example/"
            if alter == "host"
            else "https://accounts.google.com/o/oauth2/v2/auth"
        )
        + "?"
        + urlencode(params)
    )
    request = AsyncMock(
        return_value=b"{}"
        if alter == "malformed"
        else bridge.BridgeStart(authorization_url=url, client_id="app").model_dump_json().encode()
    )
    monkeypatch.setattr(bridge, "_request", request)

    async def start():
        return await bridge.start(
            provider="google",
            redirect_uri="https://customer.example/api/me/mcp-connections/oauth/callback",
            state="s" * 43,
            scopes=["openid"],
            challenge="c" * 43,
        )

    if alter == "none":
        assert (await start()).client_id == "app"
    else:
        with pytest.raises(OAuthError):
            await start()


@pytest.mark.parametrize(
    "mode", ["exchange", "refresh", "origin", "verifier", "receipt", "malformed", "incomplete"]
)
async def test_token_handoff_never_sends_tokens_to_a_changed_bridge(monkeypatch, mode) -> None:
    monkeypatch.setattr(settings, "OAUTH_BRIDGE_URL", "https://bridge.example")
    payload = _payload(
        bridge_url="https://other.example" if mode == "origin" else "https://bridge.example",
        bridge_receipt=None if mode == "receipt" else "receipt",
        code_verifier=None if mode == "verifier" else "v" * 64,
    )
    request = AsyncMock(
        return_value=b"{}"
        if mode == "malformed"
        else b'{"access_token":"new-access","refresh_token":"new-refresh"}'
        if mode == "incomplete"
        else b'{"access_token":"new-access","refresh_token":"new-refresh","receipt":"new-receipt"}'
    )
    monkeypatch.setattr(bridge, "_request", request)
    code = "ticket" if mode in {"exchange", "verifier"} else None
    if mode in {"exchange", "refresh"}:
        result = await bridge.token(payload, code=code)
        assert result.token().access_token == "new-access"
        assert result.receipt == SecretStr("new-receipt")
        assert "new-refresh" not in repr(result)
    else:
        with pytest.raises(OAuthError):
            await bridge.token(payload, code=code)
        if mode in {"origin", "receipt", "verifier"}:
            request.assert_not_awaited()


@pytest.mark.parametrize("origin", ["", "https://bridge.example", "https://bridge.example/"])
def test_bridge_origin_is_an_explicit_https_setting(origin: str) -> None:
    from app.core.config import Settings

    assert Settings.validate_oauth_bridge_url(origin) == origin.rstrip("/")


@pytest.mark.parametrize(
    "origin",
    [
        "http://bridge.example",
        "https://user:secret@bridge.example",
        "https://bridge.example/path",
        "https://bridge.example?next=x",
        "https://bridge.example#x",
        "https://bridge.example:99999",
        "https://bridge.example\\evil",
        "https://bridge.example ",
    ],
)
def test_invalid_bridge_configuration_fails_before_serving(origin: str) -> None:
    from app.core.config import Settings

    with pytest.raises(ValueError):
        Settings.validate_oauth_bridge_url(origin)
