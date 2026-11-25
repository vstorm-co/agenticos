"""The transfer API streams bytes and shares the service's reviewed state contract."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.permissions import AuthContext
from app.main import app
from app.schemas.portability_operation import PortabilityOperationRead
from app.services.portability import PortableTransferService

pytestmark = pytest.mark.anyio


async def _bytes() -> AsyncIterator[bytes]:
    yield b"bundle"


async def test_transfer_routes_preserve_tickets_streams_and_review_revisions() -> None:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    identity, request_id = uuid4(), uuid4()
    row = PortabilityOperationRead(
        id=identity,
        request_id=request_id,
        direction="import",
        phase="prepare",
        status="awaiting_upload",
        revision=1,
        completed_bytes=0,
        total_bytes=0,
        expires_at=datetime.now(UTC) + timedelta(hours=24),
    )
    service = MagicMock(spec=PortableTransferService)
    for name in ("start_export", "start_upload", "upload", "get", "apply"):
        setattr(service, name, AsyncMock(return_value=row))
    service.download = AsyncMock(return_value=_bytes())
    app.dependency_overrides[deps.get_portable_transfer_service] = lambda: service
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            export = await client.post(
                "/api/v1/portability/exports",
                json={
                    "request_id": str(request_id),
                    "root_kind": "agent",
                    "root_id": str(uuid4()),
                    "resources": {},
                },
            )
            assert export.status_code == 202
            upload = await client.post(
                "/api/v1/portability/uploads",
                json={"request_id": str(request_id), "filename": "agent.zip", "size_bytes": 6},
            )
            assert upload.status_code == 201 and upload.json()["id"] == str(identity)
            sent = await client.put(f"/api/v1/portability/{identity}/upload", content=b"bundle")
            assert sent.status_code == 200
            assert service.upload.await_args.args[:2] == (ctx, identity)
            assert (await client.get(f"/api/v1/portability/{identity}")).status_code == 200
            applied = await client.post(
                f"/api/v1/portability/{identity}/apply",
                json={"expected_revision": 1, "choices": {}},
            )
            assert applied.status_code == 202
            assert service.apply.await_args.args[2].expected_revision == 1
            downloaded = await client.get(f"/api/v1/portability/{identity}/download")
            assert downloaded.content == b"bundle"
            assert downloaded.headers["content-type"] == "application/zip"
            assert downloaded.headers["cache-control"] == "no-store"
            invalid = await client.post(
                "/api/v1/portability/uploads",
                json={
                    "request_id": str(uuid4()),
                    "filename": "x.zip",
                    "size_bytes": 512 * 1024 * 1024 + 1,
                },
            )
            assert invalid.status_code == 422
            viewer = AuthContext(
                user_id=ctx.user_id, organization_id=ctx.organization_id, role="viewer"
            )
            app.dependency_overrides[deps.get_auth_context] = lambda: viewer
            assert (
                await client.post(
                    "/api/v1/portability/uploads",
                    json={"request_id": str(uuid4()), "filename": "x.zip", "size_bytes": 1},
                )
            ).status_code == 403
    finally:
        app.dependency_overrides.clear()
