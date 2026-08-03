"""Showing a person the files their agent kept.

Two things are being protected here and only one of them is obvious. The
obvious one is that a conversation is the caller's before anything is listed.
The other is the **token**: a workspace is read with a credential that also
unlocks `exec` on the sandbox service, so it can never reach a browser and
nothing may be proxied before the access check has passed.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from app.api import deps
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.services.sandbox_workspace import WorkspaceContents

pytestmark = pytest.mark.anyio

CONVERSATION_ID = uuid.uuid4()


def _row(**overrides: object):
    row = SimpleNamespace(scope="conversation", backend="state", bytes_total=128, session_id="sc-1")
    for name, value in overrides.items():
        setattr(row, name, value)
    return row


def _override(*, conversation: object, workspaces: object) -> None:
    """Stand in for the caller and the two services the routes use.

    The identity is overridden rather than a token minted: what these tests are
    about is what happens *after* authentication, and the sweep in
    `test_platform_routes.py` is what proves these routes demand it at all.
    """
    organization_id = uuid.uuid4()
    app.dependency_overrides[deps.get_current_user] = lambda: SimpleNamespace(id=uuid.uuid4())
    app.dependency_overrides[deps.get_active_organization] = lambda: SimpleNamespace(
        id=organization_id
    )
    # The workspace service takes the caller's context rather than an
    # organization id: reading a container-backed workspace resolves a
    # connection and unseals its credential, and both are per-organization.
    app.dependency_overrides[deps.get_auth_context] = lambda: AuthContext(
        user_id=uuid.uuid4(), organization_id=organization_id, role=OrgRoleName.MEMBER
    )
    app.dependency_overrides[deps.get_conversation_service] = lambda: conversation
    app.dependency_overrides[deps.get_sandbox_workspace_service] = lambda: workspaces


class TestListing:
    async def test_the_files_and_whose_they_are(self, client: AsyncClient):
        """The label is the part that stops `agent` scope reading as a leak."""
        conversation = MagicMock(get_conversation=AsyncMock())
        workspaces = MagicMock(
            listing=AsyncMock(
                return_value=(
                    _row(scope="agent"),
                    WorkspaceContents(
                        entries=[{"path": "/uploads/report.csv", "size": 128, "is_dir": False}]
                    ),
                )
            )
        )
        _override(conversation=conversation, workspaces=workspaces)

        response = await client.get(f"/api/v1/conversations/{CONVERSATION_ID}/workspace")

        assert response.status_code == 200
        body = response.json()
        assert body["items"][0]["path"] == "/uploads/report.csv"
        assert body["owner_label"] == "Shared by everyone who uses this agent"
        assert body["total"] == 1
        # The caller's context, positionally, because reading a container-backed
        # workspace resolves a connection and unseals its credential. A stub
        # accepts any keyword, so asserting the *shape* of the call is what keeps
        # a signature change from passing here and 500ing in production - which
        # is exactly what happened once.
        assert workspaces.listing.await_args.args[0].organization_id is not None
        assert set(workspaces.listing.await_args.kwargs) == {"conversation_id"}

    async def test_a_conversation_with_no_workspace_is_empty_rather_than_an_error(
        self, client: AsyncClient
    ):
        """An agent without one is the default; a 404 would read as a fault."""
        _override(
            conversation=MagicMock(get_conversation=AsyncMock()),
            workspaces=MagicMock(listing=AsyncMock(return_value=None)),
        )

        response = await client.get(f"/api/v1/conversations/{CONVERSATION_ID}/workspace")

        assert response.status_code == 200
        assert response.json()["items"] == []
        assert response.json()["owner_label"] == "No files"

    async def test_a_conversation_that_is_not_the_callers_lists_nothing(self, client: AsyncClient):
        """And the workspace is never asked, so no token is used on the way to
        finding out."""
        conversation = MagicMock(
            get_conversation=AsyncMock(side_effect=NotFoundError(message="Conversation not found"))
        )
        workspaces = MagicMock(listing=AsyncMock())
        _override(conversation=conversation, workspaces=workspaces)

        response = await client.get(f"/api/v1/conversations/{CONVERSATION_ID}/workspace")

        assert response.status_code == 404
        workspaces.listing.assert_not_called()


class TestAHostThatCannotBeRead:
    """The panel used to show "an unexpected error occurred" beside "nothing yet".

    Two wrong answers at once, and the commonest cause was not a fault: a service
    started with no `workspace_root` keeps nothing on disk, so its files exist only
    while a sandbox runs.
    """

    async def test_the_reason_travels_with_an_empty_listing(self, client: AsyncClient):
        _override(
            conversation=MagicMock(get_conversation=AsyncMock()),
            workspaces=MagicMock(
                listing=AsyncMock(
                    return_value=(
                        _row(backend="service"),
                        WorkspaceContents(
                            entries=[],
                            unreadable_reason="This host's files could not be read. No workspace root.",
                        ),
                    )
                )
            ),
        )

        response = await client.get(f"/api/v1/conversations/{CONVERSATION_ID}/workspace")

        assert response.status_code == 200
        assert "No workspace root" in response.json()["unreadable_reason"]

    async def test_a_readable_workspace_carries_no_reason(self, client: AsyncClient):
        _override(
            conversation=MagicMock(get_conversation=AsyncMock()),
            workspaces=MagicMock(
                listing=AsyncMock(return_value=(_row(), WorkspaceContents(entries=[])))
            ),
        )

        response = await client.get(f"/api/v1/conversations/{CONVERSATION_ID}/workspace")

        assert response.json()["unreadable_reason"] is None


class TestReadingOneFile:
    async def test_the_text_comes_back(self, client: AsyncClient):
        _override(
            conversation=MagicMock(get_conversation=AsyncMock()),
            workspaces=MagicMock(read_text=AsyncMock(return_value="month,total")),
        )

        response = await client.get(
            f"/api/v1/conversations/{CONVERSATION_ID}/workspace/file",
            params={"path": "/uploads/report.csv"},
        )

        assert response.status_code == 200
        assert response.json()["content"] == "month,total"

    async def test_a_path_that_is_not_there_is_a_404(self, client: AsyncClient):
        _override(
            conversation=MagicMock(get_conversation=AsyncMock()),
            workspaces=MagicMock(read_text=AsyncMock(return_value=None)),
        )

        response = await client.get(
            f"/api/v1/conversations/{CONVERSATION_ID}/workspace/file",
            params={"path": "/nope.txt"},
        )

        assert response.status_code == 404

    async def test_a_conversation_that_is_not_the_callers_reads_nothing(self, client: AsyncClient):
        workspaces = MagicMock(read_text=AsyncMock())
        _override(
            conversation=MagicMock(
                get_conversation=AsyncMock(
                    side_effect=NotFoundError(message="Conversation not found")
                )
            ),
            workspaces=workspaces,
        )

        response = await client.get(
            f"/api/v1/conversations/{CONVERSATION_ID}/workspace/file",
            params={"path": "/uploads/report.csv"},
        )

        assert response.status_code == 404
        workspaces.read_text.assert_not_called()


class TestReadingOneFileAsBytes:
    """The route the panel's viewer uses for anything that is not a string.

    It exists beside `/sandbox-workspaces/{id}/raw` rather than instead of it, and
    the reason is authorisation: this one authorises by fetching the conversation, so
    somebody a chat was *shared with* reaches these files. The id-addressed route
    matches conversations a caller owns, and pointing the panel at it showed a share
    recipient files it then refused to open.
    """

    async def test_a_pdf_is_served_for_display(self, client: AsyncClient):
        _override(
            conversation=MagicMock(get_conversation=AsyncMock()),
            workspaces=MagicMock(read_bytes=AsyncMock(return_value=b"%PDF-1.7")),
        )

        response = await client.get(
            f"/api/v1/conversations/{CONVERSATION_ID}/workspace/raw",
            params={"path": "/report.pdf"},
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert response.headers["content-disposition"].startswith("inline")
        assert response.content == b"%PDF-1.7"

    async def test_the_same_disposition_rule_applies_here(self, client: AsyncClient):
        """Decided in one module for both routes. The second copy is where `.svg`
        would have stayed displayable."""
        _override(
            conversation=MagicMock(get_conversation=AsyncMock()),
            workspaces=MagicMock(read_bytes=AsyncMock(return_value=b"<svg onload=alert(1)>")),
        )

        response = await client.get(
            f"/api/v1/conversations/{CONVERSATION_ID}/workspace/raw",
            params={"path": "/x.svg"},
        )

        assert response.headers["content-type"] == "application/octet-stream"
        assert response.headers["content-disposition"].startswith("attachment")
        assert response.headers["x-content-type-options"] == "nosniff"

    async def test_a_download_is_forced_when_asked_even_for_a_pdf(self, client: AsyncClient):
        _override(
            conversation=MagicMock(get_conversation=AsyncMock()),
            workspaces=MagicMock(read_bytes=AsyncMock(return_value=b"%PDF-1.7")),
        )

        response = await client.get(
            f"/api/v1/conversations/{CONVERSATION_ID}/workspace/raw",
            params={"path": "/report.pdf", "download": "true"},
        )

        assert response.headers["content-disposition"].startswith("attachment")

    async def test_a_conversation_that_is_not_the_callers_reads_no_bytes(self, client: AsyncClient):
        """And the workspace is never asked, so its token is not used on the way to
        finding out."""
        workspaces = MagicMock(read_bytes=AsyncMock())
        _override(
            conversation=MagicMock(
                get_conversation=AsyncMock(
                    side_effect=NotFoundError(message="Conversation not found")
                )
            ),
            workspaces=workspaces,
        )

        response = await client.get(
            f"/api/v1/conversations/{CONVERSATION_ID}/workspace/raw",
            params={"path": "/report.pdf"},
        )

        assert response.status_code == 404
        workspaces.read_bytes.assert_not_called()

    async def test_asking_for_bytes_without_naming_a_file_is_refused(self, client: AsyncClient):
        workspaces = MagicMock(read_bytes=AsyncMock())
        _override(conversation=MagicMock(get_conversation=AsyncMock()), workspaces=workspaces)

        response = await client.get(f"/api/v1/conversations/{CONVERSATION_ID}/workspace/raw")

        assert response.status_code == 422
        workspaces.read_bytes.assert_not_called()


class TestDeletingTheConversation:
    async def test_the_workspace_is_purged_with_it(self, client: AsyncClient):
        """The row cascades; a container on the host does not."""
        workspaces = MagicMock(purge_for_conversation=AsyncMock(return_value=1))
        _override(conversation=MagicMock(delete_conversation=AsyncMock()), workspaces=workspaces)

        response = await client.delete(f"/api/v1/conversations/{CONVERSATION_ID}")

        assert response.status_code == 204
        workspaces.purge_for_conversation.assert_awaited_once()
