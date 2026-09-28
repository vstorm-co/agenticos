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

import base64
import json
import logging
import re
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

import httpx2
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext, Perm
from app.core.pinned_http import PinnedAsyncClient
from app.core.sanitize import UrlRefusedError
from app.core.secret_kinds import HttpCredentialSecret, SecretKind, unseal_secret
from app.core.vault import VaultScope
from app.db.models.organization_secret import OrganizationSecret
from app.db.session import get_worker_db_context
from app.repositories import organization_secret_repo
from app.services.access import SECRET, resolve_access
from app.services.workflow_execution import context
from app.workflows.contracts.definition import RetryGuarantee
from app.workflows.contracts.results import (
    Completed,
    Failed,
    NodeResult,
    Uncertain,
    WorkflowError,
)

logger = logging.getLogger(__name__)

HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]

MAX_REDIRECTS = 5
"""The most redirects a `GET` follows before it is refused."""

_HEADER_NAME = r"^[A-Za-z0-9!#$%&'*+.^_`|~-]{1,64}$"

# Headers the transport or the auth block owns. A configured one of these could
# smuggle a second credential past the origin check, or corrupt the request.
_RESERVED_HEADERS = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "host",
        "content-length",
        "transfer-encoding",
        "connection",
    }
)

# Never handed back in the output: a session a far side set, or how it wants to
# be authenticated to next.
_DROPPED_RESPONSE_HEADERS = frozenset(
    {"set-cookie", "set-cookie2", "authorization", "proxy-authenticate", "www-authenticate"}
)

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


class HttpAuth(BaseModel):
    """How the request authenticates, with a vault secret rather than a value."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["none", "bearer", "header", "basic"] = "none"
    secret_id: UUID | None = Field(
        default=None,
        json_schema_extra={"x-resource": "secret", "x-secret-kind": "http_credential"},
        description="An HTTP credential from the vault, bound to the origins it may be sent to.",
    )
    header_name: str | None = Field(
        default=None,
        pattern=_HEADER_NAME,
        description="For `header`: the header the token is sent in, e.g. X-Api-Key.",
    )

    @model_validator(mode="after")
    def _consistent(self) -> HttpAuth:
        if self.kind == "none":
            if self.secret_id is not None or self.header_name is not None:
                raise ValueError("Without authentication, name no secret and no header")
            return self
        if self.secret_id is None:
            raise ValueError("Choose the credential to send")
        if self.kind == "header" and self.header_name is None:
            raise ValueError("Name the header the token is sent in")
        if self.header_name is not None and self.header_name.lower() in _RESERVED_HEADERS:
            raise ValueError(f"{self.header_name} cannot carry a credential here")
        return self


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
        pattern=_HEADER_NAME,
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
        for name, value in headers.items():
            if not _is_header_name(name):
                raise ValueError(f"{name!r} is not a header name")
            if name.lower() in _RESERVED_HEADERS:
                raise ValueError(f"{name} cannot be set here")
            if len(value) > 1024 or "\n" in value or "\r" in value:
                raise ValueError(f"The value of {name} is too long or spans lines")
        return headers


def _is_header_name(name: str) -> bool:
    """Whether `name` is a token RFC 9110 allows as a field name."""
    return re.fullmatch(_HEADER_NAME, name) is not None


class HttpRequestInput(BaseModel):
    """The request body, bound from an earlier step. Sent as JSON."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    body: Any = None


class HttpResponseOutput(BaseModel):
    """What came back: the status, the safe headers, and the body."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status_code: int
    headers: dict[str, str]
    body: Any = Field(description="Parsed JSON when the response is JSON, else the text")


def retry_guarantee_for(config: BaseModel | None) -> RetryGuarantee:
    """`idempotent` for a `GET` or a write sent with an idempotency header."""
    if isinstance(config, HttpRequestConfig) and (
        config.method == "GET" or config.idempotency_key_header is not None
    ):
        return "idempotent"
    return "at_least_once"


async def _usable_secret(
    db: AsyncSession, auth: AuthContext, secret_id: UUID
) -> OrganizationSecret | None:
    row = await organization_secret_repo.get(db, secret_id, organization_id=auth.organization_id)
    if row is None or row.kind != SecretKind.HTTP_CREDENTIAL.value:
        return None
    if not await resolve_access(db, auth, row, Perm.SECRETS_VIEW, resource_type=SECRET):
        return None
    return row


async def check_resources(
    db: AsyncSession, ctx: AuthContext, config: BaseModel
) -> list[tuple[str, str]]:
    """Refuse a credential the graph's author may not use, or of the wrong kind."""
    if not isinstance(config, HttpRequestConfig) or config.auth.secret_id is None:
        return []
    if await _usable_secret(db, ctx, config.auth.secret_id) is None:
        return [
            (
                "auth.secret_id",
                "This is not an HTTP credential you can use - add one in the vault "
                "with the origins it may be sent to",
            )
        ]
    return []


def _is_http_url(url: str) -> bool:
    """An `http`/`https` URL with a host - anything else is refused before dialling."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.hostname)


def _failed(code: str, message: str, *, retryable: bool = False, **details: Any) -> Failed:
    return Failed(
        error=WorkflowError(code=code, message=message, details=details, retryable=retryable)
    )


def _auth_headers(auth: HttpAuth, secret: HttpCredentialSecret) -> dict[str, str]:
    token = secret.token.get_secret_value()
    if auth.kind == "bearer":
        return {"Authorization": f"Bearer {token}"}
    if auth.kind == "basic":
        pair = f"{secret.username or ''}:{token}".encode()
        return {"Authorization": f"Basic {base64.b64encode(pair).decode()}"}
    return {str(auth.header_name): token}


def _scrub(text: str, secret: HttpCredentialSecret | None) -> str:
    if secret is None:
        return text
    token = secret.token.get_secret_value()
    return text.replace(token, "[redacted]") if token else text


def _output(
    response: httpx2.Response, raw: bytes, secret: HttpCredentialSecret | None
) -> HttpResponseOutput:
    headers = {
        name.lower(): _scrub(value, secret)
        for name, value in response.headers.items()
        if name.lower() not in _DROPPED_RESPONSE_HEADERS
    }
    text = _scrub(raw.decode(response.encoding or "utf-8", errors="replace"), secret)
    body: Any = text
    if "json" in response.headers.get("content-type", "").lower():
        try:
            body = json.loads(text)
        except json.JSONDecodeError:
            body = text
    return HttpResponseOutput(status_code=response.status_code, headers=headers, body=body)


async def _read_capped(response: httpx2.Response, limit: int) -> bytes | None:
    """The body, or `None` once it grows past `limit` - never buffered whole."""
    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if size > limit:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Send the request, follow a `GET`'s redirects, and return what came back."""
    if not isinstance(config, HttpRequestConfig):
        return _failed("REQUEST_NOT_CONFIGURED", "This HTTP step has no request configured")
    if not _is_http_url(config.url):
        return _failed("URL_REFUSED", "The URL must be an http or https URL with a host")
    current = context.current()
    secret: HttpCredentialSecret | None = None
    if config.auth.secret_id is not None:
        async with get_worker_db_context() as db:
            row = await _usable_secret(db, current.auth, config.auth.secret_id)
        if row is None:
            return _failed(
                "SECRET_NOT_USABLE",
                "The credential this step sends is gone, of the wrong kind, or no longer usable",
            )
        opened = unseal_secret(
            row.sealed_secret,
            kind=SecretKind.HTTP_CREDENTIAL,
            scope=VaultScope.organization(current.organization_id),
            key_version=row.key_version,
        )
        if not isinstance(opened, HttpCredentialSecret):
            # `unseal_secret` already refuses an envelope whose kind is not the
            # row's; this only narrows the union for the type checker.
            raise TypeError("An http_credential row opened as another kind")
        secret = opened
        if not secret.allows(config.url):
            return _failed(
                "SECRET_ORIGIN_DENIED",
                "This credential may not be sent to the URL this step calls",
            )

    headers = dict(config.headers)
    if secret is not None:
        headers.update(_auth_headers(config.auth, secret))
    if config.idempotency_key_header is not None:
        headers[config.idempotency_key_header] = current.idempotency_key
    body = node_input.body if isinstance(node_input, HttpRequestInput) else None
    content = None if body is None else json.dumps(body, ensure_ascii=False).encode()
    if content is not None:
        headers.setdefault("Content-Type", "application/json")
    safe_to_retry = retry_guarantee_for(config) == "idempotent"

    url = config.url
    auth_header_names = set(_auth_headers(config.auth, secret)) if secret is not None else set()
    try:
        async with PinnedAsyncClient(timeout=httpx2.Timeout(config.timeout_seconds)) as client:
            for _hop in range(MAX_REDIRECTS + 1):
                request = client.build_request(config.method, url, headers=headers, content=content)
                response = await client.send(request, stream=True)
                try:
                    location = response.headers.get("location")
                    if (
                        config.method == "GET"
                        and response.status_code in _REDIRECT_STATUSES
                        and location
                    ):
                        url = str(response.url.join(location))
                        if not _is_http_url(url):
                            return _failed(
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
                    raw = await _read_capped(response, config.max_response_bytes)
                finally:
                    await response.aclose()
                break
            else:
                return _failed(
                    "TOO_MANY_REDIRECTS",
                    f"The request was redirected more than {MAX_REDIRECTS} times",
                )
    except UrlRefusedError as exc:
        # Written in this repository and naming a host at most, never the URL.
        return _failed("URL_REFUSED", str(exc))
    except (httpx2.ConnectError, httpx2.ConnectTimeout):
        return _failed("HTTP_UNREACHABLE", "The server could not be reached", retryable=True)
    except httpx2.HTTPError:
        if safe_to_retry:
            return _failed(
                "HTTP_NO_RESPONSE", "The request was sent and no response came back", retryable=True
            )
        return Uncertain(detail="The request was sent and no response came back")

    if raw is None:
        return _failed(
            "RESPONSE_TOO_LARGE",
            f"The response is larger than {config.max_response_bytes} bytes",
            limit_bytes=config.max_response_bytes,
        )
    output = _output(response, raw, secret)
    if response.is_success or config.on_error_status == "complete":
        return Completed[HttpResponseOutput](output=output)
    return _failed(
        "HTTP_ERROR_STATUS",
        f"The server answered {response.status_code}",
        retryable=safe_to_retry and (response.status_code >= 500 or response.status_code == 429),
        status_code=response.status_code,
    )
