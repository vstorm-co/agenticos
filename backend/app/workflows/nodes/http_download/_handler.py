"""`http.download`: fetch a file into the run, streamed and checked as bytes.

Every hop goes through `PinnedAsyncClient`, like `http.request`, and redirects
are followed here - a signed storage URL or a CDN usually answers with one - up
to `MAX_REDIRECTS`, each re-checked against the SSRF policy and the credential's
origins.

The body is counted as it arrives and refused past `max_bytes` whatever
`Content-Length` said, and nothing partial is stored. Its type is what its own
bytes say (`files.sniff`), never the response header, so a server calling HTML
an image cannot make it one. Only then is it stored, as a file of this run.

A `GET` repeats safely, but each attempt stores a new file, so the step is
`at_least_once`: a retry after a lost answer leaves a second copy.
"""

from __future__ import annotations

from urllib.parse import unquote, urlsplit

import httpx2
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext
from app.core.pinned_http import PinnedAsyncClient
from app.core.sanitize import UrlRefusedError
from app.workflows import files
from app.workflows.contracts.io import FileRef
from app.workflows.contracts.results import Completed, Failed, NodeResult
from app.workflows.nodes._http import (
    MAX_REDIRECTS,
    REDIRECT_STATUSES,
    HttpAuth,
    auth_headers,
    auth_problems,
    check_headers,
    credential,
    failed,
    is_http_url,
    read_capped,
)

MAX_DOWNLOAD_BYTES = 200_000_000
"""The largest file a download may store: two hundred megabytes."""


class HttpDownloadConfig(BaseModel):
    """What to fetch, and what to accept."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str = Field(
        min_length=1,
        max_length=2048,
        json_schema_extra={"x-bindable": True},
        description="An http or https URL. May be bound from an earlier step.",
    )
    headers: dict[str, str] = Field(default_factory=dict, max_length=20)
    auth: HttpAuth = Field(default_factory=HttpAuth)
    timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    max_bytes: int = Field(
        default=25_000_000,
        ge=1,
        le=MAX_DOWNLOAD_BYTES,
        description="Refuse a file larger than this, however the server describes it.",
    )
    expected_content_types: tuple[str, ...] = Field(
        default=(),
        max_length=20,
        description=(
            "Accept only these media types, as the file's own bytes show them - "
            "`application/pdf`, `image/png`. Empty accepts any."
        ),
    )
    filename: str | None = Field(
        default=None,
        max_length=255,
        description="What to call the stored file. Taken from the URL when left empty.",
    )

    @field_validator("headers")
    @classmethod
    def _headers_are_ours_to_send(cls, headers: dict[str, str]) -> dict[str, str]:
        return check_headers(headers)


class HttpDownloadOutput(BaseModel):
    """The stored file, what it turned out to be, and what the server answered."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    file: FileRef
    content_type: str = Field(description="What the file's own bytes show it is")
    filename: str | None = None
    status_code: int


async def check_resources(
    db: AsyncSession, ctx: AuthContext, config: BaseModel
) -> list[tuple[str, str]]:
    """Refuse a credential the graph's author may not use, or of the wrong kind."""
    if not isinstance(config, HttpDownloadConfig):
        return []
    return await auth_problems(db, ctx, config.auth)


def _filename_from(url: str) -> str | None:
    name = unquote(urlsplit(url).path.rsplit("/", 1)[-1])
    return name[:255] or None


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Fetch `config.url`, follow its redirects, and store what came back."""
    if not isinstance(config, HttpDownloadConfig):
        return failed("REQUEST_NOT_CONFIGURED", "This download has no URL configured")
    if not is_http_url(config.url):
        return failed("URL_REFUSED", "The URL must be an http or https URL with a host")
    secret = await credential(config.auth, config.url)
    if isinstance(secret, Failed):
        return secret
    headers = dict(config.headers)
    sent_auth = auth_headers(config.auth, secret) if secret is not None else {}
    headers.update(sent_auth)

    url = config.url
    try:
        async with PinnedAsyncClient(timeout=httpx2.Timeout(config.timeout_seconds)) as client:
            for _hop in range(MAX_REDIRECTS + 1):
                response = await client.send(
                    client.build_request("GET", url, headers=headers), stream=True
                )
                try:
                    location = response.headers.get("location")
                    if response.status_code in REDIRECT_STATUSES and location:
                        url = str(response.url.join(location))
                        if not is_http_url(url):
                            return failed(
                                "URL_REFUSED",
                                "The download was redirected to a URL it cannot follow",
                            )
                        if secret is not None and not secret.allows(url):
                            headers = {k: v for k, v in headers.items() if k not in sent_auth}
                        continue
                    if not response.is_success:
                        return failed(
                            "HTTP_ERROR_STATUS",
                            f"The server answered {response.status_code}",
                            retryable=response.status_code >= 500 or response.status_code == 429,
                            status_code=response.status_code,
                        )
                    data = await read_capped(response, config.max_bytes)
                finally:
                    await response.aclose()
                break
            else:
                return failed(
                    "TOO_MANY_REDIRECTS",
                    f"The download was redirected more than {MAX_REDIRECTS} times",
                )
    except UrlRefusedError as exc:
        return failed("URL_REFUSED", str(exc))
    except (httpx2.ConnectError, httpx2.ConnectTimeout):
        return failed("HTTP_UNREACHABLE", "The server could not be reached", retryable=True)
    except httpx2.HTTPError:
        return failed("HTTP_NO_RESPONSE", "The download started and did not finish", retryable=True)

    if data is None:
        return failed(
            "RESPONSE_TOO_LARGE",
            f"The file is larger than {config.max_bytes} bytes",
            limit_bytes=config.max_bytes,
        )
    content_type = files.sniff(data)
    if config.expected_content_types and content_type not in config.expected_content_types:
        return failed(
            "CONTENT_TYPE_MISMATCH",
            f"The file is {content_type}, not one of the types this step accepts",
            content_type=content_type,
            expected=list(config.expected_content_types),
        )
    filename = config.filename or _filename_from(url)
    stored = await files.save(data, content_type=content_type, filename=filename)
    return Completed[HttpDownloadOutput](
        output=HttpDownloadOutput(
            file=stored,
            content_type=content_type,
            filename=filename,
            status_code=response.status_code,
        )
    )
