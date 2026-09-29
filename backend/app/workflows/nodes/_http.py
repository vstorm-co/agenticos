"""What every HTTP step shares: the URL check, the headers, the credential.

`http.request`, `http.download` and `http.upload` all dial through
`PinnedAsyncClient`, walk redirects themselves and send a vault credential only
to the origins it is sealed for. The rules for each of those live here once, so
the three steps cannot drift into refusing different things.
"""

from __future__ import annotations

import base64
import json
import re
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

import httpx2
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext, Perm
from app.core.secret_kinds import HttpCredentialSecret, SecretKind, unseal_kind
from app.core.vault import VaultScope
from app.db.models.organization_secret import OrganizationSecret
from app.db.session import get_worker_db_context
from app.repositories import organization_secret_repo
from app.services.access import SECRET, resolve_access
from app.services.workflow_execution import context
from app.workflows.contracts.results import Failed, WorkflowError

MAX_REDIRECTS = 5
"""The most redirects a step follows before it is refused."""

REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})

HEADER_NAME = r"^[A-Za-z0-9!#$%&'*+.^_`|~-]{1,64}$"

# Headers the transport or the auth block owns. A configured one of these could
# smuggle a second credential past the origin check, or corrupt the request.
RESERVED_HEADERS = frozenset(
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
        pattern=HEADER_NAME,
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
        if self.header_name is not None and self.header_name.lower() in RESERVED_HEADERS:
            raise ValueError(f"{self.header_name} cannot carry a credential here")
        return self


def check_headers(headers: dict[str, str]) -> dict[str, str]:
    """`headers`, refused when one is not a header, is reserved, or spans lines."""
    for name, value in headers.items():
        if re.fullmatch(HEADER_NAME, name) is None:
            raise ValueError(f"{name!r} is not a header name")
        if name.lower() in RESERVED_HEADERS:
            raise ValueError(f"{name} cannot be set here")
        if len(value) > 1024 or "\n" in value or "\r" in value:
            raise ValueError(f"The value of {name} is too long or spans lines")
    return headers


def check_idempotency_header(name: str | None) -> str | None:
    """`name`, refused when it is a header the transport or the credential owns:
    the operation key written into it would replace what that header carries."""
    if name is not None and name.lower() in RESERVED_HEADERS:
        raise ValueError(f"{name} cannot carry the operation key")
    return name


def is_http_url(url: str) -> bool:
    """An `http`/`https` URL with a host - anything else is refused before dialling."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.hostname)


def failed(code: str, message: str, *, retryable: bool = False, **details: Any) -> Failed:
    return Failed(
        error=WorkflowError(code=code, message=message, details=details, retryable=retryable)
    )


async def usable_secret(
    db: AsyncSession, auth: AuthContext, secret_id: UUID
) -> OrganizationSecret | None:
    row = await organization_secret_repo.get(db, secret_id, organization_id=auth.organization_id)
    if row is None or row.kind != SecretKind.HTTP_CREDENTIAL.value:
        return None
    if not await resolve_access(db, auth, row, Perm.SECRETS_VIEW, resource_type=SECRET):
        return None
    return row


async def auth_problems(
    db: AsyncSession, ctx: AuthContext, auth: HttpAuth
) -> list[tuple[str, str]]:
    """Refuse a credential the graph's author may not use, or of the wrong kind."""
    if auth.secret_id is None or await usable_secret(db, ctx, auth.secret_id) is not None:
        return []
    return [
        (
            "auth.secret_id",
            "This is not an HTTP credential you can use - add one in the vault "
            "with the origins it may be sent to",
        )
    ]


def auth_headers(auth: HttpAuth, secret: HttpCredentialSecret) -> dict[str, str]:
    token = secret.token.get_secret_value()
    if auth.kind == "bearer":
        return {"Authorization": f"Bearer {token}"}
    if auth.kind == "basic":
        pair = f"{secret.username or ''}:{token}".encode()
        return {"Authorization": f"Basic {base64.b64encode(pair).decode()}"}
    return {str(auth.header_name): token}


async def credential(auth: HttpAuth, url: str) -> HttpCredentialSecret | Failed | None:
    """The secret this step sends to `url`, unsealed - or why it may not send one.

    `None` when the step sends no credential. Read again on every run, so a
    secret deleted, narrowed or unshared since publishing stops being sent.
    """
    if auth.secret_id is None:
        return None
    current = context.current()
    async with get_worker_db_context() as db:
        row = await usable_secret(db, current.auth, auth.secret_id)
    if row is None:
        return failed(
            "SECRET_NOT_USABLE",
            "The credential this step sends is gone, of the wrong kind, or no longer usable",
        )
    secret = unseal_kind(
        row.sealed_secret,
        model=HttpCredentialSecret,
        scope=VaultScope.organization(current.organization_id),
        key_version=row.key_version,
    )
    if not secret.allows(url):
        return failed(
            "SECRET_ORIGIN_DENIED", "This credential may not be sent to the URL this step calls"
        )
    return secret


# Never handed back in an output: a session a far side set, or how it wants to be
# authenticated to next.
_DROPPED_RESPONSE_HEADERS = frozenset(
    {"set-cookie", "set-cookie2", "authorization", "proxy-authenticate", "www-authenticate"}
)


class HttpResponseOutput(BaseModel):
    """What came back: the status, the safe headers, and the body."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status_code: int
    headers: dict[str, str]
    body: Any = Field(description="Parsed JSON when the response is JSON, else the text")


def _scrub(text: str, secret: HttpCredentialSecret | None) -> str:
    """`text` with the credential removed in every form this step sent it: the
    token itself, and the base64 `username:token` pair a Basic header carries,
    which does not contain the token as it was stored."""
    if secret is None:
        return text
    token = secret.token.get_secret_value()
    pair = base64.b64encode(f"{secret.username or ''}:{token}".encode()).decode()
    for form in (pair, token):
        text = text.replace(form, "[redacted]")
    return text


def response_output(
    response: httpx2.Response, raw: bytes, secret: HttpCredentialSecret | None
) -> HttpResponseOutput:
    """A response as a step hands it on, with nothing of the credential in it."""
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


async def read_capped(response: httpx2.Response, limit: int) -> bytes | None:
    """The body, or `None` once it grows past `limit` - never buffered whole."""
    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if size > limit:
            return None
        chunks.append(chunk)
    return b"".join(chunks)
