"""A real ZIP round trip proves queue admission, storage and atomic destination writes."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec
from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.repositories import background_job as jobs
from app.repositories import portability_operation as operations
from app.schemas.portability_operation import (
    BundleApplyCreate,
    BundleExportStart,
    BundleUploadStart,
)
from app.schemas.resource_bundle import BundleImportChoice
from app.services.agent_registry import AgentRegistryService
from app.services.context import ContextService
from app.services.file_storage import LocalFileStorage
from app.services.portability import PortableTransferService
from app.worker.jobs import PortableTransferPayload
from tests.integration.test_authoring import _owner

pytestmark = pytest.mark.anyio


async def _run(db: AsyncSession, service: PortableTransferService, identity: UUID) -> None:
    operation = await operations.get_for_worker(db, identity)
    assert operation is not None and operation.job_id is not None
    job = await jobs.get(db, operation.job_id)
    assert job is not None
    job.status, job.attempts = "running", 1
    job.lease_until = datetime.now(UTC) + timedelta(minutes=5)
    await db.flush()
    payload = PortableTransferPayload.model_validate(job.payload)
    assert await service.claim(payload, attempt=1)
    assert not await service.claim(payload, attempt=1)
    await service.run(payload, attempt=1)


async def _chunks(data: bytes) -> AsyncIterator[bytes]:
    for start in range(0, len(data), 65_536):
        yield data[start : start + 65_536]


async def test_zip_export_import_and_replay_preserve_large_context_without_publishing(
    db: AsyncSession, tmp_path: Path
) -> None:
    source, target = await _owner(db), await _owner(db)
    content = "  Exact context αβ\n" * 250_000
    context = await ContextService(db).create(
        source, name="Policy", description=None, content=content
    )
    agent = await AgentRegistryService(db).create(
        source, AgentSpec(name="Researcher", context_ids=[context.id]), choose_model=False
    )
    service = PortableTransferService(db, storage=LocalFileStorage(tmp_path))
    preview = await service.portability.export_agent(source, agent.id, metadata_only=True)
    request = BundleExportStart(
        request_id=uuid4(),
        root_kind="agent",
        root_id=agent.id,
        resources={option.key: option.layers for option in preview.options},
    )
    started = await service.start_export(source, request)
    assert (await service.start_export(source, request)).id == started.id
    await _run(db, service, started.id)
    ready = await service.get(source, started.id)
    assert ready.status == "ready" and ready.can_download
    archive = b"".join([chunk async for chunk in await service.download(source, started.id)])
    uploaded = await service.start_upload(
        target,
        BundleUploadStart(request_id=uuid4(), filename="researcher.zip", size_bytes=len(archive)),
    )
    await service.upload(target, uploaded.id, _chunks(archive))
    await _run(db, service, uploaded.id)
    reviewed = await service.get(target, uploaded.id)
    assert reviewed.status == "review" and reviewed.preview is not None
    assert reviewed.preview.bundle.assets
    request = BundleApplyCreate(
        expected_revision=reviewed.revision,
        choices={
            resource.key: BundleImportChoice(action="create")
            for resource in reviewed.preview.bundle.resources
        },
    )
    applied = await service.apply(target, uploaded.id, request)
    assert applied.status == "queued" and applied.phase == "apply"
    await _run(db, service, uploaded.id)
    complete = await service.get(target, uploaded.id)
    assert complete.status == "ready" and complete.receipt is not None
    assert (await service.apply(target, uploaded.id, request)).receipt == complete.receipt
    copied = await AgentRegistryService(db).get(target, next(iter(complete.receipt.roots.values())))
    spec = AgentSpec.model_validate(copied.draft_spec)
    assert (await ContextService(db).get(target, spec.context_ids[0])).content == content
    assert copied.current_version_id is None
    with pytest.raises(NotFoundError):
        await service.get(source, uploaded.id)
    with pytest.raises(NotFoundError):
        await service.download(target, started.id)


async def test_transfer_admission_size_conflicts_and_expiry_are_explicit(
    db: AsyncSession, tmp_path: Path
) -> None:
    owner = await _owner(db)
    service = PortableTransferService(db, storage=LocalFileStorage(tmp_path))
    request = BundleUploadStart(request_id=uuid4(), filename="test.zip", size_bytes=3)
    operation = await service.start_upload(owner, request)
    with pytest.raises(ConflictError, match="different transfer"):
        await service.start_upload(owner, request.model_copy(update={"size_bytes": 4}))
    for content in (b"longer", b"no"):
        with pytest.raises(BadRequestError):
            await service.upload(owner, operation.id, _chunks(content))
    assert not list(tmp_path.rglob("source.zip"))
    with pytest.raises(ConflictError, match="not ready"):
        await service.download(owner, operation.id)
    with pytest.raises(ConflictError, match="changed"):
        await service.apply(owner, operation.id, BundleApplyCreate(expected_revision=1, choices={}))
    await service.start_upload(owner, request.model_copy(update={"request_id": uuid4()}))
    await service.start_upload(owner, request.model_copy(update={"request_id": uuid4()}))
    with pytest.raises(ConflictError, match="open transfers"):
        await service.start_upload(owner, request.model_copy(update={"request_id": uuid4()}))
    row = await operations.get_for_worker(db, operation.id)
    assert row is not None
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await operations.save(db, row)
    with pytest.raises(ConflictError, match="expired"):
        await service.get(owner, operation.id)
    await service.sweep()
    assert await operations.get_for_worker(db, operation.id) is None


async def test_zip_asset_budget_is_checked_before_promoting_an_export(
    db: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.schemas.resource_bundle import BundleDownloadCreate
    from app.services.portability import facade

    ctx = await _owner(db)
    context = await ContextService(db).create(ctx, name="Policy", description=None, content="body")
    agent = await AgentRegistryService(db).create(
        ctx, AgentSpec(name="Agent", context_ids=[context.id]), choose_model=False
    )
    service = PortableTransferService(db, storage=LocalFileStorage(tmp_path))
    preview = await service.portability.export_agent(ctx, agent.id, metadata_only=True)
    monkeypatch.setattr(facade, "MAX_EXPORT_ASSET_BYTES", 1)
    with pytest.raises(BadRequestError, match="expanded bundle"):
        await service.portability.selected_agent(
            ctx,
            agent.id,
            BundleDownloadCreate(
                file_format="json",
                resources={option.key: option.layers for option in preview.options},
            ),
            asset_directory=tmp_path,
        )


async def test_unselected_reference_has_no_export_download_read(
    db: AsyncSession, tmp_path: Path
) -> None:
    ctx = await _owner(db)
    context = await ContextService(db).create(ctx, name="Policy", description=None, content="body")
    agent = await AgentRegistryService(db).create(
        ctx, AgentSpec(name="Agent", context_ids=[context.id]), choose_model=False
    )
    service = PortableTransferService(db, storage=LocalFileStorage(tmp_path))
    root = f"agent/{agent.id}"
    started = await service.start_export(
        ctx,
        BundleExportStart(
            request_id=uuid4(),
            root_kind="agent",
            root_id=agent.id,
            resources={root: frozenset({"definition"})},
        ),
    )
    await _run(db, service, started.id)
    assert b"".join([chunk async for chunk in await service.download(ctx, started.id)])
