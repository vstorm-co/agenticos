from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from pydantic import SecretStr

from app.services.rag.connectors.google_drive import GoogleDriveConnector
from app.services.rag.drive_api import DRIVE_API, DriveClient, GoogleDriveOAuthGrant


class _Token:
    valid = True
    token = "oauth-access-token"

    def refresh(self, request: object) -> None:
        raise AssertionError("the test token is valid")


@pytest.mark.anyio
async def test_oauth_source_lists_downloads_and_exports_google_docs(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/files"):
            return httpx.Response(
                200,
                json={
                    "files": [
                        {
                            "id": "doc-1",
                            "name": "Notes",
                            "mimeType": "application/vnd.google-apps.document",
                        },
                        {"id": "file-1", "name": "plain.txt", "mimeType": "text/plain"},
                    ]
                },
            )
        if request.url.path.endswith("/files/doc-1"):
            return httpx.Response(200, json={"mimeType": "application/vnd.google-apps.document"})
        if request.url.path.endswith("/files/file-1") and request.url.params.get("alt") != "media":
            return httpx.Response(200, json={"mimeType": "text/plain"})
        if request.url.path.endswith("/files/file-1"):
            return httpx.Response(200, content=b"plain text")
        return httpx.Response(200, content=b"%PDF")

    grant = GoogleDriveOAuthGrant(
        client_id="client",
        client_secret=SecretStr("client-secret"),
        refresh_token=SecretStr("refresh-token"),
    )
    with patch.object(
        DriveClient,
        "from_oauth_grant",
        side_effect=lambda **kwargs: DriveClient(
            _Token(), http=httpx.Client(base_url=DRIVE_API, transport=httpx.MockTransport(handler))
        ),
    ) as factory:
        connector = GoogleDriveConnector()
        listing = await connector.list_files({"folder_id": "folder-1"}, grant)
        local = await connector.download_file(listing.files[0], tmp_path, {}, grant)
        plain = await connector.download_file(listing.files[1], tmp_path, {}, grant)

    assert listing.files[0].name == "Notes.pdf"
    assert local.read_bytes() == b"%PDF"
    assert plain.read_bytes() == b"plain text"
    assert [request.url.path for request in requests] == [
        "/drive/v3/files",
        "/drive/v3/files/doc-1",
        "/drive/v3/files/doc-1/export",
        "/drive/v3/files/file-1",
        "/drive/v3/files/file-1",
    ]
    assert all(
        request.headers["Authorization"] == "Bearer oauth-access-token" for request in requests
    )
    assert all(request.url.params["supportsAllDrives"] == "true" for request in requests)
    factory.assert_called()
