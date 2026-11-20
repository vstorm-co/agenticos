from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import SecretStr

from app.services.mcp_connection import McpConnectionService
from app.services.portals.google_oauth import DRIVE_READONLY
from app.services.rag.drive_api import GoogleDriveOAuthGrant
from app.worker.tasks import rag_tasks

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    ("scopes", "has_credential"),
    [
        ({DRIVE_READONLY}, True),
        ({"openid", "email"}, False),
    ],
)
async def test_connector_credential_requires_a_drive_read_scope(
    monkeypatch: pytest.MonkeyPatch, scopes: set[str], has_credential: bool
) -> None:
    organization_id = uuid4()
    account_id = uuid4()
    account = SimpleNamespace(
        scope="org",
        organization_id=organization_id,
        catalog_key="google",
    )
    grant = SimpleNamespace(
        client_id="client-id",
        client_secret=SecretStr("client-secret"),
        refresh_token=SecretStr("refresh-token"),
        scopes=scopes,
    )
    monkeypatch.setattr(
        rag_tasks.mcp_connection_repo,
        "get_account",
        AsyncMock(return_value=account),
    )
    monkeypatch.setattr(
        McpConnectionService,
        "account_grant",
        AsyncMock(return_value=grant),
    )

    credential = await rag_tasks._connector_credential(
        db=object(),
        secret_id=None,
        organization_id=organization_id,
        connected_account_id=account_id,
    )

    if has_credential:
        assert isinstance(credential, GoogleDriveOAuthGrant)
    else:
        assert credential is None
