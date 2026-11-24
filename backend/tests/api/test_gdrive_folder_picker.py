"""Google Drive's organization-owned folder picker endpoint."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from google.auth.exceptions import RefreshError
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.core.secret_kinds import GoogleOAuthAppSecret
from app.db.models.mcp_connection import AUTHORIZATION_EXPIRED, McpConnection
from app.main import app
from app.repositories import mcp_connection as mcp_connection_repo
from app.services.gdrive_picker import GoogleDrivePickerService
from app.services.organization_secret import OrganizationSecretService
from app.services.portals.google_oauth import DRIVE
from app.services.rag.drive_api import DRIVE_API, DriveClient
from tests.test_connected_accounts import (
    SOURCE_GENERATION,
    SOURCE_SECRET,
    _payload,
    _sealed,
)
from tests.test_connected_accounts import (
    _account as _connected_account,
)

pytestmark = [pytest.mark.anyio, pytest.mark.security]

_DRIVE_READONLY = "https://www.googleapis.com/auth/drive.readonly"


class _Credentials:
    valid = True
    token = "access-token"

    def refresh(self, _request: object) -> None:
        raise AssertionError("the mock token is already valid")


def _account(organization_id: uuid.UUID) -> McpConnection:
    account = _connected_account(
        scope="org",
        user_id=None,
        organization_id=organization_id,
        account_source_organization_id=organization_id,
        granted_scopes=[_DRIVE_READONLY],
    )
    account.oauth_payload = _sealed(
        account,
        _payload(
            client_id="client-id",
            client_secret="client-secret",
            refresh_token="refresh-token",
            account_source_organization_id=organization_id,
        ),
    )
    return account


def _client(monkeypatch, *, organization_id, account, handler, google_client_id="client-id"):
    context = AuthContext(
        user_id=uuid.uuid4(),
        organization_id=organization_id,
        role=OrgRoleName.OWNER.value,
    )
    service = GoogleDrivePickerService(MagicMock())
    # Keep account_grant real: the picker must follow the current app and refuse
    # an expired grant or a client that no longer matches the account's token.
    monkeypatch.setattr(
        OrganizationSecretService,
        "oauth_app_identity_for_org",
        AsyncMock(
            return_value=(
                GoogleOAuthAppSecret(client_id=google_client_id, client_secret="client-secret"),
                SOURCE_SECRET,
                SOURCE_GENERATION,
            )
        ),
    )
    monkeypatch.setattr(
        mcp_connection_repo,
        "get_account",
        AsyncMock(return_value=account),
    )

    def make_drive(cls, **kwargs):
        assert kwargs["client_id"] == "client-id"
        assert kwargs["client_secret"].get_secret_value() == "client-secret"
        assert kwargs["refresh_token"].get_secret_value() == "refresh-token"
        http = httpx.Client(base_url=DRIVE_API, transport=httpx.MockTransport(handler))
        return DriveClient(_Credentials(), http=http)

    monkeypatch.setattr(DriveClient, "from_oauth_grant", classmethod(make_drive))
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_google_drive_picker_service] = lambda: service
    app.dependency_overrides[deps.get_redis] = lambda: MagicMock()
    return service, previous


async def _get(
    monkeypatch, *, organization_id, account, handler, parent="root", google_client_id="client-id"
):
    service, previous = _client(
        monkeypatch,
        organization_id=organization_id,
        account=account,
        handler=handler,
        google_client_id=google_client_id,
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.get(
                f"{settings.API_V1_STR}/sync-sources/gdrive/folders",
                params={
                    "account": str(account.id if account is not None else uuid.uuid4()),
                    "parent": parent,
                },
            )
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


async def test_root_lists_my_drive_folders_and_paged_shared_drives(monkeypatch):
    organization_id = uuid.uuid4()
    account = _account(organization_id)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/drives"):
            token = request.url.params.get("pageToken")
            return httpx.Response(
                200,
                json={
                    "nextPageToken": "drives-next" if token is None else None,
                    "drives": [
                        {"id": "drive_1", "name": "Shared"}
                        if token is None
                        else {"id": "drive_2", "name": "Archive"}
                    ],
                },
            )
        token = request.url.params.get("pageToken")
        return httpx.Response(
            200,
            json={
                "nextPageToken": "folders-next" if token is None else None,
                "files": [
                    {"id": "root_folder", "name": "Handbook"}
                    if token is None
                    else {"id": "root_folder_2", "name": "Policies"}
                ],
            },
        )

    response = await _get(
        monkeypatch, organization_id=organization_id, account=account, handler=handler
    )

    assert response.status_code == 200
    assert response.json() == {
        "drives": [
            {"id": "drive_1", "name": "Shared"},
            {"id": "drive_2", "name": "Archive"},
        ],
        "folders": [
            {"id": "root_folder", "name": "Handbook"},
            {"id": "root_folder_2", "name": "Policies"},
        ],
    }
    files_requests = [request for request in requests if request.url.path.endswith("/files")]
    assert len(files_requests) == 2
    assert all(
        request.url.params["supportsAllDrives"] == "true"
        and request.url.params["includeItemsFromAllDrives"] == "true"
        and request.url.params["corpora"] == "user"
        and request.url.params["q"]
        == "mimeType='application/vnd.google-apps.folder' and 'root' in parents and trashed=false"
        for request in files_requests
    )
    assert len([request for request in requests if request.url.path.endswith("/drives")]) == 2


@pytest.mark.parametrize(
    ("parent", "corpora", "drive_id", "parent_id"),
    [
        ("folder_parent", "allDrives", None, "folder_parent"),
        ("drive:drive_1", "drive", "drive_1", "drive_1"),
    ],
)
async def test_a_parent_lists_its_subfolders(monkeypatch, parent, corpora, drive_id, parent_id):
    organization_id = uuid.uuid4()
    account = _account(organization_id)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={"files": [{"id": "nested_folder", "name": "Subfolder"}]},
        )

    response = await _get(
        monkeypatch,
        organization_id=organization_id,
        account=account,
        handler=handler,
        parent=parent,
    )

    assert response.status_code == 200
    assert response.json() == {
        "drives": [],
        "folders": [{"id": "nested_folder", "name": "Subfolder"}],
    }
    assert len(seen) == 1
    assert seen[0].url.params["supportsAllDrives"] == "true"
    assert seen[0].url.params["includeItemsFromAllDrives"] == "true"
    assert seen[0].url.params["corpora"] == corpora
    if drive_id is not None:
        assert seen[0].url.params["driveId"] == drive_id
    assert seen[0].url.params["q"] == (
        "mimeType='application/vnd.google-apps.folder' and "
        f"'{parent_id}' in parents and trashed=false"
    )


async def test_an_account_from_another_organization_is_not_used(monkeypatch):
    organization_id = uuid.uuid4()
    foreign_account = _account(uuid.uuid4())
    drive_called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal drive_called
        drive_called = True
        return httpx.Response(200, json={})

    response = await _get(
        monkeypatch,
        organization_id=organization_id,
        account=foreign_account,
        handler=handler,
    )

    assert response.status_code == 404
    assert not drive_called


@pytest.mark.parametrize(
    "unusable", ["missing", "personal", "provider", "unsealed", "expired", "scope", "client"]
)
async def test_an_unusable_account_cannot_reach_google(monkeypatch, unusable):
    organization_id = uuid.uuid4()
    account = _account(organization_id)
    if unusable == "missing":
        account = None
    elif unusable == "personal":
        account.scope = "user"
        account.user_id = uuid.uuid4()
        account.organization_id = None
    elif unusable == "provider":
        account.catalog_key = "github"
    elif unusable == "unsealed":
        account.oauth_payload = None
    elif unusable == "expired":
        account.last_status = "error"
        account.last_error = AUTHORIZATION_EXPIRED
    elif unusable == "scope":
        account.granted_scopes = []

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={})

    response = await _get(
        monkeypatch,
        organization_id=organization_id,
        account=account,
        handler=handler,
        google_client_id="replacement-client" if unusable == "client" else "client-id",
    )

    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Google account not found"
    assert not requests


@pytest.mark.parametrize("scope", [DRIVE, _DRIVE_READONLY])
async def test_either_drive_scope_can_list_folders(monkeypatch, scope):
    organization_id = uuid.uuid4()
    account = _account(organization_id)
    account.granted_scopes = [scope]
    response = await _get(
        monkeypatch,
        organization_id=organization_id,
        account=account,
        handler=lambda _request: httpx.Response(200, json={"files": [], "drives": []}),
    )
    assert response.status_code == 200
    assert response.json() == {"drives": [], "folders": []}


def test_the_picker_dependency_uses_the_requests_session():
    db = MagicMock()
    assert deps.get_google_drive_picker_service(db).db is db


@pytest.mark.parametrize(
    ("upstream_status", "status", "code", "message"),
    [
        (
            401,
            503,
            "EXTERNAL_SERVICE_ERROR",
            "Google Drive rejected the account authorization. Reconnect the account.",
        ),
        (403, 403, "AUTHORIZATION_ERROR", "Google Drive denied access to this listing."),
        (
            404,
            404,
            "NOT_FOUND",
            "Google Drive folder not found or no longer accessible.",
        ),
        (
            502,
            503,
            "EXTERNAL_SERVICE_ERROR",
            "Google Drive could not list folders. Try again later.",
        ),
    ],
)
async def test_google_drive_listing_errors_are_controlled(
    monkeypatch, upstream_status, status, code, message
):
    organization_id = uuid.uuid4()
    account = _account(organization_id)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(upstream_status, json={"error": {"message": "provider detail"}})

    response = await _get(
        monkeypatch, organization_id=organization_id, account=account, handler=handler
    )

    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["message"] == message
    assert "provider detail" not in response.text


async def test_revoked_google_grant_returns_reconnect_error(monkeypatch):
    organization_id = uuid.uuid4()
    account = _account(organization_id)

    def refresh(_self, _request: object) -> None:
        raise RefreshError("revoked refresh token details")

    monkeypatch.setattr(_Credentials, "valid", False)
    monkeypatch.setattr(_Credentials, "refresh", refresh)
    response = await _get(
        monkeypatch,
        organization_id=organization_id,
        account=account,
        handler=lambda _request: httpx.Response(200, json={}),
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "EXTERNAL_SERVICE_ERROR"
    assert response.json()["error"]["message"] == (
        "Google Drive account authorization expired. Reconnect the account."
    )
    assert "revoked refresh token details" not in response.text
