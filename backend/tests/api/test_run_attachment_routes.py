"""What `GET /runs/{run_id}/files/{file_id}` puts on the wire.

The authorization *logic* is proven against the service in
`tests/test_run_transcript.py`: the run is resolved against the caller's
organization first, then `runs:view`, then the file has to hang on a turn of the
run's own conversation. What belongs here is the wiring, and the half that is only
decided at the HTTP layer - the disposition, the framing headers a preview needs,
and the 404 for a row whose bytes the storage no longer has.

Both routes that serve a chat attachment share `_chat_file_bytes.py` for exactly
that reason: what a browser may *display* must not depend on which route
authorized the read.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app

pytestmark = pytest.mark.anyio


@asynccontextmanager
async def _client(service: MagicMock, uploads: MagicMock) -> AsyncIterator[AsyncClient]:
    context = AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OPERATOR.value)
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_agent_runner_service] = lambda: service
    app.dependency_overrides[deps.get_file_upload_service] = lambda: uploads
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def _attachment(filename: str = "scan.pdf") -> MagicMock:
    return MagicMock(
        id=uuid4(), filename=filename, mime_type="application/pdf", storage_path="stored/scan.pdf"
    )


async def test_a_reviewer_reads_the_bytes_inline(tmp_path: Path) -> None:
    """`inline`, because the run timeline embeds this URL: a preview that always
    downloads is a preview nobody looks at."""
    stored = tmp_path / "scan.pdf"
    stored.write_bytes(b"%PDF-1.7 not really")
    service = MagicMock(get_run_attachment=AsyncMock(return_value=_attachment()))
    uploads = MagicMock(get_file_path=MagicMock(return_value=str(stored)))

    async with _client(service, uploads) as client:
        response = await client.get(f"/api/v1/runs/{uuid4()}/files/{uuid4()}")

    assert response.status_code == 200
    assert response.content == b"%PDF-1.7 not really"
    assert response.headers["content-disposition"] == 'inline; filename="scan.pdf"'
    assert response.headers["content-type"] == "application/pdf"
    # What lets the preview render in an iframe at all, and no wider than the
    # origin the app's own pages run on.
    assert response.headers["x-frame-options"] == "SAMEORIGIN"
    assert response.headers["content-security-policy"] == "frame-ancestors 'self'"


async def test_the_download_button_forces_the_browsers_dialog(tmp_path: Path) -> None:
    stored = tmp_path / "scan.pdf"
    stored.write_bytes(b"bytes")
    service = MagicMock(get_run_attachment=AsyncMock(return_value=_attachment()))
    uploads = MagicMock(get_file_path=MagicMock(return_value=str(stored)))

    async with _client(service, uploads) as client:
        response = await client.get(
            f"/api/v1/runs/{uuid4()}/files/{uuid4()}", params={"disposition": "attachment"}
        )

    assert response.headers["content-disposition"] == 'attachment; filename="scan.pdf"'


async def test_a_quote_in_the_filename_cannot_break_out_of_the_header(tmp_path: Path) -> None:
    stored = tmp_path / "odd"
    stored.write_bytes(b"bytes")
    service = MagicMock(
        get_run_attachment=AsyncMock(return_value=_attachment('a"; filename="other.pdf'))
    )
    uploads = MagicMock(get_file_path=MagicMock(return_value=str(stored)))

    async with _client(service, uploads) as client:
        response = await client.get(f"/api/v1/runs/{uuid4()}/files/{uuid4()}")

    assert response.headers["content-disposition"] == 'inline; filename="a; filename=other.pdf"'


async def test_a_row_whose_bytes_are_gone_is_a_404_rather_than_an_empty_document() -> None:
    """A row and its file can part company - a restored database, a cleaned
    volume - and zero bytes reads as an empty document rather than a missing one."""
    service = MagicMock(get_run_attachment=AsyncMock(return_value=_attachment()))
    uploads = MagicMock(get_file_path=MagicMock(return_value=None))

    async with _client(service, uploads) as client:
        response = await client.get(f"/api/v1/runs/{uuid4()}/files/{uuid4()}")

    assert response.status_code == 404


async def test_a_run_in_another_tenant_reads_as_absent() -> None:
    service = MagicMock(
        get_run_attachment=AsyncMock(side_effect=NotFoundError(message="Run not found"))
    )

    async with _client(service, MagicMock()) as client:
        response = await client.get(f"/api/v1/runs/{uuid4()}/files/{uuid4()}")

    assert response.status_code == 404


async def test_a_caller_without_runs_view_is_refused() -> None:
    service = MagicMock(
        get_run_attachment=AsyncMock(side_effect=AuthorizationError(message="Insufficient"))
    )

    async with _client(service, MagicMock()) as client:
        response = await client.get(f"/api/v1/runs/{uuid4()}/files/{uuid4()}")

    assert response.status_code == 403
