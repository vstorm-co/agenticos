"""Transfer authority, stale-worker refusal and storage integrity failure paths."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.exceptions import (
    AuthenticationError,
    AuthorizationError,
    BadRequestError,
    ConflictError,
    NotFoundError,
)
from app.core.permissions import AuthContext
from app.db.models.portability_operation import PortabilityOperation
from app.schemas.portability_operation import BundleExportStart
from app.services.file_storage import LocalFileStorage
from app.services.portability import transfers
from app.worker.jobs import PortableTransferPayload

pytestmark = pytest.mark.anyio


def _actor() -> AuthContext:
    return AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")


def _row(ctx: AuthContext) -> PortabilityOperation:
    return PortabilityOperation(
        id=uuid4(),
        organization_id=ctx.organization_id,
        user_id=ctx.subject_id,
        api_key_id=None,
        request_id=uuid4(),
        request_hash="a" * 64,
        direction="import",
        phase="prepare",
        status="queued",
        revision=1,
        worker_attempt=0,
        job_id=uuid4(),
        request={},
        source_bytes=0,
        completed_bytes=0,
        total_bytes=0,
        expires_at=datetime.now(UTC) + timedelta(hours=24),
    )


async def test_ticket_access_is_owner_scoped_unexpired_and_auth_method_bound(
    mock_db_session: AsyncMock, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ctx = _actor()
    row = _row(ctx)
    service = transfers.PortableTransferService(mock_db_session, storage=LocalFileStorage(tmp_path))
    lookup = AsyncMock(return_value=None)
    monkeypatch.setattr(transfers.operations, "get", lookup)
    with pytest.raises(NotFoundError):
        await service.get(ctx, row.id)
    lookup.return_value = row
    row.expires_at = datetime.now(UTC)
    with pytest.raises(ConflictError, match="expired"):
        await service.get(ctx, row.id)
    row.expires_at += timedelta(hours=1)
    row.api_key_id = uuid4()
    with pytest.raises(AuthorizationError, match="sign-in method"):
        await service.get(ctx, row.id)
    with pytest.raises(AuthorizationError):
        await service.get(
            AuthContext(user_id=None, organization_id=ctx.organization_id, role="owner"), row.id
        )
    with pytest.raises(AuthorizationError):
        await service.get(
            AuthContext(user_id=ctx.user_id, organization_id=ctx.organization_id, role="viewer"),
            row.id,
        )
    assert "PortabilityOperation" in repr(row)


@pytest.mark.parametrize("missing", ["organization_id", "user_id", "membership", "user", "active"])
async def test_worker_rebuilds_live_membership_and_user_authority(
    mock_db_session: AsyncMock, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, missing: str
) -> None:
    ctx = _actor()
    row = _row(ctx)
    if missing in ("organization_id", "user_id"):
        setattr(row, missing, None)
    monkeypatch.setattr(
        transfers.member_repo,
        "get_active",
        AsyncMock(return_value=None if missing == "membership" else SimpleNamespace(role="owner")),
    )
    monkeypatch.setattr(
        transfers.user_repo,
        "get_by_id",
        AsyncMock(
            return_value=None
            if missing == "user"
            else SimpleNamespace(is_active=missing != "active", is_app_admin=False)
        ),
    )
    with pytest.raises(AuthenticationError):
        await transfers.PortableTransferService(
            mock_db_session, storage=LocalFileStorage(tmp_path)
        ).context(row)


async def test_deleted_api_key_never_falls_back_to_session_authority(
    mock_db_session: AsyncMock, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ctx = _actor()
    row = _row(ctx)
    row.api_key_id = uuid4()
    key = AsyncMock(side_effect=AuthenticationError(message="Revoked"))
    member = AsyncMock()
    monkeypatch.setattr(transfers.ApiKeyService, "context_for_key", key)
    monkeypatch.setattr(transfers.member_repo, "get_active", member)
    service = transfers.PortableTransferService(mock_db_session, storage=LocalFileStorage(tmp_path))
    with pytest.raises(AuthenticationError, match="Revoked"):
        await service.context(row)
    member.assert_not_awaited()
    key.side_effect = None
    key.return_value = _actor()
    with pytest.raises(AuthenticationError, match="owner"):
        await service.context(row)
    key.return_value = ctx
    assert await service.context(row) == ctx


@pytest.mark.parametrize("state", ["missing", "wrong_org", "wrong_revision", "finished"])
async def test_stale_payload_cannot_claim_or_execute_an_operation(
    mock_db_session: AsyncMock, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, state: str
) -> None:
    ctx = _actor()
    row = _row(ctx)
    payload = PortableTransferPayload(
        operation_id=row.id, organization_id=ctx.organization_id, revision=1
    )
    if state == "wrong_org":
        row.organization_id = uuid4()
    if state == "wrong_revision":
        row.revision = 2
    if state == "finished":
        row.status = "ready"
    monkeypatch.setattr(
        transfers.operations,
        "get_for_worker",
        AsyncMock(return_value=None if state == "missing" else row),
    )
    service = transfers.PortableTransferService(mock_db_session, storage=LocalFileStorage(tmp_path))
    assert not await service.claim(payload, attempt=1)
    assert await service.run(payload, attempt=1) is None
    await service.settle(payload)
    assert row.status != "failed"


async def test_queue_fence_refuses_a_lost_lease_or_changed_review(
    mock_db_session: AsyncMock, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ctx = _actor()
    row = _row(ctx)
    payload = PortableTransferPayload(
        operation_id=row.id, organization_id=ctx.organization_id, revision=1
    )
    service = transfers.PortableTransferService(mock_db_session, storage=LocalFileStorage(tmp_path))
    fence = AsyncMock(return_value=None)
    monkeypatch.setattr(transfers.jobs, "lock_attempt", fence)
    with pytest.raises(ConflictError, match="lease"):
        await service._fence(row, payload, 1)
    row.job_id = None
    with pytest.raises(ConflictError, match="lease"):
        await service._fence(row, payload, 1)
    row.job_id = uuid4()
    fence.return_value = SimpleNamespace()
    monkeypatch.setattr(transfers.operations, "get_for_worker", AsyncMock(return_value=None))
    with pytest.raises(ConflictError, match="changed"):
        await service._fence(row, payload, 1)


@pytest.mark.parametrize("method", ["claim", "run"])
async def test_an_expiring_transfer_cannot_start_more_io(
    mock_db_session: AsyncMock, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, method: str
) -> None:
    ctx = _actor()
    row = _row(ctx)
    row.expires_at = datetime.now(UTC) + timedelta(minutes=2)
    monkeypatch.setattr(transfers.operations, "get_for_worker", AsyncMock(return_value=row))
    service = transfers.PortableTransferService(mock_db_session, storage=LocalFileStorage(tmp_path))
    monkeypatch.setattr(service, "context", AsyncMock(return_value=ctx))
    with pytest.raises(ConflictError, match="expiry"):
        await getattr(service, method)(
            PortableTransferPayload(
                operation_id=row.id, organization_id=ctx.organization_id, revision=1
            ),
            attempt=1,
        )


async def test_failed_uploads_and_unfinished_exports_do_not_look_successful(
    mock_db_session: AsyncMock, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ctx = _actor()
    row = _row(ctx)
    service = transfers.PortableTransferService(mock_db_session, storage=LocalFileStorage(tmp_path))
    monkeypatch.setattr(service, "_owned", AsyncMock(return_value=row))
    with pytest.raises(ConflictError, match="received"):
        await service.upload(ctx, row.id, _chunks(b"data"))
    request = BundleExportStart(
        root_kind="workflow", root_id=uuid4(), request_id=uuid4(), resources={}
    )
    with pytest.raises(BadRequestError, match="Workflow"):
        await service.start_export(ctx, request)
    monkeypatch.setattr(transfers.operations, "get_for_worker", AsyncMock(return_value=row))
    monkeypatch.setattr(transfers.operations, "save", AsyncMock())
    await service.settle(
        PortableTransferPayload(
            operation_id=row.id, organization_id=ctx.organization_id, revision=1
        )
    )
    assert row.status == "failed" and row.error_code == "transfer_failed"
    monkeypatch.setattr(transfers.operations, "expired", AsyncMock(return_value=[row]))
    monkeypatch.setattr(transfers.operations, "get_for_worker", AsyncMock(return_value=None))
    await service.sweep()


async def _chunks(data: bytes) -> AsyncIterator[bytes]:
    yield data


@pytest.mark.parametrize("recorded_size,recorded_hash", [(1, "bad"), (4, "bad")])
async def test_stored_upload_corruption_is_refused(
    mock_db_session: AsyncMock, tmp_path: Path, recorded_size: int, recorded_hash: str
) -> None:
    storage = LocalFileStorage(tmp_path)
    row = _row(_actor())
    row.source_path = await storage.save("owner", "source.zip", b"data")
    row.source_bytes, row.source_sha256 = recorded_size, recorded_hash
    with pytest.raises(BadRequestError, match="recorded"):
        await transfers.PortableTransferService(mock_db_session, storage=storage)._stage_source(
            row, tmp_path / "staged"
        )


async def test_worker_adapters_commit_claim_before_running_and_skip_stale_work(
    mock_db_session: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    from contextlib import asynccontextmanager

    from app.worker.tasks import portability_tasks

    @asynccontextmanager
    async def session() -> AsyncIterator[AsyncMock]:
        yield mock_db_session

    service = SimpleNamespace(
        claim=AsyncMock(return_value=True), run=AsyncMock(), settle=AsyncMock(), sweep=AsyncMock()
    )
    monkeypatch.setattr(portability_tasks, "get_worker_db_context", session)
    monkeypatch.setattr(portability_tasks, "PortableTransferService", lambda db: service)
    monkeypatch.setattr(portability_tasks, "current_attempt_number", lambda: 1)
    payload = PortableTransferPayload(operation_id=uuid4(), organization_id=uuid4(), revision=1)
    await portability_tasks.portable_transfer(payload)
    service.run.assert_awaited_once_with(payload, attempt=1)
    service.claim.return_value = False
    await portability_tasks.portable_transfer(payload)
    assert service.run.await_count == 1
    await portability_tasks.settle_transfer(payload, "dead")
    service.settle.assert_awaited_once_with(payload)
    await portability_tasks.sweep_transfers()
    service.sweep.assert_awaited_once()
