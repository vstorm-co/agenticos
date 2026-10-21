"""The Drive REST client: what it sends, and what it makes of the answer."""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from app.services.rag.drive_api import DRIVE_API, SCOPES, DriveClient


class _Credentials:
    """A service account token that is valid until told otherwise."""

    def __init__(self, *, valid: bool = True) -> None:
        self.valid = valid
        self.token = "t-1"
        self.refreshed = 0

    def refresh(self, request: object) -> None:
        self.refreshed += 1
        self.valid = True
        self.token = "t-2"


def drive(
    handler: Callable[[httpx.Request], httpx.Response], credentials: _Credentials | None = None
) -> DriveClient:
    http = httpx.Client(base_url=DRIVE_API, transport=httpx.MockTransport(handler))
    return DriveClient(credentials or _Credentials(), http=http)


class TestListing:
    def test_a_page_is_read_from_drives_own_field_names(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(
                200,
                json={
                    "nextPageToken": "p2",
                    "files": [
                        {
                            "id": "f1",
                            "name": "a.pdf",
                            "mimeType": "application/pdf",
                            "size": "2048",
                            "modifiedTime": "2026-10-19T08:00:00.000Z",
                        },
                        {
                            "id": "d1",
                            "name": "Doc",
                            "mimeType": "application/vnd.google-apps.document",
                        },
                    ],
                },
            )

        with drive(handler) as client:
            page = client.list_page(
                q="'x' in parents", fields="files(id)", page_size=100, page_token="p1"
            )

        assert page.next_page_token == "p2"
        assert [(f.id, f.size) for f in page.files] == [("f1", 2048), ("d1", 0)]
        assert page.files[0].modified_time == datetime(2026, 10, 19, 8, tzinfo=UTC)
        assert page.files[1].modified_time is None
        request = seen[0]
        assert request.url.path == "/drive/v3/files"
        assert dict(request.url.params) == {
            "q": "'x' in parents",
            "fields": "files(id)",
            "pageSize": "100",
            "pageToken": "p1",
        }
        assert request.headers["Authorization"] == "Bearer t-1"

    def test_the_first_page_sends_no_token(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={})

        with drive(handler) as client:
            page = client.list_page(q="q", fields="f", page_size=10, page_token=None)

        assert page.files == []
        assert page.next_page_token is None
        assert "pageToken" not in seen[0].url.params

    def test_a_refusal_raises_instead_of_reading_as_an_empty_folder(self) -> None:
        with (
            drive(lambda request: httpx.Response(403, json={"error": "denied"})) as client,
            pytest.raises(httpx.HTTPStatusError),
        ):
            client.list_page(q="q", fields="f", page_size=10, page_token=None)


class TestOneFile:
    def test_metadata_reads_the_fields_asked_for(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/drive/v3/files/f1"
            assert request.url.params["fields"] == "mimeType"
            return httpx.Response(200, json={"mimeType": "text/plain"})

        with drive(handler) as client:
            assert client.metadata("f1", fields="mimeType").mime_type == "text/plain"

    def test_a_remote_id_cannot_step_into_another_endpoint(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={})

        with drive(handler) as client:
            client.metadata("../about", fields="user")

        assert seen[0].url.raw_path.startswith(b"/drive/v3/files/..%2Fabout")

    def test_a_download_streams_the_body_into_the_destination(self, tmp_path: Path) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/drive/v3/files/f1"
            assert request.url.params["alt"] == "media"
            return httpx.Response(200, content=b"payload")

        dest = tmp_path / "a.txt"
        with drive(handler) as client:
            client.download("f1", dest)

        assert dest.read_bytes() == b"payload"

    def test_an_export_asks_for_the_target_format(self, tmp_path: Path) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/drive/v3/files/d1/export"
            assert request.url.params["mimeType"] == "application/pdf"
            return httpx.Response(200, content=b"%PDF")

        dest = tmp_path / "Doc.pdf"
        with drive(handler) as client:
            client.export("d1", "application/pdf", dest)

        assert dest.read_bytes() == b"%PDF"

    def test_a_failed_download_writes_nothing(self, tmp_path: Path) -> None:
        dest = tmp_path / "a.txt"
        with (
            drive(lambda request: httpx.Response(404)) as client,
            pytest.raises(httpx.HTTPStatusError),
        ):
            client.download("f1", dest)

        assert not dest.exists()


class TestTheToken:
    def test_an_expired_token_is_refreshed_before_the_request(self) -> None:
        seen: list[str] = []
        credentials = _Credentials(valid=False)

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.headers["Authorization"])
            return httpx.Response(200, json={})

        with drive(handler, credentials) as client:
            client.metadata("f1", fields="id")
            client.metadata("f2", fields="id")

        assert credentials.refreshed == 1
        assert seen == ["Bearer t-2", "Bearer t-2"]

    def test_a_service_account_is_scoped_to_read_only_drive(self) -> None:
        with patch("google.oauth2.service_account.Credentials") as credentials_cls:
            with DriveClient.from_service_account_info({"type": "service_account"}):
                pass
            with DriveClient.from_service_account_file("/keys/sa.json"):
                pass

        credentials_cls.from_service_account_info.assert_called_once_with(
            {"type": "service_account"}, scopes=SCOPES
        )
        credentials_cls.from_service_account_file.assert_called_once_with(
            "/keys/sa.json", scopes=SCOPES
        )
        assert SCOPES == ["https://www.googleapis.com/auth/drive.readonly"]
