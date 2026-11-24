"""Bounded calls to the operator-configured native runtime, never to provider OAuth."""

import json
from base64 import b64encode
from collections.abc import Sequence
from typing import Literal
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from app.core.claude_subscription import (
    ClaudeSubscriptionImage,
    ClaudeSubscriptionModel,
    ClaudeSubscriptionOwner,
    ClaudeSubscriptionThinking,
)
from app.core.config import settings
from app.core.exceptions import (
    BadRequestError,
    ConfigurationError,
    ExternalServiceError,
)
from app.schemas.claude_subscription import ClaudeSubscriptionRead

_MAX_REQUEST_BYTES = 1024 * 1024
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_ERRORS = {
    "CLAUDE_ACCESS_DENIED": (403, "This Claude connection is unavailable to the current user"),
    "CLAUDE_INVALID_REQUEST": (422, "The Claude runtime could not accept this request"),
    "CLAUDE_BUSY": (409, "Your Claude connection is busy; try again when its current request ends"),
    "CLAUDE_CAPACITY": (429, "The Claude runtime is busy; try again shortly"),
    "CLAUDE_SIGN_IN_REQUIRED": (409, "Connect your Claude subscription in AI connections"),
    "CLAUDE_LOGIN_STALE": (409, "This Claude sign-in is no longer active; start sign-in again"),
    "CLAUDE_LOGIN_NOT_READY": (
        409,
        "The Claude sign-in is still starting; wait for the sign-in link",
    ),
    "CLAUDE_INVALID_CODE": (422, "The sign-in code was not accepted; check the code and try again"),
    "CLAUDE_LOGIN_FAILED": (502, "Claude sign-in did not complete; start sign-in again"),
    "CLAUDE_LOGIN_TIMEOUT": (408, "Claude sign-in expired; start sign-in again"),
    "CLAUDE_DISCONNECT_FAILED": (502, "Claude could not sign out; try again"),
    "CLAUDE_REQUEST_FAILED": (502, "Claude did not complete this request; try again shortly"),
    "CLAUDE_REQUEST_TIMEOUT": (504, "Claude took too long to complete this request"),
    "CLAUDE_REQUEST_CANCELLED": (499, "The Claude request was cancelled"),
    "CLAUDE_OUTPUT_INVALID": (502, "Claude returned an invalid agent response"),
    "CLAUDE_STORAGE_LIMIT": (429, "This Claude connection has reached its runtime storage limit"),
    "CLAUDE_RUNTIME_UNAVAILABLE": (503, "The Claude runtime is unavailable; try again shortly"),
}


class ClaudeRuntimeError(ExternalServiceError):
    """An allowlisted native failure with no process output or caller data."""

    def __init__(self, code: str) -> None:
        status_code, message = _ERRORS[code]
        super().__init__(message=message, code=code)
        self.status_code = status_code


class ClaudeUsage(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cache_read_input_tokens: int = Field(ge=0)
    cache_creation_input_tokens: int = Field(ge=0)


class ClaudeInference(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    structured_output: dict[str, JsonValue]
    usage: ClaudeUsage
    model: str = Field(min_length=1, max_length=255)


class ClaudeSubscriptionRuntime:
    """Server-only transport; owner identity comes from an authenticated application context.

    The native process owns the provider login and its storage. The backend sends
    only an owner identity, a short-lived login code, or an inference request.
    Redirects are refused so the service key cannot follow an upstream response.
    """

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    @property
    def configured(self) -> bool:
        return bool(settings.CLAUDE_SUBSCRIPTION_URL and settings.CLAUDE_SUBSCRIPTION_SERVICE_KEY)

    async def status(self, owner: ClaudeSubscriptionOwner) -> ClaudeSubscriptionRead:
        if not self.configured:
            return ClaudeSubscriptionRead(available=False)
        return await self._state("status", owner)

    async def login(self, owner: ClaudeSubscriptionOwner) -> ClaudeSubscriptionRead:
        return await self._state("login", owner)

    async def code(
        self, owner: ClaudeSubscriptionOwner, *, login_id: UUID, code: str
    ) -> ClaudeSubscriptionRead:
        return await self._state("login/code", owner, {"login_id": str(login_id), "code": code})

    async def cancel(
        self, owner: ClaudeSubscriptionOwner, *, login_id: UUID
    ) -> ClaudeSubscriptionRead:
        return await self._state("login/cancel", owner, {"login_id": str(login_id)})

    async def disconnect(self, owner: ClaudeSubscriptionOwner) -> ClaudeSubscriptionRead:
        return await self._state("disconnect", owner)

    async def infer(
        self,
        owner: ClaudeSubscriptionOwner,
        *,
        model: ClaudeSubscriptionModel,
        prompt: str,
        output_schema: dict[str, JsonValue],
        max_output_tokens: int | None = None,
        images: Sequence[ClaudeSubscriptionImage] = (),
        thinking: ClaudeSubscriptionThinking | None = None,
    ) -> ClaudeInference:
        if len(prompt.encode("utf-8")) > 800_000:
            raise BadRequestError(
                message="This conversation is too large for the Claude subscription connection"
            )
        payload: dict[str, JsonValue] = {
            **owner.payload(),
            "model": model,
            "prompt": prompt,
            "output_schema": output_schema,
        }
        if max_output_tokens is not None:
            payload["max_output_tokens"] = max_output_tokens
        if thinking is not None:
            payload["thinking"] = thinking
        if images:
            if sum((len(image.data) + 2) // 3 * 4 for image in images) > _MAX_REQUEST_BYTES:
                raise BadRequestError(message="The Claude subscription request is too large")
            payload["images"] = [
                {"media_type": image.media_type, "data": b64encode(image.data).decode("ascii")}
                for image in images
            ]
        result = await self._post("infer", payload, timeout=610)
        try:
            return ClaudeInference.model_validate_json(result)
        except ValidationError:
            raise ExternalServiceError(
                message="The Claude runtime returned an invalid model response"
            ) from None

    async def _state(
        self,
        action: Literal["status", "login", "login/code", "login/cancel", "disconnect"],
        owner: ClaudeSubscriptionOwner,
        extra: dict[str, JsonValue] | None = None,
    ) -> ClaudeSubscriptionRead:
        result = await self._post(action, {**owner.payload(), **(extra or {})}, timeout=30)
        try:
            state = ClaudeSubscriptionRead.model_validate_json(result)
        except ValidationError:
            raise ExternalServiceError(
                message="The Claude runtime returned an invalid connection state"
            ) from None
        if state.error_code is not None and state.error_code not in {
            *_ERRORS,
            "CLAUDE_LOGIN_CANCELLED",
        }:
            raise ExternalServiceError(
                message="The Claude runtime returned an invalid connection state"
            )
        return state

    async def _post(self, action: str, payload: dict[str, JsonValue], *, timeout: float) -> bytes:
        url, key = settings.CLAUDE_SUBSCRIPTION_URL, settings.CLAUDE_SUBSCRIPTION_SERVICE_KEY
        if not url or not key:
            raise ConfigurationError(
                message="Claude subscription connections are not configured on this deployment",
                code="CLAUDE_NOT_CONFIGURED",
            )
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(body) > _MAX_REQUEST_BYTES:
            raise BadRequestError(
                message="This request is too large for the Claude subscription connection"
            )
        try:
            async with (
                httpx.AsyncClient(
                    base_url=url,
                    timeout=httpx.Timeout(timeout, connect=10),
                    follow_redirects=False,
                    transport=self._transport,
                ) as client,
                client.stream(
                    "POST",
                    f"/v1/{action}",
                    content=body,
                    headers={
                        "Content-Type": "application/json",
                        "X-Claude-Runtime-Key": key.get_secret_value(),
                    },
                ) as response,
            ):
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > _MAX_RESPONSE_BYTES:
                        raise ExternalServiceError(
                            message="The Claude runtime returned an oversized response"
                        )
                if response.status_code != 200:
                    self._raise_failure(bytes(data))
                return bytes(data)
        except httpx.HTTPError:
            raise ExternalServiceError(
                message="The Claude subscription connection is unavailable; try again shortly",
                code="CLAUDE_UNAVAILABLE",
            ) from None

    @staticmethod
    def _raise_failure(body: bytes) -> None:
        try:
            payload = json.loads(body)
        except ValueError, UnicodeDecodeError:
            payload = None
        error = payload.get("error") if isinstance(payload, dict) else None
        code = error.get("code") if isinstance(error, dict) else None
        if isinstance(code, str) and code in _ERRORS:
            raise ClaudeRuntimeError(code)
        raise ExternalServiceError(
            message="The Claude subscription request did not complete; reconnect or try again shortly",
            code="CLAUDE_RUNTIME_FAILED",
        )
