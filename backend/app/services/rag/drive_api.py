"""Google Drive v3 over plain HTTPS, for the two Drive readers.

They need four endpoints - list a folder, read a file's metadata, download a
file, export a Google Docs file - and reached them through
`google-api-python-client`, a discovery client that ships the documents for
every Google API: 108 MB of the backend image for four URLs. `google-auth`
still signs the service account's token; this module only speaks the REST.

Synchronous on purpose: both callers already run Drive work in a thread.
"""

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, Self
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from google.auth.transport import Request

DRIVE_API = "https://www.googleapis.com/drive/v3"
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
_TIMEOUT = httpx.Timeout(30.0, read=120.0)


def _file_path(file_id: str) -> str:
    # The id comes from a listing, which is the remote's word; quoted, it cannot
    # step out of `/files/` into another endpoint.
    return f"/files/{quote(file_id, safe='')}"


class DriveFile(BaseModel):
    """One entry of a listing, or one file's metadata - whichever fields were asked for."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = ""
    name: str = ""
    mime_type: str = Field(default="", alias="mimeType")
    # Drive sends `size` as a decimal string, and none at all for a Google Docs file.
    size: int = 0
    modified_time: datetime | None = Field(default=None, alias="modifiedTime")


class DrivePage(BaseModel):
    """One page of `files.list`."""

    files: list[DriveFile] = []
    next_page_token: str | None = Field(default=None, alias="nextPageToken")


class Token(Protocol):
    """What the client needs of a credential: google-auth's, or a test's."""

    @property
    def valid(self) -> bool: ...

    @property
    def token(self) -> str | None: ...

    def refresh(self, request: Request) -> None: ...


class DriveClient:
    """The Drive endpoints a reader needs, authorised as one service account.

    A context manager: it holds an HTTP connection pool, closed on exit.
    """

    def __init__(self, credentials: Token, http: httpx.Client | None = None) -> None:
        self._credentials = credentials
        self._http = http or httpx.Client(base_url=DRIVE_API, timeout=_TIMEOUT)

    @classmethod
    def from_service_account_info(cls, info: dict[str, object]) -> Self:
        # Imported here, as the SDK was: every API and background worker imports
        # the Drive readers, and only a Drive source signs a token (#2225).
        from google.oauth2.service_account import Credentials

        return cls(Credentials.from_service_account_info(info, scopes=SCOPES))

    @classmethod
    def from_service_account_file(cls, path: str) -> Self:
        from google.oauth2.service_account import Credentials

        return cls(Credentials.from_service_account_file(path, scopes=SCOPES))

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._http.close()

    def list_page(
        self, *, q: str, fields: str, page_size: int, page_token: str | None
    ) -> DrivePage:
        params = {"q": q, "fields": fields, "pageSize": str(page_size)}
        if page_token:
            params["pageToken"] = page_token
        response = self._http.get("/files", params=params, headers=self._authorization())
        response.raise_for_status()
        return DrivePage.model_validate(response.json())

    def metadata(self, file_id: str, *, fields: str) -> DriveFile:
        response = self._http.get(
            _file_path(file_id), params={"fields": fields}, headers=self._authorization()
        )
        response.raise_for_status()
        return DriveFile.model_validate(response.json())

    def download(self, file_id: str, dest_path: Path) -> None:
        self._stream(_file_path(file_id), {"alt": "media"}, dest_path)

    def export(self, file_id: str, mime_type: str, dest_path: Path) -> None:
        self._stream(f"{_file_path(file_id)}/export", {"mimeType": mime_type}, dest_path)

    def _stream(self, path: str, params: dict[str, str], dest_path: Path) -> None:
        with self._http.stream("GET", path, params=params, headers=self._authorization()) as r:
            r.raise_for_status()
            with dest_path.open("wb") as fh:
                for chunk in r.iter_bytes():
                    fh.write(chunk)

    def _authorization(self) -> dict[str, str]:
        if not self._credentials.valid:
            from google.auth.transport.requests import Request

            self._credentials.refresh(Request())
        return {"Authorization": f"Bearer {self._credentials.token}"}
