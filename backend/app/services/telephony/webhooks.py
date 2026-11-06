"""Authenticate bounded Twilio webhook forms before admitting or settling a call."""

from collections.abc import AsyncIterable
from urllib.parse import parse_qsl
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, AuthorizationError, BadRequestError, NotFoundError
from app.repositories import telephony as repo
from app.services.telephony.calls import PhoneCallService
from app.services.telephony.policy import PhonePolicyService
from app.services.telephony.provider import PhoneProvider, signature_ok, url
from app.services.telephony.runtime import _cleanup_credentials, cap_inbound, status_callback


async def read_body(chunks: AsyncIterable[bytes]) -> bytes:
    content = bytearray()
    async for chunk in chunks:
        if len(content) + len(chunk) > 16384:
            raise BadRequestError(message="Telephone webhook body is too large")
        content.extend(chunk)
    return bytes(content)


def parse_form(body: bytes) -> dict[str, str]:
    if len(body) > 16384:
        raise BadRequestError(message="Telephone webhook body is too large")
    try:
        pairs = parse_qsl(
            body.decode("utf-8"),
            keep_blank_values=True,
            max_num_fields=100,
            encoding="utf-8",
            errors="strict",
        )
    except (ValueError, UnicodeError) as exc:
        raise BadRequestError(message="Invalid telephone webhook form") from exc
    params = dict(pairs)
    if len(params) != len(pairs):
        raise BadRequestError(message="Duplicate telephone webhook fields are not accepted")
    return params


class PhoneWebhookService:
    def __init__(self, db: AsyncSession, *, provider: PhoneProvider | None = None) -> None:
        self.db = db
        self.provider = provider

    async def inbound(self, endpoint_id: UUID, body: bytes, signature: str) -> str:
        _, _, auth = await PhonePolicyService(self.db).load_endpoint(endpoint_id)
        params = parse_form(body)
        if not signature_ok(auth, url(f"/inbound/{endpoint_id}"), params, signature):
            raise AuthorizationError(message="Invalid telephone webhook signature")
        call = await PhoneCallService(self.db).inbound(endpoint_id, params)
        try:
            return await cap_inbound(self.db, call, provider=self.provider)
        except AppException:
            # Never connect an inbound media stream if its provider cap is unknown.
            return "<Response><Hangup /></Response>"

    async def status(
        self, call_id: UUID, body: bytes, signature: str, *, endpoint_id: UUID | None = None
    ) -> None:
        row = await repo.call(self.db, call_id)
        if row is None or (endpoint_id is not None and row.endpoint_id != endpoint_id):
            raise NotFoundError(message="Telephone receipt not found")
        auth = await _cleanup_credentials(self.db, row)
        params = parse_form(body)
        path = f"/status/{call_id}" if endpoint_id is None else f"/inbound-status/{endpoint_id}"
        if not signature_ok(auth, url(path), params, signature):
            raise AuthorizationError(message="Invalid telephone webhook signature")
        await status_callback(self.db, call_id, params)

    async def inbound_status(self, endpoint_id: UUID, body: bytes, signature: str) -> None:
        params = parse_form(body)
        row = await repo.call_by_sid(self.db, endpoint_id, params.get("CallSid", ""))
        if row is None:
            raise NotFoundError(message="Telephone receipt not found")
        await self.status(row.id, body, signature, endpoint_id=endpoint_id)
