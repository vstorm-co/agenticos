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
buffered whole and never silently truncated. A `GET` with `pagination` fetches
page after page the same way, collecting each page's items, and every page
together counts against that one limit.

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
from dataclasses import dataclass
from typing import Any, Literal

import httpx2
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext
from app.core.pinned_http import PinnedAsyncClient
from app.core.sanitize import UrlRefusedError
from app.core.secret_kinds import HttpCredentialSecret
from app.services.workflow_execution import context
from app.workflows.contracts.definition import RetryGuarantee
from app.workflows.contracts.results import (
    Completed,
    Failed,
    NodeResult,
    Uncertain,
)
from app.workflows.nodes import _expr
from app.workflows.nodes._http import (
    HEADER_NAME,
    MAX_REDIRECTS,
    QUERY_NAME,
    REDIRECT_STATUSES,
    HttpAuth,
    HttpResponseOutput,
    auth_headers,
    auth_problems,
    authorized_url,
    check_headers,
    check_idempotency_header,
    credential,
    failed,
    is_http_url,
    read_capped,
    response_output,
    with_query,
)

__all__ = ["MAX_REDIRECTS", "HttpAuth", "HttpResponseOutput"]

logger = logging.getLogger(__name__)

HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]


class HttpPagination(BaseModel):
    """How a `GET` fetches its next page, and when it stops.

    `next_url` follows a URL the response names, `cursor` sends back a cursor it
    names in the `param` query parameter, and `page` counts `param` up from
    `first_page`. Each is read with a JMESPath expression over the page's body.
    The items `items_path` finds on every page are collected, in order; paging
    stops when there is no next page, when a page has no items, or at
    `max_pages`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: Literal["none", "next_url", "cursor", "page"] = "none"
    items_path: str | None = Field(
        default=None,
        max_length=_expr.MAX_EXPRESSION_LENGTH,
        description="Where each page's items are, for example data or results.",
    )
    next_path: str | None = Field(
        default=None,
        max_length=_expr.MAX_EXPRESSION_LENGTH,
        description="For next_url and cursor: where the next page's URL or cursor is, "
        "for example links.next or meta.next_cursor.",
    )
    param: str | None = Field(
        default=None,
        pattern=QUERY_NAME,
        description="For cursor and page: the query parameter that carries it.",
    )
    first_page: int = Field(default=1, ge=0, le=1_000_000)
    max_pages: int = Field(default=5, ge=1, le=100, description="The most pages fetched.")

    @field_validator("items_path", "next_path")
    @classmethod
    def _checked(cls, expression: str | None) -> str | None:
        return None if expression is None else _expr.check(expression)

    @model_validator(mode="after")
    def _complete(self) -> HttpPagination:
        if self.mode == "none":
            return self
        if self.items_path is None:
            raise ValueError("Say where each page's items are")
        if self.mode in ("next_url", "cursor") and self.next_path is None:
            raise ValueError("Say where the next page is")
        if self.mode in ("cursor", "page") and self.param is None:
            raise ValueError("Name the query parameter that carries it")
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
    pagination: HttpPagination = Field(default_factory=HttpPagination)

    @model_validator(mode="after")
    def _pages_only_a_get(self) -> HttpRequestConfig:
        if self.pagination.mode != "none" and self.method != "GET":
            raise ValueError("Only a GET fetches pages")
        return self

    @field_validator("headers")
    @classmethod
    def _headers_are_ours_to_send(cls, headers: dict[str, str]) -> dict[str, str]:
        return check_headers(headers)

    @field_validator("idempotency_key_header")
    @classmethod
    def _key_header_is_ours_to_send(cls, name: str | None) -> str | None:
        return check_idempotency_header(name)


class HttpRequestOutput(HttpResponseOutput):
    """What came back - the last page's, when it paged - and every page's items."""

    items: list[Any] | None = Field(
        default=None, description="Every page's items, in order; null when it did not page"
    )
    pages: int = Field(default=1, description="How many pages were fetched")
    complete: bool = Field(
        default=True, description="False when it stopped at max_pages with more to fetch"
    )


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


@dataclass(frozen=True, slots=True)
class _Page:
    """One page as it came back, and the URL it came from once redirects settled."""

    url: str
    response: httpx2.Response
    raw: bytes


async def _fetch(
    client: PinnedAsyncClient,
    config: HttpRequestConfig,
    *,
    url: str,
    headers: dict[str, str],
    content: bytes | None,
    secret: HttpCredentialSecret | None,
    auth_header_names: set[str],
    limit: int,
) -> _Page | Failed:
    """One request - its redirects followed, for a `GET` - read up to `limit` bytes."""
    for _hop in range(MAX_REDIRECTS + 1):
        request = client.build_request(
            config.method,
            authorized_url(config.auth, secret, url),
            headers=headers,
            content=content,
        )
        response = await client.send(request, stream=True)
        try:
            location = response.headers.get("location")
            if config.method == "GET" and response.status_code in REDIRECT_STATUSES and location:
                url = str(httpx2.URL(url).join(location))
                if not is_http_url(url):
                    return failed(
                        "URL_REFUSED", "The request was redirected to a URL it cannot follow"
                    )
                if secret is not None and not secret.allows(url):
                    # A credential travels only where its secret allows.
                    headers = _without(headers, auth_header_names)
                continue
            raw = await read_capped(response, limit)
        finally:
            await response.aclose()
        if raw is None:
            return failed(
                "RESPONSE_TOO_LARGE",
                f"The response is larger than {config.max_response_bytes} bytes",
                limit_bytes=config.max_response_bytes,
            )
        return _Page(url=url, response=response, raw=raw)
    return failed(
        "TOO_MANY_REDIRECTS", f"The request was redirected more than {MAX_REDIRECTS} times"
    )


def _without(headers: dict[str, str], names: set[str]) -> dict[str, str]:
    return {name: value for name, value in headers.items() if name not in names}


def _items(pagination: HttpPagination, body: Any) -> list[Any] | Failed:
    """The items on one page: none when the path finds nothing, refused when it
    finds something that is not a list."""
    try:
        found = _expr.evaluate(str(pagination.items_path), body)
    except _expr.ExpressionError as exc:
        return failed("PAGE_ITEMS_UNREADABLE", str(exc))
    if found is None:
        return []
    if not isinstance(found, list):
        return failed("PAGE_ITEMS_NOT_A_LIST", "The items path does not find a list on this page")
    return found


def _next(
    pagination: HttpPagination, page: _Page, body: Any, *, base: str, number: int
) -> str | None:
    """The next page's URL, or None when the page names no next one."""
    if pagination.mode == "page":
        return with_query(base, str(pagination.param), str(number + 1))
    try:
        found = _expr.evaluate(str(pagination.next_path), body)
    except _expr.ExpressionError:
        return None
    if found is None or found == "":
        return None
    if pagination.mode == "cursor":
        return with_query(base, str(pagination.param), str(found))
    if not isinstance(found, str):
        return None
    following = str(httpx2.URL(page.url).join(found))
    return following if is_http_url(following) else None


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Send the request - each page of it, when it pages - and return what came back.

    Every page is dialled the way the first is: through the pinned client, with
    the credential only where its secret allows, and all of them together read
    no more than `max_response_bytes`.
    """
    if not isinstance(config, HttpRequestConfig):
        return failed("REQUEST_NOT_CONFIGURED", "This HTTP step has no request configured")
    if not is_http_url(config.url):
        return failed("URL_REFUSED", "The URL must be an http or https URL with a host")
    current = context.current()
    secret = await credential(config.auth, config.url)
    if isinstance(secret, Failed):
        return secret

    headers = dict(config.headers)
    auth_header_names = set(auth_headers(config.auth, secret)) if secret is not None else set()
    if secret is not None:
        headers.update(auth_headers(config.auth, secret))
    if config.idempotency_key_header is not None:
        headers[config.idempotency_key_header] = current.idempotency_key
    body = node_input.body if isinstance(node_input, HttpRequestInput) else None
    content = None if body is None else json.dumps(body, ensure_ascii=False).encode()
    if content is not None:
        headers.setdefault("Content-Type", "application/json")
    safe_to_retry = retry_guarantee_for(config) == "idempotent"

    pagination = config.pagination
    paging = pagination.mode != "none"
    number = pagination.first_page
    url = (
        with_query(config.url, str(pagination.param), str(number))
        if pagination.mode == "page"
        else config.url
    )
    items: list[Any] = []
    pages = 0
    read = 0
    complete = True
    try:
        async with PinnedAsyncClient(timeout=httpx2.Timeout(config.timeout_seconds)) as client:
            while True:
                allowed = secret is None or secret.allows(url)
                page = await _fetch(
                    client,
                    config,
                    url=url,
                    headers=headers if allowed else _without(headers, auth_header_names),
                    content=content,
                    secret=secret,
                    auth_header_names=auth_header_names,
                    limit=config.max_response_bytes - read,
                )
                if isinstance(page, Failed):
                    return page
                read += len(page.raw)
                pages += 1
                output = response_output(page.response, page.raw, secret)
                if not paging or not page.response.is_success:
                    break
                found = _items(pagination, output.body)
                if isinstance(found, Failed):
                    return found
                items.extend(found)
                following = (
                    _next(pagination, page, output.body, base=config.url, number=number)
                    if found
                    else None
                )
                if following is None:
                    break
                if pages >= pagination.max_pages:
                    complete = False
                    break
                url, number = following, number + 1
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

    result = HttpRequestOutput(
        **output.model_dump(), items=items if paging else None, pages=pages, complete=complete
    )
    if page.response.is_success or config.on_error_status == "complete":
        return Completed[HttpRequestOutput](output=result)
    status_code = page.response.status_code
    return failed(
        "HTTP_ERROR_STATUS",
        f"The server answered {status_code}",
        retryable=safe_to_retry and (status_code >= 500 or status_code == 429),
        status_code=status_code,
    )
