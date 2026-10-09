"""Microsoft Graph, as one client every Microsoft 365 integration shares.

SharePoint sync was its first caller and wrote it as a private class; the
connected Microsoft account and the Outlook and calendar triggers built on it
(#1983, #1984, #1986) read the same API with the same throttling, so the
transport lives here and each caller keeps only what is its own - the shape of
the items it reads and the words it refuses in.

**Two kinds of credential, one client.** An Entra app registration
(`EntraAppSecret`) signs in with the client credentials flow and reads what its
*application* permissions allow - a sync source. A member's delegated token,
already refreshed by whoever holds the grant, reads what that member consented
to - a connected account. The client signs in for the first and renews it
shortly before expiry; the second it only spends, because the refresh token is
the vault's and never reaches this module.

**Two hosts, and the secret goes to one.** `login.microsoftonline.com` is sent
the app's secret and answers a token; `graph.microsoft.com` is sent the token. A
`@odata.nextLink` or a delta link is followed only when it leads back to Graph,
so an answer cannot steer the token anywhere else. Neither host is typed by
anybody, so no `PinnedAsyncClient` is needed.

**Throttling is an answer, not a failure.** Every request is retried on a 429,
a 5xx or a transport error, `_ATTEMPTS` times in all, honouring `Retry-After`. A
refusal (400, 401, 403) is not retried: asking again with the same credential
gets the same answer.

Microsoft's national clouds (US Government, China) have other hosts and are not
supported.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import aclosing
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import BaseModel, SecretStr, ValidationError

from app.core.exceptions import AppException, BadRequestError, ExternalServiceError, NotFoundError
from app.core.secret_kinds import EntraAppSecret

logger = logging.getLogger(__name__)

GRAPH = "https://graph.microsoft.com/v1.0"
GRAPH_ORIGIN = "https://graph.microsoft.com/"
LOGIN = "https://login.microsoftonline.com"
_APP_SCOPE = "https://graph.microsoft.com/.default"
_ATTEMPTS = 4
_MAX_RETRY_AFTER = 60.0
TRANSIENT = frozenset({429, 500, 502, 503, 504})
# An app token is renewed this many seconds before Graph would stop accepting
# it, so a request made just before expiry is not refused half-way through a sync.
_TOKEN_MARGIN = 300.0
_ERROR_CODE = re.compile(r"^[A-Za-z_]{1,64}$")


@dataclass(frozen=True)
class DelegatedToken:
    """A member's access token for Graph, refreshed by the grant that holds it."""

    access_token: SecretStr


@dataclass(frozen=True)
class Retry:
    """A transient answer: try again after `wait` seconds, or `None` for the local backoff."""

    wait: float | None


class ResyncRequired(Exception):
    """A delta link Graph no longer honours (HTTP 410): the caller has to read from scratch."""


class _Token(BaseModel):
    access_token: str
    expires_in: int


def retry_after(value: str | None) -> float | None:
    """Graph's `Retry-After`, which it sends in seconds, capped; `None` when absent."""
    stripped = (value or "").strip()
    return min(float(stripped), _MAX_RETRY_AFTER) if stripped.isdigit() else None


def error_code(response: httpx.Response) -> str | None:
    """Graph's own error code - `accessDenied`, `itemNotFound` - when it is one.

    A fixed vocabulary and the most useful word for troubleshooting, so it may
    reach a log or a refusal; the error's `message` is Graph's prose and does not.
    """
    try:
        body = response.json()
    except ValueError:
        return None
    error = body.get("error") if isinstance(body, dict) else None
    code = error.get("code") if isinstance(error, dict) else error
    return code if isinstance(code, str) and _ERROR_CODE.fullmatch(code) else None


def graph_link(value: str) -> str:
    """A link Graph answered with, refused unless it leads back to Graph."""
    if not value.startswith(GRAPH_ORIGIN):
        raise ExternalServiceError(
            message="Microsoft Graph answered a link to another host, so it was not followed."
        )
    return value


class GraphClient:
    """One session against Microsoft Graph: a credential, retries, and which hosts get what.

    A caller that reads a particular kind of item subclasses it for the item's
    shape and overrides :meth:`refused` for the advice its own reader can act
    on - an app registration is fixed in the Entra admin center, a member's
    grant by connecting again.
    """

    def __init__(
        self,
        credential: EntraAppSecret | DelegatedToken,
        client: httpx.AsyncClient,
        *,
        backoff: float,
    ) -> None:
        self._credential = credential
        self._client = client
        self._backoff = backoff
        self._token: str | None = None
        self._token_expires_at = 0.0

    async def aclose(self) -> None:
        await self._client.aclose()

    def refused(self, status: int, code: str | None, *, what: str) -> AppException:
        """What a 401 or a 403 from Graph is reported as, for `what` was asked for."""
        if status == 401:
            return BadRequestError(message=f"Microsoft Graph did not accept the token for {what}.")
        return BadRequestError(
            message=f"Microsoft Graph denied access to {what} ({code or 'HTTP 403'}).",
            details={"code": code},
        )

    async def get(self, url: str, *, what: str) -> dict[str, Any]:
        """GET a Graph URL and answer its JSON object.

        Raises:
            NotFoundError: Graph found nothing at `url` (404).
            BadRequestError: Graph refused the credential (401, 403, as worded by
                :meth:`refused`) or the request (400).
            ExternalServiceError: Graph stayed unavailable, or answered something unreadable.
            ResyncRequired: a delta link Graph no longer honours (410).
        """

        async def attempt() -> httpx.Response | Retry:
            response = await self._client.get(
                url, headers={"Authorization": f"Bearer {await self._bearer()}"}
            )
            if response.status_code in TRANSIENT:
                return Retry(retry_after(response.headers.get("retry-after")))
            return response

        response = await self.with_retries(attempt, what=what)
        status = response.status_code
        if status in (401, 403):
            raise self.refused(status, error_code(response), what=what)
        if status == 404:
            raise NotFoundError(message=f"Microsoft Graph found no {what}.")
        if status == 410:
            raise ResyncRequired
        if not 200 <= status < 300:
            raise ExternalServiceError(
                message=f"Microsoft Graph answered HTTP {status} for {what} ({error_code(response) or 'no code'}).",
                details={"status": status},
            )
        try:
            body = response.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            # The body is not quoted: it is Graph's, and it may echo the request.
            raise ExternalServiceError(
                message=f"Microsoft Graph answered {what} with a body the platform could not read."
            )
        return body

    async def pages(self, url: str, *, what: str) -> AsyncGenerator[dict[str, Any]]:
        """Every page of a Graph collection, following `@odata.nextLink` on Graph only."""
        next_url: str | None = url
        while next_url is not None:
            page = await self.get(next_url, what=what)
            if "value" not in page:
                raise ExternalServiceError(
                    message=f"Microsoft Graph answered {what} with an item, not a list."
                )
            yield page
            link = page.get("@odata.nextLink")
            next_url = graph_link(link) if isinstance(link, str) and link else None

    async def delta_link(self, url: str, *, what: str) -> str:
        """The delta link that ends a delta read from `url`."""
        async with aclosing(self.pages(url, what=what)) as pages:
            async for page in pages:
                link = page.get("@odata.deltaLink")
                if isinstance(link, str) and link:
                    return graph_link(link)
        raise ExternalServiceError(message=f"Microsoft Graph ended {what} without a delta link.")

    async def with_retries[T](self, attempt: Callable[[], Awaitable[T | Retry]], *, what: str) -> T:
        """Run `attempt` until it answers, a transient failure `_ATTEMPTS` times at most.

        Raises:
            ExternalServiceError: the last attempt was still transient.
        """
        number = 1
        while True:
            backoff = self._backoff * 2 ** (number - 1)
            try:
                outcome = await attempt()
            except httpx.TransportError as exc:
                if number == _ATTEMPTS:
                    raise ExternalServiceError(
                        message=f"Microsoft 365 could not be reached for {what} ({type(exc).__name__})."
                    ) from exc
                wait = backoff
            else:
                if not isinstance(outcome, Retry):
                    return outcome
                if number == _ATTEMPTS:
                    raise ExternalServiceError(
                        message=(
                            f"Microsoft 365 stayed unavailable or kept throttling {what} after "
                            f"{_ATTEMPTS} attempts."
                        )
                    )
                wait = backoff if outcome.wait is None else outcome.wait
            logger.info("Retrying %s after a transient failure (attempt %d)", what, number)
            await asyncio.sleep(wait)
            number += 1

    async def _bearer(self) -> str:
        """The token Graph is sent: the member's as given, or the app's, signed in for once.

        Raises:
            BadRequestError: Entra refused the tenant, the app or its secret.
            ExternalServiceError: Entra stayed unavailable.
        """
        credential = self._credential
        if isinstance(credential, DelegatedToken):
            return credential.access_token.get_secret_value()
        if self._token is not None and time.monotonic() < self._token_expires_at:
            return self._token
        form = {
            "grant_type": "client_credentials",
            "client_id": credential.client_id,
            "client_secret": credential.client_secret.get_secret_value(),
            "scope": _APP_SCOPE,
        }

        async def attempt() -> httpx.Response | Retry:
            response = await self._client.post(
                f"{LOGIN}/{credential.tenant_id}/oauth2/v2.0/token", data=form
            )
            if response.status_code in TRANSIENT:
                return Retry(retry_after(response.headers.get("retry-after")))
            return response

        response = await self.with_retries(attempt, what="signing in to Microsoft Entra")
        if response.status_code in (400, 401):
            code = error_code(response) or f"HTTP {response.status_code}"
            raise BadRequestError(
                message=(
                    f"Microsoft Entra refused the app registration's credentials ({code}). Check the "
                    "tenant id, the client id and the client secret in the Vault, and whether the "
                    "secret has expired."
                ),
                details={"code": error_code(response)},
            )
        if response.status_code != 200:
            raise ExternalServiceError(
                message=f"Microsoft Entra answered HTTP {response.status_code} when the app signed in.",
                details={"status": response.status_code},
            )
        try:
            token = _Token.model_validate_json(response.content)
        except ValidationError:
            raise ExternalServiceError(
                message="Microsoft Entra answered the sign-in with no usable token."
            ) from None
        self._token = token.access_token
        self._token_expires_at = time.monotonic() + max(token.expires_in - _TOKEN_MARGIN, 0.0)
        return self._token
