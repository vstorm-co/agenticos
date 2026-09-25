"""SharePoint and OneDrive sync connector: one document library, or a folder in it, read through Microsoft Graph.

**One connector for both, addressed by the site.** A SharePoint document library
and a OneDrive are both *drives* in Microsoft Graph, and a OneDrive for Business
is itself a site - `https://contoso-my.sharepoint.com/personal/jane_contoso_com`.
So a source names a site URL, optionally a library in it and a folder in that,
and the same code reads a team site and a person's OneDrive.

**The credential's reach is the source's reach.** The source signs in as a
Microsoft Entra app registration (`EntraAppSecret`), with the client credentials
flow, and reads whatever the app's *application* permissions allow. Those are
consented by an administrator, usually tenant-wide: `Files.Read.All` reads every
drive in the organization, and a source pointed at an `org` collection with it
publishes the company's whole document estate to everyone holding
`collections:view`. `Sites.Selected`, granted on the one site, is the scope to
use. Nothing here can tell which was granted - a token does not say - so the
setup documentation is where that decision is made
(`docs/howto/configure-sync-sources.md#sharepoint-and-onedrive-setup`).

**The change signal is Graph's delta.** `remote_version` answers the drive's
delta link. The next run asks Graph what changed since that link and, when the
answer is nothing, the sync stops before listing or downloading a thing. Graph
supports delta only on a drive's root in SharePoint and OneDrive for Business,
and its items carry no path there, so a change anywhere in the library - inside
the configured folder or not - makes the next run list the folder again. What it
lists it then downloads and hashes, and an unchanged file is skipped before it
is embedded (#990).

**Three hosts, and the token goes to two.** `login.microsoftonline.com` issues
the token, `graph.microsoft.com` is asked with it, and a file's bytes come from
the pre-authenticated `*.sharepoint.com` URL Graph hands back for it, fetched
without the token. A `@odata.nextLink` or a delta link is followed only on Graph.
None of the three is typed by a source's editor - the site URL only ever becomes
part of a Graph path - so there is no address for a tenant to aim inside the
deployment's network, and no `PinnedAsyncClient` is needed.

Microsoft's national clouds (US Government, China) have other hosts and are not
supported.
"""

import asyncio
import logging
import re
import time
from collections import deque
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import aclosing
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from pathlib import Path, PurePosixPath
from typing import ClassVar
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator

from app.core.config import settings
from app.core.exceptions import AppException, BadRequestError, ExternalServiceError, NotFoundError
from app.core.secret_kinds import EntraAppSecret, SecretKind, StorableSecret
from app.services.rag.connectors import (
    BaseSyncConnector,
    ConfigRefusal,
    ConnectorConfig,
    RemoteFile,
    RemoteListing,
    WithdrawnFile,
)

logger = logging.getLogger(__name__)

GRAPH = "https://graph.microsoft.com/v1.0"
LOGIN = "https://login.microsoftonline.com"
_GRAPH_ORIGIN = "https://graph.microsoft.com/"
_SCOPE = "https://graph.microsoft.com/.default"
_TIMEOUT = httpx.Timeout(30.0)
_ATTEMPTS = 4
_MAX_RETRY_AFTER = 60.0
_TRANSIENT = frozenset({429, 500, 502, 503, 504})
_REDIRECTS = frozenset({301, 302, 303, 307, 308})
_MAX_REDIRECTS = 3
# A token is renewed this many seconds before Graph would stop accepting it, so
# a request made just before expiry is not refused half-way through a sync.
_TOKEN_MARGIN = 300.0
_PAGE_SIZE = 200
_MIB = 1024 * 1024
DEFAULT_EXTENSIONS = (".pdf", ".docx", ".md", ".txt")
_SITE_HOST = re.compile(r"^[a-z0-9][a-z0-9-]*\.sharepoint\.com$")
_SITE_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")
_EXTENSION = re.compile(r"^\.[a-z0-9]{1,10}$")
# What SharePoint refuses in a file or folder name, plus control characters.
_NAME_FORBIDDEN = re.compile(r'["*:<>?\\|\x00-\x1f\x7f]')
# Ids Graph hands out for sites (`host,guid,guid`), drives (`b!...`) and items.
# Checked before one goes into a URL path, because they are read off a response.
_GRAPH_ID = re.compile(r"^[A-Za-z0-9!._,-]{1,512}$")
_ERROR_CODE = re.compile(r"^[A-Za-z_]{1,64}$")


class SharePointConfig(BaseModel):
    """Which library a SharePoint or OneDrive source reads, and which files in it.

    The credential is not here - it is an `EntraAppSecret` the source names in
    `secret_id` (#937). `site_url` is the one required field: a library defaults
    to the site's own, the folder to the whole library.
    """

    site_url: str = Field(
        title="Site URL",
        description=(
            "The site, e.g. https://contoso.sharepoint.com/sites/Handbook - or a OneDrive, "
            "e.g. https://contoso-my.sharepoint.com/personal/jane_contoso_com"
        ),
    )
    library: str | None = Field(
        default=None,
        title="Document library",
        description=(
            "The library's name as SharePoint shows it, e.g. Documents. "
            "Leave empty for the site's default library; a OneDrive has only that one."
        ),
    )
    folder_path: str | None = Field(
        default=None,
        title="Folder",
        description="A folder inside the library, e.g. Policies/HR. Leave empty for the whole library.",
    )
    include_subfolders: bool = Field(default=True, title="Include subfolders")
    extensions: list[str] = Field(
        default_factory=lambda: list(DEFAULT_EXTENSIONS),
        title="File types",
        description=(
            "Only files with these extensions are read. Add .pptx, .xlsx and the other "
            "types the collection's parser reads."
        ),
    )

    @field_validator("site_url")
    @classmethod
    def _site_url(cls, value: str) -> str:
        """An https address on a `*.sharepoint.com` host, and nothing past the site.

        A library or a page URL pasted from the browser - `.../Shared%20Documents/
        Forms/AllItems.aspx` - is refused rather than trimmed: guessing where the
        site ends is how a source would read the wrong one.
        """
        parts = urlsplit(value.strip())
        try:
            port = parts.port
        except ValueError:
            port = -1
        if parts.scheme != "https" or not parts.hostname:
            raise ValueError("The site URL must be an https:// address.")
        if parts.username is not None or port is not None or parts.query or parts.fragment:
            raise ValueError(
                "Paste the site's own address, with no port, query string or user name."
            )
        if not _SITE_HOST.fullmatch(parts.hostname):
            raise ValueError(
                "The site URL must be on a sharepoint.com host, e.g. contoso.sharepoint.com."
            )
        segments = [segment for segment in parts.path.split("/") if segment]
        if any(
            not _SITE_SEGMENT.fullmatch(segment) or segment.lower().endswith(".aspx")
            for segment in segments
        ):
            raise ValueError(
                "That is not a site's address. Paste the site URL, e.g. "
                "https://contoso.sharepoint.com/sites/Handbook, and put the library and the "
                "folder in their own fields."
            )
        return "/".join([f"https://{parts.hostname}", *segments])

    @field_validator("library")
    @classmethod
    def _library(cls, value: str | None) -> str | None:
        name = (value or "").strip()
        if not name:
            return None
        if len(name) > 255 or _NAME_FORBIDDEN.search(name) or "/" in name:
            raise ValueError("That is not a document library's name.")
        return name

    @field_validator("folder_path")
    @classmethod
    def _folder_path(cls, value: str | None) -> str | None:
        """A folder inside the library, spelled with `/`, or `None` for all of it."""
        segments = [segment.strip() for segment in (value or "").split("/") if segment.strip()]
        if not segments:
            return None
        for segment in segments:
            if segment in (".", "..") or _NAME_FORBIDDEN.search(segment):
                raise ValueError(
                    f"{segment!r} is not a folder name SharePoint allows. "
                    "Separate folders with '/', e.g. Policies/HR."
                )
        return "/".join(segments)

    @field_validator("extensions")
    @classmethod
    def _extensions(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for raw in value:
            extension = raw.strip().lower()
            if not extension:
                continue
            extension = extension if extension.startswith(".") else f".{extension}"
            if not _EXTENSION.fullmatch(extension):
                raise ValueError(f"{raw.strip()!r} is not a file extension, e.g. .pdf.")
            if extension not in normalized:
                normalized.append(extension)
        if not normalized:
            raise ValueError("At least one file type is needed.")
        return normalized

    def site_address(self) -> str:
        """The site in Graph's path addressing: `sites/{host}` or `sites/{host}:/{path}`."""
        parts = urlsplit(self.site_url)
        path = parts.path.strip("/")
        return f"sites/{parts.hostname}:/{path}" if path else f"sites/{parts.hostname}"


class _File(BaseModel):
    mime_type: str | None = Field(default=None, alias="mimeType")


class _Item(BaseModel):
    """A drive item, a drive or a site - the fields of each this connector reads."""

    id: str
    name: str = ""
    size: int | None = None
    file: _File | None = None
    folder: dict[str, object] | None = None
    root: dict[str, object] | None = None
    last_modified: datetime | None = Field(default=None, alias="lastModifiedDateTime")
    download_url: str | None = Field(default=None, alias="@microsoft.graph.downloadUrl")


class _Page(BaseModel):
    value: list[_Item] = []
    next_link: str | None = Field(default=None, alias="@odata.nextLink")
    delta_link: str | None = Field(default=None, alias="@odata.deltaLink")


class _Token(BaseModel):
    access_token: str
    expires_in: int


@dataclass(frozen=True)
class _Retry:
    """A transient answer: try again after `wait` seconds, or `None` for the local backoff."""

    wait: float | None


class _ResyncRequired(Exception):
    """A delta link Graph no longer honours (HTTP 410): the library must be listed again."""


def _retry_after(value: str | None) -> float | None:
    """Graph's `Retry-After`, which it sends in seconds, capped; `None` when absent."""
    stripped = (value or "").strip()
    return min(float(stripped), _MAX_RETRY_AFTER) if stripped.isdigit() else None


def _graph_id(value: str) -> str:
    if not _GRAPH_ID.fullmatch(value):
        raise ExternalServiceError(
            message="Microsoft Graph answered an id this connector does not recognise, so it was not used."
        )
    return value


def _graph_link(value: str) -> str:
    """A link Graph answered with, refused unless it leads back to Graph."""
    if not value.startswith(_GRAPH_ORIGIN):
        raise ExternalServiceError(
            message="Microsoft Graph answered a link to another host, so it was not followed."
        )
    return value


def _error_code(response: httpx.Response) -> str | None:
    """Graph's own error code - `accessDenied`, `itemNotFound` - when it is one.

    A fixed vocabulary and the most useful word for troubleshooting, so it may
    reach a sync log; the error's `message` is Graph's prose and does not.
    """
    try:
        body = response.json()
    except ValueError:
        return None
    error = body.get("error") if isinstance(body, dict) else None
    code = error.get("code") if isinstance(error, dict) else error
    return code if isinstance(code, str) and _ERROR_CODE.fullmatch(code) else None


class _Graph:
    """One sync's Microsoft Graph session: the app's token, retries, and which hosts get what.

    Every request is retried on a 429, a 5xx or a transport error, `_ATTEMPTS`
    times in all, honouring Graph's `Retry-After` - throttling is how Graph
    answers a large library read quickly, not a failure. A refusal (400, 401,
    403) is not retried: asking again with the same credential gets the same
    answer.
    """

    def __init__(
        self, credential: EntraAppSecret, client: httpx.AsyncClient, backoff: float
    ) -> None:
        self._credential = credential
        self._client = client
        self._backoff = backoff
        self._token: str | None = None
        self._token_expires_at = 0.0

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get(self, url: str, *, what: str) -> _Page | _Item:
        """GET a Graph URL and parse it - a page when the body has `value`, else one item.

        Raises:
            NotFoundError: Graph found nothing at `url` (404).
            BadRequestError: Graph refused the app (401, 403) or the request (400).
            ExternalServiceError: Graph stayed unavailable, or answered something unreadable.
            _ResyncRequired: a delta link Graph no longer honours (410).
        """

        async def attempt() -> httpx.Response | _Retry:
            response = await self._client.get(
                url, headers={"Authorization": f"Bearer {await self._bearer()}"}
            )
            if response.status_code in _TRANSIENT:
                return _Retry(_retry_after(response.headers.get("retry-after")))
            return response

        response = await self._with_retries(attempt, what=what)
        status = response.status_code
        if status == 401:
            raise BadRequestError(
                message=(
                    f"Microsoft Graph did not accept the app's token for {what}. The app registration "
                    "needs a Microsoft Graph application permission, such as Sites.Selected, with "
                    "administrator consent."
                )
            )
        if status == 403:
            raise BadRequestError(
                message=(
                    f"Microsoft Graph denied the app access to {what} ({_error_code(response) or 'HTTP 403'}). "
                    "Grant the app registration read access to this site - Sites.Selected, granted on "
                    "the site - and sync again."
                ),
                details={"code": _error_code(response)},
            )
        if status == 404:
            raise NotFoundError(message=f"Microsoft Graph found no {what}.")
        if status == 410:
            raise _ResyncRequired
        if not 200 <= status < 300:
            raise ExternalServiceError(
                message=f"Microsoft Graph answered HTTP {status} for {what} ({_error_code(response) or 'no code'}).",
                details={"status": status},
            )
        try:
            body = response.json()
            return _Page.model_validate(body) if "value" in body else _Item.model_validate(body)
        except (ValueError, ValidationError, TypeError):
            # Neither the body nor the validation error is quoted: a
            # `ValidationError` embeds the input, and the input is Graph's.
            raise ExternalServiceError(
                message=f"Microsoft Graph answered {what} with a body this connector could not read."
            ) from None

    async def item(self, url: str, *, what: str) -> _Item:
        answer = await self.get(url, what=what)
        if not isinstance(answer, _Item):
            raise ExternalServiceError(
                message=f"Microsoft Graph answered {what} with a list, not an item."
            )
        return answer

    async def pages(self, url: str, *, what: str) -> AsyncGenerator[_Page]:
        """Every page of a Graph collection, following `@odata.nextLink` on Graph only."""
        next_url: str | None = url
        while next_url is not None:
            page = await self.get(next_url, what=what)
            if not isinstance(page, _Page):
                raise ExternalServiceError(
                    message=f"Microsoft Graph answered {what} with an item, not a list."
                )
            yield page
            next_url = _graph_link(page.next_link) if page.next_link else None

    async def delta_link(self, url: str, *, what: str) -> str:
        """The delta link that ends a delta read from `url`."""
        async with aclosing(self.pages(url, what=what)) as pages:
            async for page in pages:
                if page.delta_link:
                    return _graph_link(page.delta_link)
        raise ExternalServiceError(message=f"Microsoft Graph ended {what} without a delta link.")

    async def changed_since(self, link: str) -> bool:
        """Whether anything in the drive changed since `link` was issued.

        The root folder is left out: it is reported alongside whatever changed
        below it, never on its own account. A link Graph no longer honours is a
        change - the library has to be listed to know.
        """
        try:
            async with aclosing(self.pages(link, what="the library's changes")) as pages:
                async for page in pages:
                    if any(item.root is None for item in page.value):
                        return True
        except _ResyncRequired:
            return True
        return False

    async def download(self, url: str, dest: Path, *, what: str, limit: int) -> None:
        """Stream a file's pre-authenticated download URL to `dest`, without the token.

        Raises:
            BadRequestError: the file is larger than `limit`.
            ExternalServiceError: the URL is not SharePoint's, or the download failed.
        """
        target = url
        for _ in range(_MAX_REDIRECTS + 1):
            status, location = await self._with_retries(
                partial(
                    self._download_once,
                    self._download_url(target, what=what),
                    dest,
                    what=what,
                    limit=limit,
                ),
                what=what,
            )
            if 200 <= status < 300:
                return
            if status not in _REDIRECTS or location is None:
                raise ExternalServiceError(
                    message=f"SharePoint answered HTTP {status} when {what} was downloaded.",
                    details={"status": status},
                )
            target = location
        raise ExternalServiceError(
            message=f"SharePoint redirected the download of {what} too many times."
        )

    async def _download_once(
        self, url: str, dest: Path, *, what: str, limit: int
    ) -> tuple[int, str | None] | _Retry:
        """One download attempt: the status and `Location`, with the body written on a 2xx."""
        async with self._client.stream("GET", url) as response:
            if response.status_code in _TRANSIENT:
                return _Retry(_retry_after(response.headers.get("retry-after")))
            if not 200 <= response.status_code < 300:
                return response.status_code, response.headers.get("location")
            await self._write_capped(response, dest, what=what, limit=limit)
            return response.status_code, None

    @staticmethod
    def _download_url(url: str, *, what: str) -> str:
        parts = urlsplit(url)
        if parts.scheme != "https" or not _SITE_HOST.fullmatch(parts.hostname or ""):
            raise ExternalServiceError(
                message=f"Microsoft Graph pointed the download of {what} outside SharePoint, so it was not read."
            )
        return url

    @staticmethod
    async def _write_capped(response: httpx.Response, dest: Path, *, what: str, limit: int) -> None:
        written = 0
        with dest.open("wb") as handle:
            async for chunk in response.aiter_bytes():
                written += len(chunk)
                if written > limit:
                    raise BadRequestError(
                        message=f"{what} is larger than the {limit // _MIB} MB a synced file may be.",
                        details={"limit_bytes": limit},
                    )
                handle.write(chunk)

    async def _bearer(self) -> str:
        """The app's Graph token, signed in for once and renewed shortly before it expires.

        Raises:
            BadRequestError: Entra refused the tenant, the app or its secret.
            ExternalServiceError: Entra stayed unavailable.
        """
        if self._token is not None and time.monotonic() < self._token_expires_at:
            return self._token
        credential = self._credential
        form = {
            "grant_type": "client_credentials",
            "client_id": credential.client_id,
            "client_secret": credential.client_secret.get_secret_value(),
            "scope": _SCOPE,
        }

        async def attempt() -> httpx.Response | _Retry:
            response = await self._client.post(
                f"{LOGIN}/{credential.tenant_id}/oauth2/v2.0/token", data=form
            )
            if response.status_code in _TRANSIENT:
                return _Retry(_retry_after(response.headers.get("retry-after")))
            return response

        response = await self._with_retries(attempt, what="signing in to Microsoft Entra")
        if response.status_code in (400, 401):
            code = _error_code(response) or f"HTTP {response.status_code}"
            raise BadRequestError(
                message=(
                    f"Microsoft Entra refused the app registration's credentials ({code}). Check the "
                    "tenant id, the client id and the client secret in the Vault, and whether the "
                    "secret has expired."
                ),
                details={"code": _error_code(response)},
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

    async def _with_retries[T](
        self, attempt: Callable[[], Awaitable[T | _Retry]], *, what: str
    ) -> T:
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
                if not isinstance(outcome, _Retry):
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


class SharePointConnector(BaseSyncConnector):
    """Reads one SharePoint document library or OneDrive, or a folder in it, into a collection.

    One instance serves one sync: it holds the Graph session - and the app's
    token - between `remote_version`, `list_files` and the downloads, and
    `aclose` ends it.
    """

    CONNECTOR_TYPE: ClassVar[str] = "sharepoint"
    DISPLAY_NAME: ClassVar[str] = "SharePoint & OneDrive"
    SECRET_KIND: ClassVar[SecretKind] = SecretKind.ENTRA_APP
    CONFIG_MODEL: ClassVar[type[BaseModel]] = SharePointConfig
    # Seconds before the first retry of a transient failure, doubling after.
    RETRY_BACKOFF: ClassVar[float] = 1.0

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        """`transport` replaces the network for a test."""
        self._transport = transport
        self._graph: _Graph | None = None
        self._drives: dict[str, str] = {}

    async def validate_config(self, config: ConnectorConfig) -> ConfigRefusal | None:
        """The required field, then every field's shape.

        Whether the app can read the site is not asked here: `validate_config`
        sees the config and not the credential, so that is the first sync's to
        answer, on its log.
        """
        refusal = await super().validate_config(config)
        if refusal is not None:
            return refusal
        try:
            SharePointConfig.model_validate(config)
        except ValidationError as exc:
            error = exc.errors(include_url=False, include_input=False)[0]
            field = str(error["loc"][0]) if error["loc"] else None
            return ConfigRefusal(
                message=str(error["msg"]).removeprefix("Value error, "), field=field
            )
        return None

    async def remote_version(
        self, config: ConnectorConfig, credential: StorableSecret | None, previous: str | None
    ) -> str:
        """`<drive id> <delta link>`: where the library's change feed stood when this run began.

        `previous` is answered back unchanged when Graph reports nothing changed
        since it, which is what lets the sync stop early. Otherwise the answer is
        a fresh link, taken *before* the listing, so a change made while the
        listing runs is reported to the next run rather than lost between them.
        """
        parsed = SharePointConfig.model_validate(config)
        graph = self._session(credential)
        drive_id = await self._drive_id(graph, parsed)
        drive_part, _, link = (previous or "").partition(" ")
        if (
            drive_part == drive_id
            and link.startswith(_GRAPH_ORIGIN)
            and not await graph.changed_since(link)
        ):
            return f"{drive_id} {link}"
        latest = await graph.delta_link(
            f"{GRAPH}/drives/{drive_id}/root/delta?token=latest", what="the library's change feed"
        )
        return f"{drive_id} {latest}"

    async def list_files(
        self, config: ConnectorConfig, credential: StorableSecret | None
    ) -> RemoteListing:
        """Every file of the configured types in the folder, and below it unless told not to.

        Complete unless a folder below the configured one could not be listed:
        that folder's files are not in the answer, and removing their documents
        because of one refusal would empty part of the collection. The
        configured folder itself failing raises, since there is nothing to list.
        """
        parsed = SharePointConfig.model_validate(config)
        graph = self._session(credential)
        drive_id = await self._drive_id(graph, parsed)
        start = await self._start_folder(graph, drive_id, parsed)
        files: list[RemoteFile] = []
        problems: list[str] = []
        # Each folder by id, with its path in the library for the sync log.
        queue: deque[tuple[str, str]] = deque([(start, parsed.folder_path or "")])
        while queue:
            folder_id, path = queue.popleft()
            shown = path or "the library's top level"
            url = (
                f"{GRAPH}/drives/{drive_id}/items/{folder_id}/children"
                f"?$top={_PAGE_SIZE}&$select=id,name,size,file,folder,lastModifiedDateTime"
            )
            try:
                async for page in graph.pages(url, what=f"the folder {shown}"):
                    for item in page.value:
                        if item.folder is not None:
                            if parsed.include_subfolders:
                                queue.append(
                                    (_graph_id(item.id), f"{path}/{item.name}".lstrip("/"))
                                )
                            continue
                        if (
                            item.file is None
                            or PurePosixPath(item.name).suffix.lower() not in parsed.extensions
                        ):
                            # Not a file (a OneNote notebook is a package), or not a type asked for.
                            continue
                        files.append(
                            RemoteFile(
                                id=_graph_id(item.id),
                                name=item.name,
                                mime_type=item.file.mime_type,
                                size=item.size,
                                modified_at=item.last_modified,
                                source_path=f"sharepoint://{drive_id}/{item.id}",
                            )
                        )
            except AppException as exc:
                if folder_id == start:
                    raise
                problems.append(f"The folder {shown} could not be listed: {exc.message}")
        return RemoteListing(files=files, complete=not problems, problems=problems)

    async def _fetch(
        self,
        file: RemoteFile,
        dest_path: Path,
        config: ConnectorConfig,
        credential: StorableSecret | None,
    ) -> None:
        """Download one file to the path the base class chose.

        The item is read again rather than trusted from the listing: its
        download URL lives about an hour, and a file deleted since the listing
        is not a failure but a file the library no longer holds.
        """
        graph = self._session(credential)
        drive_id, _, item_id = file.source_path.removeprefix("sharepoint://").partition("/")
        try:
            item = await graph.item(
                f"{GRAPH}/drives/{_graph_id(drive_id)}/items/{_graph_id(item_id)}",
                what=f"the file {file.name}",
            )
        except NotFoundError:
            raise WithdrawnFile(
                f"{file.name} was deleted from the library before it was read."
            ) from None
        if item.file is None or not item.download_url:
            raise WithdrawnFile(f"{file.name} is no longer a file SharePoint can download.")
        limit = settings.MAX_UPLOAD_SIZE_MB * _MIB
        if item.size is not None and item.size > limit:
            raise BadRequestError(
                message=(
                    f"{file.name} is {item.size // _MIB} MB, and a synced file may be at most "
                    f"{settings.MAX_UPLOAD_SIZE_MB} MB."
                ),
                details={"size_bytes": item.size, "limit_bytes": limit},
            )
        await graph.download(item.download_url, dest_path, what=file.name, limit=limit)

    async def aclose(self) -> None:
        """End the Graph session. Safe to call twice, and before one was opened."""
        graph, self._graph = self._graph, None
        if graph is not None:
            await graph.aclose()

    def _session(self, credential: StorableSecret | None) -> _Graph:
        """This sync's Graph session, opened with the source's own credential.

        Raises:
            BadRequestError: the source names no credential, or one that is not
                a Microsoft Entra app.
        """
        if credential is None:
            raise BadRequestError(
                message=(
                    "This SharePoint source has no credential. Add a Microsoft Entra app to the Vault "
                    "and choose it as the source's credential."
                )
            )
        if not isinstance(credential, EntraAppSecret):
            raise BadRequestError(
                message="A SharePoint source needs a Microsoft Entra app credential, and the one it names is not one."
            )
        if self._graph is None:
            client = httpx.AsyncClient(
                timeout=_TIMEOUT, follow_redirects=False, transport=self._transport
            )
            self._graph = _Graph(credential, client, self.RETRY_BACKOFF)
        return self._graph

    async def _drive_id(self, graph: _Graph, parsed: SharePointConfig) -> str:
        """The drive the site URL and library name point at, looked up once per sync.

        Raises:
            BadRequestError: no such site the app can see, or no such library on it.
        """
        key = f"{parsed.site_url}\n{parsed.library or ''}"
        if key in self._drives:
            return self._drives[key]
        try:
            site = await graph.item(
                f"{GRAPH}/{quote(parsed.site_address(), safe='/:')}?$select=id", what="the site"
            )
        except NotFoundError:
            raise BadRequestError(
                message=(
                    f"There is no SharePoint site at {parsed.site_url}, or the app cannot see it - with "
                    "Sites.Selected, a site the app was not granted can answer this way."
                )
            ) from None
        site_id = _graph_id(site.id)
        if parsed.library is None:
            drive = await graph.item(
                f"{GRAPH}/sites/{site_id}/drive?$select=id,name", what="the site's library"
            )
            drive_id = _graph_id(drive.id)
        else:
            names: list[str] = []
            drive_id = ""
            async for page in graph.pages(
                f"{GRAPH}/sites/{site_id}/drives?$select=id,name", what="the site's libraries"
            ):
                for drive in page.value:
                    names.append(drive.name)
                    if drive.name.casefold() == parsed.library.casefold():
                        drive_id = _graph_id(drive.id)
            if not drive_id:
                raise BadRequestError(
                    message=(
                        f"The site has no document library named {parsed.library!r}. "
                        f"Its libraries are: {', '.join(sorted(names)) or 'none the app can see'}."
                    )
                )
        self._drives[key] = drive_id
        return drive_id

    async def _start_folder(self, graph: _Graph, drive_id: str, parsed: SharePointConfig) -> str:
        """The id of the folder the listing starts from - the library's root, or the configured folder.

        Raises:
            BadRequestError: the folder does not exist, or is a file.
        """
        if parsed.folder_path is None:
            url = f"{GRAPH}/drives/{drive_id}/root?$select=id,folder"
        else:
            url = f"{GRAPH}/drives/{drive_id}/root:/{quote(parsed.folder_path, safe='/')}?$select=id,folder"
        try:
            folder = await graph.item(url, what="the folder")
        except NotFoundError:
            raise BadRequestError(
                message=f"The library has no folder {parsed.folder_path!r}.",
                details={"folder_path": parsed.folder_path},
            ) from None
        if folder.folder is None:
            raise BadRequestError(
                message=f"{parsed.folder_path!r} is a file, not a folder.",
                details={"folder_path": parsed.folder_path},
            )
        return _graph_id(folder.id)
