"""A bridge's mandatory query credential stays out of client-visible URLs and logs."""

import logging
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.core.exceptions import ExternalServiceError
from app.services.channels.imessage_transport import BridgeCredentials, BridgeTransport

pytestmark = pytest.mark.anyio


def credentials(password: str = "private-password") -> BridgeCredentials:
    return BridgeCredentials(
        bot_id=uuid4(), server="https://bridge.example.com/prefix", password=SecretStr(password)
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://user:secret@example.com",
        "https://example.com?password=secret",
        "https://example.com#secret",
        "file:///private/bridge",
        "https://example.com/" + "x" * 500,
    ],
)
def test_credentials_refuse_ambiguous_or_embedded_authentication(url: str) -> None:
    with pytest.raises(ValidationError):
        BridgeCredentials(bot_id=uuid4(), server=url, password=SecretStr("password"))


@pytest.mark.security
def test_ephemeral_credential_roundtrip_keeps_its_secret_out_of_representation() -> None:
    original = credentials()
    assert BridgeCredentials.decode(original.encode()) == original
    assert "private-password" not in repr(original)
    assert (
        original.url("/api/v1/server/info")
        == "https://bridge.example.com/prefix/api/v1/server/info"
    )
    with pytest.raises(ValueError):
        original.url("https://different.example.com/steal")


@pytest.mark.security
@pytest.mark.parametrize(
    "value",
    ["{}", "not json", '{"server":"https://x.example","password":"","extra":"private-password"}'],
)
def test_malformed_credential_error_does_not_echo_secret_input(value: str) -> None:
    with pytest.raises(ExternalServiceError) as caught:
        BridgeCredentials.decode(value)
    assert "private-password" not in str(caught.value)
    assert caught.value.__cause__ is None


async def test_only_the_wire_request_contains_password_and_http_logs_remain_clean(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="httpx")
    sent: list[str] = []

    async def respond(request: httpx.Request) -> httpx.Response:
        sent.append(request.url.params["password"])
        assert "agenticos_imessage_password" not in request.extensions
        assert request.url.params["limit"] == "1"
        return httpx.Response(200, json={"status": 200}, request=request)

    creds = credentials()
    async with httpx.AsyncClient(transport=BridgeTransport(httpx.MockTransport(respond))) as client:
        response = await client.get(
            creds.url("/api/v1/server/info"), params={"limit": 1}, extensions=creds.extensions()
        )
    assert sent == ["private-password"]
    assert "password" not in str(response.request.url)
    assert "private-password" not in caplog.text
    assert "private-password" not in repr(response)


@pytest.mark.parametrize("status", [401, 500])
async def test_http_failure_has_only_the_public_request_url(status: int) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, request=request)

    creds = credentials()
    async with httpx.AsyncClient(transport=BridgeTransport(httpx.MockTransport(respond))) as client:
        response = await client.get(creds.url("/api/v1/server/info"), extensions=creds.extensions())
        with pytest.raises(httpx.HTTPStatusError) as caught:
            response.raise_for_status()
    assert "private-password" not in str(caught.value)
    assert "password" not in str(caught.value.request.url)


async def test_transport_failure_retires_the_wire_url_before_error_observers_see_it() -> None:
    async def fail(request: httpx.Request) -> httpx.Response:
        assert request.url.params["password"] == "private-password"
        raise httpx.ConnectError("bridge unavailable", request=request)

    creds = credentials()
    async with httpx.AsyncClient(transport=BridgeTransport(httpx.MockTransport(fail))) as client:
        with pytest.raises(httpx.ConnectError) as caught:
            await client.get(creds.url("/api/v1/server/info"), extensions=creds.extensions())
    assert "password" not in str(caught.value.request.url)


async def test_credentials_cannot_follow_one_request_to_another_bridge() -> None:
    seen: list[tuple[str, str]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.host, request.url.params["password"]))
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=BridgeTransport(httpx.MockTransport(respond))) as client:
        first = credentials("first")
        second = BridgeCredentials(
            bot_id=uuid4(), server="https://second.example.com", password=SecretStr("second")
        )
        for current in (first, second):
            await client.get(current.url("/api/v1/server/info"), extensions=current.extensions())
        with pytest.raises(ExternalServiceError):
            await client.get(first.url("/api/v1/server/info"))
    assert seen == [("bridge.example.com", "first"), ("second.example.com", "second")]
