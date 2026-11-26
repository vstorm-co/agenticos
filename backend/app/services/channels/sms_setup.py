"""Configure an existing Twilio number without buying one or sending a message."""

import asyncio
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from pydantic import BaseModel, Field, SecretStr, ValidationError

from app.core.exceptions import BadRequestError, ExternalServiceError
from app.services.channels.sms import TWILIO_API, split_credentials


class _Capabilities(BaseModel):
    sms: bool


class _Number(BaseModel):
    sid: str = Field(pattern=r"^PN[0-9a-fA-F]{32}$")
    account_sid: str = Field(pattern=r"^AC[0-9a-fA-F]{32}$")
    phone_number: str
    sms_url: str | None = None
    sms_method: str | None = None
    capabilities: _Capabilities


class _Numbers(BaseModel):
    incoming_phone_numbers: list[_Number] = Field(max_length=2)


@dataclass(frozen=True)
class SmsSetupResult:
    number_sid: str
    webhook_matches: bool
    applied: bool


async def _request[Model: BaseModel](
    client: httpx.AsyncClient,
    method: Literal["GET", "POST"],
    path: str,
    *,
    account_sid: str,
    token: SecretStr,
    model: type[Model],
    params: dict[str, str] | None = None,
    data: dict[str, str] | None = None,
) -> Model:
    try:
        async with asyncio.timeout(30):
            async with client.stream(
                method,
                TWILIO_API + path,
                follow_redirects=False,
                auth=(account_sid, token.get_secret_value()),
                params=params,
                data=data,
            ) as response:
                if response.status_code != 200:
                    raise ExternalServiceError(
                        message="Twilio did not confirm number setup; inspect its settings before retrying"
                    )
                body = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=8192):
                    body.extend(chunk)
                    if len(body) > 65536:
                        raise ExternalServiceError(
                            message="Twilio setup response exceeds the supported size"
                        )
                return model.model_validate_json(bytes(body))
    except TimeoutError, httpx.HTTPError, ValidationError:
        raise ExternalServiceError(
            message="Twilio setup was not confirmed; inspect its settings before retrying"
        ) from None


async def configure_sms_webhook(
    client: httpx.AsyncClient,
    *,
    bot_token: str,
    bot_id: UUID,
    webhook_url: str,
    apply: bool,
) -> SmsSetupResult:
    sid, auth, number = split_credentials(bot_token)
    # Sid values become path segments. Refuse malformed legacy credentials before I/O.
    if len(sid) != 34 or any(char not in "0123456789abcdefABCDEF" for char in sid[2:]):
        raise BadRequestError(message="The SMS bot has an invalid Twilio Account SID")
    parsed = urlsplit(webhook_url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.query
        or parsed.fragment
        or parsed.path != f"/api/v1/sms/{bot_id}/webhook"
    ):
        raise BadRequestError(message="Configure the exact public HTTPS SMS webhook address")
    credentials = SecretStr(auth)
    listing = await _request(
        client,
        "GET",
        f"/2010-04-01/Accounts/{sid}/IncomingPhoneNumbers.json",
        account_sid=sid,
        token=credentials,
        model=_Numbers,
        params={"PhoneNumber": number, "PageSize": "2"},
    )
    if len(listing.incoming_phone_numbers) != 1:
        raise BadRequestError(
            message="Twilio did not uniquely identify this number in the configured account"
        )
    found = listing.incoming_phone_numbers[0]
    if found.account_sid != sid or found.phone_number != number:
        raise BadRequestError(
            message="Twilio returned a number belonging to a different account or sender"
        )
    if not found.capabilities.sms:
        raise BadRequestError(message="The selected Twilio number does not support SMS")
    if not apply:
        return SmsSetupResult(
            found.sid, found.sms_url == webhook_url and found.sms_method == "POST", False
        )
    updated = await _request(
        client,
        "POST",
        f"/2010-04-01/Accounts/{sid}/IncomingPhoneNumbers/{found.sid}.json",
        account_sid=sid,
        token=credentials,
        model=_Number,
        data={"SmsUrl": webhook_url, "SmsMethod": "POST"},
    )
    if (
        updated.sid != found.sid
        or updated.account_sid != sid
        or updated.phone_number != number
        or updated.sms_url != webhook_url
        or updated.sms_method != "POST"
    ):
        raise ExternalServiceError(
            message="Twilio did not confirm the expected webhook settings; inspect the number before retrying"
        )
    return SmsSetupResult(found.sid, True, True)
