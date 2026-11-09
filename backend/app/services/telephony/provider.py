"""Twilio's call transport: one submission, explicit unknown acceptance, signed callbacks.

No submission is retried. A timeout after POST may already have rung a phone;
the durable intent waits for its signed status callback instead of redialling.
"""

import hashlib
import hmac
import re
from dataclasses import dataclass, field
from secrets import compare_digest
from typing import Protocol
from xml.etree.ElementTree import Element, SubElement, tostring

import httpx
from pydantic import SecretStr, ValidationError

from app.core.config import settings
from app.core.exceptions import BadRequestError, ExternalServiceError
from app.db.models.channel_bot import ChannelBot
from app.db.models.telephony import PhoneCall
from app.schemas.telephony import TwilioCallReceipt
from app.services.channel_bot import unseal_bot_token
from app.services.channels.exceptions import ChannelNotConfigured
from app.services.channels.sms import split_credentials, twilio_signature

SID = re.compile(r"^CA[0-9a-fA-F]{32}$")
NUMBER = re.compile(r"^\+[1-9][0-9]{6,14}$")


class AcceptanceUnknown(ExternalServiceError):
    """The request may have been accepted; only a callback may resolve it."""


@dataclass(frozen=True)
class PhoneCredentials:
    account: str
    token: SecretStr = field(repr=False)
    number: str


def credentials(bot: ChannelBot) -> PhoneCredentials:
    try:
        account, token, number = split_credentials(unseal_bot_token(bot))
    except ChannelNotConfigured as exc:
        raise BadRequestError(
            message="The Twilio bot needs an account, auth token and number"
        ) from exc
    if not re.fullmatch(r"AC[0-9a-fA-F]{32}", account) or not NUMBER.fullmatch(number):
        raise BadRequestError(message="Choose a valid Twilio SMS bot account and E.164 number")
    return PhoneCredentials(account, SecretStr(token), number)


def url(path: str, *, websocket: bool = False) -> str:
    base = settings.PUBLIC_BASE_URL.rstrip("/")
    if not base.startswith("https://"):
        raise BadRequestError(message="Telephone webhooks require an HTTPS PUBLIC_BASE_URL")
    if websocket:
        base = "wss://" + base.removeprefix("https://")
    return base + settings.API_V1_STR + "/phone" + path


def signature_ok(
    credentials: PhoneCredentials, address: str, params: dict[str, str], signature: str
) -> bool:
    return (
        bool(signature)
        and signature.isascii()
        and compare_digest(
            twilio_signature(address, params, credentials.token.get_secret_value()), signature
        )
    )


def stream_nonce(credentials: PhoneCredentials, call: PhoneCall) -> str:
    return hmac.new(
        credentials.token.get_secret_value().encode(),
        f"phone:{call.id}:{call.endpoint_generation}".encode(),
        hashlib.sha256,
    ).hexdigest()


_REPORT_VOICES = {
    "en-US": ("Polly.Joanna", "This is an automated report from your AI assistant."),
    "pl-PL": ("Polly.Ewa", "To jest automatyczny raport od Twojego asystenta AI."),
    "de-DE": ("Polly.Vicki", "Dies ist ein automatischer KI-Bericht."),
    "es-ES": ("Polly.Conchita", "Este es un informe automático de tu asistente de IA."),
}


def call_twiml(credentials: PhoneCredentials, call: PhoneCall) -> str:
    root = Element("Response")
    if call.mode == "report":
        voice, notice = _REPORT_VOICES[call.report_language]
        SubElement(root, "Say", voice=voice, language=call.report_language).text = notice
        SubElement(root, "Say", voice=voice, language=call.report_language).text = call.report
    else:
        SubElement(root, "Say").text = "This is an AI assistant. This call is transcribed."
        stream = SubElement(
            SubElement(root, "Connect"), "Stream", url=url(f"/media/{call.id}", websocket=True)
        )
        SubElement(stream, "Parameter", name="nonce", value=stream_nonce(credentials, call))
    SubElement(root, "Hangup")
    return tostring(root, encoding="unicode")


def transfer_twiml(number: str, remaining_seconds: int) -> str:
    if not NUMBER.fullmatch(number) or not 1 <= remaining_seconds <= 900:
        raise BadRequestError(message="The transfer target or remaining call time is invalid")
    root = Element("Response")
    SubElement(root, "Say").text = "Connecting you to a person."
    SubElement(
        SubElement(root, "Dial", timeLimit=str(remaining_seconds), timeout="20"), "Number"
    ).text = number
    SubElement(root, "Hangup")
    return tostring(root, encoding="unicode")


class PhoneProvider(Protocol):
    async def dial(
        self,
        credentials: PhoneCredentials,
        *,
        number: str,
        twiml: str,
        callback: str,
        cap_seconds: int,
    ) -> str: ...
    async def cap(self, credentials: PhoneCredentials, sid: str, seconds: int) -> None: ...
    async def transfer(
        self, credentials: PhoneCredentials, sid: str, *, number: str, seconds: int
    ) -> None: ...
    async def hangup(self, credentials: PhoneCredentials, sid: str) -> None: ...


class TwilioPhoneProvider:
    async def _post(
        self,
        auth: PhoneCredentials,
        *,
        sid: str | None,
        data: dict[str, str],
        allow_gone: bool = False,
    ) -> TwilioCallReceipt | None:
        if sid is not None and not SID.fullmatch(sid):
            raise BadRequestError(message="Invalid telephone call receipt")
        path = f"/{sid}.json" if sid else ".json"
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
                response = await client.post(
                    f"https://api.twilio.com/2010-04-01/Accounts/{auth.account}/Calls{path}",
                    auth=(auth.account, auth.token.get_secret_value()),
                    data=data,
                )
        except httpx.TransportError as exc:
            raise AcceptanceUnknown(
                message="Telephone provider acceptance is unknown; wait for its status callback"
            ) from exc
        if allow_gone and response.status_code == 404:
            return None
        if response.status_code >= 500:
            raise AcceptanceUnknown(
                message="Telephone provider acceptance is unknown; wait for its status callback"
            )
        if not response.is_success:
            raise ExternalServiceError(
                message="The telephone provider refused the request",
                details={"status": response.status_code},
            )
        if len(response.content) > 65536:
            raise AcceptanceUnknown(
                message="The telephone provider returned an oversized receipt; wait for its callback"
            )
        try:
            receipt = TwilioCallReceipt.model_validate_json(response.content)
        except ValidationError as exc:
            raise AcceptanceUnknown(
                message="The telephone provider returned an invalid receipt; wait for its callback"
            ) from exc
        if receipt.account_sid != auth.account or (sid is not None and receipt.sid != sid):
            raise AcceptanceUnknown(
                message="The telephone provider returned a mismatched receipt; wait for its callback"
            )
        return receipt

    async def dial(
        self,
        credentials: PhoneCredentials,
        *,
        number: str,
        twiml: str,
        callback: str,
        cap_seconds: int,
    ) -> str:
        if not NUMBER.fullmatch(number):
            raise BadRequestError(message="The contact needs a verified E.164 number")
        receipt = await self._post(
            credentials,
            sid=None,
            data={
                "To": number,
                "From": credentials.number,
                "Twiml": twiml,
                "StatusCallback": callback,
                "StatusCallbackMethod": "POST",
                "TimeLimit": str(cap_seconds),
                "Timeout": "30",
            },
        )
        assert receipt is not None
        return receipt.sid

    async def cap(self, credentials: PhoneCredentials, sid: str, seconds: int) -> None:
        await self._post(credentials, sid=sid, data={"TimeLimit": str(seconds)})

    async def transfer(
        self, credentials: PhoneCredentials, sid: str, *, number: str, seconds: int
    ) -> None:
        await self._post(credentials, sid=sid, data={"Twiml": transfer_twiml(number, seconds)})

    async def hangup(self, credentials: PhoneCredentials, sid: str) -> None:
        await self._post(credentials, sid=sid, data={"Status": "completed"}, allow_gone=True)
