"""BlueBubbles' query-only authentication, isolated from request logs and errors.

The bridge accepts its server password only as a query parameter. The ordinary
HTTP client must keep a credential-free URL: request/response hooks, access traces
and HTTPStatusError expose that URL. Add the password only at the wire transport
and remove it before returning to the client, including on transport failures.
"""

import asyncio
import json
from typing import Literal
from uuid import UUID

import httpx
from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    SecretStr,
    ValidationError,
    field_validator,
)

from app.core.exceptions import ExternalServiceError

_CREDENTIAL = "agenticos_imessage_password"


class BridgeCredentials(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    bot_id: UUID
    webhook_secret: SecretStr | None = Field(default=None, min_length=8, max_length=255)
    server: AnyHttpUrl
    password: SecretStr = Field(min_length=1, max_length=2048)

    @field_validator("server")
    @classmethod
    def endpoint_only(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if (
            value.username
            or value.password
            or value.query
            or value.fragment
            or len(str(value)) > 500
        ):
            raise ValueError(
                "An iMessage bridge endpoint cannot contain credentials, query or fragment"
            )
        return value

    def encode(self) -> str:
        """An ephemeral adapter credential, never a stored connector config or API response."""
        return json.dumps(
            {
                "bot_id": str(self.bot_id),
                "server": str(self.server),
                "password": self.password.get_secret_value(),
                "webhook_secret": None
                if self.webhook_secret is None
                else self.webhook_secret.get_secret_value(),
            }
        )

    @classmethod
    def decode(cls, value: str) -> BridgeCredentials:
        try:
            return cls.model_validate_json(value)
        except ValidationError:
            raise ExternalServiceError(
                message="The iMessage bridge credential is invalid; review its endpoint and password"
            ) from None

    def url(self, path: str) -> str:
        if not path.startswith("/api/v1/"):
            raise ValueError("A bridge request must use its versioned API")
        return f"{str(self.server).rstrip('/')}{path}"

    def extensions(self) -> dict[str, object]:
        return {_CREDENTIAL: self.password}


class BridgeTransport(httpx.AsyncBaseTransport):
    """One pooled connection transport; credentials remain specific to each request."""

    def __init__(self, inner: httpx.AsyncBaseTransport | None = None) -> None:
        self._inner = (
            inner if inner is not None else httpx.AsyncHTTPTransport(retries=0, trust_env=False)
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        password = request.extensions.pop(_CREDENTIAL, None)
        if not isinstance(password, SecretStr) or not password.get_secret_value():
            raise ExternalServiceError(message="An iMessage request needs its bridge credential")
        wire = httpx.Request(
            request.method,
            request.url.copy_merge_params({"password": password.get_secret_value()}),
            headers=request.headers,
            stream=request.stream,
            extensions=request.extensions.copy(),
        )
        try:
            return await self._inner.handle_async_request(wire)
        finally:
            wire.url = request.url

    async def aclose(self) -> None:
        await self._inner.aclose()


MAX_METADATA_BYTES = 1024 * 1024


class BridgeClient:
    """Bounded bridge responses on one pooled, credential-safe HTTP client."""

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._http = httpx.AsyncClient(
            transport=BridgeTransport(transport),
            timeout=30.0,
            follow_redirects=False,
            trust_env=False,
        )

    async def close(self) -> None:
        await self._http.aclose()

    async def json_request[T: BaseModel](
        self,
        credentials: BridgeCredentials,
        method: Literal["GET", "POST", "DELETE"],
        path: str,
        schema: type[T],
        *,
        body: dict[str, JsonValue] | None = None,
        form: dict[str, str] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
    ) -> T:
        try:
            async with asyncio.timeout(30):
                async with self._http.stream(
                    method,
                    credentials.url(path),
                    json=body,
                    data=form,
                    files=files,
                    extensions=credentials.extensions(),
                ) as response:
                    response.raise_for_status()
                    content = await self._read(response, MAX_METADATA_BYTES)
        except httpx.HTTPError, TimeoutError:
            raise ExternalServiceError(
                message="The iMessage bridge is unavailable or refused the request"
            ) from None
        try:
            return schema.model_validate_json(content)
        except ValidationError:
            raise ExternalServiceError(
                message="The iMessage bridge returned an invalid response"
            ) from None

    async def download(self, credentials: BridgeCredentials, path: str, *, limit: int) -> bytes:
        try:
            async with asyncio.timeout(30):
                async with self._http.stream(
                    "GET", credentials.url(path), extensions=credentials.extensions()
                ) as response:
                    response.raise_for_status()
                    return await self._read(response, limit)
        except httpx.HTTPError, TimeoutError:
            raise ExternalServiceError(
                message="The iMessage bridge attachment is unavailable"
            ) from None

    @staticmethod
    async def _read(response: httpx.Response, limit: int) -> bytes:
        content = bytearray()
        async for chunk in response.aiter_bytes():
            if len(content) + len(chunk) > limit:
                raise ExternalServiceError(
                    message="The iMessage bridge response exceeds its size limit"
                )
            content.extend(chunk)
        return bytes(content)
