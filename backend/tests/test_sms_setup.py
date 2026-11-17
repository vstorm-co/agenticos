"""Twilio setup owns only configuration of an existing, verified SMS number."""

import base64
from uuid import uuid4

import httpx
import pytest

from app.core.exceptions import BadRequestError, ExternalServiceError
from app.services.channels.sms_setup import configure_sms_webhook

pytestmark = [pytest.mark.anyio, pytest.mark.security]
SID = "AC" + "1" * 32
NUMBER_SID = "PN" + "2" * 32
PHONE = "+15551234567"
TOKEN = "3" * 32
BOT = uuid4()
URL = f"https://agents.example/api/v1/sms/{BOT}/webhook"
CREDENTIALS = f"{SID}:{TOKEN}:{PHONE}"


def number() -> dict[str, object]:
    return {
        "sid": NUMBER_SID,
        "account_sid": SID,
        "phone_number": PHONE,
        "sms_url": None,
        "sms_method": None,
        "capabilities": {"sms": True},
    }


@pytest.mark.parametrize("apply", [False, True])
async def test_setup_reads_or_updates_only_the_verified_existing_number(apply: bool) -> None:
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert (
            request.headers["authorization"]
            == "Basic " + base64.b64encode(f"{SID}:{TOKEN}".encode()).decode()
        )
        assert request.url.host == "api.twilio.com"
        item = number()
        if request.method == "GET":
            assert request.url.params["PhoneNumber"] == PHONE
            return httpx.Response(200, json={"incoming_phone_numbers": [item]})
        assert apply and request.method == "POST"
        assert (
            request.url.path == f"/2010-04-01/Accounts/{SID}/IncomingPhoneNumbers/{NUMBER_SID}.json"
        )
        assert b"SmsMethod=POST" in request.content
        return httpx.Response(200, json={**item, "sms_url": URL, "sms_method": "POST"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await configure_sms_webhook(
            client, bot_token=CREDENTIALS, bot_id=BOT, webhook_url=URL, apply=apply
        )
    assert result.applied is apply and result.webhook_matches is apply
    assert len(calls) == (2 if apply else 1)
    assert all("/Messages" not in str(c.url) for c in calls)


@pytest.mark.parametrize("item", [None, "two", "account", "phone", "voice-only"])
async def test_unconfirmed_number_is_never_changed(item: str | None) -> None:
    entry = number()
    if item == "account":
        entry["account_sid"] = "AC" + "4" * 32
    if item == "phone":
        entry["phone_number"] = "+15557654321"
    if item == "voice-only":
        entry["capabilities"] = {"sms": False}
    items = [] if item is None else [entry, entry] if item == "two" else [entry]
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        return httpx.Response(200, json={"incoming_phone_numbers": items})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(BadRequestError):
            await configure_sms_webhook(
                client, bot_token=CREDENTIALS, bot_id=BOT, webhook_url=URL, apply=True
            )
    assert calls == ["GET"]


@pytest.mark.parametrize(
    "status,body", [(302, b"secret"), (403, b"secret"), (200, b"bad-json"), (200, b"x" * 65537)]
)
async def test_provider_errors_are_bounded_and_not_disclosed(status: int, body: bytes) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(status, content=body))
    ) as client:
        with pytest.raises(ExternalServiceError) as error:
            await configure_sms_webhook(
                client, bot_token=CREDENTIALS, bot_id=BOT, webhook_url=URL, apply=False
            )
    assert "secret" not in error.value.message and TOKEN not in error.value.message


async def test_transport_failure_is_not_retried() -> None:
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise httpx.ReadTimeout("private-provider-detail")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ExternalServiceError) as error:
            await configure_sms_webhook(
                client, bot_token=CREDENTIALS, bot_id=BOT, webhook_url=URL, apply=True
            )
    assert len(calls) == 1 and "private-provider-detail" not in error.value.message


@pytest.mark.parametrize(
    "key,value",
    [
        ("sid", "PN" + "4" * 32),
        ("account_sid", "AC" + "4" * 32),
        ("phone_number", "+15557654321"),
        ("sms_url", "https://elsewhere.example"),
        ("sms_method", "GET"),
    ],
)
async def test_update_requires_confirmation_of_exact_settings(key: str, value: str) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"incoming_phone_numbers": [number()]})
        return httpx.Response(
            200, json={**number(), "sms_url": URL, "sms_method": "POST", key: value}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ExternalServiceError):
            await configure_sms_webhook(
                client, bot_token=CREDENTIALS, bot_id=BOT, webhook_url=URL, apply=True
            )


@pytest.mark.parametrize(
    "token,url",
    [
        ("ACbad:" + TOKEN + ":" + PHONE, URL),
        ("AC" + "z" * 32 + ":" + TOKEN + ":" + PHONE, URL),
        (CREDENTIALS, URL.replace("https:", "http:")),
        (CREDENTIALS, URL + "?token=x"),
        (CREDENTIALS, URL.replace("/sms/", "/email/")),
        (CREDENTIALS, URL.replace("agents.example", "user@agents.example")),
    ],
)
async def test_invalid_account_or_webhook_is_refused_before_network(token: str, url: str) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: pytest.fail("unexpected provider call"))
    ) as client:
        with pytest.raises(BadRequestError):
            await configure_sms_webhook(
                client, bot_token=token, bot_id=BOT, webhook_url=url, apply=True
            )


async def test_inspect_confirms_an_already_configured_webhook() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "incoming_phone_numbers": [{**number(), "sms_url": URL, "sms_method": "POST"}]
                },
            )
        )
    ) as client:
        result = await configure_sms_webhook(
            client, bot_token=CREDENTIALS, bot_id=BOT, webhook_url=URL, apply=False
        )
    assert result.webhook_matches and not result.applied
