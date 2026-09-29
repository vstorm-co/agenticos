"""`http.request`: call an HTTP API from a workflow, safely.

Every hop - the first request and each redirect followed - goes through
`PinnedAsyncClient`: the URL is checked against the deployment's SSRF policy and
dialled at the address that check approved, so a workflow cannot reach inside
the deployment's network, and a name that answers differently the second time
cannot redirect it there either.

A credential comes from the vault, never the config, and only as an
`http_credential` secret: a token sealed together with the origins it may be
sent to. The origin is checked on the URL about to be dialled - after binding,
since `url` may come from a run's input - and on every redirect, where a hop to
an origin the secret does not allow goes out without it. A response never
carries the secret back: `Set-Cookie` and the authentication headers are
dropped, and the token is scrubbed from what the body echoes.

The body is read streaming and refused past `max_response_bytes`, never
buffered whole and never silently truncated.

What a failure means for a retry is decided by what could have reached the
far side. A connection that never opened sent nothing and is a plain retryable
failure. A request that went out and got no answer is `Uncertain` for a write
without an idempotency header - the far side may have acted - and a retryable
failure otherwise. A non-2xx status is a failure by default, or, with
`on_error_status="complete"`, an ordinary output a `logic.if` can branch on.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

import httpx2
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext
from app.core.pinned_http import PinnedAsyncClient
from app.core.sanitize import UrlRefusedError
from app.services.workflow_execution import context
from app.workflows.contracts.definition import RetryGuarantee
from app.workflows.contracts.results import (
    Completed,
    Failed,
    NodeResult,
    Uncertain,
)
from app.workflows.nodes._http import (
    HEADER_NAME,
    MAX_REDIRECTS,
    REDIRECT_STATUSES,
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

__all__ = ["MAX_REDIRECTS", "HttpAuth", "HttpResponseOutput"]

logger = logging.getLogger(__name__)

HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]


class HttpRequestConfig(BaseModel):
    """Where to send the request, how, and what to accept back."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    method: HttpMethod = "GET"
    url: str = Field(
        min_length=1,
        max_length=2048,
        json_schema_extra={"x-bindable": True},
        description="An http or https URL. May be bound from an earlier step.",
    )
    headers: dict[str, str] = Field(default_factory=dict, max_length=20)
    auth: HttpAuth = Field(default_factory=HttpAuth)
    timeout_seconds: float = Field(default=15.0, gt=0, le=60)
    max_response_bytes: int = Field(default=1_000_000, ge=1, le=10_000_000)
    idempotency_key_header: str | None = Field(
        default=None,
        pattern=HEADER_NAME,
        description=(
            "Send this step's stable operation key in this header (e.g. Idempotency-Key), "
            "so a retry the far side recognises is safe."
        ),
    )
    on_error_status: Literal["fail", "complete"] = Field(
        default="fail",
        description="Whether a non-2xx status fails the step or is returned as its output.",
    )

    @field_validator("headers")
    @classmethod
    def _headers_are_ours_to_send(cls, headers: dict[str, str]) -> dict[str, str]:
        return check_headers(headers)

    @field_validator("idempotency_key_header")
    @classmethod
    def _key_header_is_ours_to_send(cls, name: str | None) -> str | None:
        return check_idempotency_header(name)


class HttpRequestInput(BaseModel):
    """The request body, bound from an earlier step. Sent as JSON."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    body: Any = None


def retry_guarantee_for(config: BaseModel | None) -> RetryGuarantee:
    """`idempotent` for a `GET` or a write sent with an idempotency header."""
    if isinstance(config, HttpRequestConfig) and (
        config.method == "GET" or config.idempotency_key_header is not None
    ):
        return "idempotent"
    return "at_least_once"


async def check_resources(
    db: AsyncSession, ctx: AuthContext, config: BaseModel
) -> list[tuple[str, str]]:
    """Refuse a credential the graph's author may not use, or of the wrong kind."""
    if not isinstance(config, HttpRequestConfig):
        return []
    return await auth_problems(db, ctx, config.auth)


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Send the request, follow a `GET`'s redirects, and return what came back."""
    if not isinstance(config, HttpRequestConfig):
        return failed("REQUEST_NOT_CONFIGURED", "This HTTP step has no request configured")
    if not is_http_url(config.url):
        return failed("URL_REFUSED", "The URL must be an http or https URL with a host")
    current = context.current()
    secret = await credential(config.auth, config.url)
    if isinstance(secret, Failed):
        return secret

    headers = dict(config.headers)
    if secret is not None:
        headers.update(auth_headers(config.auth, secret))
    if config.idempotency_key_header is not None:
        headers[config.idempotency_key_header] = current.idempotency_key
    body = node_input.body if isinstance(node_input, HttpRequestInput) else None
    content = None if body is None else json.dumps(body, ensure_ascii=False).encode()
    if content is not None:
        headers.setdefault("Content-Type", "application/json")
    safe_to_retry = retry_guarantee_for(config) == "idempotent"

    url = config.url
    auth_header_names = set(auth_headers(config.auth, secret)) if secret is not None else set()
    try:
        async with PinnedAsyncClient(timeout=httpx2.Timeout(config.timeout_seconds)) as client:
            for _hop in range(MAX_REDIRECTS + 1):
                request = client.build_request(config.method, url, headers=headers, content=content)
                response = await client.send(request, stream=True)
                try:
                    location = response.headers.get("location")
                    if (
                        config.method == "GET"
                        and response.status_code in REDIRECT_STATUSES
                        and location
                    ):
                        url = str(response.url.join(location))
                        if not is_http_url(url):
                            return failed(
                                "URL_REFUSED",
                                "The request was redirected to a URL it cannot follow",
                            )
                        if secret is not None and not secret.allows(url):
                            # A credential travels only where its secret allows.
                            headers = {
                                name: value
                                for name, value in headers.items()
                                if name not in auth_header_names
                            }
                        continue
                    raw = await read_capped(response, config.max_response_bytes)
                finally:
                    await response.aclose()
                break
            else:
                return failed(
                    "TOO_MANY_REDIRECTS",
                    f"The request was redirected more than {MAX_REDIRECTS} times",
                )
    except UrlRefusedError as exc:
        # Written in this repository and naming a host at most, never the URL.
        return failed("URL_REFUSED", str(exc))
    except (httpx2.ConnectError, httpx2.ConnectTimeout):
        return failed("HTTP_UNREACHABLE", "The server could not be reached", retryable=True)
    except httpx2.HTTPError:
        if safe_to_retry:
            return failed(
                "HTTP_NO_RESPONSE", "The request was sent and no response came back", retryable=True
            )
        return Uncertain(detail="The request was sent and no response came back")

    if raw is None:
        return failed(
            "RESPONSE_TOO_LARGE",
            f"The response is larger than {config.max_response_bytes} bytes",
            limit_bytes=config.max_response_bytes,
        )
    output = response_output(response, raw, secret)
    if response.is_success or config.on_error_status == "complete":
        return Completed[HttpResponseOutput](output=output)
    return failed(
        "HTTP_ERROR_STATUS",
        f"The server answered {response.status_code}",
        retryable=safe_to_retry and (response.status_code >= 500 or response.status_code == 429),
        status_code=response.status_code,
    )
