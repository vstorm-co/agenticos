"""`http.upload`: send one of the run's files to an HTTP endpoint.

The file is read from storage in chunks and streamed straight into the request
body, never held whole, and sent with the type its row recorded. The same
pinned transport, credential and origin rules as `http.request` apply. An
upload is a write, so it never follows a redirect - a far side that moved
answers with its `3xx`, and the step fails rather than send the file somewhere
it was not pointed at.

What a failure means for a retry follows `http.request`: a connection that
never opened sent nothing and is retryable, while one that sent the file and
got no answer is `Uncertain` unless an idempotency header lets the far side
recognise the retry.
"""

from __future__ import annotations

from typing import Literal

import httpx2
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext
from app.core.pinned_http import PinnedAsyncClient
from app.core.sanitize import UrlRefusedError
from app.services.workflow_execution import context
from app.workflows import files
from app.workflows.contracts.definition import RetryGuarantee
from app.workflows.contracts.io import FileRef
from app.workflows.contracts.results import Completed, Failed, NodeResult, Uncertain
from app.workflows.nodes._http import (
    HEADER_NAME,
    HttpAuth,
    HttpResponseOutput,
    auth_headers,
    auth_problems,
    check_headers,
    check_idempotency_header,
    credential,
    failed,
    is_http_url,
    read_capped,
    response_output,
)


class HttpUploadConfig(BaseModel):
    """Where to send the file, and how."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    method: Literal["POST", "PUT"] = "POST"
    url: str = Field(
        min_length=1,
        max_length=2048,
        json_schema_extra={"x-bindable": True},
        description="An http or https URL. May be bound from an earlier step.",
    )
    headers: dict[str, str] = Field(default_factory=dict, max_length=20)
    auth: HttpAuth = Field(default_factory=HttpAuth)
    timeout_seconds: float = Field(default=60.0, gt=0, le=300)
    max_response_bytes: int = Field(default=1_000_000, ge=1, le=10_000_000)
    idempotency_key_header: str | None = Field(
        default=None,
        pattern=HEADER_NAME,
        description=(
            "Send this step's stable operation key in this header (e.g. Idempotency-Key), "
            "so a retry the far side recognises is safe."
        ),
    )

    @field_validator("headers")
    @classmethod
    def _headers_are_ours_to_send(cls, headers: dict[str, str]) -> dict[str, str]:
        return check_headers(headers)

    @field_validator("idempotency_key_header")
    @classmethod
    def _key_header_is_ours_to_send(cls, name: str | None) -> str | None:
        return check_idempotency_header(name)


class HttpUploadInput(BaseModel):
    """The file to send, bound from an earlier step."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    file: FileRef


def retry_guarantee_for(config: BaseModel | None) -> RetryGuarantee:
    """`idempotent` only when the far side is handed a key to recognise a retry by."""
    if isinstance(config, HttpUploadConfig) and config.idempotency_key_header is not None:
        return "idempotent"
    return "at_least_once"


async def check_resources(
    db: AsyncSession, ctx: AuthContext, config: BaseModel
) -> list[tuple[str, str]]:
    """Refuse a credential the graph's author may not use, or of the wrong kind."""
    if not isinstance(config, HttpUploadConfig):
        return []
    return await auth_problems(db, ctx, config.auth)


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Stream the bound file to `config.url` and return what came back."""
    if not isinstance(config, HttpUploadConfig) or not isinstance(node_input, HttpUploadInput):
        return failed("REQUEST_NOT_CONFIGURED", "This upload has no URL or no file to send")
    if not is_http_url(config.url):
        return failed("URL_REFUSED", "The URL must be an http or https URL with a host")
    secret = await credential(config.auth, config.url)
    if isinstance(secret, Failed):
        return secret
    opened = await files.open_stream(node_input.file)
    if isinstance(opened, Failed):
        return opened
    stored, chunks = opened

    headers = dict(config.headers)
    headers["Content-Type"] = stored.content_type
    if secret is not None:
        headers.update(auth_headers(config.auth, secret))
    if config.idempotency_key_header is not None:
        headers[config.idempotency_key_header] = context.current().idempotency_key
    safe_to_retry = retry_guarantee_for(config) == "idempotent"

    try:
        async with PinnedAsyncClient(timeout=httpx2.Timeout(config.timeout_seconds)) as client:
            request = client.build_request(
                config.method, config.url, headers=headers, content=chunks
            )
            response = await client.send(request, stream=True)
            try:
                raw = await read_capped(response, config.max_response_bytes)
            finally:
                await response.aclose()
    except UrlRefusedError as exc:
        return failed("URL_REFUSED", str(exc))
    except (httpx2.ConnectError, httpx2.ConnectTimeout):
        return failed("HTTP_UNREACHABLE", "The server could not be reached", retryable=True)
    except httpx2.HTTPError:
        if safe_to_retry:
            return failed(
                "HTTP_NO_RESPONSE", "The file was sent and no response came back", retryable=True
            )
        return Uncertain(detail="The file was sent and no response came back")

    if raw is None:
        return failed(
            "RESPONSE_TOO_LARGE",
            f"The response is larger than {config.max_response_bytes} bytes",
            limit_bytes=config.max_response_bytes,
        )
    if not response.is_success:
        return failed(
            "HTTP_ERROR_STATUS",
            f"The server answered {response.status_code}",
            retryable=safe_to_retry
            and (response.status_code >= 500 or response.status_code == 429),
            status_code=response.status_code,
        )
    return Completed[HttpResponseOutput](output=response_output(response, raw, secret))
